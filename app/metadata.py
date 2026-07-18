from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.cookie import read_cookie_string
from app.search import UA
from app.urls import Target

VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
_COVER_HOST_SUFFIXES = ("bilibili.com", "hdslb.com", "biliimg.com")


class MetadataError(RuntimeError):
    pass


def safe_cover_url(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https" or not host:
        return ""
    if not any(host == suffix or host.endswith("." + suffix) for suffix in _COVER_HOST_SUFFIXES):
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    try:
        if parsed.port not in (None, 443):
            return ""
    except ValueError:
        return ""
    return text


def _duration_text(seconds: Any, part_count: int = 1) -> str:
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    hours, remain = divmod(total, 3600)
    minutes, secs = divmod(remain, 60)
    value = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    return f"{value} · {part_count}P" if part_count > 1 else value


def fetch_video_metadata(
    target: Target,
    bbdown_dir: Path,
    *,
    client: httpx.Client | Any | None = None,
) -> dict[str, Any]:
    if not target.bvid:
        return {}
    cookie = read_cookie_string(bbdown_dir)
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    owns_client = client is None
    client = client or httpx.Client(timeout=12.0, trust_env=False)
    try:
        response = client.get(VIEW_URL, params={"bvid": target.bvid}, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise MetadataError(payload.get("message") or f"作品信息接口返回 code={payload.get('code')}")
        data = payload.get("data") or {}
        owner = data.get("owner") or {}
        stat = data.get("stat") or {}
        pages = [item for item in data.get("pages") or [] if isinstance(item, dict)]
        part_count = max(1, len(pages))
        page_total = sum(
            max(0, int(item.get("duration") or 0))
            for item in pages
            if isinstance(item.get("duration"), (int, float))
        )
        duration_seconds = page_total or data.get("duration")
        return {
            "title": str(data.get("title") or "")[:300],
            "cover": safe_cover_url(str(data.get("pic") or "")),
            "author": str(owner.get("name") or "")[:300],
            "pubdate": data.get("pubdate") if isinstance(data.get("pubdate"), int) else None,
            "duration": _duration_text(duration_seconds, part_count),
            "play": stat.get("view") if isinstance(stat.get("view"), int) else None,
            "url": f"https://www.bilibili.com/video/{target.bvid}",
            "bvid": target.bvid,
        }
    finally:
        if owns_client:
            client.close()
