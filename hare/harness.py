from __future__ import annotations

import json
import os
import time
from typing import Any, AsyncGenerator

import boto3
from botocore.exceptions import ClientError

from hare.tools import TOOL_DEFINITIONS, execute_tool
from hare.tools.config import get_enabled_local_tools, get_gateway_tools
from hare.mcp_client import get_mcp_manager
from hare.persona import build_persona_prompt
from hare.tui.confirm import confirm_tool_call

# Tool confirm callback — injected by TUI layer
_tool_confirm_callback = None

def set_tool_confirm_callback(callback):
    global _tool_confirm_callback
    _tool_confirm_callback = callback


def _get_client():
    session = boto3.Session(
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
        profile_name=os.environ.get("AWS_PROFILE"),
    )
    return session.client("bedrock-agentcore")


def _build_inline_tools() -> list[dict[str, Any]]:
    enabled = set(get_enabled_local_tools())
    tools = []
    for tool_def in TOOL_DEFINITIONS:
        spec = tool_def["toolSpec"]
        if spec["name"] in enabled:
            tools.append({
                "type": "inline_function",
                "name": spec["name"],
                "config": {
                    "inlineFunction": {
                        "description": spec["description"],
                        "inputSchema": spec["inputSchema"]["json"],
                    }
                },
            })
    return tools


def _build_all_tools() -> list[dict[str, Any]]:
    """Local inline_function + remote agentcore_gateway + MCP tools."""
    tools = _build_inline_tools()
    for gw in get_gateway_tools():
        auth = gw.get("auth", "awsIam")
        auth_config = {"none": {}} if auth == "none" else {"awsIam": {}}
        tools.append({
            "type": "agentcore_gateway",
            "name": gw["name"],
            "config": {
                "agentCoreGateway": {
                    "gatewayArn": gw["gateway_arn"],
                    "outboundAuth": auth_config,
                }
            }
        })
    # MCP tools
    tools.extend(get_mcp_manager().get_tools())

    # AgentCore built-in tools (no resource creation needed, just declare)
    tools.append({"type": "agentcore_browser", "name": "browser"})
    tools.append({"type": "agentcore_code_interpreter", "name": "code_interpreter"})

    return tools


_TOOLS_PROMPT = """
You have two categories of tools — use them strictly by purpose:

**1. User's local tools** (only for accessing the user's local machine):
- local_shell: Execute commands on the user's local macOS/Linux desktop. Only for local file lookup, local processes, local directory operations, etc.
- local_read_file: Read files from the user's local machine.
- local_write_file: Write files to the user's local machine.

**2. Harness built-in capabilities** (no need to call local tools):
- You run inside an AgentCore Harness microVM with your own shell and filesystem.
- For queries about "your own runtime environment", "Harness host info", "server-side config", etc. → use the Harness built-in shell directly, do NOT call local_shell.
- Only call local_shell when the user explicitly says "on my machine..." or needs to access user-local paths.

**Important**: You have cross-session long-term memory (provided by AgentCore Memory). You can remember things the user previously told you — work habits, project context, etc. If the system has injected relevant memories into your context, use them naturally. Do not say "I don't have memory capabilities."

Key principles:
1. When the user asks about local files or directory contents, use shell_run or read_file tools directly — don't ask the user to run commands themselves
2. When the user needs system operations, execute them with shell_run and return results
3. You run on the user's local machine and have access to their filesystem
4. You have the persona_manage tool to self-manage your persona/roles. When the user asks you to change identity, create a new role, or you feel the need to evolve, use it directly
5. You have the coding_agent tool to delegate coding tasks to a local coding agent (e.g. Claude Code, Kiro). When the user needs code written, bugs fixed, or projects refactored, use coding_agent to hand off to the professional coding tool
6. You have the sub_task tool to spawn independent sub-tasks (e.g. research, calculations, translations). Sub-tasks run in isolated sessions with no access to the current conversation, so instructions must be self-contained
7. You currently **do not support image input**. If the user sends an image path or asks you to "look at an image", inform them that direct image viewing is not yet supported and suggest they describe the image content or wait for a future version
"""


def _build_system_prompt() -> list[dict[str, str]]:
    persona_text = build_persona_prompt()
    return [{"text": f"{persona_text}\n\n{_TOOLS_PROMPT}"}]


async def invoke_with_tool_loop(
    session_id: str,
    message: str,
    actor_id: str | None = None,
    stop_event=None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Invoke Harness with tool_use loop, yielding streaming events.

    Memory mode (requires bound AgentCore Memory):
    - Only sends the current message; Harness auto-loads history context from Memory
    - Calls with the same session_id auto-continue context server-side, no client-side history needed
    - actor_id is for multi-user scenarios; Memory isolates per actorId

    Harness streaming behavior:
    - Server-side tool calls and results are returned within the same streaming response
    - A single stream may contain multiple message segments: assistant(tool_use) → user(tool_result) → assistant(end_turn)
    - The third segment (final answer) may lack contentBlockStart, starting directly with contentBlockDelta

    Yields:
      {"type": "text",        "content": str}
      {"type": "tool_call",   "name": str}
      {"type": "tool_result", "name": str, "result": dict}
      {"type": "session_reset", "new_session_id": str}
      {"type": "done",        "full_text": str, "stats": dict}
    """
    client = _get_client()
    harness_arn = os.environ["HARNESS_ARN"]
    all_tools = _build_all_tools()
    system_prompt = _build_system_prompt()

    # Local messages for tool_use continuation (only for local tools that need re-invoke)
    current_content: list[dict[str, Any]] = [{"text": message}]
    current_role = "user"
    local_messages: list[dict[str, Any]] = []

    # Stats
    turn_start = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    invoke_count = 0
    tools_called: list[dict[str, Any]] = []
    orphan_repair_attempted = False

    while True:
        invoke_count += 1
        invoke_kwargs: dict[str, Any] = dict(
            harnessArn=harness_arn,
            runtimeSessionId=session_id,
            messages=local_messages + [{"role": current_role, "content": current_content}],
            systemPrompt=system_prompt,
            tools=all_tools,
        )
        if actor_id:
            invoke_kwargs["actorId"] = actor_id

        try:
            response = client.invoke_harness(**invoke_kwargs)
        except Exception as e:
            error_str = str(e)
            # 413 / PayloadTooLarge
            if "413" in error_str or "PayloadTooLarge" in error_str:
                yield {"type": "error", "message": "Previous turn content too large (e.g. image base64), Memory write failed. Skipped that turn, please continue."}
                local_messages = []
                current_content = [{"text": "(previous turn skipped due to size) " + message if invoke_count == 1 else "(continue)"}]
                current_role = "user"
                continue
            # tool_use/tool_result mismatch (corrupted Memory)
            if ("tool_result" in error_str and "tool_use" in error_str) or "toolResult" in error_str:
                if orphan_repair_attempted:
                    yield {"type": "error", "message": "Session memory repair failed, skipping this turn."}
                    yield {"type": "done", "full_text": "", "stats": {"elapsed": time.time() - turn_start, "input_tokens": 0, "output_tokens": 0, "invoke_count": invoke_count, "tools": []}}
                    return
                orphan_repair_attempted = True
                yield {"type": "error", "message": "Session memory corrupted, attempting recovery..."}
                session_id = session_id + "_r"
                yield {"type": "session_reset", "new_session_id": session_id}
                local_messages = []
                current_content = [{"text": message}]
                current_role = "user"
                continue
            raise

        full_text = ""
        tool_uses: list[dict[str, Any]] = []
        current_tool: dict[str, Any] | None = None
        assistant_content: list[dict[str, Any]] = []
        # Track current message segment role — only assistant segment text is output to user
        msg_role: str | None = None
        final_stop_reason = "end_turn"
        stream_error = None

        try:
          stream = response["stream"]
          for event in stream:
            if stop_event is not None and stop_event.is_set():
                stream.close()
                return
            if "messageStart" in event:
                msg_role = event["messageStart"].get("role")

            elif "contentBlockStart" in event:
                start = event["contentBlockStart"].get("start", {})
                if "toolUse" in start:
                    tool_type = start["toolUse"].get("type", "tool_use")
                    tool_name = start["toolUse"]["name"]
                    if tool_type == "tool_use":
                        from hare.tools import TOOL_REGISTRY
                        is_local = tool_name in TOOL_REGISTRY
                        is_mcp = tool_name.startswith("mcp__")
                        if is_local or is_mcp:
                            current_tool = {
                                "toolUseId": start["toolUse"]["toolUseId"],
                                "name": tool_name,
                                "input_json": "",
                            }
                            # input not fully assembled yet, wait for contentBlockStop to yield
                        else:
                            tools_called.append({"name": tool_name, "elapsed": 0, "ok": True, "server": True})
                            yield {"type": "server_tool_call", "name": tool_name, "tool_type": "server_tool_use"}
                    else:
                        # server_tool_use / mcp_tool_use: server-side execution, show status only
                        tools_called.append({"name": tool_name, "elapsed": 0, "ok": True, "server": True})
                        yield {"type": "server_tool_call", "name": tool_name, "tool_type": tool_type}

            elif "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    # Only collect assistant segment text (skip user/tool_result segment content)
                    if msg_role == "assistant":
                        text = delta["text"]
                        full_text += text
                        yield {"type": "text", "content": text}
                elif "toolUse" in delta and current_tool:
                    current_tool["input_json"] += delta["toolUse"].get("input", "")

            elif "contentBlockStop" in event:
                if current_tool:
                    try:
                        input_data = json.loads(current_tool["input_json"]) if current_tool["input_json"] else {}
                    except json.JSONDecodeError:
                        input_data = {}
                    current_tool["input"] = input_data
                    tool_uses.append(current_tool)
                    assistant_content.append({
                        "toolUse": {
                            "toolUseId": current_tool["toolUseId"],
                            "name": current_tool["name"],
                            "input": input_data,
                        }
                    })
                    yield {"type": "tool_call", "name": current_tool["name"], "input": input_data}
                    current_tool = None

            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                in_tok = usage.get("inputTokens", 0)
                out_tok = usage.get("outputTokens", 0)
                total_input_tokens += in_tok
                total_output_tokens += out_tok

            elif "messageStop" in event:
                final_stop_reason = event["messageStop"].get("stopReason", "end_turn")
        except Exception as e:
            stream_error = str(e)

        # If stream errored (e.g. Memory recalled corrupted history)
        if stream_error and (("tool_result" in stream_error and "tool_use" in stream_error) or "toolResult" in stream_error):
            if orphan_repair_attempted:
                yield {"type": "error", "message": "Session memory repair failed, skipping this turn."}
                yield {"type": "done", "full_text": "", "stats": {"elapsed": time.time() - turn_start, "input_tokens": 0, "output_tokens": 0, "invoke_count": invoke_count, "tools": []}}
                return
            orphan_repair_attempted = True
            yield {"type": "error", "message": "Session memory corrupted, attempting recovery..."}
            session_id = session_id + "_r"
            yield {"type": "session_reset", "new_session_id": session_id}
            local_messages = []
            current_content = [{"text": message}]
            current_role = "user"
            continue
        elif stream_error:
            raise RuntimeError(stream_error)

        # Loop ended: entire streaming response consumed
        # Check if there are tools requiring local execution
        if tool_uses:
            # Local tools need execution then re-invoke
            # In Memory mode, only pass the assistant(tool_use) + user(tool_result) pair
            # Cannot accumulate local_messages since Memory auto-recalls history
            tool_result_content = []
            for tool in tool_uses:
                tool_start = time.time()
                if _tool_confirm_callback:
                    allowed = await _tool_confirm_callback(tool["name"], tool["input"])
                else:
                    allowed = await confirm_tool_call(tool["name"], tool["input"])
                if allowed:
                    if tool["name"].startswith("mcp__"):
                        result = await get_mcp_manager().call_tool_by_full_name(tool["name"], tool["input"])
                    elif tool["name"] == "sub_task":
                        result = await execute_tool(tool["name"], {**tool["input"], "parent_session_id": session_id})
                    else:
                        result = await execute_tool(tool["name"], tool["input"])
                else:
                    result = {"error": f"User denied tool execution: {tool['name']}"}
                tool_elapsed = time.time() - tool_start
                tools_called.append({"name": tool["name"], "elapsed": tool_elapsed, "ok": "error" not in result})
                yield {"type": "tool_result", "name": tool["name"], "result": result}
                tool_result_content.append({
                    "toolResult": {
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": json.dumps(result, ensure_ascii=False)}],
                        "status": "error" if "error" in result else "success",
                    }
                })
            # Build assistant(tool_use) + user(tool_result) message pair
            if full_text:
                assistant_content.insert(0, {"text": full_text})
            local_messages = [
                {"role": "assistant", "content": assistant_content},
            ]
            current_content = tool_result_content
            current_role = "user"
            tool_uses = []
            assistant_content = []
            full_text = ""
        else:
            # No local tools to execute → conversation complete (server tools handled in stream)
            stats = {
                "elapsed": time.time() - turn_start,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "invoke_count": invoke_count,
                "tools": tools_called,
            }
            yield {"type": "done", "full_text": full_text, "stats": stats}
            break
