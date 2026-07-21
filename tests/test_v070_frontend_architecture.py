from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

CURRENT_SCRIPT_ORDER = [
    "/assets/qrcode.min.js",
    "/assets/app.js",
    "/assets/enhancements-core.js",
    "/assets/enhancements-tag-palette.js",
    "/assets/enhancements-search.js",
    "/assets/enhancements-library.js",
    "/assets/enhancements-ui-recovery.js",
    "/assets/enhancements-library-overlay.js",
    "/assets/enhancements-task-actions.js",
    "/assets/enhancements-tasks.js",
    "/assets/enhancements-polish.js",
    "/assets/enhancements-ui-v062.js",
    "/assets/enhancements-ui-v062-settings.js",
    "/assets/browser-version.js",
    "/assets/app/legacy/bridge.mjs",
]

LEGACY_DELETION_STAGE = {
    "app.js": 7,
    "enhancements-core.js": 7,
    "enhancements-tag-palette.js": 5,
    "enhancements-search.js": 6,
    "enhancements-library.js": 5,
    "enhancements-ui-recovery.js": 5,
    "enhancements-library-overlay.js": 5,
    "enhancements-task-actions.js": 4,
    "enhancements-tasks.js": 4,
    "enhancements-polish.js": 3,
    "enhancements-ui-v062.js": 3,
    "enhancements-ui-v062-settings.js": 3,
    "browser-version.js": 7,
    "app.css": 7,
    "enhancements.css": 7,
    "enhancements-catalog-v2.css": 5,
    "ui-v062.css": 7,
    "ui-v062-settings.css": 3,
}

PURE_MODULES = [
    "web/assets/app/core/route-policy.mjs",
    "web/assets/app/core/lifecycle.mjs",
    "web/assets/app/core/format.mjs",
    "web/assets/app/core/search-policy.mjs",
]

CORE_MODULES = [
    *PURE_MODULES,
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


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _asset_path(src: str) -> str:
    return src.split("?", 1)[0]


def test_pr2_keeps_legacy_shell_explicit_and_independently_bootable() -> None:
    index = _text("web/index.html")
    scripts = [_asset_path(src) for src in re.findall(r'<script[^>]+src="([^"]+)"', index)]
    assert scripts == CURRENT_SCRIPT_ORDER
    assert 'data-app-shell="legacy"' in index
    assert '<script src="/assets/app.js' in index
    assert '<script type="module" src="/assets/app/legacy/bridge.mjs' in index
    assert "/assets/app/main.mjs" not in index


def test_legacy_files_exist_and_have_a_frozen_deletion_stage() -> None:
    inventory = _text("docs/plans/V0.7.0_前端兼容文件清单.md")
    for filename, stage in LEGACY_DELETION_STAGE.items():
        assert (WEB / "assets" / filename).is_file(), filename
        assert f"`web/assets/{filename}`" in inventory
        assert f"PR {stage}" in inventory


def test_pr2_core_and_components_do_not_read_legacy_globals() -> None:
    for path in [*CORE_MODULES, *COMPONENT_MODULES]:
        module = ROOT / path
        assert module.is_file(), path
        source = module.read_text(encoding="utf-8")
        assert "export " in source
        assert "BiliEnhancements" not in source, path
        assert "BiliLegacyApp" not in source, path
        assert "MutationObserver" not in source, path
        assert "stopImmediatePropagation" not in source, path

    for path in PURE_MODULES:
        source = _text(path)
        assert "window." not in source, path
        assert "document." not in source, path

    assert not (ROOT / "package.json").exists()
    assert not (ROOT / "package-lock.json").exists()


def test_pr2_has_exactly_one_legacy_bridge_file() -> None:
    files = sorted(path.relative_to(ROOT).as_posix() for path in (WEB / "assets" / "app" / "legacy").rglob("*.*"))
    assert files == ["web/assets/app/legacy/bridge.mjs"]
    source = _text(files[0])
    assert "BiliLegacyApp" in source
    assert "BiliEnhancements" in source
    assert "MutationObserver" not in source
    assert "stopImmediatePropagation" not in source


def test_v070_does_not_create_versioned_overlay_files() -> None:
    forbidden = [
        *WEB.rglob("enhancements-v070-*"),
        *WEB.rglob("ui-v070-*"),
    ]
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
