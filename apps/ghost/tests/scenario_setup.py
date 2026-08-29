"""截图前置钩子：当前两个场景都无需额外状态，保留空实现以便后续接入登录态截图。"""

from __future__ import annotations


def prepare(page, slug: str) -> None:
    return None
