from __future__ import annotations

from tests.conftest import wait_terminal


def _download_one(client, bvid: str = "BV0000000501") -> dict:
    response = client.post(
        "/api/download",
        json={
            "items": [{"bvid": bvid, "title": "V0.5 媒体测试"}],
            "group": "媒体测试",
            "min_height": 1080,
        },
    )
    assert response.status_code == 200
    return wait_terminal(client.state_ref.queue, response.json()["data"][0]["id"])


def test_library_import_range_head_and_invalid_range(client):
    task = _download_one(client)
    assert task["status"] == "success"

    library = client.get("/api/library?page=1&page_size=10")
    assert library.status_code == 200
    item = library.json()["data"]["items"][0]
    assert item["title"] == "V0.5 媒体测试"
    file_id = item["primary_file_id"]

    ranged = client.get(
        f"/api/media/{file_id}/stream", headers={"Range": "bytes=1-3"}
    )
    assert ranged.status_code == 206
    assert ranged.content == b"ide"
    assert ranged.headers["content-range"] == "bytes 1-3/5"
    assert ranged.headers["accept-ranges"] == "bytes"

    head = client.head(f"/api/media/{file_id}/stream")
    assert head.status_code == 200
    assert head.headers["content-length"] == "5"
    assert head.content == b""

    invalid = client.get(
        f"/api/media/{file_id}/stream", headers={"Range": "bytes=99-100"}
    )
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == "bytes */5"


def test_watch_progress_and_library_filters(client):
    _download_one(client, "BV0000000502")
    item = client.get("/api/library?page=1&page_size=10").json()["data"]["items"][0]
    media_id = item["id"]
    file_id = item["primary_file_id"]

    progress = client.put(
        f"/api/library/{media_id}/progress",
        json={"file_id": file_id, "position_sec": 32, "duration_sec": 120},
    )
    assert progress.status_code == 200
    assert progress.json()["data"]["completed"] is False

    watching = client.get("/api/library?watched=watching").json()["data"]
    assert watching["total"] == 1
    assert client.get("/api/library?watched=unwatched").json()["data"]["total"] == 0
    assert client.get("/api/library?codec=hevc").json()["data"]["total"] == 1
    assert client.get("/api/library?codec=av1").json()["data"]["total"] == 0
    assert client.get("/api/library?min_height=2160").json()["data"]["total"] == 1
    assert client.get("/api/library?min_height=4320").json()["data"]["total"] == 0

    finished = client.put(
        f"/api/library/{media_id}/progress",
        json={"file_id": file_id, "position_sec": 118, "duration_sec": 120},
    )
    assert finished.json()["data"]["completed"] is True
    assert client.get("/api/library?watched=completed").json()["data"]["total"] == 1


def test_group_rename_is_logical_and_survives_index_resync(client):
    task = _download_one(client, "BV0000000503")
    old_output = task["output_path"]
    groups = client.get("/api/groups").json()["data"]["records"]
    group = next(item for item in groups if item["display_name"] == "媒体测试")

    renamed = client.patch(
        f"/api/groups/{group['id']}", json={"name": "重命名后的媒体组"}
    )
    assert renamed.status_code == 200
    client.state_ref.nas.sync_index(force=True)

    entry = client.state_ref.index.get("BV0000000503")
    assert entry["group"] == "重命名后的媒体组"
    assert entry["path"] == old_output
    result = client.get(f"/api/library?group_id={group['id']}").json()["data"]
    assert result["total"] == 1
    assert result["items"][0]["group_name"] == "重命名后的媒体组"


def test_task_list_is_compact_but_detail_remains_complete(client):
    task = _download_one(client, "BV0000000504")
    listed = client.get("/api/tasks").json()["data"]
    row = next(item for item in listed if item["id"] == task["id"])
    assert "log_tail" not in row
    assert "files" not in row
    assert "selected_tracks" not in row
    assert row["total_size"] == 5

    detail = client.get(f"/api/tasks/{task['id']}").json()["data"]
    assert detail["files"]
    assert "log_tail" in detail
