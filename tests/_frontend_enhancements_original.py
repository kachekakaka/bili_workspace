from __future__ import annotations

from pathlib import Path

from app.tag_store import _duration_seconds
from tests.conftest import wait_terminal


ROOT = Path(__file__).resolve().parent.parent


def test_frontend_assets_use_the_final_module_entry_and_semantic_styles():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "/assets/app/main.mjs" in index
    assert "/assets/qrcode.min.js" in index
    assert "/assets/styles/tokens.css" in index
    assert "/assets/styles/base.css" in index
    assert "/assets/styles/components.css" in index
    assert "/assets/styles/pages.css" in index
    for removed in (
        "/assets/app.js",
        "/assets/enhancements-core.js",
        "/assets/browser-version.js",
        "/assets/enhancements.css",
        "/assets/ui-v062.css",
    ):
        assert removed not in index
    assert not (ROOT / ".github" / "materialize").exists()


def test_frontend_exposes_requested_controls_after_final_migration():
    search = (ROOT / "web" / "assets" / "app" / "pages" / "search.mjs").read_text(
        encoding="utf-8"
    )
    library = (ROOT / "web" / "assets" / "app" / "pages" / "library.mjs").read_text(
        encoding="utf-8"
    )
    tasks = (ROOT / "web" / "assets" / "app" / "pages" / "tasks.mjs").read_text(
        encoding="utf-8"
    )
    dashboard = (ROOT / "web" / "assets" / "app" / "pages" / "dashboard.mjs").read_text(
        encoding="utf-8"
    )
    download = (ROOT / "web" / "assets" / "app" / "pages" / "download.mjs").read_text(
        encoding="utf-8"
    )

    for token in (
        "屏蔽已下载和已删除",
        "B站原页面",
        "data-search-page",
        "标题二级筛选",
        "刷新B站结果",
        "shouldPrefetchNextPage",
        "requestGeneration",
        "仍停留在搜索页",
    ):
        assert token in search
    for token in (
        "enhLibraryTag",
        "enhLibrarySortField",
        "duration",
        "group",
        "tag",
        "下载到设备",
        "__untagged__",
        "data-library-move",
        "enhMediaPlayer",
        "mark_tag: ''",
    ):
        assert token in library
    for token in (
        "enhTaskOwner",
        "enhTaskSort",
        "enhTaskDirection",
        "按用户分组显示",
        "owner_user_id",
        "全部重试失败",
        "当前大小",
        "speed_text",
        "task.duration",
        "编辑画质并重试",
        "min_height",
        "preferred_quality",
        "原任务 ID",
    ):
        assert token in tasks
    assert "enh-dashboard-stack" in dashboard
    assert 'id="downloadForm"' in download


def test_duration_text_is_sortable():
    assert _duration_seconds("03:21") == 201
    assert _duration_seconds("2:03:04 · 12P") == 7384
    assert _duration_seconds("") == 0
    assert _duration_seconds("未知") == 0


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


def test_library_supports_duration_size_group_and_tag_sorting(client):
    specs = [
        ("BV0000000991", "作品 A", "00:30", 300, "A组", "NPC"),
        ("BV0000000992", "作品 B", "02:00", 100, "B组", "夯"),
        ("BV0000000993", "作品 C", "01:00", 200, "C组", "顶级"),
    ]
    task_ids = []
    for bvid, title, duration, _, _, _ in specs:
        response = client.post(
            "/api/download",
            json={
                "items": [{"bvid": bvid, "title": title, "duration": duration}],
                "min_height": 0,
            },
        )
        task_ids.append(response.json()["data"][0]["id"])
    for task_id in task_ids:
        assert wait_terminal(client.state_ref.queue, task_id)["status"] == "success"
    client.state_ref.nas.sync_index(force=True)

    rows_by_bvid = {}
    for bvid, *_ in specs:
        response = client.get("/api/enhancements/library", params={"q": bvid})
        rows_by_bvid[bvid] = response.json()["data"]["items"][0]

    groups = {
        name: client.post("/api/groups", json={"name": name}).json()["data"]
        for name in ("A组", "B组", "C组")
    }
    for bvid, _, duration, size, group_name, tag in specs:
        row = rows_by_bvid[bvid]
        client.state_ref.nas._execute(
            "UPDATE media SET duration_text=?,total_size=?,group_id=? WHERE id=?",
            (duration, size, groups[group_name]["id"], row["id"]),
        )
        assigned = client.put(
            "/api/enhancements/tags",
            json={"source_key": row["source_key"], "media_id": row["id"], "tags": [tag]},
        )
        assert assigned.status_code == 200

    def titles(sort: str) -> list[str]:
        response = client.get(
            "/api/enhancements/library",
            params={"page_size": 100, "sort": sort},
        )
        assert response.status_code == 200
        return [row["title"] for row in response.json()["data"]["items"]]

    assert titles("duration_asc") == ["作品 A", "作品 C", "作品 B"]
    assert titles("duration_desc") == ["作品 B", "作品 C", "作品 A"]
    assert titles("size_asc") == ["作品 B", "作品 C", "作品 A"]
    assert titles("size_desc") == ["作品 A", "作品 C", "作品 B"]
    assert titles("group_asc") == ["作品 A", "作品 B", "作品 C"]
    assert titles("group_desc") == ["作品 C", "作品 B", "作品 A"]
    assert titles("tag_asc")[0] == "作品 A"
    assert titles("tag_desc")[-1] == "作品 A"
