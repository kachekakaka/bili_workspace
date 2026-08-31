from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.auth import ROLE_ADMIN, ROLE_USER, hash_password
from app.constants import DATABASE_SCHEMA_VERSION
from app.io_utils import _is_reparse_point, _path_exists
from app.runtime import RuntimeSettings

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "123456"
DEFAULT_ADMIN_DISPLAY_NAME = "管理员"
SYSTEM_DEFAULT_ADMIN = "system-default-admin"

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 disabled INTEGER NOT NULL DEFAULT 0,
 role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin','user')),
 display_name TEXT NOT NULL DEFAULT '', must_change_password INTEGER NOT NULL DEFAULT 0,
 created_by TEXT, last_login_at REAL
);
CREATE TABLE IF NOT EXISTS sessions(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, csrf_token TEXT NOT NULL, created_at REAL NOT NULL,
 expires_at REAL NOT NULL, last_seen_at REAL NOT NULL,
 user_agent TEXT NOT NULL DEFAULT '', remote_addr TEXT NOT NULL DEFAULT '',
 revoked_at REAL, revoke_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS groups(
 id TEXT PRIMARY KEY, display_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 folder_key TEXT NOT NULL UNIQUE COLLATE NOCASE, sort_order INTEGER NOT NULL DEFAULT 0,
 archived INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS media(
 id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, bvid TEXT,
 source_url TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
 cover TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '', pubdate INTEGER,
 duration_text TEXT NOT NULL DEFAULT '', group_id TEXT REFERENCES groups(id) ON DELETE SET NULL,
 output_path TEXT NOT NULL, min_height INTEGER NOT NULL DEFAULT 0,
 preferred_quality TEXT NOT NULL DEFAULT '', selected_quality TEXT NOT NULL DEFAULT '',
 selected_resolution TEXT NOT NULL DEFAULT '', selected_codec TEXT NOT NULL DEFAULT '',
 selected_fps TEXT NOT NULL DEFAULT '', selected_height INTEGER,
 total_size INTEGER NOT NULL DEFAULT 0, downloaded_at REAL NOT NULL, updated_at REAL NOT NULL,
 index_fingerprint TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_media_group ON media(group_id,downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_title ON media(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_media_downloaded ON media(downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_quality ON media(selected_height,selected_codec);
CREATE TABLE IF NOT EXISTS media_files(
 id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
 storage TEXT NOT NULL DEFAULT 'media', relative_path TEXT NOT NULL, filename TEXT NOT NULL,
 size INTEGER NOT NULL, mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
 kind TEXT NOT NULL DEFAULT 'media', is_primary INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, UNIQUE(storage,relative_path)
);
CREATE INDEX IF NOT EXISTS idx_media_files_media ON media_files(media_id,is_primary DESC,filename);
CREATE TABLE IF NOT EXISTS watch_progress(
 user_id TEXT NOT NULL, media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
 position_sec REAL NOT NULL DEFAULT 0, duration_sec REAL NOT NULL DEFAULT 0,
 completed INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
 PRIMARY KEY(user_id,media_id,file_id)
);
CREATE TABLE IF NOT EXISTS exports(
 task_id TEXT PRIMARY KEY, owner_user_id TEXT, source_key TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, relative_path TEXT NOT NULL DEFAULT '',
 filename TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, expires_at REAL NOT NULL, downloaded_at REAL,
 error TEXT NOT NULL DEFAULT '', task_payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_exports_expiry ON exports(state,expires_at);
CREATE TABLE IF NOT EXISTS transcodes(
 id TEXT PRIMARY KEY, media_id TEXT NOT NULL, source_file_id TEXT NOT NULL,
 output_file_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
 progress_message TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 created_at REAL NOT NULL, started_at REAL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_transcodes_media ON transcodes(media_id,created_at DESC);
CREATE TABLE IF NOT EXISTS task_snapshots(
 task_id TEXT PRIMARY KEY, destination TEXT NOT NULL, status TEXT NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_updated ON task_snapshots(updated_at DESC);
CREATE TABLE IF NOT EXISTS task_records(
 id TEXT PRIMARY KEY,
 owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 destination TEXT NOT NULL CHECK(destination IN ('library','device')),
 source_key TEXT NOT NULL DEFAULT '', bvid TEXT, title TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL, created_at REAL NOT NULL, started_at REAL, finished_at REAL,
 updated_at REAL NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '', remote_addr TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
 session_id TEXT, target_user_id TEXT
);
CREATE TABLE IF NOT EXISTS tag_definitions(
 name TEXT PRIMARY KEY COLLATE NOCASE, color TEXT NOT NULL DEFAULT '#64748b',
 sort_order INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
 updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS item_tags(
 source_key TEXT NOT NULL,
 tag TEXT NOT NULL COLLATE NOCASE REFERENCES tag_definitions(name) ON DELETE CASCADE,
 created_at REAL NOT NULL, PRIMARY KEY(source_key,tag)
);
CREATE INDEX IF NOT EXISTS idx_item_tags_tag ON item_tags(tag,source_key);
CREATE TABLE IF NOT EXISTS deleted_media(
 source_key TEXT PRIMARY KEY, bvid TEXT, source_url TEXT NOT NULL DEFAULT '',
 title TEXT NOT NULL DEFAULT '', cover TEXT NOT NULL DEFAULT '',
 author TEXT NOT NULL DEFAULT '', pubdate INTEGER,
 duration_text TEXT NOT NULL DEFAULT '', group_name TEXT NOT NULL DEFAULT '',
 deleted_at REAL NOT NULL, files_deleted INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_deleted_media_deleted_at ON deleted_media(deleted_at DESC);
"""


def duration_seconds(value: Any) -> int:
    text = str(value or "").split("·", 1)[0].strip()
    if not text:
        return 0
    try:
        parts = [int(part.strip()) for part in text.split(":")]
    except (TypeError, ValueError):
        return 0
    if len(parts) == 2:
        minutes, seconds = parts
        return max(0, minutes * 60 + seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return max(0, hours * 3600 + minutes * 60 + seconds)
    return 0


class Database:
    """Concrete owner of the application's SQLite connection and schema."""

    def __init__(self, runtime: RuntimeSettings) -> None:
        self.runtime = runtime
        self.path = runtime.database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._transaction_state = threading.local()
        old_version, had_existing, backup_path = self._prepare_migration_backup()
        self.migration_backup_path = backup_path
        self.connection = sqlite3.connect(
            self.path,
            timeout=30,
            check_same_thread=False,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        try:
            with self.lock:
                self.connection.execute("PRAGMA foreign_keys=ON")
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA synchronous=NORMAL")
                self.connection.execute("PRAGMA busy_timeout=30000")
                try:
                    self.connection.create_function(
                        "bili_duration_seconds",
                        1,
                        duration_seconds,
                        deterministic=True,
                    )
                except TypeError:  # pragma: no cover - older sqlite bindings
                    self.connection.create_function(
                        "bili_duration_seconds", 1, duration_seconds
                    )
                self._migrate_locked(old_version, had_existing)
                if backup_path is not None:
                    self._prune_migration_backups()
        except Exception:
            self.connection.close()
            raise

    def _prepare_migration_backup(self) -> tuple[int, bool, Path | None]:
        had_existing = self.path.exists() and self.path.stat().st_size > 0
        if not had_existing:
            return 0, False, None
        source = sqlite3.connect(self.path, timeout=30)
        try:
            check = source.execute("PRAGMA quick_check").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise sqlite3.DatabaseError("SQLite 数据库完整性检查失败")
            old_version = int(source.execute("PRAGMA user_version").fetchone()[0])
            if old_version > DATABASE_SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库 schema v{old_version} 高于当前程序支持的 "
                    f"v{DATABASE_SCHEMA_VERSION}，请使用匹配或更新版本的程序"
                )
            if old_version == DATABASE_SCHEMA_VERSION:
                return old_version, True, None
            backup_dir = self.path.parent / "backups"
            if _path_exists(backup_dir) and (
                backup_dir.is_symlink()
                or _is_reparse_point(backup_dir)
                or not backup_dir.is_dir()
            ):
                raise RuntimeError("SQLite 迁移备份目录类型无效")
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            backup_path = backup_dir / f"bili_workspace-v{old_version}-{stamp}.db"
            target: sqlite3.Connection | None = None
            created = False
            try:
                backup_path.open("xb").close()
                created = True
                target = sqlite3.connect(backup_path)
                source.backup(target)
                target.execute("PRAGMA wal_checkpoint(FULL)")
            except Exception as exc:
                if target is not None:
                    target.close()
                    target = None
                if created:
                    if (
                        not backup_path.is_file()
                        or backup_path.is_symlink()
                        or _is_reparse_point(backup_path)
                    ):
                        raise RuntimeError(
                            "SQLite 迁移备份文件类型异常，拒绝清理"
                        ) from exc
                    backup_path.unlink()
                raise
            finally:
                if target is not None:
                    try:
                        target.close()
                    except sqlite3.Error:
                        pass
            try:
                backup_path.chmod(0o600)
            except OSError:
                pass
            return old_version, True, backup_path
        finally:
            source.close()

    def _prune_migration_backups(self) -> None:
        backup_dir = self.path.parent / "backups"
        candidates = list(backup_dir.glob("bili_workspace-v*.db"))
        if any(
            not candidate.is_file()
            or candidate.is_symlink()
            or _is_reparse_point(candidate)
            for candidate in candidates
        ):
            raise RuntimeError("SQLite 迁移备份目录包含异常文件类型")
        backups = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in backups[3:]:
            stale.unlink(missing_ok=True)

    def _apply_schema_locked(self) -> None:
        for statement in SCHEMA.split(";"):
            sql = statement.strip()
            if sql:
                self.connection.execute(sql)

    def _columns_locked(self, table: str) -> set[str]:
        return {
            str(row[1])
            for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _add_column_locked(self, table: str, column: str, definition: str) -> None:
        if column not in self._columns_locked(table):
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def _admin_user_id_locked(self, *, create_local: bool) -> str:
        row = self.connection.execute(
            "SELECT id FROM users WHERE role=? ORDER BY disabled ASC,created_at,id LIMIT 1",
            (ROLE_ADMIN,),
        ).fetchone()
        if row:
            return str(row[0])
        if (
            not create_local
            or self.runtime.mode != "local"
            or self.connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        ):
            return ""
        now = time.time()
        user_id = "usr_" + uuid.uuid4().hex[:24]
        self.connection.execute(
            "INSERT INTO users(id,username,password_hash,created_at,updated_at,disabled,"
            "role,display_name,must_change_password,created_by) "
            "VALUES(?,?,?,?,?,0,?,?,?,?)",
            (
                user_id,
                DEFAULT_ADMIN_USERNAME,
                hash_password(DEFAULT_ADMIN_PASSWORD, allow_default_temp=True),
                now,
                now,
                ROLE_ADMIN,
                DEFAULT_ADMIN_DISPLAY_NAME,
                1,
                SYSTEM_DEFAULT_ADMIN,
            ),
        )
        self.connection.execute(
            "UPDATE watch_progress SET user_id=? WHERE user_id IN ('local','')",
            (user_id,),
        )
        self.connection.execute(
            "INSERT INTO audit_log(user_id,action,detail,remote_addr,created_at,"
            "session_id,target_user_id) VALUES(?,?,?,?,?,NULL,NULL)",
            (
                user_id,
                "auth.default_admin.create",
                "迁移旧本机数据时创建临时管理员",
                "",
                now,
            ),
        )
        return user_id

    def _migrate_legacy_delete_tags_locked(self) -> None:
        rows = self.connection.execute(
            "SELECT it.source_key,MAX(it.created_at) AS deleted_at "
            "FROM item_tags it LEFT JOIN media m ON m.source_key=it.source_key "
            "WHERE it.tag='不要' COLLATE NOCASE AND m.id IS NULL "
            "GROUP BY it.source_key"
        ).fetchall()
        if not rows:
            return
        now = time.time()
        self.connection.executemany(
            "INSERT OR IGNORE INTO deleted_media("
            "source_key,bvid,title,deleted_at,files_deleted) VALUES(?,?,?,?,1)",
            [
                (
                    str(row["source_key"]),
                    str(row["source_key"])
                    if str(row["source_key"]).upper().startswith("BV")
                    else None,
                    str(row["source_key"]),
                    float(row["deleted_at"] or now),
                )
                for row in rows
            ],
        )
        keys = [(str(row["source_key"]),) for row in rows]
        self.connection.executemany(
            "DELETE FROM item_tags WHERE source_key=?", keys
        )

    def _migrate_locked(self, old_version: int, had_existing: bool) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._apply_schema_locked()
            for table, column, definition in (
                ("media", "index_fingerprint", "TEXT NOT NULL DEFAULT ''"),
                ("exports", "task_payload_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("users", "role", "TEXT NOT NULL DEFAULT 'user'"),
                ("users", "display_name", "TEXT NOT NULL DEFAULT ''"),
                ("users", "must_change_password", "INTEGER NOT NULL DEFAULT 0"),
                ("users", "created_by", "TEXT"),
                ("users", "last_login_at", "REAL"),
                ("sessions", "revoked_at", "REAL"),
                ("sessions", "revoke_reason", "TEXT NOT NULL DEFAULT ''"),
                ("audit_log", "session_id", "TEXT"),
                ("audit_log", "target_user_id", "TEXT"),
                ("exports", "owner_user_id", "TEXT"),
            ):
                self._add_column_locked(table, column, definition)

            if had_existing and old_version < 3:
                users = self.connection.execute(
                    "SELECT id,username,created_at,disabled FROM users "
                    "ORDER BY disabled ASC,created_at,id"
                ).fetchall()
                if users:
                    admin_id = str(users[0]["id"])
                    self.connection.execute(
                        "UPDATE users SET role=?,display_name=CASE WHEN TRIM(display_name)='' "
                        "THEN ? ELSE display_name END WHERE id=?",
                        (ROLE_ADMIN, DEFAULT_ADMIN_DISPLAY_NAME, admin_id),
                    )
                    self.connection.execute(
                        "UPDATE users SET role=?,display_name=CASE "
                        "WHEN TRIM(display_name)='' THEN '普通用户' ELSE display_name END "
                        "WHERE id<>?",
                        (ROLE_USER, admin_id),
                    )
                    self.connection.execute(
                        "UPDATE watch_progress SET user_id=? WHERE user_id IN ('local','')",
                        (admin_id,),
                    )
                now = time.time()
                self.connection.execute(
                    "UPDATE sessions SET revoked_at=COALESCE(revoked_at,?),"
                    "revoke_reason=CASE WHEN revoke_reason='' THEN 'schema_upgrade' "
                    "ELSE revoke_reason END WHERE revoked_at IS NULL",
                    (now,),
                )

            if had_existing and old_version < 4:
                admin_id = self._admin_user_id_locked(create_local=True)
                if not admin_id:
                    raise sqlite3.IntegrityError("任务所有权迁移找不到管理员账号")
                rows = self.connection.execute(
                    "SELECT task_id,destination,status,created_at,updated_at,payload_json "
                    "FROM task_snapshots ORDER BY created_at,task_id"
                ).fetchall()
                for row in rows:
                    try:
                        payload = json.loads(str(row["payload_json"] or "{}"))
                    except (json.JSONDecodeError, TypeError):
                        payload = {}
                    if not isinstance(payload, dict):
                        payload = {}
                    requested_owner = str(payload.get("owner_user_id") or "")
                    owner_row = (
                        self.connection.execute(
                            "SELECT id FROM users WHERE id=?", (requested_owner,)
                        ).fetchone()
                        if requested_owner
                        else None
                    )
                    owner = requested_owner if owner_row else admin_id
                    payload["owner_user_id"] = owner
                    destination = str(row["destination"] or "library")
                    payload["destination"] = destination
                    status = str(payload.get("status") or row["status"] or "failed")
                    created_at = float(
                        payload.get("created_at") or row["created_at"] or time.time()
                    )
                    updated_at = float(row["updated_at"] or created_at)
                    self.connection.execute(
                        "INSERT OR REPLACE INTO task_records("
                        "id,owner_user_id,destination,source_key,bvid,title,status,created_at,"
                        "started_at,finished_at,updated_at,payload_json) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(row["task_id"]),
                            owner,
                            destination,
                            str(payload.get("source_key") or payload.get("key") or ""),
                            payload.get("bvid"),
                            str(
                                payload.get("title")
                                or payload.get("display_title")
                                or ""
                            )[:500],
                            status,
                            created_at,
                            payload.get("started_at"),
                            payload.get("finished_at"),
                            updated_at,
                            json.dumps(
                                payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                self.connection.execute(
                    "UPDATE exports SET owner_user_id=? "
                    "WHERE owner_user_id IS NULL OR TRIM(owner_user_id)=''",
                    (admin_id,),
                )

            admin_id = self._admin_user_id_locked(create_local=False)
            if admin_id:
                self.connection.execute(
                    "UPDATE exports SET owner_user_id=? "
                    "WHERE owner_user_id IS NULL OR TRIM(owner_user_id)=''",
                    (admin_id,),
                )

            for statement in (
                "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_active "
                "ON sessions(user_id,revoked_at,expires_at,last_seen_at)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_single_enabled_admin "
                "ON users(role) WHERE role='admin' AND disabled=0",
                "CREATE INDEX IF NOT EXISTS idx_task_records_owner_created "
                "ON task_records(owner_user_id,created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_task_records_owner_finished "
                "ON task_records(owner_user_id,finished_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_task_records_owner_status "
                "ON task_records(owner_user_id,status)",
                "CREATE INDEX IF NOT EXISTS idx_task_records_destination_status "
                "ON task_records(destination,status)",
                "CREATE INDEX IF NOT EXISTS idx_exports_owner_source "
                "ON exports(owner_user_id,source_key,state,expires_at)",
            ):
                self.connection.execute(statement)

            self._migrate_legacy_delete_tags_locked()
            self.connection.execute(
                f"PRAGMA user_version={DATABASE_SCHEMA_VERSION}"
            )
            errors = self.connection.execute("PRAGMA foreign_key_check").fetchall()
            if errors:
                raise sqlite3.IntegrityError(
                    "迁移后外键检查失败: "
                    + "; ".join(str(tuple(row)) for row in errors[:5])
                )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            depth = int(getattr(self._transaction_state, "depth", 0))
            savepoint = f"nested_{depth}"
            if depth == 0:
                self.connection.execute("BEGIN IMMEDIATE")
            else:
                self.connection.execute(f"SAVEPOINT {savepoint}")
            self._transaction_state.depth = depth + 1
            try:
                yield self.connection
            except Exception:
                if depth == 0:
                    self.connection.execute("ROLLBACK")
                else:
                    self.connection.execute(f"ROLLBACK TO {savepoint}")
                    self.connection.execute(f"RELEASE {savepoint}")
                raise
            else:
                if depth == 0:
                    self.connection.execute("COMMIT")
                else:
                    self.connection.execute(f"RELEASE {savepoint}")
            finally:
                self._transaction_state.depth = depth

    def execute(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> sqlite3.Cursor:
        with self.lock:
            return self.connection.execute(sql, params)

    def one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        with self.lock:
            return [
                dict(row)
                for row in self.connection.execute(sql, params).fetchall()
            ]

    def close(self) -> None:
        with self.lock:
            try:
                self.connection.close()
            except sqlite3.ProgrammingError:
                pass
