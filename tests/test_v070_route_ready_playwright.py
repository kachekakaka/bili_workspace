from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, sync_playwright  # noqa: E402

from tests.test_playwright_layout import mock_api, static_site

RUN_LAYOUT = os.getenv("BILI_RUN_PLAYWRIGHT") == "1"
pytestmark = [
    pytest.mark.playwright,
    pytest.mark.skipif(
        not RUN_LAYOUT,
        reason="set BILI_RUN_PLAYWRIGHT=1 to run Chromium route checks",
    ),
]


@pytest.fixture(scope="module")
def route_browser() -> Browser:
    with sync_playwright() as playwright:
        executable_path = os.getenv("BILI_PLAYWRIGHT_CHROMIUM") or None
        instance = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=["--no-sandbox"],
        )
        yield instance
        instance.close()


def test_every_admin_route_reaches_its_formal_ready_marker(route_browser: Browser) -> None:
    markers = {
        "dashboard": "#dashboardMetrics",
        "download": "#downloadForm",
        "search": '[data-enhanced-view="search"]',
        "library": '[data-enhanced-view="library"]',
        "groups": "#groupResults",
        "tasks": '[data-enhanced-view="tasks"]',
        "users": ".user-table-shell",
        "account": "#v062AccountTabs",
        "settings": "#settingsForm",
    }
    with static_site() as base_url:
        page = route_browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/api/**", mock_api)
        page.goto(f"{base_url}/#/dashboard", wait_until="domcontentloaded")
        page.wait_for_selector("#appRoot:not(.hidden)")
        for route, marker in markers.items():
            page.evaluate("route => { location.hash = `#/${route}`; }", route)
            try:
                page.wait_for_selector(marker, timeout=15_000)
            except Exception as error:
                content = page.locator("#pageRoot").inner_text()
                pytest.fail(f"route {route!r} did not reach {marker!r}; pageRoot={content!r}; {error}")
            assert page.locator("#pageRoot .loading-card").count() == 0, route
        page.close()
