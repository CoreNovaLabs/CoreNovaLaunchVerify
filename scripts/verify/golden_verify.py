#!/usr/bin/env python3
"""AWS Golden Verification 主入口（平台层，会产生 AWS 费用）。

    python scripts/verify/golden_verify.py --check          # 零 AWS 调用的静态门禁
    python scripts/verify/golden_verify.py --dry-run        # 零 AWS 调用的全流程计划 + 契约预览
    python scripts/verify/golden_verify.py                  # 真跑：建 canary 栈、探针、写契约
    python scripts/verify/golden_verify.py --drift          # 只比对契约漂移（免费只读 SSM）
    python scripts/verify/golden_verify.py --sync-init      # init/*.sh → app.yaml → canary.yaml

流程与硬规则：corenova/golden.py（verify-gate-design.md §5 / platform-contract.md §2/§5/§6）。
退出码：0=契约 valid；2=探针未全通过（已写 invalid 契约）；3=流程异常；4=canary 清理未确认。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from corenova.golden import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
