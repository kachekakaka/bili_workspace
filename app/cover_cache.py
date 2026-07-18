from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

_ALLOWED_SUFFIXES = ("bilibili.com", "hdslb.com", "biliimg.com")
_CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}


def validate_cover_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("封面地址为空")
    try:
        parsed = urlparse(text)
    except ValueError as exc:
        raise ValueError("封面地址无效") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        raise ValueError("封面只允许 HTTPS")
    if not any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_SUFFIXES):
        raise ValueError("封面域名不在允许列表")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("封面地址不能包含账号信息")
    try:
        if parsed.port not in (None, 443):
            raise ValueError("封面只允许 HTTPS 443 端口")
    except ValueError as exc:
        raise ValueError("封面端口无效") from exc
    return text


class CoverCache:
    """Small, SSRF-restricted on-disk cache for Bilibili cover images."""

    def __init__(
        self,
        directory: Path,
        *,
        max_total_bytes: int = 512 * 1024 * 1024,
        max_file_bytes: int = 8 * 1024 * 1024,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_total_bytes = max(8 * 1024 * 1024, int(max_total_bytes))
        self.max_file_bytes = max(256 * 1024, int(max_file_bytes))
        self.client_factory = client_factory
        self._lock = threading.RLock()

    def _existing(self, key: str) -> Path | None:
        for path in self.directory.glob(f"{key}.*"):
            if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                try:
                    os.utime(path, None)
                except OSError:
                    pass
                return path
        return None

    def fetch(self, value: str) -> tuple[Path, str]:
        url = validate_cover_url(value)
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        with self._lock:
            existing = self._existing(key)
            if existing:
                return existing, self._media_type(existing)

            with self.client_factory(
                timeout=httpx.Timeout(12.0, connect=6.0),
                follow_redirects=False,
                trust_env=False,
                headers={
                    "User-Agent": "Mozilla/5.0 bili-workspace/0.5",
                    "Referer": "https://www.bilibili.com/",
                    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif",
                },
            ) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    extension = _CONTENT_EXTENSIONS.get(media_type)
                    if extension is None:
                        raise ValueError("封面响应不是受支持的图片格式")
                    declared = response.headers.get("content-length", "").strip()
                    if declared:
                        try:
                            if int(declared) > self.max_file_bytes:
                                raise ValueError("封面文件过大")
                        except ValueError as exc:
                            if "过大" in str(exc):
                                raise
                    target = self.directory / f"{key}{extension}"
                    temp = self.directory / f".{key}.{os.getpid()}.{threading.get_ident()}.tmp"
                    size = 0
                    try:
                        with temp.open("wb") as handle:
                            for chunk in response.iter_bytes(64 * 1024):
                                size += len(chunk)
                                if size > self.max_file_bytes:
                                    raise ValueError("封面文件过大")
                                handle.write(chunk)
                            handle.flush()
                            os.fsync(handle.fileno())
                        if size <= 0:
                            raise ValueError("封面响应为空")
                        os.replace(temp, target)
                    finally:
                        temp.unlink(missing_ok=True)
            self._prune(exclude=target)
            return target, media_type

    @staticmethod
    def _media_type(path: Path) -> str:
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".avif": "image/avif",
        }.get(path.suffix.lower(), "application/octet-stream")

    def _prune(self, *, exclude: Path) -> None:
        files = [
            item
            for item in self.directory.iterdir()
            if item.is_file() and not item.is_symlink() and not item.name.startswith(".")
        ]
        total = sum(item.stat().st_size for item in files)
        if total <= self.max_total_bytes:
            return
        for item in sorted(files, key=lambda path: path.stat().st_mtime):
            if item == exclude:
                continue
            try:
                size = item.stat().st_size
                item.unlink()
                total -= size
            except OSError:
                continue
            if total <= self.max_total_bytes:
                break

    def stats(self) -> dict[str, int | str]:
        with self._lock:
            files = [
                item
                for item in self.directory.iterdir()
                if item.is_file() and not item.is_symlink() and not item.name.startswith(".")
            ]
            return {
                "directory": str(self.directory),
                "files": len(files),
                "bytes": sum(item.stat().st_size for item in files),
                "limit_bytes": self.max_total_bytes,
                "checked_at": int(time.time()),
            }
