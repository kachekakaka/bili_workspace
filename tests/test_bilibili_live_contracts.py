from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from tools.bilibili_live.contracts import (
    CREDENTIAL_RELATIVE_PATH,
    LIVE_MARKER_KIND,
    LIVE_MARKER_NAME,
    LiveBlockedError,
    LiveInconclusiveError,
    LiveMarker,
    copy_credentials,
    create_live_run,
    load_live_marker,
    read_summary,
    remove_run_credentials,
    snapshot_file,
    update_summary,
    validate_test_root,
    write_summary,
)
from tools.bilibili_live.fixtures import (
    RecordingClient,
    build_structural_candidates,
    compare_and_write_candidates,
    validate_candidate_directory,
)
from tools.bilibili_live.maintenance import (
    cleanup_stale_run,
    list_stale_runs,
    refresh_fixtures_from_run,
)


BVIDS = tuple(f"BV1TEST0000{index}" for index in range(1, 9))


def credential_source(tmp_path: Path) -> Path:
    source = tmp_path / "credential-source"
    (source / "config" / "bbdown").mkdir(parents=True)
    (source / "config" / "bbdown" / "BBDown.data").write_bytes(b"credential")
    (source / LIVE_MARKER_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": LIVE_MARKER_KIND,
                "creator_uid": "0010001",
                "download_bvids": list(BVIDS),
            }
        ),
        encoding="utf-8",
    )
    return source


def test_live_marker_is_strict_and_canonical(tmp_path: Path) -> None:
    source = credential_source(tmp_path)
    assert load_live_marker(source) == LiveMarker("10001", BVIDS)

    payload = json.loads((source / LIVE_MARKER_NAME).read_text(encoding="utf-8"))
    payload["unknown"] = True
    (source / LIVE_MARKER_NAME).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LiveBlockedError, match="字段集合"):
        load_live_marker(source)


def test_live_test_root_rejects_workspace_source_and_local_app_data(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = credential_source(tmp_path)
    local_app_data = tmp_path / "local-app-data"
    local_app_data.mkdir()

    with pytest.raises(LiveBlockedError, match="工作区或凭据源"):
        validate_test_root(
            workspace / "runs",
            workspace_root=workspace,
            credential_source=source,
            environ={"LOCALAPPDATA": str(local_app_data)},
        )
    with pytest.raises(LiveBlockedError, match="LOCALAPPDATA"):
        validate_test_root(
            local_app_data / "runs",
            workspace_root=workspace,
            credential_source=source,
            environ={"LOCALAPPDATA": str(local_app_data)},
        )
    with pytest.raises(LiveBlockedError, match="验证绝对"):
        validate_test_root(
            tmp_path / "runs",
            workspace_root=workspace,
            credential_source=source,
            environ={},
        )


def test_live_run_copies_source_read_only_and_removes_all_success_copies(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = credential_source(tmp_path)
    test_root = tmp_path / "runs"
    marker = load_live_marker(source)
    run = create_live_run(
        workspace_root=workspace,
        test_root=test_root,
        credential_source=source,
        marker=marker,
        impact="download",
        target="source",
        source_identity={"commit": "0" * 40, "dirty": True},
        environ={"LOCALAPPDATA": str(tmp_path / "other")},
    )
    source_file = source / CREDENTIAL_RELATIVE_PATH
    before = snapshot_file(source_file)
    copied_snapshot, copied = copy_credentials(source, run, workspace)
    assert copied_snapshot == before
    assert copied.read_bytes() == b"credential"
    mirrored = run / "media-tools" / "BBDown.data"
    mirrored.write_bytes(b"credential")
    alternate_case = run / "results" / "bbdown.DATA"
    alternate_case.write_bytes(b"credential")

    assert remove_run_credentials(run, workspace) == 3
    assert source_file.read_bytes() == b"credential"
    assert not copied.exists()
    assert not mirrored.exists()
    assert not alternate_case.exists()


def test_recording_and_structural_candidate_exclude_nav_and_real_values(
    tmp_path: Path,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/nav"):
            return httpx.Response(200, json={"code": 0, "data": {"name": "真实账号"}})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "owner": {"mid": 998877, "name": "真实名字"},
                    "bvid": "BV1REAL00001",
                    "pic": "https://i0.hdslb.com/bfs/archive/real.jpg",
                    "items": [
                        {"title": "真实标题", "duration": 12},
                        {"title": "另一个标题", "duration": 34},
                    ],
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    raw = tmp_path / "raw"
    with RecordingClient(raw, client) as recorder:
        recorder.get("https://api.bilibili.com/x/web-interface/nav")
        recorder.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": "secret"})
        recorder.write_index()
    assert len(list(raw.glob("*.json"))) == 2
    text = "\n".join(path.read_text(encoding="utf-8") for path in raw.glob("*.json"))
    assert "真实账号" not in text
    candidates = build_structural_candidates(raw)
    serialized = json.dumps(candidates, ensure_ascii=False, sort_keys=True)
    assert "真实名字" not in serialized
    assert "真实标题" not in serialized
    assert "BV1REAL00001" not in serialized
    assert "BV1TEST00001" in serialized
    variants = candidates["video-detail"]["variants"]
    assert len(variants[0]["data"]["items"]) == 1


def test_fixture_drift_writes_only_sanitized_candidate(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "001-creator-profile.json").write_text(
        json.dumps({"code": 0, "data": {"name": "真实姓名", "mid": 123}}),
        encoding="utf-8",
    )
    (raw / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {"kind": "creator-profile", "file": "001-creator-profile.json"}
                ],
            }
        ),
        encoding="utf-8",
    )
    tracked = tmp_path / "tracked"
    candidate = tmp_path / "candidate"
    assert compare_and_write_candidates(raw, tracked, candidate) == ["creator-profile"]
    validated = validate_candidate_directory(candidate)
    serialized = json.dumps(validated, ensure_ascii=False, sort_keys=True)
    assert "真实姓名" not in serialized
    assert '"name": "text"' in serialized


def test_fixture_indexes_must_be_json_objects(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "index.json").write_text("[]", encoding="utf-8")
    with pytest.raises(LiveInconclusiveError, match="公开响应索引"):
        build_structural_candidates(raw)

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.json").write_text("[]", encoding="utf-8")
    with pytest.raises(LiveInconclusiveError, match="候选索引"):
        validate_candidate_directory(candidate)


def test_structural_candidate_rejects_real_values_used_as_dynamic_keys(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "001-creator-profile.json").write_text(
        json.dumps(
            {
                "code": 0,
                "data": {"name": "真实昵称", "真实昵称": {"uid": 12345}},
            }
        ),
        encoding="utf-8",
    )
    (raw / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {"kind": "creator-profile", "file": "001-creator-profile.json"}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LiveInconclusiveError, match="动态值"):
        build_structural_candidates(raw)


def test_fixture_refresh_rebuilds_candidate_from_same_run_raw_response(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    tracked = workspace / "SoftwareTesting" / "bilibili_live" / "fixtures"
    tracked.mkdir(parents=True)
    source = credential_source(tmp_path)
    run = create_live_run(
        workspace_root=workspace,
        test_root=tmp_path / "runs",
        credential_source=source,
        marker=load_live_marker(source),
        impact="discovery",
        target="source",
        source_identity={"commit": "0" * 40, "dirty": False},
        environ={"LOCALAPPDATA": str(tmp_path / "other")},
    )
    raw = run / "results" / "raw-public"
    raw.mkdir()
    (raw / "001-creator-profile.json").write_text(
        json.dumps({"code": 0, "data": {"name": "真实姓名", "mid": 12345}}),
        encoding="utf-8",
    )
    (raw / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {"kind": "creator-profile", "file": "001-creator-profile.json"}
                ],
            }
        ),
        encoding="utf-8",
    )
    candidate = run / "results" / "fixture-candidate"
    drift = compare_and_write_candidates(raw, tracked, candidate)
    update_summary(
        run,
        workspace,
        status="inconclusive",
        stop_reason="fixture_drift",
        error_category="fixture_drift",
        fixture_drift=drift,
    )
    candidate_file = candidate / "creator-profile.json"
    payload = json.loads(candidate_file.read_text(encoding="utf-8"))
    payload["extra"] = "text"
    candidate_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveInconclusiveError, match="同一 run"):
        refresh_fixtures_from_run(
            run_root=run,
            workspace_root=workspace,
            tracked_root=tracked,
        )


def test_live_summary_rejects_boolean_schema_version(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = credential_source(tmp_path)
    run = create_live_run(
        workspace_root=workspace,
        test_root=tmp_path / "runs",
        credential_source=source,
        marker=load_live_marker(source),
        impact="discovery",
        target="source",
        source_identity={"commit": "0" * 40, "dirty": False},
        environ={"LOCALAPPDATA": str(tmp_path / "other")},
    )
    summary_path = run / "results" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["schema_version"] = True
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(LiveInconclusiveError, match="身份"):
        read_summary(run, workspace)


def test_stale_run_requires_72_hours_and_exact_cleanup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = credential_source(tmp_path)
    run = create_live_run(
        workspace_root=workspace,
        test_root=tmp_path / "runs",
        credential_source=source,
        marker=load_live_marker(source),
        impact="discovery",
        target="source",
        source_identity={"commit": "0" * 40, "dirty": False},
        environ={"LOCALAPPDATA": str(tmp_path / "other")},
    )
    summary = read_summary(run, workspace)
    now = datetime.now(timezone.utc)
    summary["started_at"] = (now - timedelta(hours=73)).isoformat().replace("+00:00", "Z")
    write_summary(run, workspace, summary)

    assert list_stale_runs(test_root=run.parent, workspace_root=workspace, now=now) == [run]
    parent = cleanup_stale_run(
        run_root=run,
        test_root=run.parent,
        workspace_root=workspace,
        credential_source=source,
        now=now,
    )
    assert parent == tmp_path / "runs"
    assert parent.is_dir()
    assert not run.exists()
