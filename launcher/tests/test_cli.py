from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_workspace_launcher import cli, live_session


def test_runtime_smoke_rejects_report_outside_owned_temporary_pair(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    rejected_report = tmp_path / "arbitrary.json"

    result = cli.main(
        [
            "--runtime-smoke",
            "--data-root",
            str(data_root),
            "--expected-build-id",
            "0123456789ab",
            "--runtime-smoke-report",
            str(rejected_report),
        ]
    )

    assert result == 1
    assert not rejected_report.exists()


def test_self_check_failure_returns_without_unhandled_windowed_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> int:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(cli, "self_check", fail)
    assert cli.main(["--self-check"]) == 1


def test_self_check_failure_writes_bounded_machine_readable_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "self-check.json"

    def fail() -> int:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(cli, "self_check", fail)
    monkeypatch.setattr(
        cli.AppPaths,
        "from_executable",
        classmethod(lambda _cls: SimpleNamespace(base_dir=tmp_path)),
    )

    result = cli.main(
        ["--self-check", "--self-check-report", str(report.resolve())]
    )

    assert result == 1
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "status": "failed",
        "error_type": "RuntimeError",
        "error": "injected failure",
    }


def test_live_session_dispatches_only_validated_fixed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = (tmp_path / "runtime").resolve()
    ready = (tmp_path / "results" / "candidate-live-ready.json").resolve()
    result = (tmp_path / "results" / "candidate-live-result.json").resolve()
    stop = (tmp_path / "runtime" / "candidate-live.stop").resolve()
    inputs = live_session.LiveSessionInputs(tmp_path, data_root, ready, result, stop)
    observed: dict[str, object] = {}
    session_token = "a" * 64
    monkeypatch.setenv("BILI_LIVE_SESSION_TOKEN", session_token)

    monkeypatch.setattr(
        live_session,
        "validate_live_session_inputs",
        lambda **_kwargs: inputs,
    )

    def run(**kwargs) -> dict[str, object]:
        observed.update(kwargs)
        return {"status": "stopped"}

    monkeypatch.setattr(live_session, "run_live_session", run)

    code = cli.main(
        [
            "--live-session",
            "--data-root",
            str(data_root),
            "--expected-build-id",
            "0123456789ab",
            "--live-session-ready",
            str(ready),
            "--live-session-result",
            str(result),
            "--live-session-stop",
            str(stop),
        ]
    )

    assert code == 0
    assert observed == {
        "data_root": data_root,
        "expected_build_id": "0123456789ab",
        "ready_path": ready,
        "result_path": result,
        "stop_path": stop,
        "session_token": session_token,
    }
    assert "BILI_LIVE_SESSION_TOKEN" not in live_session.os.environ
