from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "archive" / "docs" / "plans" / "V0.6.0_多用户搜索与会话方案.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v060_plan_tracks_completed_release() -> None:
    assert PLAN.is_file()
    plan = _text(PLAN)
    docs_index = _text(ROOT / "docs" / "README.md")
    requirements = _text(ROOT / "docs" / "需求文档.md")
    fields = _text(ROOT / "docs" / "字段契约.md")
    archive_index = _text(ROOT / "archive" / "docs" / "README.md")

    assert "状态：**已完成（PR 1–5 已合并，V0.6.0 已发布）**" in plan
    assert "### PR 1：搜索和布局" in plan
    assert "状态：已完成（PR #17）" in plan
    assert "状态：已完成（PR #18）" in plan
    assert "状态：已完成（PR #19）" in plan
    assert "状态：已完成（PR #20）" in plan
    assert "plans/V0.6.0_多用户搜索与会话方案.md" in archive_index
    assert "V0.6 账号权限与会话管理" in archive_index
    assert "V0.6 任务所有权与保留策略" in archive_index
    assert "活动文档总入口" in docs_index
    for entry in ("需求文档.md", "字段契约.md", "../archive/docs/README.md"):
        assert entry in docs_index
    assert "每用户最多 10 个有效会话" in requirements
    assert "普通用户最多同时拥有 10 个" in requirements
    assert "手机和平板可触控控件不低于 44px" in requirements
    assert "MAX_ACTIVE_SESSIONS_PER_USER" in fields
    assert (ROOT / "archive" / "docs" / "v0.6" / "账号权限与会话管理.md").is_file()
    assert (ROOT / "archive" / "docs" / "v0.6" / "任务所有权与保留策略.md").is_file()
    assert (ROOT / "archive" / "docs" / "releases" / "V0.6功能与验收.md").is_file()
    assert not (ROOT / "docs" / "账号权限与会话管理.md").exists()
    assert not (ROOT / "docs" / "任务所有权与保留策略.md").exists()
    assert "状态：已完成（PR #21）" in plan


def test_v060_frozen_limits_and_test_scope_are_documented() -> None:
    plan = _text(PLAN)
    for token in (
        "MAX_ACTIVE_SESSIONS_PER_USER = 10",
        "NORMAL_USER_TASK_RETENTION_DAYS = 7",
        "NORMAL_USER_TASK_HISTORY_LIMIT = 100",
        "NORMAL_USER_ACTIVE_TASK_LIMIT = 10",
        "ADMIN_TASK_HISTORY_LIMIT = 500",
        "不预加载第三页",
        "HttpOnly",
        "每用户最多 10 个有效 Token",
        "测试方案",
        "Playwright Chromium",
        "开发和合并顺序",
        "可复制的接力提示词",
    ):
        assert token in plan


def test_v05_acceptance_checklist_is_archived() -> None:
    current = ROOT / "docs" / "V0.5功能与验收.md"
    archived = ROOT / "archive" / "docs" / "v0.5" / "V0.5功能与验收.md"
    archive_index = _text(ROOT / "archive" / "docs" / "README.md")

    assert not current.exists()
    assert archived.is_file()
    assert "V0.5功能与验收.md" in archive_index
    assert "不得作为后续功能设计依据" in _text(archived)
