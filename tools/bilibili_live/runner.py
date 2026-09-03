"""T-BILIBILI-LIVE 固定顺序编排：安全检查、真实链、结构候选与结果。"""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tools.bilibili_live.api import LiveApi
from tools.bilibili_live.artifacts import (
    copy_artifact_into_run,
    git_source_identity,
    load_build_artifact,
    prepare_tool_provider,
)
from tools.bilibili_live.browser import submit_from_creator_page, verify_dashboard_entry
from tools.bilibili_live.contracts import (
    LIVE_MARKER_NAME,
    MAX_MARKER_BYTES,
    MAX_RUN_SECONDS,
    RAW_PUBLIC_RELATIVE_PATH,
    LiveBlockedError,
    LiveFailedError,
    LiveInconclusiveError,
    LiveTestError,
    assert_source_unchanged,
    copy_credentials,
    create_live_run,
    credential_file,
    load_live_marker,
    remove_run_credentials,
    resolve_credential_source,
    run_size_bytes,
    snapshot_file,
    update_summary,
    utc_now,
    validate_test_root,
)
from tools.bilibili_live.discovery import DiscoveryResult, discover_marker_targets
from tools.bilibili_live.execution import DownloadResult, execute_bounded_download
from tools.bilibili_live.fixtures import compare_and_write_candidates
from tools.bilibili_live.processes import (
    OwnedProductProcess,
    candidate_product_process,
    source_product_process,
)


VALID_IMPACTS = {"discovery", "download", "browser", "playback"}
VALID_TARGETS = {"source", "candidate"}
EXIT_BY_STATUS = {
    "passed": 0,
    "failed": 1,
    "inconclusive": 2,
    "blocked": 3,
    "not_run": 4,
}


def _stage(
    run: Path,
    workspace: Path,
    name: str,
    **values: Any,
) -> None:
    update_summary(run, workspace, stage=name, **values)


def _remaining_seconds(started_at: float) -> float:
    remaining = MAX_RUN_SECONDS - (time.monotonic() - started_at)
    if remaining <= 0:
        raise LiveInconclusiveError("真链运行达到 15 分钟总时限")
    return remaining


def _finalize_summary(
    *,
    run: Path,
    workspace: Path,
    status: str,
    started_at: float,
    stop_reason: str = "",
    error_category: str = "",
    reason: str = "",
    **values: Any,
) -> dict[str, Any]:
    return update_summary(
        run,
        workspace,
        status=status,
        stage="finished",
        finished_at=utc_now(),
        elapsed_seconds=round(max(0.0, time.monotonic() - started_at), 3),
        growth_bytes=run_size_bytes(run, workspace),
        stop_reason=stop_reason,
        error_category=error_category,
        reason=reason,
        **values,
    )


def _start_product(
    *,
    target: str,
    workspace: Path,
    run: Path,
    candidate_record: Path | None,
    tool_provider_record: Path | None,
    started_at: float,
) -> tuple[OwnedProductProcess, dict[str, Any]]:
    if target == "source":
        tools_dir, identity = prepare_tool_provider(
            workspace_root=workspace,
            run_root=run,
            record_path=tool_provider_record,
            timeout_seconds=max(1, min(240, int(_remaining_seconds(started_at)))),
        )
        process = source_product_process(
            workspace_root=workspace,
            run_root=run,
            tools_dir=tools_dir,
        )
        process.ready_timeout = max(
            1,
            min(process.ready_timeout, _remaining_seconds(started_at)),
        )
        return process, identity
    if candidate_record is None:
        raise LiveBlockedError("候选目标必须显式提供 candidate build.json")
    artifact = load_build_artifact(
        candidate_record,
        workspace_root=workspace,
        expected_kind="candidate",
    )
    executable, _copied_record = copy_artifact_into_run(
        artifact,
        run,
        directory_name="candidate",
    )
    process = candidate_product_process(
        executable=executable,
        build_id=artifact.build_id,
        run_root=run,
    )
    process.ready_timeout = max(
        1,
        min(process.ready_timeout, _remaining_seconds(started_at)),
    )
    return process, {
        "artifact_kind": artifact.artifact_kind,
        "build_id": artifact.build_id,
        "sha256": artifact.sha256,
        "source_commit": artifact.source_commit,
        "source_dirty": artifact.source_dirty,
    }


def _product_chain(
    *,
    target: str,
    impact: str,
    workspace: Path,
    run: Path,
    discovery: DiscoveryResult,
    candidate_record: Path | None,
    tool_provider_record: Path | None,
    started_at: float,
) -> tuple[DownloadResult | None, dict[str, Any]]:
    process, identity = _start_product(
        target=target,
        workspace=workspace,
        run=run,
        candidate_record=candidate_record,
        tool_provider_record=tool_provider_record,
        started_at=started_at,
    )
    identity_field = "tool_provider" if target == "source" else "candidate_identity"
    _stage(run, workspace, "product_starting", **{identity_field: identity})
    started = False
    stopped = False
    try:
        _remaining_seconds(started_at)
        base_url = process.start()
        started = True
        _stage(run, workspace, "product_ready")
        with LiveApi(base_url, run / "runtime") as api:
            _remaining_seconds(started_at)
            api.setup_admin()
            _remaining_seconds(started_at)
            api.verify_login()
            _remaining_seconds(started_at)
            resolved = api.resolve_creator(str(discovery.profile["uid"]))
            if str((resolved.get("creator") or {}).get("uid") or "") != str(
                discovery.profile["uid"]
            ):
                raise LiveFailedError("产品 API 解析到错误的 UP 主")
            api.verify_covers(discovery.items)
            _remaining_seconds(started_at)
            if impact == "discovery":
                return None, identity

            submitter = None
            if impact in {"browser", "playback"}:
                def submitter(items: list[dict[str, Any]]) -> list[str]:
                    return submit_from_creator_page(
                        api=api,
                        run_root=run,
                        discovery=discovery,
                        items=items,
                        deadline=started_at + MAX_RUN_SECONDS,
                    )
            _stage(run, workspace, "download")

            def report_download_progress(values: dict[str, int]) -> None:
                _stage(run, workspace, "download", **values)

            download = execute_bounded_download(
                api=api,
                run_root=run,
                workspace_root=workspace,
                items=[dict(item) for item in discovery.items],
                started_at=started_at,
                submitter=submitter,
                progress_callback=report_download_progress,
            )
            if impact in {"browser", "playback"}:
                _remaining_seconds(started_at)
                _stage(run, workspace, "dashboard")
                verify_dashboard_entry(
                    api=api,
                    run_root=run,
                    media_id=download.media_id,
                    verify_playback=impact == "playback",
                    deadline=started_at + MAX_RUN_SECONDS,
                )
            return download, identity
    finally:
        if started:
            try:
                process.stop()
                stopped = True
            finally:
                if not stopped:
                    process.abort()


def run_live_test(
    *,
    workspace_root: Path,
    credential_source: Path,
    impact: str,
    target: str = "source",
    candidate_record: Path | None = None,
    tool_provider_record: Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[int, Path | None]:
    if os.name != "nt":
        raise LiveBlockedError("T-BILIBILI-LIVE 首期只支持 Windows 本地运行")
    if impact not in VALID_IMPACTS:
        raise ValueError(f"不支持的影响域: {impact}")
    if target not in VALID_TARGETS:
        raise ValueError(f"不支持的执行目标: {target}")
    if target == "candidate" and tool_provider_record is not None:
        raise ValueError("candidate 目标使用自身工具，不接受单独工具提供者")
    if impact == "discovery" and tool_provider_record is not None:
        raise ValueError("discovery 影响域不准备下载工具")
    workspace = Path(workspace_root).resolve(strict=True)
    selected_env = os.environ if environ is None else environ
    configured_root = str(selected_env.get("BILI_TEST_ROOT", "")).strip()
    if not configured_root:
        raise LiveBlockedError("T-BILIBILI-LIVE 要求显式设置 BILI_TEST_ROOT")

    source = resolve_credential_source(credential_source)
    marker = load_live_marker(source)
    credential = credential_file(source)
    test_root = validate_test_root(
        configured_root,
        workspace_root=workspace,
        credential_source=source,
        environ=selected_env,
    )
    source_identity = git_source_identity(workspace)
    run = create_live_run(
        workspace_root=workspace,
        test_root=test_root,
        credential_source=source,
        marker=marker,
        impact=impact,
        target=target,
        source_identity=source_identity,
        environ=selected_env,
    )
    started_at = time.monotonic()
    marker_path = source / LIVE_MARKER_NAME
    marker_snapshot = snapshot_file(
        marker_path,
        label="真链固定场景",
        max_bytes=MAX_MARKER_BYTES,
    )
    credential_snapshot = None
    try:
        _stage(run, workspace, "credential_copy")
        credential_snapshot, _destination = copy_credentials(source, run, workspace)
        _stage(run, workspace, "discovery")
        discovery = discover_marker_targets(
            marker=marker,
            bbdown_data_dir=run / "runtime" / "config" / "bbdown",
            raw_root=run / RAW_PUBLIC_RELATIVE_PATH,
            deadline=started_at + MAX_RUN_SECONDS,
        )
        _remaining_seconds(started_at)
        tracked_fixtures = workspace / "SoftwareTesting" / "bilibili_live" / "fixtures"
        forbidden_fixture_values = {
            marker.creator_uid,
            *marker.download_bvids,
            str(discovery.profile.get("name") or ""),
        }
        for item in discovery.items:
            forbidden_fixture_values.update(
                str(item.get(field) or "")
                for field in ("title", "author", "cover", "url")
            )
        forbidden_fixture_values.discard("")
        drift = compare_and_write_candidates(
            run / RAW_PUBLIC_RELATIVE_PATH,
            tracked_fixtures,
            run / "results" / "fixture-candidate",
            forbidden_strings=forbidden_fixture_values,
        )
        _remaining_seconds(started_at)
        if drift:
            assert_source_unchanged(
                marker_path,
                marker_snapshot,
                label="真链固定场景",
                max_bytes=MAX_MARKER_BYTES,
            )
            assert_source_unchanged(credential, credential_snapshot)
            _finalize_summary(
                run=run,
                workspace=workspace,
                status="inconclusive",
                started_at=started_at,
                stop_reason="fixture_drift",
                error_category="fixture_drift",
                reason="真实公开响应结构与已跟踪 fixture 不一致，等待显式 review 和刷新",
                fixture_drift=drift,
            )
            return EXIT_BY_STATUS["inconclusive"], run

        download: DownloadResult | None = None
        product_identity: dict[str, Any] | None = None
        if target == "candidate" or impact != "discovery":
            download, product_identity = _product_chain(
                target=target,
                impact=impact,
                workspace=workspace,
                run=run,
                discovery=discovery,
                candidate_record=candidate_record,
                tool_provider_record=tool_provider_record,
                started_at=started_at,
            )
            if download is None:
                _remaining_seconds(started_at)
        assert_source_unchanged(
            marker_path,
            marker_snapshot,
            label="真链固定场景",
            max_bytes=MAX_MARKER_BYTES,
        )
        assert_source_unchanged(credential, credential_snapshot)
        removed = remove_run_credentials(run, workspace)
        values: dict[str, Any] = {
            "credential_copies_removed": removed,
        }
        if product_identity is not None:
            identity_field = "tool_provider" if target == "source" else "candidate_identity"
            values[identity_field] = product_identity
        stop_reason = "completed"
        if download is not None:
            download_values = asdict(download)
            stop_reason = str(download_values.pop("stop_reason"))
            values.update(download_values)
        _finalize_summary(
            run=run,
            workspace=workspace,
            status="passed",
            started_at=started_at,
            stop_reason=stop_reason,
            **values,
        )
        return EXIT_BY_STATUS["passed"], run
    except LiveTestError as exc:
        failure: LiveTestError = exc
        if credential_snapshot is not None:
            try:
                assert_source_unchanged(credential, credential_snapshot)
                assert_source_unchanged(
                    marker_path,
                    marker_snapshot,
                    label="真链固定场景",
                    max_bytes=MAX_MARKER_BYTES,
                )
            except LiveTestError:
                failure = LiveFailedError("凭据源固定输入在运行期间发生变化")
        _finalize_summary(
            run=run,
            workspace=workspace,
            status=failure.status,
            started_at=started_at,
            stop_reason="error",
            error_category=type(failure).__name__,
            reason=str(failure),
        )
        return EXIT_BY_STATUS[failure.status], run
    except BaseException:
        status = "inconclusive"
        error_category = "unexpected_runner_error"
        reason = "真链运行器发生未分类异常"
        if credential_snapshot is not None:
            try:
                assert_source_unchanged(credential, credential_snapshot)
                assert_source_unchanged(
                    marker_path,
                    marker_snapshot,
                    label="真链固定场景",
                    max_bytes=MAX_MARKER_BYTES,
                )
            except LiveTestError:
                status = "failed"
                error_category = "LiveFailedError"
                reason = "凭据源固定输入在运行期间发生变化"
        _finalize_summary(
            run=run,
            workspace=workspace,
            status=status,
            started_at=started_at,
            stop_reason="runner_error",
            error_category=error_category,
            reason=reason,
        )
        return EXIT_BY_STATUS[status], run
