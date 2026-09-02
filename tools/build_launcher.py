"""在 Windows amd64 Python 3.11 中构建并自检单文件启动器。"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.constants import DATABASE_SCHEMA_VERSION
from tools.build_ffmpeg_windows import (
    BUILDER_BASE_IMAGE,
    DEBIAN_SNAPSHOT,
    FFMPEG_RELEASE_KEY_FINGERPRINT,
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
    FORBIDDEN_CONFIGURATION,
    REQUIRED_CONFIGURATION,
)
from tools.prepare_launcher_resources import (
    DEFAULT_CACHE,
    DEFAULT_TARGET,
    FFMPEG_SOURCE_MEMBER,
    FFMPEG_SOURCE_EVIDENCE_MEMBER,
    prepare,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK = ROOT / "build" / "bili-launcher-pyinstaller"
EXPECTED_EXE = "bili-workspace-launcher-0.7.0.exe"
MAX_EXE_BYTES = 100 * 1024 * 1024
MAX_FFMPEG_EVIDENCE_BYTES = 64 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_ERROR_MORE_DATA = 234
_RM_SESSION_KEY_CHARACTERS = 32
_RUNTIME_SMOKE_REPORT_NAME = "runtime-smoke.json"
_SELF_CHECK_REPORT_NAME = "self-check.json"
_MAX_RUNTIME_SMOKE_REPORT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    commit: str
    dirty: bool


def _require_builder() -> None:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError(f"启动器必须使用 Python 3.11 构建，当前为 {sys.version.split()[0]}")
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Windows EXE 必须在 Windows amd64 主机上构建")
    if struct.calcsize("P") != 8:
        raise RuntimeError("启动器构建 Python 必须是 64 位")


def _pyinstaller_environment(resource_bundle: Path) -> dict[str, str]:
    """Return a deterministic Windows DLL search environment for freezing."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "QT_"))
        and key.upper() not in {"QML_IMPORT_PATH", "QML2_IMPORT_PATH"}
    }
    environment_by_upper_name = {key.upper(): value for key, value in environment.items()}
    system_root_raw = environment_by_upper_name.get(
        "SYSTEMROOT"
    ) or environment_by_upper_name.get("WINDIR")
    if not system_root_raw:
        raise RuntimeError("无法确定 Windows 系统目录")
    system_root = Path(system_root_raw).resolve(strict=False)
    search_directories = (
        Path(sys.executable).resolve(strict=False).parent,
        Path(sys.base_prefix).resolve(strict=False),
        system_root / "System32",
        system_root,
    )
    unique_directories: list[Path] = []
    seen: set[str] = set()
    for directory in search_directories:
        identity = os.path.normcase(str(directory))
        if identity not in seen:
            seen.add(identity)
            unique_directories.append(directory)
    environment["PATH"] = os.pathsep.join(str(path) for path in unique_directories)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["BILI_REPOSITORY_ROOT"] = str(ROOT)
    environment["BILI_LAUNCHER_RESOURCE_BUNDLE"] = str(resource_bundle)
    return environment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_identity() -> SourceIdentity:
    """Return the committed base and whether this candidate includes local edits."""

    if not (ROOT / ".git").exists():
        raise RuntimeError("启动器只能在可审计的 Git 工作树中构建")
    try:
        commit_result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        status_result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        commit = commit_result.stdout.decode("ascii").strip().lower()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise RuntimeError("无法取得启动器源码 Git 身份") from exc
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise RuntimeError("启动器源码 HEAD 不是完整的 40 位 Git commit")
    return SourceIdentity(commit=commit, dirty=bool(status_result.stdout))


def _windows_file_use_count(path: Path) -> int:
    """Return the Restart Manager process count for a Windows file resource."""
    if os.name != "nt":
        return 0

    from ctypes import wintypes

    manager = ctypes.WinDLL("Rstrtmgr")
    manager.RmStartSession.argtypes = [
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        wintypes.LPWSTR,
    ]
    manager.RmStartSession.restype = wintypes.DWORD
    manager.RmRegisterResources.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        ctypes.POINTER(wintypes.LPCWSTR),
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.POINTER(wintypes.LPCWSTR),
    ]
    manager.RmRegisterResources.restype = wintypes.DWORD
    manager.RmGetList.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    manager.RmGetList.restype = wintypes.DWORD
    manager.RmEndSession.argtypes = [wintypes.DWORD]
    manager.RmEndSession.restype = wintypes.DWORD

    session = wintypes.DWORD()
    session_key = ctypes.create_unicode_buffer(_RM_SESSION_KEY_CHARACTERS + 1)
    result = manager.RmStartSession(ctypes.byref(session), 0, session_key)
    if result != 0:
        raise RuntimeError(f"无法启动 Windows 文件占用检查：错误码 {result}")
    try:
        resources = (wintypes.LPCWSTR * 1)(str(path.resolve()))
        result = manager.RmRegisterResources(session, 1, resources, 0, None, 0, None)
        if result != 0:
            raise RuntimeError(f"无法登记 Windows 文件占用检查：错误码 {result}")
        needed = wintypes.UINT()
        available = wintypes.UINT()
        reboot_reasons = wintypes.DWORD()
        result = manager.RmGetList(
            session,
            ctypes.byref(needed),
            ctypes.byref(available),
            None,
            ctypes.byref(reboot_reasons),
        )
        if result not in {0, _ERROR_MORE_DATA}:
            raise RuntimeError(f"无法读取 Windows 文件占用状态：错误码 {result}")
        return int(needed.value)
    finally:
        manager.RmEndSession(session)


def _inside(candidate: Path, parent: Path) -> bool:
    child = candidate.resolve(strict=False)
    root = parent.resolve(strict=False)
    return child == root or root in child.parents


def _is_reparse_point(path: Path) -> bool:
    try:
        status = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(status, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse_point(path)


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and not _is_reparse_point(path)


def _reject_reparse(path: Path, label: str) -> None:
    if path.is_symlink() or _is_reparse_point(path):
        raise RuntimeError(f"{label}不能是符号链接或重解析点：{path}")


def _reject_reparse_ancestors(path: Path, label: str) -> None:
    absolute = Path(path).absolute()
    for candidate in (absolute, *absolute.parents):
        if _path_exists(candidate) and (
            candidate.is_symlink() or _is_reparse_point(candidate)
        ):
            raise RuntimeError(f"{label}不能经过符号链接或重解析点：{candidate}")


def _validate_owned_output(path: Path) -> None:
    candidate = path.resolve(strict=False)
    final_dist = (ROOT / "dist").resolve(strict=False)
    build_root = (ROOT / "build").resolve(strict=False)
    if candidate != final_dist and build_root not in candidate.parents:
        raise RuntimeError(f"EXE 输出目录必须位于项目 build 或 dist 内：{path}")


def _validate_build_subdirectory(path: Path, label: str) -> None:
    build_root = (ROOT / "build").resolve(strict=False)
    candidate = path.resolve(strict=False)
    if candidate == build_root or build_root not in candidate.parents:
        raise RuntimeError(f"{label} 必须是 build 下的具体子目录：{path}")


def _validate_record_path(path: Path) -> None:
    candidate = path.resolve(strict=False)
    canonical = (ROOT / "launcher" / "current-build.json").resolve(strict=False)
    if candidate != canonical and not _inside(candidate, ROOT / "build"):
        raise RuntimeError(f"构建记录只能写入 current-build.json 或 build：{path}")


def _resolve_artifact_contract(
    *,
    mode: str,
    dist_dir: Path,
    record_path: Path | None,
    run_exe_self_check: bool,
    run_exe_runtime_smoke: bool,
) -> Path:
    final_dist = (ROOT / "dist").resolve(strict=False)
    canonical_record = (ROOT / "launcher" / "current-build.json").resolve(strict=False)
    if not run_exe_self_check or not run_exe_runtime_smoke:
        raise RuntimeError("候选与正式快照都必须启用 EXE 自检和全新数据根运行时冒烟")
    if mode == "snapshot":
        if dist_dir != final_dist:
            raise RuntimeError("正式快照只能写入仓库 dist")
        if record_path is not None and record_path != canonical_record:
            raise RuntimeError("正式快照必须更新 launcher/current-build.json")
        return canonical_record
    if mode == "candidate":
        if dist_dir == final_dist:
            raise RuntimeError("候选构建不得写入正式 dist")
        if record_path is None:
            raise RuntimeError("候选构建必须在 build 内写入候选记录")
        if record_path == canonical_record:
            raise RuntimeError("候选构建不得更新 launcher/current-build.json")
        return record_path
    raise RuntimeError(f"不支持的启动器构建模式：{mode}")


def _validate_pe_amd64(path: Path) -> None:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("候选不是 PE 可执行文件")
        stream.seek(0x3C)
        offset_bytes = stream.read(4)
        if len(offset_bytes) != 4:
            raise RuntimeError("PE 头不完整")
        stream.seek(struct.unpack("<I", offset_bytes)[0])
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError("PE 签名无效")
        machine_bytes = stream.read(2)
        if len(machine_bytes) != 2:
            raise RuntimeError("PE Machine 字段不完整")
        machine = struct.unpack("<H", machine_bytes)[0]
    if machine != 0x8664:
        raise RuntimeError(f"候选 PE Machine 不是 AMD64：0x{machine:04x}")


def _parse_ffmpeg_version_output(output: str) -> dict[str, str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    version_lines = [line for line in lines if line.lower().startswith("ffmpeg version ")]
    configuration_lines = [line for line in lines if line.lower().startswith("configuration:")]
    if len(version_lines) != 1 or not version_lines[0].lower().startswith(
        "ffmpeg version 7.1.1-bili-workspace"
    ):
        raise RuntimeError("FFmpeg 冒烟输出不是固定的 7.1.1-bili-workspace 版本")
    if len(configuration_lines) != 1:
        raise RuntimeError("FFmpeg 冒烟输出缺少唯一构建配置")
    configuration = configuration_lines[0].partition(":")[2].strip()
    try:
        options = set(shlex.split(configuration, posix=True))
    except ValueError as exc:
        raise RuntimeError("FFmpeg 冒烟输出中的构建配置无法解析") from exc
    missing = REQUIRED_CONFIGURATION - options
    forbidden = FORBIDDEN_CONFIGURATION & options
    external = sorted(option for option in options if option.startswith("--enable-lib"))
    if missing:
        raise RuntimeError(f"FFmpeg 固定二进制缺少构建选项：{sorted(missing)}")
    if forbidden:
        raise RuntimeError(f"FFmpeg 固定二进制启用了禁止的许可选项：{sorted(forbidden)}")
    if external:
        raise RuntimeError(f"FFmpeg 固定二进制启用了未随附的外部库：{external}")
    return {
        "version_line": version_lines[0],
        "configuration": configuration,
        "license_mode": "LGPL-2.1-or-later",
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
    }


def _record_tool_verification(resource_dir: Path, verification: dict[str, object]) -> None:
    manifest_path = resource_dir / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("无法记录内置工具验证结果") from exc
    if (
        not isinstance(raw, dict)
        or isinstance(raw.get("schema_version"), bool)
        or raw.get("schema_version") != 1
    ):
        raise RuntimeError("内置资源清单结构无效")
    raw["tool_verification"] = verification
    temporary = manifest_path.with_suffix(".json.new")
    _write_new_record(temporary, raw)
    os.replace(temporary, manifest_path)


def _verify_ffmpeg_source_evidence(
    resource_dir: Path,
    verification: dict[str, object],
) -> dict[str, object]:
    relative = Path(*FFMPEG_SOURCE_EVIDENCE_MEMBER.split("/"))
    evidence_path = resource_dir / "source" / relative
    ffmpeg_path = resource_dir / "source" / "windows-tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if not _regular_file(evidence_path):
        raise RuntimeError("缺少 FFmpeg 官方源码自建证据")
    if evidence_path.stat().st_size <= 0 or evidence_path.stat().st_size > MAX_FFMPEG_EVIDENCE_BYTES:
        raise RuntimeError("FFmpeg 对应源码证据大小无效")
    try:
        raw = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("FFmpeg 对应源码证据不是有效 UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "status",
        "target",
        "license_mode",
        "binary",
        "source",
        "recipe",
        "artifacts",
    }:
        raise RuntimeError("FFmpeg 对应源码证据顶层字段无效")
    if raw.get("schema_version") != 1 or isinstance(raw.get("schema_version"), bool):
        raise RuntimeError("FFmpeg 对应源码证据 schema 无效")
    if (
        raw.get("status") != "verified"
        or raw.get("target") != "windows-amd64"
        or raw.get("license_mode") != "LGPL-2.1-or-later"
    ):
        raise RuntimeError("FFmpeg 对应源码证据尚未标记为 verified")

    binary = raw.get("binary")
    expected_binary = {
        "path": "ffmpeg.exe",
        "sha256": _sha256(ffmpeg_path),
        "size": ffmpeg_path.stat().st_size,
    }
    if not isinstance(binary, dict) or binary != expected_binary:
        raise RuntimeError("FFmpeg 对应源码证据与实际二进制身份不一致")

    ffmpeg_verification = verification.get("ffmpeg")
    if not isinstance(ffmpeg_verification, dict):
        raise RuntimeError("FFmpeg 冒烟验证结果缺失")
    raw_recipe = raw.get("recipe")
    evidence_configuration = (
        raw_recipe.get("configuration") if isinstance(raw_recipe, dict) else None
    )
    if (
        ffmpeg_verification.get("configuration") != evidence_configuration
        or ffmpeg_verification.get("license_mode") != raw.get("license_mode")
        or ffmpeg_verification.get("sha256") != binary.get("sha256")
    ):
        raise RuntimeError("FFmpeg 对应源码证据与实际版本、配置或许可模式不一致")

    source = raw.get("source")
    expected_source = {
        "name": FFMPEG_SOURCE_NAME,
        "url": FFMPEG_SOURCE_URL,
        "sha256": FFMPEG_SOURCE_SHA256,
        "size": FFMPEG_SOURCE_SIZE,
        "embedded_path": FFMPEG_SOURCE_MEMBER,
        "signature": {
            "name": FFMPEG_SIGNATURE_NAME,
            "url": FFMPEG_SIGNATURE_URL,
            "sha256": FFMPEG_SIGNATURE_SHA256,
            "size": FFMPEG_SIGNATURE_SIZE,
        },
        "release_key": {
            "name": FFMPEG_RELEASE_KEY_NAME,
            "url": FFMPEG_RELEASE_KEY_URL,
            "sha256": FFMPEG_RELEASE_KEY_SHA256,
            "size": FFMPEG_RELEASE_KEY_SIZE,
            "fingerprint": FFMPEG_RELEASE_KEY_FINGERPRINT,
        },
    }
    if source != expected_source:
        raise RuntimeError("FFmpeg 对应源码、签名或发布密钥身份无效")

    source_root = resource_dir / "source"
    required_identity_files = {
        FFMPEG_SOURCE_MEMBER: (FFMPEG_SOURCE_SIZE, FFMPEG_SOURCE_SHA256),
        f"THIRD_PARTY_SOURCES/{FFMPEG_SIGNATURE_NAME}": (
            FFMPEG_SIGNATURE_SIZE,
            FFMPEG_SIGNATURE_SHA256,
        ),
        f"THIRD_PARTY_SOURCES/{FFMPEG_RELEASE_KEY_NAME}": (
            FFMPEG_RELEASE_KEY_SIZE,
            FFMPEG_RELEASE_KEY_SHA256,
        ),
    }
    for relative_name, (expected_size, expected_digest) in required_identity_files.items():
        path = source_root.joinpath(*relative_name.split("/"))
        if (
            not _regular_file(path)
            or path.stat().st_size != expected_size
            or _sha256(path) != expected_digest
        ):
            raise RuntimeError(f"FFmpeg 离线来源文件身份不一致：{relative_name}")

    recipe = raw.get("recipe")
    if not isinstance(recipe, dict) or set(recipe) != {
        "base_image",
        "debian_snapshot",
        "configuration",
        "files",
        "toolchain_packages",
        "pe_imports",
    }:
        raise RuntimeError("FFmpeg 构建配方证据无效")
    if (
        recipe.get("base_image") != BUILDER_BASE_IMAGE
        or recipe.get("debian_snapshot") != DEBIAN_SNAPSHOT
    ):
        raise RuntimeError("FFmpeg 构建基础镜像或 Debian 快照身份无效")
    recipe_files = recipe.get("files")
    if not isinstance(recipe_files, dict) or set(recipe_files) != {
        "ffmpeg-builder.Dockerfile",
        "build-ffmpeg-windows.sh",
    }:
        raise RuntimeError("FFmpeg 构建配方文件清单无效")
    for name, entry in recipe_files.items():
        path = source_root / "THIRD_PARTY_SOURCES" / name
        expected = {"sha256": _sha256(path), "size": path.stat().st_size} if _regular_file(path) else None
        if entry != expected:
            raise RuntimeError(f"FFmpeg 构建配方文件身份不一致：{name}")

    artifacts = raw.get("artifacts")
    artifact_paths = {
        "ffmpeg.exe": ffmpeg_path,
        "LICENSE.md": source_root / "windows-tools" / "LICENSES" / "FFmpeg.LICENSE.md",
        "COPYING.LGPLv2.1": source_root
        / "windows-tools"
        / "LICENSES"
        / "FFmpeg.COPYING.LGPLv2.1.txt",
        "buildconf.txt": source_root
        / "THIRD_PARTY_SOURCES"
        / "ffmpeg-build"
        / "buildconf.txt",
        "pe-imports.txt": source_root
        / "THIRD_PARTY_SOURCES"
        / "ffmpeg-build"
        / "pe-imports.txt",
        "toolchain-packages.txt": source_root
        / "THIRD_PARTY_SOURCES"
        / "ffmpeg-build"
        / "toolchain-packages.txt",
    }
    expected_artifacts = {
        name: {"sha256": _sha256(path), "size": path.stat().st_size}
        for name, path in artifact_paths.items()
        if _regular_file(path)
    }
    if set(expected_artifacts) != set(artifact_paths) or artifacts != expected_artifacts:
        raise RuntimeError("FFmpeg 构建产物证据与内置文件不一致")
    try:
        embedded_configuration = artifact_paths["buildconf.txt"].read_text(
            encoding="utf-8"
        ).strip()
        embedded_toolchain = [
            line.strip()
            for line in artifact_paths["toolchain-packages.txt"]
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        embedded_imports = [
            line.strip()
            for line in artifact_paths["pe-imports.txt"]
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError("FFmpeg 内置构建清单不是有效 UTF-8 文本") from exc
    if (
        embedded_configuration != recipe.get("configuration")
        or embedded_toolchain != recipe.get("toolchain_packages")
        or embedded_imports != recipe.get("pe_imports")
    ):
        raise RuntimeError("FFmpeg 构建配置、工具链或 PE 导入清单与证据不一致")

    manifest_path = resource_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("无法核对 FFmpeg 对应源码证据的资源清单身份") from exc
    relative_key = FFMPEG_SOURCE_EVIDENCE_MEMBER
    manifest_entry = manifest.get("files", {}).get(relative_key) if isinstance(manifest, dict) else None
    expected_manifest_entry = {
        "sha256": _sha256(evidence_path),
        "size": evidence_path.stat().st_size,
    }
    if manifest_entry != expected_manifest_entry:
        raise RuntimeError("FFmpeg 对应源码证据未被当前资源清单完整覆盖")
    return {
        "schema_version": 1,
        "path": relative_key,
        "sha256": expected_manifest_entry["sha256"],
        "source_count": 1,
    }


def _smoke_tools(resource_dir: Path) -> dict[str, object]:
    tools = resource_dir / "source" / "windows-tools"
    subprocess.run(
        [str(tools / "BBDown.exe"), "--help"],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    ffmpeg_path = tools / "ffmpeg" / "bin" / "ffmpeg.exe"
    result = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-version"],
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    ffmpeg_output = result.stdout + result.stderr
    ffmpeg = _parse_ffmpeg_version_output(ffmpeg_output)
    encoder_help = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-h", "encoder=h264_mf"],
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    encoder_help_output = encoder_help.stdout + encoder_help.stderr
    if "Encoder h264_mf" not in encoder_help_output:
        raise RuntimeError("FFmpeg 未提供启动器兼容转码所需的 h264_mf 编码器")
    with tempfile.TemporaryDirectory(
        prefix=".bili-launcher-tool-smoke-", dir=resource_dir.parent
    ) as temporary:
        smoke_output = Path(temporary) / "h264-mf-aac.mp4"
        subprocess.run(
            [
                str(ffmpeg_path),
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=10",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:sample_rate=48000",
                "-t",
                "1",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
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
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(smoke_output),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=120,
        )
        if not _regular_file(smoke_output) or smoke_output.stat().st_size <= 0:
            raise RuntimeError("FFmpeg h264_mf/AAC 兼容转码冒烟未生成有效 MP4")
        compatible_transcode = {
            "video_encoder": "h264_mf",
            "audio_encoder": "aac",
            "pixel_format": "nv12",
            "software_only": True,
            "container": "mp4",
            "output_size": smoke_output.stat().st_size,
            "output_sha256": _sha256(smoke_output),
            "encoder_help_sha256": hashlib.sha256(
                encoder_help_output.encode("utf-8")
            ).hexdigest(),
        }
    verification: dict[str, object] = {
        "schema_version": 1,
        "bbdown": {
            "version": "1.6.3",
            "sha256": _sha256(tools / "BBDown.exe"),
        },
        "ffmpeg": {
            **ffmpeg,
            "sha256": _sha256(ffmpeg_path),
            "compatible_transcode": compatible_transcode,
        },
    }
    _record_tool_verification(resource_dir, verification)
    return verification


def _build_record(
    executable: Path,
    resource_dir: Path,
    published_executable: Path,
    *,
    artifact_kind: str,
    source_identity: SourceIdentity,
    exe_self_check_ran: bool,
    exe_runtime_smoke_ran: bool,
) -> dict[str, object]:
    manifest_bytes = (resource_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    import PyInstaller
    import PySide6

    try:
        executable_name = published_executable.resolve(strict=False).relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise RuntimeError("构建记录中的 EXE 必须位于仓库 build 或 dist") from exc
    return {
        "schema_version": 2,
        "artifact_kind": artifact_kind,
        "version": "0.7.0",
        "build_id": manifest["build_id"],
        "source_commit": source_identity.commit,
        "source_dirty": source_identity.dirty,
        "platform": "windows/amd64",
        "executable": executable_name,
        "sha256": _sha256(executable),
        "size_bytes": executable.stat().st_size,
        "resource_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "python_version": platform.python_version(),
        "pyinstaller_version": PyInstaller.__version__,
        "pyside6_version": PySide6.__version__,
        "exe_self_check_ran": exe_self_check_ran,
        "exe_runtime_smoke_ran": exe_runtime_smoke_ran,
        "built_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _run_exe_self_check(executable: Path) -> None:
    report_path = executable.parent / _SELF_CHECK_REPORT_NAME
    result = subprocess.run(
        [
            str(executable),
            "--self-check",
            "--self-check-report",
            str(report_path),
        ],
        cwd=executable.parent,
        check=False,
        timeout=180,
    )
    report = _read_check_report(report_path, "EXE 自检")
    if result.returncode != 0 or report != {"schema_version": 1, "status": "passed"}:
        error = str(report.get("error", "")).strip()
        detail = f"：{error}" if error else ""
        raise RuntimeError(f"候选 EXE 自检失败（退出码 {result.returncode}）{detail}")


def _read_check_report(path: Path, label: str) -> dict[str, object]:
    try:
        if path.stat().st_size > _MAX_RUNTIME_SMOKE_REPORT_BYTES:
            raise RuntimeError(f"{label}报告超过大小上限")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label}没有生成有效报告") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"{label}报告必须是 JSON object")
    return raw


def _read_runtime_smoke_report(path: Path) -> dict[str, object]:
    return _read_check_report(path, "候选运行时冒烟")


def _run_exe_runtime_smoke(executable: Path, expected_build_id: str) -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("BILI_", "PYTHON"))
    }
    environment["PYTHONUTF8"] = "1"
    with tempfile.TemporaryDirectory(prefix="bili-launcher-runtime-smoke-") as temporary:
        temporary_root = Path(temporary).resolve(strict=True)
        if _inside(temporary_root, ROOT):
            raise RuntimeError("运行时冒烟临时根必须位于 Git 工作树外")
        data_root = temporary_root / "data"
        report_path = temporary_root / _RUNTIME_SMOKE_REPORT_NAME
        result = subprocess.run(
            [
                str(executable),
                "--runtime-smoke",
                "--data-root",
                str(data_root),
                "--expected-build-id",
                expected_build_id,
                "--runtime-smoke-report",
                str(report_path),
            ],
            cwd=executable.parent,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        report = _read_runtime_smoke_report(report_path)
        expected = {
            "schema_version": 1,
            "status": "passed",
            "build_id": expected_build_id,
            "application_schema_version": DATABASE_SCHEMA_VERSION,
            "mode": "local",
            "root_page": "passed",
        }
        invalid = (
            result.returncode != 0
            or set(report) != {*expected, "port"}
            or any(report.get(key) != value for key, value in expected.items())
            or isinstance(report.get("port"), bool)
            or not isinstance(report.get("port"), int)
            or not 1 <= report["port"] <= 65535
        )
        if invalid:
            error = str(report.get("error", "")).strip()
            detail = f"：{error}" if error else ""
            raise RuntimeError(
                f"候选 EXE 全新数据根运行时冒烟失败（退出码 {result.returncode}）{detail}"
            )


def _write_new_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(
            (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )
        stream.flush()
        os.fsync(stream.fileno())


def _publish_candidate(
    *,
    staging_executable: Path,
    destination: Path,
    record_path: Path | None,
    record: dict[str, object] | None,
) -> None:
    _reject_reparse_ancestors(staging_executable, "待发布 EXE")
    _reject_reparse_ancestors(destination, "规范 EXE 目标")
    if record_path is not None:
        _reject_reparse_ancestors(record_path, "构建记录目标")
    resolved_paths = {
        staging_executable.resolve(strict=False),
        destination.resolve(strict=False),
        *(set() if record_path is None else {record_path.resolve(strict=False)}),
    }
    if len(resolved_paths) != (2 if record_path is None else 3):
        raise RuntimeError("候选、规范 EXE 与构建记录路径不能重叠")
    if not _regular_file(staging_executable):
        raise RuntimeError(f"待发布 EXE 不是普通文件：{staging_executable}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    executable_backup = destination.parent / f".{destination.name}.{token}.bak"
    record_backup = (
        record_path.parent / f".{record_path.name}.{token}.bak" if record_path is not None else None
    )
    record_new = (
        record_path.parent / f".{record_path.name}.{token}.new" if record_path is not None else None
    )
    if _path_exists(destination) and not _regular_file(destination):
        raise RuntimeError(f"规范 EXE 目标类型无效：{destination}")
    if record_path is not None and (
        _path_exists(record_path) and not _regular_file(record_path)
    ):
        raise RuntimeError(f"构建记录目标类型无效：{record_path}")
    if destination.is_file():
        process_count = _windows_file_use_count(destination)
        if process_count:
            raise RuntimeError(
                f"规范 EXE 正被 {process_count} 个进程使用；请先退出该 EXE，发布未修改任何目标"
            )
    for transaction_path in (
        executable_backup,
        record_backup,
        record_new,
    ):
        if transaction_path is not None and _path_exists(transaction_path):
            raise RuntimeError(f"候选发布事务路径已存在：{transaction_path}")
    if record_path is not None:
        if record is None or record_new is None:
            raise RuntimeError("构建记录事务缺少内容")
        _write_new_record(record_new, record)

    executable_had_old = destination.is_file()
    record_had_old = bool(record_path is not None and record_path.is_file())
    executable_published = False
    record_published = False
    try:
        if executable_had_old:
            os.replace(destination, executable_backup)
        if record_had_old and record_path is not None and record_backup is not None:
            os.replace(record_path, record_backup)
        os.replace(staging_executable, destination)
        executable_published = True
        if record_path is not None and record_new is not None:
            os.replace(record_new, record_path)
            record_published = True
        if not _regular_file(destination):
            raise RuntimeError("规范 EXE 发布后类型无效")
        if record_path is not None:
            if not _regular_file(record_path) or record is None:
                raise RuntimeError("构建记录发布后类型无效")
            try:
                published_record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("构建记录发布后不可读") from exc
            if published_record != record:
                raise RuntimeError("构建记录发布后内容不一致")
            expected_size = record.get("size_bytes")
            expected_digest = record.get("sha256")
            if (
                isinstance(expected_size, bool)
                or not isinstance(expected_size, int)
                or destination.stat().st_size != expected_size
                or not isinstance(expected_digest, str)
                or _sha256(destination) != expected_digest
            ):
                raise RuntimeError("规范 EXE 与构建记录身份不一致")
    except (OSError, RuntimeError):
        if record_published and record_path is not None:
            record_path.unlink(missing_ok=True)
        if record_had_old and record_path is not None and record_backup is not None:
            if record_backup.exists():
                os.replace(record_backup, record_path)
        if executable_published:
            os.replace(destination, staging_executable)
        if executable_had_old and executable_backup.exists():
            os.replace(executable_backup, destination)
        raise
    else:
        executable_backup.unlink(missing_ok=True)
        if record_backup is not None:
            record_backup.unlink(missing_ok=True)
    finally:
        if record_new is not None:
            record_new.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("candidate", "snapshot"), required=True)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--resource-dir", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--keep-build", action="store_true")
    parser.add_argument(
        "--run-exe-self-check",
        action="store_true",
        help="显式授权构建器启动刚生成的 EXE 执行 --self-check",
    )
    parser.add_argument(
        "--run-exe-runtime-smoke",
        action="store_true",
        help="显式授权候选 EXE 在全新仓库外临时数据根启动自有后端",
    )
    arguments = parser.parse_args(argv)
    _reject_reparse(arguments.dist_dir, "EXE 输出目录")
    _reject_reparse(arguments.work_dir, "PyInstaller 工作目录")
    _reject_reparse(arguments.resource_dir, "资源 staging")
    _reject_reparse(arguments.cache, "固定资源缓存")
    _reject_reparse_ancestors(arguments.dist_dir, "EXE 输出目录")
    _reject_reparse_ancestors(arguments.work_dir, "PyInstaller 工作目录")
    _reject_reparse_ancestors(arguments.resource_dir, "资源 staging")
    _reject_reparse_ancestors(arguments.cache, "固定资源缓存")
    dist_dir = arguments.dist_dir.resolve(strict=False)
    work_dir = arguments.work_dir.resolve(strict=False)
    resource_dir = arguments.resource_dir.resolve(strict=False)
    cache_dir = arguments.cache.resolve(strict=False)
    _validate_owned_output(dist_dir)
    _validate_build_subdirectory(work_dir, "PyInstaller 工作目录")
    _validate_build_subdirectory(resource_dir, "资源 staging")
    _validate_build_subdirectory(cache_dir, "固定资源缓存")
    owned_directories = {
        "EXE 输出目录": dist_dir,
        "PyInstaller 工作目录": work_dir,
        "资源 staging": resource_dir,
        "固定资源缓存": cache_dir,
    }
    directory_items = list(owned_directories.items())
    for index, (left_name, left) in enumerate(directory_items):
        for right_name, right in directory_items[index + 1 :]:
            if _inside(left, right) or _inside(right, left):
                raise RuntimeError(f"{left_name}与{right_name}不能重叠")

    record_path = arguments.record.resolve(strict=False) if arguments.record is not None else None
    record_path = _resolve_artifact_contract(
        mode=arguments.mode,
        dist_dir=dist_dir,
        record_path=record_path,
        run_exe_self_check=arguments.run_exe_self_check,
        run_exe_runtime_smoke=arguments.run_exe_runtime_smoke,
    )
    _validate_record_path(record_path)
    _reject_reparse(arguments.record or record_path, "构建记录")
    _reject_reparse_ancestors(arguments.record or record_path, "构建记录")
    for label, directory in (
        ("PyInstaller 工作目录", work_dir),
        ("资源 staging", resource_dir),
        ("固定资源缓存", cache_dir),
    ):
        if _inside(record_path, directory):
            raise RuntimeError(f"构建记录不能位于{label}内")

    if _path_exists(dist_dir) and (
        dist_dir.is_symlink() or _is_reparse_point(dist_dir) or not dist_dir.is_dir()
    ):
        raise RuntimeError(f"EXE 输出路径类型无效：{dist_dir}")
    unexpected_executables = (
        sorted(path for path in dist_dir.glob("*.exe") if path.name != EXPECTED_EXE)
        if dist_dir.is_dir()
        else []
    )
    if unexpected_executables:
        raise RuntimeError("EXE 输出目录包含其他可执行文件，拒绝覆盖")
    source_identity = _source_identity()
    if arguments.mode == "snapshot" and source_identity.dirty:
        raise RuntimeError("正式快照只能从干净、已提交的 Git HEAD 构建")
    _require_builder()
    bundle = prepare(resource_dir, cache_dir)
    verification = _smoke_tools(bundle)
    verification["ffmpeg_source_evidence"] = _verify_ffmpeg_source_evidence(
        bundle,
        verification,
    )
    _record_tool_verification(bundle, verification)
    try:
        bundle_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        bundle_build_id = bundle_manifest["build_id"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("无法读取候选资源 build_id") from exc
    if not isinstance(bundle_build_id, str):
        raise RuntimeError("候选资源 build_id 类型无效")
    job_dir = work_dir / f"job-{uuid.uuid4().hex}"
    staging_dist = job_dir / "dist"
    pyinstaller_work = job_dir / "pyinstaller"
    staging_dist.mkdir(parents=True)
    staging_executable = staging_dist / EXPECTED_EXE
    destination = dist_dir / EXPECTED_EXE
    environment = _pyinstaller_environment(bundle)
    try:
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--distpath",
                str(staging_dist),
                "--workpath",
                str(pyinstaller_work),
                str(ROOT / "launcher" / "bili-workspace-launcher.spec"),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        if not _regular_file(staging_executable) or staging_executable.stat().st_size <= 0:
            raise RuntimeError(f"PyInstaller 未生成规范 EXE：{staging_executable}")
        executables = sorted(path.resolve() for path in staging_dist.glob("*.exe") if path.is_file())
        if executables != [staging_executable.resolve()]:
            raise RuntimeError("EXE 输出目录必须且只能包含规范命名的一份候选")
        if staging_executable.stat().st_size >= MAX_EXE_BYTES:
            raise RuntimeError(
                f"候选为 {staging_executable.stat().st_size} 字节，达到常规 Git 单文件停止线"
            )
        _validate_pe_amd64(staging_executable)
        _run_exe_self_check(staging_executable)
        _run_exe_runtime_smoke(staging_executable, bundle_build_id)
        if arguments.mode == "snapshot":
            final_identity = _source_identity()
            if final_identity != source_identity or final_identity.dirty:
                raise RuntimeError("正式快照构建期间 Git HEAD 或工作树发生变化，拒绝晋升")
        record = _build_record(
            staging_executable,
            bundle,
            destination,
            artifact_kind=arguments.mode,
            source_identity=source_identity,
            exe_self_check_ran=True,
            exe_runtime_smoke_ran=True,
        )
        _publish_candidate(
            staging_executable=staging_executable,
            destination=destination,
            record_path=record_path,
            record=record,
        )
    except Exception:
        print(f"{arguments.mode} 构建失败；保留任务自有 staging 供诊断。", file=sys.stderr)
        raise
    if not arguments.keep_build:
        for directory in (job_dir, resource_dir):
            if directory.exists() and _inside(directory, ROOT / "build"):
                shutil.rmtree(directory)
        try:
            work_dir.rmdir()
        except OSError:
            pass
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
