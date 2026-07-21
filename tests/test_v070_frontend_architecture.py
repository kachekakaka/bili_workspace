from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

PR3_SCRIPT_ORDER = [
    "/assets/qrcode.min.js",
    "/assets/enhancements-core.js",
    "/assets/enhancements-tag-palette.js",
    "/assets/enhancements-search.js",
    "/assets/enhancements-library.js",
    "/assets/enhancements-ui-recovery.js",
    "/assets/enhancements-library-overlay.js",
    "/assets/enhancements-task-actions.js",
    "/assets/enhancements-tasks.js",
    "/assets/browser-version.js",
    "/assets/app/main.mjs",
]

REMAINING_LEGACY_ASSETS = {
    "app.js": 7,
    "enhancements-core.js": 7,
    "enhancements-tag-palette.js": 5,
    "enhancements-search.js": 6,
    "enhancements-library.js": 5,
    "enhancements-ui-recovery.js": 5,
    "enhancements-library-overlay.js": 5,
    "enhancements-task-actions.js": 4,
    "enhancements-tasks.js": 4,
    "browser-version.js": 7,
    "app.css": 7,
    "enhancements.css": 7,
    "enhancements-catalog-v2.css": 5,
    "ui-v062.css": 7,
}

PR3_REMOVED_ASSETS = [
    "web/assets/enhancements-polish.js",
    "web/assets/enhancements-ui-v062.js",
    "web/assets/enhancements-ui-v062-settings.js",
    "web/assets/ui-v062-settings.css",
]

CORE_MODULES = [
    "web/assets/app/core/route-policy.mjs",
    "web/assets/app/core/lifecycle.mjs",
    "web/assets/app/core/format.mjs",
    "web/assets/app/core/search-policy.mjs",
    "web/assets/app/core/api.mjs",
    "web/assets/app/core/router.mjs",
    "web/assets/app/core/auth-session.mjs",
    "web/assets/app/core/context-store.mjs",
    "web/assets/app/core/task-stream.mjs",
]

COMPONENT_MODULES = [
    "web/assets/app/components/modal.mjs",
    "web/assets/app/components/confirm-dialog.mjs",
    "web/assets/app/components/toast.mjs",
    "web/assets/app/components/searchable-select.mjs",
]

PAGE_MODULES = [
    "dashboard",
    "download",
    "search",
    "library",
    "groups",
    "tasks",
    "users",
    "account",
    "settings",
    "more",
]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _asset_path(src: str) -> str:
    return src.split("?", 1)[0]


def test_pr3_switches_to_the_module_shell_without_loading_app_js() -> None:
    index = _text("web/index.html")
    scripts = [_asset_path(src) for src in re.findall(r'<script[^>]+src="([^"]+)"', index)]
    assert scripts == PR3_SCRIPT_ORDER
    assert 'data-app-shell="module"' in index
    assert '<script type="module" src="/assets/app/main.mjs' in index
    assert '<script src="/assets/app.js' not in index
    assert "/assets/ui-v062-settings.css" not in index


def test_pr3_removes_the_replaced_dom_postprocessing_assets() -> None:
    for path in PR3_REMOVED_ASSETS:
        assert not (ROOT / path).exists(), path
    index = _text("web/index.html")
    for path in PR3_REMOVED_ASSETS:
        assert Path(path).name not in index


def test_remaining_legacy_assets_keep_their_frozen_deletion_stage() -> None:
    inventory = _text("docs/plans/V0.7.0_前端兼容文件清单.md")
    for filename, stage in REMAINING_LEGACY_ASSETS.items():
        assert (WEB / "assets" / filename).is_file(), filename
        assert f"`web/assets/{filename}`" in inventory
        assert f"PR {stage}" in inventory


def test_pr3_core_and_components_do_not_read_legacy_globals() -> None:
    for path in [*CORE_MODULES, *COMPONENT_MODULES]:
        module = ROOT / path
        assert module.is_file(), path
        source = module.read_text(encoding="utf-8")
        assert "export " in source
        assert "BiliEnhancements" not in source, path
        assert "BiliLegacyApp" not in source, path
        assert "MutationObserver" not in source, path
        assert "stopImmediatePropagation" not in source, path

    assert not (ROOT / "package.json").exists()
    assert not (ROOT / "package-lock.json").exists()


def test_every_pr3_page_exports_mount_and_avoids_dom_patch_techniques() -> None:
    forbidden = (
        "MutationObserver",
        "stopImmediatePropagation",
        "window.prompt",
        "window.confirm",
        "globalThis.prompt",
        "globalThis.confirm",
        "BiliEnhancements",
        "BiliLegacyApp",
    )
    for page in PAGE_MODULES:
        path = f"web/assets/app/pages/{page}.mjs"
        source = _text(path)
        assert "export async function mount(" in source, path
        for token in forbidden:
            assert token not in source, f"{path}: {token}"
        assert re.search(r"(?<![.\w])prompt\(", source) is None, path
        assert re.search(r"(?<![.\w])confirm\(", source) is None, path


def test_pr3_has_exactly_one_legacy_bridge_file() -> None:
    files = sorted(path.relative_to(ROOT).as_posix() for path in (WEB / "assets" / "app" / "legacy").rglob("*.*"))
    assert files == ["web/assets/app/legacy/bridge.mjs"]
    source = _text(files[0])
    assert "BiliLegacyApp" in source
    assert "BiliEnhancements" in source
    assert "MutationObserver" not in source
    assert "stopImmediatePropagation" not in source
    assert "root.replaceChildren(host)" in source


def test_module_shell_has_single_low_risk_renderers_and_application_dialogs() -> None:
    main = _text("web/assets/app/main.mjs")
    assert "createApiClient" in main
    assert "createRouter" in main
    assert "createSessionStore" in main
    assert "createModalService" in main
    assert "createToastService" in main
    assert "createConfirmDialog" in main
    assert "window.prompt" not in main
    assert "window.confirm" not in main
    assert "MutationObserver" not in main
    assert "stopImmediatePropagation" not in main

    users = _text("web/assets/app/pages/users.mjs")
    groups = _text("web/assets/app/pages/groups.mjs")
    assert "v062UserDisplayNameForm" in users
    assert "v062UserPasswordForm" in users
    assert "v062GroupRenameForm" in groups


def test_v070_does_not_create_versioned_overlay_files() -> None:
    forbidden = [*WEB.rglob("enhancements-v070-*"), *WEB.rglob("ui-v070-*")]
    assert forbidden == []


def test_node_test_and_mjs_syntax_gates_are_in_ci() -> None:
    workflow = _text(".github/workflows/ci.yml")
    assert "-name '*.mjs'" in workflow
    assert "node --test tests/frontend/*.test.mjs" in workflow
    assert "tests/test_v070_frontend_architecture.py" in workflow


def test_frontend_node_tests_are_dependency_free_es_modules() -> None:
    tests = sorted((ROOT / "tests" / "frontend").glob("*.test.mjs"))
    assert tests
    for test_file in tests:
        source = test_file.read_text(encoding="utf-8")
        assert "node:test" in source
        assert "node:assert" in source
        assert "node_modules" not in source
