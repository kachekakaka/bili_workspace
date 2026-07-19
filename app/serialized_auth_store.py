from __future__ import annotations

import threading
from typing import Any

from app.index_store import IndexStore
from app.nas import NasStore
from app.runtime import RuntimeSettings


class SerializedAuthNasStore(NasStore):
    """Keep credential checks and session revocation linearizable.

    Password verification is intentionally performed before ``NasStore.login``
    opens its SQLite transaction. Without a separate account-operation lock, an
    administrator could disable a user, reset a password, or revoke all sessions
    in that gap and an in-flight login could insert a new session afterwards.
    Serializing only account/session mutations avoids that race without blocking
    unrelated library and task database access.
    """

    def __init__(
        self,
        runtime: RuntimeSettings,
        index: IndexStore,
        export_index: IndexStore | None = None,
    ) -> None:
        self._auth_mutation_lock = threading.RLock()
        super().__init__(runtime, index, export_index)

    def login(
        self,
        username: str,
        password: str,
        *,
        remote_addr: str,
        user_agent: str,
    ) -> tuple[str, dict[str, Any]]:
        with self._auth_mutation_lock:
            return super().login(
                username,
                password,
                remote_addr=remote_addr,
                user_agent=user_agent,
            )

    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        *,
        keep_session_id: str,
    ) -> dict[str, Any]:
        with self._auth_mutation_lock:
            return super().change_password(
                user_id,
                current_password,
                new_password,
                keep_session_id=keep_session_id,
            )

    def set_user_disabled(
        self,
        user_id: str,
        disabled: bool,
        *,
        actor_user_id: str,
    ) -> dict[str, Any]:
        with self._auth_mutation_lock:
            return super().set_user_disabled(
                user_id,
                disabled,
                actor_user_id=actor_user_id,
            )

    def reset_user_password(
        self,
        user_id: str,
        temporary_password: str,
        *,
        actor_user_id: str,
    ) -> dict[str, Any]:
        with self._auth_mutation_lock:
            return super().reset_user_password(
                user_id,
                temporary_password,
                actor_user_id=actor_user_id,
            )

    def revoke_session(
        self,
        user_id: str,
        session_id: str,
        *,
        current_session_id: str,
        reason: str = "user_revoke",
    ) -> bool:
        with self._auth_mutation_lock:
            return super().revoke_session(
                user_id,
                session_id,
                current_session_id=current_session_id,
                reason=reason,
            )

    def revoke_other_sessions(self, user_id: str, current_session_id: str) -> int:
        with self._auth_mutation_lock:
            return super().revoke_other_sessions(user_id, current_session_id)

    def revoke_all_sessions(self, user_id: str, reason: str) -> int:
        with self._auth_mutation_lock:
            return super().revoke_all_sessions(user_id, reason)

    def logout(self, session_id: str) -> None:
        with self._auth_mutation_lock:
            super().logout(session_id)
