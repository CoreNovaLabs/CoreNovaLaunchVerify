#!/usr/bin/env python3
"""为 publish-site.yml 组装 repository_dispatch(verified-update) 的 payload（薄 CLI）。

    python scripts/verify/publish_site_payload.py --app ghost --payload-file /tmp/payload.json
    python scripts/verify/publish_site_payload.py            # 全部已发布应用

payload 形状 = repo-structure.md §4.1；`client_payload` 只是提示，前端数据一律从生效后端拉。

本步同时是 **Publish Gate 的复核点**：只有 `verified/{app}/current.json` 存在才等于"九项 checks
全真"（verification-manifest.md §6，P5 是唯一提交点）。没有 current.json 的应用一律拒绝通知前端
——否则会出现"网站重建出一个没验证过的 app"。设计文档 §5 明列为反模式。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from corenova.backend import make_backend  # noqa: E402
from corenova.config import Config  # noqa: E402
from corenova.util import log  # noqa: E402


def build(cfg: Config, wanted: str) -> tuple[dict[str, Any], list[str]]:
    backend = make_backend(cfg)
    raw = backend.get("verified/index.json")
    index = json.loads(raw) if raw else {"apps": []}
    published = {str(a.get("app")): a for a in index.get("apps") or []}

    targets = [wanted] if wanted else sorted(published)
    if not targets:
        raise ValueError("生效后端里没有任何已发布应用（index.json 为空）→ 不发 dispatch")

    apps, missing = [], []
    for app in targets:
        if not backend.exists(f"verified/{app}/current.json"):
            missing.append(app)
        else:
            apps.append(app)
    if missing:
        raise ValueError(f"这些应用没有 current.json（未通过 Publish Gate）→ 拒绝通知前端：{missing}")

    head = published.get(apps[0]) or {}
    # 单 app 时 id/version 精确；多 app 时 apps 是全量清单，id/version 取首条（仅提示用途）
    return (
        {
            "event_type": "verified-update",
            "client_payload": {
                "apps": apps,
                "verification_id": str(head.get("verification_id") or ""),
                "app_version": str(head.get("app_version") or ""),
            },
        },
        apps,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="组装 verified-update payload（并复核 Publish Gate）")
    ap.add_argument("--app", default="", help="只通知这一个应用；留空 = index.json 全部已发布应用")
    ap.add_argument("--payload-file", required=True, help="把 payload JSON 写到该文件供 curl --data @ 使用")
    args = ap.parse_args(argv)

    cfg = Config.load()
    try:
        payload, apps = build(cfg, args.app.strip())
    except (ValueError, FileNotFoundError) as exc:
        print(f"::error::{exc}")
        return 1

    path = pathlib.Path(args.payload_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log(f"payload 已写入 {path}: {json.dumps(payload, ensure_ascii=False)}")

    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as fh:
            fh.write(f"apps={json.dumps(apps)}\nrepo={cfg.site_repo}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
