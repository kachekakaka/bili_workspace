from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from app.auth import ROLE_ADMIN, ROLE_USER
from app.constants import (
    ADMIN_TASK_HISTORY_LIMIT,
    NORMAL_USER_TASK_HISTORY_LIMIT,
    NORMAL_USER_TASK_RETENTION_DAYS,
    TERMINAL_STATUSES,
)
from app.database import Database
from app.index_store import IndexStore, UnsafeIndexPathError
from app.path_safety import UnsafePathError, relative_posix, resolve_under
from app.task_logs import delete_task_log, read_task_log

_MAX_LOADED_TASKS = 5000
_PROTECTED_EXPORT_STATES = {"preparing", "ready", "cleanup_pending"}


def _safe_archive_name(value: str, fallback: str) -> str:
    result = "".join(
        character
        if character not in '\\/:*?"<>|' and ord(character) >= 32
        else "-"
        for character in value
    )
    result = result[:140].strip(" .-")
    return result or fallback


class TaskStore:
    """Task records, device exports, retention, and persisted task logs."""

    def __init__(self, database: Database, export_index: IndexStore) -> None:
        self.database = database
        self.runtime = database.runtime
        self.export_index = export_index
        self._snapshot_last_write: dict[str, float] = {}
        self._snapshot_last_status: dict[str, str] = {}
        self._last_snapshot_prune = 0.0
        self._stop = threading.Event()
        self._cleaner = threading.Thread(
            target=self._cleanup_loop,
            name="task-export-cleaner",
            daemon=True,
        )
        self._cleaner.start()

    def close(self) -> None:
        self._stop.set()
        if threading.current_thread() is not self._cleaner:
            self._cleaner.join(timeout=2)

    @property
    def export_root(self) -> Path:
        root = (self.runtime.temp_dir / "exports").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def default_owner_user_id(self) -> str:
        row = self.database.one(
            "SELECT id FROM users WHERE role=? ORDER BY disabled ASC,created_at,id LIMIT 1",
            (ROLE_ADMIN,),
        )
        return str((row or {}).get("id") or "")

    def count_active_tasks(self, owner_user_id: str) -> int:
        row = self.database.one(
            "SELECT COUNT(*) AS n FROM task_records WHERE owner_user_id=? "
            "AND status IN ('queued','running')",
            (owner_user_id,),
        )
        return int((row or {}).get("n") or 0)

    def device_download_history_for_sources(
        self,
        owner_user_id: str,
        source_keys: list[str],
    ) -> dict[str, float]:
        keys = list(dict.fromkeys(str(key or "").strip() for key in source_keys))
        keys = [key for key in keys if key]
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        rows = self.database.all(
            "SELECT source_key,downloaded_at FROM device_download_history "
            f"WHERE owner_user_id=? AND source_key IN ({placeholders})",
            tuple([str(owner_user_id), *keys]),
        )
        return {
            str(row["source_key"]): float(row["downloaded_at"])
            for row in rows
        }

    def export_states_for_sources(
        self,
        owner_user_id: str,
        source_keys: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        keys = list(dict.fromkeys(str(key or "").strip() for key in source_keys))
        keys = [key for key in keys if key]
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        rows = self.database.all(
            "SELECT e.*,tr.status AS task_status FROM exports e "
            "LEFT JOIN task_records tr ON tr.id=e.task_id "
            f"WHERE e.owner_user_id=? AND e.source_key IN ({placeholders}) "
            "ORDER BY e.created_at DESC,e.task_id DESC",
            tuple([str(owner_user_id), *keys]),
        )
        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(str(row["source_key"]), []).append(row)
        return result

    @staticmethod
    def _decode_payload(row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("payload_json")
        if raw is None:
            raw = row.get("task_payload_json")
        try:
            payload = json.loads(str(raw or "{}"))
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
                "source_key": str(
                    payload.get("source_key") or row.get("source_key") or ""
                ),
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
        rows = self.database.all(
            "SELECT tr.*,u.username,u.display_name,u.role FROM task_records tr "
            "LEFT JOIN users u ON u.id=tr.owner_user_id WHERE tr.destination=? "
            "ORDER BY tr.created_at ASC,tr.id ASC LIMIT ?",
            (destination, _MAX_LOADED_TASKS),
        )
        return [self._record_payload(row) for row in rows]

    def save_task_snapshot(
        self,
        destination: str,
        task_id: str,
        payload: dict[str, Any] | None,
    ) -> None:
        if payload is None:
            with self.database.transaction() as connection:
                connection.execute("DELETE FROM task_records WHERE id=?", (task_id,))
                connection.execute(
                    "DELETE FROM task_snapshots WHERE task_id=?",
                    (task_id,),
                )
            self._snapshot_last_write.pop(task_id, None)
            self._snapshot_last_status.pop(task_id, None)
            return
        now = time.time()
        value = dict(payload)
        status = str(value.get("status") or "failed")
        if (
            status == "running"
            and self._snapshot_last_status.get(task_id) == "running"
            and now - self._snapshot_last_write.get(task_id, 0.0) < 1.0
        ):
            return
        existing = self.database.one(
            "SELECT owner_user_id,created_at FROM task_records WHERE id=?",
            (task_id,),
        )
        owner = str(
            (existing or {}).get("owner_user_id")
            or value.get("owner_user_id")
            or self.default_owner_user_id()
        )
        if not owner:
            raise sqlite3.IntegrityError("任务拥有者不能为空")
        value["owner_user_id"] = owner
        value["destination"] = destination
        value["log_tail"] = str(value.get("log_tail") or "")[-12_000:]
        created_at = float((existing or {}).get("created_at") or value.get("created_at") or now)
        value["created_at"] = created_at
        finished_at = value.get("finished_at")
        if status in TERMINAL_STATUSES and finished_at is None:
            finished_at = now
            value["finished_at"] = now
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self.database.execute(
            "INSERT INTO task_records(id,owner_user_id,destination,source_key,bvid,title,status,"
            "created_at,started_at,finished_at,updated_at,payload_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "destination=excluded.destination,source_key=excluded.source_key,bvid=excluded.bvid,"
            "title=excluded.title,status=excluded.status,started_at=excluded.started_at,"
            "finished_at=excluded.finished_at,updated_at=excluded.updated_at,"
            "payload_json=excluded.payload_json",
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
        self._snapshot_last_status[task_id] = status
        if status in TERMINAL_STATUSES or now - self._last_snapshot_prune >= 60:
            self.cleanup_task_history(now=now, owner_user_id=owner)
            self._last_snapshot_prune = now

    def task_record(self, task_id: str) -> dict[str, Any] | None:
        row = self.database.one(
            "SELECT tr.*,u.username,u.display_name,u.role FROM task_records tr "
            "LEFT JOIN users u ON u.id=tr.owner_user_id WHERE tr.id=?",
            (task_id,),
        )
        return self._record_payload(row) if row else None

    def task_snapshot(self, task_id: str) -> dict[str, Any] | None:
        return self.task_record(task_id)

    def task_status_summary(self, owner_user_id: str | None = None) -> dict[str, int]:
        params: tuple[Any, ...] = ()
        where = ""
        if owner_user_id is not None:
            where = " WHERE owner_user_id=?"
            params = (str(owner_user_id),)
        rows = self.database.all(
            f"SELECT status,COUNT(*) AS n FROM task_records{where} GROUP BY status",
            params,
        )
        counts = {str(row["status"]): int(row["n"] or 0) for row in rows}
        return {
            "all": sum(counts.values()),
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "success": counts.get("success", 0),
            "skipped": counts.get("skipped", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "active": counts.get("queued", 0) + counts.get("running", 0),
        }

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
        rows = self.database.all(
            "SELECT tr.*,u.username,u.display_name,u.role FROM task_records tr "
            "LEFT JOIN users u ON u.id=tr.owner_user_id "
            f"{where} ORDER BY {order_column} {order_direction},"
            "tr.created_at DESC,tr.id DESC LIMIT ?",
            tuple([*params, max(1, min(5000, int(limit)))]),
        )
        return [self._record_payload(row) for row in rows]

    def list_task_snapshots(self) -> list[dict[str, Any]]:
        return self.list_task_records(limit=_MAX_LOADED_TASKS)

    def task_owner_user_id(self, task_id: str) -> str:
        row = self.database.one(
            "SELECT owner_user_id FROM task_records WHERE id=?",
            (task_id,),
        )
        return str((row or {}).get("owner_user_id") or "")

    def delete_task_snapshot(self, task_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM task_records WHERE id=?", (task_id,))
            connection.execute("DELETE FROM task_snapshots WHERE task_id=?", (task_id,))
        self._snapshot_last_write.pop(task_id, None)
        self._snapshot_last_status.pop(task_id, None)

    def clear_finished_task_snapshots(self, keep_ids: set[str] | None = None) -> int:
        keep_ids = keep_ids or set()
        rows = self.database.all(
            "SELECT id FROM task_records WHERE status IN "
            "('success','skipped','failed','cancelled')"
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
                    str(task.get("destination") or "library"),
                    task_id,
                    task,
                )

    def register_task_batch(
        self,
        destination: str,
        tasks: list[dict[str, Any]],
    ) -> list[str]:
        if destination not in {"library", "device"}:
            raise ValueError("下载目标无效")
        prepared: list[tuple[str, dict[str, Any], str, float, str]] = []
        now = time.time()
        for task in tasks:
            task_id = str(task.get("id") or "")
            owner = str(task.get("owner_user_id") or "")
            if not task_id or not owner:
                raise sqlite3.IntegrityError("批量任务 ID 和拥有者不能为空")
            value = dict(task)
            value["owner_user_id"] = owner
            value["destination"] = destination
            value["log_tail"] = str(value.get("log_tail") or "")[-12_000:]
            created_at = float(value.get("created_at") or now)
            value["created_at"] = created_at
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            prepared.append((task_id, value, owner, created_at, encoded))

        with self.database.transaction() as connection:
            for task_id, value, owner, created_at, encoded in prepared:
                connection.execute(
                    "INSERT INTO task_records(id,owner_user_id,destination,source_key,bvid,"
                    "title,status,created_at,started_at,finished_at,updated_at,payload_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        task_id,
                        owner,
                        destination,
                        str(value.get("source_key") or value.get("key") or ""),
                        value.get("bvid"),
                        str(value.get("title") or value.get("display_title") or "")[:500],
                        str(value.get("status") or "queued"),
                        created_at,
                        value.get("started_at"),
                        value.get("finished_at"),
                        now,
                        encoded,
                    ),
                )
                if destination == "device":
                    preparing_expiry = now + max(
                        self.runtime.export_ttl_sec, 7 * 24 * 3600
                    )
                    source_key = str(value.get("source_key") or value.get("key") or "")
                    connection.execute(
                        "INSERT INTO exports(task_id,owner_user_id,source_key,title,state,"
                        "relative_path,filename,size,created_at,expires_at,downloaded_at,error,"
                        "task_payload_json,cleanup_target_state) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            task_id,
                            owner,
                            source_key,
                            str(value.get("title") or value.get("bvid") or source_key)[:500],
                            "preparing",
                            "",
                            "",
                            0,
                            now,
                            preparing_expiry,
                            None,
                            "",
                            encoded,
                            "",
                        ),
                    )
        return [item[0] for item in prepared]

    def rollback_registered_batch(self, task_ids: list[str]) -> None:
        ids = [str(task_id) for task_id in task_ids if str(task_id)]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.database.transaction() as connection:
            connection.execute(
                f"DELETE FROM exports WHERE task_id IN ({placeholders})",
                tuple(ids),
            )
            connection.execute(
                f"DELETE FROM task_records WHERE id IN ({placeholders})",
                tuple(ids),
            )
            connection.execute(
                f"DELETE FROM task_snapshots WHERE task_id IN ({placeholders})",
                tuple(ids),
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
        self.database.execute(
            "INSERT OR REPLACE INTO exports(task_id,owner_user_id,source_key,title,state,"
            "relative_path,filename,size,created_at,expires_at,downloaded_at,error,"
            "task_payload_json,cleanup_target_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task["id"],
                owner,
                source_key,
                str(task.get("title") or task.get("bvid") or source_key)[:500],
                "preparing",
                "",
                "",
                0,
                now,
                preparing_expiry,
                None,
                "",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "",
            ),
        )

    def export_record(self, task_id: str) -> dict[str, Any] | None:
        return self.database.one("SELECT * FROM exports WHERE task_id=?", (task_id,))

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
        self,
        task_id: str,
        task: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.export_record(task_id)
        if not row:
            raise KeyError("设备导出记录不存在")
        if row["state"] == "ready":
            return row
        if row["state"] in {"downloaded", "expired", "discarded", "cleanup_pending"}:
            raise ValueError("设备导出文件已清理")
        task = dict(task or self.export_task_payload(task_id) or {})
        if task.get("status") != "success":
            raise ValueError("导出任务尚未下载完成")
        files: list[Path] = []
        for item in task.get("files") or []:
            relative_path = str(item.get("path") or "")
            path = resolve_under(self.export_root, relative_path)
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
            output_relative = str(task.get("output_path") or "")
            output_base = (
                resolve_under(self.export_root, output_relative)
                if output_relative
                else None
            )
            used: set[str] = set()
            with zipfile.ZipFile(
                path,
                "w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                for number, source in enumerate(files, 1):
                    try:
                        arcname = (
                            source.relative_to(output_base).as_posix()
                            if output_base
                            else source.name
                        )
                    except ValueError:
                        arcname = source.name
                    if arcname in used:
                        arcname = f"{number:03d}-{arcname}"
                    used.add(arcname)
                    archive.write(source, arcname=arcname)
        relative_path = relative_posix(self.export_root, path)
        now = time.time()
        self.database.execute(
            "UPDATE exports SET state='ready',relative_path=?,filename=?,size=?,"
            "expires_at=?,error='' WHERE task_id=?",
            (
                relative_path,
                path.name,
                path.stat().st_size,
                now + self.runtime.export_ttl_sec,
                task_id,
            ),
        )
        return self.export_record(task_id) or {}

    def active_export_for_source(
        self,
        source_key: str,
        owner_user_id: str | None = None,
    ) -> dict[str, Any] | None:
        now = time.time()
        if owner_user_id is None:
            return self.database.one(
                "SELECT * FROM exports WHERE source_key=? "
                "AND state IN ('preparing','ready') AND expires_at>? "
                "ORDER BY created_at DESC LIMIT 1",
                (source_key, now),
            )
        return self.database.one(
            "SELECT * FROM exports WHERE owner_user_id=? AND source_key=? "
            "AND state IN ('preparing','ready') AND expires_at>? "
            "ORDER BY created_at DESC LIMIT 1",
            (owner_user_id, source_key, now),
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
        relative_path = str(row.get("relative_path") or "")
        if relative_path:
            try:
                candidates.add(resolve_under(root, relative_path))
            except UnsafePathError as exc:
                errors.append(str(exc))
        candidates.add(resolve_under(root, f"packages/{row['task_id']}"))
        payload = self._decode_payload(row)
        queue_key = str(payload.get("_queue_key") or row.get("source_key") or "")
        try:
            entry = self.export_index.get(queue_key)
            output_relative = str((entry or {}).get("path") or "")
            if output_relative:
                candidates.add(resolve_under(root, output_relative))
        except (UnsafePathError, UnsafeIndexPathError) as exc:
            errors.append(str(exc))
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
        try:
            self.export_index.discard_entry(queue_key)
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
        now = time.time()
        with self.database.transaction() as connection:
            raw = connection.execute(
                "SELECT * FROM exports WHERE task_id=?", (task_id,)
            ).fetchone()
            if raw is None:
                return
            row = dict(raw)
            state = str(row.get("state") or "")
            target = str(row.get("cleanup_target_state") or "")
            if state == "cleanup_pending" and target != "downloaded":
                return
            if state not in {"ready", "cleanup_pending"}:
                return
            delivered_at = float(row.get("downloaded_at") or now)
            connection.execute(
                "UPDATE exports SET state='cleanup_pending',"
                "downloaded_at=COALESCE(downloaded_at,?),"
                "cleanup_target_state='downloaded' WHERE task_id=?",
                (delivered_at, task_id),
            )
            owner = str(row.get("owner_user_id") or "")
            source_key = str(row.get("source_key") or "").strip()
            user = connection.execute(
                "SELECT role FROM users WHERE id=?", (owner,)
            ).fetchone()
            if user is not None and str(user[0]) == ROLE_USER and source_key:
                connection.execute(
                    "INSERT INTO device_download_history(owner_user_id,source_key,downloaded_at) "
                    "VALUES(?,?,?) ON CONFLICT(owner_user_id,source_key) DO UPDATE SET "
                    "downloaded_at=MAX(device_download_history.downloaded_at,"
                    "excluded.downloaded_at)",
                    (owner, source_key, delivered_at),
                )

        row = self.export_record(task_id)
        if not row:
            return
        errors = self._cleanup_export_files(row)
        if errors:
            self.database.execute(
                "UPDATE exports SET state='cleanup_pending',"
                "cleanup_target_state='downloaded',error=? WHERE task_id=?",
                ("; ".join(errors)[-3000:], task_id),
            )
            return
        self.database.execute(
            "UPDATE exports SET state='downloaded',cleanup_target_state='',error='' "
            "WHERE task_id=?",
            (task_id,),
        )

    def discard_export(self, task_id: str, state: str = "discarded") -> bool:
        row = self.export_record(task_id)
        if not row:
            return False
        errors = self._cleanup_export_files(row)
        if errors:
            self.database.execute(
                "UPDATE exports SET state='cleanup_pending',cleanup_target_state=?,"
                "error=? WHERE task_id=?",
                (state, "; ".join(errors)[-3000:], task_id),
            )
        else:
            self.database.execute(
                "UPDATE exports SET state=?,cleanup_target_state='',error='' WHERE task_id=?",
                (state, task_id),
            )
        return True

    def retry_export_cleanup(self, task_id: str) -> None:
        row = self.export_record(task_id)
        if not row or str(row.get("state") or "") != "cleanup_pending":
            return
        target = str(row.get("cleanup_target_state") or "").strip() or "discarded"
        errors = self._cleanup_export_files(row)
        if errors:
            self.database.execute(
                "UPDATE exports SET error=? WHERE task_id=?",
                ("; ".join(errors)[-3000:], task_id),
            )
            return
        self.database.execute(
            "UPDATE exports SET state=?,cleanup_target_state='',error='' WHERE task_id=?",
            (target, task_id),
        )

    def update_export_from_task(
        self,
        task_id: str,
        payload: dict[str, Any] | None,
    ) -> None:
        if payload is None:
            return
        status = str(payload.get("status") or "")
        if status not in TERMINAL_STATUSES:
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
            self.database.execute(
                "UPDATE exports SET title=?,error='',expires_at=?,task_payload_json=? "
                "WHERE task_id=?",
                (
                    str(value.get("title") or row["title"])[:500],
                    now + self.runtime.export_ttl_sec,
                    encoded,
                    task_id,
                ),
            )
        else:
            self.database.execute(
                "UPDATE exports SET state=?,error=?,expires_at=?,task_payload_json=? "
                "WHERE task_id=?",
                (
                    status,
                    str(
                        value.get("error")
                        or value.get("progress_message")
                        or ""
                    )[-3000:],
                    now + self.runtime.export_ttl_sec,
                    encoded,
                    task_id,
                ),
            )

    def task_log(self, task_id: str, *, tail_chars: int | None = None) -> dict[str, object]:
        record = self.task_record(task_id)
        if not record:
            raise KeyError("任务不存在")
        root = (
            self.export_root
            if str(record.get("destination") or "") == "device"
            else self.runtime.media_dir
        )
        return read_task_log(root, task_id, tail_chars=tail_chars)

    def cleanup_task_history(
        self,
        *,
        now: float | None = None,
        owner_user_id: str | None = None,
    ) -> int:
        current = float(now if now is not None else time.time())
        user_rows = self.database.all(
            "SELECT id,role FROM users" + (" WHERE id=?" if owner_user_id else ""),
            (owner_user_id,) if owner_user_id else (),
        )
        stale: set[str] = set()
        for user in user_rows:
            user_id = str(user["id"])
            role = str(user.get("role") or ROLE_USER)
            terminal = self.database.all(
                "SELECT tr.id,tr.destination,tr.finished_at,tr.created_at,"
                "e.state AS export_state FROM task_records tr "
                "LEFT JOIN exports e ON e.task_id=tr.id WHERE tr.owner_user_id=? "
                "AND tr.status IN ('success','skipped','failed','cancelled') "
                "ORDER BY COALESCE(tr.finished_at,tr.created_at) DESC,"
                "tr.created_at DESC,tr.id DESC",
                (user_id,),
            )
            removable = [
                row
                for row in terminal
                if str(row.get("export_state") or "") not in _PROTECTED_EXPORT_STATES
            ]
            if role == ROLE_ADMIN:
                stale.update(
                    str(row["id"]) for row in removable[ADMIN_TASK_HISTORY_LIMIT:]
                )
                continue
            cutoff = current - NORMAL_USER_TASK_RETENTION_DAYS * 24 * 3600
            stale.update(
                str(row["id"])
                for row in removable
                if float(row.get("finished_at") or row.get("created_at") or 0) < cutoff
            )
            kept = [row for row in removable if str(row["id"]) not in stale]
            stale.update(
                str(row["id"]) for row in kept[NORMAL_USER_TASK_HISTORY_LIMIT:]
            )

        removed = 0
        for task_id in sorted(stale):
            row = self.database.one(
                "SELECT destination FROM task_records WHERE id=?",
                (task_id,),
            )
            if not row:
                continue
            export = self.export_record(task_id)
            if export and str(export.get("state") or "") in _PROTECTED_EXPORT_STATES:
                continue
            if export:
                try:
                    self.discard_export(task_id, "expired")
                except (OSError, ValueError):
                    continue
                self.database.execute("DELETE FROM exports WHERE task_id=?", (task_id,))
            root = self.export_root if row["destination"] == "device" else self.runtime.media_dir
            try:
                delete_task_log(root, task_id)
            except (OSError, ValueError):
                pass
            with self.database.transaction() as connection:
                connection.execute("DELETE FROM task_records WHERE id=?", (task_id,))
                connection.execute(
                    "DELETE FROM task_snapshots WHERE task_id=?",
                    (task_id,),
                )
                connection.execute(
                    "DELETE FROM audit_log WHERE action LIKE 'download.%' AND detail LIKE ?",
                    (f"%task={task_id}%",),
                )
            self._snapshot_last_write.pop(task_id, None)
            self._snapshot_last_status.pop(task_id, None)
            removed += 1
        return removed

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(60):
            now = time.time()
            try:
                rows = self.database.all(
                    "SELECT task_id,state FROM exports WHERE "
                    "((state IN ('preparing','ready','failed','cancelled','skipped') "
                    "AND expires_at<=?) OR state='cleanup_pending')",
                    (now,),
                )
                for row in rows:
                    if row["state"] == "cleanup_pending":
                        self.retry_export_cleanup(str(row["task_id"]))
                    else:
                        self.discard_export(str(row["task_id"]), "expired")
                self.cleanup_task_history(now=now)
            except (OSError, sqlite3.Error, ValueError):
                continue
