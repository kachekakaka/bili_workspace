import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import ConfigStore
from app.index_store import IndexStore
from app.progress import PHASE_LABELS, ProgressEvent
from app.queue import Task, TaskQueue
from app.task_extensions import cancel_task, pause_task
from app.task_logs import task_log_path
from app.urls import Target
from tests.conftest import wait_terminal


def _target(i: int) -> Target:
    key = f"K{i:03d}"
    return Target(key=key, url=f"https://www.bilibili.com/video/BV{i:010d}")


def test_serial_success_and_real_artifact_index(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    calls = []

    def runner(argv, **kwargs):
        del kwargs
        calls.append(argv)
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"video")
        time.sleep(0.02)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    created = queue.enqueue([_target(1), _target(2)])
    for task in created:
        assert wait_terminal(queue, task["id"])["status"] == "success"
    assert len(calls) == 2
    assert index.has("K001") and index.has("K002")
    queue.stop()


def test_zero_exit_without_media_is_failed(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    queue = TaskQueue(
        store,
        index,
        runner=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    created = queue.enqueue([_target(3)])[0]
    task = wait_terminal(queue, created["id"])
    assert task["status"] == "failed"
    assert "未生成" in task["error"]
    assert index.get("K003") is None
    queue.stop()


def test_force_replaces_only_after_new_artifact_is_valid(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    contents = iter((b"first", b"second"))

    def runner(argv, **kwargs):
        del kwargs
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(next(contents))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    first = queue.enqueue([_target(4)])[0]
    assert wait_terminal(queue, first["id"])["status"] == "success"
    final = tmp_env.download_dir / "groups" / "未分组" / "items" / "K004" / "demo.mp4"
    assert final.read_bytes() == b"first"
    forced = queue.enqueue([_target(4)], force=True)[0]
    assert wait_terminal(queue, forced["id"])["status"] == "success"
    assert final.read_bytes() == b"second"
    queue.stop()


def test_failed_force_keeps_old_file_and_index(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    calls = 0

    def runner(argv, **kwargs):
        nonlocal calls
        del kwargs
        calls += 1
        work = Path(argv[argv.index("--work-dir") + 1])
        if calls == 1:
            (work / "demo.mp4").write_bytes(b"old")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    first = queue.enqueue([_target(5)])[0]
    assert wait_terminal(queue, first["id"])["status"] == "success"
    forced = queue.enqueue([_target(5)], force=True)[0]
    assert wait_terminal(queue, forced["id"])["status"] == "failed"
    final = tmp_env.download_dir / "groups" / "未分组" / "items" / "K005" / "demo.mp4"
    assert final.read_bytes() == b"old"
    assert index.has("K005")
    queue.stop()


def test_history_limit_never_drops_queued_tasks(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    release = threading.Event()
    started = threading.Event()
    calls = []

    def runner(argv, **kwargs):
        del kwargs
        calls.append(argv)
        started.set()
        release.wait(timeout=5)
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"x")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner, max_history=3, max_pending=10)
    try:
        created = queue.enqueue([_target(i) for i in range(5)])
        assert len(created) == 5
        assert started.wait(timeout=2)
        assert len(queue.list_tasks()) == 5
        assert all(queue.get_task(task["id"]) is not None for task in created)
        release.set()
        assert wait_terminal(queue, created[-1]["id"], timeout=60)["status"] == "success"
        assert len(calls) == 5
        assert len(queue.list_tasks()) <= 3
        assert queue.get_task(created[-1]["id"]) is not None
    finally:
        release.set()
        queue.stop()


def test_cancel_queued_task(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    release = threading.Event()

    def runner(argv, **kwargs):
        del kwargs
        release.wait(timeout=3)
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"x")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    first, second = queue.enqueue([_target(200), _target(201)])
    deadline = time.time() + 2
    while time.time() < deadline:
        if queue.get_task(first["id"])["status"] == "running":
            break
        time.sleep(0.01)
    assert queue.cancel(second["id"]) is True
    assert queue.get_task(second["id"])["status"] == "cancelled"
    release.set()
    queue.stop()


def test_progress_and_phase_changes_notify_only_when_visible_state_changes(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    seen = []
    queue = TaskQueue(store, index, on_state_change=lambda *args: seen.append(args))
    task = Task(
        id="progress-notify",
        key="KPROGRESS",
        url="https://www.bilibili.com/video/BV1PROGRESS1",
        bvid="BV1PROGRESS1",
        force=False,
        status="running",
        phase="resolving",
        phase_label=PHASE_LABELS["resolving"],
    )
    event = ProgressEvent(
        phase="download_video",
        phase_label=PHASE_LABELS["download_video"],
        progress_percent=12.5,
        speed_text="1 MiB/s",
        message="下载视频 12.5%",
    )
    try:
        before = queue.change_count()
        queue._set_progress(task, event)
        assert queue.change_count() == before + 1
        assert len(seen) == 1

        queue._set_progress(task, event)
        assert queue.change_count() == before + 1
        assert len(seen) == 1

        queue._set_phase(task, "merge", message="正在混流", percent=None)
        assert queue.change_count() == before + 2
        queue._set_phase(task, "merge", message="正在混流", percent=None)
        assert queue.change_count() == before + 2

        task.phase = "cancelling"
        queue._set_progress(task, event)
        assert task.phase == "cancelling"
        assert queue.change_count() == before + 2
    finally:
        queue.stop()


def test_change_count_is_published_after_state_callback(tmp_env, monkeypatch):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    order = []
    queue = TaskQueue(
        store,
        index,
        on_state_change=lambda *_args: order.append("persisted"),
    )
    original_bump = queue._bump_change_locked

    def ordered_bump():
        order.append("published")
        original_bump()

    monkeypatch.setattr(queue, "_bump_change_locked", ordered_bump)
    task = Task(
        id="notification-order",
        key="KORDER",
        url="https://www.bilibili.com/video/BV1ORDER001",
        bvid="BV1ORDER001",
        force=False,
    )
    try:
        with queue._lock:
            queue._notify_locked(task)
        assert order == ["persisted", "published"]
    finally:
        queue.stop()


def test_pause_can_be_upgraded_to_cancel_without_false_terminal_state(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    started = threading.Event()
    release = threading.Event()

    def runner(argv, **kwargs):
        del kwargs
        started.set()
        release.wait(timeout=5)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    try:
        created = queue.enqueue([_target(202)])[0]
        assert started.wait(timeout=2)

        pausing = pause_task(queue, created["id"])
        assert pausing["status"] == "running"
        assert pausing["phase"] == "pausing"
        assert pausing["finished_at"] is None

        cancelling = cancel_task(queue, created["id"])
        assert cancelling["status"] == "running"
        assert cancelling["phase"] == "cancelling"
        assert cancelling["finished_at"] is None
        assert cancel_task(queue, created["id"])["phase"] == "cancelling"

        release.set()
        finished = wait_terminal(queue, created["id"])
        assert finished["status"] == "cancelled"
        assert finished["phase"] == "cancelled"
        assert finished["finished_at"] is not None
        assert cancel_task(queue, created["id"])["phase"] == "cancelled"
    finally:
        release.set()
        queue.stop()


def test_cancel_during_synchronous_metadata_wait_does_not_start_preflight(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    metadata_started = threading.Event()
    release = threading.Event()
    runner_calls = []

    def metadata_fetcher(*_args):
        metadata_started.set()
        release.wait(timeout=5)
        return {"title": "延迟元数据"}

    def runner(argv, **kwargs):
        del kwargs
        runner_calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(
        store,
        index,
        runner=runner,
        metadata_fetcher=metadata_fetcher,
    )
    try:
        created = queue.enqueue([_target(205)])[0]
        assert metadata_started.wait(timeout=2)
        cancelling = cancel_task(queue, created["id"])
        assert cancelling["status"] == "running"
        assert cancelling["phase"] == "cancelling"
        assert cancelling["finished_at"] is None
        release.set()
        finished = wait_terminal(queue, created["id"])
        assert finished["phase"] == "cancelled"
        assert runner_calls == []
    finally:
        release.set()
        queue.stop()


def test_cancel_while_execution_slot_arrives_commits_terminal_once(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    entered = threading.Event()
    allow_acquire = threading.Event()
    seen = []

    class GateSemaphore:
        def acquire(self, timeout):
            del timeout
            entered.set()
            allow_acquire.wait(timeout=3)
            return True

        def release(self):
            return None

    queue = TaskQueue(
        store,
        index,
        runner=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        execution_semaphore=GateSemaphore(),
        on_state_change=lambda _task_id, payload: seen.append(payload),
    )
    try:
        created = queue.enqueue([_target(206)])[0]
        assert entered.wait(timeout=2)
        cancelling = cancel_task(queue, created["id"])
        assert cancelling["phase"] == "cancelling"
        allow_acquire.set()
        finished = wait_terminal(queue, created["id"])
        assert finished["phase"] == "cancelled"
        terminal = [
            payload
            for payload in seen
            if payload
            and payload["id"] == created["id"]
            and payload["status"] == "cancelled"
        ]
        assert len(terminal) == 1
    finally:
        allow_acquire.set()
        queue.stop()


def test_queued_pause_is_terminal_and_cannot_be_relabelled_as_cancel(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    started = threading.Event()
    release = threading.Event()

    def runner(argv, **kwargs):
        del kwargs
        started.set()
        release.wait(timeout=5)
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"x")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    try:
        _running, queued = queue.enqueue([_target(203), _target(204)])
        assert started.wait(timeout=2)
        paused = pause_task(queue, queued["id"])
        assert paused["status"] == "cancelled"
        assert paused["phase"] == "paused"
        assert paused["finished_at"] is not None
        assert pause_task(queue, queued["id"])["phase"] == "paused"
        with pytest.raises(ValueError, match="已暂停"):
            cancel_task(queue, queued["id"])
    finally:
        release.set()
        queue.stop()


def test_force_rolls_back_old_output_when_index_commit_fails(tmp_env):
    from app.config import ConfigStore
    from app.index_store import IndexStore

    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    old_dir = tmp_env.download_dir / "items" / "BVROLLBACK01"
    old_dir.mkdir(parents=True)
    old_file = old_dir / "old.mp4"
    old_file.write_bytes(b"old")
    stat = old_file.stat()
    index.put(
        "BVROLLBACK01",
        title="old",
        path="items/BVROLLBACK01",
        files=[{
            "path": "items/BVROLLBACK01/old.mp4",
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }],
    )

    original_put = index.put

    def fail_put(*args, **kwargs):
        del args, kwargs
        raise OSError("simulated index failure")

    index.put = fail_put  # type: ignore[method-assign]

    def runner(argv, **kwargs):
        del kwargs
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "new.mp4").write_bytes(b"new")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    try:
        task = queue.enqueue(
            [Target(key="BVROLLBACK01", url="https://www.bilibili.com/video/BVROLLBACK01")],
            force=True,
        )[0]
        done = wait_terminal(queue, task["id"])
        assert done["status"] == "failed"
        assert old_file.read_bytes() == b"old"
        assert not (old_dir / "new.mp4").exists()
    finally:
        index.put = original_put  # type: ignore[method-assign]
        queue.stop()


def test_clear_finished_removes_task_log_but_keeps_media(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)

    def runner(argv, **kwargs):
        del kwargs
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"media")
        return SimpleNamespace(returncode=0, stdout="finished", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    created = queue.enqueue([_target(301)])[0]
    done = wait_terminal(queue, created["id"])
    log_path = task_log_path(tmp_env.download_dir, created["id"])
    output = tmp_env.download_dir / done["output_path"] / "demo.mp4"
    assert log_path.is_file()
    assert output.is_file()
    assert queue.clear_finished() == 1
    assert queue.get_task(created["id"]) is None
    assert not log_path.exists()
    assert output.read_bytes() == b"media"
    queue.stop()


def test_newly_finished_task_is_retained_when_history_is_trimmed(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    release = threading.Event()
    started = threading.Event()

    def runner(argv, **kwargs):
        del kwargs
        started.set()
        release.wait(timeout=3)
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"x")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner, max_history=3, max_pending=10)
    running = queue.enqueue([_target(310)])[0]
    assert started.wait(timeout=2)
    # Duplicate submissions create terminal skipped records while the first task is active.
    for _ in range(4):
        queue.enqueue([_target(310)])
    release.set()
    done = wait_terminal(queue, running["id"])
    assert done["status"] == "success"
    assert queue.get_task(running["id"]) is not None
    assert len(queue.list_tasks()) <= 3
    queue.stop()

def test_change_count_increments_without_persistence_callback(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)

    def runner(argv, **kwargs):
        del kwargs
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner)
    before = queue.change_count()
    created = queue.enqueue([_target(401)])
    assert queue.change_count() > before
    task = wait_terminal(queue, created[0]["id"])
    assert task["status"] == "success"
    assert queue.change_count() > before
    queue.stop()


def test_change_count_increments_with_callback(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    index = IndexStore(tmp_env.download_dir)
    seen = []

    def runner(argv, **kwargs):
        del kwargs
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = TaskQueue(store, index, runner=runner, on_state_change=lambda *args: seen.append(args))
    before = queue.change_count()
    queue.enqueue([_target(402)])
    wait_terminal(queue, queue.list_tasks()[0]["id"])
    assert queue.change_count() > before
    assert seen
    queue.stop()
