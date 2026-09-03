"""有界下载、任务停止与媒体库成功证据。"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.quality import quality_labels_match
from tools.bilibili_live.api import LiveApi
from tools.bilibili_live.contracts import (
    MAX_RUN_GROWTH_BYTES,
    MAX_RUN_SECONDS,
    MIN_DOWNLOAD_FREE_BYTES,
    LiveBlockedError,
    LiveFailedError,
    LiveInconclusiveError,
    run_size_bytes,
)


TERMINAL = frozenset({"success", "failed", "skipped", "cancelled"})
_DOWNLOAD_BUDGET_RESERVE_BYTES = 128 * 1024**2
_SIZE_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>KB|KIB|MB|MIB|GB|GIB)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    completed_count: int
    failed_count: int
    cancelled_count: int
    stop_reason: str
    media_id: str
    successful_bvid: str
    preferred_quality: str
    selected_quality: str
    predicted_size_bytes: int


def _size_text_bytes(value: Any) -> int | None:
    match = _SIZE_RE.search(str(value or ""))
    if not match:
        return None
    number = float(match.group("value"))
    unit = match.group("unit").upper()
    factors = {
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024**2,
        "MIB": 1024**2,
        "GB": 1024**3,
        "GIB": 1024**3,
    }
    result = int(number * factors[unit])
    return result if result > 0 else None


def _duration_seconds(item: dict[str, Any]) -> int | None:
    value = item.get("duration_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return int(value)
    text = str(item.get("duration") or "").split("·", 1)[0].strip()
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if not parts or len(parts) > 3 or any(part < 0 for part in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return total or None


def _normalized_quality(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _track_height(track: dict[str, Any]) -> int:
    value = track.get("height")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    text = f"{track.get('resolution') or ''} {track.get('dfn') or ''}".upper()
    dimensions = re.search(r"(\d{3,5})\s*[X×]\s*(\d{3,5})", text)
    if dimensions:
        return min(int(dimensions.group(1)), int(dimensions.group(2)))
    if "8K" in text:
        return 4320
    if "4K" in text:
        return 2160
    if "2K" in text:
        return 1440
    labels = [int(value) for value in re.findall(r"(?<!\d)(360|480|720|1080|1440|2160|4320)P?", text)]
    return max(labels) if labels else 0


def _track_estimate(track: dict[str, Any], duration: int | None) -> int | None:
    explicit = _size_text_bytes(track.get("size_text"))
    if explicit is not None:
        return explicit
    bandwidth = track.get("bandwidth_kbps")
    if (
        isinstance(bandwidth, (int, float))
        and not isinstance(bandwidth, bool)
        and bandwidth > 0
        and duration is not None
    ):
        return max(1, int(float(bandwidth) * 1000 / 8 * duration))
    return None


def _bounded_quality_options(
    preview: dict[str, Any],
    item: dict[str, Any],
) -> list[tuple[tuple[int, int, str], str, int]]:
    quality = preview.get("quality")
    parts = quality.get("parts") if isinstance(quality, dict) else None
    if not isinstance(parts, list) or not parts:
        raise LiveFailedError("真实画质预检没有返回分段视频流")
    maps: list[dict[str, dict[str, Any]]] = []
    for part in parts:
        available = part.get("available") if isinstance(part, dict) else None
        if not isinstance(available, list) or not available:
            raise LiveFailedError("真实画质预检存在没有可用视频流的分段")
        tracks: dict[str, dict[str, Any]] = {}
        for value in available:
            if not isinstance(value, dict):
                continue
            label = str(value.get("dfn") or "").strip()
            key = _normalized_quality(label)
            if label and key:
                tracks.setdefault(key, value)
        if not tracks:
            raise LiveFailedError("真实画质预检缺少可选择的画质名称")
        maps.append(tracks)
    common = set(maps[0])
    for tracks in maps[1:]:
        common.intersection_update(tracks)
    if not common:
        raise LiveFailedError("真实画质预检没有覆盖全部分段的共同画质")

    duration = _duration_seconds(item)
    options: list[tuple[tuple[int, int, str], str, int]] = []
    for key in common:
        tracks = [mapping[key] for mapping in maps]
        estimates = [_track_estimate(track, duration) for track in tracks]
        if any(value is None for value in estimates):
            continue
        label = str(tracks[0].get("dfn") or "").strip()
        height = min(_track_height(track) for track in tracks)
        bandwidth = min(int(track.get("bandwidth_kbps") or 0) for track in tracks)
        options.append(((height, bandwidth, label.casefold()), label, sum(estimates)))
    if not options:
        raise LiveInconclusiveError("真实画质预检无法估算任何共同画质的下载大小")
    return sorted(options)


def _prepare_bounded_items(
    *,
    api: LiveApi,
    run_root: Path,
    workspace_root: Path,
    items: list[dict[str, Any]],
    started_at: float,
) -> tuple[list[dict[str, Any]], int]:
    current_size = run_size_bytes(run_root, workspace_root)
    remaining_budget = MAX_RUN_GROWTH_BYTES - current_size - _DOWNLOAD_BUDGET_RESERVE_BYTES
    if remaining_budget <= 0:
        raise LiveInconclusiveError("下载前真链运行已没有安全增长预算")
    available_budget = remaining_budget
    prepared: list[dict[str, Any]] = []
    predicted_total = 0
    for index, original in enumerate(items):
        if time.monotonic() - started_at >= MAX_RUN_SECONDS:
            raise LiveInconclusiveError("画质预检达到 15 分钟总时限")
        item = dict(original)
        preview = api.preview(item)
        options = _bounded_quality_options(preview, item)
        remaining_items = len(items) - index
        fair_share = max(1, remaining_budget // max(1, remaining_items) // 2)
        fitting = [option for option in options if option[2] <= fair_share]
        _rank, label, estimate = max(fitting or options[:1])
        if index == 0 and estimate * 2 > remaining_budget:
            raise LiveInconclusiveError("标记首项的最低共同画质也无法安全容纳在剩余预算")
        item["preferred_quality"] = label
        item["predicted_size_bytes"] = estimate
        prepared.append(item)
        predicted_total += estimate
        remaining_budget = max(0, remaining_budget - estimate * 2)
        if run_size_bytes(run_root, workspace_root) >= MAX_RUN_GROWTH_BYTES:
            raise LiveInconclusiveError("画质预检期间真链运行达到 2 GiB 上限")
    if predicted_total * 2 > available_budget:
        raise LiveInconclusiveError("8 项最低可用画质的预估总量无法安全容纳")
    return prepared, predicted_total


def _states(api: LiveApi, task_ids: list[str]) -> dict[str, dict[str, Any]]:
    wanted = set(task_ids)
    result = {
        str(item.get("id") or ""): item
        for item in api.tasks()
        if str(item.get("id") or "") in wanted
    }
    if set(result) != wanted:
        raise LiveFailedError("产品任务列表缺少本次严格批量任务")
    return result


def _cancel_active(api: LiveApi, states: dict[str, dict[str, Any]]) -> None:
    active = [task_id for task_id, item in states.items() if item.get("status") not in TERMINAL]
    if active:
        api.cancel_tasks(active)


def execute_bounded_download(
    *,
    api: LiveApi,
    run_root: Path,
    workspace_root: Path,
    items: list[dict[str, Any]],
    started_at: float,
    submitter: Callable[[list[dict[str, Any]]], list[str]] | None = None,
    progress_callback: Callable[[dict[str, int]], None] | None = None,
) -> DownloadResult:
    if len(items) != 8:
        raise LiveFailedError("有界下载必须恰好接收固定场景中的 8 个作品")
    if shutil.disk_usage(run_root).free < MIN_DOWNLOAD_FREE_BYTES:
        raise LiveBlockedError("真链运行开始下载前可用空间少于 5 GiB")
    prepared, predicted_total = _prepare_bounded_items(
        api=api,
        run_root=run_root,
        workspace_root=workspace_root,
        items=items,
        started_at=started_at,
    )
    if progress_callback is not None:
        progress_callback({"predicted_size_bytes": predicted_total})
    task_ids = submitter(prepared) if submitter is not None else api.submit_selection(prepared)
    if len(task_ids) != 8 or len(set(task_ids)) != 8:
        raise LiveFailedError("有界下载必须以固定 8 项严格批量开始")

    stop_reason = "completed"
    states: dict[str, dict[str, Any]] = {}
    last_counts: tuple[int, int, int] | None = None

    def publish_counts() -> None:
        nonlocal last_counts
        counts = (
            sum(item.get("status") == "success" for item in states.values()),
            sum(
                item.get("status") in {"failed", "skipped"}
                for item in states.values()
            ),
            sum(item.get("status") == "cancelled" for item in states.values()),
        )
        if progress_callback is not None and counts != last_counts:
            progress_callback(
                {
                    "completed_count": counts[0],
                    "failed_count": counts[1],
                    "cancelled_count": counts[2],
                }
            )
        last_counts = counts

    while True:
        states = _states(api, task_ids)
        publish_counts()
        elapsed = time.monotonic() - started_at
        growth = run_size_bytes(run_root, workspace_root)
        if elapsed >= MAX_RUN_SECONDS:
            stop_reason = "time_limit"
            _cancel_active(api, states)
            break
        if growth >= MAX_RUN_GROWTH_BYTES:
            stop_reason = "growth_limit"
            _cancel_active(api, states)
            break
        if all(item.get("status") in TERMINAL for item in states.values()):
            break
        time.sleep(0.5)

    if stop_reason != "completed":
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            states = _states(api, task_ids)
            publish_counts()
            if all(item.get("status") in TERMINAL for item in states.values()):
                break
            time.sleep(0.5)
        if any(item.get("status") not in TERMINAL for item in states.values()):
            raise LiveInconclusiveError("资源上限触发后任务未能在时限内停止")

    successes = [item for item in states.values() if item.get("status") == "success"]
    failures = [item for item in states.values() if item.get("status") in {"failed", "skipped"}]
    cancelled = [item for item in states.values() if item.get("status") == "cancelled"]
    if failures:
        raise LiveFailedError("真实严格批量中出现可判定的下载失败")
    if cancelled and stop_reason == "completed":
        raise LiveFailedError("未触发资源上限时严格批量出现了取消任务")
    if not successes:
        raise LiveInconclusiveError("硬上限前没有作品完成下载与入库")

    prepared_by_bvid = {str(item["bvid"]): item for item in prepared}
    for success in successes:
        bvid = str(success.get("bvid") or success.get("source_key") or "")
        preferred = str(prepared_by_bvid.get(bvid, {}).get("preferred_quality") or "")
        selected = str(success.get("selected_quality") or "")
        if not quality_labels_match(preferred, selected):
            raise LiveFailedError("成功任务的实际画质与预检指定画质不一致")
    successful_bvid = str(successes[0].get("bvid") or successes[0].get("source_key") or "")
    preferred_quality = str(prepared_by_bvid.get(successful_bvid, {}).get("preferred_quality") or "")
    selected_quality = str(successes[0].get("selected_quality") or "")
    library = api.library_item_for_bvid(successful_bvid)
    if not library:
        raise LiveFailedError("成功下载的作品没有进入作品库")
    media_id = str(library.get("id") or "")
    if not media_id:
        raise LiveFailedError("成功入库作品缺少稳定媒体 ID")
    detail = api.get(f"/api/library/{media_id}").get("data")
    if not isinstance(detail, dict) or not detail.get("files"):
        raise LiveFailedError("成功入库作品详情缺少可读取文件")
    return DownloadResult(
        completed_count=len(successes),
        failed_count=len(failures),
        cancelled_count=len(cancelled),
        stop_reason=stop_reason,
        media_id=media_id,
        successful_bvid=successful_bvid,
        preferred_quality=preferred_quality,
        selected_quality=selected_quality,
        predicted_size_bytes=predicted_total,
    )
