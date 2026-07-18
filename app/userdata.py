from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from app.index_store import INDEX_NAME, IndexStore
from app.paths import ROOT
from app.runtime import RuntimeSettings


def _absolute_no_follow(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _move_regular_file(source: Path, target: Path) -> bool:
    """Move one regular file without replacing an existing destination."""
    source = Path(source)
    target = Path(target)
    if target.exists() or target.is_symlink() or not source.exists():
        return False
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"旧版用户数据不是普通文件: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError:
        temporary = target.with_name(target.name + ".migrating")
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        shutil.copy2(source, temporary)
        if temporary.stat().st_size != source.stat().st_size:
            temporary.unlink(missing_ok=True)
            raise OSError(f"迁移用户数据校验失败: {source}")
        os.replace(temporary, target)
        source.unlink()
    return True


def migrate_legacy_database(runtime: RuntimeSettings) -> dict[str, Any]:
    """Move the historical SQLite database from config/root into userdata.

    The operation runs before SQLite is opened. Existing userdata always wins,
    and WAL/SHM sidecars are moved together when a migration occurs.
    """
    target = _absolute_no_follow(Path(runtime.database_path))
    target.parent.mkdir(parents=True, exist_ok=True)
    candidates = [
        Path(runtime.config_dir) / "bili_workspace.db",
        ROOT / "config" / "bili_workspace.db",
        ROOT / "bili_workspace.db",
    ]
    moved_from = ""
    for candidate in candidates:
        legacy = _absolute_no_follow(candidate)
        if legacy == target or not legacy.exists() or target.exists():
            continue
        if _move_regular_file(legacy, target):
            moved_from = str(legacy)
            for suffix in ("-wal", "-shm"):
                _move_regular_file(Path(str(legacy) + suffix), Path(str(target) + suffix))
            break
    return {
        "database_path": str(target),
        "migrated": bool(moved_from),
        "migrated_from": moved_from,
    }


class UserdataIndexStore(IndexStore):
    """Download index whose JSON metadata lives in userdata, not media folders."""

    def __init__(self, download_dir: Path, index_path: Path):
        self._userdata_index_path = Path(index_path).resolve()
        super().__init__(download_dir)

    def set_download_dir(self, download_dir: Path) -> None:
        with self._lock:
            resolved = Path(download_dir).resolve()
            target = self._userdata_index_path
            if self.download_dir == resolved and self.path == target:
                return
            resolved.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)

            legacy = resolved / INDEX_NAME
            moved = _move_regular_file(legacy, target)
            legacy_backup = legacy.with_suffix(legacy.suffix + ".bak")
            target_backup = target.with_suffix(target.suffix + ".bak")
            if moved or not legacy.exists():
                _move_regular_file(legacy_backup, target_backup)

            self.download_dir = resolved
            self.path = target
            self._data = self._load()
            self._known_stamp = self._file_stamp()
            self._revision += 1
