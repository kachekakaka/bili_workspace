from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app.constants import (
    ADMIN_TASK_HISTORY_LIMIT,
    APP_VERSION,
    DATABASE_SCHEMA_VERSION,
    MAX_ACTIVE_SESSIONS_PER_USER,
    NORMAL_USER_ACTIVE_TASK_LIMIT,
    NORMAL_USER_TASK_HISTORY_LIMIT,
    NORMAL_USER_TASK_RETENTION_DAYS,
    SEARCH_PAGE_CACHE_SECONDS,
    WBI_KEY_CACHE_SECONDS,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_VERSION = "20260809-1"


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_repository_uses_one_python_311_baseline() -> None:
    assert sys.version_info[:2] == (3, 11)
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )
    assert 'python-version: "3.12"' not in workflows
    assert 'python-version: "3.13"' not in workflows
    dockerfile = text("docker/Dockerfile")
    assert "FROM python:3.11.15-slim-bookworm@sha256:" in dockerfile
    launcher_script = text("scripts/windows/build-launcher.bat")
    assert r".venv\Scripts\python.exe" in launcher_script
    assert "bili-launcher-py311" not in launcher_script
    assert "BILI_LAUNCHER_PYTHON" not in launcher_script
    source_verifier = text("tools/verify_source.py")
    assert 're.fullmatch(r"3\\.11\\.\\d+", raw["python_version"])' in source_verifier
    assert 're.fullmatch(r"3\\.13\\.\\d+", raw["python_version"])' not in source_verifier


def test_v070_version_and_frozen_constants() -> None:
    assert APP_VERSION == "0.7.0"
    assert DATABASE_SCHEMA_VERSION == 4
    assert MAX_ACTIVE_SESSIONS_PER_USER == 10
    assert NORMAL_USER_TASK_RETENTION_DAYS == 7
    assert NORMAL_USER_TASK_HISTORY_LIMIT == 100
    assert NORMAL_USER_ACTIVE_TASK_LIMIT == 10
    assert ADMIN_TASK_HISTORY_LIMIT == 500
    assert WBI_KEY_CACHE_SECONDS == 600
    assert SEARCH_PAGE_CACHE_SECONDS == 180


def test_release_versions_are_synchronized() -> None:
    index = text("web/index.html")
    main = text("web/assets/app/main.mjs")
    assert f'data-frontend-version="{FRONTEND_VERSION}"' in index
    assert f"const LOADED_FRONTEND_VERSION = '{FRONTEND_VERSION}';" in main
    assert "V0.7.0" in index
    assert "# bili_workspace v0.7.0" in text("README.md")
    assert "## 0.7.0 - 2026-07-21" in text("CHANGELOG.md")
    assert "bili-workspace-launcher-0.7.0.exe" in text("README.md")
    assert "bili_workspace v0.7.0 源码自检完成" in text(
        "scripts/dev/verify-source.sh"
    )
    docs_index = text("docs/README.md")
    assert "活动文档总入口" in docs_index
    assert "CHANGELOG.md" in docs_index


def test_current_docs_cover_all_delivery_and_recovery_paths() -> None:
    requirements = text("docs/需求文档.md")
    design = text("docs/设计文档.md")
    operations = text("docs/运维/发布与回滚流程.md")
    archived = text("archive/docs/releases/V0.7功能与验收.md")

    for token in (
        "Windows 本机",
        "QNAP/NAS Docker",
        "数据库 schema 为 v4",
        "五档固定视口",
        "停止未来正式发布",
    ):
        assert token in requirements + design
    for token in (
        "Windows 源码更新",
        "Docker 源码构建与更新",
        "BUILD_LOCAL=true",
        "代码回滚",
        "数据恢复",
    ):
        assert token in operations
    assert "历史快照" in archived
    assert "v0.6.2" in archived


def test_ci_uses_one_python_311_baseline_for_all_active_jobs() -> None:
    workflow = text(".github/workflows/ci.yml")
    browser_phase = text("scripts/dev/run-playwright-phase.sh")
    assert workflow.count('python-version: "3.11"') == 6
    assert 'python-version: "3.12"' not in workflow
    assert 'python-version: "3.13"' not in workflow
    assert "matrix.python-version" not in workflow
    assert "product-validation:" in workflow
    assert "windows-validation:" in workflow
    assert "docker-validation:" in workflow
    assert "bili-workspace:validation" in workflow
    for obsolete in (
        "release-validation:",
        "windows-release:",
        "docker-release:",
        "Build release image",
        "bili-workspace:v0.7.0",
        "github.head_ref == 'release/v0.7.0'",
        "github.head_ref == 'agent/v060-release-validation'",
        "github.head_ref == 'agent/v060-userless-db-migration'",
        "github.head_ref == 'feature/ui-v0.6.2'",
    ):
        assert obsolete not in workflow
    assert "tests/test_v070_release.py" in workflow
    assert "BILI_RUN_PLAYWRIGHT" in browser_phase
    assert "python -B -X utf8 -m pytest -q launcher/tests" in workflow
    assert "verify.bat" not in workflow
    assert "tests/test_integrated_runtime.py" not in workflow


def test_migration_backup_is_a_restorable_sqlite_database(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker VALUES('v070')")
        conn.execute("PRAGMA user_version=4")
        conn.commit()
        with sqlite3.connect(backup) as target:
            conn.backup(target)
    with sqlite3.connect(backup) as restored:
        assert restored.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert restored.execute("PRAGMA user_version").fetchone() == (4,)
        assert restored.execute("SELECT value FROM marker").fetchone() == ("v070",)
