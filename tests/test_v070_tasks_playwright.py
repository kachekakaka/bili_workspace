from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Route, sync_playwright  # noqa: E402

from tests.test_playwright_layout import envelope, mock_api, static_site, task_items

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


def test_task_stream_switches_modes_and_zero_lease_closes_it(task_browser: Browser) -> None:
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
              closed: window.__v070EventSources.map(source => source.closed),
            })"""
        )
        assert counts["total"] == 12
        assert counts["active"] == 1
        assert counts["urls"][:11] == ["/api/events"] * 11
        assert counts["urls"][-1] == "/api/events?view=summary"
        assert counts["closed"] == [True] * 11 + [False]

        page.evaluate("location.hash = '#/download'")
        page.wait_for_selector("#downloadForm")
        zero_lease = page.evaluate(
            """() => ({
              total: window.__v070EventSources.length,
              active: window.__v070EventSources.filter(source => !source.closed).length,
            })"""
        )
        assert zero_lease == {"total": 12, "active": 0}

        page.evaluate("location.hash = '#/dashboard'")
        page.wait_for_selector("#dashboardMetrics")
        assert page.evaluate(
            "window.__v070EventSources.filter(source => !source.closed).length"
        ) == 1

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
        assert after_logout == {"total": 13, "active": 0, "closed": [True] * 13}
        context.close()


def test_task_event_replaces_only_the_changed_card(task_browser: Browser) -> None:
    first = {
        **task_items()[0],
        "id": "task-1",
        "status": "running",
        "phase": "downloading",
        "phase_label": "正在下载",
        "finished_at": None,
    }
    second = {
        **task_items()[0],
        "id": "task-2",
        "key": "BV1TASK00002",
        "bvid": "BV1TASK00002",
        "title": "未变化任务",
        "display_title": "未变化任务",
    }
    import_job = {
        "id": "import-partial",
        "uid": "123456",
        "creator_name": "测试 UP",
        "group_name": "未分组",
        "min_height": 1080,
        "status": "partial",
        "phase": "partial",
        "created_at": 1_700_000_000,
        "finished_at": 1_700_000_100,
        "discovered": 5,
        "processed": 5,
        "queued": 4,
        "failed_count": 1,
        "failures": [{"bvid": "BV1FAILED001", "title": "失败投稿", "message": "合成失败"}],
        "can_retry_failed": True,
    }
    import_actions: list[str] = []
    event_source_script = """
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
            for (const listener of this.listeners.get(type) || []) listener({data});
          }
          close() { this.closed = true; }
        }
        window.EventSource = FakeEventSource;
        window.__v070EventSources = instances;
      })();
    """

    def route_api(route: Route) -> None:
        path = urlparse(route.request.url).path
        if path == "/api/bilibili/creator-imports" and route.request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(envelope({"items": [dict(import_job)]}), ensure_ascii=False),
            )
            return
        if path == "/api/bilibili/creator-imports/import-partial/retry-failed":
            import_actions.append("retry-failed")
            import_job.update(
                status="waiting",
                phase="waiting",
                can_retry_failed=False,
                failed_count=0,
                failures=[],
                finished_at=None,
            )
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(envelope(dict(import_job)), ensure_ascii=False),
            )
            return
        if path == "/api/tasks":
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(
                    envelope(
                        [first, second],
                        summary={"all": 2, "active": 1, "queued": 0, "running": 1, "failed": 0},
                        grouped=[],
                    ),
                    ensure_ascii=False,
                ),
            )
            return
        mock_api(route)

    with static_site() as base_url:
        page = task_browser.new_page(viewport={"width": 1024, "height": 768})
        page.add_init_script(event_source_script)
        page.route("**/api/**", route_api)
        page.goto(f"{base_url}/index.html#/tasks", wait_until="domcontentloaded")
        page.wait_for_selector('[data-task-id="task-2"]')
        page.wait_for_selector('[data-creator-import-job="import-partial"]')
        assert "全量入库作业" in page.locator(".creator-import-panel").inner_text()
        page.click('[data-creator-import-action="retry-failed"]')
        page.wait_for_function(
            "() => document.querySelector('[data-creator-import-job=\"import-partial\"]')?.textContent.includes('等待中')"
        )
        assert import_actions == ["retry-failed"]
        page.evaluate(
            """() => {
              window.__taskCardRefs = {
                first: document.querySelector('[data-task-id="task-1"]'),
                second: document.querySelector('[data-task-id="task-2"]'),
              };
            }"""
        )

        cancelling = {
            **first,
            "phase": "cancelling",
            "phase_label": "正在取消",
            "progress_message": "正在取消",
        }
        page.evaluate(
            "payload => window.__v070EventSources.at(-1).emit('tasks', JSON.stringify(payload))",
            {"tasks": [cancelling, second], "summary": {"all": 2, "active": 1, "running": 1}},
        )
        page.wait_for_function(
            "() => document.querySelector('[data-task-id=\"task-1\"]')?.textContent.includes('正在取消')"
        )
        cancelling_identity = page.evaluate(
            """() => ({
              firstChanged: document.querySelector('[data-task-id="task-1"]') !== window.__taskCardRefs.first,
              secondPreserved: document.querySelector('[data-task-id="task-2"]') === window.__taskCardRefs.second,
            })"""
        )
        assert cancelling_identity == {"firstChanged": True, "secondPreserved": True}
        page.evaluate(
            "window.__taskCardRefs.cancelling = document.querySelector('[data-task-id=\"task-1\"]')"
        )

        cancelled = {
            **cancelling,
            "status": "cancelled",
            "phase": "cancelled",
            "phase_label": "已取消",
            "finished_at": 1_700_000_200,
        }
        page.evaluate(
            "payload => window.__v070EventSources.at(-1).emit('tasks', JSON.stringify(payload))",
            {"tasks": [cancelled, second], "summary": {"all": 2, "active": 0, "running": 0}},
        )
        page.wait_for_function(
            "() => document.querySelector('[data-task-id=\"task-1\"]')?.textContent.includes('已取消')"
        )
        final_identity = page.evaluate(
            """() => ({
              firstChanged: document.querySelector('[data-task-id="task-1"]') !== window.__taskCardRefs.cancelling,
              secondPreserved: document.querySelector('[data-task-id="task-2"]') === window.__taskCardRefs.second,
            })"""
        )
        assert final_identity == {"firstChanged": True, "secondPreserved": True}
        page.close()
