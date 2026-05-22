# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import sys
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion, AutoSuggestFromHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import HTML

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner

from hare.harness import invoke_with_tool_loop, clear_session
from hare.session import get_manager
from hare.tui.session_picker import pick_or_create_session, _find_key

console = Console()


COMMANDS = [
    ("/quit",    "退出 Hare"),
    ("/clear",   "清空当前会话"),
    ("/session", "切换 / 管理会话"),
    ("/session list", "列出所有会话"),
    ("/session new",  "新建会话"),
]

class CommandAutoSuggest(AutoSuggest):
    """/ 开头时 inline 联想第一个匹配命令，其他时候走历史联想。"""

    def __init__(self):
        self._history_suggest = AutoSuggestFromHistory()

    def get_suggestion(self, buffer, document):
        text = document.text_before_cursor
        if text.startswith("/"):
            for cmd, _ in COMMANDS:
                if cmd.startswith(text) and cmd != text:
                    # 返回还未输入的补全后缀
                    return Suggestion(cmd[len(text):])
            return None
        return self._history_suggest.get_suggestion(buffer, document)


def _banner(session_name: str, session_id: str) -> None:
    console.print(Panel(
        f"[bold green]🐇 Hare[/bold green]  [dim]{session_name}[/dim]\n"
        f"[dim]session: {session_id[:8]}...  |  "
        "Ctrl+C 退出  |  /clear 清屏  |  /quit 退出  |  /session 切换会话[/dim]",
        border_style="green",
    ))


def _tool_line(name: str) -> None:
    console.print(f"[bold yellow]  🔧 调用工具:[/bold yellow] [yellow]{name}[/yellow]...")


def _tool_done(name: str, ok: bool) -> None:
    icon = "✅" if ok else "❌"
    console.print(f"[dim]  {icon} {name} 完成[/dim]")


async def _stream_response(session_id: str, message: str, messages: list) -> None:
    """流式输出 Harness 回复，messages 由外部传入（持久化引用）。"""
    full_text = ""
    first_token = False

    spinner_live = Live(
        Spinner("dots", text=" [dim]🐇 思考中...[/dim]"),
        console=console,
        refresh_per_second=10,
        transient=True,
    )
    spinner_live.start()

    try:
        async for event in invoke_with_tool_loop(session_id, message, messages):
            if event["type"] == "text":
                if not first_token:
                    spinner_live.stop()
                    console.print("\n[bold green]🐇 Hare:[/bold green]", end=" ")
                    first_token = True
                console.print(event["content"], end="", highlight=False)

            elif event["type"] == "tool_call":
                if not first_token:
                    spinner_live.stop()
                    first_token = True
                _tool_line(event["name"])

            elif event["type"] == "tool_result":
                _tool_done(event["name"], "error" not in event["result"])
                if not first_token:
                    spinner_live.start()
                else:
                    first_token = False
                    spinner_live = Live(
                        Spinner("dots", text=" [dim]🐇 继续思考...[/dim]"),
                        console=console,
                        refresh_per_second=10,
                        transient=True,
                    )
                    spinner_live.start()

            elif event["type"] == "done":
                if not first_token:
                    spinner_live.stop()
                console.print()
                break

    except Exception:
        spinner_live.stop()
        raise


async def run_chat() -> None:
    # 强制 UTF-8（避免中文 UnicodeDecodeError，尤其是 Ghostty 终端）
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    manager = get_manager()

    # ── 启动时显示 session 选择器 ────────────────────────────────────────
    session_key, session_entry = await pick_or_create_session()
    session_id = session_entry["id"]
    session_name = session_entry["name"]
    messages = manager.get_messages(session_key)  # 引用，修改自动同步

    _banner(session_name, session_id)

    kb = KeyBindings()
    prompt_session = PromptSession(
        history=InMemoryHistory(),
        auto_suggest=CommandAutoSuggest(),
        mouse_support=False,
        key_bindings=kb,
        enable_history_search=True,
    )

    while True:
        try:
            with patch_stdout():
                message = await prompt_session.prompt_async(
                    HTML("\n<ansigreen><b>[你]</b></ansigreen> "),
                )
        except (EOFError, KeyboardInterrupt):
            manager.save_messages(session_key)
            console.print("\n[dim]再见！[/dim]")
            break

        message = message.strip()
        if not message:
            # 空回车：上移两行（提示行 + 换行）并清除，保持光标原位
            sys.stdout.write("\x1b[1A\x1b[2K\x1b[1A\x1b[2K")
            sys.stdout.flush()
            continue

        # ── 内置指令 ──────────────────────────────────────────────────────

        if message in ("/quit", "/exit"):
            manager.save_messages(session_key)
            console.print("[dim]再见！[/dim]")
            break

        if message in ("/clear",):
            console.clear()
            manager.clear_messages(session_key)
            # clear_messages 已生成新 session_id，需重新读
            session_id = manager.get_session(session_key)["id"]
            messages = manager.get_messages(session_key)
            _banner(session_name, session_id)
            continue

        if message in ("/session", "/sessions"):
            # 保存当前 session 历史，然后呼出选择器
            manager.save_messages(session_key)
            session_key, session_entry = await pick_or_create_session()
            session_id = session_entry["id"]
            session_name = session_entry["name"]
            messages = manager.get_messages(session_key)
            _banner(session_name, session_id)
            continue

        if message.startswith("/session "):
            # /session list  or  /session new <name>
            sub = message[9:].strip()
            if sub == "list":
                all_sessions = manager.list_sessions()
                for i, s in enumerate(all_sessions):
                    mark = " ◀ 当前" if _find_key(manager, s["id"]) == session_key else ""
                    turns = sum(1 for m in s.get("messages", []) if m.get("role") == "user")
                    console.print(f"  [dim]{i+1}.[/dim] [green]{s['name']}[/green]  "
                                  f"[dim]{turns}轮  {s.get('updated_at','')[:10]}{mark}[/dim]")
                continue
            elif sub.startswith("new"):
                new_name = sub[3:].strip()
                manager.save_messages(session_key)
                session_key, session_entry = manager.new_session(new_name)
                session_id = session_entry["id"]
                session_name = session_entry["name"]
                messages = manager.get_messages(session_key)
                console.print(f"  [green]✓ 新建会话：{session_name}[/green]")
                _banner(session_name, session_id)
                continue

        # ── 正常对话 ──────────────────────────────────────────────────────
        try:
            await _stream_response(session_id, message, messages)
            # 每轮回复后持久化历史
            manager.save_messages(session_key)
        except KeyboardInterrupt:
            console.print("\n[dim]（中断）[/dim]")
        except Exception as e:
            console.print(f"\n[bold red]错误:[/bold red] {e}")


def main() -> None:
    asyncio.run(run_chat())
