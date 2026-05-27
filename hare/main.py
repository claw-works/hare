# -*- coding: utf-8 -*-
import os
import sys
import shutil
from pathlib import Path

HARE_DIR = Path.home() / ".hare"


def _ensure_hare_dir():
    """确保 ~/.hare/ 目录存在，并初始化缺失的配置文件。"""
    HARE_DIR.mkdir(parents=True, exist_ok=True)

    project_root = Path(__file__).parent.parent

    # 检查 .env
    env_file = HARE_DIR / ".env"
    if not env_file.exists():
        template = project_root / ".env.example"
        if template.exists():
            shutil.copy(template, env_file)

    # 检查 tools.yaml
    tools_file = HARE_DIR / "tools.yaml"
    if not tools_file.exists():
        template = project_root / "tools.yaml.example"
        if template.exists():
            shutil.copy(template, tools_file)

    # 预留目录
    for d in ["skills"]:
        (HARE_DIR / d).mkdir(exist_ok=True)


def main():
    _ensure_hare_dir()

    # 只从 ~/.hare/.env 加载
    from dotenv import load_dotenv
    load_dotenv(HARE_DIR / ".env")

    # --setup 入口：随时可重新运行 onboarding
    if "--setup" in sys.argv:
        from hare.onboard import run_onboarding
        run_onboarding()
        return

    # 首次启动自动触发：检测到 HARNESS_ARN 未配置
    from hare.onboard import needs_onboarding
    if needs_onboarding():
        from hare.onboard import run_onboarding
        run_onboarding()
        # 重新加载 .env 以获取 onboarding 写入的值
        load_dotenv(HARE_DIR / ".env", override=True)
        # 如果 onboarding 后仍未配置，退出
        if not os.environ.get("HARNESS_ARN") or "ACCOUNT_ID" in os.environ.get("HARNESS_ARN", ""):
            return

    from hare.tui_v2.app import main as run
    run()


if __name__ == "__main__":
    main()
