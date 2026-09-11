"""首启页面：断言均为 gitea/gitea:1.27.3 真容器内实测事实。

全新容器首启：/ 303 到 /install，展示数据库与基础配置的安装表单，
页面标题 Gitea: Installation。

未覆盖：完成安装并创建管理员——安装向导提交后要求重启服务，一次性
容器里重启流程不稳定，宁可少测，也不写会误判的断言。
"""

from __future__ import annotations


def test_root_reaches_install_wizard(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20, allow_redirects=True)
    assert r.status_code == 200, f"/ 重定向落点返回 {r.status_code}"
    assert "<html" in r.text.lower(), "落点不是 HTML"


def test_install_wizard_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="networkidle")
    text = page.locator("body").inner_text()
    assert text.strip(), "安装向导渲染为空白"
    # 安装向导含数据类型选择（SQLite 默认）与管理员设置区
    assert "SQLite" in text, "安装向导缺少 SQLite 数据库选项"
    assert "Administrator" in text or "管理员" in text, "安装向导缺少管理员账户设置"
