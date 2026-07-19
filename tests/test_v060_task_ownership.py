from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.constants import (
    ADMIN_TASK_HISTORY_LIMIT,
    DATABASE_SCHEMA_VERSION,
    NORMAL_USER_ACTIVE_TASK_LIMIT,
    NORMAL_USER_TASK_HISTORY_LIMIT,
)
from app.index_store import IndexStore
from app.main import create_app
from app.nas import _hash_password
from app.runtime import RuntimeSettings
from app.state import AppState
from app.task_ownership_store import TaskOwnershipNasStore
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
    user_a = state.nas.create_user(
        "user-a", "用户甲", "Temporary-123", created_by=admin["user"]["id"]
    )
    user_b = state.nas.create_user(
        "user-b", "用户乙", "Temporary-123", created_by=admin["user"]["id"]
    )
    state.nas._execute(
        "UPDATE users SET must_change_password=0 WHERE id IN (?,?)",
        (user_a["id"], user_b["id"]),
    )
    token_a = state.nas.login(
        "user-a", "Temporary-123", remote_addr="127.0.0.1", user_agent="a"
    )
    token_b = state.nas.login(
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

        rows = state.nas._all(
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

        admin_token = state.nas.login(
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
            state.nas.save_task_snapshot(
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
        state.nas.save_task_snapshot(
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
        state.nas.save_task_snapshot(
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
        state.nas.save_task_snapshot(
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
        state.nas.save_task_snapshot(
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
            state.nas.save_task_snapshot(
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

        state.nas.cleanup_task_history(now=now)
        a_terminal = state.nas._one(
            "SELECT COUNT(*) AS n FROM task_records WHERE owner_user_id=? "
            "AND status IN ('success','skipped','failed','cancelled')",
            (owner_a,),
        )
        assert int(a_terminal["n"]) == NORMAL_USER_TASK_HISTORY_LIMIT
        assert state.nas.task_record("a-old") is None
        assert state.nas.task_record("a-recent") is not None
        assert state.nas.task_record("a-active") is not None
        assert state.nas.task_record("b-keep") is not None
        admin_count = state.nas._one(
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
            ("legacy-admin", "legacyadmin", _hash_password("LegacyPass123"), now, now),
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

    store = TaskOwnershipNasStore(runtime, IndexStore(runtime.media_dir))
    try:
        assert store.migration_backup_path is not None
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
        store.close()
