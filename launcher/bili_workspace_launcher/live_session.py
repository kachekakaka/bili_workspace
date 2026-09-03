"""候选 EXE 在已验证 T-BILIBILI-LIVE run 中的隐藏受控会话。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .backend_process import BackendProcessManager
from .paths import (
    AppPaths,
    DataRootLock,
    DataRootManager,
    _is_reparse_point,
    _path_exists,
)
from .resources import ResourceManager
from .runtime_smoke import _local_available_network, _probe_root_page, _validate_build_id
from .settings import RuntimeEnvStore


_RUN_MARKER_NAME = ".bili-workspace-test-run.json"
_SUMMARY_RELATIVE = Path("results") / "summary.json"
_READY_NAME = "candidate-live-ready.json"
_RESULT_NAME = "candidate-live-result.json"
_STOP_NAME = "candidate-live.stop"
_MAX_JSON_BYTES = 1024 * 1024
_MAX_SESSION_SECONDS = 16 * 60
_SESSION_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_MARKER_FIELDS = {
    "kind",
    "project_id",
    "workspace_root",
    "test_root",
    "run_root",
    "run_id",
    "created_at",
}
_RUN_DIRECTORIES = (
    "config",
    "userdata",
    "downloads",
    "runtime",
    "media-tools",
    "home",
    "pycache",
    "tmp",
    "pytest",
    "results",
)


@dataclass(frozen=True, slots=True)
class LiveSessionInputs:
    run_root: Path
    data_root: Path
    ready_path: Path
    result_path: Path
    stop_path: Path


def _read_json(path: Path, label: str) -> dict[str, object]:
    if (
        not path.is_file()
        or path.is_symlink()
        or _is_reparse_point(path)
        or path.stat().st_size > _MAX_JSON_BYTES
    ):
        raise RuntimeError(f"{label}类型或大小无效")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label}不是有效 UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"{label}必须是 JSON object")
    return raw


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _validate_owned_run(paths: AppPaths) -> Path:
    raw_base = paths.base_dir
    if (
        not raw_base.is_dir()
        or raw_base.is_symlink()
        or _is_reparse_point(raw_base)
    ):
        raise RuntimeError("候选 live-session 的 candidate 目录类型无效")
    raw_run = raw_base.parent
    if raw_run.is_symlink() or _is_reparse_point(raw_run):
        raise RuntimeError("候选 live-session 的 run 类型无效")
    base = raw_base.resolve(strict=True)
    if base.name != "candidate":
        raise RuntimeError("候选 live-session 要求 EXE 位于 run/candidate")
    run = base.parent
    if (
        not run.is_dir()
        or run.is_symlink()
        or _is_reparse_point(run)
        or not _within(base, run)
    ):
        raise RuntimeError("候选 live-session 的 run 类型无效")
    marker = _read_json(run / _RUN_MARKER_NAME, "真链 run 所有权标记")
    if set(marker) != _RUN_MARKER_FIELDS:
        raise RuntimeError("真链 run 所有权标记字段集合无效")
    required_marker = {
        "kind": "bili-workspace-test-run",
        "project_id": "bili_workspace",
        "run_root": str(run),
        "run_id": run.name,
        "test_root": str(run.parent),
    }
    if any(marker.get(key) != value for key, value in required_marker.items()):
        raise RuntimeError("真链 run 所有权标记身份不匹配")
    created_at = marker.get("created_at")
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("真链 run 所有权标记 created_at 无效") from exc
    if not isinstance(created_at, str) or created.tzinfo is None:
        raise RuntimeError("真链 run 所有权标记 created_at 无效")
    workspace_value = marker.get("workspace_root")
    test_root_value = marker.get("test_root")
    if (
        not isinstance(workspace_value, str)
        or not Path(workspace_value).is_absolute()
        or not isinstance(test_root_value, str)
        or not Path(test_root_value).is_absolute()
    ):
        raise RuntimeError("真链 run 所有权标记缺少工作区身份")
    workspace_path = Path(workspace_value)
    test_root_path = Path(test_root_value)
    if (
        workspace_path.is_symlink()
        or _is_reparse_point(workspace_path)
        or test_root_path.is_symlink()
        or _is_reparse_point(test_root_path)
    ):
        raise RuntimeError("真链 run 所有权路径边界无效")
    try:
        workspace = workspace_path.resolve(strict=True)
        test_root = test_root_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("真链 run 所有权路径无法解析") from exc
    if (
        not workspace.is_dir()
        or workspace.is_symlink()
        or _is_reparse_point(workspace)
        or not test_root.is_dir()
        or test_root.is_symlink()
        or _is_reparse_point(test_root)
        or run.parent != test_root
        or _within(run, workspace)
        or _within(workspace, run)
    ):
        raise RuntimeError("真链 run 所有权路径边界无效")
    for relative in _RUN_DIRECTORIES:
        directory = run / relative
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or _is_reparse_point(directory)
            or not _within(directory.resolve(strict=True), run)
        ):
            raise RuntimeError(f"真链 run 缺少安全子目录: {relative}")
    summary = _read_json(run / _SUMMARY_RELATIVE, "真链摘要")
    if (
        type(summary.get("schema_version")) is not int
        or summary.get("schema_version") != 1
        or summary.get("test_id") != "T-BILIBILI-LIVE"
        or summary.get("run_id") != run.name
        or summary.get("target") != "candidate"
    ):
        raise RuntimeError("候选 live-session 摘要身份不匹配")
    return run


def validate_live_session_inputs(
    *,
    data_root: Path,
    ready_path: Path,
    result_path: Path,
    stop_path: Path,
    paths: AppPaths | None = None,
) -> LiveSessionInputs:
    app_paths = paths or AppPaths.from_executable()
    run = _validate_owned_run(app_paths)
    values = (data_root, ready_path, result_path, stop_path)
    if any(not Path(value).is_absolute() for value in values):
        raise RuntimeError("候选 live-session 的全部路径必须是绝对路径")
    data = Path(data_root).resolve(strict=False)
    ready = Path(ready_path).resolve(strict=False)
    result = Path(result_path).resolve(strict=False)
    stop = Path(stop_path).resolve(strict=False)
    if data != run / "runtime":
        raise RuntimeError("候选 live-session 数据根必须是 run/runtime")
    if ready != run / "results" / _READY_NAME:
        raise RuntimeError("候选 live-session 就绪记录路径无效")
    if result != run / "results" / _RESULT_NAME:
        raise RuntimeError("候选 live-session 结果记录路径无效")
    if stop != run / "runtime" / _STOP_NAME:
        raise RuntimeError("候选 live-session 停止路径无效")
    if not data.is_dir() or data.is_symlink() or _is_reparse_point(data):
        raise RuntimeError("候选 live-session 数据根类型无效")
    for path in (ready, result, stop):
        if _path_exists(path):
            raise RuntimeError("候选 live-session 控制文件必须是全新路径")
    return LiveSessionInputs(run, data, ready, result, stop)


def write_live_record(path: Path, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if _path_exists(path):
            raise RuntimeError("候选 live-session 控制文件已经存在")
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def live_session_token_sha256(session_token: str) -> str:
    if not isinstance(session_token, str) or _SESSION_TOKEN_RE.fullmatch(session_token) is None:
        raise RuntimeError("候选 live-session 会话令牌无效")
    return hashlib.sha256(session_token.encode("ascii")).hexdigest()


def _wait_for_stop(
    inputs: LiveSessionInputs,
    backend: BackendProcessManager,
    started_at: float,
) -> None:
    while True:
        if _path_exists(inputs.stop_path):
            if (
                not inputs.stop_path.is_file()
                or inputs.stop_path.is_symlink()
                or _is_reparse_point(inputs.stop_path)
            ):
                raise RuntimeError("候选 live-session 停止路径类型无效")
            return
        if not backend.is_running:
            raise RuntimeError("候选 live-session 后端提前退出")
        if time.monotonic() - started_at >= _MAX_SESSION_SECONDS:
            raise RuntimeError("候选 live-session 达到最大时限")
        time.sleep(0.2)


def run_live_session(
    *,
    data_root: Path,
    expected_build_id: str,
    ready_path: Path,
    result_path: Path,
    stop_path: Path,
    session_token: str,
    paths: AppPaths | None = None,
) -> dict[str, object]:
    token_digest = live_session_token_sha256(session_token)
    expected_build_id = _validate_build_id(expected_build_id)
    app_paths = paths or AppPaths.from_executable()
    inputs = validate_live_session_inputs(
        data_root=data_root,
        ready_path=ready_path,
        result_path=result_path,
        stop_path=stop_path,
        paths=app_paths,
    )
    app_paths.ensure_control_directories()
    resource_root, manifest = ResourceManager(app_paths).ensure_extracted()
    if manifest.build_id != expected_build_id:
        raise RuntimeError("候选 EXE 的内置 build_id 与真链预期不一致")

    manager = DataRootManager(
        app_paths,
        resource_root / "docker-context" / "app" / "defaults",
    )
    preview = manager.resolve_layout(inputs.data_root)
    data_lock = DataRootLock(preview)
    backend = BackendProcessManager(app_paths)
    backend_started = False
    started_at = time.monotonic()
    data_lock.acquire()
    try:
        layout = manager.prepare_locked(preview.root, data_lock)
        network = _local_available_network(RuntimeEnvStore(layout.runtime_env_file).load())
        backend.start(
            layout=layout,
            network=network,
            resource_root=resource_root,
            build_id=manifest.build_id,
            data_lock=data_lock,
        )
        backend_started = True
        backend.wait_until_ready()
        if backend.url is None or backend.process_id is None:
            raise RuntimeError("候选 live-session 没有可验证的本机 URL")
        _probe_root_page(backend.url, network.trusted_hosts[0])
        write_live_record(
            inputs.ready_path,
            {
                "schema_version": 1,
                "kind": "bili-workspace-live-candidate-ready",
                "pid": os.getpid(),
                "backend_pid": backend.process_id,
                "build_id": manifest.build_id,
                "token_sha256": token_digest,
                "host": "127.0.0.1",
                "port": backend.port,
            },
        )
        _wait_for_stop(inputs, backend, started_at)
        forced = backend.stop()
        backend_started = False
        if forced:
            raise RuntimeError("候选 live-session 后端未能优雅停止")
    finally:
        try:
            if backend_started or backend.port is not None:
                backend.stop(timeout=0)
        finally:
            data_lock.release()
    result = {
        "schema_version": 1,
        "kind": "bili-workspace-live-candidate-result",
        "status": "stopped",
        "pid": os.getpid(),
        "build_id": manifest.build_id,
        "token_sha256": token_digest,
    }
    write_live_record(inputs.result_path, result)
    return result
