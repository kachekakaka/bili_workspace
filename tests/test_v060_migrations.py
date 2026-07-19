from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from app.constants import DATABASE_SCHEMA_VERSION
from app.index_store import IndexStore
from app.nas import NasStore, _hash_password
from app.runtime import RuntimeSettings


def _runtime(root: Path, *, mode: str = "server") -> RuntimeSettings:
    for name in ("config", "media", "cache", "tmp", "bbdown", "userdata"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return RuntimeSettings(
        mode=mode,
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


def _create_v2_database(path: Path, *, invalid_session_fk: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    user_id = "legacy-user"
    conn = sqlite3.connect(path)
    try:
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
            """
        )
        now = time.time()
        conn.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,0)",
            (user_id, "legacyadmin", _hash_password("LegacyPass123"), now, now),
        )
        conn.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "legacy-session",
                "missing-user" if invalid_session_fk else user_id,
                "legacy-token-hash",
                "legacy-csrf",
                now,
                now + 3600,
                now,
                "legacy-agent",
                "127.0.0.1",
            ),
        )
        conn.execute("PRAGMA user_version=2")
        conn.commit()
    finally:
        conn.close()
    return user_id


def test_v2_upgrade_creates_backup_preserves_password_and_revokes_old_sessions(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    user_id = _create_v2_database(runtime.database_path)
    store = NasStore(runtime, IndexStore(runtime.media_dir))
    try:
        assert store.migration_backup_path is not None
        with sqlite3.connect(store.migration_backup_path) as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
            assert backup.execute(
                "SELECT username FROM users WHERE id=?", (user_id,)
            ).fetchone() == ("legacyadmin",)
            assert backup.execute(
                "SELECT user_id FROM sessions WHERE id='legacy-session'"
            ).fetchone() == (user_id,)
        version = store._one("PRAGMA user_version")
        assert version is not None
        with sqlite3.connect(runtime.database_path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            assert {
                "role",
                "display_name",
                "must_change_password",
                "created_by",
                "last_login_at",
            } <= columns
            session = conn.execute(
                "SELECT revoked_at,revoke_reason FROM sessions WHERE id='legacy-session'"
            ).fetchone()
            assert session and session[0] is not None
            assert session[1] == "schema_upgrade"
        user = store._one("SELECT * FROM users WHERE id=?", (user_id,))
        assert user and user["role"] == "admin"
        assert user["display_name"] == "管理员"
        token, session = store.login(
            "legacyadmin",
            "LegacyPass123",
            remote_addr="127.0.0.1",
            user_agent="upgrade-test",
        )
        assert token
        assert session["user_id"] == user_id
    finally:
        store.close()


def test_failed_migration_rolls_back_original_database(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _create_v2_database(runtime.database_path, invalid_session_fk=True)
    with pytest.raises(sqlite3.IntegrityError, match="外键"):
        NasStore(runtime, IndexStore(runtime.media_dir))

    with sqlite3.connect(runtime.database_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        assert "role" not in columns
    backups = list((runtime.database_path.parent / "backups").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
        assert backup.execute(
            "SELECT user_id FROM sessions WHERE id='legacy-session'"
        ).fetchone() == ("missing-user",)


def test_corrupt_database_is_not_silently_replaced(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    payload = b"not-a-sqlite-database"
    runtime.database_path.write_bytes(payload)
    with pytest.raises(sqlite3.DatabaseError):
        NasStore(runtime, IndexStore(runtime.media_dir))
    assert runtime.database_path.read_bytes() == payload


def test_only_three_recent_migration_backups_are_retained(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    store = NasStore(runtime, IndexStore(runtime.media_dir))
    try:
        backup_dir = runtime.database_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for index in range(5):
            path = backup_dir / f"bili_workspace-v2-20260719-00000{index}.db"
            shutil.copy2(runtime.database_path, path)
            stamp = time.time() + index
            path.touch()
            path.chmod(0o600)
            # Force deterministic mtimes despite fast filesystems.
            import os

            os.utime(path, (stamp, stamp))
        store._prune_migration_backups()
        remaining = sorted(backup_dir.glob("*.db"))
        assert len(remaining) == 3
        assert {item.name[-4] for item in remaining} == {"2", "3", "4"}
    finally:
        store.close()


def test_newer_schema_is_rejected_without_downgrade_or_backup(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(runtime.database_path) as conn:
        conn.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker(value) VALUES('future')")
        conn.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION + 1}")
        conn.commit()

    with pytest.raises(RuntimeError, match="高于当前程序支持"):
        NasStore(runtime, IndexStore(runtime.media_dir))

    with sqlite3.connect(runtime.database_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION + 1
        assert conn.execute("SELECT value FROM marker").fetchone() == ("future",)
    assert not (runtime.database_path.parent / "backups").exists()
