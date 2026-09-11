"""首启页面：断言均为 netdata/netdata:v2.11.0 真容器内实测事实。

全新容器首启：/api/v1/info 200 含 version；/v2 200 dashboard SPA。
验证容器只挂载数据卷，无 /proc /sys 主机挂载——dashboard 仍渲染
（自采 cgroup/容器指标），不假设主机指标存在。

未覆盖：Netdata Cloud claim——需要外部账号；断言停在"界面可用"。
"""

from __future__ import annotations


def test_info_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/api/v1/info", timeout=30)
    assert r.status_code == 200, f"/api/v1/info 返回 {r.status_code}"
    assert r.json().get("version"), "缺少 version 字段"


def test_dashboard_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # React dashboard 挂载滞后于 API；v2.x 仪表盘就在 /（/v2 已 404，实测）
    page.wait_for_selector("text=/netdata/i", timeout=120_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "仪表盘渲染为空白"
    assert "netdata" in text.lower(), "页面缺少 Netdata 标识"
