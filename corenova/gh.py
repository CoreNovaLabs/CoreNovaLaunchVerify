"""GitHub REST API 访问的统一入口：认证头与 token 策略只在这里定义。

此前 pipeline / resolver / failure 三处各自拼一份头，token 读取策略还不一致
（dispatch 只认 REPO_A_PAT，其余认 GITHUB_TOKEN/GH_TOKEN）——新增调用方时
极易拼出第四份。所有 GitHub API 调用必须从这里取头。
"""

from __future__ import annotations

import os

API_VERSION = "2022-11-28"
USER_AGENT = "corenovalaunch-verify/1.0"


def github_token(*env_keys: str) -> str:
    """按给定环境变量顺序取第一个非空 token；默认 GITHUB_TOKEN > GH_TOKEN。"""
    keys = env_keys or ("GITHUB_TOKEN", "GH_TOKEN")
    for key in keys:
        tok = os.environ.get(key, "")
        if tok:
            return tok
    return ""


def github_headers(token: str = "") -> dict[str, str]:
    """JSON API 调用的标准头。无 token 时为匿名头（GitHub 按 IP 限流 60 req/h）。

    Content-Type 对 GET 无影响、对 POST/PATCH 必需，因此恒定携带。
    """
    h = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h
