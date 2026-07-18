from __future__ import annotations

import json
import os
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.io_utils import atomic_write_json, atomic_write_text

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _assert_regular_or_missing(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} 不允许是符号链接: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"{label} 必须是普通文件: {path}")


def merge_missing(default: Any, current: Any) -> tuple[Any, bool]:
    """Recursively add keys missing from *current* without replacing user values.

    Dicts are merged recursively. Existing scalars, lists and type choices remain
    authoritative, including values such as ``0``, ``false`` and an empty string.
    """
    if not isinstance(default, dict) or not isinstance(current, dict):
        return deepcopy(current), False

    merged = deepcopy(current)
    changed = False
    for key, default_value in default.items():
        if key not in current:
            merged[key] = deepcopy(default_value)
            changed = True
            continue
        nested, nested_changed = merge_missing(default_value, current[key])
        if nested_changed:
            merged[key] = nested
            changed = True
    return merged, changed


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} JSON 无效: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} 顶层必须是 JSON 对象: {path}")
    return value


def ensure_json_from_default(default_path: Path, actual_path: Path) -> tuple[dict[str, Any], bool]:
    """Create/upgrade a JSON config from its tracked ``.default`` template."""
    default_path = Path(default_path)
    actual_path = Path(actual_path)
    _assert_regular_or_missing(default_path, label="默认配置")
    _assert_regular_or_missing(actual_path, label="实际配置")
    if not default_path.is_file():
        raise ValueError(f"缺少默认配置模板: {default_path}")

    default_data = _read_json_object(default_path, label="默认配置")
    if not actual_path.exists():
        atomic_write_json(actual_path, default_data, backup=False)
        return deepcopy(default_data), True

    current_data = _read_json_object(actual_path, label="实际配置")
    merged, changed = merge_missing(default_data, current_data)
    if changed:
        atomic_write_json(actual_path, merged, backup=True)
    return merged, changed


def migrate_legacy_json(legacy_path: Path, actual_path: Path) -> bool:
    """Copy an older mutable JSON config to its new location once.

    The legacy file is intentionally retained as a rollback copy. Existing
    targets always win, and symbolic links are rejected on both sides.
    """
    legacy_path = Path(legacy_path)
    actual_path = Path(actual_path)
    _assert_regular_or_missing(legacy_path, label="旧配置")
    _assert_regular_or_missing(actual_path, label="实际配置")
    if actual_path.exists() or not legacy_path.is_file():
        return False
    actual_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_path, actual_path)
    return True


def _dotenv_assignments(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if _ENV_KEY_RE.fullmatch(key):
            values[key] = value.strip()
    return values


def _decode_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
        if raw.strip().startswith('"'):
            value = bytes(value, "utf-8").decode("unicode_escape")
    return value


def ensure_env_from_default(default_path: Path, actual_path: Path) -> bool:
    """Create a dotenv file or append only keys introduced by a newer template."""
    default_path = Path(default_path)
    actual_path = Path(actual_path)
    _assert_regular_or_missing(default_path, label="默认环境配置")
    _assert_regular_or_missing(actual_path, label="实际环境配置")
    if not default_path.is_file():
        raise ValueError(f"缺少默认环境配置模板: {default_path}")

    default_text = default_path.read_text(encoding="utf-8")
    if not actual_path.exists():
        actual_path.parent.mkdir(parents=True, exist_ok=True)
        # Copy first to keep comments and usage guidance exactly as maintained.
        shutil.copyfile(default_path, actual_path)
        return True

    actual_text = actual_path.read_text(encoding="utf-8")
    present = _dotenv_assignments(actual_text)
    missing_lines: list[str] = []
    for line in default_text.splitlines():
        stripped = line.strip()
        candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            continue
        key = candidate.split("=", 1)[0].strip()
        if _ENV_KEY_RE.fullmatch(key) and key not in present:
            missing_lines.append(line)
            present[key] = ""

    if not missing_lines:
        return False
    suffix = "" if not actual_text or actual_text.endswith("\n") else "\n"
    updated = (
        actual_text
        + suffix
        + "\n# Added automatically from the newer .default template.\n"
        + "\n".join(missing_lines)
        + "\n"
    )
    atomic_write_text(actual_path, updated, backup=True)
    return True


def load_env_file(path: Path, *, override: bool = False) -> dict[str, str]:
    """Load the small dotenv subset used by this project.

    Existing process environment values win unless ``override`` is explicitly
    requested, which keeps Docker/Compose and service-manager settings authoritative.
    """
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return {}
    parsed = {
        key: _decode_env_value(value)
        for key, value in _dotenv_assignments(path.read_text(encoding="utf-8")).items()
    }
    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return parsed
