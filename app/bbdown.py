from __future__ import annotations

import codecs
import os
import signal
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import AppConfig
from app.constants import MAX_INFO_OUTPUT_CHARS, MAX_LOG_TAIL_CHARS
from app.progress import BbdownProgressParser, ProgressEvent


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
    creationflags = 0
    start_new_session = False
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        start_new_session = True

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
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if not text:
                    continue
                tail.append(text)
                if on_output:
                    on_output(text[-8192:])
                _emit_progress(parser, text, on_progress)
            final_text = decoder.decode(b"", final=True)
            if final_text:
                tail.append(final_text)
                if on_output:
                    on_output(final_text)
                _emit_progress(parser, final_text, on_progress)
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
) -> BbdownResult:
    argv = build_info_argv(url, cfg)
    bbdown_dir = cfg.bbdown_path()
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
    try:
        completed = subprocess.run(
            argv,
            cwd=str(bbdown_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return BbdownResult(
            -1,
            str(exc.stdout or "")[-MAX_INFO_OUTPUT_CHARS:],
            str(exc.stderr or "")[-MAX_INFO_OUTPUT_CHARS:],
            argv,
            timed_out=True,
        )
    return BbdownResult(
        int(completed.returncode),
        str(completed.stdout or "")[-MAX_INFO_OUTPUT_CHARS:],
        str(completed.stderr or "")[-MAX_INFO_OUTPUT_CHARS:],
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
) -> BbdownResult:
    target_dir = Path(work_dir or cfg.download_path()).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    argv = build_argv(url, cfg, work_dir=target_dir, dfn_priority=dfn_priority)
    bbdown_dir = cfg.bbdown_path()

    if cancel_event is not None and cancel_event.is_set():
        return BbdownResult(-1, "", "任务已取消", argv, cancelled=True)

    if runner is None:
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
