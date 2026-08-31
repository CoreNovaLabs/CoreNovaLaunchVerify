"""FAILED classification + the GitHub-issue failure registry (workflow-state-machine.md §4/§7).

Only TRANSIENT may auto-retry. Everything else routes to FIX_PR or MANUAL_REQUIRED —
a blanket retry policy would hide real regressions behind flaky-green runs.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote as _urlencode

from .util import HttpError, http_json, http_request, is_transitional_error, log

LABEL = "verify-failed"
MAX_ATTEMPTS = 3


@dataclass
class FailureRecord:
    app: str
    app_version: str
    verification_id: str
    classification: str
    failed_stage: str
    failed_check: str
    attempts: int = 1
    run_url: str = ""
    platform_verification_id: str = ""
    detail: str = ""

    def title(self) -> str:
        return f"verify({self.app}): {self.app_version} FAILED ({self.classification})"

    def labels(self) -> list[str]:
        out = [LABEL, f"classification:{self.classification}", f"app:{self.app}"]
        if self.classification in ("INFRASTRUCTURE", "MANUAL_REQUIRED") or self.attempts >= MAX_ATTEMPTS:
            out.append("needs-human")
        return out

    def body(self) -> str:
        meta = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        return (
            f"Application Verification 失败。\n\n"
            f"```corenova-failure\n{json.dumps(_block(self), ensure_ascii=False, indent=2)}\n```\n\n"
            f"### 详情\n\n```\n{self.detail[:4000]}\n```\n\n"
            f"运行：{self.run_url or '（本地运行，无 Actions 链接）'}\n\n"
            f"<!-- full record: {meta} -->\n"
        )


def _block(r: FailureRecord) -> dict[str, Any]:
    return {
        "app": r.app,
        "app_version": r.app_version,
        "verification_id": r.verification_id,
        "classification": r.classification,
        "failed_stage": r.failed_stage,
        "failed_check": r.failed_check,
        "attempts": r.attempts,
        "run_url": r.run_url,
        "platform_verification_id": r.platform_verification_id,
    }


def classify(stage: str, check: str = "", err: BaseException | None = None) -> str:
    """Map a failure onto the state machine's five categories."""
    if err is not None and is_transitional_error(err):
        return "TRANSIENT"
    if stage in ("DEPLOYING", "DEPLOYED") or check in ("cfn", "ami", "cfn_init", "nginx_platform"):
        return "INFRASTRUCTURE"
    if stage == "RESOLVED":
        return "TRANSIENT" if err is not None else "APPLICATION"
    if stage == "PUBLISHING":
        return "TRANSIENT"
    if check == "tests_passed":
        return "TEST"
    if check in ("compose_started", "container_healthy", "health_check_passed"):
        return "APPLICATION"
    if check == "required_platform_contract_valid":
        return "INFRASTRUCTURE"
    if check == "screenshots_generated":
        return "TEST"
    return "MANUAL_REQUIRED"


# --------------------------------------------------------------------------- registry


def repo_name() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "")


def _headers() -> dict[str, str]:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def find_issue(record: FailureRecord) -> dict[str, Any] | None:
    """Idempotency key = verification_id (state-machine §7)."""
    repo = repo_name()
    if not repo:
        return None
    q = f"repo:{repo} is:issue in:title {record.verification_id}"
    try:
        hits = http_json(f"https://api.github.com/search/issues?q={_urlencode(q, safe='')}&per_page=5", headers=_headers())
    except HttpError as exc:
        log(f"查询失败台账出错（忽略）：{exc}")
        return None
    for it in hits.get("items") or []:
        if record.verification_id in (it.get("body") or ""):
            return it
    return None


def record_failure(record: FailureRecord) -> None:
    """Create or update the ledger issue. Never raises: reporting must not mask the result."""
    repo = repo_name()
    if not repo:
        log("非 GitHub 环境（无 GITHUB_REPOSITORY）→ 失败台账仅打印")
        print(json.dumps(_block(record), ensure_ascii=False))
        return
    existing = find_issue(record)
    try:
        if existing:
            number = existing["number"]
            record.attempts = _attempts_of(existing.get("body") or "") + 1
            http_request(
                f"https://api.github.com/repos/{repo}/issues/{number}",
                method="PATCH",
                headers=_headers(),
                data={"body": record.body(), "labels": record.labels(), "state": "open"},
            )
            log(f"失败台账已更新 #{number}（attempt {record.attempts}）")
        else:
            resp = http_json(
                f"https://api.github.com/repos/{repo}/issues",
                method="POST",
                headers=_headers(),
                data={"title": record.title(), "body": record.body(), "labels": record.labels()},
            )
            log(f"失败台账已创建 #{resp.get('number')}")
    except Exception as exc:  # noqa: BLE001
        log(f"写失败台账出错（忽略）：{type(exc).__name__}: {exc}")


def close_failure(record: FailureRecord) -> None:
    repo = repo_name()
    if not repo:
        return
    existing = find_issue(record)
    if not existing:
        return
    try:
        http_request(
            f"https://api.github.com/repos/{repo}/issues/{existing['number']}",
            method="PATCH", headers=_headers(), data={"state": "closed"},
        )
        log(f"失败台账已关闭 #{existing['number']}")
    except Exception as exc:  # noqa: BLE001
        log(f"关闭台账出错（忽略）：{exc}")


def _attempts_of(body: str) -> int:
    m = re.search(r'"attempts":\s*(\d+)', body)
    return int(m.group(1)) if m else 1


def open_transient_failures(limit: int = 20) -> list[dict[str, Any]]:
    """Entries reverify-failed.yml may legitimately retry (TRANSIENT, attempts < 3, open)."""
    repo = repo_name()
    if not repo:
        return []
    q = f"repo:{repo} is:issue is:open label:{LABEL} label:classification:TRANSIENT"
    try:
        hits = http_json(
            f"https://api.github.com/search/issues?q={_urlencode(q, safe='')}&per_page={limit}", headers=_headers()
        )
    except HttpError as exc:
        log(f"读取失败台账出错：{exc}")
        return []
    out = []
    for it in hits.get("items") or []:
        m = re.search(r"```corenova-failure\n(.*?)\n```", it.get("body") or "", re.S)
        if not m:
            continue
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if int(meta.get("attempts", 1)) < MAX_ATTEMPTS:
            meta["issue_number"] = it["number"]
            out.append(meta)
    return out


def pending_review_failures(limit: int = 30) -> list[dict[str, Any]]:
    """Non-transient failures, surfaced for humans only — never auto-retried."""
    repo = repo_name()
    if not repo:
        return []
    out: list[dict[str, Any]] = []
    for cls in ("APPLICATION", "TEST", "INFRASTRUCTURE", "MANUAL_REQUIRED"):
        q = f"repo:{repo} is:issue is:open label:{LABEL} label:classification:{cls}"
        try:
            hits = http_json(f"https://api.github.com/search/issues?q={_urlencode(q, safe='')}&per_page={limit}", headers=_headers())
        except HttpError:
            continue
        for it in hits.get("items") or []:
            out.append({"classification": cls, "number": it["number"], "title": it["title"]})
    return out


@dataclass
class Summary:
    ok: bool
    classification: str = ""
    notes: list[str] = field(default_factory=list)
