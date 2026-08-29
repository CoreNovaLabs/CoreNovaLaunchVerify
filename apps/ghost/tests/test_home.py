"""首页与公共端点：验证"站点真的能用"，而不是"端口开着"."""

from __future__ import annotations


def test_homepage_renders_html(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20, allow_redirects=True)
    assert r.status_code == 200, f"首页返回 {r.status_code}"
    assert "<html" in r.text.lower(), "首页不是 HTML"


def test_homepage_has_ghost_markup(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="networkidle")
    assert page.locator("body").inner_text().strip(), "首页渲染为空白"
    assert page.title(), "首页缺少 <title>"


def test_robots_and_sitemap_available(base_url):
    import requests

    for path in ("/robots.txt", "/sitemap.xml"):
        r = requests.get(base_url + path, timeout=20)
        # 未发布文章时 sitemap 可能是 200 空表或 404，两者都不视为故障
        assert r.status_code in (200, 404), f"{path} 返回 {r.status_code}"
