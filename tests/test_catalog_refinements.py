from __future__ import annotations

import json
from pathlib import Path

from app.refinement_api import parse_search_terms, search_videos_by_mode
from tests.conftest import wait_terminal

ROOT = Path(__file__).resolve().parent.parent


def _search_item(bvid: str, title: str) -> dict:
    return {
        "bvid": bvid,
        "title": title,
        "author": "测试UP",
        "url": f"https://www.bilibili.com/video/{bvid}",
        "cover": "",
        "duration": "01:00",
        "pubdate": 1_700_000_000,
        "play": 100,
    }


def test_search_term_parser_supports_parentheses_and_spaces():
    assert parse_search_terms("(测试 原因) 测试") == ["测试", "原因"]
    assert parse_search_terms("甲，乙；丙") == ["甲", "乙", "丙"]


def test_word_search_modes_filter_all_or_any_terms(monkeypatch, tmp_env):
    calls: list[str] = []

    def fake_search(keyword, *, order, page, bbdown_dir):
        del order, page, bbdown_dir
        calls.append(keyword)
        values = {
            "测试 原因": [
                _search_item("BVWORD000001", "测试失败原因分析"),
                _search_item("BVWORD000002", "测试工具"),
            ],
            "测试": [
                _search_item("BVWORD000001", "测试失败原因分析"),
                _search_item("BVWORD000002", "测试工具"),
            ],
            "原因": [
                _search_item("BVWORD000001", "测试失败原因分析"),
                _search_item("BVWORD000003", "故障原因"),
            ],
            "(测试 原因)": [_search_item("BVWORD000004", "B站原始结果")],
        }
        return {
            "items": values.get(keyword, []),
            "page": 1,
            "pages": 25,
            "total": 500,
            "cached": False,
        }

    monkeypatch.setattr("app.refinement_api.search_videos", fake_search)
    precise = search_videos_by_mode(
        "(测试 原因)",
        mode="all",
        order="totalrank",
        page=1,
        bbdown_dir=tmp_env.bbdown_dir,
    )
    assert [item["bvid"] for item in precise["items"]] == ["BVWORD000001"]
    assert precise["query_terms"] == ["测试", "原因"]

    fuzzy = search_videos_by_mode(
        "(测试 原因)",
        mode="any",
        order="totalrank",
        page=1,
        bbdown_dir=tmp_env.bbdown_dir,
    )
    assert {item["bvid"] for item in fuzzy["items"]} == {
        "BVWORD000001",
        "BVWORD000002",
        "BVWORD000003",
    }

    calls.clear()
    raw = search_videos_by_mode(
        "(测试 原因)",
        mode="raw",
        order="totalrank",
        page=1,
        bbdown_dir=tmp_env.bbdown_dir,
    )
    assert calls == ["(测试 原因)"]
    assert [item["bvid"] for item in raw["items"]] == ["BVWORD000004"]


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


def test_frontend_exposes_search_modes_chips_group_move_and_ten_pages():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    search = (ROOT / "web" / "assets" / "enhancements-search-overlay.js").read_text(
        encoding="utf-8"
    )
    library = (ROOT / "web" / "assets" / "enhancements-library-overlay.js").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "web" / "assets" / "enhancements-catalog-v2.css").read_text(
        encoding="utf-8"
    )
    assert index.index("enhancements-search.js") < index.index("enhancements-search-overlay.js")
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
    for token in ("无标签", "data-library-group-chip", "data-catalog-move", "修改作品分组"):
        assert token in library
    assert ".enh-chip-strip" in css
    assert ".enh-colored-filter-chip" in css


def test_default_tag_palette_uses_distinct_colors():
    payload = json.loads((ROOT / "config" / "tags.json.default").read_text(encoding="utf-8"))
    colors = {item["name"]: item["color"] for item in payload["tags"]}
    assert colors["夯"] == "#d4a017"
    assert len(set(colors.values())) == len(colors)
