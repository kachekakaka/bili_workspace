from __future__ import annotations

from app.index_store import IndexStore
from app.state import AppState
from tests.conftest import StaticCookieChecker, artifact_runner


def test_v04_index_is_imported_without_moving_media(tmp_env, external_runtime_environment):
    item_dir = tmp_env.download_dir / "groups" / "旧分组" / "items" / "BV0000000520"
    item_dir.mkdir(parents=True)
    media = item_dir / "旧作品 [BV0000000520] [1080P].mp4"
    media.write_bytes(b"legacy")
    index = IndexStore(tmp_env.download_dir)
    index.put(
        "BV0000000520",
        title="旧作品",
        path="groups/旧分组/items/BV0000000520",
        files=[
            {
                "path": "groups/旧分组/items/BV0000000520/旧作品 [BV0000000520] [1080P].mp4",
                "size": len(b"legacy"),
            }
        ],
        extra={
            "bvid": "BV0000000520",
            "group": "旧分组",
            "selected_quality": "1080P 高清",
            "selected_height": 1080,
            "selected_codec": "AVC",
        },
    )

    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    try:
        summary = state.catalog_store.library_summary()
        assert summary["media_count"] == 1
        item = state.catalog_store.library_list(
            page=1,
            page_size=20,
            query="",
            group_id="",
            sort="newest",
            user_id="local",
        )["items"][0]
        assert item["title"] == "旧作品"
        assert item["selected_height"] == 1080
        assert media.is_file()
    finally:
        state.stop()


def test_task_snapshots_survive_restart_and_running_becomes_interrupted(
    tmp_env, external_runtime_environment
):
    first = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    snapshot = {
        "id": "persisted-running",
        "key": "BV0000000521",
        "url": "https://www.bilibili.com/video/BV0000000521",
        "bvid": "BV0000000521",
        "force": False,
        "status": "running",
        "title": "重启中断测试",
        "created_at": 100.0,
        "started_at": 101.0,
    }
    first.task_store.save_task_snapshot("library", snapshot["id"], snapshot)
    first.stop()

    second = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    try:
        restored = second.queue.get_task("persisted-running")
        assert restored is not None
        assert restored["status"] == "failed"
        assert "服务重启" in restored["error"]
    finally:
        second.stop()


def test_index_sync_short_circuits_when_unchanged(tmp_env, external_runtime_environment):
    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    try:
        first = state.catalog_store.sync_index(force=True)
        second = state.catalog_store.sync_index()
        assert first["imported"] == 0
        assert second == {"imported": 0, "unchanged": 0, "skipped": 0, "removed": 0}
    finally:
        state.stop()


def test_index_sync_does_not_acknowledge_changes_after_its_snapshot(
    tmp_env, monkeypatch, external_runtime_environment
):
    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    original_snapshot = state.index.snapshot_if_changed
    captured_tokens = []
    mutate_after_first_snapshot = True

    def snapshot_with_concurrent_change(previous_token):
        nonlocal mutate_after_first_snapshot
        result = original_snapshot(previous_token)
        captured_tokens.append(result[0])
        if mutate_after_first_snapshot:
            mutate_after_first_snapshot = False
            with state.index._lock:
                state.index._revision += 1
        return result

    monkeypatch.setattr(state.index, "snapshot_if_changed", snapshot_with_concurrent_change)
    try:
        state.catalog_store.sync_index(force=True)
        assert state.catalog_store._last_index_token == captured_tokens[0]
        assert state.catalog_store._last_index_token != state.index.change_token()

        state.catalog_store.sync_index()
        assert len(captured_tokens) == 2
        assert state.catalog_store._last_index_token == captured_tokens[1]
        assert state.catalog_store._last_index_token == state.index.change_token()
    finally:
        state.stop()


def test_running_snapshot_writes_are_debounced(
    tmp_env, monkeypatch, external_runtime_environment
):
    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    try:
        writes = 0
        original = state.database.execute

        def counted(sql, params=()):
            nonlocal writes
            if sql.startswith("INSERT INTO task_records"):
                writes += 1
            return original(sql, params)

        monkeypatch.setattr(state.database, "execute", counted)
        payload = {
            "id": "debounced-running",
            "status": "running",
            "created_at": 100.0,
            "progress_percent": 1,
        }
        state.task_store.save_task_snapshot("library", payload["id"], payload)
        payload["progress_percent"] = 2
        state.task_store.save_task_snapshot("library", payload["id"], payload)
        assert writes == 1

        payload["status"] = "success"
        state.task_store.save_task_snapshot("library", payload["id"], payload)
        assert writes == 2
    finally:
        state.stop()


def test_running_transition_is_not_hidden_by_progress_debounce(
    tmp_env, external_runtime_environment
):
    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    payload = {
        "id": "queued-to-running",
        "owner_user_id": state.task_store.default_owner_user_id(),
        "status": "queued",
        "created_at": 100.0,
    }
    try:
        state.task_store.save_task_snapshot("library", payload["id"], payload)
        payload["status"] = "running"
        payload["started_at"] = 101.0
        state.task_store.save_task_snapshot("library", payload["id"], payload)

        record = state.task_store.task_record(payload["id"])
        assert record is not None
        assert record["status"] == "running"
        assert state.task_store.task_status_summary()["running"] == 1
    finally:
        state.stop()
