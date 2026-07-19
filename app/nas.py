from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.artifacts import remove_relative_target
from app.auth import (
    ROLE_ADMIN,
    ROLE_USER,
    is_loopback_address,
    permissions_for_role,
    validate_display_name,
    validate_password,
    validate_username,
)
from app.constants import (
    DATABASE_SCHEMA_VERSION,
    MAX_ACTIVE_SESSIONS_PER_USER,
    SESSION_ABSOLUTE_DAYS,
    SESSION_TOUCH_INTERVAL_SECONDS,
)
from app.grouping import DEFAULT_GROUP, normalize_group
from app.index_store import IndexStore, UnsafeIndexPathError
from app.path_safety import UnsafePathError, relative_posix, resolve_under
from app.runtime import RuntimeSettings

_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".flv", ".webm", ".mov", ".ts", ".m4v"}
_MEDIA_EXTENSIONS = _VIDEO_EXTENSIONS | {".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg"}
_PASSWORD_N = 2**14
_MAX_PERSISTED_TASKS = 500
_DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_ADMIN_PASSWORD = "123456"
_DEFAULT_ADMIN_DISPLAY_NAME = "管理员"
_SYSTEM_DEFAULT_ADMIN = "system-default-admin"

_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 disabled INTEGER NOT NULL DEFAULT 0,
 role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin','user')),
 display_name TEXT NOT NULL DEFAULT '',
 must_change_password INTEGER NOT NULL DEFAULT 0,
 created_by TEXT,
 last_login_at REAL
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
 task_id TEXT PRIMARY KEY, source_key TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL, relative_path TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL DEFAULT '',
 size INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, expires_at REAL NOT NULL,
 downloaded_at REAL, error TEXT NOT NULL DEFAULT '', task_payload_json TEXT NOT NULL DEFAULT '{}'
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
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '', remote_addr TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
 session_id TEXT, target_user_id TEXT
);
"""


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_password(
    password: str, salt: bytes | None = None, *, allow_default_temp: bool = False
) -> str:
    validate_password(password, allow_default_temp=allow_default_temp)
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_PASSWORD_N, r=8, p=1, dklen=32
    )
    return f"scrypt${_PASSWORD_N}$8$1${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _media_id(key: str) -> str:
    return "med_" + hashlib.sha256(key.encode()).hexdigest()[:24]


def _file_id(storage: str, rel: str) -> str:
    return "fil_" + hashlib.sha256(f"{storage}:{rel}".encode()).hexdigest()[:24]


def _entry_fingerprint(entry: dict[str, Any]) -> str:
    encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_archive_name(value: str, fallback: str) -> str:
    result = "".join(ch if ch not in '\\/:*?"<>|' and ord(ch) >= 32 else "-" for ch in value)
    result = result[:140].strip(" .-")
    return result or fallback


class NasStore:
    """Persistent NAS/server state: auth, groups, library, exports and task history."""

    def __init__(
        self,
        runtime: RuntimeSettings,
        index: IndexStore,
        export_index: IndexStore | None = None,
    ):
        self.runtime = runtime
        self.index = index
        self.export_index = export_index
        self.path = runtime.database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        old_version, had_existing, backup_path = self._prepare_migration_backup()
        self.migration_backup_path = backup_path
        self._conn = sqlite3.connect(
            self.path, timeout=30, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        try:
            with self._lock:
                self._conn.execute("PRAGMA foreign_keys=ON")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
                self._conn.execute("PRAGMA busy_timeout=30000")
                self._migrate_locked(old_version, had_existing)
                if backup_path is not None:
                    self._prune_migration_backups()
        except Exception:
            self._conn.close()
            raise
        self.bootstrap_path = runtime.config_dir / "bootstrap-token.txt"
        self._bootstrap_token = ""
        self._login_failures: dict[str, list[float]] = {}
        self._snapshot_last_write: dict[str, float] = {}
        self._last_snapshot_prune = 0.0
        self._transcode_lock = threading.Semaphore(1)
        self._stop = threading.Event()
        self._last_index_token: tuple[str, int, int, int] | None = None
        self._cleaner = threading.Thread(
            target=self._cleanup_loop, name="v060-cleaner", daemon=True
        )
        try:
            self._ensure_default_admin()
            self._reject_remote_default_password()
            self._ensure_default_group()
            self._ensure_bootstrap()
            self._recover_interrupted_records()
            self.sync_index(force=True)
        except Exception:
            self._conn.close()
            raise
        self._cleaner.start()

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
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = backup_dir / f"bili_workspace-v{old_version}-{stamp}.db"
            target = sqlite3.connect(backup_path)
            try:
                source.backup(target)
                target.execute("PRAGMA wal_checkpoint(FULL)")
            finally:
                target.close()
            try:
                backup_path.chmod(0o600)
            except OSError:
                pass
            return old_version, True, backup_path
        finally:
            source.close()

    def _prune_migration_backups(self) -> None:
        backup_dir = self.path.parent / "backups"
        backups = sorted(
            backup_dir.glob("bili_workspace-v*.db"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale in backups[3:]:
            stale.unlink(missing_ok=True)

    def _apply_schema_locked(self) -> None:
        for statement in _SCHEMA.split(";"):
            sql = statement.strip()
            if sql:
                self._conn.execute(sql)

    def _columns_locked(self, table: str) -> set[str]:
        return {
            str(row[1])
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _add_column_locked(self, table: str, column: str, definition: str) -> None:
        if column not in self._columns_locked(table):
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_locked(self, old_version: int, had_existing: bool) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._apply_schema_locked()
            self._add_column_locked(
                "media", "index_fingerprint", "TEXT NOT NULL DEFAULT ''"
            )
            self._add_column_locked(
                "exports", "task_payload_json", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._add_column_locked("users", "role", "TEXT NOT NULL DEFAULT 'user'")
            self._add_column_locked(
                "users", "display_name", "TEXT NOT NULL DEFAULT ''"
            )
            self._add_column_locked(
                "users", "must_change_password", "INTEGER NOT NULL DEFAULT 0"
            )
            self._add_column_locked("users", "created_by", "TEXT")
            self._add_column_locked("users", "last_login_at", "REAL")
            self._add_column_locked("sessions", "revoked_at", "REAL")
            self._add_column_locked(
                "sessions", "revoke_reason", "TEXT NOT NULL DEFAULT ''"
            )
            self._add_column_locked("audit_log", "session_id", "TEXT")
            self._add_column_locked("audit_log", "target_user_id", "TEXT")

            if had_existing and old_version < DATABASE_SCHEMA_VERSION:
                users = self._conn.execute(
                    "SELECT id,username,created_at,disabled FROM users "
                    "ORDER BY disabled ASC,created_at,id"
                ).fetchall()
                if users:
                    admin_id = str(users[0]["id"])
                    self._conn.execute(
                        "UPDATE users SET role=?,display_name=CASE WHEN TRIM(display_name)='' "
                        "THEN ? ELSE display_name END WHERE id=?",
                        (ROLE_ADMIN, _DEFAULT_ADMIN_DISPLAY_NAME, admin_id),
                    )
                    self._conn.execute(
                        "UPDATE users SET role=?,display_name=CASE "
                        "WHEN TRIM(display_name)='' THEN '普通用户' ELSE display_name END "
                        "WHERE id<>?",
                        (ROLE_USER, admin_id),
                    )
                    self._conn.execute(
                        "UPDATE watch_progress SET user_id=? WHERE user_id IN ('local','')",
                        (admin_id,),
                    )
                now = time.time()
                self._conn.execute(
                    "UPDATE sessions SET revoked_at=COALESCE(revoked_at,?),"
                    "revoke_reason=CASE WHEN revoke_reason='' THEN 'schema_upgrade' ELSE revoke_reason END "
                    "WHERE revoked_at IS NULL",
                    (now,),
                )

            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_quality "
                "ON media(selected_height,selected_codec)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_active "
                "ON sessions(user_id,revoked_at,expires_at,last_seen_at)"
            )
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_single_enabled_admin "
                "ON users(role) WHERE role='admin' AND disabled=0"
            )
            self._conn.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION}")
            errors = self._conn.execute("PRAGMA foreign_key_check").fetchall()
            if errors:
                raise sqlite3.IntegrityError(
                    "迁移后外键检查失败: " + "; ".join(str(tuple(row)) for row in errors[:5])
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _ensure_default_admin(self) -> None:
        if (
            self.has_users()
            or self.runtime.mode != "local"
            or not self.runtime.auth_required
        ):
            return
        now = time.time()
        user_id = "usr_" + uuid.uuid4().hex[:24]
        self._execute(
            "INSERT INTO users(id,username,password_hash,created_at,updated_at,disabled,"
            "role,display_name,must_change_password,created_by) VALUES(?,?,?,?,?,0,?,?,?,?)",
            (
                user_id,
                _DEFAULT_ADMIN_USERNAME,
                _hash_password(_DEFAULT_ADMIN_PASSWORD, allow_default_temp=True),
                now,
                now,
                ROLE_ADMIN,
                _DEFAULT_ADMIN_DISPLAY_NAME,
                1,
                _SYSTEM_DEFAULT_ADMIN,
            ),
        )
        self.audit(user_id, "auth.default_admin.create", "创建本机临时管理员")

    def _reject_remote_default_password(self) -> None:
        if not self.runtime.server_mode:
            return
        row = self._one(
            "SELECT id FROM users WHERE role=? AND disabled=0 AND must_change_password=1 "
            "AND created_by=? LIMIT 1",
            (ROLE_ADMIN, _SYSTEM_DEFAULT_ADMIN),
        )
        if row:
            raise RuntimeError("默认管理员密码尚未修改，应用拒绝切换到非回环监听")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def close(self) -> None:
        self._stop.set()
        if threading.current_thread() is not self._cleaner:
            self._cleaner.join(timeout=2)
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.ProgrammingError:
                pass

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    # Authentication -------------------------------------------------
    @staticmethod
    def _public_user(row: dict[str, Any]) -> dict[str, Any]:
        user_id = row.get("user_id") or row.get("id") or ""
        created_at = row.get("user_created_at")
        if created_at is None:
            created_at = row.get("created_at")
        return {
            "id": str(user_id),
            "username": str(row["username"]),
            "display_name": str(row.get("display_name") or ""),
            "role": str(row.get("role") or ROLE_USER),
            "disabled": bool(row.get("disabled")),
            "must_change_password": bool(row.get("must_change_password")),
            "created_at": float(created_at or 0),
            "last_login_at": row.get("last_login_at"),
        }

    def has_users(self) -> bool:
        return self._one("SELECT 1 AS ok FROM users LIMIT 1") is not None

    def setup_required(self) -> bool:
        return not self.has_users()

    def _ensure_bootstrap(self) -> None:
        if not self.setup_required():
            self.bootstrap_path.unlink(missing_ok=True)
            return
        configured = os.getenv("BILI_BOOTSTRAP_TOKEN", "").strip()
        self._bootstrap_token = configured or secrets.token_urlsafe(24)
        if not configured:
            self.bootstrap_path.write_text(self._bootstrap_token + "\n", encoding="utf-8")
            try:
                self.bootstrap_path.chmod(0o600)
            except OSError:
                pass

    def _active_session_count_locked(self, user_id: str, now: float) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id=? AND revoked_at IS NULL "
            "AND expires_at>?",
            (user_id, now),
        ).fetchone()
        return int(row[0] if row else 0)

    def active_session_count(self, user_id: str) -> int:
        with self._lock:
            return self._active_session_count_locked(user_id, time.time())

    def auth_status(self, session_token: str = "") -> dict[str, Any]:
        session = self.get_session(session_token) if session_token else None
        setup_required = self.setup_required()
        data: dict[str, Any] = {
            "required": self.runtime.auth_required,
            "setup_required": setup_required,
            "authenticated": session is not None or not self.runtime.auth_required,
            "user": None,
            "username": "",
            "display_name": "",
            "role": "",
            "permissions": [],
            "must_change_password": False,
            "csrf_token": "",
            "session_expires_at": None,
            "active_session_count": 0,
            "bootstrap_hint": (
                (
                    "使用部署时设置的 BILI_BOOTSTRAP_TOKEN"
                    if os.getenv("BILI_BOOTSTRAP_TOKEN", "").strip()
                    else "读取配置卷中的 bootstrap-token.txt"
                )
                if setup_required
                else ""
            ),
        }
        if session:
            user = self._public_user(session)
            data.update(
                {
                    "user": user,
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "role": user["role"],
                    "permissions": permissions_for_role(user["role"]),
                    "must_change_password": user["must_change_password"],
                    "csrf_token": str(session["csrf_token"]),
                    "session_expires_at": float(session["expires_at"]),
                    "active_session_count": self.active_session_count(user["id"]),
                }
            )
        return data

    def setup_admin(
        self,
        username: str,
        password: str,
        bootstrap_token: str,
        display_name: str = _DEFAULT_ADMIN_DISPLAY_NAME,
    ) -> dict[str, Any]:
        if self.has_users():
            raise ValueError("管理员已经初始化")
        expected = os.getenv("BILI_BOOTSTRAP_TOKEN", "").strip() or self._bootstrap_token
        if not expected or not hmac.compare_digest(
            str(bootstrap_token or "").strip(), expected
        ):
            raise ValueError("初始化令牌无效")
        username = validate_username(username)
        display_name = validate_display_name(display_name)
        password_hash = _hash_password(password)
        now = time.time()
        user_id = "usr_" + uuid.uuid4().hex[:24]
        try:
            with self._transaction():
                existing = self._conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
                if existing:
                    raise ValueError("管理员已经初始化")
                self._conn.execute(
                    "INSERT INTO users(id,username,password_hash,created_at,updated_at,disabled,"
                    "role,display_name,must_change_password,created_by) "
                    "VALUES(?,?,?,?,?,0,?,?,0,NULL)",
                    (
                        user_id,
                        username,
                        password_hash,
                        now,
                        now,
                        ROLE_ADMIN,
                        display_name,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已经存在") from exc
        self.bootstrap_path.unlink(missing_ok=True)
        self._bootstrap_token = ""
        self.audit(user_id, "auth.setup", "初始化管理员")
        return self._public_user(
            self._one("SELECT * FROM users WHERE id=?", (user_id,)) or {}
        )

    def login_allowed(self, remote_addr: str) -> tuple[bool, int]:
        now = time.time()
        key = remote_addr or "unknown"
        values = [
            stamp for stamp in self._login_failures.get(key, []) if now - stamp < 900
        ]
        self._login_failures[key] = values
        if len(values) >= 8:
            return False, max(1, int(900 - (now - values[0])))
        return True, 0

    def record_login_failure(self, remote_addr: str) -> None:
        self._login_failures.setdefault(remote_addr or "unknown", []).append(time.time())

    def login(
        self,
        username: str,
        password: str,
        *,
        remote_addr: str,
        user_agent: str,
    ) -> tuple[str, dict[str, Any]]:
        allowed, retry = self.login_allowed(remote_addr)
        if not allowed:
            raise RuntimeError(f"登录尝试过多，请 {retry} 秒后再试")
        candidate = str(username or "").strip()
        user = self._one(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (candidate,),
        )
        if (
            not user
            or int(user["disabled"])
            or not _verify_password(password, str(user["password_hash"]))
        ):
            self.record_login_failure(remote_addr)
            self.audit(None, "auth.login.failed", f"账号={candidate[:32]}", remote_addr)
            raise ValueError("用户名或密码错误")
        if (
            str(user.get("created_by") or "") == _SYSTEM_DEFAULT_ADMIN
            and bool(user.get("must_change_password"))
            and not is_loopback_address(remote_addr)
        ):
            self.record_login_failure(remote_addr)
            self.audit(
                str(user["id"]),
                "auth.login.failed",
                "默认临时密码禁止远程登录",
                remote_addr,
            )
            raise ValueError("默认临时密码只能从本机回环地址登录")

        token = secrets.token_urlsafe(48)
        now = time.time()
        session_id = "ses_" + uuid.uuid4().hex[:24]
        session = {
            **user,
            "session_id": session_id,
            "user_id": str(user["id"]),
            "csrf_token": secrets.token_urlsafe(32),
            "session_created_at": now,
            "expires_at": now + SESSION_ABSOLUTE_DAYS * 24 * 3600,
            "last_seen_at": now,
            "user_agent": user_agent[:300],
            "remote_addr": remote_addr[:100],
        }
        session["must_change_password"] = bool(session.get("must_change_password"))
        evicted: list[str] = []
        with self._transaction():
            self._conn.execute(
                "UPDATE users SET last_login_at=?,updated_at=? WHERE id=?",
                (now, now, session["user_id"]),
            )
            self._conn.execute(
                "INSERT INTO sessions(id,user_id,token_hash,csrf_token,created_at,expires_at,"
                "last_seen_at,user_agent,remote_addr,revoked_at,revoke_reason) "
                "VALUES(?,?,?,?,?,?,?,?,?,NULL,'')",
                (
                    session_id,
                    session["user_id"],
                    _token_hash(token),
                    session["csrf_token"],
                    now,
                    session["expires_at"],
                    now,
                    session["user_agent"],
                    session["remote_addr"],
                ),
            )
            rows = self._conn.execute(
                "SELECT id FROM sessions WHERE user_id=? AND revoked_at IS NULL "
                "AND expires_at>? ORDER BY last_seen_at ASC,created_at ASC,id ASC",
                (session["user_id"], now),
            ).fetchall()
            overflow = max(0, len(rows) - MAX_ACTIVE_SESSIONS_PER_USER)
            candidates = [str(row["id"]) for row in rows if str(row["id"]) != session_id]
            evicted = candidates[:overflow]
            if evicted:
                placeholders = ",".join("?" for _ in evicted)
                self._conn.execute(
                    f"UPDATE sessions SET revoked_at=?,revoke_reason='session_limit' "
                    f"WHERE id IN ({placeholders})",
                    (now, *evicted),
                )
        self._login_failures.pop(remote_addr or "unknown", None)
        session["last_login_at"] = now
        self.audit(
            session["user_id"],
            "auth.login",
            f"创建会话；淘汰 {len(evicted)} 个旧会话",
            remote_addr,
            session_id=session_id,
        )
        for evicted_id in evicted:
            self.audit(
                session["user_id"],
                "auth.session.evicted",
                "超过每用户 10 个有效会话",
                remote_addr,
                session_id=evicted_id,
            )
        return token, session

    def get_session(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        now = time.time()
        row = self._one(
            "SELECT s.id AS session_id,s.user_id,s.csrf_token,s.created_at AS session_created_at,"
            "s.expires_at,s.last_seen_at,s.user_agent,s.remote_addr,s.revoked_at,s.revoke_reason,"
            "u.id,u.username,u.display_name,u.role,u.disabled,u.must_change_password,"
            "u.created_at AS user_created_at,u.last_login_at,u.created_by "
            "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
            (_token_hash(token),),
        )
        if not row or int(row["disabled"]) or row.get("revoked_at") is not None:
            return None
        if float(row["expires_at"]) <= now:
            self._execute(
                "UPDATE sessions SET revoked_at=?,revoke_reason='expired' "
                "WHERE id=? AND revoked_at IS NULL",
                (now, row["session_id"]),
            )
            return None
        if now - float(row["last_seen_at"]) >= SESSION_TOUCH_INTERVAL_SECONDS:
            self._execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=? AND revoked_at IS NULL",
                (now, row["session_id"]),
            )
            row["last_seen_at"] = now
        row["must_change_password"] = bool(row["must_change_password"])
        return row

    def get_session_by_id(self, session_id: str) -> dict[str, Any] | None:
        now = time.time()
        row = self._one(
            "SELECT s.*,u.username,u.display_name,u.role,u.disabled,u.must_change_password "
            "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=?",
            (session_id,),
        )
        if (
            not row
            or bool(row["disabled"])
            or row.get("revoked_at") is not None
            or float(row["expires_at"]) <= now
        ):
            return None
        if now - float(row["last_seen_at"]) >= SESSION_TOUCH_INTERVAL_SECONDS:
            self._execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=? AND revoked_at IS NULL",
                (now, session_id),
            )
            row["last_seen_at"] = now
        return row

    def session_is_active(self, session_id: str) -> bool:
        session = self.get_session_by_id(session_id)
        if session is None:
            return False
        now = time.time()
        if now - float(session["last_seen_at"]) >= SESSION_TOUCH_INTERVAL_SECONDS:
            self._execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=? AND revoked_at IS NULL",
                (now, session_id),
            )
        return True

    def list_sessions(self, user_id: str, current_session_id: str) -> list[dict[str, Any]]:
        now = time.time()
        rows = self._all(
            "SELECT id,user_agent,remote_addr,created_at,last_seen_at,expires_at "
            "FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>? "
            "ORDER BY last_seen_at DESC,created_at DESC",
            (user_id, now),
        )
        for row in rows:
            row["current"] = str(row["id"]) == current_session_id
        return rows

    def revoke_session(
        self,
        user_id: str,
        session_id: str,
        *,
        current_session_id: str,
        reason: str = "user_revoke",
    ) -> bool:
        if session_id == current_session_id:
            raise ValueError("不能通过此接口撤销当前设备，请使用退出登录")
        now = time.time()
        cursor = self._execute(
            "UPDATE sessions SET revoked_at=?,revoke_reason=? WHERE id=? AND user_id=? "
            "AND revoked_at IS NULL AND expires_at>?",
            (now, reason[:80], session_id, user_id, now),
        )
        return cursor.rowcount > 0

    def revoke_other_sessions(self, user_id: str, current_session_id: str) -> int:
        now = time.time()
        cursor = self._execute(
            "UPDATE sessions SET revoked_at=?,revoke_reason='user_revoke_others' "
            "WHERE user_id=? AND id<>? AND revoked_at IS NULL AND expires_at>?",
            (now, user_id, current_session_id, now),
        )
        return int(cursor.rowcount)

    def revoke_all_sessions(self, user_id: str, reason: str) -> int:
        now = time.time()
        cursor = self._execute(
            "UPDATE sessions SET revoked_at=?,revoke_reason=? WHERE user_id=? "
            "AND revoked_at IS NULL AND expires_at>?",
            (now, reason[:80], user_id, now),
        )
        return int(cursor.rowcount)

    def logout(self, session_id: str) -> None:
        self._execute(
            "UPDATE sessions SET revoked_at=?,revoke_reason='logout' "
            "WHERE id=? AND revoked_at IS NULL",
            (time.time(), session_id),
        )

    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        *,
        keep_session_id: str,
    ) -> dict[str, Any]:
        user = self._one(
            "SELECT * FROM users WHERE id=?", (user_id,)
        )
        if (
            not user
            or int(user["disabled"])
            or not _verify_password(current_password, str(user["password_hash"]))
        ):
            raise ValueError("当前密码错误")
        if hmac.compare_digest(current_password, new_password):
            raise ValueError("新密码不能与当前密码相同")
        encoded = _hash_password(new_password)
        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        now = time.time()
        with self._transaction():
            self._conn.execute(
                "UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?",
                (encoded, now, user_id),
            )
            row = self._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id=? AND id<>? "
                "AND revoked_at IS NULL AND expires_at>?",
                (user_id, keep_session_id, now),
            ).fetchone()
            self._conn.execute(
                "UPDATE sessions SET revoked_at=?,revoke_reason='password_change' "
                "WHERE user_id=? AND id<>? AND revoked_at IS NULL AND expires_at>?",
                (now, user_id, keep_session_id, now),
            )
            cursor = self._conn.execute(
                "UPDATE sessions SET token_hash=?,csrf_token=?,last_seen_at=? "
                "WHERE id=? AND user_id=? AND revoked_at IS NULL AND expires_at>?",
                (
                    _token_hash(token),
                    csrf_token,
                    now,
                    keep_session_id,
                    user_id,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("当前会话已经失效，请重新登录")
        session = self.get_session(token)
        if not session:
            raise RuntimeError("密码修改后会话轮换失败")
        return {
            "token": token,
            "csrf_token": csrf_token,
            "other_sessions_revoked": int(row[0] if row else 0),
            "session": session,
        }

    def update_profile(self, user_id: str, display_name: str) -> dict[str, Any]:
        display_name = validate_display_name(display_name)
        self._execute(
            "UPDATE users SET display_name=?,updated_at=? WHERE id=? AND disabled=0",
            (display_name, time.time(), user_id),
        )
        user = self._one("SELECT * FROM users WHERE id=?", (user_id,))
        if not user:
            raise KeyError("用户不存在")
        return self._public_user(user)

    def list_users(self) -> list[dict[str, Any]]:
        now = time.time()
        rows = self._all(
            "SELECT u.*,COUNT(s.id) AS active_session_count FROM users u "
            "LEFT JOIN sessions s ON s.user_id=u.id AND s.revoked_at IS NULL AND s.expires_at>? "
            "GROUP BY u.id ORDER BY CASE u.role WHEN 'admin' THEN 0 ELSE 1 END,"
            "u.created_at,u.username COLLATE NOCASE",
            (now,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = self._public_user(row)
            item["active_session_count"] = int(row.get("active_session_count") or 0)
            result.append(item)
        return result

    def create_user(
        self,
        username: str,
        display_name: str,
        temporary_password: str,
        *,
        created_by: str,
    ) -> dict[str, Any]:
        username = validate_username(username)
        display_name = validate_display_name(display_name)
        encoded = _hash_password(temporary_password)
        now = time.time()
        user_id = "usr_" + uuid.uuid4().hex[:24]
        try:
            self._execute(
                "INSERT INTO users(id,username,password_hash,created_at,updated_at,disabled,"
                "role,display_name,must_change_password,created_by) "
                "VALUES(?,?,?,?,?,0,?,?,1,?)",
                (
                    user_id,
                    username,
                    encoded,
                    now,
                    now,
                    ROLE_USER,
                    display_name,
                    created_by,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("登录账号已经存在") from exc
        return self._public_user(
            self._one("SELECT * FROM users WHERE id=?", (user_id,)) or {}
        )

    def set_user_display_name(self, user_id: str, display_name: str) -> dict[str, Any]:
        return self.update_profile(user_id, display_name)

    def set_user_disabled(
        self, user_id: str, disabled: bool, *, actor_user_id: str
    ) -> dict[str, Any]:
        user = self._one("SELECT * FROM users WHERE id=?", (user_id,))
        if not user:
            raise KeyError("用户不存在")
        if str(user["role"]) == ROLE_ADMIN:
            raise ValueError("不能禁用当前管理员")
        self._execute(
            "UPDATE users SET disabled=?,updated_at=? WHERE id=?",
            (1 if disabled else 0, time.time(), user_id),
        )
        if disabled:
            self.revoke_all_sessions(user_id, "user_disabled")
        updated = self._one("SELECT * FROM users WHERE id=?", (user_id,)) or user
        self.audit(
            actor_user_id,
            "admin.user.disable" if disabled else "admin.user.enable",
            str(updated["username"]),
            target_user_id=user_id,
        )
        return self._public_user(updated)

    def reset_user_password(
        self, user_id: str, temporary_password: str, *, actor_user_id: str
    ) -> dict[str, Any]:
        user = self._one("SELECT * FROM users WHERE id=?", (user_id,))
        if not user:
            raise KeyError("用户不存在")
        if str(user["role"]) == ROLE_ADMIN and user_id == actor_user_id:
            raise ValueError("管理员请使用修改自己密码接口")
        encoded = _hash_password(temporary_password)
        with self._transaction():
            self._conn.execute(
                "UPDATE users SET password_hash=?,must_change_password=1,updated_at=? WHERE id=?",
                (encoded, time.time(), user_id),
            )
            now = time.time()
            cursor = self._conn.execute(
                "UPDATE sessions SET revoked_at=?,revoke_reason='admin_password_reset' "
                "WHERE user_id=? AND revoked_at IS NULL AND expires_at>?",
                (now, user_id, now),
            )
        self.audit(
            actor_user_id,
            "admin.user.password_reset",
            f"撤销会话 {cursor.rowcount} 个",
            target_user_id=user_id,
        )
        updated = self._one("SELECT * FROM users WHERE id=?", (user_id,)) or user
        return {
            "user": self._public_user(updated),
            "sessions_revoked": int(cursor.rowcount),
        }

    def audit(
        self,
        user_id: str | None,
        action: str,
        detail: str = "",
        remote_addr: str = "",
        *,
        session_id: str | None = None,
        target_user_id: str | None = None,
    ) -> None:
        self._execute(
            "INSERT INTO audit_log(user_id,action,detail,remote_addr,created_at,session_id,"
            "target_user_id) VALUES(?,?,?,?,?,?,?)",
            (
                user_id,
                action[:120],
                detail[:1000],
                remote_addr[:100],
                time.time(),
                session_id,
                target_user_id,
            ),
        )

    # Storage health --------------------------------------------------
    def storage_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {"minimum_free_bytes": self.runtime.min_free_bytes}
        for name, path in (
            ("media", self.runtime.media_dir),
            ("temp", self.runtime.temp_dir),
            ("cache", self.runtime.cache_dir),
        ):
            usage = shutil.disk_usage(path)
            result[name] = {
                "path": str(path),
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "healthy": usage.free >= self.runtime.min_free_bytes,
            }
        return result

    def ensure_space(self, destination: str) -> None:
        target = self.runtime.temp_dir if destination == "device" else self.runtime.media_dir
        free = shutil.disk_usage(target).free
        if free < self.runtime.min_free_bytes:
            required = self.runtime.min_free_bytes / 1024**3
            available = free / 1024**3
            raise ValueError(
                f"目标磁盘剩余空间不足：当前 {available:.2f} GiB，至少保留 {required:.2f} GiB"
            )

    # Groups ----------------------------------------------------------
    def _ensure_default_group(self) -> dict[str, Any]:
        existing = self._one(
            "SELECT * FROM groups WHERE display_name=? COLLATE NOCASE", (DEFAULT_GROUP,)
        )
        return existing or self.create_group(DEFAULT_GROUP)

    def _group_stats(self, row: dict[str, Any]) -> dict[str, Any]:
        stats = self._one(
            "SELECT COUNT(*) AS media_count,COALESCE(SUM(total_size),0) AS total_size,"
            "MAX(downloaded_at) AS latest_download FROM media WHERE group_id=?",
            (row["id"],),
        ) or {}
        cover = self._one(
            "SELECT cover FROM media WHERE group_id=? AND cover<>'' ORDER BY downloaded_at DESC LIMIT 1",
            (row["id"],),
        )
        return {
            **row,
            "archived": bool(row["archived"]),
            "media_count": int(stats.get("media_count") or 0),
            "total_size": int(stats.get("total_size") or 0),
            "latest_download": stats.get("latest_download"),
            "cover": str((cover or {}).get("cover") or ""),
        }

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM groups WHERE id=?", (group_id,))
        return self._group_stats(row) if row else None

    def group_by_folder(self, folder: str) -> dict[str, Any] | None:
        row = self._one(
            "SELECT * FROM groups WHERE folder_key=? COLLATE NOCASE", (folder,)
        )
        return self._group_stats(row) if row else None

    def group_by_name(self, name: str) -> dict[str, Any] | None:
        row = self._one(
            "SELECT * FROM groups WHERE display_name=? COLLATE NOCASE", (name,)
        )
        return self._group_stats(row) if row else None

    def list_groups(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE g.archived=0"
        rows = self._all(
            "SELECT g.*,COUNT(m.id) AS media_count,COALESCE(SUM(m.total_size),0) AS total_size,"
            f"MAX(m.downloaded_at) AS latest_download FROM groups g LEFT JOIN media m ON m.group_id=g.id {where} "
            "GROUP BY g.id ORDER BY g.sort_order,g.display_name COLLATE NOCASE"
        )
        covers = {
            str(item["group_id"]): str(item["cover"] or "")
            for item in self._all(
                "SELECT m.group_id,m.cover FROM media m JOIN (SELECT group_id,MAX(downloaded_at) AS latest "
                "FROM media WHERE cover<>'' GROUP BY group_id) x ON x.group_id=m.group_id AND x.latest=m.downloaded_at"
            )
        }
        for row in rows:
            row["archived"] = bool(row["archived"])
            row["media_count"] = int(row["media_count"] or 0)
            row["total_size"] = int(row["total_size"] or 0)
            row["cover"] = covers.get(str(row["id"]), "")
        return rows

    def _unique_folder(self, base: str, excluding: str = "") -> str:
        candidate, number = base, 2
        while True:
            row = self._one(
                "SELECT id FROM groups WHERE folder_key=? COLLATE NOCASE", (candidate,)
            )
            if not row or row["id"] == excluding:
                return candidate
            suffix = f"-{number}"
            candidate = base[: max(1, 60 - len(suffix))] + suffix
            number += 1

    def create_group(self, name: str) -> dict[str, Any]:
        normalized = normalize_group(name)
        existing = self.group_by_name(normalized.display)
        if existing:
            return existing
        now = time.time()
        group_id = "grp_" + uuid.uuid4().hex[:20]
        folder = self._unique_folder(normalized.folder)
        self._execute(
            "INSERT INTO groups(id,display_name,folder_key,created_at,updated_at) VALUES(?,?,?,?,?)",
            (group_id, normalized.display, folder, now, now),
        )
        return self.get_group(group_id) or {}

    def resolve_group(self, group_id: str = "", fallback_name: str = "") -> dict[str, Any]:
        if group_id:
            group = self.get_group(group_id)
            if not group or group["archived"]:
                raise ValueError("所选分组不存在或已归档")
            return group
        return self.create_group(fallback_name or DEFAULT_GROUP)

    def _index_patches_for_group(
        self, group_id: str, display_name: str
    ) -> dict[str, dict[str, Any]]:
        rows = self._all("SELECT source_key FROM media WHERE group_id=?", (group_id,))
        return {
            str(row["source_key"]): {"group_id": group_id, "group": display_name}
            for row in rows
        }

    def rename_group(self, group_id: str, name: str) -> dict[str, Any]:
        group = self.get_group(group_id)
        if not group:
            raise KeyError("分组不存在")
        normalized = normalize_group(name)
        conflict = self.group_by_name(normalized.display)
        if conflict and conflict["id"] != group_id:
            raise ValueError("已经存在同名分组")
        patches = self._index_patches_for_group(group_id, normalized.display)
        if patches:
            self.index.patch_entries(patches)
        self._execute(
            "UPDATE groups SET display_name=?,updated_at=? WHERE id=?",
            (normalized.display, time.time(), group_id),
        )
        self._last_index_token = self.index.change_token()
        return self.get_group(group_id) or {}

    def merge_group(self, source_id: str, target_id: str) -> dict[str, Any]:
        if source_id == target_id:
            raise ValueError("不能合并到同一分组")
        source, target = self.get_group(source_id), self.get_group(target_id)
        if not source or not target:
            raise KeyError("分组不存在")
        patches = {
            str(row["source_key"]): {
                "group_id": target_id,
                "group": target["display_name"],
            }
            for row in self._all("SELECT source_key FROM media WHERE group_id=?", (source_id,))
        }
        if patches:
            self.index.patch_entries(patches)
        with self._transaction() as conn:
            conn.execute(
                "UPDATE media SET group_id=?,updated_at=? WHERE group_id=?",
                (target_id, time.time(), source_id),
            )
            conn.execute("DELETE FROM groups WHERE id=?", (source_id,))
        self._last_index_token = self.index.change_token()
        return self.get_group(target_id) or {}

    def delete_group(self, group_id: str) -> None:
        group = self.get_group(group_id)
        if not group:
            raise KeyError("分组不存在")
        if group["display_name"] == DEFAULT_GROUP:
            raise ValueError("默认分组不能删除")
        if group["media_count"]:
            raise ValueError("分组中还有作品，请先移动或合并")
        self._execute("DELETE FROM groups WHERE id=?", (group_id,))

    # Library ---------------------------------------------------------
    def _resolve_entry_group(self, entry: dict[str, Any]) -> dict[str, Any]:
        group_id = str(entry.get("group_id") or "").strip()
        group = self.get_group(group_id) if group_id else None
        if not group:
            folder = str(entry.get("group_folder") or "").strip()
            group = self.group_by_folder(folder) if folder else None
        return group or self.create_group(str(entry.get("group") or DEFAULT_GROUP))

    def sync_index(self, force: bool = False) -> dict[str, int]:
        token, entries = self.index.snapshot()
        if not force and token == self._last_index_token:
            return {"imported": 0, "unchanged": len(entries), "skipped": 0, "removed": 0}

        imported = unchanged = skipped = 0
        valid_keys: set[str] = set()
        patches: dict[str, dict[str, Any]] = {}
        for key, original_entry in entries.items():
            try:
                valid_entry = self.index.get_valid(key)
                if not valid_entry:
                    skipped += 1
                    continue
                entry = dict(original_entry)
                group = self._resolve_entry_group(entry)
                if (
                    str(entry.get("group_id") or "") != str(group["id"])
                    or str(entry.get("group") or "") != str(group["display_name"])
                ):
                    entry["group_id"] = group["id"]
                    entry["group"] = group["display_name"]
                    patches[key] = {
                        "group_id": group["id"],
                        "group": group["display_name"],
                    }

                media_id = _media_id(key)
                files = [
                    dict(item)
                    for item in entry.get("files") or []
                    if isinstance(item, dict)
                ]
                actual_files: list[tuple[dict[str, Any], Path]] = []
                for item in files:
                    rel = str(item.get("path") or "").strip()
                    if not rel:
                        continue
                    path = resolve_under(self.runtime.media_dir, rel)
                    if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                        actual_files.append((item, path))
                if not actual_files:
                    skipped += 1
                    continue

                fingerprint = _entry_fingerprint(entry)
                current = self._one(
                    "SELECT index_fingerprint,group_id FROM media WHERE source_key=?", (key,)
                )
                valid_keys.add(key)
                if (
                    current
                    and str(current.get("index_fingerprint") or "") == fingerprint
                    and str(current.get("group_id") or "") == str(group["id"])
                ):
                    unchanged += 1
                    continue

                total = sum(path.stat().st_size for _, path in actual_files)
                now = time.time()
                self._execute(
                    "INSERT INTO media(id,source_key,bvid,source_url,title,cover,author,pubdate,duration_text,"
                    "group_id,output_path,min_height,preferred_quality,selected_quality,selected_resolution,"
                    "selected_codec,selected_fps,selected_height,total_size,downloaded_at,updated_at,index_fingerprint) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(source_key) DO UPDATE SET bvid=excluded.bvid,source_url=excluded.source_url,"
                    "title=excluded.title,cover=excluded.cover,author=excluded.author,pubdate=excluded.pubdate,"
                    "duration_text=excluded.duration_text,group_id=excluded.group_id,output_path=excluded.output_path,"
                    "min_height=excluded.min_height,preferred_quality=excluded.preferred_quality,"
                    "selected_quality=excluded.selected_quality,selected_resolution=excluded.selected_resolution,"
                    "selected_codec=excluded.selected_codec,selected_fps=excluded.selected_fps,"
                    "selected_height=excluded.selected_height,total_size=excluded.total_size,"
                    "downloaded_at=excluded.downloaded_at,updated_at=excluded.updated_at,"
                    "index_fingerprint=excluded.index_fingerprint",
                    (
                        media_id,
                        key,
                        entry.get("bvid") or (key if key.startswith("BV") else None),
                        str(entry.get("url") or ""),
                        str(entry.get("title") or key)[:500],
                        str(entry.get("cover") or "")[:2048],
                        str(entry.get("author") or "")[:300],
                        entry.get("pubdate") if isinstance(entry.get("pubdate"), int) else None,
                        str(entry.get("duration") or "")[:32],
                        group["id"],
                        str(entry.get("path") or ""),
                        int(entry.get("min_height") or 0),
                        str(entry.get("preferred_quality") or "")[:120],
                        str(entry.get("selected_quality") or "")[:120],
                        str(entry.get("selected_resolution") or "")[:80],
                        str(entry.get("selected_codec") or "")[:80],
                        str(entry.get("selected_fps") or "")[:40],
                        entry.get("selected_height")
                        if isinstance(entry.get("selected_height"), int)
                        else None,
                        total,
                        float(entry.get("finished_at") or now),
                        now,
                        fingerprint,
                    ),
                )
                self._execute(
                    "DELETE FROM media_files WHERE media_id=? AND kind='media'", (media_id,)
                )
                primary_path: Path | None = next(
                    (path for _, path in actual_files if path.suffix.lower() in _VIDEO_EXTENSIONS),
                    None,
                )
                if primary_path is None:
                    primary_path = next(
                        (path for _, path in actual_files if path.suffix.lower() in _MEDIA_EXTENSIONS),
                        actual_files[0][1],
                    )
                for item, path in actual_files:
                    rel = relative_posix(self.runtime.media_dir, path)
                    self._execute(
                        "INSERT OR REPLACE INTO media_files(id,media_id,storage,relative_path,filename,size,"
                        "mime_type,kind,is_primary,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            _file_id("media", rel),
                            media_id,
                            "media",
                            rel,
                            path.name,
                            path.stat().st_size,
                            mimetypes.guess_type(path.name)[0]
                            or "application/octet-stream",
                            "media",
                            1 if path == primary_path else 0,
                            now,
                        ),
                    )
                imported += 1
            except (OSError, ValueError, UnsafePathError, UnsafeIndexPathError):
                skipped += 1

        existing_keys = {
            str(row["source_key"])
            for row in self._all("SELECT source_key FROM media")
        }
        stale = existing_keys - valid_keys
        removed = 0
        if stale:
            with self._transaction() as conn:
                for key in stale:
                    conn.execute("DELETE FROM media WHERE source_key=?", (key,))
                    removed += 1
        if patches:
            self.index.patch_entries(patches)
        self._last_index_token = self.index.change_token()
        return {
            "imported": imported,
            "unchanged": unchanged,
            "skipped": skipped,
            "removed": removed,
        }

    def library_list(
        self,
        *,
        page: int,
        page_size: int,
        query: str,
        group_id: str,
        sort: str,
        user_id: str,
        codec: str = "",
        min_height: int = 0,
        watched: str = "",
    ) -> dict[str, Any]:
        self.sync_index()
        page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
        clauses: list[str] = []
        params: list[Any] = []
        if query.strip():
            needle = f"%{query.strip()}%"
            clauses.append(
                "(m.title LIKE ? OR m.bvid LIKE ? OR m.author LIKE ? OR m.source_key LIKE ?)"
            )
            params += [needle, needle, needle, needle]
        if group_id:
            clauses.append("m.group_id=?")
            params.append(group_id)
        if codec.strip():
            clauses.append("LOWER(m.selected_codec) LIKE ?")
            params.append(f"%{codec.strip().lower()}%")
        if int(min_height or 0) > 0:
            clauses.append("COALESCE(m.selected_height,0)>=?")
            params.append(int(min_height))
        watched = watched.strip().lower()
        if watched in {"completed", "in_progress", "unwatched"}:
            progress_sql = (
                "SELECT 1 FROM watch_progress wp WHERE wp.media_id=m.id AND wp.user_id=? "
            )
            params.append(user_id)
            if watched == "completed":
                clauses.append(f"EXISTS ({progress_sql}AND wp.completed=1)")
            elif watched == "in_progress":
                clauses.append(
                    f"EXISTS ({progress_sql}AND wp.completed=0 AND wp.position_sec>0)"
                )
            else:
                clauses.append(
                    f"NOT EXISTS ({progress_sql}AND wp.position_sec>0)"
                )
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        order = {
            "newest": "m.downloaded_at DESC",
            "oldest": "m.downloaded_at ASC",
            "title": "m.title COLLATE NOCASE",
            "size": "m.total_size DESC",
            "recent": "COALESCE(w.updated_at,0) DESC,m.downloaded_at DESC",
        }.get(sort, "m.downloaded_at DESC")
        total = int(
            (
                self._one(f"SELECT COUNT(*) AS n FROM media m {where}", tuple(params))
                or {}
            ).get("n")
            or 0
        )
        rows = self._all(
            "SELECT m.*,g.display_name AS group_name,g.folder_key AS group_folder,"
            "f.id AS primary_file_id,f.filename AS primary_filename,f.mime_type AS primary_mime,"
            "COALESCE(w.position_sec,0) AS watch_position,COALESCE(w.duration_sec,0) AS watch_duration,"
            f"COALESCE(w.completed,0) AS watch_completed FROM media m "
            "LEFT JOIN groups g ON g.id=m.group_id "
            "LEFT JOIN media_files f ON f.media_id=m.id AND f.is_primary=1 "
            "LEFT JOIN watch_progress w ON w.file_id=f.id AND w.user_id=? "
            f"{where} ORDER BY {order} LIMIT ? OFFSET ?",
            tuple([user_id, *params, page_size, (page - 1) * page_size]),
        )
        for row in rows:
            row["watch_completed"] = bool(row["watch_completed"])
        return {
            "items": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size if total else 0,
            "filters": {
                "query": query,
                "group_id": group_id,
                "codec": codec,
                "min_height": int(min_height or 0),
                "watched": watched,
                "sort": sort,
            },
        }

    def library_summary(self) -> dict[str, Any]:
        self.sync_index()
        row = self._one(
            "SELECT COUNT(*) AS media_count,COALESCE(SUM(total_size),0) AS total_size,"
            "MAX(downloaded_at) AS latest_download FROM media"
        ) or {}
        return {
            "media_count": int(row.get("media_count") or 0),
            "total_size": int(row.get("total_size") or 0),
            "latest_download": row.get("latest_download"),
        }

    def media_detail(self, media_id: str, user_id: str) -> dict[str, Any] | None:
        self.sync_index()
        row = self._one(
            "SELECT m.*,g.display_name AS group_name,g.folder_key AS group_folder FROM media m "
            "LEFT JOIN groups g ON g.id=m.group_id WHERE m.id=?",
            (media_id,),
        )
        if not row:
            return None
        row["files"] = self._all(
            "SELECT f.*,COALESCE(w.position_sec,0) AS watch_position,"
            "COALESCE(w.duration_sec,0) AS watch_duration,COALESCE(w.completed,0) AS watch_completed "
            "FROM media_files f LEFT JOIN watch_progress w ON w.file_id=f.id AND w.user_id=? "
            "WHERE f.media_id=? ORDER BY f.is_primary DESC,f.kind,f.filename COLLATE NOCASE",
            (user_id, media_id),
        )
        for item in row["files"]:
            item["watch_completed"] = bool(item["watch_completed"])
        return row

    def resolve_media_file(self, file_id: str) -> tuple[dict[str, Any], Path]:
        row = self._one(
            "SELECT f.*,m.title,m.id AS media_id,m.source_key FROM media_files f "
            "JOIN media m ON m.id=f.media_id WHERE f.id=?",
            (file_id,),
        )
        if not row:
            raise KeyError("媒体文件不存在")
        base = self.runtime.media_dir if row["storage"] == "media" else self.runtime.cache_dir
        path = resolve_under(base, str(row["relative_path"]))
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("媒体文件已不存在")
        return row, path

    def save_progress(
        self, user_id: str, media_id: str, file_id: str, position: float, duration: float
    ) -> dict[str, Any]:
        if not self._one(
            "SELECT 1 AS ok FROM media_files WHERE id=? AND media_id=?", (file_id, media_id)
        ):
            raise KeyError("媒体文件不存在")
        position, duration = max(0, float(position)), max(0, float(duration))
        if duration:
            position = min(position, duration)
        completed = duration > 0 and position >= max(0, duration - 15)
        now = time.time()
        self._execute(
            "INSERT INTO watch_progress(user_id,media_id,file_id,position_sec,duration_sec,completed,updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,media_id,file_id) DO UPDATE SET "
            "position_sec=excluded.position_sec,duration_sec=excluded.duration_sec,"
            "completed=excluded.completed,updated_at=excluded.updated_at",
            (user_id, media_id, file_id, position, duration, 1 if completed else 0, now),
        )
        return {
            "position_sec": position,
            "duration_sec": duration,
            "completed": completed,
            "updated_at": now,
        }

    def move_media(self, media_id: str, group_id: str) -> dict[str, Any]:
        group = self.get_group(group_id)
        if not group:
            raise KeyError("目标分组不存在")
        row = self._one("SELECT source_key FROM media WHERE id=?", (media_id,))
        if not row:
            raise KeyError("作品不存在")
        self.index.patch_entry(
            str(row["source_key"]),
            {"group_id": group_id, "group": group["display_name"]},
        )
        self._execute(
            "UPDATE media SET group_id=?,updated_at=? WHERE id=?",
            (group_id, time.time(), media_id),
        )
        self._last_index_token = self.index.change_token()
        return self.media_detail(media_id, "local") or {}

    def delete_media(self, media_id: str, delete_files: bool) -> dict[str, Any]:
        row = self._one(
            "SELECT source_key,output_path FROM media WHERE id=?", (media_id,)
        )
        if not row:
            raise KeyError("作品不存在")
        source_key = str(row["source_key"])
        if delete_files:
            removed = self.index.remove_entry_and_files(source_key)
            if not removed and str(row["output_path"]):
                remove_relative_target(self.runtime.media_dir, str(row["output_path"]))
        else:
            self.index.discard_entry(source_key)
        compat = resolve_under(self.runtime.cache_dir, f"compatible/{media_id}")
        if compat.exists() and not compat.is_symlink():
            shutil.rmtree(compat)
        self._execute("DELETE FROM media WHERE id=?", (media_id,))
        self._last_index_token = self.index.change_token()
        return {"deleted": True, "files_deleted": bool(delete_files)}

    # Manual compatible copy ----------------------------------------
    def start_compatible(
        self, media_id: str, file_id: str, ffmpeg: Path
    ) -> dict[str, Any]:
        row, source = self.resolve_media_file(file_id)
        if row["media_id"] != media_id:
            raise ValueError("文件不属于该作品")
        self.ensure_space("device")
        job_id = "tr_" + uuid.uuid4().hex[:20]
        now = time.time()
        self._execute(
            "INSERT INTO transcodes(id,media_id,source_file_id,status,progress_message,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (job_id, media_id, file_id, "queued", "等待转码", now),
        )
        thread = threading.Thread(
            target=self._transcode_worker,
            args=(job_id, row, source, Path(ffmpeg)),
            daemon=True,
            name=f"transcode-{job_id}",
        )
        thread.start()
        return self.transcode_status(job_id) or {}

    def transcode_status(self, job_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM transcodes WHERE id=?", (job_id,))

    def _transcode_worker(
        self, job_id: str, row: dict[str, Any], source: Path, ffmpeg: Path
    ) -> None:
        with self._transcode_lock:
            self._execute(
                "UPDATE transcodes SET status='running',progress_message=?,started_at=? WHERE id=?",
                ("正在生成 H.264/AAC 兼容副本", time.time(), job_id),
            )
            try:
                directory = resolve_under(
                    self.runtime.cache_dir, f"compatible/{row['media_id']}"
                )
                directory.mkdir(parents=True, exist_ok=True)
                output = directory / f"{row['id']}.browser.mp4"
                command = [
                    str(ffmpeg),
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                ]
                if self.runtime.transcode_threads > 0:
                    command += ["-threads", str(self.runtime.transcode_threads)]
                command.append(str(output))
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=24 * 3600,
                    check=False,
                )
                if (
                    completed.returncode != 0
                    or not output.is_file()
                    or output.stat().st_size <= 0
                ):
                    raise RuntimeError(
                        (completed.stderr or completed.stdout or "FFmpeg 转码失败")[-2000:]
                    )
                rel = relative_posix(self.runtime.cache_dir, output)
                new_id = _file_id("cache", rel)
                self._execute(
                    "INSERT OR REPLACE INTO media_files(id,media_id,storage,relative_path,filename,size,"
                    "mime_type,kind,is_primary,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        row["media_id"],
                        "cache",
                        rel,
                        output.name,
                        output.stat().st_size,
                        "video/mp4",
                        "compatible",
                        0,
                        time.time(),
                    ),
                )
                self._execute(
                    "UPDATE transcodes SET status='success',progress_message=?,output_file_id=?,"
                    "finished_at=? WHERE id=?",
                    ("兼容副本已生成", new_id, time.time(), job_id),
                )
            except Exception as exc:  # noqa: BLE001
                self._execute(
                    "UPDATE transcodes SET status='failed',progress_message=?,error=?,finished_at=? WHERE id=?",
                    ("兼容副本生成失败", str(exc)[-3000:], time.time(), job_id),
                )

    # Device export --------------------------------------------------
    @property
    def export_root(self) -> Path:
        root = (self.runtime.temp_dir / "exports").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def register_export_task(self, task: dict[str, Any]) -> None:
        now = time.time()
        # The TTL starts when the file is ready. Preparing downloads receive a generous
        # safety window so a large legal download is not deleted while BBDown is running.
        preparing_expiry = now + max(self.runtime.export_ttl_sec, 7 * 24 * 3600)
        payload = dict(task)
        payload["destination"] = "device"
        payload["log_tail"] = str(payload.get("log_tail") or "")[-12_000:]
        self._execute(
            "INSERT OR REPLACE INTO exports(task_id,source_key,title,state,relative_path,filename,size,"
            "created_at,expires_at,downloaded_at,error,task_payload_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task["id"],
                task["key"],
                str(task.get("title") or task.get("bvid") or task["key"])[:500],
                "preparing",
                "",
                "",
                0,
                now,
                preparing_expiry,
                None,
                "",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def export_record(self, task_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM exports WHERE task_id=?", (task_id,))

    def export_task_payload(self, task_id: str) -> dict[str, Any] | None:
        row = self.export_record(task_id)
        if not row:
            return None
        try:
            value = json.loads(str(row.get("task_payload_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def prepare_export(
        self, task_id: str, task: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        row = self.export_record(task_id)
        if not row:
            raise KeyError("设备导出记录不存在")
        if row["state"] == "ready":
            return row
        if row["state"] in {"downloaded", "expired", "discarded"}:
            raise ValueError("设备导出文件已清理")
        task = dict(task or self.export_task_payload(task_id) or {})
        if task.get("status") != "success":
            raise ValueError("导出任务尚未下载完成")
        files: list[Path] = []
        for item in task.get("files") or []:
            rel = str(item.get("path") or "")
            path = resolve_under(self.export_root, rel)
            if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                files.append(path)
        if not files:
            raise FileNotFoundError("导出产物不存在")
        if len(files) == 1:
            path = files[0]
        else:
            package_dir = resolve_under(self.export_root, f"packages/{task_id}")
            package_dir.mkdir(parents=True, exist_ok=True)
            safe = _safe_archive_name(str(row["title"]), task_id)
            path = package_dir / f"{safe}.zip"
            output_rel = str(task.get("output_path") or "")
            output_base = resolve_under(self.export_root, output_rel) if output_rel else None
            used: set[str] = set()
            with zipfile.ZipFile(
                path, "w", compression=zipfile.ZIP_STORED, allowZip64=True
            ) as archive:
                for number, source in enumerate(files, 1):
                    try:
                        arc = source.relative_to(output_base).as_posix() if output_base else source.name
                    except ValueError:
                        arc = source.name
                    if arc in used:
                        arc = f"{number:03d}-{arc}"
                    used.add(arc)
                    archive.write(source, arcname=arc)
        rel = relative_posix(self.export_root, path)
        now = time.time()
        self._execute(
            "UPDATE exports SET state='ready',relative_path=?,filename=?,size=?,expires_at=?,error='' "
            "WHERE task_id=?",
            (
                rel,
                path.name,
                path.stat().st_size,
                now + self.runtime.export_ttl_sec,
                task_id,
            ),
        )
        return self.export_record(task_id) or {}

    def active_export_for_source(self, source_key: str) -> dict[str, Any] | None:
        """Return an unexpired export that still owns the source artifact."""
        now = time.time()
        return self._one(
            "SELECT * FROM exports WHERE source_key=? AND state IN ('preparing','ready') "
            "AND expires_at>? ORDER BY created_at DESC LIMIT 1",
            (source_key, now),
        )

    def resolve_export(self, task_id: str) -> tuple[dict[str, Any], Path]:
        row = self.export_record(task_id)
        if not row:
            raise KeyError("设备导出记录不存在")
        if float(row["expires_at"]) <= time.time() and row["state"] not in {
            "downloaded",
            "expired",
        }:
            self.discard_export(task_id, "expired")
            raise ValueError("设备导出已过期")
        if row["state"] != "ready":
            raise ValueError("设备导出尚未就绪或已经清理")
        path = resolve_under(self.export_root, str(row["relative_path"]))
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("设备导出文件已不存在")
        return row, path

    def _cleanup_export_files(self, row: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        root = self.export_root
        candidates: set[Path] = set()
        rel = str(row.get("relative_path") or "")
        if rel:
            try:
                candidates.add(resolve_under(root, rel))
            except UnsafePathError as exc:
                errors.append(str(exc))
        candidates.add(resolve_under(root, f"packages/{row['task_id']}"))
        export_index = self.export_index
        if export_index is not None:
            try:
                entry = export_index.get(str(row["source_key"]))
                output_rel = str((entry or {}).get("path") or "")
                if output_rel:
                    candidates.add(resolve_under(root, output_rel))
            except (UnsafePathError, UnsafeIndexPathError) as exc:
                errors.append(str(exc))
        # Children first, then empty parents.
        for path in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
            try:
                if not path.exists():
                    continue
                if path.is_symlink():
                    raise UnsafePathError(f"拒绝清理符号链接: {path}")
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.is_file():
                    path.unlink()
                else:
                    raise UnsafePathError(f"拒绝清理特殊文件: {path}")
            except (OSError, UnsafePathError) as exc:
                errors.append(str(exc))
        if export_index is not None:
            try:
                export_index.discard_entry(str(row["source_key"]))
            except (OSError, UnsafePathError) as exc:
                errors.append(str(exc))
        for path in candidates:
            parent = path.parent
            while parent != root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        return errors

    def complete_export(self, task_id: str) -> None:
        row = self.export_record(task_id)
        if not row or row["state"] not in {"ready", "cleanup_pending"}:
            return
        errors = self._cleanup_export_files(row)
        if errors:
            self._execute(
                "UPDATE exports SET state='cleanup_pending',error=? WHERE task_id=?",
                ("; ".join(errors)[-3000:], task_id),
            )
            return
        self._execute(
            "UPDATE exports SET state='downloaded',downloaded_at=?,error='' WHERE task_id=?",
            (time.time(), task_id),
        )

    def discard_export(self, task_id: str, state: str = "discarded") -> bool:
        row = self.export_record(task_id)
        if not row:
            return False
        errors = self._cleanup_export_files(row)
        if errors:
            self._execute(
                "UPDATE exports SET state='cleanup_pending',error=? WHERE task_id=?",
                ("; ".join(errors)[-3000:], task_id),
            )
        else:
            self._execute(
                "UPDATE exports SET state=?,error='' WHERE task_id=?", (state, task_id)
            )
        return True

    # Persistent task history ---------------------------------------
    def _recover_interrupted_records(self) -> None:
        # TaskQueue restores queued records and converts running records to a safe
        # interrupted/failed state. Transcode jobs are not resumable.
        now = time.time()
        self._execute(
            "UPDATE transcodes SET status='failed',progress_message='服务重启中断转码',"
            "error='服务重启中断转码，可重新生成',finished_at=? WHERE status IN ('queued','running')",
            (now,),
        )

    def bind_export_index(self, export_index: IndexStore) -> None:
        self.export_index = export_index

    def load_task_snapshots(self, destination: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        rows = list(
            reversed(
                self._all(
                    "SELECT payload_json FROM task_snapshots WHERE destination=? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (destination, _MAX_PERSISTED_TASKS),
                )
            )
        )
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict):
                result.append(payload)
        return result

    def save_task_snapshot(
        self, destination: str, task_id: str, payload: dict[str, Any] | None
    ) -> None:
        if payload is None:
            self._execute("DELETE FROM task_snapshots WHERE task_id=?", (task_id,))
            self._snapshot_last_write.pop(task_id, None)
            return
        now = time.time()
        value = dict(payload)
        status = str(value.get("status") or "failed")
        # BBDown may refresh progress many times per second. Persisting every
        # terminal-style carriage-return update creates avoidable SQLite WAL
        # traffic on a NAS. One running snapshot per second is sufficient for
        # restart recovery; terminal and queued transitions are always written.
        if status == "running" and now - self._snapshot_last_write.get(task_id, 0.0) < 1.0:
            return
        value["destination"] = destination
        value["log_tail"] = str(value.get("log_tail") or "")[-12_000:]
        self._execute(
            "INSERT INTO task_snapshots(task_id,destination,status,created_at,updated_at,payload_json) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET destination=excluded.destination,"
            "status=excluded.status,updated_at=excluded.updated_at,payload_json=excluded.payload_json",
            (
                task_id,
                destination,
                status,
                float(value.get("created_at") or now),
                now,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        self._snapshot_last_write[task_id] = now
        if status in {"success", "skipped", "failed", "cancelled"} or now - self._last_snapshot_prune >= 60:
            rows = self._all(
                "SELECT task_id FROM task_snapshots ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                (_MAX_PERSISTED_TASKS,),
            )
            for row in rows:
                stale_id = str(row["task_id"])
                self._execute("DELETE FROM task_snapshots WHERE task_id=?", (stale_id,))
                self._snapshot_last_write.pop(stale_id, None)
            self._last_snapshot_prune = now

    def update_export_from_task(
        self, task_id: str, payload: dict[str, Any] | None
    ) -> None:
        if payload is None:
            return
        status = str(payload.get("status") or "")
        # Live progress is served from TaskQueue/SSE. The export table only
        # needs a durable terminal payload; skipping in-flight writes avoids a
        # second SQLite write/read for every console progress refresh.
        if status not in {"success", "failed", "cancelled", "skipped"}:
            return
        row = self.export_record(task_id)
        if not row:
            return
        value = dict(payload)
        value["destination"] = "device"
        value["log_tail"] = str(value.get("log_tail") or "")[-12_000:]
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        if status == "success":
            self._execute(
                "UPDATE exports SET title=?,error='',expires_at=?,task_payload_json=? WHERE task_id=?",
                (
                    str(value.get("title") or row["title"])[:500],
                    now + self.runtime.export_ttl_sec,
                    encoded,
                    task_id,
                ),
            )
        elif status in {"failed", "cancelled", "skipped"}:
            self._execute(
                "UPDATE exports SET state=?,error=?,expires_at=?,task_payload_json=? "
                "WHERE task_id=?",
                (
                    status,
                    str(value.get("error") or value.get("progress_message") or "")[-3000:],
                    now + self.runtime.export_ttl_sec,
                    encoded,
                    task_id,
                ),
            )
        else:
            self._execute(
                "UPDATE exports SET title=?,task_payload_json=? WHERE task_id=?",
                (
                    str(value.get("title") or row["title"])[:500],
                    encoded,
                    task_id,
                ),
            )

    def persist_task_snapshots(self, tasks: list[dict[str, Any]]) -> None:
        now = time.time()
        with self._transaction() as conn:
            for task in tasks:
                task_id = str(task.get("id") or "")
                if not task_id:
                    continue
                payload = dict(task)
                payload["log_tail"] = str(payload.get("log_tail") or "")[-12_000:]
                conn.execute(
                    "INSERT INTO task_snapshots(task_id,destination,status,created_at,updated_at,payload_json) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET destination=excluded.destination,"
                    "status=excluded.status,updated_at=excluded.updated_at,payload_json=excluded.payload_json",
                    (
                        task_id,
                        str(payload.get("destination") or "library"),
                        str(payload.get("status") or "failed"),
                        float(payload.get("created_at") or now),
                        now,
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
            excess = conn.execute(
                "SELECT task_id FROM task_snapshots ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                (_MAX_PERSISTED_TASKS,),
            ).fetchall()
            for row in excess:
                conn.execute("DELETE FROM task_snapshots WHERE task_id=?", (row[0],))

    def task_snapshot(self, task_id: str) -> dict[str, Any] | None:
        row = self._one(
            "SELECT destination,payload_json FROM task_snapshots WHERE task_id=?", (task_id,)
        )
        if not row:
            return None
        try:
            payload = json.loads(str(row["payload_json"]))
        except (json.JSONDecodeError, TypeError):
            return None
        payload["destination"] = str(row["destination"])
        payload["persisted"] = True
        return payload

    def list_task_snapshots(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in self._all(
            "SELECT destination,payload_json FROM task_snapshots ORDER BY updated_at DESC"
        ):
            try:
                payload = json.loads(str(row["payload_json"]))
            except (json.JSONDecodeError, TypeError):
                continue
            payload["destination"] = str(row["destination"])
            payload["persisted"] = True
            result.append(payload)
        return result

    def delete_task_snapshot(self, task_id: str) -> None:
        self._execute("DELETE FROM task_snapshots WHERE task_id=?", (task_id,))

    def clear_finished_task_snapshots(self, keep_ids: set[str] | None = None) -> int:
        keep_ids = keep_ids or set()
        rows = self._all(
            "SELECT task_id FROM task_snapshots WHERE status IN ('success','skipped','failed','cancelled')"
        )
        remove = [str(row["task_id"]) for row in rows if str(row["task_id"]) not in keep_ids]
        with self._transaction() as conn:
            for task_id in remove:
                conn.execute("DELETE FROM task_snapshots WHERE task_id=?", (task_id,))
        return len(remove)

    # Cleaner --------------------------------------------------------
    def _cleanup_loop(self) -> None:
        while not self._stop.wait(60):
            now = time.time()
            try:
                self._execute(
                    "UPDATE sessions SET revoked_at=COALESCE(revoked_at,?),"
                    "revoke_reason=CASE WHEN revoke_reason='' THEN 'expired' ELSE revoke_reason END "
                    "WHERE expires_at<=? AND revoked_at IS NULL",
                    (now, now),
                )
                rows = self._all(
                    "SELECT task_id,state FROM exports WHERE "
                    "((state IN ('preparing','ready','failed','cancelled','skipped') "
                    "AND expires_at<=?) OR state='cleanup_pending')",
                    (now,),
                )
                for row in rows:
                    if row["state"] == "cleanup_pending":
                        self.complete_export(str(row["task_id"]))
                    else:
                        self.discard_export(str(row["task_id"]), "expired")
            except (OSError, sqlite3.Error, ValueError):
                # Cleanup is best effort and must never stop the application.
                continue
