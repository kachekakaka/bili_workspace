"""隔离产品会话的本地管理 API 客户端。"""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import httpx

from tools.bilibili_live.contracts import (
    LiveBlockedError,
    LiveFailedError,
    LiveInconclusiveError,
)


class LiveApi:
    def __init__(self, base_url: str, data_root: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.data_root = Path(data_root)
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=30,
            trust_env=False,
            follow_redirects=False,
        )
        self.csrf_token = ""

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "LiveApi":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise LiveFailedError("隔离产品 API 返回了非 JSON 响应") from exc
        if not isinstance(payload, dict):
            raise LiveFailedError("隔离产品 API 响应类型无效")
        if response.status_code >= 400 or payload.get("ok") is not True:
            code = str(payload.get("code") or "")
            if code in {
                "bilibili_login_required",
                "bilibili_risk_control",
                "bilibili_unavailable",
                "creator_inaccessible",
            }:
                raise LiveBlockedError("真实 Bilibili 环境阻止了产品 API")
            raise LiveFailedError(f"隔离产品 API 合同失败: {code or response.status_code}")
        return payload

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise LiveInconclusiveError("无法访问隔离产品 API") from exc
        return self._decode(response)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"x-csrf-token": self.csrf_token} if self.csrf_token else {}
        try:
            response = self.client.post(path, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise LiveInconclusiveError("无法访问隔离产品 API") from exc
        return self._decode(response)

    def setup_admin(self) -> None:
        bootstrap = self.data_root / "config" / "bootstrap-token.txt"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not bootstrap.is_file():
            time.sleep(0.1)
        try:
            token = bootstrap.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise LiveInconclusiveError("隔离产品没有生成初始化令牌") from exc
        if len(token) < 8:
            raise LiveInconclusiveError("隔离产品初始化令牌无效")
        password = f"Live{secrets.token_hex(12)}A1"
        payload = self.post(
            "/api/auth/setup",
            {
                "username": "live_admin",
                "password": password,
                "bootstrap_token": token,
                "display_name": "真链测试",
            },
        )
        data = payload.get("data")
        csrf = data.get("csrf_token") if isinstance(data, dict) else None
        if not isinstance(csrf, str) or not csrf:
            raise LiveFailedError("隔离产品初始化响应缺少 CSRF")
        self.csrf_token = csrf

    def verify_login(self) -> None:
        payload = self.get("/api/status", params={"refresh_login": "true"})
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("logged_in") is not True:
            raise LiveBlockedError("复制的 Bilibili 登录已经失效或无法确认")

    def resolve_creator(self, uid: str) -> dict[str, Any]:
        payload = self.get(
            "/api/bilibili/creators/resolve",
            params={
                "locator": uid,
                "order": "pubdate",
                "destination": "library",
                "fresh": "true",
            },
        )
        data = payload.get("data")
        creator = data.get("creator") if isinstance(data, dict) else None
        if not isinstance(creator, dict) or str(creator.get("uid")) != uid:
            raise LiveFailedError("隔离产品没有解析到指定 UP 主")
        return data

    def verify_covers(self, items: Iterable[dict[str, Any]]) -> int:
        checked = 0
        for item in items:
            cover = str(item.get("cover") or "")
            if not cover:
                raise LiveFailedError("真实投稿缺少封面 URL")
            try:
                response = self.client.get(f"/api/cover?url={quote(cover, safe='')}", timeout=30)
            except httpx.HTTPError as exc:
                raise LiveBlockedError("真实封面当前无法读取") from exc
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code != 200 or not content_type.startswith("image/") or not response.content:
                raise LiveFailedError("产品封面代理没有返回有效图片")
            if len(response.content) > 16 * 1024 * 1024:
                raise LiveFailedError("产品封面代理响应异常过大")
            checked += 1
        return checked

    def preview(self, item: dict[str, Any]) -> dict[str, Any]:
        preferred_quality = str(item.get("preferred_quality") or "")
        payload = self.post(
            "/api/preview",
            {
                "item": {
                    "bvid": item["bvid"],
                    "url": item["url"],
                    "title": item.get("title", ""),
                    "cover": item.get("cover", ""),
                    "author": item.get("author", ""),
                    "pubdate": item.get("pubdate"),
                    "duration": item.get("duration", ""),
                    "play": item.get("play"),
                    "preferred_quality": preferred_quality,
                },
                "min_height": 0,
                "preferred_quality": preferred_quality,
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("quality"), dict):
            raise LiveFailedError("真实画质预检响应无效")
        return data

    def submit_selection(self, items: list[dict[str, Any]]) -> list[str]:
        payload = self.post(
            "/api/download/selection",
            {
                "urls": [],
                "bvids": [],
                "items": [
                    {
                        "bvid": item["bvid"],
                        "url": item["url"],
                        "title": item.get("title", ""),
                        "cover": item.get("cover", ""),
                        "author": item.get("author", ""),
                        "pubdate": item.get("pubdate"),
                        "duration": item.get("duration", ""),
                        "play": item.get("play"),
                        "preferred_quality": str(item.get("preferred_quality") or ""),
                    }
                    for item in items
                ],
                "force": False,
                "group_id": "",
                "group": "",
                "destination": "library",
                "min_height": 0,
            },
        )
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(items):
            raise LiveFailedError("严格批量入口没有原子创建全部 8 个任务")
        task_ids = [str(item.get("id") or "") for item in data if isinstance(item, dict)]
        if (
            len(task_ids) != len(items)
            or len(set(task_ids)) != len(items)
            or any(not task_id for task_id in task_ids)
        ):
            raise LiveFailedError("严格批量入口返回了无效任务身份")
        return task_ids

    def tasks(self) -> list[dict[str, Any]]:
        payload = self.get("/api/tasks", params={"direction": "desc"})
        data = payload.get("data")
        if not isinstance(data, list):
            raise LiveFailedError("任务列表响应无效")
        return [item for item in data if isinstance(item, dict)]

    def cancel_tasks(self, task_ids: Iterable[str]) -> None:
        for task_id in task_ids:
            try:
                self.post(f"/api/tasks/{quote(task_id, safe='')}/cancel", {})
            except LiveFailedError:
                current = {str(item.get("id")): item for item in self.tasks()}.get(task_id)
                if not current or current.get("status") not in {
                    "success",
                    "failed",
                    "skipped",
                    "cancelled",
                }:
                    raise

    def library_item_for_bvid(self, bvid: str) -> dict[str, Any] | None:
        payload = self.get("/api/enhancements/library", params={"q": bvid, "page": 1})
        data = payload.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise LiveFailedError("作品库列表响应无效")
        for item in items:
            if isinstance(item, dict) and str(item.get("bvid") or "") == bvid:
                return item
        return None
