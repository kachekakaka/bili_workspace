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
        reason="set BILI_RUN_PLAYWRIGHT=1 to run Chromium Search checks",
    ),
]


@pytest.fixture(scope="module")
def search_browser() -> Browser:
    with sync_playwright() as playwright:
        executable_path = os.getenv("BILI_PLAYWRIGHT_CHROMIUM") or None
        instance = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=["--no-sandbox"],
        )
        yield instance
        instance.close()


def test_stale_search_response_cannot_overwrite_library_or_tasks(
    search_browser: Browser,
) -> None:
    with static_site() as base_url:
        page = search_browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script(
            """
            (() => {
              const originalFetch = window.fetch.bind(window);
              window.fetch = async (input, init) => {
                const response = await originalFetch(input, init);
                const url = new URL(typeof input === 'string' ? input : input.url, location.href);
                if (url.pathname === '/api/search' && url.searchParams.get('q') === '慢查询') {
                  await new Promise(resolve => setTimeout(resolve, 450));
                }
                return response;
              };
            })();
            """
        )
        page.route("**/api/**", mock_api)
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="search"]')
        page.fill("#enhSearchQuery", "慢查询")
        page.click("#enhSearchButton")
        page.evaluate("location.hash = '#/library'")
        page.wait_for_selector('[data-enhanced-view="library"]')
        page.evaluate("location.hash = '#/tasks'")
        page.wait_for_selector('[data-enhanced-view="tasks"]')
        page.wait_for_timeout(650)
        assert page.locator('[data-enhanced-view="tasks"]').count() == 1
        assert page.locator('[data-enhanced-view="search"]').count() == 0
        assert page.locator("[data-search-key]").count() == 0
        page.close()


def test_create_task_on_second_page_preserves_search_route_and_page(
    search_browser: Browser,
) -> None:
    download_requests: list[dict] = []

    def route_api(route: Route) -> None:
        path = urlparse(route.request.url).path
        if path == "/api/download":
            download_requests.append(route.request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(
                    envelope(
                        [
                            {
                                "id": "created-task",
                                "status": "queued",
                                "bvid": "BV1LAYOUT002A",
                            }
                        ],
                        total=1,
                    ),
                    ensure_ascii=False,
                ),
            )
            return
        mock_api(route)

    with static_site() as base_url:
        page = search_browser.new_page(viewport={"width": 1024, "height": 768})
        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="search"]')
        page.fill("#enhSearchQuery", "测试")
        page.click("#enhSearchButton")
        page.wait_for_selector('[data-search-key="BV1LAYOUT001"]')
        page.click('[data-search-page="2"]')
        page.wait_for_selector('[data-search-key="BV1LAYOUT002A"]')
        page.check('[data-search-select="BV1LAYOUT002A"]')
        page.click("#enhSearchDownloadSelected")
        page.wait_for_function(
            "() => document.querySelector('#enhSearchSummary')?.textContent.includes('第 2 / 5 页')"
        )
        assert page.url.endswith("#/search")
        assert page.locator('[data-search-key="BV1LAYOUT002A"]').count() == 1
        assert len(download_requests) == 1
        assert download_requests[0]["items"][0]["bvid"] == "BV1LAYOUT002A"
        page.close()
