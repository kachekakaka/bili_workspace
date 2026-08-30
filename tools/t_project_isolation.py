#!/usr/bin/env python3
"""为项目测试创建、校验并精确清理仓库外临时运行目录。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ID = "bili_workspace"
RUN_MARKER_NAME = ".bili-workspace-test-run.json"
RUN_MARKER_KIND = "bili-workspace-test-run"
RUN_DIRECTORIES = (
    "config",
    "userdata",
    "downloads",
    "runtime",
    "media-tools",
    "home",
    "pycache",
    "tmp",
    "pytest",
    "results",
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


class IsolationError(RuntimeError):
    """隔离目录不满足所有权或路径边界。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _raw_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _is_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _resolved(path: Path | str, label: str, *, must_exist: bool = False) -> Path:
    raw = _raw_absolute(path)
    if raw.exists() and _is_reparse(raw):
        raise IsolationError(f"{label}不能是符号链接或重解析点: {raw}")
    try:
        return raw.resolve(strict=must_exist)
    except OSError as exc:
        raise IsolationError(f"无法解析{label}: {raw}: {exc}") from exc


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _check_external(workspace: Path, test_root: Path) -> None:
    if _is_within(test_root, workspace) or _is_within(workspace, test_root):
        raise IsolationError("测试根与工作区不得互相包含")


def _default_test_root() -> Path:
    configured = os.environ.get("BILI_TEST_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / f"{PROJECT_ID}_test"


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.fullmatch(run_id):
        raise IsolationError(
            "run-id 只能包含字母、数字、点、下划线和连字符，且长度不超过 96"
        )
    if run_id in {".", ".."}:
        raise IsolationError("run-id 不能是相对路径标记")
    return run_id


def _write_marker(path: Path, payload: dict[str, str]) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _read_marker(path: Path) -> dict[str, object]:
    if not path.is_file() or _is_reparse(path):
        raise IsolationError(f"运行目录缺少普通所有权标记: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IsolationError(f"无法读取运行目录所有权标记: {path}") from exc
    if not isinstance(payload, dict):
        raise IsolationError("运行目录所有权标记必须是 JSON 对象")
    return payload


def create_run(
    workspace_root: Path | str,
    test_root: Path | str | None = None,
    run_id: str | None = None,
) -> Path:
    """在仓库外创建一个全新的、带最小所有权标记的运行目录。"""

    workspace = _resolved(workspace_root, "工作区", must_exist=True)
    if not workspace.is_dir():
        raise IsolationError(f"工作区不是目录: {workspace}")

    requested_root = test_root if test_root is not None else _default_test_root()
    raw_test_root = _raw_absolute(requested_root)
    if raw_test_root.exists() and _is_reparse(raw_test_root):
        raise IsolationError(f"测试根不能是符号链接或重解析点: {raw_test_root}")
    raw_test_root.mkdir(parents=True, exist_ok=True)
    test = _resolved(raw_test_root, "测试根", must_exist=True)
    if not test.is_dir():
        raise IsolationError(f"测试根不是目录: {test}")
    _check_external(workspace, test)

    identity = _validate_run_id(run_id or _new_run_id())
    run = test / identity
    if run.exists() or run.is_symlink():
        raise IsolationError(f"运行目录已经存在: {run}")

    run.mkdir()
    try:
        for relative in RUN_DIRECTORIES:
            (run / relative).mkdir(parents=True)
        _write_marker(
            run / RUN_MARKER_NAME,
            {
                "kind": RUN_MARKER_KIND,
                "project_id": PROJECT_ID,
                "workspace_root": str(workspace),
                "test_root": str(test),
                "run_root": str(run),
                "run_id": identity,
                "created_at": _utc_now(),
            },
        )
        return validate_run(run, workspace)
    except Exception:
        if run.is_dir() and not _is_reparse(run):
            shutil.rmtree(run)
        raise


def validate_run(
    run_root: Path | str,
    workspace_root: Path | str,
) -> Path:
    """校验运行目录的所有权、直接父子关系和 containment。"""

    workspace = _resolved(workspace_root, "工作区", must_exist=True)
    run = _resolved(run_root, "运行目录", must_exist=True)
    if not run.is_dir():
        raise IsolationError(f"运行目录不是目录: {run}")

    marker = _read_marker(run / RUN_MARKER_NAME)
    required = {
        "kind": RUN_MARKER_KIND,
        "project_id": PROJECT_ID,
        "workspace_root": str(workspace),
        "run_root": str(run),
        "run_id": run.name,
    }
    for field, expected in required.items():
        if marker.get(field) != expected:
            raise IsolationError(f"运行目录所有权标记字段不匹配: {field}")

    marker_test_root = marker.get("test_root")
    if not isinstance(marker_test_root, str) or not marker_test_root:
        raise IsolationError("运行目录所有权标记缺少 test_root")
    test = _resolved(marker_test_root, "测试根", must_exist=True)
    _check_external(workspace, test)
    if run.parent != test:
        raise IsolationError("运行目录必须是测试根的直接子目录")
    if _is_within(run, workspace) or _is_within(workspace, run):
        raise IsolationError("运行目录与工作区不得互相包含")

    for relative in RUN_DIRECTORIES:
        directory = run / relative
        if not directory.is_dir() or _is_reparse(directory):
            raise IsolationError(f"运行目录缺少安全子目录: {relative}")
        if not _is_within(directory.resolve(strict=True), run):
            raise IsolationError(f"运行子目录越界: {relative}")
    return run


def cleanup_run(
    run_root: Path | str,
    workspace_root: Path | str,
) -> Path:
    """只删除通过所有权校验的精确运行目录，保留测试根和相邻内容。"""

    run = validate_run(run_root, workspace_root)
    test_root = run.parent
    shutil.rmtree(run)
    return test_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="创建隔离运行目录")
    create.add_argument("--workspace-root", type=Path, required=True)
    create.add_argument("--test-root", type=Path)
    create.add_argument("--run-id")

    validate = subparsers.add_parser("validate", help="校验隔离运行目录")
    validate.add_argument("--workspace-root", type=Path, required=True)
    validate.add_argument("--run-root", type=Path, required=True)

    cleanup = subparsers.add_parser("cleanup", help="精确清理隔离运行目录")
    cleanup.add_argument("--workspace-root", type=Path, required=True)
    cleanup.add_argument("--run-root", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "create":
            print(create_run(args.workspace_root, args.test_root, args.run_id))
        elif args.command == "validate":
            print(validate_run(args.run_root, args.workspace_root))
        else:
            cleanup_run(args.run_root, args.workspace_root)
            print(args.run_root)
    except (IsolationError, OSError) as exc:
        print(f"[FAIL] {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
