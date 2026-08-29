#!/usr/bin/env python3
"""RESOLVED：渲染精确 tag 并解析 linux/amd64 不可变 digest（实现见 resolve.py）。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from resolve import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("image"))
