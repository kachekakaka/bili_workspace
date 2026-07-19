from __future__ import annotations

import hashlib
import threading
from typing import Any

from app.constants import TERMINAL_STATUSES
from app.queue import QueueFullError, Task, TaskQueue
from app.urls import Target


class OwnedTaskQueue(TaskQueue):
    """TaskQueue with immutable website-user ownership.

    Device-export queues may namespace their internal storage/index key by owner.
    The public ``key``/``source_key`` remains the original Bilibili source key,
    so two users can export the same BV without sharing temporary artifacts.
    """

    def __init__(
        self,
        *args,
        default_owner_user_id: str,
        namespace_by_owner: bool = False,
        **kwargs,
    ) -> None:
        raw_initial = [dict(item) for item in kwargs.get("initial_tasks") or []]
        self.default_owner_user_id = str(default_owner_user_id or "")
        self.namespace_by_owner = bool(namespace_by_owner)
        self._owners: dict[str, str] = {}
        self._source_keys: dict[str, str] = {}
        self._queue_key_sources: dict[str, str] = {}
        self._owner_context = threading.local()

        prepared: list[dict[str, Any]] = []
        for item in raw_initial:
            task_id = str(item.get("id") or "")
            owner = str(item.get("owner_user_id") or self.default_owner_user_id)
            source_key = str(item.get("source_key") or item.get("key") or "")
            queue_key = str(item.get("_queue_key") or "")
            if not queue_key:
                queue_key = self._queue_key(owner, source_key)
            item["key"] = queue_key
            item["source_key"] = source_key
            item["_queue_key"] = queue_key
            prepared.append(item)
            if task_id:
                self._owners[task_id] = owner
                self._source_keys[task_id] = source_key
            if queue_key:
                self._queue_key_sources[queue_key] = source_key
        kwargs["initial_tasks"] = prepared
        super().__init__(*args, **kwargs)

    def _queue_key(self, owner_user_id: str, source_key: str) -> str:
        source = str(source_key or "")
        if not self.namespace_by_owner:
            return source
        prefix = hashlib.sha256(str(owner_user_id or "").encode("utf-8")).hexdigest()[:16]
        return f"owner-{prefix}:{source}"

    def _context_owner(self) -> str:
        return str(
            getattr(self._owner_context, "owner_user_id", "")
            or self.default_owner_user_id
        )

    def _context_sources(self) -> dict[str, str]:
        value = getattr(self._owner_context, "source_by_queue_key", None)
        return value if isinstance(value, dict) else {}

    def _remember_locked(self, task: Task) -> None:
        owner = self._context_owner()
        source_key = self._context_sources().get(task.key)
        if source_key is None:
            source_key = self._queue_key_sources.get(task.key, task.key)
        self._owners.setdefault(task.id, owner)
        self._source_keys.setdefault(task.id, str(source_key or task.key))
        self._queue_key_sources[task.key] = self._source_keys[task.id]
        super()._remember_locked(task)

    def _public_payload(self, task: Task, *, queue_position: int | None = None) -> dict[str, Any]:
        payload = task.to_dict(queue_position=queue_position)
        source_key = self._source_keys.get(task.id, task.key)
        payload["_queue_key"] = task.key
        payload["source_key"] = source_key
        payload["key"] = source_key
        payload["owner_user_id"] = self._owners.get(
            task.id, self.default_owner_user_id
        )
        return payload

    def _notify_locked(self, task: Task | None, *, task_id: str = "") -> None:
        callback = self.on_state_change
        if callback is None:
            return
        try:
            if task is None:
                callback(task_id, None)
                return
            callback(task.id, self._public_payload(task))
        except Exception:
            # Persistence must never turn a valid download into a failed task.
            pass

    def _drop_task_locked(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        queue_key = task.key if task is not None else ""
        super()._drop_task_locked(task_id)
        self._owners.pop(task_id, None)
        self._source_keys.pop(task_id, None)
        if queue_key and not any(item.key == queue_key for item in self._tasks.values()):
            self._queue_key_sources.pop(queue_key, None)

    def owner_for_task(self, task_id: str) -> str:
        with self._lock:
            return str(self._owners.get(task_id) or "")

    def source_key_for_task(self, task_id: str) -> str:
        with self._lock:
            return str(self._source_keys.get(task_id) or "")

    def active_count_for_owner(self, owner_user_id: str) -> int:
        owner = str(owner_user_id or "")
        with self._lock:
            return sum(
                1
                for task_id, task in self._tasks.items()
                if self._owners.get(task_id) == owner
                and task.status in {"queued", "running"}
            )

    def _queue_needed_locked(self, targets: list[Target], *, force: bool) -> int:
        active_keys = {
            task.key for task in self._tasks.values() if task.status in {"queued", "running"}
        }
        queue_needed = 0
        for target in targets:
            if target.key in active_keys:
                continue
            if not force:
                valid = self.index.get_valid(target.key)
                if valid is not None:
                    continue
                if self.index.get(target.key) is not None:
                    self.index.discard_entry(target.key)
            queue_needed += 1
            active_keys.add(target.key)
        return queue_needed

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
        owner_user_id: str = "",
        owner_active_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        owner = str(owner_user_id or self._context_owner())
        if not owner:
            raise ValueError("任务拥有者不能为空")

        source_by_queue_key: dict[str, str] = {}
        transformed: list[Target] = []
        source_metadata = metadata or {}
        transformed_metadata: dict[str, dict[str, Any]] = {}
        for target in targets:
            source_key = self._queue_key_sources.get(target.key, target.key)
            queue_key = self._queue_key(owner, source_key)
            source_by_queue_key[queue_key] = source_key
            transformed.append(Target(key=queue_key, url=target.url, bvid=target.bvid))
            transformed_metadata[queue_key] = dict(
                source_metadata.get(source_key)
                or source_metadata.get(target.key)
                or {}
            )

        with self._cv:
            if owner_active_limit is not None:
                active = self.active_count_for_owner(owner)
                needed = self._queue_needed_locked(transformed, force=force)
                if active + needed > max(0, int(owner_active_limit)):
                    raise QueueFullError(
                        f"当前账号已有 {active} 个活动任务，本次需新增 {needed} 个，"
                        f"上限 {int(owner_active_limit)} 个"
                    )
            previous_owner = getattr(self._owner_context, "owner_user_id", "")
            previous_sources = getattr(
                self._owner_context, "source_by_queue_key", None
            )
            self._owner_context.owner_user_id = owner
            self._owner_context.source_by_queue_key = source_by_queue_key
            try:
                items = super().enqueue(
                    transformed,
                    force=force,
                    metadata=transformed_metadata,
                    group=group,
                    group_id=group_id,
                    group_folder=group_folder,
                    min_height=min_height,
                    retry_of=retry_of,
                )
            finally:
                self._owner_context.owner_user_id = previous_owner
                self._owner_context.source_by_queue_key = previous_sources

            result: list[dict[str, Any]] = []
            for item in items:
                task_id = str(item.get("id") or "")
                task = self._tasks.get(task_id)
                if task is not None:
                    result.append(
                        self._public_payload(
                            task,
                            queue_position=self._queue_positions_locked().get(task_id),
                        )
                    )
            return result

    def retry(self, task_id: str, *, force: bool = False) -> list[dict[str, Any]]:
        owner = self.owner_for_task(task_id) or self.default_owner_user_id
        previous = getattr(self._owner_context, "owner_user_id", "")
        self._owner_context.owner_user_id = owner
        try:
            return super().retry(task_id, force=force)
        finally:
            self._owner_context.owner_user_id = previous

    def list_tasks(self, owner_user_id: str | None = None) -> list[dict[str, Any]]:
        owner_filter = None if owner_user_id is None else str(owner_user_id)
        with self._lock:
            positions = self._queue_positions_locked()
            return [
                self._public_payload(
                    self._tasks[task_id], queue_position=positions.get(task_id)
                )
                for task_id in reversed(self._order)
                if task_id in self._tasks
                and (
                    owner_filter is None
                    or self._owners.get(task_id) == owner_filter
                )
            ]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return self._public_payload(
                task, queue_position=self._queue_positions_locked().get(task_id)
            )

    def key_statuses(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        # Search status is only used by the non-namespaced administrator library
        # queue. Keep the public key shape even when called defensively elsewhere.
        result = super().key_statuses(keys)
        for item in result.values():
            task_id = str(item.get("id") or "")
            source_key = self._source_keys.get(task_id, str(item.get("key") or ""))
            item["_queue_key"] = str(item.get("key") or "")
            item["source_key"] = source_key
            item["key"] = source_key
            item["owner_user_id"] = self._owners.get(task_id, "")
        return result

    def clear_finished(self, owner_user_id: str | None = None) -> int:
        if owner_user_id is None:
            return super().clear_finished()
        owner = str(owner_user_id)
        with self._lock:
            remove = [
                task_id
                for task_id, task in self._tasks.items()
                if task.status in TERMINAL_STATUSES
                and self._owners.get(task_id) == owner
            ]
            for task_id in remove:
                self._drop_task_locked(task_id)
            return len(remove)
