from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.constants import MEDIA_EXTENSIONS
from app.path_safety import UnsafePathError, relative_posix, resolve_under

_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def target_dir_name(key: str) -> str:
    key = str(key).strip()
    if _SAFE_KEY_RE.fullmatch(key):
        return key
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"url-{digest}"


def final_relative_path(key: str, group_folder: str | None = None) -> str:
    if group_folder:
        return f"groups/{group_folder}/items/{target_dir_name(key)}"
    return f"items/{target_dir_name(key)}"


def work_relative_path(key: str, task_id: str) -> str:
    return f".bili_tmp/{target_dir_name(key)}-{task_id}"


def _remove_existing(path: Path) -> None:
    if path.is_symlink():
        raise UnsafePathError(f"拒绝操作符号链接: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def prepare_work_dir(download_dir: Path, key: str, task_id: str) -> Path:
    base = Path(download_dir).resolve()
    rel = work_relative_path(key, task_id)
    work = resolve_under(base, rel)
    work.parent.mkdir(parents=True, exist_ok=True)
    if work.exists() or work.is_symlink():
        _remove_existing(work)
    work.mkdir(parents=True, exist_ok=False)
    return work


def cleanup_work_dir(download_dir: Path, key: str, task_id: str) -> None:
    base = Path(download_dir).resolve()
    work = resolve_under(base, work_relative_path(key, task_id))
    if work.exists() or work.is_symlink():
        _remove_existing(work)


def discover_media_files(download_dir: Path, directory: Path) -> list[dict[str, Any]]:
    base = Path(download_dir).resolve()
    directory = Path(directory).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise UnsafePathError(f"产物目录越界: {directory}") from exc

    files: list[dict[str, Any]] = []
    for candidate in sorted(directory.rglob("*")):
        if candidate.is_symlink():
            raise UnsafePathError(f"产物包含符号链接: {candidate}")
        if not candidate.is_file() or candidate.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        stat = candidate.stat()
        if stat.st_size <= 0:
            continue
        files.append(
            {
                "path": relative_posix(base, candidate),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return files


@dataclass
class Promotion:
    final_dir: Path
    backup_dir: Path
    files: list[dict[str, Any]]
    had_old: bool
    _committed: bool = False

    def commit(self) -> None:
        """Finalize a successful replacement; stale backup removal is best effort."""
        self._committed = True
        if self.backup_dir.exists() or self.backup_dir.is_symlink():
            try:
                _remove_existing(self.backup_dir)
            except OSError:
                # A leftover backup is safer than turning a completed download into failure.
                pass

    def rollback(self) -> None:
        """Restore the previous final directory when the index commit fails."""
        if self._committed:
            return
        if self.final_dir.exists() or self.final_dir.is_symlink():
            _remove_existing(self.final_dir)
        if self.had_old and self.backup_dir.exists():
            os.replace(self.backup_dir, self.final_dir)


def promote_work_dir(
    download_dir: Path,
    key: str,
    task_id: str,
    *,
    final_rel: str | None = None,
) -> Promotion:
    """Stage a validated replacement while retaining the old target for rollback."""
    base = Path(download_dir).resolve()
    work = resolve_under(base, work_relative_path(key, task_id))
    final = resolve_under(base, final_rel or final_relative_path(key))
    if not work.is_dir() or work.is_symlink():
        raise FileNotFoundError(f"临时产物目录不存在: {work}")

    preflight = discover_media_files(base, work)
    if not preflight:
        raise ValueError("BBDown 返回成功，但未生成非空媒体文件")

    final.parent.mkdir(parents=True, exist_ok=True)
    backup = resolve_under(base, f".bili_backup/{target_dir_name(key)}-{task_id}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists() or backup.is_symlink():
        _remove_existing(backup)

    moved_old = False
    moved_new = False
    try:
        if final.exists() or final.is_symlink():
            if final.is_symlink():
                raise UnsafePathError(f"最终目录是符号链接: {final}")
            os.replace(final, backup)
            moved_old = True
        os.replace(work, final)
        moved_new = True
        files = discover_media_files(base, final)
        if not files:
            raise ValueError("产物替换后未找到非空媒体文件")
        return Promotion(final, backup, files, moved_old)
    except Exception:
        if moved_new and (final.exists() or final.is_symlink()):
            _remove_existing(final)
        if moved_old and backup.exists() and not final.exists():
            os.replace(backup, final)
        raise


def remove_relative_target(download_dir: Path, relative_path: str) -> bool:
    """Remove one previously indexed target after strict root containment checks."""
    base = Path(download_dir).resolve()
    target = resolve_under(base, relative_path)
    if not target.exists() and not target.is_symlink():
        return False
    _remove_existing(target)
    # Remove now-empty grouping parents (items/group), but never the groups root
    # or reserved service directories.
    for parent in target.parents:
        if parent == base or parent.name in {"groups", ".bili_tmp", ".bili_backup"}:
            break
        try:
            parent.rmdir()
        except OSError:
            break
    return True


def infer_title(files: list[dict[str, Any]], fallback: str) -> str:
    if not files:
        return fallback
    first = Path(str(files[0].get("path") or ""))
    return first.stem or fallback
