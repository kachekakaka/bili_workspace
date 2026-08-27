from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools import config_sync
from tools import t_project_isolation as isolation


ROOT = config_sync.ROOT
GC_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _set_result_age(
    run_root: Path,
    *,
    status: str,
    age: timedelta,
    finalized: bool,
) -> None:
    result_path = run_root / isolation.RESULT_RELATIVE_PATH
    result = json.loads(result_path.read_text(encoding="utf-8"))
    timestamp = isolation._format_utc(GC_NOW - age)
    result["status"] = status
    result["updated_at"] = timestamp
    result["finalized_at"] = timestamp if finalized else None
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _set_run_created_at(run_root: Path, age: timedelta) -> None:
    marker_path = run_root / isolation.RUN_MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["created_at"] = isolation._format_utc(GC_NOW - age)
    marker_path.write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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
    assert root_marker["schema_version"] == isolation.ROOT_MARKER_SCHEMA_VERSION
    assert run_marker["run_id"] == "run-001"
    assert run_marker["schema_version"] == isolation.RUN_SCHEMA_VERSION
    assert run_marker["test_id"] == isolation.TEST_ID
    for name in isolation.RUN_DIRECTORIES:
        assert (run_root / name).is_dir()
    initial_result = json.loads(
        (run_root / isolation.RESULT_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    assert initial_result["finalized_at"] is None

    result_path = isolation.record_result(
        run_root,
        workspace,
        "passed",
        exit_code=0,
        message="ok",
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == isolation.RESULT_SCHEMA_VERSION
    assert result["test_id"] == isolation.TEST_ID
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["message"] == "ok"
    assert result["finalized_at"] == result["updated_at"]
    assert run_root.is_dir()


def test_legacy_v1_run_remains_t_project_and_record_preserves_schema(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_root = isolation.create_run(workspace, tmp_path / "test-root", "legacy-v1")
    marker_path = run_root / isolation.RUN_MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["schema_version"] = isolation.LEGACY_RUN_SCHEMA_VERSION
    marker.pop("test_id")
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    assert isolation.validate_run(run_root, workspace) == run_root.resolve()
    result_path = isolation.record_result(run_root, workspace, "passed")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == isolation.LEGACY_RUN_SCHEMA_VERSION
    assert "test_id" not in result


@pytest.mark.parametrize(
    ("schema_version", "test_id", "message"),
    [
        (3, isolation.TEST_ID, "不支持的 schema_version"),
        (isolation.RUN_SCHEMA_VERSION, None, "test_id"),
        (isolation.RUN_SCHEMA_VERSION, "T-DOCKER", "test_id"),
    ],
)
def test_validate_run_rejects_unknown_schema_or_wrong_identity(
    tmp_path: Path,
    schema_version: int,
    test_id: str | None,
    message: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_root = isolation.create_run(workspace, tmp_path / "test-root", "invalid-run")
    marker_path = run_root / isolation.RUN_MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["schema_version"] = schema_version
    if test_id is None:
        marker.pop("test_id", None)
    else:
        marker["test_id"] = test_id
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(isolation.IsolationError, match=message):
        isolation.validate_run(run_root, workspace)


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


def test_reparse_attribute_is_detected_without_following_target() -> None:
    class ReparsePath:
        def lstat(self) -> object:
            return type(
                "FakeStat",
                (),
                {"st_file_attributes": isolation.REPARSE_POINT_ATTRIBUTE},
            )()

        def is_symlink(self) -> bool:
            return False

    assert isolation._is_reparse_point(ReparsePath())


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
        assert 'export TEMP="$RUN_ROOT/tmp"' in content
        assert 'export TMP="$RUN_ROOT/tmp"' in content
        assert "tr -d '\\r'" in content
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
    windows_source = _text("scripts/windows/new-test-run.ps1")
    assert "finalized_at = $null" in windows_source
    assert "updated_at = $finalizedAt" in windows_source
    assert "finalized_at = $finalizedAt" in windows_source


def test_gc_plan_applies_status_retention_at_exact_boundaries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "test-root"
    passed = isolation.create_run(workspace, test_root, "passed-expired")
    failed = isolation.create_run(workspace, test_root, "failed-expired")
    fresh = isolation.create_run(workspace, test_root, "not-run-fresh")
    _set_result_age(
        passed,
        status="passed",
        age=isolation.GC_SHORT_RETENTION,
        finalized=True,
    )
    _set_result_age(
        failed,
        status="failed",
        age=isolation.GC_LONG_RETENTION,
        finalized=True,
    )
    _set_result_age(
        fresh,
        status="not_run",
        age=isolation.GC_SHORT_RETENTION - timedelta(seconds=1),
        finalized=True,
    )

    plan = isolation.build_gc_plan(workspace, test_root, now=GC_NOW)

    assert [item["run_id"] for item in plan["candidates"]] == [
        "failed-expired",
        "passed-expired",
    ]
    assert {item["category"] for item in plan["candidates"]} == {
        isolation.GC_ORDINARY_CATEGORY
    }
    assert {item["evidence_state"] for item in plan["candidates"]} == {
        "finalized"
    }
    assert len(plan["test_root_marker_sha256"]) == 64
    assert len(plan["plan_digest"]) == 64


def test_gc_plan_is_read_only_when_test_root_is_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing_root = tmp_path / "missing-test-root"

    with pytest.raises(isolation.IsolationError, match="不存在或不是目录"):
        isolation.build_gc_plan(workspace, missing_root, now=GC_NOW)

    assert not missing_root.exists()


def test_gc_plan_rejects_result_identity_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "test-root"
    run_root = isolation.create_run(workspace, test_root, "identity-mismatch")
    _set_result_age(
        run_root,
        status="passed",
        age=isolation.GC_SHORT_RETENTION,
        finalized=True,
    )
    result_path = run_root / isolation.RESULT_RELATIVE_PATH
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["run_id"] = "another-run"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(isolation.IsolationError, match="结果字段不匹配: run_id"):
        isolation.build_gc_plan(
            workspace,
            test_root,
            run_ids=["identity-mismatch"],
            now=GC_NOW,
        )


def test_gc_apply_rejects_drift_and_deletes_only_confirmed_run(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "test-root"
    expired = isolation.create_run(workspace, test_root, "expired")
    preserved = isolation.create_run(workspace, test_root, "preserved")
    _set_result_age(
        expired,
        status="passed",
        age=isolation.GC_SHORT_RETENTION,
        finalized=True,
    )
    _set_result_age(
        preserved,
        status="passed",
        age=timedelta(hours=1),
        finalized=True,
    )
    expected = [("expired", isolation.GC_ORDINARY_CATEGORY)]
    plan = isolation.build_gc_plan(
        workspace,
        test_root,
        run_ids=["expired"],
        now=GC_NOW,
    )

    with pytest.raises(isolation.IsolationError, match="计划已漂移"):
        isolation.apply_gc_plan(
            workspace,
            test_root,
            expected,
            "0" * 64,
            now=GC_NOW,
        )
    assert expired.is_dir()
    assert preserved.is_dir()

    with pytest.raises(isolation.IsolationError, match="候选分类已漂移"):
        isolation.apply_gc_plan(
            workspace,
            test_root,
            [("expired", isolation.GC_LEGACY_CATEGORY)],
            plan["plan_digest"],
            allow_legacy_or_abandoned=True,
            now=GC_NOW,
        )
    assert expired.is_dir()

    result_path = expired / isolation.RESULT_RELATIVE_PATH
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["message"] = "changed after dry-run"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(isolation.IsolationError, match="计划已漂移"):
        isolation.apply_gc_plan(
            workspace,
            test_root,
            expected,
            plan["plan_digest"],
            now=GC_NOW,
        )
    assert expired.is_dir()

    refreshed = isolation.build_gc_plan(
        workspace,
        test_root,
        run_ids=["expired"],
        now=GC_NOW,
    )
    assert isolation.apply_gc_plan(
        workspace,
        test_root,
        expected,
        refreshed["plan_digest"],
        now=GC_NOW,
    ) == ("expired",)
    assert not expired.exists()
    assert preserved.is_dir()


def test_gc_apply_requires_special_confirmation_for_legacy_candidate(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "test-root"
    legacy = isolation.create_run(workspace, test_root, "legacy")
    _set_result_age(
        legacy,
        status="inconclusive",
        age=isolation.GC_LONG_RETENTION,
        finalized=False,
    )
    plan = isolation.build_gc_plan(
        workspace,
        test_root,
        run_ids=["legacy"],
        now=GC_NOW,
    )
    candidate = plan["candidates"][0]
    expected = [("legacy", isolation.GC_LEGACY_CATEGORY)]
    assert candidate["category"] == isolation.GC_LEGACY_CATEGORY
    assert candidate["evidence_state"] == "missing_finalized_at"

    with pytest.raises(isolation.IsolationError, match="显式"):
        isolation.apply_gc_plan(
            workspace,
            test_root,
            expected,
            plan["plan_digest"],
            now=GC_NOW,
        )
    assert legacy.is_dir()

    assert isolation.apply_gc_plan(
        workspace,
        test_root,
        expected,
        plan["plan_digest"],
        allow_legacy_or_abandoned=True,
        now=GC_NOW,
    ) == ("legacy",)
    assert not legacy.exists()


def test_gc_can_plan_abandoned_owned_run_without_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "test-root"
    abandoned = isolation.create_run(workspace, test_root, "abandoned")
    _set_run_created_at(abandoned, isolation.GC_LONG_RETENTION)
    (abandoned / isolation.RESULT_RELATIVE_PATH).unlink()
    (abandoned / "results").rmdir()
    plan = isolation.build_gc_plan(
        workspace,
        test_root,
        run_ids=["abandoned"],
        now=GC_NOW,
    )
    candidate = plan["candidates"][0]
    expected = [("abandoned", isolation.GC_LEGACY_CATEGORY)]
    assert candidate["status"] == "unknown"
    assert candidate["evidence_state"] == "missing_result"
    assert candidate["result_sha256"] is None

    with pytest.raises(isolation.IsolationError, match="显式"):
        isolation.apply_gc_plan(
            workspace,
            test_root,
            expected,
            plan["plan_digest"],
            now=GC_NOW,
        )
    assert abandoned.is_dir()

    assert isolation.apply_gc_plan(
        workspace,
        test_root,
        expected,
        plan["plan_digest"],
        allow_legacy_or_abandoned=True,
        now=GC_NOW,
    ) == ("abandoned",)
    assert not abandoned.exists()


def test_gc_validation_rejects_non_direct_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_root = tmp_path / "test-root"
    run_root = isolation.create_run(workspace, test_root, "nested-run")
    nested_parent = test_root / "nested"
    nested_parent.mkdir()
    nested_run = run_root.rename(nested_parent / run_root.name)
    marker_path = nested_run / isolation.RUN_MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["run_root"] = str(nested_run.resolve())
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(isolation.IsolationError, match="直接子目录"):
        isolation._gc_candidate(nested_run, workspace.resolve(), GC_NOW)


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
