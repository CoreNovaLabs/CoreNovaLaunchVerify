"""首启页面：断言均为 vaultwarden/server:1.37.2-alpine 真容器内实测事实。

全新容器首启：/alive 200（返回 JSON 字符串化的时间戳）；/ 由内嵌 web vault
提供，SPA 渲染出登录/注册界面（hash 路由，前端文案为英文默认主题）。

未覆盖：注册账户与写入密码项——注册会创建真实用户数据，一次性
容器里无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_alive_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/alive", timeout=20)
    assert r.status_code == 200, f"/alive 返回 {r.status_code}"
    # 实测 1.37.2：/alive 返回 JSON 字符串化的 RFC3339 时间戳（不再是 "Ok"）
    body = r.json()
    assert isinstance(body, str) and "T" in body, f"/alive 响应体异常: {str(body)[:100]}"


def test_web_vault_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="networkidle")
    text = page.locator("body").inner_text()
    assert text.strip(), "Web vault 渲染为空白"
    # 默认主题的 web vault 含登录入口
    assert "log in" in text.lower() or "master pass" in text.lower(), "Web vault 缺少登录入口"
