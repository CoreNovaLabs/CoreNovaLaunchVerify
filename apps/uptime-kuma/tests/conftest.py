"""Uptime Kuma 预写测试的共用夹具。

与 Ghost 同理：容器是每次验证从零启动、跑完销毁的一次性环境。
Uptime Kuma 的业务 API 面是 socket.io，无稳定可调的 REST 管理端点，
因此预写测试只覆盖能用 HTTP 稳定断言的部分（见 test_home.py 的未覆盖说明）。
"""

from __future__ import annotations

import os

import pytest

BASE_URL = os.environ.get("CORENOVA_APP_URL", "http://localhost:3001")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


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
