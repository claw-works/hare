# -*- coding: utf-8 -*-
"""Sub-agent tool — spawn sub-sessions on the same Harness for independent sub-tasks.

Sub-session characteristics:
- Independent short-term memory (conversation history is isolated)
- Shared long-term memory (distilled info across sessions is accessible)
- Ephemeral: disposed after use, not shown in session list
- session_id starts with hsub_ for easy identification
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import boto3


def _new_sub_session_id(parent_session_id: str) -> str:
    """Generate sub-session ID: hsub_ + first 8 chars of parent + _ + short uuid."""
    parent_prefix = parent_session_id[1:9] if parent_session_id.startswith("h") else parent_session_id[:8]
    return f"hsub_{parent_prefix}_{uuid.uuid4().hex[:12]}"


def sub_task(
    task: str,
    parent_session_id: str | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """
    Spawn a sub-task session, return results after completion.

    task: sub-task description/instructions
    parent_session_id: parent session ID (used to generate sub-session ID prefix)
    system_prompt: optional sub-task system prompt (defaults to a concise task execution prompt)
    """
    session = boto3.Session(
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
        profile_name=os.environ.get("AWS_PROFILE"),
    )
    client = session.client("bedrock-agentcore")
    harness_arn = os.environ["HARNESS_ARN"]

    sub_session_id = _new_sub_session_id(parent_session_id or "h_unknown_")

    default_system = "You are a focused sub-task assistant. Complete the task directly, reply concisely with results, no small talk."
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
