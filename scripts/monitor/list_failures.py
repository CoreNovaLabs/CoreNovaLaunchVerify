#!/usr/bin/env python3
"""失败台账只读 CLI（workflow-state-machine.md §7）——薄封装 corenova/failure.py。

    python scripts/monitor/list_failures.py --retryable-only --json
    python scripts/monitor/list_failures.py --classification TRANSIENT --summary-file /tmp/x.md

台账唯一载体是 GitHub issue（不引入第二个状态存储），所以本脚本只在有
GITHUB_REPOSITORY + GITHUB_TOKEN 的环境里返回真实数据；本地跑得到空集合并明确说明原因，
避免把"读不到"当成"没有失败"。

分类口径（§4）：只有 TRANSIENT 且 attempts < 3 且 issue open 的记录有自动重试资格；
APPLICATION / TEST / INFRASTRUCTURE / MANUAL_REQUIRED 四类永不自动触发，只汇总给人看。
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from corenova import failure
from corenova.util import log

ALL_CLASSIFICATIONS = failure.ALL_CLASSIFICATIONS


def fetch_all(limit: int, errors: list[str] | None = None) -> list[dict[str, Any]]:
    """按 label 拉 open 的 verify-failed issue，补齐 attempts / dispatch_target。

    跨 label 去重：同一 issue 可能同时带多个 classification 标签（罕见但发生过）。
    TRANSIENT 的 attempts<3 判定额外以 `failure.open_transient_failures()` 为准：
    pipeline 写入端与本脚本读取端可能因并发看到不同的 attempts 值，取并集更安全。
    """
    repo = failure.repo_name()
    if not repo:
        log("非 GitHub 环境（无 GITHUB_REPOSITORY）→ 台账读取返回空集合")
        return []
    if errors is None:
        errors = []

    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for cls in ALL_CLASSIFICATIONS:
        for row in failure.open_failures_by_classification(cls, limit=limit, errors=errors):
            key = (row.get("issue_number") or 0, row.get("verification_id") or "")
            if key in seen:
                continue
            seen.add(key)
            out.append(row)

    # TRANSIENT 再走一次契约实现，确保 attempts<3 判定与本仓 pipeline 写入端同源。
    try:
        contract_ids = {r.get("verification_id") for r in failure.open_transient_failures(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        contract_ids = set()
        log(f"open_transient_failures() 不可用（{type(exc).__name__}: {exc}）→ 用本脚本的等价过滤")
    if contract_ids:
        for row in out:
            if row["classification"] == "TRANSIENT":
                row["retryable"] = bool(row["verification_id"]) and row["verification_id"] in contract_ids
    return sorted(out, key=lambda r: (not r["retryable"], r["classification"], r["app"]))


def render_markdown(rows: list[dict[str, Any]]) -> str:
    retryable = [r for r in rows if r["retryable"]]
    manual = [r for r in rows if not r["retryable"]]
    lines = [
        "## 失败台账（GitHub issue）",
        "",
        f"- 可自动重试（TRANSIENT 且 attempts<{failure.MAX_ATTEMPTS}）：**{len(retryable)}**",
        f"- 需人工处置：{len(manual)}",
        "",
        "| app | version | vid | 分类 | stage/check | attempts | 处置 | issue |",
        "|-----|---------|-----|------|-------------|----------|------|-------|",
    ]
    for r in rows:
        action = f"重新 dispatch → {r['dispatch_target']}" if r["retryable"] else "仅汇总，不自动重试"
        lines.append(
            "| {app} | `{ver}` | `{vid}` | {cls} | {stage}/{check} | {att} | {act} | #{num} |".format(
                app=r["app"] or "—",
                ver=r["app_version"] or "—",
                vid=r["verification_id"] or "—",
                cls=r["classification"],
                stage=r["failed_stage"] or "—",
                check=r["failed_check"] or "—",
                att=f"{r['attempts']}/{failure.MAX_ATTEMPTS}",
                act=action,
                num=r["issue_number"],
            )
        )
    if not rows:
        lines += ["", "（台账为空或当前环境无法读取）"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="读取 CoreNova 失败台账（GitHub issue，state-machine §7）：默认输出 JSON 数组到 stdout"
    )
    ap.add_argument("--classification", choices=ALL_CLASSIFICATIONS, help="只看某一分类")
    ap.add_argument("--retryable-only", action="store_true", help="只输出可自动重试条目（TRANSIENT 且 attempts<3）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认可读文本）")
    ap.add_argument("--app", help="只看某个应用")
    ap.add_argument("--limit", type=int, default=50, help="每类最多读取条数（默认 50）")
    ap.add_argument("--summary-file", help="同时把 markdown 摘要写到该文件（供 job summary 使用）")
    ap.add_argument("--strict", action="store_true", help="任何一类台账读取失败即退出码 3（CI 里用，避免把读失败当成\u201c无失败\u201d）")
    args = ap.parse_args(argv)

    errors: list[str] = []
    rows = fetch_all(limit=args.limit, errors=errors)
    if args.classification:
        rows = [r for r in rows if r["classification"] == args.classification]
    if args.app:
        rows = [r for r in rows if r["app"] == args.app]
    if args.retryable_only:
        rows = [r for r in rows if r["retryable"]]

    if args.summary_file:
        pathlib.Path(args.summary_file).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.summary_file).write_text(render_markdown(rows), encoding="utf-8")

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(rows))

    if errors:
        print(f"::warning::台账部分不可读（{len(errors)}/{len(ALL_CLASSIFICATIONS)} 类）：{errors[0]}")
    # "台账为空"与"台账读不到"必须能区分：后者若当成功，reverify 会在看不见的失败上静默通过
    if not failure.repo_name():
        log("提示：缺少 GITHUB_REPOSITORY/GITHUB_TOKEN → 台账不可读（本地环境属预期，退出码 0）")
        return 0
    if len(errors) >= len(ALL_CLASSIFICATIONS):
        log("台账完全不可读 → 退出码 3（调用方不得据此判定\u201c无失败\u201d）")
        return 3
    if args.strict and errors:
        log("--strict：存在读取失败 → 退出码 3")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
