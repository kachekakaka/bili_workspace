from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_VERSION = "20260719-2"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_browser_displays_application_and_loaded_frontend_versions() -> None:
    index = _text("web/index.html")
    script = _text("web/assets/browser-version.js")

    assert f'data-frontend-version="{FRONTEND_VERSION}"' in index
    assert 'id="browserVersionBadge"' in index
    assert f"前端 {FRONTEND_VERSION}" in index
    assert f"const LOADED_FRONTEND_VERSION = '{FRONTEND_VERSION}';" in script
    assert "应用 ${application}" in script
    assert "缓存不一致" in script
    assert "loadedFrontendVersion" in script
    assert "expectedFrontendVersion" in script
    assert "cacheMatch" in script


def test_frontend_assets_use_one_visible_cache_batch() -> None:
    index = _text("web/index.html")
    versioned_assets = re.findall(
        r'(?:href|src)="(/assets/[^"?]+\.(?:css|js))\?v=([^"&]+)"',
        index,
    )

    assert versioned_assets
    assert {version for _, version in versioned_assets} == {FRONTEND_VERSION}
    assert f'/assets/browser-version.js?v={FRONTEND_VERSION}' in index
    assert index.index("enhancements-deletion-status.js") < index.index("browser-version.js")
