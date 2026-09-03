"""源码或候选产品进程的精确拥有、就绪校验和停止。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any, Mapping, Sequence

from tools.bilibili_live.contracts import (
    LiveBlockedError,
    LiveInconclusiveError,
    is_reparse,
)


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def isolated_process_environment(run_root: Path) -> dict[str, str]:
    run = Path(run_root).resolve(strict=True)
    directories = (
        run / "home",
        run / "tmp",
        run / "pycache",
        run / "runtime" / "userdata" / "cache",
        run / "runtime" / "userdata" / "local-app-data",
        run / "runtime" / "userdata" / "roaming-app-data",
    )
    for directory in directories:
        if directory.exists() and (
            not directory.is_dir()
            or directory.is_symlink()
            or is_reparse(directory)
        ):
            raise LiveInconclusiveError("隔离子进程目录类型无效")
        directory.mkdir(parents=True, exist_ok=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("BILI_", "PYTHON"))
        and key.upper() not in {"HOMEDRIVE", "HOMEPATH"}
    }
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONPYCACHEPREFIX": str(run / "pycache"),
            "HOME": str(run / "home"),
            "USERPROFILE": str(run / "home"),
            "LOCALAPPDATA": str(run / "runtime" / "userdata" / "local-app-data"),
            "APPDATA": str(run / "runtime" / "userdata" / "roaming-app-data"),
            "XDG_CACHE_HOME": str(run / "runtime" / "userdata" / "cache"),
            "DOTNET_BUNDLE_EXTRACT_BASE_DIR": str(
                run / "runtime" / "userdata" / "cache" / "dotnet"
            ),
            "DOTNET_CLI_HOME": str(run / "home" / "dotnet"),
            "TEMP": str(run / "tmp"),
            "TMP": str(run / "tmp"),
            "TMPDIR": str(run / "tmp"),
        }
    )
    return environment


def source_environment(
    *,
    workspace_root: Path,
    run_root: Path,
    port: int,
    tools_dir: Path,
) -> dict[str, str]:
    run = Path(run_root).resolve(strict=True)
    data = run / "runtime"
    environment = isolated_process_environment(run)
    environment.update(
        {
            "BILI_DISABLE_LEGACY_MIGRATION": "1",
            "BILI_APP_MODE": "local",
            "BILI_HOST": "127.0.0.1",
            "BILI_PORT": str(port),
            "BILI_TRUSTED_HOSTS": "127.0.0.1,localhost",
            "BILI_ALLOW_IP_HOSTS": "false",
            "BILI_CONFIG_DIR": str(data / "config"),
            "BILI_USERDATA_DIR": str(data / "userdata"),
            "BILI_DATABASE_PATH": str(data / "userdata" / "bili_workspace.db"),
            "BILI_MEDIA_DIR": str(data / "downloads"),
            "BILI_CACHE_DIR": str(data / "userdata" / "cache"),
            "BILI_TEMP_DIR": str(data / "userdata" / "tmp"),
            "BILI_BBDOWN_DIR": str(Path(tools_dir).resolve(strict=True)),
            "BILI_BBDOWN_DATA_DIR": str(data / "config" / "bbdown"),
            "BILI_APP_RESOURCE_ROOT": str(Path(workspace_root).resolve(strict=True)),
            "BILI_MIN_FREE_GIB": "5",
            "BILI_DOWNLOAD_CONCURRENCY": "1",
        }
    )
    return environment


class OwnedProductProcess:
    def __init__(
        self,
        *,
        command: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
        log_path: Path,
        ready_path: Path,
        result_path: Path,
        stop_path: Path,
        expected_ready_kind: str,
        expected_result_kind: str,
        expected_build_id: str | None = None,
        expected_token_sha256: str | None = None,
        ready_timeout: float = 90,
    ) -> None:
        self.command = list(command)
        self.cwd = Path(cwd)
        self.environment = dict(environment)
        self.log_path = Path(log_path)
        self.ready_path = Path(ready_path)
        self.result_path = Path(result_path)
        self.stop_path = Path(stop_path)
        self.expected_ready_kind = expected_ready_kind
        self.expected_result_kind = expected_result_kind
        self.expected_build_id = expected_build_id
        self.expected_token_sha256 = expected_token_sha256
        self.ready_timeout = ready_timeout
        self.process: subprocess.Popen[bytes] | None = None
        self._log_stream: IO[bytes] | None = None
        self._job: Any | None = None
        self.url: str | None = None

    def start(self) -> str:
        for path in (self.log_path, self.ready_path, self.result_path, self.stop_path):
            if path.exists() or path.is_symlink() or is_reparse(path):
                raise LiveInconclusiveError("产品会话控制文件必须是全新路径")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self._log_stream = self.log_path.open("xb")
            self.process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=self._log_stream,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            if os.name == "nt":
                from launcher.bili_workspace_launcher.backend_process import _create_job

                self._job = _create_job()
                self._job.assign(self.process)
        except (OSError, RuntimeError) as exc:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.kill()
                    self.process.wait(timeout=10)
                except Exception:
                    pass
            self._close_ownership()
            raise LiveBlockedError("无法启动受控产品进程") from exc

        try:
            deadline = time.monotonic() + self.ready_timeout
            while time.monotonic() < deadline:
                if self.ready_path.is_file():
                    ready = self._read_control(self.ready_path, self.expected_ready_kind)
                    pid = ready.get("pid")
                    port = ready.get("port")
                    if (
                        self.process is None
                        or isinstance(pid, bool)
                        or pid != self.process.pid
                        or isinstance(port, bool)
                        or not isinstance(port, int)
                        or not 1 <= port <= 65535
                        or ready.get("host") != "127.0.0.1"
                        or (
                            self.expected_build_id is not None
                            and ready.get("build_id") != self.expected_build_id
                        )
                        or (
                            self.expected_token_sha256 is not None
                            and ready.get("token_sha256")
                            != self.expected_token_sha256
                        )
                    ):
                        raise LiveInconclusiveError("产品会话就绪身份不匹配")
                    self.url = f"http://127.0.0.1:{port}"
                    return self.url
                if self.process is not None and self.process.poll() is not None:
                    raise LiveBlockedError("产品进程在就绪前退出")
                time.sleep(0.1)
            raise LiveBlockedError("产品进程未在时限内就绪")
        except BaseException:
            self.abort()
            raise

    @staticmethod
    def _read_control(path: Path, expected_kind: str) -> dict[str, Any]:
        if (
            not path.is_file()
            or path.is_symlink()
            or is_reparse(path)
            or path.stat().st_size > 64 * 1024
        ):
            raise LiveInconclusiveError("产品会话控制文件类型无效")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LiveInconclusiveError("产品会话控制文件无效") from exc
        if (
            not isinstance(raw, dict)
            or type(raw.get("schema_version")) is not int
            or raw.get("schema_version") != 1
            or raw.get("kind") != expected_kind
        ):
            raise LiveInconclusiveError("产品会话控制文件身份无效")
        return raw

    def stop(self, timeout: float = 30) -> dict[str, Any]:
        process = self.process
        if process is None:
            raise LiveInconclusiveError("产品进程尚未启动")
        if self.stop_path.is_symlink() or is_reparse(self.stop_path) or (
            self.stop_path.exists() and not self.stop_path.is_file()
        ):
            raise LiveInconclusiveError("产品会话停止路径类型无效")
        if not self.stop_path.exists():
            with self.stop_path.open("xb") as stream:
                stream.write(b"stop\n")
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.abort()
            raise LiveInconclusiveError("产品进程未能优雅停止")
        finally:
            self._close_ownership()
        result = self._read_control(self.result_path, self.expected_result_kind)
        if (
            return_code != 0
            or result.get("status") != "stopped"
            or (
                self.expected_build_id is not None
                and result.get("build_id") != self.expected_build_id
            )
            or (
                self.expected_token_sha256 is not None
                and result.get("token_sha256") != self.expected_token_sha256
            )
        ):
            raise LiveInconclusiveError("产品进程以异常状态结束")
        return result

    def abort(self) -> None:
        process = self.process
        try:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        except Exception:
            pass
        finally:
            self._close_ownership()

    def _close_ownership(self) -> None:
        if self._job is not None:
            try:
                self._job.close()
            except Exception:
                pass
            self._job = None
        if self._log_stream is not None:
            try:
                self._log_stream.close()
            except OSError:
                pass
            self._log_stream = None


def source_product_process(
    *,
    workspace_root: Path,
    run_root: Path,
    tools_dir: Path,
) -> OwnedProductProcess:
    port = reserve_loopback_port()
    run = Path(run_root)
    return OwnedProductProcess(
        command=[
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "tools.bilibili_live.source_host",
            "--workspace-root",
            str(Path(workspace_root).resolve(strict=True)),
            "--run-root",
            str(run.resolve(strict=True)),
            "--port",
            str(port),
        ],
        cwd=workspace_root,
        environment=source_environment(
            workspace_root=workspace_root,
            run_root=run,
            port=port,
            tools_dir=tools_dir,
        ),
        log_path=run / "results" / "source-process.log",
        ready_path=run / "results" / "source-live-ready.json",
        result_path=run / "results" / "source-live-result.json",
        stop_path=run / "runtime" / "source-live.stop",
        expected_ready_kind="bili-workspace-live-source-ready",
        expected_result_kind="bili-workspace-live-source-result",
    )


def candidate_product_process(
    *,
    executable: Path,
    build_id: str,
    run_root: Path,
) -> OwnedProductProcess:
    run = Path(run_root).resolve(strict=True)
    candidate = Path(executable).resolve(strict=True)
    session_token = secrets.token_hex(32)
    token_digest = hashlib.sha256(session_token.encode("ascii")).hexdigest()
    environment = isolated_process_environment(run)
    environment.update(
        {
            "BILI_LIVE_SESSION_TOKEN": session_token,
        }
    )
    return OwnedProductProcess(
        command=[
            str(candidate),
            "--live-session",
            "--data-root",
            str(run / "runtime"),
            "--expected-build-id",
            build_id,
            "--live-session-ready",
            str(run / "results" / "candidate-live-ready.json"),
            "--live-session-result",
            str(run / "results" / "candidate-live-result.json"),
            "--live-session-stop",
            str(run / "runtime" / "candidate-live.stop"),
        ],
        cwd=candidate.parent,
        environment=environment,
        log_path=run / "results" / "candidate-process.log",
        ready_path=run / "results" / "candidate-live-ready.json",
        result_path=run / "results" / "candidate-live-result.json",
        stop_path=run / "runtime" / "candidate-live.stop",
        expected_ready_kind="bili-workspace-live-candidate-ready",
        expected_result_kind="bili-workspace-live-candidate-result",
        expected_build_id=build_id,
        expected_token_sha256=token_digest,
    )
