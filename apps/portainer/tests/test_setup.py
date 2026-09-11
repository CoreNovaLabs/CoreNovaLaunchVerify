"""首启页面：断言均为 portainer/portainer-ce:2.45.0 真容器内实测事实。

全新容器首启：/ 200 返回 SPA 外壳，前端路由到 /#!/init/admin 管理员创建页
（未创建用户时 init 向导强制前置）。/api/status 免鉴权返回版本 JSON。

未覆盖：创建管理员并连接 Docker endpoint——写真实管理员数据到一次性
容器无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_status_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/api/status", timeout=20)
    assert r.status_code == 200, f"/api/status 返回 {r.status_code}"
    doc = r.json()
    assert doc.get("Version"), "缺少 Version 字段"


def test_admin_setup_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # SPA 挂载后 init 向导要求创建管理员（用户名固定 admin、密码 + 确认密码）
    page.wait_for_selector("input", timeout=60_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "管理界面渲染为空白"
    assert "admin" in text.lower() or "user" in text.lower(), "首启页面缺少管理员设置"
