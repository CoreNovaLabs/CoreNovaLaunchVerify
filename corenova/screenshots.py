"""Playwright screenshots, one PNG per `tests.scenarios[].slug` (ASCII filenames only).

An app may ship `tests/scenario_setup.py` with `prepare(page, slug)` for scenarios that
need state (e.g. signing in before capturing the admin dashboard). Missing the hook is
fine — the scenario still gets captured as-is.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .appspec import AppSpec
from .util import log


def capture(spec: AppSpec, root: Path, base_url: str, out_dir: Path, timeout_ms: int = 120_000) -> list[dict[str, Any]]:
    """-> [{slug, file, caption}] in scenario order. Raises if Playwright is unusable."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    prepare = _load_hook(spec, root)
    results: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        for s in spec.scenarios:
            slug, url = str(s["slug"]), base_url.rstrip("/") + str(s.get("url", "/"))
            # networkidle 只给 45s 预算：长轮询应用（如 syncthing 的事件流）永不
            # 网络空闲，超时后降级到 load 态 + 加长 settle，而不是硬失败。
            settled = True
            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
            except Exception:  # noqa: BLE001 - 降级渲染路径
                settled = False
            if prepare:
                prepare(page, slug)
            page.wait_for_timeout(500 if settled else 4_000)
            target = out_dir / f"{slug}.png"
            # 视口尺寸而非 full_page：full_page 让截图高度随页面内容变化（矮页面 1440x900、
            # 高页面 1440x1513），官网截图卡是固定 16:10，非 16:10 的图会被 contain 留出约四成空白。
            page.screenshot(path=str(target), full_page=False)
            results.append({"slug": slug, "file": target.name, "caption": s.get("caption") or {}})
            log(f"截图 {slug} -> {target.name} ({target.stat().st_size} bytes)")
        context.close()
        browser.close()
    return results


def _load_hook(spec: AppSpec, root: Path) -> Callable[..., None] | None:
    hook = root / spec.g("tests.predefined_dir") / "scenario_setup.py"
    if not hook.exists():
        return None
    name = f"corenova_scenario_hook_{spec.name}"
    module_spec = importlib.util.spec_from_file_location(name, hook)
    if module_spec is None or module_spec.loader is None:
        return None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    func = getattr(module, "prepare", None)
    return func if callable(func) else None


def ensure_installed() -> None:
    """Fail fast with an actionable message if the browser binary is missing."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("缺少 playwright：pip install -r requirements.txt") from exc
