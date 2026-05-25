# -*- coding: utf-8 -*-
"""人设系统 — identity / soul / companion / personas 管理。

存储结构 (~/.hare/):
├── identity.yaml       # 当前激活的身份
├── soul.yaml           # 行为灵魂（跨人格不变）
├── companion.yaml      # 人类同伴信息
└── personas/           # 预设角色库
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


# ── 初始化默认文件 ─────────────────────────────────────────────────────────

DEFAULT_SOUL = {
    "core": [
        "直接帮忙，不要废话",
        "有自己的判断，可以表达不同意见",
        "先自己找答案，再问人",
        "尊重被赋予的信任和访问权",
    ],
    "boundaries": [
        "私密信息不外泄",
        "对外操作先确认",
    ],
    "language": "中文为主，技术术语用英文",
    "continuity": "文件即记忆，每次醒来从这里开始",
}

DEFAULT_PERSONA = {
    "name": "Hare",
    "creature": "兔系 AI 助手",
    "vibe": "安静可靠，话不多但管用",
    "emoji": "🐇",
    "tone": "简洁直接，偶尔幽默",
}

DEFAULT_COMPANION = {
    "name": "",
    "context": "",
    "preferences": [],
}


def ensure_defaults() -> None:
    """确保默认配置文件存在。"""
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


# ── 查询 ──────────────────────────────────────────────────────────────────

def get_active_persona_name() -> str:
    identity = _load_yaml(IDENTITY_FILE)
    return identity.get("active", "hare")


def get_persona(name: str | None = None) -> dict[str, Any]:
    """获取指定人格，默认为当前激活的。"""
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
    """列出所有可用人格，返回 [{name, ...persona_data}]。"""
    result = []
    if PERSONAS_DIR.exists():
        for f in sorted(PERSONAS_DIR.glob("*.yaml")):
            data = _load_yaml(f)
            data["_file"] = f.stem
            result.append(data)
    return result


# ── 切换 ──────────────────────────────────────────────────────────────────

def set_active_persona(name: str) -> bool:
    """切换当前人格。返回是否成功。"""
    path = PERSONAS_DIR / f"{name}.yaml"
    if not path.exists():
        return False
    identity = _load_yaml(IDENTITY_FILE)
    identity["active"] = name
    _save_yaml(IDENTITY_FILE, identity)
    return True


# ── 构建 System Prompt ────────────────────────────────────────────────────

def build_persona_prompt() -> str:
    """根据当前人设生成注入到 system prompt 的文本段落。"""
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

    parts.append(f"你是 {name} {emoji}，{creature}。")
    if vibe:
        parts.append(f"气质：{vibe}")
    if tone:
        parts.append(f"语气：{tone}")

    # Soul
    core = soul.get("core", [])
    if core:
        parts.append("\n行为准则：")
        for rule in core:
            parts.append(f"- {rule}")

    boundaries = soul.get("boundaries", [])
    if boundaries:
        parts.append("\n边界：")
        for b in boundaries:
            parts.append(f"- {b}")

    lang = soul.get("language")
    if lang:
        parts.append(f"\n语言：{lang}")

    # Companion
    comp_name = companion.get("name")
    if comp_name:
        comp_ctx = companion.get("context", "")
        parts.append(f"\n你的同伴是 {comp_name}。{comp_ctx}")
        prefs = companion.get("preferences", [])
        if prefs:
            parts.append("同伴偏好：")
            for p in prefs:
                parts.append(f"- {p}")

    return "\n".join(parts)
