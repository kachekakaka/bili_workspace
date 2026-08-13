"""launcher.json 与数据根网络安全配置的严格解析和持久化。"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.io_utils import atomic_write_text

from .constants import DEFAULT_BACKEND_HOST, DEFAULT_BACKEND_PORT
from .paths import AppPaths, _is_reparse_point, _path_exists

_ENV_ASSIGNMENT_RE = re.compile(r"^(?P<prefix>\s*(?:export\s+)?)"
                                r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
_MAX_SETTINGS_BYTES = 1024 * 1024
_MAX_PATH_CHARACTERS = 32_767


class SettingsError(ValueError):
    """启动器控制设置或网络安全设置无效。"""


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class LauncherSettings:
    schema_version: int
    data_root: str
    recent_export_dir: str = ""

    @classmethod
    def create(cls, data_root: Path, recent_export_dir: str = "") -> "LauncherSettings":
        return cls(1, str(Path(data_root).resolve()), recent_export_dir)

    @classmethod
    def from_mapping(cls, raw: object) -> "LauncherSettings":
        if not isinstance(raw, dict):
            raise SettingsError("launcher.json 必须是 JSON object")
        allowed = {"schema_version", "data_root", "recent_export_dir"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise SettingsError("launcher.json 包含未知字段：" + ", ".join(unknown))
        if isinstance(raw.get("schema_version"), bool) or raw.get("schema_version") != 1:
            raise SettingsError("launcher.json schema_version 不受支持")
        data_root = raw.get("data_root")
        recent = raw.get("recent_export_dir", "")
        if not isinstance(data_root, str) or not data_root.strip():
            raise SettingsError("data_root 必须是非空字符串")
        if not isinstance(recent, str):
            raise SettingsError("recent_export_dir 必须是字符串")
        data_root = data_root.strip()
        recent = recent.strip()
        if (
            len(data_root) > _MAX_PATH_CHARACTERS
            or "\0" in data_root
            or not Path(data_root).is_absolute()
        ):
            raise SettingsError("data_root 必须是有效绝对路径")
        if recent and (
            len(recent) > _MAX_PATH_CHARACTERS
            or "\0" in recent
            or not Path(recent).is_absolute()
        ):
            raise SettingsError("recent_export_dir 必须为空或有效绝对路径")
        return cls(1, data_root, recent)


class SettingsStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    @property
    def exists(self) -> bool:
        path = self.paths.settings_file
        return path.is_file() and not path.is_symlink() and not _is_reparse_point(path)

    def load(self) -> LauncherSettings | None:
        if not _path_exists(self.paths.settings_file):
            return None
        if not self.exists:
            raise SettingsError("launcher.json 必须是普通文件")
        try:
            if self.paths.settings_file.stat().st_size > _MAX_SETTINGS_BYTES:
                raise SettingsError("launcher.json 超过大小上限")
            raw = json.loads(self.paths.settings_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SettingsError("无法读取 launcher.json") from exc
        return LauncherSettings.from_mapping(raw)

    def save(self, settings: LauncherSettings) -> None:
        if _path_exists(self.paths.settings_file) and not self.exists:
            raise SettingsError("launcher.json 必须是普通文件")
        validated = LauncherSettings.from_mapping(asdict(settings))
        _atomic_text(
            self.paths.settings_file,
            json.dumps(asdict(validated), ensure_ascii=False, indent=2) + "\n",
        )


def _bool_value(name: str, raw: str, default: bool) -> bool:
    value = raw.strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} 必须是布尔值")


def _valid_bind_host(value: str) -> bool:
    host = value.strip()
    if not host or any(character.isspace() for character in host):
        return False
    if host.lower() == "localhost":
        return True
    if host.startswith("[") or host.endswith("]"):
        if not (host.startswith("[") and host.endswith("]")):
            return False
        try:
            return ipaddress.ip_address(host[1:-1]).version == 6
        except ValueError:
            return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        normalized = host.rstrip(".")
        labels = normalized.split(".")
        return bool(normalized) and len(normalized) <= 253 and all(
            1 <= len(label) <= 63
            and label[0].isascii()
            and label[0].isalnum()
            and label[-1].isascii()
            and label[-1].isalnum()
            and all(
                character.isascii() and (character.isalnum() or character == "-")
                for character in label
            )
            for label in labels
        )


def _normalize_bind_host(value: str) -> str:
    host = value.strip()
    try:
        if host.startswith("[") and host.endswith("]"):
            return str(ipaddress.ip_address(host[1:-1]))
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host.rstrip(".").lower()


def _normalize_trusted_host(value: str) -> str:
    host = value.strip()
    if not host or any(character.isspace() for character in host) or "*" in host:
        raise SettingsError("可信 Host 必须是显式主机名或 IP，且禁止通配符")
    if host.startswith("[") or host.endswith("]"):
        if not (host.startswith("[") and host.endswith("]")):
            raise SettingsError(f"可信 Host 无效：{value}")
        try:
            address = ipaddress.ip_address(host[1:-1])
        except ValueError as exc:
            raise SettingsError(f"可信 Host 无效：{value}") from exc
        if address.version != 6:
            raise SettingsError(f"可信 Host 无效：{value}")
        return f"[{address.compressed}]"
    try:
        address = ipaddress.ip_address(host)
        return f"[{address.compressed}]" if address.version == 6 else str(address)
    except ValueError:
        normalized = host.rstrip(".").lower()
        labels = normalized.split(".")
        if (
            not normalized
            or len(normalized) > 253
            or not all(
                1 <= len(label) <= 63
                and label[0].isascii()
                and label[0].isalnum()
                and label[-1].isascii()
                and label[-1].isalnum()
                and all(
                    character.isascii() and (character.isalnum() or character == "-")
                    for character in label
                )
                for label in labels
            )
        ):
            raise SettingsError(f"可信 Host 无效：{value}")
        return normalized


def _host_key(value: str) -> str:
    return value.strip().strip("[]").rstrip(".").lower()


def _loopback(value: str) -> bool:
    raw = value.strip().lower().strip("[]")
    if raw == "localhost":
        return True
    try:
        return ipaddress.ip_address(raw).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class NetworkSettings:
    mode: str = "local"
    host: str = DEFAULT_BACKEND_HOST
    port: int = DEFAULT_BACKEND_PORT
    trusted_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver")
    trusted_proxy_ips: tuple[str, ...] = ("127.0.0.1",)
    public_base_url: str = ""
    allow_ip_hosts: bool = False
    cookie_secure: bool = False
    hsts_enabled: bool = False

    def validated(self) -> "NetworkSettings":
        if not isinstance(self.mode, str):
            raise SettingsError("运行模式必须是字符串")
        if not isinstance(self.host, str):
            raise SettingsError("监听地址必须是字符串")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise SettingsError("端口必须是 1-65535 的整数")
        if not isinstance(self.trusted_hosts, tuple) or not all(
            isinstance(item, str) for item in self.trusted_hosts
        ):
            raise SettingsError("可信 Host 必须是字符串列表")
        if not isinstance(self.trusted_proxy_ips, tuple) or not all(
            isinstance(item, str) for item in self.trusted_proxy_ips
        ):
            raise SettingsError("可信代理必须是字符串列表")
        if not isinstance(self.public_base_url, str):
            raise SettingsError("公开 URL 必须是字符串")
        if not all(
            isinstance(value, bool)
            for value in (self.allow_ip_hosts, self.cookie_secure, self.hsts_enabled)
        ):
            raise SettingsError("网络安全开关必须是布尔值")
        mode = self.mode.strip().lower()
        if mode not in {"local", "server"}:
            raise SettingsError("运行模式只支持 local/server")
        raw_host = self.host.strip()
        if not _valid_bind_host(raw_host):
            raise SettingsError("监听地址无效")
        host = _normalize_bind_host(raw_host)
        if mode == "local" and not _loopback(host):
            raise SettingsError("本机模式必须监听回环地址")
        if mode == "server" and _loopback(host):
            raise SettingsError("局域网服务器模式不能只监听回环地址")
        if not 1 <= self.port <= 65535:
            raise SettingsError("端口必须是 1-65535 的整数")
        trusted_hosts = tuple(
            dict.fromkeys(_normalize_trusted_host(item) for item in self.trusted_hosts if item.strip())
        )
        if not trusted_hosts:
            raise SettingsError("可信 Host 必须显式列出且禁止通配符")
        if mode == "local" and not any(_loopback(item) for item in trusted_hosts):
            raise SettingsError("本机模式的可信 Host 必须包含回环地址或 localhost")
        if mode == "local" and self.allow_ip_hosts:
            raise SettingsError("本机模式不能启用任意 IP Host")
        raw_proxies = tuple(item.strip() for item in self.trusted_proxy_ips if item.strip())
        if not raw_proxies or any("*" in item for item in raw_proxies):
            raise SettingsError("可信代理必须显式列出且禁止通配符")
        proxies_list: list[str] = []
        for proxy in raw_proxies:
            try:
                proxy_network = ipaddress.ip_network(proxy, strict=False)
            except ValueError as exc:
                raise SettingsError(f"可信代理地址无效：{proxy}") from exc
            if proxy_network.prefixlen == 0:
                raise SettingsError("可信代理禁止使用覆盖全部地址的 CIDR")
            normalized_proxy = str(proxy_network)
            if normalized_proxy not in proxies_list:
                proxies_list.append(normalized_proxy)
        proxies = tuple(proxies_list)
        public = self.public_base_url.strip().rstrip("/")
        public_host = ""
        public_scheme = ""
        if public:
            try:
                parsed = urlparse(public)
                parsed_host = parsed.hostname
                parsed_port = parsed.port
            except ValueError as exc:
                raise SettingsError("公开 URL 无效") from exc
            public_scheme = parsed.scheme.lower()
            if (
                public_scheme not in {"http", "https"}
                or not parsed_host
                or parsed.username
                or parsed.password
                or parsed.netloc.endswith(":")
                or parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise SettingsError("公开 URL 必须是无凭据、无子路径的完整 http/https 地址")
            normalized_public_host = _normalize_trusted_host(parsed_host)
            public_host = _host_key(normalized_public_host)
            port_suffix = f":{parsed_port}" if parsed_port is not None else ""
            public = f"{public_scheme}://{normalized_public_host}{port_suffix}"
        if public_host and public_host not in {_host_key(item) for item in trusted_hosts}:
            raise SettingsError("公开 URL 域名必须包含在可信 Host 中")
        if public_scheme == "https" and not self.cookie_secure:
            raise SettingsError("HTTPS 公开 URL 必须开启 Secure Cookie")
        if self.hsts_enabled and (not self.cookie_secure or public_scheme != "https"):
            raise SettingsError("HSTS 只能在 HTTPS 与 Secure Cookie 同时启用时开启")
        return NetworkSettings(
            mode=mode,
            host=host,
            port=self.port,
            trusted_hosts=trusted_hosts,
            trusted_proxy_ips=proxies,
            public_base_url=public,
            allow_ip_hosts=self.allow_ip_hosts,
            cookie_secure=self.cookie_secure,
            hsts_enabled=self.hsts_enabled,
        )

    def environment(self) -> dict[str, str]:
        value = self.validated()
        return {
            "BILI_APP_MODE": value.mode,
            "BILI_HOST": value.host,
            "BILI_PORT": str(value.port),
            "BILI_TRUSTED_HOSTS": ",".join(value.trusted_hosts),
            "BILI_TRUSTED_PROXY_IPS": ",".join(value.trusted_proxy_ips),
            "BILI_PUBLIC_BASE_URL": value.public_base_url,
            "BILI_ALLOW_IP_HOSTS": "true" if value.allow_ip_hosts else "false",
            "BILI_COOKIE_SECURE": "true" if value.cookie_secure else "false",
            "BILI_HSTS": "true" if value.hsts_enabled else "false",
        }


class RuntimeEnvStore:
    _KEYS = tuple(NetworkSettings().environment())

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> tuple[str, dict[str, str]]:
        if (
            self.path.is_symlink()
            or _is_reparse_point(self.path)
            or (_path_exists(self.path) and not self.path.is_file())
        ):
            raise SettingsError("runtime.env 必须是普通文件")
        try:
            if self.path.stat().st_size > _MAX_SETTINGS_BYTES:
                raise SettingsError("runtime.env 超过大小上限")
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SettingsError("无法读取 runtime.env") from exc
        values: dict[str, str] = {}
        for line in text.splitlines():
            match = _ENV_ASSIGNMENT_RE.match(line)
            if not match:
                continue
            key = match.group("key")
            if key in values:
                raise SettingsError(f"runtime.env 包含重复键：{key}")
            values[key] = match.group("value").strip()
        return text, values

    def load(self) -> NetworkSettings:
        _text, values = self._read()
        raw_mode = values.get("BILI_APP_MODE", "local").strip().lower() or "local"
        host = values.get("BILI_HOST", "").strip()
        if raw_mode == "auto":
            mode = "local" if not host or _loopback(host) else "server"
        elif raw_mode in {"nas", "docker"}:
            mode = "server"
        else:
            mode = raw_mode
        if not host:
            host = DEFAULT_BACKEND_HOST if mode == "local" else "0.0.0.0"
        raw_port = values.get("BILI_PORT", "").strip()
        try:
            port = int(raw_port) if raw_port else DEFAULT_BACKEND_PORT
        except ValueError as exc:
            raise SettingsError("BILI_PORT 必须是整数") from exc
        hosts = tuple(item.strip() for item in values.get(
            "BILI_TRUSTED_HOSTS", "127.0.0.1,localhost,testserver"
        ).split(",") if item.strip())
        proxies = tuple(item.strip() for item in values.get(
            "BILI_TRUSTED_PROXY_IPS", "127.0.0.1"
        ).split(",") if item.strip())
        public = values.get("BILI_PUBLIC_BASE_URL", "").strip()
        secure_default = public.startswith("https://")
        settings = NetworkSettings(
            mode=mode,
            host=host,
            port=port,
            trusted_hosts=hosts,
            trusted_proxy_ips=proxies,
            public_base_url=public,
            allow_ip_hosts=_bool_value(
                "BILI_ALLOW_IP_HOSTS", values.get("BILI_ALLOW_IP_HOSTS", ""), mode == "server"
            ),
            cookie_secure=_bool_value(
                "BILI_COOKIE_SECURE", values.get("BILI_COOKIE_SECURE", ""), secure_default
            ),
            hsts_enabled=_bool_value(
                "BILI_HSTS", values.get("BILI_HSTS", ""), secure_default
            ),
        )
        return settings.validated()

    def save(self, settings: NetworkSettings) -> None:
        text, _values = self._read()
        updates = settings.validated().environment()
        seen: set[str] = set()
        lines: list[str] = []
        for line in text.splitlines():
            match = _ENV_ASSIGNMENT_RE.match(line)
            key = match.group("key") if match else ""
            if key in updates:
                if key in seen:
                    raise SettingsError(f"runtime.env 包含重复键：{key}")
                lines.append(f"{match.group('prefix')}{key}={updates[key]}")
                seen.add(key)
            else:
                lines.append(line)
        missing = [key for key in self._KEYS if key not in seen]
        if missing:
            if lines and lines[-1]:
                lines.append("")
            lines.append("# Managed by bili_workspace launcher.")
            lines.extend(f"{key}={updates[key]}" for key in missing)
        atomic_write_text(self.path, "\n".join(lines) + "\n", backup=True)
