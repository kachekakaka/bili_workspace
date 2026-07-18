from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_TOOL_GROUPS = {
    "BBDown": {"BBDown.exe", "BBDown", "bbdown"},
    "FFmpeg": {
        "ffmpeg/bin/ffmpeg.exe",
        "ffmpeg/bin/ffmpeg",
        "ffmpeg.exe",
        "ffmpeg",
    },
}


@dataclass
class IntegrityStatus:
    checked: bool
    ok: bool
    files: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_tool_manifest(bbdown_dir: Path) -> IntegrityStatus:
    manifest = Path(bbdown_dir) / "checksums.sha256"
    if not manifest.is_file() or manifest.is_symlink():
        return IntegrityStatus(checked=False, ok=True)

    expected: dict[str, str] = {}
    errors: list[str] = []
    for line in manifest.read_text(encoding="utf-8", errors="strict").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 or len(parts[0]) != 64:
            errors.append(f"校验清单格式错误: {line[:120]}")
            continue
        rel = " ".join(parts[1:]).lstrip("*")
        expected[rel.replace("\\", "/")] = parts[0].lower()

    manifest_names = set(expected)
    for label, alternatives in REQUIRED_TOOL_GROUPS.items():
        if not (manifest_names & alternatives):
            choices = " / ".join(sorted(alternatives))
            errors.append(f"校验清单缺少必需条目: {label}（{choices}）")

    actual: dict[str, str] = {}
    for rel, wanted in expected.items():
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            errors.append(f"校验清单路径越界: {rel}")
            continue
        target = Path(bbdown_dir).joinpath(*rel_path.parts)
        if not target.is_file() or target.is_symlink():
            errors.append(f"工具文件缺失或不是普通文件: {rel}")
            continue
        got = sha256_file(target)
        actual[rel] = got
        if got != wanted:
            errors.append(f"工具哈希不匹配: {rel}")
    return IntegrityStatus(checked=True, ok=not errors, files=actual, errors=errors)
