from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Route, sync_playwright  # noqa: E402

from tests.test_playwright_layout import envelope, mock_api, static_site

RUN_LAYOUT = os.getenv("BILI_RUN_PLAYWRIGHT") == "1"
pytestmark = [
    pytest.mark.playwright,
    pytest.mark.skipif(
        not RUN_LAYOUT,
        reason="set BILI_RUN_PLAYWRIGHT=1 to run Chromium Library checks",
    ),
]


@pytest.fixture(scope="module")
def library_browser() -> Browser:
    with sync_playwright() as playwright:
        executable_path = os.getenv("BILI_PLAYWRIGHT_CHROMIUM") or None
        instance = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=["--no-sandbox"],
        )
        yield instance
        instance.close()


def library_item() -> dict:
    return {
        "id": "media-1",
        "source_key": "BV1LIBRARY01",
        "bvid": "BV1LIBRARY01",
        "title": "作品库迁移测试",
        "author": "测试UP",
        "cover": "",
        "group_id": "group-a",
        "group_name": "分组 A",
        "total_size": 1024,
        "selected_quality": "1080P",
        "selected_codec": "AVC",
        "duration_text": "01:23",
        "watch_position": 0,
        "watch_duration": 83,
        "primary_file_id": "file-1",
        "tags": [],
    }


def test_library_module_filters_moves_and_does_not_duplicate_actions(
    library_browser: Browser,
) -> None:
    calls: list[tuple[str, str, dict[str, list[str]]]] = []
    item = library_item()

    def route_api(route: Route) -> None:
        parsed = urlparse(route.request.url)
        path = parsed.path
        method = route.request.method
        query = parse_qs(parsed.query)
        calls.append((method, path, query))

        if path in {"/api/media/file-1/stream", "/api/media/file-2/stream"}:
            route.fulfill(status=204, body="")
            return
        if path == "/api/status":
            payload = envelope(
                {
                    "version": "0.7.0",
                    "server_mode": False,
                    "login_state": "valid",
                    "message": "测试登录有效",
                    "default_group": "分组 A",
                    "default_min_height": 1080,
                    "download_dir": "/downloads",
                    "temp_dir": "/tmp/exports",
                    "cache_dir": "/tmp/cache",
                    "library": {"media_count": 1, "total_size": 1024},
                    "group_records": [
                        {"id": "group-a", "display_name": "分组 A", "folder_key": "a", "media_count": 1, "task_count": 0},
                        {"id": "group-b", "display_name": "分组 B", "folder_key": "b", "media_count": 0, "task_count": 0},
                    ],
                }
            )
        elif path == "/api/groups":
            payload = envelope(
                {
                    "default_group": "分组 A",
                    "default_min_height": 1080,
                    "items": ["分组 A", "分组 B"],
                    "records": [
                        {"id": "group-a", "display_name": "分组 A", "folder_key": "a", "media_count": 1, "task_count": 0},
                        {"id": "group-b", "display_name": "分组 B", "folder_key": "b", "media_count": 0, "task_count": 0},
                    ],
                }
            )
        elif path == "/api/enhancements/tags" and method == "GET":
            payload = envelope(
                {
                    "items": [
                        {"name": "夯", "color": "#dc2626"},
                        {"name": "NPC", "color": "#64748b"},
                    ]
                }
            )
        elif path == "/api/enhancements/library" and method == "GET":
            payload = envelope(
                {
                    "items": [dict(item)],
                    "page": int(query.get("page", ["1"])[0]),
                    "pages": 1,
                    "total": 1,
                }
            )
        elif path == "/api/enhancements/library/items":
            payload = envelope([dict(item)])
        elif path == "/api/enhancements/tags" and method == "PUT":
            body = route.request.post_data_json
            item["tags"] = list(body.get("tags") or [])
            payload = envelope(
                {
                    "source_key": item["source_key"],
                    "tags": item["tags"],
                }
            )
        elif path == "/api/library/media-1/move":
            body = route.request.post_data_json
            item["group_id"] = body["group_id"]
            item["group_name"] = "分组 B" if body["group_id"] == "group-b" else "分组 A"
            payload = envelope(
                {
                    "group_id": item["group_id"],
                    "group_name": item["group_name"],
                }
            )
        elif path == "/api/library/media-1":
            payload = envelope(
                {
                    **item,
                    "source_url": "https://www.bilibili.com/video/BV1LIBRARY01",
                    "files": [
                        {
                            "id": "file-1",
                            "filename": "main.mp4",
                            "kind": "media",
                            "size": 1024,
                            "is_primary": True,
                            "watch_position": 12,
                        },
                        {
                            "id": "file-2",
                            "filename": "part-2.mp4",
                            "kind": "media",
                            "size": 2048,
                            "is_primary": False,
                            "watch_position": 0,
                        },
                    ],
                }
            )
        elif path == "/api/library/media-1/progress":
            payload = envelope({"saved": True})
        elif path == "/api/enhancements/library/delete":
            payload = envelope(
                {
                    "deleted": ["media-1"],
                    "errors": {},
                    "deleted_recorded": True,
                }
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
        page = library_browser.new_page(viewport={"width": 1024, "height": 768})
        page.add_init_script(
            """
            window.__nativeConfirmCalled = false;
            window.confirm = () => {
              window.__nativeConfirmCalled = true;
              return false;
            };
            """
        )
        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/#/library", wait_until="domcontentloaded")
        page.wait_for_selector('[data-library-id="media-1"]')

        page.click('[data-library-tag-chip="__untagged__"]')
        page.wait_for_function(
            "() => document.querySelector('#enhLibrarySummary')?.textContent.includes('共 1 个作品')"
        )
        assert any(
            path == "/api/enhancements/library"
            and query.get("tag") == ["__untagged__"]
            for _, path, query in calls
        )

        page.click('[data-library-group-chip="group-b"]')
        page.wait_for_function(
            "() => document.querySelector('#enhLibrarySummary')?.textContent.includes('共 1 个作品')"
        )
        assert any(
            path == "/api/enhancements/library"
            and query.get("group_id") == ["group-b"]
            for _, path, query in calls
        )

        page.click('[data-library-move="media-1"]')
        page.wait_for_selector("#enhMoveMediaForm")
        page.select_option("#enhMoveMediaGroup", "group-b")
        page.click('#enhMoveMediaForm button[type="submit"]')
        page.wait_for_selector('[data-library-id="media-1"]')
        move_calls = [entry for entry in calls if entry[1] == "/api/library/media-1/move"]
        assert len(move_calls) == 1

        for _ in range(10):
            page.evaluate("location.hash = '#/dashboard'")
            page.wait_for_selector("#dashboardMetrics")
            page.evaluate("location.hash = '#/library'")
            page.wait_for_selector('[data-library-id="media-1"]')

        page.click('[data-library-id="media-1"] [data-tag-name="夯"]')
        page.wait_for_function(
            "() => document.querySelector('[data-library-id=\"media-1\"] [data-tag-name=\"夯\"]')?.getAttribute('aria-pressed') === 'true'"
        )
        tag_calls = [
            entry
            for entry in calls
            if entry[0] == "PUT" and entry[1] == "/api/enhancements/tags"
        ]
        assert len(tag_calls) == 1

        page.click('[data-library-open="media-1"]')
        page.wait_for_selector("#enhMediaPlayer")
        assert page.locator("#enhMoveCurrentMediaGroup").count() == 1
        assert page.locator('[data-enh-play-file="file-2"]').count() == 1
        assert page.evaluate("window.__nativeConfirmCalled") is False
        page.close()


def test_library_selection_and_tag_updates_preserve_card_nodes(
    library_browser: Browser,
) -> None:
    items = [
        library_item(),
        {
            **library_item(),
            "id": "media-2",
            "source_key": "BV1LIBRARY02",
            "bvid": "BV1LIBRARY02",
            "title": "作品库节点身份测试",
            "primary_file_id": "file-2",
        },
    ]
    tag_updates = 0

    def route_api(route: Route) -> None:
        nonlocal tag_updates
        path = urlparse(route.request.url).path
        method = route.request.method
        if path == "/api/enhancements/library" and method == "GET":
            payload = envelope({"items": [dict(item) for item in items], "page": 1, "pages": 1, "total": 2})
        elif path == "/api/enhancements/tags" and method == "GET":
            payload = envelope({"items": [{"name": "夯", "color": "#dc2626"}]})
        elif path == "/api/enhancements/tags" and method == "PUT":
            tag_updates += 1
            body = route.request.post_data_json
            item = next(value for value in items if value["source_key"] == body["source_key"])
            item["tags"] = list(body.get("tags") or [])
            payload = envelope({"source_key": item["source_key"], "tags": item["tags"]})
        else:
            mock_api(route)
            return
        route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(payload, ensure_ascii=False),
        )

    with static_site() as base_url:
        page = library_browser.new_page(viewport={"width": 1024, "height": 768})
        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/#/library", wait_until="domcontentloaded")
        page.wait_for_selector('[data-library-id="media-2"]')
        page.evaluate(
            """() => {
              window.__libraryCardRefs = {
                first: document.querySelector('[data-library-id="media-1"]'),
                second: document.querySelector('[data-library-id="media-2"]'),
              };
            }"""
        )

        def card_identity() -> dict[str, bool]:
            return page.evaluate(
                """() => ({
                  first: document.querySelector('[data-library-id="media-1"]') === window.__libraryCardRefs.first,
                  second: document.querySelector('[data-library-id="media-2"]') === window.__libraryCardRefs.second,
                })"""
            )

        page.check('[data-library-select="media-1"]')
        assert card_identity() == {"first": True, "second": True}
        page.click("#enhLibrarySelectVisible")
        assert card_identity() == {"first": True, "second": True}
        page.click("#enhLibraryClear")
        assert card_identity() == {"first": True, "second": True}

        page.click('[data-library-id="media-1"] [data-tag-name="夯"]')
        page.wait_for_function(
            "() => document.querySelector('[data-library-id=\"media-1\"] [data-tag-name=\"夯\"]')?.getAttribute('aria-pressed') === 'true'"
        )
        assert tag_updates == 1
        assert card_identity() == {"first": True, "second": True}
        page.close()
