from __future__ import annotations

from pathlib import Path

import pytest

from app.runtime import RuntimeSettings


def _base(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    values = {
        "BILI_APP_MODE": "docker",
        "BILI_CONFIG_DIR": str(tmp_path / "config"),
        "BILI_MEDIA_DIR": str(tmp_path / "media"),
        "BILI_CACHE_DIR": str(tmp_path / "cache"),
        "BILI_TEMP_DIR": str(tmp_path / "tmp"),
        "BILI_BBDOWN_DIR": str(tmp_path / "bbdown"),
        "BILI_PUBLIC_BASE_URL": "https://bili.example.test",
        "BILI_TRUSTED_HOSTS": "bili.example.test",
        "BILI_AUTH_REQUIRED": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_server_mode_forces_authentication(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_AUTH_REQUIRED", "false")
    settings = RuntimeSettings.from_env()
    assert settings.auth_required is True


def test_wildcard_only_trusted_hosts_is_rejected(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_TRUSTED_HOSTS", "*")
    with pytest.raises(ValueError, match="明确域名"):
        RuntimeSettings.from_env()


def test_https_public_url_enables_secure_cookie_and_hsts(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    settings = RuntimeSettings.from_env()
    assert settings.server_mode is True
    assert settings.cookie_secure is True
    assert settings.hsts_enabled is True
    assert settings.host == "0.0.0.0"
    assert settings.database_path.parent.is_dir()


def test_download_concurrency_is_bounded(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_DOWNLOAD_CONCURRENCY", "4")
    with pytest.raises(ValueError, match="1–3"):
        RuntimeSettings.from_env()


def test_public_url_rejects_subpaths_and_credentials(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_PUBLIC_BASE_URL", "https://bili.example.test/app")
    with pytest.raises(ValueError, match="独立域名"):
        RuntimeSettings.from_env()

    monkeypatch.setenv("BILI_PUBLIC_BASE_URL", "https://admin:secret@bili.example.test")
    with pytest.raises(ValueError, match="用户名或密码"):
        RuntimeSettings.from_env()


def test_wildcard_trusted_proxy_is_rejected(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_TRUSTED_PROXY_IPS", "*")
    with pytest.raises(ValueError, match="可信代理地址"):
        RuntimeSettings.from_env()


def test_https_origin_requires_secure_cookie_and_matching_trusted_host(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_COOKIE_SECURE", "false")
    with pytest.raises(ValueError, match="BILI_COOKIE_SECURE"):
        RuntimeSettings.from_env()

    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_TRUSTED_HOSTS", "other.example.test")
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        RuntimeSettings.from_env()


def test_hsts_rejected_without_https(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_PUBLIC_BASE_URL", "http://bili.example.test")
    monkeypatch.setenv("BILI_COOKIE_SECURE", "false")
    monkeypatch.setenv("BILI_HSTS", "true")
    with pytest.raises(ValueError, match="HSTS"):
        RuntimeSettings.from_env()


def test_server_can_bind_all_interfaces_on_port_3389(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_HOST", "0.0.0.0")
    monkeypatch.setenv("BILI_PORT", "3389")
    settings = RuntimeSettings.from_env()
    assert settings.host == "0.0.0.0"
    assert settings.port == 3389
    assert settings.auth_required is True
    assert settings.allow_ip_hosts is True


def test_config_hostname_promotes_local_runtime_and_updates_trusted_hosts(
    monkeypatch, tmp_env, tmp_path
):
    from app.state import AppState
    from tests.conftest import StaticCookieChecker, artifact_runner

    monkeypatch.setenv("BILI_APP_MODE", "local")
    monkeypatch.delenv("BILI_HOST", raising=False)
    monkeypatch.setenv("BILI_CONFIG_DIR", str(tmp_path / "runtime-config"))
    monkeypatch.setenv("BILI_MEDIA_DIR", str(tmp_path / "runtime-media"))
    monkeypatch.setenv("BILI_CACHE_DIR", str(tmp_path / "runtime-cache"))
    monkeypatch.setenv("BILI_TEMP_DIR", str(tmp_path / "runtime-tmp"))
    monkeypatch.setenv("BILI_TRUSTED_HOSTS", "127.0.0.1,localhost,testserver")

    initial = dict(tmp_env.initial)
    initial["host"] = "nas-box.home"
    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(),
    )
    try:
        assert state.runtime.server_mode is True
        assert state.runtime.auth_required is True
        assert state.runtime.host == "nas-box.home"
        assert "nas-box.home" in state.runtime.trusted_hosts
    finally:
        state.stop()


def test_invalid_bind_hostname_is_rejected(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    monkeypatch.setenv("BILI_HOST", "-invalid.home")
    with pytest.raises(ValueError, match="BILI_HOST"):
        RuntimeSettings.from_env()


def test_explicit_environment_port_overrides_local_json_config(monkeypatch, tmp_env, tmp_path):
    from app.state import AppState
    from tests.conftest import StaticCookieChecker, artifact_runner

    monkeypatch.setenv("BILI_APP_MODE", "local")
    monkeypatch.setenv("BILI_HOST", "127.0.0.1")
    monkeypatch.setenv("BILI_PORT", "34177")
    monkeypatch.setenv("BILI_CONFIG_DIR", str(tmp_path / "runtime-config"))
    monkeypatch.setenv("BILI_MEDIA_DIR", str(tmp_path / "runtime-media"))
    monkeypatch.setenv("BILI_CACHE_DIR", str(tmp_path / "runtime-cache"))
    monkeypatch.setenv("BILI_TEMP_DIR", str(tmp_path / "runtime-tmp"))

    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(),
    )
    try:
        assert state.runtime.port == 34177
        assert state.config_store.get().port == 34177
    finally:
        state.stop()
