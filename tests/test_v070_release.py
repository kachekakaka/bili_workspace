from __future__ import annotations

from pathlib import Path

from app import __version__
from app.build_info import _SOURCE_SUFFIXES, build_metadata
from app.constants import DATABASE_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v070_release_identity_and_build_fingerprint() -> None:
    assert __version__ == "0.7.0"
    assert DATABASE_SCHEMA_VERSION == 4
    assert ".mjs" in _SOURCE_SUFFIXES
    metadata = build_metadata()
    assert metadata["version"] == "0.7.0"
    assert metadata["frontend_version"] == "20260720-2"
    assert len(metadata["build_id"]) == 12


def test_local_verifiers_cover_all_frontend_modules() -> None:
    windows = text("verify.bat")
    source = text("scripts/dev/verify-source.sh")
    assert "for /r \"web\" %%F in (*.mjs)" in windows
    assert "node --test" in windows
    assert "-name '*.mjs'" in source
    assert "node --test tests/frontend/*.test.mjs" in source


def test_v070_release_workflow_is_gated_and_idempotent() -> None:
    workflow = text(".github/workflows/release-v070.yml")
    for token in (
        'workflows: ["CI", "V0.6.2 UI"]',
        "head_branch == 'main'",
        "head_sha",
        "ci_status",
        "ui_status",
        "git tag -a v0.7.0",
        "gh release create v0.7.0",
        "gh release view v0.7.0",
        "docs/releases/V0.7.0.md",
    ):
        assert token in workflow


def test_v070_docs_state_completion_and_rollback_contract() -> None:
    docs = text("docs/README.md")
    plans = text("docs/plans/README.md")
    acceptance = text("docs/V0.7功能与验收.md")
    notes = text("docs/releases/V0.7.0.md")
    assert "当前应用版本为 V0.7.0" in docs
    assert "V0.7.0 前端结构整理方案" in plans
    assert "已完成" in plans
    assert "PR 1–8" in acceptance
    assert "schema v4" in acceptance
    assert "v0.6.2" in acceptance
    assert "bili_workspace v0.7.0" in notes
