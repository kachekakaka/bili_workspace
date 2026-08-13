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
    assert metadata["frontend_version"] == "20260809-1"
    assert len(metadata["build_id"]) == 12


def test_local_verifiers_cover_all_frontend_modules() -> None:
    source = text("scripts/dev/verify-source.sh")
    browser_phase = text("scripts/dev/run-playwright-phase.sh")
    assert "-name '*.mjs'" in source
    assert "node --test tests/frontend/*.test.mjs" in source
    assert "T-PROJECT 完整源码自检要求 Node.js" in source
    assert "BILI_RUN_PLAYWRIGHT=1" in source
    assert "-B -X utf8 tools/playwright_runtime.py" in source
    assert "playwright install" not in source
    assert "-m playwright" in browser_phase
    assert "tools/t_project_isolation.py create" in browser_phase
    assert "tools/t_project_isolation.py record" in browser_phase
    assert not (ROOT / ".github" / "workflows" / "ui-v062.yml").exists()
    assert "SoftwareTesting/doc_consistency/test_doc_consistency.py" not in source


def test_v070_release_regression_now_enforces_no_formal_publication() -> None:
    active_release = ROOT / ".github" / "workflows" / "release-v070.yml"
    archived_release = ROOT / "archive" / "docs" / "workflows" / "release-v070.yml"
    docker = text(".github/workflows/docker-image.yml")
    decision = text("docs/adr/0002-source-push-does-not-publish.md")

    assert not active_release.exists()
    assert archived_release.is_file()
    historical = archived_release.read_text(encoding="utf-8")
    assert "git tag -a v0.7.0" in historical
    assert "gh release create v0.7.0" in historical
    assert "gh workflow run docker-image.yml" in historical

    for token in (
        "contents: read",
        "platforms: linux/amd64,linux/arm64",
        "push: false",
        "Build amd64/arm64 image without publishing",
        "- app/defaults/**",
        "- THIRD_PARTY_NOTICES.md",
        "- LICENSES/**",
    ):
        assert token in docker
    for forbidden in (
        "packages: write",
        "docker/login-action",
        "push: true",
        "workflow_dispatch:",
        "release_tag",
        "type=ref,event=tag",
        "ghcr.io/",
    ):
        assert forbidden not in docker

    active_workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )
    for forbidden in (
        "git tag -a ",
        "gh release create ",
        "git push origin refs/tags/",
        "docker/login-action",
        "push: true",
    ):
        assert forbidden not in active_workflows
    assert "停止未来的正式发布" in decision


def test_v070_historical_docs_are_archived_and_current_facts_are_routed() -> None:
    readme = text("README.md")
    docs = text("docs/README.md")
    requirements = text("docs/需求文档.md")
    design = text("docs/设计文档.md")
    fields = text("docs/字段契约.md")
    archive_index = text("archive/docs/README.md")
    acceptance = text("archive/docs/releases/V0.7功能与验收.md")
    notes = text("archive/docs/releases/V0.7.0.md")
    update_process = text("docs/运维/发布与回滚流程.md")

    assert "当前应用版本为 V0.7.0" in readme
    assert "活动文档总入口" in docs
    assert "CHANGELOG.md" in docs
    assert "停止未来正式发布" in requirements
    assert "当前已交付" in requirements
    assert "前端架构与页面生命周期" in design
    assert "DATABASE_SCHEMA_VERSION" in fields
    assert "V0.7.0 功能与验收" in archive_index
    assert "历史快照" in acceptance
    assert "bili_workspace v0.7.0" in notes
    assert "BUILD_LOCAL=true" in update_process
    assert not (ROOT / "docs" / "V0.7功能与验收.md").exists()
    assert not (ROOT / "docs" / "releases" / "V0.7.0.md").exists()
