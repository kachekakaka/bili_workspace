from __future__ import annotations

import json
import os
import shutil
import threading
import time
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.constants import MEDIA_EXTENSIONS
from app.io_utils import atomic_write_json
from app.path_safety import UnsafePathError, resolve_under

INDEX_NAME = ".bili_index.json"


class UnsafeIndexPathError(UnsafePathError):
    pass


class IndexStore:
    """Thread-safe download index with atomic writes and external-change detection."""

    def __init__(self, download_dir: Path):
        self._lock = threading.RLock()
        self.download_dir = Path()
        self.path = Path()
        self._data: dict[str, Any] = {}
        self._revision = 0
        self._known_stamp: tuple[int, int] | None = None
        self.set_download_dir(download_dir)

    def set_download_dir(self, download_dir: Path) -> None:
        with self._lock:
            resolved = Path(download_dir).resolve()
            if self.download_dir == resolved and self.path:
                return
            resolved.mkdir(parents=True, exist_ok=True)
            self.download_dir = resolved
            self.path = resolved / INDEX_NAME
            self._data = self._load()
            self._known_stamp = self._file_stamp()
            self._revision += 1

    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _refresh_if_external_change(self) -> None:
        stamp = self._file_stamp()
        if stamp == self._known_stamp:
            return
        self._data = self._load()
        self._known_stamp = self._file_stamp()
        self._revision += 1

    @property
    def revision(self) -> int:
        with self._lock:
            self._refresh_if_external_change()
            return self._revision

    def change_token(self) -> tuple[str, int, int, int]:
        """Return a cheap token suitable for incremental media-library synchronization."""
        with self._lock:
            self._refresh_if_external_change()
            stamp = self._known_stamp or (0, 0)
            return str(self.path), self._revision, stamp[0], stamp[1]

    def snapshot(self) -> tuple[tuple[str, int, int, int], dict[str, dict[str, Any]]]:
        with self._lock:
            self._refresh_if_external_change()
            token = self.change_token()
            return token, {
                str(key): deepcopy(value)
                for key, value in self._data.items()
                if isinstance(value, dict)
            }

    def _decode(self, path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("索引顶层必须是 JSON 对象")
        return raw

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return self._decode(self.path)
        except (json.JSONDecodeError, OSError, ValueError) as primary_error:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            corrupt = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
            try:
                os.replace(self.path, corrupt)
            except OSError:
                corrupt = self.path
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            if backup.exists():
                try:
                    data = self._decode(backup)
                    atomic_write_json(self.path, data, backup=False)
                    warnings.warn(
                        f"索引损坏，已保留为 {corrupt.name} 并从备份恢复",
                        RuntimeWarning,
                    )
                    return data
                except (json.JSONDecodeError, OSError, ValueError):
                    pass
            warnings.warn(
                f"索引损坏，已保留为 {corrupt.name}: {primary_error}",
                RuntimeWarning,
            )
            return {}

    def _save(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, self._data, backup=True)
        self._known_stamp = self._file_stamp()
        self._revision += 1

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            self._refresh_if_external_change()
            value = self._data.get(key)
            return deepcopy(value) if isinstance(value, dict) else None

    def entries(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            self._refresh_if_external_change()
            return {
                str(key): deepcopy(value)
                for key, value in self._data.items()
                if isinstance(value, dict)
            }

    def _entry_target(self, entry: dict[str, Any]) -> Path | None:
        rel = str(entry.get("path") or "").strip()
        if not rel:
            return None
        try:
            return resolve_under(self.download_dir, rel)
        except UnsafePathError as exc:
            raise UnsafeIndexPathError(str(exc)) from exc

    def _entry_file(self, target: Path, rel: str) -> Path:
        try:
            candidate = resolve_under(self.download_dir, rel)
            if target.is_file():
                if candidate != target:
                    raise UnsafePathError("文件记录不属于索引目标")
            else:
                candidate.relative_to(target)
            return candidate
        except (UnsafePathError, ValueError) as exc:
            raise UnsafeIndexPathError(f"索引文件路径越出目标目录: {rel}") from exc

    def get_valid(self, key: str) -> dict[str, Any] | None:
        """Return an entry only when at least one recorded media output still exists."""
        with self._lock:
            self._refresh_if_external_change()
            entry = self._data.get(key)
            if not isinstance(entry, dict):
                return None
            target = self._entry_target(entry)
            if target is None or not target.exists():
                return None

            files = entry.get("files")
            if isinstance(files, list) and files:
                for item in files:
                    if not isinstance(item, dict):
                        continue
                    rel = str(item.get("path") or "").strip()
                    if not rel:
                        continue
                    candidate = self._entry_file(target, rel)
                    if candidate.is_file() and candidate.stat().st_size > 0:
                        return deepcopy(entry)
                return None

            candidates = [target] if target.is_file() else target.rglob("*")
            for candidate in candidates:
                if (
                    candidate.is_file()
                    and not candidate.is_symlink()
                    and candidate.suffix.lower() in MEDIA_EXTENSIONS
                    and candidate.stat().st_size > 0
                ):
                    return deepcopy(entry)
            return None

    def has(self, key: str) -> bool:
        return self.get_valid(key) is not None

    def list_groups(self) -> list[str]:
        with self._lock:
            self._refresh_if_external_change()
            groups = {
                str(entry.get("group") or "").strip()
                for entry in self._data.values()
                if isinstance(entry, dict) and str(entry.get("group") or "").strip()
            }
        return sorted(groups, key=lambda item: item.casefold())

    def put(
        self,
        key: str,
        *,
        title: str = "",
        path: str,
        files: list[dict[str, Any]],
        extra: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._refresh_if_external_change()
            target = resolve_under(self.download_dir, path)
            for item in files:
                self._entry_file(target, str(item.get("path") or ""))
            entry: dict[str, Any] = {
                "title": title,
                "path": path,
                "files": deepcopy(files),
                "finished_at": time.time(),
            }
            if extra:
                entry.update(deepcopy(extra))
            self._data[key] = entry
            self._save()

    def patch_entry(self, key: str, patch: dict[str, Any]) -> bool:
        return self.patch_entries({key: patch}) > 0

    def patch_entries(self, patches: dict[str, dict[str, Any]]) -> int:
        """Batch metadata updates into one atomic index write."""
        with self._lock:
            self._refresh_if_external_change()
            changed = 0
            for key, values in patches.items():
                entry = self._data.get(key)
                if not isinstance(entry, dict) or not isinstance(values, dict):
                    continue
                updated = deepcopy(entry)
                for field, value in values.items():
                    if value is None:
                        updated.pop(str(field), None)
                    else:
                        updated[str(field)] = deepcopy(value)
                if updated != entry:
                    self._data[key] = updated
                    changed += 1
            if changed:
                self._save()
            return changed

    def discard_entry(self, key: str) -> bool:
        """Remove index metadata only; never touches files."""
        with self._lock:
            self._refresh_if_external_change()
            existed = self._data.pop(key, None) is not None
            if existed:
                self._save()
            return existed

    def remove_entry_and_files(self, key: str) -> bool:
        """Delete a recorded target only after strict download-root containment checks."""
        with self._lock:
            self._refresh_if_external_change()
            entry = self._data.get(key)
            if not isinstance(entry, dict):
                return False
            target = self._entry_target(entry)
            if target is not None and target.exists():
                if target.is_symlink():
                    raise UnsafeIndexPathError(f"拒绝删除符号链接: {target}")
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.is_file():
                    target.unlink()
                else:
                    raise UnsafeIndexPathError(f"拒绝删除特殊文件: {target}")
            self._data.pop(key, None)
            self._save()
            return True
