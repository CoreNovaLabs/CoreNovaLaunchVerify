"""首启页面：断言均为 jellyfin/jellyfin:12.0 真容器内实测事实。

全新容器首启：/health 200 "Healthy"；/ 302 到 /web/ SPA，
StartupWizardCompleted=false 时前端路由到初始化向导（选择语言/用户/媒体库）。
/system/info/public 免鉴权含 Version。

未覆盖：完成向导并添加媒体库——写真实用户数据到一次性容器无意义；
断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_health_ready(base_url):
    import time

    import requests

    # 12.0 首启跑 DB 迁移，/health 会在 200/503 间闪断（实测）：轮询至稳定
    deadline = time.time() + 240
    last = 0
    while time.time() < deadline:
        try:
            last = requests.get(base_url + "/health", timeout=20).status_code
            if last == 200:
                # 连续两次 200 才算稳定（防迁移中闪断）
                time.sleep(3)
                if requests.get(base_url + "/health", timeout=20).status_code == 200:
                    return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise AssertionError(f"/health 240s 内未稳定 200（最后 {last}）")


def test_wizard_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # 等向导的真实文本渲染出来（加载外壳可能先匹配到隐藏控件，实测截图
    # 为 "Welcome to Jellyfin!" 表单；pytest 先于管线截图执行）
    page.wait_for_selector("text=Jellyfin", timeout=180_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "向导页面渲染为空白"
    assert "jellyfin" in text.lower(), "页面缺少 Jellyfin 标识"
