"""后端监听端口探测。"""

from __future__ import annotations

import socket
from collections.abc import Callable

from .constants import DEFAULT_BACKEND_HOST


def is_port_available(port: int, host: str = DEFAULT_BACKEND_HOST) -> bool:
    if not 1 <= port <= 65535:
        return False
    family = socket.AF_INET6 if ":" in host.strip("[]") else socket.AF_INET
    probe = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind((host.strip("[]"), port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def recommend_available_port(
    preferred: int,
    *,
    checker: Callable[[int], bool] = is_port_available,
) -> int | None:
    for port in range(max(preferred + 1, 1024), 65536):
        if checker(port):
            return port
    for port in range(1024, min(max(preferred, 1024), 65536)):
        if checker(port):
            return port
    return None
