from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_VERSION = "20260719-5"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_browser_displays_application_frontend_and_server_versions() -> None:
    index = _text("web/index.html")
    script = _text("web/assets/browser-version.js")

    assert f'data-frontend-version="{FRONTEND_VERSION}"' in index
    assert 'id="browserVersionBadge"' in index
    assert f"前端 {FRONTEND_VERSION}" in index
    assert f"const LOADED_FRONTEND_VERSION = '{FRONTEND_VERSION}';" in script
    assert "应用 ${application}" in script
    assert "版本不一致" in script
    assert "服务仍是旧版" in script
    assert "fetch(`/healthz?_=${Date.now()}`" in script
    for token in (
        "loadedFrontendVersion",
        "expectedFrontendVersion",
        "serverFrontendVersion",
        "serverBuildId",
        "cacheMatch",
    ):
        assert token in script


def test_frontend_assets_use_one_visible_cache_batch() -> None:
    index = _text("web/index.html")
    versioned_assets = re.findall(
        r'(?:href|src)="(/assets/[^"?]+\.(?:css|js))\?v=([^"&]+)"',
        index,
    )

    assert versioned_assets
    assert {version for _, version in versioned_assets} == {FRONTEND_VERSION}
    assert f"/assets/browser-version.js?v={FRONTEND_VERSION}" in index
    assert "enhancements-search-overlay.js" not in index
    assert "enhancements-deletion-status.js" not in index
    assert index.index("enhancements-search.js") < index.index("browser-version.js")


def test_healthz_exposes_the_running_source_build(client) -> None:
    response = client.get("/healthz")
    payload = response.json()

    assert payload["ok"] is True
    assert payload["service"] == "bili_workspace"
    assert payload["frontend_version"] == FRONTEND_VERSION
    assert re.fullmatch(r"[0-9a-f]{12}", payload["build_id"])
    assert "pid" not in payload
    assert response.headers["x-bili-build"] == payload["build_id"]
    assert response.headers["x-bili-frontend"] == FRONTEND_VERSION
