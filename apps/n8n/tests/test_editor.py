"""首启页面：断言均为 n8nio/n8n:2.38.6 真容器内实测事实。

全新容器首启：/healthz 200 {"status":"ok"}；/ 由编辑器 SPA 提供，
无既有用户时渲染所有者设置（Setup）界面。

未覆盖：创建所有者账户与编排工作流——账户创建会写入真实数据，
一次性容器里无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_healthz_ready(base_url):
    import requests

    r = requests.get(base_url + "/healthz", timeout=20)
    assert r.status_code == 200, f"/healthz 返回 {r.status_code}"
    assert r.json().get("status") == "ok", f"/healthz 状态异常: {r.text[:100]}"


def test_editor_renders(base_url, browser_page):
    # 双保险：探针已等编辑器就绪，这里再容忍 SPA 客户端渲染的滞后
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector("input", timeout=60_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "编辑器渲染为空白"
    # 无既有用户的首启：所有者设置界面（n8n 2.x，实测文案 "Set up owner account"）
    assert "owner account" in text.lower(), "首启页面缺少所有者设置界面"
