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
