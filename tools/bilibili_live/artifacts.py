"""启动器工具提供者和候选 EXE 的只读身份校验与运行内复制。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.bilibili_live.contracts import (
    LiveBlockedError,
    LiveInconclusiveError,
    is_reparse,
)
from tools.bilibili_live.processes import isolated_process_environment


@dataclass(frozen=True, slots=True)
class BuildArtifact:
    record_path: Path
    executable_path: Path
    artifact_kind: str
    build_id: str
    sha256: str
    size_bytes: int
    source_commit: str
    source_dirty: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _reject_reparse_chain(path: Path, boundary: Path, label: str) -> None:
    candidate = Path(os.path.abspath(os.fspath(path)))
    parent = Path(os.path.abspath(os.fspath(boundary)))
    try:
        candidate.relative_to(parent)
    except ValueError as exc:
        raise LiveBlockedError(f"{label}越出允许目录") from exc
    current = candidate
    while True:
        if current.is_symlink() or is_reparse(current):
            raise LiveBlockedError(f"{label}不得经过符号链接或重解析点")
        if current == parent:
            return
        current = current.parent


def load_build_artifact(
    record_path: Path,
    *,
    workspace_root: Path,
    expected_kind: str,
) -> BuildArtifact:
    workspace = Path(workspace_root).resolve(strict=True)
    record = Path(record_path)
    if not record.is_absolute():
        record = workspace / record
    record = Path(os.path.abspath(os.fspath(record)))
    if expected_kind == "snapshot":
        expected_record = workspace / "launcher" / "current-build.json"
        if record != expected_record:
            raise LiveBlockedError("启动器工具提供者必须使用规范构建记录")
        _reject_reparse_chain(record, workspace, "启动器工具提供者构建记录")
    elif expected_kind == "candidate":
        try:
            record.relative_to(workspace / "build")
        except ValueError as exc:
            raise LiveBlockedError("候选构建记录必须位于仓库 build 目录") from exc
        _reject_reparse_chain(record, workspace, "候选构建记录")
        if not _within(record, workspace / "build"):
            raise LiveBlockedError("候选构建记录必须位于仓库 build 目录")
    else:
        raise ValueError(f"不支持的构建产物类型: {expected_kind}")
    if (
        not record.is_file()
        or record.is_symlink()
        or is_reparse(record)
        or record.stat().st_size > 1024 * 1024
    ):
        raise LiveBlockedError("启动器构建记录不是有效普通文件")
    record = record.resolve(strict=True)
    try:
        raw = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveBlockedError("启动器构建记录不是有效 UTF-8 JSON") from exc
    required = {
        "schema_version",
        "artifact_kind",
        "build_id",
        "executable",
        "sha256",
        "size_bytes",
        "source_commit",
        "source_dirty",
        "exe_self_check_ran",
        "exe_runtime_smoke_ran",
    }
    if not isinstance(raw, dict) or not required.issubset(raw):
        raise LiveBlockedError("启动器构建记录字段不完整")
    build_id = raw.get("build_id")
    digest = raw.get("sha256")
    size = raw.get("size_bytes")
    source_commit = raw.get("source_commit")
    relative_executable = raw.get("executable")
    if (
        raw.get("schema_version") != 2
        or raw.get("artifact_kind") != expected_kind
        or not isinstance(build_id, str)
        or len(build_id) != 12
        or any(character not in "0123456789abcdef" for character in build_id)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
        or not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
        or not isinstance(raw.get("source_dirty"), bool)
        or raw.get("exe_self_check_ran") is not True
        or raw.get("exe_runtime_smoke_ran") is not True
        or not isinstance(relative_executable, str)
    ):
        raise LiveBlockedError("启动器构建记录身份无效")
    relative = Path(relative_executable)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise LiveBlockedError("启动器构建记录的 executable 路径无效")
    raw_executable = workspace / relative
    _reject_reparse_chain(raw_executable, workspace, "启动器 EXE")
    executable = raw_executable.resolve(strict=False)
    if not _within(executable, workspace) or (
        not executable.is_file()
        or executable.is_symlink()
        or is_reparse(executable)
        or executable.stat().st_size != size
        or sha256_file(executable) != digest
    ):
        raise LiveBlockedError("启动器 EXE 与构建记录不一致")
    return BuildArtifact(
        record_path=record,
        executable_path=executable.resolve(strict=True),
        artifact_kind=expected_kind,
        build_id=build_id,
        sha256=digest,
        size_bytes=size,
        source_commit=source_commit,
        source_dirty=raw["source_dirty"],
    )


def _copy_file_exclusive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink() or is_reparse(destination):
        raise LiveInconclusiveError("运行内产物目标已经存在")
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    except OSError as exc:
        raise LiveInconclusiveError("无法复制已校验启动器产物") from exc


def _run_owned_tool(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: float,
) -> int:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process: subprocess.Popen[bytes] | None = None
    job: Any | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        if os.name == "nt":
            from launcher.bili_workspace_launcher.backend_process import _create_job

            job = _create_job()
            job.assign(process)
        return process.wait(timeout=timeout)
    except BaseException:
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=10)
            except Exception:
                pass
        raise
    finally:
        if job is not None:
            try:
                job.close()
            except Exception:
                pass


def copy_artifact_into_run(
    artifact: BuildArtifact,
    run_root: Path,
    *,
    directory_name: str,
) -> tuple[Path, Path]:
    if directory_name not in {"candidate", "tool-provider"}:
        raise ValueError("运行内启动器目录名称无效")
    run = Path(run_root).resolve(strict=True)
    destination_dir = run / directory_name
    if destination_dir.exists() or destination_dir.is_symlink() or is_reparse(destination_dir):
        raise LiveInconclusiveError("运行内启动器目录必须是全新路径")
    destination_dir.mkdir()
    executable = destination_dir / artifact.executable_path.name
    record = destination_dir / "build.json"
    _copy_file_exclusive(artifact.executable_path, executable)
    _copy_file_exclusive(artifact.record_path, record)
    if executable.stat().st_size != artifact.size_bytes or sha256_file(executable) != artifact.sha256:
        raise LiveInconclusiveError("运行内启动器副本身份不一致")
    return executable, record


def prepare_tool_provider(
    *,
    workspace_root: Path,
    run_root: Path,
    record_path: Path | None = None,
    timeout_seconds: int = 240,
) -> tuple[Path, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds

    def remaining_timeout() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LiveBlockedError("启动器工具提供者达到准备时限")
        return remaining

    selected_record = record_path or workspace_root / "launcher" / "current-build.json"
    artifact = load_build_artifact(
        selected_record,
        workspace_root=workspace_root,
        expected_kind="candidate" if record_path is not None else "snapshot",
    )
    executable, _record = copy_artifact_into_run(
        artifact,
        run_root,
        directory_name="tool-provider",
    )
    self_check = executable.parent / "self-check.json"
    run = Path(run_root).resolve(strict=True)
    environment = isolated_process_environment(run)
    try:
        return_code = _run_owned_tool(
            [
                str(executable),
                "--self-check",
                "--self-check-report",
                str(self_check),
            ],
            cwd=executable.parent,
            environment=environment,
            timeout=remaining_timeout(),
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise LiveBlockedError("启动器工具提供者无法完成 EXE 自检") from exc
    try:
        report = json.loads(self_check.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveBlockedError("启动器工具提供者没有生成有效自检报告") from exc
    if return_code != 0 or report != {"schema_version": 1, "status": "passed"}:
        raise LiveBlockedError("启动器工具提供者 EXE 自检失败")

    smoke_data = run / "tool-provider-smoke-data"
    smoke_report = run / "runtime-smoke.json"
    try:
        return_code = _run_owned_tool(
            [
                str(executable),
                "--runtime-smoke",
                "--data-root",
                str(smoke_data),
                "--expected-build-id",
                artifact.build_id,
                "--runtime-smoke-report",
                str(smoke_report),
            ],
            cwd=executable.parent,
            environment=environment,
            timeout=remaining_timeout(),
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise LiveBlockedError("启动器工具提供者无法展开并验证工具") from exc
    try:
        smoke = json.loads(smoke_report.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveBlockedError("启动器工具提供者没有生成有效运行时报告") from exc
    if (
        return_code != 0
        or smoke.get("status") != "passed"
        or smoke.get("build_id") != artifact.build_id
    ):
        raise LiveBlockedError("启动器工具提供者运行时自检失败")
    tools = executable.parent / "resources" / artifact.build_id / "windows-tools"
    bbdown = tools / "BBDown.exe"
    ffmpeg = tools / "ffmpeg" / "bin" / "ffmpeg.exe"
    if any(not path.is_file() or path.is_symlink() or is_reparse(path) for path in (bbdown, ffmpeg)):
        raise LiveBlockedError("启动器工具提供者没有展开完整 BBDown/FFmpeg")
    return tools.resolve(strict=True), {
        "artifact_kind": artifact.artifact_kind,
        "build_id": artifact.build_id,
        "sha256": artifact.sha256,
        "source_commit": artifact.source_commit,
        "source_dirty": artifact.source_dirty,
    }


def git_source_identity(workspace_root: Path) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve(strict=True)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise LiveBlockedError("无法读取当前源码 Git 身份") from exc
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise LiveBlockedError("当前源码 Git 身份无效")
    return {"commit": commit, "dirty": dirty}
