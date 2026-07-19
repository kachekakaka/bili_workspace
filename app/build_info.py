from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import re

from app.constants import APP_VERSION
from app.paths import ROOT

_FRONTEND_VERSION_RE = re.compile(
    r'data-frontend-version=["\']([^"\']+)["\']', re.IGNORECASE
)
_SOURCE_SUFFIXES = {".bat", ".css", ".html", ".js", ".ps1", ".py"}


def _source_files() -> list[Path]:
    files: set[Path] = set()
    for directory in (ROOT / "app", ROOT / "web", ROOT / "scripts" / "windows"):
        if not directory.is_dir():
            continue
        files.update(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
        )
    for path in (ROOT / "start.bat", ROOT / "update.bat", ROOT / "verify.bat"):
        if path.is_file():
            files.add(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


@lru_cache(maxsize=1)
def frontend_version() -> str:
    """Return the cache batch declared by the current HTML document."""
    try:
        text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = _FRONTEND_VERSION_RE.search(text)
    return match.group(1).strip() if match else "unknown"


@lru_cache(maxsize=1)
def build_id() -> str:
    """Fingerprint the source actually used by this running process."""
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
