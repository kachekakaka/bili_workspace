from __future__ import annotations

from pathlib import Path

from tests.conftest import wait_terminal


ROOT = Path(__file__).resolve().parent.parent
ASSETS = (
    "enhancements-core.js",
    "enhancements-search.js",
    "enhancements-library.js",
    "enhancements-task-actions.js",
    "enhancements-tasks.js",
)


def test_enhancement_assets_are_loaded_in_dependency_order():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    positions = []
    for name in ASSETS:
        path = ROOT / "web" / "assets" / name
        assert path.is_file()
        positions.append(index.index(f"/assets/{name}"))
    assert positions == sorted(positions)
    assert index.index("/assets/app.js") < positions[0]
    assert "/assets/enhancements.css" in index
    assert not (ROOT / ".github" / "materialize").exists()


def test_enhanced_frontend_exposes_requested_controls():
    search = (ROOT / "web" / "assets" / "enhancements-search.js").read_text(encoding="utf-8")
    library = (ROOT / "web" / "assets" / "enhancements-library.js").read_text(encoding="utf-8")
    tasks = (ROOT / "web" / "assets" / "enhancements-tasks.js").read_text(encoding="utf-8")
    actions = (ROOT / "web" / "assets" / "enhancements-task-actions.js").read_text(encoding="utf-8")

    for token in ("隐藏已经下载过的作品", "B站原页面", "data-search-page", "tags/bulk"):
        assert token in search
    for token in ("enhLibraryTag", "下载到设备", "删除选中", "mark_tag: '不要'"):
        assert token in library
    for token in ("全部重试失败", "批量暂停", "当前大小", "speed_text", "task.duration"):
        assert token in tasks
    for token in ("编辑画质并重试", "min_height", "preferred_quality", "原任务 ID"):
        assert token in actions


def test_retry_enhancement_reuses_task_id_and_updates_quality(client):
    created = client.post(
        "/api/download",
        json={"bvids": ["BV0000000981"], "min_height": 0},
    ).json()["data"][0]
    completed = wait_terminal(client.state_ref.queue, created["id"])
    assert completed["status"] == "success"

    response = client.post(
        f"/api/enhancements/tasks/{created['id']}/retry",
        json={"force": False, "min_height": 720, "preferred_quality": ""},
    )
    assert response.status_code == 200
    retried = response.json()["data"]
    assert retried["id"] == created["id"]
    assert retried["min_height"] == 720
    assert retried["status"] in {"queued", "running"}

    finished = wait_terminal(client.state_ref.queue, created["id"])
    assert finished["status"] == "success"
    assert sum(task["id"] == created["id"] for task in client.state_ref.queue.list_tasks()) == 1


def test_tags_round_trip_and_filter_the_library(client):
    created = client.post(
        "/api/download",
        json={
            "items": [
                {
                    "bvid": "BV0000000982",
                    "title": "标签筛选测试",
                    "author": "测试UP",
                }
            ],
            "min_height": 0,
        },
    ).json()["data"][0]
    assert wait_terminal(client.state_ref.queue, created["id"])["status"] == "success"
    client.state_ref.nas.sync_index(force=True)

    library = client.get("/api/enhancements/library", params={"q": "BV0000000982"})
    assert library.status_code == 200
    item = library.json()["data"]["items"][0]

    assigned = client.put(
        "/api/enhancements/tags",
        json={"source_key": item["source_key"], "media_id": item["id"], "tags": ["夯"]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["data"]["tags"] == ["夯"]

    filtered = client.get("/api/enhancements/library", params={"tag": "夯"})
    assert filtered.status_code == 200
    assert item["id"] in {row["id"] for row in filtered.json()["data"]["items"]}
