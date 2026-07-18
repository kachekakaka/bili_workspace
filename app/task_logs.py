from __future__ import annotations

import os
import re
import shutil
import threading
from pathlib import Path

from app.constants import MAX_LOG_FILE_BYTES
from app.path_safety import resolve_under
from app.paths import ROOT
from app.progress import clean_terminal_text

_TASK_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_LOCK = threading.RLock()
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(SESSDATA\s*[=:]\s*)[^;\s\"']+"), r"\1***"),
    (re.compile(r"(?i)(bili_jct\s*[=:]\s*)[^;\s\"']+"), r"\1***"),
    (re.compile(r"(?i)(DedeUserID\s*[=:]\s*)[^;\s\"']+"), r"\1***"),
    (re.compile(r"(?i)(Cookie\s*:\s*)[^\r\n]+"), r"\1***"),
    (re.compile(r"(?i)(Authorization\s*:\s*)[^\r\n]+"), r"\1***"),
)


def validate_task_id(task_id: str) -> str:
    value = str(task_id or "").strip().lower()
    if not _TASK_ID_RE.fullmatch(value):
        raise ValueError("任务编号无效")
    return value


def redact_sensitive(text: str) -> str:
    value = clean_terminal_text(text).replace("\r\n", "\n").replace("\r", "\n")
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _under_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _configured_log_root(download_dir: Path) -> Path:
    download_root = Path(download_dir).resolve()
    raw_userdata = os.getenv("BILI_USERDATA_DIR", "").strip()
    if raw_userdata:
        candidate = Path(raw_userdata).expanduser()
        if candidate.is_absolute():
            return (candidate.resolve() / "task_logs").resolve()
        # Relative defaults belong to the repository runtime. Standalone queues
        # created against isolated temporary directories keep their logs beside
        # that temporary download root instead of leaking into project userdata.
        if _under_project(download_root):
            return ((ROOT / candidate).resolve() / "task_logs").resolve()
        return (download_root / ".bili_logs").resolve()
    raw_database = os.getenv("BILI_DATABASE_PATH", "").strip()
    if raw_database:
        candidate = Path(raw_database).expanduser()
        if candidate.is_absolute():
            return (candidate.resolve().parent / "task_logs").resolve()
        if _under_project(download_root):
            return ((ROOT / candidate).resolve().parent / "task_logs").resolve()
    return (download_root / ".bili_logs").resolve()


def task_log_path(download_dir: Path, task_id: str) -> Path:
    safe_id = validate_task_id(task_id)
    download_root = Path(download_dir).resolve()
    legacy = resolve_under(download_root, f".bili_logs/{safe_id}.log")
    target = resolve_under(_configured_log_root(download_root), f"{safe_id}.log")
    if target != legacy and not target.exists() and legacy.exists():
        if legacy.is_symlink() or not legacy.is_file():
            raise ValueError("旧版任务日志类型异常")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(legacy, target)
        except OSError:
            shutil.copy2(legacy, target)
            legacy.unlink()
        try:
            legacy.parent.rmdir()
        except OSError:
            pass
    return target


def _truncate_if_needed(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= MAX_LOG_FILE_BYTES:
        return
    keep = max(64 * 1024, int(MAX_LOG_FILE_BYTES * 0.70))
    with path.open("rb") as handle:
        handle.seek(max(0, size - keep), os.SEEK_SET)
        tail = handle.read()
    marker = "[日志已截断，仅保留最近内容]\n".encode()
    with path.open("wb") as handle:
        handle.write(marker)
        handle.write(tail)
        handle.flush()
        os.fsync(handle.fileno())


def append_task_log(download_dir: Path, task_id: str, text: str) -> tuple[str, int]:
    cleaned = redact_sensitive(text)
    if not cleaned:
        path = task_log_path(download_dir, task_id)
        return "", path.stat().st_size if path.exists() else 0
    path = task_log_path(download_dir, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(cleaned)
            handle.flush()
        _truncate_if_needed(path)
        size = path.stat().st_size
    return cleaned, size


def read_task_log(
    download_dir: Path,
    task_id: str,
    *,
    tail_chars: int | None = None,
) -> dict[str, object]:
    path = task_log_path(download_dir, task_id)
    if not path.is_file() or path.is_symlink():
        return {"text": "", "size": 0, "truncated": False}
    with _LOCK:
        size = path.stat().st_size
        if tail_chars is None:
            data = path.read_bytes()
            text = data.decode("utf-8", errors="replace")
            return {"text": text, "size": size, "truncated": False}
        limit = max(1, int(tail_chars))
        read_bytes = min(size, max(4096, limit * 4))
        with path.open("rb") as handle:
            handle.seek(max(0, size - read_bytes), os.SEEK_SET)
            data = handle.read()
        text = data.decode("utf-8", errors="replace")
        truncated = size > read_bytes or len(text) > limit
        return {"text": text[-limit:], "size": size, "truncated": truncated}


def delete_task_log(download_dir: Path, task_id: str) -> bool:
    """Delete one task log without accepting an arbitrary filesystem path."""
    path = task_log_path(download_dir, task_id)
    with _LOCK:
        if not path.exists():
            return False
        if path.is_symlink() or not path.is_file():
            raise ValueError("任务日志类型异常")
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
    return True
