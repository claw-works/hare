# -*- coding: utf-8 -*-
"""人设管理工具 — 让 Hare 自己管理角色。"""
from __future__ import annotations

from pathlib import Path

import yaml

from hare.persona import PERSONAS_DIR, IDENTITY_FILE, get_active_persona_name, _load_yaml, _save_yaml


def manage_persona(
    action: str,
    name: str | None = None,
    data: dict | None = None,
) -> dict:
    """
    管理人设角色。

    action:
      - list: 列出所有可用人格
      - get: 获取指定人格详情
      - create: 创建新人格（name + data）
      - update: 更新已有人格（name + data，合并覆盖）
      - switch: 切换当前激活人格
      - delete: 删除人格（不能删除当前激活的）
    """
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)

    if action == "list":
        personas = []
        for f in sorted(PERSONAS_DIR.glob("*.yaml")):
            p = _load_yaml(f)
            p["_id"] = f.stem
            personas.append(p)
        active = get_active_persona_name()
        return {"personas": personas, "active": active}

    if action == "get":
        if not name:
            return {"error": "需要指定 name"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"人格 '{name}' 不存在"}
        return {"persona": _load_yaml(path)}

    if action == "create":
        if not name:
            return {"error": "需要指定 name"}
        if not data:
            return {"error": "需要指定 data（至少包含 name, emoji, vibe）"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if path.exists():
            return {"error": f"人格 '{name}' 已存在，使用 update 来修改"}
        _save_yaml(path, data)
        return {"success": True, "message": f"已创建人格 '{name}'", "persona": data}

    if action == "update":
        if not name:
            return {"error": "需要指定 name"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"人格 '{name}' 不存在"}
        existing = _load_yaml(path)
        if data:
            existing.update(data)
        _save_yaml(path, existing)
        return {"success": True, "message": f"已更新人格 '{name}'", "persona": existing}

    if action == "switch":
        if not name:
            return {"error": "需要指定 name"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"人格 '{name}' 不存在"}
        identity = _load_yaml(IDENTITY_FILE)
        identity["active"] = name
        _save_yaml(IDENTITY_FILE, identity)
        persona = _load_yaml(path)
        return {"success": True, "message": f"已切换到 '{name}'", "persona": persona}

    if action == "delete":
        if not name:
            return {"error": "需要指定 name"}
        if name == "hare":
            return {"error": "默认人格 'hare' 不可删除"}
        if name == get_active_persona_name():
            return {"error": f"不能删除当前激活的人格 '{name}'，请先切换"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"人格 '{name}' 不存在"}
        path.unlink()
        return {"success": True, "message": f"已删除人格 '{name}'"}

    return {"error": f"未知 action: '{action}'，可用: list/get/create/update/switch/delete"}
