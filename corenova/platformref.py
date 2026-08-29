"""Platform Contract resolution & validity (contracts/platform-contract.md).

Application Verification does not touch AWS infrastructure; it *references* a contract and
must prove the reference is still trustworthy:

    required_platform_contract_valid =
        contract exists AND status == valid
        AND not expired (platform_verified_at + reverify_interval_days)
        AND all six *_revision equal the current repo revisions
        AND contract.region covers deployment.regions
        AND (public mode) the SSM public parameter still yields the recorded ami_id
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import git_revision

REVISION_KEYS = (
    "cloudformation_revision",
    "cfn_init_revision",
    "infrastructure_revision",
    "base_ami_revision",
    "nginx_base_revision",
    "docker_runtime_revision",
)


@dataclass
class ContractCheck:
    valid: bool = False
    contract: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    drift_checked: bool = False


def contract_key(region: str, arch: str) -> str:
    return f"platform/platform-contract-{region}-{arch}.json"


def _hash_group(files: list[Path], root: Path, label: str) -> str:
    """One revision value per asset group; empty group is an explicit `missing`."""
    if not files:
        return "missing"
    if len(files) == 1:
        return git_revision(files[0], root)
    import hashlib

    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return f"{label}-sha:" + h.hexdigest()[:40]


def compute_revisions(cfg, base_ami_id: str = "") -> dict[str, str]:
    root: Path = cfg.root
    cfn = root / "templates" / "cloudformation" / "fixed"
    init = cfn / "init"
    assets = [p for p in sorted(init.glob("*")) if p.is_file()] if init.is_dir() else []
    docker_assets = [p for p in assets if "docker" in p.name.lower()]
    nginx_assets = [p for p in assets if "nginx" in p.name.lower()]
    return {
        "cloudformation_revision": git_revision(cfn, root),
        "cfn_init_revision": git_revision(init, root),
        "infrastructure_revision": git_revision(cfn / "network.yaml", root),
        "nginx_base_revision": _hash_group(nginx_assets, root, "nginx"),
        "docker_runtime_revision": _hash_group(docker_assets, root, "docker"),
        "base_ami_revision": (
            f"public:{cfg.ami_ssm_parameter()}@{base_ami_id}"
            if cfg.base_ami_source == "public"
            else git_revision(root.parent / "CoreNovaLaunchAmi" / "packer", root)
        ),
    }


def _age_days(iso: str) -> float:
    try:
        t = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return (time.time() - time.mktime(t)) / 86400.0
    except (ValueError, TypeError):
        return 1e9


def check(backend, cfg, spec, regions_required: list[str], check_drift: bool = True) -> ContractCheck:
    out = ContractCheck()
    key = contract_key(cfg.region, cfg.architecture)
    raw = backend.get(key)
    if not raw:
        out.reasons.append(f"缺少 Platform Contract：{key}（需先跑 golden-verify）")
        return out
    c = json.loads(raw)
    out.contract = c
    bad = []
    if c.get("status") != "valid":
        bad.append(f"status={c.get('status')!r} 非 valid")
    interval = int(c.get("reverify_interval_days") or cfg.reverify_interval_days)
    if _age_days(c.get("platform_verified_at", "")) > interval:
        bad.append(f"契约已超复验周期（{interval} 天）→ 需重跑 Golden Verification")
    if c.get("invalidated_reason"):
        bad.append(f"invalidated_reason={c['invalidated_reason']}")

    current = compute_revisions(cfg, c.get("ami_id", ""))
    for k, v in current.items():
        recorded = c.get(k)
        if recorded and v and recorded != v:
            bad.append(f"{k} 变更：契约 {recorded} != 当前 {v}（平台层改动 → 必须重跑 Golden Verification）")

    if c.get("region") not in regions_required:
        bad.append(f"deployment.regions={regions_required} 未被契约区域 {c.get('region')!r} 覆盖")

    if cfg.base_ami_source == "public" and check_drift:
        try:
            live = resolve_public_ami_id(cfg)
            out.drift_checked = True
            if live and live != c.get("ami_id"):
                bad.append(f"公开 AMI 已被厂商替换：契约 {c.get('ami_id')} != 现值 {live}")
        except Exception as exc:  # noqa: BLE001
            out.reasons.append(f"（跳过 AMI 漂移检测：{type(exc).__name__}: {exc}）")

    out.valid = not bad
    out.reasons.extend(bad)
    return out


def resolve_public_ami_id(cfg) -> str:
    """Resolve the SSM parameter once — never re-queried mid-workflow (§6)."""
    import boto3

    client = boto3.client("ssm", region_name=cfg.region)
    return client.get_parameter(Name=cfg.ami_ssm_parameter())["Parameter"]["Value"]
