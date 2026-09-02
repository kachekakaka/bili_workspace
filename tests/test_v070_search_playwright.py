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
        if path == "/api/download/selection":
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


def test_keyword_search_skips_fully_hidden_page_until_candidate(
    search_browser: Browser,
) -> None:
    requested_pages: list[int] = []

    def item(bvid: str, status: str, title: str) -> dict:
        return {
            "bvid": bvid,
            "title": title,
            "author": "测试UP",
            "play": 1,
            "duration": "00:10",
            "pubdate": 1_700_000_000,
            "cover": "",
            "url": f"https://www.bilibili.com/video/{bvid}",
            "local_status": status,
            "local_status_label": {
                "downloaded": "已下载",
                "deleted": "已删除",
                "not_downloaded": "未下载",
            }[status],
            "selectable": True,
            "tags": [],
        }

    def route_api(route: Route) -> None:
        parsed = urlparse(route.request.url)
        if parsed.path != "/api/search":
            mock_api(route)
            return
        query = dict(
            value.split("=", 1)
            for value in parsed.query.split("&")
            if "=" in value
        )
        page_number = int(query.get("page", "1"))
        requested_pages.append(page_number)
        items = (
            [
                item("BV1HIDDEN001", "downloaded", "已下载作品"),
                item("BV1HIDDEN002", "deleted", "不要的作品"),
            ]
            if page_number == 1
            else [item("BV1VISIBLE01", "not_downloaded", "可下载作品")]
        )
        route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(
                envelope(
                    {
                        "keyword": "按需续页",
                        "order": "totalrank",
                        "page": page_number,
                        "pages": 3,
                        "total": 60,
                        "items": items,
                        "limits": {
                            "selection": 100,
                            "auto_scan_pages": 10,
                            "page_size": 20,
                            "active_tasks": 0,
                        },
                    }
                ),
                ensure_ascii=False,
            ),
        )

    with static_site() as base_url:
        page = search_browser.new_page(viewport={"width": 1024, "height": 768})
        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.wait_for_selector('[data-enhanced-view="search"]')
        page.fill("#enhSearchQuery", "按需续页")
        page.click("#enhSearchButton")
        page.wait_for_selector('[data-search-key="BV1VISIBLE01"]')

        assert requested_pages == [1, 2]
        assert "第 1–2 页" in page.locator("#enhSearchResults .notice").first.inner_text()
        page.close()


def test_creator_name_selection_scans_on_demand_and_preserves_conflicted_batch(
    search_browser: Browser,
) -> None:
    submission_pages: list[int] = []
    selection_requests: list[dict] = []
    import_requests: list[dict] = []
    import_jobs: list[dict] = []
    cover_requests: list[str] = []

    def submission_item(bvid: str, status: str, title: str) -> dict:
        return {
            "bvid": bvid,
            "title": title,
            "author": "测试UP",
            "play": 123,
            "duration": "00:10",
            "duration_seconds": 10,
            "pubdate": 1_700_000_000,
            "cover": "https://i0.hdslb.com/bfs/cover/test.jpg",
            "url": f"https://www.bilibili.com/video/{bvid}",
            "local_status": status,
            "local_status_label": {
                "downloaded": "已下载",
                "deleted": "已删除",
                "not_downloaded": "未下载",
            }[status],
            "selectable": True,
            "block_reason": "",
            "tags": [],
        }

    def route_api(route: Route) -> None:
        parsed = urlparse(route.request.url)
        path = parsed.path
        query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
        if path == "/api/cover":
            cover_requests.append(route.request.url)
            route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>',
            )
            return
        if path == "/api/bilibili/creators/search":
            payload = envelope(
                {
                    "keyword": "测试UP",
                    "page": 1,
                    "pages": 1,
                    "total": 1,
                    "page_size": 20,
                    "items": [
                        {
                            "uid": "123456",
                            "name": "测试UP",
                            "avatar": "",
                            "bio": "公开简介",
                            "followers": 99,
                            "submission_count": 60,
                            "profile_url": "https://space.bilibili.com/123456",
                        }
                    ],
                }
            )
        elif path == "/api/bilibili/creators/resolve":
            payload = envelope(
                {
                    "state": "ready",
                    "creator": {
                        "uid": "123456",
                        "name": "测试UP",
                        "avatar": "",
                        "bio": "公开简介",
                        "followers": 99,
                        "submission_count": 60,
                        "profile_url": "https://space.bilibili.com/123456",
                    },
                    "submissions": {
                        "uid": "123456",
                        "order": "pubdate",
                        "page": 1,
                        "pages": 3,
                        "total": 60,
                        "page_size": 20,
                        "items": [
                            submission_item("BV1CREATOR01", "downloaded", "已下载投稿"),
                            submission_item("BV1CREATOR02", "deleted", "不要的投稿"),
                        ],
                        "limits": {
                            "selection": 100,
                            "auto_scan_pages": 10,
                            "page_size": 20,
                            "active_tasks": 0,
                        },
                    },
                }
            )
        elif path == "/api/bilibili/creators/123456/submissions":
            page_number = int(query.get("page", "1"))
            submission_pages.append(page_number)
            payload = envelope(
                {
                    "uid": "123456",
                    "order": "pubdate",
                    "page": page_number,
                    "pages": 3,
                    "total": 60,
                    "page_size": 20,
                    "items": [
                        submission_item("BV1CREATOR03", "not_downloaded", "可下载投稿")
                    ],
                    "limits": {
                        "selection": 100,
                        "auto_scan_pages": 10,
                        "page_size": 20,
                        "active_tasks": 0,
                    },
                }
            )
        elif path == "/api/bilibili/creator-imports" and route.request.method == "GET":
            payload = envelope({"items": list(import_jobs)})
        elif path == "/api/bilibili/creator-imports" and route.request.method == "POST":
            import_requests.append(route.request.post_data_json)
            job = {
                "id": "creator-import-1",
                "uid": "123456",
                "creator_name": "测试UP",
                "group_name": "未分组",
                "min_height": 1080,
                "status": "discovering",
                "phase": "discovering",
                "created_at": 1_700_000_000,
                "current_page": 1,
                "total_pages": 3,
                "discovered": 20,
                "processed": 0,
                "queued": 0,
                "can_cancel": True,
            }
            import_jobs[:] = [job]
            payload = envelope({"job": job, "created": True})
        elif path == "/api/download/selection":
            selection_requests.append(route.request.post_data_json)
            if len(selection_requests) == 1:
                route.fulfill(
                    status=409,
                    content_type="application/json; charset=utf-8",
                    body=json.dumps(
                        {
                            "ok": False,
                            "code": "batch_conflict",
                            "error": "批量冲突",
                            "data": {
                                "items": [
                                    {
                                        "source_key": "BV1CREATOR03",
                                        "code": "active_task_conflict",
                                        "message": "同一作品已有活动任务",
                                    }
                                ]
                            },
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            payload = envelope(
                [{"id": "creator-task", "status": "queued", "bvid": "BV1CREATOR03"}],
                total=1,
                limit=100,
            )
        else:
            mock_api(route)
            return
        route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(payload, ensure_ascii=False),
        )

    with static_site() as base_url:
        page = search_browser.new_page(viewport={"width": 1024, "height": 768})
        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/#/search", wait_until="domcontentloaded")
        page.click('[data-search-discovery-mode="creator"]')
        page.click('[data-creator-locator-mode="name"]')
        page.fill('[data-creator-input]', "测试UP")
        page.click('[data-creator-start]')
        page.wait_for_selector('[data-creator-pick="123456"]')
        page.click('[data-creator-pick="123456"]')
        page.wait_for_selector('[data-submission-key="BV1CREATOR03"]')

        assert submission_pages == [2]
        assert "第 1–2 页" in page.locator("[data-submission-results] .notice").first.inner_text()
        cover_src = page.locator('[data-submission-key="BV1CREATOR03"] img[data-cover-img]').get_attribute("src")
        assert cover_src and cover_src.startswith("/api/cover?url=https%3A")
        assert any("https%3A%2F%2Fi0.hdslb.com" in url for url in cover_requests)

        page.select_option('[data-submission-destination]', "device")
        page.wait_for_function(
            "() => document.querySelector('.creator-import-panel')?.classList.contains('hidden')"
        )
        page.select_option('[data-submission-destination]', "library")
        page.wait_for_selector('[data-creator-import-start]:not([disabled])')
        page.click('[data-creator-import-start]')
        page.wait_for_selector('[data-confirm-message]')
        confirmation = page.locator('[data-confirm-message]').inner_text()
        assert "忽略当前标题筛选和页面排序" in confirmation
        assert "删除历史" in confirmation
        page.click('[data-confirm-accept]')
        page.wait_for_selector('[data-creator-import-job="creator-import-1"]')
        assert import_requests == [
            {"uid": "123456", "group_id": "", "min_height": 1080}
        ]

        page.check('[data-submission-select="BV1CREATOR03"]')
        page.click('[data-submission-download-selected]')
        page.wait_for_selector('[data-submission-key="BV1CREATOR03"] .notice.bad')
        assert page.locator('[data-submission-select="BV1CREATOR03"]').is_checked()
        assert len(selection_requests) == 1

        page.click('[data-submission-download-selected]')
        page.wait_for_function(
            "() => document.querySelector('[data-submission-key=\"BV1CREATOR03\"]')?.textContent.includes('排队中')"
        )
        assert len(selection_requests) == 2
        assert selection_requests[1]["items"][0]["bvid"] == "BV1CREATOR03"
        assert selection_requests[1]["destination"] == "library"
        assert submission_pages == [2, 2]
        page.close()
