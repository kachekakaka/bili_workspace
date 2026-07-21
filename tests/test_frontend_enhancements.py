from __future__ import annotations

from pathlib import Path

from tests._frontend_enhancements_original import *  # noqa: F401,F403

ROOT = Path(__file__).resolve().parent.parent


def test_frontend_exposes_requested_controls_after_final_migration():
    search = (ROOT / "web" / "assets" / "app" / "pages" / "search.mjs").read_text(
        encoding="utf-8"
    )
    library = (
        ROOT / "web" / "assets" / "app" / "pages" / "library-impl.mjs"
    ).read_text(encoding="utf-8")
    tasks = (ROOT / "web" / "assets" / "app" / "pages" / "tasks.mjs").read_text(
        encoding="utf-8"
    )
    dashboard = (
        ROOT / "web" / "assets" / "app" / "pages" / "dashboard.mjs"
    ).read_text(encoding="utf-8")
    download = (
        ROOT / "web" / "assets" / "app" / "pages" / "download.mjs"
    ).read_text(encoding="utf-8")

    for token in (
        "屏蔽已下载和已删除",
        "B站原页面",
        "data-search-page",
        "标题二级筛选",
        "刷新B站结果",
        "shouldPrefetchNextPage",
        "requestGeneration",
        "仍停留在搜索页",
    ):
        assert token in search
    for token in (
        "enhLibraryTag",
        "enhLibrarySortField",
        "duration",
        "group",
        "tag",
        "下载到设备",
        "__untagged__",
        "data-library-move",
        "enhMediaPlayer",
        "mark_tag: ''",
    ):
        assert token in library
    for token in (
        "enhTaskOwner",
        "enhTaskSort",
        "enhTaskDirection",
        "按用户分组显示",
        "owner_user_id",
        "全部重试失败",
        "当前大小",
        "speed_text",
        "task.duration",
        "编辑画质并重试",
        "min_height",
        "preferred_quality",
        "原任务 ID",
    ):
        assert token in tasks
    assert "enh-dashboard-stack" in dashboard
    assert 'id="downloadForm"' in download
