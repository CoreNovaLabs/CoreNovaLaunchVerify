"""后台链路（断言均为在 ghost:6.61.0-alpine 真容器内实测得到的事实）。

未覆盖：owner 建立与发文写入。Ghost 6 的 setup/session 端点载荷形状与 5.x 文档不一致
（POST /authentication/setup/ 建号成功后仍返回 500 主题解构错误；密码 grant 返回 404），
在确认正确调用方式之前，宁可少测，也不写会误判的断言。
"""

from __future__ import annotations

PROTECTED = ("/ghost/api/admin/users/me/", "/ghost/api/admin/posts/", "/ghost/api/admin/newsletters/")


def test_public_admin_site_endpoint_answers(api, base_url):
    r = api.get(base_url.rstrip("/") + "/ghost/api/admin/site/", timeout=20)
    assert r.status_code == 200, f"admin/site 返回 {r.status_code}"
    assert (r.json().get("site") or {}).get("title"), "响应缺少 site.title"


def test_protected_admin_endpoints_reject_unauthenticated(api, base_url):
    for path in PROTECTED:
        r = api.get(base_url.rstrip("/") + path, timeout=20)
        assert r.status_code in (401, 403), f"{path} 未鉴权却返回 {r.status_code}（安全边界异常）"


def test_admin_spa_is_served(base_url, browser_page):
    page = browser_page
    resp = page.goto(base_url.rstrip("/") + "/ghost/", wait_until="networkidle")
    assert resp and resp.status == 200, f"后台入口返回 {resp.status if resp else 'None'}"
    assert page.locator("body").inner_text().strip(), "后台页面渲染为空白"
