"""内置后端子进程的启动、身份校验、健康探测与精确停止。"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.io_utils import atomic_write_json, atomic_write_text
from app.task_logs import redact_sensitive

from .constants import (
    BACKEND_START_TIMEOUT_SECONDS,
    BACKEND_STOP_TIMEOUT_SECONDS,
)
from .paths import (
    AppPaths,
    DataRootLayout,
    DataRootLock,
    DataRootManager,
    _is_reparse_point,
    _path_exists,
)
from .resources import ResourceManager
from .settings import NetworkSettings

_CHILD_SESSION_MAX_AGE_SECONDS = 5 * 60
_CHILD_SESSION_MAX_FUTURE_SKEW_SECONDS = 30
_CHILD_PARENT_COMMIT_TIMEOUT_SECONDS = 5.0
_MAX_CHILD_JOURNAL_BYTES = 64 * 1024
_DIRECT_URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_BACKEND_SESSION_FILES = frozenset({"session.json", "stop.request", "child-error.txt"})
_ERROR_INVALID_PARAMETER = 87
_STILL_ACTIVE = 259


class BackendProcessError(RuntimeError):
    """后端子进程无法安全启动、验证或停止。"""


class JobHandle(Protocol):
    def assign(self, process: Any) -> None: ...
    def close(self) -> None: ...


class _NoopJob:
    def assign(self, process: Any) -> None:
        del process

    def close(self) -> None:
        return


class _WindowsJob:
    """关闭父进程句柄时终止全部子进程的 Windows Job Object。"""

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _EXTENDED_LIMIT(ctypes.Structure):
        pass

    _EXTENDED_LIMIT._fields_ = [
        ("BasicLimitInformation", _BASIC_LIMIT),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = self._EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise OSError(error, "SetInformationJobObject failed")
        self._kernel32 = kernel32
        self._handle = handle

    def assign(self, process: Any) -> None:
        handle = self._handle
        process_handle = getattr(process, "_handle", None)
        if not handle or process_handle is None:
            raise OSError("Popen process handle is unavailable")
        if not self._kernel32.AssignProcessToJobObject(handle, ctypes.c_void_p(process_handle)):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            self._kernel32.CloseHandle(handle)


def _create_job() -> JobHandle:
    return _WindowsJob() if os.name == "nt" else _NoopJob()


def backend_command_prefix() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "bili_workspace_launcher"]


def _url_host(host: str) -> str:
    value = host.strip("[]")
    if value in {"0.0.0.0", "::"}:
        value = "127.0.0.1" if value == "0.0.0.0" else "::1"
    return f"[{value}]" if ":" in value else value


def _read_bounded_tail(path: Path, max_bytes: int) -> str | None:
    if (
        max_bytes <= 0
        or not path.is_file()
        or path.is_symlink()
        or _is_reparse_point(path)
    ):
        return None
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, size - max_bytes))
            payload = stream.read(max_bytes)
    except OSError:
        return None
    return payload.decode("utf-8", errors="replace")


def _process_exists(pid: int) -> bool:
    """Return True when a PID is alive or its state cannot be checked safely."""
    if pid <= 0:
        return True
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != _ERROR_INVALID_PARAMETER
        try:
            exit_code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, PermissionError):
        return True
    return True


def _stale_session_pid(paths: AppPaths, session_dir: Path) -> int | None:
    """Validate a launcher-owned session directory before considering cleanup."""
    try:
        paths.assert_owned_work_path(session_dir)
    except ValueError:
        return None
    if (
        not session_dir.name.startswith("backend-")
        or len(session_dir.name) != len("backend-") + 32
        or any(character not in "0123456789abcdef" for character in session_dir.name[8:])
        or not session_dir.is_dir()
        or session_dir.is_symlink()
        or _is_reparse_point(session_dir)
    ):
        return None
    try:
        entries = list(session_dir.iterdir())
    except OSError:
        return None
    if not entries or any(
        entry.name not in _BACKEND_SESSION_FILES
        or not entry.is_file()
        or entry.is_symlink()
        or _is_reparse_point(entry)
        for entry in entries
    ):
        return None
    journal_file = session_dir / "session.json"
    if journal_file not in entries:
        return None
    try:
        if journal_file.stat().st_size > _MAX_CHILD_JOURNAL_BYTES:
            return None
        raw = json.loads(journal_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    allowed_fields = {
        "schema_version",
        "kind",
        "job_id",
        "build_id",
        "token_sha256",
        "data_root",
        "resource_root",
        "host",
        "port",
        "created_at",
        "pid",
        "spawned_at",
    }
    pid = raw.get("pid") if isinstance(raw, dict) else None
    if (
        not isinstance(raw, dict)
        or set(raw) != allowed_fields
        or raw.get("schema_version") != 1
        or isinstance(raw.get("schema_version"), bool)
        or raw.get("kind") != "backend-session"
        or raw.get("job_id") != session_dir.name
        or not isinstance(raw.get("build_id"), str)
        or len(raw["build_id"]) != 12
        or any(character not in "0123456789abcdef" for character in raw["build_id"])
        or not isinstance(raw.get("token_sha256"), str)
        or len(raw["token_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in raw["token_sha256"])
        or not isinstance(raw.get("data_root"), str)
        or not Path(raw["data_root"]).is_absolute()
        or not isinstance(raw.get("resource_root"), str)
        or not Path(raw["resource_root"]).is_absolute()
        or not isinstance(raw.get("host"), str)
        or not raw["host"]
        or isinstance(raw.get("port"), bool)
        or not isinstance(raw.get("port"), int)
        or not 1 <= raw["port"] <= 65535
        or isinstance(raw.get("created_at"), bool)
        or not isinstance(raw.get("created_at"), int)
        or raw["created_at"] < 0
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(raw.get("spawned_at"), bool)
        or not isinstance(raw.get("spawned_at"), int)
        or raw["spawned_at"] < raw["created_at"]
    ):
        return None
    return pid


class BackendProcessManager:
    def __init__(
        self,
        paths: AppPaths,
        *,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        job_factory: Callable[[], JobHandle] = _create_job,
    ) -> None:
        self.paths = paths
        self._popen_factory = popen_factory
        self._job_factory = job_factory
        self._process: Any | None = None
        self._job: JobHandle | None = None
        self._data_lock: DataRootLock | None = None
        self._session_dir: Path | None = None
        self._stop_file: Path | None = None
        self._journal_file: Path | None = None
        self._failure_file: Path | None = None
        self._log_file: Path | None = None
        self._network: NetworkSettings | None = None
        self._expected_build_id: str | None = None

    @property
    def process_id(self) -> int | None:
        process = self._process
        return int(process.pid) if process is not None and process.poll() is None else None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def port(self) -> int | None:
        return self._network.port if self._network is not None else None

    @property
    def url(self) -> str | None:
        if self._network is None:
            return None
        if self._network.public_base_url:
            return self._network.public_base_url + "/"
        return f"http://{_url_host(self._network.host)}:{self._network.port}/"

    @property
    def bind_description(self) -> str:
        if self._network is None:
            return ""
        return f"{self._network.host}:{self._network.port}"

    def recover_stale_sessions(self) -> list[str]:
        """Remove only strictly validated sessions whose recorded process is gone."""
        messages: list[str] = []
        if not self.paths.work_dir.is_dir():
            return messages
        for session_dir in sorted(self.paths.work_dir.glob("backend-*")):
            pid = _stale_session_pid(self.paths, session_dir)
            if pid is None or _process_exists(pid):
                continue
            try:
                for entry in session_dir.iterdir():
                    entry.unlink()
                session_dir.rmdir()
            except OSError as exc:
                messages.append(f"遗留后端会话清理失败：{session_dir.name}：{exc}")
            else:
                messages.append(f"已清理无存活进程的遗留后端会话：{session_dir.name}")
        return messages

    def start(
        self,
        *,
        layout: DataRootLayout,
        network: NetworkSettings,
        resource_root: Path,
        build_id: str,
        data_lock: DataRootLock | None = None,
    ) -> None:
        if self.is_running:
            raise BackendProcessError("后端已经由当前启动器启动")
        network = network.validated()
        if (
            len(build_id) != 12
            or any(character not in "0123456789abcdef" for character in build_id)
        ):
            raise BackendProcessError("内置资源 build_id 无效")
        resource_candidate = Path(resource_root)
        if (
            resource_candidate.is_symlink()
            or _is_reparse_point(resource_candidate)
            or not resource_candidate.is_dir()
        ):
            raise BackendProcessError("内置资源根类型无效")
        try:
            resolved_resource = resource_candidate.resolve(strict=True)
            expected_resource = (self.paths.resources_dir / build_id).resolve(strict=True)
        except OSError as exc:
            raise BackendProcessError("无法解析内置资源根") from exc
        if resolved_resource != expected_resource:
            raise BackendProcessError("内置资源根与 build_id 不匹配")
        tools_dir = resolved_resource / "windows-tools"
        required_tools = (
            tools_dir / "BBDown.exe",
            tools_dir / "ffmpeg" / "bin" / "ffmpeg.exe",
        )
        if any(
            not tool.is_file() or tool.is_symlink() or _is_reparse_point(tool)
            for tool in required_tools
        ):
            raise BackendProcessError("内置 BBDown/FFmpeg 资源不完整")
        self.paths.ensure_control_directories()
        owned_lock: DataRootLock | None = None
        if data_lock is None:
            owned_lock = DataRootLock(layout)
            owned_lock.acquire()
        elif (
            not data_lock.acquired
            or data_lock.layout.root.resolve() != layout.root.resolve()
        ):
            raise BackendProcessError("调用方持有的数据根锁与当前数据根不匹配")
        session_dir: Path | None = None
        session_created = False
        process: Any | None = None
        job: JobHandle | None = None
        try:
            job_id = f"backend-{uuid.uuid4().hex}"
            session_dir = self.paths.owned_job_dir(job_id)
            session_dir.mkdir(parents=False, exist_ok=False)
            session_created = True
            stop_file = session_dir / "stop.request"
            journal_file = session_dir / "session.json"
            failure_file = session_dir / "child-error.txt"
            log_dir = layout.logs_dir
            if _path_exists(log_dir) and (
                log_dir.is_symlink() or _is_reparse_point(log_dir) or not log_dir.is_dir()
            ):
                raise BackendProcessError(f"后端日志目录类型无效：{log_dir}")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = layout.backend_log_file
            if _path_exists(log_file) and (
                log_file.is_symlink() or _is_reparse_point(log_file) or not log_file.is_file()
            ):
                raise BackendProcessError(f"后端日志文件类型无效：{log_file}")
            token = uuid.uuid4().hex
            token_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
            journal = {
                "schema_version": 1,
                "kind": "backend-session",
                "job_id": job_id,
                "build_id": build_id,
                "token_sha256": token_digest,
                "data_root": str(layout.root),
                "resource_root": str(resolved_resource),
                "host": network.host,
                "port": network.port,
                "created_at": int(time.time()),
            }
            atomic_write_json(journal_file, journal, backup=False)
            # The selected data root and launcher-owned session are authoritative.
            # Inherited BILI_* variables must not redirect the packaged child.
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith(("BILI_", "PYTHON"))
            }
            environment.update(network.environment())
            environment.update(
                {
                    "PYTHONUTF8": "1",
                    "BILI_LAUNCHER_CHILD": "1",
                    "BILI_DISABLE_LEGACY_MIGRATION": "1",
                    "BILI_CONFIG_DIR": str(layout.config_dir),
                    "BILI_USERDATA_DIR": str(layout.userdata_dir),
                    "BILI_DATABASE_PATH": str(layout.database_file),
                    "BILI_MEDIA_DIR": str(layout.downloads_dir),
                    "BILI_CACHE_DIR": str(layout.cache_dir),
                    "BILI_TEMP_DIR": str(layout.temp_dir),
                    "BILI_BBDOWN_TOOLS_DIR": str(tools_dir),
                    "BILI_BBDOWN_DATA_DIR": str(layout.bbdown_data_dir),
                    "BILI_APP_RESOURCE_ROOT": str(resolved_resource / "docker-context"),
                    "BILI_BUILD_ID": build_id,
                    "BILI_LAUNCHER_TOKEN": token,
                    "HOME": str(layout.home_dir),
                    "XDG_CACHE_HOME": str(layout.cache_dir),
                    "DOTNET_BUNDLE_EXTRACT_BASE_DIR": str(layout.dotnet_bundle_dir),
                    "TEMP": str(layout.temp_dir),
                    "TMP": str(layout.temp_dir),
                    "TMPDIR": str(layout.temp_dir),
                }
            )
            command = [
                *backend_command_prefix(),
                "--run-backend",
                "--session-journal",
                str(journal_file),
                "--stop-file",
                str(stop_file),
                "--log-file",
                str(log_file),
            ]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = self._popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=creationflags,
                env=environment,
            )
            job = self._job_factory()
            job.assign(process)
            journal["pid"] = int(process.pid)
            journal["spawned_at"] = int(time.time())
            atomic_write_json(journal_file, journal, backup=False)
        except Exception as exc:
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass
            if job is not None:
                try:
                    job.close()
                except Exception:
                    pass
            if owned_lock is not None:
                owned_lock.release()
            if session_created and session_dir is not None and _path_exists(session_dir):
                self.paths.assert_owned_work_path(session_dir)
                if (
                    session_dir.is_symlink()
                    or _is_reparse_point(session_dir)
                    or not session_dir.is_dir()
                ):
                    raise BackendProcessError(
                        f"后端启动失败，且会话目录类型已改变：{session_dir}"
                    ) from exc
                shutil.rmtree(session_dir)
            raise BackendProcessError("无法创建并约束内置后端子进程") from exc
        assert session_dir is not None
        self._process = process
        self._job = job
        self._data_lock = owned_lock
        self._session_dir = session_dir
        self._stop_file = stop_file
        self._journal_file = journal_file
        self._failure_file = failure_file
        self._log_file = log_file
        self._network = network
        self._expected_build_id = build_id

    def health_ready(self, timeout: float = 0.5) -> bool:
        if not self.is_running or self._network is None:
            return False
        url = f"http://{_url_host(self._network.host)}:{self._network.port}/healthz"
        request = urllib.request.Request(
            url,
            headers={"Host": self._network.trusted_hosts[0]},
        )
        try:
            with _DIRECT_URL_OPENER.open(request, timeout=timeout) as response:
                payload = response.read(4097)
                if response.status != 200 or len(payload) > 4096:
                    return False
                decoded = json.loads(payload.decode("utf-8"))
                return (
                    isinstance(decoded, dict)
                    and decoded.get("ok") is True
                    and decoded.get("build_id") == self._expected_build_id
                    and decoded.get("mode") == self._network.mode
                    and self._process is not None
                    and self._process.poll() is None
                )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
        ):
            return False

    def wait_until_ready(self, timeout: float = BACKEND_START_TIMEOUT_SECONDS) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise BackendProcessError("内置后端启动后提前退出：" + self.log_tail())
            if self.health_ready():
                return
            time.sleep(0.1)
        raise BackendProcessError("内置后端未在时限内通过健康检查")

    def log_tail(self, lines: int = 30) -> str:
        log_file = self._log_file
        failure = ""
        if self._failure_file is not None:
            failure = (_read_bounded_tail(self._failure_file, 4096) or "").strip()
        if log_file is None:
            return failure or "无后端日志"
        raw_log = _read_bounded_tail(log_file, 256 * 1024)
        if raw_log is None:
            return "无法读取后端日志"
        content = raw_log.splitlines()
        tail = "\n".join(content[-max(1, min(lines, 200)):]) or "后端日志为空"
        combined = f"{tail}\n{failure}" if failure else tail
        return redact_sensitive(combined)

    def stop(self, timeout: float = BACKEND_STOP_TIMEOUT_SECONDS) -> bool:
        process = self._process
        forced = False
        if process is None:
            self._release_ownership()
            return forced
        if process.poll() is None:
            assert self._stop_file is not None
            session_dir = self._session_dir
            if session_dir is None or self._stop_file.parent != session_dir:
                raise BackendProcessError("后端停止请求缺少当前会话身份")
            try:
                self.paths.assert_owned_work_path(session_dir)
            except ValueError as exc:
                raise BackendProcessError("后端会话目录越出启动器工作区") from exc
            if (
                not session_dir.is_dir()
                or session_dir.is_symlink()
                or _is_reparse_point(session_dir)
            ):
                raise BackendProcessError(f"后端会话目录类型无效：{session_dir}")
            if _path_exists(self._stop_file) and (
                self._stop_file.is_symlink()
                or _is_reparse_point(self._stop_file)
                or not self._stop_file.is_file()
            ):
                raise BackendProcessError(f"停止请求路径类型无效：{self._stop_file}")
            atomic_write_text(self._stop_file, "stop\n", backup=False)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if self._process is process and process.poll() is None:
                    process.kill()
                    forced = True
                    process.wait(timeout=5)
        self._cleanup_session()
        return forced

    def _release_ownership(self) -> None:
        job = self._job
        self._job = None
        first_error: Exception | None = None
        if job is not None:
            try:
                job.close()
            except Exception as exc:
                first_error = exc
        lock = self._data_lock
        self._data_lock = None
        if lock is not None:
            try:
                lock.release()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _cleanup_session(self) -> None:
        session_dir = self._session_dir
        cleanup_error: Exception | None = None
        try:
            self._release_ownership()
            if session_dir is not None and _path_exists(session_dir):
                self.paths.assert_owned_work_path(session_dir)
                if (
                    session_dir.is_symlink()
                    or _is_reparse_point(session_dir)
                    or not session_dir.is_dir()
                ):
                    raise BackendProcessError(f"后端会话目录类型无效：{session_dir}")
                shutil.rmtree(session_dir)
        except Exception as exc:
            cleanup_error = exc
        finally:
            self._process = None
            self._session_dir = None
            self._stop_file = None
            self._journal_file = None
            self._failure_file = None
            self._log_file = None
            self._network = None
            self._expected_build_id = None
        if cleanup_error is not None:
            if isinstance(cleanup_error, BackendProcessError):
                raise cleanup_error
            raise BackendProcessError(f"无法清理后端会话：{session_dir}") from cleanup_error


def _load_and_verify_child_session(
    *,
    paths: AppPaths,
    journal_file: Path,
    stop_file: Path,
    log_file: Path,
    wait_for_parent_commit: bool = False,
) -> tuple[DataRootLayout, Path, dict[str, Any]]:
    paths.assert_owned_work_path(journal_file)
    paths.assert_owned_work_path(stop_file)
    session_dir = journal_file.parent
    if (
        journal_file.name != "session.json"
        or stop_file != session_dir / "stop.request"
        or not session_dir.name.startswith("backend-")
        or len(session_dir.name) != len("backend-") + 32
        or any(character not in "0123456789abcdef" for character in session_dir.name[8:])
    ):
        raise BackendProcessError("内部会话文件不属于同一作业")
    if (
        not session_dir.is_dir()
        or session_dir.is_symlink()
        or _is_reparse_point(session_dir)
        or not journal_file.is_file()
        or journal_file.is_symlink()
        or _is_reparse_point(journal_file)
        or (_path_exists(stop_file) and (
            not stop_file.is_file()
            or stop_file.is_symlink()
            or _is_reparse_point(stop_file)
        ))
    ):
        raise BackendProcessError("内部会话文件类型无效")
    deadline = time.monotonic() + _CHILD_PARENT_COMMIT_TIMEOUT_SECONDS
    while True:
        try:
            if journal_file.stat().st_size > _MAX_CHILD_JOURNAL_BYTES:
                raise BackendProcessError("内部会话 journal 超过大小上限")
            raw = json.loads(journal_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendProcessError("内部会话 journal 无效") from exc
        if not wait_for_parent_commit or (
            isinstance(raw, dict) and "pid" in raw and "spawned_at" in raw
        ):
            break
        if time.monotonic() >= deadline:
            raise BackendProcessError("父进程未在时限内提交完整会话身份")
        time.sleep(0.025)
    required = {
        "schema_version": 1,
        "kind": "backend-session",
        "job_id": session_dir.name,
        "build_id": os.getenv("BILI_BUILD_ID", ""),
        "host": os.getenv("BILI_HOST", ""),
    }
    allowed_fields = {
        "schema_version",
        "kind",
        "job_id",
        "build_id",
        "token_sha256",
        "data_root",
        "resource_root",
        "host",
        "port",
        "created_at",
        "pid",
        "spawned_at",
    }
    if (
        not isinstance(raw, dict)
        or isinstance(raw.get("schema_version"), bool)
        or any(raw.get(key) != value for key, value in required.items())
        or set(raw) - allowed_fields
        or isinstance(raw.get("created_at"), bool)
        or not isinstance(raw.get("created_at"), int)
        or raw["created_at"] < 0
        or "pid" not in raw
        or "spawned_at" not in raw
    ):
        raise BackendProcessError("内部会话身份不匹配")
    try:
        environment_port = int(os.environ["BILI_PORT"])
    except (KeyError, ValueError) as exc:
        raise BackendProcessError("内部会话端口无效") from exc
    if (
        isinstance(raw.get("port"), bool)
        or not isinstance(raw.get("port"), int)
        or raw["port"] != environment_port
    ):
        raise BackendProcessError("内部会话端口不匹配")
    token = os.getenv("BILI_LAUNCHER_TOKEN", "")
    token_digest = raw.get("token_sha256")
    token_is_valid = len(token) == 32 and all(
        character in "0123456789abcdef" for character in token
    )
    actual_token_digest = (
        hashlib.sha256(token.encode("ascii")).hexdigest() if token_is_valid else ""
    )
    if (
        not token_is_valid
        or not isinstance(token_digest, str)
        or len(token_digest) != 64
        or any(character not in "0123456789abcdef" for character in token_digest)
        or not hmac.compare_digest(actual_token_digest, token_digest)
    ):
        raise BackendProcessError("内部会话令牌不匹配")
    now = int(time.time())
    created_at = raw["created_at"]
    if (
        created_at < now - _CHILD_SESSION_MAX_AGE_SECONDS
        or created_at > now + _CHILD_SESSION_MAX_FUTURE_SKEW_SECONDS
    ):
        raise BackendProcessError("内部会话令牌已过期或创建时间异常")
    if (
        isinstance(raw["pid"], bool)
        or not isinstance(raw["pid"], int)
        or raw["pid"] != os.getpid()
    ):
        raise BackendProcessError("内部会话 PID 不匹配")
    if (
        isinstance(raw["spawned_at"], bool)
        or not isinstance(raw["spawned_at"], int)
        or raw["spawned_at"] < raw["created_at"]
        or raw["spawned_at"] > now + _CHILD_SESSION_MAX_FUTURE_SKEW_SECONDS
    ):
        raise BackendProcessError("内部会话创建时间无效")
    raw_config_dir = os.environ.get("BILI_CONFIG_DIR", "").strip()
    if not raw_config_dir or not Path(raw_config_dir).is_absolute():
        raise BackendProcessError("内部会话配置目录无效")
    data_root = Path(raw_config_dir).resolve().parent
    try:
        journal_data_root = Path(str(raw.get("data_root") or "")).resolve(strict=True)
    except OSError as exc:
        raise BackendProcessError("内部会话数据根不存在") from exc
    if data_root != journal_data_root:
        raise BackendProcessError("内部会话数据根不匹配")
    layout = DataRootLayout(data_root)
    raw_resource_root = str(raw.get("resource_root") or "").strip()
    if not raw_resource_root or not Path(raw_resource_root).is_absolute():
        raise BackendProcessError("内部会话资源根无效")
    resource_root = Path(raw_resource_root).resolve()
    paths.assert_owned_resource_path(resource_root)
    manager = ResourceManager(paths)
    manifest = manager.load_manifest()
    if manifest.build_id != raw.get("build_id"):
        raise BackendProcessError("展开资源与内部会话 build_id 不一致")
    if resource_root != (paths.resources_dir / manifest.build_id).resolve():
        raise BackendProcessError("展开资源目录与 build_id 不一致")
    manager.verify_tree(resource_root, manifest)
    expected_paths = {
        "BILI_CONFIG_DIR": layout.config_dir,
        "BILI_USERDATA_DIR": layout.userdata_dir,
        "BILI_DATABASE_PATH": layout.database_file,
        "BILI_MEDIA_DIR": layout.downloads_dir,
        "BILI_CACHE_DIR": layout.cache_dir,
        "BILI_TEMP_DIR": layout.temp_dir,
        "BILI_BBDOWN_TOOLS_DIR": resource_root / "windows-tools",
        "BILI_BBDOWN_DATA_DIR": layout.bbdown_data_dir,
        "BILI_APP_RESOURCE_ROOT": resource_root / "docker-context",
        "HOME": layout.home_dir,
        "XDG_CACHE_HOME": layout.cache_dir,
        "DOTNET_BUNDLE_EXTRACT_BASE_DIR": layout.dotnet_bundle_dir,
        "TEMP": layout.temp_dir,
        "TMP": layout.temp_dir,
        "TMPDIR": layout.temp_dir,
    }
    for name, expected in expected_paths.items():
        raw_value = os.environ.get(name, "").strip()
        if not raw_value or not Path(raw_value).is_absolute():
            raise BackendProcessError(f"内部会话路径缺失或不是绝对路径：{name}")
        if Path(raw_value).resolve() != expected.resolve():
            raise BackendProcessError(f"内部会话路径不匹配：{name}")
    if os.environ.get("BILI_DISABLE_LEGACY_MIGRATION", "").strip() != "1":
        raise BackendProcessError("启动器子进程必须禁用旧路径迁移")
    layout = DataRootManager(paths).prepare(data_root)
    if log_file.resolve(strict=False) != layout.backend_log_file.resolve(strict=False):
        raise BackendProcessError("后端日志路径不匹配")
    return layout, resource_root, raw


def run_backend_child(*, journal_file: Path, stop_file: Path, log_file: Path) -> int:
    if os.getenv("BILI_LAUNCHER_CHILD", "") != "1":
        raise BackendProcessError("内部后端只能由启动器创建")
    paths = AppPaths.from_executable()
    _layout, _resource_root, _journal = _load_and_verify_child_session(
        paths=paths,
        journal_file=journal_file,
        stop_file=stop_file,
        log_file=log_file,
        wait_for_parent_commit=True,
    )
    # The one-time launch secret is no longer needed after the journal and all
    # inherited paths have been verified. Do not leak it to BBDown/FFmpeg.
    os.environ.pop("BILI_LAUNCHER_TOKEN", None)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler],
        force=True,
    )

    from app.main import create_app
    from app.state import AppState
    import uvicorn

    state = AppState.create()
    runtime = state.runtime
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(state),
            host=runtime.host,
            port=runtime.port,
            log_config=None,
            access_log=False,
            proxy_headers=runtime.server_mode,
            forwarded_allow_ips=(
                ",".join(runtime.trusted_proxy_ips) if runtime.server_mode else ""
            ),
        )
    )
    finished = threading.Event()

    def monitor_stop_file() -> None:
        while not finished.wait(0.2):
            if stop_file.is_file():
                server.should_exit = True
                return

    monitor = threading.Thread(target=monitor_stop_file, name="launcher-stop-monitor", daemon=True)
    monitor.start()
    try:
        server.run()
    finally:
        finished.set()
        monitor.join(timeout=1)
    return 0


def record_backend_child_failure(journal_file: Path, error: BaseException) -> None:
    """Persist an early child failure only inside the launcher-owned session."""

    try:
        paths = AppPaths.from_executable()
        journal = Path(journal_file).resolve()
        paths.assert_owned_work_path(journal)
        failure_file = journal.parent / "child-error.txt"
        paths.assert_owned_work_path(failure_file)
        detail = redact_sensitive(str(error).replace("\r", " ").replace("\n", " "))
        detail = " ".join(detail.split())[:1000]
        message = f"{type(error).__name__}: {detail or '后端子进程初始化失败'}\n"
        atomic_write_text(failure_file, message, backup=False)
    except Exception:
        return
