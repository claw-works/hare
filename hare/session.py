"""Session 管理模块 — 持久化多会话元数据。

存储格式 (~/.hare/sessions.json):
{
  "sessions": {
    "<uuid>": {
      "id": "huuid...",
      "name": "默认会话",
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
            # 迁移旧格式：{"default": "h..."} → 新格式 {"sessions": {}, "last_active": null}
            if "sessions" not in data:
                # 旧格式，直接丢弃，返回空结构（旧的 session_id 在服务端已有历史，不可复用）
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
    """多 session 管理器，持久化到 ~/.hare/sessions.json。"""

    def __init__(self) -> None:
        self._store = _load_store()

    # ── 查询 ──────────────────────────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """返回所有 session 列表，按 updated_at 倒序。"""
        sessions = list(self._store["sessions"].values())
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions

    def get_session(self, key: str) -> dict | None:
        """按 uuid key 获取 session。"""
        return self._store["sessions"].get(key)

    @property
    def last_active_key(self) -> str | None:
        return self._store.get("last_active")

    # ── 创建 / 切换 ────────────────────────────────────────────────────────

    def new_session(self, name: str = "") -> tuple[str, dict]:
        """新建 session，返回 (key, session_dict)。"""
        key = str(uuid.uuid4())
        session_id = _new_session_id()
        name = name.strip() or f"会话 {len(self._store['sessions']) + 1}"
        entry = {
            "id": session_id,
            "name": name,
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
        """激活指定 session（设为 last_active），返回 session_dict。"""
        session = self._store["sessions"].get(key)
        if session:
            self._store["last_active"] = key
            _save_store(self._store)
        return session

    # ── 删除 / 重命名 ──────────────────────────────────────────────────────

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
        """增加对话轮数，返回新的轮数。"""
        if key in self._store["sessions"]:
            session = self._store["sessions"][key]
            session["turns"] = session.get("turns", 0) + 1
            session["updated_at"] = _now()
            _save_store(self._store)
            return session["turns"]
        return 0

    def update_summary(self, key: str, title: str, summary: str) -> None:
        """更新会话标题和摘要。"""
        if key in self._store["sessions"]:
            session = self._store["sessions"][key]
            if title.strip():
                session["name"] = title.strip()
            if summary.strip():
                session["summary"] = summary.strip()
            session["updated_at"] = _now()
            _save_store(self._store)

    # ── 兼容旧接口 ──────────────────────────────────────────────────────────

    def get_or_create_default(self) -> tuple[str, dict]:
        """获取最近使用的 session，若无则新建。"""
        key = self._store.get("last_active")
        if key and key in self._store["sessions"]:
            return key, self._store["sessions"][key]
        return self.new_session("默认会话")


# 模块级单例
_manager: SessionManager | None = None


def get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


# ── 兼容旧接口 ────────────────────────────────────────────────────────────

def new_session(name: str) -> str:
    _, entry = get_manager().new_session(name)
    return entry["id"]


def get_or_create_session(name: str) -> str:
    _, entry = get_manager().get_or_create_default()
    return entry["id"]
