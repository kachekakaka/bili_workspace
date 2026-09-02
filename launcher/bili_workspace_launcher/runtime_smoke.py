"""候选 EXE 的全新数据根运行时冒烟。"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

from app.constants import DATABASE_SCHEMA_VERSION

from .backend_process import BackendProcessManager
from .paths import AppPaths, DataRootLock, DataRootManager, _is_reparse_point, _path_exists
from .ports import is_port_available, recommend_available_port
from .resources import ResourceManager
from .settings import NetworkSettings, RuntimeEnvStore

_DIRECT_URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_MAX_ROOT_RESPONSE_BYTES = 2 * 1024 * 1024
_REPORT_NAME = "runtime-smoke.json"


def _validate_build_id(value: str) -> str:
    if len(value) != 12 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError("运行时冒烟的预期 build_id 无效")
    return value


def validate_runtime_smoke_inputs(
    data_root: Path, report_path: Path
) -> tuple[Path, Path]:
    raw_data_root = Path(data_root)
    raw_report = Path(report_path)
    if not raw_data_root.is_absolute() or not raw_report.is_absolute():
        raise RuntimeError("运行时冒烟的数据根和报告路径必须是绝对路径")
    resolved_data_root = raw_data_root.resolve(strict=False)
    resolved_report = raw_report.resolve(strict=False)
    if _path_exists(resolved_data_root):
        raise RuntimeError("运行时冒烟只接受尚不存在的全新数据根")
    if (
        resolved_report.name != _REPORT_NAME
        or resolved_report.parent != resolved_data_root.parent
        or _path_exists(resolved_report)
    ):
        raise RuntimeError("运行时冒烟报告必须是数据根同级的全新固定文件")
    return resolved_data_root, resolved_report


def write_report(path: Path, payload: dict[str, object]) -> None:
    """只创建构建器预先约定的报告文件，不覆盖任何既有路径。"""

    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    with Path(path).open("xb") as stream:
        stream.write(encoded)


def _local_available_network(network: NetworkSettings) -> NetworkSettings:
    validated = network.validated()
    if validated.mode != "local" or validated.public_base_url:
        raise RuntimeError("全新数据根必须使用无公开 URL 的本机模式")
    if is_port_available(validated.port, validated.host):
        return validated
    recommended = recommend_available_port(
        validated.port,
        checker=lambda port: is_port_available(port, validated.host),
    )
    if recommended is None:
        raise RuntimeError("没有可供运行时冒烟使用的本机端口")
    return replace(validated, port=recommended).validated()


def _probe_root_page(url: str, trusted_host: str) -> None:
    request = urllib.request.Request(url, headers={"Host": trusted_host})
    try:
        with _DIRECT_URL_OPENER.open(request, timeout=5) as response:
            payload = response.read(_MAX_ROOT_RESPONSE_BYTES + 1)
            content_type = response.headers.get_content_type()
            status = response.status
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("无法读取候选后端页面入口") from exc
    lowered = payload.lower()
    if (
        status != 200
        or content_type != "text/html"
        or len(payload) > _MAX_ROOT_RESPONSE_BYTES
        or b"<html" not in lowered
    ):
        raise RuntimeError("候选后端页面入口响应无效")


def _database_schema(path: Path) -> int:
    if not path.is_file() or path.is_symlink() or _is_reparse_point(path):
        raise RuntimeError("运行时冒烟没有生成 SQLite 数据库")
    try:
        database_uri = path.resolve(strict=True).as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as connection:
            value = connection.execute("PRAGMA user_version").fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError("无法读取运行时冒烟数据库 schema") from exc
    version = int(value[0]) if value else -1
    if version != DATABASE_SCHEMA_VERSION:
        raise RuntimeError(
            f"运行时冒烟数据库为 schema v{version}，预期 v{DATABASE_SCHEMA_VERSION}"
        )
    return version


def run_runtime_smoke(
    data_root: Path,
    expected_build_id: str,
    report_path: Path,
    *,
    paths: AppPaths | None = None,
) -> dict[str, object]:
    """展开候选资源，启动自有后端并验证健康、首页和 schema。"""

    expected_build_id = _validate_build_id(expected_build_id)
    data_root, _report_path = validate_runtime_smoke_inputs(data_root, report_path)
    app_paths = paths or AppPaths.from_executable()
    app_paths.ensure_control_directories()
    resource_root, manifest = ResourceManager(app_paths).ensure_extracted()
    if manifest.build_id != expected_build_id:
        raise RuntimeError("候选 EXE 的内置 build_id 与构建器预期不一致")

    data_roots = DataRootManager(
        app_paths,
        resource_root / "docker-context" / "app" / "defaults",
    )
    preview = data_roots.resolve_layout(data_root)
    data_lock = DataRootLock(preview)
    backend = BackendProcessManager(app_paths)
    backend_started = False
    data_lock.acquire()
    try:
        layout = data_roots.prepare_locked(preview.root, data_lock)
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
        if backend.url is None:
            raise RuntimeError("候选后端没有可验证的本机 URL")
        _probe_root_page(backend.url, network.trusted_hosts[0])
        port = backend.port
        forced = backend.stop()
        backend_started = False
        if forced:
            raise RuntimeError("候选后端未能优雅停止")
    finally:
        try:
            if backend_started or backend.port is not None:
                backend.stop(timeout=0)
        finally:
            data_lock.release()

    schema_version = _database_schema(layout.database_file)
    return {
        "schema_version": 1,
        "status": "passed",
        "build_id": manifest.build_id,
        "application_schema_version": schema_version,
        "mode": network.mode,
        "root_page": "passed",
        "port": port,
    }
