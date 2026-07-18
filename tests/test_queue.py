import threading
import time
from pathlib import Path
from types import SimpleNamespace

from app.config import ConfigStore
from app.index_store import IndexStore
from app.queue import TaskQueue
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

    queue = TaskQueue(store, index, runner=runner, max_history=100, max_pending=200)
    created = queue.enqueue([_target(i) for i in range(105)])
    assert len(created) == 105
    assert started.wait(timeout=2)
    assert len(queue.list_tasks()) == 105
    assert all(queue.get_task(task["id"]) is not None for task in created)
    release.set()
    deadline = time.time() + 10
    while time.time() < deadline and len(calls) < 105:
        time.sleep(0.02)
    assert len(calls) == 105
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
    log_path = tmp_env.download_dir / ".bili_logs" / f"{created['id']}.log"
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
