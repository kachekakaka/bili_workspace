from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from bili_workspace_launcher.paths import AppPaths
from bili_workspace_launcher.ports import recommend_available_port
from bili_workspace_launcher.settings import (
    LauncherSettings,
    NetworkSettings,
    RuntimeEnvStore,
    SettingsError,
    SettingsStore,
)


def test_launcher_settings_only_own_control_convenience(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path)
    store = SettingsStore(paths)
    assert store.load() is None
    value = LauncherSettings.create(tmp_path / "data", str(tmp_path / "exports"))
    store.save(value)
    assert store.load() == value
    raw = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert set(raw) == {"schema_version", "data_root", "recent_export_dir"}


def test_launcher_settings_reject_unknown_or_future_fields(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path)
    paths.settings_file.write_text(
        '{"schema_version": 2, "data_root": "x", "token": "secret"}', encoding="utf-8"
    )
    with pytest.raises(SettingsError):
        SettingsStore(paths).load()
    paths.settings_file.write_text(
        '{"schema_version": true, "data_root": "x"}', encoding="utf-8"
    )
    with pytest.raises(SettingsError, match="schema_version"):
        SettingsStore(paths).load()
    paths.settings_file.write_text(
        '{"schema_version": 1, "data_root": "relative-data"}', encoding="utf-8"
    )
    with pytest.raises(SettingsError, match="绝对路径"):
        SettingsStore(paths).load()


def test_launcher_and_runtime_settings_reject_invalid_utf8(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path)
    paths.settings_file.write_bytes(b"\xff")
    with pytest.raises(SettingsError, match="无法读取 launcher.json"):
        SettingsStore(paths).load()

    runtime = tmp_path / "runtime.env"
    runtime.write_bytes(b"\xff")
    with pytest.raises(SettingsError, match="无法读取 runtime.env"):
        RuntimeEnvStore(runtime).load()


def test_network_settings_enforce_lan_security_links() -> None:
    with pytest.raises(SettingsError, match="回环"):
        NetworkSettings(mode="server", host="127.0.0.1").validated()
    with pytest.raises(SettingsError, match="通配符"):
        NetworkSettings(mode="server", host="0.0.0.0", trusted_hosts=("*",)).validated()
    with pytest.raises(SettingsError, match="通配符"):
        NetworkSettings(
            mode="server", host="0.0.0.0", trusted_hosts=("*.example.test",)
        ).validated()
    with pytest.raises(SettingsError, match="任意 IP Host"):
        NetworkSettings(mode="local", host="127.0.0.1", allow_ip_hosts=True).validated()
    with pytest.raises(SettingsError, match="Secure Cookie"):
        NetworkSettings(
            mode="server",
            host="0.0.0.0",
            trusted_hosts=("bili.example.test",),
            public_base_url="https://bili.example.test",
            cookie_secure=False,
        ).validated()
    with pytest.raises(SettingsError, match="Secure Cookie"):
        NetworkSettings(
            mode="server",
            host="0.0.0.0",
            trusted_hosts=("bili.example.test",),
            public_base_url="HTTPS://bili.example.test",
            cookie_secure=False,
        ).validated()
    with pytest.raises(SettingsError, match="覆盖全部"):
        NetworkSettings(trusted_proxy_ips=("0.0.0.0/0",)).validated()
    with pytest.raises(SettingsError, match="覆盖全部"):
        NetworkSettings(trusted_proxy_ips=("::/0",)).validated()
    valid = NetworkSettings(
        mode="server",
        host="0.0.0.0",
        trusted_hosts=("bili.example.test",),
        public_base_url="https://bili.example.test",
        cookie_secure=True,
        hsts_enabled=True,
    ).validated()
    assert valid.mode == "server"
    assert replace(valid, public_base_url="HTTPS://BILI.EXAMPLE.TEST/").validated().public_base_url == (
        "https://bili.example.test"
    )
    assert NetworkSettings(host="[::1]").validated().host == "::1"
    assert NetworkSettings(host="LOCALHOST.").validated().host == "localhost"
    ipv6 = NetworkSettings(
        mode="server",
        host="::",
        trusted_hosts=("2001:db8::1",),
        public_base_url="HTTPS://[2001:DB8::1]:8443/",
        cookie_secure=True,
        hsts_enabled=True,
    ).validated()
    assert ipv6.trusted_hosts == ("[2001:db8::1]",)
    assert ipv6.public_base_url == "https://[2001:db8::1]:8443"


def test_network_settings_reject_coercible_or_incomplete_values() -> None:
    with pytest.raises(SettingsError, match="整数"):
        NetworkSettings(port="3398").validated()  # type: ignore[arg-type]
    with pytest.raises(SettingsError, match="布尔"):
        NetworkSettings(cookie_secure=1).validated()  # type: ignore[arg-type]
    with pytest.raises(SettingsError, match="字符串列表"):
        NetworkSettings(trusted_hosts="localhost").validated()  # type: ignore[arg-type]
    with pytest.raises(SettingsError, match="回环地址"):
        NetworkSettings(trusted_hosts=("example.test",)).validated()
    with pytest.raises(SettingsError, match="监听地址无效"):
        NetworkSettings(host="本机.example").validated()


def test_runtime_env_save_preserves_unknown_lines(tmp_path: Path) -> None:
    path = tmp_path / "runtime.env"
    path.write_text(
        "# keep\nBILI_APP_MODE=local\nBILI_HOST=\nBILI_PORT=\nCUSTOM_VALUE=keep-me\n",
        encoding="utf-8",
    )
    store = RuntimeEnvStore(path)
    assert store.load().host == "127.0.0.1"
    store.save(NetworkSettings(mode="server", host="0.0.0.0", port=3400))
    assert path.with_suffix(".env.bak").read_text(encoding="utf-8") == (
        "# keep\nBILI_APP_MODE=local\nBILI_HOST=\nBILI_PORT=\nCUSTOM_VALUE=keep-me\n"
    )
    text = path.read_text(encoding="utf-8")
    assert "CUSTOM_VALUE=keep-me" in text
    loaded = store.load()
    assert loaded.mode == "server"
    assert loaded.host == "0.0.0.0"
    assert loaded.port == 3400


def test_recommend_port_requires_explicit_checker_result() -> None:
    assert recommend_available_port(3398, checker=lambda value: value == 3401) == 3401
