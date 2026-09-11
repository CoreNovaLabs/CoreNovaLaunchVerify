"""首启页面：断言均为 stirlingtools/stirling-pdf:2.14.3 真容器内实测事实。

全新容器首启：/ 401（2.x 登录强制），/login 200 SPA 登录页；
/api/v1/info/status 免鉴权含 {"version":"2.14.3","status":"UP"}。

未覆盖：创建用户并执行 PDF 操作——写真实用户数据到一次性容器
无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_status_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/api/v1/info/status", timeout=30)
    assert r.status_code == 200, f"/api/v1/info/status 返回 {r.status_code}"
    doc = r.json()
    assert doc.get("status") == "UP", f"status 非 UP: {doc}"


def test_login_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/login", wait_until="domcontentloaded")
    # Thymeleaf/JS 混合渲染：等真实表单控件出现再断言
    page.wait_for_selector("input", timeout=90_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "登录页渲染为空白"
    assert "stirling" in text.lower() or "sign" in text.lower() or "登录" in text, "页面缺少 Stirling PDF 标识"
