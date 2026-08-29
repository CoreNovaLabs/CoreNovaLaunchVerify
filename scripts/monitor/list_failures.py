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
import os
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from corenova import failure  # noqa: E402
from corenova.util import log  # noqa: E402

ALL_CLASSIFICATIONS = ("TRANSIENT", "APPLICATION", "TEST", "INFRASTRUCTURE", "MANUAL_REQUIRED")
_ATTEMPTS_RE = re.compile(r'"attempts":\s*(\d+)')


def _attempts_of(body: str) -> int:
    """台账里的 attempt 计数（缺失按 1 算，绝不按 0 算——0 会绕过 attempts<3）。"""
    m = _ATTEMPTS_RE.search(body or "")
    return int(m.group(1)) if m else 1


def _meta_from_body(body: str) -> dict[str, Any] | None:
    """解析正文里的 fenced ```corenova-failure 机器可读块。"""
    m = re.search(r"```corenova-failure\n(.*?)\n```", body or "", re.S)
    if not m:
        return None
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return meta if isinstance(meta, dict) else None


def search_url(repo: str, query: str, limit: int) -> str:
    """issue search 的 q 里有空格，必须百分号编码：urllib 会把裸空格判成 control character。"""
    from urllib.parse import urlencode

    return "https://api.github.com/search/issues?" + urlencode({"q": query, "per_page": limit})


def row_from_item(item: dict[str, Any], meta: dict[str, Any] | None) -> dict[str, Any]:
    """issue + fenced metadata → 台账行。§7 规则 1/5：仅 TRANSIENT 且 attempts<3 可自动重试。"""
    meta = meta or {}
    classification = str(meta.get("classification") or _label_of(item, "classification:"))
    attempts = int(meta.get("attempts") or _attempts_of(item.get("body") or ""))
    return {
        "issue_number": item.get("number"),
        "issue_url": item.get("html_url") or "",
        "app": str(meta.get("app") or _label_of(item, "app:")),
        "app_version": str(meta.get("app_version") or ""),
        "verification_id": str(meta.get("verification_id") or ""),
        "classification": classification,
        "failed_stage": str(meta.get("failed_stage") or ""),
        "failed_check": str(meta.get("failed_check") or ""),
        "attempts": attempts,
        "run_url": str(meta.get("run_url") or ""),
        "platform_verification_id": str(meta.get("platform_verification_id") or ""),
        "retryable": classification == "TRANSIENT"
        and attempts < failure.MAX_ATTEMPTS
        and str(item.get("state") or "").lower() == "open",
        # INFRASTRUCTURE 的复验只能落在 golden-verify，且 reverify 永不自动触发它
        "dispatch_target": "golden-verify.yml" if classification == "INFRASTRUCTURE" else "application-verify.yml",
        "updated_at": item.get("updated_at") or "",
    }


def fetch_all(limit: int, errors: list[str] | None = None) -> list[dict[str, Any]]:
    """按 label 拉 open 的 verify-failed issue，并补齐 attempts / dispatch_target。

    TRANSIENT 的 attempts<3 判定优先复用 `failure.open_transient_failures()`（与 pipeline 写入端
    同源）；但该 helper 目前把带空格的 query 直接拼进 URL → 会被 urllib 拒（InvalidURL），
    因此这里等它失败时降级到本脚本内的等价过滤，并保留可对比的字段。
    每类读取失败会 append 到 errors，让调用方区分“台账为空”与“台账读不到”。
    """
    repo = failure.repo_name()
    if not repo:
        log("非 GitHub 环境（无 GITHUB_REPOSITORY）→ 台账读取返回空集合")
        return []
    if errors is None:
        errors = []

    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    def add(item: dict[str, Any], meta: dict[str, Any] | None) -> None:
        meta = meta or {}
        key = (int(item.get("number") or 0), str(meta.get("verification_id") or item.get("title")))
        if key in seen:
            return
        seen.add(key)
        out.append(row_from_item(item, meta))

    for cls in ALL_CLASSIFICATIONS:
        q = f"repo:{repo} is:issue is:open label:{failure.LABEL} label:classification:{cls}"
        try:
            from corenova.util import http_json

            hits = http_json(search_url(repo, q, limit), headers=failure._headers())
        except Exception as exc:  # noqa: BLE001 - 读台账失败要可见，但不编造数据
            errors.append(f"{cls}: {type(exc).__name__}: {exc}")
            log(f"读取 classification={cls} 台账失败：{type(exc).__name__}: {exc}")
            continue
        for item in hits.get("items") or []:
            add(item, _meta_from_body(item.get("body") or ""))

    # TRANSIENT 再走一次契约实现，确保 attempts<3 判定与本仓 pipeline 写入端同源。
    # corenova/failure.py 的 search URL 未做百分号编码（裸空格）→ 可能直接抛 InvalidURL；
    # 只读 CLI 不能因此崩掉，降级用上面已算出的等价过滤（TRANSIENT + attempts<3 + open）。
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


def _label_of(item: dict[str, Any], prefix: str) -> str:
    for lab in item.get("labels") or []:
        name = lab.get("name") if isinstance(lab, dict) else str(lab)
        if name and name.startswith(prefix):
            return name[len(prefix) :]
    return ""


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
    ap.add_argument("--strict", action="store_true", help="任何一类台账读取失败即退出码 3（CI 里用，避免把读失败当成“无失败”）")
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
        log("台账完全不可读 → 退出码 3（调用方不得据此判定“无失败”）")
        return 3
    if args.strict and errors:
        log("--strict：存在读取失败 → 退出码 3")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
