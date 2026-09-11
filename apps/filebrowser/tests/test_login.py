"""首启页面：断言均为 filebrowser/filebrowser:v2.63.23 真容器内实测事实。

全新容器首启：/ 200 渲染登录页（Vue SPA，等真实控件出现再断言）。
未覆盖：登录后的文件操作——默认账号策略不在契约内，HTTP 断言已覆盖"服务可用"。
"""

from __future__ import annotations


def test_root_reachable(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20)
    assert r.status_code == 200, f"/ 返回 {r.status_code}"


def test_login_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # Vue SPA：等真实控件出现再断言
    page.wait_for_selector("input, button", timeout=90_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "登录页渲染为空白"
