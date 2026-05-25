from __future__ import annotations

import asyncio
from typing import Any, Callable

from hare.tools.shell import shell_run
from hare.tools.filesystem import read_file, write_file
from hare.tools.persona_tool import manage_persona
from hare.tools.acp import invoke_agent, list_agents
from hare.tools.config import get_enabled_local_tools

TOOL_REGISTRY: dict[str, Callable] = {
    "local_shell": shell_run,
    "local_read_file": read_file,
    "local_write_file": write_file,
    "persona_manage": manage_persona,
    "coding_agent": invoke_agent,
    "coding_agent_list": list_agents,
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "toolSpec": {
            "name": "local_shell",
            "description": (
                "Execute a shell command on the USER'S LOCAL MACHINE (macOS/Linux desktop) and return stdout/stderr. "
                "Use ONLY for operations on the user's local filesystem, local processes, or local system info. "
                "Do NOT use this for querying the Harness environment, remote servers, or cloud infrastructure — "
                "those are handled by Harness built-in shell or other tools."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute on the user's local machine."},
                        "working_dir": {"type": "string", "description": "Optional working directory on the local machine.", "default": "."},
                    },
                    "required": ["command"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "local_read_file",
            "description": (
                "Read the contents of a file on the USER'S LOCAL MACHINE. "
                "Use ONLY for local files (e.g., ~/Documents, /Users/...). "
                "Do NOT use for files inside the Harness environment or remote servers."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute or relative file path on the user's local machine."},
                    },
                    "required": ["path"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "local_write_file",
            "description": (
                "Write content to a file on the USER'S LOCAL MACHINE, creating directories as needed. "
                "Use ONLY for writing to the user's local filesystem."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path on the user's local machine."},
                        "content": {"type": "string", "description": "Content to write."},
                    },
                    "required": ["path", "content"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "coding_agent",
            "description": (
                "Delegate a coding task to a local AI coding agent (like Claude Code or Kiro). "
                "Use this when the user asks you to write code, fix bugs, refactor, or perform any "
                "programming task on their local project. The agent runs in the specified working directory "
                "and has full access to the local filesystem."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Which coding agent to use: 'claude' (Claude Code) or 'kiro' (Kiro CLI).",
                            "enum": ["claude", "kiro"],
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The coding task description to send to the agent. Be specific and detailed.",
                        },
                        "working_dir": {
                            "type": "string",
                            "description": "Working directory for the agent (absolute path). Defaults to the user's current project.",
                        },
                    },
                    "required": ["agent", "prompt"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "coding_agent_list",
            "description": (
                "List available coding agents and their status (installed, enabled)."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "persona_manage",
            "description": (
                "Manage your own persona/identity. You can create new personas, update existing ones, "
                "switch between them, or delete them. This is YOUR self-management tool — "
                "use it when you want to evolve, add a new role, or when the user asks you to change personality. "
                "Actions: list, get, create, update, switch, delete."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "get", "create", "update", "switch", "delete"],
                            "description": "The action to perform.",
                        },
                        "name": {
                            "type": "string",
                            "description": "Persona identifier (filename without .yaml). Required for all actions except list.",
                        },
                        "data": {
                            "type": "object",
                            "description": "Persona data for create/update. Should include: name (display name), emoji, creature, vibe, tone.",
                        },
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
