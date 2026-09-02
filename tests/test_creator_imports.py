from __future__ import annotations

import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.creator_imports import CreatorImportManager


def _video(number: int, pubdate: int) -> dict[str, Any]:
    bvid = f"BV{number:010d}"
    return {
        "bvid": bvid,
        "title": f"投稿 {number}",
        "author": "测试 UP",
        "cover": "https://i0.hdslb.com/test.jpg",
        "pubdate": pubdate,
        "duration": "00:10",
        "play": number,
    }


class FakeQueue:
    max_pending = 100

    def __init__(self, *, auto_finish: bool = True) -> None:
        self.auto_finish = auto_finish
        self.enqueued: list[str] = []
        self.tasks: dict[str, dict[str, Any]] = {}
        self.external_active: dict[str, dict[str, Any]] = {}
        self.failures: Counter[str] = Counter()
        self.max_active_seen = 0
        self._lock = threading.Lock()

    def active_count(self) -> int:
        with self._lock:
            own = sum(
                task["status"] in {"queued", "running"}
                for task in self.tasks.values()
            )
            external = sum(
                task["status"] in {"queued", "running"}
                for task in self.external_active.values()
            )
            return own + external

    def key_statuses(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        with self._lock:
            result = {
                key: dict(self.external_active[key])
                for key in keys
                if key in self.external_active
            }
            for task in self.tasks.values():
                key = str(task["source_key"])
                if key in keys and task["status"] in {"queued", "running"}:
                    result[key] = dict(task)
            return result

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.tasks.get(task_id)
            return dict(value) if value else None

    def enqueue(self, targets, *, before_publish=None, **kwargs):
        del kwargs
        source_key = str(targets[0].key)
        with self._lock:
            if self.failures[source_key] > 0:
                self.failures[source_key] -= 1
                raise ValueError(f"{source_key} 合成入队失败")
            task_id = f"task-{len(self.enqueued) + 1}"
            task = {
                "id": task_id,
                "owner_user_id": "admin-user",
                "source_key": source_key,
                "status": "queued",
            }
            if before_publish:
                before_publish([dict(task)])
            self.enqueued.append(source_key)
            self.tasks[task_id] = task
            active = sum(
                item["status"] in {"queued", "running"}
                for item in self.tasks.values()
            )
            self.max_active_seen = max(self.max_active_seen, active)
            if self.auto_finish:
                self.tasks[task_id]["status"] = "success"
            return [dict(task)]

    def finish_first_active(self) -> None:
        with self._lock:
            for task in self.tasks.values():
                if task["status"] in {"queued", "running"}:
                    task["status"] = "success"
                    return

    def remove_one_external(self) -> None:
        with self._lock:
            if self.external_active:
                self.external_active.pop(next(iter(self.external_active)))


class FakeIndex:
    def __init__(self, valid: set[str] | None = None) -> None:
        self.valid = set(valid or set())

    def get_valid(self, key: str):
        return {"source_key": key} if key in self.valid else None


class FakeDeletionStore:
    def __init__(self, deleted: set[str] | None = None) -> None:
        self.deleted = set(deleted or set())

    def for_keys(self, keys: list[str]):
        return {key: {"source_key": key} for key in keys if key in self.deleted}


class FakeCatalogStore:
    def resolve_group(self, group_id: str, fallback_name: str):
        del fallback_name
        return {
            "id": group_id or "grp-default",
            "display_name": "测试分组",
            "folder_key": "测试分组",
        }


class FakeTaskStore:
    def __init__(self) -> None:
        self.registered: list[str] = []
        self.rolled_back: list[str] = []

    def register_task_batch(self, destination: str, tasks: list[dict[str, Any]]):
        assert destination == "library"
        ids = [str(task["id"]) for task in tasks]
        self.registered.extend(ids)
        return ids

    def rollback_registered_batch(self, task_ids: list[str]) -> None:
        self.rolled_back.extend(task_ids)


def _manager(
    queue: FakeQueue,
    page_loader,
    *,
    index: FakeIndex | None = None,
    deleted: FakeDeletionStore | None = None,
    worker_window: int = 2,
) -> CreatorImportManager:
    return CreatorImportManager(
        queue=queue,
        index=index or FakeIndex(),
        deletion_store=deleted or FakeDeletionStore(),
        catalog_store=FakeCatalogStore(),
        task_store=FakeTaskStore(),
        config_store=SimpleNamespace(get=lambda: SimpleNamespace(default_min_height=1080)),
        bbdown_dir=Path("unused"),
        worker_window=worker_window,
        page_loader=page_loader,
        profile_loader=lambda uid: {
            "uid": uid,
            "name": "测试 UP",
            "avatar": "https://i0.hdslb.com/avatar.jpg",
            "profile_url": f"https://space.bilibili.com/{uid}",
        },
        clock=lambda: 200,
        retry_delays=(),
        capacity_poll_seconds=0.01,
    )


def _start(manager: CreatorImportManager, uid: str = "123456") -> str:
    job, created = manager.start(
        uid=uid,
        owner_user_id="admin-user",
        group_id="grp-1",
        min_height=1080,
    )
    assert created is True
    return str(job["id"])


def _wait_for(manager: CreatorImportManager, job_id: str, statuses: set[str], timeout=3):
    deadline = time.monotonic() + timeout
    snapshot = manager.get_job(job_id)
    while time.monotonic() < deadline:
        snapshot = manager.get_job(job_id)
        if snapshot["status"] in statuses:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {statuses}: {snapshot!r}")


def test_import_orders_snapshot_and_classifies_expected_skips() -> None:
    queue = FakeQueue()
    queue.external_active["BV0000000002"] = {"status": "queued", "id": "manual"}
    index = FakeIndex({"BV0000000001"})
    deleted = FakeDeletionStore({"BV0000000003"})

    def pages(uid: str, page: int):
        assert uid == "123456"
        if page == 1:
            return {
                "total": 6,
                "pages": 2,
                "items": [_video(1, 100), _video(4, 190), _video(5, 201)],
            }
        return {
            "total": 6,
            "pages": 2,
            "items": [_video(2, 180), _video(3, 170), _video(4, 190)],
        }

    manager = _manager(queue, pages, index=index, deleted=deleted)
    try:
        job = _wait_for(manager, _start(manager), {"completed"})
        assert queue.enqueued == ["BV0000000004"]
        assert job["discovered"] == 4
        assert job["queued"] == 1
        assert job["skipped_downloaded"] == 1
        assert job["skipped_active"] == 1
        assert job["skipped_deleted"] == 1
        assert job["processed"] == 4
        assert job["failed_count"] == 0
    finally:
        manager.stop()


def test_import_isolates_item_failure_and_retries_only_failed_items() -> None:
    queue = FakeQueue()
    failed_key = "BV0000000002"
    queue.failures[failed_key] = 1
    manager = _manager(
        queue,
        lambda uid, page: {
            "total": 2,
            "pages": 1,
            "items": [_video(1, 190), _video(2, 180)],
        },
    )
    try:
        job_id = _start(manager)
        partial = _wait_for(manager, job_id, {"partial"})
        assert partial["queued"] == 1
        assert partial["failed_count"] == 1
        assert partial["failures"][0]["bvid"] == failed_key
        assert "item" not in partial["failures"][0]

        manager.retry_failed(job_id)
        completed = _wait_for(manager, job_id, {"completed"})
        assert completed["queued"] == 2
        assert completed["failed_count"] == 0
        assert completed["retry_round"] == 1
        assert queue.enqueued == ["BV0000000001", failed_key]
    finally:
        manager.stop()


def test_failed_page_resumes_from_same_page_without_losing_prior_discovery() -> None:
    fail_second = True
    calls: list[int] = []

    def pages(uid: str, page: int):
        del uid
        nonlocal fail_second
        calls.append(page)
        if page == 2 and fail_second:
            raise RuntimeError("upstream down")
        return {
            "total": 2,
            "pages": 2,
            "items": [_video(page, 200 - page)],
        }

    queue = FakeQueue()
    manager = _manager(queue, pages)
    try:
        job_id = _start(manager)
        failed = _wait_for(manager, job_id, {"failed"})
        assert failed["failed_page"] == 2
        assert failed["failure_code"] == "page_failed"
        assert queue.enqueued == []

        fail_second = False
        manager.resume(job_id)
        completed = _wait_for(manager, job_id, {"completed"})
        assert completed["discovered"] == 2
        assert calls == [1, 2, 2]
        assert queue.enqueued == ["BV0000000001", "BV0000000002"]
    finally:
        manager.stop()


def test_same_uid_is_idempotent_and_other_uids_wait_fifo() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []

    def pages(uid: str, page: int):
        assert page == 1
        calls.append(uid)
        if uid == "111":
            first_started.set()
            assert release_first.wait(2)
        return {"total": 0, "pages": 0, "items": []}

    manager = _manager(FakeQueue(), pages)
    try:
        first_id = _start(manager, "111")
        assert first_started.wait(1)
        same, created = manager.start(
            uid="111",
            owner_user_id="admin-user",
            group_id="grp-1",
            min_height=1080,
        )
        assert created is False
        assert same["id"] == first_id
        second_id = _start(manager, "222")
        assert manager.get_job(second_id)["status"] == "waiting"
        assert manager.get_job(second_id)["wait_position"] == 1

        release_first.set()
        _wait_for(manager, first_id, {"completed"})
        _wait_for(manager, second_id, {"completed"})
        assert calls == ["111", "222"]
    finally:
        release_first.set()
        manager.stop()


def test_low_priority_window_and_cancel_stop_future_enqueue() -> None:
    queue = FakeQueue(auto_finish=False)
    manager = _manager(
        queue,
        lambda uid, page: {
            "total": 2,
            "pages": 1,
            "items": [_video(1, 190), _video(2, 180)],
        },
        worker_window=1,
    )
    try:
        job_id = _start(manager)
        deadline = time.monotonic() + 2
        while len(queue.enqueued) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert queue.enqueued == ["BV0000000001"]
        assert queue.max_active_seen == 1

        stopping = manager.cancel(job_id)
        assert stopping["status"] in {"stopping", "cancelled"}
        cancelled = _wait_for(manager, job_id, {"cancelled"})
        assert cancelled["queued"] == 1
        assert queue.enqueued == ["BV0000000001"]
        assert queue.get_task("task-1")["status"] == "queued"
    finally:
        manager.stop()


def test_bulk_import_leaves_queue_capacity_for_manual_submissions() -> None:
    queue = FakeQueue()
    queue.external_active = {
        f"manual-{number}": {"status": "queued", "id": f"manual-{number}"}
        for number in range(98)
    }
    manager = _manager(
        queue,
        lambda uid, page: {"total": 1, "pages": 1, "items": [_video(1, 190)]},
        worker_window=2,
    )
    try:
        job_id = _start(manager)
        _wait_for(manager, job_id, {"enqueuing"})
        time.sleep(0.05)
        assert queue.enqueued == []

        queue.remove_one_external()
        completed = _wait_for(manager, job_id, {"completed"})
        assert completed["queued"] == 1
        assert queue.enqueued == ["BV0000000001"]
    finally:
        manager.stop()


def test_changed_source_is_retraversed_until_one_stable_pass() -> None:
    calls: list[int] = []

    def pages(uid: str, page: int):
        del uid
        calls.append(page)
        first_pass = len(calls) <= 2
        total = 2 if first_pass and page == 1 else 3
        return {
            "total": total,
            "pages": 2,
            "items": [_video((10 if first_pass else 20) + page, 200 - page)],
        }

    queue = FakeQueue()
    manager = _manager(queue, pages)
    try:
        completed = _wait_for(manager, _start(manager), {"completed"})
        assert calls == [1, 2, 1, 2]
        assert completed["stability_pass"] == 2
        assert queue.enqueued == ["BV0000000021", "BV0000000022"]
    finally:
        manager.stop()


def test_unstable_source_can_be_restarted_cleanly_in_current_process() -> None:
    unstable = True
    calls = 0

    def pages(uid: str, page: int):
        del uid
        nonlocal calls
        calls += 1
        total = calls if unstable else 2
        return {
            "total": total,
            "pages": 2,
            "items": [_video(page, 200 - page)],
        }

    queue = FakeQueue()
    manager = _manager(queue, pages)
    try:
        job_id = _start(manager)
        failed = _wait_for(manager, job_id, {"failed"})
        assert failed["failure_code"] == "source_unstable"
        assert failed["failed_page"] == 1
        assert queue.enqueued == []

        unstable = False
        manager.resume(job_id)
        completed = _wait_for(manager, job_id, {"completed"})
        assert completed["stability_pass"] == 1
        assert completed["discovered"] == 2
        assert queue.enqueued == ["BV0000000001", "BV0000000002"]
    finally:
        manager.stop()


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/bilibili/creator-imports", "get"),
        ("/api/bilibili/creator-imports", "post"),
        ("/api/bilibili/creator-imports/job-1", "get"),
        ("/api/bilibili/creator-imports/job-1/cancel", "post"),
        ("/api/bilibili/creator-imports/job-1/resume", "post"),
        ("/api/bilibili/creator-imports/job-1/retry-failed", "post"),
    ],
)
def test_creator_import_api_rejects_normal_users(client, path: str, method: str) -> None:
    admin = client.state_ref.auth_store.default_owner_user_id()
    user = client.state_ref.auth_store.create_user(
        "creator-user", "普通用户", "Temporary-123", created_by=admin
    )
    client.state_ref.database.execute(
        "UPDATE users SET must_change_password=0 WHERE id=?", (user["id"],)
    )
    token, session = client.state_ref.auth_store.login(
        "creator-user", "Temporary-123", remote_addr="127.0.0.1", user_agent="test"
    )
    client.cookies.clear()
    client.cookies.set("bili_session", token, domain="127.0.0.1", path="/")
    client.headers.update({"X-CSRF-Token": str(session["csrf_token"])})

    kwargs = {"json": {"uid": "123456"}} if method == "post" else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_creator_import_start_api_uses_session_owner_and_returns_idempotency(client, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def start(**kwargs):
        calls.append(kwargs)
        return ({"id": "job-1", "uid": "123456", "status": "waiting"}, False)

    monkeypatch.setattr(client.state_ref.creator_imports, "start", start)
    response = client.post(
        "/api/bilibili/creator-imports",
        json={"uid": "123456", "group_id": "grp-1", "min_height": 720},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "job": {"id": "job-1", "uid": "123456", "status": "waiting"},
        "created": False,
    }
    assert calls[0]["owner_user_id"] == client.state_ref.auth_store.default_owner_user_id()
    assert calls[0]["group_id"] == "grp-1"
    assert calls[0]["min_height"] == 720


def test_creator_import_write_api_requires_csrf(client, monkeypatch) -> None:
    called = False

    def start(**kwargs):
        nonlocal called
        called = True
        return ({}, True)

    monkeypatch.setattr(client.state_ref.creator_imports, "start", start)
    csrf = client.headers.pop("X-CSRF-Token")
    try:
        response = client.post(
            "/api/bilibili/creator-imports",
            json={"uid": "123456", "group_id": "", "min_height": 1080},
        )
    finally:
        client.headers.update({"X-CSRF-Token": csrf})

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert called is False
