#!/usr/bin/env python3
"""RESOLVED 阶段单步：解析上游版本 / 精确镜像 tag / 不可变 digest。

用法：
    python scripts/verify/resolve_version.py --app ghost
    python scripts/verify/resolve_image.py --app ghost --version v6.61.0
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from corenova import appspec, resolver  # noqa: E402
from corenova.appspec import render_image_ref  # noqa: E402
from corenova.config import Config  # noqa: E402


def main(kind: str) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--version")
    args = ap.parse_args()
    cfg = Config.load()
    spec = appspec.load(args.app, cfg.root)

    if kind == "version":
        r = resolver.pick_release(spec, wanted=args.version)
        print(json.dumps({
            "app_version": r.app_version, "release_tag": r.release_tag,
            "source_revision": r.source_revision, "release_type": r.release_type,
            "type_evidence": r.type_evidence, "previous_version": r.previous_version,
            "image_reference": render_image_ref(spec, r.app_version),
        }, ensure_ascii=False, indent=2))
        return 0

    version = args.version or resolver.pick_release(spec).app_version
    ref = render_image_ref(spec, version)
    img = resolver.resolve_digest(ref, cfg.registry_mirror)
    print(json.dumps({
        "requested": ref, "image_ref": img.image_ref, "pull_ref": img.pull_ref,
        "digest": img.digest, "manifest_digest": img.manifest_digest,
        "registry_host": img.host, "platform": "linux/amd64",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    name = pathlib.Path(__file__).stem
    raise SystemExit(main("version" if name == "resolve_version" else "image"))
