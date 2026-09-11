"""首启页面：断言均为 grafana/grafana:13.2.1 真容器内实测事实。

全新容器首启：/api/health 200（database ok），/ 302 到 /login，
登录页标题 Grafana。

未覆盖：登录进仪表盘——内置 admin 账户首登强制改密，改密流程属于
一次性交互状态，宁可少测，也不写会误判的断言。
"""

from __future__ import annotations


def test_api_health_ready(base_url):
    import requests

    r = requests.get(base_url + "/api/health", timeout=20)
    assert r.status_code == 200, f"/api/health 返回 {r.status_code}"
    body = r.json()
    assert body.get("database") == "ok", f"数据库未就绪: {body}"


def test_login_page_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/login", wait_until="networkidle")
    text = page.locator("body").inner_text()
    assert text.strip(), "登录页渲染为空白"
    assert "grafana" in text.lower(), "登录页缺少 Grafana 标识"
