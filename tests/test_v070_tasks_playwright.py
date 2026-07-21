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
        reason="set BILI_RUN_PLAYWRIGHT=1 to run Chromium lifecycle checks",
    ),
]


@pytest.fixture(scope="module")
def task_browser() -> Browser:
    with sync_playwright() as playwright:
        executable_path = os.getenv("BILI_PLAYWRIGHT_CHROMIUM") or None
        instance = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=["--no-sandbox"],
        )
        yield instance
        instance.close()


def test_tasks_reuse_one_sse_and_logout_closes_it(task_browser: Browser) -> None:
    with static_site() as base_url:
        context = task_browser.new_context(viewport={"width": 1024, "height": 768})
        page = context.new_page()
        logged_in = True

        page.add_init_script(
            """
            (() => {
              const instances = [];
              class FakeEventSource {
                constructor(url) {
                  this.url = url;
                  this.closed = false;
                  this.listeners = new Map();
                  instances.push(this);
                  queueMicrotask(() => this.emit('open', ''));
                }
                addEventListener(type, listener) {
                  if (!this.listeners.has(type)) this.listeners.set(type, []);
                  this.listeners.get(type).push(listener);
                }
                emit(type, data) {
                  for (const listener of this.listeners.get(type) || []) listener({ data });
                }
                close() { this.closed = true; }
              }
              window.EventSource = FakeEventSource;
              window.__v070EventSources = instances;
            })();
            """
        )

        def route_api(route: Route) -> None:
            nonlocal logged_in
            path = urlparse(route.request.url).path
            if path == "/api/auth/logout":
                logged_in = False
                route.fulfill(
                    status=200,
                    content_type="application/json; charset=utf-8",
                    body=json.dumps(envelope({}), ensure_ascii=False),
                )
                return
            if path == "/api/auth/status" and not logged_in:
                route.fulfill(
                    status=200,
                    content_type="application/json; charset=utf-8",
                    body=json.dumps(
                        envelope(
                            {
                                "authenticated": False,
                                "required": True,
                                "setup_required": False,
                            }
                        ),
                        ensure_ascii=False,
                    ),
                )
                return
            mock_api(route)

        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/index.html#/tasks", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="tasks"]')

        for _ in range(10):
            page.evaluate("location.hash = '#/download'")
            page.wait_for_selector("#downloadForm")
            page.evaluate("location.hash = '#/tasks'")
            page.wait_for_selector('[data-enhanced-view="tasks"]')

        page.evaluate("location.hash = '#/dashboard'")
        page.wait_for_selector("#dashboardMetrics")
        counts = page.evaluate(
            """() => ({
              total: window.__v070EventSources.length,
              active: window.__v070EventSources.filter(source => !source.closed).length,
              urls: window.__v070EventSources.map(source => source.url),
            })"""
        )
        assert counts == {"total": 1, "active": 1, "urls": ["/api/events"]}

        page.click("#userMenuButton")
        page.click("[data-menu-logout]")
        page.wait_for_selector("#authForm")
        after_logout = page.evaluate(
            """() => ({
              total: window.__v070EventSources.length,
              active: window.__v070EventSources.filter(source => !source.closed).length,
              closed: window.__v070EventSources.map(source => source.closed),
            })"""
        )
        assert after_logout == {"total": 1, "active": 0, "closed": [True]}
        context.close()
