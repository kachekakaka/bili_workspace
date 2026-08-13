from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_root_contains_no_legacy_windows_entrypoints() -> None:
    script_suffixes = {".bat", ".cmd", ".ps1", ".sh"}
    scripts = {
        path.name
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix.lower() in script_suffixes
    }
    assert scripts == set()


def test_helpers_and_dependency_locks_are_grouped() -> None:
    expected = (
        "requirements/dev.lock",
        "requirements/runtime.lock",
        "scripts/README.md",
        "scripts/windows/new-test-run.ps1",
        "scripts/windows/build-launcher.bat",
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
        "update.bat",
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
        ".env.default",
        ".github/workflows/build-integrated-runtime.yml",
        "BBDown_portable",
        "vendor/windows",
        "config/config.json.default",
        "config/runtime.env.default",
        "config/tags.json.default",
        "config/README.md",
        "downloads/.gitkeep",
        "userdata/.gitkeep",
        "userdata/README.md",
        "scripts/windows/bootstrap-portable.ps1",
        "scripts/windows/bootstrap-runtime.bat",
        "scripts/windows/prepare-runtime.bat",
        "scripts/windows/configure-network.bat",
        "scripts/windows/bilibili-login.bat",
        "tools/build_integrated_runtime.py",
        "tools/configure_network.py",
        "tools/server_instance.py",
        "tools/start_info.py",
        "tests/test_configure_network.py",
        "tests/test_integrated_runtime.py",
        "tests/test_server_instance.py",
        "docs/源码仓库与发布包.md",
        "docs/GitHub仓库网页搭建与协作分工指南.md",
    )
    for name in obsolete:
        assert not (ROOT / name).exists(), name


def test_launcher_build_and_test_helpers_are_the_only_windows_scripts() -> None:
    build = _text("scripts/windows/build-launcher.bat")

    assert r".venv\Scripts\python.exe" in build
    assert "-m tools.build_launcher" in build
    assert "--run-exe-self-check" in build
    assert ".bili-workspace-test-run.json" in _text(
        "scripts/windows/new-test-run.ps1"
    )


def test_historical_release_reports_are_archived() -> None:
    reports = (
        "V0.5.0_发布说明与验证报告.md",
        "V0.5.4_发布与验证说明.md",
        "V0.5.6_发布与验证说明.md",
    )
    for name in reports:
        assert not (ROOT / "docs" / name).exists()
        assert (ROOT / "archive" / "docs" / "releases" / name).is_file()

    index = _text("docs/README.md")
    assert "../archive/docs/README.md" in index
    assert "文档归档" in _text("archive/docs/README.md")


def test_docker_context_excludes_windows_runtime_and_helper_assets() -> None:
    dockerignore = _text(".dockerignore")
    for pattern in ("scripts", "*.bat", "requirements/dev.lock"):
        assert pattern in dockerignore


def test_tracked_root_layout_stays_small_and_intentional() -> None:
    allowed_files = {
        ".dockerignore",
        ".gitattributes",
        ".gitignore",
        "AGENTS.md",
        "CHANGELOG.md",
        "CONTEXT.md",
        "README.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
    }
    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--deleted",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked_root_files = {
        line
        for line in result.stdout.splitlines()
        if line and "/" not in line and (ROOT / line).exists()
    }
    assert tracked_root_files == allowed_files

    for obsolete in ("Dockerfile", "compose.yaml", "compose.build.yaml"):
        assert not (ROOT / obsolete).exists()
    assert (ROOT / "docker" / "Dockerfile").is_file()
    assert (ROOT / "docker" / "compose.yaml").is_file()


def test_completed_plan_index_is_archived() -> None:
    plans = ROOT / "archive" / "docs" / "plans"
    assert (plans / "V0.6.0_多用户搜索与会话方案.md").is_file()
    assert (plans / "V0.7.0_前端结构整理方案.md").is_file()
    assert (plans / "V0.7.0_前端结构整理方案_REVIEW.md").is_file()
    assert (ROOT / "archive" / "docs" / "releases" / "V0.7功能与验收.md").is_file()
    assert not (ROOT / "docs" / "V0.7功能与验收.md").exists()
    assert not (ROOT / ".github" / "workflows" / "release-v070.yml").exists()
    assert (ROOT / "archive" / "docs" / "workflows" / "release-v070.yml").is_file()

    index = _text("archive/docs/plans/README.md")
    assert "## 当前计划" in index
    assert "当前没有未完成的已批准计划" in index
    assert "## 已完成计划" in index
    assert "V0.7.0 前端结构整理方案" in index
    assert "PR 1–8" in index
    assert "V0.6.0 多用户、会话 Token、搜索与界面开发基线" in index
