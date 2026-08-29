#!/usr/bin/env python3
"""失败诊断（规则式，非 AI）——AI 生成测试脚本尚未接入，当前为规则式诊断。

为什么是规则而不是模型：白名单外的改动必须**可证明地**被拒绝（state-machine §6），
而概率性输出无法给出该保证；同时本仓不允许在 CI 里调任何外部 AI API（密钥面 + 不可复现）。
因此这里用"分类器 + 日志特征"给出结构化诊断与建议范围；将来接入 AI 生成时，
只需替换 _diagnose() 的实现，白名单校验与退出码契约保持不变即可。

    python scripts/ai-test/analyze_failure.py --run-dir data/runs/<verification_id>
    python scripts/ai-test/analyze_failure.py --vid ghost-v6.61.0-20260829-001
    python scripts/ai-test/analyze_failure.py --app ghost --classification TEST

输入 = 一次失败运行的 ``data/runs/{vid}/state.json``（corenova/pipeline.py::_write_state 落盘）：
    {"summary": {...}, "manifest": {...}}

输出 = 结构化诊断 JSON（stdout + 可选 --out-file / job summary）。只读工具：
    classification / failed_stage / failed_check / suspected_causes[] /
    suggested_paths[]（已按白名单裁剪）/ disallowed_suggestions[] / actions / next_step

铁律（verify-gate-design.md §8）：
- 只允许建议 apps/{app}/tests/** 与 apps/{app}.yaml 内的改动；白名单外路径直接拒绝并说明理由。
- 不自动开 PR、不改代码、不重试：FIX_PR 需要人 review，MANUAL_REQUIRED 需要人处理。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from corenova.config import Config  # noqa: E402
from corenova.failure import MAX_ATTEMPTS, classify  # noqa: E402
from corenova.publish import LOCAL_CHECKS  # noqa: E402
from corenova.util import log  # noqa: E402

# state-machine §8 禁止清单（这些路径出现在建议里必须被拒绝）
DISALLOWED_PATTERNS = (
    ".github/workflows/",
    "templates/cloudformation/",
    "packer/",
    "infra/",
    "corenova/",
    "scripts/",
    "tests/",          # 仓库级测试目录：不是某个 app 的预写测试
    "config/",
    "docs/",
    "contracts/",
)

CHECK_TO_STAGE = {
    "compose_started": "VERIFYING",
    "container_healthy": "VERIFYING",
    "health_check_passed": "VERIFYING",
    "tests_passed": "VERIFYING",
    "screenshots_generated": "VERIFYING",
    "required_platform_contract_valid": "RESOLVED",
    "publish_commit": "PUBLISHING",
}


class PathNotAllowed(RuntimeError):
    """建议改动落在 AI 白名单之外。"""


# 日志里出现的越权路径要"显式拒绝并说明"，而不是静默丢掉（否则人看不到被拦了什么）
DISALLOWED_LOOSE_RE = re.compile(
    r"(?:^|[\s\"'`(=:])(\.?/?((?:\.github/workflows|templates/cloudformation|packer|infra|corenova|scripts|tests|config|docs|contracts)/[^\s\"')`,]+))",
    re.M,
)


def _forbidden_reason(path: str) -> str:
    return (
        f"{path!r} 属禁止清单（state-machine §6 / verify-gate-design.md §8）："
        "工作流、CFN、packer、infra、IAM/SG/网络与生产部署逻辑只能人工经 PR review 修改。"
    )


def scan_disallowed(text: str) -> list[dict[str, Any]]:
    """从日志文本里挑出被提及的白名单外文件，逐条给出拒绝理由。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in DISALLOWED_LOOSE_RE.finditer(text or ""):
        path = m.group(2).strip()
        if path in seen:
            continue
        seen.add(path)
        out.append({"raw_path": path, "reason": _forbidden_reason(path)})
    return out


def allowed_prefixes(app: str) -> tuple[str, ...]:
    """白名单：默认允许 apps/{app}/tests/**；视设计允许 apps/{app}.yaml（仅应用配置）。"""
    return (f"apps/{app}/tests/", f"apps/{app}.yaml")


def assert_whitelisted(app: str, path: str) -> None:
    p = _normalize(path)
    if not p.startswith(allowed_prefixes(app)):
        raise PathNotAllowed(
            f"{path!r} 不在 AI 白名单内（只允许 apps/{app}/tests/** 与 apps/{app}.yaml）。"
            "见 verify-gate-design.md §8 / workflow-state-machine.md §6。"
        )
    # 禁止清单按"路径段"匹配，不用子串：否则 apps/ghost/tests/ 会被仓库级 tests 误伤
    for bad in DISALLOWED_PATTERNS:
        stem = bad.rstrip("/")
        if p == stem or p.startswith(bad):
            raise PathNotAllowed(f"{path!r} 命中禁止清单 {bad!r}（基础设施/工作流/平台层不得由 AI 改）")


def _normalize(path: str) -> str:
    p = str(path).strip().lstrip("./")
    while p.startswith("/"):
        p = p[1:]
    return p


# --------------------------------------------------------------------------- evidence extraction
def load_state(cfg: Config, vid: str) -> dict[str, Any]:
    path = cfg.output_dir / "runs" / vid / "state.json"
    if not path.exists():
        raise FileNotFoundError(f"缺少运行状态文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def latest_vid_for_app(cfg: Config, app: str) -> str | None:
    runs = sorted((cfg.output_dir / "runs").glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in runs:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        name = str((doc.get("manifest") or {}).get("app") or (doc.get("summary") or {}).get("app") or "")
        if name == app:
            return p.parent.name
    return None


def evidence_of(doc: dict[str, Any]) -> dict[str, Any]:
    """从 state.json 里抽出判定所需的最小事实集。"""
    summary = doc.get("summary") or {}
    manifest = doc.get("manifest") or {}
    checks = dict(manifest.get("checks") or summary.get("checks") or {})
    ev = manifest.get("_evidence") or {}
    tests_detail = str(ev.get("tests") or summary.get("tests_detail") or "")
    assertion = ev.get("version_assertion") or {}
    probe = ev.get("health_probe") or {}
    log_tail = "\n".join(
        [
            str(summary.get("detail") or ""),
            str(summary.get("report_path") or ""),
            tests_detail,
            str(assertion.get("detail") or ""),
            str(probe.get("detail") or ""),
            *([str(r) for r in (summary.get("notes") or [])]),
        ]
    )
    failed_check = str(summary.get("failed_check") or "")
    if not failed_check:
        truthy = [c for c in LOCAL_CHECKS if checks and not checks.get(c)]
        failed_check = truthy[0] if truthy else str(summary.get("failed_check") or "unknown")
    stage = str(summary.get("failed_stage") or CHECK_TO_STAGE.get(failed_check, "VERIFYING"))
    return {
        "app": str(manifest.get("app") or summary.get("app") or ""),
        "app_version": str(manifest.get("app_version") or summary.get("app_version") or ""),
        "verification_id": str(manifest.get("verification_id") or summary.get("verification_id") or ""),
        "attempts": int(summary.get("attempts") or 1),
        "status": str(summary.get("status") or ""),
        "checks": checks,
        "failed_check": failed_check,
        "failed_stage": stage,
        "container_state": str(ev.get("container_state") or ""),
        "probe_status": probe.get("status"),
        "probe_detail": str(probe.get("detail") or ""),
        "assertion_ok": assertion.get("ok"),
        "assertion_actual": str(assertion.get("actual") or ""),
        "assertion_detail": str(assertion.get("detail") or ""),
        "tests_detail": tests_detail,
        "log_tail": log_tail,
        "report_url": str((manifest.get("artifacts") or {}).get("report_url") or ""),
        "workflow_run_url": str((manifest.get("artifacts") or {}).get("workflow_run_url") or ""),
        "platform_reasons": summary.get("platform_reasons") or [],
    }


# --------------------------------------------------------------------------- rule table
# (regex, 疑似原因, 白名单内建议路径模板, 置信度)
TEST_RULES: list[tuple[str, str, str, float]] = [
    (r"strict mode violation|resolved to \d+ elements",
     "selector 命中多个元素，Playwright strict mode 断言失败",
     "apps/{app}/tests/", 0.85),
    (r"waiting for selector|waiting for locator|locator\(.*\) not found|no element found",
     "页面结构/DOM 变化导致 selector 失效（上游 UI 改版）",
     "apps/{app}/tests/", 0.8),
    (r"expect\(|assert .*visible|to_be_visible|to_have_text|to_contain_text",
     "断言的文案或可见性与新版本实际渲染不符",
     "apps/{app}/tests/", 0.75),
    (r"Timeout \d+ms exceeded|page\.goto|net::ERR_",
     "场景 URL 在新版本不存在或加载超时（路由变更）",
     "apps/{app}/tests/", 0.7),
    (r"FAILED apps/\S+::\S+",
     "预写用例失败（详见 pytest 输出末尾）",
     "apps/{app}/tests/", 0.6),
]

APP_RULES: list[tuple[str, str, str, float]] = [
    (r"version_assertion|不匹配（exact）|期望\s*['\"]?v?\d+\.\d+",
     "容器自报版本与被解析 app_version 不一致 → tag 模板或断言 expected 需对齐",
     "apps/{app}.yaml", 0.9),
    (r"/ghost/|admin|setup|signin",
     "后台/初始化路径在新版本迁移（多为 setup 流程变化）→ 先测真实可达路径再改 scenario url",
     "apps/{app}/tests/", 0.6),
]

# health_check_passed 的两种语义必须分开：端口可达但 4xx 属“注册错了”（改 yaml），
# 完全连不上/超时才可能是应用真起不来（人工）。
PROBE_RULES: list[tuple[str, str, str, float]] = [
    (r"HTTP 40[13]|鉴权|未登录|unauthorized|forbidden",
     "探针打到了需要鉴权的端点：应用其实已就绪，属 health_check.endpoint 选错",
     "apps/{app}.yaml", 0.9),
    (r"HTTP 404",
     "health_check.endpoint 在该版本不存在（路径变更）",
     "apps/{app}.yaml", 0.85),
    (r"Connection refused|timed out|timeout|ReadTimeout|URLError",
     "端口始终不可达：应用启动/迁移阶段就失败，需看容器日志定位",
     "", 0.7),
]


def _scan(rules: list[tuple[str, str, str, float]], text: str, app: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for pattern, cause, path_tpl, confidence in rules:
        m = re.search(pattern, text, re.I | re.S)
        if not m:
            continue
        raw_path = path_tpl.format(app=app) if path_tpl else ""
        entry: dict[str, Any] = {
            "cause": cause,
            "matched": m.group(0)[:160].replace("\n", " "),
            "confidence": confidence,
            "raw_path": raw_path,
        }
        if raw_path:
            try:
                assert_whitelisted(app, raw_path)
                entry["suggested_path"] = _normalize(raw_path)
            except PathNotAllowed as exc:
                entry["suggested_path"] = ""
                entry["rejected"] = str(exc)
        else:
            entry["suggested_path"] = ""
        hits.append(entry)
    return hits


def _classify_evidence(ev: dict[str, Any], err_like: str) -> str:
    """沿用 pipeline 的分类器口径，再把"探针 4xx 且版本断言失败"归到 APPLICATION。"""
    exc: BaseException | None = None
    if err_like.strip():
        exc = RuntimeError(err_like[:500])
    cls = classify(ev["failed_stage"], ev["failed_check"], exc)
    if ev["failed_check"] == "health_check_passed" and cls == "APPLICATION":
        probe = f"{ev['probe_detail']} {ev['assertion_detail']}"
        if re.search(r"HTTP 4\d\d", probe):
            # 应用已应答 → 不是"起不来"，而是注册/版本绑定不对；仍属应用配置层，交 FIX_PR
            cls = "APPLICATION"
    return cls


def diagnose(ev: dict[str, Any]) -> dict[str, Any]:
    app = ev["app"] or "<app>"
    text = "\n".join([ev["log_tail"], ev["tests_detail"], ev["assertion_detail"], ev["probe_detail"]])
    check = ev["failed_check"]
    stage = ev["failed_stage"]

    causes: list[dict[str, Any]] = []
    notes: list[str] = []

    if stage == "PUBLISHING" or check in ("publish_commit", "screenshots_uploaded", "report_uploaded"):
        causes += _scan([], text, app)
        notes.append(
            "PUBLISHING 失败按 §9.1 只允许 TRANSIENT 退避：P1–P4 任一步失败都不会写 current.json，"
            "官网无损。补投用 scripts/verify/publish.py（幂等，同一 verification_id）。"
        )
        # 不硬编码 TRANSIENT：未知发布失败仍按分类器落到 MANUAL_REQUIRED（§4）
        cls = _classify_evidence(ev, text)
    elif check == "required_platform_contract_valid":
        cls = "INFRASTRUCTURE"
        reasons = ev.get("platform_reasons") or []
        notes.append(
            "平台契约失效（缺失/过期/revision 变更/公开 AMI 漂移）→ 唯一出路是重跑 golden-verify.yml，"
            "不得改 apps/ 绕过。"
        )
        if isinstance(reasons, list) and reasons:
            causes.append({"cause": "契约判定原因：" + "; ".join(str(r) for r in reasons)[:400],
                           "matched": "", "confidence": 0.95, "raw_path": "", "suggested_path": ""})
    elif check == "tests_passed":
        cls = "TEST"
        causes += _scan(TEST_RULES, text, app)
        if not causes:
            causes.append({"cause": "pytest 失败但未匹配到已知特征，需读报告确认",
                           "matched": "", "confidence": 0.4, "raw_path": f"apps/{app}/tests/",
                           "suggested_path": f"apps/{app}/tests/"})
    elif check == "screenshots_generated":
        cls = "TEST"
        causes += _scan(TEST_RULES, text, app)
        causes.append({"cause": "截图数量与 tests.scenarios 不齐（浏览器崩溃或 scenario url 不可达）",
                       "matched": "", "confidence": 0.6, "raw_path": f"apps/{app}/tests/",
                       "suggested_path": f"apps/{app}/tests/"})
    elif check == "health_check_passed":
        cls = _classify_evidence(ev, text)
        causes += _scan(PROBE_RULES, text, app)
        if ev["assertion_ok"] is False:
            causes += _scan(APP_RULES, ev["assertion_detail"], app)
    elif check in ("compose_started", "container_healthy"):
        cls = _classify_evidence(ev, text)
        causes += _scan(TEST_RULES, text, app)
        causes.append({"cause": f"容器未起来或未运行（state={ev['container_state'] or 'unknown'}）："
                                "先看 compose logs 与镜像 digest 是否存在",
                       "matched": "", "confidence": 0.7, "raw_path": "", "suggested_path": ""})
    else:
        cls = _classify_evidence(ev, text)
        causes += _scan(TEST_RULES + APP_RULES, text, app)

    if not causes:
        causes.append({"cause": "未匹配到已知日志特征（未知失败）→ 建议人工读报告确认",
                       "matched": "", "confidence": 0.3, "raw_path": "", "suggested_path": ""})
        notes.append("分类沿用 pipeline 的 checks 判定（§4），本工具不因缺少日志特征而改判分类。")

    suggested = sorted({c["suggested_path"] for c in causes if c.get("suggested_path")})
    rejected = [{"raw_path": c["raw_path"], "reason": c["rejected"]} for c in causes if c.get("rejected")]
    # 日志里被点名但没进建议的越权路径，同样要显式拒绝并说明
    for item in scan_disallowed(text):
        if item["raw_path"] not in {r["raw_path"] for r in rejected}:
            rejected.append(item)

    actions, next_step = _route(cls, ev["attempts"])
    return {
        "app": ev["app"],
        "app_version": ev["app_version"],
        "verification_id": ev["verification_id"],
        "failed_stage": stage,
        "failed_check": check,
        "checks": ev["checks"],
        "classification": cls,
        "attempts": ev["attempts"],
        "suspected_causes": sorted(causes, key=lambda c: -float(c.get("confidence") or 0)),
        "suggested_paths": suggested,
        "disallowed_suggestions": rejected,
        "whitelist": {
            "default_allowed": [f"apps/{app}/tests/**"],
            "design_allowed": [f"apps/{app}.yaml"],
            "forbidden": list(DISALLOWED_PATTERNS),
        },
        "actions": actions,
        "next_step": next_step,
        "notes": notes,
        "automated_fix_applied": False,
        "engine": "rule-based (AI-generated test scripts not wired up yet)",
        "evidence": {
            "container_state": ev["container_state"],
            "probe_status": ev["probe_status"],
            "assertion_ok": ev["assertion_ok"],
            "assertion_actual": ev["assertion_actual"],
            "report_url": ev["report_url"],
            "workflow_run_url": ev["workflow_run_url"],
        },
    }


def _route(cls: str, attempts: int) -> tuple[list[str], str]:
    """§4 流转：TRANSIENT ≤3 次退避重试；APPLICATION/TEST → FIX_PR；其余 → MANUAL_REQUIRED。"""
    if cls == "TRANSIENT":
        if attempts >= MAX_ATTEMPTS:
            return (
                [f"attempts 已达上限（{MAX_ATTEMPTS}）→ 台账应改判 classification:MANUAL_REQUIRED + needs-human，停止自动重试"],
                "MANUAL_REQUIRED（不再自动重试）",
            )
        return (
            [f"由 reverify-failed.yml 重新 dispatch application-verify.yml（沿用同一 verification_id，attempt {attempts + 1}/{MAX_ATTEMPTS}）"],
            "RETRY",
        )
    if cls in ("APPLICATION", "TEST"):
        return (
            [
                "人工确认后由 AI 在白名单内出修复分支并开 PR（Fixes #<issue>）",
                "PR 必须跑过 CI 并由人 review 后合并 → 再 Re-verify",
            ],
            "FIX_PR",
        )
    return (
        ["保留台账 issue + needs-human，基础设施/安全层改动必须人工"],
        "MANUAL_REQUIRED",
    )


def render_markdown(diag: dict[str, Any]) -> str:
    lines = [
        f"## 失败诊断 · `{diag['app']}`@`{diag['app_version']}`",
        "",
        f"- 分类：**{diag['classification']}** → 流转 **{diag['next_step']}**",
        f"- 失败位置：{diag['failed_stage']} / `{diag['failed_check']}`（attempts {diag['attempts']}/{MAX_ATTEMPTS}）",
        f"- verification_id：`{diag['verification_id']}`",
        "",
        "### 疑似原因（按置信度）",
        "",
    ]
    for c in diag["suspected_causes"]:
        path = c.get("suggested_path") or "—"
        lines.append(f"- [{c['confidence']:.2f}] {c['cause']}")
        if c.get("matched"):
            lines.append(f"  - 命中特征：`{c['matched']}`")
        lines.append(f"  - 建议改动：`{path}`")
    if diag["suggested_paths"]:
        lines += ["", "### 允许改动的路径（白名单内）", ""] + [f"- `{p}`" for p in diag["suggested_paths"]]
    if diag["disallowed_suggestions"]:
        lines += ["", "### 已拒绝的越权建议", ""]
        lines += [f"- `{r['raw_path']}` — {r['reason']}" for r in diag["disallowed_suggestions"]]
    lines += ["", "### 处置动作", ""] + [f"- {a}" for a in diag["actions"]]
    if diag["notes"]:
        lines += ["", "### 说明", ""] + [f"- {n}" for n in diag["notes"]]
    lines += [
        "",
        "> 本工具不自动开 PR、不改代码；白名单：`apps/<app>/tests/**`（默认）与 `apps/<app>.yaml`（视设计）。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="规则式失败诊断（AI 生成测试脚本尚未接入）")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--run-dir", help="一次失败运行的目录：data/runs/{verification_id}")
    src.add_argument("--vid", help="verification_id，等价于 --run-dir data/runs/<vid>")
    src.add_argument("--app", help="没有 run 目录时按 app 取最近一次失败运行；配合 --classification/--text 使用")
    ap.add_argument("--classification", help="无 state.json 时手工指定分类线索（如 TEST）")
    ap.add_argument("--text", help="无 state.json 时的日志文本（文件或 - 表示 stdin）")
    ap.add_argument("--out-file", help="把诊断 JSON 落到该文件")
    ap.add_argument("--summary-file", help="把 markdown 摘要落到该文件（供 job summary 使用）")
    args = ap.parse_args(argv)

    cfg = Config.load()
    try:
        if args.run_dir or args.vid:
            vid = pathlib.Path(args.run_dir).name if args.run_dir else args.vid
            doc = load_state(cfg, str(vid))
            ev = evidence_of(doc)
            diag = diagnose(ev)
        else:
            app = args.app or ""
            if not app:
                log("必须提供 --run-dir / --vid / --app 之一")
                return 2
            text = ""
            if args.text:
                if args.text == "-":
                    text = sys.stdin.read()
                else:
                    candidate = pathlib.Path(args.text)
                    # 允许直接传日志文本：CI step 里 `--text "$(...)"` 比临时文件更省事
                    text = candidate.read_text(encoding="utf-8") if candidate.exists() else args.text
            ev = evidence_of(
                {
                    "summary": {
                        "app": app,
                        "status": "FAILED",
                        "failed_stage": "VERIFYING",
                        "failed_check": {"TEST": "tests_passed", "INFRASTRUCTURE": "required_platform_contract_valid"}.get(
                            args.classification or "", "unknown"
                        ),
                        "detail": text,
                    },
                    "manifest": {"app": app, "checks": {}},
                }
            )
            diag = diagnose(ev)
            diag["classification"] = args.classification or diag["classification"]
    except FileNotFoundError as exc:
        log(str(exc))
        return 3

    out = json.dumps(diag, ensure_ascii=False, indent=2)
    print(out)
    if args.out_file:
        p = pathlib.Path(args.out_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out + "\n", encoding="utf-8")
    if args.summary_file:
        p = pathlib.Path(args.summary_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_markdown(diag) + "\n", encoding="utf-8")
        gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if gh_summary:
            with open(gh_summary, "a", encoding="utf-8") as fh:
                fh.write(render_markdown(diag) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
