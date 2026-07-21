from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_settings_behavior_moves_into_the_module_page() -> None:
    index = text("web/index.html")
    assert "/assets/ui-v062-settings.css" not in index
    assert "/assets/enhancements-ui-v062-settings.js" not in index
    assert "/assets/app/main.mjs?v=20260720-2" in index


def test_settings_keep_basic_fields_visible_and_fold_advanced_fields() -> None:
    script = text("web/assets/app/pages/settings.mjs")
    assert "v062-settings-advanced" in script
    assert "高级设置" in script
    assert "不熟悉时保持默认即可" in script
    for basic_id in ("cfgPort", "cfgDownload", "cfgGroup", "cfgQuality"):
        assert f'id="{basic_id}"' in script
    for advanced_id in ("cfgTimeout", "cfgPoll", "cfgDfn", "cfgEncoding"):
        assert f'id="{advanced_id}"' in script
    assert script.index('id="cfgQuality"') < script.index("v062-settings-advanced")
