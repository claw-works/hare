# -*- coding: utf-8 -*-
"""Tool call auto-allow mechanism.
Supports allowlist config (with wildcards); tools not in the allowlist prompt user before execution.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

HARE_DIR = Path.home() / ".hare"
TOOLS_YAML = HARE_DIR / "tools.yaml"


def _load_auto_allow() -> list[str]:
    """Read auto_allow list from tools.yaml."""
    try:
        import yaml
        if TOOLS_YAML.exists():
            with open(TOOLS_YAML, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("auto_allow", [])
    except Exception:
        pass
    return []


def _save_auto_allow(patterns: list[str]) -> None:
    """Write auto_allow list back to tools.yaml."""
    try:
        import yaml
        cfg = {}
        if TOOLS_YAML.exists():
            with open(TOOLS_YAML, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        cfg["auto_allow"] = sorted(set(patterns))
        HARE_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOOLS_YAML, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    except Exception:
        pass


def is_allowed(tool_name: str) -> bool:
    """Check if tool is in the auto_allow list (supports wildcards)."""
    patterns = _load_auto_allow()
    return any(fnmatch.fnmatch(tool_name, p) for p in patterns)


# Session-level temporary allow list (valid for this run only, not persisted)
_session_allowed: set[str] = set()


def is_session_allowed(tool_name: str) -> bool:
    return tool_name in _session_allowed or any(
        fnmatch.fnmatch(tool_name, p) for p in _session_allowed
    )


def add_session_allow(pattern: str) -> None:
    _session_allowed.add(pattern)


def add_permanent_allow(pattern: str) -> None:
    patterns = _load_auto_allow()
    patterns.append(pattern)
    _save_auto_allow(patterns)
    _session_allowed.add(pattern)
