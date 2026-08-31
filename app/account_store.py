from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
import uuid
from typing import Any

from app.auth import (
    ROLE_ADMIN,
    ROLE_USER,
    hash_password,
    is_loopback_address,
    permissions_for_role,
    validate_display_name,
    validate_username,
    verify_password,
)
from app.constants import (
    MAX_ACTIVE_SESSIONS_PER_USER,
    SESSION_ABSOLUTE_DAYS,
    SESSION_TOUCH_INTERVAL_SECONDS,
)
from app.database import (
    DEFAULT_ADMIN_DISPLAY_NAME,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    SYSTEM_DEFAULT_ADMIN,
    Database,
)
from app.io_utils import atomic_write_text
from app.runtime import RuntimeSettings


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthStore:
    """Users, credentials, sessions, and authentication audit records."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.runtime: RuntimeSettings = database.runtime
        self.bootstrap_path = self.runtime.config_dir / "bootstrap-token.txt"
        self._bootstrap_token = ""
        self._login_failures: dict[str, list[float]] = {}
        self._mutation_lock = threading.RLock()
        self._stop = threading.Event()
        self._cleaner = threading.Thread(
            target=self._cleanup_loop,
            name="auth-session-cleaner",
            daemon=True,
        )
        self._ensure_default_admin()
        self._reject_remote_default_password()
        self._ensure_bootstrap()
        self._cleaner.start()

    def close(self) -> None:
        self._stop.set()
        if threading.current_thread() is not self._cleaner:
            self._cleaner.join(timeout=2)

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
        return self.database.one("SELECT 1 AS ok FROM users LIMIT 1") is not None

    def setup_required(self) -> bool:
        return not self.has_users()

    def default_owner_user_id(self) -> str:
        row = self.database.one(
            "SELECT id FROM users WHERE role=? ORDER BY disabled ASC,created_at,id LIMIT 1",
            (ROLE_ADMIN,),
        )
        return str((row or {}).get("id") or "")

    def _ensure_default_admin(self) -> None:
        if (
            self.has_users()
            or self.runtime.mode != "local"
            or not self.runtime.auth_required
        ):
            return
        now = time.time()
        user_id = "usr_" + uuid.uuid4().hex[:24]
        with self.database.transaction() as connection:
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                return
            connection.execute(
                "INSERT INTO users(id,username,password_hash,created_at,updated_at,disabled,"
                "role,display_name,must_change_password,created_by) VALUES(?,?,?,?,?,0,?,?,?,?)",
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
            connection.execute(
                "INSERT INTO audit_log(user_id,action,detail,remote_addr,created_at,"
                "session_id,target_user_id) VALUES(?,?,?,?,?,NULL,NULL)",
                (
                    user_id,
                    "auth.default_admin.create",
                    "创建本机临时管理员",
                    "",
                    now,
                ),
            )

    def _reject_remote_default_password(self) -> None:
        if not self.runtime.server_mode:
            return
        row = self.database.one(
            "SELECT id FROM users WHERE role=? AND disabled=0 AND must_change_password=1 "
            "AND created_by=? LIMIT 1",
            (ROLE_ADMIN, SYSTEM_DEFAULT_ADMIN),
        )
        if row:
            raise RuntimeError("默认管理员密码尚未修改，应用拒绝切换到非回环监听")

    def _ensure_bootstrap(self) -> None:
        if not self.setup_required():
            self.bootstrap_path.unlink(missing_ok=True)
            return
        configured = os.getenv("BILI_BOOTSTRAP_TOKEN", "").strip()
        self._bootstrap_token = configured or secrets.token_urlsafe(24)
        if not configured:
            atomic_write_text(
                self.bootstrap_path,
                self._bootstrap_token + "\n",
                backup=False,
            )
            try:
                self.bootstrap_path.chmod(0o600)
            except OSError:
                pass

    def active_session_count(self, user_id: str) -> int:
        now = time.time()
        row = self.database.one(
            "SELECT COUNT(*) AS n FROM sessions WHERE user_id=? AND revoked_at IS NULL "
            "AND expires_at>?",
            (user_id, now),
        )
        return int((row or {}).get("n") or 0)

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
        display_name: str = DEFAULT_ADMIN_DISPLAY_NAME,
    ) -> dict[str, Any]:
        with self._mutation_lock:
            if self.has_users():
                raise ValueError("管理员已经初始化")
            expected = os.getenv("BILI_BOOTSTRAP_TOKEN", "").strip() or self._bootstrap_token
            if not expected or not hmac.compare_digest(
                str(bootstrap_token or "").strip(), expected
            ):
                raise ValueError("初始化令牌无效")
            username = validate_username(username)
            display_name = validate_display_name(display_name)
            password_hash = hash_password(password)
            now = time.time()
            user_id = "usr_" + uuid.uuid4().hex[:24]
            try:
                with self.database.transaction() as connection:
                    if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                        raise ValueError("管理员已经初始化")
                    connection.execute(
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
                self.database.one("SELECT * FROM users WHERE id=?", (user_id,)) or {}
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
        with self._mutation_lock:
            allowed, retry = self.login_allowed(remote_addr)
            if not allowed:
                raise RuntimeError(f"登录尝试过多，请 {retry} 秒后再试")
            candidate = str(username or "").strip()
            user = self.database.one(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE",
                (candidate,),
            )
            if (
                not user
                or int(user["disabled"])
                or not verify_password(password, str(user["password_hash"]))
            ):
                self.record_login_failure(remote_addr)
                self.audit(None, "auth.login.failed", f"账号={candidate[:32]}", remote_addr)
                raise ValueError("用户名或密码错误")
            if (
                str(user.get("created_by") or "") == SYSTEM_DEFAULT_ADMIN
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
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE users SET last_login_at=?,updated_at=? WHERE id=?",
                    (now, now, session["user_id"]),
                )
                connection.execute(
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
                rows = connection.execute(
                    "SELECT id FROM sessions WHERE user_id=? AND revoked_at IS NULL "
                    "AND expires_at>? ORDER BY last_seen_at ASC,created_at ASC,id ASC",
                    (session["user_id"], now),
                ).fetchall()
                overflow = max(0, len(rows) - MAX_ACTIVE_SESSIONS_PER_USER)
                candidates = [
                    str(row["id"]) for row in rows if str(row["id"]) != session_id
                ]
                evicted = candidates[:overflow]
                if evicted:
                    placeholders = ",".join("?" for _ in evicted)
                    connection.execute(
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
        row = self.database.one(
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
            self.database.execute(
                "UPDATE sessions SET revoked_at=?,revoke_reason='expired' "
                "WHERE id=? AND revoked_at IS NULL",
                (now, row["session_id"]),
            )
            return None
        if now - float(row["last_seen_at"]) >= SESSION_TOUCH_INTERVAL_SECONDS:
            self.database.execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=? AND revoked_at IS NULL",
                (now, row["session_id"]),
            )
            row["last_seen_at"] = now
        row["must_change_password"] = bool(row["must_change_password"])
        return row

    def get_session_by_id(self, session_id: str) -> dict[str, Any] | None:
        now = time.time()
        row = self.database.one(
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
            self.database.execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=? AND revoked_at IS NULL",
                (now, session_id),
            )
            row["last_seen_at"] = now
        return row

    def session_is_active(self, session_id: str) -> bool:
        return self.get_session_by_id(session_id) is not None

    def list_sessions(self, user_id: str, current_session_id: str) -> list[dict[str, Any]]:
        now = time.time()
        rows = self.database.all(
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
        with self._mutation_lock:
            if session_id == current_session_id:
                raise ValueError("不能通过此接口撤销当前设备，请使用退出登录")
            now = time.time()
            cursor = self.database.execute(
                "UPDATE sessions SET revoked_at=?,revoke_reason=? WHERE id=? AND user_id=? "
                "AND revoked_at IS NULL AND expires_at>?",
                (now, reason[:80], session_id, user_id, now),
            )
            return cursor.rowcount > 0

    def revoke_other_sessions(self, user_id: str, current_session_id: str) -> int:
        with self._mutation_lock:
            now = time.time()
            cursor = self.database.execute(
                "UPDATE sessions SET revoked_at=?,revoke_reason='user_revoke_others' "
                "WHERE user_id=? AND id<>? AND revoked_at IS NULL AND expires_at>?",
                (now, user_id, current_session_id, now),
            )
            return int(cursor.rowcount)

    def revoke_all_sessions(self, user_id: str, reason: str) -> int:
        with self._mutation_lock:
            now = time.time()
            cursor = self.database.execute(
                "UPDATE sessions SET revoked_at=?,revoke_reason=? WHERE user_id=? "
                "AND revoked_at IS NULL AND expires_at>?",
                (now, reason[:80], user_id, now),
            )
            return int(cursor.rowcount)

    def logout(self, session_id: str) -> None:
        with self._mutation_lock:
            self.database.execute(
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
        with self._mutation_lock:
            user = self.database.one("SELECT * FROM users WHERE id=?", (user_id,))
            if (
                not user
                or int(user["disabled"])
                or not verify_password(current_password, str(user["password_hash"]))
            ):
                raise ValueError("当前密码错误")
            if hmac.compare_digest(current_password, new_password):
                raise ValueError("新密码不能与当前密码相同")
            encoded = hash_password(new_password)
            token = secrets.token_urlsafe(48)
            csrf_token = secrets.token_urlsafe(32)
            now = time.time()
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE users SET password_hash=?,must_change_password=0,updated_at=? "
                    "WHERE id=?",
                    (encoded, now, user_id),
                )
                row = connection.execute(
                    "SELECT COUNT(*) FROM sessions WHERE user_id=? AND id<>? "
                    "AND revoked_at IS NULL AND expires_at>?",
                    (user_id, keep_session_id, now),
                ).fetchone()
                connection.execute(
                    "UPDATE sessions SET revoked_at=?,revoke_reason='password_change' "
                    "WHERE user_id=? AND id<>? AND revoked_at IS NULL AND expires_at>?",
                    (now, user_id, keep_session_id, now),
                )
                cursor = connection.execute(
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
        self.database.execute(
            "UPDATE users SET display_name=?,updated_at=? WHERE id=? AND disabled=0",
            (display_name, time.time(), user_id),
        )
        user = self.database.one("SELECT * FROM users WHERE id=?", (user_id,))
        if not user:
            raise KeyError("用户不存在")
        return self._public_user(user)

    def list_users(self) -> list[dict[str, Any]]:
        now = time.time()
        rows = self.database.all(
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
        with self._mutation_lock:
            username = validate_username(username)
            display_name = validate_display_name(display_name)
            encoded = hash_password(temporary_password)
            now = time.time()
            user_id = "usr_" + uuid.uuid4().hex[:24]
            try:
                self.database.execute(
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
                self.database.one("SELECT * FROM users WHERE id=?", (user_id,)) or {}
            )

    def set_user_display_name(self, user_id: str, display_name: str) -> dict[str, Any]:
        return self.update_profile(user_id, display_name)

    def set_user_disabled(
        self, user_id: str, disabled: bool, *, actor_user_id: str
    ) -> dict[str, Any]:
        with self._mutation_lock:
            user = self.database.one("SELECT * FROM users WHERE id=?", (user_id,))
            if not user:
                raise KeyError("用户不存在")
            if str(user["role"]) == ROLE_ADMIN:
                raise ValueError("不能禁用当前管理员")
            self.database.execute(
                "UPDATE users SET disabled=?,updated_at=? WHERE id=?",
                (1 if disabled else 0, time.time(), user_id),
            )
            if disabled:
                self.revoke_all_sessions(user_id, "user_disabled")
            updated = self.database.one("SELECT * FROM users WHERE id=?", (user_id,)) or user
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
        with self._mutation_lock:
            user = self.database.one("SELECT * FROM users WHERE id=?", (user_id,))
            if not user:
                raise KeyError("用户不存在")
            if str(user["role"]) == ROLE_ADMIN and user_id == actor_user_id:
                raise ValueError("管理员请使用修改自己密码接口")
            encoded = hash_password(temporary_password)
            now = time.time()
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE users SET password_hash=?,must_change_password=1,updated_at=? "
                    "WHERE id=?",
                    (encoded, now, user_id),
                )
                cursor = connection.execute(
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
            updated = self.database.one("SELECT * FROM users WHERE id=?", (user_id,)) or user
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
        self.database.execute(
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

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(60):
            now = time.time()
            try:
                self.database.execute(
                    "UPDATE sessions SET revoked_at=COALESCE(revoked_at,?),"
                    "revoke_reason=CASE WHEN revoke_reason='' THEN 'expired' ELSE revoke_reason END "
                    "WHERE expires_at<=? AND revoked_at IS NULL",
                    (now, now),
                )
            except sqlite3.Error:
                continue
