from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v062_settings_assets_are_loaded() -> None:
    index = text("web/index.html")
    assert "/assets/ui-v062-settings.css?v=20260720-2" in index
    assert "/assets/enhancements-ui-v062-settings.js?v=20260720-2" in index


def test_v062_settings_keep_basic_fields_visible_and_fold_advanced_fields() -> None:
    script = text("web/assets/enhancements-ui-v062-settings.js")
    assert "ADVANCED_FIELD_IDS = ['cfgTimeout', 'cfgPoll', 'cfgDfn', 'cfgEncoding']" in script
    assert "v062-settings-advanced" in script
    assert "高级设置" in script
    assert "不熟悉时保持默认即可" in script
    for basic_id in ("cfgPort", "cfgDownload", "cfgGroup", "cfgQuality"):
        assert basic_id not in script.split("ADVANCED_FIELD_IDS", 1)[1].split("]", 1)[0]
