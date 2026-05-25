# -*- coding: utf-8 -*-
"""hare onboarding — 引导员工完成初始化配置。
只面向员工，不做运维操作（IAM/Harness/Memory 的创建由运维执行 scripts/ 脚本完成）。
"""
from __future__ import annotations

import os
import sys
import boto3
from pathlib import Path
from dotenv import load_dotenv, set_key

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

HARE_DIR = Path.home() / ".hare"
ENV_FILE = HARE_DIR / ".env"

console = Console()


def _section(step: int, total: int, title: str) -> None:
    console.print(f"\n[bold cyan]Step {step}/{total}  {title}[/bold cyan]")
    console.print("[dim]" + "─" * 50 + "[/dim]")


def _ok(msg: str) -> None:
    console.print(f"  [bold green]✅[/bold green]  {msg}")


def _warn(msg: str) -> None:
    console.print(f"  [bold yellow]⚠️[/bold yellow]   {msg}")


def _err(msg: str) -> None:
    console.print(f"  [bold red]❌[/bold red]  {msg}")


def _save_env(key: str, value: str) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), key, value)


def run_onboarding() -> None:
    """运行员工 onboarding 流程。"""
    console.print(Panel(
        "[bold green]🐇 hare 初始化向导[/bold green]\n"
        "[dim]引导你完成初始配置，约需 1-2 分钟\n"
        "Harness ARN 和 Memory 由 IT/运维提前部署，向他们索取即可[/dim]",
        border_style="green",
        padding=(1, 4),
    ))

    HARE_DIR.mkdir(parents=True, exist_ok=True)
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)

    # ── Step 1: AWS Region & Profile ─────────────────────────────────────
    _section(1, 3, "AWS 凭证配置")

    region = os.environ.get("AWS_REGION", "")
    if region:
        _ok(f"AWS_REGION 已配置: {region}")
        if Confirm.ask("  是否修改?", default=False):
            region = ""
    if not region:
        region = Prompt.ask("  AWS Region", default="us-west-2")
        _save_env("AWS_REGION", region)
        os.environ["AWS_REGION"] = region

    profile = os.environ.get("AWS_PROFILE", "")
    if profile:
        _ok(f"AWS_PROFILE 已配置: {profile}")
        if Confirm.ask("  是否修改?", default=False):
            profile = ""
    if not profile:
        profile = Prompt.ask("  AWS Profile", default="default")
        _save_env("AWS_PROFILE", profile)
        os.environ["AWS_PROFILE"] = profile

    # ── Step 2: 验证 AWS 凭证 ─────────────────────────────────────────────
    _section(2, 3, "验证 AWS 凭证")

    try:
        session = boto3.Session(region_name=region, profile_name=profile)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        _ok(f"凭证有效 — Account: {identity['Account']}, User: {identity['Arn'].split('/')[-1]}")
    except Exception as e:
        _err(f"AWS 凭证无效: {e}")
        console.print("  请检查 ~/.aws/credentials 中的 profile 配置")
        console.print("  修正后重新运行: [bold]uv run hare --setup[/bold]")
        sys.exit(1)

    # ── Step 3: HARNESS_ARN ───────────────────────────────────────────────
    _section(3, 3, "Harness ARN")

    harness_arn = os.environ.get("HARNESS_ARN", "")
    is_placeholder = not harness_arn or "ACCOUNT_ID" in harness_arn

    if harness_arn and not is_placeholder:
        _ok(f"HARNESS_ARN 已配置: {harness_arn}")
        if Confirm.ask("  是否修改?", default=False):
            is_placeholder = True

    if is_placeholder:
        console.print("  [dim]请向 IT/运维索取 Harness ARN，格式如：[/dim]")
        console.print("  [dim]arn:aws:bedrock-agentcore:us-west-2:123456789012:harness/abc123[/dim]")
        harness_arn = Prompt.ask("  HARNESS_ARN")

    # 验证 Harness 可访问
    try:
        harness_id = harness_arn.split("/")[-1]
        control = session.client("bedrock-agentcore-control")
        detail = control.get_harness(harnessId=harness_id)
        status = detail.get("status", "UNKNOWN")
        if status == "READY":
            _ok(f"Harness 状态正常: {status}")
        else:
            _warn(f"Harness 状态: {status}（非 READY，可能仍在初始化）")
    except Exception as e:
        _err(f"无法访问 Harness: {e}")
        console.print("  请确认 ARN 正确且你的 AWS 账号有访问权限")
        if not Confirm.ask("  仍然保存此 ARN?", default=False):
            sys.exit(1)

    _save_env("HARNESS_ARN", harness_arn)
    os.environ["HARNESS_ARN"] = harness_arn

    # ── 完成 ──────────────────────────────────────────────────────────────
    console.print(Panel(
        "[bold green]🎉 配置完成！[/bold green]\n\n"
        f"配置文件: [cyan]{ENV_FILE}[/cyan]\n"
        "运行 [bold]uv run hare[/bold] 开始使用\n"
        "随时可通过 [bold]uv run hare --setup[/bold] 重新配置",
        border_style="green",
        padding=(1, 4),
    ))


def needs_onboarding() -> bool:
    """检测是否需要 onboarding（HARNESS_ARN 未配置或为模板值）。"""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)
    arn = os.environ.get("HARNESS_ARN", "")
    return not arn or "ACCOUNT_ID" in arn
