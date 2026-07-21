from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
APP = WEB / "assets" / "app"

PAGE_MODULES = [
    "dashboard", "download", "search", "library", "groups",
    "tasks", "users", "account", "settings", "more",
]
CORE_MODULES = [
    "api.mjs", "auth-session.mjs", "context-store.mjs", "format.mjs",
    "lifecycle.mjs", "route-policy.mjs", "router.mjs", "search-policy.mjs",
    "task-stream.mjs", "version-check.mjs",
]
REMOVED_ASSETS = [
    "web/assets/app.js",
    "web/assets/enhancements-core.js",
    "web/assets/browser-version.js",
    "web/assets/app.css",
    "web/assets/enhancements.css",
    "web/assets/ui-v062.css",
    "web/assets/enhancements-polish.js",
    "web/assets/enhancements-ui-v062.js",
    "web/assets/enhancements-ui-v062-settings.js",
    "web/assets/ui-v062-settings.css",
    "web/assets/enhancements-task-actions.js",
    "web/assets/enhancements-tasks.js",
    "web/assets/enhancements-tag-palette.js",
    "web/assets/enhancements-library.js",
    "web/assets/enhancements-ui-recovery.js",
    "web/assets/enhancements-library-overlay.js",
    "web/assets/enhancements-catalog-v2.css",
    "web/assets/enhancements-search.js",
    "web/assets/app/legacy/bridge.mjs",
]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _asset_path(src: str) -> str:
    return src.split("?", 1)[0]


def test_final_index_has_one_application_entry_and_semantic_css() -> None:
    index = _text("web/index.html")
    scripts = [_asset_path(src) for src in re.findall(r'<script[^>]+src="([^"]+)"', index)]
    assert scripts == ["/assets/qrcode.min.js", "/assets/app/main.mjs"]
    application_scripts = [path for path in scripts if path != "/assets/qrcode.min.js"]
    assert application_scripts == ["/assets/app/main.mjs"]
    assert 'type="module" src="/assets/app/main.mjs' in index
    styles = [_asset_path(src) for src in re.findall(r'<link[^>]+href="([^"]+\.css[^\"]*)"', index)]
    assert styles == [
        "/assets/styles/tokens.css",
        "/assets/styles/base.css",
        "/assets/styles/components.css",
        "/assets/styles/pages.css",
    ]


def test_all_replaced_assets_and_the_legacy_directory_are_deleted() -> None:
    index = _text("web/index.html")
    for path in REMOVED_ASSETS:
        assert not (ROOT / path).exists(), path
        assert Path(path).name not in index
    legacy = APP / "legacy"
    assert not legacy.exists() or not any(legacy.rglob("*"))
    assert not list(WEB.rglob("enhancements-*.js"))
    assert not list(WEB.rglob("enhancements-*.css"))
    assert not list(WEB.rglob("ui-v*.css"))


def test_every_page_has_mount_dispose_and_no_patch_techniques() -> None:
    forbidden = (
        "MutationObserver",
        "stopImmediatePropagation",
        "window.prompt",
        "window.confirm",
        "globalThis.prompt",
        "globalThis.confirm",
        "BiliEnhancements",
        "BiliLegacyApp",
        "context.legacy",
        "syncLegacy",
    )
    for page in PAGE_MODULES:
        path = f"web/assets/app/pages/{page}.mjs"
        source = _text(path)
        assert "export async function mount(" in source, path
        assert "dispose" in source, path
        for token in forbidden:
            assert token not in source, f"{path}: {token}"
        assert re.search(r"(?<![.\w])prompt\(", source) is None, path
        assert re.search(r"(?<![.\w])confirm\(", source) is None, path


def test_core_and_components_export_modules_without_application_globals() -> None:
    module_paths = [
        *(f"web/assets/app/core/{name}" for name in CORE_MODULES),
        "web/assets/app/components/modal.mjs",
        "web/assets/app/components/confirm-dialog.mjs",
        "web/assets/app/components/toast.mjs",
        "web/assets/app/components/searchable-select.mjs",
    ]
    for path in module_paths:
        source = _text(path)
        assert "export " in source, path
        for token in (
            "BiliEnhancements", "BiliLegacyApp", "MutationObserver",
            "stopImmediatePropagation", "Object.defineProperty(window",
        ):
            assert token not in source, f"{path}: {token}"
    assert not (ROOT / "package.json").exists()
    assert not (ROOT / "package-lock.json").exists()


def test_main_owns_one_api_session_modal_toast_router_and_task_stream() -> None:
    main = _text("web/assets/app/main.mjs")
    for token in (
        "createApiClient", "createSessionStore", "createContextStore",
        "createRouter", "createTaskStream", "createModalService",
        "createToastService", "createConfirmDialog", "createVersionChecker",
    ):
        assert main.count(token) >= 1
    assert main.count("createApiClient({") == 1
    assert main.count("createSessionStore()") == 1
    assert main.count("createTaskStream()") == 1
    assert main.count("createModalService(") == 1
    assert main.count("createToastService(") == 1
    for token in (
        "BiliEnhancements", "BiliLegacyApp", "legacyBridge", "syncLegacy",
        "MutationObserver", "stopImmediatePropagation", "window.prompt", "window.confirm",
    ):
        assert token not in main


def test_task_stream_and_route_generation_contracts_remain_single() -> None:
    stream = _text("web/assets/app/core/task-stream.mjs")
    router = _text("web/assets/app/core/router.mjs")
    tasks = _text("web/assets/app/pages/tasks.mjs")
    dashboard = _text("web/assets/app/pages/dashboard.mjs")
    assert "url = '/api/events'" in stream
    assert stream.count("new EventSourceImpl(url)") == 1
    assert "createGenerationGate" in router
    assert "controller.abort()" in router
    assert "context.taskStream.start()" in tasks
    assert "context.taskStream.subscribe(" in tasks
    assert "context.taskStream.start()" in dashboard
    assert "context.taskStream.subscribe(" in dashboard
    assert "bili-v070-library-query" in tasks


def test_version_mismatch_recovery_is_in_core_without_dom_observation() -> None:
    version = _text("web/assets/app/core/version-check.mjs")
    main = _text("web/assets/app/main.mjs")
    for token in (
        "versionMismatchReason",
        "版本不一致",
        "服务仍是旧版",
        "点击恢复",
        "location?.reload",
        "data.recoveryAction".replace("data.", "dataset."),
        "fetchImpl(`/healthz?_=${Date.now()}`",
    ):
        assert token in version
    assert "MutationObserver" not in version
    assert "createVersionChecker" in main
    assert "versionChecker.refresh()" in main


def test_semantic_css_layers_preserve_required_contracts() -> None:
    tokens = _text("web/assets/styles/tokens.css")
    base = _text("web/assets/styles/base.css")
    components = _text("web/assets/styles/components.css")
    pages = _text("web/assets/styles/pages.css")
    for token in ("--control-height-sm", "--control-height-md", "--control-height-lg"):
        assert token in tokens
    for token in (".app-root", ".sidebar", ".modal-root", ".mobile-nav"):
        assert token in base
    for token in (
        ".enh-search-primary-grid", ".enh-library-chip-filters",
        ".enh-task-filter-strip", ".enh-pagination",
    ):
        assert token in components
    for token in (".v062-account-tabs", ".v062-session-row", ".user-table-shell"):
        assert token in pages


def test_v070_does_not_create_versioned_overlay_files() -> None:
    assert [*WEB.rglob("enhancements-v070-*"), *WEB.rglob("ui-v070-*")] == []


def test_node_and_playwright_gates_are_in_ci() -> None:
    workflow = _text(".github/workflows/ci.yml")
    assert "-name '*.mjs'" in workflow
    assert "node --test tests/frontend/*.test.mjs" in workflow
    assert "tests/test_v070_frontend_architecture.py" in workflow
    assert "tests/test_v070_*_playwright.py" in workflow
