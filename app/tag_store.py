from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Iterable

from app.config_files import ensure_json_from_default
from app.paths import ROOT
from app.runtime import RuntimeSettings

_TAG_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS tag_definitions(
 name TEXT PRIMARY KEY COLLATE NOCASE,
 color TEXT NOT NULL DEFAULT '#64748b',
 sort_order INTEGER NOT NULL DEFAULT 0,
 enabled INTEGER NOT NULL DEFAULT 1,
 updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS item_tags(
 source_key TEXT NOT NULL,
 tag TEXT NOT NULL COLLATE NOCASE REFERENCES tag_definitions(name) ON DELETE CASCADE,
 created_at REAL NOT NULL,
 PRIMARY KEY(source_key, tag)
);
CREATE INDEX IF NOT EXISTS idx_item_tags_tag ON item_tags(tag, source_key);
"""


class TagStore:
    """Small persistent tag layer backed by the existing media-library SQLite DB."""

    def __init__(self, runtime: RuntimeSettings):
        self.runtime = runtime
        self.path = runtime.database_path
        self.config_path = runtime.config_dir / "tags.json"
        self.default_config_path = ROOT / "config" / "tags.json.default"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path, timeout=30, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.executescript(_TAG_SCHEMA)
        self.reload_definitions()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.ProgrammingError:
                pass

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def reload_definitions(self) -> list[dict[str, Any]]:
        data, _ = ensure_json_from_default(self.default_config_path, self.config_path)
        raw_tags = data.get("tags") or []
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw_tags):
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:40]
            folded = name.casefold()
            if not name or folded in seen:
                continue
            seen.add(folded)
            color = str(item.get("color") or "#64748b").strip()[:32]
            if not color.startswith("#"):
                color = "#64748b"
            normalized.append(
                {
                    "name": name,
                    "color": color,
                    "enabled": bool(item.get("enabled", True)),
                    "sort_order": index,
                }
            )
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for item in normalized:
                    self._conn.execute(
                        "INSERT INTO tag_definitions(name,color,sort_order,enabled,updated_at) "
                        "VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                        "color=excluded.color,sort_order=excluded.sort_order,"
                        "enabled=excluded.enabled,updated_at=excluded.updated_at",
                        (
                            item["name"],
                            item["color"],
                            item["sort_order"],
                            1 if item["enabled"] else 0,
                            now,
                        ),
                    )
                if normalized:
                    placeholders = ",".join("?" for _ in normalized)
                    self._conn.execute(
                        f"UPDATE tag_definitions SET enabled=0,updated_at=? "
                        f"WHERE name NOT IN ({placeholders})",
                        (now, *(item["name"] for item in normalized)),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return self.definitions(include_disabled=True)

    def definitions(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        where = "" if include_disabled else "WHERE enabled=1"
        rows = self._all(
            f"SELECT name,color,sort_order,enabled FROM tag_definitions {where} "
            "ORDER BY sort_order,name COLLATE NOCASE"
        )
        for row in rows:
            row["enabled"] = bool(row["enabled"])
        return rows

    def _valid_names(self) -> dict[str, str]:
        return {
            str(row["name"]).casefold(): str(row["name"])
            for row in self.definitions()
        }

    def set_tags(self, source_key: str, tags: Iterable[str]) -> list[str]:
        source_key = str(source_key or "").strip()[:256]
        if not source_key:
            raise ValueError("作品标识不能为空")
        valid = self._valid_names()
        selected: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            folded = str(raw or "").strip().casefold()
            canonical = valid.get(folded)
            if canonical and folded not in seen:
                seen.add(folded)
                selected.append(canonical)
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM item_tags WHERE source_key=?", (source_key,))
                self._conn.executemany(
                    "INSERT INTO item_tags(source_key,tag,created_at) VALUES(?,?,?)",
                    [(source_key, tag, now) for tag in selected],
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return selected

    def add_tag(self, source_key: str, tag: str) -> list[str]:
        current = self.tags_for_keys([source_key]).get(source_key, [])
        return self.set_tags(source_key, [*current, tag])

    def tags_for_keys(self, keys: Iterable[str]) -> dict[str, list[str]]:
        values = [str(key or "").strip() for key in keys if str(key or "").strip()]
        values = list(dict.fromkeys(values))[:500]
        result = {key: [] for key in values}
        if not values:
            return result
        placeholders = ",".join("?" for _ in values)
        rows = self._all(
            "SELECT it.source_key,it.tag FROM item_tags it "
            "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
            f"WHERE it.source_key IN ({placeholders}) "
            "ORDER BY td.sort_order,td.name COLLATE NOCASE",
            tuple(values),
        )
        for row in rows:
            result.setdefault(str(row["source_key"]), []).append(str(row["tag"]))
        return result

    def media_keys(self, media_ids: Iterable[str]) -> dict[str, str]:
        values = [str(value or "").strip() for value in media_ids if str(value or "").strip()]
        values = list(dict.fromkeys(values))[:500]
        if not values:
            return {}
        placeholders = ",".join("?" for _ in values)
        rows = self._all(
            f"SELECT id,source_key FROM media WHERE id IN ({placeholders})", tuple(values)
        )
        return {str(row["id"]): str(row["source_key"]) for row in rows}

    def library_items(self, media_ids: Iterable[str]) -> list[dict[str, Any]]:
        values = [str(value or "").strip() for value in media_ids if str(value or "").strip()]
        values = list(dict.fromkeys(values))[:100]
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        rows = self._all(
            "SELECT m.id,m.source_key,m.bvid,m.source_url,m.title,m.cover,m.author,"
            "m.duration_text,m.total_size,f.id AS primary_file_id,f.filename AS primary_filename "
            "FROM media m LEFT JOIN media_files f ON f.media_id=m.id AND f.is_primary=1 "
            f"WHERE m.id IN ({placeholders})",
            tuple(values),
        )
        tags = self.tags_for_keys(str(row["source_key"]) for row in rows)
        for row in rows:
            row["tags"] = tags.get(str(row["source_key"]), [])
        return rows

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
        tag: str = "",
    ) -> dict[str, Any]:
        page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
        clauses: list[str] = []
        params: list[Any] = []
        if query.strip():
            needle = f"%{query.strip()}%"
            clauses.append("(m.title LIKE ? OR m.bvid LIKE ? OR m.author LIKE ? OR m.source_key LIKE ?)")
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
        if tag.strip():
            clauses.append("EXISTS (SELECT 1 FROM item_tags it WHERE it.source_key=m.source_key AND it.tag=? COLLATE NOCASE)")
            params.append(tag.strip())
        watched = watched.strip().lower()
        if watched in {"completed", "in_progress", "watching", "unwatched"}:
            progress_sql = "SELECT 1 FROM watch_progress wp WHERE wp.media_id=m.id AND wp.user_id=? "
            params.append(user_id)
            if watched == "completed":
                clauses.append(f"EXISTS ({progress_sql}AND wp.completed=1)")
            elif watched in {"in_progress", "watching"}:
                clauses.append(f"EXISTS ({progress_sql}AND wp.completed=0 AND wp.position_sec>0)")
            else:
                clauses.append(f"NOT EXISTS ({progress_sql}AND wp.position_sec>0)")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        order_sql = {
            "newest": "m.downloaded_at DESC",
            "oldest": "m.downloaded_at ASC",
            "title": "m.title COLLATE NOCASE",
            "size": "m.total_size DESC",
            "recent": "COALESCE(w.updated_at,0) DESC,m.downloaded_at DESC",
        }.get(sort, "m.downloaded_at DESC")
        total = int(
            (self._one(f"SELECT COUNT(*) AS n FROM media m {where}", tuple(params)) or {}).get("n")
            or 0
        )
        rows = self._all(
            "SELECT m.*,g.display_name AS group_name,g.folder_key AS group_folder,"
            "f.id AS primary_file_id,f.filename AS primary_filename,f.mime_type AS primary_mime,"
            "COALESCE(w.position_sec,0) AS watch_position,COALESCE(w.duration_sec,0) AS watch_duration,"
            "COALESCE(w.completed,0) AS watch_completed FROM media m "
            "LEFT JOIN groups g ON g.id=m.group_id "
            "LEFT JOIN media_files f ON f.media_id=m.id AND f.is_primary=1 "
            "LEFT JOIN watch_progress w ON w.file_id=f.id AND w.user_id=? "
            f"{where} ORDER BY {order_sql} LIMIT ? OFFSET ?",
            tuple([user_id, *params, page_size, (page - 1) * page_size]),
        )
        tags = self.tags_for_keys(str(row["source_key"]) for row in rows)
        for row in rows:
            row["watch_completed"] = bool(row["watch_completed"])
            row["tags"] = tags.get(str(row["source_key"]), [])
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
                "tag": tag,
            },
        }
