"""Load config/platform.yaml + config/verify.yaml with environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass
class Config:
    root: Path
    platform: dict[str, Any]
    verify: dict[str, Any]

    # ---- platform identity -------------------------------------------------
    @property
    def region(self) -> str:
        return os.environ.get("AWS_REGION") or self.platform["region"]

    @property
    def architecture(self) -> str:
        return self.platform["architecture"]

    @property
    def base_ami_source(self) -> str:
        return os.environ.get("BASE_AMI_SOURCE") or self.platform["base_ami_source"]

    @property
    def reverify_interval_days(self) -> int:
        return int(self.platform.get("reverify_interval_days", 30))

    def ami_ssm_parameter(self) -> str:
        if self.base_ami_source == "public":
            return self.platform["public_ami"]["ssm_parameter"]
        return self.platform["custom_ami"]["ssm_parameter"]

    # ---- publish backend ---------------------------------------------------
    @property
    def verified_backend(self) -> str:
        return (os.environ.get("VERIFIED_BACKEND") or self.verify.get("verified_backend") or "dir").strip()

    @property
    def output_dir(self) -> Path:
        raw = os.environ.get("VERIFIED_OUTPUT_DIR") or self.verify.get("output_dir") or "data"
        p = Path(raw)
        return p if p.is_absolute() else self.root / p

    @property
    def r2_bucket(self) -> str:
        return os.environ.get("R2_BUCKET_NAME") or (self.verify.get("r2") or {}).get("bucket") or ""

    @property
    def r2_public_base_url(self) -> str:
        return (
            os.environ.get("R2_PUBLIC_BASE_URL")
            or (self.verify.get("r2") or {}).get("public_base_url")
            or ""
        ).rstrip("/")

    @property
    def r2_endpoint(self) -> str:
        return os.environ.get("R2_ENDPOINT") or (self.verify.get("r2") or {}).get("endpoint") or ""

    @property
    def registry_mirror(self) -> str:
        return (os.environ.get("CORENOVA_REGISTRY_MIRROR") or self.verify.get("registry_mirror") or "").strip().rstrip("/")

    @property
    def site_repo(self) -> str:
        return os.environ.get("SITE_REPO") or self.verify.get("site_repo") or ""

    @property
    def run_opts(self) -> dict[str, Any]:
        return self.verify.get("run") or {}

    @staticmethod
    def load(root: Path | None = None) -> "Config":
        root = root or REPO_ROOT
        return Config(
            root=root,
            platform=_yaml(root / "config" / "platform.yaml"),
            verify=_yaml(root / "config" / "verify.yaml"),
        )
