from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_workspace_launcher import live_session
from bili_workspace_launcher.paths import AppPaths, DataRootLayout
from bili_workspace_launcher.settings import NetworkSettings


def _owned_run(tmp_path: Path) -> tuple[Path, AppPaths]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "runs"
    run = test_root / "run-test"
    candidate = run / "candidate"
    for relative in live_session._RUN_DIRECTORIES:
        (run / relative).mkdir(parents=True, exist_ok=True)
    candidate.mkdir()
    (run / ".bili-workspace-test-run.json").write_text(
        json.dumps(
            {
                "kind": "bili-workspace-test-run",
                "project_id": "bili_workspace",
                "workspace_root": str(workspace),
                "test_root": str(test_root),
                "run_root": str(run),
                "run_id": run.name,
                "created_at": "2026-09-03T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (run / "results" / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "test_id": "T-BILIBILI-LIVE",
                "run_id": run.name,
                "target": "candidate",
            }
        ),
        encoding="utf-8",
    )
    return run, AppPaths(candidate)


def test_live_session_only_accepts_fixed_owned_run_paths(tmp_path: Path) -> None:
    run, paths = _owned_run(tmp_path)
    inputs = live_session.validate_live_session_inputs(
        data_root=(run / "runtime").resolve(),
        ready_path=(run / "results" / "candidate-live-ready.json").resolve(),
        result_path=(run / "results" / "candidate-live-result.json").resolve(),
        stop_path=(run / "runtime" / "candidate-live.stop").resolve(),
        paths=paths,
    )
    assert inputs.run_root == run.resolve()

    with pytest.raises(RuntimeError, match="run/runtime"):
        live_session.validate_live_session_inputs(
            data_root=(run / "other-data").resolve(),
            ready_path=inputs.ready_path,
            result_path=inputs.result_path,
            stop_path=inputs.stop_path,
            paths=paths,
        )


def test_live_session_rejects_incomplete_or_extended_ownership_marker(
    tmp_path: Path,
) -> None:
    run, paths = _owned_run(tmp_path)
    marker_path = run / ".bili-workspace-test-run.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["unexpected"] = True
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(RuntimeError, match="字段集合"):
        live_session.validate_live_session_inputs(
            data_root=(run / "runtime").resolve(),
            ready_path=(run / "results" / "candidate-live-ready.json").resolve(),
            result_path=(run / "results" / "candidate-live-result.json").resolve(),
            stop_path=(run / "runtime" / "candidate-live.stop").resolve(),
            paths=paths,
        )


def test_live_session_rejects_missing_standard_run_directory(tmp_path: Path) -> None:
    run, paths = _owned_run(tmp_path)
    (run / "downloads").rmdir()

    with pytest.raises(RuntimeError, match="安全子目录"):
        live_session.validate_live_session_inputs(
            data_root=(run / "runtime").resolve(),
            ready_path=(run / "results" / "candidate-live-ready.json").resolve(),
            result_path=(run / "results" / "candidate-live-result.json").resolve(),
            stop_path=(run / "runtime" / "candidate-live.stop").resolve(),
            paths=paths,
        )


def test_live_session_rejects_boolean_summary_schema_version(tmp_path: Path) -> None:
    run, paths = _owned_run(tmp_path)
    summary_path = run / "results" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["schema_version"] = True
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(RuntimeError, match="摘要身份"):
        live_session.validate_live_session_inputs(
            data_root=(run / "runtime").resolve(),
            ready_path=(run / "results" / "candidate-live-ready.json").resolve(),
            result_path=(run / "results" / "candidate-live-result.json").resolve(),
            stop_path=(run / "runtime" / "candidate-live.stop").resolve(),
            paths=paths,
        )


def test_live_session_rejects_invalid_session_token() -> None:
    with pytest.raises(RuntimeError, match="会话令牌"):
        live_session.live_session_token_sha256("not-a-token")


def test_live_session_enforces_maximum_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = live_session.LiveSessionInputs(
        run_root=tmp_path,
        data_root=tmp_path / "runtime",
        ready_path=tmp_path / "ready.json",
        result_path=tmp_path / "result.json",
        stop_path=tmp_path / "stop",
    )
    backend = SimpleNamespace(is_running=True)
    monkeypatch.setattr(
        live_session.time,
        "monotonic",
        lambda: live_session._MAX_SESSION_SECONDS,
    )

    with pytest.raises(RuntimeError, match="最大时限"):
        live_session._wait_for_stop(inputs, backend, 0)


def test_live_session_rejects_unsafe_stop_path(tmp_path: Path) -> None:
    stop_path = tmp_path / "stop"
    stop_path.mkdir()
    inputs = live_session.LiveSessionInputs(
        run_root=tmp_path,
        data_root=tmp_path / "runtime",
        ready_path=tmp_path / "ready.json",
        result_path=tmp_path / "result.json",
        stop_path=stop_path,
    )

    with pytest.raises(RuntimeError, match="停止路径类型"):
        live_session._wait_for_stop(
            inputs,
            SimpleNamespace(is_running=True),
            live_session.time.monotonic(),
        )


def test_live_session_starts_and_stops_only_its_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, paths = _owned_run(tmp_path)
    build_id = "0123456789ab"
    session_token = "a" * 64
    observed: dict[str, object] = {}

    class FakeResources:
        def __init__(self, app_paths: AppPaths) -> None:
            self.paths = app_paths

        def ensure_extracted(self):
            root = self.paths.resources_dir / build_id
            (root / "docker-context" / "app" / "defaults").mkdir(parents=True)
            return root, SimpleNamespace(build_id=build_id)

    class FakeDataRoots:
        def __init__(self, app_paths: AppPaths, template_dir: Path) -> None:
            observed["template_dir"] = template_dir

        def resolve_layout(self, candidate: Path) -> DataRootLayout:
            return DataRootLayout(candidate)

        def prepare_locked(self, candidate: Path, data_lock) -> DataRootLayout:
            assert data_lock.acquired
            layout = DataRootLayout(candidate)
            layout.config_dir.mkdir(exist_ok=True)
            layout.runtime_env_file.write_text("BILI_APP_MODE=local\n", encoding="utf-8")
            return layout

    class FakeRuntimeEnvStore:
        def __init__(self, path: Path) -> None:
            observed["runtime_env"] = path

        def load(self) -> NetworkSettings:
            return NetworkSettings(port=3399)

    class FakeBackend:
        def __init__(self, app_paths: AppPaths) -> None:
            self.port: int | None = None
            self.url: str | None = None
            self.process_id: int | None = None
            self.is_running = False

        def start(self, **kwargs) -> None:
            assert kwargs["data_lock"].acquired
            self.port = 3399
            self.url = "http://127.0.0.1:3399/"
            self.process_id = 123
            self.is_running = True

        def wait_until_ready(self) -> None:
            (run / "runtime" / "candidate-live.stop").write_text("stop\n", encoding="utf-8")

        def stop(self, timeout=None) -> bool:
            observed["stopped"] = timeout
            self.port = None
            self.url = None
            self.process_id = None
            self.is_running = False
            return False

    monkeypatch.setattr(live_session, "ResourceManager", FakeResources)
    monkeypatch.setattr(live_session, "DataRootManager", FakeDataRoots)
    monkeypatch.setattr(live_session, "RuntimeEnvStore", FakeRuntimeEnvStore)
    monkeypatch.setattr(live_session, "BackendProcessManager", FakeBackend)
    monkeypatch.setattr(live_session, "_probe_root_page", lambda *_args: None)
    monkeypatch.setattr(live_session, "_local_available_network", lambda network: network)

    result = live_session.run_live_session(
        data_root=(run / "runtime").resolve(),
        expected_build_id=build_id,
        ready_path=(run / "results" / "candidate-live-ready.json").resolve(),
        result_path=(run / "results" / "candidate-live-result.json").resolve(),
        stop_path=(run / "runtime" / "candidate-live.stop").resolve(),
        session_token=session_token,
        paths=paths,
    )
    assert result["status"] == "stopped"
    assert result["token_sha256"] == live_session.live_session_token_sha256(
        session_token
    )
    assert observed["stopped"] is None
    assert (run / "results" / "candidate-live-ready.json").is_file()
    assert (run / "results" / "candidate-live-result.json").is_file()
