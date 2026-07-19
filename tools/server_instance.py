from __future__ import annotations

import argparse
import json
import locale
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
from urllib import error, parse, request

from app.build_info import build_metadata
from app.paths import ROOT

EXIT_LAUNCH = 0
EXIT_ALREADY_CURRENT = 10
EXIT_BLOCKED = 2
_LISTENING_STATES = {"LISTEN", "LISTENING"}


def health_url(base_url: str) -> str:
    value = base_url.strip()
    if not value:
        raise ValueError("服务地址不能为空")
    parts = parse.urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"服务地址无效: {base_url}")
    return parse.urlunsplit(
        (parts.scheme, parts.netloc, "/healthz", f"_={time.time_ns()}", "")
    )


def probe_health(base_url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    target = health_url(base_url)
    incoming = request.Request(
        target,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with request.urlopen(incoming, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def is_bili_workspace(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    if payload.get("service") == "bili_workspace":
        return True
    # V0.5.6 instances before build metadata exposed this compact health shape.
    return (
        payload.get("ok") is True
        and isinstance(payload.get("version"), str)
        and payload.get("mode") in {"local", "server", "nas", "docker"}
    )


def parse_netstat_listeners(text: str, port: int) -> list[int]:
    result: set[int] = set()
    for raw_line in text.splitlines():
        parts = re.split(r"\s+", raw_line.strip())
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        state = parts[-2].upper()
        if state not in _LISTENING_STATES:
            continue
        local_address = parts[1]
        try:
            local_port = int(local_address.rsplit(":", 1)[1])
            pid = int(parts[-1])
        except (IndexError, ValueError):
            continue
        if local_port == port and pid > 0:
            result.add(pid)
    return sorted(result)


def windows_listeners(port: int) -> list[int]:
    if os.name != "nt":
        return []
    encoding = locale.getpreferredencoding(False) or "utf-8"
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_netstat_listeners(completed.stdout, port)


def windows_process_details(pid: int) -> str:
    if os.name != "nt" or pid <= 0:
        return ""
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {pid}";'
        "if($p){$p.ExecutablePath;$p.CommandLine}"
    )
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip()


def belongs_to_checkout(details: str, root: Path = ROOT) -> bool:
    normalized = details.replace("/", "\\").casefold()
    root_text = str(root.resolve()).replace("/", "\\").casefold()
    python_text = str(
        (root / ".runtime" / "python" / "python.exe").resolve()
    ).replace("/", "\\").casefold()
    launches_app = " -m app" in normalized or "\\app\\__main__.py" in normalized
    return launches_app and (root_text in normalized or python_text in normalized)


def stop_windows_process(pid: int) -> bool:
    if os.name != "nt" or pid <= 0:
        return False
    try:
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False) or "utf-8",
            errors="replace",
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def wait_port_free(port: int, timeout: float = 10.0) -> bool:
    if os.name != "nt":
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not windows_listeners(port):
            return True
        time.sleep(0.2)
    return not windows_listeners(port)


def _version_label(payload: dict[str, Any]) -> str:
    application = str(payload.get("version") or "未知")
    frontend = str(payload.get("frontend_version") or "旧版未报告")
    build = str(payload.get("build_id") or "旧版未报告")
    return f"应用 {application} / 前端 {frontend} / 构建 {build}"


def prepare_start(base_url: str, port: int) -> int:
    current = build_metadata()
    running = probe_health(base_url)
    listeners = windows_listeners(port)

    if running and is_bili_workspace(running):
        same_build = (
            running.get("build_id") == current["build_id"]
            and running.get("frontend_version") == current["frontend_version"]
        )
        if same_build:
            print(
                "[已运行] 当前源码对应的服务已经在运行："
                f"{_version_label(running)}"
            )
            return EXIT_ALREADY_CURRENT

        pid = int(running.get("pid") or 0)
        if pid <= 0 and len(listeners) == 1:
            pid = listeners[0]
        if pid <= 0:
            print(
                "[错误] 检测到旧版 bili_workspace，但无法确定监听进程。"
                "请关闭旧的启动窗口后重试。"
            )
            return EXIT_BLOCKED

        details = windows_process_details(pid)
        if not belongs_to_checkout(details):
            print(f"[错误] 端口 {port} 上的旧服务进程 PID {pid} 不属于当前目录。")
            if details:
                print(details)
            print("请关闭该实例，或确认当前使用的是正确的仓库目录。")
            return EXIT_BLOCKED

        print(f"[更新] 检测到当前目录仍在运行旧服务：{_version_label(running)}")
        print(
            "[更新] 当前源码要求："
            f"应用 {current['version']} / 前端 {current['frontend_version']} / "
            f"构建 {current['build_id']}"
        )
        print(f"[更新] 正在关闭旧进程 PID {pid} 并启动当前版本...")
        if not stop_windows_process(pid) or not wait_port_free(port):
            print("[错误] 无法关闭旧服务。请手动关闭旧启动窗口后重试。")
            return EXIT_BLOCKED
        return EXIT_LAUNCH

    if listeners:
        joined = ", ".join(str(pid) for pid in listeners)
        print(
            f"[错误] 端口 {port} 已被其他程序占用（PID: {joined}），"
            "且没有返回 bili_workspace 健康信息。"
        )
        return EXIT_BLOCKED

    return EXIT_LAUNCH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect an existing bili_workspace listener before Windows startup."
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        return prepare_start(args.url, args.port)
    except ValueError as exc:
        print(f"[错误] {exc}")
        return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
