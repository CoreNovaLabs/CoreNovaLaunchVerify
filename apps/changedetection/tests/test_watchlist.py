"""首启页面：断言均为 dgtlmoon/changedetection.io:0.60.4 真容器内实测事实。

全新容器首启：/ 200 直接渲染 watchlist 界面（Flask 单体，无独立首启向导）。
未覆盖：实际抓取任务——需要外部目标站点配合，HTTP 断言已覆盖"服务可用"。
"""

from __future__ import annotations


def test_root_reachable(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20)
    assert r.status_code == 200, f"/ 返回 {r.status_code}"


def test_watchlist_renders(base_url, browser_page):
    page = browser_page
    # 首启可能仍在建库，整轮重试 8 次。
    # 注意 state="attached"：text 引擎会先命中侧栏 logo 的隐藏 span
    # （#logo-expanded，折叠态不可见），默认 visible 语义会永远等不到。
    last_err = None
    for _ in range(8):
        try:
            page.goto(base_url + "/", wait_until="domcontentloaded")
            page.wait_for_selector(
                "text=/changedetection|watch|add/i", state="attached", timeout=30_000
            )
            text = page.locator("body").inner_text()
            assert text.strip(), "页面渲染为空白"
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise last_err
