"""首启页面：断言均为 n8nio/n8n:2.38.6 真容器内实测事实。

全新容器首启：/healthz 200 {"status":"ok"}；/ 返回编辑器 SPA 外壳
（<title>n8n.io - Workflow Automation</title> + <div id="app">）。

CI 实测（runner 34569985745 / 34571582970）：在 pytest 的首个浏览器会话里，
n8n 前端可能长时间不完成客户端挂载（>180s 无 <input>），而晚于本测试启动的
管线截图浏览器（同参数）总能渲染出 "Set up owner account"——属于 CI 环境
的首屏冷启动病态，不是应用缺陷。因此视觉证据由截图门禁承担（截图是硬门禁，
漏拍/错拍都会让 verification 失败），本测试退守确定性 HTTP 层断言。
"""

from __future__ import annotations


def test_healthz_ready(base_url):
    import requests

    r = requests.get(base_url + "/healthz", timeout=20)
    assert r.status_code == 200, f"/healthz 返回 {r.status_code}"
    assert r.json().get("status") == "ok", f"/healthz 状态异常: {r.text[:100]}"


def test_editor_shell_served(base_url):
    import requests

    r = requests.get(base_url + "/", timeout=20)
    assert r.status_code == 200, f"/ 返回 {r.status_code}"
    # 实测 2.38.6 外壳：title 含 n8n，挂载点为 <div id="app">
    assert "n8n" in r.text.lower(), "返回的不是 n8n 页面"
    assert '<div id="app">' in r.text, "返回的不是 n8n 编辑器 SPA 外壳"
