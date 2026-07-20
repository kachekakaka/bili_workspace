from __future__ import annotations

import time
import uuid

from app.auth import ROLE_ADMIN
from app.nas import (
    _DEFAULT_ADMIN_DISPLAY_NAME,
    _DEFAULT_ADMIN_PASSWORD,
    _DEFAULT_ADMIN_USERNAME,
    _SYSTEM_DEFAULT_ADMIN,
    _hash_password,
)
from app.task_ownership_store import TaskOwnershipNasStore


class MigrationSafeTaskOwnershipNasStore(TaskOwnershipNasStore):
    """Repair a valid pre-V0.6 local database that has no website users.

    V0.5 local mode did not require a website account, so a schema-v2 database
    could legitimately contain media/tasks while its ``users`` table remained
    empty. Schema-v4 task ownership migration needs an administrator owner
    before ``NasStore.__init__`` later reaches its normal default-admin setup.

    The parent migration calls ``_admin_user_id_locked`` while its transaction
    is active. Creating the restricted local default administrator here keeps
    account creation, legacy owner reassignment and the schema bump atomic. A
    server/NAS database is not auto-bootstrapped and continues to require its
    explicit setup token.
    """

    def _admin_user_id_locked(self) -> str:
        admin_id = super()._admin_user_id_locked()
        if admin_id or self.runtime.mode != "local":
            return admin_id
        if self._conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return ""

        now = time.time()
        user_id = "usr_" + uuid.uuid4().hex[:24]
        self._conn.execute(
            "INSERT INTO users(id,username,password_hash,created_at,updated_at,disabled,"
            "role,display_name,must_change_password,created_by) "
            "VALUES(?,?,?,?,?,0,?,?,?,?)",
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
        self._conn.execute(
            "UPDATE watch_progress SET user_id=? WHERE user_id IN ('local','')",
            (user_id,),
        )
        self._conn.execute(
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
