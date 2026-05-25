# -*- coding: utf-8 -*-
"""创建并绑定 AgentCore Browser 和 Code Interpreter 工具到 Harness。

注意：Browser 和 Code Interpreter 是独立的 AgentCore 资源，需要先创建获得 ARN，
然后通过 update_harness 绑定到 Harness 的 tools 列表。
"""
import json
import os
import time

import boto3
from dotenv import load_dotenv

# 从 ~/.hare/.env 加载
from pathlib import Path
env_file = Path.home() / ".hare" / ".env"
if env_file.exists():
    load_dotenv(env_file)

REGION = os.environ.get("AWS_REGION", "us-west-2")
PROFILE = os.environ.get("AWS_PROFILE")
HARNESS_ARN = os.environ.get("HARNESS_ARN", "")
EXECUTION_ROLE_ARN = os.environ.get("EXECUTION_ROLE_ARN", "")


def _wait_ready(client, resource_type: str, resource_id: str, get_fn, timeout: int = 120) -> str:
    """轮询等待资源 READY，返回 ARN。"""
    for i in range(timeout // 3):
        time.sleep(3)
        detail = get_fn(resource_id)
        inner = detail.get(resource_type) or detail
        status = inner.get("status", "UNKNOWN")
        print(f"   [{i*3}s] status: {status}")
        if status in ("READY", "ACTIVE"):
            return inner.get("browserArn") or inner.get("codeInterpreterArn") or inner.get("arn", "")
        elif status in ("FAILED", "DELETED"):
            raise RuntimeError(f"{resource_type} 创建失败: {status}")
    raise TimeoutError(f"{resource_type} 等待超时")


def create_browser(client) -> str:
    """创建 AgentCore Browser，返回 browserArn。"""
    print("⏳ 创建 AgentCore Browser...")
    resp = client.create_browser(
        name="hare_browser",
        description="Hare assistant browser tool",
        executionRoleArn=EXECUTION_ROLE_ARN,
        networkConfiguration={"networkMode": "PUBLIC"},
    )
    print(f"   create_browser 返回字段: {list(resp.keys())}")
    inner = resp.get("browser") or resp
    browser_id = inner.get("browserId") or inner.get("id")
    browser_arn = inner.get("browserArn") or inner.get("arn")
    print(f"   ID: {browser_id}, ARN: {browser_arn}")

    if not browser_arn and browser_id:
        browser_arn = _wait_ready(
            client, "browser", browser_id,
            lambda bid: client.get_browser(browserId=bid)
        )

    print(f"✅ Browser ARN: {browser_arn}")
    return browser_arn


def create_code_interpreter(client) -> str:
    """创建 AgentCore Code Interpreter，返回 codeInterpreterArn。"""
    print("⏳ 创建 AgentCore Code Interpreter...")
    resp = client.create_code_interpreter(
        name="hare_code_interpreter",
        description="Hare assistant code interpreter",
        executionRoleArn=EXECUTION_ROLE_ARN,
        networkConfiguration={"networkMode": "SANDBOX"},
    )
    print(f"   create_code_interpreter 返回字段: {list(resp.keys())}")
    inner = resp.get("codeInterpreter") or resp
    ci_id = inner.get("codeInterpreterId") or inner.get("id")
    ci_arn = inner.get("codeInterpreterArn") or inner.get("arn")
    print(f"   ID: {ci_id}, ARN: {ci_arn}")

    if not ci_arn and ci_id:
        ci_arn = _wait_ready(
            client, "codeInterpreter", ci_id,
            lambda cid: client.get_code_interpreter(codeInterpreterId=cid)
        )

    print(f"✅ Code Interpreter ARN: {ci_arn}")
    return ci_arn


def bind_tools_to_harness(client, harness_id: str, browser_arn: str, ci_arn: str) -> None:
    """将 Browser 和 Code Interpreter 绑定到 Harness 的 tools。"""
    print(f"\n⏳ 绑定工具到 Harness ({harness_id})...")

    # 先获取当前 harness 的 tools 列表（避免覆盖已有工具）
    current = client.get_harness(harnessId=harness_id)
    existing_tools = current.get("tools", []) or []

    # 过滤掉已有的 browser/code_interpreter 工具（避免重复）
    new_tools = [t for t in existing_tools
                 if t.get("type") not in ("agentcore_browser", "agentcore_code_interpreter")]

    # 追加新工具
    if browser_arn:
        new_tools.append({
            "type": "agentcore_browser",
            "name": "browser",
            "config": {"agentCoreBrowser": {"browserArn": browser_arn}},
        })
    if ci_arn:
        new_tools.append({
            "type": "agentcore_code_interpreter",
            "name": "code_interpreter",
            "config": {"agentCoreCodeInterpreter": {"codeInterpreterArn": ci_arn}},
        })

    client.update_harness(harnessId=harness_id, tools=new_tools)
    print(f"✅ 已绑定 {len(new_tools)} 个工具到 Harness")


def main():
    if not EXECUTION_ROLE_ARN or "ACCOUNT_ID" in EXECUTION_ROLE_ARN:
        print("❌ 请在 ~/.hare/.env 中设置 EXECUTION_ROLE_ARN")
        return
    if not HARNESS_ARN or "ACCOUNT_ID" in HARNESS_ARN:
        print("❌ 请在 ~/.hare/.env 中设置 HARNESS_ARN")
        return

    session = boto3.Session(region_name=REGION, profile_name=PROFILE)
    client = session.client("bedrock-agentcore-control")

    harness_id = HARNESS_ARN.split("/")[-1]

    browser_arn = create_browser(client)
    ci_arn = create_code_interpreter(client)

    bind_tools_to_harness(client, harness_id, browser_arn, ci_arn)

    print(f"\n🎉 Browser 和 Code Interpreter 已绑定到 Harness！")
    print(f"\n请将以下内容追加到 ~/.hare/.env（可选，供参考）：")
    print(f"BROWSER_ARN={browser_arn}")
    print(f"CODE_INTERPRETER_ARN={ci_arn}")


if __name__ == "__main__":
    main()
