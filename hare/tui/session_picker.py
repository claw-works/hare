# -*- coding: utf-8 -*-
"""Session picker TUI — supports arrow key selection."""
from __future__ import annotations

import sys
from datetime import datetime

from prompt_toolkit import PromptSession as PtSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from hare.session import get_manager, SessionManager

console = Console()


def _fmt_time(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        now = datetime.now()
        delta = now - dt
        if delta.days == 0:
            if delta.seconds < 60:
                return "just now"
            if delta.seconds < 3600:
                return f"{delta.seconds // 60}m ago"
            return f"{delta.seconds // 3600}h ago"
        elif delta.days == 1:
            return "yesterday"
        elif delta.days < 7:
            return f"{delta.days}d ago"
        else:
            return dt.strftime("%m/%d")
    except Exception:
        return ts


MAX_DISPLAY = 20


def _render_picker(manager: SessionManager, selected_idx: int, sessions: list[dict], search_query: str = "") -> None:
    console.clear()
    last_key = manager.last_active_key
    total = len(manager.list_sessions())

    title_extra = f"  [dim italic]Search: \"{search_query}\" ({len(sessions)}/{total})[/dim italic]" if search_query else ""
    console.print(Panel(
        f"[bold green]🐇 Hare[/bold green]  [dim]Pick a session to continue, or create a new one[/dim]{title_extra}",
        border_style="green",
        padding=(0, 2),
    ))

    if not sessions:
        if search_query:
            console.print(f"\n  [dim]No sessions matching \"{search_query}\"[/dim]\n")
        else:
            console.print("\n  [dim]No sessions yet, press [bold]N[/bold] to create one[/dim]\n")
    else:
        table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold dim",
            border_style="dim",
            padding=(0, 1),
            expand=True,
        )
        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("Session", min_width=16)
        table.add_column("Summary", style="dim")
        table.add_column("Turns", justify="right", width=4)
        table.add_column("Updated", width=8)
        table.add_column("", width=4)

        for i, s in enumerate(sessions):
            key = _find_key(manager, s["id"])
            num = str(i + 1)
            name = s.get("name", "Untitled")
            summary = s.get("summary", "")
            turns = str(s.get("turns", 0))
            updated = _fmt_time(s.get("updated_at", ""))

            mark = ""
            if key == last_key:
                mark = "[green]◀[/green]"

            if i == selected_idx:
                row_style = "bold green on dark_green"
                name_text = f"▶ {name}"
            else:
                row_style = ""
                name_text = f"  {name}"

            # Truncate long summaries
            if len(summary) > 40:
                summary = summary[:38] + "…"

            table.add_row(num, name_text, summary, turns, updated, mark, style=row_style)

        console.print(table)

        if not search_query and total > MAX_DISPLAY:
            console.print(f"  [dim]Showing latest {MAX_DISPLAY} of {total}. Type / to search more.[/dim]")

    console.print(
        "\n  [dim]"
        "[bold white]↑↓[/bold white] Select  "
        "[bold white]Enter[/bold white] Confirm  "
        "[bold white]/[/bold white] Search  "
        "[bold white]N[/bold white] New  "
        "[bold white]D[/bold white] Delete  "
        "[bold white]R[/bold white] Rename  "
        "[bold white]Q[/bold white] Quit"
        "[/dim]\n"
    )


def _find_key(manager: SessionManager, session_id: str) -> str | None:
    for k, v in manager._store["sessions"].items():
        if v["id"] == session_id:
            return k
    return None


async def pick_or_create_session() -> tuple[str, dict]:
    manager = get_manager()
    sessions = manager.list_sessions()

    if not sessions:
        console.print("\n  [dim]First launch, creating default session...[/dim]")
        key, session = manager.new_session("Default Session")
        return key, session

    # Search state
    search_query = ""

    def _get_visible_sessions() -> list[dict]:
        all_sessions = manager.list_sessions()
        if search_query:
            q = search_query.lower()
            filtered = [s for s in all_sessions if q in s.get("name", "").lower() or q in s.get("summary", "").lower()]
            return filtered
        return all_sessions[:MAX_DISPLAY]

    sessions = _get_visible_sessions()

    # Find last active session index as default selection
    last_key = manager.last_active_key
    selected_idx = 0
    for i, s in enumerate(sessions):
        if _find_key(manager, s["id"]) == last_key:
            selected_idx = i
            break

    # Used to pass actions from key bindings
    action: dict = {"type": None}

    kb = KeyBindings()

    @kb.add(Keys.Up)
    def _up(event):
        action["type"] = "up"
        event.app.exit(result="")

    @kb.add(Keys.Down)
    def _down(event):
        action["type"] = "down"
        event.app.exit(result="")

    @kb.add(Keys.Enter)
    def _enter(event):
        buf = event.app.current_buffer
        if not buf.text.strip():
            action["type"] = "select"
        event.app.exit(result=buf.text)

    pt = PtSession(key_bindings=kb)

    while True:
        _render_picker(manager, selected_idx, sessions, search_query)

        try:
            raw = (await pt.prompt_async(HTML("  <ansigreen><b>Action</b></ansigreen> > "))).strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            sys.exit(0)

        # Handle key binding actions
        if action["type"] == "up":
            action["type"] = None
            selected_idx = (selected_idx - 1) % len(sessions) if sessions else 0
            continue
        elif action["type"] == "down":
            action["type"] = None
            selected_idx = (selected_idx + 1) % len(sessions) if sessions else 0
            continue
        elif action["type"] == "select":
            action["type"] = None
            if sessions:
                selected = sessions[selected_idx]
                key = _find_key(manager, selected["id"])
                session = manager.activate(key)
                console.clear()
                return key, session
            continue

        if not raw:
            # Enter (fallback when no key binding triggered)
            if sessions:
                selected = sessions[selected_idx]
                key = _find_key(manager, selected["id"])
                session = manager.activate(key)
                console.clear()
                return key, session

        elif raw == "/" or raw.startswith("/"):
            # Search mode
            query_input = raw[1:] if len(raw) > 1 else ""
            if not query_input:
                try:
                    query_input = (await pt.prompt_async(
                        HTML("  <ansicyan><b>Search</b></ansicyan> > ")
                    )).strip()
                except (EOFError, KeyboardInterrupt):
                    continue
            if query_input:
                search_query = query_input
            else:
                search_query = ""
            sessions = _get_visible_sessions()
            selected_idx = 0
            continue

        elif raw == "q":
            console.print("\n[dim]Goodbye![/dim]")
            sys.exit(0)

        elif raw == "n":
            console.print()
            try:
                name_raw = (await pt.prompt_async(
                    HTML("  <ansigreen><b>Session name</b></ansigreen> (leave empty for auto) > ")
                )).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            key, session = manager.new_session(name_raw)
            console.clear()
            return key, session

        elif raw == "d":
            if not sessions:
                continue
            console.print()
            try:
                num_raw = (await pt.prompt_async(
                    HTML("  <ansired><b>Delete</b></ansired> enter number > ")
                )).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            try:
                idx = int(num_raw) - 1
                if 0 <= idx < len(sessions):
                    key_to_del = _find_key(manager, sessions[idx]["id"])
                    name_del = sessions[idx].get("name", "")
                    manager.delete_session(key_to_del)
                    console.print(f"  [dim]Deleted: {name_del}[/dim]")
                    sessions = _get_visible_sessions()
                    if not sessions and not search_query:
                        key, session = manager.new_session("Default Session")
                        console.clear()
                        return key, session
                    selected_idx = min(selected_idx, max(0, len(sessions) - 1))
            except ValueError:
                pass

        elif raw == "r":
            if not sessions:
                continue
            console.print()
            try:
                num_raw = (await pt.prompt_async(
                    HTML("  <ansiyellow><b>Rename</b></ansiyellow> enter number > ")
                )).strip()
                idx = int(num_raw) - 1
                if 0 <= idx < len(sessions):
                    new_name = (await pt.prompt_async(
                        HTML("  New name > ")
                    )).strip()
                    key_to_rename = _find_key(manager, sessions[idx]["id"])
                    manager.rename_session(key_to_rename, new_name)
                    sessions = _get_visible_sessions()
            except (ValueError, EOFError, KeyboardInterrupt):
                pass

        else:
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
