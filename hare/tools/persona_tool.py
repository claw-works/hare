# -*- coding: utf-8 -*-
"""Persona management tool — lets Hare self-manage its roles."""
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
    Manage persona roles.

    action:
      - list: List all available personas
      - get: Get details of a specific persona
      - create: Create a new persona (name + data)
      - update: Update an existing persona (name + data, merge-override)
      - switch: Switch the currently active persona
      - delete: Delete a persona (cannot delete the currently active one)
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
            return {"error": "name is required"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"Persona '{name}' does not exist"}
        return {"persona": _load_yaml(path)}

    if action == "create":
        if not name:
            return {"error": "name is required"}
        if not data:
            return {"error": "data is required (must include at least name, emoji, vibe)"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if path.exists():
            return {"error": f"Persona '{name}' already exists, use update to modify"}
        _save_yaml(path, data)
        return {"success": True, "message": f"Created persona '{name}'", "persona": data}

    if action == "update":
        if not name:
            return {"error": "name is required"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"Persona '{name}' does not exist"}
        existing = _load_yaml(path)
        if data:
            existing.update(data)
        _save_yaml(path, existing)
        return {"success": True, "message": f"Updated persona '{name}'", "persona": existing}

    if action == "switch":
        if not name:
            return {"error": "name is required"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"Persona '{name}' does not exist"}
        identity = _load_yaml(IDENTITY_FILE)
        identity["active"] = name
        _save_yaml(IDENTITY_FILE, identity)
        persona = _load_yaml(path)
        return {"success": True, "message": f"Switched to '{name}'", "persona": persona}

    if action == "delete":
        if not name:
            return {"error": "name is required"}
        if name == "hare":
            return {"error": "Default persona 'hare' cannot be deleted"}
        if name == get_active_persona_name():
            return {"error": f"Cannot delete the active persona '{name}', switch first"}
        path = PERSONAS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"Persona '{name}' does not exist"}
        path.unlink()
        return {"success": True, "message": f"Deleted persona '{name}'"}

    return {"error": f"Unknown action: '{action}', available: list/get/create/update/switch/delete"}
