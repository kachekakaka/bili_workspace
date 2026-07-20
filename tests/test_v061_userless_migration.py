from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from app.constants import DATABASE_SCHEMA_VERSION
from app.index_store import IndexStore
from app.migration_safe_task_store import MigrationSafeTaskOwnershipNasStore
from app.runtime import RuntimeSettings


def _local_runtime(root: Path) -> RuntimeSettings:
    for name in ("config", "media", "cache", "tmp", "bbdown", "userdata"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return RuntimeSettings(
        mode="local",
        config_dir=root / "config",
        media_dir=root / "media",
        cache_dir=root / "cache",
        temp_dir=root / "tmp",
        database_path=root / "userdata" / "bili_workspace.db",
        bbdown_dir=root / "bbdown",
        host="127.0.0.1",
        port=3398,
        public_base_url="",
        trusted_hosts=("127.0.0.1", "localhost", "testserver"),
        trusted_proxy_ips=("127.0.0.1",),
        allow_ip_hosts=False,
        auth_required=True,
        cookie_secure=False,
        hsts_enabled=False,
        export_ttl_sec=86400,
        min_free_bytes=0,
        download_concurrency=1,
        transcode_threads=0,
    )


def _create_userless_v2_database(path: Path) -> dict[str, object]:
    now = time.time()
    payload: dict[str, object] = {
        "id": "legacy-local-task",
        "key": "BV1LOCAL0001",
        "title": "旧版本机任务",
        "status": "success",
        "created_at": now,
        "finished_at": now,
    }
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE users(
              id TEXT PRIMARY KEY,
              username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              disabled INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE sessions(
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              token_hash TEXT NOT NULL UNIQUE,
              csrf_token TEXT NOT NULL,
              created_at REAL NOT NULL,
              expires_at REAL NOT NULL,
              last_seen_at REAL NOT NULL,
              user_agent TEXT NOT NULL DEFAULT '',
              remote_addr TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE task_snapshots(
              task_id TEXT PRIMARY KEY,
              destination TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE exports(
              task_id TEXT PRIMARY KEY,
              source_key TEXT NOT NULL,
              title TEXT NOT NULL DEFAULT '',
              state TEXT NOT NULL,
              relative_path TEXT NOT NULL DEFAULT '',
              filename TEXT NOT NULL DEFAULT '',
              size INTEGER NOT NULL DEFAULT 0,
              created_at REAL NOT NULL,
              expires_at REAL NOT NULL,
              downloaded_at REAL,
              error TEXT NOT NULL DEFAULT '',
              task_payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        encoded = json.dumps(payload, ensure_ascii=False)
        conn.execute(
            "INSERT INTO task_snapshots VALUES(?,?,?,?,?,?)",
            (payload["id"], "device", "success", now, now, encoded),
        )
        conn.execute(
            "INSERT INTO exports VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["id"],
                payload["key"],
                payload["title"],
                "failed",
                "",
                "",
                0,
                now,
                now + 3600,
                None,
                "",
                encoded,
            ),
        )
        conn.execute("PRAGMA user_version=2")
        conn.commit()
    return payload


def test_userless_v2_local_database_creates_admin_and_migrates_ownership(
    tmp_path: Path,
) -> None:
    runtime = _local_runtime(tmp_path)
    payload = _create_userless_v2_database(runtime.database_path)

    store = MigrationSafeTaskOwnershipNasStore(runtime, IndexStore(runtime.media_dir))
    try:
        assert store.migration_backup_path is not None
        with sqlite3.connect(store.migration_backup_path) as backup:
            assert backup.execute("PRAGMA user_version").fetchone() == (2,)
            assert backup.execute("SELECT COUNT(*) FROM users").fetchone() == (0,)

        with sqlite3.connect(runtime.database_path) as upgraded:
            upgraded.row_factory = sqlite3.Row
            assert (
                upgraded.execute("PRAGMA user_version").fetchone()[0]
                == DATABASE_SCHEMA_VERSION
            )
            assert upgraded.execute("PRAGMA foreign_key_check").fetchall() == []
            admin = upgraded.execute(
                "SELECT id,username,role,display_name,must_change_password,created_by "
                "FROM users"
            ).fetchone()
            assert admin is not None
            assert admin["username"] == "admin"
            assert admin["role"] == "admin"
            assert admin["display_name"] == "管理员"
            assert admin["must_change_password"] == 1
            assert admin["created_by"] == "system-default-admin"
            assert (
                upgraded.execute(
                    "SELECT owner_user_id FROM task_records WHERE id=?",
                    (payload["id"],),
                ).fetchone()[0]
                == admin["id"]
            )
            assert (
                upgraded.execute(
                    "SELECT owner_user_id FROM exports WHERE task_id=?",
                    (payload["id"],),
                ).fetchone()[0]
                == admin["id"]
            )
            assert (
                upgraded.execute(
                    "SELECT COUNT(*) FROM audit_log "
                    "WHERE user_id=? AND action='auth.default_admin.create'",
                    (admin["id"],),
                ).fetchone()[0]
                == 1
            )

        token, session = store.login(
            "admin",
            "123456",
            remote_addr="127.0.0.1",
            user_agent="legacy-local-upgrade",
        )
        assert token
        assert session["must_change_password"] is True
    finally:
        store.close()
