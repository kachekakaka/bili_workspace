from __future__ import annotations

import copy
import hashlib
import re
import threading
import time
from typing import Any

import httpx

from app.constants import (
    DISCOVERY_PAGE_SIZE,
    SEARCH_PAGE_CACHE_SECONDS,
    WBI_KEY_CACHE_SECONDS,
)
from app.cookie import read_cookie_string
from app.wbi import sign_params

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
CREATOR_PROFILE_URL = "https://api.bilibili.com/x/web-interface/card"
CREATOR_SUBMISSIONS_URL = "https://api.bilibili.com/x/space/wbi/arc/search"

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
_CACHE_LIMIT = 160
_CACHE_LOCK = threading.RLock()
_SEARCH_CACHE: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_WBI_KEY_CACHE: dict[str, tuple[float, tuple[str, str]]] = {}


class SearchError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "bilibili_unavailable",
        status_code: int = 502,
        public_message: str = "Bilibili 暂时不可用，请稍后重试",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.public_message = public_message


def _headers(cookie: str) -> dict[str, str]:
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def fetch_wbi_keys(client: httpx.Client, cookie: str) -> tuple[str, str]:
    response = client.get(NAV_URL, headers=_headers(cookie))
    response.raise_for_status()
    payload = response.json()
    wbi = (payload.get("data") or {}).get("wbi_img") or {}
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
    cover = _https_image(item.get("pic") or item.get("cover"))
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


def _cookie_token(cookie: str) -> str:
    return hashlib.sha256(cookie.encode("utf-8")).hexdigest()[:16] if cookie else "guest"


def _cached(key: tuple[str, ...]) -> dict[str, Any] | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        row = _SEARCH_CACHE.get(key)
        if not row:
            return None
        created, value = row
        if now - created > SEARCH_PAGE_CACHE_SECONDS:
            _SEARCH_CACHE.pop(key, None)
            return None
        return copy.deepcopy(value)


def _store_cache(key: tuple[str, ...], value: dict[str, Any]) -> None:
    now = time.monotonic()
    with _CACHE_LOCK:
        _SEARCH_CACHE[key] = (now, copy.deepcopy(value))
        if len(_SEARCH_CACHE) > _CACHE_LIMIT:
            count = len(_SEARCH_CACHE) - _CACHE_LIMIT
            oldest = sorted(_SEARCH_CACHE.items(), key=lambda item: item[1][0])[:count]
            for old_key, _ in oldest:
                _SEARCH_CACHE.pop(old_key, None)


def _invalidate_search_page(key: tuple[str, ...]) -> None:
    with _CACHE_LOCK:
        _SEARCH_CACHE.pop(key, None)


def _cached_wbi_keys(token: str) -> tuple[str, str] | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        row = _WBI_KEY_CACHE.get(token)
        if not row:
            return None
        created, keys = row
        if now - created > WBI_KEY_CACHE_SECONDS:
            _WBI_KEY_CACHE.pop(token, None)
            return None
        return keys


def _store_wbi_keys(token: str, keys: tuple[str, str]) -> None:
    with _CACHE_LOCK:
        _WBI_KEY_CACHE[token] = (time.monotonic(), keys)


def _invalidate_wbi_keys(token: str) -> None:
    with _CACHE_LOCK:
        _WBI_KEY_CACHE.pop(token, None)


def _get_wbi_keys(
    client: httpx.Client,
    cookie: str,
    token: str,
    *,
    force: bool = False,
) -> tuple[str, str]:
    if not force:
        cached = _cached_wbi_keys(token)
        if cached is not None:
            return cached
    keys = fetch_wbi_keys(client, cookie)
    _store_wbi_keys(token, keys)
    return keys


def _is_wbi_signature_error(payload: dict[str, Any]) -> bool:
    code = payload.get("code")
    message = str(payload.get("message") or payload.get("msg") or "").casefold()
    return code == -403 or any(
        marker in message for marker in ("w_rid", "wbi", "signature", "签名")
    )


def _payload_error(
    payload: dict[str, Any],
    *,
    not_found: bool = False,
) -> SearchError:
    code = payload.get("code")
    message = str(payload.get("message") or payload.get("msg") or f"code={code}")
    if not_found and code in {-400, -404}:
        return SearchError(
            message,
            code="creator_not_found",
            status_code=404,
            public_message="未找到这个 UP 主",
        )
    if code in {-352, -412}:
        return SearchError(
            message,
            code="bilibili_risk_control",
            status_code=503,
            public_message="Bilibili 风控暂时阻止了读取，请稍后重试或联系管理员检查 Bilibili 登录",
        )
    if code in {-101, -111}:
        return SearchError(
            message,
            code="bilibili_login_required",
            status_code=503,
            public_message="服务端 Bilibili 登录已失效，请联系管理员重新登录",
        )
    return SearchError(message)


def _request_json(
    client: httpx.Client,
    url: str,
    *,
    cookie: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = client.get(url, params=params, headers=_headers(cookie))
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise SearchError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise SearchError("Bilibili 返回了无法识别的数据")
    return payload


def _signed_payload(
    client: httpx.Client,
    url: str,
    *,
    cookie: str,
    cookie_token: str,
    params: dict[str, Any],
    wbi_keys: tuple[str, str] | None = None,
) -> dict[str, Any]:
    keys = wbi_keys or _get_wbi_keys(client, cookie, cookie_token)
    for attempt in range(2):
        payload = _request_json(
            client,
            url,
            cookie=cookie,
            params=sign_params(params, keys[0], keys[1]),
        )
        if payload.get("code") == 0:
            return payload
        if attempt == 0 and _is_wbi_signature_error(payload):
            _invalidate_wbi_keys(cookie_token)
            keys = _get_wbi_keys(client, cookie, cookie_token, force=True)
            continue
        raise _payload_error(payload)
    raise SearchError("搜索签名重试失败")


def _result_from_payload(
    payload: dict[str, Any],
    *,
    keyword: str,
    order: str,
    page: int,
) -> dict[str, Any]:
    data = payload.get("data") or {}
    results = []
    for item in (data.get("result") or [])[:DISCOVERY_PAGE_SIZE]:
        normalized = _normalize_item(item)
        if normalized:
            results.append(normalized)
    pages = int(data.get("numPages") or data.get("num_pages") or 0)
    total = int(data.get("numResults") or data.get("num_results") or len(results))
    return {
        "keyword": keyword,
        "order": order,
        "page": page,
        "pages": pages,
        "total": total,
        "numPages": pages,
        "numResults": total,
        "num_pages": pages,
        "num_results": total,
        "page_size": DISCOVERY_PAGE_SIZE,
        "items": results,
        "cached": False,
    }


def clear_search_caches() -> None:
    """Clear process-local Bilibili search caches.

    This is intentionally public for deterministic tests and explicit maintenance;
    normal refreshes should use ``fresh=True`` so only one raw page is evicted.
    """

    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()
        _WBI_KEY_CACHE.clear()


def search_videos(
    keyword: str,
    *,
    order: str = "totalrank",
    page: int = 1,
    bbdown_dir,
    client: httpx.Client | None = None,
    wbi_keys: tuple[str, str] | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    keyword = (keyword or "").strip()
    if not keyword:
        raise SearchError("请输入关键词")
    order_key = ORDER_MAP.get(order, "totalrank")
    page = max(1, int(page))

    cookie = read_cookie_string(bbdown_dir)
    cookie_token = _cookie_token(cookie)
    cache_key = ("video", keyword.casefold(), order_key, str(page), cookie_token)
    if fresh:
        _invalidate_search_page(cache_key)
    else:
        cached = _cached(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    owns_client = client is None
    http_client = client or httpx.Client(timeout=20.0, trust_env=False)
    try:
        params = {
            "search_type": "video",
            "keyword": keyword,
            "order": order_key,
            "page": page,
            "page_size": DISCOVERY_PAGE_SIZE,
        }
        payload = _signed_payload(
            http_client,
            SEARCH_URL,
            cookie=cookie,
            cookie_token=cookie_token,
            params=params,
            wbi_keys=wbi_keys,
        )
        result = _result_from_payload(
            payload,
            keyword=keyword,
            order=order_key,
            page=page,
        )
        _store_cache(cache_key, result)
        return result
    finally:
        if owns_client:
            http_client.close()


def _https_image(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("//"):
        return "https:" + text
    if text.lower().startswith("http://"):
        return "https://" + text[7:]
    return text


def _normalize_creator(item: dict[str, Any]) -> dict[str, Any] | None:
    uid = str(item.get("mid") or item.get("uid") or "").strip()
    if not uid.isdigit() or int(uid) <= 0:
        return None
    name = _strip_html(str(item.get("uname") or item.get("name") or "")).strip()
    return {
        "uid": str(int(uid)),
        "name": name,
        "avatar": _https_image(item.get("upic") or item.get("face")),
        "bio": str(item.get("usign") or item.get("sign") or "").strip(),
        "followers": int(item.get("fans") or item.get("follower") or 0),
        "submission_count": int(
            item.get("videos") or item.get("archive_count") or item.get("video") or 0
        ),
        "profile_url": f"https://space.bilibili.com/{int(uid)}",
    }


def search_creators(
    keyword: str,
    *,
    page: int = 1,
    bbdown_dir,
    client: httpx.Client | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    keyword = str(keyword or "").strip()
    if not keyword:
        raise SearchError(
            "请输入 UP 主名称",
            code="invalid_creator_query",
            status_code=400,
            public_message="请输入 UP 主名称",
        )
    page = max(1, int(page))
    cookie = read_cookie_string(bbdown_dir)
    cookie_token = _cookie_token(cookie)
    cache_key = ("creator-name", keyword.casefold(), str(page), cookie_token)
    if fresh:
        _invalidate_search_page(cache_key)
    else:
        cached = _cached(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    owns_client = client is None
    http_client = client or httpx.Client(timeout=20.0, trust_env=False)
    try:
        payload = _signed_payload(
            http_client,
            SEARCH_URL,
            cookie=cookie,
            cookie_token=cookie_token,
            params={
                "search_type": "bili_user",
                "keyword": keyword,
                "page": page,
                "page_size": DISCOVERY_PAGE_SIZE,
            },
        )
        data = payload.get("data") or {}
        items = []
        for raw in (data.get("result") or [])[:DISCOVERY_PAGE_SIZE]:
            if isinstance(raw, dict):
                normalized = _normalize_creator(raw)
                if normalized:
                    items.append(normalized)
        pages = int(data.get("numPages") or data.get("num_pages") or 0)
        total = int(data.get("numResults") or data.get("num_results") or len(items))
        result = {
            "keyword": keyword,
            "page": page,
            "pages": pages,
            "total": total,
            "page_size": DISCOVERY_PAGE_SIZE,
            "items": items,
            "cached": False,
        }
        _store_cache(cache_key, result)
        return result
    finally:
        if owns_client:
            http_client.close()


def creator_profile(
    uid: str,
    *,
    bbdown_dir,
    client: httpx.Client | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    canonical_uid = str(int(str(uid)))
    cookie = read_cookie_string(bbdown_dir)
    cookie_token = _cookie_token(cookie)
    cache_key = ("creator-profile", canonical_uid, cookie_token)
    if fresh:
        _invalidate_search_page(cache_key)
    else:
        cached = _cached(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    owns_client = client is None
    http_client = client or httpx.Client(timeout=20.0, trust_env=False)
    try:
        payload = _request_json(
            http_client,
            CREATOR_PROFILE_URL,
            cookie=cookie,
            params={"mid": canonical_uid, "photo": "true"},
        )
        if payload.get("code") != 0:
            raise _payload_error(payload, not_found=True)
        data = payload.get("data") or {}
        card = data.get("card") or data
        if not isinstance(card, dict):
            raise SearchError("UP 主资料格式无效")
        merged = dict(card)
        merged["archive_count"] = data.get("archive_count") or card.get("archive_count") or 0
        result = _normalize_creator(merged)
        if result is None:
            raise SearchError(
                "UP 主资料缺少 UID",
                code="creator_not_found",
                status_code=404,
                public_message="未找到这个 UP 主",
            )
        result["cached"] = False
        _store_cache(cache_key, result)
        return result
    finally:
        if owns_client:
            http_client.close()


def creator_submissions(
    uid: str,
    *,
    order: str = "pubdate",
    page: int = 1,
    bbdown_dir,
    client: httpx.Client | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    canonical_uid = str(int(str(uid)))
    order_key = "click" if order == "click" else "pubdate"
    page = max(1, int(page))
    cookie = read_cookie_string(bbdown_dir)
    cookie_token = _cookie_token(cookie)
    cache_key = (
        "creator-submissions",
        canonical_uid,
        order_key,
        str(page),
        cookie_token,
    )
    if fresh:
        _invalidate_search_page(cache_key)
    else:
        cached = _cached(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    owns_client = client is None
    http_client = client or httpx.Client(timeout=20.0, trust_env=False)
    try:
        payload = _signed_payload(
            http_client,
            CREATOR_SUBMISSIONS_URL,
            cookie=cookie,
            cookie_token=cookie_token,
            params={
                "mid": canonical_uid,
                "pn": page,
                "ps": DISCOVERY_PAGE_SIZE,
                "order": order_key,
                "keyword": "",
            },
        )
        data = payload.get("data") or {}
        list_data = data.get("list") or {}
        raw_items = list_data.get("vlist") or data.get("vlist") or []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_items[:DISCOVERY_PAGE_SIZE]:
            if not isinstance(raw, dict):
                continue
            mapped = dict(raw)
            mapped["duration"] = raw.get("length") or raw.get("duration") or ""
            mapped["pubdate"] = raw.get("created") or raw.get("pubdate") or 0
            mapped["pic"] = raw.get("pic") or raw.get("cover") or ""
            normalized = _normalize_item(mapped)
            if not normalized:
                continue
            bvid = str(normalized["bvid"])
            if bvid in seen:
                continue
            seen.add(bvid)
            items.append(normalized)
        page_info = data.get("page") or {}
        total = int(page_info.get("count") or data.get("count") or len(items))
        pages = (total + DISCOVERY_PAGE_SIZE - 1) // DISCOVERY_PAGE_SIZE if total else 0
        result = {
            "uid": canonical_uid,
            "order": order_key,
            "page": page,
            "pages": pages,
            "total": total,
            "page_size": DISCOVERY_PAGE_SIZE,
            "items": items,
            "cached": False,
        }
        _store_cache(cache_key, result)
        return result
    finally:
        if owns_client:
            http_client.close()
