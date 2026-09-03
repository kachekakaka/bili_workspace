"""只由 T-BILIBILI-LIVE 编排器启动的当前源码回环服务。"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from pathlib import Path

import uvicorn

from app.main import create_app
from app.state import AppState
from tools.bilibili_live.contracts import (
    MAX_RUN_SECONDS,
    LiveInconclusiveError,
    is_reparse,
    read_summary,
)
from tools.t_project_isolation import validate_run


_READY_NAME = "source-live-ready.json"
_RESULT_NAME = "source-live-result.json"
_STOP_NAME = "source-live.stop"


def _write_exclusive(path: Path, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink() or is_reparse(path):
            raise LiveInconclusiveError("源码服务控制文件已经存在")
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_source_host_inputs(
    workspace_root: Path,
    run_root: Path,
    port: int,
) -> tuple[Path, Path, Path, Path]:
    workspace = Path(workspace_root).resolve(strict=True)
    run = validate_run(run_root, workspace)
    summary = read_summary(run, workspace)
    if summary.get("target") != "source":
        raise LiveInconclusiveError("源码服务只接受 target=source 的真链运行")
    if isinstance(port, bool) or not 1 <= int(port) <= 65535:
        raise LiveInconclusiveError("源码服务端口无效")
    data_root = run / "runtime"
    ready = run / "results" / _READY_NAME
    result = run / "results" / _RESULT_NAME
    stop = data_root / _STOP_NAME
    if not data_root.is_dir() or data_root.is_symlink() or is_reparse(data_root):
        raise LiveInconclusiveError("源码服务数据根类型无效")
    for path in (ready, result, stop):
        if path.exists() or path.is_symlink() or is_reparse(path):
            raise LiveInconclusiveError("源码服务控制文件必须是全新路径")
    return run, ready, result, stop


def run_source_host(workspace_root: Path, run_root: Path, port: int) -> int:
    run, ready, result, stop = validate_source_host_inputs(
        workspace_root,
        run_root,
        port,
    )
    state = AppState.create()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(state),
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
            proxy_headers=False,
            timeout_graceful_shutdown=10,
        )
    )
    finished = threading.Event()
    started_at = time.monotonic()

    def monitor() -> None:
        ready_written = False
        while not finished.wait(0.1):
            if server.started and not ready_written:
                _write_exclusive(
                    ready,
                    {
                        "schema_version": 1,
                        "kind": "bili-workspace-live-source-ready",
                        "pid": os.getpid(),
                        "host": "127.0.0.1",
                        "port": port,
                    },
                )
                ready_written = True
            if stop.is_file() or time.monotonic() - started_at >= MAX_RUN_SECONDS + 60:
                server.should_exit = True
                return

    watcher = threading.Thread(target=monitor, name="live-source-stop-monitor", daemon=True)
    watcher.start()
    exit_code = 0
    status = "stopped"
    try:
        server.run()
        if not ready.exists():
            status = "failed_before_ready"
            exit_code = 1
        elif not stop.is_file():
            status = "deadline_exceeded"
            exit_code = 1
    except BaseException:
        status = "host_error"
        exit_code = 1
    finally:
        finished.set()
        watcher.join(timeout=1)
        if not result.exists():
            _write_exclusive(
                result,
                {
                    "schema_version": 1,
                    "kind": "bili-workspace-live-source-result",
                    "status": status,
                    "pid": os.getpid(),
                },
            )
    return exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return run_source_host(
            arguments.workspace_root,
            arguments.run_root,
            arguments.port,
        )
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
