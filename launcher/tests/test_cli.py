from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_workspace_launcher import cli


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
