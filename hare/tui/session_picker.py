# -*- coding: utf-8 -*-
"""Session 选择器 TUI — Rich + prompt_toolkit 实现。

使用方式：
    key, session = pick_or_create_session()
    # key: str (UUID), session: dict with id/name/messages/...
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Optional

from prompt_toolkit import PromptSession as PtSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from hare.session import get_manager, SessionManager

console = Console()


def _fmt_time(ts: str) -> str:
    """将 ISO 时间格式化为人类可读。"""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        now = datetime.now()
        delta = now - dt
        if delta.days == 0:
            if delta.seconds < 60:
                return "刚刚"
            if delta.seconds < 3600:
                return f"{delta.seconds // 60} 分钟前"
            return f"{delta.seconds // 3600} 小时前"
        elif delta.days == 1:
            return "昨天"
        elif delta.days < 7:
            return f"{delta.days} 天前"
        else:
            return dt.strftime("%m/%d")
    except Exception:
        return ts


def _render_picker(manager: SessionManager, selected_idx: int = 0) -> None:
    """渲染 session 列表面板。"""
    console.clear()
    sessions = manager.list_sessions()
    last_key = manager.last_active_key

    # 标题
    console.print(Panel(
        "[bold green]🐇 Hare[/bold green]  [dim]选择一个会话继续，或新建会话[/dim]",
        border_style="green",
        padding=(0, 2),
    ))

    if not sessions:
        console.print("\n  [dim]暂无会话，按 [bold]N[/bold] 新建[/dim]\n")
    else:
        table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold dim",
            border_style="dim",
            padding=(0, 1),
            expand=False,
        )
        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("会话名称", min_width=20)
        table.add_column("对话轮数", justify="right", width=8)
        table.add_column("最近更新", width=10)
        table.add_column("", width=4)  # 标记列

        for i, s in enumerate(sessions):
            # 找到该 session 的 key
            key = _find_key(manager, s["id"])
            num = str(i + 1)
            name = s.get("name", "未命名")
            # messages 里 role=user 的数量 = 对话轮数
            turns = sum(1 for m in s.get("messages", []) if m.get("role") == "user")
            updated = _fmt_time(s.get("updated_at", ""))

            # 标记最近使用
            mark = ""
            if key == last_key:
                mark = "[green]◀ 上次[/green]"

            if i == selected_idx:
                row_style = "bold green on dark_green"
                name_text = f"▶ {name}"
            else:
                row_style = ""
                name_text = f"  {name}"

            table.add_row(num, name_text, str(turns), updated, mark, style=row_style)

        console.print(table)

    # 操作提示
    console.print(
        "\n  [dim]"
        "[bold white]数字键[/bold white] 选择  "
        "[bold white]N[/bold white] 新建  "
        "[bold white]D[/bold white] 删除  "
        "[bold white]R[/bold white] 重命名  "
        "[bold white]Enter[/bold white] 进入上次会话  "
        "[bold white]Q[/bold white] 退出"
        "[/dim]\n"
    )


def _find_key(manager: SessionManager, session_id: str) -> str | None:
    """通过 session_id 找到对应的 UUID key。"""
    for k, v in manager._store["sessions"].items():
        if v["id"] == session_id:
            return k
    return None


async def pick_or_create_session() -> tuple[str, dict]:
    """
    显示 session 选择器，返回 (key, session_dict)。
    key: UUID str（用于 SessionManager 索引）
    session_dict: 含 id/name/messages/...
    """
    manager = get_manager()
    sessions = manager.list_sessions()

    # 如果完全没有 session，直接新建一个默认的
    if not sessions:
        console.print("\n  [dim]首次启动，自动创建默认会话...[/dim]")
        key, session = manager.new_session("默认会话")
        return key, session

    pt = PtSession()
    selected_idx = 0
    sessions = manager.list_sessions()  # 按 updated_at 倒序

    while True:
        _render_picker(manager, selected_idx)
        sessions = manager.list_sessions()  # 每次刷新

        try:
            raw = (await pt.prompt_async(HTML("  <ansigreen><b>操作</b></ansigreen> > "))).strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见！[/dim]")
            sys.exit(0)

        if not raw:
            # 直接回车 → 进入上次使用的 session
            key = manager.last_active_key
            if key and manager.get_session(key):
                session = manager.activate(key)
                console.clear()
                return key, session
            elif sessions:
                # fallback: 进入列表第一个
                first = sessions[0]
                key = _find_key(manager, first["id"])
                session = manager.activate(key)
                console.clear()
                return key, session

        elif raw == "q":
            console.print("\n[dim]再见！[/dim]")
            sys.exit(0)

        elif raw == "n":
            # 新建 session
            console.print()
            try:
                name_raw = (await pt.prompt_async(
                    HTML("  <ansigreen><b>会话名称</b></ansigreen> (留空自动命名) > ")
                )).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            key, session = manager.new_session(name_raw)
            console.clear()
            return key, session

        elif raw == "d":
            # 删除 session
            if not sessions:
                continue
            console.print()
            try:
                num_raw = (await pt.prompt_async(
                    HTML("  <ansired><b>删除</b></ansired> 输入序号 > ")
                )).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            try:
                idx = int(num_raw) - 1
                if 0 <= idx < len(sessions):
                    key_to_del = _find_key(manager, sessions[idx]["id"])
                    name_del = sessions[idx].get("name", "")
                    manager.delete_session(key_to_del)
                    console.print(f"  [dim]已删除：{name_del}[/dim]")
                    sessions = manager.list_sessions()
                    if not sessions:
                        key, session = manager.new_session("默认会话")
                        console.clear()
                        return key, session
            except ValueError:
                pass

        elif raw == "r":
            # 重命名
            if not sessions:
                continue
            console.print()
            try:
                num_raw = (await pt.prompt_async(
                    HTML("  <ansiyellow><b>重命名</b></ansiyellow> 输入序号 > ")
                )).strip()
                idx = int(num_raw) - 1
                if 0 <= idx < len(sessions):
                    new_name = (await pt.prompt_async(
                        HTML("  新名称 > ")
                    )).strip()
                    key_to_rename = _find_key(manager, sessions[idx]["id"])
                    manager.rename_session(key_to_rename, new_name)
            except (ValueError, EOFError, KeyboardInterrupt):
                pass

        else:
            # 数字选择
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(sessions):
                    selected = sessions[idx]
                    key = _find_key(manager, selected["id"])
                    session = manager.activate(key)
                    console.clear()
                    return key, session
            except ValueError:
                pass
