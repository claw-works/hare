# -*- coding: utf-8 -*-
"""Hare TUI v2 — Textual 全屏界面。"""
from __future__ import annotations

import os
# 必须在 import textual 之前设置
# 禁用 kitty keyboard protocol（CJK IME 连续输入兼容）
os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")

import asyncio
import sys
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual import work
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Static, Label, OptionList, RichLog, TextArea
from textual.widgets import Markdown as MarkdownWidget
from textual.containers import VerticalScroll
from textual.widgets.option_list import Option
from textual.message import Message

from rich.markdown import Markdown, TableElement
from rich.text import Text
from rich import box

# Markdown 表格默认无竖线，patch 为带竖线的样式
_orig_table_rich_console = TableElement.__rich_console__

def _patched_table_rich_console(self, console, options):
    from rich.table import Table
    table = Table(
        box=box.ROUNDED,
        pad_edge=False,
        style="markdown.table.border",
        show_edge=True,
        collapse_padding=True,
    )
    if self.header is not None and self.header.row is not None:
        for column in self.header.row.cells:
            table.add_column(column.content)
    if self.body is not None:
        for row in self.body.rows:
            row_content = [cell.content for cell in row.cells]
            table.add_row(*row_content)
    yield table

TableElement.__rich_console__ = _patched_table_rich_console

from hare.harness import invoke_with_tool_loop
from hare.session import get_manager, _save_store
from hare.persona import (
    ensure_defaults, get_active_persona_name, get_persona,
    list_personas, set_active_persona, build_persona_prompt,
)
from hare.tools.acp import ensure_acp_config
from hare.mcp_client import get_mcp_manager


class SessionStats:
    """会话级别的累计统计。"""

    def __init__(self, session_key: str = None, manager=None):
        self._session_key = session_key
        self._manager = manager
        saved = {}
        if session_key and manager:
            s = manager.get_session(session_key) or {}
            saved = s.get("stats", {})
        self.total_input_tokens = saved.get("input_tokens", 0)
        self.total_output_tokens = saved.get("output_tokens", 0)
        self.total_turns = saved.get("turns", 0)
        self.total_tools = saved.get("tools", 0)
        self.last_input_tokens = 0
        self.last_output_tokens = 0

    def update(self, stats: dict) -> None:
        self.last_input_tokens = stats.get("input_tokens", 0)
        self.last_output_tokens = stats.get("output_tokens", 0)
        self.total_input_tokens += self.last_input_tokens
        self.total_output_tokens += self.last_output_tokens
        self.total_turns += 1
        self.total_tools += len(stats.get("tools", []))
        self._persist()

    def _persist(self) -> None:
        if self._session_key and self._manager:
            session = self._manager.get_session(self._session_key)
            if session:
                session["stats"] = {
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "turns": self.total_turns,
                    "tools": self.total_tools,
                }
                _save_store(self._manager._store)


# ── 自定义 Widgets ──────────────────────────────────────────────────────────


class StatusBar(Static):
    """底部状态条。"""

    def render(self) -> Text:
        app: HareApp = self.app
        _p = get_persona()
        emoji = _p.get("emoji", "🐇")
        name = _p.get("name", "Hare")
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]

        stats = app.session_stats
        total = f"Σ ↑{stats.total_input_tokens:,} ↓{stats.total_output_tokens:,}"
        last = ""
        if stats.last_input_tokens or stats.last_output_tokens:
            last = f"  (↑{stats.last_input_tokens:,} ↓{stats.last_output_tokens:,})"
        turns = f"{stats.total_turns} turns"
        session_name = app.session_name or ""

        text = Text()
        text.append(f" {emoji} ", style="bold")
        text.append(f"{name}", style="bold white")
        text.append(" │ ", style="dim")
        text.append(session_name, style="cyan")
        text.append(" │ ", style="dim")
        text.append(cwd, style="green")
        text.append(" │ ", style="dim")
        text.append(total, style="yellow")
        text.append(last, style="yellow dim")
        text.append(" │ ", style="dim")
        text.append(turns, style="white")
        text.append(" ")
        return text


SLASH_COMMANDS = [
    ("/cos", "切换人设"),
    ("/session", "切换会话"),
    ("/clear", "清屏 / 新建会话"),
    ("/quit", "退出"),
]


class CommandPalette(OptionList):
    """斜杠命令选择面板。"""

    DEFAULT_CSS = """
    CommandPalette {
        height: auto;
        max-height: 8;
        padding: 0;
        background: $boost;
        display: none;
        border: tall $accent;
    }
    """

    class CommandSelected(Message):
        def __init__(self, command: str):
            super().__init__()
            self.command = command

    def show_commands(self, prefix: str = "/") -> None:
        matches = [(cmd, desc) for cmd, desc in SLASH_COMMANDS if cmd.startswith(prefix)]
        if matches:
            self.clear_options()
            for cmd, desc in matches:
                self.add_option(Option(f" {cmd}  {desc}", id=cmd))
            self.highlighted = 0
            self.display = True
        else:
            self.display = False

    def hide(self) -> None:
        self.display = False

    def get_highlighted_command(self) -> str | None:
        """获取当前高亮的命令。"""
        if self.display and self.highlighted is not None and self.option_count > 0:
            option = self.get_option_at_index(self.highlighted)
            return option.id if option else None
        return None


class ChatInput(TextArea):
    """自定义输入框：Enter 发送，Shift+Enter 换行。"""

    BINDINGS = [
        Binding("enter", "submit", "发送", show=False),
    ]

    class Submitted(Message):
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    class TextChanged(Message):
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    async def action_submit(self) -> None:
        text = self.text.strip()
        if text:
            self.post_message(self.Submitted(text))
            self.text = ""

    _cmd_just_filled = False

    async def _on_key(self, event) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            # 如果命令面板可见且有高亮项，填入命令（只一次）
            if not self._cmd_just_filled:
                try:
                    palette = self.app.query_one("#cmd-palette", CommandPalette)
                    cmd = palette.get_highlighted_command()
                    if cmd:
                        self.text = cmd
                        palette.hide()
                        self._cmd_just_filled = True
                        return
                except Exception:
                    pass
            self._cmd_just_filled = False
            await self.action_submit()
        elif event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")
        elif event.key == "down" and self.text.strip().startswith("/"):
            # 命令面板里移动高亮
            try:
                palette = self.app.query_one("#cmd-palette", CommandPalette)
                if palette.display and palette.option_count > 0:
                    event.prevent_default()
                    event.stop()
                    idx = (palette.highlighted or 0) + 1
                    if idx >= palette.option_count:
                        idx = 0
                    palette.highlighted = idx
                    return
            except Exception:
                pass
            await super()._on_key(event)
        elif event.key == "up" and self.text.strip().startswith("/"):
            try:
                palette = self.app.query_one("#cmd-palette", CommandPalette)
                if palette.display and palette.option_count > 0:
                    event.prevent_default()
                    event.stop()
                    idx = (palette.highlighted or 0) - 1
                    if idx < 0:
                        idx = palette.option_count - 1
                    palette.highlighted = idx
                    return
            except Exception:
                pass
            await super()._on_key(event)
        elif event.key == "escape":
            try:
                palette = self.app.query_one("#cmd-palette", CommandPalette)
                if palette.display:
                    palette.hide()
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass
            await super()._on_key(event)
        else:
            await super()._on_key(event)
        # 通知文本变化
        self.post_message(self.TextChanged(self.text))


class ChatMessage(Static):
    """单条聊天消息。"""

    def __init__(self, content: str, role: str = "assistant", **kwargs):
        super().__init__(**kwargs)
        self._content = content
        self._role = role
        if role == "user":
            self.update(Text(content))
        else:
            self.update(Markdown(content))

    def set_content(self, content: str) -> None:
        self._content = content
        self.update(Markdown(content))


class ToolStatus(Static):
    """工具调用状态。"""

    def __init__(self, name: str, status: str = "running", **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self._status = status

    def render(self) -> Text:
        text = Text()
        if self._status == "running":
            text.append("  🔧 ", style="yellow")
            text.append(self._name, style="yellow")
            text.append("...", style="dim")
        elif self._status == "done":
            text.append("  ✅ ", style="green")
            text.append(self._name, style="dim")
        elif self._status == "server":
            text.append("  ⚡ ", style="cyan")
            text.append(self._name, style="cyan")
            text.append("...", style="dim")
        elif self._status == "error":
            text.append("  ❌ ", style="red")
            text.append(self._name, style="red")
        return text


# ── 主应用 ──────────────────────────────────────────────────────────────────


class HareApp(App):
    """Hare TUI v2 — Textual 全屏界面。"""

    TITLE = "Hare"
    CSS = """
    Screen {
        layout: vertical;
    }

    #chat-area {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }

    .user-msg {
        margin: 2 0 0 0;
        padding: 0 1;
        height: auto;
        color: $success;
        text-style: bold;
    }

    .assistant-md {
        margin: 0 0 1 2;
        padding: 0 1;
        height: auto;
    }

    .tool-msg {
        height: 1;
        margin: 0 0 0 2;
        padding: 0 1;
        color: $text-muted;
    }

    .system-msg {
        height: auto;
        margin: 0 0 0 2;
        padding: 0 1;
        color: $text-muted;
    }

    #input-area {
        height: auto;
        max-height: 10;
        dock: bottom;
        padding: 0 1;
    }

    .thinking-msg {
        height: 1;
        margin: 0 0 0 2;
        padding: 0 1;
        color: $success;
    }

    #user-input {
        height: auto;
        min-height: 2;
        max-height: 6;
        border: tall $accent;
    }

    #user-input:focus {
        border: tall $success;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出"),
        Binding("ctrl+l", "clear_chat", "清屏"),
        Binding("ctrl+p", "switch_persona", "切换人设"),
        Binding("ctrl+s", "switch_session", "切换会话"),
        Binding("ctrl+y", "copy_last", "拷贝最后回复"),
        Binding("ctrl+c", "copy_selection", "拷贝选中", show=False),
    ]

    ENABLE_COMMAND_PALETTE = False

    session_name = reactive("")
    is_thinking = reactive(False)

    def __init__(self):
        super().__init__()
        self.manager = get_manager()
        self.session_key = None
        self.session_id = None
        self.session_stats = SessionStats()
        self._current_response = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="chat-area")
        with Vertical(id="input-area"):
            yield CommandPalette(id="cmd-palette")
            yield ChatInput(id="user-input", language=None)

    async def on_mount(self) -> None:
        ensure_defaults()
        ensure_acp_config()
        await get_mcp_manager().initialize()

        # 选择或创建 session
        key, entry = self.manager.get_or_create_default()
        self._activate_session(key, entry)

        self.query_one("#chat-area", VerticalScroll).can_focus = False
        self.query_one("#user-input", ChatInput).focus()
        self._update_header()

    def _activate_session(self, key: str, entry: dict) -> None:
        self.session_key = key
        self.session_id = entry["id"]
        self.session_name = entry.get("name", "")
        self.session_stats = SessionStats(key, self.manager)
        self._update_header()
        self._refresh_status()

    def _update_header(self) -> None:
        _p = get_persona()
        emoji = _p.get("emoji", "🐇")
        name = _p.get("name", "Hare")
        self.title = f"{emoji} {name} │ {self.session_name}"

        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        stats = self.session_stats
        total = f"↑{stats.total_input_tokens:,} ↓{stats.total_output_tokens:,}"
        self.sub_title = f"{cwd} │ {total} │ {stats.total_turns} turns"

    def _refresh_status(self) -> None:
        self._update_header()

    _thinking_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _thinking_idx = 0
    _thinking_timer = None
    _thinking_widget: Static | None = None

    def watch_is_thinking(self, thinking: bool) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        if thinking:
            if self._thinking_widget is None:
                self._thinking_widget = Static("", classes="thinking-msg")
                chat.mount(self._thinking_widget)
            self._thinking_idx = 0
            self._update_thinking_text()
            chat.scroll_end(animate=False)
            self._thinking_timer = self.set_interval(0.08, self._animate_thinking)
        else:
            if self._thinking_timer:
                self._thinking_timer.stop()
                self._thinking_timer = None
            if self._thinking_widget:
                self._thinking_widget.remove()
                self._thinking_widget = None

    def _animate_thinking(self) -> None:
        self._thinking_idx = (self._thinking_idx + 1) % len(self._thinking_frames)
        self._update_thinking_text()

    def _update_thinking_text(self) -> None:
        if self._thinking_widget:
            _p = get_persona()
            emoji = _p.get("emoji", "🐇")
            name = _p.get("name", "Hare")
            frame = self._thinking_frames[self._thinking_idx]
            self._thinking_widget.update(f"  {frame} {emoji} {name} 思考中...")

    # ── 输入处理 ────────────────────────────────────────────────────────────


    def on_chat_input_text_changed(self, event: ChatInput.TextChanged) -> None:
        palette = self.query_one("#cmd-palette", CommandPalette)
        text = event.text.strip()
        if text.startswith("/") and "\n" not in text and len(text) < 12:
            palette.show_commands(text)
        else:
            palette.hide()

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        self.query_one("#cmd-palette", CommandPalette).hide()
        message = event.text
        user_input = self.query_one("#user-input", ChatInput)
        user_input.read_only = True

        # 命令处理
        if message.startswith("/"):
            handled = await self._handle_command(message)
            if handled:
                user_input.read_only = False
                user_input.focus()
                return

        # 显示用户消息
        chat = self.query_one("#chat-area", VerticalScroll)
        await chat.mount(Static(message, classes="user-msg"))
        chat.scroll_end(animate=False)

        # 启动后台流式响应
        self._stream_response(message)

    async def _handle_command(self, cmd: str) -> bool:
        if cmd in ("/quit", "/exit"):
            self.exit()
            return True

        if cmd in ("/clear",):
            await self.action_clear_chat()
            return True

        if cmd in ("/cos",):
            await self.action_switch_persona()
            return True

        if cmd in ("/session", "/sessions"):
            await self.action_switch_session()
            return True

        if cmd.startswith("/cos "):
            target = cmd[5:].strip()
            if set_active_persona(target):
                if self.session_key in self.manager._store["sessions"]:
                    self.manager._store["sessions"][self.session_key]["persona"] = target
                    _save_store(self.manager._store)
                self._update_header()
                self._add_system_msg(f"✓ 已切换人设: {get_persona().get('emoji','')} {get_persona().get('name','')}")
            else:
                self._add_system_msg(f"✗ 未找到人格 \"{target}\"")
            return True

        return False

    # ── 流式响应 ────────────────────────────────────────────────────────────

    @work(exclusive=True)
    async def _stream_response(self, message: str) -> None:
        self.is_thinking = True
        chat = self.query_one("#chat-area", VerticalScroll)
        full_text = ""
        md_widget: MarkdownWidget | None = None

        try:
            # invoke_with_tool_loop 内部用同步 boto3，逐事件 yield
            # 用 queue 把同步阻塞的事件流桥接到 async 世界
            import queue
            import threading

            event_queue: queue.Queue = queue.Queue()

            def _run_harness():
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    async def _collect():
                        async for ev in invoke_with_tool_loop(self.session_id, message):
                            event_queue.put(ev)
                        event_queue.put(None)
                    loop.run_until_complete(_collect())
                except Exception as e:
                    event_queue.put({"type": "error", "message": str(e)})
                    event_queue.put(None)
                finally:
                    loop.close()

            thread = threading.Thread(target=_run_harness, daemon=True)
            thread.start()

            while True:
                # Non-blocking poll with short sleep to keep UI responsive
                try:
                    event = event_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue

                if event is None:
                    break
                if event["type"] == "session_reset":
                    self.session_id = event["new_session_id"]
                    if self.session_key in self.manager._store["sessions"]:
                        self.manager._store["sessions"][self.session_key]["id"] = self.session_id
                        _save_store(self.manager._store)
                    continue

                elif event["type"] == "text":
                    self.is_thinking = False
                    full_text += event["content"]
                    if md_widget is None:
                        md_widget = MarkdownWidget("", classes="assistant-md")
                        await chat.mount(md_widget)
                    await md_widget.update(full_text)
                    chat.scroll_end(animate=False)

                elif event["type"] == "tool_call":
                    if md_widget:
                        md_widget = None
                        full_text = ""
                    self.is_thinking = False
                    await chat.mount(Static(f"  🔧 {event['name']}...", classes="tool-msg"))
                    chat.scroll_end(animate=False)

                elif event["type"] == "server_tool_call":
                    if md_widget:
                        md_widget = None
                        full_text = ""
                    self.is_thinking = False
                    await chat.mount(Static(f"  ⚡ {event['name']}...", classes="tool-msg"))
                    chat.scroll_end(animate=False)

                elif event["type"] == "tool_result":
                    ok = "error" not in event["result"]
                    icon = "✅" if ok else "❌"
                    await chat.mount(Static(f"  {icon} {event['name']}", classes="tool-msg"))
                    chat.scroll_end(animate=False)
                    self.is_thinking = True

                elif event["type"] == "error":
                    await chat.mount(Static(f"  ⚠ {event['message']}", classes="system-msg"))
                    chat.scroll_end(animate=False)
                    self.is_thinking = True

                elif event["type"] == "done":
                    if full_text:
                        self._current_response = full_text
                    stats = event.get("stats")
                    if stats:
                        self.session_stats.update(stats)
                        self._refresh_status()
                        elapsed = stats.get("elapsed", 0)
                        inp = stats.get("input_tokens", 0)
                        out = stats.get("output_tokens", 0)
                        await chat.mount(Static(
                            f"[dim]  {elapsed:.1f}s │ ↑{inp:,} ↓{out:,}[/dim]",
                            classes="system-msg", markup=True
                        ))
                        chat.scroll_end(animate=False)
                    current_persona = get_active_persona_name()
                    s = self.manager.get_session(self.session_key)
                    if s and s.get("persona") != current_persona:
                        s["persona"] = current_persona
                        _save_store(self.manager._store)
                    break

        except Exception as e:
            self._add_system_msg(f"错误: {e}")
        finally:
            self.is_thinking = False
            user_input = self.query_one("#user-input", ChatInput)
            user_input.read_only = False
            user_input.focus()

        # 更新轮数和自动摘要
        turns = self.manager.increment_turns(self.session_key)
        if turns == 3 or (turns > 3 and (turns % 5 == 0 or not (self.manager.get_session(self.session_key) or {}).get("summary"))):
            asyncio.create_task(self._auto_summarize())

    # ── Actions ─────────────────────────────────────────────────────────────

    async def action_clear_chat(self) -> None:
        new_name = f"会话 {datetime.now().strftime('%m/%d %H:%M')}"
        key, entry = self.manager.new_session(new_name)
        self._activate_session(key, entry)
        chat = self.query_one("#chat-area", VerticalScroll)
        await chat.remove_children()
        self._add_system_msg("已创建新会话")

    async def action_switch_persona(self) -> None:
        personas = list_personas()
        active = get_active_persona_name()
        self.push_screen(PersonaPickerScreen(personas, active))

    async def action_switch_session(self) -> None:
        sessions = self.manager.list_sessions()[:20]
        self.push_screen(SessionPickerScreen(sessions, self.manager))

    async def action_copy_selection(self) -> None:
        """拷贝当前选中的文本到剪贴板。"""
        chat = self.query_one("#chat-area", VerticalScroll)
        for widget in chat.query(MarkdownWidget):
            selection = widget.text_selection
            if selection:
                import subprocess
                try:
                    subprocess.run(["pbcopy"], input=selection.encode(), check=True)
                    self.notify("✓ 已拷贝  (退出: Ctrl+Q)", timeout=2)
                except Exception:
                    pass
                return
        # fallback: 拷贝最后回复
        await self.action_copy_last()

    async def action_copy_last(self) -> None:
        """拷贝最后一条 AI 回复到剪贴板。"""
        if self._current_response:
            import subprocess
            try:
                subprocess.run(["pbcopy"], input=self._current_response.encode(), check=True)
                self.notify("✓ 已拷贝最后回复  (退出: Ctrl+Q)", timeout=2)
            except Exception:
                self.notify("✗ 拷贝失败", severity="error", timeout=2)
        else:
            self.notify("没有可拷贝的回复", severity="warning", timeout=2)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _add_system_msg(self, text: str) -> None:
        chat = self.query_one("#chat-area", VerticalScroll)
        chat.mount(Static(f"[dim]  {text}[/dim]", classes="system-msg", markup=True))
        chat.scroll_end(animate=False)

    async def _auto_summarize(self) -> None:
        try:
            from hare.summarize import SUMMARIZE_PROMPT
            import boto3
            from dotenv import load_dotenv
            from pathlib import Path
            load_dotenv(Path.home() / ".hare" / ".env")

            session = boto3.Session(
                region_name=os.environ.get("AWS_REGION", "us-west-2"),
                profile_name=os.environ.get("AWS_PROFILE"),
            )
            client = session.client("bedrock-agentcore")
            harness_arn = os.environ["HARNESS_ARN"]

            response = client.invoke_harness(
                harnessArn=harness_arn,
                runtimeSessionId=self.session_id,
                messages=[{"role": "user", "content": [{"text": SUMMARIZE_PROMPT}]}],
                systemPrompt=[{"text": "你是一个会话摘要助手。只输出 JSON，不要输出其他内容。"}],
                tools=[],
            )

            import json
            full_text = ""
            for ev in response["stream"]:
                if "contentBlockDelta" in ev:
                    delta = ev["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        full_text += delta["text"]

            full_text = full_text.strip()
            if full_text.startswith("```"):
                lines = full_text.split("\n")
                full_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

            result = json.loads(full_text)
            if "title" in result and "summary" in result:
                self.manager.update_summary(self.session_key, result["title"], result["summary"])
                self.session_name = result["title"]
                self._update_header()
        except Exception:
            pass

    # ── Persona/Session picker callbacks ────────────────────────────────────

    def on_persona_selected(self, message: "PersonaSelected") -> None:
        target = message.persona_id
        if set_active_persona(target):
            if self.session_key in self.manager._store["sessions"]:
                self.manager._store["sessions"][self.session_key]["persona"] = target
                _save_store(self.manager._store)
            self._update_header()
            self._refresh_status()
            self._add_system_msg(f"✓ 已切换人设: {get_persona().get('emoji','')} {get_persona().get('name','')}")

    def on_session_selected(self, message: "SessionSelected") -> None:
        key = message.session_key
        entry = self.manager.activate(key)
        if entry:
            self._activate_session(key, entry)
            chat = self.query_one("#chat-area", VerticalScroll)
            chat.remove_children()
            self._add_system_msg(f"已切换到: {entry.get('name', '')}")


# ── Picker Screens ──────────────────────────────────────────────────────────


class PersonaSelected(Message):
    def __init__(self, persona_id: str):
        super().__init__()
        self.persona_id = persona_id


class SessionSelected(Message):
    def __init__(self, session_key: str):
        super().__init__()
        self.session_key = session_key


class PersonaPickerScreen(Screen):
    """人格选择 — 全屏通栏。"""

    CSS = """
    Screen {
        background: $surface;
    }
    #picker-title {
        text-align: center;
        padding: 1 0;
        text-style: bold;
        background: $boost;
    }
    OptionList {
        height: 1fr;
        margin: 1 2;
    }
    #picker-hint {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        dock: bottom;
    }
    """

    BINDINGS = [Binding("escape", "dismiss", "取消")]

    def __init__(self, personas: list[dict], active: str, **kwargs):
        super().__init__(**kwargs)
        self._personas = personas
        self._active = active

    def compose(self) -> ComposeResult:
        yield Label("✨ 选择人设  (↑↓ 选择, Enter 确认, Esc 取消)", id="picker-title")
        ol = OptionList()
        active_idx = 0
        for i, p in enumerate(self._personas):
            file_name = p.get("_file", "")
            emoji = p.get("emoji", "")
            name = p.get("name", file_name)
            vibe = p.get("vibe", "")
            mark = "  ◀ 当前" if file_name == self._active else ""
            if file_name == self._active:
                active_idx = i
            ol.add_option(Option(f"  {emoji}  {name} — {vibe}{mark}", id=file_name))
        ol.highlighted = active_idx
        yield ol

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.app.post_message(PersonaSelected(event.option.id))
        self.dismiss()

    def action_dismiss(self) -> None:
        self.dismiss()


class SessionPickerScreen(Screen):
    """会话选择 — 全屏通栏。"""

    CSS = """
    Screen {
        background: $surface;
    }
    #picker-title {
        text-align: center;
        padding: 1 0;
        text-style: bold;
        background: $boost;
    }
    OptionList {
        height: 1fr;
        margin: 1 2;
    }
    #picker-actions {
        height: 1;
        padding: 0 2;
        dock: bottom;
        background: $boost;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "取消"),
        Binding("n", "new_session", "新建"),
        Binding("d", "delete_session", "删除"),
    ]

    def __init__(self, sessions: list[dict], manager, **kwargs):
        super().__init__(**kwargs)
        self._sessions = sessions
        self._manager = manager

    def compose(self) -> ComposeResult:
        yield Label("📋 选择会话  (↑↓ 选择, Enter 确认, N 新建, D 删除, Esc 取消)", id="picker-title")
        ol = OptionList(id="session-list")
        self._rebuild_options(ol)
        yield ol
        yield Static("[bold]N[/bold] 新建  [bold]D[/bold] 删除  [bold]Esc[/bold] 取消", id="picker-actions", markup=True)

    def _rebuild_options(self, ol: OptionList | None = None) -> None:
        if ol is None:
            ol = self.query_one("#session-list", OptionList)
            ol.clear_options()
        last_key = self._manager.last_active_key
        active_idx = 0
        self._sessions = self._manager.list_sessions()[:20]
        for i, s in enumerate(self._sessions):
            name = s.get("name", "未命名")
            summary = s.get("summary", "")
            turns = s.get("turns", 0)
            key = None
            for k, v in self._manager._store["sessions"].items():
                if v["id"] == s["id"]:
                    key = k
                    break
            if key == last_key:
                active_idx = i
            mark = "  ◀ 当前" if key == last_key else ""
            label = f"  {name}  [{turns}轮]{mark}"
            if summary:
                label += f"\n    {summary[:50]}"
            ol.add_option(Option(label, id=key or s["id"]))
        ol.highlighted = active_idx

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.app.post_message(SessionSelected(event.option.id))
        self.dismiss()

    def action_new_session(self) -> None:
        from datetime import datetime
        new_name = f"会话 {datetime.now().strftime('%m/%d %H:%M')}"
        key, entry = self._manager.new_session(new_name)
        self.app.post_message(SessionSelected(key))
        self.dismiss()

    def action_delete_session(self) -> None:
        ol = self.query_one("#session-list", OptionList)
        if ol.highlighted is not None and len(self._sessions) > 0:
            idx = ol.highlighted
            if idx < len(self._sessions):
                s = self._sessions[idx]
                key = None
                for k, v in self._manager._store["sessions"].items():
                    if v["id"] == s["id"]:
                        key = k
                        break
                if key and key != self._manager.last_active_key:
                    self._manager.delete_session(key)
                    self._rebuild_options()
                else:
                    self.notify("不能删除当前会话", severity="warning", timeout=2)

    def action_dismiss(self) -> None:
        self.dismiss()


# ── Entry point ─────────────────────────────────────────────────────────────


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path.home() / ".hare" / ".env")

    app = HareApp()
    app.run()
