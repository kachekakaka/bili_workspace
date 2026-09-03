from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from app.metadata import VIEW_URL, fetch_video_metadata
from app.search import (
    CREATOR_PROFILE_URL,
    CREATOR_SUBMISSIONS_URL,
    NAV_URL,
    SEARCH_URL,
    clear_search_caches,
    creator_profile,
    creator_submissions,
    search_creators,
)
from app.urls import Target


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "SoftwareTesting" / "bilibili_live" / "fixtures"
KINDS = {
    "creator-search": SEARCH_URL,
    "creator-profile": CREATOR_PROFILE_URL,
    "creator-submissions": CREATOR_SUBMISSIONS_URL,
    "video-detail": VIEW_URL,
}
IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff7463802950c7033c9cdac"


def _variants() -> dict[str, list[dict[str, Any]]]:
    paths = {path.stem: path for path in FIXTURE_ROOT.glob("*.json")}
    if not paths:
        pytest.skip("真实 Bilibili 结构基线尚未显式刷新")
    assert set(paths) == set(KINDS)
    result: dict[str, list[dict[str, Any]]] = {}
    for kind, path in paths.items():
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert type(raw.get("schema_version")) is int
        assert raw["schema_version"] == 1
        assert raw.get("kind") == kind
        variants = raw.get("variants")
        assert isinstance(variants, list) and variants
        assert all(isinstance(value, dict) for value in variants)
        result[kind] = variants
    return result


def _client(url: str, payload: dict[str, Any]) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        requested = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        if requested == NAV_URL:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "wbi_img": {
                            "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
                            "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
                        }
                    },
                },
            )
        assert requested == url
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)


def _exercise_variants(
    *,
    kind: str,
    variants: dict[str, list[dict[str, Any]]],
    call: Callable[[httpx.Client], Any],
) -> None:
    for payload in variants[kind]:
        clear_search_caches()
        try:
            with _client(KINDS[kind], payload) as client:
                assert call(client) is not None
        finally:
            clear_search_caches()


def test_sanitized_live_fixtures_remain_consumable_by_current_adapters(
    tmp_path: Path,
) -> None:
    variants = _variants()
    bbdown = tmp_path / "bbdown"
    bbdown.mkdir()
    (bbdown / "BBDown.data").write_text("SESSDATA=fake", encoding="utf-8")

    _exercise_variants(
        kind="creator-search",
        variants=variants,
        call=lambda client: search_creators(
            "text",
            page=1,
            bbdown_dir=bbdown,
            client=client,
            fresh=True,
        ),
    )
    _exercise_variants(
        kind="creator-profile",
        variants=variants,
        call=lambda client: creator_profile(
            "10001",
            bbdown_dir=bbdown,
            client=client,
            fresh=True,
        ),
    )
    _exercise_variants(
        kind="creator-submissions",
        variants=variants,
        call=lambda client: creator_submissions(
            "10001",
            page=1,
            bbdown_dir=bbdown,
            client=client,
            fresh=True,
        ),
    )
    _exercise_variants(
        kind="video-detail",
        variants=variants,
        call=lambda client: fetch_video_metadata(
            Target(
                key="BV1TEST00001",
                bvid="BV1TEST00001",
                url="https://www.bilibili.com/video/BV1TEST00001",
            ),
            bbdown,
            client=client,
        ),
    )
