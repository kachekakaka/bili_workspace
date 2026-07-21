from __future__ import annotations

import sqlite3
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
FRONTEND_VERSION = "20260720-2"


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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
    assert "bili_workspace v0.7.0" in text("start.bat")
    assert "v0.7.0 自检全部通过" in text("verify.bat")
    assert "bili_workspace v0.7.0 源码自检完成" in text(
        "scripts/dev/verify-source.sh"
    )
    assert "当前应用版本为 V0.7.0" in text("docs/README.md")


def test_release_document_covers_all_delivery_paths() -> None:
    release = text("docs/V0.7功能与验收.md")
    for token in (
        "Windows 验收",
        "干净 clone",
        "原地升级",
        "Docker / QNAP 验收",
        "数据库 schema 继续为 v4",
        "Python 3.11、3.12、3.13",
        "1920×1080",
        "390×844",
        "v0.6.2",
        "回滚",
    ):
        assert token in release


def test_ci_contains_release_validation_matrix() -> None:
    workflow = text(".github/workflows/ci.yml")
    assert 'python-version: ["3.11", "3.12", "3.13"]' in workflow
    assert "github.head_ref == 'release/v0.7.0'" in workflow
    assert "windows-release:" in workflow
    assert "docker-release:" in workflow
    assert "bili-workspace:v0.7.0" in workflow
    assert "tests/test_v070_release.py" in workflow
    assert "BILI_RUN_PLAYWRIGHT" in workflow


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
