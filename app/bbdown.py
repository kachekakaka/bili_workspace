from __future__ import annotations

import codecs
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import AppConfig
from app.constants import MAX_INFO_OUTPUT_CHARS, MAX_LOG_TAIL_CHARS
from app.progress import BbdownProgressParser, ProgressEvent

_CREDENTIAL_FILE = "BBDown.data"
_SYNC_LOCK = threading.Lock()


@dataclass
class BbdownResult:
    returncode: int
    stdout: str
    stderr: str
    argv: list[str]
    timed_out: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    @property
    def combined(self) -> str:
        values = [value for value in (self.stdout, self.stderr) if value]
        return "\n".join(values)

    @property
    def tail(self) -> str:
        return self.combined.strip()[-MAX_LOG_TAIL_CHARS:]


class _TailBuffer:
    def __init__(self, max_chars: int = MAX_LOG_TAIL_CHARS):
        self.max_chars = max_chars
        self._parts: deque[str] = deque()
        self._size = 0
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        if not text:
            return
        text = text[-self.max_chars :]
        with self._lock:
            self._parts.append(text)
            self._size += len(text)
            while self._parts and self._size > self.max_chars:
                removed = self._parts.popleft()
                self._size -= len(removed)

    def text(self) -> str:
        with self._lock:
            return "".join(self._parts)[-self.max_chars :]


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


class _EncodingProbe:
    """Detect whether BBDown console output is UTF-8 or ANSI (GBK).

    BBDown on Windows writes console output with the system ANSI code page
    (GBK) when stdout is redirected.  A plain UTF-8 decoder would turn every
    Chinese character into U+FFFD.  Output encoding is consistent for one
    process, so a bounded prefix decides the codec before decoding starts.
    """

    _LIMIT = 32 * 1024

    def __init__(self) -> None:
        self._buffer = b""
        self._decided: str | None = None
        self._failed_at_tail = False

    def feed(self, chunk: bytes) -> tuple[str, bytes] | None:
        if self._decided is not None:
            return self._decided, b""
        self._buffer += chunk
        if not any(byte >= 0x80 for byte in self._buffer):
            if len(self._buffer) >= 4096:
                self._decided = "utf-8"
                return self._decided, self._buffer
            return None
        try:
            self._buffer.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            if len(self._buffer) - exc.start <= 3 and len(self._buffer) < self._LIMIT:
                # A UTF-8 multi-byte sequence may be cut at the chunk boundary.
                self._failed_at_tail = True
                return None
            self._decided = "gbk"
        else:
            self._decided = "utf-8"
        return self._decided, self._buffer

    def finish(self) -> str:
        if self._decided is not None:
            return self._decided
        # Never decided: pure ASCII, or a trailing sequence that stayed
        # incomplete up to the stream end.  Real BBDown output is ANSI/GBK,
        # so a failed tail favours GBK; pure ASCII is identical in both.
        return "gbk" if self._failed_at_tail else "utf-8"


def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    probe = _EncodingProbe()
    decision = probe.feed(data)
    if decision is None:
        return data.decode(probe.finish(), errors="replace")
    encoding, payload = decision
    return payload.decode(encoding, errors="replace")


def sync_credentials_to_tool_dir(credential_dir: Path, tool_dir: Path) -> None:
    """Keep BBDown.data next to BBDown.exe before every invocation.

    BBDown 1.6.3 reads its cookie only from its own executable directory.
    The launcher keeps the binary in a read-only resource directory while
    credentials live in the data root, so credentials must be mirrored
    before each run: copy when present, remove stale copies when absent.
    Failures are tolerated (logged to stderr) so downloads are not blocked.
    """
    source = Path(credential_dir).resolve() / _CREDENTIAL_FILE
    target_dir = Path(tool_dir).resolve()
    target = target_dir / _CREDENTIAL_FILE
    if target_dir == source.parent:
        return
    with _SYNC_LOCK:
        try:
            if source.is_file() and not source.is_symlink():
                temporary = target_dir / f".{_CREDENTIAL_FILE}.{uuid.uuid4().hex}.tmp"
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
            elif target.is_file() and not target.is_symlink():
                target.unlink()
        except OSError as exc:
            print(f"[bbdown] 凭据同步失败（忽略并继续）: {exc}", file=sys.stderr)


def find_ffmpeg(bbdown_dir: Path) -> Path | None:
    for path in (
        bbdown_dir / "ffmpeg" / "bin" / "ffmpeg.exe",
        bbdown_dir / "ffmpeg" / "bin" / "ffmpeg",
        bbdown_dir / "ffmpeg.exe",
        bbdown_dir / "ffmpeg",
    ):
        if _regular_file(path):
            return path
    for pattern in ("ffmpeg-*/bin/ffmpeg.exe", "ffmpeg-*/bin/ffmpeg"):
        for path in sorted(bbdown_dir.glob(pattern)):
            if _regular_file(path):
                return path
    if os.getenv("BILI_LAUNCHER_CHILD", "").strip() == "1":
        return None
    found = shutil.which("ffmpeg")
    return Path(found).resolve() if found else None


def find_bbdown_exe(bbdown_dir: Path) -> Path | None:
    for name in ("BBDown.exe", "BBDown", "bbdown"):
        executable = bbdown_dir / name
        if _regular_file(executable):
            return executable
    return None


def _binaries(cfg: AppConfig, ffmpeg: Path | None = None) -> tuple[Path, Path]:
    bbdown_dir = cfg.bbdown_path()
    exe = find_bbdown_exe(bbdown_dir)
    if exe is None:
        raise FileNotFoundError(f"未找到 BBDown 可执行文件: {bbdown_dir}")
    ffmpeg_path = ffmpeg or find_ffmpeg(bbdown_dir)
    if ffmpeg_path is None:
        raise FileNotFoundError(f"未找到 FFmpeg: {bbdown_dir}")
    return exe, ffmpeg_path


def build_argv(
    url: str,
    cfg: AppConfig,
    *,
    work_dir: Path | None = None,
    ffmpeg: Path | None = None,
    dfn_priority: str | None = None,
) -> list[str]:
    exe, ffmpeg_path = _binaries(cfg, ffmpeg)
    target_dir = Path(work_dir or cfg.download_path()).resolve()
    argv = [
        str(exe),
        url,
        "--work-dir",
        str(target_dir),
        "--file-pattern",
        "<videoTitle> [<bvid>] [<dfn>]",
        "--multi-file-pattern",
        "<videoTitle> [<bvid>]/[P<pageNumberWithZero>] <pageTitle> [<dfn>]",
        "--ffmpeg-path",
        str(ffmpeg_path),
    ]
    quality_priority = cfg.dfn_priority if dfn_priority is None else str(dfn_priority).strip()
    if quality_priority:
        argv.extend(["--dfn-priority", quality_priority])
    if cfg.encoding_priority:
        argv.extend(["--encoding-priority", cfg.encoding_priority])
    return argv


def build_info_argv(url: str, cfg: AppConfig, *, ffmpeg: Path | None = None) -> list[str]:
    exe, ffmpeg_path = _binaries(cfg, ffmpeg)
    argv = [
        str(exe),
        url,
        "--only-show-info",
        "--show-all",
        "--ffmpeg-path",
        str(ffmpeg_path),
    ]
    if cfg.encoding_priority:
        argv.extend(["--encoding-priority", cfg.encoding_priority])
    return argv


def _terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass


def _emit_progress(
    parser: BbdownProgressParser,
    text: str,
    on_progress: Callable[[ProgressEvent], None] | None,
) -> None:
    if on_progress is None:
        return
    for event in parser.feed(text):
        on_progress(event)


def _run_streaming(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float | None,
    cancel_event: threading.Event | None,
    on_output: Callable[[str], None] | None,
    on_progress: Callable[[ProgressEvent], None] | None,
) -> BbdownResult:
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    start_new_session = os.name != "nt"

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
        creationflags=creationflags,
        start_new_session=start_new_session,
    )
    tail = _TailBuffer()
    parser = BbdownProgressParser()

    def read_output() -> None:
        assert proc.stdout is not None
        probe = _EncodingProbe()
        decoder: codecs.IncrementalDecoder | None = None

        def emit(text: str) -> None:
            if not text:
                return
            tail.append(text)
            if on_output:
                on_output(text[-8192:])
            _emit_progress(parser, text, on_progress)

        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                if decoder is None:
                    decision = probe.feed(chunk)
                    if decision is None:
                        continue
                    decided, payload = decision
                    decoder = codecs.getincrementaldecoder(decided)(errors="replace")
                    chunk = payload
                emit(decoder.decode(chunk))
            if decoder is None:
                decoder = codecs.getincrementaldecoder(probe.finish())(errors="replace")
            emit(decoder.decode(b"", final=True))
            if on_progress:
                for event in parser.flush():
                    on_progress(event)
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass

    reader = threading.Thread(target=read_output, name=f"bbdown-log-{proc.pid}", daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout if timeout is not None else None
    timed_out = False
    cancelled = False

    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            _terminate_process_tree(proc)
            break
        if deadline is not None and time.monotonic() >= deadline:
            timed_out = True
            _terminate_process_tree(proc)
            break
        time.sleep(0.1)

    try:
        returncode = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        returncode = proc.wait(timeout=5)
    reader.join(timeout=2)
    return BbdownResult(
        returncode=returncode,
        stdout=tail.text(),
        stderr="",
        argv=argv,
        timed_out=timed_out,
        cancelled=cancelled,
    )


def _run_injected(
    runner,
    argv: list[str],
    *,
    cwd: Path,
    timeout: float | None,
    max_chars: int,
) -> BbdownResult:
    try:
        completed = runner(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = str(exc.stdout or "")[-max_chars:]
        error = str(exc.stderr or "")[-max_chars:]
        return BbdownResult(-1, output, error, argv, timed_out=True)
    return BbdownResult(
        returncode=int(completed.returncode),
        stdout=str(completed.stdout or "")[-max_chars:],
        stderr=str(completed.stderr or "")[-max_chars:],
        argv=argv,
    )


def run_bbdown_info(
    url: str,
    cfg: AppConfig,
    *,
    timeout: float | None = 60.0,
    runner=None,
    credential_dir: Path | None = None,
) -> BbdownResult:
    argv = build_info_argv(url, cfg)
    bbdown_dir = Path(credential_dir or cfg.bbdown_path()).resolve()
    if runner is not None and not getattr(runner, "supports_info", False):
        # Legacy test/provider runners only implement the download invocation.
        synthetic = (
            "共计1条视频流.\n"
            "0. [8K 超高清] [7680x4320] [HEVC] [60] [50000kbps] [~1 GB]\n"
        )
        return BbdownResult(0, synthetic, "", argv)
    if runner is not None:
        return _run_injected(
            runner,
            argv,
            cwd=bbdown_dir,
            timeout=timeout,
            max_chars=MAX_INFO_OUTPUT_CHARS,
        )
    sync_credentials_to_tool_dir(bbdown_dir, Path(argv[0]).resolve().parent)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(bbdown_dir),
            capture_output=True,
            text=False,
            timeout=timeout,
            shell=False,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        return BbdownResult(
            -1,
            _decode_output(bytes(exc.stdout or b""))[-MAX_INFO_OUTPUT_CHARS:],
            _decode_output(bytes(exc.stderr or b""))[-MAX_INFO_OUTPUT_CHARS:],
            argv,
            timed_out=True,
        )
    return BbdownResult(
        int(completed.returncode),
        _decode_output(completed.stdout)[-MAX_INFO_OUTPUT_CHARS:],
        _decode_output(completed.stderr)[-MAX_INFO_OUTPUT_CHARS:],
        argv,
    )


def run_bbdown(
    url: str,
    cfg: AppConfig,
    *,
    work_dir: Path | None = None,
    timeout: float | None = None,
    cancel_event: threading.Event | None = None,
    on_output: Callable[[str], None] | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    dfn_priority: str | None = None,
    runner=None,
    credential_dir: Path | None = None,
) -> BbdownResult:
    target_dir = Path(work_dir or cfg.download_path()).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    argv = build_argv(url, cfg, work_dir=target_dir, dfn_priority=dfn_priority)
    bbdown_dir = Path(credential_dir or cfg.bbdown_path()).resolve()

    if cancel_event is not None and cancel_event.is_set():
        return BbdownResult(-1, "", "任务已取消", argv, cancelled=True)

    if runner is None:
        sync_credentials_to_tool_dir(bbdown_dir, Path(argv[0]).resolve().parent)
        return _run_streaming(
            argv,
            cwd=bbdown_dir,
            timeout=timeout,
            cancel_event=cancel_event,
            on_output=on_output,
            on_progress=on_progress,
        )

    result = _run_injected(
        runner,
        argv,
        cwd=bbdown_dir,
        timeout=timeout,
        max_chars=MAX_LOG_TAIL_CHARS,
    )
    combined = result.combined
    if on_output and combined:
        on_output(combined[-8192:])
    if on_progress and combined:
        parser = BbdownProgressParser()
        for event in parser.feed(combined):
            on_progress(event)
        for event in parser.flush():
            on_progress(event)
    return result
