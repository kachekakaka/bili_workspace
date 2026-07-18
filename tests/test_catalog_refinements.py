from __future__ import annotations

import json
from pathlib import Path

from app.catalog_overrides import parse_title_search_terms, search_videos_title_mode
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


def test_search_term_parser_supports_parentheses_and_spaces():
    assert parse_title_search_terms("(测试 原因) 测试") == ["测试", "原因"]
    assert parse_title_search_terms("甲，乙；丙") == ["甲", "乙", "丙"]


def test_title_search_calls_original_query_once_and_filters_titles(monkeypatch, tmp_env):
    calls: list[str] = []
    original_results = [
        _search_item("BVWORD000001", "测试失败原因分析"),
        _search_item("BVWORD000002", "测试工具", author="原因UP"),
        _search_item("BVWORD000003", "故障原因"),
        _search_item("BVWORD000004", "完全无关", author="测试 原因"),
    ]

    def fake_search(keyword, *, order, page, bbdown_dir):
        del order, page, bbdown_dir
        calls.append(keyword)
        return {
            "items": list(original_results),
            "page": 1,
            "pages": 25,
            "total": 500,
            "cached": False,
        }

    monkeypatch.setattr("app.catalog_overrides.search_videos", fake_search)

    precise = search_videos_title_mode(
        "(测试 原因)",
        mode="all",
        order="totalrank",
        page=1,
        bbdown_dir=tmp_env.bbdown_dir,
    )
    assert calls == ["(测试 原因)"]
    assert [item["bvid"] for item in precise["items"]] == ["BVWORD000001"]
    assert precise["query_terms"] == ["测试", "原因"]
    assert precise["source_queries"] == ["(测试 原因)"]
    assert precise["source_count"] == 1

    calls.clear()
    fuzzy = search_videos_title_mode(
        "(测试 原因)",
        mode="any",
        order="totalrank",
        page=1,
        bbdown_dir=tmp_env.bbdown_dir,
    )
    assert calls == ["(测试 原因)"]
    assert {item["bvid"] for item in fuzzy["items"]} == {
        "BVWORD000001",
        "BVWORD000002",
        "BVWORD000003",
    }
    # Author/BV matches never make a title-only result pass.
    assert "BVWORD000004" not in {item["bvid"] for item in fuzzy["items"]}

    calls.clear()
    raw = search_videos_title_mode(
        "(测试 原因)",
        mode="raw",
        order="totalrank",
        page=1,
        bbdown_dir=tmp_env.bbdown_dir,
    )
    assert calls == ["(测试 原因)"]
    assert [item["bvid"] for item in raw["items"]] == [
        "BVWORD000001",
        "BVWORD000002",
        "BVWORD000003",
        "BVWORD000004",
    ]


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

    def fake_search(keyword, *, order, page, bbdown_dir):
        del order, page, bbdown_dir
        return {
            "keyword": keyword,
            "items": [_search_item(bvid, "以后不要忘记已删除")],
            "page": 1,
            "pages": 1,
            "total": 1,
            "cached": False,
        }

    monkeypatch.setattr("app.catalog_overrides.search_videos", fake_search)
    searched = client.get(
        "/api/search",
        params={"q": "删除", "mode": "raw", "fresh": "true"},
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
        params={"q": "删除", "mode": "raw", "fresh": "true"},
    ).json()["data"]["items"][0]
    assert searched_again["local_status"] == "downloaded"
    assert client.app.state.deletion_store.for_keys([bvid]) == {}


def test_frontend_exposes_search_modes_chips_group_move_and_ten_pages():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    search = (ROOT / "web" / "assets" / "enhancements-search-overlay.js").read_text(
        encoding="utf-8"
    )
    deletion = (ROOT / "web" / "assets" / "enhancements-deletion-status.js").read_text(
        encoding="utf-8"
    )
    library = (ROOT / "web" / "assets" / "enhancements-library-overlay.js").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "web" / "assets" / "enhancements-catalog-v2.css").read_text(
        encoding="utf-8"
    )
    assert index.index("enhancements-search.js") < index.index("enhancements-search-overlay.js")
    assert index.index("enhancements-polish.js") < index.index("enhancements-deletion-status.js")
    assert index.index("enhancements-library.js") < index.index("enhancements-library-overlay.js")
    for token in (
        "精准：匹配全部词",
        "模糊：匹配任一词",
        "原始：B站直接结果",
        "再显示10页",
        "search.cache.clear()",
        "fresh: fresh ? 'true' : 'false'",
    ):
        assert token in search
    for token in (
        "精准：标题匹配全部词",
        "模糊：标题匹配任一词",
        "屏蔽已下载和已删除",
        "local_status === 'deleted'",
        "以前被你删除过",
    ):
        assert token in deletion
    for token in ("无标签", "data-library-group-chip", "data-catalog-move", "修改作品分组"):
        assert token in library
    assert ".enh-chip-strip" in css
    assert ".enh-colored-filter-chip" in css


def test_default_tag_palette_uses_distinct_colors():
    payload = json.loads((ROOT / "config" / "tags.json.default").read_text(encoding="utf-8"))
    colors = {item["name"]: item["color"] for item in payload["tags"]}
    assert colors["夯"] == "#d4a017"
    assert len(set(colors.values())) == len(colors)
