from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Route, sync_playwright  # noqa: E402

from tests.test_playwright_layout import envelope, mock_api, static_site

RUN_LAYOUT = os.getenv("BILI_RUN_PLAYWRIGHT") == "1"
pytestmark = [
    pytest.mark.playwright,
    pytest.mark.skipif(
        not RUN_LAYOUT,
        reason="set BILI_RUN_PLAYWRIGHT=1 to run version recovery checks",
    ),
]


@pytest.fixture(scope="module")
def version_browser() -> Browser:
    with sync_playwright() as playwright:
        executable_path = os.getenv("BILI_PLAYWRIGHT_CHROMIUM") or None
        instance = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=["--no-sandbox"],
        )
        yield instance
        instance.close()


def test_version_mismatch_shows_explicit_recovery_action(version_browser: Browser) -> None:
    def route_api(route: Route) -> None:
        path = urlparse(route.request.url).path
        if path == "/healthz":
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(
                    {
                        "ok": True,
                        "service": "bili_workspace",
                        "version": "0.6.2",
                        "frontend_version": "stale-build",
                        "build_id": "abcdef123456",
                    },
                    ensure_ascii=False,
                ),
            )
            return
        if path.startswith("/api/"):
            mock_api(route)
            return
        route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(envelope({}), ensure_ascii=False),
        )

    with static_site() as base_url:
        page = version_browser.new_page(viewport={"width": 1024, "height": 768})
        page.route("**/healthz**", route_api)
        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/#/dashboard", wait_until="domcontentloaded")
        page.wait_for_selector('#browserVersionBadge[data-cache-match="false"]')
        badge = page.locator("#browserVersionBadge")
        assert "版本不一致" in badge.inner_text()
        assert "点击恢复" in badge.inner_text()
        assert "重新启动服务" in badge.get_attribute("title")
        assert badge.get_attribute("data-recovery-action") == "reload"
        assert badge.get_attribute("data-server-frontend-version") == "stale-build"
        page.close()
