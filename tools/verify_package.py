from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path, PurePosixPath

# Release verification must not create __pycache__ inside the package it scans.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrity import sha256_file, verify_tool_manifest  # noqa: E402

REQUIRED = (
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "Dockerfile",
    "compose.yaml",
    ".env.default",
    "config/config.json.default",
    "config/runtime.env.default",
    "config/tags.json.default",
    "config/README.md",
    "docker/.env.default",
    ".dockerignore",
    "requirements.txt",
    "requirements.lock",
    "requirements-runtime.lock",
    "start.bat",
    "setup.bat",
    "login.bat",
    "verify.bat",
    "tools/bootstrap_windows_runtime.py",
    "RELEASE_MANIFEST.sha256",
    "app/__main__.py",
    "app/main.py",
    "app/api.py",
    "app/enhancement_api.py",
    "app/tag_store.py",
    "app/task_extensions.py",
    "app/userdata.py",
    "app/nas.py",
    "app/media_stream.py",
    "app/cover_cache.py",
    "app/qr_login.py",
    "app/runtime.py",
    "app/state.py",
    "app/queue.py",
    "app/index_store.py",
    "app/config.py",
    "app/progress.py",
    "app/task_logs.py",
    "app/platform_actions.py",
    "app/grouping.py",
    "app/quality.py",
    "app/metadata.py",
    "web/index.html",
    "web/assets/app.js",
    "web/assets/app.css",
    "web/assets/enhancements.css",
    "web/assets/qrcode.min.js",
    "docker/entrypoint.sh",
    "docker/healthcheck.py",
    "docker/verify-config.sh",
    "docker/build-and-start.sh",
    "docs/QNAP_Docker部署指南.md",
    "docs/域名与反向代理配置.md",
    "docs/备份恢复与V0.4迁移.md",
    "docs/V0.5功能与验收.md",
    "docs/V0.5.0_发布说明与验证报告.md",
    "docs/V0.5.4_发布与验证说明.md",
    "docs/产品需求与架构基线.md",
    "docs/发布与回滚流程.md",
    "docs/源文件与恢复清单.md",
    "LICENSES/QRCodeJS.LICENSE.txt",
    "BBDown_portable/BBDown.exe",
    "BBDown_portable/BBDown.LICENSE.txt",
    "BBDown_portable/ffmpeg/bin/ffmpeg.exe",
    "BBDown_portable/ffmpeg/LICENSE.txt",
    "BBDown_portable/checksums.sha256",
)

STRICT_FORBIDDEN_NAMES = {
    "BBDown.data",
    "ffplay.exe",
    "ffprobe.exe",
}
STRICT_FORBIDDEN_DIRS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".server",
    ".v05_state",
    ".cache",
    ".tmp",
    ".bili_logs",
    ".bili_tmp",
    ".bili_backup",
}
MUTABLE_PREFIXES = (
    ".venv/",
    ".server/",
    ".v05_state/",
    ".cache/",
    ".tmp/",
    "downloads/",
    "userdata/",
)
MUTABLE_EXACT = {
    "BBDown_portable/BBDown.data",
    "config.json",
    "config.json.bak",
    "config/config.json",
    "config/config.json.bak",
    "config/runtime.env",
    "config/runtime.env.bak",
    "config/tags.json",
    "config/tags.json.bak",
    "docker/.env",
    "docker/.env.bak",
}
SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:SESSDATA|bili_jct|DedeUserID)\s*=\s*[A-Za-z0-9%._~-]{8,}"
)
TEXT_SUFFIXES = {
    ".py", ".js", ".css", ".html", ".md", ".txt", ".json", ".bat",
    ".ini", ".toml", ".yml", ".yaml", ".gitignore", ".dockerignore",
    ".sh", ".lock", ".example", ".default", "dockerfile",
}


def _safe_manifest_path(raw: str) -> PurePosixPath:
    rel = PurePosixPath(raw)
    if rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") for p in rel.parts):
        raise ValueError(f"清单路径不安全: {raw}")
    return rel


def _is_mutable(rel: str) -> bool:
    return rel in MUTABLE_EXACT or any(
        rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in MUTABLE_PREFIXES
    )


def _is_runtime_generated(rel: str) -> bool:
    pure = PurePosixPath(rel)
    return (
        any(part in STRICT_FORBIDDEN_DIRS for part in pure.parts)
        or pure.suffix.lower() in {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3"}
        or pure.name.endswith((".db-wal", ".db-shm"))
        or pure.name.endswith((".tmp", ".log"))
    )


def _immutable_files(root: Path) -> set[str]:
    files: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if (
            rel == "RELEASE_MANIFEST.sha256"
            or _is_mutable(rel)
            or _is_runtime_generated(rel)
        ):
            continue
        files.add(rel)
    return files


def verify_release_manifest(root: Path) -> list[str]:
    path = root / "RELEASE_MANIFEST.sha256"
    if not path.is_file():
        return ["缺少 RELEASE_MANIFEST.sha256"]
    errors: list[str] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            errors.append(f"发布清单第 {lineno} 行格式错误")
            continue
        wanted, raw = parts[0].lower(), parts[1].lstrip("*")
        try:
            rel = _safe_manifest_path(raw)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        rel_text = rel.as_posix()
        if rel_text in seen:
            errors.append(f"发布清单重复条目: {rel_text}")
            continue
        seen.add(rel_text)
        target = root.joinpath(*rel.parts)
        if not target.is_file() or target.is_symlink():
            errors.append(f"发布文件缺失或类型异常: {rel_text}")
            continue
        got = sha256_file(target)
        if got != wanted:
            errors.append(f"发布文件哈希不匹配: {rel_text}")

    expected_files = _immutable_files(root)
    for rel in sorted(expected_files - seen):
        errors.append(f"发布清单遗漏文件: {rel}")
    for rel in sorted(seen - expected_files):
        errors.append(f"发布清单包含不应固定的文件: {rel}")
    return errors


def strict_release_scan(root: Path) -> list[str]:
    errors: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"发布包不得包含符号链接: {rel}")
            continue
        if path.is_dir() and path.name in STRICT_FORBIDDEN_DIRS:
            errors.append(f"发布包包含禁止目录: {rel}")
        if path.is_file() and path.name in STRICT_FORBIDDEN_NAMES:
            errors.append(f"发布包包含禁止文件: {rel}")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
            errors.append(f"发布包包含 Python 缓存: {rel}")
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        suffix = path.suffix.lower() or path.name.lower()
        if suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if SECRET_RE.search(text):
            errors.append(f"疑似包含登录凭据: {rel}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 bili_workspace 发布包")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--release", action="store_true", help="启用发布前严格清理检查")
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []

    for rel in REQUIRED:
        target = root / rel
        if not target.is_file() or target.is_symlink():
            errors.append(f"必需文件缺失或类型异常: {rel}")

    tool_status = verify_tool_manifest(root / "BBDown_portable")
    if not tool_status.checked:
        errors.append("工具校验清单未启用")
    elif not tool_status.ok:
        errors.extend(tool_status.errors)

    errors.extend(verify_release_manifest(root))
    if args.release:
        errors.extend(strict_release_scan(root))

    if errors:
        print("[失败] 包校验发现问题：")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("[通过] 目录结构、发布清单和 BBDown/FFmpeg 哈希均正常。")
    if args.release:
        print("[通过] 未发现 Cookie、旧虚拟环境、缓存、ffplay 或 ffprobe。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
