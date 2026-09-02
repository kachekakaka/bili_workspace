"""启动器命令入口、内部后端协议与 PyInstaller 自检。"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import re
import sys
from pathlib import Path, PurePosixPath

from .backend_process import record_backend_child_failure, run_backend_child
from .paths import AppPaths, _path_exists
from .resources import ResourceManager, sha256_file
from .version import PRODUCT_VERSION

_PYSIDE_OFFICIAL_LICENSES = {
    "qtpyside-v6.11.1/LICENSES/GPL-3.0-only.txt": {
        "size": 35_147,
        "sha256": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
    },
    "qtpyside-v6.11.1/LICENSES/LGPL-3.0-only.txt": {
        "size": 7_651,
        "sha256": "da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768",
    },
    "qtpyside-v6.11.1/LICENSES/Qt-GPL-exception-1.0.txt": {
        "size": 965,
        "sha256": "40678d338ce53cd93f8b22b281a2ecbcaa3ee65ce60b25ffb0c462b0530846b2",
    },
}
_SELF_CHECK_REPORT_NAME = "self-check.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bili-workspace-launcher")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--self-check", action="store_true", help=argparse.SUPPRESS)
    operation.add_argument("--run-backend", action="store_true", help=argparse.SUPPRESS)
    operation.add_argument("--runtime-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-check-report", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--session-journal", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--stop-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--log-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--data-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--expected-build-id", help=argparse.SUPPRESS)
    parser.add_argument("--runtime-smoke-report", type=Path, help=argparse.SUPPRESS)
    return parser


def _emit(message: str) -> None:
    if sys.stdout is not None:
        print(message)


def _validated_self_check_report(path: Path) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise RuntimeError("EXE 自检报告路径必须是绝对路径")
    report = raw.resolve(strict=False)
    base_dir = AppPaths.from_executable().base_dir.resolve(strict=False)
    if (
        report.parent != base_dir
        or report.name != _SELF_CHECK_REPORT_NAME
        or _path_exists(report)
    ):
        raise RuntimeError("EXE 自检报告必须是 EXE 同级的全新固定文件")
    return report


def _write_self_check_report(path: Path, payload: dict[str, object]) -> None:
    with path.open("xb") as stream:
        stream.write(
            (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _verify_license_materials(source_dir: Path) -> None:
    license_root = source_dir / "THIRD_PARTY_LICENSES"
    manifest_path = license_root / "installed" / "manifest.json"
    relinking_path = license_root / "RELINKING.md"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        relinking = relinking_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("启动器缺少可审计的第三方许可证材料") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("启动器第三方许可证清单必须是 JSON object")
    packages = raw.get("packages")
    python = raw.get("python")
    if (
        isinstance(raw.get("schema_version"), bool)
        or raw.get("schema_version") != 1
        or raw.get("contains_lgplv3_text") is not True
        or not isinstance(packages, list)
        or not isinstance(python, dict)
        or python.get("version") != sys.version.split()[0]
    ):
        raise RuntimeError("启动器第三方许可证清单结构或 Python 身份无效")

    declared_paths: set[str] = set()

    def verify_entry(entry: object, label: str) -> dict[str, object]:
        if not isinstance(entry, dict):
            raise RuntimeError(f"{label}许可证条目类型无效")
        relative = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if not isinstance(relative, str):
            raise RuntimeError(f"{label}许可证路径无效")
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in {"", ".", ".."} for part in pure.parts)
            or pure.as_posix() in declared_paths
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise RuntimeError(f"{label}许可证文件身份无效")
        declared_paths.add(pure.as_posix())
        path = manifest_path.parent.joinpath(*pure.parts)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
            or sha256_file(path) != digest
        ):
            raise RuntimeError(f"{label}许可证文件缺失或摘要不一致：{relative}")
        return entry

    verify_entry(python, "Python")
    versions: dict[str, str] = {}
    pyside_official_licenses: dict[str, dict[str, object]] = {}
    for raw_entry in packages:
        entry = verify_entry(raw_entry, "Python 包")
        distribution = entry.get("distribution")
        version = entry.get("version")
        if not isinstance(distribution, str) or not distribution or not isinstance(version, str):
            raise RuntimeError("Python 包许可证缺少发行包身份")
        canonical = _canonical_distribution_name(distribution)
        previous = versions.setdefault(canonical, version)
        if previous != version:
            raise RuntimeError(f"Python 包许可证版本冲突：{distribution}")
        source_path = entry.get("source_path")
        if (
            canonical == "pyside6"
            and isinstance(source_path, str)
            and source_path.startswith("qtpyside-v")
        ):
            if source_path in pyside_official_licenses:
                raise RuntimeError(f"PySide6 官方许可证来源重复：{source_path}")
            pyside_official_licenses[source_path] = {
                "size": entry.get("size"),
                "sha256": entry.get("sha256"),
            }

    actual_paths = {
        path.relative_to(manifest_path.parent).as_posix()
        for path in manifest_path.parent.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual_paths != declared_paths:
        raise RuntimeError("启动器许可证文件集合与清单不一致")

    required = {
        "pyside6": "6.11.1",
        "pyside6-essentials": "6.11.1",
        "pyside6-addons": "6.11.1",
        "shiboken6": "6.11.1",
        "pyinstaller": "6.22.0",
    }
    lock_path = source_dir / "docker-context" / "requirements" / "runtime.lock"
    try:
        lock_lines = lock_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("启动器内置运行依赖锁不可读") from exc
    for line in lock_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.count("==") != 1:
            raise RuntimeError("启动器内置运行依赖锁不是精确版本")
        name, version = stripped.split("==", 1)
        required[_canonical_distribution_name(name)] = version
    if versions != required:
        raise RuntimeError("启动器第三方许可证清单与固定构建依赖不一致")
    if pyside_official_licenses != _PYSIDE_OFFICIAL_LICENSES:
        raise RuntimeError("启动器缺少固定 Qt for Python 官方开源许可证全文")
    for marker in ("6.11.1", "qtbase", "反向工程", "重新构建"):
        if marker not in relinking:
            raise RuntimeError(f"Qt/PySide6 重新链接说明缺少 {marker}")


def _verify_tool_record(manifest_path: Path, source_dir: Path) -> None:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("启动器资源清单缺少工具验证记录") from exc
    verification = raw.get("tool_verification") if isinstance(raw, dict) else None
    bbdown = verification.get("bbdown") if isinstance(verification, dict) else None
    ffmpeg = verification.get("ffmpeg") if isinstance(verification, dict) else None
    compatible_transcode = (
        ffmpeg.get("compatible_transcode") if isinstance(ffmpeg, dict) else None
    )
    source_record = (
        verification.get("ffmpeg_source_evidence") if isinstance(verification, dict) else None
    )
    source_evidence = source_dir / "THIRD_PARTY_LICENSES" / "FFmpeg.SOURCE.json"
    if (
        not isinstance(verification, dict)
        or isinstance(verification.get("schema_version"), bool)
        or verification.get("schema_version") != 1
        or not isinstance(bbdown, dict)
        or not isinstance(ffmpeg, dict)
        or bbdown.get("version") != "1.6.3"
        or not str(ffmpeg.get("version_line", "")).lower().startswith(
            "ffmpeg version 7.1.1-bili-workspace"
        )
        or ffmpeg.get("license_mode") != "LGPL-2.1-or-later"
        or "--disable-autodetect" not in str(ffmpeg.get("configuration", "")).split()
        or "--enable-mediafoundation"
        not in str(ffmpeg.get("configuration", "")).split()
        or "--disable-network" not in str(ffmpeg.get("configuration", "")).split()
        or "--enable-gpl" in str(ffmpeg.get("configuration", "")).split()
        or "--enable-version3" in str(ffmpeg.get("configuration", "")).split()
        or "--enable-nonfree" in str(ffmpeg.get("configuration", "")).split()
        or any(
            option.startswith("--enable-lib")
            for option in str(ffmpeg.get("configuration", "")).split()
        )
        or not isinstance(compatible_transcode, dict)
        or compatible_transcode.get("video_encoder") != "h264_mf"
        or compatible_transcode.get("audio_encoder") != "aac"
        or compatible_transcode.get("pixel_format") != "nv12"
        or compatible_transcode.get("software_only") is not True
        or compatible_transcode.get("container") != "mp4"
        or isinstance(compatible_transcode.get("output_size"), bool)
        or not isinstance(compatible_transcode.get("output_size"), int)
        or compatible_transcode["output_size"] <= 0
        or re.fullmatch(
            r"[0-9a-f]{64}", str(compatible_transcode.get("output_sha256", ""))
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(compatible_transcode.get("encoder_help_sha256", "")),
        )
        is None
        or not isinstance(source_record, dict)
        or source_record.get("schema_version") != 1
        or isinstance(source_record.get("schema_version"), bool)
        or source_record.get("path") != "THIRD_PARTY_LICENSES/FFmpeg.SOURCE.json"
        or isinstance(source_record.get("source_count"), bool)
        or not isinstance(source_record.get("source_count"), int)
        or source_record["source_count"] != 1
        or not isinstance(source_record.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", source_record["sha256"]) is None
        or not source_evidence.is_file()
        or source_evidence.is_symlink()
        or source_record["sha256"] != sha256_file(source_evidence)
    ):
        raise RuntimeError("启动器内置工具验证记录与许可边界不一致")
    expected_files = {
        "bbdown": source_dir / "windows-tools" / "BBDown.exe",
        "ffmpeg": source_dir / "windows-tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
    }
    for name, path in expected_files.items():
        entry = verification[name]
        if entry.get("sha256") != sha256_file(path):
            raise RuntimeError(f"内置 {name} 与工具验证记录不一致")


def self_check() -> int:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError(f"启动器必须内置 Python 3.11，当前为 {sys.version.split()[0]}")
    import fastapi
    import PySide6
    import uvicorn
    from PySide6 import QtWidgets
    from app.constants import APP_VERSION
    from app.main import create_app
    from . import docker_jobs, gui

    if APP_VERSION != PRODUCT_VERSION:
        raise RuntimeError("启动器与后端产品版本不一致")
    manager = ResourceManager(AppPaths.from_executable())
    manifest = manager.verify_embedded_bundle()
    if create_app is None or QtWidgets.QApplication is None:
        raise RuntimeError("后端或 Qt GUI 未完整打包")
    if docker_jobs.DockerJobs is None or gui.MainWindow is None:
        raise RuntimeError("Docker 作业或 GUI 模块未完整打包")
    notice = manager.source_dir / "THIRD_PARTY_NOTICES.txt"
    try:
        notice_text = notice.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("启动器缺少第三方许可告知") from exc
    for name in ("PySide6", "PyInstaller", "BBDown", "FFmpeg"):
        if name not in notice_text:
            raise RuntimeError(f"第三方许可告知缺少 {name}")
    _verify_license_materials(manager.source_dir)
    _verify_tool_record(manager.manifest_path, manager.source_dir)
    _emit(
        "self-check passed: "
        f"bili_workspace {PRODUCT_VERSION} build {manifest.build_id}, "
        f"Python {sys.version.split()[0]}, FastAPI {fastapi.__version__}, "
        f"Uvicorn {uvicorn.__version__}, PySide6 {PySide6.__version__}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    arguments = _parser().parse_args(argv)
    backend_internal = {
        "session-journal": arguments.session_journal,
        "stop-file": arguments.stop_file,
        "log-file": arguments.log_file,
    }
    runtime_internal = {
        "data-root": arguments.data_root,
        "expected-build-id": arguments.expected_build_id,
        "runtime-smoke-report": arguments.runtime_smoke_report,
    }
    self_check_internal = {"self-check-report": arguments.self_check_report}
    if arguments.self_check:
        unexpected = [
            name
            for name, value in {**backend_internal, **runtime_internal}.items()
            if value is not None
        ]
        if unexpected:
            raise RuntimeError("EXE 自检不接受其他内部参数：" + ", ".join(unexpected))
        if arguments.self_check_report is not None:
            try:
                self_check_report = _validated_self_check_report(
                    arguments.self_check_report
                )
            except Exception:
                return 1
        else:
            self_check_report = None
        try:
            result = self_check()
        except Exception as exc:
            if self_check_report is not None:
                try:
                    _write_self_check_report(
                        self_check_report,
                        {
                            "schema_version": 1,
                            "status": "failed",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass
            return 1
        if self_check_report is not None:
            _write_self_check_report(
                self_check_report,
                {"schema_version": 1, "status": "passed"},
            )
        return result
    if arguments.runtime_smoke:
        unexpected = [
            name
            for name, value in {**backend_internal, **self_check_internal}.items()
            if value is not None
        ]
        if unexpected:
            raise RuntimeError("运行时冒烟不接受后端子进程参数：" + ", ".join(unexpected))
        missing = [name for name, value in runtime_internal.items() if value is None]
        if missing:
            raise RuntimeError("缺少运行时冒烟参数：" + ", ".join(missing))
        from .runtime_smoke import (
            run_runtime_smoke,
            validate_runtime_smoke_inputs,
            write_report,
        )

        assert arguments.data_root is not None
        assert arguments.expected_build_id is not None
        assert arguments.runtime_smoke_report is not None
        try:
            _data_root, safe_report = validate_runtime_smoke_inputs(
                arguments.data_root,
                arguments.runtime_smoke_report,
            )
        except Exception:
            return 1
        try:
            result = run_runtime_smoke(
                arguments.data_root,
                arguments.expected_build_id,
                arguments.runtime_smoke_report,
            )
        except Exception as exc:
            try:
                write_report(
                    safe_report,
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            except Exception:
                pass
            return 1
        write_report(safe_report, result)
        return 0
    if arguments.run_backend:
        unexpected = [
            name
            for name, value in {**runtime_internal, **self_check_internal}.items()
            if value is not None
        ]
        if unexpected:
            raise RuntimeError("后端子进程不接受运行时冒烟参数：" + ", ".join(unexpected))
        missing = [name for name, value in backend_internal.items() if value is None]
        if missing:
            raise RuntimeError("缺少内部后端参数：" + ", ".join(missing))
        try:
            return run_backend_child(
                journal_file=arguments.session_journal,
                stop_file=arguments.stop_file,
                log_file=arguments.log_file,
            )
        except Exception as exc:
            record_backend_child_failure(arguments.session_journal, exc)
            return 1
    unused_internal = {**backend_internal, **runtime_internal, **self_check_internal}
    unexpected = [name for name, value in unused_internal.items() if value is not None]
    if unexpected:
        raise RuntimeError("内部参数缺少对应操作：" + ", ".join(unexpected))
    from .gui import run_gui

    return run_gui()
