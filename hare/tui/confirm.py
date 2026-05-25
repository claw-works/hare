# -*- coding: utf-8 -*-
"""TUI 工具调用确认交互。

询问用户是否允许执行工具：
  y/Enter - 允许本次
  n       - 拒绝
  a       - 本次会话始终允许该工具
  A       - 永久写入白名单
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
    """询问用户是否允许执行工具。返回 True 表示允许。

    如果工具已在白名单或会话允许列表中，直接返回 True。
    """
    if is_allowed(tool_name) or is_session_allowed(tool_name):
        return True

    console.print(
        f"[bold yellow]  ⚠ 工具 [white]{tool_name}[/white] 请求执行[/bold yellow]"
    )
    console.print(f"[dim]    参数: {input_data}[/dim]")
    console.print(
        "[dim]    [y/Enter] 允许  [n] 拒绝  "
        "[a] 本次会话始终允许  [A] 永久加入白名单[/dim]"
    )

    session = PromptSession()
    try:
        answer = await session.prompt_async(
            HTML("    <ansiyellow><b>允许？</b></ansiyellow> "),
        )
    except (EOFError, KeyboardInterrupt):
        return False

    answer = answer.strip()

    if answer in ("", "y", "Y"):
        return True
    elif answer == "a":
        add_session_allow(tool_name)
        console.print(f"[dim]    ✓ 本次会话始终允许 {tool_name}[/dim]")
        return True
    elif answer == "A":
        add_permanent_allow(tool_name)
        console.print(f"[green]    ✓ 已将 {tool_name} 加入永久白名单[/green]")
        return True
    else:
        console.print("[dim]    ✗ 已拒绝[/dim]")
        return False
