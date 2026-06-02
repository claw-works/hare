# -*- coding: utf-8 -*-
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "local_tools": [
        {"name": "local_shell",      "enabled": True, "description": "Execute shell commands on local machine"},
        {"name": "local_read_file",  "enabled": True, "description": "Read local files"},
        {"name": "local_write_file", "enabled": True, "description": "Write local files"},
        {"name": "persona_manage",   "enabled": True, "description": "Manage persona roles"},
    ],
    "gateway_tools": [
        {
            "name": "agentmate_tools",
            "enabled": False,
            "gateway_arn": "",
            "description": "AgentMate MCP toolset",
            "auth": "awsIam",
        }
    ],
}

def load_tools_config() -> dict:
    """Load ~/.hare/tools.yaml, returns default config if not found."""
    path = Path.home() / ".hare" / "tools.yaml"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or DEFAULT_CONFIG
        except Exception:
            pass
    return DEFAULT_CONFIG

_BUILTIN_TOOLS = {"local_shell", "local_read_file", "local_write_file", "persona_manage", "coding_agent", "coding_agent_list", "sub_task"}


def get_enabled_local_tools() -> list[str]:
    config = load_tools_config()
    configured = {t["name"] for t in config.get("local_tools", [])}
    enabled = [t["name"] for t in config.get("local_tools", []) if t.get("enabled", True)]
    # Built-in tools not in config file are enabled by default
    for name in _BUILTIN_TOOLS:
        if name not in configured:
            enabled.append(name)
    return enabled

def get_gateway_tools() -> list[dict]:
    config = load_tools_config()
    return [t for t in config.get("gateway_tools", []) if t.get("enabled") and t.get("gateway_arn")]
