from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_root_only_contains_primary_windows_entrypoints() -> None:
    script_suffixes = {".bat", ".cmd", ".ps1", ".sh"}
    scripts = {
        path.name
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix.lower() in script_suffixes
    }
    assert scripts == {"start.bat", "update.bat", "verify.bat"}


def test_helpers_and_dependency_locks_are_grouped() -> None:
    expected = (
        "requirements/dev.lock",
        "requirements/runtime.lock",
        "scripts/README.md",
        "scripts/windows/bootstrap-portable.ps1",
        "scripts/windows/bootstrap-runtime.bat",
        "scripts/windows/prepare-runtime.bat",
        "scripts/windows/configure-network.bat",
        "scripts/windows/bilibili-login.bat",
        "scripts/dev/verify-source.sh",
    )
    for name in expected:
        assert (ROOT / name).is_file(), name

    obsolete = (
        "bootstrap.bat",
        "configure_network.bat",
        "login.bat",
        "run.bat",
        "setup.bat",
        "verify-source.bat",
        "verify-source.sh",
        "requirements-dev.txt",
        "requirements.txt",
        "requirements.lock",
        "requirements-runtime.lock",
        "pytest.ini",
        "tools/bootstrap_portable.ps1",
        "tools/bootstrap_windows_runtime.py",
        "tools/build_release_manifest.py",
        "tools/verify_package.py",
        "tests/test_bootstrap_windows_runtime.py",
        "tests/test_release_tools.py",
        "docs/源码仓库与发布包.md",
        "docs/GitHub仓库网页搭建与协作分工指南.md",
    )
    for name in obsolete:
        assert not (ROOT / name).exists(), name


def test_entrypoints_use_internal_runtime_preparation() -> None:
    start = _text("start.bat")
    update = _text("update.bat")
    verify = _text("verify.bat")
    prepare = _text("scripts/windows/prepare-runtime.bat")

    assert r"scripts\windows\prepare-runtime.bat" in start
    assert r"scripts\windows\prepare-runtime.bat" in verify
    assert "call verify.bat" in update
    assert r"vendor\windows\runtime-manifest.json" in prepare
    assert r".runtime\python\python.exe" in prepare
    assert ".venv" not in prepare
    assert "pip install" not in prepare
    assert "bootstrap_windows_runtime" not in prepare


def test_historical_release_reports_are_archived() -> None:
    reports = (
        "V0.5.0_发布说明与验证报告.md",
        "V0.5.4_发布与验证说明.md",
        "V0.5.6_发布与验证说明.md",
    )
    for name in reports:
        assert not (ROOT / "docs" / name).exists()
        assert (ROOT / "docs" / "archive" / "releases" / name).is_file()

    index = _text("docs/README.md")
    assert "archive/releases/" in index
    assert "历史文档" in _text("docs/archive/README.md")


def test_docker_context_excludes_windows_runtime_and_helper_assets() -> None:
    dockerignore = _text(".dockerignore")
    for pattern in ("vendor", "scripts", "*.bat", "requirements/dev.lock"):
        assert pattern in dockerignore


def test_tracked_root_layout_stays_small_and_intentional() -> None:
    allowed_files = {
        ".dockerignore",
        ".env.default",
        ".gitattributes",
        ".gitignore",
        "CHANGELOG.md",
        "README.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
        "start.bat",
        "update.bat",
        "verify.bat",
    }
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked_root_files = {
        line for line in result.stdout.splitlines() if line and "/" not in line
    }
    assert tracked_root_files == allowed_files

    for obsolete in ("Dockerfile", "compose.yaml", "compose.build.yaml"):
        assert not (ROOT / obsolete).exists()
    assert (ROOT / "docker" / "Dockerfile").is_file()
    assert (ROOT / "docker" / "compose.yaml").is_file()


def test_plan_index_distinguishes_current_and_completed_work() -> None:
    plans = ROOT / "docs" / "plans"
    assert (plans / "V0.6.0_多用户搜索与会话方案.md").is_file()
    assert (plans / "V0.7.0_前端结构整理方案.md").is_file()
    assert (plans / "V0.7.0_前端结构整理方案_REVIEW.md").is_file()

    index = _text("docs/plans/README.md")
    assert "## 当前计划" in index
    assert "V0.7.0 前端结构整理方案" in index
    assert "已批准，待按 PR 1–8 顺序实施" in index
    assert "V0.7.0 方案 Review" in index
    assert "## 已完成计划" in index
    assert "V0.6.0 多用户、会话 Token、搜索与界面开发基线" in index
    assert "当前没有未完成的已批准计划" not in index
