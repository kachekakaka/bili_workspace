from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

PR4_SCRIPT_ORDER = [
    "/assets/qrcode.min.js",
    "/assets/enhancements-core.js",
    "/assets/enhancements-tag-palette.js",
    "/assets/enhancements-search.js",
    "/assets/enhancements-library.js",
    "/assets/enhancements-ui-recovery.js",
    "/assets/enhancements-library-overlay.js",
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
    "browser-version.js": 7,
    "app.css": 7,
    "enhancements.css": 7,
    "enhancements-catalog-v2.css": 5,
    "ui-v062.css": 7,
}

REMOVED_ASSETS = [
    "web/assets/enhancements-polish.js",
    "web/assets/enhancements-ui-v062.js",
    "web/assets/enhancements-ui-v062-settings.js",
    "web/assets/ui-v062-settings.css",
    "web/assets/enhancements-task-actions.js",
    "web/assets/enhancements-tasks.js",
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


def test_pr4_keeps_the_module_shell_and_removes_legacy_task_entries() -> None:
    index = _text("web/index.html")
    scripts = [_asset_path(src) for src in re.findall(r'<script[^>]+src="([^"]+)"', index)]
    assert scripts == PR4_SCRIPT_ORDER
    assert 'data-app-shell="module"' in index
    assert '<script type="module" src="/assets/app/main.mjs' in index
    assert '<script src="/assets/app.js' not in index
    assert "enhancements-task-actions.js" not in index
    assert "enhancements-tasks.js" not in index
    assert 'data-enhanced-view="tasks"' not in index


def test_replaced_dom_and_task_assets_are_deleted() -> None:
    index = _text("web/index.html")
    for path in REMOVED_ASSETS:
        assert not (ROOT / path).exists(), path
        assert Path(path).name not in index


def test_remaining_legacy_assets_keep_their_frozen_deletion_stage() -> None:
    inventory = _text("docs/plans/V0.7.0_前端兼容文件清单.md")
    for filename, stage in REMAINING_LEGACY_ASSETS.items():
        assert (WEB / "assets" / filename).is_file(), filename
        assert f"`web/assets/{filename}`" in inventory
        assert f"PR {stage}" in inventory


def test_core_and_components_do_not_read_legacy_globals() -> None:
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


def test_every_page_exports_mount_and_avoids_dom_patch_techniques() -> None:
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


def test_pr4_has_exactly_one_legacy_bridge_file() -> None:
    files = sorted(path.relative_to(ROOT).as_posix() for path in (WEB / "assets" / "app" / "legacy").rglob("*.*"))
    assert files == ["web/assets/app/legacy/bridge.mjs"]
    source = _text(files[0])
    assert "BiliLegacyApp" in source
    assert "BiliEnhancements" in source
    assert "MutationObserver" not in source
    assert "stopImmediatePropagation" not in source
    assert "root.replaceChildren(host)" in source


def test_module_shell_has_single_core_services_and_application_dialogs() -> None:
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


def test_tasks_and_dashboard_share_the_single_task_stream() -> None:
    stream = _text("web/assets/app/core/task-stream.mjs")
    tasks = _text("web/assets/app/pages/tasks.mjs")
    dashboard = _text("web/assets/app/pages/dashboard.mjs")
    assert "url = '/api/events'" in stream
    assert stream.count("new EventSourceImpl(url)") == 1
    assert "context.taskStream.start()" in tasks
    assert "context.taskStream.subscribe(" in tasks
    assert "context.taskStream.subscribeConnection(" in tasks
    assert "context.taskStream.start()" in dashboard
    assert "context.taskStream.subscribe(" in dashboard
    assert "legacyBridge" not in tasks
    assert "new EventSource" not in tasks
    assert "new EventSource" not in dashboard


def test_tasks_preserve_filters_actions_and_application_confirmations() -> None:
    tasks = _text("web/assets/app/pages/tasks.mjs")
    for token in (
        "enhTaskOwner",
        "enhTaskDestination",
        "enhTaskStatus",
        "enhTaskSort",
        "enhTaskDirection",
        "enhTaskGroupByUser",
        "按用户分组显示",
        "data-task-action",
        "data-task-log",
        "data-task-edit-retry",
        "编辑画质并重试",
        "/api/enhancements/tasks/batch",
        "/api/enhancements/tasks/clear",
        "context.confirm",
    ):
        assert token in tasks
    assert "window.confirm" not in tasks
    assert "confirm(" not in tasks


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
