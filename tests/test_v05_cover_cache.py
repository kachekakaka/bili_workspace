from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.cover_cache import CoverCache, validate_cover_url


def test_cover_url_validation_blocks_ssrf_shapes():
    assert validate_cover_url("https://i0.hdslb.com/bfs/archive/demo.jpg")
    for value in (
        "http://i0.hdslb.com/demo.jpg",
        "https://evil.example/demo.jpg",
        "https://hdslb.com.evil.example/demo.jpg",
        "https://user:pass@i0.hdslb.com/demo.jpg",
        "https://i0.hdslb.com:444/demo.jpg",
    ):
        with pytest.raises(ValueError):
            validate_cover_url(value)


def test_cover_is_fetched_once_and_reused_from_disk(tmp_path: Path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg", "Content-Length": "4"},
            content=b"jpeg",
        )

    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        return httpx.Client(transport=transport, **kwargs)

    cache = CoverCache(tmp_path, client_factory=factory)
    url = "https://i0.hdslb.com/bfs/archive/demo.jpg"
    first, media_type = cache.fetch(url)
    second, second_type = cache.fetch(url)
    assert first == second
    assert first.read_bytes() == b"jpeg"
    assert media_type == second_type == "image/jpeg"
    assert len(calls) == 1


def test_cover_size_limit_is_enforced(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"x" * 300_000)

    transport = httpx.MockTransport(handler)
    cache = CoverCache(
        tmp_path,
        max_file_bytes=256 * 1024,
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
    )
    with pytest.raises(ValueError, match="过大"):
        cache.fetch("https://i0.hdslb.com/bfs/archive/huge.png")
    assert not list(tmp_path.glob("*.png"))
