# -*- coding: utf-8 -*-
"""ACP (Agent Communication Protocol) — bidirectional communication with local coding agents via stream-json.

Claude Code ACP mode:
  claude -p --output-format stream-json --input-format stream-json

Supported agents:
- claude: Claude Code CLI (stream-json bidirectional stream)
- kiro: Kiro CLI (print mode)

Config file: ~/.hare/acp.yaml
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

HARE_DIR = Path.home() / ".hare"
ACP_CONFIG = HARE_DIR / "acp.yaml"

DEFAULT_AGENTS = {
    "claude": {
        "command": "claude",
        "args": [
            "-p",
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
            "{prompt}",
        ],
        "description": "Claude Code — ACP stream-json mode",
        "enabled": True,
        "working_dir": None,
        "timeout": 300,
    },
    "kiro": {
        "command": "kiro",
        "args": ["--prompt", "{prompt}"],
        "description": "Kiro CLI — AI coding tool",
        "enabled": False,
        "working_dir": None,
        "timeout": 300,
    },
}


def _load_acp_config() -> dict[str, Any]:
    if ACP_CONFIG.exists():
        try:
            data = yaml.safe_load(ACP_CONFIG.read_text(encoding="utf-8")) or {}
            return data.get("agents", {})
        except Exception:
            pass
    return DEFAULT_AGENTS


def _save_acp_config(agents: dict) -> None:
    ACP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    ACP_CONFIG.write_text(
        yaml.dump({"agents": agents}, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def ensure_acp_config() -> None:
    """Ensure acp.yaml exists."""
    if not ACP_CONFIG.exists():
        _save_acp_config(DEFAULT_AGENTS)


def _parse_stream_json(output: str) -> str:
    """Extract final result text from stream-json output.

    stream-json has one JSON object per line, format:
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}
    {"type": "result", "result": "...", "cost_usd": 0.01, ...}
    """
    result_text = ""
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "result":
            # Final result
            result_text = event.get("result", "")
            break
        elif etype == "assistant":
            # Intermediate assistant message, extract text
            msg = event.get("message", {})
            content = msg.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    result_text = block.get("text", "")

    return result_text


async def invoke_agent(
    agent: str,
    prompt: str,
    working_dir: str | None = None,
) -> dict[str, Any]:
    """
    Invoke the specified coding agent to execute a coding task.

    agent: agent name (claude, kiro, etc.)
    prompt: the prompt/task description to send to the agent
    working_dir: working directory (optional, defaults to agent config or cwd)
    """
    agents = _load_acp_config()

    if agent not in agents:
        available = [k for k, v in agents.items() if v.get("enabled", True)]
        return {"error": f"Unknown agent: '{agent}'", "available": available}

    cfg = agents[agent]
    if not cfg.get("enabled", True):
        return {"error": f"Agent '{agent}' is not enabled, enable it in ~/.hare/acp.yaml"}

    command = cfg["command"]
    if not shutil.which(command):
        return {"error": f"Command '{command}' not found, confirm it is installed"}

    # Build args, replace {prompt} placeholder
    args = []
    for arg in cfg.get("args", []):
        if "{prompt}" in arg:
            args.append(arg.replace("{prompt}", prompt))
        else:
            args.append(arg)

    # Working directory
    cwd = working_dir or cfg.get("working_dir") or os.getcwd()
    timeout = cfg.get("timeout", 300)

    try:
        proc = await asyncio.create_subprocess_exec(
            command, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"Agent '{agent}' timed out ({timeout}s)"}

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return {
                "error": f"Agent '{agent}' exit code {proc.returncode}",
                "stdout": stdout_text[-2000:] if len(stdout_text) > 2000 else stdout_text,
                "stderr": stderr_text[-1000:] if len(stderr_text) > 1000 else stderr_text,
            }

        # Parse Claude Code stream-json output
        is_stream_json = "--output-format" in cfg.get("args", []) and "stream-json" in cfg.get("args", [])
        if is_stream_json:
            result = _parse_stream_json(stdout_text)
        else:
            result = stdout_text

        # Truncate overly long output
        if len(result) > 4000:
            result = result[:2000] + "\n\n...(truncated)...\n\n" + result[-2000:]

        return {
            "output": result,
            "exit_code": 0,
        }

    except FileNotFoundError:
        return {"error": f"Command '{command}' does not exist"}
    except Exception as e:
        return {"error": f"Execution failed: {str(e)}"}


def list_agents() -> dict[str, Any]:
    """List all available coding agents."""
    agents = _load_acp_config()
    result = []
    for name, cfg in agents.items():
        available = shutil.which(cfg["command"]) is not None
        result.append({
            "name": name,
            "command": cfg["command"],
            "description": cfg.get("description", ""),
            "enabled": cfg.get("enabled", True),
            "installed": available,
        })
    return {"agents": result}
