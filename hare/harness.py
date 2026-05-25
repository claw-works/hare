from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator

import boto3

from hare.tools import TOOL_DEFINITIONS, execute_tool
from hare.tools.config import get_enabled_local_tools, get_gateway_tools
from hare.mcp_client import get_mcp_manager
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
    return tools


SYSTEM_PROMPT = [{"text": """你是 Hare，一个运行在用户本地机器上的 AI 助手。

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
4. 默认用中文回复用户
"""}]


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

    Yields:
      {"type": "text",        "content": str}
      {"type": "tool_call",   "name": str}
      {"type": "tool_result", "name": str, "result": dict}
      {"type": "done",        "full_text": str}
    """
    client = _get_client()
    harness_arn = os.environ["HARNESS_ARN"]
    all_tools = _build_all_tools()

    # 第一轮：只传当前用户消息，Memory 帮你补历史
    # tool_use 续轮：必须传 [assistant+toolUse, user+toolResult] 配对，
    #   不能只传 toolResult（因为 Memory 恢复的历史里没有这次 invoke 产生的 toolUse）
    # 因此 tool_use 循环内维护一个局部 messages 列表（仅当前 invoke 轮次）
    current_content: list[dict[str, Any]] = [{"text": message}]
    current_role = "user"
    local_messages: list[dict[str, Any]] = []  # 当前 invoke 产生的 toolUse/toolResult 配对

    while True:
        invoke_kwargs: dict[str, Any] = dict(
            harnessArn=harness_arn,
            runtimeSessionId=session_id,
            messages=local_messages + [{"role": current_role, "content": current_content}],
            systemPrompt=SYSTEM_PROMPT,
            tools=all_tools,
        )
        if actor_id:
            invoke_kwargs["actorId"] = actor_id

        response = client.invoke_harness(**invoke_kwargs)

        full_text = ""
        tool_uses: list[dict[str, Any]] = []
        current_tool: dict[str, Any] | None = None
        stop_reason = "end_turn"
        assistant_content: list[dict[str, Any]] = []

        for event in response["stream"]:
            if "contentBlockStart" in event:
                start = event["contentBlockStart"].get("start", {})
                if "toolUse" in start:
                    tool_type = start["toolUse"].get("type", "tool_use")
                    tool_name = start["toolUse"]["name"]
                    if tool_type == "tool_use":
                        # inline_function：本地执行
                        current_tool = {
                            "toolUseId": start["toolUse"]["toolUseId"],
                            "name": tool_name,
                            "input_json": "",
                        }
                        yield {"type": "tool_call", "name": tool_name}
                    else:
                        # server_tool_use / mcp_tool_use：服务端执行，只显示状态
                        yield {"type": "server_tool_call", "name": tool_name, "tool_type": tool_type}

            elif "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
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

                    # 只把本地注册表里有的工具加进 tool_uses（让本地执行）
                    # Harness 内置工具（如 shell、code_interpreter）不在注册表里，
                    # 它们由 Harness 服务端直接执行，stopReason=tool_result 时自动续轮
                    from hare.tools import TOOL_REGISTRY
                    from hare.mcp_client import get_mcp_manager as _get_mcp_mgr
                    is_local = current_tool["name"] in TOOL_REGISTRY
                    is_mcp = current_tool["name"].startswith("mcp__")
                    if is_local or is_mcp:
                        tool_uses.append(current_tool)
                        assistant_content.append({
                            "toolUse": {
                                "toolUseId": current_tool["toolUseId"],
                                "name": current_tool["name"],
                                "input": input_data,
                            }
                        })
                    # else: Harness 内置工具，跳过本地执行
                    current_tool = None

            elif "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason", "end_turn")
                # 同一次 streaming 可能包含多个 message 段（tool_use → tool_result → end_turn）
                # 一旦遇到 end_turn，整个对话在服务端已完成，不需要再循环
                if stop_reason == "end_turn":
                    break  # 直接跳出 for 循环，后面判断会 yield done

        if stop_reason == "tool_use" and not tool_uses:
            # tool_use 但 tool_uses 为空 = Harness 内置工具（已跳过本地执行）
            # 直接继续循环，等待服务端处理完后的 tool_result
            current_content = [{"text": ""}]
            current_role = "user"
            local_messages = []
        elif stop_reason == "tool_use" and tool_uses:
            # 本地工具执行，下一轮只传 toolResult（不传历史）
            current_content = []
            for tool in tool_uses:
                allowed = await confirm_tool_call(tool["name"], tool["input"])
                if allowed:
                    if tool["name"].startswith("mcp__"):
                        result = await get_mcp_manager().call_tool_by_full_name(tool["name"], tool["input"])
                    else:
                        result = await execute_tool(tool["name"], tool["input"])
                else:
                    result = {"error": f"用户拒绝执行工具 {tool['name']}"}
                yield {"type": "tool_result", "name": tool["name"], "result": result}
                current_content.append({
                    "toolResult": {
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": json.dumps(result, ensure_ascii=False)}],
                        "status": "error" if "error" in result else "success",
                    }
                })
            # 把本次 invoke 的 assistant toolUse 加入局部 messages，
            # 让下一轮的 toolResult 能和它配对
            if assistant_content:
                if full_text:
                    assistant_content.insert(0, {"text": full_text})
                local_messages.append({"role": "assistant", "content": assistant_content})
            current_role = "user"
            tool_uses = []
            full_text = ""
        elif stop_reason == "tool_result":
            # 服务端工具（server_tool_use）执行完毕，Harness 把结果注入后
            # 需要继续循环，让模型看到结果后再推理输出最终回答
            # 下一轮只传一个空的 user 消息触发继续推理
            current_content = [{"text": ""}]
            current_role = "user"
            local_messages = []
            tool_uses = []
            full_text = ""
        else:
            yield {"type": "done", "full_text": full_text}
            break
