"""首启页面：断言均为在 louislam/uptime-kuma:2.5.3 真容器内实测得到的事实。

全新容器首启：/ 302 到 /setup-database（2.x 引入的数据库选择向导），页面标题
Uptime Kuma，向导提供 SQLite / MariaDB 选项。

未覆盖：创建管理员账户与监控项写入——2.x 的设置向导是纯 UI 流程
（socket.io 驱动），在确认稳定调用方式之前，宁可少测，也不写会误判的断言。
"""

from __future__ import annotations


def test_root_reaches_first_run_page(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20, allow_redirects=True)
    assert r.status_code == 200, f"/ 重定向落点返回 {r.status_code}"
    assert "<html" in r.text.lower(), "落点不是 HTML"
    assert "<title>Uptime Kuma</title>" in r.text, "页面标题不是 Uptime Kuma"


def test_first_run_wizard_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="networkidle")
    text = page.locator("body").inner_text()
    assert text.strip(), "首启页面渲染为空白"
    # 2.x 首启为数据库选择向导；上游若改动该流程，此断言应红（人工复核新流程）
    assert "SQLite" in text and "MariaDB" in text, "首启页面缺少数据库选择选项"
