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


def test_library_shared_request_survives_route_exit_and_stale_retry(
    route_browser: Browser,
) -> None:
    delayed_library_fetch = r"""
      (() => {
        const originalFetch = window.fetch.bind(window);
        const state = {calls: 0, aborts: 0, fail: false, releaseFirst: null};
        window.__libraryFetchState = state;
        window.fetch = (input, init = {}) => {
          const raw = typeof input === 'string' ? input : input.url;
          const url = new URL(raw, location.origin);
          if (url.pathname !== '/api/enhancements/library') return originalFetch(input, init);
          state.calls += 1;
          const call = state.calls;
          return new Promise((resolve, reject) => {
            let settled = false;
            const finish = () => {
              if (settled) return;
              settled = true;
              if (state.fail) {
                reject(new Error('合成刷新失败'));
                return;
              }
              resolve(new Response(JSON.stringify({
                ok: true,
                data: {
                  items: [{
                    id: 'media-shared', source_key: 'BV1SHARED001', bvid: 'BV1SHARED001',
                    title: '共享请求测试', author: '测试UP', cover: '', group_id: 'group-default',
                    group_name: '未分组', total_size: 1024, selected_quality: '1080P',
                    selected_codec: 'AVC', duration_text: '01:23', watch_position: 0,
                    watch_duration: 83, primary_file_id: 'file-shared', tags: [],
                  }],
                  page: 1, pages: 1, total: 1,
                },
              }), {status: 200, headers: {'Content-Type': 'application/json; charset=utf-8'}}));
            };
            let timer = null;
            if (call === 1) state.releaseFirst = finish;
            else timer = setTimeout(finish, 25);
            const abort = () => {
              if (settled) return;
              settled = true;
              if (timer) clearTimeout(timer);
              state.aborts += 1;
              reject(new DOMException('Aborted', 'AbortError'));
            };
            if (init.signal?.aborted) abort();
            else init.signal?.addEventListener('abort', abort, {once: true});
          });
        };
      })();
    """
    with static_site() as base_url:
        page = route_browser.new_page(viewport={"width": 1024, "height": 768})
        page.add_init_script(delayed_library_fetch)
        page.route("**/api/**", mock_api)
        page.goto(f"{base_url}/#/library", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="library"]')
        page.wait_for_function("() => window.__libraryFetchState?.calls === 1")

        page.evaluate("location.hash = '#/dashboard'")
        page.wait_for_selector("#dashboardMetrics")
        page.evaluate("location.hash = '#/library'")
        page.wait_for_selector('[data-enhanced-view="library"]')
        state = page.evaluate(
            "() => ({calls: window.__libraryFetchState.calls, aborts: window.__libraryFetchState.aborts, fail: window.__libraryFetchState.fail})"
        )
        assert state == {"calls": 1, "aborts": 0, "fail": False}
        page.evaluate("window.__libraryFetchState.releaseFirst()")
        page.wait_for_selector('[data-library-id="media-shared"]')

        page.evaluate("window.__libraryFetchState.fail = true")
        page.evaluate("location.hash = '#/dashboard'")
        page.wait_for_selector("#dashboardMetrics")
        page.evaluate("location.hash = '#/library'")
        page.wait_for_selector('[data-library-id="media-shared"]')
        page.wait_for_function("() => window.__libraryFetchState?.calls === 2")
        page.wait_for_timeout(200)
        stale_state = page.evaluate(
            """() => ({
              fetch: {
                calls: window.__libraryFetchState.calls,
                aborts: window.__libraryFetchState.aborts,
                fail: window.__libraryFetchState.fail,
              },
              hash: location.hash,
              className: document.querySelector('#enhLibraryStale')?.className || '',
              text: document.querySelector('#enhLibraryStale')?.textContent || '',
            })"""
        )
        assert stale_state["className"] == "notice warn", stale_state
        assert "最近一次缓存" in page.locator("#enhLibraryStale").inner_text()

        page.evaluate("window.__libraryFetchState.fail = false")
        page.click("[data-library-retry]")
        page.wait_for_function(
            "() => document.querySelector('#enhLibraryStale')?.classList.contains('hidden')"
        )
        final_state = page.evaluate(
            "() => ({calls: window.__libraryFetchState.calls, aborts: window.__libraryFetchState.aborts, fail: window.__libraryFetchState.fail})"
        )
        assert final_state == {"calls": 3, "aborts": 0, "fail": False}
        page.close()
