from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.auth import ROLE_ADMIN, ROLE_USER
from app.constants import (
    ADMIN_TASK_HISTORY_LIMIT,
    DATABASE_SCHEMA_VERSION,
    NORMAL_USER_TASK_HISTORY_LIMIT,
    NORMAL_USER_TASK_RETENTION_DAYS,
    TERMINAL_STATUSES,
)
from app.serialized_auth_store import SerializedAuthNasStore
from app.task_logs import delete_task_log, read_task_log

_MAX_LOADED_TASKS = 5000
_PROTECTED_EXPORT_STATES = {"preparing", "ready", "cleanup_pending"}


class TaskOwnershipNasStore(SerializedAuthNasStore):
    """Schema v4 persistence for per-user task and export ownership."""

    def _apply_schema_locked(self) -> None:
        super()._apply_schema_locked()
        self._add_column_locked("exports", "owner_user_id", "TEXT")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_records(
              id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
              destination TEXT NOT NULL CHECK(destination IN ('library','device')),
              source_key TEXT NOT NULL DEFAULT '',
              bvid TEXT,
              title TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              created_at REAL NOT NULL,
              started_at REAL,
              finished_at REAL,
              updated_at REAL NOT NULL,
              payload_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )

    def _admin_user_id_locked(self) -> str:
        row = self._conn.execute(
            "SELECT id FROM users WHERE role=? ORDER BY disabled ASC,created_at,id LIMIT 1",
            (ROLE_ADMIN,),
        ).fetchone()
        return str(row[0]) if row else ""

    def _valid_owner_locked(self, owner_user_id: str) -> str:
        owner = str(owner_user_id or "")
        if owner:
            row = self._conn.execute("SELECT id FROM users WHERE id=?", (owner,)).fetchone()
            if row:
                return owner
        return self._admin_user_id_locked()

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
            self._add_column_locked("exports", "owner_user_id", "TEXT")

            # PR 2 account migration must only run when crossing schema v3. A later
            # task-only migration must not revoke every valid login again.
            if had_existing and old_version < 3:
                users = self._conn.execute(
                    "SELECT id,username,created_at,disabled FROM users "
                    "ORDER BY disabled ASC,created_at,id"
                ).fetchall()
                if users:
                    admin_id = str(users[0]["id"])
                    self._conn.execute(
                        "UPDATE users SET role=?,display_name=CASE WHEN TRIM(display_name)='' "
                        "THEN ? ELSE display_name END WHERE id=?",
                        (ROLE_ADMIN, "管理员", admin_id),
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

            if had_existing and old_version < 4:
                admin_id = self._admin_user_id_locked()
                if not admin_id:
                    raise sqlite3.IntegrityError("任务所有权迁移找不到管理员账号")
                rows = self._conn.execute(
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
                    owner = self._valid_owner_locked(
                        str(payload.get("owner_user_id") or admin_id)
                    )
                    payload["owner_user_id"] = owner
                    destination = str(row["destination"] or "library")
                    payload["destination"] = destination
                    status = str(payload.get("status") or row["status"] or "failed")
                    created_at = float(payload.get("created_at") or row["created_at"] or time.time())
                    updated_at = float(row["updated_at"] or created_at)
                    finished_at = payload.get("finished_at")
                    self._conn.execute(
                        "INSERT OR REPLACE INTO task_records(id,owner_user_id,destination,source_key,bvid,"
                        "title,status,created_at,started_at,finished_at,updated_at,payload_json) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(row["task_id"]),
                            owner,
                            destination,
                            str(payload.get("key") or payload.get("source_key") or ""),
                            payload.get("bvid"),
                            str(payload.get("title") or payload.get("display_title") or "")[:500],
                            status,
                            created_at,
                            payload.get("started_at"),
                            finished_at,
                            updated_at,
                            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                self._conn.execute(
                    "UPDATE exports SET owner_user_id=? "
                    "WHERE owner_user_id IS NULL OR TRIM(owner_user_id)=''",
                    (admin_id,),
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
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_records_owner_created "
                "ON task_records(owner_user_id,created_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_records_owner_finished "
                "ON task_records(owner_user_id,finished_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_records_owner_status "
                "ON task_records(owner_user_id,status)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_records_destination_status "
                "ON task_records(destination,status)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_exports_owner_source "
                "ON exports(owner_user_id,source_key,state,expires_at)"
            )
            self._conn.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION}")
            errors = self._conn.execute("PRAGMA foreign_key_check").fetchall()
            if errors:
                raise sqlite3.IntegrityError(
                    "迁移后外键检查失败: "
                    + "; ".join(str(tuple(row)) for row in errors[:5])
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def default_owner_user_id(self) -> str:
        with self._lock:
            return self._admin_user_id_locked()

    def count_active_tasks(self, owner_user_id: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM task_records WHERE owner_user_id=? "
            "AND status IN ('queued','running')",
            (owner_user_id,),
        )
        return int((row or {}).get("n") or 0)

    @staticmethod
    def _decode_payload(row: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _record_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = self._decode_payload(row)
        payload.update(
            {
                "id": str(row["id"]),
                "owner_user_id": str(row["owner_user_id"]),
                "destination": str(row["destination"]),
                "key": str(payload.get("key") or row.get("source_key") or ""),
                "bvid": payload.get("bvid") or row.get("bvid"),
                "title": str(payload.get("title") or row.get("title") or ""),
                "status": str(row["status"]),
                "created_at": float(row["created_at"]),
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
                "updated_at": float(row["updated_at"]),
                "persisted": True,
            }
        )
        username = str(row.get("username") or "")
        display_name = str(row.get("display_name") or "")
        role = str(row.get("role") or "")
        if username or display_name:
            payload["owner"] = {
                "id": str(row["owner_user_id"]),
                "username": username,
                "display_name": display_name,
                "role": role,
            }
            payload["owner_label"] = (
                f"{display_name}（{username}）" if display_name else username
            )
        return payload

    def load_task_snapshots(self, destination: str) -> list[dict[str, Any]]:
        self.cleanup_task_history()
        rows = self._all(
            "SELECT tr.*,u.username,u.display_name,u.role FROM task_records tr "
            "LEFT JOIN users u ON u.id=tr.owner_user_id WHERE tr.destination=? "
            "ORDER BY tr.created_at ASC,tr.id ASC LIMIT ?",
            (destination, _MAX_LOADED_TASKS),
        )
        return [self._record_payload(row) for row in rows]

    def save_task_snapshot(
        self, destination: str, task_id: str, payload: dict[str, Any] | None
    ) -> None:
        if payload is None:
            self._execute("DELETE FROM task_records WHERE id=?", (task_id,))
            self._execute("DELETE FROM task_snapshots WHERE task_id=?", (task_id,))
            self._snapshot_last_write.pop(task_id, None)
            return
        now = time.time()
        value = dict(payload)
        status = str(value.get("status") or "failed")
        if status == "running" and now - self._snapshot_last_write.get(task_id, 0.0) < 1.0:
            return
        existing = self._one(
            "SELECT owner_user_id FROM task_records WHERE id=?", (task_id,)
        )
        owner = str((existing or {}).get("owner_user_id") or value.get("owner_user_id") or "")
        if not owner:
            owner = self.default_owner_user_id()
        if not owner:
            raise sqlite3.IntegrityError("任务拥有者不能为空")
        value["owner_user_id"] = owner
        value["destination"] = destination
        value["log_tail"] = str(value.get("log_tail") or "")[-12_000:]
        created_at = float(value.get("created_at") or now)
        finished_at = value.get("finished_at")
        if status in TERMINAL_STATUSES and finished_at is None:
            finished_at = now
            value["finished_at"] = now
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self._execute(
            "INSERT INTO task_records(id,owner_user_id,destination,source_key,bvid,title,status,"
            "created_at,started_at,finished_at,updated_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET destination=excluded.destination,source_key=excluded.source_key,"
            "bvid=excluded.bvid,title=excluded.title,status=excluded.status,started_at=excluded.started_at,"
            "finished_at=excluded.finished_at,updated_at=excluded.updated_at,payload_json=excluded.payload_json",
            (
                task_id,
                owner,
                destination,
                str(value.get("source_key") or value.get("key") or ""),
                value.get("bvid"),
                str(value.get("title") or value.get("display_title") or "")[:500],
                status,
                created_at,
                value.get("started_at"),
                finished_at,
                now,
                encoded,
            ),
        )
        self._snapshot_last_write[task_id] = now
        if status in TERMINAL_STATUSES or now - self._last_snapshot_prune >= 60:
            self.cleanup_task_history(now=now, owner_user_id=owner)
            self._last_snapshot_prune = now

    def task_record(self, task_id: str) -> dict[str, Any] | None:
        row = self._one(
            "SELECT tr.*,u.username,u.display_name,u.role FROM task_records tr "
            "LEFT JOIN users u ON u.id=tr.owner_user_id WHERE tr.id=?",
            (task_id,),
        )
        return self._record_payload(row) if row else None

    def task_snapshot(self, task_id: str) -> dict[str, Any] | None:
        return self.task_record(task_id)

    def list_task_records(
        self,
        *,
        owner_user_id: str | None = None,
        status: str = "",
        destination: str = "",
        query: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_user_id is not None:
            clauses.append("tr.owner_user_id=?")
            params.append(owner_user_id)
        if status:
            clauses.append("tr.status=?")
            params.append(status)
        if destination:
            clauses.append("tr.destination=?")
            params.append(destination)
        if query.strip():
            needle = f"%{query.strip()}%"
            clauses.append(
                "(tr.title LIKE ? OR tr.bvid LIKE ? OR tr.source_key LIKE ? "
                "OR u.username LIKE ? OR u.display_name LIKE ?)"
            )
            params.extend([needle] * 5)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        order_column = {
            "created_at": "tr.created_at",
            "finished_at": "COALESCE(tr.finished_at,0)",
            "user": "u.display_name COLLATE NOCASE",
            "status": "tr.status",
            "destination": "tr.destination",
        }.get(sort, "tr.created_at")
        order_direction = "ASC" if direction.lower() == "asc" else "DESC"
        rows = self._all(
            "SELECT tr.*,u.username,u.display_name,u.role FROM task_records tr "
            "LEFT JOIN users u ON u.id=tr.owner_user_id "
            f"{where} ORDER BY {order_column} {order_direction},tr.created_at DESC,tr.id DESC LIMIT ?",
            tuple([*params, max(1, min(5000, int(limit)))]),
        )
        return [self._record_payload(row) for row in rows]

    def list_task_snapshots(self) -> list[dict[str, Any]]:
        return self.list_task_records(limit=_MAX_LOADED_TASKS)

    def task_owner_user_id(self, task_id: str) -> str:
        row = self._one("SELECT owner_user_id FROM task_records WHERE id=?", (task_id,))
        return str((row or {}).get("owner_user_id") or "")

    def delete_task_snapshot(self, task_id: str) -> None:
        self._execute("DELETE FROM task_records WHERE id=?", (task_id,))
        self._execute("DELETE FROM task_snapshots WHERE task_id=?", (task_id,))

    def clear_finished_task_snapshots(self, keep_ids: set[str] | None = None) -> int:
        keep_ids = keep_ids or set()
        rows = self._all(
            "SELECT id FROM task_records WHERE status IN ('success','skipped','failed','cancelled')"
        )
        remove = [str(row["id"]) for row in rows if str(row["id"]) not in keep_ids]
        for task_id in remove:
            self.delete_task_snapshot(task_id)
        return len(remove)

    def persist_task_snapshots(self, tasks: list[dict[str, Any]]) -> None:
        for task in tasks:
            task_id = str(task.get("id") or "")
            if task_id:
                self.save_task_snapshot(
                    str(task.get("destination") or "library"), task_id, task
                )

    def register_export_task(self, task: dict[str, Any]) -> None:
        now = time.time()
        owner = str(task.get("owner_user_id") or self.default_owner_user_id())
        if not owner:
            raise sqlite3.IntegrityError("导出任务拥有者不能为空")
        preparing_expiry = now + max(self.runtime.export_ttl_sec, 7 * 24 * 3600)
        payload = dict(task)
        payload["owner_user_id"] = owner
        payload["destination"] = "device"
        source_key = str(payload.get("source_key") or payload.get("key") or "")
        payload["log_tail"] = str(payload.get("log_tail") or "")[-12_000:]
        self._execute(
            "INSERT OR REPLACE INTO exports(task_id,owner_user_id,source_key,title,state,relative_path,"
            "filename,size,created_at,expires_at,downloaded_at,error,task_payload_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task["id"],
                owner,
                source_key,
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

    def _cleanup_export_files(self, row: dict[str, Any]) -> list[str]:
        value = dict(row)
        try:
            payload = json.loads(str(value.get("task_payload_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if isinstance(payload, dict):
            queue_key = str(payload.get("_queue_key") or "")
            if queue_key:
                value["source_key"] = queue_key
        return super()._cleanup_export_files(value)

    def active_export_for_source(
        self, source_key: str, owner_user_id: str | None = None
    ) -> dict[str, Any] | None:
        now = time.time()
        if owner_user_id is None:
            return self._one(
                "SELECT * FROM exports WHERE source_key=? AND state IN ('preparing','ready') "
                "AND expires_at>? ORDER BY created_at DESC LIMIT 1",
                (source_key, now),
            )
        return self._one(
            "SELECT * FROM exports WHERE owner_user_id=? AND source_key=? "
            "AND state IN ('preparing','ready') AND expires_at>? "
            "ORDER BY created_at DESC LIMIT 1",
            (owner_user_id, source_key, now),
        )

    def task_log(self, task_id: str, *, tail_chars: int | None = None) -> dict[str, object]:
        record = self.task_record(task_id)
        if not record:
            raise KeyError("任务不存在")
        root: Path = (
            self.export_root
            if str(record.get("destination") or "") == "device"
            else self.runtime.media_dir
        )
        return read_task_log(root, task_id, tail_chars=tail_chars)

    def cleanup_task_history(
        self, *, now: float | None = None, owner_user_id: str | None = None
    ) -> int:
        current = float(now if now is not None else time.time())
        user_rows = self._all(
            "SELECT id,role FROM users" + (" WHERE id=?" if owner_user_id else ""),
            (owner_user_id,) if owner_user_id else (),
        )
        stale: set[str] = set()
        for user in user_rows:
            user_id = str(user["id"])
            role = str(user.get("role") or ROLE_USER)
            terminal = self._all(
                "SELECT tr.id,tr.destination,tr.finished_at,tr.created_at,e.state AS export_state "
                "FROM task_records tr LEFT JOIN exports e ON e.task_id=tr.id "
                "WHERE tr.owner_user_id=? AND tr.status IN ('success','skipped','failed','cancelled') "
                "ORDER BY COALESCE(tr.finished_at,tr.created_at) DESC,tr.created_at DESC,tr.id DESC",
                (user_id,),
            )
            removable = [
                row
                for row in terminal
                if str(row.get("export_state") or "") not in _PROTECTED_EXPORT_STATES
            ]
            if role == ROLE_ADMIN:
                stale.update(str(row["id"]) for row in removable[ADMIN_TASK_HISTORY_LIMIT:])
                continue
            cutoff = current - NORMAL_USER_TASK_RETENTION_DAYS * 24 * 3600
            stale.update(
                str(row["id"])
                for row in removable
                if float(row.get("finished_at") or row.get("created_at") or 0) < cutoff
            )
            kept = [row for row in removable if str(row["id"]) not in stale]
            stale.update(
                str(row["id"])
                for row in kept[NORMAL_USER_TASK_HISTORY_LIMIT:]
            )

        for task_id in sorted(stale):
            row = self._one(
                "SELECT destination FROM task_records WHERE id=?", (task_id,)
            )
            if not row:
                continue
            export = self.export_record(task_id)
            if export and str(export.get("state") or "") in _PROTECTED_EXPORT_STATES:
                continue
            if export:
                try:
                    super().discard_export(task_id, "expired")
                except (OSError, ValueError):
                    continue
                self._execute("DELETE FROM exports WHERE task_id=?", (task_id,))
            root = self.export_root if row["destination"] == "device" else self.runtime.media_dir
            try:
                delete_task_log(root, task_id)
            except (OSError, ValueError):
                pass
            with self._transaction() as conn:
                conn.execute("DELETE FROM task_records WHERE id=?", (task_id,))
                conn.execute("DELETE FROM task_snapshots WHERE task_id=?", (task_id,))
                conn.execute(
                    "DELETE FROM audit_log WHERE action LIKE 'download.%' AND detail LIKE ?",
                    (f"%task={task_id}%",),
                )
            self._snapshot_last_write.pop(task_id, None)
        return len(stale)

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
                self.cleanup_task_history(now=now)
            except (OSError, sqlite3.Error, ValueError):
                continue
