from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    validate_display_name,
    validate_password,
    validate_username,
)
from app.index_store import IndexStore
from app.main import create_app
from app.nas import NasStore
from app.runtime import RuntimeSettings
from app.state import AppState
from tests.conftest import StaticCookieChecker, artifact_runner


def _runtime(
    root: Path,
    *,
    mode: str = "server",
    auth_required: bool = True,
    cookie_secure: bool = False,
) -> RuntimeSettings:
    config = root / "config"
    media = root / "media"
    cache = root / "cache"
    temp = root / "tmp"
    bbdown = config / "bbdown"
    for path in (config, media, cache, temp, bbdown):
        path.mkdir(parents=True, exist_ok=True)
    return RuntimeSettings(
        mode=mode,
        config_dir=config,
        media_dir=media,
        cache_dir=cache,
        temp_dir=temp,
        database_path=root / "userdata" / "bili_workspace.db",
        bbdown_dir=bbdown,
        host="127.0.0.1" if mode == "local" else "0.0.0.0",
        port=3398,
        public_base_url="",
        trusted_hosts=("testserver", "127.0.0.1", "localhost"),
        trusted_proxy_ips=("127.0.0.1",),
        allow_ip_hosts=True,
        auth_required=auth_required,
        cookie_secure=cookie_secure,
        hsts_enabled=False,
        export_ttl_sec=86400,
        min_free_bytes=0,
        download_concurrency=1,
        transcode_threads=0,
    )


def _server_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NasStore:
    monkeypatch.setenv("BILI_BOOTSTRAP_TOKEN", "bootstrap-token-for-tests")
    runtime = _runtime(tmp_path)
    store = NasStore(runtime, IndexStore(runtime.media_dir))
    store.setup_admin(
        "administrator",
        "StrongPassword123",
        "bootstrap-token-for-tests",
        "管理员",
    )
    return store


def _server_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppState:
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
        "BILI_CACHE_DIR": str(tmp_path / "cache"),
        "BILI_TEMP_DIR": str(tmp_path / "tmp"),
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
    return AppState.create(
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )


def _setup_admin(client: TestClient) -> str:
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
    return str(response.json()["data"]["csrf_token"])


def test_account_validation_rules() -> None:
    assert validate_username("user_01") == "user_01"
    assert validate_username("Guest-a") == "Guest-a"
    for invalid in ("中文", "01user", "user name", "ab", "user@host"):
        with pytest.raises(ValueError):
            validate_username(invalid)

    assert validate_display_name("繁體名稱") == "繁體名稱"
    for invalid in ("A用户", "用户1", "用户 名", "用户。", "管"):
        with pytest.raises(ValueError):
            validate_display_name(invalid)

    assert validate_password("Password123") == "Password123"
    for invalid in (
        "short1A",
        "onlyletters",
        "1234567890",
        "Password 123",
        "密码Password123",
        "Password\n123",
    ):
        with pytest.raises(ValueError):
            validate_password(invalid)


def test_fresh_local_install_creates_restricted_default_admin(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, mode="local")
    store = NasStore(runtime, IndexStore(runtime.media_dir))
    try:
        users = store.list_users()
        assert len(users) == 1
        assert users[0]["username"] == "admin"
        assert users[0]["display_name"] == "管理员"
        assert users[0]["role"] == "admin"
        assert users[0]["must_change_password"] is True

        with pytest.raises(ValueError, match="回环"):
            store.login(
                "admin",
                "123456",
                remote_addr="192.168.1.20",
                user_agent="remote",
            )
        token, session = store.login(
            "admin", "123456", remote_addr="127.0.0.1", user_agent="local"
        )
        assert session["must_change_password"] is True
        assert store.get_session(token) is not None
        row = store._one("SELECT token_hash FROM sessions WHERE id=?", (session["session_id"],))
        assert row and row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(row)
    finally:
        store.close()


def test_default_admin_blocks_switch_to_remote_bind(tmp_path: Path) -> None:
    local_runtime = _runtime(tmp_path, mode="local")
    local = NasStore(local_runtime, IndexStore(local_runtime.media_dir))
    local.close()

    remote_runtime = _runtime(tmp_path, mode="server")
    with pytest.raises(RuntimeError, match="默认管理员密码尚未修改"):
        NasStore(remote_runtime, IndexStore(remote_runtime.media_dir))


def test_eleventh_login_evicts_oldest_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        sessions: list[tuple[str, dict]] = []
        for index in range(10):
            sessions.append(
                store.login(
                    "administrator",
                    "StrongPassword123",
                    remote_addr=f"127.0.0.{index + 1}",
                    user_agent=f"device-{index}",
                )
            )
        oldest_token, oldest = sessions[0]
        recently_used_token, recently_used = sessions[1]
        now = time.time()
        store._execute(
            "UPDATE sessions SET last_seen_at=?,created_at=? WHERE id=?",
            (now - 500, now - 600, oldest["session_id"]),
        )
        store._execute(
            "UPDATE sessions SET last_seen_at=?,created_at=? WHERE id=?",
            (now, now - 1000, recently_used["session_id"]),
        )

        newest_token, newest = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.99",
            user_agent="device-11",
        )

        assert store.active_session_count(str(newest["user_id"])) == 10
        assert store.get_session(oldest_token) is None
        assert store.get_session(recently_used_token) is not None
        assert store.get_session(newest_token) is not None
        revoked = store._one(
            "SELECT revoke_reason FROM sessions WHERE id=?", (oldest["session_id"],)
        )
        assert revoked and revoked["revoke_reason"] == "session_limit"
    finally:
        store.close()


def test_session_limit_tie_uses_created_at_and_new_session_is_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        items = [
            store.login(
                "administrator",
                "StrongPassword123",
                remote_addr="127.0.0.1",
                user_agent=str(index),
            )
            for index in range(10)
        ]
        base = time.time() - 100
        for index, (_token, session) in enumerate(items):
            store._execute(
                "UPDATE sessions SET last_seen_at=?,created_at=? WHERE id=?",
                (base, base + index, session["session_id"]),
            )
        token, new_session = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="new",
        )
        assert store.get_session(items[0][0]) is None
        assert store.get_session(items[1][0]) is not None
        assert store.get_session(token) is not None
        assert store.get_session_by_id(new_session["session_id"]) is not None
    finally:
        store.close()


def test_expired_and_revoked_sessions_do_not_consume_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        tokens = [
            store.login(
                "administrator",
                "StrongPassword123",
                remote_addr="127.0.0.1",
                user_agent=str(index),
            )
            for index in range(10)
        ]
        store._execute(
            "UPDATE sessions SET expires_at=? WHERE id=?",
            (time.time() - 1, tokens[0][1]["session_id"]),
        )
        store.logout(tokens[1][1]["session_id"])
        added = [
            store.login(
                "administrator",
                "StrongPassword123",
                remote_addr="127.0.0.1",
                user_agent=f"extra-{index}",
            )
            for index in range(2)
        ]
        assert store.active_session_count(str(added[0][1]["user_id"])) == 10
        assert all(store.get_session(token) is not None for token, _ in added)
    finally:
        store.close()


def test_concurrent_logins_still_leave_at_most_ten_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    barrier = threading.Barrier(12)

    def login(index: int) -> str:
        barrier.wait(timeout=10)
        token, _session = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr=f"127.0.1.{index + 1}",
            user_agent=f"parallel-{index}",
        )
        return token

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            tokens = list(pool.map(login, range(12)))
        user_id = str(store.list_users()[0]["id"])
        assert store.active_session_count(user_id) == 10
        assert sum(store.get_session(token) is not None for token in tokens) == 10
    finally:
        store.close()


def test_password_change_rotates_current_token_and_only_logout_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        first_token, first = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="first",
        )
        second_token, second = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="second",
        )
        changed = store.change_password(
            str(second["user_id"]),
            "StrongPassword123",
            "NewPassword456",
            keep_session_id=str(second["session_id"]),
        )
        new_token = str(changed["token"])
        assert changed["other_sessions_revoked"] == 1
        assert store.get_session(first_token) is None
        assert store.get_session(second_token) is None
        assert store.get_session(new_token) is not None

        third_token, third = store.login(
            "administrator",
            "NewPassword456",
            remote_addr="127.0.0.1",
            user_agent="third",
        )
        store.logout(str(third["session_id"]))
        assert store.get_session(third_token) is None
        assert store.get_session(new_token) is not None
    finally:
        store.close()


def test_admin_user_api_forced_password_and_session_csrf_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _server_app(tmp_path, monkeypatch)
    app = create_app(state)
    with TestClient(app, base_url="https://bili.example.test") as admin_client:
        admin_csrf = _setup_admin(admin_client)
        created = admin_client.post(
            "/api/admin/users",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "username": "guest-a",
                "display_name": "访客甲",
                "temporary_password": "Temporary123",
            },
        )
        assert created.status_code == 200, created.text
        user_id = str(created.json()["data"]["id"])

        with TestClient(app, base_url="https://bili.example.test") as user_client:
            login = user_client.post(
                "/api/auth/login",
                json={"username": "GUEST-A", "password": "Temporary123"},
            )
            assert login.status_code == 200, login.text
            user_csrf = str(login.json()["data"]["csrf_token"])
            assert login.json()["data"]["must_change_password"] is True

            blocked = user_client.get("/api/status")
            assert blocked.status_code == 403
            assert blocked.json()["code"] == "password_change_required"

            wrong_csrf = user_client.post(
                "/api/auth/password",
                headers={"X-CSRF-Token": admin_csrf},
                json={
                    "current_password": "Temporary123",
                    "new_password": "Permanent456",
                },
            )
            assert wrong_csrf.status_code == 403
            assert wrong_csrf.json()["code"] == "csrf_failed"

            changed = user_client.post(
                "/api/auth/password",
                headers={"X-CSRF-Token": user_csrf},
                json={
                    "current_password": "Temporary123",
                    "new_password": "Permanent456",
                },
            )
            assert changed.status_code == 200, changed.text
            user_csrf = str(changed.json()["data"]["csrf_token"])
            limited_status = user_client.get("/api/status")
            assert limited_status.status_code == 200
            assert "database_path" not in limited_status.text
            assert "download_dir" not in limited_status.text
            sessions = user_client.get("/api/auth/sessions")
            assert sessions.status_code == 200
            assert sessions.json()["data"]["items"][0]["current"] is True

            disabled = admin_client.patch(
                f"/api/admin/users/{user_id}",
                headers={"X-CSRF-Token": admin_csrf},
                json={"disabled": True},
            )
            assert disabled.status_code == 200, disabled.text
            assert user_client.get("/api/auth/sessions").status_code == 401


def test_database_and_audit_never_store_plain_session_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _server_store(tmp_path, monkeypatch)
    try:
        token, session = store.login(
            "administrator",
            "StrongPassword123",
            remote_addr="127.0.0.1",
            user_agent="privacy-test",
        )
        store.audit(
            str(session["user_id"]),
            "test.audit",
            "ordinary detail",
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
    source = (Path(__file__).resolve().parents[1] / "web" / "assets" / "app.js").read_text(
        encoding="utf-8"
    )
    assert 'id="authDisplayName"' in source
    assert "display_name:$('#authDisplayName').value" in source


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
        stale = time.time() - 120
        state.nas._execute(
            "UPDATE sessions SET last_seen_at=? WHERE id=?", (stale, session_id)
        )
        assert state.nas.session_is_active(str(session_id)) is True
        row = state.nas._one(
            "SELECT last_seen_at FROM sessions WHERE id=?", (session_id,)
        )
        assert row and float(row["last_seen_at"]) > stale + 60
