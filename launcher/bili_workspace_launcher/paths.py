"""EXE 控制根、用户数据根与独占所有权边界。"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.config_files import ensure_env_from_default, ensure_json_from_default
from app.io_utils import atomic_write_json
from app.paths import defaults_dir

from .constants import EXECUTABLE_BASENAME

_SAFE_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
_MARKER_NAME = ".bili-workspace-data-root.json"
_LOCK_NAME = ".bili-workspace.lock"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_MAX_MARKER_BYTES = 64 * 1024
_MAX_DATA_CONFIG_BYTES = 8 * 1024 * 1024


class PathOwnershipError(ValueError):
    """路径越出启动器明确拥有的边界。"""


class DataRootError(ValueError):
    """所选目录不能安全地作为数据根。"""


class DataRootLockError(RuntimeError):
    """另一个活动启动器已经拥有同一数据根。"""


def _is_within(candidate: Path, parent: Path) -> bool:
    resolved_candidate = candidate.resolve(strict=False)
    resolved_parent = parent.resolve(strict=False)
    return resolved_candidate == resolved_parent or resolved_parent in resolved_candidate.parents


def _overlaps(left: Path, right: Path) -> bool:
    return _is_within(left, right) or _is_within(right, left)


def _is_reparse_point(path: Path) -> bool:
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse_point(path)


def _regular_file_or_missing(path: Path) -> bool:
    return not _path_exists(path) or (
        path.is_file() and not path.is_symlink() and not _is_reparse_point(path)
    )


def _git_boundary(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        marker = candidate / ".git"
        if _path_exists(marker):
            return candidate
    return None


@dataclass(frozen=True, slots=True)
class AppPaths:
    """跟随某一份 EXE 的可重建控制根。"""

    base_dir: Path

    @classmethod
    def from_executable(cls, executable: Path | None = None) -> "AppPaths":
        if executable is None:
            if getattr(sys, "frozen", False):
                executable = Path(sys.executable)
            else:
                executable = Path(__file__).resolve().parents[1] / EXECUTABLE_BASENAME
        return cls(Path(executable).resolve(strict=False).parent)

    @property
    def settings_file(self) -> Path:
        return self.base_dir / "launcher.json"

    @property
    def resources_dir(self) -> Path:
        return self.base_dir / "resources"

    @property
    def work_dir(self) -> Path:
        return self.base_dir / "work"

    def ensure_control_directories(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.resources_dir, self.work_dir):
            if directory.is_symlink() or _is_reparse_point(directory):
                raise PathOwnershipError(f"控制目录不能是重解析点：{directory}")
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise PathOwnershipError(f"控制路径不是目录：{directory}")
        descriptor: int | None = None
        probe: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=".launcher-write-", dir=self.base_dir)
            probe = Path(name)
            os.close(descriptor)
            descriptor = None
            probe.unlink()
            probe = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if probe is not None:
                probe.unlink(missing_ok=True)

    def owned_job_dir(self, job_id: str) -> Path:
        if not _SAFE_JOB_ID_RE.fullmatch(job_id):
            raise PathOwnershipError(f"非法作业 ID：{job_id!r}")
        candidate = self.work_dir / job_id
        self.assert_owned_work_path(candidate)
        return candidate

    def assert_owned_resource_path(self, candidate: Path) -> None:
        if not _is_within(candidate, self.resources_dir):
            raise PathOwnershipError(f"资源路径越界：{candidate}")

    def assert_owned_work_path(self, candidate: Path) -> None:
        if not _is_within(candidate, self.work_dir):
            raise PathOwnershipError(f"作业路径越界：{candidate}")


@dataclass(frozen=True, slots=True)
class DataRootLayout:
    root: Path

    @property
    def marker_file(self) -> Path:
        return self.root / _MARKER_NAME

    @property
    def lock_file(self) -> Path:
        return self.root / _LOCK_NAME

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def userdata_dir(self) -> Path:
        return self.root / "userdata"

    @property
    def downloads_dir(self) -> Path:
        return self.root / "downloads"

    @property
    def bbdown_data_dir(self) -> Path:
        return self.config_dir / "bbdown"

    @property
    def cache_dir(self) -> Path:
        return self.userdata_dir / "cache"

    @property
    def temp_dir(self) -> Path:
        return self.userdata_dir / "tmp"

    @property
    def logs_dir(self) -> Path:
        return self.userdata_dir / "logs"

    @property
    def task_logs_dir(self) -> Path:
        return self.userdata_dir / "task_logs"

    @property
    def home_dir(self) -> Path:
        return self.userdata_dir / "home"

    @property
    def backups_dir(self) -> Path:
        return self.userdata_dir / "backups"

    @property
    def indexes_dir(self) -> Path:
        return self.userdata_dir / "indexes"

    @property
    def exports_dir(self) -> Path:
        return self.temp_dir / "exports"

    @property
    def covers_dir(self) -> Path:
        return self.cache_dir / "covers"

    @property
    def compatible_dir(self) -> Path:
        return self.cache_dir / "compatible"

    @property
    def dotnet_bundle_dir(self) -> Path:
        return self.cache_dir / "dotnet"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def runtime_env_file(self) -> Path:
        return self.config_dir / "runtime.env"

    @property
    def tags_file(self) -> Path:
        return self.config_dir / "tags.json"

    @property
    def database_file(self) -> Path:
        return self.userdata_dir / "bili_workspace.db"

    @property
    def export_config_file(self) -> Path:
        return self.userdata_dir / "export_runtime.json"

    @property
    def bootstrap_token_file(self) -> Path:
        return self.config_dir / "bootstrap-token.txt"

    @property
    def bbdown_credentials_file(self) -> Path:
        return self.bbdown_data_dir / "BBDown.data"

    @property
    def backend_log_file(self) -> Path:
        return self.logs_dir / "backend.log"


class DataRootManager:
    """验证并初始化用户明确选择的仓库外数据根。"""

    def __init__(self, paths: AppPaths, template_dir: Path | None = None) -> None:
        self.paths = paths
        self.template_dir = (template_dir or defaults_dir()).resolve()

    def resolve_layout(self, candidate: Path) -> DataRootLayout:
        """创建并解析数据根本身，不写入其内部结构或配置。"""

        raw = Path(candidate).expanduser()
        if _path_exists(raw) and (
            raw.is_symlink() or _is_reparse_point(raw) or not raw.is_dir()
        ):
            raise DataRootError(f"数据根必须是普通目录：{raw}")
        preview = raw.resolve(strict=False)
        if _overlaps(preview, self.paths.base_dir):
            raise DataRootError("数据根不能与 EXE 控制根重叠")
        preview_boundary = _git_boundary(preview)
        if preview_boundary is not None:
            raise DataRootError(f"数据根不能位于 Git 工作树内：{preview_boundary}")
        try:
            raw.mkdir(parents=True, exist_ok=True)
            root = raw.resolve(strict=True)
        except OSError as exc:
            raise DataRootError(f"无法创建或解析数据根：{raw}") from exc
        if _overlaps(root, self.paths.base_dir):
            raise DataRootError("数据根不能与 EXE 控制根重叠")
        boundary = _git_boundary(root)
        if boundary is not None:
            raise DataRootError(f"数据根不能位于 Git 工作树内：{boundary}")
        return DataRootLayout(root)

    def prepare(self, candidate: Path) -> DataRootLayout:
        return self._prepare_layout(self.resolve_layout(candidate))

    def prepare_locked(
        self,
        candidate: Path,
        data_lock: DataRootLock,
    ) -> DataRootLayout:
        """仅在调用方已持有同一数据根锁时初始化可写内容。"""

        layout = self.resolve_layout(candidate)
        if (
            not data_lock.acquired
            or data_lock.layout.root.resolve() != layout.root.resolve()
        ):
            raise DataRootLockError("调用方未持有当前数据根的独占锁")
        return self._prepare_layout(layout)

    def _prepare_layout(self, layout: DataRootLayout) -> DataRootLayout:
        root = layout.root
        self._verify_or_create_directories(layout, create=False)
        self._verify_marker(layout, create=False)
        for fixed_file in (
            layout.lock_file,
            layout.config_file,
            layout.config_file.with_suffix(layout.config_file.suffix + ".bak"),
            layout.runtime_env_file,
            layout.runtime_env_file.with_suffix(layout.runtime_env_file.suffix + ".bak"),
            layout.tags_file,
            layout.tags_file.with_suffix(layout.tags_file.suffix + ".bak"),
            layout.database_file,
            layout.database_file.with_name(layout.database_file.name + "-journal"),
            layout.database_file.with_name(layout.database_file.name + "-shm"),
            layout.database_file.with_name(layout.database_file.name + "-wal"),
            layout.export_config_file,
            layout.export_config_file.with_suffix(layout.export_config_file.suffix + ".bak"),
            layout.indexes_dir / "library.json",
            layout.indexes_dir / "library.json.bak",
            layout.indexes_dir / "exports.json",
            layout.indexes_dir / "exports.json.bak",
            layout.bootstrap_token_file,
            layout.bbdown_credentials_file,
            layout.backend_log_file,
            layout.backend_log_file.with_name(layout.backend_log_file.name + ".1"),
            layout.backend_log_file.with_name(layout.backend_log_file.name + ".2"),
            layout.backend_log_file.with_name(layout.backend_log_file.name + ".3"),
        ):
            if not _regular_file_or_missing(fixed_file):
                raise DataRootError(f"固定数据文件类型无效：{fixed_file}")
        self._preflight_json_configs(layout)
        self._verify_writable(root)
        self._verify_or_create_directories(layout, create=True)
        self._verify_marker(layout, create=True)
        try:
            ensure_json_from_default(self.template_dir / "config.json.default", layout.config_file)
            ensure_env_from_default(self.template_dir / "runtime.env.default", layout.runtime_env_file)
            ensure_json_from_default(self.template_dir / "tags.json.default", layout.tags_file)
        except (OSError, ValueError) as exc:
            raise DataRootError(f"数据根配置无效：{exc}") from exc
        return layout

    def _preflight_json_configs(self, layout: DataRootLayout) -> None:
        specifications = (
            (
                self.template_dir / "config.json.default",
                layout.config_file,
                "config_schema_version",
                "主配置",
            ),
            (
                self.template_dir / "tags.json.default",
                layout.tags_file,
                "palette_version",
                "标签配置",
            ),
        )
        for default_path, actual_path, version_key, label in specifications:
            try:
                if default_path.stat().st_size > _MAX_DATA_CONFIG_BYTES or (
                    actual_path.exists()
                    and actual_path.stat().st_size > _MAX_DATA_CONFIG_BYTES
                ):
                    raise DataRootError(f"{label}超过大小上限")
                default_raw = json.loads(default_path.read_text(encoding="utf-8"))
                actual_raw = (
                    json.loads(actual_path.read_text(encoding="utf-8"))
                    if actual_path.exists()
                    else None
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DataRootError(f"{label} JSON 无效，拒绝修改数据根") from exc
            if not isinstance(default_raw, dict) or (
                actual_raw is not None and not isinstance(actual_raw, dict)
            ):
                raise DataRootError(f"{label}顶层必须是 JSON object")
            expected_version = default_raw.get(version_key)
            if isinstance(expected_version, bool) or not isinstance(expected_version, int):
                raise DataRootError(f"{label}默认模板缺少有效 {version_key}")
            if actual_raw is None or version_key not in actual_raw:
                continue
            actual_version = actual_raw[version_key]
            if (
                isinstance(actual_version, bool)
                or not isinstance(actual_version, int)
                or actual_version < 1
                or actual_version > expected_version
            ):
                raise DataRootError(f"{label} {version_key} 不受支持")

    def _verify_or_create_directories(
        self, layout: DataRootLayout, *, create: bool
    ) -> None:
        for directory in (
            layout.config_dir,
            layout.userdata_dir,
            layout.downloads_dir,
            layout.bbdown_data_dir,
            layout.cache_dir,
            layout.temp_dir,
            layout.logs_dir,
            layout.task_logs_dir,
            layout.home_dir,
            layout.backups_dir,
            layout.indexes_dir,
            layout.exports_dir,
            layout.covers_dir,
            layout.compatible_dir,
            layout.dotnet_bundle_dir,
        ):
            if _path_exists(directory) and (
                not directory.is_dir() or directory.is_symlink() or _is_reparse_point(directory)
            ):
                raise DataRootError(f"固定数据目录类型无效：{directory}")
            if not create and not _path_exists(directory):
                continue
            try:
                directory.mkdir(parents=True, exist_ok=True)
                resolved = directory.resolve(strict=True)
            except OSError as exc:
                raise DataRootError(f"无法创建或解析固定数据目录：{directory}") from exc
            if not _is_within(resolved, layout.root):
                raise DataRootError(f"固定数据目录逃出数据根：{directory}")

    @staticmethod
    def _verify_marker(layout: DataRootLayout, *, create: bool) -> None:
        marker = layout.marker_file
        if not _regular_file_or_missing(marker):
            raise DataRootError(f"数据根标记类型无效：{marker}")
        if _path_exists(marker):
            try:
                if marker.stat().st_size > _MAX_MARKER_BYTES:
                    raise DataRootError("数据根标记超过大小上限")
                raw = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DataRootError("数据根标记损坏，拒绝覆盖") from exc
            if (
                not isinstance(raw, dict)
                or set(raw) != {"schema_version", "product", "created_at"}
                or isinstance(raw.get("schema_version"), bool)
                or raw.get("schema_version") != 1
                or isinstance(raw.get("created_at"), bool)
                or not isinstance(raw.get("created_at"), int)
                or raw["created_at"] < 0
            ):
                raise DataRootError("数据根标记 schema 不受支持")
            if raw.get("product") != "bili_workspace":
                raise DataRootError("所选目录属于其他产品")
            return
        if not create:
            return
        atomic_write_json(
            marker,
            {
                "schema_version": 1,
                "product": "bili_workspace",
                "created_at": int(time.time()),
            },
            backup=False,
        )

    @staticmethod
    def _verify_writable(root: Path) -> None:
        probe: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=".bili-write-", dir=root)
            probe = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"ok")
                stream.flush()
                os.fsync(stream.fileno())
            probe.unlink()
            probe = None
        except OSError as exc:
            if probe is not None:
                try:
                    probe.unlink(missing_ok=True)
                except OSError:
                    pass
            raise DataRootError(f"数据根不可写：{root}") from exc


class DataRootLock:
    """用操作系统文件锁保证同一数据根只有一个启动器拥有者。"""

    def __init__(self, layout: DataRootLayout) -> None:
        self.layout = layout
        self.token = uuid.uuid4().hex
        self._stream: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        return self._stream is not None

    def acquire(self) -> None:
        if self.acquired:
            return
        if (
            not self.layout.root.is_dir()
            or self.layout.root.is_symlink()
            or _is_reparse_point(self.layout.root)
        ):
            raise DataRootLockError(f"数据根锁目录类型无效：{self.layout.root}")
        lock_file = self.layout.lock_file
        if not _regular_file_or_missing(lock_file):
            raise DataRootLockError(f"数据根锁文件必须是普通文件：{lock_file}")
        stream = lock_file.open("a+b")
        try:
            if os.name == "nt":
                # Windows byte-range locking requires the target byte to exist.
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
            self._lock_stream(stream)
        except OSError as exc:
            try:
                stream.seek(0)
                owner = stream.read(2048).decode("utf-8", errors="replace").strip()
            except OSError:
                owner = ""
            stream.close()
            detail = f"；当前记录：{owner}" if owner else ""
            raise DataRootLockError("该数据根正由另一份启动器使用" + detail) from exc
        try:
            payload = json.dumps(
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "acquired_at": int(time.time()),
                    "token": self.token,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            stream.seek(0)
            stream.truncate()
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        except OSError as exc:
            try:
                self._unlock_stream(stream)
            except OSError:
                pass
            stream.close()
            raise DataRootLockError("无法写入数据根锁所有权记录") from exc
        self._stream = stream

    @staticmethod
    def _lock_stream(stream: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_stream(stream: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        try:
            self._unlock_stream(stream)
        finally:
            stream.close()

    def __enter__(self) -> "DataRootLock":
        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()
