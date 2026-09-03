"""通过当前源码适配器执行真实 UP 主发现并记录允许的公开响应。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.cookie import check_cookie_status
from app.metadata import MetadataError, fetch_video_metadata
from app.search import (
    UA,
    SearchError,
    clear_search_caches,
    creator_profile,
    creator_submissions,
    search_creators,
)
from app.urls import Target
from tools.bilibili_live.contracts import (
    LiveBlockedError,
    LiveFailedError,
    LiveInconclusiveError,
    LiveMarker,
)
from tools.bilibili_live.fixtures import RecordingClient


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    profile: dict[str, Any]
    items: tuple[dict[str, Any], ...]
    page_by_bvid: dict[str, int]
    submission_pages: int
    name_search_page: int


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise LiveInconclusiveError("真实发现阶段达到 15 分钟总时限")


def _map_search_error(exc: BaseException) -> LiveTestErrorAlias:
    code = getattr(exc, "code", "")
    cause = exc.__cause__
    message = str(exc)
    if isinstance(exc, SearchError) and (
        isinstance(cause, (TypeError, ValueError))
        or "格式无效" in message
        or "无法识别的数据" in message
    ):
        return LiveFailedError("当前源码无法解析真实 Bilibili 公开响应")
    if code in {
        "bilibili_login_required",
        "bilibili_risk_control",
        "bilibili_unavailable",
        "creator_inaccessible",
        "creator_not_found",
    } or isinstance(exc, (MetadataError, httpx.HTTPError)):
        return LiveBlockedError("真实 Bilibili 环境或固定目标阻止了发现")
    return LiveFailedError("当前源码无法解析真实 Bilibili 公开响应")


LiveTestErrorAlias = LiveBlockedError | LiveFailedError | LiveInconclusiveError


def _owner_uid(payload: Any) -> str:
    data = payload.get("data") if isinstance(payload, dict) else None
    owner = data.get("owner") if isinstance(data, dict) else None
    mid = owner.get("mid") if isinstance(owner, dict) else None
    try:
        value = int(mid)
    except (TypeError, ValueError):
        return ""
    return str(value) if value > 0 else ""


def _read_public_cover(client: httpx.Client, url: str) -> None:
    if not url.startswith("https://"):
        raise LiveFailedError("真实作品封面 URL 未经过 HTTPS 安全归一化")
    try:
        with client.stream(
            "GET",
            url,
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
            timeout=30,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("image/"):
                raise LiveFailedError("真实作品封面不是图片响应")
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 16 * 1024 * 1024:
                    raise LiveFailedError("真实作品封面响应异常过大")
            if size <= 0:
                raise LiveFailedError("真实作品封面响应为空")
    except httpx.HTTPError as exc:
        raise LiveBlockedError("真实作品封面当前无法访问") from exc


def discover_marker_targets(
    *,
    marker: LiveMarker,
    bbdown_data_dir: Path,
    raw_root: Path,
    deadline: float,
) -> DiscoveryResult:
    clear_search_caches()
    try:
        with RecordingClient(raw_root) as recorder:
            try:
                _check_deadline(deadline)
                login = check_cookie_status(bbdown_data_dir, client=recorder)
                if login.logged_in is not True or login.online_verified is not True:
                    raise LiveBlockedError("复制的 Bilibili 登录已经失效或无法在线确认")
                _check_deadline(deadline)
                profile = creator_profile(
                    marker.creator_uid,
                    bbdown_dir=bbdown_data_dir,
                    client=recorder,
                    fresh=True,
                )
                if str(profile.get("uid") or "") != marker.creator_uid:
                    raise LiveFailedError("真实 UP 主资料 UID 与固定场景不一致")
                profile_name = str(profile.get("name") or "").strip()
                if not profile_name:
                    raise LiveBlockedError("真实 UP 主资料当前缺少可搜索名称")

                name_search_page = 0
                found_creator = False
                page = 1
                while not found_creator:
                    _check_deadline(deadline)
                    result = search_creators(
                        profile_name,
                        page=page,
                        bbdown_dir=bbdown_data_dir,
                        client=recorder,
                        fresh=True,
                    )
                    if any(
                        str(item.get("uid") or "") == marker.creator_uid
                        for item in result.get("items") or []
                        if isinstance(item, dict)
                    ):
                        found_creator = True
                        name_search_page = page
                        break
                    pages = max(0, int(result.get("pages") or 0))
                    if page >= pages:
                        break
                    page += 1
                if not found_creator:
                    raise LiveBlockedError("UP 主名称搜索当前没有返回标记 UID")

                remaining = set(marker.download_bvids)
                submissions: dict[str, dict[str, Any]] = {}
                page_by_bvid: dict[str, int] = {}
                page = 1
                total_pages = 0
                while remaining:
                    _check_deadline(deadline)
                    result = creator_submissions(
                        marker.creator_uid,
                        order="pubdate",
                        page=page,
                        bbdown_dir=bbdown_data_dir,
                        client=recorder,
                        fresh=True,
                    )
                    total_pages = max(total_pages, int(result.get("pages") or 0))
                    for item in result.get("items") or []:
                        if not isinstance(item, dict):
                            continue
                        bvid = str(item.get("bvid") or "")
                        if bvid in remaining:
                            submissions[bvid] = dict(item)
                            page_by_bvid[bvid] = page
                            remaining.remove(bvid)
                    if not remaining or page >= total_pages:
                        break
                    page += 1
                if remaining:
                    raise LiveBlockedError("固定场景中的作品不再出现在指定 UP 主投稿中")

                cover_client = httpx.Client(timeout=30, trust_env=False, follow_redirects=False)
                try:
                    normalized: list[dict[str, Any]] = []
                    for bvid in marker.download_bvids:
                        _check_deadline(deadline)
                        target = Target(
                            key=bvid,
                            bvid=bvid,
                            url=f"https://www.bilibili.com/video/{bvid}",
                        )
                        metadata = fetch_video_metadata(
                            target,
                            bbdown_data_dir,
                            client=recorder,
                        )
                        if _owner_uid(recorder.last_payload("video-detail")) != marker.creator_uid:
                            raise LiveBlockedError("标记作品的真实 owner.mid 与 UID 不一致")
                        if metadata.get("bvid") != bvid:
                            raise LiveFailedError("当前源码返回了错误的作品身份")
                        cover = str(metadata.get("cover") or "")
                        _read_public_cover(cover_client, cover)
                        item = dict(submissions[bvid])
                        item.update(metadata)
                        item["duration_seconds"] = submissions[bvid].get("duration_seconds")
                        normalized.append(item)
                finally:
                    cover_client.close()
            except (SearchError, MetadataError, httpx.HTTPError) as exc:
                raise _map_search_error(exc) from exc
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise LiveFailedError("当前源码无法解析真实 Bilibili 公开响应") from exc
            finally:
                recorder.write_index()
    finally:
        clear_search_caches()
    return DiscoveryResult(
        profile=dict(profile),
        items=tuple(normalized),
        page_by_bvid=page_by_bvid,
        submission_pages=total_pages,
        name_search_page=name_search_page,
    )
