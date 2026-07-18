from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import wait_terminal


def test_download_metadata_is_retained_and_log_is_available(client):
    response = client.post(
        "/api/download",
        json={
            "items": [
                {
                    "bvid": "BV1qt4y1X7TW",
                    "url": "https://www.bilibili.com/video/BV1qt4y1X7TW",
                    "title": "元数据标题",
                    "cover": "https://i0.hdslb.com/bfs/archive/demo.jpg",
                    "author": "测试UP",
                    "pubdate": 1700000000,
                    "duration": "03:21",
                    "play": 12345,
                }
            ]
        },
    )
    assert response.status_code == 200
    created = response.json()["data"][0]
    task = wait_terminal(client.state_ref.queue, created["id"])
    assert task["status"] == "success"
    assert task["title"] == "元数据标题"
    assert task["author"] == "测试UP"
    assert task["cover"].startswith("https://i0.hdslb.com/")
    assert task["progress_percent"] == 100.0
    assert task["log_available"] is True

    log_response = client.get(f"/api/tasks/{task['id']}/log", params={"tail": 20000})
    assert log_response.status_code == 200
    assert "开始执行" in log_response.json()["data"]["text"]
    download = client.get(f"/api/tasks/{task['id']}/log/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/plain")
    assert "task-" in download.headers["content-disposition"]


def test_untrusted_cover_metadata_is_removed(client):
    response = client.post(
        "/api/download",
        json={"items": [{"bvid": "BV0000000010", "cover": "https://evil.example/track.jpg"}]},
    )
    created = response.json()["data"][0]
    assert created["cover"] == ""


def test_force_retry_endpoint_creates_a_new_task(client):
    first = client.post("/api/download", json={"bvids": ["BV0000000011"]}).json()["data"][0]
    completed = wait_terminal(client.state_ref.queue, first["id"])
    assert completed["status"] == "success"
    response = client.post(f"/api/tasks/{first['id']}/retry", json={"force": True})
    assert response.status_code == 200
    retried = response.json()["data"][0]
    assert retried["retry_of"] == first["id"]
    assert retried["force"] is True
    assert wait_terminal(client.state_ref.queue, retried["id"])["status"] == "success"


def test_tasks_response_contains_summary(client):
    client.post("/api/download", json={"bvids": ["BV0000000012"]})
    response = client.get("/api/tasks")
    body = response.json()
    assert body["ok"] is True
    assert "summary" in body
    assert body["summary"]["all"] >= 1


def test_search_marks_existing_index_as_downloaded(client, tmp_env):
    directory = tmp_env.download_dir / "items" / "BV1qt4y1X7TW"
    directory.mkdir(parents=True)
    video = directory / "demo.mp4"
    video.write_bytes(b"x")
    stat = video.stat()
    client.state_ref.index.put(
        "BV1qt4y1X7TW",
        title="已下载标题",
        path="items/BV1qt4y1X7TW",
        files=[{
            "path": "items/BV1qt4y1X7TW/demo.mp4",
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }],
    )
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "numPages": 2,
            "numResults": 21,
            "result": [{
                "bvid": "BV1qt4y1X7TW",
                "title": "<em class=\"keyword\">测试</em>标题",
                "author": "UP",
                "play": 100,
                "duration": "01:30",
                "pubdate": 1700000000,
                "pic": "//i0.hdslb.com/demo.jpg",
            }],
        },
    }
    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    mock_client.close.return_value = None
    with patch(
        "app.search.fetch_wbi_keys",
        return_value=("7cd084941338484aae1ad9425b84077c", "4932caff0ff7463802950c7033c9cdac"),
    ), patch("app.search.httpx.Client", return_value=mock_client):
        response = client.get("/api/search", params={"q": "测试"})
    item = response.json()["data"]["items"][0]
    assert item["local_status"] == "downloaded"
    assert item["output_path"] == "items/BV1qt4y1X7TW"
    assert item["duration_seconds"] == 90
    assert item["cover"] == "https://i0.hdslb.com/demo.jpg"
