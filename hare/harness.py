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
    """本地 inline_function + 远端 agentcore_gateway + MCP tools。"""
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

    # AgentCore 内置工具（无需创建资源，直接声明即可）
    tools.append({"type": "agentcore_browser", "name": "browser"})
    tools.append({"type": "agentcore_code_interpreter", "name": "code_interpreter"})

    return tools


_TOOLS_PROMPT = """
你有两类工具，必须根据用途严格区分：

**1. 用户本地工具**（只用于访问用户的本地机器）：
- local_shell：在用户的本地 macOS/Linux 桌面执行命令。仅用于本地文件查找、本地进程、本地目录操作等。
- local_read_file：读取用户本地文件。
- local_write_file：向用户本地写入文件。

**2. Harness 自身能力**（不需要调用本地工具）：
- 你自己运行在 AgentCore Harness 的 microVM 里，有自己的 shell 和文件系统。
- 查询"你自己的运行环境"、"Harness 宿主机信息"、"服务端配置"等 → 直接使用 Harness 内置 shell，不要调用 local_shell。
- local_shell 只在用户明确说"帮我在我的电脑上..."或需要访问用户本地路径时才调用。

**重要**：你拥有跨会话的长期记忆（由 AgentCore Memory 提供）。你能记住用户之前告诉过你的事情、工作习惯、项目背景等。如果系统已将相关记忆注入到你的上下文中，请自然地利用这些信息回答用户，不要说"我没有记忆功能"。

重要原则：
1. 当用户询问本地文件、目录内容时，优先使用 shell_run 或 read_file 工具直接查找，不要让用户自己去跑命令
2. 当用户需要执行系统操作时，直接用 shell_run 执行，返回结果
3. 你运行在用户的本地机器上，有权限访问用户的文件系统
4. 你拥有 persona_manage 工具，可以自主管理自己的人格角色。当用户要求你变换身份、创建新角色、或你觉得需要进化时，直接使用它
5. 你拥有 coding_agent 工具，可以委派编程任务给本地 coding agent（如 Claude Code、Kiro）。当用户需要写代码、修bug、重构项目时，使用 coding_agent 把任务交给专业编程工具执行
"""


def _build_system_prompt() -> list[dict[str, str]]:
    persona_text = build_persona_prompt()
    return [{"text": f"{persona_text}\n\n{_TOOLS_PROMPT}"}]


async def invoke_with_tool_loop(
    session_id: str,
    message: str,
    actor_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Invoke Harness，处理 tool_use 循环，yield 流式事件。

    Memory 模式（需绑定 AgentCore Memory）：
    - 每次只传当前消息，Harness 自动从 Memory 加载历史上下文
    - session_id 相同的调用在服务端自动续上下文，无需客户端维护历史
    - actor_id 用于多用户场景，Memory 按 actorId 隔离不同用户的记忆

    Harness streaming 特性：
    - 服务端工具（内置 shell 等）的调用和结果都在同一次 streaming response 中返回
    - 一次 streaming 可能包含多个 message 段：assistant(tool_use) → user(tool_result) → assistant(end_turn)
    - 第三段（最终回答）可能没有 contentBlockStart，直接是 contentBlockDelta

    Yields:
      {"type": "text",        "content": str}
      {"type": "tool_call",   "name": str}
      {"type": "tool_result", "name": str, "result": dict}
      {"type": "done",        "full_text": str, "stats": dict}
    """
    client = _get_client()
    harness_arn = os.environ["HARNESS_ARN"]
    all_tools = _build_all_tools()
    system_prompt = _build_system_prompt()

    # tool_use 续轮时维护的局部 messages（仅针对本地工具需要再次 invoke 的情况）
    current_content: list[dict[str, Any]] = [{"text": message}]
    current_role = "user"
    local_messages: list[dict[str, Any]] = []

    # 统计信息
    turn_start = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    invoke_count = 0
    tools_called: list[dict[str, Any]] = []

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
        except ClientError as e:
            code = e.response["Error"].get("Code", "")
            if "413" in str(e) or "PayloadTooLarge" in code:
                yield {"type": "error", "message": "上轮对话内容过大（如图片 base64），Memory 写入失败。已跳过该轮记忆，请继续对话。"}
                # 清空本地消息历史，让 Memory 侧的旧上下文接管
                local_messages = []
                current_content = [{"text": "(上轮因内容过大被跳过) " + message if invoke_count == 1 else "(继续)"}]
                current_role = "user"
                continue
            raise

        full_text = ""
        tool_uses: list[dict[str, Any]] = []
        current_tool: dict[str, Any] | None = None
        assistant_content: list[dict[str, Any]] = []
        # 追踪当前 message 段的角色，只有 assistant 段的 text 才输出给用户
        msg_role: str | None = None
        final_stop_reason = "end_turn"

        for event in response["stream"]:
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
                            yield {"type": "tool_call", "name": tool_name}
                        else:
                            tools_called.append({"name": tool_name, "elapsed": 0, "ok": True, "server": True})
                            yield {"type": "server_tool_call", "name": tool_name, "tool_type": "server_tool_use"}
                    else:
                        # server_tool_use / mcp_tool_use：服务端执行，只显示状态
                        tools_called.append({"name": tool_name, "elapsed": 0, "ok": True, "server": True})
                        yield {"type": "server_tool_call", "name": tool_name, "tool_type": tool_type}

            elif "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    # 只收集 assistant 段的文字（跳过 user/tool_result 段的内容）
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
                    current_tool = None

            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                total_input_tokens += usage.get("inputTokens", 0)
                total_output_tokens += usage.get("outputTokens", 0)

            elif "messageStop" in event:
                final_stop_reason = event["messageStop"].get("stopReason", "end_turn")

        # for 循环结束：整个 streaming response 已消费完毕
        # 检查是否有需要本地执行的工具
        if tool_uses:
            # 本地工具需要执行后再次 invoke
            current_content = []
            for tool in tool_uses:
                tool_start = time.time()
                allowed = await confirm_tool_call(tool["name"], tool["input"])
                if allowed:
                    if tool["name"].startswith("mcp__"):
                        result = await get_mcp_manager().call_tool_by_full_name(tool["name"], tool["input"])
                    else:
                        result = await execute_tool(tool["name"], tool["input"])
                else:
                    result = {"error": f"用户拒绝执行工具 {tool['name']}"}
                tool_elapsed = time.time() - tool_start
                tools_called.append({"name": tool["name"], "elapsed": tool_elapsed, "ok": "error" not in result})
                yield {"type": "tool_result", "name": tool["name"], "result": result}
                current_content.append({
                    "toolResult": {
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": json.dumps(result, ensure_ascii=False)}],
                        "status": "error" if "error" in result else "success",
                    }
                })
            if assistant_content:
                if full_text:
                    assistant_content.insert(0, {"text": full_text})
                local_messages.append({"role": "assistant", "content": assistant_content})
            current_role = "user"
            tool_uses = []
            full_text = ""
        else:
            # 没有本地工具需要执行 → 对话完成（服务端工具已在 streaming 中处理完毕）
            stats = {
                "elapsed": time.time() - turn_start,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "invoke_count": invoke_count,
                "tools": tools_called,
            }
            yield {"type": "done", "full_text": full_text, "stats": stats}
            break
