from __future__ import annotations

import time
from typing import Any, Iterable, Mapping

from app.database import Database


class DeletionStore:
    """Persistent tombstones for works explicitly removed by the user.

    Tombstones are deliberately separate from the visible media library and from
    normal user tags. They let search results say "已删除" after the media row and
    files have been removed, without making the deleted work reappear in the
    library.
    """

    def __init__(self, database: Database):
        self.database = database
        self.path = database.path

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
        self.database.execute(
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
        rows = self.database.all(
            f"SELECT * FROM deleted_media WHERE source_key IN ({placeholders})",
            tuple(values),
        )
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
        cursor = self.database.execute(
            f"DELETE FROM deleted_media WHERE source_key IN ({placeholders})",
            tuple(values),
        )
        return max(0, int(cursor.rowcount or 0))
