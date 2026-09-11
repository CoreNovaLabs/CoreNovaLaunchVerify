"""首启页面：断言均为 ghcr.io/home-assistant/home-assistant:2026.9.1 真容器内实测事实。

全新容器首启：/ 302 → /onboarding.html（200），创建管理员账户向导。
版本来自 `python3 -m homeassistant --version`（恰为版本号一行）。

未覆盖：完成向导并接入设备——写真实用户数据到一次性容器无意义；
断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_onboarding_reachable(base_url):
    import requests

    r = requests.get(base_url + "/onboarding.html", timeout=30)
    assert r.status_code == 200, f"/onboarding.html 返回 {r.status_code}"


def test_onboarding_renders(base_url, browser_page):
    page = browser_page
    # 首启初始化慢（实测 2-4 分钟）：goto + 等真实文本，整轮重试。
    # 注意：HA 是 Web Components 应用，正文全在 shadow DOM 里，
    # page.locator("body").inner_text() 返回空串；Playwright locator
    # 会自动穿透 open shadow root，用它断言向导文案真的渲染。
    import time

    last_exc = None
    for _ in range(8):
        try:
            page.goto(base_url + "/", wait_until="domcontentloaded", timeout=30_000)
            btn = page.locator(
                "text=/create my smart home|awaken your home|welcome/i"
            ).first
            btn.wait_for(state="attached", timeout=30_000)
            assert btn.inner_text().strip(), "向导按钮渲染为空"
            assert "home assistant" in page.title().lower(), (
                f"页面标题缺少 Home Assistant 标识：{page.title()!r}"
            )
            return
        except Exception as exc:  # noqa: BLE001 - 初始化窗口内整轮重试
            last_exc = exc
            time.sleep(10)
    raise AssertionError(f"初始化向导 8 轮内未渲染：{last_exc}")
