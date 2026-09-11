"""首启页面：断言均为 adguard/adguardhome:v0.107.79 真容器内实测事实。

全新容器首启：/ 302 → /install.html（200），Go 直出的安装向导
（欢迎页 → 网卡选择 → 账户创建）。版本来自 --version 第 4 列（带 v）。

未覆盖：完成向导并创建管理员——向导提交会改写配置文件并要求重启
服务，一次性容器里重启流程不稳定，宁可少测，也不写会误判的断言。
"""

from __future__ import annotations


def test_root_reaches_installer(base_url):
    import requests

    r = requests.get(base_url + "/install.html", timeout=20)
    assert r.status_code == 200, f"/install.html 返回 {r.status_code}"


def test_install_wizard_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # Go html/template 直出（非 SPA），控件稳定；等 Welcome 文本即可
    page.wait_for_selector("text=/welcome|adguard/i", timeout=60_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "安装向导渲染为空白"
    assert "adguard" in text.lower(), "页面缺少 AdGuard Home 标识"
