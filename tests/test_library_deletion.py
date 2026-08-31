from __future__ import annotations

import sqlite3
from pathlib import Path

from app.path_safety import resolve_under
from tests.conftest import wait_terminal


def _downloaded_media(client, bvid: str) -> tuple[dict, Path]:
    created = client.post(
        "/api/download",
        json={"items": [{"bvid": bvid, "title": f"删除测试 {bvid}"}], "min_height": 0},
    ).json()["data"][0]
    assert wait_terminal(client.state_ref.queue, created["id"])["status"] == "success"
    client.state_ref.catalog_store.sync_index(force=True)
    listing = client.get(
        "/api/enhancements/library",
        params={"q": bvid},
    ).json()["data"]["items"]
    assert len(listing) == 1
    media = listing[0]
    entry = client.state_ref.index.get(str(media["source_key"]))
    assert entry is not None
    target = resolve_under(client.tmp_env.download_dir, str(entry["path"]))
    return media, target


def test_keep_files_commits_catalog_tags_and_tombstone_together(client) -> None:
    media, target = _downloaded_media(client, "BVKEEPFILES01")
    client.state_ref.tag_store.set_tags(media["source_key"], ["夯"])

    response = client.delete(
        f"/api/library/{media['id']}",
        params={"delete_files": "false"},
    )

    assert response.status_code == 200, response.text
    assert target.is_dir()
    assert client.state_ref.database.one(
        "SELECT id FROM media WHERE id=?",
        (media["id"],),
    ) is None
    assert client.state_ref.tag_store.tags_for_keys([media["source_key"]])[
        media["source_key"]
    ] == []
    tombstone = client.state_ref.deletion_store.for_keys([media["source_key"]])[
        media["source_key"]
    ]
    assert tombstone["files_deleted"] is False


def test_partial_file_failure_does_not_commit_logical_delete_and_can_retry(
    client,
    monkeypatch,
) -> None:
    media, target = _downloaded_media(client, "BVPARTFAIL01")
    client.state_ref.tag_store.set_tags(media["source_key"], ["夯"])
    original = client.state_ref.index.remove_entry_and_files

    def remove_one_file_then_fail(key: str) -> bool:
        entry = client.state_ref.index.get(key)
        assert entry is not None
        first = resolve_under(
            client.tmp_env.download_dir,
            str(entry["files"][0]["path"]),
        )
        first.unlink()
        raise OSError("注入文件删除中途失败")

    monkeypatch.setattr(
        client.state_ref.index,
        "remove_entry_and_files",
        remove_one_file_then_fail,
    )
    failed = client.delete(
        f"/api/library/{media['id']}",
        params={"delete_files": "true"},
    )

    assert failed.status_code == 409
    assert "注入文件删除中途失败" in failed.text
    assert client.state_ref.database.one(
        "SELECT id FROM media WHERE id=?",
        (media["id"],),
    ) is not None
    assert client.state_ref.tag_store.tags_for_keys([media["source_key"]])[
        media["source_key"]
    ] == ["夯"]
    assert client.state_ref.deletion_store.for_keys([media["source_key"]]) == {}
    assert client.state_ref.index.get(media["source_key"]) is not None
    assert target.is_dir()

    monkeypatch.setattr(client.state_ref.index, "remove_entry_and_files", original)
    retried = client.delete(
        f"/api/library/{media['id']}",
        params={"delete_files": "true"},
    )
    assert retried.status_code == 200, retried.text
    assert client.state_ref.database.one(
        "SELECT id FROM media WHERE id=?",
        (media["id"],),
    ) is None


def test_database_failure_restores_retryable_index_and_rolls_back_other_stores(
    client,
    monkeypatch,
) -> None:
    media, target = _downloaded_media(client, "BVDBFAIL0001")
    client.state_ref.tag_store.set_tags(media["source_key"], ["夯"])
    original = client.state_ref.deletion_store.record

    def fail_record(*args, **kwargs):
        del args, kwargs
        raise sqlite3.OperationalError("注入删除记录提交失败")

    monkeypatch.setattr(client.state_ref.deletion_store, "record", fail_record)
    failed = client.delete(
        f"/api/library/{media['id']}",
        params={"delete_files": "true"},
    )

    assert failed.status_code == 409
    assert not target.exists()
    assert client.state_ref.database.one(
        "SELECT id FROM media WHERE id=?",
        (media["id"],),
    ) is not None
    assert client.state_ref.tag_store.tags_for_keys([media["source_key"]])[
        media["source_key"]
    ] == ["夯"]
    assert client.state_ref.deletion_store.for_keys([media["source_key"]]) == {}
    assert client.state_ref.index.get(media["source_key"]) is not None

    monkeypatch.setattr(client.state_ref.deletion_store, "record", original)
    retried = client.delete(
        f"/api/library/{media['id']}",
        params={"delete_files": "true"},
    )
    assert retried.status_code == 200, retried.text


def test_batch_delete_commits_each_item_and_reports_mixed_result(
    client,
    monkeypatch,
) -> None:
    failed_media, _ = _downloaded_media(client, "BVBATCHFAIL1")
    good_media, _ = _downloaded_media(client, "BVBATCHGOOD1")
    original = client.state_ref.index.remove_entry_and_files

    def fail_selected(key: str) -> bool:
        if key == failed_media["source_key"]:
            raise OSError("注入单项失败")
        return original(key)

    monkeypatch.setattr(
        client.state_ref.index,
        "remove_entry_and_files",
        fail_selected,
    )
    response = client.post(
        "/api/enhancements/library/delete",
        json={
            "media_ids": [failed_media["id"], good_media["id"], good_media["id"]],
            "delete_files": True,
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["deleted"] == [good_media["id"]]
    assert failed_media["id"] in data["errors"]
    assert client.state_ref.database.one(
        "SELECT id FROM media WHERE id=?",
        (failed_media["id"],),
    ) is not None
    assert client.state_ref.database.one(
        "SELECT id FROM media WHERE id=?",
        (good_media["id"],),
    ) is None

    repeated = client.delete(
        f"/api/library/{good_media['id']}",
        params={"delete_files": "true"},
    )
    assert repeated.status_code == 404
