from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import pytest

from app import search as search_module
from app.constants import SEARCH_PAGE_CACHE_SECONDS, WBI_KEY_CACHE_SECONDS
from app.search import NAV_URL, SEARCH_URL, SearchError, search_videos


IMG_KEY_1 = "7cd084941338484aae1ad9425b84077c"
SUB_KEY_1 = "4932caff0ff7463802950c7033c9cdac"
IMG_KEY_2 = "8cd084941338484aae1ad9425b84077c"
SUB_KEY_2 = "5932caff0ff7463802950c7033c9cdac"


@dataclass
class FakeResponse:
    payload: dict[str, Any]
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSearchClient:
    def __init__(self, *, search_payloads: list[dict[str, Any]] | None = None):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.nav_count = 0
        self.search_payloads = list(search_payloads or [])

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if url == NAV_URL:
            self.nav_count += 1
            img = IMG_KEY_1 if self.nav_count == 1 else IMG_KEY_2
            sub = SUB_KEY_1 if self.nav_count == 1 else SUB_KEY_2
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "wbi_img": {
                            "img_url": f"https://i0.hdslb.com/bfs/wbi/{img}.png",
                            "sub_url": f"https://i0.hdslb.com/bfs/wbi/{sub}.png",
                        }
                    },
                }
            )
        if url == SEARCH_URL:
            payload = self.search_payloads.pop(0) if self.search_payloads else _success_payload()
            return FakeResponse(payload)
        raise AssertionError(f"unexpected URL: {url}")

    def close(self) -> None:
        return None


def _success_payload(*, bvid: str = "BV1SEARCH0001", title: str = "测试标题") -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "numPages": 8,
            "numResults": 160,
            "result": [
                {
                    "bvid": bvid,
                    "title": title,
                    "author": "测试UP",
                    "play": 321,
                    "duration": "01:23",
                    "pubdate": 1_700_000_000,
                    "pic": "//i0.hdslb.com/bfs/cover/test.jpg",
                }
            ],
        },
    }


@pytest.fixture(autouse=True)
def clear_search_caches() -> None:
    search_module.clear_search_caches()
    yield
    search_module.clear_search_caches()


def _url_counts(client: FakeSearchClient) -> Counter[str]:
    return Counter(url for url, _ in client.calls)


def test_frozen_search_cache_constants() -> None:
    assert WBI_KEY_CACHE_SECONDS == 600
    assert SEARCH_PAGE_CACHE_SECONDS == 180


def test_search_uses_wbi_cache_and_raw_page_cache(tmp_env) -> None:
    fake = FakeSearchClient()

    first = search_videos(
        "测试",
        page=1,
        order="totalrank",
        bbdown_dir=tmp_env.bbdown_dir,
        client=fake,
    )
    assert _url_counts(fake) == Counter({NAV_URL: 1, SEARCH_URL: 1})

    second = search_videos(
        "测试",
        page=2,
        order="totalrank",
        bbdown_dir=tmp_env.bbdown_dir,
        client=fake,
    )
    cached = search_videos(
        "测试",
        page=1,
        order="totalrank",
        bbdown_dir=tmp_env.bbdown_dir,
        client=fake,
    )

    assert first["cached"] is False
    assert second["cached"] is False
    assert cached["cached"] is True
    assert _url_counts(fake) == Counter({SEARCH_URL: 2, NAV_URL: 1})
    assert all(
        call[1]["params"]["page_size"] == 20
        for call in fake.calls
        if call[0] == SEARCH_URL
    )


def test_wbi_and_raw_page_cache_expire_at_frozen_ttls(tmp_env, monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(search_module.time, "monotonic", lambda: clock[0])
    fake = FakeSearchClient()

    search_videos("缓存", page=1, bbdown_dir=tmp_env.bbdown_dir, client=fake)
    clock[0] = 179.0
    cached = search_videos("缓存", page=1, bbdown_dir=tmp_env.bbdown_dir, client=fake)
    assert cached["cached"] is True
    assert _url_counts(fake) == Counter({NAV_URL: 1, SEARCH_URL: 1})

    clock[0] = 181.0
    refreshed_page = search_videos(
        "缓存", page=1, bbdown_dir=tmp_env.bbdown_dir, client=fake
    )
    assert refreshed_page["cached"] is False
    assert _url_counts(fake) == Counter({SEARCH_URL: 2, NAV_URL: 1})

    clock[0] = 601.0
    search_videos("缓存", page=2, bbdown_dir=tmp_env.bbdown_dir, client=fake)
    assert _url_counts(fake) == Counter({SEARCH_URL: 3, NAV_URL: 2})


def test_search_never_returns_more_than_one_bilibili_page(tmp_env) -> None:
    payload = _success_payload()
    payload["data"]["result"] = [
        {
            **payload["data"]["result"][0],
            "bvid": f"BV1LIMIT{index:04d}",
            "title": f"结果 {index}",
        }
        for index in range(25)
    ]
    fake = FakeSearchClient(search_payloads=[payload])

    result = search_videos("限制", bbdown_dir=tmp_env.bbdown_dir, client=fake)

    assert len(result["items"]) == 20
    assert result["page_size"] == 20
    assert _url_counts(fake) == Counter({NAV_URL: 1, SEARCH_URL: 1})


def test_refresh_evicts_only_requested_raw_page(tmp_env) -> None:
    fake = FakeSearchClient()
    search_videos("测试", page=1, bbdown_dir=tmp_env.bbdown_dir, client=fake)
    search_videos("测试", page=2, bbdown_dir=tmp_env.bbdown_dir, client=fake)

    refreshed = search_videos(
        "测试",
        page=1,
        bbdown_dir=tmp_env.bbdown_dir,
        client=fake,
        fresh=True,
    )
    page_two = search_videos("测试", page=2, bbdown_dir=tmp_env.bbdown_dir, client=fake)

    assert refreshed["cached"] is False
    assert page_two["cached"] is True
    assert _url_counts(fake) == Counter({SEARCH_URL: 3, NAV_URL: 1})


def test_wbi_signature_failure_clears_keys_and_retries_once(tmp_env) -> None:
    fake = FakeSearchClient(
        search_payloads=[
            {"code": -403, "message": "invalid w_rid"},
            _success_payload(bvid="BV1RETRY00001"),
        ]
    )

    result = search_videos("重试", bbdown_dir=tmp_env.bbdown_dir, client=fake)

    assert result["items"][0]["bvid"] == "BV1RETRY00001"
    assert _url_counts(fake) == Counter({NAV_URL: 2, SEARCH_URL: 2})


def test_wbi_signature_failure_never_retries_more_than_once(tmp_env) -> None:
    fake = FakeSearchClient(
        search_payloads=[
            {"code": -403, "message": "invalid w_rid"},
            {"code": -403, "message": "invalid w_rid"},
        ]
    )

    with pytest.raises(SearchError, match="invalid w_rid"):
        search_videos("重试失败", bbdown_dir=tmp_env.bbdown_dir, client=fake)

    assert _url_counts(fake) == Counter({NAV_URL: 2, SEARCH_URL: 2})


def test_only_one_formal_search_route_is_registered(client) -> None:
    routes = [
        route
        for route in client.app.routes
        if getattr(route, "path", None) == "/api/search"
        and "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert len(routes) == 1


def test_search_response_merges_tags_download_and_deleted_state(client, monkeypatch) -> None:
    bvid = "BV1MERGED0001"
    client.app.state.tag_store.set_tags(bvid, ["夯"])
    client.app.state.deletion_store.record(
        {"source_key": bvid, "bvid": bvid, "title": "已删除作品"},
        files_deleted=True,
    )

    def fake_search(keyword: str, **kwargs: Any) -> dict[str, Any]:
        assert keyword == "测试"
        assert kwargs["fresh"] is True
        return {
            "keyword": keyword,
            "order": kwargs["order"],
            "page": kwargs["page"],
            "pages": 1,
            "total": 1,
            "items": [
                {
                    "bvid": bvid,
                    "title": "已删除作品",
                    "author": "测试UP",
                    "cover": "",
                    "url": f"https://www.bilibili.com/video/{bvid}",
                }
            ],
            "cached": False,
        }

    monkeypatch.setattr("app.api.search_videos", fake_search)
    response = client.get(
        "/api/search",
        params={"q": "测试", "order": "pubdate", "page": 1, "fresh": "true"},
    )

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["tags"] == ["夯"]
    assert item["local_status"] == "deleted"
    assert item["local_status_label"] == "已删除"
    assert item["deleted_record"] is True
