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
            print(f"⚠️  已创建 {env_file}")
            print("   请编辑该文件，填入 AWS_REGION、AWS_PROFILE、HARNESS_ARN")
            print(f"   vi {env_file}")
            sys.exit(1)

    # 检查 tools.yaml
    tools_file = HARE_DIR / "tools.yaml"
    if not tools_file.exists():
        template = project_root / "tools.yaml.example"
        if template.exists():
            shutil.copy(template, tools_file)
            print(f"✅ 已从模板创建 {tools_file}，可按需修改工具配置")

    # 预留目录（identity/soul/skills 后续用）
    for d in ["skills"]:
        (HARE_DIR / d).mkdir(exist_ok=True)


def main():
    _ensure_hare_dir()

    # 只从 ~/.hare/.env 加载，不从项目目录加载
    from dotenv import load_dotenv
    load_dotenv(HARE_DIR / ".env")

    from hare.tui.app import main as run
    run()


if __name__ == "__main__":
    main()
