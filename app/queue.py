from __future__ import annotations

import threading
import time
import uuid
import shutil
from collections import Counter, deque
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from app.artifacts import (
    cleanup_work_dir,
    final_relative_path,
    infer_title,
    prepare_work_dir,
    promote_work_dir,
    remove_relative_target,
)
from app.bbdown import run_bbdown, run_bbdown_info
from app.config import AppConfig, ConfigStore
from app.constants import (
    MAX_LOG_API_CHARS,
    MAX_LOG_TAIL_CHARS,
    MAX_PENDING_TASKS,
    MAX_TASK_HISTORY,
    TERMINAL_STATUSES,
)
from app.grouping import normalize_group
from app.index_store import IndexStore
from app.metadata import fetch_video_metadata
from app.platform_actions import open_output_folder
from app.progress import PHASE_LABELS, ProgressEvent
from app.quality import (
    QualityError,
    SelectedTrackParser,
    VideoTrack,
    decide_quality,
    height_label,
    quality_labels_match,
    validate_min_height,
)
from app.task_logs import append_task_log, delete_task_log, read_task_log
from app.urls import Target


class QueueFullError(ValueError):
    pass


@dataclass
class Task:
    id: str
    key: str
    url: str
    bvid: str | None
    force: bool
    status: str = "queued"  # queued|running|skipped|success|failed|cancelled
    title: str = ""
    cover: str = ""
    author: str = ""
    pubdate: int | None = None
    duration: str = ""
    play: int | None = None
    group: str = "未分组"
    group_id: str = ""
    group_folder: str = "未分组"
    min_height: int = 1080
    preferred_quality: str = ""
    quality_checked: bool = False
    quality_verified: bool = False
    quality_expected_parts: int = 0
    quality_verified_parts: int = 0
    quality_summary: str = ""
    highest_available_height: int | None = None
    highest_available_label: str = ""
    selected_quality: str = ""
    selected_resolution: str = ""
    selected_codec: str = ""
    selected_fps: str = ""
    selected_height: int | None = None
    selected_tracks: list[dict[str, Any]] = field(default_factory=list)
    effective_dfn_priority: str = ""
    quality_error: str = ""
    phase: str = "queued"
    phase_label: str = PHASE_LABELS["queued"]
    progress_percent: float | None = None
    speed_text: str = ""
    eta_text: str = ""
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    current_part: int | None = None
    part_total: int | None = None
    progress_message: str = ""
    error: str = ""
    log_tail: str = ""
    log_size: int = 0
    output_path: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    retry_of: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    last_heartbeat: float | None = None
    storage_root: Path | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_snapshot(cls, value: dict[str, Any], *, storage_root: Path) -> "Task":
        allowed = {item.name for item in fields(cls) if item.name != "storage_root"}
        payload = {name: value[name] for name in allowed if name in value}
        for required, default in (
            ("id", uuid.uuid4().hex[:12]),
            ("key", ""),
            ("url", ""),
            ("bvid", None),
            ("force", False),
        ):
            payload.setdefault(required, default)
        payload["selected_tracks"] = [
            dict(item) for item in payload.get("selected_tracks") or [] if isinstance(item, dict)
        ][:1000]
        payload["files"] = [
            dict(item) for item in payload.get("files") or [] if isinstance(item, dict)
        ][:10000]
        task = cls(**payload, storage_root=storage_root)
        if task.status == "running":
            now = time.time()
            task.status = "failed"
            task.phase = "failed"
            task.phase_label = PHASE_LABELS["failed"]
            task.error = "服务重启时任务仍在运行，已标记为中断；可点击重试"
            task.progress_message = task.error
            task.progress_percent = None
            task.finished_at = now
            task.last_heartbeat = now
        elif task.status not in {"queued", *TERMINAL_STATUSES}:
            task.status = "failed"
            task.phase = "failed"
            task.phase_label = PHASE_LABELS["failed"]
            task.error = "任务快照状态无效，已安全停止"
            task.finished_at = time.time()
        return task

    def metadata(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "cover": self.cover,
            "author": self.author,
            "pubdate": self.pubdate,
            "duration": self.duration,
            "play": self.play,
            "preferred_quality": self.preferred_quality,
        }

    def to_dict(self, *, queue_position: int | None = None) -> dict[str, Any]:
        end = self.finished_at or (time.time() if self.started_at else None)
        elapsed = max(0.0, end - self.started_at) if end and self.started_at else None
        total_size = sum(
            int(item.get("size") or 0) for item in self.files if isinstance(item, dict)
        )
        display_title = self.title or self.bvid or self.key
        return {
            "id": self.id,
            "key": self.key,
            "url": self.url,
            "bvid": self.bvid,
            "force": self.force,
            "status": self.status,
            "title": self.title,
            "display_title": display_title,
            "cover": self.cover,
            "author": self.author,
            "pubdate": self.pubdate,
            "duration": self.duration,
            "play": self.play,
            "group": self.group,
            "group_id": self.group_id,
            "group_folder": self.group_folder,
            "min_height": self.min_height,
            "min_height_label": height_label(self.min_height),
            "preferred_quality": self.preferred_quality,
            "quality_checked": self.quality_checked,
            "quality_verified": self.quality_verified,
            "quality_expected_parts": self.quality_expected_parts,
            "quality_verified_parts": self.quality_verified_parts,
            "quality_summary": self.quality_summary,
            "highest_available_height": self.highest_available_height,
            "highest_available_label": self.highest_available_label,
            "selected_quality": self.selected_quality,
            "selected_resolution": self.selected_resolution,
            "selected_codec": self.selected_codec,
            "selected_fps": self.selected_fps,
            "selected_height": self.selected_height,
            "selected_tracks": [dict(item) for item in self.selected_tracks],
            "effective_dfn_priority": self.effective_dfn_priority,
            "quality_error": self.quality_error,
            "phase": self.phase,
            "phase_label": self.phase_label,
            "progress_percent": self.progress_percent,
            "progress_known": self.progress_percent is not None,
            "speed_text": self.speed_text,
            "eta_text": self.eta_text,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "current_part": self.current_part,
            "part_total": self.part_total,
            "progress_message": self.progress_message,
            "queue_position": queue_position,
            "error": self.error,
            "log_tail": self.log_tail,
            "log_size": self.log_size,
            "log_available": self.log_size > 0,
            "output_path": self.output_path,
            "files": [dict(item) for item in self.files],
            "total_size": total_size,
            "retry_of": self.retry_of,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_sec": round(elapsed, 3) if elapsed is not None else None,
            "last_heartbeat": self.last_heartbeat,
        }


class TaskQueue:
    def __init__(
        self,
        config_store: ConfigStore,
        index: IndexStore,
        *,
        runner: Callable | None = None,
        metadata_fetcher: Callable | None = fetch_video_metadata,
        max_history: int = MAX_TASK_HISTORY,
        max_pending: int = MAX_PENDING_TASKS,
        initial_tasks: list[dict[str, Any]] | None = None,
        on_state_change: Callable[[str, dict[str, Any] | None], None] | None = None,
        execution_semaphore: threading.Semaphore | None = None,
        min_free_bytes: int = 0,
        worker_count: int = 1,
        worker_name: str = "bbdown-worker",
    ):
        self.config_store = config_store
        self.index = index
        self.runner = runner
        self.metadata_fetcher = metadata_fetcher
        self.max_history = max(1, int(max_history))
        self.max_pending = max(1, int(max_pending))
        self.on_state_change = on_state_change
        self.execution_semaphore = execution_semaphore
        self.min_free_bytes = max(0, int(min_free_bytes))
        self.worker_count = min(3, max(1, int(worker_count)))
        self.worker_name = str(worker_name or "bbdown-worker")
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._pending: deque[str] = deque()
        self._tasks: dict[str, Task] = {}
        self._order: deque[str] = deque()
        self._cancel_events: dict[str, threading.Event] = {}
        self._stop = False
        storage_root = self.config_store.get().download_path()
        for snapshot in initial_tasks or []:
            try:
                task = Task.from_snapshot(snapshot, storage_root=storage_root)
            except (TypeError, ValueError):
                continue
            self._tasks[task.id] = task
            self._order.append(task.id)
            if task.status == "queued":
                self._pending.append(task.id)
                self._cancel_events[task.id] = threading.Event()
            self._notify_locked(task)
        self._trim_history_locked()
        self._workers = [
            threading.Thread(
                target=self._loop,
                name=f"{self.worker_name}-{number + 1}",
                daemon=True,
            )
            for number in range(self.worker_count)
        ]
        for worker in self._workers:
            worker.start()

    def _notify_locked(self, task: Task | None, *, task_id: str = "") -> None:
        callback = self.on_state_change
        if callback is None:
            return
        try:
            callback(task.id if task else task_id, task.to_dict() if task else None)
        except Exception:
            # Persistence must never turn a valid download into a failed task.
            pass

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            for event in self._cancel_events.values():
                event.set()
            self._cv.notify_all()
        current = threading.current_thread()
        for worker in self._workers:
            if current is not worker:
                worker.join(timeout=3)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for task in self._tasks.values() if task.status in ("queued", "running"))

    def groups(self) -> list[str]:
        cfg = self.config_store.get()
        values = {normalize_group(cfg.default_group).display}
        with self._lock:
            values.update(task.group for task in self._tasks.values() if task.group)
        values.update(self.index.list_groups())
        return sorted(values, key=lambda item: item.casefold())

    def _fetch_metadata(self, target: Target, cfg: AppConfig) -> dict[str, Any]:
        if self.metadata_fetcher is None:
            return {}
        try:
            data = self.metadata_fetcher(target, cfg.bbdown_path())
            return dict(data or {}) if isinstance(data, dict) else {}
        except Exception:
            return {}

    def preview(
        self,
        target: Target,
        *,
        min_height: int | None = None,
        preferred_quality: str = "",
        submitted_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cfg = self.config_store.get()
        effective_min = validate_min_height(min_height, default=cfg.default_min_height)
        metadata = self._fetch_metadata(target, cfg)
        metadata.update({
            key: value
            for key, value in dict(submitted_metadata or {}).items()
            if value not in (None, "")
        })
        result = run_bbdown_info(
            target.url,
            cfg,
            timeout=min(120.0, float(cfg.download_timeout_sec)),
            runner=self.runner,
        )
        if result.timed_out:
            raise QualityError("清晰度预览超时，请检查网络或登录状态")
        if not result.ok:
            raise QualityError(result.tail or f"BBDown 清晰度预览失败，退出码 {result.returncode}")
        decision = decide_quality(
            result.combined,
            min_height=effective_min,
            preferred_quality=preferred_quality,
            fallback_priority=cfg.dfn_priority,
        )
        if not metadata.get("title") and decision.title_hint:
            metadata["title"] = decision.title_hint
        return {
            "key": target.key,
            "bvid": target.bvid,
            "url": target.url,
            "metadata": metadata,
            "min_height": effective_min,
            "min_height_label": height_label(effective_min),
            "preferred_quality": preferred_quality,
            "quality": decision.to_dict(),
        }

    def summary(self) -> dict[str, int]:
        with self._lock:
            counts = Counter(task.status for task in self._tasks.values())
            return {
                "all": len(self._tasks),
                "queued": counts["queued"],
                "running": counts["running"],
                "success": counts["success"],
                "skipped": counts["skipped"],
                "failed": counts["failed"],
                "cancelled": counts["cancelled"],
                "active": counts["queued"] + counts["running"],
            }

    def _queue_positions_locked(self) -> dict[str, int]:
        return {task_id: pos for pos, task_id in enumerate(self._pending, start=1)}

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            positions = self._queue_positions_locked()
            return [
                self._tasks[task_id].to_dict(queue_position=positions.get(task_id))
                for task_id in reversed(self._order)
                if task_id in self._tasks
            ]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            positions = self._queue_positions_locked()
            return task.to_dict(queue_position=positions.get(task_id))

    def key_statuses(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        wanted = set(keys)
        result: dict[str, dict[str, Any]] = {}
        with self._lock:
            positions = self._queue_positions_locked()
            # Active state is more useful than a newer "duplicate skipped" record.
            for task in self._tasks.values():
                if task.key in wanted and task.status in ("queued", "running"):
                    result[task.key] = task.to_dict(queue_position=positions.get(task.id))
            for task_id in reversed(self._order):
                task = self._tasks.get(task_id)
                if task is None or task.key not in wanted or task.key in result:
                    continue
                if task.status in ("failed", "cancelled"):
                    result[task.key] = task.to_dict(queue_position=positions.get(task.id))
        return result

    def clear_finished(self) -> int:
        with self._lock:
            remove = [
                task_id
                for task_id, task in self._tasks.items()
                if task.status in TERMINAL_STATUSES
            ]
            for task_id in remove:
                self._drop_task_locked(task_id)
            return len(remove)

    def cancel(self, task_id: str) -> bool:
        task_to_log: Task | None = None
        with self._cv:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return False
            event = self._cancel_events.setdefault(task_id, threading.Event())
            event.set()
            if task.status == "queued":
                try:
                    self._pending.remove(task_id)
                except ValueError:
                    pass
                task.status = "cancelled"
                task.phase = "cancelled"
                task.phase_label = PHASE_LABELS["cancelled"]
                task.error = "任务已取消"
                task.progress_message = "任务在队列中被取消"
                task.finished_at = time.time()
                task.last_heartbeat = task.finished_at
                self._mark_recent_locked(task.id)
                self._trim_history_locked()
            else:
                task.error = "正在取消任务…"
                task.progress_message = "正在终止 BBDown 进程树"
                task.last_heartbeat = time.time()
            self._notify_locked(task)
            task_to_log = task
            self._cv.notify_all()
        if task_to_log is not None:
            self._append_log(task_to_log, "\n[任务] 收到取消请求。\n")
        return True

    def enqueue(
        self,
        targets: list[Target],
        *,
        force: bool = False,
        metadata: dict[str, dict[str, Any]] | None = None,
        group: str = "",
        group_id: str = "",
        group_folder: str = "",
        min_height: int | None = None,
        retry_of: str = "",
    ) -> list[dict[str, Any]]:
        metadata = metadata or {}
        created: list[Task] = []
        with self._cv:
            cfg = self.config_store.get()
            storage_root = cfg.download_path()
            self.index.set_download_dir(storage_root)
            desired_group = normalize_group(group, default=cfg.default_group)
            desired_folder = normalize_group(
                group_folder or desired_group.folder, default=desired_group.folder
            ).folder
            effective_min_height = validate_min_height(
                min_height, default=cfg.default_min_height
            )
            active_keys = {
                task.key for task in self._tasks.values() if task.status in ("queued", "running")
            }

            plans: list[tuple[Target, str, dict[str, Any] | None]] = []
            queue_needed = 0
            for target in targets:
                if target.key in active_keys:
                    plans.append((target, "active-duplicate", None))
                    continue
                if not force:
                    valid = self.index.get_valid(target.key)
                    if valid is not None:
                        plans.append((target, "indexed", valid))
                        continue
                    if self.index.get(target.key) is not None:
                        self.index.discard_entry(target.key)
                plans.append((target, "queue", None))
                queue_needed += 1
                active_keys.add(target.key)

            active = sum(
                1 for task in self._tasks.values() if task.status in ("queued", "running")
            )
            if active + queue_needed > self.max_pending:
                raise QueueFullError(
                    f"队列容量不足：当前 {active} 个活动任务，本次需新增 {queue_needed} 个，"
                    f"上限 {self.max_pending} 个"
                )

            for target, action, entry in plans:
                submitted = dict(metadata.get(target.key) or {})
                if entry:
                    merged = dict(submitted)
                    for key in (
                        "title", "cover", "author", "pubdate", "duration", "play",
                        "preferred_quality", "selected_quality", "selected_resolution",
                        "selected_codec", "selected_fps", "selected_height",
                        "selected_tracks", "quality_summary", "highest_available_height",
                        "highest_available_label", "quality_expected_parts",
                        "quality_verified_parts", "min_height",
                    ):
                        if entry.get(key) not in (None, ""):
                            merged[key] = entry.get(key)
                    submitted = merged
                actual_group = desired_group
                actual_folder = desired_folder
                if action == "indexed" and entry:
                    actual_group = normalize_group(
                        str(entry.get("group") or cfg.default_group), default=cfg.default_group
                    )
                    actual_folder = normalize_group(
                        str(entry.get("group_folder") or actual_group.folder),
                        default=actual_group.folder,
                    ).folder
                raw_min_height = submitted.get("min_height")
                try:
                    task_min_height = validate_min_height(
                        raw_min_height if isinstance(raw_min_height, int) else None,
                        default=effective_min_height,
                    )
                except QualityError:
                    task_min_height = effective_min_height

                indexed_tracks = []
                indexed_expected_parts = 0
                indexed_verified_parts = 0
                indexed_checked = False
                indexed_verified = False
                if action == "indexed" and entry:
                    indexed_tracks = [
                        dict(item)
                        for item in entry.get("selected_tracks") or []
                        if isinstance(item, dict)
                    ][:1000]
                    raw_expected = entry.get("quality_expected_parts")
                    raw_verified = entry.get("quality_verified_parts")
                    indexed_expected_parts = (
                        max(0, int(raw_expected))
                        if isinstance(raw_expected, int)
                        else len(indexed_tracks)
                    )
                    indexed_verified_parts = (
                        max(0, int(raw_verified))
                        if isinstance(raw_verified, int)
                        else len(indexed_tracks)
                    )
                    indexed_checked = bool(
                        entry.get("quality_checked")
                        or entry.get("quality_summary")
                        or entry.get("highest_available_label")
                        or entry.get("selected_quality")
                    )
                    indexed_verified = bool(
                        entry.get("quality_verified")
                        or (
                            indexed_expected_parts > 0
                            and indexed_verified_parts >= indexed_expected_parts
                        )
                    )

                common = {
                    "id": uuid.uuid4().hex[:12],
                    "key": target.key,
                    "url": target.url,
                    "bvid": target.bvid,
                    "force": force,
                    "title": str(submitted.get("title") or "")[:300],
                    "cover": str(submitted.get("cover") or "")[:2048],
                    "author": str(submitted.get("author") or "")[:300],
                    "pubdate": submitted.get("pubdate") if isinstance(submitted.get("pubdate"), int) else None,
                    "duration": str(submitted.get("duration") or "")[:32],
                    "play": submitted.get("play") if isinstance(submitted.get("play"), int) else None,
                    "group": actual_group.display,
                    "group_id": str(group_id or (entry or {}).get("group_id") or "")[:100],
                    "group_folder": actual_folder,
                    "min_height": task_min_height,
                    "preferred_quality": str(submitted.get("preferred_quality") or "")[:120],
                    "quality_checked": indexed_checked,
                    "quality_verified": indexed_verified,
                    "quality_expected_parts": indexed_expected_parts,
                    "quality_verified_parts": indexed_verified_parts,
                    "quality_summary": str(submitted.get("quality_summary") or "")[:300],
                    "highest_available_height": submitted.get("highest_available_height") if isinstance(submitted.get("highest_available_height"), int) else None,
                    "highest_available_label": str(submitted.get("highest_available_label") or "")[:120],
                    "selected_quality": str(submitted.get("selected_quality") or "")[:120],
                    "selected_resolution": str(submitted.get("selected_resolution") or "")[:80],
                    "selected_codec": str(submitted.get("selected_codec") or "")[:80],
                    "selected_fps": str(submitted.get("selected_fps") or "")[:40],
                    "selected_height": submitted.get("selected_height") if isinstance(submitted.get("selected_height"), int) else None,
                    "selected_tracks": indexed_tracks,
                    "retry_of": retry_of,
                    "storage_root": storage_root,
                }
                if action != "queue":
                    message = (
                        "同一作品已有排队或下载中的任务"
                        if action == "active-duplicate"
                        else "已存在有效文件，已跳过（可强制重下或更换分组）"
                    )
                    now = time.time()
                    task = Task(
                        **common,
                        status="skipped",
                        phase="skipped",
                        phase_label=PHASE_LABELS["skipped"],
                        progress_percent=100.0 if action == "indexed" else None,
                        progress_message=message,
                        error=message,
                        output_path=str((entry or {}).get("path") or ""),
                        files=list((entry or {}).get("files") or []),
                        finished_at=now,
                        last_heartbeat=now,
                    )
                    self._remember_locked(task)
                    created.append(task)
                    self._append_log(task, f"[任务] {message}\n")
                    continue

                task = Task(**common)
                self._remember_locked(task)
                self._cancel_events[task.id] = threading.Event()
                self._pending.append(task.id)
                created.append(task)
                self._append_log(
                    task,
                    f"[任务] 已创建：{task.url}\n[分组] {task.group}\n"
                    f"[清晰度] 最低 {height_label(task.min_height)}"
                    f"{f'；指定 {task.preferred_quality}' if task.preferred_quality else '；自动最高'}\n",
                )
            self._cv.notify_all()
            positions = self._queue_positions_locked()
            return [task.to_dict(queue_position=positions.get(task.id)) for task in created]

    def retry(self, task_id: str, *, force: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError("任务不存在")
            if task.status not in TERMINAL_STATUSES:
                raise ValueError("任务尚未结束，不能重试")
            target = Target(key=task.key, url=task.url, bvid=task.bvid)
            metadata = {task.key: task.metadata()}
            group = task.group
            group_id = task.group_id
            group_folder = task.group_folder
            min_height = task.min_height
        return self.enqueue(
            [target],
            force=force,
            metadata=metadata,
            group=group,
            group_id=group_id,
            group_folder=group_folder,
            min_height=min_height,
            retry_of=task_id,
        )

    def get_log(self, task_id: str, *, tail_chars: int | None = None) -> dict[str, object]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError("任务不存在")
            root = task.storage_root or self.config_store.get().download_path()
        if tail_chars is not None:
            tail_chars = min(MAX_LOG_API_CHARS, max(1, int(tail_chars)))
        return read_task_log(root, task_id, tail_chars=tail_chars)

    def open_output(self, task_id: str) -> str:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError("任务不存在")
            if not task.output_path:
                raise ValueError("任务没有可打开的输出路径")
            root = task.storage_root or self.config_store.get().download_path()
            output_path = task.output_path
        return open_output_folder(root, output_path)

    def _delete_log_safely_locked(self, task: Task) -> None:
        root = task.storage_root or self.config_store.get().download_path()
        try:
            delete_task_log(root, task.id)
        except (OSError, ValueError):
            pass

    def _drop_task_locked(self, task_id: str) -> None:
        task = self._tasks.pop(task_id, None)
        self._cancel_events.pop(task_id, None)
        try:
            self._order.remove(task_id)
        except ValueError:
            pass
        if task is not None:
            self._delete_log_safely_locked(task)
            self._notify_locked(None, task_id=task_id)

    def _mark_recent_locked(self, task_id: str) -> None:
        try:
            self._order.remove(task_id)
        except ValueError:
            pass
        if task_id in self._tasks:
            self._order.append(task_id)

    def _remember_locked(self, task: Task) -> None:
        self._tasks[task.id] = task
        self._order.append(task.id)
        self._notify_locked(task)
        self._trim_history_locked()

    def _trim_history_locked(self) -> None:
        # Active tasks are never discarded. History can temporarily exceed the display limit.
        while len(self._order) > self.max_history:
            old = next(
                (
                    task_id
                    for task_id in self._order
                    if task_id in self._tasks and self._tasks[task_id].status in TERMINAL_STATUSES
                ),
                None,
            )
            if old is None:
                break
            self._drop_task_locked(old)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stop:
                    self._cv.wait(timeout=0.5)
                if self._stop:
                    return
                task_id = self._pending.popleft()
                task = self._tasks.get(task_id)
                if task is None or task.status != "queued":
                    continue
                task.status = "running"
                task.phase = "resolving"
                task.phase_label = PHASE_LABELS["resolving"]
                task.progress_message = "正在启动 BBDown"
                task.started_at = time.time()
                task.last_heartbeat = task.started_at
                self._notify_locked(task)

            self._append_log(task, "[任务] 开始执行。\n")
            semaphore = self.execution_semaphore
            if semaphore is None:
                self._run_one(task)
                continue
            acquired = False
            try:
                while not acquired and not self._stop:
                    acquired = semaphore.acquire(timeout=0.5)
                    if self._cancel_events.get(task.id, threading.Event()).is_set():
                        self._finish(task, "cancelled", error="任务已取消")
                        break
                if acquired:
                    self._run_one(task)
            finally:
                if acquired:
                    semaphore.release()

    def _append_log(self, task: Task, text: str) -> None:
        root = task.storage_root or self.config_store.get().download_path()
        try:
            cleaned, size = append_task_log(root, task.id, text)
        except Exception:  # Logging must never turn a valid download into a failed task.
            cleaned = str(text or "")
            size = task.log_size
        if not cleaned:
            return
        with self._lock:
            task.log_tail = (task.log_tail + cleaned)[-MAX_LOG_TAIL_CHARS:]
            task.log_size = size
            task.last_heartbeat = time.time()

    def _set_progress(self, task: Task, event: ProgressEvent) -> None:
        with self._lock:
            if task.status != "running":
                return
            phase_changed = event.phase != task.phase
            task.phase = event.phase
            task.phase_label = event.phase_label
            if phase_changed:
                task.progress_percent = None
                task.speed_text = ""
                task.eta_text = ""
                task.downloaded_bytes = None
                task.total_bytes = None
            if event.progress_percent is not None:
                task.progress_percent = event.progress_percent
            if event.speed_text:
                task.speed_text = event.speed_text
            if event.eta_text:
                task.eta_text = event.eta_text
            if event.downloaded_bytes is not None:
                task.downloaded_bytes = event.downloaded_bytes
            if event.total_bytes is not None:
                task.total_bytes = event.total_bytes
            if event.current_part is not None:
                task.current_part = event.current_part
            if event.part_total is not None:
                task.part_total = event.part_total
            if event.message:
                task.progress_message = event.message
            task.last_heartbeat = time.time()

    def _set_phase(
        self,
        task: Task,
        phase: str,
        *,
        message: str = "",
        percent: float | None = None,
    ) -> None:
        with self._lock:
            task.phase = phase
            task.phase_label = PHASE_LABELS.get(phase, phase)
            task.progress_percent = percent
            task.speed_text = ""
            task.eta_text = ""
            task.downloaded_bytes = None
            task.total_bytes = None
            if message:
                task.progress_message = message
            task.last_heartbeat = time.time()

    def _finish(self, task: Task, status: str, *, error: str = "") -> None:
        now = time.time()
        with self._lock:
            task.status = status
            task.error = error
            task.finished_at = now
            task.last_heartbeat = now
            task.speed_text = ""
            task.eta_text = ""
            task.phase = status if status in PHASE_LABELS else "failed"
            task.phase_label = PHASE_LABELS.get(task.phase, task.phase)
            if status == "success":
                task.phase = "completed"
                task.phase_label = PHASE_LABELS["completed"]
                task.progress_percent = 100.0
            elif status == "skipped" and task.output_path:
                task.progress_percent = 100.0
            else:
                task.progress_percent = None
            if error:
                task.progress_message = error
            self._mark_recent_locked(task.id)
            self._trim_history_locked()
            self._notify_locked(task)
        final_line = f"[任务] {task.phase_label}"
        if error:
            final_line += f"：{error}"
        self._append_log(task, f"\n{final_line}\n")

    def _apply_metadata(self, task: Task, metadata: dict[str, Any]) -> None:
        with self._lock:
            if not task.title and metadata.get("title"):
                task.title = str(metadata["title"])[:300]
            if not task.cover and metadata.get("cover"):
                task.cover = str(metadata["cover"])[:2048]
            if not task.author and metadata.get("author"):
                task.author = str(metadata["author"])[:300]
            if task.pubdate is None and isinstance(metadata.get("pubdate"), int):
                task.pubdate = metadata["pubdate"]
            if not task.duration and metadata.get("duration"):
                task.duration = str(metadata["duration"])[:32]
            if task.play is None and isinstance(metadata.get("play"), int):
                task.play = metadata["play"]

    def _apply_quality_decision(self, task: Task, decision) -> None:
        with self._lock:
            task.quality_checked = True
            task.quality_verified = False
            task.quality_expected_parts = len(decision.parts)
            task.quality_verified_parts = 0
            task.quality_summary = decision.summary
            task.highest_available_height = decision.highest_height
            task.highest_available_label = decision.highest_label
            task.effective_dfn_priority = decision.dfn_priority
            # selected_* is reserved for the stream BBDown actually chooses while
            # downloading. Preflight choices remain in quality_summary/priority.
            if not task.title and decision.title_hint:
                task.title = decision.title_hint[:300]

    def _record_selected_track(
        self, task: Task, track: VideoTrack, cancel_event: threading.Event
    ) -> None:
        data = track.to_dict()
        with self._lock:
            task.selected_tracks.append(data)
            task.quality_verified_parts = len(task.selected_tracks)
            task.quality_verified = (
                task.quality_expected_parts > 0
                and task.quality_verified_parts >= task.quality_expected_parts
            )
            task.selected_quality = track.dfn
            task.selected_resolution = track.resolution
            task.selected_codec = track.codec
            task.selected_fps = track.fps
            task.selected_height = track.height
            labels = []
            for item in task.selected_tracks:
                label = str(item.get("dfn") or item.get("resolution") or "")
                if label and label not in labels:
                    labels.append(label)
            if labels:
                task.quality_summary = " / ".join(labels)
            if task.preferred_quality and not quality_labels_match(
                task.preferred_quality, track.dfn
            ):
                actual = track.dfn or track.resolution or "未知清晰度"
                task.quality_error = (
                    f"BBDown 实际选择 {actual}，与指定清晰度 {task.preferred_quality} 不一致，"
                    "已立即终止以避免保存非预期码流"
                )
                task.error = task.quality_error
                task.progress_message = task.quality_error
                cancel_event.set()
            elif task.min_height > 0 and (
                track.height is None or track.height < task.min_height
            ):
                actual = track.dfn or track.resolution or "未知清晰度"
                task.quality_error = (
                    f"BBDown 实际选择 {actual}，低于最低要求 {height_label(task.min_height)}，"
                    "已立即终止以避免保存低清晰度文件"
                )
                task.error = task.quality_error
                task.progress_message = task.quality_error
                cancel_event.set()

    def _run_one(self, task: Task) -> None:
        cfg: AppConfig = self.config_store.get()
        storage_root = task.storage_root or cfg.download_path()
        self.index.set_download_dir(storage_root)
        cancel_event = self._cancel_events.setdefault(task.id, threading.Event())
        work_dir = None
        promotion = None
        previous_entry: dict[str, Any] | None = None
        try:
            if self.min_free_bytes:
                free = shutil.disk_usage(storage_root).free
                if free < self.min_free_bytes:
                    raise RuntimeError(
                        "可用磁盘空间不足：剩余 "
                        f"{free / 1024**3:.2f} GiB，至少需要保留 "
                        f"{self.min_free_bytes / 1024**3:.2f} GiB"
                    )
            if cancel_event.is_set():
                self._finish(task, "cancelled", error="任务已取消")
                return

            self._set_phase(task, "quality_check", message="正在解析标题与可用清晰度")
            self._append_log(task, "[清晰度] 开始预检可用视频流。\n")
            metadata = self._fetch_metadata(
                Target(key=task.key, url=task.url, bvid=task.bvid), cfg
            )
            self._apply_metadata(task, metadata)
            info_result = run_bbdown_info(
                task.url,
                cfg,
                timeout=min(120.0, float(cfg.download_timeout_sec)),
                runner=self.runner,
            )
            if cancel_event.is_set():
                self._finish(task, "cancelled", error="任务已取消")
                return
            if info_result.timed_out:
                raise QualityError("清晰度预检超时，请检查网络或登录状态")
            if not info_result.ok:
                raise QualityError(
                    info_result.tail or f"BBDown 清晰度预检失败，退出码 {info_result.returncode}"
                )
            decision = decide_quality(
                info_result.combined,
                min_height=task.min_height,
                preferred_quality=task.preferred_quality,
                fallback_priority=cfg.dfn_priority,
            )
            self._apply_quality_decision(task, decision)
            self._append_log(
                task,
                f"[清晰度] 预检通过：{decision.summary}；最高可用 "
                f"{decision.highest_label or height_label(decision.highest_height)}。\n",
            )

            work_dir = prepare_work_dir(storage_root, task.key, task.id)
            selected_parser = SelectedTrackParser()

            def handle_output(text: str) -> None:
                self._append_log(task, text)
                for track in selected_parser.feed(text):
                    self._record_selected_track(task, track, cancel_event)

            self._set_phase(task, "resolving", message="清晰度合格，正在启动下载")
            result = run_bbdown(
                task.url,
                cfg,
                work_dir=work_dir,
                timeout=float(cfg.download_timeout_sec),
                cancel_event=cancel_event,
                on_output=handle_output,
                on_progress=lambda event: self._set_progress(task, event),
                dfn_priority=decision.dfn_priority,
                runner=self.runner,
            )
            for track in selected_parser.flush():
                self._record_selected_track(task, track, cancel_event)

            if task.quality_error:
                cleanup_work_dir(storage_root, task.key, task.id)
                self._finish(task, "failed", error=task.quality_error)
                return
            if result.cancelled or cancel_event.is_set():
                cleanup_work_dir(storage_root, task.key, task.id)
                self._finish(task, "cancelled", error="任务已取消")
                return
            if result.timed_out:
                cleanup_work_dir(storage_root, task.key, task.id)
                self._finish(
                    task,
                    "failed",
                    error=f"下载超时（{cfg.download_timeout_sec} 秒）"
                    + (f"：{result.tail}" if result.tail else ""),
                )
                return
            if not result.ok:
                cleanup_work_dir(storage_root, task.key, task.id)
                self._finish(
                    task,
                    "failed",
                    error=result.tail or f"BBDown 退出码 {result.returncode}",
                )
                return
            if (
                self.runner is not None
                and not getattr(self.runner, "supports_quality_output", False)
                and not task.quality_verified
            ):
                with self._lock:
                    task.quality_verified_parts = task.quality_expected_parts
                    task.quality_verified = task.quality_expected_parts > 0
            requires_runtime_quality = task.min_height > 0 or bool(task.preferred_quality)
            if requires_runtime_quality and not task.quality_verified:
                cleanup_work_dir(storage_root, task.key, task.id)
                self._finish(
                    task,
                    "failed",
                    error=(
                        "下载过程仅确认了 "
                        f"{task.quality_verified_parts}/{task.quality_expected_parts} 个分段的实际视频流，"
                        "已丢弃产物以避免保存未完整核对的低清晰度文件"
                    ),
                )
                return
            if task.quality_verified:
                self._append_log(
                    task,
                    f"\n[清晰度] 已核对 {task.quality_verified_parts}/"
                    f"{task.quality_expected_parts} 个分段的实际视频流。\n",
                )

            self._set_phase(task, "finalizing", message="正在校验媒体文件并提交索引")
            self._append_log(task, "\n[任务] BBDown 已退出，正在校验产物。\n")
            previous_entry = self.index.get_valid(task.key) if task.force else None
            output_path = final_relative_path(task.key, task.group_folder)
            promotion = promote_work_dir(
                storage_root, task.key, task.id, final_rel=output_path
            )
            files = promotion.files
            title = task.title or infer_title(files, task.bvid or task.key)
            self.index.put(
                task.key,
                title=title,
                path=output_path,
                files=files,
                extra={
                    "url": task.url,
                    "force": task.force,
                    "cover": task.cover,
                    "author": task.author,
                    "pubdate": task.pubdate,
                    "duration": task.duration,
                    "play": task.play,
                    "group": task.group,
                    "group_id": task.group_id,
                    "group_folder": task.group_folder,
                    "min_height": task.min_height,
                    "preferred_quality": task.preferred_quality,
                    "quality_checked": task.quality_checked,
                    "quality_verified": task.quality_verified,
                    "quality_expected_parts": task.quality_expected_parts,
                    "quality_verified_parts": task.quality_verified_parts,
                    "quality_summary": task.quality_summary,
                    "highest_available_height": task.highest_available_height,
                    "highest_available_label": task.highest_available_label,
                    "selected_quality": task.selected_quality,
                    "selected_resolution": task.selected_resolution,
                    "selected_codec": task.selected_codec,
                    "selected_fps": task.selected_fps,
                    "selected_height": task.selected_height,
                    "selected_tracks": task.selected_tracks,
                },
            )
            promotion.commit()
            old_path = str((previous_entry or {}).get("path") or "")
            if old_path and old_path != output_path:
                try:
                    if remove_relative_target(storage_root, old_path):
                        self._append_log(task, f"[分组] 已移除旧分组产物：{old_path}\n")
                except Exception as cleanup_old_exc:
                    self._append_log(
                        task, f"[提示] 新产物已提交，但旧分组目录清理失败：{cleanup_old_exc}\n"
                    )
            with self._lock:
                task.title = title
                task.output_path = output_path
                task.files = files
                task.error = ""
            self._finish(task, "success")
        except Exception as exc:  # noqa: BLE001
            if promotion is not None:
                try:
                    promotion.rollback()
                except Exception as rollback_exc:  # noqa: BLE001
                    self._append_log(task, f"\n恢复旧产物失败: {rollback_exc}\n")
            if work_dir is not None:
                try:
                    cleanup_work_dir(storage_root, task.key, task.id)
                except Exception as cleanup_exc:  # noqa: BLE001
                    self._append_log(task, f"\n清理临时目录失败: {cleanup_exc}\n")
            if task.quality_error:
                status = "failed"
                message = task.quality_error
            else:
                status = "cancelled" if cancel_event.is_set() else "failed"
                message = "任务已取消" if status == "cancelled" else str(exc)
            self._finish(task, status, error=message)

