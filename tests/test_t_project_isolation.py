from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import config_sync
from tools import t_project_isolation as isolation


ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_create_and_validate_minimal_owned_run(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    test_root = tmp_path / "test-root"

    run_root = isolation.create_run(workspace, test_root, "run-001")

    assert isolation.validate_run(run_root, workspace) == run_root.resolve()
    marker = json.loads(
        (run_root / isolation.RUN_MARKER_NAME).read_text(encoding="utf-8")
    )
    assert marker == {
        "created_at": marker["created_at"],
        "kind": isolation.RUN_MARKER_KIND,
        "project_id": isolation.PROJECT_ID,
        "run_id": "run-001",
        "run_root": str(run_root.resolve()),
        "test_root": str(test_root.resolve()),
        "workspace_root": str(workspace.resolve()),
    }
    assert all((run_root / relative).is_dir() for relative in isolation.RUN_DIRECTORIES)
    assert not (run_root / "results" / "result.json").exists()
    assert not (test_root / ".bili-workspace-test-root.json").exists()


def test_default_root_uses_temp_or_explicit_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    configured = tmp_path / "configured-root"
    monkeypatch.setenv("BILI_TEST_ROOT", str(configured))

    run_root = isolation.create_run(workspace, run_id="from-env")

    assert run_root.parent == configured.resolve()


@pytest.mark.parametrize("test_root_kind", ["inside", "contains"])
def test_test_root_and_workspace_cannot_overlap(
    tmp_path: Path,
    test_root_kind: str,
) -> None:
    workspace = _workspace(tmp_path)
    test_root = workspace / "runs" if test_root_kind == "inside" else tmp_path

    with pytest.raises(isolation.IsolationError, match="互相包含"):
        isolation.create_run(workspace, test_root, "run-001")


def test_existing_test_root_contents_are_left_untouched(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    test_root = tmp_path / "test-root"
    test_root.mkdir()
    unrelated = test_root / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")

    run_root = isolation.create_run(workspace, test_root, "run-001")
    isolation.cleanup_run(run_root, workspace)

    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert test_root.is_dir()


def test_invalid_run_id_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(isolation.IsolationError, match="run-id"):
        isolation.create_run(workspace, tmp_path / "test-root", "../escape")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "other"),
        ("project_id", "other"),
        ("workspace_root", "C:/other"),
        ("run_root", "C:/other"),
        ("run_id", "other"),
    ],
)
def test_tampered_owner_marker_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    workspace = _workspace(tmp_path)
    run_root = isolation.create_run(workspace, tmp_path / "test-root", "run-001")
    marker_path = run_root / isolation.RUN_MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker[field] = value
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(isolation.IsolationError, match="字段不匹配"):
        isolation.validate_run(run_root, workspace)


def test_unowned_directory_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    unowned = tmp_path / "test-root" / "unowned"
    unowned.mkdir(parents=True)

    with pytest.raises(isolation.IsolationError, match="缺少普通所有权标记"):
        isolation.validate_run(unowned, workspace)


def test_missing_or_linked_managed_directory_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    run_root = isolation.create_run(workspace, tmp_path / "test-root", "run-001")
    (run_root / "results").rmdir()

    with pytest.raises(isolation.IsolationError, match="缺少安全子目录: results"):
        isolation.validate_run(run_root, workspace)


def test_symlink_test_root_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "test-root-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建目录符号链接")

    with pytest.raises(isolation.IsolationError, match="符号链接或重解析点"):
        isolation.create_run(workspace, link, "run-001")


def test_cleanup_only_removes_validated_exact_run(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    test_root = tmp_path / "test-root"
    first = isolation.create_run(workspace, test_root, "first")
    second = isolation.create_run(workspace, test_root, "second")

    returned_root = isolation.cleanup_run(first, workspace)

    assert returned_root == test_root.resolve()
    assert not first.exists()
    assert second.is_dir()
    assert test_root.is_dir()


def test_cleanup_refuses_tampered_run(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    run_root = isolation.create_run(workspace, tmp_path / "test-root", "run-001")
    (run_root / isolation.RUN_MARKER_NAME).unlink()

    with pytest.raises(isolation.IsolationError, match="缺少普通所有权标记"):
        isolation.cleanup_run(run_root, workspace)
    assert run_root.is_dir()


def test_cli_exposes_only_create_validate_and_cleanup(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    test_root = tmp_path / "test-root"
    command = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        str(ROOT / "tools" / "t_project_isolation.py"),
    ]

    created = subprocess.run(
        [*command, "create", "--workspace-root", str(workspace), "--test-root", str(test_root), "--run-id", "cli"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert created.returncode == 0, created.stdout + created.stderr
    run_root = Path(created.stdout.strip())

    validated = subprocess.run(
        [*command, "validate", "--workspace-root", str(workspace), "--run-root", str(run_root)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr

    cleaned = subprocess.run(
        [*command, "cleanup", "--workspace-root", str(workspace), "--run-root", str(run_root)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
    assert not run_root.exists()

    help_result = subprocess.run(
        [*command, "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert "record" not in help_result.stdout
    assert "gc-plan" not in help_result.stdout


def test_shell_consumers_keep_local_cleanup_and_ci_artifacts() -> None:
    source = (ROOT / "scripts" / "dev" / "verify-source.sh").read_text(encoding="utf-8")
    browser = (ROOT / "scripts" / "dev" / "run-playwright-phase.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "t_project_isolation.py cleanup" in source
    assert "t_project_isolation.py record" not in source
    assert "t_project_isolation.py cleanup" not in browser
    assert "t_project_isolation.py record" not in browser
    assert "if: always()" in workflow
    assert "bili_workspace_test/**" in workflow


def test_config_sync_accepts_owned_run_and_keeps_writes_inside(
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


def test_config_sync_rejects_config_outside_owned_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = isolation.create_run(
        config_sync.ROOT,
        tmp_path / "config-sync-runs",
        "config-sync",
    )
    monkeypatch.setenv("BILI_VERIFY_RUN_ROOT", str(run_root))
    monkeypatch.setenv("BILI_APP_MODE", "local")
    monkeypatch.setenv("BILI_CONFIG_DIR", str(tmp_path / "outside"))

    with pytest.raises(ValueError, match="必须位于已验证的运行目录内"):
        config_sync.sync_configs()
