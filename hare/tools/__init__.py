from __future__ import annotations

import asyncio
from typing import Any, Callable

from hare.tools.shell import shell_run
from hare.tools.filesystem import read_file, write_file
from hare.tools.config import get_enabled_local_tools

TOOL_REGISTRY: dict[str, Callable] = {
    "shell_run": shell_run,
    "read_file": read_file,
    "write_file": write_file,
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "toolSpec": {
            "name": "shell_run",
            "description": "Execute a shell command locally and return stdout/stderr.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute."},
                        "working_dir": {"type": "string", "description": "Optional working directory.", "default": "."},
                    },
                    "required": ["command"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute or relative file path."},
                    },
                    "required": ["path"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "write_file",
            "description": "Write content to a file, creating directories as needed.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to write to."},
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
    enabled = get_enabled_local_tools()
    if name not in enabled:
        return {"error": f"工具 '{name}' 未启用或不存在"}
    handler = TOOL_REGISTRY.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    if asyncio.iscoroutinefunction(handler):
        return await handler(**input_data)
    return await asyncio.to_thread(handler, **input_data)
