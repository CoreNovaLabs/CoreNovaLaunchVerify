"""Playwright screenshots, one PNG per `tests.scenarios[].slug` (ASCII filenames only).

An app may ship `tests/scenario_setup.py` with `prepare(page, slug)` for scenarios that
need state (e.g. signing in before capturing the admin dashboard). Missing the hook is
fine — the scenario still gets captured as-is.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

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
            page.goto(url, wait_until="networkidle")
            if prepare:
                prepare(page, slug)
            page.wait_for_timeout(500)
            target = out_dir / f"{slug}.png"
            page.screenshot(path=str(target), full_page=True)
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
