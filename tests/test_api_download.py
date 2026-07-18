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
