from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "plans" / "V0.6.0_多用户搜索与会话方案.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v060_plan_is_indexed_and_not_claimed_as_current() -> None:
    assert PLAN.is_file()
    plan = _text(PLAN)
    docs_index = _text(ROOT / "docs" / "README.md")
    current = _text(ROOT / "docs" / "需求落实清单.md")

    assert "状态：**已批准，等待开发**" in plan
    assert "plans/V0.6.0_多用户搜索与会话方案.md" in docs_index
    assert "尚未实现" in docs_index
    assert "尚未实现" in current
    assert "不得提前把计划功能写成当前能力" in current


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
    archived = ROOT / "docs" / "archive" / "v0.5" / "V0.5功能与验收.md"
    archive_index = _text(ROOT / "docs" / "archive" / "README.md")

    assert not current.exists()
    assert archived.is_file()
    assert "V0.5功能与验收.md" in archive_index
    assert "不得作为后续功能设计依据" in _text(archived)
