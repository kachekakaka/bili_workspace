from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_VERSION = "20260720-2"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_browser_displays_application_frontend_and_server_versions() -> None:
    index = _text("web/index.html")
    main = _text("web/assets/app/main.mjs")
    version = _text("web/assets/app/core/version-check.mjs")

    assert f'data-frontend-version="{FRONTEND_VERSION}"' in index
    assert 'id="browserVersionBadge"' in index
    assert f"前端 {FRONTEND_VERSION}" in index
    assert f"const LOADED_FRONTEND_VERSION = '{FRONTEND_VERSION}';" in main
    for token in (
        "versionMismatchReason",
        "应用 ${application}",
        "版本不一致",
        "服务仍是旧版",
        "点击恢复",
        "fetchImpl(`/healthz?_=${Date.now()}`",
        "loadedFrontendVersion",
        "expectedFrontendVersion",
        "serverFrontendVersion",
        "serverBuildId",
        "cacheMatch",
        "recoveryAction",
        "location?.reload",
    ):
        assert token in version
    assert "MutationObserver" not in version
    assert "BiliEnhancements" not in version


def test_frontend_assets_use_one_visible_cache_batch() -> None:
    index = _text("web/index.html")
    main = _text("web/assets/app/main.mjs")
    versioned_assets = re.findall(
        r'(?:href|src)="(/assets/[^"?]+\.(?:css|js|mjs))\?v=([^"&]+)"',
        index,
    )

    assert versioned_assets
    assert {version for _, version in versioned_assets} == {FRONTEND_VERSION}
    assert f"/assets/app/main.mjs?v={FRONTEND_VERSION}" in index
    for stylesheet in ("tokens.css", "base.css", "components.css", "pages.css"):
        assert f"/assets/styles/{stylesheet}?v={FRONTEND_VERSION}" in index
    assert "browser-version.js" not in index
    assert "enhancements-" not in index
    assert "ui-v062.css" not in index
    assert index.index("qrcode.min.js") < index.index("app/main.mjs")
    assert "import { createVersionChecker } from './core/version-check.mjs';" in main
    assert "versionChecker.start()" in main


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
