"""Publish targets. Exactly one backend is active at a time (repo-structure.md §4.2.1).

Key layout (shared by both backends, identical file shapes):
    verified/index.json
    verified/{app}/current.json
    verified/{app}/versions/{app_version}.json
    screenshots/{app}/{app_version}/{slug}.png
    reports/{verification_id}.html
    platform/platform-contract-{region}-{arch}.json
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class Backend(Protocol):
    name: str

    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> None: ...

    def exists(self, key: str) -> bool: ...

    def get_with_etag(self, key: str) -> tuple[bytes | None, str | None]: ...

    def put_if_match(self, key: str, data: bytes, etag: str | None) -> bool: ...


class DirBackend:
    """Local fixtures: same shapes as R2, used while R2 is not wired up."""

    name = "dir"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        # 纵深防御：键片段在调用侧已清洗（sanitize_for_id），这里再断言解析后的
        # 路径仍在根目录内，挡住任何 `../` 之类的穿越键。
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root.resolve()):
            raise ValueError(f"对象键越出后端根目录：{key!r}")
        return p

    def get(self, key: str) -> bytes | None:
        p = self._p(key)
        return p.read_bytes() if p.exists() else None

    def get_with_etag(self, key: str) -> tuple[bytes | None, str | None]:
        data = self.get(key)
        if data is None:
            return None, None
        # 本地无对象级 ETag，用内容哈希充当：与 R2 的 If-Match 语义一致（内容变即失配）。
        import hashlib

        return data, hashlib.sha256(data).hexdigest()

    def put_if_match(self, key: str, data: bytes, etag: str | None) -> bool:
        if etag is not None and self.get_with_etag(key)[1] != etag:
            return False
        self.put(key, data)
        return True

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def exists(self, key: str) -> bool:
        p = self._p(key)
        return p.exists() and p.stat().st_size > 0

    def mirror_from(self, src_dir: Path) -> None:
        """Import an existing fixtures tree (used by tests / re-runs)."""
        for f in Path(src_dir).rglob("*"):
            if f.is_file():
                rel = f.relative_to(src_dir)
                self.put(str(rel), f.read_bytes())


class R2Backend:
    """Cloudflare R2 over its S3-compatible API (needs R2_ACCESS_KEY_ID / SECRET)."""

    name = "r2"

    def __init__(self, bucket: str, endpoint: str = "", region: str = "auto"):
        import os

        import boto3

        ak = os.environ.get("R2_ACCESS_KEY_ID") or ""
        sk = os.environ.get("R2_SECRET_ACCESS_KEY") or ""
        if not (bucket and ak and sk):
            raise RuntimeError(
                "R2 后端需要 R2_BUCKET_NAME + R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY"
            )
        endpoint = endpoint or f"https://{os.environ.get('CF_ACCOUNT_ID','')}.s3.cloudflare.com"
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            region_name=region,
        )
        self.bucket = bucket

    def get(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:  # noqa: BLE001 - S3 surfaces 404 as ClientError
            if "NoSuchKey" in type(exc).__name__ or "404" in str(exc):
                return None
            raise

    def get_with_etag(self, key: str) -> tuple[bytes | None, str | None]:
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read(), (resp.get("ETag") or "").strip('"') or None
        except Exception as exc:  # noqa: BLE001 - S3 surfaces 404 as ClientError
            if "NoSuchKey" in type(exc).__name__ or "404" in str(exc):
                return None, None
            raise

    def put_if_match(self, key: str, data: bytes, etag: str | None) -> bool:
        """条件写（R2 支持 S3 If-Match / If-None-Match:*）。

        返回 False 仅表示前置条件失配（对象已被并发方改写 / 已存在），
        调用方应重读-重合-重试；其他错误照常抛出。
        """
        kwargs: dict = dict(Bucket=self.bucket, Key=key, Body=data,
                            ContentType="application/json")
        if etag is not None:
            kwargs["IfMatch"] = f'"{etag}"'
        else:
            kwargs["IfNoneMatch"] = "*"  # 只允许首发，挡住两个首次写者都成功
        try:
            self.s3.put_object(**kwargs)
            return True
        except Exception as exc:  # noqa: BLE001
            if "PreconditionFailed" in type(exc).__name__ or "412" in str(exc) or "Conditional" in str(exc):
                return False
            raise

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:  # noqa: BLE001 - S3 surfaces 404 as ClientError
            # 只把"对象不存在"当作 False；限流/网络错误必须上抛——
            # exists() 是 P3 探测与 Publish Gate 复核的判据，瞬时故障被误判成
            # "不存在"会把一次基础设施抖动报成门禁失败。
            if "NoSuchKey" in type(exc).__name__ or "404" in str(exc) or "Not Found" in str(exc):
                return False
            raise


def make_backend(cfg) -> Backend:
    kind = cfg.verified_backend
    if kind == "dir":
        return DirBackend(cfg.output_dir)
    if kind == "r2":
        return R2Backend(cfg.r2_bucket, cfg.r2_endpoint)
    raise RuntimeError(f"VERIFIED_BACKEND 只允许 dir|r2，实为 {kind!r}")


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(Path(src).rglob("*")):
        if f.is_file():
            target = dst / f.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
