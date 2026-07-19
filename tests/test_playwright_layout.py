from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Page, Route, sync_playwright  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
VIEWPORTS = [
    (1920, 1080),
    (1440, 900),
    (1024, 768),
    (768, 1024),
    (390, 844),
]
RUN_LAYOUT = os.getenv("BILI_RUN_PLAYWRIGHT") == "1"
pytestmark = [
    pytest.mark.playwright,
    pytest.mark.skipif(
        not RUN_LAYOUT,
        reason="set BILI_RUN_PLAYWRIGHT=1 to run Chromium layout checks",
    ),
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
        executable_path = os.getenv("BILI_PLAYWRIGHT_CHROMIUM") or None
        instance = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=["--no-sandbox"],
        )
        yield instance
        instance.close()


def envelope(data=None, **extra):
    payload = {"ok": True, "data": data}
    payload.update(extra)
    return payload


def search_items(page: int) -> list[dict]:
    if page == 1:
        specs = [
            ("BV1LAYOUT001", "测试 原因 完整讲解", "not_downloaded", []),
            ("BV1LAYOUT002", "测试工具", "downloaded", ["夯"]),
            ("BV1LAYOUT003", "完全无关", "deleted", []),
        ]
    else:
        specs = [
            (f"BV1LAYOUT{page:03d}A", f"测试 原因 第 {page} 页", "not_downloaded", []),
        ]
    return [
        {
            "bvid": bvid,
            "title": title,
            "author": "测试UP",
            "play": 12345,
            "duration": "01:23",
            "pubdate": 1_700_000_000,
            "cover": "",
            "url": f"https://www.bilibili.com/video/{bvid}",
            "local_status": status,
            "local_status_label": {
                "not_downloaded": "未下载",
                "downloaded": "已下载",
                "deleted": "已删除",
            }[status],
            "deleted_record": status == "deleted",
            "tags": tags,
        }
        for bvid, title, status, tags in specs
    ]


def mock_api(route: Route) -> None:
    parsed = urlparse(route.request.url)
    path = parsed.path
    query = parse_qs(parsed.query)
    if path == "/api/events":
        route.abort()
        return
    if path == "/api/cover":
        route.fulfill(status=204, body="")
        return
    if path == "/api/auth/status":
        payload = envelope(
            {
                "authenticated": True,
                "required": False,
                "setup_required": False,
                "csrf_token": "",
                "username": "local",
            }
        )
    elif path == "/api/status":
        payload = envelope(
            {
                "version": "0.5.6",
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
                "items": ["未分组"],
                "records": [
                    {
                        "id": "group-default",
                        "display_name": "未分组",
                        "folder_key": "default",
                        "media_count": 0,
                        "task_count": 0,
                    }
                ],
            }
        )
    elif path == "/api/tasks":
        payload = envelope([], summary={"all": 0, "active": 0, "queued": 0, "running": 0, "failed": 0})
    elif path == "/api/enhancements/tags":
        payload = envelope({"items": [{"name": "夯", "color": "#d4a017"}]})
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
    elif path == "/api/account/bilibili":
        payload = envelope({})
    elif path == "/api/search":
        page = int(query.get("page", ["1"])[0])
        items = search_items(page)
        payload = envelope(
            {
                "keyword": query.get("q", [""])[0],
                "order": query.get("order", ["totalrank"])[0],
                "page": page,
                "pages": 5,
                "total": 100,
                "numPages": 5,
                "numResults": 100,
                "items": items,
                "cached": False,
            }
        )
    else:
        payload = envelope({})
    route.fulfill(
        status=200,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
    )


def assert_no_horizontal_overflow(page: Page) -> None:
    metrics = page.evaluate(
        """() => ({
          viewport: window.innerWidth,
          html: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          root: document.querySelector('#pageRoot')?.scrollWidth || 0,
        })"""
    )
    assert metrics["html"] <= metrics["viewport"] + 1, metrics
    assert metrics["body"] <= metrics["viewport"] + 1, metrics
    assert metrics["root"] <= metrics["viewport"] + 1, metrics


def assert_visible_controls_do_not_overlap(page: Page, selector: str) -> None:
    overlaps = page.eval_on_selector_all(
        selector,
        """nodes => {
          const visible = nodes.filter(node => {
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          });
          const hits = [];
          for (let i = 0; i < visible.length; i += 1) {
            const a = visible[i].getBoundingClientRect();
            for (let j = i + 1; j < visible.length; j += 1) {
              const b = visible[j].getBoundingClientRect();
              const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
              const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
              if (x > 2 && y > 2) hits.push([visible[i].id || visible[i].textContent, visible[j].id || visible[j].textContent]);
            }
          }
          return hits;
        }""",
    )
    assert overlaps == []


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_search_filtering_preload_and_layout(browser: Browser, width: int, height: int) -> None:
    requests: list[str] = []
    with static_site() as base_url:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.route("**/api/**", mock_api)
        page.on(
            "request",
            lambda request: requests.append(request.url)
            if urlparse(request.url).path == "/api/search"
            else None,
        )
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="search"]')
        page.fill("#enhSearchQuery", "测试 原因")
        page.click("#enhSearchButton")
        page.wait_for_selector('[data-search-key="BV1LAYOUT001"]')
        page.wait_for_timeout(350)

        pages_requested = [int(parse_qs(urlparse(url).query)["page"][0]) for url in requests]
        assert pages_requested.count(1) == 1
        assert set(pages_requested) <= {1, 2}
        assert pages_requested.count(2) <= 1

        before_filter = len(requests)
        page.click('[data-search-filter-mode="all"]')
        page.fill("#enhSearchTitleFilter", "测试 原因")
        page.wait_for_timeout(50)
        assert len(requests) == before_filter
        assert page.locator('[data-search-key]:visible').count() == 1
        assert "原始 3 条" in page.locator("#enhSearchSummary").inner_text()
        assert "筛选后 1 条" in page.locator("#enhSearchSummary").inner_text()

        with page.expect_request(
            lambda request: urlparse(request.url).path == "/api/search"
            and parse_qs(urlparse(request.url).query).get("fresh") == ["true"]
        ):
            page.click("#enhSearchRefresh")
        page.wait_for_selector('[data-search-key="BV1LAYOUT001"]')
        page.wait_for_timeout(120)
        refreshed_pages = [int(parse_qs(urlparse(url).query)["page"][0]) for url in requests]
        assert refreshed_pages.count(1) == 2
        assert refreshed_pages.count(2) <= 1

        assert_no_horizontal_overflow(page)
        assert_visible_controls_do_not_overlap(
            page,
            '[data-enhanced-view="search"] button, [data-enhanced-view="search"] input, [data-enhanced-view="search"] select',
        )
        if width == 390:
            heights = page.eval_on_selector_all(
                ".enh-search-primary-actions .btn",
                "nodes => nodes.filter(n => getComputedStyle(n).display !== 'none').map(n => n.getBoundingClientRect().height)",
            )
            assert heights and min(heights) >= 44
        page.close()


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_current_admin_pages_fit_fixed_viewports(browser: Browser, width: int, height: int) -> None:
    pages = ["dashboard", "download", "search", "library", "groups", "tasks", "account", "settings"]
    with static_site() as base_url:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.route("**/api/**", mock_api)
        page.goto(f"{base_url}/#/dashboard", wait_until="domcontentloaded")
        page.wait_for_selector("#appRoot:not(.hidden)")
        for name in pages:
            page.evaluate("name => { location.hash = `#/${name}`; }", name)
            page.wait_for_function(
                "name => location.hash === `#/${name}` && !document.querySelector('#pageRoot .loading-card')",
                arg=name,
            )
            if name in {"search", "library", "tasks"}:
                page.wait_for_selector(f'[data-enhanced-view="{name}"]')
            assert_no_horizontal_overflow(page)
            assert_visible_controls_do_not_overlap(
                page,
                "#pageRoot button, #pageRoot input, #pageRoot select",
            )
        page.close()


def test_query_change_aborts_old_request_and_ignores_stale_response(browser: Browser) -> None:
    delayed_search_fetch = r"""
      (() => {
        const originalFetch = window.fetch.bind(window);
        window.__searchAbortCount = 0;
        window.fetch = (input, init = {}) => {
          const raw = typeof input === 'string' ? input : input.url;
          const url = new URL(raw, location.origin);
          if (url.pathname !== '/api/search') return originalFetch(input, init);
          const query = url.searchParams.get('q') || '';
          const pageNumber = Number(url.searchParams.get('page') || 1);
          const isOld = query.includes('旧');
          const payload = {
            ok: true,
            data: {
              keyword: query,
              order: url.searchParams.get('order') || 'totalrank',
              page: pageNumber,
              pages: 2,
              total: 2,
              items: [{
                bvid: isOld ? 'BV1STALE0001' : 'BV1CURRENT01',
                title: isOld ? '旧关键词结果' : '新关键词结果',
                author: '测试UP', play: 1, duration: '00:30', pubdate: 1700000000,
                cover: '', url: 'https://www.bilibili.com/video/test',
                local_status: 'not_downloaded', local_status_label: '未下载',
                deleted_record: false, tags: [],
              }],
            },
          };
          return new Promise((resolve, reject) => {
            let settled = false;
            const timer = setTimeout(() => {
              settled = true;
              resolve(new Response(JSON.stringify(payload), {
                status: 200,
                headers: {'Content-Type': 'application/json; charset=utf-8'},
              }));
            }, isOld ? 350 : 25);
            const abort = () => {
              if (settled) return;
              clearTimeout(timer);
              window.__searchAbortCount += 1;
              reject(new DOMException('Aborted', 'AbortError'));
            };
            if (init.signal?.aborted) abort();
            else init.signal?.addEventListener('abort', abort, {once: true});
          });
        };
      })();
    """
    with static_site() as base_url:
        page = browser.new_page(viewport={"width": 1024, "height": 768})
        page.add_init_script(delayed_search_fetch)
        page.route("**/api/**", mock_api)
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="search"]')

        page.fill("#enhSearchQuery", "旧关键词")
        page.click("#enhSearchButton")
        page.fill("#enhSearchQuery", "新关键词")
        page.click("#enhSearchButton")

        page.wait_for_selector('[data-search-key="BV1CURRENT01"]')
        page.wait_for_timeout(420)
        assert page.locator('[data-search-key="BV1STALE0001"]').count() == 0
        assert page.evaluate("window.__searchAbortCount") >= 1
        page.close()


def test_data_saver_disables_next_page_preload(browser: Browser) -> None:
    requests: list[str] = []
    with static_site() as base_url:
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.add_init_script(
            "Object.defineProperty(navigator, 'connection', {value: {saveData: true}, configurable: true});"
        )
        page.route("**/api/**", mock_api)
        page.on(
            "request",
            lambda request: requests.append(request.url)
            if urlparse(request.url).path == "/api/search"
            else None,
        )
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="search"]')
        page.fill("#enhSearchQuery", "省流量")
        page.click("#enhSearchButton")
        page.wait_for_selector('[data-search-key="BV1LAYOUT001"]')
        page.wait_for_timeout(250)
        pages_requested = [int(parse_qs(urlparse(url).query)["page"][0]) for url in requests]
        assert pages_requested == [1]
        page.close()


def test_failed_current_page_does_not_preload(browser: Browser) -> None:
    requests: list[str] = []

    def failing_search(route: Route) -> None:
        if urlparse(route.request.url).path == "/api/search":
            requests.append(route.request.url)
            route.fulfill(
                status=502,
                content_type="application/json; charset=utf-8",
                body=json.dumps({"ok": False, "error": "上游搜索失败"}, ensure_ascii=False),
            )
            return
        mock_api(route)

    with static_site() as base_url:
        page = browser.new_page(viewport={"width": 1024, "height": 768})
        page.route("**/api/**", failing_search)
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="search"]')
        page.fill("#enhSearchQuery", "失败")
        page.click("#enhSearchButton")
        page.wait_for_selector("#enhSearchResults .notice.bad")
        page.wait_for_timeout(250)
        assert len(requests) == 1
        page.close()


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_login_page_fits_fixed_viewports(browser: Browser, width: int, height: int) -> None:
    def login_api(route: Route) -> None:
        if urlparse(route.request.url).path == "/api/auth/status":
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(
                    envelope(
                        {
                            "authenticated": False,
                            "required": True,
                            "setup_required": False,
                            "csrf_token": "",
                        }
                    ),
                    ensure_ascii=False,
                ),
            )
            return
        mock_api(route)

    with static_site() as base_url:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.route("**/api/**", login_api)
        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_selector("#authRoot:not(.hidden) .auth-card")
        assert_no_horizontal_overflow(page)
        assert_visible_controls_do_not_overlap(page, "#authRoot button, #authRoot input")
        if width == 390:
            button_height = page.locator("#authForm .btn.primary").evaluate(
                "node => node.getBoundingClientRect().height"
            )
            assert button_height >= 44
        page.close()
