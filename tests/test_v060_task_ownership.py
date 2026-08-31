from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth import hash_password
from app.constants import (
    ADMIN_TASK_HISTORY_LIMIT,
    DATABASE_SCHEMA_VERSION,
    NORMAL_USER_ACTIVE_TASK_LIMIT,
    NORMAL_USER_TASK_HISTORY_LIMIT,
)
from app.database import Database
from app.main import create_app
from app.runtime import RuntimeSettings
from app.state import AppState
from app.task_routes import events
from tests.conftest import StaticCookieChecker, artifact_runner, wait_terminal


def _configure_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    config_dir = tmp_path / "config"
    bbdown_dir = config_dir / "bbdown"
    bbdown_dir.mkdir(parents=True)
    (bbdown_dir / "BBDown").write_bytes(b"fake")
    (bbdown_dir / "ffmpeg").write_bytes(b"fake")
    values = {
        "BILI_APP_MODE": "docker",
        "BILI_CONFIG_DIR": str(config_dir),
        "BILI_USERDATA_DIR": str(tmp_path / "userdata"),
        "BILI_MEDIA_DIR": str(tmp_path / "media"),
        "BILI_CACHE_DIR": str(tmp_path / "userdata" / "cache"),
        "BILI_TEMP_DIR": str(tmp_path / "userdata" / "tmp"),
        "BILI_BBDOWN_DIR": str(bbdown_dir),
        "BILI_PUBLIC_BASE_URL": "https://bili.example.test",
        "BILI_TRUSTED_HOSTS": "bili.example.test,testserver",
        "BILI_TRUSTED_PROXY_IPS": "127.0.0.1",
        "BILI_COOKIE_SECURE": "true",
        "BILI_HSTS": "true",
        "BILI_BOOTSTRAP_TOKEN": "bootstrap-token-for-tests",
        "BILI_MIN_FREE_GIB": "0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def _setup_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runner=None,
) -> tuple[AppState, TestClient, dict, tuple[str, dict], tuple[str, dict]]:
    values = _configure_server(tmp_path, monkeypatch)
    state = AppState.create(
        runner=runner or artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    client = TestClient(create_app(state), base_url="https://bili.example.test")
    setup = client.post(
        "/api/auth/setup",
        json={
            "username": "administrator",
            "display_name": "管理员",
            "password": "Admin-password-123",
            "bootstrap_token": values["BILI_BOOTSTRAP_TOKEN"],
        },
    )
    assert setup.status_code == 200, setup.text
    admin = setup.json()["data"]
    user_a = state.auth_store.create_user(
        "user-a", "用户甲", "Temporary-123", created_by=admin["user"]["id"]
    )
    user_b = state.auth_store.create_user(
        "user-b", "用户乙", "Temporary-123", created_by=admin["user"]["id"]
    )
    state.database.execute(
        "UPDATE users SET must_change_password=0 WHERE id IN (?,?)",
        (user_a["id"], user_b["id"]),
    )
    token_a = state.auth_store.login(
        "user-a", "Temporary-123", remote_addr="127.0.0.1", user_agent="a"
    )
    token_b = state.auth_store.login(
        "user-b", "Temporary-123", remote_addr="127.0.0.1", user_agent="b"
    )
    return state, client, admin, token_a, token_b


def _as(client: TestClient, token_and_session: tuple[str, dict]) -> None:
    token, session = token_and_session
    client.cookies.clear()
    client.cookies.set(
        "__Host-bili_session", token, domain="bili.example.test", path="/"
    )
    client.headers.update({"X-CSRF-Token": str(session["csrf_token"])})


def test_normal_users_are_isolated_and_can_export_same_bv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, admin, user_a, user_b = _setup_state(tmp_path, monkeypatch)
    try:
        _as(client, user_a)
        created_a = client.post(
            "/api/download",
            json={
                "bvids": ["BV1SAME00001"],
                "destination": "library",
                "force": True,
                "group": "越权分组",
                "owner_user_id": user_b[1]["user_id"],
            },
        )
        assert created_a.status_code == 200, created_a.text
        task_a = created_a.json()["data"][0]
        assert task_a["destination"] == "device"
        assert task_a["owner_user_id"] == user_a[1]["user_id"]

        _as(client, user_b)
        created_b = client.post(
            "/api/download",
            json={"bvids": ["BV1SAME00001"], "destination": "device"},
        )
        assert created_b.status_code == 200, created_b.text
        task_b = created_b.json()["data"][0]
        assert task_b["owner_user_id"] == user_b[1]["user_id"]
        assert task_b["id"] != task_a["id"]

        finished_a = wait_terminal(state.export_queue, task_a["id"])
        finished_b = wait_terminal(state.export_queue, task_b["id"])
        assert finished_a["status"] == "success"
        assert finished_b["status"] == "success"
        assert finished_a["source_key"] == finished_b["source_key"] == "BV1SAME00001"
        assert finished_a["_queue_key"] != finished_b["_queue_key"]

        rows = state.database.all(
            "SELECT owner_user_id,source_key FROM exports ORDER BY owner_user_id"
        )
        assert {row["owner_user_id"] for row in rows} == {
            user_a[1]["user_id"],
            user_b[1]["user_id"],
        }
        assert {row["source_key"] for row in rows} == {"BV1SAME00001"}

        _as(client, user_a)
        own = client.get("/api/tasks")
        assert own.status_code == 200
        assert {item["id"] for item in own.json()["data"]} == {task_a["id"]}
        assert client.get(f"/api/tasks/{task_b['id']}").status_code == 404
        assert client.get(f"/api/tasks/{task_b['id']}/log").status_code == 404
        assert client.post(f"/api/exports/{task_b['id']}/prepare").status_code == 404

        # Ordinary status is useful to the download page but contains no filesystem paths.
        status = client.get("/api/status")
        assert status.status_code == 200
        serialized = json.dumps(status.json(), ensure_ascii=False)
        assert "database_path" not in serialized
        assert "download_dir" not in serialized
        assert client.get("/api/search?q=test").status_code == 403
        assert client.get("/api/library").status_code == 403

        admin_token = state.auth_store.login(
            "administrator",
            "Admin-password-123",
            remote_addr="127.0.0.1",
            user_agent="admin",
        )
        _as(client, admin_token)
        all_tasks = client.get("/api/tasks?group_by_user=true")
        assert all_tasks.status_code == 200
        assert {item["id"] for item in all_tasks.json()["data"]} >= {
            task_a["id"],
            task_b["id"],
        }
        filtered = client.get(
            f"/api/tasks?owner_user_id={user_a[1]['user_id']}"
        )
        assert {item["owner_user_id"] for item in filtered.json()["data"]} == {
            user_a[1]["user_id"]
        }
        assert admin["user"]["role"] == "admin"
    finally:
        client.close()
        state.stop()


def test_owned_queue_cancel_during_preflight_is_realtime_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info_started = threading.Event()
    cancellation_seen = threading.Event()
    release = threading.Event()

    def cancellable_runner(argv, **kwargs):
        cancel_event = kwargs.get("cancel_event")
        if "--only-show-info" in argv:
            info_started.set()
            while cancel_event is not None and not cancel_event.wait(timeout=0.01):
                pass
            cancellation_seen.set()
            release.wait(timeout=2)
            return SimpleNamespace(returncode=1, stdout="预检已停止", stderr="")
        return artifact_runner()(argv)

    cancellable_runner.supports_info = True
    cancellable_runner.supports_cancel_event = True
    state, client, _admin, user_a, _user_b = _setup_state(
        tmp_path, monkeypatch, runner=cancellable_runner
    )
    try:
        _as(client, user_a)
        before = state.export_queue.change_count()
        created_response = client.post(
            "/api/download", json={"bvids": ["BV1CANCEL001"]}
        )
        assert created_response.status_code == 200, created_response.text
        task_id = created_response.json()["data"][0]["id"]
        assert info_started.wait(timeout=2)
        assert state.export_queue.change_count() > before

        cancelling = client.post(f"/api/tasks/{task_id}/cancel")
        assert cancelling.status_code == 200, cancelling.text
        snapshot = cancelling.json()["data"]
        assert snapshot["status"] == "running"
        assert snapshot["phase"] == "cancelling"
        assert snapshot["finished_at"] is None
        assert cancellation_seen.wait(timeout=1)

        repeated = client.post(f"/api/tasks/{task_id}/cancel")
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["data"]["phase"] == "cancelling"

        release.set()
        finished = wait_terminal(state.export_queue, task_id)
        assert finished["status"] == "cancelled"
        assert finished["phase"] == "cancelled"
        assert finished["finished_at"] is not None
        assert state.export_queue.change_count() > before + 1

        terminal_repeat = client.post(f"/api/tasks/{task_id}/cancel")
        assert terminal_repeat.status_code == 200, terminal_repeat.text
        assert terminal_repeat.json()["data"]["phase"] == "cancelled"
    finally:
        release.set()
        client.close()
        state.stop()


def test_task_status_summary_aggregates_five_hundred_rows_without_loading_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, _admin, user_a, user_b = _setup_state(tmp_path, monkeypatch)
    statuses = ("queued", "running", "success", "skipped", "failed", "cancelled")
    now = time.time()
    rows = []
    for index in range(500):
        owner = user_a[1]["user_id"] if index < 300 else user_b[1]["user_id"]
        status = statuses[index % len(statuses)]
        rows.append(
            (
                f"summary-{index:04d}",
                owner,
                "device",
                f"BV{index:010d}",
                status,
                now + index,
                now + index,
                '{"large":"payload-not-needed"}',
            )
        )
    try:
        with state.database.transaction() as conn:
            conn.executemany(
                "INSERT INTO task_records(id,owner_user_id,destination,source_key,status,"
                "created_at,updated_at,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                rows,
            )

        summary = state.task_store.task_status_summary()
        assert summary["all"] == 500
        assert summary["active"] == summary["queued"] + summary["running"]

        owner_summary = state.task_store.task_status_summary(user_a[1]["user_id"])
        assert owner_summary["all"] == 300
        assert sum(owner_summary[name] for name in statuses) == 300

        async def first_summary_event() -> str:
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/events",
                    "query_string": b"view=summary",
                    "headers": [],
                    "app": client.app,
                    "state": {
                        "auth_context": {
                            "user_id": user_a[1]["user_id"],
                            "role": "user",
                            "session_id": "",
                        }
                    },
                },
                receive=receive,
            )
            response = await events(request, view="summary")
            chunk = await anext(response.body_iterator)
            return chunk.decode() if isinstance(chunk, bytes) else chunk

        chunk = asyncio.run(first_summary_event())
        data_line = next(line for line in chunk.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        assert set(payload) == {"summary", "at"}
        assert payload["summary"]["all"] == 300
    finally:
        client.close()
        state.stop()


def test_normal_user_active_task_limit_is_per_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def blocking_runner(argv, **kwargs):
        del kwargs
        if "--only-show-info" in argv:
            return artifact_runner()(argv)
        release.wait(timeout=10)
        work_dir = Path(argv[argv.index("--work-dir") + 1])
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "demo.mp4").write_bytes(b"video")
        return SimpleNamespace(
            returncode=0,
            stdout="[视频] [1080P 高清] [1920x1080] [AVC] [30]\n下载视频 100%",
            stderr="",
        )

    blocking_runner.supports_info = True
    blocking_runner.supports_quality_output = True
    state, client, _admin, user_a, user_b = _setup_state(
        tmp_path, monkeypatch, runner=blocking_runner
    )
    try:
        _as(client, user_a)
        for index in range(NORMAL_USER_ACTIVE_TASK_LIMIT):
            response = client.post(
                "/api/download", json={"bvids": [f"BV1LIMIT{index:04d}"]}
            )
            assert response.status_code == 200, response.text
        rejected = client.post(
            "/api/download", json={"bvids": ["BV1LIMIT9999"]}
        )
        assert rejected.status_code == 429
        assert rejected.json()["code"] == "active_task_limit"

        _as(client, user_b)
        allowed_other_user = client.post(
            "/api/download", json={"bvids": ["BV1LIMIT9999"]}
        )
        assert allowed_other_user.status_code == 200, allowed_other_user.text
    finally:
        release.set()
        client.close()
        state.stop()


def test_discovered_selection_is_atomic_and_enforces_normal_user_quality_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def blocking_runner(argv, **kwargs):
        del kwargs
        if "--only-show-info" in argv:
            return artifact_runner()(argv)
        release.wait(timeout=10)
        work_dir = Path(argv[argv.index("--work-dir") + 1])
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "demo.mp4").write_bytes(b"video")
        return SimpleNamespace(
            returncode=0,
            stdout="[视频] [1080P 高清] [1920x1080] [AVC] [30]\n下载视频 100%",
            stderr="",
        )

    blocking_runner.supports_info = True
    blocking_runner.supports_quality_output = True
    state, client, _admin, user_a, _user_b = _setup_state(
        tmp_path, monkeypatch, runner=blocking_runner
    )
    try:
        _as(client, user_a)
        response = client.post(
            "/api/download/selection",
            json={
                "items": [
                    {"bvid": "BV1ATOMIC001", "title": "一", "preferred_quality": "720P"},
                    {"bvid": "BV1ATOMIC002", "title": "二", "preferred_quality": "4K"},
                ],
                "destination": "library",
                "min_height": 360,
            },
        )
        assert response.status_code == 200, response.text
        created = response.json()["data"]
        assert len(created) == 2
        assert {item["destination"] for item in created} == {"device"}
        assert {item["min_height"] for item in created} == {
            state.config_store.get().default_min_height
        }
        assert {item["preferred_quality"] for item in created} == {""}
        ids = {item["id"] for item in created}
        rows = state.database.all(
            "SELECT id FROM task_records WHERE id IN (?,?)",
            tuple(ids),
        )
        exports = state.database.all(
            "SELECT task_id FROM exports WHERE task_id IN (?,?)",
            tuple(ids),
        )
        assert {row["id"] for row in rows} == ids
        assert {row["task_id"] for row in exports} == ids

        before = state.database.one("SELECT COUNT(*) AS n FROM task_records")["n"]
        conflict = client.post(
            "/api/download/selection",
            json={"bvids": ["BV1ATOMIC001", "BV1ATOMIC003"]},
        )
        assert conflict.status_code == 409, conflict.text
        payload = conflict.json()
        assert payload["code"] == "batch_conflict"
        assert payload["data"]["items"] == [
            {
                "source_key": "BV1ATOMIC001",
                "code": "active_task_conflict",
                "message": "同一作品已有排队或下载中的任务",
            }
        ]
        after = state.database.one("SELECT COUNT(*) AS n FROM task_records")["n"]
        assert after == before
        assert state.database.one(
            "SELECT id FROM task_records WHERE source_key='BV1ATOMIC003'"
        ) is None
    finally:
        release.set()
        client.close()
        state.stop()


def test_discovered_selection_persistence_failure_publishes_no_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, _admin, user_a, _user_b = _setup_state(tmp_path, monkeypatch)
    try:
        _as(client, user_a)

        def fail_batch(_destination, _tasks):
            raise sqlite3.OperationalError("synthetic write failure")

        monkeypatch.setattr(state.task_store, "register_task_batch", fail_batch)
        response = client.post(
            "/api/download/selection",
            json={"bvids": ["BV1NOPUB0001", "BV1NOPUB0002"]},
        )
        assert response.status_code == 500
        assert response.json()["code"] == "batch_create_failed"
        assert state.export_queue.key_statuses(
            ["BV1NOPUB0001", "BV1NOPUB0002"],
            owner_user_id=user_a[1]["user_id"],
        ) == {}
        assert state.database.one(
            "SELECT id FROM task_records WHERE source_key IN ('BV1NOPUB0001','BV1NOPUB0002')"
        ) is None
    finally:
        client.close()
        state.stop()


def test_discovered_selection_capacity_rejects_the_whole_normal_user_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, _admin, user_a, _user_b = _setup_state(tmp_path, monkeypatch)
    try:
        _as(client, user_a)
        bvids = [f"BV1CAPA{i:05d}" for i in range(NORMAL_USER_ACTIVE_TASK_LIMIT + 1)]
        response = client.post("/api/download/selection", json={"bvids": bvids})
        assert response.status_code == 429
        body = response.json()
        assert body["code"] == "active_task_limit"
        assert body["data"]["selection_limit"] == NORMAL_USER_ACTIVE_TASK_LIMIT
        assert len(body["data"]["items"]) == len(bvids)
        assert state.database.one(
            "SELECT id FROM task_records WHERE owner_user_id=?",
            (user_a[1]["user_id"],),
        ) is None
        assert state.export_queue.active_count_for_owner(user_a[1]["user_id"]) == 0
    finally:
        client.close()
        state.stop()


def test_discovered_selection_publish_failure_rolls_back_database_and_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, _admin, user_a, _user_b = _setup_state(tmp_path, monkeypatch)
    try:
        _as(client, user_a)

        def fail_notification(_task, *, task_id=""):
            del task_id
            raise RuntimeError("synthetic publish failure")

        monkeypatch.setattr(state.export_queue, "_notify_locked", fail_notification)
        response = client.post(
            "/api/download/selection",
            json={"bvids": ["BV1PUBFAIL01", "BV1PUBFAIL02"]},
        )
        assert response.status_code == 500
        assert response.json()["code"] == "batch_create_failed"
        assert state.export_queue.key_statuses(
            ["BV1PUBFAIL01", "BV1PUBFAIL02"],
            owner_user_id=user_a[1]["user_id"],
        ) == {}
        assert state.database.one(
            "SELECT id FROM task_records WHERE source_key IN ('BV1PUBFAIL01','BV1PUBFAIL02')"
        ) is None
        assert state.database.one(
            "SELECT task_id FROM exports WHERE source_key IN ('BV1PUBFAIL01','BV1PUBFAIL02')"
        ) is None
    finally:
        client.close()
        state.stop()


def test_concurrent_discovered_selection_allows_only_one_same_owner_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    start = threading.Barrier(2)

    def blocking_runner(argv, **kwargs):
        del kwargs
        if "--only-show-info" in argv:
            return artifact_runner()(argv)
        release.wait(timeout=10)
        work_dir = Path(argv[argv.index("--work-dir") + 1])
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "demo.mp4").write_bytes(b"video")
        return SimpleNamespace(
            returncode=0,
            stdout="[视频] [1080P 高清] [1920x1080] [AVC] [30]\n下载视频 100%",
            stderr="",
        )

    blocking_runner.supports_info = True
    blocking_runner.supports_quality_output = True
    state, client_a, _admin, user_a, _user_b = _setup_state(
        tmp_path, monkeypatch, runner=blocking_runner
    )
    client_b = TestClient(client_a.app, base_url="https://bili.example.test")
    try:
        _as(client_a, user_a)
        _as(client_b, user_a)

        def submit(client):
            start.wait(timeout=5)
            return client.post(
                "/api/download/selection",
                json={"bvids": ["BV1CONCUR001", "BV1CONCUR002"]},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, (client_a, client_b)))
        assert sorted(response.status_code for response in responses) == [200, 409]
        assert sum(response.json().get("total", 0) for response in responses) == 2
        rows = state.database.all(
            "SELECT source_key,COUNT(*) AS n FROM task_records "
            "WHERE source_key IN ('BV1CONCUR001','BV1CONCUR002') GROUP BY source_key"
        )
        assert rows == [
            {"source_key": "BV1CONCUR001", "n": 1},
            {"source_key": "BV1CONCUR002", "n": 1},
        ]
    finally:
        release.set()
        client_b.close()
        client_a.close()
        state.stop()


def test_device_history_is_written_only_after_full_transfer_and_outlives_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, _admin, user_a, _user_b = _setup_state(tmp_path, monkeypatch)
    owner = user_a[1]["user_id"]
    try:
        _as(client, user_a)
        first = client.post("/api/download", json={"bvids": ["BV1HISTORY01"]})
        task_id = first.json()["data"][0]["id"]
        assert wait_terminal(state.export_queue, task_id)["status"] == "success"
        assert client.post(f"/api/exports/{task_id}/prepare").status_code == 200

        assert client.head(f"/api/exports/{task_id}/download").status_code == 200
        assert state.task_store.device_download_history_for_sources(
            owner, ["BV1HISTORY01"]
        ) == {}
        claimable_conflict = client.post(
            "/api/download/selection",
            json={"bvids": ["BV1HISTORY01", "BV1HISTORY03"]},
        )
        assert claimable_conflict.status_code == 409
        assert claimable_conflict.json()["data"]["items"][0]["code"] == "claimable_export"
        assert state.database.one(
            "SELECT id FROM task_records WHERE source_key='BV1HISTORY03'"
        ) is None
        assert client.get(f"/api/exports/{task_id}/download").content == b"video"
        history = state.task_store.device_download_history_for_sources(
            owner, ["BV1HISTORY01"]
        )
        assert set(history) == {"BV1HISTORY01"}

        deleted = client.post(
            f"/api/enhancements/tasks/{task_id}/delete", json={}
        )
        assert deleted.status_code == 200, deleted.text
        assert state.task_store.task_record(task_id) is None
        assert set(
            state.task_store.device_download_history_for_sources(
                owner, ["BV1HISTORY01"]
            )
        ) == {"BV1HISTORY01"}

        second = client.post("/api/download", json={"bvids": ["BV1HISTORY02"]})
        second_id = second.json()["data"][0]["id"]
        assert wait_terminal(state.export_queue, second_id)["status"] == "success"
        assert client.post(f"/api/exports/{second_id}/prepare").status_code == 200
        assert client.delete(f"/api/exports/{second_id}").status_code == 200
        assert state.task_store.device_download_history_for_sources(
            owner, ["BV1HISTORY02"]
        ) == {}
    finally:
        client.close()
        state.stop()


def test_cleanup_retry_preserves_delivery_fact_and_never_invents_discard_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, _admin, user_a, _user_b = _setup_state(tmp_path, monkeypatch)
    owner = user_a[1]["user_id"]
    original_cleanup = state.task_store._cleanup_export_files
    try:
        _as(client, user_a)
        delivered = client.post("/api/download", json={"bvids": ["BV1CLEANUP01"]})
        delivered_id = delivered.json()["data"][0]["id"]
        assert wait_terminal(state.export_queue, delivered_id)["status"] == "success"
        assert client.post(f"/api/exports/{delivered_id}/prepare").status_code == 200
        monkeypatch.setattr(
            state.task_store,
            "_cleanup_export_files",
            lambda _row: ["synthetic cleanup failure"],
        )
        assert client.get(f"/api/exports/{delivered_id}/download").content == b"video"
        pending = state.task_store.export_record(delivered_id)
        assert pending["state"] == "cleanup_pending"
        assert pending["cleanup_target_state"] == "downloaded"
        first_history = state.task_store.device_download_history_for_sources(
            owner, ["BV1CLEANUP01"]
        )["BV1CLEANUP01"]

        monkeypatch.setattr(state.task_store, "_cleanup_export_files", original_cleanup)
        state.task_store.retry_export_cleanup(delivered_id)
        completed = state.task_store.export_record(delivered_id)
        assert completed["state"] == "downloaded"
        assert completed["cleanup_target_state"] == ""
        assert state.task_store.device_download_history_for_sources(
            owner, ["BV1CLEANUP01"]
        )["BV1CLEANUP01"] == first_history

        discarded = client.post("/api/download", json={"bvids": ["BV1CLEANUP02"]})
        discarded_id = discarded.json()["data"][0]["id"]
        assert wait_terminal(state.export_queue, discarded_id)["status"] == "success"
        assert client.post(f"/api/exports/{discarded_id}/prepare").status_code == 200
        monkeypatch.setattr(
            state.task_store,
            "_cleanup_export_files",
            lambda _row: ["synthetic cleanup failure"],
        )
        assert client.delete(f"/api/exports/{discarded_id}").status_code == 200
        discard_pending = state.task_store.export_record(discarded_id)
        assert discard_pending["state"] == "cleanup_pending"
        assert discard_pending["cleanup_target_state"] == "discarded"
        assert state.task_store.device_download_history_for_sources(
            owner, ["BV1CLEANUP02"]
        ) == {}

        monkeypatch.setattr(state.task_store, "_cleanup_export_files", original_cleanup)
        state.task_store.retry_export_cleanup(discarded_id)
        assert state.task_store.export_record(discarded_id)["state"] == "discarded"
        assert state.task_store.device_download_history_for_sources(
            owner, ["BV1CLEANUP02"]
        ) == {}
    finally:
        client.close()
        state.stop()


def test_creator_discovery_role_boundary_and_normal_user_response_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, _admin, user_a, _user_b = _setup_state(tmp_path, monkeypatch)

    def fake_profile(uid: str, **_kwargs):
        return {
            "uid": uid,
            "name": "公开UP",
            "avatar": "https://evil.example/avatar.jpg",
            "bio": "公开简介",
            "followers": 10,
            "submission_count": 1,
            "profile_url": f"https://space.bilibili.com/{uid}",
            "cached": False,
        }

    def fake_submissions(uid: str, **kwargs):
        return {
            "uid": uid,
            "order": kwargs.get("order", "pubdate"),
            "page": kwargs.get("page", 1),
            "pages": 1,
            "total": 1,
            "page_size": 20,
            "cached": False,
            "items": [
                {
                    "bvid": "BV1ROLEAPI01",
                    "title": "公开投稿",
                    "author": "公开UP",
                    "cover": "https://i0.hdslb.com/bfs/cover/test.jpg",
                    "url": "https://www.bilibili.com/video/BV1ROLEAPI01",
                    "play": 1,
                    "duration": "00:01",
                    "pubdate": 1,
                }
            ],
        }

    monkeypatch.setattr("app.routes.creator_profile", fake_profile)
    monkeypatch.setattr("app.routes.creator_submissions", fake_submissions)
    monkeypatch.setattr(
        "app.routes.search_creators",
        lambda q, **_kwargs: {
            "keyword": q,
            "page": 1,
            "pages": 1,
            "total": 1,
            "page_size": 20,
            "cached": False,
            "items": [{"uid": "123456", "name": "公开UP", "avatar": ""}],
        },
    )
    try:
        _as(client, user_a)
        assert client.get(
            "/api/bilibili/creators/search", params={"q": "公开UP"}
        ).status_code == 403
        invalid = client.get(
            "/api/bilibili/creators/resolve", params={"locator": "公开UP"}
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "invalid_creator_locator"

        resolved = client.get(
            "/api/bilibili/creators/resolve",
            params={"locator": "https://space.bilibili.com/123456", "destination": "library"},
        )
        assert resolved.status_code == 200, resolved.text
        data = resolved.json()["data"]
        assert data["state"] == "ready"
        assert data["creator"]["avatar"] == ""
        submissions = data["submissions"]
        assert submissions["destination"] == "device"
        assert submissions["limits"]["selection"] == NORMAL_USER_ACTIVE_TASK_LIMIT
        item = submissions["items"][0]
        assert item["local_status"] == "not_downloaded"
        assert "tags" not in item
        assert "output_path" not in item
        assert "deleted_record" not in item

        next_page = client.get(
            "/api/bilibili/creators/123456/submissions",
            params={"page": 1, "order": "click", "destination": "library"},
        )
        assert next_page.status_code == 200
        assert next_page.json()["data"]["destination"] == "device"

        preview = client.post(
            "/api/preview",
            json={
                "item": {
                    "bvid": "BV1ROLEAPI01",
                    "preferred_quality": "720P",
                },
                "min_height": 360,
                "preferred_quality": "720P",
            },
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["data"]["min_height"] == state.config_store.get().default_min_height
        assert preview.json()["data"]["preferred_quality"] == ""

        admin_token = state.auth_store.login(
            "administrator",
            "Admin-password-123",
            remote_addr="127.0.0.1",
            user_agent="admin",
        )
        _as(client, admin_token)
        candidates = client.get(
            "/api/bilibili/creators/search", params={"q": "公开UP"}
        )
        assert candidates.status_code == 200
        assert candidates.json()["data"]["items"][0]["uid"] == "123456"
    finally:
        client.close()
        state.stop()


def test_task_retention_is_per_user_and_preserves_active_and_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, client, admin, user_a, user_b = _setup_state(tmp_path, monkeypatch)
    try:
        now = time.time()
        owner_a = user_a[1]["user_id"]
        owner_b = user_b[1]["user_id"]
        admin_id = admin["user"]["id"]
        for index in range(NORMAL_USER_TASK_HISTORY_LIMIT + 1):
            finished = now - index
            state.task_store.save_task_snapshot(
                "device",
                f"a-{index:03d}",
                {
                    "id": f"a-{index:03d}",
                    "owner_user_id": owner_a,
                    "key": f"A{index}",
                    "status": "success",
                    "created_at": finished - 1,
                    "finished_at": finished,
                },
            )
        state.task_store.save_task_snapshot(
            "device",
            "a-old",
            {
                "id": "a-old",
                "owner_user_id": owner_b,
                "key": "OLD",
                "status": "failed",
                "created_at": now - 9 * 86400,
                "finished_at": now - 8 * 86400,
            },
        )
        state.task_store.save_task_snapshot(
            "device",
            "a-recent",
            {
                "id": "a-recent",
                "owner_user_id": owner_b,
                "key": "RECENT",
                "status": "failed",
                "created_at": now - 7 * 86400,
                "finished_at": now - (6 * 86400 + 23 * 3600),
            },
        )
        state.task_store.save_task_snapshot(
            "device",
            "a-active",
            {
                "id": "a-active",
                "owner_user_id": owner_a,
                "key": "ACTIVE",
                "status": "queued",
                "created_at": now - 30 * 86400,
            },
        )
        state.task_store.save_task_snapshot(
            "device",
            "b-keep",
            {
                "id": "b-keep",
                "owner_user_id": owner_b,
                "key": "B",
                "status": "success",
                "created_at": now - 1,
                "finished_at": now,
            },
        )
        for index in range(ADMIN_TASK_HISTORY_LIMIT + 1):
            state.task_store.save_task_snapshot(
                "library",
                f"admin-{index:03d}",
                {
                    "id": f"admin-{index:03d}",
                    "owner_user_id": admin_id,
                    "key": f"ADMIN{index}",
                    "status": "success",
                    "created_at": now - index,
                    "finished_at": now - index,
                },
            )

        state.task_store.cleanup_task_history(now=now)
        a_terminal = state.database.one(
            "SELECT COUNT(*) AS n FROM task_records WHERE owner_user_id=? "
            "AND status IN ('success','skipped','failed','cancelled')",
            (owner_a,),
        )
        assert int(a_terminal["n"]) == NORMAL_USER_TASK_HISTORY_LIMIT
        assert state.task_store.task_record("a-old") is None
        assert state.task_store.task_record("a-recent") is not None
        assert state.task_store.task_record("a-active") is not None
        assert state.task_store.task_record("b-keep") is not None
        admin_count = state.database.one(
            "SELECT COUNT(*) AS n FROM task_records WHERE owner_user_id=?",
            (admin_id,),
        )
        assert int(admin_count["n"]) == ADMIN_TASK_HISTORY_LIMIT
    finally:
        client.close()
        state.stop()


def _runtime(root: Path) -> RuntimeSettings:
    for name in ("config", "media", "cache", "tmp", "bbdown", "userdata"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return RuntimeSettings(
        mode="server",
        config_dir=root / "config",
        media_dir=root / "media",
        cache_dir=root / "cache",
        temp_dir=root / "tmp",
        database_path=root / "userdata" / "bili_workspace.db",
        bbdown_dir=root / "bbdown",
        host="0.0.0.0",
        port=3398,
        public_base_url="",
        trusted_hosts=("testserver",),
        trusted_proxy_ips=("127.0.0.1",),
        allow_ip_hosts=True,
        auth_required=True,
        cookie_secure=False,
        hsts_enabled=False,
        export_ttl_sec=86400,
        min_free_bytes=0,
        download_concurrency=1,
        transcode_threads=0,
    )


def test_v3_to_v4_migration_assigns_admin_without_revoking_sessions(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    conn = sqlite3.connect(runtime.database_path)
    now = time.time()
    try:
        conn.executescript(
            """
            CREATE TABLE users(
              id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
              disabled INTEGER NOT NULL DEFAULT 0, role TEXT NOT NULL DEFAULT 'user',
              display_name TEXT NOT NULL DEFAULT '', must_change_password INTEGER NOT NULL DEFAULT 0,
              created_by TEXT, last_login_at REAL
            );
            CREATE TABLE sessions(
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              token_hash TEXT NOT NULL UNIQUE, csrf_token TEXT NOT NULL, created_at REAL NOT NULL,
              expires_at REAL NOT NULL, last_seen_at REAL NOT NULL,
              user_agent TEXT NOT NULL DEFAULT '', remote_addr TEXT NOT NULL DEFAULT '',
              revoked_at REAL, revoke_reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE task_snapshots(
              task_id TEXT PRIMARY KEY, destination TEXT NOT NULL, status TEXT NOT NULL,
              created_at REAL NOT NULL, updated_at REAL NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE exports(
              task_id TEXT PRIMARY KEY, source_key TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
              state TEXT NOT NULL, relative_path TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL DEFAULT '',
              size INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, expires_at REAL NOT NULL,
              downloaded_at REAL, error TEXT NOT NULL DEFAULT '', task_payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        conn.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,0,'admin','管理员',0,NULL,NULL)",
            ("legacy-admin", "legacyadmin", hash_password("LegacyPass123"), now, now),
        )
        conn.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,NULL,'')",
            (
                "legacy-session",
                "legacy-admin",
                "legacy-token-hash",
                "legacy-csrf",
                now,
                now + 3600,
                now,
                "agent",
                "127.0.0.1",
            ),
        )
        payload = {
            "id": "legacy-task",
            "key": "BV1LEGACY001",
            "status": "success",
            "created_at": now,
            "finished_at": now,
        }
        conn.execute(
            "INSERT INTO task_snapshots VALUES(?,?,?,?,?,?)",
            (
                "legacy-task",
                "device",
                "success",
                now,
                now,
                json.dumps(payload),
            ),
        )
        conn.execute(
            "INSERT INTO exports VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-task",
                "BV1LEGACY001",
                "legacy",
                "failed",
                "",
                "",
                0,
                now,
                now + 3600,
                None,
                "",
                json.dumps(payload),
            ),
        )
        conn.execute("PRAGMA user_version=3")
        conn.commit()
    finally:
        conn.close()

    database = Database(runtime)
    try:
        assert database.migration_backup_path is not None
        with sqlite3.connect(runtime.database_path) as upgraded:
            assert upgraded.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
            assert upgraded.execute("PRAGMA foreign_key_check").fetchall() == []
            session = upgraded.execute(
                "SELECT revoked_at FROM sessions WHERE id='legacy-session'"
            ).fetchone()
            assert session == (None,)
            assert upgraded.execute(
                "SELECT owner_user_id FROM task_records WHERE id='legacy-task'"
            ).fetchone() == ("legacy-admin",)
            assert upgraded.execute(
                "SELECT owner_user_id FROM exports WHERE task_id='legacy-task'"
            ).fetchone() == ("legacy-admin",)
    finally:
        database.close()
