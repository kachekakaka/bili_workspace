from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath


class UnsafePathError(ValueError):
    pass


def _portable_relative_parts(value: str | os.PathLike[str]) -> tuple[str, ...]:
    """Parse an internal path consistently on Windows and POSIX.

    Index paths are written with POSIX separators.  We still inspect them as a
    Windows path first so drive-relative paths (``C:foo``), UNC paths and
    backslash traversal cannot become dangerous after moving an index between
    operating systems.
    """
    raw = os.fspath(value)
    if not isinstance(raw, str):
        raise UnsafePathError("路径必须是文本")
    if not raw or "\x00" in raw:
        raise UnsafePathError("拒绝空路径或 NUL 字符")

    windows = PureWindowsPath(raw)
    if windows.is_absolute() or windows.drive or windows.root:
        raise UnsafePathError(f"拒绝 Windows 绝对/驱动器路径: {value}")

    normalized = raw.replace("\\", "/")
    posix = PurePosixPath(normalized)
    if posix.is_absolute():
        raise UnsafePathError(f"拒绝绝对路径: {value}")
    parts = posix.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise UnsafePathError(f"拒绝无效相对路径: {value}")
    return parts


def resolve_under(
    base: Path, value: str | os.PathLike[str], *, allow_base: bool = False
) -> Path:
    """Resolve a relative path under *base* while rejecting traversal and symlink hops."""
    base = Path(base).resolve()
    parts = _portable_relative_parts(value)

    lexical = base.joinpath(*parts)
    cursor = base
    for part in parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise UnsafePathError(f"拒绝符号链接路径: {value}")

    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise UnsafePathError(f"路径越界: {value}") from exc
    if resolved == base and not allow_base:
        raise UnsafePathError("拒绝操作下载根目录")
    return resolved


def relative_posix(base: Path, target: Path) -> str:
    base = Path(base).resolve()
    target = Path(target).resolve(strict=False)
    try:
        rel = target.relative_to(base)
    except ValueError as exc:
        raise UnsafePathError(f"目标不在下载目录内: {target}") from exc
    if not rel.parts:
        raise UnsafePathError("拒绝使用下载根目录作为目标")
    return rel.as_posix()
