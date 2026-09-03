from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.bilibili_live import runner
from tools.bilibili_live.contracts import LIVE_MARKER_KIND, LIVE_MARKER_NAME, read_summary
from tools.bilibili_live.discovery import DiscoveryResult
from tools.bilibili_live.execution import DownloadResult


BVIDS = tuple(f"BV1TEST0000{index}" for index in range(1, 9))


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "config" / "bbdown").mkdir(parents=True)
    (source / "config" / "bbdown" / "BBDown.data").write_bytes(b"cookie")
    (source / LIVE_MARKER_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": LIVE_MARKER_KIND,
                "creator_uid": "10001",
                "download_bvids": list(BVIDS),
            }
        ),
        encoding="utf-8",
    )
    return source


def _discovery(raw_root: Path) -> DiscoveryResult:
    raw_root.mkdir(parents=True)
    (raw_root / "001-creator-profile.json").write_text(
        json.dumps({"code": 0, "data": {"mid": 10001, "name": "测试"}}),
        encoding="utf-8",
    )
    (raw_root / "index.json").write_text(
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
    items = tuple(
        {
            "bvid": bvid,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "title": "测试",
            "cover": "https://i0.hdslb.com/bfs/archive/test.jpg",
            "author": "测试",
            "duration": "00:01",
            "duration_seconds": 1,
            "pubdate": 1,
            "play": 1,
        }
        for bvid in BVIDS
    )
    return DiscoveryResult(
        profile={"uid": "10001", "name": "测试"},
        items=items,
        page_by_bvid={bvid: 1 for bvid in BVIDS},
        submission_pages=1,
        name_search_page=1,
    )


@pytest.mark.skipif(runner.os.name != "nt", reason="live runner is Windows-only")
def test_tool_provider_is_rejected_outside_source_download_impacts(
    tmp_path: Path,
) -> None:
    provider = tmp_path / "build.json"
    with pytest.raises(ValueError, match="candidate 目标"):
        runner.run_live_test(
            workspace_root=tmp_path / "missing-workspace",
            credential_source=tmp_path / "missing-source",
            impact="download",
            target="candidate",
            tool_provider_record=provider,
        )
    with pytest.raises(ValueError, match="discovery 影响域"):
        runner.run_live_test(
            workspace_root=tmp_path / "missing-workspace",
            credential_source=tmp_path / "missing-source",
            impact="discovery",
            target="source",
            tool_provider_record=provider,
        )


@pytest.mark.skipif(runner.os.name != "nt", reason="live runner is Windows-only")
def test_first_structure_baseline_stops_before_product_and_retains_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "SoftwareTesting" / "bilibili_live" / "fixtures").mkdir(parents=True)
    source = _source(tmp_path)
    monkeypatch.setattr(
        runner,
        "git_source_identity",
        lambda _workspace: {"commit": "0" * 40, "dirty": True},
    )
    monkeypatch.setattr(
        runner,
        "discover_marker_targets",
        lambda **kwargs: _discovery(kwargs["raw_root"]),
    )
    monkeypatch.setattr(
        runner,
        "_product_chain",
        lambda **_kwargs: pytest.fail("fixture drift must stop before product"),
    )

    code, run = runner.run_live_test(
        workspace_root=workspace,
        credential_source=source,
        impact="download",
        environ={
            "BILI_TEST_ROOT": str(tmp_path / "runs"),
            "LOCALAPPDATA": str(tmp_path / "other"),
        },
    )
    assert code == 2
    assert run is not None
    summary = read_summary(run, workspace)
    assert summary["status"] == "inconclusive"
    assert summary["stop_reason"] == "fixture_drift"
    assert (run / "runtime" / "config" / "bbdown" / "BBDown.data").is_file()


@pytest.mark.skipif(runner.os.name != "nt", reason="live runner is Windows-only")
def test_discovery_pass_removes_credentials_when_structure_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "SoftwareTesting" / "bilibili_live" / "fixtures").mkdir(parents=True)
    source = _source(tmp_path)
    monkeypatch.setattr(
        runner,
        "git_source_identity",
        lambda _workspace: {"commit": "0" * 40, "dirty": True},
    )
    monkeypatch.setattr(
        runner,
        "discover_marker_targets",
        lambda **kwargs: _discovery(kwargs["raw_root"]),
    )
    monkeypatch.setattr(
        runner,
        "compare_and_write_candidates",
        lambda *_args, **_kwargs: [],
    )

    code, run = runner.run_live_test(
        workspace_root=workspace,
        credential_source=source,
        impact="discovery",
        environ={
            "BILI_TEST_ROOT": str(tmp_path / "runs"),
            "LOCALAPPDATA": str(tmp_path / "other"),
        },
    )
    assert code == 0
    assert run is not None
    summary = read_summary(run, workspace)
    assert summary["status"] == "passed"
    assert summary["credential_copies_removed"] == 1
    assert not (run / "runtime" / "config" / "bbdown" / "BBDown.data").exists()


@pytest.mark.parametrize(
    ("target", "identity_field", "other_field"),
    [
        ("source", "tool_provider", "candidate_identity"),
        ("candidate", "candidate_identity", "tool_provider"),
    ],
)
@pytest.mark.skipif(runner.os.name != "nt", reason="live runner is Windows-only")
def test_product_identity_uses_target_specific_summary_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    identity_field: str,
    other_field: str,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "SoftwareTesting" / "bilibili_live" / "fixtures").mkdir(
        parents=True
    )
    source = _source(tmp_path)
    identity = {"artifact_kind": "candidate", "build_id": "0123456789ab"}
    monkeypatch.setattr(
        runner,
        "git_source_identity",
        lambda _workspace: {"commit": "0" * 40, "dirty": True},
    )
    monkeypatch.setattr(
        runner,
        "discover_marker_targets",
        lambda **kwargs: _discovery(kwargs["raw_root"]),
    )
    monkeypatch.setattr(
        runner,
        "compare_and_write_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        runner,
        "_product_chain",
        lambda **_kwargs: (
            DownloadResult(
                completed_count=1,
                failed_count=0,
                cancelled_count=7,
                stop_reason="time_limit",
                media_id="media-1",
                successful_bvid=BVIDS[0],
                preferred_quality="360P",
                selected_quality="360P",
                predicted_size_bytes=1,
            ),
            identity,
        ),
    )

    code, run = runner.run_live_test(
        workspace_root=workspace,
        credential_source=source,
        impact="download",
        target=target,
        candidate_record=(workspace / "build" / "candidate" / "build.json")
        if target == "candidate"
        else None,
        environ={
            "BILI_TEST_ROOT": str(tmp_path / "runs"),
            "LOCALAPPDATA": str(tmp_path / "other"),
        },
    )

    assert code == 0
    assert run is not None
    summary = read_summary(run, workspace)
    assert summary[identity_field] == identity
    assert summary[other_field] is None


@pytest.mark.skipif(runner.os.name != "nt", reason="live runner is Windows-only")
def test_unexpected_error_still_detects_credential_source_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "SoftwareTesting" / "bilibili_live" / "fixtures").mkdir(
        parents=True
    )
    source = _source(tmp_path)
    monkeypatch.setattr(
        runner,
        "git_source_identity",
        lambda _workspace: {"commit": "0" * 40, "dirty": True},
    )

    def fail_unexpectedly(**_kwargs) -> DiscoveryResult:
        credential = source / "config" / "bbdown" / "BBDown.data"
        credential.write_bytes(b"changed-cookie")
        raise RuntimeError("private unexpected detail")

    monkeypatch.setattr(runner, "discover_marker_targets", fail_unexpectedly)

    code, run = runner.run_live_test(
        workspace_root=workspace,
        credential_source=source,
        impact="discovery",
        environ={
            "BILI_TEST_ROOT": str(tmp_path / "runs"),
            "LOCALAPPDATA": str(tmp_path / "other"),
        },
    )

    assert code == 1
    assert run is not None
    summary = read_summary(run, workspace)
    assert summary["status"] == "failed"
    assert summary["reason"] == "凭据源固定输入在运行期间发生变化"
    assert "private unexpected detail" not in json.dumps(summary, ensure_ascii=False)
