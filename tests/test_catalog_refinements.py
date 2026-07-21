from __future__ import annotations

from pathlib import Path

from tests._catalog_refinements_original import *  # noqa: F401,F403

ROOT = Path(__file__).resolve().parent.parent


def test_frontend_search_and_library_are_integrated_without_overlay_competition():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    search = (ROOT / "web" / "assets" / "app" / "pages" / "search.mjs").read_text(
        encoding="utf-8"
    )
    library = (
        ROOT / "web" / "assets" / "app" / "pages" / "library-impl.mjs"
    ).read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "styles" / "components.css").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "web" / "assets" / "app" / "main.mjs").read_text(
        encoding="utf-8"
    )

    for removed in (
        "app.js",
        "enhancements-core.js",
        "enhancements-search.js",
        "enhancements-search-overlay.js",
        "enhancements-deletion-status.js",
        "enhancements-library.js",
        "enhancements-library-overlay.js",
        "enhancements-ui-recovery.js",
        "enhancements-tag-palette.js",
        "enhancements-catalog-v2.css",
    ):
        assert removed not in index
        assert not (ROOT / "web" / "assets" / removed).exists()
    assert "import * as searchPage from './pages/search.mjs';" in main
    assert "import * as libraryPage from './pages/library.mjs';" in main
    for token in (
        "精准：标题包含全部词",
        "模糊：标题包含任意词",
        "屏蔽已下载和已删除",
        "AbortController",
        "requestIdleCallback",
        "navigator?.connection",
        "刷新B站结果",
        "本页没有标题匹配项，可查看下一页；系统不会自动抓取全部页面。",
        "仍停留在搜索页",
    ):
        assert token in search
    for forbidden in ("tags/bulk", "MutationObserver", "insertBefore", "enh-spacer"):
        assert forbidden not in search
    for token in (
        "无标签",
        "data-library-group-chip",
        "data-library-move",
        "修改作品分组",
        "context.confirm",
    ):
        assert token in library
    for forbidden in ("MutationObserver", "stopImmediatePropagation", "window.confirm"):
        assert forbidden not in library
    assert ".enh-chip-strip" in css
    assert ".enh-colored-filter-chip" in css
