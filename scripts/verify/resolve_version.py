#!/usr/bin/env python3
"""RESOLVED：解析 app_version + release.type（实现见 resolve.py）。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from resolve import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("version"))
