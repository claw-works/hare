# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import asyncio
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion, AutoSuggestFromHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import HTML

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.markdown import Markdown

from hare.harness import invoke_with_tool_loop
from hare.session import get_manager
from hare.persona import ensure_defaults, get_active_persona_name, get_persona, list_personas, set_active_persona
from hare.tools.acp import ensure_acp_config
from hare.tui.session_picker import pick_or_create_session, _find_key
from hare.mcp_client import get_mcp_manager

AUTO_SUMMARIZE_AT = 3

console = Console()


COMMANDS = [
    ("/quit",    "退出 Hare"),
    ("/clear",   "清空当前会话"),
    ("/cos",     "切换人设 / 列出可用人格"),
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
                    return Suggestion(cmd[len(text):])
            return None
        return self._history_suggest.get_suggestion(buffer, document)


def _banner(session_name: str, session_id: str) -> None:
    persona = get_persona()
    emoji = persona.get("emoji", "🐇")
    name = persona.get("name", "Hare")
    console.print(Panel(
        f"[bold green]{emoji} {name}[/bold green]  [dim]{session_name}[/dim]\n"
        f"[dim]session: {session_id[:8]}...  |  "
        "Ctrl+C 清除输入  |  /cos 切换人设  |  /quit 退出  |  /session 切换会话[/dim]",
        border_style="green",
    ))


def _tool_line(name: str) -> None:
    console.print(f"[bold yellow]  🔧 调用工具:[/bold yellow] [yellow]{name}[/yellow]...")


def _tool_done(name: str, ok: bool) -> None:
    icon = "✅" if ok else "❌"
    console.print(f"[dim]  {icon} {name} 完成[/dim]")


def _print_stats(stats: dict) -> None:
    """在回复结束后显示本轮统计摘要。"""
    elapsed = stats.get("elapsed", 0)
    input_tokens = stats.get("input_tokens", 0)
    output_tokens = stats.get("output_tokens", 0)
    tools = stats.get("tools", [])

    parts = []

    # 耗时
    if elapsed >= 60:
        parts.append(f"{elapsed:.0f}s")
    else:
        parts.append(f"{elapsed:.1f}s")

    # Token
    if input_tokens or output_tokens:
        parts.append(f"↑{input_tokens} ↓{output_tokens} tokens")

    # 工具摘要
    if tools:
        tool_names = [t["name"].split("__")[-1] if "__" in t["name"] else t["name"] for t in tools]
        # 去重计数
        from collections import Counter
        counts = Counter(tool_names)
        tool_parts = []
        for name, count in counts.items():
            tool_parts.append(f"{name}×{count}" if count > 1 else name)
        parts.append("tools: " + ", ".join(tool_parts))

    if parts:
        console.print(f"\n[dim]  {'  |  '.join(parts)}[/dim]")


async def _auto_summarize(session_key: str, session_id: str, manager) -> None:
    """后台自动生成会话标题和摘要。"""
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _sync_generate_summary, session_id
        )
        if result:
            manager.update_summary(session_key, result.get("title", ""), result.get("summary", ""))
    except Exception:
        pass


def _sync_generate_summary(session_id: str) -> dict[str, str] | None:
    """同步版 generate_summary，用于 run_in_executor。"""
    import json
    import os
    import boto3

    try:
        from hare.summarize import SUMMARIZE_PROMPT
        session = boto3.Session(
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
            profile_name=os.environ.get("AWS_PROFILE"),
        )
        client = session.client("bedrock-agentcore")
        harness_arn = os.environ["HARNESS_ARN"]

        response = client.invoke_harness(
            harnessArn=harness_arn,
            runtimeSessionId=session_id,
            messages=[{"role": "user", "content": [{"text": SUMMARIZE_PROMPT}]}],
            systemPrompt=[{"text": "你是一个会话摘要助手。只输出 JSON，不要输出其他内容。"}],
            tools=[],
        )

        full_text = ""
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    full_text += delta["text"]

        full_text = full_text.strip()
        if full_text.startswith("```"):
            lines = full_text.split("\n")
            full_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        return json.loads(full_text)
    except Exception:
        return None


async def _stream_response(session_id: str, message: str, actor_id: str | None = None) -> None:
    """流式输出 Harness 回复，历史由服务端 Memory 托管。"""
    full_text = ""
    first_token = False

    waiting_live = Live(
        Spinner("dots", text=" [dim]🐇 思考中...[/dim]"),
        console=console,
        refresh_per_second=10,
        transient=True,
    )
    waiting_live.start()
    response_live: Live | None = None

    try:
        async for event in invoke_with_tool_loop(session_id, message, actor_id=actor_id):
            if event["type"] == "text":
                if not first_token:
                    waiting_live.stop()
                    first_token = True
                    response_live = Live(
                        console=console,
                        refresh_per_second=15,
                        vertical_overflow="visible",
                    )
                    response_live.start()
                full_text += event["content"]
                if response_live:
                    _persona = get_persona()
                    _title = f"[bold green]{_persona.get('emoji', '🐇')} {_persona.get('name', 'Hare')}[/bold green]"
                    response_live.update(
                        Panel(Markdown(full_text),
                              title=_title,
                              border_style="green",
                              padding=(0, 1))
                    )

            elif event["type"] == "tool_call":
                if not first_token:
                    waiting_live.stop()
                    first_token = True
                if response_live:
                    response_live.stop()
                    response_live = None
                _tool_line(event["name"])

            elif event["type"] == "server_tool_call":
                if not first_token:
                    waiting_live.stop()
                    first_token = True
                if response_live:
                    response_live.stop()
                    response_live = None
                console.print(f"[bold cyan]  ⚡ 服务端执行:[/bold cyan] [cyan]{event['name']}[/cyan]...")
                first_token = False
                waiting_live = Live(
                    Spinner("dots", text=f" [dim]⚡ {event['name']} 执行中...[/dim]"),
                    console=console, refresh_per_second=10, transient=True,
                )
                waiting_live.start()

            elif event["type"] == "error":
                if not first_token:
                    waiting_live.stop()
                    first_token = True
                if response_live:
                    response_live.stop()
                    response_live = None
                console.print(f"[bold yellow]  ⚠ {event['message']}[/bold yellow]")
                # 重启 spinner 等待重试
                first_token = False
                waiting_live = Live(
                    Spinner("dots", text=" [dim]🐇 重试中...[/dim]"),
                    console=console, refresh_per_second=10, transient=True,
                )
                waiting_live.start()

            elif event["type"] == "tool_result":
                _tool_done(event["name"], "error" not in event["result"])
                if not first_token:
                    waiting_live.start()
                else:
                    first_token = False
                    waiting_live = Live(
                        Spinner("dots", text=" [dim]🐇 继续思考...[/dim]"),
                        console=console,
                        refresh_per_second=10,
                        transient=True,
                    )
                    waiting_live.start()

            elif event["type"] == "done":
                if not first_token:
                    waiting_live.stop()
                if response_live:
                    response_live.stop()
                    response_live = None
                # 显示统计
                stats = event.get("stats")
                if stats:
                    _print_stats(stats)
                break

    except Exception:
        waiting_live.stop()
        if response_live:
            response_live.stop()
        raise


async def run_chat() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    manager = get_manager()
    ensure_defaults()
    ensure_acp_config()

    await get_mcp_manager().initialize()

    session_key, session_entry = await pick_or_create_session()
    session_id = session_entry["id"]
    session_name = session_entry["name"]

    _banner(session_name, session_id)

    kb = KeyBindings()

    @kb.add(Keys.Escape)
    def _esc(event):
        buf = event.app.current_buffer
        if buf.text:
            buf.reset()

    @kb.add(Keys.ControlC)
    def _ctrl_c(event):
        buf = event.app.current_buffer
        if buf.text:
            buf.reset()
        else:
            event.app.exit(exception=EOFError())

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
            console.print("\n[dim]再见！[/dim]")
            break

        message = message.strip()
        if not message:
            sys.stdout.write("\x1b[1A\x1b[2K\x1b[1A\x1b[2K")
            sys.stdout.flush()
            continue

        # ── 内置指令 ──────────────────────────────────────────────────────

        if message in ("/quit", "/exit"):
            console.print("[dim]再见！[/dim]")
            break

        if message in ("/clear",):
            console.clear()
            new_name = f"会话 {datetime.now().strftime('%m/%d %H:%M')}"
            session_key, session_entry = manager.new_session(new_name)
            session_id = session_entry["id"]
            session_name = new_name
            _banner(session_name, session_id)
            continue

        if message in ("/session", "/sessions"):
            session_key, session_entry = await pick_or_create_session()
            session_id = session_entry["id"]
            session_name = session_entry["name"]
            _banner(session_name, session_id)
            continue

        if message.startswith("/session "):
            sub = message[9:].strip()
            if sub == "list":
                all_sessions = manager.list_sessions()
                for i, s in enumerate(all_sessions):
                    mark = " ◀ 当前" if _find_key(manager, s["id"]) == session_key else ""
                    console.print(f"  [dim]{i+1}.[/dim] [green]{s['name']}[/green]  "
                                  f"[dim]{s.get('updated_at','')[:10]}{mark}[/dim]")
                continue
            elif sub.startswith("new"):
                new_name = sub[3:].strip()
                session_key, session_entry = manager.new_session(new_name)
                session_id = session_entry["id"]
                session_name = session_entry["name"]
                console.print(f"  [green]✓ 新建会话：{session_name}[/green]")
                _banner(session_name, session_id)
                continue

        if message == "/cos":
            # 列出所有人格供选择
            personas = list_personas()
            active = get_active_persona_name()
            console.print("\n  [bold]可用人格：[/bold]")
            for p in personas:
                file_name = p.get("_file", "")
                emoji = p.get("emoji", "")
                name = p.get("name", file_name)
                vibe = p.get("vibe", "")
                mark = " [green]◀ 当前[/green]" if file_name == active else ""
                console.print(f"    {emoji} [bold]{file_name}[/bold] — {name}，{vibe}{mark}")
            console.print(f"\n  [dim]使用 /cos <名称> 切换，如 /cos catgirl[/dim]\n")
            continue

        if message.startswith("/cos "):
            target = message[5:].strip()
            if set_active_persona(target):
                persona = get_persona(target)
                emoji = persona.get("emoji", "")
                name = persona.get("name", target)
                console.print(f"  [green]✓ 已切换人设：{emoji} {name}[/green]")
                _banner(session_name, session_id)
            else:
                console.print(f"  [red]✗ 未找到人格 \"{target}\"[/red]")
                console.print(f"  [dim]可用人格：{', '.join(p.get('_file', '') for p in list_personas())}[/dim]")
            continue

        # ── 正常对话 ──────────────────────────────────────────────────────
        try:
            await _stream_response(session_id, message)
        except KeyboardInterrupt:
            console.print("\n[dim]（中断）[/dim]")
            continue
        except Exception as e:
            console.print(f"\n[bold red]错误:[/bold red] {e}")
            continue

        # 更新轮数，到达阈值时自动生成摘要
        turns = manager.increment_turns(session_key)
        if turns == AUTO_SUMMARIZE_AT:
            asyncio.ensure_future(_auto_summarize(session_key, session_id, manager))


def main() -> None:
    asyncio.run(run_chat())
