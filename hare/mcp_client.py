# -*- coding: utf-8 -*-
"""本地 MCP server 管理器。
支持标准 mcp.json 格式，兼容 Claude Code / Cursor 等工具的配置文件。
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
    """加载 mcp.json，项目级配置覆盖全局同名 server。"""
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
        """发送通知（fire-and-forget，不等待响应）。"""
        pass  # 默认 no-op，子类按需 override

    async def close(self) -> None:
        pass


class StdioTransport(MCPTransport):
    """stdio 传输：管理子进程，通过 stdin/stdout 收发 JSON-RPC。"""

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
        """发送通知，fire-and-forget。"""
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
    """SSE 传输：通过 HTTP SSE 连接收发。"""

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
    """Streamable HTTP 传输（MCP 2025-03 规范），支持 mcp-session-id。"""

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
        """解析响应，支持 SSE 和 JSON 两种格式。"""
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
        """发送通知，fire-and-forget（不等响应）。"""
        try:
            await self._client.post(
                self.url, json=notification, headers=self._build_headers()
            )
        except Exception:
            pass  # 通知失败无所谓

    async def close(self) -> None:
        await self._client.aclose()


class MCPServer:
    """单个 MCP server 连接。"""

    def __init__(self, name: str, transport: MCPTransport):
        self.name = name
        self.transport = transport
        self._tools: list[dict] = []
        self._initialized = False

    async def initialize(self) -> None:
        """发送 initialize + initialized 握手，然后获取工具列表。"""
        if isinstance(self.transport, StdioTransport):
            await self.transport.start()

        # initialize 握手
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

        # initialized 通知（notification，无需等待响应）
        await self.transport.notify({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # 获取工具列表
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
        """调用 MCP server 上的工具。"""
        resp = await self.transport.send({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        if "error" in resp:
            return {"error": resp["error"].get("message", str(resp["error"]))}
        result = resp.get("result", {})
        # MCP 工具返回 content 数组，提取文本
        content = result.get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return {"output": "\n".join(texts)} if texts else {"output": json.dumps(result)}

    async def close(self) -> None:
        await self.transport.close()


class MCPManager:
    """管理所有 MCP server 连接。"""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """加载配置并连接所有 MCP server。"""
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
                print(f"[MCP] 连接 {name} 失败: {e}", file=sys.stderr)
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
            raise ValueError(f"不支持的 MCP 传输类型: {transport_type}")

    def get_tools(self) -> list[dict[str, Any]]:
        """返回所有 MCP 工具的 inline_function 定义（兼容 harness 格式）。"""
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
        """调用指定 server 上的工具。"""
        server = self._servers.get(server_name)
        if not server:
            return {"error": f"MCP server '{server_name}' 未连接"}
        return await server.call_tool(tool_name, arguments)

    async def call_tool_by_full_name(self, full_name: str, arguments: dict) -> dict:
        """通过完整工具名 (mcp__{server}__{tool}) 调用。"""
        parts = full_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            return {"error": f"无效的 MCP 工具名: {full_name}"}
        return await self.call_tool(parts[1], parts[2], arguments)

    async def close(self) -> None:
        """关闭所有 MCP server 连接。"""
        for server in self._servers.values():
            try:
                await server.close()
            except Exception:
                pass
        self._servers.clear()
        self._initialized = False


# 模块级单例
_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
