# -*- coding: utf-8 -*-
"""Sub-agent 工具 — 在同一个 Harness 上启动子会话执行独立子任务。

子会话特点：
- 独立的短期记忆（对话历史隔离）
- 共享长期记忆（跨 session 的提炼信息可互通）
- 临时性：用完即弃，不出现在会话列表中
- session_id 以 hsub_ 开头，方便区分
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import boto3


def _new_sub_session_id(parent_session_id: str) -> str:
    """生成子会话 ID：hsub_ + 父会话前8位 + _ + 短 uuid。"""
    parent_prefix = parent_session_id[1:9] if parent_session_id.startswith("h") else parent_session_id[:8]
    return f"hsub_{parent_prefix}_{uuid.uuid4().hex[:12]}"


def sub_task(
    task: str,
    parent_session_id: str | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """
    启动一个子任务会话，执行完毕后返回结果。

    task: 子任务的描述/指令
    parent_session_id: 父会话 ID（用于生成子会话 ID 前缀）
    system_prompt: 可选的子任务 system prompt（默认用简洁的任务执行 prompt）
    """
    session = boto3.Session(
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
        profile_name=os.environ.get("AWS_PROFILE"),
    )
    client = session.client("bedrock-agentcore")
    harness_arn = os.environ["HARNESS_ARN"]

    sub_session_id = _new_sub_session_id(parent_session_id or "h_unknown_")

    default_system = "你是一个专注执行子任务的助手。直接完成任务，简洁回复结果，不要寒暄。"
    sys_prompt = [{"text": system_prompt or default_system}]

    try:
        response = client.invoke_harness(
            harnessArn=harness_arn,
            runtimeSessionId=sub_session_id,
            messages=[{"role": "user", "content": [{"text": task}]}],
            systemPrompt=sys_prompt,
            tools=[],
            timeoutSeconds=120,
        )

        full_text = ""
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    full_text += delta["text"]

        return {"output": full_text.strip(), "sub_session_id": sub_session_id}

    except Exception as e:
        return {"error": str(e), "sub_session_id": sub_session_id}
