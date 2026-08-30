from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAX_TRACKED_FILE = 50 * 1024 * 1024
MAX_TRACKED_LAUNCHER = 100 * 1024 * 1024
FORBIDDEN_NAMES = {
    ".env",
    "BBDown.data",
    "bootstrap-token.txt",
    "RELEASE_MANIFEST.sha256",
}
FORBIDDEN_DIRS = {
    ".git",
    ".venv",
    ".runtime",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "bootstrap",
    "wheelhouse",
}
FORBIDDEN_RELATIVE = {
    "config/config.json",
    "config/runtime.env",
    "docker/.env",
}
SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:SESSDATA|bili_jct|DedeUserID)\s*=\s*[A-Za-z0-9%._~-]{8,}"
)
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\Users\\|/home/[^/]+/|/mnt/data/)")
ABSOLUTE_PATH_SCAN_EXEMPT = {"tools/verify_source.py"}
TEXT_SUFFIXES = {
    ".py",
    ".ps1",
    ".js",
    ".mjs",
    ".css",
    ".html",
    ".md",
    ".txt",
    ".json",
    ".bat",
    ".ini",
    ".toml",
    ".yml",
    ".yaml",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".sh",
    ".lock",
    ".default",
}


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _tracked_paths() -> tuple[str, ...] | None:
    if not (ROOT / ".git").exists():
        return None
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = (item.decode("utf-8") for item in result.stdout.split(b"\0") if item)
    return tuple(
        sorted(
            relative
            for relative in paths
            if (ROOT / relative).exists() or (ROOT / relative).is_symlink()
        )
    )


def _fallback_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_file()
            and not any(part in FORBIDDEN_DIRS for part in path.relative_to(ROOT).parts)
        )
    )


def _is_allowed_large_launcher(relative: str, size: int) -> bool:
    path = Path(relative)
    return (
        path.parts[:1] == ("dist",)
        and path.suffix.lower() == ".exe"
        and size <= MAX_TRACKED_LAUNCHER
    )


def _check_file(relative: str, errors: list[str]) -> None:
    path = ROOT / relative
    if not path.exists() and not path.is_symlink():
        errors.append(f"Git 跟踪文件不存在: {relative}")
        return
    if _is_reparse_point(path):
        errors.append(f"源码仓库不得包含符号链接或重解析点: {relative}")
        return
    if not path.is_file():
        errors.append(f"Git 跟踪路径不是普通文件: {relative}")
        return

    parts = Path(relative).parts
    if path.name in FORBIDDEN_NAMES or relative in FORBIDDEN_RELATIVE:
        errors.append(f"源码仓库包含禁止文件: {relative}")
        return
    if any(part in FORBIDDEN_DIRS for part in parts):
        errors.append(f"源码仓库跟踪了运行时目录内容: {relative}")
        return

    size = path.stat().st_size
    if size > MAX_TRACKED_FILE and not _is_allowed_large_launcher(relative, size):
        errors.append(f"源码仓库包含未说明的超过 50 MiB 文件: {relative}")
        return

    suffix = path.suffix.lower() or path.name.lower()
    if size > 2 * 1024 * 1024 or suffix not in TEXT_SUFFIXES:
        return
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if SECRET_RE.search(content):
        errors.append(f"疑似包含真实 Bilibili 登录凭据: {relative}")
    if (
        relative not in ABSOLUTE_PATH_SCAN_EXEMPT
        and not relative.startswith("archive/")
        and ABSOLUTE_PATH_RE.search(content)
    ):
        errors.append(f"疑似包含构建机绝对路径: {relative}")


def main() -> int:
    errors: list[str] = []
    if sys.version_info[:2] != (3, 11):
        errors.append(
            "源码验证必须使用 Python 3.11，"
            f"当前为 {sys.version_info.major}.{sys.version_info.minor}"
        )

    paths = _tracked_paths() or _fallback_paths()
    for relative in paths:
        _check_file(relative, errors)

    if errors:
        print("[失败] 源码安全边界发现问题：")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("[通过] Git 跟踪文件的类型、大小、路径和敏感信息边界正常。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
