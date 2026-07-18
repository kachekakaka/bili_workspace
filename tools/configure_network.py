from __future__ import annotations

import ipaddress
import json
from pathlib import Path

from app.io_utils import atomic_write_json
from tools.config_sync import sync_configs


def _valid_host(value: str) -> bool:
    host = value.strip()
    if not host or any(ch.isspace() for ch in host):
        return False
    if host.lower() == "localhost":
        return True
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return all(part and part.replace("-", "").isalnum() for part in host.rstrip(".").split("."))


def main() -> int:
    paths = sync_configs()
    path = Path(paths["app_config"])
    data = json.loads(path.read_text(encoding="utf-8"))
    current_host = str(data.get("host") or "127.0.0.1")
    current_port = int(data.get("port") or 3398)

    print("当前监听地址：", current_host)
    print("当前端口：", current_port)
    print("手机访问通常使用 0.0.0.0；只允许本机访问使用 127.0.0.1。")
    host = input(f"监听地址 [{current_host}]: ").strip() or current_host
    if not _valid_host(host):
        raise SystemExit("[错误] 监听地址无效")
    raw_port = input(f"端口 [{current_port}]: ").strip()
    port = current_port if not raw_port else int(raw_port)
    if not 1 <= port <= 65535:
        raise SystemExit("[错误] 端口必须在 1–65535")

    data["host"] = host
    data["port"] = port
    atomic_write_json(path, data, backup=True)
    print(f"[完成] 已保存到 {path}")
    print("重新运行 start.bat 后生效。非回环地址会强制启用管理员登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
