#!/usr/bin/env python3
"""校验 apps/{app}.yaml 是否满足 app-schema.md §5 十五条 + app-profiles 阶梯。

用法：
    python scripts/verify/validate_app_schema.py --app ghost
    python scripts/verify/validate_app_schema.py --all
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from corenova import appspec  # noqa: E402
from corenova.config import Config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    cfg = Config.load()
    names = appspec.all_apps(cfg.root) if args.all else [args.app or ""]
    if not [n for n in names if n]:
        print("必须指定 --app 或 --all", file=sys.stderr)
        return 2

    failed = False
    for name in names:
        if not name:
            continue
        try:
            spec = appspec.load(name, cfg.root)
        except FileNotFoundError as exc:
            print(f"FAIL {name}: {exc}")
            failed = True
            continue
        errors = appspec.validate(spec, cfg.root, cfg.region)
        if errors:
            failed = True
            print(f"FAIL {name}（{len(errors)} 处违反契约）")
            for e in errors:
                print(f"  - {e}")
        else:
            # resources() 依赖合法 app_type/size，必须在通过校验后才调用，
            # 否则畸形 schema 会在这里抛 KeyError/ValueError 而不是打印违规清单
            instance, disk = spec.resources()
            print(
                f"OK   {name}: app_type={spec.app_type} size={spec.size()[0]} "
                f"-> {instance}/{disk}GB, port={spec.container_port}, "
                f"scenarios={[s['slug'] for s in spec.scenarios]}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
