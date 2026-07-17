from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = PROJECT_ROOT / "defaults"


def runtime_config_dir() -> Path:
    configured = os.environ.get("BILI_CONFIG_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (PROJECT_ROOT / "config").resolve()


def deep_fill_missing(current: Any, defaults: Any) -> tuple[Any, bool]:
    if not isinstance(defaults, Mapping) or not isinstance(current, Mapping):
        return current, False
    merged = copy.deepcopy(dict(current))
    changed = False
    for key, default_value in defaults.items():
        if key not in merged:
            merged[key] = copy.deepcopy(default_value)
            changed = True
            continue
        value, child_changed = deep_fill_missing(merged[key], default_value)
        if child_changed:
            merged[key] = value
            changed = True
    return merged, changed


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _merge_json_template(template: Path, target: Path) -> bool:
    defaults = json.loads(template.read_text(encoding="utf-8-sig"))
    if not target.exists():
        _atomic_write_text(target, json.dumps(defaults, ensure_ascii=False, indent=2) + "\n")
        return True
    try:
        current = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"配置文件损坏，未覆盖原文件: {target}: {exc}") from exc
    merged, changed = deep_fill_missing(current, defaults)
    if changed:
        _atomic_write_text(target, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    return changed


def _parse_env(text: str) -> tuple[list[str], dict[str, str]]:
    order: list[str] = []
    values: dict[str, str] = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in values:
            order.append(key)
            values[key] = value
    return order, values


def _merge_env_template(template: Path, target: Path) -> bool:
    template_text = template.read_text(encoding="utf-8-sig")
    if not target.exists():
        _atomic_write_text(target, template_text.rstrip() + "\n")
        return True
    current_text = target.read_text(encoding="utf-8-sig")
    _, current = _parse_env(current_text)
    order, defaults = _parse_env(template_text)
    missing = [key for key in order if key not in current]
    if not missing:
        return False
    addition = ["", "# Added automatically from the updated .default template"]
    addition.extend(f"{key}={defaults[key]}" for key in missing)
    _atomic_write_text(target, current_text.rstrip() + "\n" + "\n".join(addition) + "\n")
    return True


def ensure_runtime_configs(template_root: Path | None = None, target_root: Path | None = None) -> list[Path]:
    source_root = (template_root or TEMPLATE_ROOT).resolve()
    destination_root = (target_root or runtime_config_dir()).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    changed: list[Path] = []
    if not source_root.exists():
        return changed
    for template in sorted(source_root.rglob("*.default")):
        relative = template.relative_to(source_root)
        target_relative = Path(str(relative)[: -len(".default")])
        target = destination_root / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        suffix = target.suffix.lower()
        if suffix == ".json":
            did_change = _merge_json_template(template, target)
        elif suffix in {".env", ".ini", ".conf"} or target.name == ".env":
            did_change = _merge_env_template(template, target)
        elif not target.exists():
            shutil.copy2(template, target)
            did_change = True
        else:
            did_change = False
        if did_change:
            changed.append(target)
    return changed


def load_json_config(name: str, *, target_root: Path | None = None) -> dict[str, Any]:
    ensure_runtime_configs(target_root=target_root)
    path = (target_root or runtime_config_dir()) / name
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"配置顶层必须是对象: {path}")
    return value
