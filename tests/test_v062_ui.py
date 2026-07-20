from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v062_assets_are_loaded_after_enhancement_core() -> None:
    index = text("web/index.html")
    assert "/assets/ui-v062.css?v=20260720-2" in index
    assert "/assets/enhancements-ui-v062.js?v=20260720-2" in index
    assert index.index("enhancements-core.js") < index.index("enhancements-ui-v062.js")


def test_v062_control_height_tokens_are_consistent() -> None:
    css = text("web/assets/ui-v062.css")
    assert "--control-height-sm: 32px" in css
    assert "--control-height-md: 40px" in css
    assert "--control-height-lg: 48px" in css
    assert ".input,\n.select" in css
    assert "height: var(--control-height-md)" in css
    assert "min-height: 44px" in css


def test_v062_replaces_prompt_style_user_and_group_actions() -> None:
    script = text("web/assets/enhancements-ui-v062.js")
    for selector in ("[data-user-edit]", "[data-user-reset]", "[data-rename-group]"):
        assert selector in script
    assert "interceptLegacyPromptActions" in script
    assert "showModal('修改显示名'" in script
    assert "showModal('设置临时密码'" in script
    assert "showModal('重命名分组'" in script
    assert "event.stopImmediatePropagation()" in script
    assert "prompt(" not in script


def test_v062_separates_bilibili_and_website_account_surfaces() -> None:
    script = text("web/assets/enhancements-ui-v062.js")
    assert 'id = \'v062AccountTabs\'' in script
    assert 'data-v062-account-tab="bilibili"' in script
    assert 'data-v062-account-tab="website"' in script
    assert "网站账号与设备" in script
    assert "/api/auth/sessions" in script
    assert "/api/auth/sessions/revoke-others" in script
    assert "/api/auth/profile" in script


def test_v062_large_dynamic_selects_use_searchable_list() -> None:
    script = text("web/assets/enhancements-ui-v062.js")
    assert "SEARCHABLE_OPTION_THRESHOLD = 8" in script
    assert "SEARCHABLE_SELECT_ID = /(group|user|owner)/i" in script
    assert "openSearchableSelect" in script
    assert "v062-select-option-grid" in script
    assert "输入关键词筛选" in script
