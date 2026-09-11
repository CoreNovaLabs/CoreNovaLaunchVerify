"""首启页面：断言均为 fireflyiii/core:version-6.6.6 真容器内实测事实。

全新容器首启：/ 302 → /login（200），Blade 渲染的登录表单；
未注册用户时 /register 开放首个（管理员）账户创建。
/api/v1/about 需鉴权（实测 302），版本走容器内 artisan 命令。

未覆盖：注册账户并记账——注册会创建真实用户数据，一次性容器里
无意义；断言停在"界面可用"这一层。
"""

from __future__ import annotations


def test_login_page_reachable(base_url):
    import time

    import requests

    # 首启 Laravel/Passport 迁移期间 /login 会 500（实测）：轮询到稳定 200
    deadline = time.time() + 240
    last = 0
    while time.time() < deadline:
        try:
            last = requests.get(base_url + "/login", timeout=30).status_code
            if last == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise AssertionError(f"/login 240s 内未就绪（最后 {last}）")


def test_login_renders(base_url, browser_page):
    page = browser_page
    # 迁移窗口内偶发 500 落在 goto 的一次加载里（实测）：goto+等控件整轮重试
    last_exc = None
    for _ in range(6):
        try:
            page.goto(base_url + "/login", wait_until="domcontentloaded", timeout=30_000)
            # 表单第一个 input 是隐藏元素（实测 64×resolved to 6 elements），
            # 用 attached 语义而非默认 visible
            page.wait_for_selector("input", state="attached", timeout=30_000)
            break
        except Exception as exc:  # noqa: BLE001 - 重试下一次加载
            last_exc = exc
            page.wait_for_timeout(5_000)
    else:
        raise AssertionError(f"登录/注册表单 6 轮内未渲染：{last_exc}")
    text = page.locator("body").inner_text()
    assert text.strip(), "登录页渲染为空白"
    assert "firefly" in text.lower() or "register" in text.lower() or "log" in text.lower(), "页面缺少 Firefly III 标识"
