from unittest.mock import MagicMock, patch


def test_search_maps_fields(client):
    search_payload = {
        "code": 0,
        "data": {
            "numPages": 1,
            "numResults": 1,
            "result": [
                {
                    "bvid": "BV1qt4y1X7TW",
                    "title": '<em class="keyword">测试</em>标题',
                    "author": "UP",
                    "play": 123,
                    "duration": "10:00",
                    "pubdate": 1700000000,
                    "pic": "//i0.hdslb.com/bfs/cover/x.jpg",
                }
            ],
        },
    }

    mock_client = MagicMock()
    mock_client.get.return_value = MagicMock(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: search_payload,
    )

    with patch(
        "app.search.fetch_wbi_keys",
        return_value=("7cd084941338484aae1ad9425b84077c", "4932caff0ff7463802950c7033c9cdac"),
    ), patch("app.search.httpx.Client", return_value=mock_client):
        res = client.get("/api/search", params={"q": "测试", "order": "click"})

    body = res.json()
    assert body["ok"] is True
    item = body["data"]["items"][0]
    assert item["bvid"] == "BV1qt4y1X7TW"
    assert item["title"] == "测试标题"
    assert item["cover"].startswith("https:")
    assert body["data"]["order"] == "click"
    params = mock_client.get.call_args.kwargs["params"]
    assert params["order"] == "click"


def test_search_empty_query(client):
    res = client.get("/api/search", params={"q": "  "})
    assert res.json()["ok"] is False
