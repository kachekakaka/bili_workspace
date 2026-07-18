from __future__ import annotations

import re
from typing import Any

import httpx

from app.cookie import read_cookie_string
from app.wbi import sign_params

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

ORDER_MAP = {
    "totalrank": "totalrank",
    "click": "click",
    "pubdate": "pubdate",
}

_TAG_RE = re.compile(r"<[^>]+>")


class SearchError(Exception):
    pass


def _headers(cookie: str) -> dict[str, str]:
    h = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    if cookie:
        h["Cookie"] = cookie
    return h


def fetch_wbi_keys(client: httpx.Client, cookie: str) -> tuple[str, str]:
    resp = client.get(NAV_URL, headers=_headers(cookie))
    resp.raise_for_status()
    data = resp.json()
    wbi = (data.get("data") or {}).get("wbi_img") or {}
    img_url = wbi.get("img_url") or ""
    sub_url = wbi.get("sub_url") or ""
    if not img_url or not sub_url:
        raise SearchError("无法获取 WBI 密钥，请检查登录状态或网络")
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "")


def _duration_seconds(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    bvid = item.get("bvid") or ""
    if not bvid:
        return None
    title = _strip_html(str(item.get("title") or ""))
    author = item.get("author") or ""
    play = item.get("play")
    if play is None:
        play = item.get("view")
    duration = item.get("duration") or ""
    pubdate = item.get("pubdate") or item.get("created") or 0
    cover = item.get("pic") or item.get("cover") or ""
    if cover.startswith("//"):
        cover = "https:" + cover
    return {
        "bvid": bvid,
        "title": title,
        "author": author,
        "play": play,
        "duration": duration,
        "duration_seconds": _duration_seconds(duration),
        "pubdate": pubdate,
        "cover": cover,
        "url": f"https://www.bilibili.com/video/{bvid}",
    }


def search_videos(
    keyword: str,
    *,
    order: str = "totalrank",
    page: int = 1,
    bbdown_dir,
    client: httpx.Client | None = None,
    wbi_keys: tuple[str, str] | None = None,
) -> dict[str, Any]:
    keyword = (keyword or "").strip()
    if not keyword:
        raise SearchError("请输入关键词")
    order_key = ORDER_MAP.get(order, "totalrank")
    page = max(1, int(page))

    cookie = read_cookie_string(bbdown_dir)
    owns_client = client is None
    # Avoid broken system HTTP(S)_PROXY (common cause of empty 502 to Bilibili APIs).
    client = client or httpx.Client(timeout=20.0, trust_env=False)
    try:
        if wbi_keys:
            img_key, sub_key = wbi_keys
        else:
            img_key, sub_key = fetch_wbi_keys(client, cookie)

        params = {
            "search_type": "video",
            "keyword": keyword,
            "order": order_key,
            "page": page,
            "page_size": 20,
        }
        signed = sign_params(params, img_key, sub_key)
        resp = client.get(SEARCH_URL, params=signed, headers=_headers(cookie))
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise SearchError(payload.get("message") or f"搜索失败 code={payload.get('code')}")
        data = payload.get("data") or {}
        results = []
        for item in data.get("result") or []:
            norm = _normalize_item(item)
            if norm:
                results.append(norm)
        return {
            "keyword": keyword,
            "order": order_key,
            "page": page,
            "numPages": data.get("numPages") or 0,
            "numResults": data.get("numResults") or len(results),
            "items": results,
        }
    finally:
        if owns_client:
            client.close()
