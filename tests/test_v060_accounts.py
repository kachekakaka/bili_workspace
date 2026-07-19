from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import MAX_ACTIVE_SESSIONS_PER_USER
from app.main import create_app
from app.state import AppState
from tests.conftest import StaticCookieChecker, artifact_runner


@pytest.fixture
def account_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_dir = tmp_path / "config"
    bbdown_dir = config_dir / "bbdown"
    bbdown_dir.mkdir(parents=True)
    (bbdown_dir / "BBDown").write_bytes(b"fake")
    (bbdown_dir / "ffmpeg").write_bytes(b"fake")
    values = {
        "BILI_APP_MODE": "docker",
        "BILI_CONFIG_DIR": str(config_dir),
        "BILI_USERDATA_DIR": str(tmp_path / "userdata"),
        "BILI_MEDIA_DIR": str(tmp_path / "media"),
        "BILI_CACHE_DIR": str(tmp_path / "userdata" / "cache"),
        "BILI_TEMP_DIR": str(tmp_path / "userdata" / "tmp"),
        "BILI_BBDOWN_DIR": str(bbdown_dir),
        "BILI_PUBLIC_BASE_URL": "https://bili.example.test",
        "BILI_TRUSTED_HOSTS": "bili.example.test,testserver",
        "BILI_TRUSTED_PROXY_IPS": "127.0.0.1",
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
        setup = client.post(
            "/api/auth/setup",
            json={
                "username": "administrator",
                "display_name": "管理员",
                "password": "Admin-password-123",
                "bootstrap_token": values["BILI_BOOTSTRAP_TOKEN"],
            },
        )
        assert setup.status_code == 200, setup.text
        client.headers.update({"X-CSRF-Token": setup.json()["data"]["csrf_token"]})
        yield client


def test_account_validation_and_admin_user_lifecycle(account_client: TestClient):
    invalid = account_client.post(
        "/api/admin/users",
        json={
            "username": "01user",
            "display_name": "张三",
            "temporary_password": "Temporary-123",
        },
    )
    assert invalid.status_code == 400

    invalid_display = account_client.post(
        "/api/admin/users",
        json={
            "username": "user_01",
            "display_name": "User01",
            "temporary_password": "Temporary-123",
        },
    )
    assert invalid_display.status_code == 400

    created = account_client.post(
        "/api/admin/users",
        json={
            "username": "User_01",
            "display_name": "张三",
            "temporary_password": "Temporary-123",
        },
    )
    assert created.status_code == 200, created.text
    user = created.json()["data"]
    assert user["role"] == "user"
    assert user["must_change_password"] is True

    duplicate = account_client.post(
        "/api/admin/users",
        json={
            "username": "user_01",
            "display_name": "李四",
            "temporary_password": "Temporary-456",
        },
    )
    assert duplicate.status_code == 400

    updated = account_client.patch(
        f"/api/admin/users/{user['id']}", json={"display_name": "李四"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["display_name"] == "李四"

    disabled = account_client.patch(
        f"/api/admin/users/{user['id']}", json={"disabled": True}
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["disabled"] is True

    enabled = account_client.patch(
        f"/api/admin/users/{user['id']}", json={"disabled": False}
    )
    assert enabled.status_code == 200
    assert enabled.json()["data"]["disabled"] is False


def test_temporary_password_requires_change_and_normal_user_is_denied_admin_api(
    account_client: TestClient,
):
    created = account_client.post(
        "/api/admin/users",
        json={
            "username": "guest-a",
            "display_name": "访客甲",
            "temporary_password": "Temporary-123",
        },
    ).json()["data"]
    state = account_client.state_ref
    token, session = state.nas.login(
        "guest-a", "Temporary-123", remote_addr="127.0.0.1", user_agent="pytest"
    )

    account_client.cookies.clear()
    account_client.cookies.set("__Host-bili_session", token, domain="bili.example.test", path="/")
    account_client.headers.update({"X-CSRF-Token": session["csrf_token"]})

    blocked = account_client.get("/api/status")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "password_change_required"

    changed = account_client.post(
        "/api/auth/password",
        json={
            "current_password": "Temporary-123",
            "new_password": "Permanent-456",
        },
    )
    assert changed.status_code == 200, changed.text
    account_client.headers.update({"X-CSRF-Token": changed.json()["data"]["csrf_token"]})

    forbidden = account_client.get("/api/admin/users")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "forbidden"
    assert state.nas.active_session_count(created["id"]) == 1


def test_session_limit_evicts_least_recent_and_never_new_session(account_client: TestClient):
    state = account_client.state_ref
    user = state.nas.create_user(
        "session-user", "会话用户", "Temporary-123", created_by="test"
    )
    state.nas._execute(
        "UPDATE users SET must_change_password=0 WHERE id=?", (user["id"],)
    )
    issued: list[tuple[str, dict]] = []
    for index in range(MAX_ACTIVE_SESSIONS_PER_USER):
        token, session = state.nas.login(
            "session-user",
            "Temporary-123",
            remote_addr="127.0.0.1",
            user_agent=f"device-{index}",
        )
        issued.append((token, session))
        state.nas._execute(
            "UPDATE sessions SET last_seen_at=?,created_at=? WHERE id=?",
            (1000 + index, 1000 + index, session["session_id"]),
        )

    newest_token, newest_session = state.nas.login(
        "session-user",
        "Temporary-123",
        remote_addr="127.0.0.1",
        user_agent="device-new",
    )
    assert state.nas.active_session_count(user["id"]) == MAX_ACTIVE_SESSIONS_PER_USER
    assert state.nas.get_session(issued[0][0]) is None
    assert state.nas.get_session(issued[1][0]) is not None
    assert state.nas.get_session(newest_token) is not None
    row = state.nas._one(
        "SELECT revoke_reason FROM sessions WHERE id=?", (issued[0][1]["session_id"],)
    )
    assert row and row["revoke_reason"] == "session_limit"
    assert newest_session["session_id"] != issued[0][1]["session_id"]


def test_session_limit_uses_created_at_as_tie_breaker(account_client: TestClient):
    state = account_client.state_ref
    user = state.nas.create_user(
        "tie-user", "并发用户", "Temporary-123", created_by="test"
    )
    state.nas._execute(
        "UPDATE users SET must_change_password=0 WHERE id=?", (user["id"],)
    )
    issued = [
        state.nas.login(
            "tie-user", "Temporary-123", remote_addr="127.0.0.1", user_agent=str(i)
        )
        for i in range(10)
    ]
    for index, (_token, session) in enumerate(issued):
        state.nas._execute(
            "UPDATE sessions SET last_seen_at=5000,created_at=? WHERE id=?",
            (100 + index, session["session_id"]),
        )
    state.nas.login(
        "tie-user", "Temporary-123", remote_addr="127.0.0.1", user_agent="new"
    )
    assert state.nas.get_session(issued[0][0]) is None
    assert state.nas.get_session(issued[1][0]) is not None


def test_concurrent_logins_finish_with_at_most_ten_sessions(account_client: TestClient):
    state = account_client.state_ref
    user = state.nas.create_user(
        "parallel-user", "并发登录", "Temporary-123", created_by="test"
    )
    state.nas._execute(
        "UPDATE users SET must_change_password=0 WHERE id=?", (user["id"],)
    )
    errors: list[BaseException] = []

    def do_login(index: int) -> None:
        try:
            state.nas.login(
                "parallel-user",
                "Temporary-123",
                remote_addr=f"127.0.0.{index + 1}",
                user_agent=f"thread-{index}",
            )
        except BaseException as exc:  # pragma: no cover - assertion captures it
            errors.append(exc)

    threads = [threading.Thread(target=do_login, args=(index,)) for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not errors
    assert state.nas.active_session_count(user["id"]) == 10


def test_expired_and_revoked_sessions_do_not_consume_limit(account_client: TestClient):
    state = account_client.state_ref
    user = state.nas.create_user(
        "expiry-user", "过期会话", "Temporary-123", created_by="test"
    )
    state.nas._execute(
        "UPDATE users SET must_change_password=0 WHERE id=?", (user["id"],)
    )
    tokens = [
        state.nas.login(
            "expiry-user", "Temporary-123", remote_addr="127.0.0.1", user_agent=str(i)
        )
        for i in range(10)
    ]
    state.nas._execute(
        "UPDATE sessions SET expires_at=? WHERE id=?",
        (time.time() - 1, tokens[0][1]["session_id"]),
    )
    state.nas._execute(
        "UPDATE sessions SET revoked_at=?,revoke_reason='test' WHERE id=?",
        (time.time(), tokens[1][1]["session_id"]),
    )
    state.nas.login(
        "expiry-user", "Temporary-123", remote_addr="127.0.0.1", user_agent="11"
    )
    state.nas.login(
        "expiry-user", "Temporary-123", remote_addr="127.0.0.1", user_agent="12"
    )
    assert state.nas.active_session_count(user["id"]) == 10
    assert state.nas.get_session(tokens[2][0]) is not None


def test_cross_session_csrf_is_rejected_and_logout_only_revokes_current(
    account_client: TestClient,
):
    state = account_client.state_ref
    token_a, session_a = state.nas.login(
        "administrator", "Admin-password-123", remote_addr="127.0.0.1", user_agent="a"
    )
    token_b, session_b = state.nas.login(
        "administrator", "Admin-password-123", remote_addr="127.0.0.1", user_agent="b"
    )
    account_client.cookies.clear()
    account_client.cookies.set("__Host-bili_session", token_a, domain="bili.example.test", path="/")
    account_client.headers.update({"X-CSRF-Token": session_b["csrf_token"]})
    rejected = account_client.patch(
        "/api/auth/profile", json={"display_name": "系统管理员"}
    )
    assert rejected.status_code == 403

    account_client.headers.update({"X-CSRF-Token": session_a["csrf_token"]})
    logged_out = account_client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert state.nas.get_session(token_a) is None
    assert state.nas.get_session(token_b) is not None


def test_plaintext_session_token_is_not_persisted(account_client: TestClient):
    state = account_client.state_ref
    token, _session = state.nas.login(
        "administrator", "Admin-password-123", remote_addr="127.0.0.1", user_agent="secret"
    )
    database_bytes = state.runtime.database_path.read_bytes()
    assert token.encode() not in database_bytes
    rows = state.nas._all("SELECT detail FROM audit_log")
    assert all(token not in str(row["detail"]) for row in rows)
