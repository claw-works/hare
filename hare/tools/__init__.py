from __future__ import annotations

import asyncio
from typing import Any, Callable

from hare.tools.shell import shell_run
from hare.tools.filesystem import read_file, write_file
from hare.tools.persona_tool import manage_persona
from hare.tools.acp import invoke_agent, list_agents
from hare.tools.sub_agent import sub_task
from hare.tools.config import get_enabled_local_tools

TOOL_REGISTRY: dict[str, Callable] = {
    "local_shell": shell_run,
    "local_read_file": read_file,
    "local_write_file": write_file,
    "persona_manage": manage_persona,
    "coding_agent": invoke_agent,
    "coding_agent_list": list_agents,
    "sub_task": sub_task,
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "toolSpec": {
            "name": "local_shell",
            "description": "Run a shell command on the user's local machine. Returns stdout/stderr.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "working_dir": {"type": "string"},
                    },
                    "required": ["command"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "local_read_file",
            "description": "Read a file from the user's local machine.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "local_write_file",
            "description": "Write content to a file on the user's local machine.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "coding_agent",
            "description": "Delegate coding tasks to a local AI agent (Claude Code / Kiro).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "enum": ["claude", "kiro"]},
                        "prompt": {"type": "string"},
                        "working_dir": {"type": "string"},
                    },
                    "required": ["agent", "prompt"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "coding_agent_list",
            "description": "List available coding agents and their status.",
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "sub_task",
            "description": "Spawn a sub-agent for an independent task (isolated context, shared long-term memory).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "system_prompt": {"type": "string"},
                    },
                    "required": ["task"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "persona_manage",
            "description": "Manage your personas. Actions: list, get, create, update, switch, delete.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "get", "create", "update", "switch", "delete"]},
                        "name": {"type": "string"},
                        "data": {"type": "object"},
                    },
                    "required": ["action"],
                }
            },
        }
    },
]


async def execute_tool(name: str, input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute a registered tool and return the result."""
    # MCP 工具路由（包含 mcp__ 前缀）
    if name.startswith("mcp__"):
        from hare.mcp_client import get_mcp_manager
        return await get_mcp_manager().call_tool_by_full_name(name, input_data)

    enabled = get_enabled_local_tools()
    # 兼容旧名称（向后兼容）
    canonical = name
    if name not in enabled:
        return {"error": f"工具 '{name}' 未启用或不存在"}
    handler = TOOL_REGISTRY.get(canonical)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    if asyncio.iscoroutinefunction(handler):
        return await handler(**input_data)
    return await asyncio.to_thread(handler, **input_data)
