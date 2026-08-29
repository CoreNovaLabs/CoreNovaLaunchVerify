"""PUBLISHING: two-phase commit per verification-manifest.md §6.

    P1 placeholder versions/{app_version}.json   (three upload checks = false)
    P2 upload screenshots + report
    P3 probe every object is readable           -> truthful values for the upload checks
    P4 rewrite versions/{app_version}.json      (final state, nine checks truthful)
    P5 commit point: current.json + verified/index.json

Anything failing before P5 leaves the website exactly as it was — that is the gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import CHECKS, report_url, screenshot_key
from .util import log, parse_semver, utcnow

UPLOAD_CHECKS = ("screenshots_uploaded", "report_uploaded", "verification_manifest_uploaded")
LOCAL_CHECKS = tuple(c for c in CHECKS if c not in UPLOAD_CHECKS)


# --------------------------------------------------------------------------- current state


def _get_current(backend, app: str) -> dict[str, Any] | None:
    raw = backend.get(f"verified/{app}/current.json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def current_version(app: str, cfg=None) -> str | None:
    """RESOLVED 阶段查"当前已发布版本"（release.type 判定与覆盖保护共用同一事实源）。"""
    from .backend import make_backend
    from .config import Config

    cfg = cfg or Config.load()
    cur = _get_current(make_backend(cfg), app)
    return str(cur["app_version"]) if cur and cur.get("app_version") else None


def may_update_current(
    backend,
    app: str,
    candidate_version: str,
    candidate_run_id: str,
    strategy: str,
    force: bool = False,
) -> tuple[bool, str]:
    """版本覆盖保护（workflow-state-machine.md §5）。"""
    cur = _get_current(backend, app)
    if not cur:
        return True, "尚无 current.json"
    if force:
        return True, f"force=true（{cur.get('app_version')} -> {candidate_version}）"
    cur_v, cur_run = str(cur.get("app_version") or ""), str(cur.get("verification_run_id") or "0")
    a, b = parse_semver(candidate_version), parse_semver(cur_v)
    if a and b and strategy in ("release_tag", "semver_latest"):
        if a >= b:
            return True, f"semver {candidate_version} >= 当前 {cur_v}"
        return False, f"拒绝回退：候选 {candidate_version} < 当前 {cur_v}"
    try:
        newer = int(candidate_run_id) > int(cur_run)
    except ValueError:
        newer = False
    if newer:
        return True, f"非 semver 版本 {candidate_version}，run {candidate_run_id} 较新于 {cur_run}"
    return False, f"拒绝覆盖：版本不可 semver 比较且 run {candidate_run_id} 不新于 {cur_run}"


@dataclass
class PublishResult:
    checks: dict[str, bool] = field(default_factory=dict)
    verification_id: str = ""
    committed_ready: bool = False
    current_written: bool = False
    notes: list[str] = field(default_factory=list)


def _strip_scratch(manifest: dict[str, Any]) -> dict[str, Any]:
    """Drop pipeline-internal keys (prefixed `_`) — versions/*.json must equal the contract."""
    return {k: v for k, v in manifest.items() if not k.startswith("_")}


def _put_json(backend, key: str, payload: dict[str, Any]) -> None:
    backend.put(key, json.dumps(payload, ensure_ascii=False, indent=2).encode() + b"\n")


def publish(
    backend,
    cfg,
    manifest: dict[str, Any],
    screenshots_dir: Path,
    report_html: str,
    force: bool = False,
    retries: int = 3,
) -> PublishResult:
    app = manifest["app"]
    app_version = manifest["app_version"]
    strategy = str(manifest.get("_strategy") or "release_tag")
    ver_key = f"verified/{app}/versions/{app_version}.json"
    result = PublishResult(verification_id=manifest["verification_id"])

    local_failed = [c for c in LOCAL_CHECKS if not manifest["checks"].get(c)]
    if local_failed:
        result.notes.append(f"P0 门禁未过，PUBLISHING 不开始（R2/磁盘零写入）：{local_failed}")
        result.checks = dict(manifest["checks"])
        return result

    def serialize() -> dict[str, Any]:
        out = _strip_scratch(manifest)
        out["website"] = _strip_scratch(manifest["website"])
        return out

    def placeholder() -> dict[str, Any]:
        out = serialize()
        for c in UPLOAD_CHECKS:
            out["checks"][c] = False
        return out

    # ---------------- P1: placeholder record (never claim an upload we haven't done)
    # versions/{app_version}.json 以版本为键：同一版本重新验证 = 覆盖该记录，
    # seq 只用于区分不同次验证的 verification_id（契约 §2）。
    existing = backend.get(ver_key)
    notes: list[str] = []
    if existing:
        prev = json.loads(existing)
        recorded = prev.get("verification_id") or ""
        if str(prev.get("verification_run_id") or "") != str(manifest.get("verification_run_id") or ""):
            _rename_id(manifest, _seq_of(recorded) + 1)
            notes.append(
                f"该版本已由 run {prev.get('verification_run_id')} 验证过（{recorded}）"
                f"→ 本次 verification_id = {manifest['verification_id']}"
            )
        else:
            notes.append(f"同一 run 重试，沿用 {recorded}")
    _put_json(backend, ver_key, placeholder())
    manifest["checks"]["verification_manifest_uploaded"] = backend.exists(ver_key)

    # ---------------- P2: screenshots + report
    shots = manifest["artifacts"]["screenshots"]
    for s in shots:
        src = Path(screenshots_dir) / s["file"]
        if src.exists():
            backend.put(screenshot_key(app, app_version, s["file"]), src.read_bytes(), "image/png")
        else:
            notes.append(f"缺少本地截图 {src}")
    vid = manifest["verification_id"]
    report_key = f"reports/{vid}.html"
    backend.put(report_key, report_html.encode("utf-8"), "text/html; charset=utf-8")
    url = report_url(cfg, vid)
    manifest["artifacts"]["report_url"] = url
    manifest["website"]["report_url"] = url

    # ---------------- P3: probe — the only honest source for the upload checks
    probes: dict[str, bool] = {}
    for attempt in range(1, retries + 1):
        probes = {
            "screenshots": bool(shots) and all(
                backend.exists(screenshot_key(app, app_version, s["file"])) for s in shots
            ),
            "report": backend.exists(report_key),
            "manifest": backend.exists(ver_key),
        }
        if all(probes.values()):
            break
        notes.append(f"P3 探测未通过（第 {attempt} 次）：{probes}")
    manifest["checks"]["screenshots_uploaded"] = bool(probes.get("screenshots"))
    manifest["checks"]["report_uploaded"] = bool(probes.get("report"))
    manifest["checks"]["verification_manifest_uploaded"] = bool(probes.get("manifest"))

    if not all(probes.values()):
        _put_json(backend, ver_key, placeholder())
        result.notes.extend(notes)
        result.notes.append("P3 未通过 → 不写 current.json（按 TRANSIENT 重试，官网无损）")
        result.checks = dict(manifest["checks"])
        return result

    # ---------------- P4: final record, nine checks truthful
    result.committed_ready = all(manifest["checks"][c] for c in CHECKS)
    if result.committed_ready:
        # build 时上传类 check 尚为 false，status 被算成 pending；发布成立后必须是 verified
        manifest["website"]["status"] = "verified"
    _put_json(backend, ver_key, serialize())
    if not backend.exists(ver_key):
        result.notes.append("P4 重写失败 → 不提交")
        result.checks = dict(manifest["checks"])
        return result

    # ---------------- P5: commit point
    ok, why = may_update_current(
        backend, app, app_version, str(manifest.get("verification_run_id") or "0"), strategy, force
    )
    if not ok:
        result.notes.extend(notes + [f"版本覆盖保护：不更新 current.json —— {why}"])
        result.checks = dict(manifest["checks"])
        return result
    _put_json(backend, f"verified/{app}/current.json", serialize()["website"])
    _update_index(backend, app, manifest)
    result.current_written = True
    result.committed = True
    result.notes.extend(notes + [why])
    result.checks = dict(manifest["checks"])
    log(f"PUBLISHED {vid} -> current.json + index.json（{why}）")
    return result


def _update_index(backend, app: str, manifest: dict[str, Any]) -> None:
    """verified/index.json — the website's only way to enumerate apps (§2.1)."""
    key = "verified/index.json"
    raw = backend.get(key)
    index = json.loads(raw) if raw else {"schema_version": "1.0", "apps": []}
    w = manifest["website"]
    entry = {
        "app": app,
        "app_version": manifest["app_version"],
        "verification_id": manifest["verification_id"],
        "status": w["status"],
        "health": w["health"],
        "verified_at": manifest["verified_at"],
    }
    index["apps"] = sorted(
        [a for a in index.get("apps", []) if a.get("app") != app] + [entry],
        key=lambda a: a["app"],
    )
    index["generated_at"] = utcnow()
    _put_json(backend, key, index)


def _seq_of(vid: str) -> int:
    try:
        return int(vid.rsplit("-", 1)[-1])
    except ValueError:
        return 1


def _rename_id(manifest: dict[str, Any], seq: int) -> None:
    new = manifest["verification_id"][: -3] + f"{seq:03d}"
    manifest["verification_id"] = new
    manifest["website"]["verification_id"] = new
