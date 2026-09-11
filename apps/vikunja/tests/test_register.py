"""首启页面：断言均为 vikunja/vikunja:2.6.0 真容器内实测事实。

全新容器首启：/api/v1/info 免鉴权含 version；/ 200 SPA，
无既有用户时注册页开放（/register）。

未覆盖：注册账户并创建项目——注册会创建真实用户数据，一次性
容器里无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_info_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/api/v1/info", timeout=20)
    assert r.status_code == 200, f"/api/v1/info 返回 {r.status_code}"
    assert r.json().get("version"), "缺少 version 字段"


def test_register_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/register", wait_until="domcontentloaded")
    # SPA 挂载滞后：等真实表单控件出现再断言
    page.wait_for_selector("input", timeout=90_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "注册页渲染为空白"
    assert "vikunja" in text.lower() or "register" in text.lower() or "创建账户" in text, "页面缺少 Vikunja 注册标识"
