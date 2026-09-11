"""首启页面：断言均为 axllent/mailpit:v1.31.1 真容器内实测事实。

全新容器首启：/api/v1/info 200 含 Version；/ 200 Web 收件箱（空库）。
未覆盖：SMTP 收信——需要外部客户端发信，HTTP 断言已覆盖"服务可用"。
"""

from __future__ import annotations


def test_info_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/api/v1/info", timeout=20)
    assert r.status_code == 200, f"/api/v1/info 返回 {r.status_code}"
    assert r.json().get("Version"), "缺少 Version 字段"


def test_inbox_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # Vue SPA：等真实控件出现再断言
    page.wait_for_selector("input, button, .message", timeout=90_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "收件箱渲染为空白"
    assert "mailpit" in text.lower(), "页面缺少 Mailpit 标识"
