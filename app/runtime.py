from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.config_files import ensure_env_from_default, load_env_file
from app.paths import ROOT


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum}–{maximum}")
    return value


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum}–{maximum}")
    return value


def _path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default.resolve()


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.getenv(name, default).split(",") if part.strip())


def _is_loopback_host(value: str) -> bool:
    host = value.strip().lower().strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _valid_bind_host(value: str) -> bool:
    host = value.strip()
    if not host or any(char.isspace() for char in host):
        return False
    if host.lower() == "localhost":
        return True
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        normalized = host.rstrip(".")
        if not normalized or len(normalized) > 253:
            return False
        labels = normalized.split(".")
        return all(
            1 <= len(label) <= 63
            and label[0].isalnum()
            and label[-1].isalnum()
            and all(char.isalnum() or char == "-" for char in label)
            for label in labels
        )


def _prepare_env_files() -> None:
    """Materialize tracked defaults while preserving user-owned runtime files."""
    # A system service or Docker Compose may already provide BILI_APP_MODE. In
    # that case the process environment is authoritative and no project-root
    # .env is required inside the immutable image.
    if "BILI_APP_MODE" not in os.environ:
        ensure_env_from_default(ROOT / ".env.default", ROOT / ".env")
        load_env_file(ROOT / ".env")

    preliminary_mode = os.getenv("BILI_APP_MODE", "auto").strip().lower() or "auto"
    containerized = preliminary_mode in {"nas", "docker"}
    default_config_dir = Path("/data/config") if containerized else ROOT / "config"
    config_dir = _path("BILI_CONFIG_DIR", default_config_dir)
    runtime_default = ROOT / "config" / "runtime.env.default"
    runtime_actual = config_dir / "runtime.env"
    ensure_env_from_default(runtime_default, runtime_actual)
    # Explicit environment values (Compose/service manager) always win.
    load_env_file(runtime_actual, override=False)


@dataclass(frozen=True)
class RuntimeSettings:
    mode: str
    config_dir: Path
    media_dir: Path
    cache_dir: Path
    temp_dir: Path
    database_path: Path
    bbdown_dir: Path
    host: str
    port: int
    public_base_url: str
    trusted_hosts: tuple[str, ...]
    trusted_proxy_ips: tuple[str, ...]
    allow_ip_hosts: bool
    auth_required: bool
    cookie_secure: bool
    hsts_enabled: bool
    export_ttl_sec: int
    min_free_bytes: int
    download_concurrency: int
    transcode_threads: int

    @property
    def server_mode(self) -> bool:
        return self.mode in {"server", "nas", "docker"}

    @property
    def userdata_dir(self) -> Path:
        """Root for persistent library, task and account data."""
        return self.database_path.parent

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        _prepare_env_files()

        requested_mode = os.getenv("BILI_APP_MODE", "auto").strip().lower() or "auto"
        if requested_mode not in {"auto", "local", "server", "nas", "docker"}:
            raise ValueError("BILI_APP_MODE 只支持 auto/local/server/nas/docker")

        default_host = "0.0.0.0" if requested_mode in {"server", "nas", "docker"} else "127.0.0.1"
        host = os.getenv("BILI_HOST", default_host).strip() or default_host
        if not _valid_bind_host(host):
            raise ValueError("BILI_HOST 必须是有效 IP 地址或主机名")
        if requested_mode == "auto":
            mode = "local" if _is_loopback_host(host) else "server"
        elif requested_mode == "local" and not _is_loopback_host(host):
            # Do not leave a LAN/public bind in the unauthenticated local mode.
            mode = "server"
        else:
            mode = requested_mode

        server = mode != "local"
        containerized = mode in {"nas", "docker"}
        data_root = Path("/data") if containerized else ROOT
        config_dir = _path("BILI_CONFIG_DIR", data_root / "config")
        userdata_dir = _path("BILI_USERDATA_DIR", data_root / "userdata")
        media_default = Path("/downloads") if containerized else ROOT / "downloads"
        media_dir = _path("BILI_MEDIA_DIR", media_default)
        cache_dir = _path("BILI_CACHE_DIR", userdata_dir / "cache")
        temp_dir = _path("BILI_TEMP_DIR", userdata_dir / "tmp")
        database_path = _path("BILI_DATABASE_PATH", userdata_dir / "bili_workspace.db")
        default_bbdown = config_dir / "bbdown" if containerized else ROOT / "BBDown_portable"
        bbdown_dir = _path("BILI_BBDOWN_DIR", default_bbdown)
        port = _int("BILI_PORT", 3398, 1, 65535)

        public = os.getenv("BILI_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if public:
            parsed = urlparse(public)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("BILI_PUBLIC_BASE_URL 必须是完整的 http/https 地址")
            if parsed.username or parsed.password:
                raise ValueError("BILI_PUBLIC_BASE_URL 不能包含用户名或密码")
            if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
                raise ValueError("BILI_PUBLIC_BASE_URL 仅支持独立域名，不支持子路径、查询参数或片段")

        default_hosts = ["127.0.0.1", "localhost", "[::1]", "testserver"]
        bind_host = host.strip("[]")
        try:
            ipaddress.ip_address(bind_host)
        except ValueError:
            pass
        if bind_host not in {"", "0.0.0.0", "::"} and bind_host not in default_hosts:
            default_hosts.append(bind_host)
        public_host = str(urlparse(public).hostname or "") if public else ""
        if public_host and public_host not in default_hosts:
            default_hosts.append(public_host)

        trusted_hosts = tuple(item for item in _csv("BILI_TRUSTED_HOSTS", ",".join(default_hosts)) if item != "*")
        if not trusted_hosts:
            raise ValueError("BILI_TRUSTED_HOSTS 必须包含明确域名，禁止只使用通配符")
        trusted_proxies = _csv("BILI_TRUSTED_PROXY_IPS", "127.0.0.1")
        if not trusted_proxies or any(item == "*" for item in trusted_proxies):
            raise ValueError("BILI_TRUSTED_PROXY_IPS 必须列出可信代理地址，禁止使用通配符")

        allow_ip_hosts = _bool("BILI_ALLOW_IP_HOSTS", server)
        requested_auth = _bool("BILI_AUTH_REQUIRED", server)
        auth_required = True if server else requested_auth
        cookie_secure = _bool("BILI_COOKIE_SECURE", bool(public.startswith("https://")))
        hsts_enabled = _bool("BILI_HSTS", cookie_secure and bool(public.startswith("https://")))
        if public_host and public_host not in trusted_hosts:
            raise ValueError("BILI_TRUSTED_HOSTS 必须包含 PUBLIC_BASE_URL 的域名")
        if public.startswith("https://") and not cookie_secure:
            raise ValueError("HTTPS 公网地址必须开启 BILI_COOKIE_SECURE")
        if hsts_enabled and (not cookie_secure or not public.startswith("https://")):
            raise ValueError("BILI_HSTS 只能在 HTTPS 和安全 Cookie 已启用时开启")

        ttl = _int("BILI_EXPORT_TTL_SEC", 24 * 3600, 300, 7 * 24 * 3600)
        min_free_gib = _float("BILI_MIN_FREE_GIB", 2.0 if server else 1.0, 0.0, 1024.0)
        download_concurrency = _int("BILI_DOWNLOAD_CONCURRENCY", 1, 1, 3)
        transcode_threads = _int("BILI_TRANSCODE_THREADS", 0, 0, 128)
        for directory in (
            config_dir,
            userdata_dir,
            media_dir,
            cache_dir,
            temp_dir,
            database_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        return cls(
            mode=mode,
            config_dir=config_dir,
            media_dir=media_dir,
            cache_dir=cache_dir,
            temp_dir=temp_dir,
            database_path=database_path,
            bbdown_dir=bbdown_dir,
            host=host,
            port=port,
            public_base_url=public,
            trusted_hosts=trusted_hosts,
            trusted_proxy_ips=trusted_proxies,
            allow_ip_hosts=allow_ip_hosts,
            auth_required=auth_required,
            cookie_secure=cookie_secure,
            hsts_enabled=hsts_enabled,
            export_ttl_sec=ttl,
            min_free_bytes=int(min_free_gib * 1024**3),
            download_concurrency=download_concurrency,
            transcode_threads=transcode_threads,
        )
