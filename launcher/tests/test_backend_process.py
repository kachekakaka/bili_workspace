from __future__ import annotations

import json
import hashlib
import os
import shutil
import time
from pathlib import Path

import pytest

from bili_workspace_launcher.backend_process import (
    BackendProcessError,
    BackendProcessManager,
    _load_and_verify_child_session,
)
from bili_workspace_launcher.paths import AppPaths, DataRootLock, DataRootManager
from bili_workspace_launcher.settings import NetworkSettings


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 43210
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        del timeout
        self.returncode = 0
        return 0

    def kill(self):
        self.killed = True
        self.returncode = -9


class FakeJob:
    def __init__(self) -> None:
        self.assigned = None
        self.closed = False

    def assign(self, process) -> None:
        self.assigned = process

    def close(self) -> None:
        self.closed = True


class FakeResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._payload


def _templates(root: Path) -> Path:
    root.mkdir()
    (root / "config.json.default").write_text(
        '{"config_schema_version":2,"host":"127.0.0.1","port":3398,'
        '"download_dir":"downloads",'
        '"bbdown_dir":"tools","poll_hint_ms":1500,"download_timeout_sec":3600,'
        '"dfn_priority":"","encoding_priority":"","default_group":"未分组",'
        '"default_min_height":1080}\n',
        encoding="utf-8",
    )
    (root / "runtime.env.default").write_text(
        "BILI_APP_MODE=local\nBILI_HOST=\nBILI_PORT=\n", encoding="utf-8"
    )
    (root / "tags.json.default").write_text(
        '{"palette_version": 2, "tags": []}\n', encoding="utf-8"
    )
    return root


def _tools(root: Path) -> Path:
    tools = root / "windows-tools"
    tools.mkdir(parents=True)
    (tools / "BBDown.exe").write_bytes(b"fake")
    ffmpeg = tools / "ffmpeg" / "bin"
    ffmpeg.mkdir(parents=True)
    (ffmpeg / "ffmpeg.exe").write_bytes(b"fake")
    return root


def test_backend_uses_explicit_data_and_tool_paths_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    layout = DataRootManager(paths, _templates(tmp_path / "templates")).prepare(tmp_path / "data")
    resource_root = _tools(paths.resources_dir / "0123456789ab")
    captured = {}
    process = FakeProcess()
    job = FakeJob()
    monkeypatch.setenv("BILI_MEDIA_DIR", str(tmp_path / "inherited-media"))
    monkeypatch.setenv("BILI_BBDOWN_DIR", str(tmp_path / "legacy-bbdown"))
    monkeypatch.setenv("BILI_BOOTSTRAP_TOKEN", "must-not-cross-process-boundary")
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "inherited-python-home"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "inherited-python-path"))

    def popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return process

    manager = BackendProcessManager(paths, popen_factory=popen, job_factory=lambda: job)
    manager.start(
        layout=layout,
        network=NetworkSettings(),
        resource_root=resource_root,
        build_id="0123456789ab",
    )
    environment = captured["env"]
    assert environment["BILI_LAUNCHER_CHILD"] == "1"
    assert Path(environment["BILI_CONFIG_DIR"]) == layout.config_dir
    assert Path(environment["BILI_MEDIA_DIR"]) == layout.downloads_dir
    assert Path(environment["BILI_BBDOWN_TOOLS_DIR"]) == resource_root / "windows-tools"
    assert Path(environment["BILI_BBDOWN_DATA_DIR"]) == layout.bbdown_data_dir
    assert "BILI_BBDOWN_DIR" not in environment
    assert Path(environment["BILI_APP_RESOURCE_ROOT"]) == resource_root / "docker-context"
    assert Path(environment["HOME"]) == layout.home_dir
    assert Path(environment["DOTNET_BUNDLE_EXTRACT_BASE_DIR"]) == layout.dotnet_bundle_dir
    assert Path(environment["TEMP"]) == layout.temp_dir
    assert Path(environment["TMP"]) == layout.temp_dir
    assert "BILI_BOOTSTRAP_TOKEN" not in environment
    assert "PYTHONHOME" not in environment
    assert "PYTHONPATH" not in environment
    assert job.assigned is process
    assert manager.process_id == process.pid
    assert manager.stop() is False
    assert job.closed is True

    second = BackendProcessManager(paths, popen_factory=popen, job_factory=lambda: FakeJob())
    second.start(
        layout=layout,
        network=NetworkSettings(),
        resource_root=resource_root,
        build_id="0123456789ab",
    )
    second.stop()


def test_backend_setup_failure_releases_lock_and_removes_owned_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    layout = DataRootManager(paths, _templates(tmp_path / "templates")).prepare(tmp_path / "data")
    resource_root = _tools(paths.resources_dir / "0123456789ab")

    def fail_journal(*_args, **_kwargs):
        raise OSError("injected journal failure")

    monkeypatch.setattr(
        "bili_workspace_launcher.backend_process.atomic_write_json", fail_journal
    )
    manager = BackendProcessManager(paths, popen_factory=lambda *_args, **_kwargs: FakeProcess())
    with pytest.raises(BackendProcessError, match="无法创建"):
        manager.start(
            layout=layout,
            network=NetworkSettings(),
            resource_root=resource_root,
            build_id="0123456789ab",
        )

    assert not list(paths.work_dir.glob("backend-*"))
    lock = DataRootLock(layout)
    lock.acquire()
    lock.release()


def test_backend_recovers_only_valid_dead_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()

    def create_session(name: str, pid: int) -> Path:
        session = paths.owned_job_dir(name)
        session.mkdir()
        (session / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "backend-session",
                    "job_id": name,
                    "build_id": "0123456789ab",
                    "token_sha256": "a" * 64,
                    "data_root": str(tmp_path / "data"),
                    "resource_root": str(paths.resources_dir / "0123456789ab"),
                    "host": "127.0.0.1",
                    "port": 3398,
                    "created_at": 100,
                    "pid": pid,
                    "spawned_at": 101,
                }
            ),
            encoding="utf-8",
        )
        return session

    dead = create_session("backend-" + "a" * 32, 111)
    active = create_session("backend-" + "b" * 32, 222)
    invalid = create_session("backend-" + "c" * 32, 333)
    (invalid / "unowned.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        "bili_workspace_launcher.backend_process._process_exists",
        lambda pid: pid == 222,
    )

    messages = BackendProcessManager(paths).recover_stale_sessions()

    assert not dead.exists()
    assert active.is_dir()
    assert invalid.is_dir()
    assert messages == [f"已清理无存活进程的遗留后端会话：{dead.name}"]


def test_backend_does_not_release_caller_owned_data_lock(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    layout = DataRootManager(paths, _templates(tmp_path / "templates")).prepare(tmp_path / "data")
    resource_root = _tools(paths.resources_dir / "0123456789ab")
    data_lock = DataRootLock(layout)
    data_lock.acquire()
    manager = BackendProcessManager(
        paths,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
        job_factory=FakeJob,
    )

    manager.start(
        layout=layout,
        network=NetworkSettings(),
        resource_root=resource_root,
        build_id="0123456789ab",
        data_lock=data_lock,
    )
    manager.stop()

    assert data_lock.acquired is True
    data_lock.release()


def test_health_probe_requires_exact_backend_build_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = BackendProcessManager(AppPaths(tmp_path / "control"))
    manager._process = FakeProcess()
    manager._network = NetworkSettings()
    manager._expected_build_id = "0123456789ab"

    class Opener:
        payload = {"ok": True, "build_id": "wrong", "mode": "local"}

        def open(self, _request, timeout):
            del timeout
            return FakeResponse(self.payload)

    opener = Opener()
    monkeypatch.setattr("bili_workspace_launcher.backend_process._DIRECT_URL_OPENER", opener)
    assert manager.health_ready() is False

    opener.payload = {"ok": True, "build_id": "0123456789ab", "mode": "server"}
    assert manager.health_ready() is False

    opener.payload = {"ok": True, "build_id": "0123456789ab", "mode": "local"}
    assert manager.health_ready() is True


def test_stop_rejects_session_directory_type_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    layout = DataRootManager(paths, _templates(tmp_path / "templates")).prepare(tmp_path / "data")
    resource_root = _tools(paths.resources_dir / "0123456789ab")
    manager = BackendProcessManager(
        paths,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
        job_factory=FakeJob,
    )
    manager.start(
        layout=layout,
        network=NetworkSettings(),
        resource_root=resource_root,
        build_id="0123456789ab",
    )
    session = manager._session_dir
    assert session is not None
    changed = True
    monkeypatch.setattr(
        "bili_workspace_launcher.backend_process._is_reparse_point",
        lambda path: changed and Path(path) == session,
    )

    with pytest.raises(BackendProcessError, match="会话目录类型无效"):
        manager.stop()
    assert manager._stop_file is not None
    assert not manager._stop_file.exists()

    changed = False
    manager.stop()


def test_backend_log_tail_is_bounded_and_redacted(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    manager = BackendProcessManager(paths)
    log = tmp_path / "backend.log"
    log.write_text("x" * (300 * 1024) + "\nCookie: secret-cookie-value\n", encoding="utf-8")
    manager._log_file = log

    tail = manager.log_tail()

    assert len(tail) < 300 * 1024
    assert "secret-cookie-value" not in tail
    assert "Cookie: ***" in tail


def test_child_session_rejects_wrong_token_before_starting_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    session = paths.owned_job_dir("backend-" + "a" * 32)
    session.mkdir()
    journal = session / "session.json"
    stop = session / "stop.request"
    log = tmp_path / "data" / "userdata" / "logs" / "backend.log"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "backend-session",
                "job_id": session.name,
                "build_id": "0123456789ab",
                "host": "127.0.0.1",
                "port": 3398,
                "token_sha256": "0" * 64,
                "data_root": str(tmp_path / "data"),
                "resource_root": str(paths.resources_dir / "0123456789ab"),
                "created_at": int(time.time()),
                "pid": os.getpid(),
                "spawned_at": int(time.time()),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILI_BUILD_ID", "0123456789ab")
    monkeypatch.setenv("BILI_HOST", "127.0.0.1")
    monkeypatch.setenv("BILI_PORT", "3398")
    monkeypatch.setenv("BILI_LAUNCHER_TOKEN", "wrong")
    monkeypatch.setenv("BILI_CONFIG_DIR", str(tmp_path / "data" / "config"))
    with pytest.raises(BackendProcessError, match="令牌"):
        _load_and_verify_child_session(
            paths=paths,
            journal_file=journal,
            stop_file=stop,
            log_file=log,
        )


def test_child_session_requires_every_path_to_match_launcher_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    paths.ensure_control_directories()
    layout = DataRootManager(paths).prepare(tmp_path / "data")
    build_id = "0123456789ab"
    bundle = tmp_path / "bundle"
    source = bundle / "source"
    defaults = source / "docker-context" / "app" / "defaults"
    defaults.mkdir(parents=True)
    payloads = {
        defaults / "config.json.default": b'{"config_schema_version": 2}\n',
        defaults / "runtime.env.default": b"BILI_NETWORK_MODE=local\n",
        defaults / "tags.json.default": b'{"palette_version": 2}\n',
    }
    for payload, content in payloads.items():
        payload.write_bytes(content)
    manifest = {
        "schema_version": 1,
        "product_version": "0.7.0",
        "build_id": build_id,
        "files": {
            payload.relative_to(source).as_posix(): {
                "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                "size": payload.stat().st_size,
            }
            for payload in payloads
        },
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    resource_root = paths.resources_dir / build_id
    shutil.copytree(source, resource_root)
    monkeypatch.setenv("BILI_LAUNCHER_RESOURCE_BUNDLE", str(bundle))

    session = paths.owned_job_dir("backend-" + "b" * 32)
    session.mkdir()
    journal = session / "session.json"
    stop = session / "stop.request"
    log = layout.userdata_dir / "logs" / "backend.log"
    token = "d" * 32
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "backend-session",
                "job_id": session.name,
                "build_id": build_id,
                "host": "127.0.0.1",
                "port": 3398,
                "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
                "data_root": str(layout.root),
                "resource_root": str(resource_root),
                "created_at": int(time.time()),
                "pid": os.getpid(),
                "spawned_at": int(time.time()),
            }
        ),
        encoding="utf-8",
    )
    expected = {
        "BILI_BUILD_ID": build_id,
        "BILI_HOST": "127.0.0.1",
        "BILI_PORT": "3398",
        "BILI_LAUNCHER_TOKEN": token,
        "BILI_DISABLE_LEGACY_MIGRATION": "1",
        "BILI_CONFIG_DIR": str(layout.config_dir),
        "BILI_USERDATA_DIR": str(layout.userdata_dir),
        "BILI_DATABASE_PATH": str(layout.userdata_dir / "bili_workspace.db"),
        "BILI_MEDIA_DIR": str(layout.downloads_dir),
        "BILI_CACHE_DIR": str(layout.userdata_dir / "cache"),
        "BILI_TEMP_DIR": str(layout.userdata_dir / "tmp"),
        "BILI_BBDOWN_TOOLS_DIR": str(resource_root / "windows-tools"),
        "BILI_BBDOWN_DATA_DIR": str(layout.bbdown_data_dir),
        "BILI_APP_RESOURCE_ROOT": str(resource_root / "docker-context"),
        "HOME": str(layout.home_dir),
        "XDG_CACHE_HOME": str(layout.cache_dir),
        "DOTNET_BUNDLE_EXTRACT_BASE_DIR": str(layout.dotnet_bundle_dir),
        "TEMP": str(layout.temp_dir),
        "TMP": str(layout.temp_dir),
        "TMPDIR": str(layout.temp_dir),
    }
    for key, value in expected.items():
        monkeypatch.setenv(key, value)
    loaded_layout, loaded_resource, _raw = _load_and_verify_child_session(
        paths=paths,
        journal_file=journal,
        stop_file=stop,
        log_file=log,
    )
    assert loaded_layout.root == layout.root
    assert loaded_resource == resource_root

    expired = json.loads(journal.read_text(encoding="utf-8"))
    expired["created_at"] = 1
    journal.write_text(json.dumps(expired), encoding="utf-8")
    with pytest.raises(BackendProcessError, match="已过期"):
        _load_and_verify_child_session(
            paths=paths,
            journal_file=journal,
            stop_file=stop,
            log_file=log,
        )
    expired["created_at"] = int(time.time())
    expired["spawned_at"] = expired["created_at"]
    journal.write_text(json.dumps(expired), encoding="utf-8")

    monkeypatch.setenv("BILI_APP_RESOURCE_ROOT", str(resource_root))
    with pytest.raises(BackendProcessError, match="BILI_APP_RESOURCE_ROOT"):
        _load_and_verify_child_session(
            paths=paths,
            journal_file=journal,
            stop_file=stop,
            log_file=log,
        )
