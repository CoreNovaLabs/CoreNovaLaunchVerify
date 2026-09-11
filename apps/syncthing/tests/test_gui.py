"""首启页面：断言均为 syncthing/syncthing:2.1.5 真容器内实测事实。

全新容器首启：/rest/noauth/health 200 {"status":"OK"}；/ 200 Web GUI
（Vue 单页，默认无 GUI 密码，直出仪表盘空状态）。

未覆盖：添加设备与共享文件夹——需要第二个 syncthing 实例与真实
设备 ID；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_health_endpoint(base_url):
    import requests

    r = requests.get(base_url + "/rest/noauth/health", timeout=20)
    assert r.status_code == 200, f"/rest/noauth/health 返回 {r.status_code}"
    assert r.json().get("status") == "OK", "health 状态非 OK"


def test_gui_renders(base_url, browser_page):
    page = browser_page
    page.goto(base_url + "/", wait_until="domcontentloaded")
    # Vue GUI 挂载滞后于 healthz：等真实交互控件出现再断言
    page.wait_for_selector("input, button, #syncthingBody, .panel", timeout=90_000)
    text = page.locator("body").inner_text()
    assert text.strip(), "GUI 渲染为空白"
    assert "syncthing" in text.lower() or "folder" in text.lower() or "device" in text.lower(), "页面缺少 Syncthing 标识"
