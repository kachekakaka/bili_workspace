from __future__ import annotations

import argparse
import ipaddress
import json
import socket
from pathlib import Path

from app.runtime import RuntimeSettings
from tools.config_sync import sync_configs


def _is_loopback(host: str) -> bool:
    value = host.strip().lower().strip("[]")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _lan_addresses() -> list[str]:
    result: set[str] = set()
    try:
        for value in socket.gethostbyname_ex(socket.gethostname())[2]:
            ip = ipaddress.ip_address(value)
            if ip.version == 4 and not ip.is_loopback and not ip.is_link_local:
                result.add(value)
    except (OSError, ValueError):
        pass
    return sorted(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", action="store_true")
    args = parser.parse_args()

    paths = sync_configs()
    runtime = RuntimeSettings.from_env()
    config = json.loads(Path(paths["app_config"]).read_text(encoding="utf-8"))
    host = runtime.host if runtime.server_mode else str(config.get("host") or "127.0.0.1")
    port = runtime.port if runtime.server_mode else int(config.get("port") or 3398)
    server = runtime.server_mode or not _is_loopback(host)
    open_host = "127.0.0.1" if host.strip("[]") in {"0.0.0.0", "::"} else host.strip("[]")
    open_url = f"http://{open_host}:{port}/"

    if args.machine:
        print(f"OPEN_URL={open_url}")
        print(f"BIND_HOST={host}")
        print(f"BIND_PORT={port}")
        print(f"SERVER_MODE={1 if server else 0}")
        return 0

    print(f"本机地址：{open_url}")
    if server:
        for address in _lan_addresses():
            print(f"手机/局域网地址：http://{address}:{port}/")
        print("非回环监听会强制启用网站管理员认证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
