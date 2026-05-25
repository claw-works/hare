# -*- coding: utf-8 -*-
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "local_tools": [
        {"name": "local_shell",      "enabled": True, "description": "在本机执行 shell 命令"},
        {"name": "local_read_file",  "enabled": True, "description": "读取本地文件"},
        {"name": "local_write_file", "enabled": True, "description": "写入本地文件"},
    ],
    "gateway_tools": [
        {
            "name": "agentmate_tools",
            "enabled": False,
            "gateway_arn": "",
            "description": "AgentMate MCP 工具集",
            "auth": "awsIam",
        }
    ],
}

def load_tools_config() -> dict:
    """加载 ~/.hare/tools.yaml，找不到时返回默认配置。"""
    path = Path.home() / ".hare" / "tools.yaml"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or DEFAULT_CONFIG
        except Exception:
            pass
    return DEFAULT_CONFIG

def get_enabled_local_tools() -> list[str]:
    config = load_tools_config()
    return [t["name"] for t in config.get("local_tools", []) if t.get("enabled", True)]

def get_gateway_tools() -> list[dict]:
    config = load_tools_config()
    return [t for t in config.get("gateway_tools", []) if t.get("enabled") and t.get("gateway_arn")]
