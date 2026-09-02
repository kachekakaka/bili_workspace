from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from app.queue import BatchConflictError, QueueFullError
from app.quality import validate_min_height
from app.search import SearchError, creator_profile, creator_submissions
from app.urls import parse_creator_locator, parse_inputs

ACTIVE_JOB_STATUSES = frozenset(
    {"waiting", "discovering", "enqueuing", "stopping"}
)
TERMINAL_JOB_STATUSES = frozenset(
    {"completed", "partial", "failed", "cancelled"}
)

_MAX_SOURCE_PAGES = 10_000
_DEFAULT_RETRY_DELAYS = (0.25, 1.0, 2.0)


class CreatorImportNotFoundError(KeyError):
    pass


class CreatorImportStateError(ValueError):
    pass


@dataclass
class _CreatorImportJob:
    id: str
    uid: str
    owner_user_id: str
    group_id: str
    group_name: str
    group_folder: str
    min_height: int
    cutoff_at: float
    created_at: float
    status: str = "waiting"
    phase: str = "waiting"
    creator_name: str = ""
    creator_avatar: str = ""
    creator_profile_url: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    updated_at: float = 0.0
    current_page: int = 0
    total_pages: int = 0
    total_estimate: int = 0
    pages_scanned: int = 0
    discovered: int = 0
    queued: int = 0
    skipped_downloaded: int = 0
    skipped_active: int = 0
    skipped_deleted: int = 0
    failed_items: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)
    created_task_ids: list[str] = field(default_factory=list)
    last_error: str = ""
    failure_code: str = ""
    failed_page: int | None = None
    retry_round: int = 0
    stability_pass: int = 1
    next_page: int = 1
    pass_total: int | None = None
    pass_pages: int | None = None
    pass_changed: bool = False
    pass_items: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)
    pending_items: deque[dict[str, Any]] = field(default_factory=deque)
    discovery_complete: bool = False
    retry_failed_only: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)


class CreatorImportManager:
    """Coordinate non-persistent, low-priority creator library imports."""

    def __init__(
        self,
        *,
        queue,
        index,
        deletion_store,
        catalog_store,
        task_store,
        config_store,
        bbdown_dir,
        worker_window: int = 1,
        page_loader: Callable[[str, int], dict[str, Any]] | None = None,
        profile_loader: Callable[[str], dict[str, Any]] | None = None,
        audit_callback: Callable[[str, str, str], None] | None = None,
        clock: Callable[[], float] = time.time,
        retry_delays: tuple[float, ...] = _DEFAULT_RETRY_DELAYS,
        capacity_poll_seconds: float = 0.25,
        max_history: int = 20,
        max_stability_passes: int = 3,
    ) -> None:
        self.queue = queue
        self.index = index
        self.deletion_store = deletion_store
        self.catalog_store = catalog_store
        self.task_store = task_store
        self.config_store = config_store
        self.bbdown_dir = bbdown_dir
        self.worker_window = max(1, int(worker_window))
        self._manual_capacity_reserve = self.worker_window
        self._page_loader = page_loader or self._load_page
        self._profile_loader = profile_loader or self._load_profile
        self._audit_callback = audit_callback
        self._clock = clock
        self._retry_delays = tuple(max(0.0, float(value)) for value in retry_delays)
        self._capacity_poll_seconds = max(0.01, float(capacity_poll_seconds))
        self._max_history = max(1, int(max_history))
        self._max_stability_passes = max(1, int(max_stability_passes))
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._jobs: OrderedDict[str, _CreatorImportJob] = OrderedDict()
        self._waiting: deque[str] = deque()
        self._active_job_id = ""
        self._thread: threading.Thread | None = None
        self._stopped = False

    def _load_page(self, uid: str, page: int) -> dict[str, Any]:
        return creator_submissions(
            uid,
            order="pubdate",
            page=page,
            bbdown_dir=self.bbdown_dir,
            fresh=True,
        )

    def _load_profile(self, uid: str) -> dict[str, Any]:
        return creator_profile(uid, bbdown_dir=self.bbdown_dir)

    def _touch_locked(self, job: _CreatorImportJob) -> None:
        job.updated_at = self._clock()

    @staticmethod
    def _safe_error(exc: BaseException, *, page: bool = False) -> str:
        if isinstance(exc, SearchError):
            return str(exc.public_message or "Bilibili 投稿读取失败")[:500]
        if isinstance(exc, (ValueError, CreatorImportStateError)):
            return str(exc)[:500]
        return "Bilibili 投稿读取暂时不可用" if page else "投稿暂时无法创建下载任务"

    def _audit(self, job: _CreatorImportJob, action: str, detail: str = "") -> None:
        if self._audit_callback is None:
            return
        safe = f"job={job.id}; uid={job.uid}"
        if detail:
            safe += f"; {detail}"
        try:
            self._audit_callback(job.owner_user_id, action, safe[:1000])
        except Exception:
            pass

    def _ensure_thread_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            name="creator-import-worker",
            daemon=True,
        )
        self._thread.start()

    def _trim_locked(self) -> None:
        terminal = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in TERMINAL_JOB_STATUSES
        ]
        while len(terminal) > self._max_history:
            job_id = terminal.pop(0)
            self._jobs.pop(job_id, None)

    def _waiting_position_locked(self, job_id: str) -> int:
        try:
            return list(self._waiting).index(job_id) + 1
        except ValueError:
            return 0

    def _ensure_uid_available_locked(self, job: _CreatorImportJob) -> None:
        conflict = next(
            (
                existing
                for existing in self._jobs.values()
                if existing.id != job.id
                and existing.uid == job.uid
                and existing.status in ACTIVE_JOB_STATUSES
            ),
            None,
        )
        if conflict is not None:
            raise CreatorImportStateError("这个 UP 主已有活动或等待中的全量入库作业")

    def _snapshot_locked(self, job: _CreatorImportJob) -> dict[str, Any]:
        failures = [
            {
                "bvid": str(value.get("bvid") or ""),
                "title": str(value.get("title") or ""),
                "message": str(value.get("message") or ""),
            }
            for value in list(job.failed_items.values())[:100]
        ]
        processed = (
            job.queued
            + job.skipped_downloaded
            + job.skipped_active
            + job.skipped_deleted
            + len(job.failed_items)
        )
        return {
            "id": job.id,
            "uid": job.uid,
            "owner_user_id": job.owner_user_id,
            "creator_name": job.creator_name,
            "creator_avatar": job.creator_avatar,
            "creator_profile_url": job.creator_profile_url,
            "group_id": job.group_id,
            "group_name": job.group_name,
            "min_height": job.min_height,
            "cutoff_at": job.cutoff_at,
            "status": job.status,
            "phase": job.phase,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "updated_at": job.updated_at,
            "current_page": job.current_page,
            "total_pages": job.total_pages,
            "total_estimate": job.total_estimate,
            "pages_scanned": job.pages_scanned,
            "discovered": job.discovered,
            "processed": processed,
            "queued": job.queued,
            "skipped_downloaded": job.skipped_downloaded,
            "skipped_active": job.skipped_active,
            "skipped_deleted": job.skipped_deleted,
            "failed_count": len(job.failed_items),
            "failures": failures,
            "last_error": job.last_error,
            "failure_code": job.failure_code,
            "failed_page": job.failed_page,
            "wait_position": self._waiting_position_locked(job.id),
            "retry_round": job.retry_round,
            "stability_pass": job.stability_pass,
            "can_cancel": job.status in {"waiting", "discovering", "enqueuing"},
            "can_resume": job.status == "failed" and bool(job.failed_page),
            "can_retry_failed": job.status == "partial" and bool(job.failed_items),
        }

    def start(
        self,
        *,
        uid: str,
        owner_user_id: str,
        group_id: str,
        min_height: int | None,
    ) -> tuple[dict[str, Any], bool]:
        canonical_uid = parse_creator_locator(uid)
        owner = str(owner_user_id or "").strip()
        if not owner:
            raise ValueError("任务拥有者不能为空")
        group = self.catalog_store.resolve_group(str(group_id or ""), "")
        effective_min_height = validate_min_height(
            min_height,
            default=self.config_store.get().default_min_height,
        )
        now = self._clock()
        with self._cv:
            if self._stopped:
                raise CreatorImportStateError("全量入库服务正在停止")
            for existing in reversed(self._jobs.values()):
                if existing.uid == canonical_uid and existing.status in ACTIVE_JOB_STATUSES:
                    return self._snapshot_locked(existing), False
            job = _CreatorImportJob(
                id=uuid.uuid4().hex[:12],
                uid=canonical_uid,
                owner_user_id=owner,
                group_id=str(group.get("id") or ""),
                group_name=str(group.get("display_name") or ""),
                group_folder=str(group.get("folder_key") or ""),
                min_height=effective_min_height,
                cutoff_at=now,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job.id] = job
            self._waiting.append(job.id)
            self._trim_locked()
            self._ensure_thread_locked()
            self._cv.notify_all()
            snapshot = self._snapshot_locked(job)
        self._audit(job, "creator_import.start")
        return snapshot, True

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._snapshot_locked(job)
                for job in reversed(self._jobs.values())
            ]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            if job is None:
                raise CreatorImportNotFoundError("全量入库作业不存在")
            return self._snapshot_locked(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._cv:
            job = self._jobs.get(str(job_id or ""))
            if job is None:
                raise CreatorImportNotFoundError("全量入库作业不存在")
            if job.status == "cancelled":
                return self._snapshot_locked(job)
            if job.status not in ACTIVE_JOB_STATUSES:
                raise CreatorImportStateError("当前作业已经结束，不能取消")
            job.cancel_event.set()
            if job.status == "waiting":
                try:
                    self._waiting.remove(job.id)
                except ValueError:
                    pass
                job.status = "cancelled"
                job.phase = "cancelled"
                job.finished_at = self._clock()
                self._trim_locked()
            else:
                job.status = "stopping"
                job.phase = "stopping"
            self._touch_locked(job)
            self._cv.notify_all()
            snapshot = self._snapshot_locked(job)
        self._audit(job, "creator_import.cancel")
        return snapshot

    def resume(self, job_id: str) -> dict[str, Any]:
        with self._cv:
            job = self._jobs.get(str(job_id or ""))
            if job is None:
                raise CreatorImportNotFoundError("全量入库作业不存在")
            if job.status != "failed" or not job.failed_page:
                raise CreatorImportStateError("当前作业没有可继续的失败页")
            if self._stopped:
                raise CreatorImportStateError("全量入库服务正在停止")
            self._ensure_uid_available_locked(job)
            if job.failure_code == "source_unstable":
                job.stability_pass = 1
                job.next_page = 1
                job.pass_total = None
                job.pass_pages = None
                job.pass_changed = False
                job.pass_items = OrderedDict()
                job.pending_items.clear()
                job.discovered = 0
                job.discovery_complete = False
            job.cancel_event.clear()
            job.status = "waiting"
            job.phase = "waiting"
            job.finished_at = None
            job.last_error = ""
            job.failure_code = ""
            job.retry_failed_only = False
            self._touch_locked(job)
            self._waiting.append(job.id)
            self._ensure_thread_locked()
            self._cv.notify_all()
            snapshot = self._snapshot_locked(job)
        self._audit(job, "creator_import.resume")
        return snapshot

    def retry_failed(self, job_id: str) -> dict[str, Any]:
        with self._cv:
            job = self._jobs.get(str(job_id or ""))
            if job is None:
                raise CreatorImportNotFoundError("全量入库作业不存在")
            if job.status != "partial" or not job.failed_items:
                raise CreatorImportStateError("当前作业没有可重试的失败投稿")
            if self._stopped:
                raise CreatorImportStateError("全量入库服务正在停止")
            self._ensure_uid_available_locked(job)
            retry_items = [dict(value["item"]) for value in job.failed_items.values()]
            job.failed_items.clear()
            job.pending_items = deque(retry_items)
            job.cancel_event.clear()
            job.status = "waiting"
            job.phase = "waiting"
            job.finished_at = None
            job.last_error = ""
            job.failure_code = ""
            job.failed_page = None
            job.retry_failed_only = True
            job.retry_round += 1
            self._touch_locked(job)
            self._waiting.append(job.id)
            self._ensure_thread_locked()
            self._cv.notify_all()
            snapshot = self._snapshot_locked(job)
        self._audit(job, "creator_import.retry_failed")
        return snapshot

    def stop(self) -> None:
        thread: threading.Thread | None
        with self._cv:
            if self._stopped:
                return
            self._stopped = True
            now = self._clock()
            for job_id in list(self._waiting):
                job = self._jobs.get(job_id)
                if job is None or job.status != "waiting":
                    continue
                job.cancel_event.set()
                job.status = "cancelled"
                job.phase = "cancelled"
                job.finished_at = now
                self._touch_locked(job)
            self._waiting.clear()
            active = self._jobs.get(self._active_job_id)
            if active is not None and active.status in ACTIVE_JOB_STATUSES:
                active.cancel_event.set()
                active.status = "stopping"
                active.phase = "stopping"
                self._touch_locked(active)
            self._cv.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._stopped and not self._waiting:
                    self._cv.wait()
                if self._stopped:
                    return
                job_id = self._waiting.popleft()
                job = self._jobs.get(job_id)
                if job is None or job.status != "waiting":
                    continue
                self._active_job_id = job.id
                if job.started_at is None:
                    job.started_at = self._clock()
                job.status = "enqueuing" if job.retry_failed_only else (
                    "enqueuing" if job.discovery_complete else "discovering"
                )
                job.phase = job.status
                self._touch_locked(job)
            try:
                self._run_job(job)
            except Exception as exc:  # noqa: BLE001 - worker must remain available
                if self._cancelled(job):
                    self._finish_cancelled(job)
                else:
                    with self._lock:
                        if job.status not in TERMINAL_JOB_STATUSES:
                            job.status = "failed"
                            job.phase = "failed"
                            job.failure_code = "job_failed"
                            job.last_error = self._safe_error(exc)
                            job.finished_at = self._clock()
                            self._touch_locked(job)
                    self._audit(job, "creator_import.failed")
            finally:
                with self._cv:
                    if self._active_job_id == job.id:
                        self._active_job_id = ""
                    self._trim_locked()
                    self._cv.notify_all()

    def _run_job(self, job: _CreatorImportJob) -> None:
        if self._cancelled(job):
            self._finish_cancelled(job)
            return
        if not job.retry_failed_only and not job.discovery_complete:
            self._load_profile_safely(job)
            if not self._discover(job):
                if self._cancelled(job):
                    self._finish_cancelled(job)
                return
        if self._cancelled(job):
            self._finish_cancelled(job)
            return
        with self._lock:
            job.status = "enqueuing"
            job.phase = "enqueuing"
            job.failed_page = None
            self._touch_locked(job)
        self._enqueue_pending(job)
        if self._cancelled(job):
            self._finish_cancelled(job)
            return
        with self._lock:
            job.status = "partial" if job.failed_items else "completed"
            job.phase = job.status
            job.finished_at = self._clock()
            job.last_error = ""
            job.failure_code = ""
            job.retry_failed_only = False
            self._touch_locked(job)
        self._audit(job, f"creator_import.{job.status}")

    def _cancelled(self, job: _CreatorImportJob) -> bool:
        return self._stopped or job.cancel_event.is_set()

    def _finish_cancelled(self, job: _CreatorImportJob) -> None:
        with self._lock:
            job.status = "cancelled"
            job.phase = "cancelled"
            job.finished_at = self._clock()
            job.retry_failed_only = False
            self._touch_locked(job)

    def _load_profile_safely(self, job: _CreatorImportJob) -> None:
        if job.creator_name or self._cancelled(job):
            return
        try:
            profile = dict(self._profile_loader(job.uid) or {})
        except Exception:
            return
        with self._lock:
            job.creator_name = str(profile.get("name") or "")[:300]
            job.creator_avatar = str(profile.get("avatar") or "")[:2048]
            job.creator_profile_url = str(profile.get("profile_url") or "")[:2048]
            self._touch_locked(job)

    def _load_page_with_retry(
        self, job: _CreatorImportJob, page: int
    ) -> dict[str, Any] | None:
        attempts = max(1, len(self._retry_delays) + 1)
        last_error: BaseException | None = None
        for attempt in range(attempts):
            if self._cancelled(job):
                return None
            try:
                data = self._page_loader(job.uid, page)
                if not isinstance(data, dict):
                    raise ValueError("Bilibili 投稿页响应格式无效")
                return data
            except Exception as exc:  # noqa: BLE001 - translated to safe job state
                last_error = exc
                if attempt >= attempts - 1:
                    break
                delay = self._retry_delays[attempt]
                if job.cancel_event.wait(delay) or self._stopped:
                    return None
        with self._lock:
            job.status = "failed"
            job.phase = "failed"
            job.failure_code = "page_failed"
            job.failed_page = page
            job.next_page = page
            job.last_error = self._safe_error(
                last_error or RuntimeError("投稿页读取失败"), page=True
            )
            job.finished_at = self._clock()
            self._touch_locked(job)
        self._audit(job, "creator_import.page_failed", f"page={page}")
        return None

    @staticmethod
    def _page_numbers(data: dict[str, Any]) -> tuple[int, int]:
        try:
            total = max(0, int(data.get("total") or 0))
            pages = max(0, int(data.get("pages") or 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Bilibili 投稿页计数格式无效") from exc
        if pages > _MAX_SOURCE_PAGES:
            raise ValueError("UP 主投稿页数超过安全上限")
        return total, pages

    @staticmethod
    def _normalized_item(raw: Any, cutoff_at: float) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        bvid = str(raw.get("bvid") or "").strip()
        if not bvid:
            return None
        pubdate = raw.get("pubdate")
        try:
            published_at = int(pubdate or 0)
        except (TypeError, ValueError):
            published_at = 0
        if published_at > cutoff_at:
            return None
        item = dict(raw)
        item["bvid"] = bvid
        item["pubdate"] = published_at
        return item

    def _discover(self, job: _CreatorImportJob) -> bool:
        while not self._cancelled(job):
            page = max(1, int(job.next_page or 1))
            data = self._load_page_with_retry(job, page)
            if data is None:
                return False
            try:
                total, pages = self._page_numbers(data)
            except ValueError as exc:
                with self._lock:
                    job.status = "failed"
                    job.phase = "failed"
                    job.failure_code = "source_invalid"
                    job.failed_page = page
                    job.last_error = str(exc)
                    job.finished_at = self._clock()
                    self._touch_locked(job)
                return False

            with self._lock:
                if job.pass_total is None:
                    job.pass_total = total
                    job.pass_pages = pages
                    if not job.total_estimate:
                        job.total_estimate = total
                elif total != job.pass_total or pages != job.pass_pages:
                    job.pass_changed = True
                    job.pass_pages = max(int(job.pass_pages or 0), pages)
                effective_pages = max(1, int(job.pass_pages or pages or 1))
                job.total_pages = effective_pages
                job.current_page = page
                job.pages_scanned += 1

            raw_items = data.get("items") or []
            if not isinstance(raw_items, list):
                with self._lock:
                    job.status = "failed"
                    job.phase = "failed"
                    job.failure_code = "source_invalid"
                    job.failed_page = page
                    job.last_error = "Bilibili 投稿页列表格式无效"
                    job.finished_at = self._clock()
                    self._touch_locked(job)
                return False
            for raw in raw_items:
                item = self._normalized_item(raw, job.cutoff_at)
                if item is None:
                    continue
                bvid = str(item["bvid"])
                with self._lock:
                    job.pass_items.setdefault(bvid, item)
                    if not job.creator_name:
                        job.creator_name = str(item.get("author") or "")[:300]
                    job.discovered = len(job.pass_items)
                    self._touch_locked(job)

            with self._lock:
                effective_pages = max(1, int(job.pass_pages or 1))
                if page < effective_pages:
                    job.next_page = page + 1
                    continue
                if job.pass_changed:
                    if job.stability_pass >= self._max_stability_passes:
                        job.status = "failed"
                        job.phase = "failed"
                        job.failure_code = "source_unstable"
                        job.failed_page = 1
                        job.next_page = 1
                        job.last_error = "遍历期间投稿总数持续变化，请稍后继续"
                        job.finished_at = self._clock()
                        self._touch_locked(job)
                        self._audit(
                            job,
                            "creator_import.source_unstable",
                            f"passes={job.stability_pass}",
                        )
                        return False
                    job.stability_pass += 1
                    job.next_page = 1
                    job.pass_total = None
                    job.pass_pages = None
                    job.pass_changed = False
                    job.pass_items = OrderedDict()
                    job.discovered = 0
                    self._touch_locked(job)
                    continue

                ordered = sorted(
                    job.pass_items.values(),
                    key=lambda item: (
                        int(item.get("pubdate") or 0),
                        str(item.get("bvid") or ""),
                    ),
                    reverse=True,
                )
                job.pending_items = deque(dict(item) for item in ordered)
                job.discovered = len(ordered)
                job.discovery_complete = True
                job.failed_page = None
                job.last_error = ""
                job.failure_code = ""
                self._touch_locked(job)
                return True
        return False

    def _bulk_active_count(self, job: _CreatorImportJob) -> int:
        with self._lock:
            task_ids = tuple(job.created_task_ids)
        count = 0
        for task_id in task_ids:
            task = self.queue.get_task(task_id)
            if task and task.get("status") in {"queued", "running"}:
                count += 1
        return count

    def _wait_for_capacity(self, job: _CreatorImportJob) -> bool:
        while not self._cancelled(job):
            max_pending = max(1, int(self.queue.max_pending))
            reserve = min(self._manual_capacity_reserve, max_pending - 1)
            bulk_ceiling = max_pending - reserve
            if (
                self._bulk_active_count(job) < self.worker_window
                and self.queue.active_count() < bulk_ceiling
            ):
                return True
            if job.cancel_event.wait(self._capacity_poll_seconds):
                return False
        return False

    def _classify_existing(self, item: dict[str, Any]) -> str:
        key = str(item.get("bvid") or "")
        task = self.queue.key_statuses([key]).get(key)
        if task and task.get("status") in {"queued", "running"}:
            return "active"
        if self.index.get_valid(key) is not None:
            return "downloaded"
        if key in self.deletion_store.for_keys([key]):
            return "deleted"
        return ""

    def _record_skip(self, job: _CreatorImportJob, category: str) -> None:
        with self._lock:
            if category == "downloaded":
                job.skipped_downloaded += 1
            elif category == "active":
                job.skipped_active += 1
            elif category == "deleted":
                job.skipped_deleted += 1
            self._touch_locked(job)

    def _record_item_failure(
        self, job: _CreatorImportJob, item: dict[str, Any], message: str
    ) -> None:
        bvid = str(item.get("bvid") or "未知投稿")
        with self._lock:
            job.failed_items[bvid] = {
                "bvid": bvid,
                "title": str(item.get("title") or "")[:300],
                "message": str(message or "投稿处理失败")[:500],
                "item": dict(item),
            }
            self._touch_locked(job)

    def _enqueue_one(self, job: _CreatorImportJob, item: dict[str, Any]) -> str:
        target = parse_inputs(bvids=[str(item.get("bvid") or "")], max_items=1)[0]
        metadata = {
            target.key: {
                "title": str(item.get("title") or "")[:300],
                "cover": str(item.get("cover") or "")[:2048],
                "author": str(item.get("author") or "")[:300],
                "pubdate": item.get("pubdate")
                if isinstance(item.get("pubdate"), int)
                else None,
                "duration": str(item.get("duration") or "")[:32],
                "play": item.get("play") if isinstance(item.get("play"), int) else None,
                "preferred_quality": "",
            }
        }
        persisted_ids: list[str] = []
        published = False

        def persist(items: list[dict[str, Any]]) -> None:
            persisted_ids.extend(self.task_store.register_task_batch("library", items))

        try:
            tasks = self.queue.enqueue(
                [target],
                force=False,
                metadata=metadata,
                group=job.group_name,
                group_id=job.group_id,
                group_folder=job.group_folder,
                min_height=job.min_height,
                owner_user_id=job.owner_user_id,
                strict=True,
                before_publish=persist,
            )
            published = True
        except Exception:
            if persisted_ids and not published:
                self.task_store.rollback_registered_batch(persisted_ids)
            raise
        task = tasks[0]
        task_id = str(task.get("id") or "")
        if not task_id:
            raise ValueError("下载任务创建结果缺少标识")
        with self._lock:
            job.created_task_ids.append(task_id)
            job.queued += 1
            job.failed_items.pop(target.key, None)
            self._touch_locked(job)
        self._audit(job, "creator_import.enqueue", f"task={task_id}")
        return task_id

    def _enqueue_pending(self, job: _CreatorImportJob) -> None:
        while not self._cancelled(job):
            with self._lock:
                if not job.pending_items:
                    return
                item = dict(job.pending_items[0])
            try:
                category = self._classify_existing(item)
            except Exception:
                category = ""
                self._record_item_failure(job, item, "本地作品状态暂时无法确认")
                with self._lock:
                    job.pending_items.popleft()
                continue
            if category:
                self._record_skip(job, category)
                with self._lock:
                    job.failed_items.pop(str(item.get("bvid") or ""), None)
                    job.pending_items.popleft()
                continue
            if not self._wait_for_capacity(job):
                return
            try:
                self._enqueue_one(job, item)
            except BatchConflictError as exc:
                code = str((exc.reasons[0] if exc.reasons else {}).get("code") or "")
                if code == "active_task_conflict":
                    self._record_skip(job, "active")
                elif code == "already_downloaded":
                    self._record_skip(job, "downloaded")
                else:
                    self._record_item_failure(job, item, str(exc))
            except QueueFullError:
                continue
            except Exception as exc:  # noqa: BLE001 - isolate one submission
                self._record_item_failure(job, item, self._safe_error(exc))
            with self._lock:
                if job.pending_items:
                    job.pending_items.popleft()
