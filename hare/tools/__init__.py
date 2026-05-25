from __future__ import annotations

import asyncio
from typing import Any, Callable

from hare.tools.shell import shell_run
from hare.tools.filesystem import read_file, write_file
from hare.tools.config import get_enabled_local_tools

TOOL_REGISTRY: dict[str, Callable] = {
    "local_shell": shell_run,
    "local_read_file": read_file,
    "local_write_file": write_file,
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
