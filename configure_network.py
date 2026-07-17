from __future__ import annotations

import argparse
import json

from app.config_bootstrap import ensure_runtime_configs, runtime_config_dir


def valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("端口必须是整数") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 1-65535 之间")
    return port


def main() -> None:
    parser = argparse.ArgumentParser(description="配置网站监听地址和端口")
    parser.add_argument("--host", help="例如 127.0.0.1 或 0.0.0.0")
    parser.add_argument("--port", type=valid_port, help="任意未占用的 1-65535 端口")
    parser.add_argument("--trusted-host", action="append", dest="trusted_hosts", help="可重复使用")
    parser.add_argument("--show", action="store_true", help="仅显示当前配置")
    args = parser.parse_args()

    ensure_runtime_configs()
    path = runtime_config_dir() / "server.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not args.show:
        if args.host:
            data.setdefault("listen", {})["host"] = args.host.strip()
            if args.host.strip() not in {"127.0.0.1", "::1", "localhost"}:
                data.setdefault("access", {})["mode"] = "server"
        if args.port is not None:
            data.setdefault("listen", {})["port"] = args.port
        if args.trusted_hosts:
            data.setdefault("access", {})["trusted_hosts"] = args.trusted_hosts
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
