"""app-profiles.md §3 sizing ladder."""

from __future__ import annotations

LADDER: dict[str, dict[str, tuple[str, int]]] = {
    "stateless_web": {"small": ("t3.small", 20), "medium": ("t3.medium", 40), "large": ("t3.large", 80), "xlarge": ("t3.xlarge", 160)},
    "stateful_app": {"small": ("t3.small", 30), "medium": ("t3.medium", 60), "large": ("t3.large", 120), "xlarge": ("t3.xlarge", 240)},
    "database": {"medium": ("t3.medium", 100), "large": ("t3.large", 200), "xlarge": ("t3.xlarge", 400)},
    "cache": {"small": ("t3.small", 10), "medium": ("t3.medium", 20), "large": ("t3.large", 40)},
    "queue": {"small": ("t3.small", 20), "medium": ("t3.medium", 40), "large": ("t3.large", 80)},
    "worker": {"small": ("t3.small", 10), "medium": ("t3.medium", 20), "large": ("t3.large", 40)},
    "cron": {"small": ("t3.small", 10), "medium": ("t3.medium", 20), "large": ("t3.large", 40)},
    "other": {"small": ("t3.small", 20), "medium": ("t3.medium", 40), "large": ("t3.large", 80)},
}

# app_type -> (min_size, default_size, port_tier, stateful_volume, startup_timeout_seconds)
TYPES: dict[str, tuple[str, str, str, bool, int]] = {
    "stateless_web": ("small", "small", "public", False, 180),
    "stateful_app": ("small", "small", "public", True, 180),
    "database": ("medium", "medium", "internal", True, 240),
    "cache": ("small", "small", "internal", False, 120),
    "queue": ("small", "small", "internal", True, 180),
    "worker": ("small", "small", "none", False, 120),
    "cron": ("small", "small", "none", False, 120),
    "other": ("small", "small", "internal", False, 180),
}

SIZE_ORDER = ["small", "medium", "large", "xlarge"]

CATEGORIES = ["cms", "ai", "media", "devops", "productivity", "database", "auth", "automation", "other"]
RELEASE_TYPES = ["initial", "new_version", "security_update", "bug_fix"]
ASSERTION_KINDS = ["env", "label", "api_json_path", "header", "exec_command"]
VERSION_STRATEGIES = ["release_tag", "semver_latest", "git_branch", "pinned"]


def rank(size: str) -> int:
    return SIZE_ORDER.index(size)


def resolve_size(app_type: str, size: str | None) -> tuple[str, str, str]:
    """-> (effective_size, min_size, default_size). Raises KeyError for unknown app_type."""
    min_size, default_size, _tier, _vol, _timeout = TYPES[app_type]
    return (size or default_size), min_size, default_size


def derive(app_type: str, size: str) -> tuple[str, int] | None:
    """-> (instance_type, disk_gb)，该 app_type 无此档时返回 None（由校验规则报错）。"""
    return LADDER.get(app_type, {}).get(size)


def startup_timeout(app_type: str) -> int:
    return TYPES[app_type][4]


def port_tier(app_type: str) -> str:
    return TYPES[app_type][2]
