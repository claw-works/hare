# -*- coding: utf-8 -*-
"""ACP (Agent Communication Protocol) — 通过 stream-json 与本地 coding agent 双向通信。

Claude Code ACP 模式：
  claude -p --output-format stream-json --input-format stream-json

支持的 agent：
- claude: Claude Code CLI (stream-json 双向流)
- kiro: Kiro CLI (print 模式)

配置文件：~/.hare/acp.yaml
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
        "description": "Claude Code — ACP stream-json 模式",
        "enabled": True,
        "working_dir": None,
        "timeout": 300,
    },
    "kiro": {
        "command": "kiro",
        "args": ["--prompt", "{prompt}"],
        "description": "Kiro CLI — AI 编程工具",
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
    """确保 acp.yaml 存在。"""
    if not ACP_CONFIG.exists():
        _save_acp_config(DEFAULT_AGENTS)


def _parse_stream_json(output: str) -> str:
    """从 stream-json 输出中提取最终结果文本。

    stream-json 每行一个 JSON 对象，格式如：
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
            # 最终结果
            result_text = event.get("result", "")
            break
        elif etype == "assistant":
            # 中间 assistant 消息，提取文本
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
    调用指定的 coding agent 执行编程任务。

    agent: agent 名称（claude, kiro, 等）
    prompt: 要发送给 agent 的提示/任务描述
    working_dir: 工作目录（可选，默认用 agent 配置或当前目录）
    """
    agents = _load_acp_config()

    if agent not in agents:
        available = [k for k, v in agents.items() if v.get("enabled", True)]
        return {"error": f"未知 agent: '{agent}'", "available": available}

    cfg = agents[agent]
    if not cfg.get("enabled", True):
        return {"error": f"agent '{agent}' 未启用，请在 ~/.hare/acp.yaml 中开启"}

    command = cfg["command"]
    if not shutil.which(command):
        return {"error": f"未找到命令 '{command}'，请确认已安装"}

    # 构建参数，替换 {prompt} 占位符
    args = []
    for arg in cfg.get("args", []):
        if "{prompt}" in arg:
            args.append(arg.replace("{prompt}", prompt))
        else:
            args.append(arg)

    # 工作目录
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
            return {"error": f"agent '{agent}' 执行超时（{timeout}s）"}

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return {
                "error": f"agent '{agent}' 退出码 {proc.returncode}",
                "stdout": stdout_text[-2000:] if len(stdout_text) > 2000 else stdout_text,
                "stderr": stderr_text[-1000:] if len(stderr_text) > 1000 else stderr_text,
            }

        # 对 Claude Code stream-json 输出做解析
        is_stream_json = "--output-format" in cfg.get("args", []) and "stream-json" in cfg.get("args", [])
        if is_stream_json:
            result = _parse_stream_json(stdout_text)
        else:
            result = stdout_text

        # 截断过长输出
        if len(result) > 4000:
            result = result[:2000] + "\n\n...(中间省略)...\n\n" + result[-2000:]

        return {
            "output": result,
            "exit_code": 0,
        }

    except FileNotFoundError:
        return {"error": f"命令 '{command}' 不存在"}
    except Exception as e:
        return {"error": f"执行失败: {str(e)}"}


def list_agents() -> dict[str, Any]:
    """列出所有可用的 coding agent。"""
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
