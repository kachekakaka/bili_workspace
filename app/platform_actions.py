from __future__ import annotations

import os
from pathlib import Path

from app.path_safety import relative_posix, resolve_under


def resolve_output_folder(download_dir: Path, relative_path: str) -> Path:
    root = Path(download_dir).resolve()
    target = resolve_under(root, relative_path)
    if not target.exists():
        raise FileNotFoundError(f"输出路径不存在: {relative_path}")
    folder = target if target.is_dir() else target.parent
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("输出目录类型异常")
    # Revalidate the final folder after following normal path components.
    relative_posix(root, folder)
    return folder


def open_output_folder(download_dir: Path, relative_path: str) -> str:
    folder = resolve_output_folder(download_dir, relative_path)
    if os.name != "nt":
        raise RuntimeError("打开目录功能仅在 Windows 上可用")
    os.startfile(str(folder))  # type: ignore[attr-defined]
    return relative_posix(Path(download_dir).resolve(), folder)
