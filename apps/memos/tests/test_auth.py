"""首启页面：断言均为 neosmemo/memos:0.30.0 真容器内实测事实。

全新容器首启：/healthz 200 "OK."；/ 渲染 "FIRST RUN / Set up your instance"
管理员创建页（0.30 起首启直接建管理员，不再跳 /auth 注册页）。

未覆盖：创建管理员与写入笔记——会写入真实用户数据，一次性
容器里无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_healthz_ready(base_url):
    import requests

    r = requests.get(base_url + "/healthz", timeout=20)
    assert r.status_code == 200, f"/healthz 返回 {r.status_code}"


def test_auth_page_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="networkidle")
    text = page.locator("body").inner_text()
    assert text.strip(), "首启页面渲染为空白"
    assert "Memos" in text, "页面缺少 Memos 标识"
    # 全新实例无用户：0.30 首启为管理员创建页（实测文案 "Set up your instance"）
    assert "set up" in text.lower() or "administrator" in text.lower(), "首启页面缺少管理员设置入口"
