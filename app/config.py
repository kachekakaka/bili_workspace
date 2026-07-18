from __future__ import annotations

import ipaddress
import json
import os
import shutil
import threading
import warnings
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from app.config_files import ensure_json_from_default
from app.grouping import DEFAULT_GROUP, normalize_group
from app.io_utils import atomic_write_json
from app.quality import DEFAULT_MIN_HEIGHT, validate_min_height
from app.paths import ROOT, resolve_path

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 3398,
    "download_dir": "downloads",
    "bbdown_dir": "BBDown_portable",
    "poll_hint_ms": 1500,
    "download_timeout_sec": 3600,
    "dfn_priority": "",
    "encoding_priority": "",
    "default_group": DEFAULT_GROUP,
    "default_min_height": DEFAULT_MIN_HEIGHT,
}

# Executable location and bind address are startup trust decisions, not web-editable settings.
WEB_EDITABLE_FIELDS = frozenset(
    {
        "port",
        "download_dir",
        "poll_hint_ms",
        "download_timeout_sec",
        "dfn_priority",
        "encoding_priority",
        "default_group",
        "default_min_height",
    }
)


@dataclass
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 3398
    download_dir: str = "downloads"
    bbdown_dir: str = "BBDown_portable"
    poll_hint_ms: int = 1500
    download_timeout_sec: int = 3600
    dfn_priority: str = ""
    encoding_priority: str = ""
    default_group: str = DEFAULT_GROUP
    default_min_height: int = DEFAULT_MIN_HEIGHT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def download_path(self) -> Path:
        return resolve_path(self.download_dir)

    def bbdown_path(self) -> Path:
        return resolve_path(self.bbdown_dir)


_KNOWN_FIELDS = tuple(field.name for field in fields(AppConfig))


def _is_loopback_host(value: str) -> bool:
    host = value.strip().lower()
    if host == "localhost":
        return True
    host = host.strip("[]")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _has_ffmpeg(bbdown: Path) -> bool:
    candidates = (
        bbdown / "ffmpeg" / "bin" / "ffmpeg.exe",
        bbdown / "ffmpeg" / "bin" / "ffmpeg",
        bbdown / "ffmpeg.exe",
        bbdown / "ffmpeg",
    )
    if any(_regular(path) for path in candidates):
        return True
    if any(_regular(path) for pattern in ("ffmpeg-*/bin/ffmpeg.exe", "ffmpeg-*/bin/ffmpeg") for path in bbdown.glob(pattern)):
        return True
    return shutil.which("ffmpeg") is not None


def _has_bbdown(bbdown: Path) -> bool:
    return any(_regular(bbdown / name) for name in ("BBDown.exe", "BBDown", "bbdown"))


class ConfigStore:
    """Thread-safe, validated configuration with template upgrades and atomic persistence."""

    def __init__(
        self,
        path: Path | None = None,
        initial: dict[str, Any] | None = None,
        startup_overrides: dict[str, Any] | None = None,
        default_path: Path | None = None,
        server_mode: bool | None = None,
    ):
        self.path = path or (ROOT / "config" / "config.json")
        self.default_path = default_path or (ROOT / "config" / "config.json.default")
        self.server_mode = (
            os.getenv("BILI_APP_MODE", "local").strip().lower() in {"server", "nas", "docker"}
            if server_mode is None
            else bool(server_mode)
        )
        self._startup_overrides = dict(startup_overrides or {})
        self._lock = threading.RLock()
        self._boot_host: str | None = None
        self._boot_port: int | None = None

        if initial is not None:
            data = self._normalize({**initial, **self._startup_overrides})
            self._validate(data)
            self._data = data
        else:
            try:
                ensure_json_from_default(self.default_path, self.path)
            except ValueError as exc:
                backup = self.path.with_suffix(self.path.suffix + ".bak")
                recoverable = backup.is_file() and (
                    "实际配置 JSON 无效" in str(exc)
                    or "实际配置 顶层必须是 JSON 对象" in str(exc)
                )
                if not recoverable:
                    raise
            self._data = self._load_existing()
        self.mark_boot()

    @staticmethod
    def _app_data(data: dict[str, Any]) -> dict[str, Any]:
        return {name: data[name] for name in _KNOWN_FIELDS}

    def _load_existing(self) -> dict[str, Any]:
        candidates = [self.path, self.path.with_suffix(self.path.suffix + ".bak")]
        errors: list[str] = []
        for index, candidate in enumerate(candidates):
            if not candidate.exists():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("顶层必须是 JSON 对象")
                data = self._normalize({**raw, **self._startup_overrides})
                self._validate(data)
                if index == 1:
                    warnings.warn(f"主配置损坏，已从备份恢复: {candidate}", RuntimeWarning)
                    atomic_write_json(self.path, data, backup=False)
                elif data != raw:
                    # Persist type normalization and trusted startup overrides.
                    atomic_write_json(self.path, data, backup=True)
                return data
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.append(f"{candidate}: {exc}")
        joined = "; ".join(errors) or "没有可读取的配置文件"
        raise ValueError(f"配置文件无效，拒绝启动: {joined}")

    def mark_boot(self) -> None:
        with self._lock:
            self._boot_host = str(self._data["host"])
            self._boot_port = int(self._data["port"])

    def get(self) -> AppConfig:
        with self._lock:
            return AppConfig(**self._app_data(self._data))

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.path, self._data, backup=True)

    def update(self, patch: dict[str, Any]) -> tuple[AppConfig, bool]:
        """Apply a web-safe patch. Returns (config, restart_required)."""
        with self._lock:
            forbidden = sorted(set(patch) - WEB_EDITABLE_FIELDS)
            if forbidden:
                raise ValueError(f"配置项不可通过网页修改: {', '.join(forbidden)}")
            merged = dict(self._data)
            merged.update(patch)
            normalized = self._normalize(merged)
            self._validate(normalized)
            restart = int(normalized["port"]) != self._boot_port
            self._data = normalized
            self.save()
            return self.get(), restart

    def apply_startup_overrides(self, patch: dict[str, Any]) -> AppConfig:
        """Apply trusted process/environment settings before serving requests."""
        with self._lock:
            merged = dict(self._data)
            merged.update(patch)
            normalized = self._normalize(merged)
            self._validate(normalized)
            changed = normalized != self._data
            self._data = normalized
            if changed:
                self.save()
            self.mark_boot()
            return self.get()

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        # Preserve unknown/newer keys so upgrades never discard user data.
        data = deepcopy(raw)
        for name, value in DEFAULTS.items():
            if name not in data or data[name] is None:
                data[name] = value
        data["port"] = int(data["port"])
        data["poll_hint_ms"] = int(data["poll_hint_ms"])
        data["download_timeout_sec"] = int(data["download_timeout_sec"])
        data["default_min_height"] = int(data.get("default_min_height", DEFAULT_MIN_HEIGHT))
        data["host"] = str(data["host"]).strip() or "127.0.0.1"
        data["download_dir"] = str(data["download_dir"]).strip() or "downloads"
        data["bbdown_dir"] = str(data["bbdown_dir"]).strip() or "BBDown_portable"
        data["dfn_priority"] = str(data.get("dfn_priority") or "").strip()
        data["encoding_priority"] = str(data.get("encoding_priority") or "").strip()
        data["default_group"] = normalize_group(
            str(data.get("default_group") or DEFAULT_GROUP), default=DEFAULT_GROUP
        ).display
        return data

    def _validate(self, data: dict[str, Any]) -> None:
        if not self.server_mode and not _is_loopback_host(str(data["host"])):
            # A non-loopback bind is automatically treated as server mode so
            # LAN access never accidentally runs without administrator auth.
            self.server_mode = True
        if self.server_mode and str(data["host"]).strip() not in {"0.0.0.0", "::", "[::]"}:
            host = str(data["host"]).strip("[]")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                # Uvicorn also accepts a local interface hostname. Keep domain
                # access controlled separately by the HTTP Host guard.
                if not host or any(char.isspace() for char in host):
                    raise ValueError("服务器模式 host 必须是 IP 地址或有效主机名")
        if not (1 <= int(data["port"]) <= 65535):
            raise ValueError("port 必须在 1–65535")
        if not (200 <= int(data["poll_hint_ms"]) <= 60_000):
            raise ValueError("poll_hint_ms 必须在 200–60000")
        if not (30 <= int(data["download_timeout_sec"]) <= 86_400):
            raise ValueError("download_timeout_sec 必须在 30–86400")
        validate_min_height(int(data["default_min_height"]), default=DEFAULT_MIN_HEIGHT)
        normalize_group(str(data["default_group"]), default=DEFAULT_GROUP)

        download = resolve_path(data["download_dir"])
        if download.exists() and not download.is_dir():
            raise ValueError(f"download_dir 不是目录: {download}")

        bbdown = resolve_path(data["bbdown_dir"])
        if not bbdown.is_dir() or bbdown.is_symlink():
            raise ValueError(f"bbdown_dir 无效: {bbdown}")
        # The source repository intentionally omits third-party binaries.
        # Their absence is reported by /api/status and download operations,
        # but it must not prevent configuration upgrades or media-library use.
