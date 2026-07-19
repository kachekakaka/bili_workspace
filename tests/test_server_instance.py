from __future__ import annotations

from pathlib import Path

from tools import server_instance


def test_health_url_always_bypasses_document_cache() -> None:
    value = server_instance.health_url("http://127.0.0.1:3398/?old=1#/dashboard")
    assert value.startswith("http://127.0.0.1:3398/healthz?_")
    assert "#/dashboard" not in value


def test_health_payload_recognizes_current_and_legacy_instances() -> None:
    assert server_instance.is_bili_workspace(
        {
            "ok": True,
            "service": "bili_workspace",
            "version": "0.5.6",
            "mode": "local",
        }
    )
    assert server_instance.is_bili_workspace(
        {"ok": True, "version": "0.5.6", "mode": "local"}
    )
    assert not server_instance.is_bili_workspace(
        {"ok": True, "version": "1", "mode": "something-else"}
    )


def test_netstat_parser_handles_ipv4_ipv6_and_duplicates() -> None:
    text = """
      TCP    127.0.0.1:3398       0.0.0.0:0       LISTENING       4120
      TCP    0.0.0.0:3398         0.0.0.0:0       LISTENING       4120
      TCP    [::]:3398            [::]:0          LISTENING       9001
      TCP    127.0.0.1:3399       0.0.0.0:0       LISTENING       7777
      TCP    127.0.0.1:3398       127.0.0.1:5000  ESTABLISHED     8888
    """
    assert server_instance.parse_netstat_listeners(text, 3398) == [4120, 9001]


def test_process_ownership_requires_current_runtime_and_app_module(tmp_path: Path) -> None:
    root = tmp_path / "bili_workspace"
    python = root / ".runtime" / "python" / "python.exe"
    details = f'{python}\n"{python}" -m app'
    assert server_instance.belongs_to_checkout(details, root)
    assert not server_instance.belongs_to_checkout(
        'C:\\other\\python.exe\n"C:\\other\\python.exe" -m app', root
    )
    assert not server_instance.belongs_to_checkout(f'{python}\n"{python}" -m http.server', root)


def test_current_running_build_is_reused(monkeypatch) -> None:
    current = {
        "service": "bili_workspace",
        "version": "0.5.6",
        "frontend_version": "frontend-a",
        "build_id": "build-a",
        "mode": "local",
        "pid": 123,
    }
    monkeypatch.setattr(server_instance, "build_metadata", lambda: dict(current))
    monkeypatch.setattr(server_instance, "probe_health", lambda _url: dict(current))
    monkeypatch.setattr(server_instance, "windows_listeners", lambda _port: [123])

    assert (
        server_instance.prepare_start("http://127.0.0.1:3398/", 3398)
        == server_instance.EXIT_ALREADY_CURRENT
    )


def test_stale_same_checkout_process_is_stopped(monkeypatch) -> None:
    current = {
        "service": "bili_workspace",
        "version": "0.5.6",
        "frontend_version": "frontend-new",
        "build_id": "build-new",
    }
    old = {
        "ok": True,
        "version": "0.5.6",
        "mode": "local",
    }
    stopped: list[int] = []
    monkeypatch.setattr(server_instance, "build_metadata", lambda: dict(current))
    monkeypatch.setattr(server_instance, "probe_health", lambda _url: dict(old))
    monkeypatch.setattr(server_instance, "windows_listeners", lambda _port: [456])
    monkeypatch.setattr(
        server_instance, "windows_process_details", lambda _pid: "current checkout"
    )
    monkeypatch.setattr(server_instance, "belongs_to_checkout", lambda _details: True)
    monkeypatch.setattr(
        server_instance,
        "stop_windows_process",
        lambda pid: stopped.append(pid) is None or True,
    )
    monkeypatch.setattr(server_instance, "wait_port_free", lambda _port: True)

    assert (
        server_instance.prepare_start("http://127.0.0.1:3398/", 3398)
        == server_instance.EXIT_LAUNCH
    )
    assert stopped == [456]


def test_unknown_listener_is_never_terminated(monkeypatch) -> None:
    monkeypatch.setattr(server_instance, "probe_health", lambda _url: None)
    monkeypatch.setattr(server_instance, "windows_listeners", lambda _port: [999])

    assert (
        server_instance.prepare_start("http://127.0.0.1:3398/", 3398)
        == server_instance.EXIT_BLOCKED
    )
