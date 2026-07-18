from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_MANIFEST = ROOT / "vendor" / "windows" / "runtime-manifest.json"
MAX_REGULAR_GIT_FILE = 100 * 1024 * 1024

REQUIRED = (
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".env.default",
    "config/config.json.default",
    "config/runtime.env.default",
    "config/README.md",
    "docker/.env.default",
    "README.md",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "Dockerfile",
    "compose.yaml",
    "compose.build.yaml",
    "requirements.lock",
    "requirements-runtime.lock",
    "app/__main__.py",
    "app/api.py",
    "app/config_files.py",
    "app/nas.py",
    "web/index.html",
    "web/assets/app.js",
    "tests/test_v05_auth.py",
    "tests/test_v05_export.py",
    "tests/test_config_files.py",
    "tests/test_configure_network.py",
    "tests/test_integrated_runtime.py",
    "tools/bootstrap_windows_runtime.py",
    "tools/bootstrap_portable.ps1",
    "tools/build_integrated_runtime.py",
    "docs/源码仓库与发布包.md",
    "docs/需求落实清单.md",
    "docs/产品需求与架构基线.md",
    "docs/V0.5.6_发布与验证说明.md",
    "docs/发布与回滚流程.md",
    "docs/源文件与恢复清单.md",
    ".github/workflows/ci.yml",
    ".github/workflows/build-integrated-runtime.yml",
    ".github/workflows/docker-image.yml",
    "bootstrap.bat",
    "configure_network.bat",
    "run.bat",
    "update.bat",
    "verify-source.sh",
    "verify-source.bat",
)

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
    "BBDown_portable/BBDown.exe",
    "BBDown_portable/ffmpeg/bin/ffmpeg.exe",
}
SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:SESSDATA|bili_jct|DedeUserID)\s*=\s*[A-Za-z0-9%._~-]{8,}"
)
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\Users\\|/home/[^/]+/|/mnt/data/)")
TEXT_SUFFIXES = {
    ".py", ".ps1", ".js", ".css", ".html", ".md", ".txt", ".json", ".bat",
    ".ini", ".toml", ".yml", ".yaml", ".gitignore", ".gitattributes",
    ".dockerignore", ".sh", ".lock", ".default",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _runtime_packs(errors: list[str]) -> dict[str, str]:
    if not RUNTIME_MANIFEST.is_file():
        return {}
    try:
        data = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("platform") != "windows-x64":
            raise ValueError("schema/platform 不受支持")
        packs = data["packs"]
        result: dict[str, str] = {}
        for name in ("python", "media"):
            row = packs[name]
            rel = str(row["path"]).replace("\\", "/")
            expected = str(row["sha256"]).lower()
            if not rel.startswith("vendor/windows/") or len(expected) != 64:
                raise ValueError(f"{name} 运行包清单无效")
            path = ROOT / rel
            if not path.is_file() or path.is_symlink():
                errors.append(f"缺少集成运行包: {rel}")
                continue
            if path.stat().st_size >= MAX_REGULAR_GIT_FILE:
                errors.append(f"集成运行包超过普通 Git 100 MiB 限制: {rel}")
                continue
            actual = sha256_file(path)
            if actual != expected:
                errors.append(f"集成运行包 SHA-256 不匹配: {rel}")
            result[rel] = expected
        return result
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"集成运行时清单无效: {exc}")
        return {}


def main() -> int:
    errors: list[str] = []
    tracked = _tracked_files()
    runtime_packs = _runtime_packs(errors)

    for rel in REQUIRED:
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():
            errors.append(f"缺少源码文件或类型异常: {rel}")

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
        if path.stat().st_size > 50 * 1024 * 1024 and rel not in runtime_packs:
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
        if rel != "tools/verify_source.py" and ABSOLUTE_PATH_RE.search(text):
            errors.append(f"疑似包含构建机绝对路径: {rel}")

    if errors:
        print("[失败] 源码仓库校验发现问题：")
        for item in errors:
            print(f"  - {item}")
        return 1

    runtime_text = "，集成运行包哈希正常" if runtime_packs else "（运行包等待 GitHub 构建工作流生成）"
    print(f"[通过] 源码结构、默认配置、文件大小和敏感信息边界正常{runtime_text}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
