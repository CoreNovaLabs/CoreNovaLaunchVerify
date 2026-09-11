"""首启页面：断言均为 freshrss/freshrss:1.30.0 真容器内实测事实。

全新容器首启：/ 302 → /i/ 安装向导（PHP 直出，步骤 1 语言选择），
页面标识 FreshRSS。版本来自 constants.php 的 FRESHRSS_VERSION 常量。

未覆盖：完成安装并创建管理员——向导提交后要求重启服务，一次性
容器里重启流程不稳定，宁可少测，也不写会误判的断言。
"""

from __future__ import annotations


def test_root_reaches_installer(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20, allow_redirects=True)
    assert r.status_code == 200, f"/ 重定向落点返回 {r.status_code}"
    assert "freshrss" in r.text.lower(), "落点页面缺少 FreshRSS 标识"


def test_install_wizard_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    text = page.locator("body").inner_text()
    assert text.strip(), "安装向导渲染为空白"
    assert "freshrss" in text.lower(), "页面缺少 FreshRSS 标识"
    # 向导含语言选择或下一步表单控件
    assert page.locator("select, input, button").count() > 0, "安装向导缺少表单控件"
