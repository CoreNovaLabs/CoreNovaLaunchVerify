"""Ghost 预写测试的共用夹具。

凭据是**一次性本地容器**内的（每次验证从零启动、跑完销毁），不是任何真实账号，
因此写死在这里是安全的；测试目录本身也是 AI 自动修复的白名单范围
（contracts/workflow-state-machine.md §6）。
"""

from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("CORENOVA_APP_URL", "http://localhost:2368")
ADMIN_API = BASE_URL.rstrip("/") + "/ghost/api/admin"
OWNER_EMAIL = "verify@corenovalaunch.test"
OWNER_PASSWORD = "CoreNova-Verify-2026!"
OWNER_NAME = "CoreNova Verify"


def api_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
    return s


def setup_token(s: requests.Session) -> str | None:
    """Ghost 在尚无 owner 时，通过该端点暴露一次性 setup token。"""
    try:
        r = s.get(f"{ADMIN_API}/authentication/setup/", timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("setup") if isinstance(data, dict) else data
        return items[0]["token"] if items else None
    except Exception:  # noqa: BLE001
        return None


def seed_owner(s: requests.Session) -> dict[str, str] | None:
    """创建 owner（幂等）。返回 {access_token, refresh_token} 或 None。"""
    token = setup_token(s)
    if not token:
        # 已有 owner：走密码登录
        r = s.post(
            f"{ADMIN_API}/authentication/",
            json={
                "username": OWNER_EMAIL,
                "password": OWNER_PASSWORD,
                "grant_type": "password",
                "scope": "all",
                "client_id": "ghost-admin",
            },
            timeout=20,
        )
        if r.status_code == 200:
            d = r.json()
            return {"access_token": d.get("access_token", ""), "refresh_token": d.get("refresh_token", "")}
        return None
    r = s.post(
        f"{ADMIN_API}/authentication/setup/",
        json={"setup": [{"name": OWNER_NAME, "email": OWNER_EMAIL, "password": OWNER_PASSWORD, "token": token}]},
        timeout=60,
    )
    if r.status_code not in (200, 201):
        return None
    d = r.json()
    return {"access_token": d.get("access_token", ""), "refresh_token": d.get("refresh_token", "")}


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def api() -> requests.Session:
    return api_session()


@pytest.fixture(scope="session")
def owner_tokens(api) -> dict[str, str] | None:
    return seed_owner(api)


@pytest.fixture(scope="session")
def auth_api(owner_tokens) -> requests.Session:
    if not owner_tokens or not owner_tokens.get("access_token"):
        pytest.skip("未能创建/登录 Ghost owner，后台鉴权用例无法执行")
    s = api_session()
    s.headers["Authorization"] = f"Bearer {owner_tokens['access_token']}"
    return s


@pytest.fixture(scope="session")
def browser_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.set_default_timeout(60_000)
        try:
            yield page
        finally:
            browser.close()
