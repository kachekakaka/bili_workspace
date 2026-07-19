from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import wait_terminal

ROOT = Path(__file__).resolve().parent.parent


def _search_item(bvid: str, title: str, *, author: str = "UP主") -> dict:
    return {
        "bvid": bvid,
        "title": title,
        "author": author,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "cover": "",
        "duration": "01:00",
        "pubdate": 1_700_000_000,
        "play": 100,
    }


def test_untagged_filter_and_media_group_move(client):
    first = client.post(
        "/api/download",
        json={"items": [{"bvid": "BVUNTAG00001", "title": "有标签作品"}], "min_height": 0},
    ).json()["data"][0]
    second = client.post(
        "/api/download",
        json={"items": [{"bvid": "BVUNTAG00002", "title": "无标签作品"}], "min_height": 0},
    ).json()["data"][0]
    assert wait_terminal(client.state_ref.queue, first["id"])["status"] == "success"
    assert wait_terminal(client.state_ref.queue, second["id"])["status"] == "success"
    client.state_ref.nas.sync_index(force=True)

    listing = client.get("/api/enhancements/library", params={"q": "BVUNTAG"}).json()["data"]
    by_key = {item["source_key"]: item for item in listing["items"]}
    tagged = by_key["BVUNTAG00001"]
    untagged = by_key["BVUNTAG00002"]
    assigned = client.put(
        "/api/enhancements/tags",
        json={"source_key": tagged["source_key"], "media_id": tagged["id"], "tags": ["夯"]},
    )
    assert assigned.status_code == 200

    filtered = client.get(
        "/api/enhancements/library", params={"tag": "__untagged__"}
    ).json()["data"]
    ids = {item["id"] for item in filtered["items"]}
    assert untagged["id"] in ids
    assert tagged["id"] not in ids

    group = client.post("/api/groups", json={"name": "重新分组"}).json()["data"]
    moved = client.post(
        f"/api/library/{untagged['id']}/move", json={"group_id": group["id"]}
    )
    assert moved.status_code == 200
    grouped = client.get(
        "/api/enhancements/library", params={"group_id": group["id"]}
    ).json()["data"]
    assert untagged["id"] in {item["id"] for item in grouped["items"]}


def test_deleted_work_is_tombstoned_hidden_from_library_and_marked_in_search(
    client, monkeypatch
):
    bvid = "BVDELETE0001"
    created = client.post(
        "/api/download",
        json={"items": [{"bvid": bvid, "title": "以后不要忘记已删除"}], "min_height": 0},
    ).json()["data"][0]
    assert wait_terminal(client.state_ref.queue, created["id"])["status"] == "success"
    client.state_ref.nas.sync_index(force=True)

    listing = client.get("/api/enhancements/library", params={"q": bvid}).json()["data"]
    media = listing["items"][0]
    removed = client.post(
        "/api/enhancements/library/delete",
        json={"media_ids": [media["id"]], "delete_files": True, "mark_tag": "不要"},
    )
    assert removed.status_code == 200
    assert removed.json()["data"]["deleted_recorded"] is True
    assert removed.json()["data"]["marked_tag"] == ""
    assert client.get("/api/enhancements/library", params={"q": bvid}).json()["data"]["items"] == []
    assert client.app.state.deletion_store.for_keys([bvid])[bvid]["title"] == "以后不要忘记已删除"
    assert client.app.state.tag_store.tags_for_keys([bvid])[bvid] == []

    def fake_search(keyword, *, order, page, bbdown_dir, fresh=False):
        del order, page, bbdown_dir, fresh
        return {
            "keyword": keyword,
            "items": [_search_item(bvid, "以后不要忘记已删除")],
            "page": 1,
            "pages": 1,
            "total": 1,
            "cached": False,
        }

    monkeypatch.setattr("app.api.search_videos", fake_search)
    searched = client.get(
        "/api/search",
        params={"q": "删除", "fresh": "true"},
    ).json()["data"]["items"][0]
    assert searched["local_status"] == "deleted"
    assert searched["local_status_label"] == "已删除"
    assert searched["deleted_record"] is True

    # An explicit re-download is allowed; once a valid file exists again, the
    # tombstone is cleared and search returns the normal downloaded state.
    redownload = client.post(
        "/api/download",
        json={"items": [{"bvid": bvid, "title": "重新下载"}], "min_height": 0},
    ).json()["data"][0]
    assert wait_terminal(client.state_ref.queue, redownload["id"])["status"] == "success"
    client.state_ref.nas.sync_index(force=True)
    searched_again = client.get(
        "/api/search",
        params={"q": "删除", "fresh": "true"},
    ).json()["data"]["items"][0]
    assert searched_again["local_status"] == "downloaded"
    assert client.app.state.deletion_store.for_keys([bvid]) == {}


def test_frontend_search_is_integrated_without_overlay_competition():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    search = (ROOT / "web" / "assets" / "enhancements-search.js").read_text(
        encoding="utf-8"
    )
    library = (ROOT / "web" / "assets" / "enhancements-library-overlay.js").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "web" / "assets" / "enhancements-catalog-v2.css").read_text(
        encoding="utf-8"
    )
    app = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")

    assert "enhancements-search-overlay.js" not in index
    assert "enhancements-deletion-status.js" not in index
    assert not (ROOT / "web" / "assets" / "enhancements-search-overlay.js").exists()
    assert not (ROOT / "web" / "assets" / "enhancements-deletion-status.js").exists()
    assert "function renderSearch(" not in app
    assert "AUTO_RENDER_PAGES = new Set(['library', 'tasks'])" in (ROOT / "web" / "assets" / "enhancements-core.js").read_text(encoding="utf-8")
    for token in (
        "精准：标题包含全部词",
        "模糊：标题包含任意词",
        "屏蔽已下载和已删除",
        "AbortController",
        "requestIdleCallback",
        "navigator.connection",
        "刷新B站结果",
        "本页没有标题匹配项，可查看下一页；系统不会自动抓取全部页面。",
    ):
        assert token in search
    for forbidden in ("tags/bulk", "MutationObserver", "insertBefore", "enh-spacer"):
        assert forbidden not in search
    for token in ("无标签", "data-library-group-chip", "data-catalog-move", "修改作品分组"):
        assert token in library
    assert ".enh-chip-strip" in css
    assert ".enh-colored-filter-chip" in css


def test_default_tag_palette_uses_distinct_colors():
    payload = json.loads((ROOT / "config" / "tags.json.default").read_text(encoding="utf-8"))
    colors = {item["name"]: item["color"] for item in payload["tags"]}
    assert colors["夯"] == "#d4a017"
    assert len(set(colors.values())) == len(colors)
