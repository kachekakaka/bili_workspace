from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


PROJECT_ID = "bili_workspace"
ROOT_MARKER_NAME = ".bili-workspace-test-root.json"
RUN_MARKER_NAME = ".bili-workspace-test-run.json"
RESULT_RELATIVE_PATH = Path("results") / "result.json"
ROOT_MARKER_SCHEMA_VERSION = 1
LEGACY_RUN_SCHEMA_VERSION = 1
RUN_SCHEMA_VERSION = 2
RESULT_SCHEMA_VERSION = 2
TEST_ID = "T-PROJECT"
RESULT_STATUSES = (
    "passed",
    "failed",
    "blocked",
    "inconclusive",
    "not_run",
)
TEST_ID_PATTERN = re.compile(r"^T-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
GC_PLAN_SCHEMA_VERSION = 1
GC_ORDINARY_CATEGORY = "ordinary"
GC_LEGACY_CATEGORY = "legacy_or_abandoned"
GC_CATEGORIES = (GC_ORDINARY_CATEGORY, GC_LEGACY_CATEGORY)
GC_SHORT_RETENTION = timedelta(hours=72)
GC_LONG_RETENTION = timedelta(days=7)
RUN_DIRECTORIES = (
    "runtime",
    "media",
    "config",
    "userdata",
    "downloads",
    "tmp",
    "pycache",
    "home",
    "results",
)
PATH_MARKER_FIELDS = {"workspace_root", "test_root", "run_root"}
REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class IsolationError(RuntimeError):
    """Raised when a T-PROJECT ownership or containment rule is violated."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_now(value: datetime | None) -> datetime:
    selected = value or datetime.now(UTC)
    if selected.tzinfo is None:
        raise IsolationError("GC 当前时间必须包含时区")
    return selected.astimezone(UTC)


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IsolationError(f"{label}缺少有效 UTC 时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IsolationError(f"{label}不是有效 ISO-8601 时间") from exc
    if parsed.tzinfo is None:
        raise IsolationError(f"{label}必须包含时区")
    return parsed.astimezone(UTC)


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_external(test_root: Path, workspace_root: Path) -> None:
    if _is_within(test_root, workspace_root) or _is_within(workspace_root, test_root):
        raise IsolationError(
            f"测试根目录与仓库不得相同或互相包含: {test_root} / {workspace_root}"
        )


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise IsolationError(f"无法检查路径重解析点属性: {path}") from exc
    return path.is_symlink() or bool(attributes & REPARSE_POINT_ATTRIBUTE)


def _assert_not_reparse_point(path: Path | str, label: str) -> None:
    candidate = _lexical_absolute(path)
    for current in (candidate, *candidate.parents):
        if _is_reparse_point(current):
            raise IsolationError(
                f"{label}路径不得经过符号链接或重解析点: {current}"
            )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IsolationError(f"无法读取{label}: {path}") from exc
    if not isinstance(value, dict):
        raise IsolationError(f"{label}顶层必须是 JSON 对象: {path}")
    return value


def _marker_value_matches(key: str, actual: Any, expected: Any) -> bool:
    if key not in PATH_MARKER_FIELDS:
        return actual == expected
    if not isinstance(actual, str) or not actual:
        return False
    return os.path.normcase(str(_resolved(actual))) == os.path.normcase(
        str(_resolved(expected))
    )


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def default_test_root() -> Path:
    configured = os.getenv("BILI_TEST_ROOT", "").strip()
    if configured:
        return _lexical_absolute(configured)
    if os.name == "nt":
        return Path(r"D:\Projects\python\bili_workspace_test")
    return _resolved(Path(tempfile.gettempdir()) / "bili_workspace_test")


def _validate_root_marker(test_root: Path, workspace_root: Path) -> dict[str, Any]:
    marker_path = test_root / ROOT_MARKER_NAME
    if not marker_path.is_file():
        raise IsolationError(f"已有测试根目录缺少所有权标记: {marker_path}")
    _assert_not_reparse_point(marker_path, "测试根目录所有权标记")
    marker = _read_json(marker_path, "测试根目录所有权标记")
    expected = {
        "schema_version": ROOT_MARKER_SCHEMA_VERSION,
        "kind": "bili-workspace-test-root",
        "project_id": PROJECT_ID,
        "workspace_root": str(workspace_root),
        "test_root": str(test_root),
    }
    for key, value in expected.items():
        if not _marker_value_matches(key, marker.get(key), value):
            raise IsolationError(f"测试根目录所有权标记字段不匹配: {key}")
    if not isinstance(marker.get("created_at"), str) or not marker[
        "created_at"
    ].strip():
        raise IsolationError("测试根目录所有权标记缺少 created_at")
    return marker


def ensure_test_root(
    workspace_root: Path | str,
    test_root: Path | str | None = None,
) -> Path:
    raw_workspace = _lexical_absolute(workspace_root)
    raw_root = (
        _lexical_absolute(test_root) if test_root is not None else default_test_root()
    )
    _assert_not_reparse_point(raw_workspace, "仓库根目录")
    _assert_not_reparse_point(raw_root, "测试根目录")
    workspace = _resolved(raw_workspace)
    root = _resolved(raw_root)
    _assert_external(root, workspace)

    if root.exists():
        if not root.is_dir():
            raise IsolationError(f"测试根目录不是目录: {root}")
        _validate_root_marker(root, workspace)
        return root

    root.mkdir(parents=True, exist_ok=False)
    _write_json_atomic(
        root / ROOT_MARKER_NAME,
        {
            "schema_version": ROOT_MARKER_SCHEMA_VERSION,
            "kind": "bili-workspace-test-root",
            "project_id": PROJECT_ID,
            "workspace_root": str(workspace),
            "test_root": str(root),
            "created_at": _utc_now(),
        },
    )
    return root


def _open_test_root_read_only(
    workspace_root: Path | str,
    test_root: Path | str | None = None,
) -> tuple[Path, Path]:
    raw_workspace = _lexical_absolute(workspace_root)
    raw_root = (
        _lexical_absolute(test_root) if test_root is not None else default_test_root()
    )
    _assert_not_reparse_point(raw_workspace, "仓库根目录")
    _assert_not_reparse_point(raw_root, "测试根目录")
    workspace = _resolved(raw_workspace)
    root = _resolved(raw_root)
    _assert_external(root, workspace)
    if not root.is_dir():
        raise IsolationError(f"测试根目录不存在或不是目录: {root}")
    _validate_root_marker(root, workspace)
    return workspace, root


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:12]}"


def _validate_run_id(run_id: str) -> str:
    if run_id in {".", ".."} or not RUN_ID_PATTERN.fullmatch(run_id):
        raise IsolationError(
            "run-id 只能包含 1–80 个 ASCII 字母、数字、点、下划线或连字符，"
            "且必须以字母或数字开头"
        )
    return run_id


def create_run(
    workspace_root: Path | str,
    test_root: Path | str | None = None,
    run_id: str | None = None,
) -> Path:
    root = ensure_test_root(workspace_root, test_root)
    workspace = _resolved(workspace_root)
    selected_id = _validate_run_id(run_id or _new_run_id())
    run_root = root / selected_id
    run_root.mkdir(exist_ok=False)
    _write_json_atomic(
        run_root / RUN_MARKER_NAME,
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "kind": "bili-workspace-test-run",
            "project_id": PROJECT_ID,
            "test_id": TEST_ID,
            "workspace_root": str(workspace),
            "test_root": str(root),
            "run_root": str(run_root),
            "run_id": selected_id,
            "created_at": _utc_now(),
        },
    )
    for name in RUN_DIRECTORIES:
        (run_root / name).mkdir()
    record_result(
        run_root,
        workspace,
        "inconclusive",
        message="验证已创建，但尚未写入最终结果。",
        finalized=False,
    )
    return run_root


def _validate_owned_run(
    run_root: Path | str,
    workspace_root: Path | str,
    expected_test_id: str | None = None,
    *,
    require_layout: bool = True,
) -> tuple[Path, dict[str, Any], str]:
    raw_workspace = _lexical_absolute(workspace_root)
    raw_run = _lexical_absolute(run_root)
    _assert_not_reparse_point(raw_workspace, "仓库根目录")
    _assert_not_reparse_point(raw_run, "测试运行目录")
    workspace = _resolved(raw_workspace)
    run = _resolved(raw_run)
    if not run.is_dir():
        raise IsolationError(f"测试运行目录不存在: {run}")

    marker_path = run / RUN_MARKER_NAME
    if not marker_path.is_file():
        raise IsolationError(f"测试运行目录缺少所有权标记: {marker_path}")
    _assert_not_reparse_point(marker_path, "测试运行所有权标记")
    marker = _read_json(marker_path, "测试运行所有权标记")
    try:
        raw_test_root = _lexical_absolute(str(marker["test_root"]))
        _assert_not_reparse_point(raw_test_root, "测试根目录")
        test_root = _resolved(raw_test_root)
    except (KeyError, TypeError, ValueError) as exc:
        raise IsolationError("测试运行所有权标记缺少有效 test_root") from exc
    _assert_external(test_root, workspace)
    _validate_root_marker(test_root, workspace)
    if run.parent != test_root:
        raise IsolationError("测试运行目录必须是测试根目录的直接子目录")

    schema_version = marker.get("schema_version")
    if schema_version not in {LEGACY_RUN_SCHEMA_VERSION, RUN_SCHEMA_VERSION}:
        raise IsolationError(
            f"测试运行所有权标记使用不支持的 schema_version: {schema_version}"
        )
    expected = {
        "kind": "bili-workspace-test-run",
        "project_id": PROJECT_ID,
        "workspace_root": str(workspace),
        "test_root": str(test_root),
        "run_root": str(run),
        "run_id": run.name,
    }
    for key, value in expected.items():
        if not _marker_value_matches(key, marker.get(key), value):
            raise IsolationError(f"测试运行所有权标记字段不匹配: {key}")
    if schema_version == LEGACY_RUN_SCHEMA_VERSION:
        test_id = TEST_ID
    else:
        test_id = marker.get("test_id")
        if not isinstance(test_id, str) or not TEST_ID_PATTERN.fullmatch(test_id):
            raise IsolationError("测试运行所有权标记缺少有效 test_id")
    if expected_test_id is not None and test_id != expected_test_id:
        raise IsolationError("测试运行所有权标记字段不匹配: test_id")
    if not isinstance(marker.get("created_at"), str) or not marker[
        "created_at"
    ].strip():
        raise IsolationError("测试运行所有权标记缺少 created_at")
    _validate_run_id(run.name)
    for child in run.iterdir():
        _assert_not_reparse_point(child, "测试运行直接子项")
    if require_layout:
        for name in RUN_DIRECTORIES:
            child = run / name
            if not child.is_dir():
                raise IsolationError(f"测试运行子目录缺失或不是普通目录: {child}")
    return run, marker, test_id


def validate_run(
    run_root: Path | str,
    workspace_root: Path | str,
) -> Path:
    run, _, _ = _validate_owned_run(run_root, workspace_root, TEST_ID)
    return run


def record_result(
    run_root: Path | str,
    workspace_root: Path | str,
    status: str,
    *,
    exit_code: int | None = None,
    message: str = "",
    finalized: bool = True,
) -> Path:
    if status not in RESULT_STATUSES:
        raise IsolationError(f"不支持的验证状态: {status}")
    run = validate_run(run_root, workspace_root)
    marker = _read_json(run / RUN_MARKER_NAME, "测试运行所有权标记")
    result_path = run / RESULT_RELATIVE_PATH
    schema_version = marker["schema_version"]
    timestamp = _utc_now()
    result: dict[str, Any] = {
        "schema_version": schema_version,
        "project_id": PROJECT_ID,
        "run_id": marker["run_id"],
        "status": status,
        "updated_at": timestamp,
        "finalized_at": timestamp if finalized else None,
        "workspace_root": marker["workspace_root"],
        "run_root": str(run),
    }
    if schema_version == RESULT_SCHEMA_VERSION:
        result["test_id"] = TEST_ID
    if exit_code is not None:
        result["exit_code"] = exit_code
    if message:
        result["message"] = message
    _write_json_atomic(result_path, result)
    return result_path


def _sha256_file(path: Path, label: str) -> str:
    _assert_not_reparse_point(path, label)
    if not path.is_file():
        raise IsolationError(f"{label}不是普通文件: {path}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise IsolationError(f"无法读取{label}: {path}") from exc
    return hashlib.sha256(payload).hexdigest()


def _validate_result(
    run: Path,
    workspace: Path,
    marker: dict[str, Any],
    test_id: str,
) -> tuple[dict[str, Any], datetime, datetime | None]:
    result_path = run / RESULT_RELATIVE_PATH
    _assert_not_reparse_point(result_path, "测试结果文件")
    if not result_path.is_file():
        raise IsolationError(f"测试运行缺少结果文件: {result_path}")
    result = _read_json(result_path, "测试结果文件")
    schema_version = marker["schema_version"]
    expected = {
        "schema_version": schema_version,
        "project_id": PROJECT_ID,
        "run_id": marker["run_id"],
        "workspace_root": str(workspace),
        "run_root": str(run),
    }
    for key, value in expected.items():
        if not _marker_value_matches(key, result.get(key), value):
            raise IsolationError(f"测试结果字段不匹配: {key}")
    if schema_version == RESULT_SCHEMA_VERSION and result.get("test_id") != test_id:
        raise IsolationError("测试结果字段不匹配: test_id")
    status = result.get("status")
    if status not in RESULT_STATUSES:
        raise IsolationError(f"测试结果使用非法状态: {status}")
    updated_at = _parse_utc(result.get("updated_at"), "测试结果 updated_at")
    raw_finalized = result.get("finalized_at")
    finalized_at = (
        _parse_utc(raw_finalized, "测试结果 finalized_at")
        if raw_finalized is not None
        else None
    )
    if finalized_at is not None and finalized_at != updated_at:
        raise IsolationError("测试结果 finalized_at 必须与最终 updated_at 一致")
    return result, updated_at, finalized_at


def _gc_candidate(
    run_root: Path,
    workspace: Path,
    now: datetime,
) -> dict[str, Any] | None:
    run, marker, test_id = _validate_owned_run(
        run_root,
        workspace,
        require_layout=False,
    )
    result_path = run / RESULT_RELATIVE_PATH
    _assert_not_reparse_point(result_path, "测试结果文件")
    has_result = result_path.exists()
    updated_at: datetime | None = None
    finalized_at: datetime | None = None
    if not has_result:
        category = GC_LEGACY_CATEGORY
        evidence_state = "missing_result"
        status = "unknown"
        eligible_at = (
            _parse_utc(marker.get("created_at"), "测试运行 created_at")
            + GC_LONG_RETENTION
        )
        result_sha256: str | None = None
    else:
        result, updated_at, finalized_at = _validate_result(
            run,
            workspace,
            marker,
            test_id,
        )
        status = str(result["status"])
        result_sha256 = _sha256_file(result_path, "测试结果文件")
    if has_result and finalized_at is None:
        if updated_at is None:
            raise IsolationError("GC 无法确定未终结结果的更新时间")
        category = GC_LEGACY_CATEGORY
        evidence_state = "missing_finalized_at"
        eligible_at = updated_at + GC_LONG_RETENTION
    elif has_result:
        category = GC_ORDINARY_CATEGORY
        evidence_state = "finalized"
        retention = (
            GC_SHORT_RETENTION
            if status in {"passed", "not_run"}
            else GC_LONG_RETENTION
        )
        eligible_at = finalized_at + retention
    if now < eligible_at:
        return None
    return {
        "run_id": marker["run_id"],
        "run_root": str(run),
        "test_id": test_id,
        "status": status,
        "category": category,
        "evidence_state": evidence_state,
        "eligible_at": _format_utc(eligible_at),
        "run_marker_sha256": _sha256_file(
            run / RUN_MARKER_NAME,
            "测试运行所有权标记",
        ),
        "result_sha256": result_sha256,
    }


def _gc_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_gc_plan(
    workspace_root: Path | str,
    test_root: Path | str | None = None,
    *,
    run_ids: list[str] | tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    workspace, root = _open_test_root_read_only(workspace_root, test_root)
    selected_now = _normalize_now(now)
    requested = None if run_ids is None else list(run_ids)
    if requested is not None:
        if len(set(requested)) != len(requested):
            raise IsolationError("GC 计划不得重复指定 run-id")
        paths = [root / _validate_run_id(run_id) for run_id in requested]
    else:
        paths = sorted(path for path in root.iterdir() if path.is_dir())

    candidates: list[dict[str, Any]] = []
    for path in paths:
        candidate = _gc_candidate(path, workspace, selected_now)
        if candidate is None:
            if requested is not None:
                raise IsolationError(f"测试运行尚未达到清理期限: {path.name}")
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: str(item["run_id"]))
    identity = {
        "schema_version": GC_PLAN_SCHEMA_VERSION,
        "kind": "bili-workspace-test-gc-plan",
        "project_id": PROJECT_ID,
        "workspace_root": str(workspace),
        "test_root": str(root),
        "test_root_marker_sha256": _sha256_file(
            root / ROOT_MARKER_NAME,
            "测试根目录所有权标记",
        ),
        "candidates": candidates,
    }
    return {
        **identity,
        "generated_at": _format_utc(selected_now),
        "plan_digest": _gc_digest(identity),
    }


def apply_gc_plan(
    workspace_root: Path | str,
    test_root: Path | str | None,
    expected_candidates: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    expected_digest: str,
    *,
    allow_legacy_or_abandoned: bool = False,
    now: datetime | None = None,
) -> tuple[str, ...]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise IsolationError("GC 预期计划摘要必须是 64 位小写 SHA-256")
    normalized_candidates: list[tuple[str, str]] = []
    for run_id, category in expected_candidates:
        normalized_run_id = _validate_run_id(run_id)
        if category not in GC_CATEGORIES:
            raise IsolationError(f"不支持的 GC 候选分类: {category}")
        normalized_candidates.append((normalized_run_id, category))
    if not normalized_candidates:
        raise IsolationError("GC apply 必须至少包含一个到期候选")
    if len({run_id for run_id, _ in normalized_candidates}) != len(
        normalized_candidates
    ):
        raise IsolationError("GC apply 不得重复指定 run-id")
    plan = build_gc_plan(
        workspace_root,
        test_root,
        run_ids=[run_id for run_id, _ in normalized_candidates],
        now=now,
    )
    if plan["plan_digest"] != expected_digest:
        raise IsolationError("GC 计划已漂移，必须重新生成 dry-run 并确认")
    candidates = plan["candidates"]
    actual_candidates = [
        (str(item["run_id"]), str(item["category"])) for item in candidates
    ]
    if sorted(normalized_candidates) != sorted(actual_candidates):
        raise IsolationError("GC 候选分类已漂移，必须重新生成 dry-run 并确认")
    if (
        any(item["category"] == GC_LEGACY_CATEGORY for item in candidates)
        and not allow_legacy_or_abandoned
    ):
        raise IsolationError(
            "legacy_or_abandoned 候选需要显式 --allow-legacy-or-abandoned"
        )

    deleted: list[str] = []
    for item in candidates:
        run = _resolved(str(item["run_root"]))
        _assert_not_reparse_point(run, "GC 目标运行目录")
        if run.parent != _resolved(str(plan["test_root"])):
            raise IsolationError("GC 目标必须是测试根目录的直接子目录")
        shutil.rmtree(run)
        deleted.append(str(item["run_id"]))
    return tuple(deleted)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理 T-PROJECT 仓库外隔离运行目录")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="创建带所有权标记的新运行目录")
    create.add_argument("--workspace-root", type=Path, required=True)
    create.add_argument("--test-root", type=Path)
    create.add_argument("--run-id")

    validate = subparsers.add_parser("validate", help="验证既有运行目录的边界和标记")
    validate.add_argument("--workspace-root", type=Path, required=True)
    validate.add_argument("--run-root", type=Path, required=True)

    record = subparsers.add_parser("record", help="原子写入运行结果")
    record.add_argument("--workspace-root", type=Path, required=True)
    record.add_argument("--run-root", type=Path, required=True)
    record.add_argument("--status", choices=RESULT_STATUSES, required=True)
    record.add_argument("--exit-code", type=int)
    record.add_argument("--message", default="")

    gc_plan = subparsers.add_parser("gc-plan", help="只读生成到期运行精确清理计划")
    gc_plan.add_argument("--workspace-root", type=Path, required=True)
    gc_plan.add_argument("--test-root", type=Path)
    gc_plan.add_argument("--run-id", action="append", dest="run_ids")

    gc_apply = subparsers.add_parser("gc-apply", help="按已确认摘要删除精确到期运行")
    gc_apply.add_argument("--workspace-root", type=Path, required=True)
    gc_apply.add_argument("--test-root", type=Path)
    gc_apply.add_argument(
        "--candidate",
        action="append",
        dest="candidates",
        required=True,
        metavar="RUN_ID:CATEGORY",
        help="逐项指定 dry-run 中的 run-id 与分类",
    )
    gc_apply.add_argument("--expected-digest", required=True)
    gc_apply.add_argument("--allow-legacy-or-abandoned", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            print(create_run(args.workspace_root, args.test_root, args.run_id))
        elif args.command == "validate":
            print(validate_run(args.run_root, args.workspace_root))
        elif args.command == "record":
            record_result(
                args.run_root,
                args.workspace_root,
                args.status,
                exit_code=args.exit_code,
                message=args.message,
            )
        elif args.command == "gc-plan":
            print(
                json.dumps(
                    build_gc_plan(
                        args.workspace_root,
                        args.test_root,
                        run_ids=args.run_ids,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            expected_candidates: list[tuple[str, str]] = []
            for raw_candidate in args.candidates:
                run_id, separator, category = raw_candidate.rpartition(":")
                if not separator:
                    raise IsolationError(
                        "GC 候选必须使用 RUN_ID:CATEGORY 格式"
                    )
                expected_candidates.append((run_id, category))
            deleted = apply_gc_plan(
                args.workspace_root,
                args.test_root,
                expected_candidates,
                args.expected_digest,
                allow_legacy_or_abandoned=args.allow_legacy_or_abandoned,
            )
            print(json.dumps({"deleted_run_ids": deleted}, ensure_ascii=False))
    except IsolationError as exc:
        print(f"[阻断] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
