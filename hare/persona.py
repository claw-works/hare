# -*- coding: utf-8 -*-
"""Persona system — identity / soul / companion / personas management.

Storage structure (~/.hare/):
├── identity.yaml       # Currently active identity
├── soul.yaml           # Behavioral soul (invariant across personas)
├── companion.yaml      # Human companion info
└── personas/           # Preset persona library
    ├── hare.yaml
    └── ...
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

HARE_DIR = Path.home() / ".hare"
PERSONAS_DIR = HARE_DIR / "personas"
IDENTITY_FILE = HARE_DIR / "identity.yaml"
SOUL_FILE = HARE_DIR / "soul.yaml"
COMPANION_FILE = HARE_DIR / "companion.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


# ── Initialize default files ──────────────────────────────────────────────

DEFAULT_SOUL = {
    "core": [
        "Help directly, no fluff",
        "Have your own judgment, express differing opinions",
        "Find answers yourself first, then ask",
        "Respect the trust and access granted to you",
    ],
    "boundaries": [
        "Never leak private information",
        "Confirm before external operations",
    ],
    "language": "English primarily, technical terms as-is",
    "continuity": "Files are memory, start from here each time you wake",
}

DEFAULT_PERSONA = {
    "name": "Hare",
    "creature": "Rabbit-style AI assistant",
    "vibe": "Quiet and reliable, few words but effective",
    "emoji": "🐇",
    "tone": "Concise and direct, occasionally humorous",
}

DEFAULT_COMPANION = {
    "name": "",
    "context": "",
    "preferences": [],
}


def ensure_defaults() -> None:
    """Ensure default config files exist."""
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)

    if not SOUL_FILE.exists():
        _save_yaml(SOUL_FILE, DEFAULT_SOUL)

    default_persona_file = PERSONAS_DIR / "hare.yaml"
    if not default_persona_file.exists():
        _save_yaml(default_persona_file, DEFAULT_PERSONA)

    if not IDENTITY_FILE.exists():
        _save_yaml(IDENTITY_FILE, {"active": "hare"})

    if not COMPANION_FILE.exists():
        _save_yaml(COMPANION_FILE, DEFAULT_COMPANION)


# ── Query ─────────────────────────────────────────────────────────────────

def get_active_persona_name() -> str:
    identity = _load_yaml(IDENTITY_FILE)
    return identity.get("active", "hare")


def get_persona(name: str | None = None) -> dict[str, Any]:
    """Get the specified persona, defaults to the currently active one."""
    if name is None:
        name = get_active_persona_name()
    path = PERSONAS_DIR / f"{name}.yaml"
    if path.exists():
        return _load_yaml(path)
    return DEFAULT_PERSONA


def get_soul() -> dict[str, Any]:
    return _load_yaml(SOUL_FILE)


def get_companion() -> dict[str, Any]:
    return _load_yaml(COMPANION_FILE)


def list_personas() -> list[dict[str, Any]]:
    """List all available personas, returns [{name, ...persona_data}]."""
    result = []
    if PERSONAS_DIR.exists():
        for f in sorted(PERSONAS_DIR.glob("*.yaml")):
            data = _load_yaml(f)
            data["_file"] = f.stem
            result.append(data)
    return result


# ── Switch ────────────────────────────────────────────────────────────────

def set_active_persona(name: str) -> bool:
    """Switch the active persona. Returns success."""
    path = PERSONAS_DIR / f"{name}.yaml"
    if not path.exists():
        return False
    identity = _load_yaml(IDENTITY_FILE)
    identity["active"] = name
    _save_yaml(IDENTITY_FILE, identity)
    return True


# ── Build System Prompt ───────────────────────────────────────────────────

def build_persona_prompt() -> str:
    """Generate the system prompt text segment based on the active persona."""
    persona = get_persona()
    soul = get_soul()
    companion = get_companion()

    parts = []

    # Identity
    name = persona.get("name", "Hare")
    emoji = persona.get("emoji", "🐇")
    creature = persona.get("creature", "")
    vibe = persona.get("vibe", "")
    tone = persona.get("tone", "")

    parts.append(f"You are {name} {emoji}, {creature}.")
    if vibe:
        parts.append(f"Vibe: {vibe}")
    if tone:
        parts.append(f"Tone: {tone}")

    # Soul
    core = soul.get("core", [])
    if core:
        parts.append("\nBehavioral principles:")
        for rule in core:
            parts.append(f"- {rule}")

    boundaries = soul.get("boundaries", [])
    if boundaries:
        parts.append("\nBoundaries:")
        for b in boundaries:
            parts.append(f"- {b}")

    lang = soul.get("language")
    if lang:
        parts.append(f"\nLanguage: {lang}")

    # Companion
    comp_name = companion.get("name")
    if comp_name:
        comp_ctx = companion.get("context", "")
        parts.append(f"\nYour companion is {comp_name}. {comp_ctx}")
        prefs = companion.get("preferences", [])
        if prefs:
            parts.append("Companion preferences:")
            for p in prefs:
                parts.append(f"- {p}")

    return "\n".join(parts)
