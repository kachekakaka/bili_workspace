from __future__ import annotations

from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re

from app.constants import APP_VERSION
from app.paths import ROOT, web_dir

_FRONTEND_VERSION_RE = re.compile(
    r'data-frontend-version=["\']([^"\']+)["\']', re.IGNORECASE
)
_SOURCE_SUFFIXES = {".bat", ".css", ".html", ".js", ".mjs", ".ps1", ".py"}


def _source_files() -> list[Path]:
    files: set[Path] = set()
    for directory in (ROOT / "app", ROOT / "web"):
        if not directory.is_dir():
            continue
        files.update(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
        )
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


@lru_cache(maxsize=1)
def frontend_version() -> str:
    """Return the cache batch declared by the current HTML document."""
    try:
        override = os.getenv("BILI_FRONTEND_VERSION", "").strip()
        if override:
            return override
        text = (web_dir() / "index.html").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = _FRONTEND_VERSION_RE.search(text)
    return match.group(1).strip() if match else "unknown"


@lru_cache(maxsize=1)
def build_id() -> str:
    """Fingerprint the source actually used by this running process."""
    override = os.getenv("BILI_BUILD_ID", "").strip().lower()
    if override:
        if not re.fullmatch(r"[0-9a-f]{12,64}", override):
            raise ValueError("BILI_BUILD_ID 必须是 12-64 位小写十六进制摘要")
        return override
    digest = hashlib.sha256()
    for path in _source_files():
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def build_metadata() -> dict[str, str]:
    return {
        "service": "bili_workspace",
        "version": APP_VERSION,
        "frontend_version": frontend_version(),
        "build_id": build_id(),
    }
