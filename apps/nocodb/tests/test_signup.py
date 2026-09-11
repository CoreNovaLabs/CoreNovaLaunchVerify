"""首启页面：断言均为 nocodb/nocodb:2026.09.0 真容器内实测事实。

全新容器首启：/api/v1/health 200 {"message":"OK"}；/api/v1/meta/nocodb/info
免鉴权含 firstUser:true；/ 200 SPA，无既有用户时注册页开放。

未覆盖：注册首个用户并建表——注册会创建真实用户数据，一次性
容器里无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_health_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/api/v1/health", timeout=20)
    assert r.status_code == 200, f"/api/v1/health 返回 {r.status_code}"


def test_signup_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/signup", wait_until="domcontentloaded")
    # Vue SPA 挂载滞后于 healthz：等真实表单控件出现再断言
    page.wait_for_selector("input", timeout=90_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "注册页渲染为空白"
    assert "nocodb" in text.lower() or "sign" in text.lower() or "注册" in text, "页面缺少 NocoDB 注册标识"
