from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config_files import (
    ensure_env_from_default,
    ensure_json_from_default,
    merge_missing,
    migrate_legacy_json,
)


def test_recursive_default_merge_preserves_existing_and_extra_values():
    default = {"server": {"host": "127.0.0.1", "port": 3398}, "new": True}
    current = {"server": {"port": 3389}, "custom": "keep"}
    merged, changed = merge_missing(default, current)
    assert changed is True
    assert merged == {
        "server": {"host": "127.0.0.1", "port": 3389},
        "new": True,
        "custom": "keep",
    }


def test_json_default_is_copied_then_only_missing_fields_are_added(tmp_path: Path):
    default = tmp_path / "config.json.default"
    actual = tmp_path / "config.json"
    default.write_text(json.dumps({"port": 3398, "nested": {"a": 1}}), encoding="utf-8")

    data, created = ensure_json_from_default(default, actual)
    assert created is True
    assert data["port"] == 3398

    actual.write_text(json.dumps({"port": 3389, "nested": {}, "extra": 7}), encoding="utf-8")
    data, changed = ensure_json_from_default(default, actual)
    assert changed is True
    assert data == {"port": 3389, "nested": {"a": 1}, "extra": 7}
    assert actual.with_suffix(".json.bak").is_file()


def test_invalid_existing_json_is_not_overwritten(tmp_path: Path):
    default = tmp_path / "config.json.default"
    actual = tmp_path / "config.json"
    default.write_text('{"port": 3398}', encoding="utf-8")
    actual.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="实际配置 JSON 无效"):
        ensure_json_from_default(default, actual)
    assert actual.read_text(encoding="utf-8") == "{broken"


def test_env_default_appends_new_keys_without_overwriting(tmp_path: Path):
    default = tmp_path / ".env.default"
    actual = tmp_path / ".env"
    default.write_text("A=default\nB=2\n", encoding="utf-8")
    actual.write_text("A=user\nCUSTOM=yes\n", encoding="utf-8")
    assert ensure_env_from_default(default, actual) is True
    text = actual.read_text(encoding="utf-8")
    assert "A=user" in text
    assert "A=default" not in text
    assert "B=2" in text
    assert "CUSTOM=yes" in text


def test_config_target_symlink_is_rejected(tmp_path: Path):
    default = tmp_path / "config.json.default"
    target = tmp_path / "target.json"
    actual = tmp_path / "config.json"
    default.write_text("{}", encoding="utf-8")
    target.write_text("{}", encoding="utf-8")
    try:
        actual.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="符号链接"):
        ensure_json_from_default(default, actual)


def test_legacy_json_is_copied_once_and_existing_target_wins(tmp_path: Path):
    legacy = tmp_path / "config.json"
    actual = tmp_path / "config" / "config.json"
    legacy.write_text('{"port": 3389}', encoding="utf-8")
    assert migrate_legacy_json(legacy, actual) is True
    assert json.loads(actual.read_text(encoding="utf-8"))["port"] == 3389
    actual.write_text('{"port": 3398}', encoding="utf-8")
    assert migrate_legacy_json(legacy, actual) is False
    assert json.loads(actual.read_text(encoding="utf-8"))["port"] == 3398


def test_tracked_default_names_map_to_untracked_runtime_names():
    root = Path(__file__).resolve().parent.parent
    pairs = (
        (root / ".env.default", root / ".env"),
        (root / "config" / "config.json.default", root / "config" / "config.json"),
        (root / "config" / "runtime.env.default", root / "config" / "runtime.env"),
        (root / "docker" / ".env.default", root / "docker" / ".env"),
    )
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    for default, actual in pairs:
        assert default.is_file()
        assert actual.relative_to(root).as_posix() in ignored
