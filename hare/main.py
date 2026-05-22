# -*- coding: utf-8 -*-
import os
import sys

# 确保 UTF-8 输出
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("LANG", "en_US.UTF-8")

from dotenv import load_dotenv
load_dotenv()


def main():
    from hare.tui.app import main as run
    run()


if __name__ == "__main__":
    main()
