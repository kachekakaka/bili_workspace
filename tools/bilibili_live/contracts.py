"""真实 Bilibili 测试的标记、路径、摘要与凭据安全合同。"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.t_project_isolation import IsolationError, create_run, validate_run


LIVE_TEST_ID = "T-BILIBILI-LIVE"
LIVE_MARKER_NAME = ".bili-workspace-live-test.json"
LIVE_MARKER_KIND = "bili-workspace-live-test"
LIVE_SUMMARY_SCHEMA_VERSION = 1
CREDENTIAL_RELATIVE_PATH = Path("config") / "bbdown" / "BBDown.data"
SUMMARY_RELATIVE_PATH = Path("results") / "summary.json"
FIXTURE_CANDIDATE_RELATIVE_PATH = Path("results") / "fixture-candidate"
RAW_PUBLIC_RELATIVE_PATH = Path("results") / "raw-public"
MAX_MARKER_BYTES = 64 * 1024
MAX_CREDENTIAL_BYTES = 32 * 1024 * 1024
STALE_AFTER_SECONDS = 72 * 60 * 60
MIN_DOWNLOAD_FREE_BYTES = 5 * 1024**3
MAX_RUN_GROWTH_BYTES = 2 * 1024**3
MAX_RUN_SECONDS = 15 * 60
_BVID_RE = re.compile(r"^BV[0-9A-Za-z]{10}$")


class LiveTestError(RuntimeError):
    """可安全映射到真链结果状态的基础异常。"""

    status = "inconclusive"
    public_message = "真链测试未能形成可判定结果"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.public_message)


class LiveBlockedError(LiveTestError):
    status = "blocked"
    public_message = "真链测试缺少授权、依赖或外部环境"


class LiveFailedError(LiveTestError):
    status = "failed"
    public_message = "真实产品行为或安全合同不符合预期"


class LiveInconclusiveError(LiveTestError):
    status = "inconclusive"
    public_message = "真链运行器中断或真实结构等待审查"


@dataclass(frozen=True, slots=True)
class LiveMarker:
    creator_uid: str
    download_bvids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    size: int
    modified_ns: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _raw_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def is_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and attributes & flag)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or is_reparse(path)


def _is_within(path: Path, parent: Path) -> bool:
    normalized_path = os.path.normcase(str(path.resolve(strict=False)))
    normalized_parent = os.path.normcase(str(parent.resolve(strict=False)))
    try:
        return os.path.commonpath([normalized_path, normalized_parent]) == normalized_parent
    except ValueError:
        return False


def paths_overlap(left: Path, right: Path) -> bool:
    return _is_within(left, right) or _is_within(right, left)


def _reject_existing_reparse_ancestors(path: Path, label: str) -> None:
    candidate = _raw_absolute(path)
    existing: list[Path] = []
    current = candidate
    while True:
        if _path_exists(current):
            existing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for entry in reversed(existing):
        if is_reparse(entry):
            raise LiveBlockedError(f"{label}不得经过符号链接或重解析点")


def _regular_file(path: Path, label: str, *, max_bytes: int) -> Path:
    _reject_existing_reparse_ancestors(path, label)
    if not path.is_file() or path.is_symlink() or is_reparse(path):
        raise LiveBlockedError(f"{label}不是普通文件")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise LiveBlockedError(f"无法读取{label}状态") from exc
    if size <= 0 or size > max_bytes:
        raise LiveBlockedError(f"{label}大小超出允许范围")
    return path.resolve(strict=True)


def resolve_credential_source(value: Path | str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise LiveBlockedError("凭据源数据根必须显式使用绝对路径")
    _reject_existing_reparse_ancestors(raw, "凭据源数据根")
    if not raw.is_dir() or raw.is_symlink() or is_reparse(raw):
        raise LiveBlockedError("凭据源数据根不是已有普通目录")
    return raw.resolve(strict=True)


def load_live_marker(credential_source: Path | str) -> LiveMarker:
    source = resolve_credential_source(credential_source)
    marker_path = _regular_file(
        source / LIVE_MARKER_NAME,
        "真链固定场景",
        max_bytes=MAX_MARKER_BYTES,
    )
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveBlockedError("真链固定场景不是有效 UTF-8 JSON") from exc
    allowed = {"schema_version", "kind", "creator_uid", "download_bvids"}
    if not isinstance(raw, dict) or set(raw) != allowed:
        raise LiveBlockedError("真链固定场景字段集合无效")
    if (
        isinstance(raw.get("schema_version"), bool)
        or raw.get("schema_version") != 1
        or raw.get("kind") != LIVE_MARKER_KIND
    ):
        raise LiveBlockedError("真链固定场景 schema 或 kind 无效")
    uid = raw.get("creator_uid")
    if not isinstance(uid, str) or not uid.isdigit() or int(uid) <= 0:
        raise LiveBlockedError("真链固定场景 creator_uid 必须是正整数字符串")
    canonical_uid = str(int(uid))
    values = raw.get("download_bvids")
    if not isinstance(values, list) or len(values) != 8:
        raise LiveBlockedError("真链固定场景必须恰好包含 8 个 BV")
    if any(not isinstance(value, str) or not _BVID_RE.fullmatch(value) for value in values):
        raise LiveBlockedError("真链固定场景包含非法 BV")
    if len(set(values)) != len(values):
        raise LiveBlockedError("真链固定场景包含重复 BV")
    return LiveMarker(canonical_uid, tuple(values))


def credential_file(credential_source: Path | str) -> Path:
    source = resolve_credential_source(credential_source)
    return _regular_file(
        source / CREDENTIAL_RELATIVE_PATH,
        "BBDown 凭据",
        max_bytes=MAX_CREDENTIAL_BYTES,
    )


def snapshot_file(
    path: Path,
    *,
    label: str = "BBDown 凭据",
    max_bytes: int = MAX_CREDENTIAL_BYTES,
) -> FileSnapshot:
    checked = _regular_file(path, label, max_bytes=max_bytes)
    metadata = checked.stat()
    return FileSnapshot(size=metadata.st_size, modified_ns=metadata.st_mtime_ns)


def validate_test_root(
    value: Path | str,
    *,
    workspace_root: Path | str,
    credential_source: Path | str,
    environ: Mapping[str, str] | None = None,
) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise LiveBlockedError("BILI_TEST_ROOT 必须显式使用绝对路径")
    workspace = Path(workspace_root).resolve(strict=True)
    source = resolve_credential_source(credential_source)
    absolute = _raw_absolute(raw)
    _reject_existing_reparse_ancestors(absolute, "BILI_TEST_ROOT")
    candidate = absolute.resolve(strict=False)
    if paths_overlap(candidate, workspace) or paths_overlap(candidate, source):
        raise LiveBlockedError("BILI_TEST_ROOT 不得与工作区或凭据源互相包含")
    selected_env = os.environ if environ is None else environ
    local_app_data = str(selected_env.get("LOCALAPPDATA", "")).strip()
    if not local_app_data or not Path(local_app_data).expanduser().is_absolute():
        raise LiveBlockedError("无法验证绝对 LOCALAPPDATA 边界")
    local_root = _raw_absolute(local_app_data).resolve(strict=False)
    if _is_within(candidate, local_root):
        raise LiveBlockedError("真链测试根不得位于 LOCALAPPDATA")
    if _path_exists(candidate) and (
        not candidate.is_dir() or candidate.is_symlink() or is_reparse(candidate)
    ):
        raise LiveBlockedError("BILI_TEST_ROOT 不是普通目录")
    return candidate


def create_live_run(
    *,
    workspace_root: Path,
    test_root: Path,
    credential_source: Path,
    marker: LiveMarker,
    impact: str,
    target: str,
    source_identity: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
) -> Path:
    safe_root = validate_test_root(
        test_root,
        workspace_root=workspace_root,
        credential_source=credential_source,
        environ=environ,
    )
    try:
        run = create_run(workspace_root, safe_root, run_id=None)
    except (IsolationError, OSError) as exc:
        raise LiveBlockedError("无法在 BILI_TEST_ROOT 创建安全真链运行") from exc
    summary = {
        "schema_version": LIVE_SUMMARY_SCHEMA_VERSION,
        "test_id": LIVE_TEST_ID,
        "run_id": run.name,
        "status": "inconclusive",
        "stage": "created",
        "started_at": utc_now(),
        "finished_at": None,
        "impact": impact,
        "target": target,
        "source_identity": dict(source_identity),
        "candidate_identity": None,
        "tool_provider": None,
        "creator_uid": marker.creator_uid,
        "download_bvids": list(marker.download_bvids),
        "requested_count": len(marker.download_bvids),
        "completed_count": 0,
        "cancelled_count": 0,
        "failed_count": 0,
        "elapsed_seconds": 0,
        "growth_bytes": 0,
        "fixture_drift": [],
        "stop_reason": "",
        "error_category": "",
        "reason": "",
    }
    write_summary(run, workspace_root, summary, create=True)
    return run


def read_summary(run_root: Path, workspace_root: Path) -> dict[str, Any]:
    run = validate_run(run_root, workspace_root)
    path = run / SUMMARY_RELATIVE_PATH
    if not path.is_file() or path.is_symlink() or is_reparse(path):
        raise LiveInconclusiveError("真链运行缺少普通 summary.json")
    try:
        if path.stat().st_size > 1024 * 1024:
            raise LiveInconclusiveError("真链 summary.json 超过大小上限")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveInconclusiveError("真链 summary.json 无效") from exc
    if (
        not isinstance(raw, dict)
        or type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != LIVE_SUMMARY_SCHEMA_VERSION
        or raw.get("test_id") != LIVE_TEST_ID
        or raw.get("run_id") != run.name
    ):
        raise LiveInconclusiveError("真链 summary.json 身份不匹配")
    return raw


def write_summary(
    run_root: Path,
    workspace_root: Path,
    payload: Mapping[str, Any],
    *,
    create: bool = False,
) -> None:
    run = validate_run(run_root, workspace_root)
    path = run / SUMMARY_RELATIVE_PATH
    if path.is_symlink() or is_reparse(path) or (path.exists() and not path.is_file()):
        raise LiveInconclusiveError("真链 summary.json 路径类型无效")
    value = dict(payload)
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != LIVE_SUMMARY_SCHEMA_VERSION
        or value.get("test_id") != LIVE_TEST_ID
        or value.get("run_id") != run.name
    ):
        raise LiveInconclusiveError("拒绝写入身份不匹配的真链摘要")
    if create and path.exists():
        raise LiveInconclusiveError("真链摘要已经存在")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def update_summary(
    run_root: Path,
    workspace_root: Path,
    **changes: Any,
) -> dict[str, Any]:
    summary = read_summary(run_root, workspace_root)
    summary.update(changes)
    write_summary(run_root, workspace_root, summary)
    return summary


def copy_credentials(
    credential_source: Path,
    run_root: Path,
    workspace_root: Path,
) -> tuple[FileSnapshot, Path]:
    source = credential_file(credential_source)
    before = snapshot_file(source)
    run = validate_run(run_root, workspace_root)
    destination = run / "runtime" / CREDENTIAL_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _path_exists(destination):
        raise LiveInconclusiveError("真链运行的凭据目标已经存在")
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    except OSError as exc:
        raise LiveBlockedError("无法把 BBDown 凭据复制到隔离运行") from exc
    after = snapshot_file(source)
    if before != after:
        raise LiveFailedError("凭据源文件在复制期间发生变化")
    return before, destination


def assert_source_unchanged(
    path: Path,
    expected: FileSnapshot,
    *,
    label: str = "BBDown 凭据",
    max_bytes: int = MAX_CREDENTIAL_BYTES,
) -> None:
    if snapshot_file(path, label=label, max_bytes=max_bytes) != expected:
        raise LiveFailedError(f"{label}在真链运行期间发生变化")


def iter_run_files(run_root: Path, workspace_root: Path) -> Iterable[Path]:
    run = validate_run(run_root, workspace_root)
    pending = [run]
    while pending:
        directory = pending.pop()
        if directory.is_symlink() or is_reparse(directory) or not directory.is_dir():
            raise LiveInconclusiveError("真链运行目录包含不安全的目录类型")
        try:
            entries = list(directory.iterdir())
        except OSError as exc:
            raise LiveInconclusiveError("无法枚举真链运行目录") from exc
        for entry in entries:
            if entry.is_symlink() or is_reparse(entry):
                raise LiveInconclusiveError("真链运行目录包含重解析点")
            if entry.is_dir():
                pending.append(entry)
            elif entry.is_file():
                yield entry
            else:
                raise LiveInconclusiveError("真链运行目录包含非常规文件")


def run_size_bytes(run_root: Path, workspace_root: Path) -> int:
    total = 0
    for path in iter_run_files(run_root, workspace_root):
        try:
            total += path.stat().st_size
        except OSError as exc:
            raise LiveInconclusiveError("无法统计真链运行大小") from exc
    return total


def remove_run_credentials(run_root: Path, workspace_root: Path) -> int:
    run = validate_run(run_root, workspace_root)
    targets = [
        path
        for path in iter_run_files(run, workspace_root)
        if path.name.casefold() == "bbdown.data"
    ]
    removed = 0
    for path in targets:
        if not _is_within(path.resolve(strict=True), run):
            raise LiveInconclusiveError("凭据副本路径越出真链运行")
        try:
            path.unlink()
        except OSError as exc:
            raise LiveInconclusiveError("成功运行后无法删除凭据副本") from exc
        removed += 1
    if any(
        path.name.casefold() == "bbdown.data"
        for path in iter_run_files(run, workspace_root)
    ):
        raise LiveInconclusiveError("成功运行后仍残留凭据副本")
    return removed
