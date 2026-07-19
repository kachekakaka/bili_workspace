from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.state import AppState
from tests.conftest import StaticCookieChecker, artifact_runner


@pytest.fixture
def server_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_dir = tmp_path / "config"
    media_dir = tmp_path / "media"
    cache_dir = tmp_path / "cache"
    temp_dir = tmp_path / "tmp"
    bbdown_dir = config_dir / "bbdown"
    bbdown_dir.mkdir(parents=True)
    (bbdown_dir / "BBDown").write_bytes(b"fake")
    (bbdown_dir / "ffmpeg").write_bytes(b"fake")

    values = {
        "BILI_APP_MODE": "docker",
        "BILI_CONFIG_DIR": str(config_dir),
        "BILI_MEDIA_DIR": str(media_dir),
        "BILI_USERDATA_DIR": str(tmp_path / "userdata"),
        "BILI_CACHE_DIR": str(cache_dir),
        "BILI_TEMP_DIR": str(temp_dir),
        "BILI_BBDOWN_DIR": str(bbdown_dir),
        "BILI_PUBLIC_BASE_URL": "https://bili.example.test",
        "BILI_TRUSTED_HOSTS": "bili.example.test,testserver",
        "BILI_TRUSTED_PROXY_IPS": "127.0.0.1",
        "BILI_AUTH_REQUIRED": "true",
        "BILI_COOKIE_SECURE": "true",
        "BILI_HSTS": "true",
        "BILI_BOOTSTRAP_TOKEN": "bootstrap-token-for-tests",
        "BILI_MIN_FREE_GIB": "0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    state = AppState.create(
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    app = create_app(state)
    with TestClient(app, base_url="https://bili.example.test") as client:
        client.state_ref = state
        client.bootstrap_token = values["BILI_BOOTSTRAP_TOKEN"]
        yield client


def _setup(client: TestClient) -> str:
    response = client.post(
        "/api/auth/setup",
        json={
            "username": "administrator",
            "password": "strong-password-123",
            "bootstrap_token": client.bootstrap_token,
        },
    )
    assert response.status_code == 200
    return str(response.json()["data"]["csrf_token"])


def test_server_mode_requires_authentication_and_initial_setup(server_client):
    status = server_client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.json()["data"]["setup_required"] is True
    assert server_client.get("/api/status").status_code == 401

    csrf = _setup(server_client)
    auth = server_client.get("/api/auth/status").json()["data"]
    assert auth["authenticated"] is True
    assert auth["username"] == "administrator"
    assert auth["csrf_token"] == csrf
    assert server_client.get("/api/status").status_code == 200


def test_server_cookie_security_and_csrf(server_client):
    csrf = _setup(server_client)
    header = server_client.cookies.get("__Host-bili_session")
    assert header

    no_csrf = server_client.post("/api/groups", json={"name": "安全测试"})
    assert no_csrf.status_code == 403
    good = server_client.post(
        "/api/groups",
        json={"name": "安全测试"},
        headers={"X-CSRF-Token": csrf},
    )
    assert good.status_code == 200

    set_cookie = server_client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "strong-password-123"},
    ).headers["set-cookie"]
    lowered = set_cookie.lower()
    assert "secure" in lowered
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered


def test_invalid_host_is_rejected(server_client):
    _setup(server_client)
    response = server_client.get("/api/status", headers={"Host": "evil.example"})
    assert response.status_code == 400


def test_bootstrap_token_is_one_time(server_client):
    _setup(server_client)
    again = server_client.post(
        "/api/auth/setup",
        json={
            "username": "second-admin",
            "password": "another-strong-password",
            "bootstrap_token": server_client.bootstrap_token,
        },
    )
    assert again.status_code == 400
    assert "已经初始化" in again.json()["error"]


def test_change_password_rotates_csrf_and_revokes_other_sessions(server_client):
    _setup(server_client)
    first_token = server_client.cookies.get("__Host-bili_session")
    assert first_token

    second_login = server_client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "strong-password-123"},
    )
    assert second_login.status_code == 200
    second_csrf = str(second_login.json()["data"]["csrf_token"])
    second_token = server_client.cookies.get("__Host-bili_session")
    assert second_token and second_token != first_token

    changed = server_client.post(
        "/api/auth/password",
        json={
            "current_password": "strong-password-123",
            "new_password": "new-strong-password-456",
        },
        headers={"X-CSRF-Token": second_csrf},
    )
    assert changed.status_code == 200
    data = changed.json()["data"]
    assert data["csrf_token"] != second_csrf
    assert data["other_sessions_revoked"] >= 1
    rotated_token = server_client.cookies.get("__Host-bili_session")
    assert rotated_token and rotated_token not in {first_token, second_token}
    assert server_client.state_ref.nas.get_session(first_token) is None
    assert server_client.state_ref.nas.get_session(second_token) is None
    assert server_client.state_ref.nas.get_session(rotated_token) is not None

    old_password = server_client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "strong-password-123"},
    )
    assert old_password.status_code == 401
    new_password = server_client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "new-strong-password-456"},
    )
    assert new_password.status_code == 200


def test_security_headers_are_applied_to_early_auth_rejections(server_client):
    response = server_client.get("/api/status")
    assert response.status_code == 401
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_numeric_ip_host_is_allowed_for_phone_access(server_client):
    response = server_client.get("/api/auth/status", headers={"Host": "192.168.1.50:3389"})
    assert response.status_code == 200
