from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.constants import DATABASE_SCHEMA_VERSION
from bili_workspace_launcher import runtime_smoke
from bili_workspace_launcher.paths import AppPaths, DataRootLayout
from bili_workspace_launcher.settings import NetworkSettings


def test_runtime_smoke_uses_fresh_root_and_stops_own_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_id = "0123456789ab"
    paths = AppPaths(tmp_path / "control")
    data_root = tmp_path / "data"
    report_path = tmp_path / "runtime-smoke.json"
    observed: dict[str, object] = {}

    class FakeResources:
        def __init__(self, app_paths: AppPaths) -> None:
            self.paths = app_paths

        def ensure_extracted(self):
            root = self.paths.resources_dir / build_id
            root.mkdir(parents=True)
            return root, SimpleNamespace(build_id=build_id)

    class FakeDataRoots:
        def __init__(self, app_paths: AppPaths, template_dir: Path) -> None:
            observed["template_dir"] = template_dir
            self.paths = app_paths

        def resolve_layout(self, candidate: Path) -> DataRootLayout:
            candidate.mkdir()
            return DataRootLayout(candidate)

        def prepare_locked(
            self, candidate: Path, data_lock
        ) -> DataRootLayout:
            assert data_lock.acquired
            layout = DataRootLayout(candidate)
            layout.config_dir.mkdir()
            layout.userdata_dir.mkdir()
            layout.runtime_env_file.write_text("BILI_APP_MODE=local\n", encoding="utf-8")
            with sqlite3.connect(layout.database_file) as connection:
                connection.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION}")
            return layout

    class FakeRuntimeEnvStore:
        def __init__(self, path: Path) -> None:
            observed["runtime_env"] = path

        def load(self) -> NetworkSettings:
            return NetworkSettings(port=3399)

    class FakeBackend:
        def __init__(self, app_paths: AppPaths) -> None:
            self.paths = app_paths
            self.port: int | None = None
            self.url: str | None = None

        def start(self, **kwargs) -> None:
            assert kwargs["data_lock"].acquired
            assert kwargs["build_id"] == build_id
            self.port = kwargs["network"].port
            self.url = f"http://127.0.0.1:{self.port}/"
            observed["started"] = True

        def wait_until_ready(self) -> None:
            observed["ready"] = True

        def stop(self, timeout=None) -> bool:
            observed["stopped"] = timeout
            self.port = None
            self.url = None
            return False

    monkeypatch.setattr(runtime_smoke, "ResourceManager", FakeResources)
    monkeypatch.setattr(runtime_smoke, "DataRootManager", FakeDataRoots)
    monkeypatch.setattr(runtime_smoke, "RuntimeEnvStore", FakeRuntimeEnvStore)
    monkeypatch.setattr(runtime_smoke, "BackendProcessManager", FakeBackend)
    monkeypatch.setattr(runtime_smoke, "is_port_available", lambda _port, _host: True)
    monkeypatch.setattr(
        runtime_smoke,
        "_probe_root_page",
        lambda url, host: observed.update(root_url=url, root_host=host),
    )

    result = runtime_smoke.run_runtime_smoke(
        data_root,
        build_id,
        report_path,
        paths=paths,
    )

    assert result == {
        "schema_version": 1,
        "status": "passed",
        "build_id": build_id,
        "application_schema_version": DATABASE_SCHEMA_VERSION,
        "mode": "local",
        "root_page": "passed",
        "port": 3399,
    }
    assert observed["started"] is True
    assert observed["ready"] is True
    assert observed["stopped"] is None
    assert observed["root_host"] == "127.0.0.1"
    assert not report_path.exists()


def test_runtime_smoke_rejects_existing_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    with pytest.raises(RuntimeError, match="全新数据根"):
        runtime_smoke.run_runtime_smoke(
            data_root,
            "0123456789ab",
            tmp_path / "runtime-smoke.json",
            paths=AppPaths(tmp_path / "control"),
        )


def test_database_schema_gate_rejects_stale_schema(tmp_path: Path) -> None:
    database = tmp_path / "database.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=4")
    with pytest.raises(RuntimeError, match="schema v4"):
        runtime_smoke._database_schema(database)
