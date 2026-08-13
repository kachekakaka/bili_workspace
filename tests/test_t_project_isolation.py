from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import config_sync
from tools import t_project_isolation as isolation


ROOT = config_sync.ROOT


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_create_run_marks_owned_external_tree_and_records_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "test-root"

    run_root = isolation.create_run(workspace, test_root, "run-001")

    assert isolation.validate_run(run_root, workspace) == run_root.resolve()
    root_marker = json.loads(
        (test_root / isolation.ROOT_MARKER_NAME).read_text(encoding="utf-8")
    )
    run_marker = json.loads(
        (run_root / isolation.RUN_MARKER_NAME).read_text(encoding="utf-8")
    )
    assert root_marker["project_id"] == isolation.PROJECT_ID
    assert run_marker["run_id"] == "run-001"
    for name in isolation.RUN_DIRECTORIES:
        assert (run_root / name).is_dir()

    result_path = isolation.record_result(
        run_root,
        workspace,
        "passed",
        exit_code=0,
        message="ok",
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["message"] == "ok"
    assert run_root.is_dir()


@pytest.mark.parametrize("placement", ["same", "child", "parent"])
def test_create_run_rejects_workspace_overlap(tmp_path: Path, placement: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if placement == "same":
        test_root = workspace
    elif placement == "child":
        test_root = workspace / "test-root"
    else:
        test_root = tmp_path
    with pytest.raises(isolation.IsolationError, match="互相包含"):
        isolation.create_run(workspace, test_root, "run-001")


def test_create_run_rejects_unowned_existing_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "existing-test-root"
    test_root.mkdir()
    (test_root / "unrelated.txt").write_text("do not touch", encoding="utf-8")

    with pytest.raises(isolation.IsolationError, match="缺少所有权标记"):
        isolation.create_run(workspace, test_root, "run-001")
    assert (test_root / "unrelated.txt").read_text(encoding="utf-8") == "do not touch"


def test_create_run_rejects_symlink_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "test-root-target"
    target.mkdir()
    link = tmp_path / "test-root-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("当前平台不允许创建测试用目录符号链接")

    with pytest.raises(isolation.IsolationError, match="符号链接"):
        isolation.create_run(workspace, link, "run-001")


def test_normative_entrypoints_keep_all_outputs_in_owned_run() -> None:
    source = _text("scripts/dev/verify-source.sh")
    browser_phase = _text("scripts/dev/run-playwright-phase.sh")
    for content in (source, browser_phase):
        assert "BILI_VERIFY_RUN_ROOT" in content
        assert "PYTHONPYCACHEPREFIX" in content
        assert "--basetemp" in content
        assert "BILI_RUN_PLAYWRIGHT" in content
        assert "BILI_PLAYWRIGHT_CHROMIUM" in content
        assert "playwright_runtime.py" in content
        assert "--probe" in content
        assert "playwright install" not in content
    assert "results" in content
    assert "export BILI_DATABASE_PATH=" not in source
    assert "unset BILI_DATABASE_PATH" in source
    assert "unset BILI_CONFIG_DIR" not in source
    assert "-B -X utf8 tools/playwright_runtime.py" in source
    assert "-B -X utf8 tools/playwright_runtime.py" in browser_phase
    assert "-m playwright" in browser_phase
    assert "tools/t_project_isolation.py record" in browser_phase
    assert "result-record.log" in browser_phase
    assert "rm -rf" not in source


def test_config_sync_verification_override_stays_in_owned_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_root = tmp_path / "config-sync-runs"
    run_root = isolation.create_run(config_sync.ROOT, test_root, "config-sync")
    monkeypatch.setenv("BILI_VERIFY_RUN_ROOT", str(run_root))
    monkeypatch.setenv("BILI_APP_MODE", "local")
    monkeypatch.setenv("BILI_CONFIG_DIR", str(run_root / "config"))

    paths = config_sync.sync_configs()

    assert Path(paths["runtime_env"]).is_relative_to(run_root)
    assert Path(paths["app_config"]).is_relative_to(run_root)


def test_config_sync_rejects_config_dir_outside_owned_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = isolation.create_run(
        config_sync.ROOT,
        tmp_path / "config-sync-runs",
        "outside-config-check",
    )
    monkeypatch.setenv("BILI_VERIFY_RUN_ROOT", str(run_root))
    monkeypatch.setenv("BILI_CONFIG_DIR", str(tmp_path / "outside-config"))

    with pytest.raises(ValueError, match="配置目录"):
        config_sync.sync_configs()
