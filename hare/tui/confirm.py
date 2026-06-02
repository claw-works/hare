# -*- coding: utf-8 -*-
"""TUI tool call confirmation interaction.

Ask user whether to allow tool execution:
  y/Enter - Allow this time
  n       - Deny
  a       - Always allow this tool for current session
  A       - Permanently add to allowlist
"""
from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console

from hare.allow import (
    add_permanent_allow,
    add_session_allow,
    is_allowed,
    is_session_allowed,
)

console = Console()


async def confirm_tool_call(tool_name: str, input_data: dict) -> bool:
    """Ask user whether to allow tool execution. Returns True if allowed.

    If tool is already in the allowlist or session allow list, returns True directly.
    """
    if is_allowed(tool_name) or is_session_allowed(tool_name):
        return True

    console.print(
        f"[bold yellow]  ⚠ Tool [white]{tool_name}[/white] requests execution[/bold yellow]"
    )
    console.print(f"[dim]    Args: {input_data}[/dim]")
    console.print(
        "[dim]    [y/Enter] Allow  [n] Deny  "
        "[a] Always allow this session  [A] Add to permanent allowlist[/dim]"
    )

    session = PromptSession()
    try:
        answer = await session.prompt_async(
            HTML("    <ansiyellow><b>Allow?</b></ansiyellow> "),
        )
    except (EOFError, KeyboardInterrupt):
        return False

    answer = answer.strip()

    if answer in ("", "y", "Y"):
        return True
    elif answer == "a":
        add_session_allow(tool_name)
        console.print(f"[dim]    ✓ Always allowing {tool_name} this session[/dim]")
        return True
    elif answer == "A":
        add_permanent_allow(tool_name)
        console.print(f"[green]    ✓ Added {tool_name} to permanent allowlist[/green]")
        return True
    else:
        console.print("[dim]    ✗ Denied[/dim]")
        return False
