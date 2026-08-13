from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _is_reparse_point(path: Path) -> bool:
    try:
        status = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(status, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse_point(path)


def _assert_regular_or_missing(path: Path, label: str) -> None:
    if _path_exists(path) and (
        not path.is_file() or path.is_symlink() or _is_reparse_point(path)
    ):
        raise ValueError(f"{label}必须是普通文件：{path}")


def atomic_write_text(path: Path, text: str, *, backup: bool = True) -> None:
    """Write UTF-8 text using a same-directory temporary file and os.replace()."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_regular_or_missing(path, "写入目标")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    backup_tmp: Path | None = None
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if backup and path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            _assert_regular_or_missing(backup_path, "备份目标")
            backup_fd, backup_name = tempfile.mkstemp(
                prefix=f".{backup_path.name}.", suffix=".tmp", dir=path.parent
            )
            backup_tmp = Path(backup_name)
            with os.fdopen(backup_fd, "wb") as destination:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(backup_tmp, backup_path)
            backup_tmp = None
        os.replace(tmp, path)
        # Best effort directory sync on POSIX; Windows does not expose O_DIRECTORY.
        if hasattr(os, "O_DIRECTORY"):
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        if backup_tmp is not None:
            try:
                backup_tmp.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(path: Path, data: dict[str, Any], *, backup: bool = True) -> None:
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        backup=backup,
    )
