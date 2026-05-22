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
        if auth == "none":
            auth_config = {"none": {}}
        else:
            auth_config = {"awsIam": {}}
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

重要原则：
1. 当用户询问本地文件、目录内容时，优先使用 shell_run 或 read_file 工具直接查找，不要让用户自己去跑命令
2. 当用户需要执行系统操作时，直接用 shell_run 执行，返回结果
3. 你运行在用户的本地机器上，有权限访问用户的文件系统
4. 默认用中文回复用户
"""}]


async def invoke_with_tool_loop(
    session_id: str,
    message: str,
    messages: list[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Invoke Harness，处理 tool_use 循环，yield 流式事件。

    - messages 由调用方（app.py）维护和传入，harness 不自管历史
    - runtimeSessionId 用于 Harness 的 stateful 会话（内存/filesystem）
    """
    client = _get_client()
    harness_arn = os.environ["HARNESS_ARN"]
    inline_tools = _build_all_tools()

    # 追加用户消息（由调用方传入 messages 引用，修改会自动同步到 SessionManager）
    messages.append({"role": "user", "content": [{"text": message}]})

    while True:
        response = client.invoke_harness(
            harnessArn=harness_arn,
            runtimeSessionId=session_id,
            messages=messages,          # 传完整历史
            systemPrompt=SYSTEM_PROMPT,
            tools=inline_tools,
        )

        full_text = ""
        tool_uses: list[dict[str, Any]] = []
        current_tool: dict[str, Any] | None = None
        stop_reason = "end_turn"
        assistant_content: list[dict[str, Any]] = []

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
                    assistant_content.append({
                        "toolUse": {
                            "toolUseId": current_tool["toolUseId"],
                            "name": current_tool["name"],
                            "input": input_data,
                        }
                    })
                    current_tool = None
                elif full_text:
                    pass

            elif "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason", "end_turn")

        # 把 assistant 这轮的文字也加进 content
        if full_text and not any("toolUse" in c for c in assistant_content):
            assistant_content = [{"text": full_text}]
        elif full_text:
            assistant_content.insert(0, {"text": full_text})

        # 把 assistant 消息加入历史
        if assistant_content:
            messages.append({"role": "assistant", "content": assistant_content})

        if stop_reason == "tool_use" and tool_uses:
            # 执行本地工具
            tool_result_content: list[dict[str, Any]] = []
            for tool in tool_uses:
                result = await execute_tool(tool["name"], tool["input"])
                yield {"type": "tool_result", "name": tool["name"], "result": result}
                tool_result_content.append({
                    "toolResult": {
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": json.dumps(result, ensure_ascii=False)}],
                        "status": "error" if "error" in result else "success",
                    }
                })

            messages.append({"role": "user", "content": tool_result_content})
            tool_uses = []
            full_text = ""
        else:
            yield {"type": "done", "full_text": full_text}
            break


def clear_session(session_id: str, messages: list) -> None:
    """清空传入的 messages 列表（由调用方负责持久化）。"""
    messages.clear()
