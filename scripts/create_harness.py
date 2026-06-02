# -*- coding: utf-8 -*-
"""Interactive wizard: create full Harness resource stack."""
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
    """Auto-create IAM execution role, return ARN."""
    iam = session.client("iam")

    try:
        existing = iam.get_role(RoleName=ROLE_NAME)
        role_arn = existing["Role"]["Arn"]
        _ok(f"IAM Role already exists: {role_arn}")
        return role_arn
    except iam.exceptions.NoSuchEntityException:
        pass

    console.print(f"  ⏳ Creating IAM Role: {ROLE_NAME} ...")
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
    _ok("Permission policy attached")

    console.print("  ⏳ Waiting for Role to propagate (~10s)...")
    time.sleep(10)
    _ok(f"IAM Role ready: {role_arn}")
    return role_arn


# ── Memory ────────────────────────────────────────────────────────────────────


def _create_memory(client, harness_arn: str) -> str | None:
    """Create Memory and bind to Harness, return memory_arn."""
    console.print("  ⏳ Looking for existing Memory...")
    memories = client.list_memories().get("memories") or []
    existing = next((m for m in memories if m.get("id", "").startswith(MEMORY_NAME)), None)

    if existing:
        memory_arn = existing["arn"]
        memory_id = existing["id"]
        _ok(f"Memory already exists: {memory_id}")
    else:
        console.print(f"  ⏳ Creating Memory '{MEMORY_NAME}'...")
        resp = client.create_memory(
            name=MEMORY_NAME,
            description="Hare assistant long-term memory",
            eventExpiryDuration=90,
        )
        inner = resp.get("memory") or resp
        memory_arn = inner.get("arn") or inner.get("memoryArn")
        memory_id = inner.get("id") or inner.get("memoryId")

        # Wait for ACTIVE
        for i in range(30):
            time.sleep(3)
            detail = client.get_memory(memoryId=memory_id)
            inner_d = detail.get("memory") or detail
            status = inner_d.get("status", "UNKNOWN")
            console.print(f"    [{i*3}s] status: {status}")
            if status == "ACTIVE":
                break
            elif status in ("FAILED", "DELETED"):
                _err(f"Memory creation failed: {status}")
                return None
        _ok(f"Memory ready: {memory_arn}")

    # Bind to Harness
    harness_id = harness_arn.split("/")[-1]
    console.print(f"  ⏳ Binding Memory to Harness...")
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
    _ok("Memory bound to Harness")
    return memory_arn


# ── Main Wizard ───────────────────────────────────────────────────────────────


def main():
    console.print(Panel(
        "[bold green]🐇 Hare Harness Setup Wizard[/bold green]\n"
        "[dim]Interactively create full Harness resource stack, no .env file needed[/dim]",
        border_style="green",
        padding=(1, 4),
    ))

    total_steps = 7

    # ── Step 1: AWS Region & Profile ──────────────────────────────────────
    _section(1, total_steps, "AWS Region & Profile")

    region = Prompt.ask("  AWS Region", default="us-west-2")
    profile = Prompt.ask("  AWS Profile", default="default")

    # ── Step 2: Verify AWS Credentials ─────────────────────────────────────
    _section(2, total_steps, "Verify AWS Credentials")

    try:
        session = boto3.Session(region_name=region, profile_name=profile)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        account_id = identity["Account"]
        _ok(f"Credentials valid — Account: {account_id}, User: {identity['Arn'].split('/')[-1]}")
    except Exception as e:
        _err(f"Invalid AWS credentials: {e}")
        console.print("  Check the profile config in ~/.aws/credentials and retry")
        sys.exit(1)

    # ── Step 3: Execution Role ARN ────────────────────────────────────────
    _section(3, total_steps, "Execution Role ARN")

    console.print(Panel(
        "[bold]How to get EXECUTION_ROLE_ARN[/bold]\n\n"
        "[green]Option 1 (Recommended): Let the script auto-create[/green]\n"
        "   → Auto-creates hare-harness-execution-role with all required permissions\n\n"
        "[yellow]Option 2: Create manually in AWS Console[/yellow]\n"
        "   1. Open https://console.aws.amazon.com/iam/home#/roles\n"
        "   2. Create role → Select 'AWS service' → Select 'Bedrock AgentCore'\n"
        "   3. Attach permission policies (see below)\n"
        "   4. Suggested role name: hare-harness-execution-role\n"
        "   Required permissions:\n"
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

    auto_create = Confirm.ask("  Auto-create Execution Role?", default=True)
    if auto_create:
        execution_role_arn = _create_execution_role(session)
    else:
        execution_role_arn = Prompt.ask("  Enter EXECUTION_ROLE_ARN")
        if not execution_role_arn.startswith("arn:aws:iam::"):
            _err("ARN format incorrect, should start with arn:aws:iam::")
            sys.exit(1)
        _ok(f"Using existing Role: {execution_role_arn}")

    # ── Step 4: Create Harness ─────────────────────────────────────────────
    _section(4, total_steps, "Create Harness")

    client = session.client("bedrock-agentcore-control")
    console.print(f"  ⏳ Creating Harness (region: {region})...")

    resp = client.create_harness(
        harnessName="hare_assistant",
        executionRoleArn=execution_role_arn,
    )
    harness_id = resp.get("harnessId") or resp.get("harness", {}).get("harnessId")
    harness_arn = resp.get("harnessArn") or resp.get("harness", {}).get("harnessArn")

    console.print(f"  ⏳ Waiting for Harness READY...")
    for i in range(150):
        time.sleep(2)
        detail = client.get_harness(harnessId=harness_id)
        status = detail.get("status", "UNKNOWN")
        if i % 5 == 0:
            console.print(f"    [{i*2}s] status: {status}")
        if status == "READY":
            _ok(f"Harness ready! ARN: {harness_arn}")
            break
        elif status in ("FAILED", "DELETED"):
            _err(f"Harness creation failed: {status}")
            console.print(json.dumps(detail, indent=2, default=str))
            sys.exit(1)
    else:
        _err("Timeout, please check Harness status manually")
        sys.exit(1)

    # ── Step 5: AgentCore Memory ──────────────────────────────────────────
    _section(5, total_steps, "AgentCore Memory (long-term memory)")

    memory_arn = None
    if Confirm.ask("  Create AgentCore Memory? (recommended Yes)", default=True):
        memory_arn = _create_memory(client, harness_arn)

    # ── Step 6: Browser & Code Interpreter ────────────────────────────────
    _section(6, total_steps, "Browser & Code Interpreter")

    _info("Browser and Code Interpreter don't need extra resources")
    _info("hare already enables both tools by default in tools.yaml")
    enable_browser = Confirm.ask("  Enable Browser?", default=True)
    enable_code_interpreter = Confirm.ask("  Enable Code Interpreter?", default=True)

    # ── Step 7: Gateway ARN ───────────────────────────────────────────────
    _section(7, total_steps, "Gateway ARN (optional, for enterprise MCP tools)")

    console.print(Panel(
        "[bold]How to get Gateway ARN[/bold]\n\n"
        "1. Open AWS Console → Amazon Bedrock → AgentCore → Gateways\n"
        "2. Create Gateway, register your MCP server URL\n"
        "3. Copy the Gateway ARN after creation\n"
        "4. Or run scripts/create_gateway.py later",
        border_style="dim",
        padding=(1, 2),
    ))

    gateway_arn = None
    if Confirm.ask("  Configure Gateway ARN now?", default=False):
        gateway_arn = Prompt.ask("  Enter Gateway ARN")

    # ── Final summary ─────────────────────────────────────────────────────
    env_lines = [
        f"AWS_REGION={region}",
        f"AWS_PROFILE={profile}",
        f"HARNESS_ARN={harness_arn}",
        f"EXECUTION_ROLE_ARN={execution_role_arn}",
    ]
    if memory_arn:
        env_lines.append(f"MEMORY_ARN={memory_arn}")

    env_block = "\n".join(env_lines)

    # Browser/Code Interpreter note
    tools_note = ""
    if enable_browser or enable_code_interpreter:
        tools_note = (
            "\n[bold]Optional (configured in tools.yaml):[/bold]\n"
            "Browser and Code Interpreter are enabled by default in hare, no extra config needed\n"
        )

    # Gateway note
    gateway_note = ""
    if gateway_arn:
        gateway_note = (
            f"\n[bold]Gateway configured:[/bold]\n"
            f"GATEWAY_ARN={gateway_arn}\n"
            "Add to gateway_tools in ~/.hare/tools.yaml:\n"
            "  - name: my_gateway\n"
            "    enabled: true\n"
        )
    else:
        gateway_note = (
            "\n[bold]Optional (for enterprise tools):[/bold]\n"
            "Add to gateway_tools in ~/.hare/tools.yaml:\n"
            "  - name: my_gateway\n"
            "    enabled: true\n"
        )

    console.print(Panel(
        "[bold green]🎉 Setup complete![/bold green]\n\n"
        f"Write the following to [cyan]~/.hare/.env[/cyan]:\n\n"
        f"[white]{env_block}[/white]\n"
        f"{tools_note}"
        f"{gateway_note}",
        border_style="green",
        padding=(1, 4),
    ))


if __name__ == "__main__":
    main()
