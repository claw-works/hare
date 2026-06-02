# -*- coding: utf-8 -*-
import os
import sys
import shutil
from pathlib import Path

HARE_DIR = Path.home() / ".hare"


def _ensure_hare_dir():
    """Ensure ~/.hare/ directory exists and initialize missing config files."""
    HARE_DIR.mkdir(parents=True, exist_ok=True)

    project_root = Path(__file__).parent.parent

    # Check .env
    env_file = HARE_DIR / ".env"
    if not env_file.exists():
        template = project_root / ".env.example"
        if template.exists():
            shutil.copy(template, env_file)

    # Check tools.yaml
    tools_file = HARE_DIR / "tools.yaml"
    if not tools_file.exists():
        template = project_root / "tools.yaml.example"
        if template.exists():
            shutil.copy(template, tools_file)

    # Reserved directories
    for d in ["skills"]:
        (HARE_DIR / d).mkdir(exist_ok=True)


def main():
    _ensure_hare_dir()

    # Only load from ~/.hare/.env
    from dotenv import load_dotenv
    load_dotenv(HARE_DIR / ".env")

    # --setup entry: re-run onboarding anytime
    if "--setup" in sys.argv:
        from hare.onboard import run_onboarding
        run_onboarding()
        return

    # Auto-trigger on first launch: HARNESS_ARN not configured
    from hare.onboard import needs_onboarding
    if needs_onboarding():
        from hare.onboard import run_onboarding
        run_onboarding()
        # Reload .env to get values written by onboarding
        load_dotenv(HARE_DIR / ".env", override=True)
        # If still not configured after onboarding, exit
        if not os.environ.get("HARNESS_ARN") or "ACCOUNT_ID" in os.environ.get("HARNESS_ARN", ""):
            return

    from hare.tui_v2.app import main as run
    run()


if __name__ == "__main__":
    main()
