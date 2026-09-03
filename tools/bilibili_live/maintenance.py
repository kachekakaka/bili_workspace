"""真链运行的显式 fixture 刷新、过期列举与精确清理。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tools.bilibili_live.contracts import (
    FIXTURE_CANDIDATE_RELATIVE_PATH,
    STALE_AFTER_SECONDS,
    LiveBlockedError,
    LiveInconclusiveError,
    _reject_existing_reparse_ancestors,
    iter_run_files,
    is_reparse,
    paths_overlap,
    read_summary,
    resolve_credential_source,
)
from tools.bilibili_live.fixtures import (
    refresh_tracked_fixtures,
    validate_candidate_matches_raw,
)
from tools.t_project_isolation import IsolationError, cleanup_run, validate_run


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LiveInconclusiveError("真链摘要缺少 UTC started_at")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LiveInconclusiveError("真链摘要 started_at 无效") from exc
    return parsed.astimezone(timezone.utc)


def list_stale_runs(
    *,
    test_root: Path,
    workspace_root: Path,
    now: datetime | None = None,
) -> list[Path]:
    raw_root = Path(test_root).expanduser()
    if not raw_root.is_absolute():
        raise LiveBlockedError("过期列举要求显式普通测试根绝对路径")
    _reject_existing_reparse_ancestors(raw_root, "过期列举测试根")
    if not raw_root.is_dir() or raw_root.is_symlink() or is_reparse(raw_root):
        raise LiveBlockedError("过期列举要求显式普通测试根绝对路径")
    workspace = Path(workspace_root).resolve(strict=True)
    root = raw_root.resolve(strict=True)
    if paths_overlap(root, workspace):
        raise LiveBlockedError("过期列举的测试根不得与工作区重叠")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result: list[Path] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir() or candidate.is_symlink() or is_reparse(candidate):
            continue
        try:
            run = validate_run(candidate, workspace)
            summary = read_summary(run, workspace)
            started = _parse_utc(summary.get("started_at"))
        except (IsolationError, LiveInconclusiveError, OSError):
            continue
        if (current - started).total_seconds() >= STALE_AFTER_SECONDS:
            result.append(run)
    return result


def cleanup_stale_run(
    *,
    run_root: Path,
    test_root: Path,
    workspace_root: Path,
    credential_source: Path,
    now: datetime | None = None,
) -> Path:
    raw_root = Path(test_root).expanduser()
    if not raw_root.is_absolute():
        raise LiveBlockedError("精确清理要求显式普通测试根绝对路径")
    _reject_existing_reparse_ancestors(raw_root, "精确清理测试根")
    root = raw_root.resolve(strict=True)
    try:
        run = validate_run(run_root, workspace_root)
    except IsolationError as exc:
        raise LiveBlockedError("待清理 run 的通用所有权校验失败") from exc
    source = resolve_credential_source(credential_source)
    if run.parent != root:
        raise LiveBlockedError("待清理 run 不是指定测试根的直接子目录")
    if paths_overlap(run, Path(workspace_root).resolve(strict=True)) or paths_overlap(run, source):
        raise LiveBlockedError("待清理 run 与工作区或凭据源重叠")
    stale = list_stale_runs(test_root=root, workspace_root=workspace_root, now=now)
    if run not in stale:
        raise LiveBlockedError("待清理 run 尚未满 72 小时或身份无效")
    list(iter_run_files(run, workspace_root))
    try:
        return cleanup_run(run, workspace_root)
    except IsolationError as exc:
        raise LiveInconclusiveError("清理前 run 所有权状态发生变化") from exc


def refresh_fixtures_from_run(
    *,
    run_root: Path,
    workspace_root: Path,
    tracked_root: Path,
) -> list[Path]:
    try:
        run = validate_run(run_root, workspace_root)
    except IsolationError as exc:
        raise LiveBlockedError("fixture 刷新 run 的通用所有权校验失败") from exc
    summary = read_summary(run, workspace_root)
    drift = summary.get("fixture_drift")
    if (
        summary.get("status") != "inconclusive"
        or summary.get("stop_reason") != "fixture_drift"
        or summary.get("error_category") != "fixture_drift"
        or not isinstance(drift, list)
        or not drift
    ):
        raise LiveBlockedError("只有结构漂移的不可判定 run 可以刷新 fixture")
    candidate = run / FIXTURE_CANDIDATE_RELATIVE_PATH
    tracked = Path(tracked_root).resolve(strict=False)
    workspace = Path(workspace_root).resolve(strict=True)
    expected = (workspace / "SoftwareTesting" / "bilibili_live" / "fixtures").resolve(
        strict=False
    )
    if tracked != expected:
        raise LiveBlockedError("fixture 刷新目标必须是规范跟踪目录")
    creator_uid = summary.get("creator_uid")
    download_bvids = summary.get("download_bvids")
    if not isinstance(creator_uid, str) or not isinstance(download_bvids, list):
        raise LiveInconclusiveError("真链摘要缺少 fixture 禁止值身份")
    forbidden = {creator_uid}
    forbidden.update(str(value) for value in download_bvids if isinstance(value, str))
    candidates = validate_candidate_matches_raw(
        run / "results" / "raw-public",
        candidate,
        forbidden_strings=forbidden,
    )
    if set(candidates) != set(drift):
        raise LiveInconclusiveError("fixture 候选与摘要漂移类型不一致")
    return refresh_tracked_fixtures(candidate, tracked)
