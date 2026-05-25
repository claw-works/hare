# -*- coding: utf-8 -*-
"""交互式向导：创建 Harness 全套资源。"""
from __future__ import annotations

import json
import os
import sys
import time

import boto3
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

ROLE_NAME = "hare-harness-execution-role"
MEMORY_NAME = "hare_memory"

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}

INLINE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:ListEvents",
                "bedrock-agentcore:GetMemory",
                "bedrock-agentcore:CreateEvent",
                "bedrock-agentcore:InvokeMemory",
                "bedrock-agentcore:RetrieveMemoryRecords",
            ],
            "Resource": "arn:aws:bedrock-agentcore:*:*:memory/*",
        },
        {
            "Effect": "Allow",
            "Action": ["bedrock-agentcore:InvokeBrowser"],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": ["bedrock-agentcore:InvokeCodeInterpreter"],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": ["bedrock-agentcore:InvokeGateway"],
            "Resource": "*",
        },
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _section(step: int, total: int, title: str) -> None:
    console.print(f"\n[bold cyan]Step {step}/{total}  {title}[/bold cyan]")
    console.print("[dim]" + "─" * 50 + "[/dim]")


def _ok(msg: str) -> None:
    console.print(f"  [bold green]✅[/bold green]  {msg}")


def _err(msg: str) -> None:
    console.print(f"  [bold red]❌[/bold red]  {msg}")


def _info(msg: str) -> None:
    console.print(f"  [dim]{msg}[/dim]")


# ── IAM Role ──────────────────────────────────────────────────────────────────


def _create_execution_role(session: boto3.Session) -> str:
    """自动创建 IAM 执行角色，返回 ARN。"""
    iam = session.client("iam")

    try:
        existing = iam.get_role(RoleName=ROLE_NAME)
        role_arn = existing["Role"]["Arn"]
        _ok(f"IAM Role 已存在: {role_arn}")
        return role_arn
    except iam.exceptions.NoSuchEntityException:
        pass

    console.print(f"  ⏳ 创建 IAM Role: {ROLE_NAME} ...")
    resp = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
        Description="Execution role for Hare AgentCore Harness",
    )
    role_arn = resp["Role"]["Arn"]

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="hare-bedrock-invoke",
        PolicyDocument=json.dumps(INLINE_POLICY),
    )
    _ok("权限策略已附加")

    console.print("  ⏳ 等待 Role 生效（约 10 秒）...")
    time.sleep(10)
    _ok(f"IAM Role 就绪: {role_arn}")
    return role_arn


# ── Memory ────────────────────────────────────────────────────────────────────


def _create_memory(client, harness_arn: str) -> str | None:
    """创建 Memory 并绑定到 Harness，返回 memory_arn。"""
    console.print("  ⏳ 查找已有 Memory...")
    memories = client.list_memories().get("memories") or []
    existing = next((m for m in memories if m.get("id", "").startswith(MEMORY_NAME)), None)

    if existing:
        memory_arn = existing["arn"]
        memory_id = existing["id"]
        _ok(f"Memory 已存在: {memory_id}")
    else:
        console.print(f"  ⏳ 创建 Memory '{MEMORY_NAME}'...")
        resp = client.create_memory(
            name=MEMORY_NAME,
            description="Hare assistant long-term memory",
            eventExpiryDuration=90,
        )
        inner = resp.get("memory") or resp
        memory_arn = inner.get("arn") or inner.get("memoryArn")
        memory_id = inner.get("id") or inner.get("memoryId")

        # 等待 ACTIVE
        for i in range(30):
            time.sleep(3)
            detail = client.get_memory(memoryId=memory_id)
            inner_d = detail.get("memory") or detail
            status = inner_d.get("status", "UNKNOWN")
            console.print(f"    [{i*3}s] status: {status}")
            if status == "ACTIVE":
                break
            elif status in ("FAILED", "DELETED"):
                _err(f"Memory 创建失败: {status}")
                return None
        _ok(f"Memory 就绪: {memory_arn}")

    # 绑定到 Harness
    harness_id = harness_arn.split("/")[-1]
    console.print(f"  ⏳ 绑定 Memory 到 Harness...")
    client.update_harness(
        harnessId=harness_id,
        memory={
            "optionalValue": {
                "agentCoreMemoryConfiguration": {
                    "arn": memory_arn,
                    "messagesCount": 20,
                }
            }
        },
    )
    _ok("Memory 已绑定到 Harness")
    return memory_arn


# ── Main Wizard ───────────────────────────────────────────────────────────────


def main():
    console.print(Panel(
        "[bold green]🐇 Hare Harness 初始化向导[/bold green]\n"
        "[dim]交互式创建 Harness 全套资源，无需 .env 文件[/dim]",
        border_style="green",
        padding=(1, 4),
    ))

    total_steps = 7

    # ── Step 1: AWS Region & Profile ──────────────────────────────────────
    _section(1, total_steps, "AWS Region & Profile")

    region = Prompt.ask("  AWS Region", default="us-west-2")
    profile = Prompt.ask("  AWS Profile", default="default")

    # ── Step 2: 验证 AWS 凭证 ─────────────────────────────────────────────
    _section(2, total_steps, "验证 AWS 凭证")

    try:
        session = boto3.Session(region_name=region, profile_name=profile)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        account_id = identity["Account"]
        _ok(f"凭证有效 — Account: {account_id}, User: {identity['Arn'].split('/')[-1]}")
    except Exception as e:
        _err(f"AWS 凭证无效: {e}")
        console.print("  请检查 ~/.aws/credentials 中的 profile 配置后重试")
        sys.exit(1)

    # ── Step 3: Execution Role ARN ────────────────────────────────────────
    _section(3, total_steps, "Execution Role ARN")

    console.print(Panel(
        "[bold]EXECUTION_ROLE_ARN 获取方式[/bold]\n\n"
        "[green]方式1（推荐）：让脚本自动创建[/green]\n"
        "   → 自动创建 hare-harness-execution-role，包含所有必要权限\n\n"
        "[yellow]方式2：手动在 AWS Console 创建[/yellow]\n"
        "   1. 打开 https://console.aws.amazon.com/iam/home#/roles\n"
        "   2. 创建角色 → 选「AWS 服务」→ 选「Bedrock AgentCore」\n"
        "   3. 附加权限策略（见下方）\n"
        "   4. 角色名称建议：hare-harness-execution-role\n"
        "   所需权限：\n"
        "   - bedrock:InvokeModel\n"
        "   - bedrock:InvokeModelWithResponseStream\n"
        "   - bedrock-agentcore:ListEvents\n"
        "   - bedrock-agentcore:CreateEvent\n"
        "   - bedrock-agentcore:InvokeBrowser\n"
        "   - bedrock-agentcore:InvokeCodeInterpreter\n"
        "   - bedrock-agentcore:InvokeGateway",
        border_style="dim",
        padding=(1, 2),
    ))

    auto_create = Confirm.ask("  自动创建 Execution Role?", default=True)
    if auto_create:
        execution_role_arn = _create_execution_role(session)
    else:
        execution_role_arn = Prompt.ask("  请输入 EXECUTION_ROLE_ARN")
        if not execution_role_arn.startswith("arn:aws:iam::"):
            _err("ARN 格式不正确，应以 arn:aws:iam:: 开头")
            sys.exit(1)
        _ok(f"使用已有 Role: {execution_role_arn}")

    # ── Step 4: 创建 Harness ──────────────────────────────────────────────
    _section(4, total_steps, "创建 Harness")

    client = session.client("bedrock-agentcore-control")
    console.print(f"  ⏳ 创建 Harness (region: {region})...")

    resp = client.create_harness(
        harnessName="hare_assistant",
        executionRoleArn=execution_role_arn,
    )
    harness_id = resp.get("harnessId") or resp.get("harness", {}).get("harnessId")
    harness_arn = resp.get("harnessArn") or resp.get("harness", {}).get("harnessArn")

    console.print(f"  ⏳ 等待 Harness READY...")
    for i in range(150):
        time.sleep(2)
        detail = client.get_harness(harnessId=harness_id)
        status = detail.get("status", "UNKNOWN")
        if i % 5 == 0:
            console.print(f"    [{i*2}s] status: {status}")
        if status == "READY":
            _ok(f"Harness 就绪！ARN: {harness_arn}")
            break
        elif status in ("FAILED", "DELETED"):
            _err(f"Harness 创建失败: {status}")
            console.print(json.dumps(detail, indent=2, default=str))
            sys.exit(1)
    else:
        _err("超时，请手动检查 Harness 状态")
        sys.exit(1)

    # ── Step 5: AgentCore Memory ──────────────────────────────────────────
    _section(5, total_steps, "AgentCore Memory（长期记忆）")

    memory_arn = None
    if Confirm.ask("  是否创建 AgentCore Memory?（建议 Yes）", default=True):
        memory_arn = _create_memory(client, harness_arn)

    # ── Step 6: Browser & Code Interpreter ────────────────────────────────
    _section(6, total_steps, "Browser & Code Interpreter")

    _info("Browser 和 Code Interpreter 无需创建额外资源")
    _info("hare 已在 tools.yaml 中默认启用这两个工具")
    enable_browser = Confirm.ask("  确认启用 Browser?", default=True)
    enable_code_interpreter = Confirm.ask("  确认启用 Code Interpreter?", default=True)

    # ── Step 7: Gateway ARN ───────────────────────────────────────────────
    _section(7, total_steps, "Gateway ARN（可选，接入企业 MCP 工具）")

    console.print(Panel(
        "[bold]Gateway ARN 获取方式[/bold]\n\n"
        "1. 打开 AWS Console → Amazon Bedrock → AgentCore → Gateways\n"
        "2. 创建 Gateway，注册你的 MCP server URL\n"
        "3. 创建完成后复制 Gateway ARN\n"
        "4. 也可以之后运行 scripts/create_gateway.py 来创建",
        border_style="dim",
        padding=(1, 2),
    ))

    gateway_arn = None
    if Confirm.ask("  现在配置 Gateway ARN?", default=False):
        gateway_arn = Prompt.ask("  请输入 Gateway ARN")

    # ── 最终汇总 ──────────────────────────────────────────────────────────
    env_lines = [
        f"AWS_REGION={region}",
        f"AWS_PROFILE={profile}",
        f"HARNESS_ARN={harness_arn}",
        f"EXECUTION_ROLE_ARN={execution_role_arn}",
    ]
    if memory_arn:
        env_lines.append(f"MEMORY_ARN={memory_arn}")

    env_block = "\n".join(env_lines)

    # Browser/Code Interpreter 提示
    tools_note = ""
    if enable_browser or enable_code_interpreter:
        tools_note = (
            "\n[bold]可选（已在 tools.yaml 中配置）：[/bold]\n"
            "Browser 和 Code Interpreter 已在 hare 中默认启用，无需额外配置\n"
        )

    # Gateway 提示
    gateway_note = ""
    if gateway_arn:
        gateway_note = (
            f"\n[bold]Gateway 已配置：[/bold]\n"
            f"GATEWAY_ARN={gateway_arn}\n"
            "请在 ~/.hare/tools.yaml 的 gateway_tools 中添加：\n"
            "  - name: my_gateway\n"
            "    enabled: true\n"
        )
    else:
        gateway_note = (
            "\n[bold]可选（如需接入企业工具）：[/bold]\n"
            "在 ~/.hare/tools.yaml 的 gateway_tools 中添加：\n"
            "  - name: my_gateway\n"
            "    enabled: true\n"
        )

    console.print(Panel(
        "[bold green]🎉 初始化完成！[/bold green]\n\n"
        f"请将以下内容写入 [cyan]~/.hare/.env[/cyan]：\n\n"
        f"[white]{env_block}[/white]\n"
        f"{tools_note}"
        f"{gateway_note}",
        border_style="green",
        padding=(1, 4),
    ))


if __name__ == "__main__":
    main()
