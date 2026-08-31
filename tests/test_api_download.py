import time
from pathlib import Path


def _wait_terminal(client, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        task = response.json()["data"]
        if task["status"] in ("success", "failed", "skipped", "cancelled"):
            return task
        time.sleep(0.02)
    raise AssertionError("task not finished")


def test_download_success_then_skip_then_force(client):
    response = client.post("/api/download", json={"bvids": ["BV1qt4y1X7TW"]})
    body = response.json()
    assert body["ok"] is True
    task = _wait_terminal(client, body["data"][0]["id"])
    assert task["status"] == "success"
    assert task["output_path"].startswith("groups/未分组/items/")
    assert task["files"] and task["files"][0]["size"] > 0

    response = client.post("/api/download", json={"bvids": ["BV1qt4y1X7TW"]})
    assert response.json()["data"][0]["status"] == "skipped"

    final = Path(client.tmp_env.download_dir, task["output_path"], "demo.mp4")
    final.write_bytes(b"old")
    response = client.post(
        "/api/download", json={"bvids": ["BV1qt4y1X7TW"], "force": True}
    )
    forced = _wait_terminal(client, response.json()["data"][0]["id"])
    assert forced["status"] == "success"
    assert final.read_bytes() == b"video"


def test_download_invalid(client):
    response = client.post("/api/download", json={"urls": ["nope"]})
    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_batch_limit_is_explicit(client):
    values = [f"BV{i:010d}" for i in range(101)]
    response = client.post("/api/download", json={"bvids": values})
    assert response.status_code == 422

    response = client.post("/api/download", json={"urls": ["\n".join(values)]})
    assert response.status_code == 400
    assert "最多" in response.json()["error"]


def test_strict_selection_rejects_entire_admin_batch_on_library_conflict(client):
    first = client.post("/api/download", json={"bvids": ["BV1STRICT001"]})
    first_task = _wait_terminal(client, first.json()["data"][0]["id"])
    assert first_task["status"] == "success"

    rejected = client.post(
        "/api/download/selection",
        json={"bvids": ["BV1STRICT001", "BV1STRICT002"]},
    )
    assert rejected.status_code == 409
    body = rejected.json()
    assert body["code"] == "batch_conflict"
    assert body["data"]["items"] == [
        {
            "source_key": "BV1STRICT001",
            "code": "already_downloaded",
            "message": "作品已存在有效文件，需要确认重新下载",
        }
    ]
    assert client.state_ref.task_store.database.one(
        "SELECT id FROM task_records WHERE source_key='BV1STRICT002'"
    ) is None

    accepted = client.post(
        "/api/download/selection",
        json={
            "bvids": ["BV1STRICT001", "BV1STRICT002"],
            "force": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["total"] == 2
