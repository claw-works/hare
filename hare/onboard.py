# -*- coding: utf-8 -*-
"""hare onboarding — guide users through initial configuration.
User-facing only; ops tasks (IAM/Harness/Memory creation) are handled via scripts/.
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
    """Run user onboarding flow."""
    console.print(Panel(
        "[bold green]🐇 hare setup wizard[/bold green]\n"
        "[dim]Guides you through initial configuration, takes 1-2 minutes\n"
        "Harness ARN and Memory are pre-deployed by IT/ops — ask them for the values[/dim]",
        border_style="green",
        padding=(1, 4),
    ))

    HARE_DIR.mkdir(parents=True, exist_ok=True)
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)

    # ── Step 1: AWS Region & Profile ─────────────────────────────────────
    _section(1, 3, "AWS Credentials")

    region = os.environ.get("AWS_REGION", "")
    if region:
        _ok(f"AWS_REGION configured: {region}")
        if Confirm.ask("  Change?", default=False):
            region = ""
    if not region:
        region = Prompt.ask("  AWS Region", default="us-west-2")
        _save_env("AWS_REGION", region)
        os.environ["AWS_REGION"] = region

    profile = os.environ.get("AWS_PROFILE", "")
    if profile:
        _ok(f"AWS_PROFILE configured: {profile}")
        if Confirm.ask("  Change?", default=False):
            profile = ""
    if not profile:
        profile = Prompt.ask("  AWS Profile", default="default")
        _save_env("AWS_PROFILE", profile)
        os.environ["AWS_PROFILE"] = profile

    # ── Step 2: Verify AWS Credentials ────────────────────────────────────
    _section(2, 3, "Verify AWS Credentials")

    try:
        session = boto3.Session(region_name=region, profile_name=profile)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        _ok(f"Credentials valid — Account: {identity['Account']}, User: {identity['Arn'].split('/')[-1]}")
    except Exception as e:
        _err(f"Invalid AWS credentials: {e}")
        console.print("  Check the profile config in ~/.aws/credentials")
        console.print("  Then re-run: [bold]uv run hare --setup[/bold]")
        sys.exit(1)

    # ── Step 3: HARNESS_ARN ───────────────────────────────────────────────
    _section(3, 3, "Harness ARN")

    harness_arn = os.environ.get("HARNESS_ARN", "")
    is_placeholder = not harness_arn or "ACCOUNT_ID" in harness_arn

    if harness_arn and not is_placeholder:
        _ok(f"HARNESS_ARN configured: {harness_arn}")
        if Confirm.ask("  Change?", default=False):
            is_placeholder = True

    if is_placeholder:
        console.print("  [dim]Get the Harness ARN from IT/ops, format:[/dim]")
        console.print("  [dim]arn:aws:bedrock-agentcore:us-west-2:123456789012:harness/abc123[/dim]")
        harness_arn = Prompt.ask("  HARNESS_ARN")

    # Verify Harness is accessible
    try:
        harness_id = harness_arn.split("/")[-1]
        control = session.client("bedrock-agentcore-control")
        detail = control.get_harness(harnessId=harness_id)
        status = detail.get("status", "UNKNOWN")
        if status == "READY":
            _ok(f"Harness status OK: {status}")
        else:
            _warn(f"Harness status: {status} (not READY, may still be initializing)")
    except Exception as e:
        _err(f"Cannot access Harness: {e}")
        console.print("  Confirm the ARN is correct and your AWS account has access")
        if not Confirm.ask("  Save this ARN anyway?", default=False):
            sys.exit(1)

    _save_env("HARNESS_ARN", harness_arn)
    os.environ["HARNESS_ARN"] = harness_arn

    # ── Done ──────────────────────────────────────────────────────────────
    console.print(Panel(
        "[bold green]🎉 Setup complete![/bold green]\n\n"
        f"Config file: [cyan]{ENV_FILE}[/cyan]\n"
        "Run [bold]uv run hare[/bold] to get started\n"
        "Re-run [bold]uv run hare --setup[/bold] anytime to reconfigure",
        border_style="green",
        padding=(1, 4),
    ))


def needs_onboarding() -> bool:
    """Check if onboarding is needed (HARNESS_ARN not configured or is a placeholder)."""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)
    arn = os.environ.get("HARNESS_ARN", "")
    return not arn or "ACCOUNT_ID" in arn
