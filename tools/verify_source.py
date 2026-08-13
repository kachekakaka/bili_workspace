from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_REGULAR_GIT_FILE = 100 * 1024 * 1024
LAUNCHER_EXE_REL = "dist/bili-workspace-launcher-0.7.0.exe"
LAUNCHER_RECORD_REL = "launcher/current-build.json"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400

REQUIRED = (
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    "CONTEXT.md",
    "docker/.env.default",
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "docker/Dockerfile",
    "docker/compose.yaml",
    "requirements/dev.lock",
    "requirements/runtime.lock",
    "app/__main__.py",
    "app/defaults/config.json.default",
    "app/defaults/runtime.env.default",
    "app/defaults/tags.json.default",
    "app/api.py",
    "app/config_files.py",
    "app/nas.py",
    "launcher/THIRD_PARTY_NOTICES.txt",
    "launcher/RELINKING.md",
    "launcher/bili-workspace-launcher.spec",
    "launcher/bili_workspace_launcher/__main__.py",
    "launcher/bili_workspace_launcher/backend_process.py",
    "launcher/bili_workspace_launcher/cli.py",
    "launcher/bili_workspace_launcher/commands.py",
    "launcher/bili_workspace_launcher/constants.py",
    "launcher/bili_workspace_launcher/docker_jobs.py",
    "launcher/bili_workspace_launcher/gui.py",
    "launcher/bili_workspace_launcher/paths.py",
    "launcher/bili_workspace_launcher/ports.py",
    "launcher/bili_workspace_launcher/resources.py",
    "launcher/bili_workspace_launcher/settings.py",
    "launcher/bili_workspace_launcher/version.py",
    "launcher/bili_workspace_launcher_entry.py",
    "launcher/requirements.txt",
    "launcher/requirements-dev.txt",
    "launcher/tests/conftest.py",
    "launcher/tests/test_app_integration.py",
    "launcher/tests/test_backend_process.py",
    "launcher/tests/test_build_tools.py",
    "launcher/tests/test_docker_jobs.py",
    "launcher/tests/test_gui_smoke.py",
    "launcher/tests/test_paths.py",
    "launcher/tests/test_resources.py",
    "launcher/tests/test_settings_and_ports.py",
    "web/index.html",
    "web/assets/app/main.mjs",
    "web/assets/app/core/version-check.mjs",
    "web/assets/styles/tokens.css",
    "web/assets/styles/base.css",
    "web/assets/styles/components.css",
    "web/assets/styles/pages.css",
    "tests/test_v05_auth.py",
    "tests/test_v05_export.py",
    "tests/test_config_files.py",
    "tests/test_repository_layout.py",
    "tests/test_playwright_runtime.py",
    "tests/test_t_project_isolation.py",
    "tools/check_markdown_links.py",
    "tools/playwright_runtime.py",
    "tools/t_project_isolation.py",
    "tools/build_launcher.py",
    "tools/prepare_launcher_resources.py",
    "scripts/README.md",
    "scripts/windows/new-test-run.ps1",
    "scripts/windows/build-launcher.bat",
    "scripts/dev/run-playwright-phase.sh",
    "scripts/dev/verify-source.sh",
    "docs/README.md",
    "docs/需求文档.md",
    "docs/设计文档.md",
    "docs/已知问题与待做需求.md",
    "docs/软件测试.md",
    "docs/字段契约.md",
    "docs/adr/0001-current-facts-by-type.md",
    "docs/adr/0002-source-push-does-not-publish.md",
    "docs/运维/README.md",
    "docs/运维/Docker镜像打包与离线交付.md",
    "docs/运维/发布与回滚流程.md",
    "docs/运维/源文件与恢复清单.md",
    "SoftwareTesting/README.md",
    "SoftwareTesting/PROTOCOL.md",
    "SoftwareTesting/SAFETY.md",
    "SoftwareTesting/doc_consistency/README.md",
    "SoftwareTesting/doc_consistency/test_doc_consistency.py",
    "SoftwareTesting/doc_consistency/test_doc_consistency_rules.py",
    "SoftwareTesting/project/README.md",
    "SoftwareTesting/launcher/README.md",
    "archive/docs/README.md",
    "archive/docs/workflows/README.md",
    "archive/docs/workflows/release-v070.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/launcher.yml",
    ".github/workflows/docker-image.yml",
)

ALLOWED_ROOT_SCRIPTS: set[str] = set()
ROOT_SCRIPT_SUFFIXES = {".bat", ".cmd", ".ps1", ".sh"}

ALLOWED_ROOT_FILES = {
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
OBSOLETE_RELATIVE = {
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
    "docs/源码仓库与发布包.md",
    "docs/GitHub仓库网页搭建与协作分工指南.md",
    "Dockerfile",
    "compose.yaml",
    "compose.build.yaml",
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
    "start.bat",
    "verify.bat",
}
FORBIDDEN_NAMES = {
    ".env",
    "BBDown.data",
    "bootstrap-token.txt",
    "RELEASE_MANIFEST.sha256",
}
FORBIDDEN_DIRS = {
    ".git",
    ".venv",
    ".runtime",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "bootstrap",
    "wheelhouse",
}
FORBIDDEN_RELATIVE = {
    "config/config.json",
    "config/runtime.env",
    "docker/.env",
}
SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:SESSDATA|bili_jct|DedeUserID)\s*=\s*[A-Za-z0-9%._~-]{8,}"
)
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\Users\\|/home/[^/]+/|/mnt/data/)")
ABSOLUTE_PATH_SCAN_EXEMPT = {
    "SoftwareTesting/doc_consistency/test_doc_consistency.py",
    "tools/verify_source.py",
}
TEXT_SUFFIXES = {
    ".py",
    ".ps1",
    ".js",
    ".mjs",
    ".css",
    ".html",
    ".md",
    ".txt",
    ".json",
    ".bat",
    ".ini",
    ".toml",
    ".yml",
    ".yaml",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".sh",
    ".lock",
    ".default",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        status = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(status, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _tracked_files() -> set[str] | None:
    if not (ROOT / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}


def _launcher_candidate(errors: list[str], tracked: set[str] | None) -> dict[str, str]:
    executable = ROOT / LAUNCHER_EXE_REL
    record_path = ROOT / LAUNCHER_RECORD_REL
    if tracked is not None:
        tracked_executables = sorted(
            rel for rel in tracked if rel.startswith("dist/") and rel.lower().endswith(".exe")
        )
        if tracked_executables not in ([], [LAUNCHER_EXE_REL]):
            errors.append("Git 只能跟踪一份规范 Windows 启动器 EXE")
    executable_exists = executable.exists() or executable.is_symlink()
    record_exists = record_path.exists() or record_path.is_symlink()
    if executable_exists != record_exists:
        errors.append("Windows 启动器 EXE 与 current-build.json 必须成对出现")
        return {}
    if not executable_exists:
        return {}
    if (
        not executable.is_file()
        or executable.is_symlink()
        or _is_reparse_point(executable)
        or not record_path.is_file()
        or record_path.is_symlink()
        or _is_reparse_point(record_path)
    ):
        errors.append("Windows 启动器候选或构建记录类型异常")
        return {}
    try:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Windows 启动器构建记录无效: {exc}")
        return {}
    size = raw.get("size_bytes") if isinstance(raw, dict) else None
    digest = raw.get("sha256") if isinstance(raw, dict) else None
    required = {
        "schema_version": 1,
        "version": "0.7.0",
        "platform": "windows/amd64",
        "executable": LAUNCHER_EXE_REL,
        "pyinstaller_version": "6.22.0",
        "pyside6_version": "6.11.1",
        "exe_self_check_ran": True,
    }
    expected_fields = set(required) | {
        "build_id",
        "sha256",
        "size_bytes",
        "resource_manifest_sha256",
        "python_version",
        "built_at_utc",
    }
    built_at = raw.get("built_at_utc") if isinstance(raw, dict) else None
    valid_built_at = False
    if isinstance(built_at, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", built_at
    ):
        try:
            datetime.fromisoformat(built_at.removesuffix("Z") + "+00:00")
            valid_built_at = True
        except ValueError:
            pass
    if (
        not isinstance(raw, dict)
        or set(raw) != expected_fields
        or any(raw.get(key) != value for key, value in required.items())
        or isinstance(raw.get("schema_version"), bool)
        or not isinstance(raw.get("build_id"), str)
        or re.fullmatch(r"[0-9a-f]{12}", raw["build_id"]) is None
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
        or size >= MAX_REGULAR_GIT_FILE
        or not isinstance(raw.get("resource_manifest_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", raw["resource_manifest_sha256"]) is None
        or not isinstance(raw.get("python_version"), str)
        or re.fullmatch(r"3\.11\.\d+", raw["python_version"]) is None
        or not valid_built_at
    ):
        errors.append("Windows 启动器构建记录字段或固定版本无效")
        return {}
    if executable.stat().st_size != size or sha256_file(executable) != digest:
        errors.append("Windows 启动器 EXE 大小或 SHA-256 与构建记录不一致")
        return {}
    try:
        with executable.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("缺少 MZ")
            stream.seek(0x3C)
            offset = int.from_bytes(stream.read(4), "little")
            stream.seek(offset)
            if stream.read(4) != b"PE\0\0" or int.from_bytes(stream.read(2), "little") != 0x8664:
                raise ValueError("不是 PE AMD64")
    except (OSError, ValueError) as exc:
        errors.append(f"Windows 启动器 PE 架构无效: {exc}")
        return {}
    return {LAUNCHER_EXE_REL: digest}


def _check_root_layout(errors: list[str]) -> None:
    root_scripts = {
        path.name
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix.lower() in ROOT_SCRIPT_SUFFIXES
    }
    unexpected = sorted(root_scripts - ALLOWED_ROOT_SCRIPTS)
    missing = sorted(ALLOWED_ROOT_SCRIPTS - root_scripts)
    if unexpected:
        errors.append("根目录包含非用户入口脚本: " + ", ".join(unexpected))
    if missing:
        errors.append("根目录缺少 Windows 用户入口: " + ", ".join(missing))

    root_files = {path.name for path in ROOT.iterdir() if path.is_file()}
    root_files.discard(".env")
    extra_files = sorted(root_files - ALLOWED_ROOT_FILES)
    missing_files = sorted(ALLOWED_ROOT_FILES - root_files)
    if extra_files:
        errors.append("根目录包含未归类文件: " + ", ".join(extra_files))
    if missing_files:
        errors.append("根目录缺少必要文件: " + ", ".join(missing_files))

    obsolete = sorted(rel for rel in OBSOLETE_RELATIVE if (ROOT / rel).exists())
    if obsolete:
        errors.append("仓库重新出现已淘汰文件: " + ", ".join(obsolete))


def main() -> int:
    errors: list[str] = []
    if sys.version_info[:2] != (3, 11):
        errors.append(
            "源码验证必须使用全仓统一的 Python 3.11，"
            f"当前为 {sys.version_info.major}.{sys.version_info.minor}"
        )
    tracked = _tracked_files()
    launcher_candidates = _launcher_candidate(errors, tracked)
    allowed_large_files = set(launcher_candidates)

    for rel in REQUIRED:
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():
            errors.append(f"缺少源码文件或类型异常: {rel}")

    _check_root_layout(errors)

    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT).as_posix()
        if tracked is not None and path.is_file() and rel not in tracked:
            continue
        if path.is_symlink():
            errors.append(f"源码仓库不得包含符号链接: {rel}")
            continue
        if path.is_dir() and path.name in FORBIDDEN_DIRS:
            continue
        if not path.is_file() or any(part in FORBIDDEN_DIRS for part in path.parts):
            continue
        if path.name in FORBIDDEN_NAMES or rel in FORBIDDEN_RELATIVE:
            errors.append(f"源码仓库包含禁止文件: {rel}")
            continue
        if path.stat().st_size > 50 * 1024 * 1024 and rel not in allowed_large_files:
            errors.append(f"源码仓库包含未登记的超过 50 MiB 文件: {rel}")
            continue
        suffix = path.suffix.lower() or path.name.lower()
        if path.stat().st_size > 2 * 1024 * 1024 or suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if SECRET_RE.search(text):
            errors.append(f"疑似包含真实 Bilibili 登录凭据: {rel}")
        if rel not in ABSOLUTE_PATH_SCAN_EXEMPT and ABSOLUTE_PATH_RE.search(text):
            errors.append(f"疑似包含构建机绝对路径: {rel}")

    if errors:
        print("[失败] 源码仓库校验发现问题：")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("[通过] 源码结构、根目录边界、文件大小和敏感信息边界正常。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
