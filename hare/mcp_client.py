# -*- coding: utf-8 -*-
"""Local MCP server manager.
Supports standard mcp.json format, compatible with Claude Code / Cursor config files.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

HARE_DIR = Path.home() / ".hare"
GLOBAL_MCP_CONFIG = HARE_DIR / "mcp.json"
PROJECT_MCP_CONFIG = Path(".hare") / "mcp.json"


def _load_mcp_config() -> dict:
    """Load mcp.json; project-level config overrides global servers of the same name."""
    global_cfg = {}
    project_cfg = {}

    if GLOBAL_MCP_CONFIG.exists():
        try:
            global_cfg = json.loads(GLOBAL_MCP_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass

    if PROJECT_MCP_CONFIG.exists():
        try:
            project_cfg = json.loads(PROJECT_MCP_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass

    merged = dict(global_cfg.get("mcpServers", {}))
    merged.update(project_cfg.get("mcpServers", {}))
    return merged


class MCPTransport:
    """Base class for MCP transports."""

    async def send(self, request: dict) -> dict:
        raise NotImplementedError

    async def notify(self, notification: dict) -> None:
        """Send notification (fire-and-forget, no response expected)."""
        pass  # Default no-op, subclasses override as needed

    async def close(self) -> None:
        pass


class StdioTransport(MCPTransport):
    """stdio transport: manages subprocess, sends/receives JSON-RPC via stdin/stdout."""

    def __init__(self, command: str, args: list[str], env: dict | None = None):
        self.command = command
        self.args = args
        self.env = {**os.environ, **(env or {})}
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )

    async def send(self, request: dict) -> dict:
        if not self._proc or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("stdio transport not started")
        async with self._lock:
            payload = json.dumps(request) + "\n"
            self._proc.stdin.write(payload.encode())
            await self._proc.stdin.drain()
            line = await self._proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed stdout")
            return json.loads(line)

    async def notify(self, notification: dict) -> None:
        """Send notification, fire-and-forget."""
        if self._proc and self._proc.stdin:
            payload = json.dumps(notification) + "\n"
            self._proc.stdin.write(payload.encode())
            try:
                await self._proc.stdin.drain()
            except Exception:
                pass

    async def close(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()


class SSETransport(MCPTransport):
    """SSE transport: sends/receives via HTTP SSE connection."""

    def __init__(self, url: str, headers: dict | None = None):
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self._client = httpx.AsyncClient(timeout=60)
        self._msg_id = 0

    async def send(self, request: dict) -> dict:
        self._msg_id += 1
        request.setdefault("id", self._msg_id)
        resp = await self._client.post(
            self.url, json=request, headers=self.headers
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()


class StreamableHTTPTransport(MCPTransport):
    """Streamable HTTP transport (MCP 2025-03 spec), supports mcp-session-id."""

    def __init__(self, url: str, headers: dict | None = None):
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self._client = httpx.AsyncClient(timeout=60)
        self._msg_id = 0
        self._session_id: str | None = None

    def _build_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _parse_response(self, resp: httpx.Response) -> dict:
        """Parse response, supports both SSE and JSON formats."""
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        return json.loads(data)
            return {}
        return resp.json()

    async def send(self, request: dict) -> dict:
        self._msg_id += 1
        request.setdefault("id", self._msg_id)
        resp = await self._client.post(
            self.url, json=request, headers=self._build_headers()
        )
        resp.raise_for_status()
        return self._parse_response(resp)

    async def notify(self, notification: dict) -> None:
        """Send notification, fire-and-forget (no response expected)."""
        try:
            await self._client.post(
                self.url, json=notification, headers=self._build_headers()
            )
        except Exception:
            pass  # Notification failure is acceptable

    async def close(self) -> None:
        await self._client.aclose()


class MCPServer:
    """Single MCP server connection."""

    def __init__(self, name: str, transport: MCPTransport):
        self.name = name
        self.transport = transport
        self._tools: list[dict] = []
        self._initialized = False

    async def initialize(self) -> None:
        """Send initialize + initialized handshake, then get tool list."""
        if isinstance(self.transport, StdioTransport):
            await self.transport.start()

        # initialize handshake
        await self.transport.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hare", "version": "0.1.0"},
            },
        })

        # initialized notification (no response expected)
        await self.transport.notify({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # Get tool list
        tools_resp = await self.transport.send({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        self._tools = tools_resp.get("result", {}).get("tools", [])
        self._initialized = True

    @property
    def tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call a tool on the MCP server."""
        resp = await self.transport.send({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        if "error" in resp:
            return {"error": resp["error"].get("message", str(resp["error"]))}
        result = resp.get("result", {})
        # MCP tools return content array, extract text
        content = result.get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return {"output": "\n".join(texts)} if texts else {"output": json.dumps(result)}

    async def close(self) -> None:
        await self.transport.close()


class MCPManager:
    """Manages all MCP server connections."""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Load config and connect all MCP servers."""
        if self._initialized:
            return
        config = _load_mcp_config()
        for name, server_cfg in config.items():
            try:
                transport = self._create_transport(server_cfg)
                server = MCPServer(name, transport)
                await server.initialize()
                self._servers[name] = server
            except Exception as e:
                import sys
                print(f"[MCP] Failed to connect {name}: {e}", file=sys.stderr)
        self._initialized = True

    def _create_transport(self, cfg: dict) -> MCPTransport:
        transport_type = cfg.get("type", "stdio")
        if transport_type == "stdio":
            return StdioTransport(
                command=cfg["command"],
                args=cfg.get("args", []),
                env=cfg.get("env"),
            )
        elif transport_type == "sse":
            return SSETransport(
                url=cfg["url"],
                headers=cfg.get("headers"),
            )
        elif transport_type == "streamable-http":
            return StreamableHTTPTransport(
                url=cfg["url"],
                headers=cfg.get("headers"),
            )
        else:
            raise ValueError(f"Unsupported MCP transport type: {transport_type}")

    def get_tools(self) -> list[dict[str, Any]]:
        """Return all MCP tools as inline_function definitions (harness-compatible)."""
        tools = []
        for server_name, server in self._servers.items():
            for tool in server.tools:
                tools.append({
                    "type": "inline_function",
                    "name": f"mcp__{server_name}__{tool['name']}",
                    "config": {
                        "inlineFunction": {
                            "description": tool.get("description", ""),
                            "inputSchema": tool.get("inputSchema", {"type": "object", "properties": {}}),
                        }
                    },
                })
        return tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the specified server."""
        server = self._servers.get(server_name)
        if not server:
            return {"error": f"MCP server '{server_name}' not connected"}
        return await server.call_tool(tool_name, arguments)

    async def call_tool_by_full_name(self, full_name: str, arguments: dict) -> dict:
        """Call by full tool name (mcp__{server}__{tool})."""
        parts = full_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            return {"error": f"Invalid MCP tool name: {full_name}"}
        return await self.call_tool(parts[1], parts[2], arguments)

    async def close(self) -> None:
        """Close all MCP server connections."""
        for server in self._servers.values():
            try:
                await server.close()
            except Exception:
                pass
        self._servers.clear()
        self._initialized = False


# Module-level singleton
_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
