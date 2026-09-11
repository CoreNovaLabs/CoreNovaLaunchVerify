"""resolver.semver_latest 策略测试。

背景（app-schema.md §4）：semver_latest = "从 tag 中取满足 semver 的最新稳定版"。
上游可能发布非版本号命名的最新 release（如 n8n 的 "stable"），或 tag 带仓库前缀
（如 "n8n@2.38.6"）——策略必须扫描 release 列表并宽容提取 semver，而不是只看
/releases/latest。
"""

from __future__ import annotations

from corenova.resolver import extract_semver


def test_extract_semver_plain():
    assert extract_semver("1.37.2") == (1, 37, 2)


def test_extract_semver_v_prefix():
    assert extract_semver("v1.27.3") == (1, 27, 3)


def test_extract_semver_repo_prefix():
    assert extract_semver("n8n@2.38.6") == (2, 38, 6)


def test_extract_semver_suffix():
    assert extract_semver("1.37.2-alpine") == (1, 37, 2)
    assert extract_semver("v0.30.0-rc.1") == (0, 30, 0)


def test_extract_semver_non_semver_returns_none():
    assert extract_semver("stable") is None
    assert extract_semver("2024-10-22") is None
    assert extract_semver("") is None
