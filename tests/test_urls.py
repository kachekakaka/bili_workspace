import pytest

from app.urls import normalize_line, parse_inputs


def test_normalize_bvid_and_url():
    target = normalize_line("BV1qt4y1X7TW")
    assert target.bvid == "BV1qt4y1X7TW"
    target2 = normalize_line("https://www.bilibili.com/video/BV1qt4y1X7TW?spm=1")
    assert target2.key == "BV1qt4y1X7TW"


def test_parse_dedupe_and_multiline():
    targets = parse_inputs(
        urls=["BV1qt4y1X7TW\nhttps://www.bilibili.com/video/BV1qt4y1X7TW"],
        bvids=["BV1xx411c7mD"],
    )
    assert [target.key for target in targets] == ["BV1qt4y1X7TW", "BV1xx411c7mD"]


@pytest.mark.parametrize(
    "url",
    [
        "https://notbilibili.com/video/BV1qt4y1X7TW",
        "https://bilibili.com.evil.example/video/BV1qt4y1X7TW",
        "https://b23.tv.evil.example/BV1qt4y1X7TW",
        "http://www.bilibili.com/video/BV1qt4y1X7TW",
        "https://user@www.bilibili.com/video/BV1qt4y1X7TW",
        "https://www.bilibili.com:444/video/BV1qt4y1X7TW",
    ],
)
def test_spoofed_or_insecure_urls_rejected(url):
    with pytest.raises(ValueError):
        normalize_line(url)


def test_valid_subdomain_and_trailing_dot_allowed():
    assert normalize_line("https://www.bilibili.com./video/BV1qt4y1X7TW").bvid
    short = normalize_line("https://b23.tv/abc123")
    assert short.url == "https://b23.tv/abc123"


def test_any_invalid_line_rejects_partial_batch():
    with pytest.raises(ValueError):
        parse_inputs(urls=["BV1qt4y1X7TW\nnot-a-video"])
