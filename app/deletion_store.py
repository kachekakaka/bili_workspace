from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Iterable, Mapping

from app.runtime import RuntimeSettings

_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS deleted_media(
 source_key TEXT PRIMARY KEY,
 bvid TEXT,
 source_url TEXT NOT NULL DEFAULT '',
 title TEXT NOT NULL DEFAULT '',
 cover TEXT NOT NULL DEFAULT '',
 author TEXT NOT NULL DEFAULT '',
 pubdate INTEGER,
 duration_text TEXT NOT NULL DEFAULT '',
 group_name TEXT NOT NULL DEFAULT '',
 deleted_at REAL NOT NULL,
 files_deleted INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_deleted_media_deleted_at
 ON deleted_media(deleted_at DESC);
"""


class DeletionStore:
    """Persistent tombstones for works explicitly removed by the user.

    Tombstones are deliberately separate from the visible media library and from
    normal user tags. They let search results say "已删除" after the media row and
    files have been removed, without making the deleted work reappear in the
    library.
    """

    def __init__(self, runtime: RuntimeSettings):
        self.path = runtime.database_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path, timeout=30, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.executescript(_SCHEMA)
            self._migrate_legacy_delete_tags_locked()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.ProgrammingError:
                pass

    def _migrate_legacy_delete_tags_locked(self) -> None:
        """Convert old orphaned “不要” tags into dedicated tombstones once."""
        tables = {
            str(row[0])
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "item_tags" not in tables or "media" not in tables:
            return
        rows = self._conn.execute(
            "SELECT it.source_key,MAX(it.created_at) AS deleted_at "
            "FROM item_tags it LEFT JOIN media m ON m.source_key=it.source_key "
            "WHERE it.tag='不要' COLLATE NOCASE AND m.id IS NULL "
            "GROUP BY it.source_key"
        ).fetchall()
        if not rows:
            return
        now = time.time()
        self._conn.executemany(
            "INSERT OR IGNORE INTO deleted_media("
            "source_key,bvid,title,deleted_at,files_deleted"
            ") VALUES(?,?,?,?,1)",
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
        self._conn.executemany("DELETE FROM item_tags WHERE source_key=?", keys)

    @staticmethod
    def _value(media: Mapping[str, Any], key: str, default: Any = "") -> Any:
        value = media.get(key, default)
        return default if value is None else value

    def record(self, media: Mapping[str, Any], *, files_deleted: bool) -> dict[str, Any]:
        source_key = str(self._value(media, "source_key")).strip()[:300]
        if not source_key:
            raise ValueError("作品标识不能为空")
        now = time.time()
        payload = {
            "source_key": source_key,
            "bvid": str(self._value(media, "bvid")).strip()[:80] or None,
            "source_url": str(self._value(media, "source_url"))[:2048],
            "title": str(self._value(media, "title", source_key))[:500],
            "cover": str(self._value(media, "cover"))[:2048],
            "author": str(self._value(media, "author"))[:300],
            "pubdate": self._value(media, "pubdate", None),
            "duration_text": str(self._value(media, "duration_text"))[:64],
            "group_name": str(
                self._value(media, "group_name", self._value(media, "group", ""))
            )[:300],
            "deleted_at": now,
            "files_deleted": 1 if files_deleted else 0,
        }
        if not isinstance(payload["pubdate"], int):
            payload["pubdate"] = None
        with self._lock:
            self._conn.execute(
                "INSERT INTO deleted_media("
                "source_key,bvid,source_url,title,cover,author,pubdate,duration_text,"
                "group_name,deleted_at,files_deleted"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(source_key) DO UPDATE SET "
                "bvid=excluded.bvid,source_url=excluded.source_url,title=excluded.title,"
                "cover=excluded.cover,author=excluded.author,pubdate=excluded.pubdate,"
                "duration_text=excluded.duration_text,group_name=excluded.group_name,"
                "deleted_at=excluded.deleted_at,files_deleted=excluded.files_deleted",
                (
                    payload["source_key"],
                    payload["bvid"],
                    payload["source_url"],
                    payload["title"],
                    payload["cover"],
                    payload["author"],
                    payload["pubdate"],
                    payload["duration_text"],
                    payload["group_name"],
                    payload["deleted_at"],
                    payload["files_deleted"],
                ),
            )
        payload["files_deleted"] = bool(payload["files_deleted"])
        return payload

    def for_keys(self, keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        values = [str(key or "").strip() for key in keys if str(key or "").strip()]
        values = list(dict.fromkeys(values))[:500]
        if not values:
            return {}
        placeholders = ",".join("?" for _ in values)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM deleted_media WHERE source_key IN ({placeholders})",
                tuple(values),
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            item["files_deleted"] = bool(item.get("files_deleted"))
            result[str(item["source_key"])] = item
        return result

    def clear(self, keys: Iterable[str]) -> int:
        values = [str(key or "").strip() for key in keys if str(key or "").strip()]
        values = list(dict.fromkeys(values))[:500]
        if not values:
            return 0
        placeholders = ",".join("?" for _ in values)
        with self._lock:
            cursor = self._conn.execute(
                f"DELETE FROM deleted_media WHERE source_key IN ({placeholders})",
                tuple(values),
            )
            return max(0, int(cursor.rowcount or 0))
