from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_workspace_launcher.paths import (
    AppPaths,
    DataRootError,
    DataRootLock,
    DataRootLockError,
    DataRootManager,
)


def _templates(root: Path) -> Path:
    root.mkdir()
    (root / "config.json.default").write_text('{"config_schema_version": 2}\n', encoding="utf-8")
    (root / "runtime.env.default").write_text("BILI_APP_MODE=local\n", encoding="utf-8")
    (root / "tags.json.default").write_text(
        '{"palette_version": 2, "tags": []}\n', encoding="utf-8"
    )
    return root


def test_data_root_is_external_and_fixed_layout_is_created(tmp_path: Path) -> None:
    control = tmp_path / "control"
    paths = AppPaths(control)
    manager = DataRootManager(paths, _templates(tmp_path / "templates"))
    layout = manager.prepare(tmp_path / "chosen-data")

    assert layout.root == (tmp_path / "chosen-data").resolve()
    assert layout.config_file.is_file()
    assert layout.runtime_env_file.is_file()
    assert layout.tags_file.is_file()
    assert layout.bbdown_data_dir.is_dir()
    assert layout.cache_dir.is_dir()
    assert layout.temp_dir.is_dir()
    assert layout.logs_dir.is_dir()
    assert layout.task_logs_dir.is_dir()
    assert layout.home_dir.is_dir()
    assert layout.backups_dir.is_dir()
    assert layout.indexes_dir.is_dir()
    assert layout.dotnet_bundle_dir.is_dir()
    marker = json.loads(layout.marker_file.read_text(encoding="utf-8"))
    assert marker["schema_version"] == 1
    assert marker["product"] == "bili_workspace"


def test_locked_prepare_requires_ownership_before_writing_data_layout(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    manager = DataRootManager(paths, _templates(tmp_path / "templates"))
    preview = manager.resolve_layout(tmp_path / "chosen-data")
    lock = DataRootLock(preview)

    with pytest.raises(DataRootLockError, match="未持有"):
        manager.prepare_locked(preview.root, lock)
    assert not preview.config_dir.exists()
    assert not preview.marker_file.exists()

    lock.acquire()
    try:
        layout = manager.prepare_locked(preview.root, lock)
        assert layout.config_file.is_file()
        assert layout.marker_file.is_file()
    finally:
        lock.release()


def test_data_root_rejects_control_root_and_git_worktree(tmp_path: Path) -> None:
    control = tmp_path / "control"
    paths = AppPaths(control)
    manager = DataRootManager(paths, _templates(tmp_path / "templates"))
    with pytest.raises(DataRootError, match="控制根"):
        manager.prepare(control / "data")
    assert not (control / "data").exists()

    worktree = tmp_path / "repo"
    (worktree / ".git").mkdir(parents=True)
    with pytest.raises(DataRootError, match="Git 工作树"):
        manager.prepare(worktree / "data")
    assert not (worktree / "data").exists()


def test_data_root_rejects_git_reparse_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = tmp_path / "control"
    paths = AppPaths(control)
    manager = DataRootManager(paths, _templates(tmp_path / "templates"))
    worktree = tmp_path / "repo"
    worktree.mkdir()
    marker = worktree / ".git"
    monkeypatch.setattr(
        "bili_workspace_launcher.paths._is_reparse_point",
        lambda path: Path(path) == marker,
    )

    with pytest.raises(DataRootError, match="Git 工作树"):
        manager.resolve_layout(worktree / "data")
    assert not (worktree / "data").exists()


def test_data_root_does_not_overwrite_broken_marker_or_config(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    templates = _templates(tmp_path / "templates")
    root = tmp_path / "data"
    root.mkdir()
    (root / ".bili-workspace-data-root.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(DataRootError, match="标记损坏"):
        DataRootManager(paths, templates).prepare(root)
    assert (root / ".bili-workspace-data-root.json").read_text(encoding="utf-8") == "{broken"
    assert not (root / "config").exists()
    assert not (root / "userdata").exists()
    assert not (root / "downloads").exists()


def test_data_root_rejects_non_utf8_marker_without_writing_layout(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    templates = _templates(tmp_path / "templates")
    root = tmp_path / "data"
    root.mkdir()
    marker = root / ".bili-workspace-data-root.json"
    marker.write_bytes(b"\xff")

    with pytest.raises(DataRootError, match="标记损坏"):
        DataRootManager(paths, templates).prepare(root)

    assert marker.read_bytes() == b"\xff"
    assert not (root / "config").exists()


def test_data_root_rejects_boolean_marker_schema(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    templates = _templates(tmp_path / "templates")
    root = tmp_path / "data"
    root.mkdir()
    (root / ".bili-workspace-data-root.json").write_text(
        '{"schema_version": true, "product": "bili_workspace"}\n', encoding="utf-8"
    )
    with pytest.raises(DataRootError, match="schema"):
        DataRootManager(paths, templates).prepare(root)


def test_data_root_rejects_future_config_schema_without_rewriting_it(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    templates = _templates(tmp_path / "templates")
    manager = DataRootManager(paths, templates)
    layout = manager.prepare(tmp_path / "data")
    future = {"config_schema_version": 99, "custom": "keep"}
    layout.config_file.write_text(json.dumps(future), encoding="utf-8")

    with pytest.raises(DataRootError, match="config_schema_version"):
        manager.prepare(layout.root)

    assert json.loads(layout.config_file.read_text(encoding="utf-8")) == future


def test_data_root_preflights_all_json_before_adding_missing_defaults(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    templates = _templates(tmp_path / "templates")
    manager = DataRootManager(paths, templates)
    layout = manager.prepare(tmp_path / "data")
    layout.config_file.unlink()
    layout.tags_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(DataRootError, match="标签配置 JSON 无效"):
        manager.prepare(layout.root)

    assert not layout.config_file.exists()
    assert layout.tags_file.read_text(encoding="utf-8") == "{broken"


def test_broken_existing_config_does_not_claim_unmarked_directory(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    templates = _templates(tmp_path / "templates")
    root = tmp_path / "data"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(DataRootError, match="主配置 JSON 无效"):
        DataRootManager(paths, templates).prepare(root)

    assert not (root / ".bili-workspace-data-root.json").exists()
    assert not (root / "userdata").exists()
    assert not (root / "downloads").exists()


def test_data_root_rejects_reparse_fixed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    manager = DataRootManager(paths, _templates(tmp_path / "templates"))
    layout = manager.prepare(tmp_path / "data")
    monkeypatch.setattr(
        "bili_workspace_launcher.paths._is_reparse_point",
        lambda path: Path(path) == layout.config_file,
    )
    with pytest.raises(DataRootError, match="固定数据文件"):
        manager.prepare(layout.root)


def test_data_root_rejects_dangling_fixed_directory_link(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    manager = DataRootManager(paths, _templates(tmp_path / "templates"))
    root = tmp_path / "data"
    root.mkdir()
    try:
        (root / "config").symlink_to(root / "missing", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(DataRootError, match="固定数据目录"):
        manager.prepare(root)


def test_data_root_rejects_invalid_fixed_backup_target(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    manager = DataRootManager(paths, _templates(tmp_path / "templates"))
    layout = manager.prepare(tmp_path / "data")
    layout.config_file.with_suffix(".json.bak").mkdir()

    with pytest.raises(DataRootError, match="固定数据文件"):
        manager.prepare(layout.root)


def test_data_root_lock_excludes_second_launcher(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "control")
    layout = DataRootManager(paths, _templates(tmp_path / "templates")).prepare(tmp_path / "data")
    first = DataRootLock(layout)
    second = DataRootLock(layout)
    first.acquire()
    try:
        with pytest.raises(DataRootLockError, match="另一份启动器"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_data_root_lock_rejects_reparse_lock_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    layout = DataRootManager(paths, _templates(tmp_path / "templates")).prepare(tmp_path / "data")
    monkeypatch.setattr(
        "bili_workspace_launcher.paths._is_reparse_point",
        lambda path: Path(path) == layout.lock_file,
    )
    with pytest.raises(DataRootLockError, match="普通文件"):
        DataRootLock(layout).acquire()
