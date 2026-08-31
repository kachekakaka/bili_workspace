from __future__ import annotations

import shutil
from typing import Any, Iterable

from app.artifacts import remove_relative_target
from app.catalog_store import CatalogStore
from app.database import Database
from app.deletion_store import DeletionStore
from app.path_safety import UnsafePathError, resolve_under
from app.tag_store import TagStore


class LibraryService:
    """Coordinates catalog, index, files, tags, and deletion tombstones."""

    def __init__(
        self,
        database: Database,
        catalog: CatalogStore,
        tags: TagStore,
        deletions: DeletionStore,
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.tags = tags
        self.deletions = deletions

    def library_list(self, **filters: Any) -> dict[str, Any]:
        result = self.catalog.library_list(**filters)
        rows = result["items"]
        tags = self.tags.tags_for_keys(str(row["source_key"]) for row in rows)
        for row in rows:
            row["tags"] = tags.get(str(row["source_key"]), [])
        return result

    def library_items(self, media_ids: Iterable[str]) -> list[dict[str, Any]]:
        values = [str(media_id) for media_id in media_ids]
        rows = self.catalog.library_items(values)
        tags = self.tags.tags_for_keys(str(row["source_key"]) for row in rows)
        for row in rows:
            row["tags"] = tags.get(str(row["source_key"]), [])
        return rows

    def media_keys(self, media_ids: Iterable[str]) -> dict[str, str]:
        return self.catalog.media_keys([str(media_id) for media_id in media_ids])

    def _remove_compatible_files(self, media_id: str) -> None:
        target = resolve_under(
            self.catalog.runtime.cache_dir,
            f"compatible/{media_id}",
        )
        if not target.exists() and not target.is_symlink():
            return
        if target.is_symlink():
            raise UnsafePathError(f"拒绝删除符号链接: {target}")
        if not target.is_dir():
            raise UnsafePathError(f"兼容副本目标不是目录: {target}")
        shutil.rmtree(target)

    def _restore_index(
        self,
        source_key: str,
        captured_entry: dict[str, Any] | None,
    ) -> str:
        if captured_entry is None or self.catalog.index.get(source_key) is not None:
            return ""
        try:
            self.catalog.index.restore_entry(source_key, captured_entry)
            return ""
        except Exception as exc:  # noqa: BLE001 - preserve primary failure and recovery fact
            return f"索引恢复失败: {exc}"

    def _reconcile_failed_file_step(self, media_id: str) -> str:
        try:
            self.catalog.reconcile_media_files(media_id)
            return ""
        except Exception as exc:  # noqa: BLE001 - returned with the primary failure
            return f"文件记录刷新失败: {exc}"

    @staticmethod
    def _raise_with_recovery(primary: Exception, recovery: list[str]) -> None:
        details = [str(primary), *(item for item in recovery if item)]
        message = "；".join(item for item in details if item) or primary.__class__.__name__
        raise RuntimeError(message) from primary

    def delete_media(
        self,
        media_id: str,
        *,
        delete_files: bool,
        user_id: str,
    ) -> dict[str, Any]:
        with self.catalog.mutation_lock:
            media = self.catalog.media_detail(media_id, user_id)
            if not media:
                raise KeyError("作品不存在")
            source_key = str(media.get("source_key") or "")
            output_path = str(media.get("output_path") or "")
            captured_entry = self.catalog.index.get(source_key)

            try:
                if delete_files:
                    removed = self.catalog.index.remove_entry_and_files(source_key)
                    if not removed and output_path:
                        remove_relative_target(
                            self.catalog.runtime.media_dir,
                            output_path,
                        )
                else:
                    self.catalog.index.discard_entry(source_key)
                self._remove_compatible_files(media_id)
            except Exception as exc:  # noqa: BLE001 - filesystem failures are result data
                recovery = [
                    self._restore_index(source_key, captured_entry),
                    self._reconcile_failed_file_step(media_id),
                ]
                self.catalog.acknowledge_index_change()
                self._raise_with_recovery(exc, recovery)

            try:
                with self.database.transaction():
                    self.catalog.delete_media_record(media_id)
                    self.tags.clear_tags(source_key)
                    tombstone = self.deletions.record(
                        media,
                        files_deleted=delete_files,
                    )
            except Exception as exc:  # noqa: BLE001 - restore retryable index state
                recovery = [
                    self._restore_index(source_key, captured_entry),
                    self._reconcile_failed_file_step(media_id),
                ]
                self.catalog.acknowledge_index_change()
                self._raise_with_recovery(exc, recovery)

            self.catalog.acknowledge_index_change()
            return {
                "deleted": True,
                "files_deleted": bool(delete_files),
                "media_id": media_id,
                "source_key": source_key,
                "deleted_recorded": True,
                "deleted_at": tombstone["deleted_at"],
            }

    def delete_many(
        self,
        media_ids: Iterable[str],
        *,
        delete_files: bool,
        user_id: str,
    ) -> dict[str, Any]:
        deleted: list[str] = []
        records: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        values = list(dict.fromkeys(str(media_id) for media_id in media_ids))
        for media_id in values:
            try:
                record = self.delete_media(
                    media_id,
                    delete_files=delete_files,
                    user_id=user_id,
                )
                deleted.append(media_id)
                records.append(record)
            except Exception as exc:  # noqa: BLE001 - batch commits and reports per item
                errors[media_id] = str(exc)
        return {
            "deleted": deleted,
            "deleted_records": records,
            "errors": errors,
            "files_deleted": bool(delete_files),
            "deleted_recorded": bool(deleted),
            "marked_tag": "",
        }
