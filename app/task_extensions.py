from __future__ import annotations

import threading
import time
from types import MethodType
from typing import Any, Iterable

from app.artifacts import cleanup_work_dir
from app.constants import TERMINAL_STATUSES
from app.progress import PHASE_LABELS
from app.quality import validate_min_height


def install_task_extensions(queue) -> None:
    """Install a tiny pause marker hook without changing TaskQueue's core worker."""
    if getattr(queue, "_enhancements_installed", False):
        return
    queue._enhancements_installed = True
    queue._enhancement_pause_requested = set()
    original_finish = queue._finish

    def wrapped_finish(self, task, status: str, *, error: str = "") -> None:
        pause_requested = self._enhancement_pause_requested
        if status == "cancelled" and task.id in pause_requested:
            pause_requested.discard(task.id)
            original_finish(
                task,
                "cancelled",
                error="任务已暂停；点击继续会使用同一任务 ID 从头重新开始当前下载",
            )
            return
        original_finish(task, status, error=error)

    queue._finish = MethodType(wrapped_finish, queue)


def _task_or_raise(queue, task_id: str):
    task = queue._tasks.get(task_id)
    if task is None:
        raise KeyError("任务不存在")
    return task


def _active_duplicate(queue, task) -> bool:
    return any(
        other.id != task.id
        and other.key == task.key
        and other.status in {"queued", "running"}
        for other in queue._tasks.values()
    )


def retry_in_place(
    queue,
    task_id: str,
    *,
    force: bool = False,
    min_height: int | None = None,
    preferred_quality: str | None = None,
) -> dict[str, Any]:
    """Reset a terminal task and enqueue the same task object/ID again."""
    install_task_extensions(queue)
    task_to_log = None
    cleanup: tuple[Any, str, str] | None = None
    with queue._cv:
        task = _task_or_raise(queue, task_id)
        if task.status not in TERMINAL_STATUSES:
            raise ValueError("任务尚未结束，不能重新排队")
        if _active_duplicate(queue, task):
            raise ValueError("同一作品已有排队或下载中的任务")
        active = sum(
            1 for item in queue._tasks.values() if item.status in {"queued", "running"}
        )
        if active >= queue.max_pending:
            raise ValueError(f"队列已满，上限 {queue.max_pending} 个活动任务")

        cfg = queue.config_store.get()
        effective_min = validate_min_height(
            min_height if min_height is not None else task.min_height,
            default=cfg.default_min_height,
        )
        effective_preferred = (
            task.preferred_quality
            if preferred_quality is None
            else str(preferred_quality or "").strip()[:120]
        )
        root = task.storage_root or cfg.download_path()
        cleanup = (root, task.key, task.id)

        queue._enhancement_pause_requested.discard(task.id)
        try:
            queue._pending.remove(task.id)
        except ValueError:
            pass
        queue._cancel_events[task.id] = threading.Event()

        task.force = bool(force)
        task.min_height = effective_min
        task.preferred_quality = effective_preferred
        task.status = "queued"
        task.phase = "queued"
        task.phase_label = PHASE_LABELS["queued"]
        task.quality_checked = False
        task.quality_verified = False
        task.quality_expected_parts = 0
        task.quality_verified_parts = 0
        task.quality_summary = ""
        task.highest_available_height = None
        task.highest_available_label = ""
        task.selected_quality = ""
        task.selected_resolution = ""
        task.selected_codec = ""
        task.selected_fps = ""
        task.selected_height = None
        task.selected_tracks = []
        task.effective_dfn_priority = ""
        task.quality_error = ""
        task.progress_percent = None
        task.speed_text = ""
        task.eta_text = ""
        task.downloaded_bytes = None
        task.total_bytes = None
        task.current_part = None
        task.part_total = None
        task.progress_message = "已使用原任务重新加入队列"
        task.error = ""
        task.log_tail = ""
        task.log_size = 0
        task.output_path = ""
        task.files = []
        task.started_at = None
        task.finished_at = None
        task.last_heartbeat = time.time()
        task.created_at = task.last_heartbeat

        queue._delete_log_safely_locked(task)
        queue._pending.append(task.id)
        queue._mark_recent_locked(task.id)
        queue._notify_locked(task)
        queue._cv.notify_all()
        task_to_log = task
        positions = queue._queue_positions_locked()
        result = task.to_dict(queue_position=positions.get(task.id))

    if cleanup is not None:
        try:
            cleanup_work_dir(*cleanup)
        except (OSError, ValueError):
            pass
    if task_to_log is not None:
        queue._append_log(
            task_to_log,
            "[任务] 原地重试：保留任务 ID，清空旧错误与进度后重新排队。\n"
            f"[清晰度] 最低 {effective_min}；"
            f"{'指定 ' + effective_preferred if effective_preferred else '自动最高'}。\n",
        )
    return result


def pause_task(queue, task_id: str) -> dict[str, Any]:
    """Safely stop a queued/running task; resume restarts it with the same ID."""
    install_task_extensions(queue)
    with queue._cv:
        task = _task_or_raise(queue, task_id)
        if task.status == "queued":
            try:
                queue._pending.remove(task.id)
            except ValueError:
                pass
            event = queue._cancel_events.setdefault(task.id, threading.Event())
            event.set()
            now = time.time()
            task.status = "cancelled"
            task.phase = "cancelled"
            task.phase_label = PHASE_LABELS["cancelled"]
            task.error = "任务已暂停；点击继续会使用同一任务 ID 从头重新开始当前下载"
            task.progress_message = task.error
            task.finished_at = now
            task.last_heartbeat = now
            queue._mark_recent_locked(task.id)
            queue._notify_locked(task)
            queue._cv.notify_all()
            queue._append_log(task, "\n[任务] 已在排队阶段暂停。\n")
            return task.to_dict()
        if task.status != "running":
            raise ValueError("只有排队中或下载中的任务可以暂停")
        queue._enhancement_pause_requested.add(task.id)
    if not queue.cancel(task_id):
        raise ValueError("任务已结束，无法暂停")
    return queue.get_task(task_id) or {}


def cancel_task(queue, task_id: str) -> dict[str, Any]:
    install_task_extensions(queue)
    queue._enhancement_pause_requested.discard(task_id)
    if not queue.cancel(task_id):
        raise ValueError("任务已结束，无法取消")
    return queue.get_task(task_id) or {}


def delete_task(queue, task_id: str) -> bool:
    install_task_extensions(queue)
    with queue._cv:
        task = _task_or_raise(queue, task_id)
        if task.status not in TERMINAL_STATUSES:
            raise ValueError("排队中或下载中的任务不能直接删除，请先取消")
        queue._enhancement_pause_requested.discard(task.id)
        queue._drop_task_locked(task.id)
        queue._cv.notify_all()
        return True


def clear_tasks(queue, statuses: Iterable[str]) -> int:
    wanted = {str(value or "").strip() for value in statuses}
    allowed = TERMINAL_STATUSES.intersection(wanted)
    if not allowed:
        return 0
    with queue._cv:
        ids = [
            task_id
            for task_id, task in queue._tasks.items()
            if task.status in allowed
        ]
        for task_id in ids:
            queue._enhancement_pause_requested.discard(task_id)
            queue._drop_task_locked(task_id)
        queue._cv.notify_all()
        return len(ids)
