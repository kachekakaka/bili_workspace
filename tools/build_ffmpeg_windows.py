"""用固定 Linux/amd64 容器从 FFmpeg 官方源码交叉构建 Windows amd64 工具。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "build" / "launcher-ffmpeg-windows-amd64"
DOCKERFILE = ROOT / "launcher" / "ffmpeg-builder.Dockerfile"
BUILD_SCRIPT = ROOT / "launcher" / "build-ffmpeg-windows.sh"

FFMPEG_VERSION = "7.1.1"
FFMPEG_SOURCE_NAME = f"ffmpeg-{FFMPEG_VERSION}.tar.xz"
FFMPEG_SOURCE_URL = f"https://ffmpeg.org/releases/{FFMPEG_SOURCE_NAME}"
FFMPEG_SOURCE_SHA256 = "733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1"
FFMPEG_SOURCE_SIZE = 11_019_500
FFMPEG_SIGNATURE_NAME = f"{FFMPEG_SOURCE_NAME}.asc"
FFMPEG_SIGNATURE_URL = f"{FFMPEG_SOURCE_URL}.asc"
FFMPEG_SIGNATURE_SHA256 = "a52e92620b266ea341191a01b42a191e01c15a9f56e99b173582181781f5bc75"
FFMPEG_SIGNATURE_SIZE = 520
FFMPEG_RELEASE_KEY_NAME = "ffmpeg-devel.asc"
FFMPEG_RELEASE_KEY_URL = "https://ffmpeg.org/ffmpeg-devel.asc"
FFMPEG_RELEASE_KEY_SHA256 = "397b3becedcd5a98769967ff1ff8501ddc89f8368b8f766e4701377d7dbaabe5"
FFMPEG_RELEASE_KEY_SIZE = 1_709
FFMPEG_RELEASE_KEY_FINGERPRINT = "FCF986EA15E6E293A5644F10B4322F04D67658D8"

BUILDER_BASE_IMAGE = (
    "debian@sha256:362e64223cc0da95422b3b13c045186fc0a81250e765d31c025fbddf257f6143"
)
DEBIAN_SNAPSHOT = "20260803T000000Z"
EVIDENCE_NAME = "build-evidence.json"
EXPECTED_OUTPUT_NAMES = {
    "COPYING.LGPLv2.1",
    "LICENSE.md",
    EVIDENCE_NAME,
    "buildconf.txt",
    "ffmpeg.exe",
    "pe-imports.txt",
    "toolchain-packages.txt",
}
REQUIRED_CONFIGURATION = {
    "--arch=x86_64",
    "--cross-prefix=x86_64-w64-mingw32-",
    "--disable-autodetect",
    "--disable-debug",
    "--disable-doc",
    "--disable-ffplay",
    "--disable-ffprobe",
    "--disable-network",
    "--disable-postproc",
    "--disable-pthreads",
    "--disable-shared",
    "--enable-static",
    "--enable-mediafoundation",
    "--enable-w32threads",
    "--extra-version=bili-workspace",
    "--host-cc=gcc",
    "--pkg-config=false",
    "--target-os=mingw32",
}
FORBIDDEN_CONFIGURATION = {"--enable-gpl", "--enable-nonfree", "--enable-version3"}
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        status = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(status, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and not _is_reparse_point(path)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse_point(path)


def _inside(path: Path, parent: Path) -> bool:
    candidate = path.resolve(strict=False)
    boundary = parent.resolve(strict=False)
    return candidate == boundary or boundary in candidate.parents


def _assert_build_subdirectory(path: Path) -> None:
    build_root = (ROOT / "build").resolve(strict=False)
    candidate = path.resolve(strict=False)
    if candidate == build_root or not _inside(candidate, build_root):
        raise RuntimeError(f"FFmpeg 构建输出必须是 build 下的具体子目录：{path}")
    for ancestor in (Path(path).absolute(), *Path(path).absolute().parents):
        if _path_exists(ancestor) and (
            ancestor.is_symlink() or _is_reparse_point(ancestor)
        ):
            raise RuntimeError(f"FFmpeg 构建路径不能经过符号链接或重解析点：{ancestor}")


def _validate_input(path: Path, *, size: int, sha256: str, label: str) -> None:
    if not _regular_file(path):
        raise RuntimeError(f"{label}必须是普通文件：{path}")
    if path.stat().st_size != size or sha256_file(path) != sha256:
        raise RuntimeError(f"{label}大小或 SHA-256 不匹配：{path}")


def _validate_recipe_files() -> dict[str, dict[str, object]]:
    expected_base = f"FROM {BUILDER_BASE_IMAGE} AS builder"
    files: dict[str, dict[str, object]] = {}
    for path in (DOCKERFILE, BUILD_SCRIPT):
        if not _regular_file(path):
            raise RuntimeError(f"FFmpeg 构建配方缺失：{path}")
        files[path.name] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
    dockerfile_text = DOCKERFILE.read_text(encoding="utf-8")
    if expected_base not in dockerfile_text or f"ARG DEBIAN_SNAPSHOT={DEBIAN_SNAPSHOT}" not in dockerfile_text:
        raise RuntimeError("FFmpeg Dockerfile 与固定基础镜像或 Debian 快照身份不一致")
    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    if FFMPEG_RELEASE_KEY_FINGERPRINT not in script_text:
        raise RuntimeError("FFmpeg 构建脚本未固定官方发布密钥指纹")
    return files


def _validate_pe_amd64(path: Path) -> None:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("FFmpeg 构建结果不是 PE 文件")
        stream.seek(0x3C)
        offset = stream.read(4)
        if len(offset) != 4:
            raise RuntimeError("FFmpeg PE 头不完整")
        stream.seek(struct.unpack("<I", offset)[0])
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError("FFmpeg PE 签名无效")
        machine = stream.read(2)
    if len(machine) != 2 or struct.unpack("<H", machine)[0] != 0x8664:
        raise RuntimeError("FFmpeg 构建结果不是 Windows AMD64")


def _configuration_options(configuration: str) -> set[str]:
    try:
        options = set(shlex.split(configuration, posix=True))
    except ValueError as exc:
        raise RuntimeError("FFmpeg 构建配置无法解析") from exc
    missing = REQUIRED_CONFIGURATION - options
    forbidden = FORBIDDEN_CONFIGURATION & options
    external = sorted(option for option in options if option.startswith("--enable-lib"))
    if missing:
        raise RuntimeError(f"FFmpeg 构建配置缺少固定选项：{sorted(missing)}")
    if forbidden:
        raise RuntimeError(f"FFmpeg 构建配置包含禁止许可选项：{sorted(forbidden)}")
    if external:
        raise RuntimeError(f"FFmpeg 构建配置启用了未随附的外部库：{external}")
    return options


def _nonempty_lines(path: Path, label: str) -> list[str]:
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"FFmpeg {label}不可读") from exc
    if not lines:
        raise RuntimeError(f"FFmpeg {label}为空")
    return lines


def _artifact_record(path: Path) -> dict[str, object]:
    return {"sha256": sha256_file(path), "size": path.stat().st_size}


def _write_evidence(output: Path, recipe_files: dict[str, dict[str, object]]) -> None:
    configuration_lines = _nonempty_lines(output / "buildconf.txt", "构建配置")
    if len(configuration_lines) != 1:
        raise RuntimeError("FFmpeg 构建配置必须只有一行")
    configuration = configuration_lines[0]
    _configuration_options(configuration)
    toolchain = _nonempty_lines(output / "toolchain-packages.txt", "工具链清单")
    imports = _nonempty_lines(output / "pe-imports.txt", "PE 导入清单")
    if any(
        name.casefold().startswith(("libgcc", "libstdc++", "libwinpthread")) for name in imports
    ):
        raise RuntimeError("FFmpeg 构建结果依赖未随附的 MinGW 运行库 DLL")
    ffmpeg = output / "ffmpeg.exe"
    _validate_pe_amd64(ffmpeg)
    evidence = {
        "schema_version": 1,
        "status": "verified",
        "target": "windows-amd64",
        "license_mode": "LGPL-2.1-or-later",
        "binary": {"path": "ffmpeg.exe", **_artifact_record(ffmpeg)},
        "source": {
            "name": FFMPEG_SOURCE_NAME,
            "url": FFMPEG_SOURCE_URL,
            "sha256": FFMPEG_SOURCE_SHA256,
            "size": FFMPEG_SOURCE_SIZE,
            "embedded_path": f"THIRD_PARTY_SOURCES/{FFMPEG_SOURCE_NAME}",
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
        },
        "recipe": {
            "base_image": BUILDER_BASE_IMAGE,
            "debian_snapshot": DEBIAN_SNAPSHOT,
            "configuration": configuration,
            "files": recipe_files,
            "toolchain_packages": toolchain,
            "pe_imports": imports,
        },
        "artifacts": {
            name: _artifact_record(output / name)
            for name in sorted(EXPECTED_OUTPUT_NAMES - {EVIDENCE_NAME})
        },
    }
    (output / EVIDENCE_NAME).write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def validate_output(output: Path) -> dict[str, object]:
    output = Path(output)
    if not output.is_dir() or output.is_symlink() or _is_reparse_point(output):
        raise RuntimeError(f"FFmpeg 构建输出目录无效：{output}")
    actual_names = {path.name for path in output.iterdir()}
    if actual_names != EXPECTED_OUTPUT_NAMES or any(not _regular_file(path) for path in output.iterdir()):
        raise RuntimeError("FFmpeg 构建输出文件集合无效")
    try:
        evidence = json.loads((output / EVIDENCE_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("FFmpeg 构建证据不是有效 JSON") from exc
    if not isinstance(evidence, dict):
        raise RuntimeError("FFmpeg 构建证据结构无效")
    recipe_files = _validate_recipe_files()
    expected_source = {
        "name": FFMPEG_SOURCE_NAME,
        "url": FFMPEG_SOURCE_URL,
        "sha256": FFMPEG_SOURCE_SHA256,
        "size": FFMPEG_SOURCE_SIZE,
        "embedded_path": f"THIRD_PARTY_SOURCES/{FFMPEG_SOURCE_NAME}",
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
    if (
        evidence.get("schema_version") != 1
        or isinstance(evidence.get("schema_version"), bool)
        or evidence.get("status") != "verified"
        or evidence.get("target") != "windows-amd64"
        or evidence.get("license_mode") != "LGPL-2.1-or-later"
        or evidence.get("source") != expected_source
    ):
        raise RuntimeError("FFmpeg 构建证据的来源、目标或许可身份无效")
    binary = evidence.get("binary")
    ffmpeg = output / "ffmpeg.exe"
    if binary != {"path": "ffmpeg.exe", **_artifact_record(ffmpeg)}:
        raise RuntimeError("FFmpeg 构建证据与实际二进制不一致")
    recipe = evidence.get("recipe")
    if (
        not isinstance(recipe, dict)
        or recipe.get("base_image") != BUILDER_BASE_IMAGE
        or recipe.get("debian_snapshot") != DEBIAN_SNAPSHOT
        or recipe.get("files") != recipe_files
    ):
        raise RuntimeError("FFmpeg 构建证据与当前固定配方不一致")
    configuration = recipe.get("configuration")
    if not isinstance(configuration, str):
        raise RuntimeError("FFmpeg 构建证据缺少配置")
    _configuration_options(configuration)
    if _nonempty_lines(output / "buildconf.txt", "构建配置") != [configuration]:
        raise RuntimeError("FFmpeg 构建配置文件与证据不一致")
    if recipe.get("toolchain_packages") != _nonempty_lines(
        output / "toolchain-packages.txt", "工具链清单"
    ):
        raise RuntimeError("FFmpeg 工具链清单与证据不一致")
    if recipe.get("pe_imports") != _nonempty_lines(output / "pe-imports.txt", "PE 导入清单"):
        raise RuntimeError("FFmpeg PE 导入清单与证据不一致")
    expected_artifacts = {
        name: _artifact_record(output / name)
        for name in sorted(EXPECTED_OUTPUT_NAMES - {EVIDENCE_NAME})
    }
    if evidence.get("artifacts") != expected_artifacts:
        raise RuntimeError("FFmpeg 构建产物清单与实际文件不一致")
    _validate_pe_amd64(ffmpeg)
    return evidence


def build(
    *,
    output: Path,
    source_archive: Path,
    source_signature: Path,
    release_key: Path,
) -> Path:
    output = Path(output).resolve(strict=False)
    _assert_build_subdirectory(output)
    _validate_input(
        Path(source_archive),
        size=FFMPEG_SOURCE_SIZE,
        sha256=FFMPEG_SOURCE_SHA256,
        label="FFmpeg 官方源码归档",
    )
    _validate_input(
        Path(source_signature),
        size=FFMPEG_SIGNATURE_SIZE,
        sha256=FFMPEG_SIGNATURE_SHA256,
        label="FFmpeg 官方源码签名",
    )
    _validate_input(
        Path(release_key),
        size=FFMPEG_RELEASE_KEY_SIZE,
        sha256=FFMPEG_RELEASE_KEY_SHA256,
        label="FFmpeg 官方发布公钥",
    )
    recipe_files = _validate_recipe_files()
    if _path_exists(output):
        validate_output(output)
        return output

    output.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    context = output.parent / f".{output.name}.{token}.context"
    staging = output.parent / f".{output.name}.{token}.tmp"
    if _path_exists(context) or _path_exists(staging):
        raise RuntimeError("FFmpeg 构建事务路径已存在")
    context.mkdir()
    try:
        shutil.copy2(source_archive, context / FFMPEG_SOURCE_NAME)
        shutil.copy2(source_signature, context / FFMPEG_SIGNATURE_NAME)
        shutil.copy2(release_key, context / FFMPEG_RELEASE_KEY_NAME)
        shutil.copy2(DOCKERFILE, context / "Dockerfile")
        shutil.copy2(BUILD_SCRIPT, context / BUILD_SCRIPT.name)
        environment = os.environ.copy()
        environment["DOCKER_BUILDKIT"] = "1"
        subprocess.run(
            [
                "docker",
                "buildx",
                "build",
                "--platform",
                "linux/amd64",
                "--provenance=false",
                "--output",
                f"type=local,dest={staging}",
                str(context),
            ],
            check=True,
            env=environment,
        )
        _write_evidence(staging, recipe_files)
        validate_output(staging)
        os.replace(staging, output)
        validate_output(output)
    finally:
        if _path_exists(staging):
            if staging.is_dir() and not staging.is_symlink() and not _is_reparse_point(staging):
                shutil.rmtree(staging)
            else:
                raise RuntimeError(f"FFmpeg 临时输出类型异常，拒绝清理：{staging}")
        if _path_exists(context):
            if context.is_dir() and not context.is_symlink() and not _is_reparse_point(context):
                shutil.rmtree(context)
            else:
                raise RuntimeError(f"FFmpeg 临时上下文类型异常，拒绝清理：{context}")
    return output


def main(argv: list[str] | None = None) -> int:
    cache = ROOT / "build" / "launcher-download-cache"
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source", type=Path, default=cache / FFMPEG_SOURCE_NAME)
    parser.add_argument("--signature", type=Path, default=cache / FFMPEG_SIGNATURE_NAME)
    parser.add_argument("--release-key", type=Path, default=cache / FFMPEG_RELEASE_KEY_NAME)
    arguments = parser.parse_args(argv)
    print(
        build(
            output=arguments.output,
            source_archive=arguments.source,
            source_signature=arguments.signature,
            release_key=arguments.release_key,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
