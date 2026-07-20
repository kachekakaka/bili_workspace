from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Route, sync_playwright  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
RUN_LAYOUT = os.getenv("BILI_RUN_PLAYWRIGHT") == "1"
pytestmark = [
    pytest.mark.playwright,
    pytest.mark.skipif(not RUN_LAYOUT, reason="set BILI_RUN_PLAYWRIGHT=1"),
]


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return None


@contextmanager
def static_site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietStaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture(scope="module")
def browser() -> Browser:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        yield instance
        instance.close()


def envelope(data=None, **extra):
    payload = {"ok": True, "data": data}
    payload.update(extra)
    return payload


USERS = [
    {
        "id": "admin-user",
        "username": "administrator",
        "display_name": "管理员",
        "role": "admin",
        "disabled": False,
        "must_change_password": False,
        "active_session_count": 2,
        "last_login_at": 1_700_000_000,
        "created_at": 1_699_000_000,
    },
    {
        "id": "user-a",
        "username": "guest-a",
        "display_name": "访客甲",
        "role": "user",
        "disabled": False,
        "must_change_password": False,
        "active_session_count": 1,
        "last_login_at": 1_700_000_050,
        "created_at": 1_699_500_000,
    },
]

GROUPS = [
    {
        "id": f"group-{index}",
        "display_name": "未分组" if index == 0 else f"分组 {index}",
        "folder_key": f"group-{index}",
        "media_count": 0,
        "task_count": 0,
        "active_count": 0,
        "failed_count": 0,
    }
    for index in range(10)
]


def mock_api(route: Route) -> None:
    path = urlparse(route.request.url).path
    method = route.request.method.upper()
    if path == "/api/events":
        route.abort()
        return
    if path == "/api/auth/status":
        payload = envelope(
            {
                "authenticated": True,
                "required": True,
                "setup_required": False,
                "csrf_token": "v062-csrf",
                "username": "administrator",
                "display_name": "管理员",
                "role": "admin",
                "permissions": ["admin:*"],
                "must_change_password": False,
                "user": USERS[0],
            }
        )
    elif path == "/api/status":
        payload = envelope(
            {
                "version": "0.6.2",
                "server_mode": False,
                "login_state": "valid",
                "message": "测试登录有效",
                "default_group": "未分组",
                "default_min_height": 1080,
                "download_dir": "/downloads",
                "temp_dir": "/tmp/exports",
                "cache_dir": "/tmp/cache",
                "library": {"media_count": 0, "total_size": 0},
            }
        )
    elif path == "/api/groups":
        payload = envelope(
            {
                "default_group": "未分组",
                "default_min_height": 1080,
                "items": [group["display_name"] for group in GROUPS],
                "records": GROUPS,
            }
        )
    elif path == "/api/tasks":
        payload = envelope([], summary={"all": 0, "active": 0, "queued": 0, "running": 0, "failed": 0}, grouped=[])
    elif path == "/api/admin/users" and method == "GET":
        payload = envelope({"items": USERS})
    elif path.startswith("/api/admin/users/"):
        payload = envelope({"sessions_revoked": 1})
    elif path == "/api/auth/sessions":
        payload = envelope(
            {
                "limit": 10,
                "items": [
                    {
                        "id": "session-current",
                        "current": True,
                        "user_agent": "Chromium 当前设备",
                        "remote_addr": "127.0.0.1",
                        "created_at": 1_700_000_000,
                        "last_seen_at": 1_700_000_100,
                        "expires_at": 1_800_000_000,
                    },
                    {
                        "id": "session-other",
                        "current": False,
                        "user_agent": "手机浏览器",
                        "remote_addr": "192.0.2.10",
                        "created_at": 1_700_000_010,
                        "last_seen_at": 1_700_000_090,
                        "expires_at": 1_800_000_000,
                    },
                ],
            }
        )
    elif path.startswith("/api/auth/sessions/") or path == "/api/auth/profile":
        payload = envelope({"revoked": 1})
    elif path == "/api/enhancements/tags":
        payload = envelope({"items": []})
    elif path == "/api/library/summary":
        payload = envelope({"media_count": 0, "total_size": 0})
    elif path in {"/api/library", "/api/enhancements/library"}:
        payload = envelope({"items": [], "page": 1, "pages": 1, "total": 0})
    elif path == "/api/config":
        payload = envelope(
            {
                "host": "127.0.0.1",
                "port": 3398,
                "download_dir": "/downloads",
                "temp_dir": "/tmp/exports",
                "cache_dir": "/tmp/cache",
                "default_group": "未分组",
                "default_min_height": 1080,
                "download_timeout_sec": 3600,
                "poll_hint_ms": 1000,
                "dfn_priority": "",
                "encoding_priority": "",
            }
        )
    else:
        payload = envelope({})
    route.fulfill(
        status=200,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
    )


def new_page(browser: Browser, base_url: str, path: str):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.add_init_script(
        "window.__nativePromptCalled = false; window.prompt = () => { window.__nativePromptCalled = true; return null; };"
    )
    page.route("**/api/**", mock_api)
    page.goto(f"{base_url}/#/{path}", wait_until="domcontentloaded")
    return page


def test_account_credentials_are_separated_into_tabs(browser: Browser) -> None:
    with static_site() as base_url:
        page = new_page(browser, base_url, "account")
        page.wait_for_selector("#v062AccountTabs")
        assert page.locator('[data-v062-account-panel="bilibili"]').is_visible()
        assert page.locator('[data-v062-account-panel="website"]').is_hidden()
        page.click('[data-v062-account-tab="website"]')
        page.wait_for_selector("#v062SessionPanel .v062-session-row")
        assert page.locator('[data-v062-account-panel="website"] h2').inner_text() == "网站账号"
        assert page.locator('[data-v062-account-panel="bilibili"]').is_hidden()
        assert page.locator("#v062SessionPanel .v062-session-row").count() == 2
        page.close()


def test_user_and_group_prompt_actions_open_application_modals(browser: Browser) -> None:
    with static_site() as base_url:
        page = new_page(browser, base_url, "users")
        page.wait_for_selector("[data-user-edit]")
        page.click('[data-user-edit="user-a"]')
        page.wait_for_selector("#v062UserDisplayNameForm")
        assert page.evaluate("window.__nativePromptCalled") is False
        page.click("[data-v062-cancel]")
        page.click('[data-user-reset="user-a"]')
        page.wait_for_selector("#v062UserPasswordForm")
        assert page.evaluate("window.__nativePromptCalled") is False
        page.click("[data-v062-cancel]")
        page.goto(f"{base_url}/#/groups", wait_until="domcontentloaded")
        page.wait_for_selector('[data-rename-group="group-1"]')
        page.click('[data-rename-group="group-1"]')
        page.wait_for_selector("#v062GroupRenameForm")
        assert page.evaluate("window.__nativePromptCalled") is False
        page.close()


def test_large_group_select_uses_searchable_option_list(browser: Browser) -> None:
    with static_site() as base_url:
        page = new_page(browser, base_url, "download")
        page.wait_for_selector("#downloadGroup[data-v062-searchable='1']")
        page.click("#downloadGroup + .v062-select-trigger")
        page.fill("#v062SelectSearch", "分组 9")
        page.wait_for_selector('[data-v062-option="group-9"]')
        assert page.locator("#v062SelectOptions [data-v062-option]").count() == 1
        page.click('[data-v062-option="group-9"]')
        assert page.locator("#downloadGroup").input_value() == "group-9"
        page.close()
