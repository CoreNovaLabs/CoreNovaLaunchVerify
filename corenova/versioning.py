"""版本裁决的单一事实源（workflow-state-machine.md §5）。

版本覆盖保护（publish.may_update_current）与监控扇出（scripts/monitor/check_versions.compare）
此前各写一套 semver 比较：监控判 "newer" 而发布端判 "older" 的口径漂移，会造成
"扇出了验证、P5 却拒绝覆盖 current.json" 的空转（或反之——更糟）。所有版本比较
必须经由本模块；两个调用方的等价性由 tests/test_versioning.py 锁定。

契约年龄（age_days）与 semver 无关，但同属"时间/版本口径只允许一处实现"的约束，
从 golden._age_days / platformref._age_days 的重复实现收敛而来。
"""

from __future__ import annotations

import calendar
import time

from .util import parse_semver

# 契约时间戳无法解析时的哨兵：视为"无限老"，让过期判定必然成立而不是误判有效。
UNPARSEABLE_AGE_DAYS = 1e9


def semver_relation(candidate: str, current: str) -> str | None:
    """纯 semver 比较：返回 "newer" / "same" / "older"；任一侧不可解析返回 None。

    调用方决定 None 的回退策略（P5 用 run_id，监控用字符串等值 + unknown）。
    注意 parse_semver 忽略 prerelease/build 后缀，"v1.2.3-rc.1" 与 "v1.2.3" 判 same。
    """
    a, b = parse_semver(candidate), parse_semver(current)
    if not a or not b:
        return None
    if a > b:
        return "newer"
    if a == b:
        return "same"
    return "older"


def relation(candidate: str, current: str | None) -> str:
    """监控口径的完整五值关系：initial / newer / same / older / unknown。

    current 缺失 → initial（从未发布）；非 semver 且字符串相等 → same；
    非 semver 且不等 → unknown（commit SHA / 日期标签无法用版本号裁决）。
    """
    if not current:
        return "initial"
    rel = semver_relation(candidate, current)
    if rel:
        return rel
    return "same" if candidate == current else "unknown"


def age_days(iso: str) -> float:
    """UTC ISO 时间戳（%Y-%m-%dT%H:%M:%SZ）距今的天数，负值钳到 0。

    解析失败（含 None/非字符串）返回 UNPARSEABLE_AGE_DAYS：过期判定宁可误报
    "需复验"也不能把坏时间戳当成"契约很新"。
    """
    try:
        # platform_verified_at 是 UTC；time.mktime 会按本地时区解释它，
        # 非 UTC 机器上契约年龄会偏一个时区偏移，必须用 timegm。
        t = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return max(0.0, (time.time() - calendar.timegm(t)) / 86400.0)
    except (ValueError, TypeError):
        return UNPARSEABLE_AGE_DAYS
