from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import pytest

import app.nas as nas_module
from app.index_store import IndexStore
from app.runtime import RuntimeSettings
from app.serialized_auth_store import SerializedAuthNasStore


def _runtime(root: Path) -> RuntimeSettings:
    for name in ("config", "media", "cache", "tmp", "bbdown", "userdata"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return RuntimeSettings(
        mode="server",
        config_dir=root / "config",
        media_dir=root / "media",
        cache_dir=root / "cache",
        temp_dir=root / "tmp",
        database_path=root / "userdata" / "bili_workspace.db",
        bbdown_dir=root / "bbdown",
        host="0.0.0.0",
        port=3398,
        public_base_url="",
        trusted_hosts=("testserver",),
        trusted_proxy_ips=("127.0.0.1",),
        allow_ip_hosts=True,
        auth_required=True,
        cookie_secure=False,
        hsts_enabled=False,
        export_ttl_sec=86400,
        min_free_bytes=0,
        download_concurrency=1,
        transcode_threads=0,
    )


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SerializedAuthNasStore, dict]:
    monkeypatch.setenv("BILI_BOOTSTRAP_TOKEN", "bootstrap-token-for-tests")
    runtime = _runtime(tmp_path)
    store = SerializedAuthNasStore(runtime, IndexStore(runtime.media_dir))
    admin = store.setup_admin(
        "administrator",
        "AdminPassword123",
        "bootstrap-token-for-tests",
        "管理员",
    )
    user = store.create_user(
        "race-user",
        "竞态用户",
        "Temporary123",
        created_by=str(admin["id"]),
    )
    return store, user


def _block_password_verification(
    monkeypatch: pytest.MonkeyPatch,
    password_to_block: str,
) -> tuple[threading.Event, threading.Event]:
    entered = threading.Event()
    release = threading.Event()
    original: Callable[[str, str], bool] = nas_module._verify_password

    def blocking_verify(password: str, encoded: str) -> bool:
        valid = original(password, encoded)
        if password == password_to_block:
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("password verification test gate timed out")
        return valid

    monkeypatch.setattr(nas_module, "_verify_password", blocking_verify)
    return entered, release


def test_disable_cannot_be_overtaken_by_inflight_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user = _store(tmp_path, monkeypatch)
    entered, release = _block_password_verification(monkeypatch, "Temporary123")
    login_result: dict[str, object] = {}
    errors: list[BaseException] = []
    disable_started = threading.Event()

    def login() -> None:
        try:
            token, session = store.login(
                "race-user",
                "Temporary123",
                remote_addr="127.0.0.1",
                user_agent="inflight-disable",
            )
            login_result.update(token=token, session=session)
        except BaseException as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    def disable() -> None:
        try:
            disable_started.set()
            store.set_user_disabled(
                str(user["id"]),
                True,
                actor_user_id="administrator",
            )
        except BaseException as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    login_thread = threading.Thread(target=login)
    disable_thread = threading.Thread(target=disable)
    try:
        login_thread.start()
        assert entered.wait(timeout=5)
        disable_thread.start()
        assert disable_started.wait(timeout=5)
        time.sleep(0.05)
        release.set()
        login_thread.join(timeout=5)
        disable_thread.join(timeout=5)

        assert not login_thread.is_alive()
        assert not disable_thread.is_alive()
        assert not errors
        token = str(login_result["token"])
        rows = store._all(
            "SELECT revoked_at,revoke_reason FROM sessions WHERE user_id=?",
            (str(user["id"]),),
        )
        assert rows
        assert all(row["revoked_at"] is not None for row in rows)
        assert any(row["revoke_reason"] == "user_disabled" for row in rows)

        store.set_user_disabled(
            str(user["id"]),
            False,
            actor_user_id="administrator",
        )
        assert store.get_session(token) is None
    finally:
        release.set()
        login_thread.join(timeout=1)
        disable_thread.join(timeout=1)
        store.close()


def test_password_reset_revokes_login_that_started_with_old_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user = _store(tmp_path, monkeypatch)
    entered, release = _block_password_verification(monkeypatch, "Temporary123")
    login_result: dict[str, object] = {}
    errors: list[BaseException] = []
    reset_started = threading.Event()

    def login() -> None:
        try:
            token, session = store.login(
                "race-user",
                "Temporary123",
                remote_addr="127.0.0.1",
                user_agent="inflight-reset",
            )
            login_result.update(token=token, session=session)
        except BaseException as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    def reset_password() -> None:
        try:
            reset_started.set()
            store.reset_user_password(
                str(user["id"]),
                "Replacement456",
                actor_user_id="administrator",
            )
        except BaseException as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    login_thread = threading.Thread(target=login)
    reset_thread = threading.Thread(target=reset_password)
    try:
        login_thread.start()
        assert entered.wait(timeout=5)
        reset_thread.start()
        assert reset_started.wait(timeout=5)
        time.sleep(0.05)
        release.set()
        login_thread.join(timeout=5)
        reset_thread.join(timeout=5)

        assert not login_thread.is_alive()
        assert not reset_thread.is_alive()
        assert not errors
        token = str(login_result["token"])
        assert store.get_session(token) is None
        rows = store._all(
            "SELECT revoked_at,revoke_reason FROM sessions WHERE user_id=?",
            (str(user["id"]),),
        )
        assert rows
        assert all(row["revoked_at"] is not None for row in rows)
        assert any(row["revoke_reason"] == "admin_password_reset" for row in rows)

        with pytest.raises(ValueError, match="用户名或密码错误"):
            store.login(
                "race-user",
                "Temporary123",
                remote_addr="127.0.0.1",
                user_agent="old-password",
            )
        new_token, new_session = store.login(
            "race-user",
            "Replacement456",
            remote_addr="127.0.0.1",
            user_agent="new-password",
        )
        assert new_token
        assert new_session["must_change_password"] is True
    finally:
        release.set()
        login_thread.join(timeout=1)
        reset_thread.join(timeout=1)
        store.close()
