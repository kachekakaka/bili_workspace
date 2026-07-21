from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE
from app.main import create_app
from app.nas import NasStore
from app.state import AppState


def _server_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NasStore:
    monkeypatch.setenv("BILI_SERVER_MODE", "1")
    monkeypatch.setenv("BILI_USERDATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.setenv("BILI_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("BILI_TEMP_DIR", str(tmp_path / "temp"))
    return NasStore(tmp_path / "userdata" / "bili.db")


def _server_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppState:
    monkeypatch.setenv("BILI_SERVER_MODE", "1")
    monkeypatch.setenv("BILI_USERDATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.setenv("BILI_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("BILI_TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setenv("BILI_BOOTSTRAP_TOKEN", "bootstrap-token-for-tests")
    return AppState.create()


def test_session_token_is_hashed_and_never_persisted_in_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        user = store.create_initial_admin(
            username="administrator",
            display_name="管理员",
            password="StrongPassword123",
        )
        token, session = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="pytest",
        )
        assert token
        assert token not in store.path.read_text(encoding="latin-1", errors="ignore")
        row = store._one("SELECT * FROM sessions WHERE id=?", (session["session_id"],))
        assert row is not None
        assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert row["user_id"] == user["id"]
        assert "token" not in row.keys()
    finally:
        store.close()


def test_session_limit_revokes_oldest_active_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        store.create_initial_admin(
            username="administrator",
            display_name="管理员",
            password="StrongPassword123",
        )
        sessions = []
        for index in range(12):
            token, session = store.login(
                "administrator",
                "StrongPassword123",
                remote_addr=f"192.0.2.{index}",
                user_agent=f"session-{index}",
            )
            sessions.append((token, session))
            time.sleep(0.002)
        active = store.list_sessions(sessions[-1][1]["user_id"], sessions[-1][1]["session_id"])
        assert len(active) == 10
        assert store.session_for_token(sessions[0][0]) is None
        assert store.session_for_token(sessions[1][0]) is None
        assert store.session_for_token(sessions[-1][0]) is not None
    finally:
        store.close()


def test_expired_session_is_rejected_and_revoked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        store.create_initial_admin(
            username="administrator",
            display_name="管理员",
            password="StrongPassword123",
        )
        token, session = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="expired",
        )
        store._execute(
            "UPDATE sessions SET expires_at=? WHERE id=?",
            (time.time() - 1, session["session_id"]),
        )
        assert store.session_for_token(token) is None
        row = store._one("SELECT revoked_at FROM sessions WHERE id=?", (session["session_id"],))
        assert row is not None and row["revoked_at"] is not None
    finally:
        store.close()


def test_password_change_rotates_session_and_revokes_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        store.create_initial_admin(
            username="administrator",
            display_name="管理员",
            password="StrongPassword123",
        )
        first_token, first = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="first",
        )
        second_token, second = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.2",
            user_agent="second",
        )
        next_token, changed = store.change_password(
            user_id=first["user_id"],
            current_password="StrongPassword123",
            new_password="AnotherStrongPassword456",
            current_session_id=first["session_id"],
        )
        assert changed["other_sessions_revoked"] == 1
        assert store.session_for_token(first_token) is None
        assert store.session_for_token(second_token) is None
        assert store.session_for_token(next_token) is not None
        assert next_token not in store.path.read_text(encoding="latin-1", errors="ignore")
        assert second["session_id"] != changed["session_id"]
    finally:
        store.close()


def test_session_management_endpoints_keep_cookie_host_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _server_app(tmp_path, monkeypatch)
    app = create_app(state)
    with TestClient(app) as client:
        setup = client.post(
            "/api/auth/setup",
            json={
                "username": "administrator",
                "display_name": "管理员",
                "password": "StrongPassword123",
                "bootstrap_token": "bootstrap-token-for-tests",
            },
        )
        assert setup.status_code == 200
        csrf = setup.json()["data"]["csrf_token"]
        sessions = client.get("/api/auth/sessions")
        assert sessions.status_code == 200
        assert sessions.json()["data"]["limit"] == 10
        revoke_others = client.post(
            "/api/auth/sessions/revoke-others",
            headers={"X-CSRF-Token": csrf},
        )
        assert revoke_others.status_code == 200
        assert revoke_others.json()["data"]["revoked"] == 0
        cookie = setup.headers.get("set-cookie", "")
        assert f"{SESSION_COOKIE}=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Domain=" not in cookie
    state.close()


def test_cookie_token_never_appears_in_tables_or_database_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        store.create_initial_admin(
            username="administrator",
            display_name="管理员",
            password="StrongPassword123",
        )
        token = secrets.token_urlsafe(48)
        session = store.create_session_for_user(
            user_id=store.list_users()[0]["id"],
            token=token,
            remote_addr="127.0.0.1",
            user_agent="explicit-token",
        )
        assert store.session_for_token(token) is not None
        store.revoke_session(
            user_id=session["user_id"],
            session_id=str(session["session_id"]),
        )
        for table in ("sessions", "audit_log"):
            rows = store._all(f"SELECT * FROM {table}")
            assert token not in repr(rows)
        assert token.encode() not in store.path.read_bytes()
    finally:
        store.close()


def test_sse_session_heartbeat_refreshes_last_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        _token, session = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="sse-heartbeat",
        )
        old_seen = time.time() - 300
        store._execute(
            "UPDATE sessions SET last_seen_at=? WHERE id=?",
            (old_seen, session["session_id"]),
        )
        assert store.session_is_active(str(session["session_id"])) is True
        row = store._one(
            "SELECT last_seen_at FROM sessions WHERE id=?",
            (session["session_id"],),
        )
        assert row is not None
        assert float(row["last_seen_at"]) > old_seen + 60
    finally:
        store.close()


def test_remote_setup_form_collects_chinese_display_name() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "web" / "assets" / "app" / "main.mjs"
    ).read_text(encoding="utf-8")
    assert 'id="authDisplayName"' in source
    assert "display_name: authRoot.querySelector('#authDisplayName').value" in source


def test_secure_cookie_is_httponly_host_scoped_and_session_heartbeat_touches_last_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _server_app(tmp_path, monkeypatch)
    app = create_app(state)
    with TestClient(app, base_url="https://bili.example.test") as client:
        response = client.post(
            "/api/auth/setup",
            json={
                "username": "administrator",
                "display_name": "管理员",
                "password": "StrongPassword123",
                "bootstrap_token": "bootstrap-token-for-tests",
            },
        )
        assert response.status_code == 200, response.text
        cookie = response.headers.get("set-cookie", "")
        assert "__Host-bili_session=" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Domain=" not in cookie

        session_id = state.nas.list_sessions(
            str(response.json()["data"]["user"]["id"]), ""
        )[0]["id"]
        old_seen = time.time() - 300
        state.nas._execute(
            "UPDATE sessions SET last_seen_at=? WHERE id=?",
            (old_seen, session_id),
        )
        assert state.nas.session_is_active(str(session_id)) is True
        row = state.nas._one(
            "SELECT last_seen_at FROM sessions WHERE id=?",
            (session_id,),
        )
        assert row is not None
        assert float(row["last_seen_at"]) > old_seen + 60
    state.close()


def test_user_agent_is_sanitized_before_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        store.create_initial_admin(
            username="administrator",
            display_name="管理员",
            password="StrongPassword123",
        )
        _token, session = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="\x00Mozilla\n" + "A" * 600,
        )
        row = store._one("SELECT user_agent FROM sessions WHERE id=?", (session["session_id"],))
        assert row is not None
        value = str(row["user_agent"])
        assert "\x00" not in value
        assert "\n" not in value
        assert len(value) <= 512
    finally:
        store.close()


def test_session_ids_are_random_and_not_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        store.create_initial_admin(
            username="administrator",
            display_name="管理员",
            password="StrongPassword123",
        )
        ids = {
            store.login(
                "administrator",
                "StrongPassword123",
                remote_addr="127.0.0.1",
                user_agent=f"random-{index}",
            )[1]["session_id"]
            for index in range(5)
        }
        assert len(ids) == 5
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{32,}", value) for value in ids)
    finally:
        store.close()


def test_sessions_table_has_expected_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        with sqlite3.connect(store.path) as db:
            indexes = {row[1] for row in db.execute("PRAGMA index_list(sessions)")}
        assert "idx_sessions_token_hash" in indexes
        assert "idx_sessions_user_active" in indexes
    finally:
        store.close()
