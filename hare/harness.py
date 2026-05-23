from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator

import boto3

from hare.tools import TOOL_DEFINITIONS, execute_tool
from hare.tools.config import get_enabled_local_tools, get_gateway_tools


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
    """本地 inline_function + 远端 agentcore_gateway。"""
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
    return tools


SYSTEM_PROMPT = [{"text": """你是 Hare，一个运行在用户本地机器上的 AI 助手。

你拥有以下本地工具，可以直接操作用户的本地系统：
- shell_run：在用户本地执行任意 shell 命令，可用于查找文件、运行程序、获取系统信息等
- read_file：读取用户本地的文件内容
- write_file：向用户本地写入文件

你拥有跨会话的长期记忆（由 AgentCore Memory 提供）。你能记住用户之前告诉过你的事情、工作习惯、项目背景等。如果系统已将相关记忆注入到你的上下文中，请自然地利用这些信息回答用户，不要说"我没有记忆功能"。

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

    # 每次只传当前轮内容，历史由 Harness + Memory 在服务端托管
    current_content: list[dict[str, Any]] = [{"text": message}]
    current_role = "user"

    while True:
        invoke_kwargs: dict[str, Any] = dict(
            harnessArn=harness_arn,
            runtimeSessionId=session_id,
            messages=[{"role": current_role, "content": current_content}],
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

        for event in response["stream"]:
            if "contentBlockStart" in event:
                start = event["contentBlockStart"].get("start", {})
                if "toolUse" in start:
                    current_tool = {
                        "toolUseId": start["toolUse"]["toolUseId"],
                        "name": start["toolUse"]["name"],
                        "input_json": "",
                    }
                    yield {"type": "tool_call", "name": current_tool["name"]}

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
                    tool_uses.append(current_tool)
                    current_tool = None

            elif "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason", "end_turn")

        if stop_reason == "tool_use" and tool_uses:
            # 本地工具执行，下一轮只传 toolResult（不传历史）
            current_content = []
            for tool in tool_uses:
                result = await execute_tool(tool["name"], tool["input"])
                yield {"type": "tool_result", "name": tool["name"], "result": result}
                current_content.append({
                    "toolResult": {
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": json.dumps(result, ensure_ascii=False)}],
                        "status": "error" if "error" in result else "success",
                    }
                })
            current_role = "user"
            tool_uses = []
            full_text = ""
        else:
            yield {"type": "done", "full_text": full_text}
            break
