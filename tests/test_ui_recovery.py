from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_dashboard_and_library_recovery_is_replaced_by_formal_modules():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    dashboard = (ROOT / "web" / "assets" / "app" / "pages" / "dashboard.mjs").read_text(
        encoding="utf-8"
    )
    library = (
        ROOT / "web" / "assets" / "app" / "pages" / "library-impl.mjs"
    ).read_text(encoding="utf-8")
    expected = re.search(r'data-frontend-version="([^"]+)"', index)
    versions = re.findall(r'/assets/[^"\']+\?v=([^"\']+)', index)
    assert expected is not None
    assert versions and set(versions) == {expected.group(1)}
    for removed in (
        "enhancements-ui-recovery.js",
        "enhancements-library-overlay.js",
        "enhancements-library.js",
    ):
        assert removed not in index
        assert not (ROOT / "web" / "assets" / removed).exists()
    for token in (
        "最近观看与下载",
        "运行状态",
        "enh-dashboard-stack",
        'data-dashboard-sections="stacked"',
    ):
        assert token in dashboard
    for token in (
        "data-library-group-chip",
        "data-library-tag-chip",
        "__untagged__",
        "enh-native-chip-filter",
        "data-library-move",
    ):
        assert token in library
    assert "MutationObserver" not in library
    assert "stopImmediatePropagation" not in library


def test_formal_library_asset_is_revalidated(client):
    response = client.get("/assets/app/pages/library.mjs")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache"
