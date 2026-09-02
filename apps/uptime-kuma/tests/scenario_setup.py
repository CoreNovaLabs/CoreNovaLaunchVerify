"""截图前置钩子：当前唯一场景（首启向导）无需额外状态，保留空实现以便后续接入。"""

from __future__ import annotations


def prepare(page, slug: str) -> None:
    return None
