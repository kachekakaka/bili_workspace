from __future__ import annotations

import ipaddress
import os
import webbrowser
from pathlib import Path
from threading import Timer
from typing import Any

import uvicorn

from app.config_bootstrap import ensure_runtime_configs, load_json_config, runtime_config_dir


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _valid_port(raw: Any) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"端口必须是 1-65535 的整数，当前值: {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise SystemExit(f"端口必须是 1-65535，当前值: {port}")
    return port


def _is_loopback_bind(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _set_path_env(storage: dict[str, Any]) -> None:
    mappings = {
        "config_dir": "BILI_CONFIG_DIR",
        "media_dir": "BILI_MEDIA_DIR",
        "cache_dir": "BILI_CACHE_DIR",
        "temp_dir": "BILI_TEMP_DIR",
    }
    for key, env_name in mappings.items():
        configured = _env(env_name) or str(storage.get(key, "")).strip()
        if configured:
            os.environ[env_name] = str(Path(configured).expanduser().resolve())


def main() -> None:
    ensure_runtime_configs()
    server = load_json_config("server.json")
    listen = server.get("listen", {})
    access = server.get("access", {})
    storage = server.get("storage", {})
    if isinstance(storage, dict):
        _set_path_env(storage)

    docker = _bool(_env("BILI_DOCKER"), False)
    default_host = "0.0.0.0" if docker else str(listen.get("host", "127.0.0.1"))
    host = _env("BILI_HOST") or _env("HOST") or default_host
    port = _valid_port(_env("BILI_PORT") or _env("PORT") or listen.get("port", 3398))

    mode = (_env("APP_MODE") or str(access.get("mode", "local"))).lower()
    if not _is_loopback_bind(host):
        mode = "server"
        os.environ.setdefault("AUTH_REQUIRED", "true")
    os.environ["APP_MODE"] = mode
    os.environ["BILI_HOST"] = host
    os.environ["BILI_PORT"] = str(port)

    public_base_url = _env("PUBLIC_BASE_URL") or str(access.get("public_base_url", "")).strip()
    trusted_hosts = _list(_env("TRUSTED_HOSTS") or access.get("trusted_hosts"))
    trusted_proxy_ips = _list(_env("TRUSTED_PROXY_IPS") or access.get("trusted_proxy_ips"))
    if public_base_url:
        os.environ["PUBLIC_BASE_URL"] = public_base_url
    if trusted_hosts:
        os.environ["TRUSTED_HOSTS"] = ",".join(trusted_hosts)
    if trusted_proxy_ips:
        os.environ["TRUSTED_PROXY_IPS"] = ",".join(trusted_proxy_ips)
    os.environ["COOKIE_SECURE"] = "true" if _bool(_env("COOKIE_SECURE"), _bool(access.get("cookie_secure"))) else "false"
    os.environ["ENABLE_HSTS"] = "true" if _bool(_env("ENABLE_HSTS"), _bool(access.get("enable_hsts"))) else "false"

    config_dir = runtime_config_dir()
    print(f"配置目录: {config_dir}")
    print(f"监听地址: {host}:{port}")
    print(f"运行模式: {mode}")
    if host == "0.0.0.0":
        print(f"局域网访问请使用本机实际 IP，例如 http://192.168.1.20:{port}/")
    if port == 3389:
        print("提示：端口 3389 可以使用，但请确认未与系统中的其他服务冲突。")

    if not docker and _bool(_env("BILI_OPEN_BROWSER"), True):
        browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        Timer(1.2, lambda: webbrowser.open(f"http://{browser_host}:{port}/")).start()

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        proxy_headers=bool(trusted_proxy_ips),
        forwarded_allow_ips=",".join(trusted_proxy_ips) if trusted_proxy_ips else "127.0.0.1",
        log_level=_env("LOG_LEVEL") or "info",
    )


if __name__ == "__main__":
    main()
