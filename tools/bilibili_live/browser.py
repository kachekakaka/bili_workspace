"""真实隔离产品页面的 Playwright 冒烟，不复用用户浏览器 profile。"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlsplit

from tools.bilibili_live.api import LiveApi
from tools.bilibili_live.contracts import (
    LiveBlockedError,
    LiveFailedError,
    LiveInconclusiveError,
    is_reparse,
)
from tools.bilibili_live.discovery import DiscoveryResult
from tools.bilibili_live.processes import isolated_process_environment
from tools.playwright_runtime import BrowserBlockedError, PROBE_ARGS, resolve_existing_browser


def _cookie_payloads(api: LiveApi) -> list[dict[str, str]]:
    cookies: list[dict[str, str]] = []
    for cookie in api.client.cookies.jar:
        if cookie.value:
            cookies.append({"name": cookie.name, "value": cookie.value, "url": api.base_url})
    if not cookies:
        raise LiveFailedError("隔离产品浏览器没有可复用的本地会话 Cookie")
    return cookies


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise LiveInconclusiveError("真实浏览器阶段达到 15 分钟总时限")


def _browser_environment(run_root: Path) -> dict[str, str]:
    return isolated_process_environment(run_root)


def _select_creator_name_page(page: Any, page_number: int, creator_uid: str) -> None:
    page.wait_for_selector("[data-creator-name-jump]", timeout=30_000)
    if page_number != 1:
        direct = page.locator(f'[data-creator-name-page="{page_number}"]')
        if direct.count() and direct.first.is_enabled():
            direct.first.click()
        else:
            page.fill("[data-creator-name-jump]", str(page_number))
            page.click("[data-creator-name-jump-button]")
    page.locator(f'[data-creator-pick="{creator_uid}"]').wait_for(timeout=30_000)


def _select_submission_page(page: Any, page_number: int, bvid: str | None = None) -> None:
    direct = page.locator(f'[data-submission-page="{page_number}"]')
    if direct.count():
        direct.first.click()
    else:
        jump = page.locator("[data-submission-jump]")
        button = page.locator("[data-submission-jump-button]")
        if not jump.count() or not button.count():
            raise LiveFailedError("投稿页面缺少跨页跳转控件")
        jump.fill(str(page_number))
        button.click()
    if bvid is not None:
        page.wait_for_selector(f'[data-submission-key="{bvid}"]', timeout=30_000)
    else:
        page.wait_for_function(
            "expected => document.querySelector('[data-submission-summary]')?.textContent?.includes(`第 ${expected} /`)",
            page_number,
            timeout=30_000,
        )


def _set_preferred_quality(page: Any, bvid: str, preferred_quality: str) -> None:
    if not preferred_quality:
        raise LiveFailedError("浏览器严格批量缺少预检指定画质")
    page.click(f'[data-submission-preview="{bvid}"]')
    selector = page.locator("[data-preview-quality]")
    selector.wait_for(timeout=30_000)
    selected = selector.select_option(value=preferred_quality)
    if selected != [preferred_quality]:
        raise LiveFailedError("产品页面无法选择预检指定画质")
    page.click('[role="dialog"] .close-button')
    page.locator('[role="dialog"]').wait_for(state="detached", timeout=10_000)


def submit_from_creator_page(
    *,
    api: LiveApi,
    run_root: Path,
    discovery: DiscoveryResult,
    items: list[dict[str, Any]],
    deadline: float,
) -> list[str]:
    _check_deadline(deadline)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise LiveBlockedError("当前环境没有既有 Playwright Python 包") from exc
    try:
        browser_executable = resolve_existing_browser()
    except BrowserBlockedError as exc:
        raise LiveBlockedError("当前环境没有可用的既有 Chromium 浏览器") from exc

    profile = Path(run_root) / "runtime" / "browser-profile"
    if profile.exists() or profile.is_symlink() or is_reparse(profile):
        raise LiveFailedError("真链浏览器 profile 不是全新路径")
    creator_uid = str(discovery.profile["uid"])
    creator_name = str(discovery.profile["name"])
    prepared = {str(item.get("bvid") or ""): item for item in items}
    if set(prepared) != set(discovery.page_by_bvid) or len(prepared) != 8:
        raise LiveFailedError("浏览器严格批量目标与真实发现结果不一致")
    task_ids: list[str] = []
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=str(browser_executable),
                headless=True,
                args=[
                    *PROBE_ARGS,
                    "--disable-breakpad",
                    "--disable-crash-reporter",
                    "--no-proxy-server",
                ],
                env=_browser_environment(run_root),
                timeout=30_000,
            )
        except PlaywrightError as exc:
            raise LiveBlockedError("既有 Chromium 无法启动隔离真链 profile") from exc
        try:
            _check_deadline(deadline)
            context.add_cookies(_cookie_payloads(api))
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(f"{api.base_url}/#/search", wait_until="domcontentloaded")
            page.wait_for_selector('[data-enhanced-view="search"]', timeout=30_000)
            page.click('[data-search-discovery-mode="creator"]')
            destination = page.locator("[data-submission-destination]")
            if destination.select_option(value="library") != ["library"]:
                raise LiveFailedError("产品页面无法固定真实下载目标为媒体库")
            quality = page.locator("[data-submission-quality]")
            if quality.select_option(value="0") != ["0"]:
                raise LiveFailedError("产品页面无法关闭会覆盖预检结果的最低清晰度筛选")
            page.click('[data-creator-locator-mode="name"]')
            page.fill("[data-creator-input]", creator_name)
            page.click("[data-creator-start]")
            _select_creator_name_page(page, discovery.name_search_page, creator_uid)
            candidate = page.locator(f'[data-creator-pick="{creator_uid}"]')
            candidate.click()
            page.wait_for_selector("[data-submission-results]", timeout=30_000)

            pages: dict[int, list[str]] = {}
            for bvid, page_number in discovery.page_by_bvid.items():
                pages.setdefault(page_number, []).append(bvid)
            for page_number in sorted(pages):
                _check_deadline(deadline)
                bvids = pages[page_number]
                _select_submission_page(page, page_number, bvids[0])
                for bvid in bvids:
                    _check_deadline(deadline)
                    card = page.locator(f'[data-submission-key="{bvid}"]')
                    card.wait_for(timeout=30_000)
                    card.scroll_into_view_if_needed(timeout=30_000)
                    image = card.locator("img[data-cover-img]")
                    loaded = bool(
                        image.count()
                        and image.evaluate(
                            "image => image.decode().then(() => image.complete && image.naturalWidth > 0).catch(() => false)"
                        )
                    )
                    source = str(image.get_attribute("src") or "") if image.count() else ""
                    if not source.startswith("/api/cover?url=") or not loaded:
                        raise LiveFailedError("真实投稿封面没有在产品页面加载")
                    _set_preferred_quality(
                        page,
                        bvid,
                        str(prepared[bvid].get("preferred_quality") or ""),
                    )
                    page.check(f'[data-submission-select="{bvid}"]')

            if discovery.submission_pages < 2:
                raise LiveBlockedError("指定 UP 主当前不足两页投稿，无法形成跨页选择证据")
            if len(pages) == 1:
                selected_page = next(iter(pages))
                detour_page = 1 if selected_page != 1 else 2
                _select_submission_page(page, detour_page)
                _select_submission_page(page, selected_page, pages[selected_page][0])

            import_button = page.locator("[data-creator-import-start]")
            _check_deadline(deadline)
            import_button.wait_for(timeout=30_000)
            import_button.click()
            page.wait_for_selector("[data-confirm-message]", timeout=10_000)
            page.click("[data-confirm-cancel]")
            if page.locator('[data-creator-import-job]').count():
                raise LiveFailedError("取消确认后仍启动了 UP 主全量入库")

            download_button = page.locator("[data-submission-download-selected]")
            _check_deadline(deadline)
            if "（8）" not in download_button.inner_text():
                raise LiveFailedError("跨页选择没有保留全部 8 个作品")
            with page.expect_response(
                lambda response: urlsplit(response.url).path == "/api/download/selection"
                and response.request.method == "POST",
                timeout=30_000,
            ) as response_info:
                download_button.click()
            response = response_info.value
            try:
                payload = response.json()
            except ValueError as exc:
                raise LiveFailedError("页面批量下载返回了非 JSON 响应") from exc
            data = payload.get("data") if isinstance(payload, dict) else None
            if (
                response.status != 200
                or not isinstance(payload, dict)
                or payload.get("ok") is not True
                or not isinstance(data, list)
            ):
                raise LiveFailedError("页面没有通过严格批量入口创建任务")
            task_ids = [str(item.get("id") or "") for item in data if isinstance(item, dict)]
            if (
                len(task_ids) != 8
                or len(set(task_ids)) != 8
                or any(not value for value in task_ids)
            ):
                raise LiveFailedError("页面严格批量入口没有返回 8 个任务")
        except PlaywrightError as exc:
            raise LiveFailedError("真实产品页面没有完成约定的批量下载交互") from exc
        finally:
            with suppress(PlaywrightError):
                context.close()
    return task_ids


def verify_dashboard_entry(
    *,
    api: LiveApi,
    run_root: Path,
    media_id: str,
    deadline: float,
    verify_playback: bool = False,
) -> None:
    _check_deadline(deadline)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise LiveBlockedError("当前环境没有既有 Playwright Python 包") from exc
    try:
        browser_executable = resolve_existing_browser()
    except BrowserBlockedError as exc:
        raise LiveBlockedError("当前环境没有可用的既有 Chromium 浏览器") from exc
    profile = Path(run_root) / "runtime" / "dashboard-browser-profile"
    if profile.exists() or profile.is_symlink() or is_reparse(profile):
        raise LiveFailedError("概览验证浏览器 profile 不是全新路径")
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=str(browser_executable),
                headless=True,
                args=[
                    *PROBE_ARGS,
                    "--disable-breakpad",
                    "--disable-crash-reporter",
                    "--no-proxy-server",
                ],
                env=_browser_environment(run_root),
                timeout=30_000,
            )
        except PlaywrightError as exc:
            raise LiveBlockedError("既有 Chromium 无法启动概览验证 profile") from exc
        try:
            _check_deadline(deadline)
            context.add_cookies(_cookie_payloads(api))
            page = context.pages[0] if context.pages else context.new_page()
            selector = f'[data-dashboard-media="{media_id}"]'
            page.goto(f"{api.base_url}/#/dashboard", wait_until="domcontentloaded")
            card = page.locator(selector)
            card.wait_for(timeout=30_000)
            if card.get_attribute("role") != "button" or card.get_attribute("tabindex") != "0":
                raise LiveFailedError("概览作品卡缺少可点击或键盘入口语义")
            if verify_playback:
                with page.expect_response(
                    lambda response: "/api/media/" in urlsplit(response.url).path
                    and urlsplit(response.url).path.endswith("/stream")
                    and bool(response.request.headers.get("range")),
                    timeout=30_000,
                ) as response_info:
                    card.click()
            else:
                card.click()
            page.wait_for_selector("#enhMediaPlayer", timeout=30_000)
            if verify_playback:
                page.wait_for_function(
                    "() => document.querySelector('#enhMediaPlayer')?.readyState >= 1",
                    timeout=30_000,
                )
                response = response_info.value
                if response.status != 206 or not response.headers.get("content-range"):
                    raise LiveFailedError("实际媒体播放没有形成有效 Range 响应")
            _check_deadline(deadline)
            page.goto(f"{api.base_url}/#/dashboard", wait_until="domcontentloaded")
            card = page.locator(selector)
            card.wait_for(timeout=30_000)
            card.focus()
            card.press("Enter")
            page.wait_for_selector("#enhMediaPlayer", timeout=30_000)
            _check_deadline(deadline)
        except PlaywrightError as exc:
            raise LiveFailedError("概览作品入口没有完成约定的页面交互") from exc
        finally:
            with suppress(PlaywrightError):
                context.close()
