from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from app.database import Database
from app.grouping import DEFAULT_GROUP, normalize_group
from app.index_store import IndexStore, UnsafeIndexPathError
from app.path_safety import UnsafePathError, relative_posix, resolve_under
from app.runtime import RuntimeSettings

_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".flv", ".webm", ".mov", ".ts", ".m4v"}
_MEDIA_EXTENSIONS = _VIDEO_EXTENSIONS | {".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg"}
_UNTAGGED = "__untagged__"


def _media_id(key: str) -> str:
    return "med_" + hashlib.sha256(key.encode()).hexdigest()[:24]


def _file_id(storage: str, relative_path: str) -> str:
    value = f"{storage}:{relative_path}"
    return "fil_" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _entry_fingerprint(entry: dict[str, Any]) -> str:
    encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compatible_video_encode_args(runtime: RuntimeSettings) -> list[str]:
    if runtime.launcher_managed:
        return [
            "-vf",
            "format=nv12",
            "-c:v",
            "h264_mf",
            "-rate_control",
            "quality",
            "-quality",
            "80",
            "-hw_encoding",
            "0",
        ]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]


class CatalogStore:
    """Groups, media catalog, watch progress, and transcode records."""

    def __init__(self, database: Database, index: IndexStore) -> None:
        self.database = database
        self.runtime = database.runtime
        self.index = index
        self.mutation_lock = threading.RLock()
        self._transcode_lock = threading.Semaphore(1)
        self._last_index_token: tuple[str, int, int, int] | None = None
        self._ensure_default_group()
        self._recover_transcodes()
        self.sync_index(force=True)

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

    def _ensure_default_group(self) -> dict[str, Any]:
        existing = self.database.one(
            "SELECT * FROM groups WHERE display_name=? COLLATE NOCASE",
            (DEFAULT_GROUP,),
        )
        return self._group_stats(existing) if existing else self.create_group(DEFAULT_GROUP)

    def _group_stats(self, row: dict[str, Any]) -> dict[str, Any]:
        stats = self.database.one(
            "SELECT COUNT(*) AS media_count,COALESCE(SUM(total_size),0) AS total_size,"
            "MAX(downloaded_at) AS latest_download FROM media WHERE group_id=?",
            (row["id"],),
        ) or {}
        cover = self.database.one(
            "SELECT cover FROM media WHERE group_id=? AND cover<>'' "
            "ORDER BY downloaded_at DESC LIMIT 1",
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
        row = self.database.one("SELECT * FROM groups WHERE id=?", (group_id,))
        return self._group_stats(row) if row else None

    def group_by_folder(self, folder: str) -> dict[str, Any] | None:
        row = self.database.one(
            "SELECT * FROM groups WHERE folder_key=? COLLATE NOCASE",
            (folder,),
        )
        return self._group_stats(row) if row else None

    def group_by_name(self, name: str) -> dict[str, Any] | None:
        row = self.database.one(
            "SELECT * FROM groups WHERE display_name=? COLLATE NOCASE",
            (name,),
        )
        return self._group_stats(row) if row else None

    def list_groups(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE g.archived=0"
        rows = self.database.all(
            "SELECT g.*,COUNT(m.id) AS media_count,COALESCE(SUM(m.total_size),0) AS total_size,"
            f"MAX(m.downloaded_at) AS latest_download FROM groups g "
            f"LEFT JOIN media m ON m.group_id=g.id {where} "
            "GROUP BY g.id ORDER BY g.sort_order,g.display_name COLLATE NOCASE"
        )
        covers = {
            str(item["group_id"]): str(item["cover"] or "")
            for item in self.database.all(
                "SELECT m.group_id,m.cover FROM media m JOIN "
                "(SELECT group_id,MAX(downloaded_at) AS latest FROM media "
                "WHERE cover<>'' GROUP BY group_id) x "
                "ON x.group_id=m.group_id AND x.latest=m.downloaded_at"
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
            row = self.database.one(
                "SELECT id FROM groups WHERE folder_key=? COLLATE NOCASE",
                (candidate,),
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
        self.database.execute(
            "INSERT INTO groups(id,display_name,folder_key,created_at,updated_at) "
            "VALUES(?,?,?,?,?)",
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

    def rename_group(self, group_id: str, name: str) -> dict[str, Any]:
        with self.mutation_lock:
            group = self.get_group(group_id)
            if not group:
                raise KeyError("分组不存在")
            normalized = normalize_group(name)
            conflict = self.group_by_name(normalized.display)
            if conflict and conflict["id"] != group_id:
                raise ValueError("已经存在同名分组")
            rows = self.database.all(
                "SELECT source_key FROM media WHERE group_id=?",
                (group_id,),
            )
            patches = {
                str(row["source_key"]): {
                    "group_id": group_id,
                    "group": normalized.display,
                }
                for row in rows
            }
            if patches:
                self.index.patch_entries(patches)
            self.database.execute(
                "UPDATE groups SET display_name=?,updated_at=? WHERE id=?",
                (normalized.display, time.time(), group_id),
            )
            self._last_index_token = self.index.change_token()
            return self.get_group(group_id) or {}

    def merge_group(self, source_id: str, target_id: str) -> dict[str, Any]:
        with self.mutation_lock:
            if source_id == target_id:
                raise ValueError("不能合并到同一分组")
            source, target = self.get_group(source_id), self.get_group(target_id)
            if not source or not target:
                raise KeyError("分组不存在")
            rows = self.database.all(
                "SELECT source_key FROM media WHERE group_id=?",
                (source_id,),
            )
            patches = {
                str(row["source_key"]): {
                    "group_id": target_id,
                    "group": target["display_name"],
                }
                for row in rows
            }
            if patches:
                self.index.patch_entries(patches)
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE media SET group_id=?,updated_at=? WHERE group_id=?",
                    (target_id, time.time(), source_id),
                )
                connection.execute("DELETE FROM groups WHERE id=?", (source_id,))
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
        self.database.execute("DELETE FROM groups WHERE id=?", (group_id,))

    def _resolve_entry_group(self, entry: dict[str, Any]) -> dict[str, Any]:
        group_id = str(entry.get("group_id") or "").strip()
        group = self.get_group(group_id) if group_id else None
        if not group:
            folder = str(entry.get("group_folder") or "").strip()
            group = self.group_by_folder(folder) if folder else None
        return group or self.create_group(str(entry.get("group") or DEFAULT_GROUP))

    def sync_index(self, force: bool = False) -> dict[str, int]:
        with self.mutation_lock:
            token, entry_count, entries = self.index.snapshot_if_changed(
                None if force else self._last_index_token
            )
            if entries is None:
                return {
                    "imported": 0,
                    "unchanged": entry_count,
                    "skipped": 0,
                    "removed": 0,
                }

            imported = unchanged = skipped = 0
            indexed_keys = set(entries)
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
                        relative_path = str(item.get("path") or "").strip()
                        if not relative_path:
                            continue
                        path = resolve_under(self.runtime.media_dir, relative_path)
                        if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                            actual_files.append((item, path))
                    if not actual_files:
                        skipped += 1
                        continue

                    fingerprint = _entry_fingerprint(entry)
                    current = self.database.one(
                        "SELECT index_fingerprint,group_id FROM media WHERE source_key=?",
                        (key,),
                    )
                    if (
                        current
                        and str(current.get("index_fingerprint") or "") == fingerprint
                        and str(current.get("group_id") or "") == str(group["id"])
                    ):
                        unchanged += 1
                        continue

                    total = sum(path.stat().st_size for _, path in actual_files)
                    now = time.time()
                    primary_path = next(
                        (
                            path
                            for _, path in actual_files
                            if path.suffix.lower() in _VIDEO_EXTENSIONS
                        ),
                        None,
                    )
                    if primary_path is None:
                        primary_path = next(
                            (
                                path
                                for _, path in actual_files
                                if path.suffix.lower() in _MEDIA_EXTENSIONS
                            ),
                            actual_files[0][1],
                        )
                    with self.database.transaction() as connection:
                        connection.execute(
                            "INSERT INTO media(id,source_key,bvid,source_url,title,cover,author,pubdate,"
                            "duration_text,group_id,output_path,min_height,preferred_quality,selected_quality,"
                            "selected_resolution,selected_codec,selected_fps,selected_height,total_size,"
                            "downloaded_at,updated_at,index_fingerprint) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                            "ON CONFLICT(source_key) DO UPDATE SET bvid=excluded.bvid,"
                            "source_url=excluded.source_url,title=excluded.title,cover=excluded.cover,"
                            "author=excluded.author,pubdate=excluded.pubdate,duration_text=excluded.duration_text,"
                            "group_id=excluded.group_id,output_path=excluded.output_path,"
                            "min_height=excluded.min_height,preferred_quality=excluded.preferred_quality,"
                            "selected_quality=excluded.selected_quality,"
                            "selected_resolution=excluded.selected_resolution,"
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
                                entry.get("pubdate")
                                if isinstance(entry.get("pubdate"), int)
                                else None,
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
                        connection.execute(
                            "DELETE FROM media_files WHERE media_id=? AND kind='media'",
                            (media_id,),
                        )
                        for _item, path in actual_files:
                            relative_path = relative_posix(self.runtime.media_dir, path)
                            connection.execute(
                                "INSERT OR REPLACE INTO media_files(id,media_id,storage,relative_path,"
                                "filename,size,mime_type,kind,is_primary,created_at) "
                                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (
                                    _file_id("media", relative_path),
                                    media_id,
                                    "media",
                                    relative_path,
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
                for row in self.database.all("SELECT source_key FROM media")
            }
            stale = existing_keys - indexed_keys
            if stale:
                with self.database.transaction() as connection:
                    for key in stale:
                        connection.execute("DELETE FROM media WHERE source_key=?", (key,))
            if patches:
                self.index.patch_entries(patches)
            self._last_index_token = token
            return {
                "imported": imported,
                "unchanged": unchanged,
                "skipped": skipped,
                "removed": len(stale),
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
        tag: str = "",
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
        selected_tag = tag.strip()
        if selected_tag == _UNTAGGED:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM item_tags it "
                "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
                "WHERE it.source_key=m.source_key)"
            )
        elif selected_tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM item_tags it "
                "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
                "WHERE it.source_key=m.source_key AND it.tag=? COLLATE NOCASE)"
            )
            params.append(selected_tag)
        watched = watched.strip().lower()
        if watched in {"completed", "in_progress", "watching", "unwatched"}:
            progress_sql = (
                "SELECT 1 FROM watch_progress wp WHERE wp.media_id=m.id AND wp.user_id=? "
            )
            params.append(user_id)
            if watched == "completed":
                clauses.append(f"EXISTS ({progress_sql}AND wp.completed=1)")
            elif watched in {"in_progress", "watching"}:
                clauses.append(
                    f"EXISTS ({progress_sql}AND wp.completed=0 AND wp.position_sec>0)"
                )
            else:
                clauses.append(f"NOT EXISTS ({progress_sql}AND wp.position_sec>0)")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        tag_name_sql = (
            "(SELECT MIN(it.tag) FROM item_tags it "
            "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
            "WHERE it.source_key=m.source_key)"
        )
        duration_sql = "bili_duration_seconds(m.duration_text)"
        order_sql = {
            "newest": "m.downloaded_at DESC,m.title COLLATE NOCASE ASC",
            "oldest": "m.downloaded_at ASC,m.title COLLATE NOCASE ASC",
            "title": "m.title COLLATE NOCASE ASC",
            "size": "m.total_size DESC,m.title COLLATE NOCASE ASC",
            "recent": "COALESCE(w.updated_at,0) DESC,m.downloaded_at DESC",
            "newest_desc": "m.downloaded_at DESC,m.title COLLATE NOCASE ASC",
            "newest_asc": "m.downloaded_at ASC,m.title COLLATE NOCASE ASC",
            "recent_desc": "COALESCE(w.updated_at,0) DESC,m.downloaded_at DESC",
            "recent_asc": "COALESCE(w.updated_at,0) ASC,m.downloaded_at ASC",
            "title_asc": "m.title COLLATE NOCASE ASC",
            "title_desc": "m.title COLLATE NOCASE DESC",
            "duration_asc": (
                f"CASE WHEN {duration_sql}>0 THEN 0 ELSE 1 END ASC,"
                f"{duration_sql} ASC,m.title COLLATE NOCASE ASC"
            ),
            "duration_desc": f"{duration_sql} DESC,m.title COLLATE NOCASE ASC",
            "size_asc": "m.total_size ASC,m.title COLLATE NOCASE ASC",
            "size_desc": "m.total_size DESC,m.title COLLATE NOCASE ASC",
            "group_asc": (
                "CASE WHEN COALESCE(g.display_name,'')<>'' THEN 0 ELSE 1 END ASC,"
                "g.display_name COLLATE NOCASE ASC,m.title COLLATE NOCASE ASC"
            ),
            "group_desc": (
                "CASE WHEN COALESCE(g.display_name,'')<>'' THEN 0 ELSE 1 END ASC,"
                "g.display_name COLLATE NOCASE DESC,m.title COLLATE NOCASE ASC"
            ),
            "tag_asc": (
                f"CASE WHEN {tag_name_sql} IS NULL THEN 1 ELSE 0 END ASC,"
                f"{tag_name_sql} COLLATE NOCASE ASC,m.title COLLATE NOCASE ASC"
            ),
            "tag_desc": (
                f"CASE WHEN {tag_name_sql} IS NULL THEN 1 ELSE 0 END ASC,"
                f"{tag_name_sql} COLLATE NOCASE DESC,m.title COLLATE NOCASE ASC"
            ),
        }.get(sort, "m.downloaded_at DESC,m.title COLLATE NOCASE ASC")
        total = int(
            (
                self.database.one(
                    f"SELECT COUNT(*) AS n FROM media m {where}",
                    tuple(params),
                )
                or {}
            ).get("n")
            or 0
        )
        rows = self.database.all(
            "SELECT m.*,g.display_name AS group_name,g.folder_key AS group_folder,"
            "f.id AS primary_file_id,f.filename AS primary_filename,f.mime_type AS primary_mime,"
            "COALESCE(w.position_sec,0) AS watch_position,"
            "COALESCE(w.duration_sec,0) AS watch_duration,"
            "COALESCE(w.completed,0) AS watch_completed FROM media m "
            "LEFT JOIN groups g ON g.id=m.group_id "
            "LEFT JOIN media_files f ON f.media_id=m.id AND f.is_primary=1 "
            "LEFT JOIN watch_progress w ON w.file_id=f.id AND w.user_id=? "
            f"{where} ORDER BY {order_sql} LIMIT ? OFFSET ?",
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
                "tag": selected_tag,
            },
        }

    def library_summary(self) -> dict[str, Any]:
        self.sync_index()
        row = self.database.one(
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
        row = self.database.one(
            "SELECT m.*,g.display_name AS group_name,g.folder_key AS group_folder "
            "FROM media m LEFT JOIN groups g ON g.id=m.group_id WHERE m.id=?",
            (media_id,),
        )
        if not row:
            return None
        row["files"] = self.database.all(
            "SELECT f.*,COALESCE(w.position_sec,0) AS watch_position,"
            "COALESCE(w.duration_sec,0) AS watch_duration,"
            "COALESCE(w.completed,0) AS watch_completed FROM media_files f "
            "LEFT JOIN watch_progress w ON w.file_id=f.id AND w.user_id=? "
            "WHERE f.media_id=? ORDER BY f.is_primary DESC,f.kind,f.filename COLLATE NOCASE",
            (user_id, media_id),
        )
        for item in row["files"]:
            item["watch_completed"] = bool(item["watch_completed"])
        return row

    def media_keys(self, media_ids: list[str]) -> dict[str, str]:
        values = list(dict.fromkeys(str(value).strip() for value in media_ids if str(value).strip()))[
            :500
        ]
        if not values:
            return {}
        placeholders = ",".join("?" for _ in values)
        rows = self.database.all(
            f"SELECT id,source_key FROM media WHERE id IN ({placeholders})",
            tuple(values),
        )
        return {str(row["id"]): str(row["source_key"]) for row in rows}

    def library_items(self, media_ids: list[str]) -> list[dict[str, Any]]:
        values = list(dict.fromkeys(str(value).strip() for value in media_ids if str(value).strip()))[
            :100
        ]
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        return self.database.all(
            "SELECT m.id,m.source_key,m.bvid,m.source_url,m.title,m.cover,m.author,"
            "m.duration_text,m.total_size,f.id AS primary_file_id,"
            "f.filename AS primary_filename FROM media m "
            "LEFT JOIN media_files f ON f.media_id=m.id AND f.is_primary=1 "
            f"WHERE m.id IN ({placeholders})",
            tuple(values),
        )

    def resolve_media_file(self, file_id: str) -> tuple[dict[str, Any], Path]:
        row = self.database.one(
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
        self,
        user_id: str,
        media_id: str,
        file_id: str,
        position: float,
        duration: float,
    ) -> dict[str, Any]:
        if not self.database.one(
            "SELECT 1 AS ok FROM media_files WHERE id=? AND media_id=?",
            (file_id, media_id),
        ):
            raise KeyError("媒体文件不存在")
        position, duration = max(0, float(position)), max(0, float(duration))
        if duration:
            position = min(position, duration)
        completed = duration > 0 and position >= max(0, duration - 15)
        now = time.time()
        self.database.execute(
            "INSERT INTO watch_progress(user_id,media_id,file_id,position_sec,duration_sec,"
            "completed,updated_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id,media_id,file_id) DO UPDATE SET "
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
        with self.mutation_lock:
            group = self.get_group(group_id)
            if not group:
                raise KeyError("目标分组不存在")
            row = self.database.one(
                "SELECT source_key FROM media WHERE id=?",
                (media_id,),
            )
            if not row:
                raise KeyError("作品不存在")
            self.index.patch_entry(
                str(row["source_key"]),
                {"group_id": group_id, "group": group["display_name"]},
            )
            self.database.execute(
                "UPDATE media SET group_id=?,updated_at=? WHERE id=?",
                (group_id, time.time(), media_id),
            )
            self._last_index_token = self.index.change_token()
            return self.media_detail(media_id, "local") or {}

    def delete_media_record(self, media_id: str) -> None:
        cursor = self.database.execute("DELETE FROM media WHERE id=?", (media_id,))
        if cursor.rowcount != 1:
            raise KeyError("作品不存在")

    def acknowledge_index_change(self) -> None:
        self._last_index_token = self.index.change_token()

    def reconcile_media_files(self, media_id: str) -> dict[str, int]:
        """Make persisted file rows reflect what still exists after a failed file step."""
        rows = self.database.all(
            "SELECT id,storage,relative_path FROM media_files WHERE media_id=?",
            (media_id,),
        )
        missing: list[str] = []
        remaining_media_size = 0
        for row in rows:
            base = (
                self.runtime.media_dir
                if str(row["storage"]) == "media"
                else self.runtime.cache_dir
            )
            path = resolve_under(base, str(row["relative_path"]))
            if path.is_file() and not path.is_symlink():
                if str(row["storage"]) == "media":
                    remaining_media_size += max(0, path.stat().st_size)
            else:
                missing.append(str(row["id"]))
        with self.database.transaction() as connection:
            for file_id in missing:
                connection.execute("DELETE FROM media_files WHERE id=?", (file_id,))
            connection.execute(
                "UPDATE media SET total_size=?,updated_at=? WHERE id=?",
                (remaining_media_size, time.time(), media_id),
            )
        return {"removed_rows": len(missing), "remaining_size": remaining_media_size}

    def start_compatible(
        self, media_id: str, file_id: str, ffmpeg: Path
    ) -> dict[str, Any]:
        row, source = self.resolve_media_file(file_id)
        if row["media_id"] != media_id:
            raise ValueError("文件不属于该作品")
        self.ensure_space("device")
        job_id = "tr_" + uuid.uuid4().hex[:20]
        now = time.time()
        self.database.execute(
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
        return self.database.one("SELECT * FROM transcodes WHERE id=?", (job_id,))

    def _recover_transcodes(self) -> None:
        now = time.time()
        self.database.execute(
            "UPDATE transcodes SET status='failed',progress_message='服务重启中断转码',"
            "error='服务重启中断转码，可重新生成',finished_at=? "
            "WHERE status IN ('queued','running')",
            (now,),
        )

    def _transcode_worker(
        self,
        job_id: str,
        row: dict[str, Any],
        source: Path,
        ffmpeg: Path,
    ) -> None:
        with self._transcode_lock:
            self.database.execute(
                "UPDATE transcodes SET status='running',progress_message=?,started_at=? "
                "WHERE id=?",
                ("正在生成 H.264/AAC 兼容副本", time.time(), job_id),
            )
            try:
                directory = resolve_under(
                    self.runtime.cache_dir,
                    f"compatible/{row['media_id']}",
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
                    *_compatible_video_encode_args(self.runtime),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                ]
                if self.runtime.transcode_threads > 0 and not self.runtime.launcher_managed:
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
                relative_path = relative_posix(self.runtime.cache_dir, output)
                new_id = _file_id("cache", relative_path)
                with self.database.transaction() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO media_files(id,media_id,storage,relative_path,"
                        "filename,size,mime_type,kind,is_primary,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            new_id,
                            row["media_id"],
                            "cache",
                            relative_path,
                            output.name,
                            output.stat().st_size,
                            "video/mp4",
                            "compatible",
                            0,
                            time.time(),
                        ),
                    )
                    connection.execute(
                        "UPDATE transcodes SET status='success',progress_message=?,"
                        "output_file_id=?,finished_at=? WHERE id=?",
                        ("兼容副本已生成", new_id, time.time(), job_id),
                    )
            except Exception as exc:  # noqa: BLE001
                self.database.execute(
                    "UPDATE transcodes SET status='failed',progress_message=?,error=?,"
                    "finished_at=? WHERE id=?",
                    ("兼容副本生成失败", str(exc)[-3000:], time.time(), job_id),
                )
