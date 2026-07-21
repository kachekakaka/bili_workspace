from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v062_styles_are_retained_while_behavior_moves_to_modules() -> None:
    index = text("web/index.html")
    assert "/assets/ui-v062.css?v=20260720-2" in index
    assert "/assets/enhancements-ui-v062.js" not in index
    assert "/assets/app/main.mjs?v=20260720-2" in index


def test_v062_control_height_tokens_are_consistent() -> None:
    css = text("web/assets/ui-v062.css")
    assert "--control-height-sm: 32px" in css
    assert "--control-height-md: 40px" in css
    assert "--control-height-lg: 48px" in css
    assert ".input,\n.select" in css
    assert "height: var(--control-height-md)" in css
    assert "min-height: 44px" in css


def test_module_pages_replace_prompt_style_user_and_group_actions() -> None:
    users = text("web/assets/app/pages/users.mjs")
    groups = text("web/assets/app/pages/groups.mjs")
    for control in ("data-user-edit=", "data-user-reset="):
        assert control in users
    assert "data-rename-group=" in groups
    assert "title: '修改显示名'" in users
    assert "title: '设置临时密码'" in users
    assert "title: '重命名分组'" in groups
    combined = users + groups
    assert "stopImmediatePropagation" not in combined
    assert "prompt(" not in combined
    assert "window.confirm" not in combined


def test_module_account_separates_bilibili_and_website_surfaces() -> None:
    script = text("web/assets/app/pages/account.mjs")
    assert 'id="v062AccountTabs"' in script
    assert 'data-v062-account-tab="bilibili"' in script
    assert 'data-v062-account-tab="website"' in script
    assert "网站账号与设备" in text("web/assets/app/main.mjs")
    assert "/api/auth/sessions" in script
    assert "/api/auth/sessions/revoke-others" in script
    assert "/api/auth/profile" in script


def test_large_dynamic_selects_use_the_shared_searchable_component() -> None:
    component = text("web/assets/app/components/searchable-select.mjs")
    download = text("web/assets/app/pages/download.mjs")
    assert "threshold = 8" in component
    assert "mountSearchableSelect" in component
    assert "v062-select-option-grid" in component
    assert "输入关键词筛选" in component
    assert "context.mountSearchableSelect" in download
