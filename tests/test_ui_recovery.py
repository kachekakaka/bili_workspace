from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_dashboard_and_library_recovery_is_loaded_before_legacy_overlay():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    recovery = (ROOT / "web" / "assets" / "enhancements-ui-recovery.js").read_text(
        encoding="utf-8"
    )
    assert index.index("enhancements-library.js") < index.index("enhancements-ui-recovery.js")
    assert index.index("enhancements-ui-recovery.js") < index.index("enhancements-library-overlay.js")
    versions = re.findall(r'/assets/[^"\']+\?v=([^"\']+)', index)
    assert versions and set(versions) == {"20260719-1"}
    for token in (
        "最近观看与下载",
        "运行状态",
        "gridTemplateColumns: 'minmax(0, 1fr)'",
        "enh-dashboard-stack",
        "data-recovery-group",
        "data-recovery-tag",
        "__untagged__",
        "enh-native-chip-filter",
        "stopImmediatePropagation",
    ):
        assert token in recovery


def test_static_assets_are_revalidated(client):
    response = client.get("/assets/enhancements-ui-recovery.js")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache"
