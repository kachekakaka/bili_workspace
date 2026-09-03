from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

from tools.bilibili_live.artifacts import load_build_artifact, sha256_file
from tools.bilibili_live.contracts import LiveBlockedError, LiveInconclusiveError
from tools.bilibili_live.processes import OwnedProductProcess, candidate_product_process


def _candidate_record(workspace: Path) -> tuple[Path, Path]:
    candidate = workspace / "build" / "candidate"
    candidate.mkdir(parents=True)
    executable = candidate / "bili-workspace.exe"
    executable.write_bytes(b"candidate")
    record = candidate / "build.json"
    record.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_kind": "candidate",
                "build_id": "0123456789ab",
                "executable": executable.relative_to(workspace).as_posix(),
                "sha256": sha256_file(executable),
                "size_bytes": executable.stat().st_size,
                "source_commit": "a" * 40,
                "source_dirty": True,
                "exe_self_check_ran": True,
                "exe_runtime_smoke_ran": True,
            }
        ),
        encoding="utf-8",
    )
    return record, executable


def test_candidate_artifact_requires_matching_record_and_digest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    record, executable = _candidate_record(workspace)

    artifact = load_build_artifact(
        record,
        workspace_root=workspace,
        expected_kind="candidate",
    )
    assert artifact.executable_path == executable.resolve()
    assert artifact.build_id == "0123456789ab"

    executable.write_bytes(b"changed")
    with pytest.raises(LiveBlockedError, match="不一致"):
        load_build_artifact(
            record,
            workspace_root=workspace,
            expected_kind="candidate",
        )


def test_candidate_process_rehomes_temporary_state_inside_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    candidate = run / "candidate" / "bili-workspace.exe"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate")
    monkeypatch.setenv("BILI_HOST", "external")
    monkeypatch.setenv("PYTHONPATH", "external")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "external-local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "external-roaming"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "external-profile"))

    process = candidate_product_process(
        executable=candidate,
        build_id="0123456789ab",
        run_root=run,
    )

    assert "BILI_HOST" not in process.environment
    assert process.environment["HOME"] == str(run / "home")
    assert process.environment["TEMP"] == str(run / "tmp")
    assert process.environment["PYTHONPYCACHEPREFIX"] == str(run / "pycache")
    assert process.environment["LOCALAPPDATA"] == str(
        run / "runtime" / "userdata" / "local-app-data"
    )
    assert process.environment["APPDATA"] == str(
        run / "runtime" / "userdata" / "roaming-app-data"
    )
    assert process.environment["USERPROFILE"] == str(run / "home")
    session_token = process.environment["BILI_LIVE_SESSION_TOKEN"]
    assert re.fullmatch(r"[0-9a-f]{64}", session_token)
    assert process.expected_token_sha256 == hashlib.sha256(
        session_token.encode("ascii")
    ).hexdigest()
    assert process.expected_build_id == "0123456789ab"


def test_owned_process_aborts_child_when_ready_record_is_malformed(
    tmp_path: Path,
) -> None:
    ready = tmp_path / "ready.json"
    result = tmp_path / "result.json"
    stop = tmp_path / "stop"
    child = (
        "from pathlib import Path; import time; "
        f"Path({str(ready)!r}).write_text('not-json', encoding='utf-8'); "
        "time.sleep(60)"
    )
    process = OwnedProductProcess(
        command=[sys.executable, "-B", "-X", "utf8", "-c", child],
        cwd=tmp_path,
        environment=dict(os.environ),
        log_path=tmp_path / "process.log",
        ready_path=ready,
        result_path=result,
        stop_path=stop,
        expected_ready_kind="ready",
        expected_result_kind="result",
        ready_timeout=5,
    )

    with pytest.raises(LiveInconclusiveError, match="控制文件无效"):
        process.start()

    assert process.process is not None
    assert process.process.poll() is not None


def test_owned_candidate_process_rejects_wrong_session_token_digest(
    tmp_path: Path,
) -> None:
    ready = tmp_path / "ready.json"
    result = tmp_path / "result.json"
    stop = tmp_path / "stop"
    payload = {
        "schema_version": 1,
        "kind": "ready",
        "host": "127.0.0.1",
        "port": 3398,
        "token_sha256": "b" * 64,
    }
    child = (
        "from pathlib import Path; import json, os, time; "
        f"payload = {payload!r}; payload['pid'] = os.getpid(); "
        f"Path({str(ready)!r}).write_text(json.dumps(payload), encoding='utf-8'); "
        "time.sleep(60)"
    )
    process = OwnedProductProcess(
        command=[sys.executable, "-B", "-X", "utf8", "-c", child],
        cwd=tmp_path,
        environment=dict(os.environ),
        log_path=tmp_path / "process.log",
        ready_path=ready,
        result_path=result,
        stop_path=stop,
        expected_ready_kind="ready",
        expected_result_kind="result",
        expected_token_sha256="a" * 64,
        ready_timeout=5,
    )

    with pytest.raises(LiveInconclusiveError, match="身份不匹配"):
        process.start()

    assert process.process is not None
    assert process.process.poll() is not None
