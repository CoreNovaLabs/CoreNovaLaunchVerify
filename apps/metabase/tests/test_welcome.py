"""首启页面：断言均为 metabase/metabase:v0.63.17 真容器内实测事实。

全新容器首启：/ 302 到 /auth/login（已跳过 setup 的空库会先出欢迎/登录流），
/api/health 免鉴权 {"status":"ok"}，/api/session/properties 免鉴权含 version.tag。

未覆盖：完成 setup 创建管理员——写真实管理员数据到一次性容器无意义；
断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_health_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/api/health", timeout=20)
    assert r.status_code == 200, f"/api/health 返回 {r.status_code}"
    assert r.json().get("status") == "ok", "health 状态非 ok"


def test_spa_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # React 挂载滞后于 healthz；欢迎页只有按钮没有输入框（实测截图）
    page.wait_for_selector("button", timeout=120_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "欢迎页渲染为空白"
    assert "metabase" in text.lower(), "页面缺少 Metabase 标识"
