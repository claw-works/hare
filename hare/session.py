"""Session management — persists multi-session metadata.

Storage format (~/.hare/sessions.json):
{
  "sessions": {
    "<uuid>": {
      "id": "huuid...",
      "name": "Default Session",
      "created_at": "2026-05-22T21:00:00",
      "updated_at": "2026-05-22T21:57:00"
    }
  },
  "last_active": "<uuid>"
}
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

SESSIONS_FILE = Path.home() / ".hare" / "sessions.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _load_store() -> dict:
    if SESSIONS_FILE.exists():
        try:
            data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
            # Migrate old format: {"default": "h..."} → new format {"sessions": {}, "last_active": null}
            if "sessions" not in data:
                # Old format, discard and return empty structure (old session_ids have server-side history, not reusable)
                return {"sessions": {}, "last_active": None}
            return data
        except Exception:
            pass
    return {"sessions": {}, "last_active": None}


def _save_store(store: dict) -> None:
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(
        json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _new_session_id() -> str:
    return "h" + uuid.uuid4().hex + uuid.uuid4().hex[:4]  # 37 chars


class SessionManager:
    """Multi-session manager, persisted to ~/.hare/sessions.json."""

    def __init__(self) -> None:
        self._store = _load_store()

    # ── Query ─────────────────────────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """Return all sessions, sorted by updated_at descending."""
        sessions = list(self._store["sessions"].values())
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions

    def get_session(self, key: str) -> dict | None:
        """Get session by uuid key."""
        return self._store["sessions"].get(key)

    @property
    def last_active_key(self) -> str | None:
        return self._store.get("last_active")

    # ── Create / Switch ─────────────────────────────────────────────────────

    def new_session(self, name: str = "", persona: str = "") -> tuple[str, dict]:
        """Create a new session, return (key, session_dict)."""
        from hare.persona import get_active_persona_name
        key = str(uuid.uuid4())
        session_id = _new_session_id()
        name = name.strip() or f"Session {len(self._store['sessions']) + 1}"
        entry = {
            "id": session_id,
            "name": name,
            "persona": persona or get_active_persona_name(),
            "summary": "",
            "turns": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._store["sessions"][key] = entry
        self._store["last_active"] = key
        _save_store(self._store)
        return key, entry

    def activate(self, key: str) -> dict | None:
        """Activate the given session (set as last_active) and restore its bound persona."""
        session = self._store["sessions"].get(key)
        if session:
            self._store["last_active"] = key
            _save_store(self._store)
            # Restore session-bound persona
            persona_name = session.get("persona")
            if persona_name:
                from hare.persona import set_active_persona
                set_active_persona(persona_name)
        return session

    # ── Delete / Rename ────────────────────────────────────────────────────

    def delete_session(self, key: str) -> bool:
        if key in self._store["sessions"]:
            del self._store["sessions"][key]
            if self._store.get("last_active") == key:
                sessions = self.list_sessions()
                self._store["last_active"] = sessions[0].get("_key") if sessions else None
            _save_store(self._store)
            return True
        return False

    def rename_session(self, key: str, new_name: str) -> bool:
        if key in self._store["sessions"] and new_name.strip():
            self._store["sessions"][key]["name"] = new_name.strip()
            self._store["sessions"][key]["updated_at"] = _now()
            _save_store(self._store)
            return True
        return False

    def increment_turns(self, key: str) -> int:
        """Increment turn count, return the new count."""
        if key in self._store["sessions"]:
            session = self._store["sessions"][key]
            session["turns"] = session.get("turns", 0) + 1
            session["updated_at"] = _now()
            _save_store(self._store)
            return session["turns"]
        return 0

    def update_summary(self, key: str, title: str, summary: str) -> None:
        """Update session title and summary."""
        if key in self._store["sessions"]:
            session = self._store["sessions"][key]
            if title.strip():
                session["name"] = title.strip()
            if summary.strip():
                session["summary"] = summary.strip()
            session["updated_at"] = _now()
            _save_store(self._store)

    # ── Legacy API ─────────────────────────────────────────────────────────

    def get_or_create_default(self) -> tuple[str, dict]:
        """Get the most recently used session, or create a new one."""
        key = self._store.get("last_active")
        if key and key in self._store["sessions"]:
            return key, self._store["sessions"][key]
        return self.new_session("Default Session")


# Module-level singleton
_manager: SessionManager | None = None


def get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


# ── Legacy API ────────────────────────────────────────────────────────────

def new_session(name: str) -> str:
    _, entry = get_manager().new_session(name)
    return entry["id"]


def get_or_create_session(name: str) -> str:
    _, entry = get_manager().get_or_create_default()
    return entry["id"]
