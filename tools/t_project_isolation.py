from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import UTC, datetime
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
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
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


class IsolationError(RuntimeError):
    """Raised when a T-PROJECT ownership or containment rule is violated."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def _assert_not_symlink(path: Path | str, label: str) -> None:
    candidate = _lexical_absolute(path)
    for current in (candidate, *candidate.parents):
        if current.exists() and current.is_symlink():
            raise IsolationError(f"{label}路径不得经过符号链接: {current}")


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
    if marker_path.is_symlink():
        raise IsolationError(f"测试根目录所有权标记不得是符号链接: {marker_path}")
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
    _assert_not_symlink(raw_workspace, "仓库根目录")
    _assert_not_symlink(raw_root, "测试根目录")
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
    )
    return run_root


def validate_run(
    run_root: Path | str,
    workspace_root: Path | str,
) -> Path:
    raw_workspace = _lexical_absolute(workspace_root)
    raw_run = _lexical_absolute(run_root)
    _assert_not_symlink(raw_workspace, "仓库根目录")
    _assert_not_symlink(raw_run, "测试运行目录")
    workspace = _resolved(raw_workspace)
    run = _resolved(raw_run)
    if not run.is_dir():
        raise IsolationError(f"测试运行目录不存在: {run}")

    marker_path = run / RUN_MARKER_NAME
    if not marker_path.is_file():
        raise IsolationError(f"测试运行目录缺少所有权标记: {marker_path}")
    if marker_path.is_symlink():
        raise IsolationError(f"测试运行所有权标记不得是符号链接: {marker_path}")
    marker = _read_json(marker_path, "测试运行所有权标记")
    try:
        raw_test_root = _lexical_absolute(str(marker["test_root"]))
        _assert_not_symlink(raw_test_root, "测试根目录")
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
    if schema_version == RUN_SCHEMA_VERSION and marker.get("test_id") != TEST_ID:
        raise IsolationError("测试运行所有权标记字段不匹配: test_id")
    if not isinstance(marker.get("created_at"), str) or not marker[
        "created_at"
    ].strip():
        raise IsolationError("测试运行所有权标记缺少 created_at")
    _validate_run_id(run.name)
    for name in RUN_DIRECTORIES:
        child = run / name
        if not child.is_dir() or child.is_symlink():
            raise IsolationError(f"测试运行子目录缺失或不是普通目录: {child}")
    return run


def record_result(
    run_root: Path | str,
    workspace_root: Path | str,
    status: str,
    *,
    exit_code: int | None = None,
    message: str = "",
) -> Path:
    if status not in RESULT_STATUSES:
        raise IsolationError(f"不支持的验证状态: {status}")
    run = validate_run(run_root, workspace_root)
    marker = _read_json(run / RUN_MARKER_NAME, "测试运行所有权标记")
    result_path = run / RESULT_RELATIVE_PATH
    schema_version = marker["schema_version"]
    result: dict[str, Any] = {
        "schema_version": schema_version,
        "project_id": PROJECT_ID,
        "run_id": marker["run_id"],
        "status": status,
        "updated_at": _utc_now(),
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            print(create_run(args.workspace_root, args.test_root, args.run_id))
        elif args.command == "validate":
            print(validate_run(args.run_root, args.workspace_root))
        else:
            record_result(
                args.run_root,
                args.workspace_root,
                args.status,
                exit_code=args.exit_code,
                message=args.message,
            )
    except IsolationError as exc:
        print(f"[阻断] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
