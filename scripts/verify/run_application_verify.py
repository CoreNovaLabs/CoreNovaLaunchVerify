#!/usr/bin/env python3
"""Application Verification 主入口（默认无 AWS）。

    python scripts/verify/run_application_verify.py --app ghost
    python scripts/verify/run_application_verify.py --app ghost --version v6.61.0 --no-publish

流程与门禁：corenova/pipeline.py（verify-gate-design.md §4 / verification-manifest.md §6）。
退出码：0=PUBLISHED 或 VERIFIED；2=FAILED（已按分类写失败台账）。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from corenova.pipeline import main  # noqa: E402

if __name__ == "__main__":
    main()
