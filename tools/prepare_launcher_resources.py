"""生成 Windows 启动器内置的确定源码、BBDown 与 FFmpeg 资源。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from tools.build_ffmpeg_windows import (
    BUILD_SCRIPT as FFMPEG_BUILD_SCRIPT,
    DEFAULT_OUTPUT as DEFAULT_FFMPEG_OUTPUT,
    DOCKERFILE as FFMPEG_DOCKERFILE,
    EVIDENCE_NAME as FFMPEG_BUILD_EVIDENCE_NAME,
    FFMPEG_RELEASE_KEY_NAME,
    FFMPEG_RELEASE_KEY_SHA256,
    FFMPEG_RELEASE_KEY_SIZE,
    FFMPEG_RELEASE_KEY_URL,
    FFMPEG_SIGNATURE_NAME,
    FFMPEG_SIGNATURE_SHA256,
    FFMPEG_SIGNATURE_SIZE,
    FFMPEG_SIGNATURE_URL,
    FFMPEG_SOURCE_NAME,
    FFMPEG_SOURCE_SHA256,
    FFMPEG_SOURCE_SIZE,
    FFMPEG_SOURCE_URL,
    build as build_ffmpeg_windows,
    validate_output as validate_ffmpeg_output,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "build" / "bili-launcher-resources"
DEFAULT_CACHE = ROOT / "build" / "launcher-download-cache"
FFMPEG_SOURCE_EVIDENCE_MEMBER = "THIRD_PARTY_LICENSES/FFmpeg.SOURCE.json"
FFMPEG_SOURCE_MEMBER = f"THIRD_PARTY_SOURCES/{FFMPEG_SOURCE_NAME}"

BBDOWN_NAME = "BBDown_1.6.3_20240814_win-x64.zip"
BBDOWN_URL = f"https://github.com/nilaoda/BBDown/releases/download/1.6.3/{BBDOWN_NAME}"
BBDOWN_SHA256 = "40f1e2af0d4e74df765c6f93d2e931f9bea201d5168d0bc62dc35a54b7e0ec02"
BBDOWN_SIZE = 8_040_728

PYSIDE_SOURCE_VERSION = "6.11.1"
PYSIDE_LICENSE_BASE_URL = (
    "https://code.qt.io/cgit/pyside/pyside-setup.git/plain/LICENSES"
)
PYSIDE_LICENSE_TEXTS: dict[str, dict[str, object]] = {
    "GPL-3.0-only.txt": {
        "url": f"{PYSIDE_LICENSE_BASE_URL}/GPL-3.0-only.txt?h=v{PYSIDE_SOURCE_VERSION}",
        "sha256": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
        "size": 35_147,
    },
    "LGPL-3.0-only.txt": {
        "url": f"{PYSIDE_LICENSE_BASE_URL}/LGPL-3.0-only.txt?h=v{PYSIDE_SOURCE_VERSION}",
        "sha256": "da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768",
        "size": 7_651,
    },
    "Qt-GPL-exception-1.0.txt": {
        "url": (
            f"{PYSIDE_LICENSE_BASE_URL}/Qt-GPL-exception-1.0.txt"
            f"?h=v{PYSIDE_SOURCE_VERSION}"
        ),
        "sha256": "40678d338ce53cd93f8b22b281a2ecbcaa3ee65ce60b25ffb0c462b0530846b2",
        "size": 965,
    },
}

LICENSE_SHA256 = {
    "BBDown.LICENSE.txt": "fdf0e8b5269954ed06c1a704c76f797dd1f19a60ef686cf697829e82110caa5b",
}

CHUNK_SIZE = 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
USER_AGENT = "bili-workspace-launcher/0.7.0 resource-builder"
MAX_LICENSE_FILE_BYTES = 2 * 1024 * 1024
MAX_LICENSE_TOTAL_BYTES = 24 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400

_LAUNCHER_DISTRIBUTIONS = {
    "PySide6": "6.11.1",
    "PySide6-Essentials": "6.11.1",
    "PySide6-Addons": "6.11.1",
    "shiboken6": "6.11.1",
    "PyInstaller": "6.22.0",
}

_IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
_FORBIDDEN_FILE_NAMES = {
    ".env",
    "BBDown.data",
    "credentials.json",
    "launcher.json",
    "secrets.json",
}
_FORBIDDEN_FILE_NAMES_FOLDED = {name.casefold() for name in _FORBIDDEN_FILE_NAMES}
_SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:SESSDATA|bili_jct|DedeUserID)\s*=\s*[A-Za-z0-9%._~-]{8,}"
)
_TEXT_SCAN_SUFFIXES = {
    ".css",
    ".default",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".lock",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_FORBIDDEN_SUFFIXES = {
    ".db",
    ".jks",
    ".keystore",
    ".mp4",
    ".mkv",
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".pyc",
    ".sqlite",
    ".sqlite3",
}
_ALLOWED_EXECUTABLES = {
    "windows-tools/BBDown.exe",
    "windows-tools/ffmpeg/bin/ffmpeg.exe",
}
_ALLOWED_UNTRACKED_DOCKER_INPUTS = {
    "app/defaults/config.json.default",
    "app/defaults/runtime.env.default",
    "app/defaults/tags.json.default",
}
_LAUNCHER_MODULE_NAMES = {
    "__init__.py",
    "__main__.py",
    "backend_process.py",
    "cli.py",
    "commands.py",
    "constants.py",
    "docker_jobs.py",
    "gui.py",
    "paths.py",
    "ports.py",
    "resources.py",
    "settings.py",
    "version.py",
}
_WINDOWS_RESERVED_BASENAMES = {
    "aux",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse_point(path)


def _assert_no_reparse_ancestors(path: Path, label: str) -> None:
    absolute = Path(path).absolute()
    for candidate in (absolute, *absolute.parents):
        if _path_exists(candidate) and (
            candidate.is_symlink() or _is_reparse_point(candidate)
        ):
            raise RuntimeError(f"{label}不能经过符号链接或重解析点：{candidate}")


def _inside(path: Path, parent: Path) -> bool:
    candidate = path.resolve(strict=False)
    boundary = parent.resolve(strict=False)
    return candidate == boundary or boundary in candidate.parents


def _assert_build_target(path: Path) -> None:
    path = Path(path).absolute()
    build_root = (ROOT / "build").resolve(strict=False)
    if path.resolve(strict=False) == build_root or not _inside(path, build_root):
        raise RuntimeError(f"资源 staging 必须是 build 下的具体子目录：{path}")
    current = Path(path)
    while current != ROOT / "build" and current != current.parent:
        if _path_exists(current) and (current.is_symlink() or _is_reparse_point(current)):
            raise RuntimeError(f"资源 staging 路径不能经过重解析点：{current}")
        current = current.parent


def download(
    url: str,
    expected_sha256: str,
    expected_size: int,
    destination: Path,
    retries: int = 4,
) -> Path:
    if expected_size <= 0 or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("固定资源的期望大小或 SHA-256 无效")
    _assert_no_reparse_ancestors(destination.parent, "下载缓存路径")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _path_exists(destination) and (
        not destination.is_file()
        or destination.is_symlink()
        or _is_reparse_point(destination)
    ):
        raise RuntimeError(f"下载缓存目标不是普通文件：{destination}")
    if (
        destination.is_file()
        and destination.stat().st_size == expected_size
        and sha256_file(destination) == expected_sha256
    ):
        return destination
    destination.unlink(missing_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        partial = destination.with_suffix(destination.suffix + ".part")
        partial.unlink(missing_ok=True)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("xb") as output:
                raw_length = response.headers.get("Content-Length")
                if raw_length is not None:
                    try:
                        content_length = int(raw_length)
                    except ValueError as exc:
                        raise ValueError("固定资源响应的 Content-Length 无效") from exc
                    if content_length != expected_size:
                        raise ValueError(
                            f"{destination.name} 响应大小不匹配："
                            f"{content_length}，期望 {expected_size}"
                        )
                received = 0
                while chunk := response.read(CHUNK_SIZE):
                    received += len(chunk)
                    if received > expected_size:
                        raise ValueError(f"{destination.name} 下载内容超过固定大小")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            actual_size = partial.stat().st_size
            actual = sha256_file(partial)
            if actual_size != expected_size or actual != expected_sha256:
                raise ValueError(
                    f"{destination.name} 大小或 SHA-256 不匹配："
                    f"{actual_size}/{actual}，期望 {expected_size}/{expected_sha256}"
                )
            os.replace(partial, destination)
            return destination
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(attempt * 2)
    raise RuntimeError(f"无法取得固定资源 {destination.name}: {last_error}") from last_error


def safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/").rstrip("/")
    raw_parts = normalized.split("/")
    member = PurePosixPath(normalized)
    if (
        not member.parts
        or member.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or member.parts[0].endswith(":")
        or any(
            len(part) > 255
            or part != part.rstrip(" .")
            or ":" in part
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_BASENAMES
            for part in member.parts
        )
    ):
        raise ValueError(f"压缩包路径不安全：{name}")
    return member


def _zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    seen: set[str] = set()
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        files = [info for info in entries if not info.is_dir()]
        if len(files) > MAX_ARCHIVE_FILES:
            raise ValueError("压缩包文件数量超过安全上限")
        for info in entries:
            member = safe_member(info.filename)
            folded = member.as_posix().casefold()
            if folded in seen or _zip_symlink(info) or info.flag_bits & 0x1:
                raise ValueError(f"压缩包包含重复路径、符号链接或加密成员：{info.filename}")
            seen.add(folded)
            if info.is_dir():
                destination.joinpath(*member.parts).mkdir(parents=True, exist_ok=True)
                continue
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("压缩包展开大小超过安全上限")
            target = destination.joinpath(*member.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=CHUNK_SIZE)


def _unique_file(root: Path, basename: str) -> Path:
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name.casefold() == basename.casefold()
    ]
    if len(matches) != 1:
        raise RuntimeError(f"期望压缩包中恰好一个 {basename}，实际 {len(matches)} 个")
    return matches[0]


def _copy_regular(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink() or _is_reparse_point(source):
        raise RuntimeError(f"启动器资源缺少普通文件：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _walk_regular_tree(source: Path, *, skip_ignored: bool) -> list[tuple[Path, bool]]:
    entries: list[tuple[Path, bool]] = []

    def walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as scanned:
                children = sorted(scanned, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            raise RuntimeError(f"无法扫描启动器资源目录：{directory}") from exc
        for child in children:
            path = Path(child.path)
            if child.is_symlink() or _is_reparse_point(path):
                raise RuntimeError(f"启动器资源禁止符号链接或重解析点：{path}")
            try:
                is_directory = child.is_dir(follow_symlinks=False)
                is_file = child.is_file(follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError(f"无法读取启动器资源类型：{path}") from exc
            if is_directory:
                if skip_ignored and child.name in _IGNORED_DIRECTORY_NAMES:
                    continue
                entries.append((path, True))
                walk(path)
            elif is_file:
                entries.append((path, False))
            else:
                raise RuntimeError(f"启动器资源包含不支持的文件类型：{path}")

    walk(source)
    return entries


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    allowed_repository_files: set[str] | None = None,
) -> None:
    if not source.is_dir() or source.is_symlink() or _is_reparse_point(source):
        raise RuntimeError(f"启动器资源目录缺失：{source}")
    for path, is_directory in _walk_regular_tree(source, skip_ignored=True):
        relative = path.relative_to(source)
        target = destination / relative
        if is_directory:
            target.mkdir(parents=True, exist_ok=True)
        else:
            if allowed_repository_files is not None:
                relative_to_repository = path.relative_to(ROOT).as_posix()
                if relative_to_repository not in allowed_repository_files:
                    raise RuntimeError(
                        f"拒绝把未登记的工作区文件打入 EXE：{relative_to_repository}"
                    )
            _copy_regular(path, target)


def _git_tracked_files() -> set[str] | None:
    if not (ROOT / ".git").exists():
        raise RuntimeError("启动器资源构建必须在可审计的 Git 工作树中执行")
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("无法取得 Git 跟踪文件清单，拒绝构建资源") from exc
    try:
        return {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}
    except UnicodeDecodeError as exc:
        raise RuntimeError("Git 跟踪文件清单不是 UTF-8，拒绝构建资源") from exc


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _locked_runtime_distributions() -> dict[str, str]:
    locked: dict[str, str] = {}
    lock_path = ROOT / "requirements" / "runtime.lock"
    for number, raw_line in enumerate(lock_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1:
            raise RuntimeError(f"运行依赖锁第 {number} 行不是精确版本：{line}")
        name, version = line.split("==", 1)
        if not name or not version:
            raise RuntimeError(f"运行依赖锁第 {number} 行无效：{line}")
        locked[name] = version
    return locked


def _is_license_entry(relative: PurePosixPath) -> bool:
    folded_parts = [part.casefold() for part in relative.parts]
    if any(part in {"license", "licenses"} for part in folded_parts[:-1]):
        return True
    basename = folded_parts[-1]
    return any(
        basename == prefix or basename.startswith(prefix + separator)
        for prefix in ("license", "licence", "copying", "notice")
        for separator in (".", "-", "_")
    )


def collect_license_materials(
    destination: Path,
    *,
    expected_distributions: dict[str, str] | None = None,
    python_license: Path | None = None,
    pyside_license_files: dict[str, Path] | None = None,
) -> Path:
    """从实际构建环境收集许可证，并记录逐文件身份。"""

    expected = (
        {**_locked_runtime_distributions(), **_LAUNCHER_DISTRIBUTIONS}
        if expected_distributions is None
        else dict(expected_distributions)
    )
    if destination.exists():
        raise RuntimeError(f"许可证 staging 已存在：{destination}")
    destination.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    total = 0
    has_lgpl3 = False
    seen_destinations: set[str] = set()
    for requested_name, expected_version in sorted(
        expected.items(), key=lambda item: _canonical_distribution_name(item[0])
    ):
        try:
            distribution = importlib.metadata.distribution(requested_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"构建环境缺少固定依赖：{requested_name}=={expected_version}") from exc
        actual_name = distribution.metadata.get("Name", requested_name)
        if (
            _canonical_distribution_name(actual_name)
            != _canonical_distribution_name(requested_name)
            or distribution.version != expected_version
        ):
            raise RuntimeError(
                f"构建依赖身份不匹配：{requested_name}=={distribution.version}，"
                f"期望 {expected_version}"
            )
        package_files = distribution.files
        if package_files is None:
            raise RuntimeError(f"构建依赖缺少可审计文件清单：{requested_name}")
        selected: list[tuple[PurePosixPath, Path, int]] = []
        for item in package_files:
            pure = PurePosixPath(str(item).replace("\\", "/"))
            if (
                pure.is_absolute()
                or not pure.parts
                or any(part in {"", ".", ".."} for part in pure.parts)
                or not _is_license_entry(pure)
            ):
                continue
            source = Path(distribution.locate_file(item))
            if not source.is_file() or source.is_symlink() or _is_reparse_point(source):
                raise RuntimeError(f"依赖许可证不是普通文件：{requested_name}/{pure}")
            size = source.stat().st_size
            if size <= 0 or size > MAX_LICENSE_FILE_BYTES:
                raise RuntimeError(f"依赖许可证大小异常：{requested_name}/{pure}")
            selected.append((pure, source, size))
        if not selected:
            raise RuntimeError(f"构建依赖未提供许可证文件：{requested_name}")
        package_dir = _canonical_distribution_name(requested_name)
        for pure, source, size in sorted(selected, key=lambda item: item[0].as_posix().casefold()):
            target_relative = PurePosixPath("python-packages", package_dir, *pure.parts)
            folded = target_relative.as_posix().casefold()
            if folded in seen_destinations:
                raise RuntimeError(f"依赖许可证目标路径冲突：{target_relative}")
            seen_destinations.add(folded)
            target = destination.joinpath(*target_relative.parts)
            _copy_regular(source, target)
            digest = sha256_file(target)
            if package_dir.startswith(("pyside6", "shiboken6")):
                content = target.read_bytes()
                has_lgpl3 = has_lgpl3 or (
                    b"GNU LESSER GENERAL PUBLIC LICENSE" in content
                    and (b"Version 3" in content or b"version 3" in content)
                )
            total += size
            if total > MAX_LICENSE_TOTAL_BYTES:
                raise RuntimeError("构建依赖许可证总大小超过安全上限")
            entries.append(
                {
                    "distribution": actual_name,
                    "version": distribution.version,
                    "source_path": pure.as_posix(),
                    "path": target_relative.as_posix(),
                    "size": size,
                    "sha256": digest,
                }
            )

    requires_pyside = any(
        _canonical_distribution_name(name).startswith(("pyside6", "shiboken6"))
        for name in expected
    )
    if requires_pyside:
        if pyside_license_files is None or set(pyside_license_files) != set(
            PYSIDE_LICENSE_TEXTS
        ):
            raise RuntimeError("PySide6 官方开源许可证文件集合不完整")
        for name, identity in sorted(PYSIDE_LICENSE_TEXTS.items()):
            source = Path(pyside_license_files[name])
            expected_size = identity["size"]
            expected_sha256 = identity["sha256"]
            if (
                isinstance(expected_size, bool)
                or not isinstance(expected_size, int)
                or not isinstance(expected_sha256, str)
                or not source.is_file()
                or source.is_symlink()
                or _is_reparse_point(source)
                or source.stat().st_size != expected_size
                or sha256_file(source) != expected_sha256
            ):
                raise RuntimeError(f"PySide6 官方开源许可证身份不匹配：{name}")
            source_path = PurePosixPath(
                f"qtpyside-v{PYSIDE_SOURCE_VERSION}", "LICENSES", name
            )
            target_relative = PurePosixPath(
                "python-packages", "pyside6", *source_path.parts
            )
            folded = target_relative.as_posix().casefold()
            if folded in seen_destinations:
                raise RuntimeError(f"依赖许可证目标路径冲突：{target_relative}")
            seen_destinations.add(folded)
            target = destination.joinpath(*target_relative.parts)
            _copy_regular(source, target)
            content = target.read_bytes()
            if name == "LGPL-3.0-only.txt":
                has_lgpl3 = (
                    b"GNU LESSER GENERAL PUBLIC LICENSE" in content
                    and b"Version 3" in content
                )
            total += expected_size
            if total > MAX_LICENSE_TOTAL_BYTES:
                raise RuntimeError("构建依赖许可证总大小超过安全上限")
            entries.append(
                {
                    "distribution": "PySide6",
                    "version": PYSIDE_SOURCE_VERSION,
                    "source_path": source_path.as_posix(),
                    "path": target_relative.as_posix(),
                    "size": expected_size,
                    "sha256": expected_sha256,
                }
            )

    python_source = python_license or Path(sys.base_prefix) / "LICENSE.txt"
    if (
        not python_source.is_file()
        or python_source.is_symlink()
        or _is_reparse_point(python_source)
    ):
        raise RuntimeError(f"构建 Python 缺少普通许可证文件：{python_source}")
    python_target = destination / "python" / "LICENSE.txt"
    _copy_regular(python_source, python_target)
    python_entry = {
        "version": sys.version.split()[0],
        "path": python_target.relative_to(destination).as_posix(),
        "size": python_target.stat().st_size,
        "sha256": sha256_file(python_target),
    }
    if requires_pyside and not has_lgpl3:
        raise RuntimeError("PySide6 许可证材料缺少 LGPLv3 全文")
    manifest = {
        "schema_version": 1,
        "python": python_entry,
        "packages": entries,
        "contains_lgplv3_text": has_lgpl3,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def _copy_docker_context(source_root: Path) -> None:
    context = source_root / "docker-context"
    tracked = _git_tracked_files()
    allowed = None if tracked is None else tracked | _ALLOWED_UNTRACKED_DOCKER_INPUTS
    for directory in ("app", "web", "LICENSES"):
        _copy_tree(
            ROOT / directory,
            context / directory,
            allowed_repository_files=allowed,
        )
    direct_inputs = [
        (ROOT / "requirements" / "runtime.lock", context / "requirements" / "runtime.lock"),
        (ROOT / "THIRD_PARTY_NOTICES.md", context / "THIRD_PARTY_NOTICES.md"),
        *(
            (ROOT / "docker" / name, context / "docker" / name)
            for name in ("Dockerfile", "entrypoint.sh", "healthcheck.py")
        ),
    ]
    for source, destination in direct_inputs:
        relative = source.relative_to(ROOT).as_posix()
        if allowed is not None and relative not in allowed:
            raise RuntimeError(f"拒绝把未登记的工作区文件打入 EXE：{relative}")
        _copy_regular(source, destination)
    (context / ".dockerignore").write_text(
        ".git\n.env\n*.db\n*.sqlite*\nBBDown.data\nlauncher.json\n",
        encoding="utf-8",
        newline="\n",
    )


def _scan_source(source_root: Path) -> dict[str, dict[str, object]]:
    files: dict[str, dict[str, object]] = {}
    for path, is_directory in _walk_regular_tree(source_root, skip_ignored=False):
        if is_directory:
            continue
        relative = path.relative_to(source_root).as_posix()
        folded_name = path.name.casefold()
        if (
            folded_name in _FORBIDDEN_FILE_NAMES_FOLDED
            or folded_name.startswith(".env.")
            or path.suffix.lower() in _FORBIDDEN_SUFFIXES
        ):
            raise RuntimeError(f"禁止把本地配置、数据或产物打入 EXE：{relative}")
        if path.suffix.lower() == ".exe" and relative not in _ALLOWED_EXECUTABLES:
            raise RuntimeError(f"内置资源包含未授权 EXE：{relative}")
        if path.stat().st_size <= 2 * 1024 * 1024 and path.suffix.lower() in _TEXT_SCAN_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise RuntimeError(f"无法按 UTF-8 审计内置文本资源：{relative}") from exc
            if _SECRET_RE.search(text):
                raise RuntimeError(f"内置资源疑似包含真实 Bilibili 登录凭据：{relative}")
        files[relative] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    if set(_ALLOWED_EXECUTABLES) - set(files):
        raise RuntimeError("内置 Windows 工具不完整")
    return files


def _build_id(files: dict[str, dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for relative, entry in sorted(files.items()):
        digest.update(f"resource/{relative}\0{entry['sha256']}\0{entry['size']}\n".encode("utf-8"))
    launcher_root = ROOT / "launcher" / "bili_workspace_launcher"
    actual_modules = {
        path.name
        for path in launcher_root.glob("*.py")
        if path.is_file() and not path.is_symlink() and not _is_reparse_point(path)
    }
    if actual_modules != _LAUNCHER_MODULE_NAMES:
        missing = sorted(_LAUNCHER_MODULE_NAMES - actual_modules)
        extra = sorted(actual_modules - _LAUNCHER_MODULE_NAMES)
        raise RuntimeError(f"启动器模块集合不一致：缺失 {missing}；多出 {extra}")
    launcher_inputs = [launcher_root / name for name in sorted(_LAUNCHER_MODULE_NAMES)]
    launcher_inputs.extend(
        [
            ROOT / "launcher" / "bili_workspace_launcher_entry.py",
            ROOT / "launcher" / "bili-workspace-launcher.spec",
            ROOT / "launcher" / "requirements.txt",
            ROOT / "launcher" / "requirements-dev.txt",
            ROOT / "launcher" / "THIRD_PARTY_NOTICES.txt",
            ROOT / "launcher" / "RELINKING.md",
        ]
    )
    for path in launcher_inputs:
        if not path.is_file() or path.is_symlink() or _is_reparse_point(path):
            raise RuntimeError(f"构建身份输入缺失：{path}")
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _validate_replaceable_bundle(target: Path) -> None:
    if target.is_symlink() or _is_reparse_point(target) or not target.is_dir():
        raise RuntimeError(f"资源 staging 目标类型无效：{target}")
    try:
        with os.scandir(target) as entries:
            top_level = {entry.name for entry in entries}
        raw = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"资源 staging 不是本工具生成的完整目录：{target}") from exc
    build_id = raw.get("build_id") if isinstance(raw, dict) else None
    if (
        top_level != {"manifest.json", "source"}
        or not isinstance(raw, dict)
        or isinstance(raw.get("schema_version"), bool)
        or raw.get("schema_version") != 1
        or raw.get("product_version") != "0.7.0"
        or not isinstance(build_id, str)
        or re.fullmatch(r"[0-9a-f]{12}", build_id) is None
        or not isinstance(raw.get("files"), dict)
        or not raw["files"]
    ):
        raise RuntimeError(f"资源 staging 不是本工具生成的完整目录：{target}")
    _walk_regular_tree(target, skip_ignored=False)


def _remove_generated_directory(path: Path, label: str) -> None:
    if not _path_exists(path):
        return
    if path.is_symlink() or _is_reparse_point(path) or not path.is_dir():
        raise RuntimeError(f"{label}类型无效，拒绝清理：{path}")
    shutil.rmtree(path)


def _populate_bundle(
    *,
    target: Path,
    bbdown_archive: Path,
    ffmpeg_build: Path,
    ffmpeg_source: Path,
    ffmpeg_signature: Path,
    ffmpeg_release_key: Path,
    collect_installed_licenses: bool,
    pyside_license_files: dict[str, Path] | None,
) -> Path:
    source_root = target / "source"
    source_root.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="bili-launcher-tools-") as temporary_name:
        temporary = Path(temporary_name)
        bbdown_extract = temporary / "bbdown"
        safe_extract_zip(bbdown_archive, bbdown_extract)
        _copy_regular(
            _unique_file(bbdown_extract, "BBDown.exe"),
            source_root / "windows-tools" / "BBDown.exe",
        )
    _copy_regular(
        ffmpeg_build / "ffmpeg.exe",
        source_root / "windows-tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
    )
    _copy_regular(
        ffmpeg_build / "LICENSE.md",
        source_root / "windows-tools" / "LICENSES" / "FFmpeg.LICENSE.md",
    )
    _copy_regular(
        ffmpeg_build / "COPYING.LGPLv2.1",
        source_root / "windows-tools" / "LICENSES" / "FFmpeg.COPYING.LGPLv2.1.txt",
    )
    _copy_regular(
        ffmpeg_build / FFMPEG_BUILD_EVIDENCE_NAME,
        source_root.joinpath(*PurePosixPath(FFMPEG_SOURCE_EVIDENCE_MEMBER).parts),
    )
    _copy_regular(
        ffmpeg_source,
        source_root.joinpath(*PurePosixPath(FFMPEG_SOURCE_MEMBER).parts),
    )
    _copy_regular(
        ffmpeg_signature,
        source_root / "THIRD_PARTY_SOURCES" / FFMPEG_SIGNATURE_NAME,
    )
    _copy_regular(
        ffmpeg_release_key,
        source_root / "THIRD_PARTY_SOURCES" / FFMPEG_RELEASE_KEY_NAME,
    )
    _copy_regular(
        FFMPEG_DOCKERFILE,
        source_root / "THIRD_PARTY_SOURCES" / FFMPEG_DOCKERFILE.name,
    )
    _copy_regular(
        FFMPEG_BUILD_SCRIPT,
        source_root / "THIRD_PARTY_SOURCES" / FFMPEG_BUILD_SCRIPT.name,
    )
    for name in ("buildconf.txt", "pe-imports.txt", "toolchain-packages.txt"):
        _copy_regular(
            ffmpeg_build / name,
            source_root / "THIRD_PARTY_SOURCES" / "ffmpeg-build" / name,
        )
    for name, expected in LICENSE_SHA256.items():
        license_path = ROOT / "LICENSES" / name
        if sha256_file(license_path) != expected:
            raise RuntimeError(f"第三方许可证身份不匹配：{name}")
        _copy_regular(license_path, source_root / "windows-tools" / "LICENSES" / name)
    _copy_regular(
        ROOT / "launcher" / "THIRD_PARTY_NOTICES.txt", source_root / "THIRD_PARTY_NOTICES.txt"
    )
    license_root = source_root / "THIRD_PARTY_LICENSES"
    _copy_regular(ROOT / "launcher" / "RELINKING.md", license_root / "RELINKING.md")
    if collect_installed_licenses:
        collect_license_materials(
            license_root / "installed",
            pyside_license_files=pyside_license_files,
        )
    _copy_docker_context(source_root)
    files = _scan_source(source_root)
    build_id = _build_id(files)
    manifest = {
        "schema_version": 1,
        "product_version": "0.7.0",
        "build_id": build_id,
        "sources": {
            "bbdown": {
                "url": BBDOWN_URL,
                "sha256": BBDOWN_SHA256,
                "size": BBDOWN_SIZE,
            },
            "ffmpeg_source": {
                "url": FFMPEG_SOURCE_URL,
                "sha256": FFMPEG_SOURCE_SHA256,
                "size": FFMPEG_SOURCE_SIZE,
                "embedded_path": FFMPEG_SOURCE_MEMBER,
                "signature": {
                    "url": FFMPEG_SIGNATURE_URL,
                    "sha256": FFMPEG_SIGNATURE_SHA256,
                    "size": FFMPEG_SIGNATURE_SIZE,
                },
                "release_key": {
                    "url": FFMPEG_RELEASE_KEY_URL,
                    "sha256": FFMPEG_RELEASE_KEY_SHA256,
                    "size": FFMPEG_RELEASE_KEY_SIZE,
                },
            },
            **(
                {
                    "pyside_license_texts": {
                        name: {
                            **identity,
                            "embedded_path": (
                                "THIRD_PARTY_LICENSES/installed/python-packages/"
                                f"pyside6/qtpyside-v{PYSIDE_SOURCE_VERSION}/LICENSES/{name}"
                            ),
                        }
                        for name, identity in sorted(PYSIDE_LICENSE_TEXTS.items())
                    }
                }
                if pyside_license_files is not None
                else {}
            ),
        },
        "files": files,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def assemble_bundle(
    *,
    target: Path,
    bbdown_archive: Path,
    ffmpeg_build: Path,
    ffmpeg_source: Path,
    ffmpeg_signature: Path,
    ffmpeg_release_key: Path,
    expected_bbdown_sha256: str = BBDOWN_SHA256,
    expected_ffmpeg_source_sha256: str = FFMPEG_SOURCE_SHA256,
    expected_ffmpeg_source_size: int = FFMPEG_SOURCE_SIZE,
    expected_ffmpeg_signature_sha256: str = FFMPEG_SIGNATURE_SHA256,
    expected_ffmpeg_signature_size: int = FFMPEG_SIGNATURE_SIZE,
    expected_ffmpeg_release_key_sha256: str = FFMPEG_RELEASE_KEY_SHA256,
    expected_ffmpeg_release_key_size: int = FFMPEG_RELEASE_KEY_SIZE,
    collect_installed_licenses: bool = False,
    pyside_license_files: dict[str, Path] | None = None,
) -> Path:
    target = Path(target)
    bbdown_archive = Path(bbdown_archive)
    ffmpeg_build = Path(ffmpeg_build)
    ffmpeg_source = Path(ffmpeg_source)
    ffmpeg_signature = Path(ffmpeg_signature)
    ffmpeg_release_key = Path(ffmpeg_release_key)
    pyside_license_files = (
        None
        if pyside_license_files is None
        else {name: Path(path) for name, path in pyside_license_files.items()}
    )
    _assert_no_reparse_ancestors(target.parent, "资源 staging 路径")
    _assert_no_reparse_ancestors(bbdown_archive, "BBDown 固定资源路径")
    _assert_no_reparse_ancestors(ffmpeg_build, "FFmpeg 固定构建路径")
    _assert_no_reparse_ancestors(ffmpeg_source, "FFmpeg 固定源码路径")
    _assert_no_reparse_ancestors(ffmpeg_signature, "FFmpeg 固定签名路径")
    _assert_no_reparse_ancestors(ffmpeg_release_key, "FFmpeg 固定发布公钥路径")
    if collect_installed_licenses and pyside_license_files is None:
        raise RuntimeError("收集 PySide6 开源许可时必须提供固定官方许可证文件")
    if pyside_license_files is not None:
        if set(pyside_license_files) != set(PYSIDE_LICENSE_TEXTS):
            raise RuntimeError("PySide6 固定许可证文件集合无效")
        for name, path in pyside_license_files.items():
            _assert_no_reparse_ancestors(path, f"PySide6 固定许可证路径（{name}）")
    if (
        not bbdown_archive.is_file()
        or bbdown_archive.is_symlink()
        or _is_reparse_point(bbdown_archive)
        or not ffmpeg_source.is_file()
        or ffmpeg_source.is_symlink()
        or _is_reparse_point(ffmpeg_source)
        or not ffmpeg_signature.is_file()
        or ffmpeg_signature.is_symlink()
        or _is_reparse_point(ffmpeg_signature)
        or not ffmpeg_release_key.is_file()
        or ffmpeg_release_key.is_symlink()
        or _is_reparse_point(ffmpeg_release_key)
    ):
        raise RuntimeError("BBDown 固定资源和 FFmpeg 官方源码必须是普通文件")
    validate_ffmpeg_output(ffmpeg_build)
    if sha256_file(bbdown_archive) != expected_bbdown_sha256:
        raise RuntimeError("BBDown 固定资源 SHA-256 不匹配")
    if (
        ffmpeg_source.stat().st_size != expected_ffmpeg_source_size
        or sha256_file(ffmpeg_source) != expected_ffmpeg_source_sha256
    ):
        raise RuntimeError("FFmpeg 官方源码 SHA-256 不匹配")
    if (
        ffmpeg_signature.stat().st_size != expected_ffmpeg_signature_size
        or sha256_file(ffmpeg_signature) != expected_ffmpeg_signature_sha256
    ):
        raise RuntimeError("FFmpeg 官方源码签名身份不匹配")
    if (
        ffmpeg_release_key.stat().st_size != expected_ffmpeg_release_key_size
        or sha256_file(ffmpeg_release_key) != expected_ffmpeg_release_key_sha256
    ):
        raise RuntimeError("FFmpeg 官方发布公钥身份不匹配")

    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(target, "资源 staging 路径")
    target_had_old = _path_exists(target)
    if target_had_old:
        _validate_replaceable_bundle(target)
    token = uuid.uuid4().hex
    temporary = target.parent / f".{target.name}.{token}.tmp"
    backup = target.parent / f".{target.name}.{token}.bak"
    if _path_exists(temporary) or _path_exists(backup):
        raise RuntimeError("随机资源 staging 事务路径已存在")

    replaced_existing = False
    published = False
    try:
        _populate_bundle(
            target=temporary,
            bbdown_archive=bbdown_archive,
            ffmpeg_build=ffmpeg_build,
            ffmpeg_source=ffmpeg_source,
            ffmpeg_signature=ffmpeg_signature,
            ffmpeg_release_key=ffmpeg_release_key,
            collect_installed_licenses=collect_installed_licenses,
            pyside_license_files=pyside_license_files,
        )
        _validate_replaceable_bundle(temporary)
        if target_had_old:
            os.replace(target, backup)
            replaced_existing = True
        os.replace(temporary, target)
        published = True
        _validate_replaceable_bundle(target)
    except BaseException as exc:
        rollback_error: Exception | None = None
        try:
            if published and _path_exists(target):
                os.replace(target, temporary)
            if replaced_existing and _path_exists(backup):
                os.replace(backup, target)
        except OSError as rollback_exc:
            rollback_error = rollback_exc
        if rollback_error is not None:
            raise RuntimeError(
                f"资源 staging 发布失败，且旧目录回滚失败：{rollback_error}"
            ) from exc
        raise
    else:
        _remove_generated_directory(backup, "资源 staging 旧备份")
    finally:
        _remove_generated_directory(temporary, "资源 staging 临时目录")
    return target


def prepare(target: Path = DEFAULT_TARGET, cache: Path = DEFAULT_CACHE) -> Path:
    target = Path(target)
    cache = Path(cache)
    _assert_build_target(target)
    _assert_build_target(cache)
    target = target.resolve(strict=False)
    cache = cache.resolve(strict=False)
    bbdown = download(BBDOWN_URL, BBDOWN_SHA256, BBDOWN_SIZE, cache / BBDOWN_NAME)
    ffmpeg_source = download(
        FFMPEG_SOURCE_URL,
        FFMPEG_SOURCE_SHA256,
        FFMPEG_SOURCE_SIZE,
        cache / FFMPEG_SOURCE_NAME,
    )
    ffmpeg_signature = download(
        FFMPEG_SIGNATURE_URL,
        FFMPEG_SIGNATURE_SHA256,
        FFMPEG_SIGNATURE_SIZE,
        cache / FFMPEG_SIGNATURE_NAME,
    )
    ffmpeg_release_key = download(
        FFMPEG_RELEASE_KEY_URL,
        FFMPEG_RELEASE_KEY_SHA256,
        FFMPEG_RELEASE_KEY_SIZE,
        cache / FFMPEG_RELEASE_KEY_NAME,
    )
    pyside_license_files = {
        name: download(
            str(identity["url"]),
            str(identity["sha256"]),
            int(identity["size"]),
            cache / f"qtpyside-{PYSIDE_SOURCE_VERSION}-{name}",
        )
        for name, identity in PYSIDE_LICENSE_TEXTS.items()
    }
    ffmpeg_build = build_ffmpeg_windows(
        output=DEFAULT_FFMPEG_OUTPUT,
        source_archive=ffmpeg_source,
        source_signature=ffmpeg_signature,
        release_key=ffmpeg_release_key,
    )
    return assemble_bundle(
        target=target,
        bbdown_archive=bbdown,
        ffmpeg_build=ffmpeg_build,
        ffmpeg_source=ffmpeg_source,
        ffmpeg_signature=ffmpeg_signature,
        ffmpeg_release_key=ffmpeg_release_key,
        collect_installed_licenses=True,
        pyside_license_files=pyside_license_files,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    arguments = parser.parse_args(argv)
    print(prepare(arguments.target, arguments.cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
