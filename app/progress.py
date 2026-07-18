from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
PERCENT_RE = re.compile(r"(?<!\d)(100(?:\.0+)?|\d{1,2}(?:\.\d+)?)\s*%")
SIZE_TOKEN = r"(?P<{name}>\d+(?:\.\d+)?)\s*(?P<{unit}>[KMGTPE]?i?B)"
SIZE_PAIR_RE = re.compile(
    SIZE_TOKEN.format(name="done", unit="done_unit")
    + r"\s*(?:/|of|OF|共)\s*"
    + SIZE_TOKEN.format(name="total", unit="total_unit"),
    re.IGNORECASE,
)
SPEED_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[KMGTPE]?i?B)\s*(?:/s|ps|每秒)",
    re.IGNORECASE,
)
ETA_RE = re.compile(
    r"(?:ETA|预计剩余|剩余(?:时间)?)\s*[:：]?\s*"
    r"(?P<eta>\d{1,3}:\d{2}(?::\d{2})?|\d+(?:\.\d+)?\s*(?:秒|分钟|分))",
    re.IGNORECASE,
)
PART_RE = re.compile(
    r"(?:\bP|Part\s*|分(?:片|P)?\s*)(?P<current>\d+)\s*(?:/|of)\s*(?P<total>\d+)",
    re.IGNORECASE,
)

PHASE_LABELS = {
    "queued": "等待中",
    "resolving": "解析作品信息",
    "quality_check": "检查清晰度",
    "download_video": "下载视频流",
    "download_audio": "下载音频流",
    "download_subtitle": "下载字幕",
    "downloading": "下载媒体",
    "merge": "FFmpeg 混流",
    "finalizing": "校验并写入索引",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "skipped": "已跳过",
}


@dataclass(frozen=True)
class ProgressEvent:
    phase: str
    phase_label: str
    progress_percent: float | None = None
    speed_text: str = ""
    eta_text: str = ""
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    current_part: int | None = None
    part_total: int | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def clean_terminal_text(text: str) -> str:
    text = ANSI_RE.sub("", str(text or ""))
    # Remove control characters except tab/newline/carriage return.
    return "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32)


def _unit_bytes(value: str, unit: str) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    unit = unit.upper()
    binary = "I" in unit
    base = 1024 if binary else 1000
    power_map = {"B": 0, "KB": 1, "KIB": 1, "MB": 2, "MIB": 2, "GB": 3, "GIB": 3,
                 "TB": 4, "TIB": 4, "PB": 5, "PIB": 5, "EB": 6, "EIB": 6}
    power = power_map.get(unit)
    if power is None:
        return None
    return int(number * (base ** power))


def _detect_phase(line: str, fallback: str) -> str:
    lower = line.lower()
    if any(token in lower for token in ("混流", "合并音视频", "muxing", "mux ", "ffmpeg")):
        return "merge"
    if any(token in lower for token in ("下载字幕", "subtitle", "danmaku")):
        return "download_subtitle"
    if any(token in lower for token in ("下载音频", "音频流", "audio stream", "audio:")):
        return "download_audio"
    if any(token in lower for token in ("下载视频", "视频流", "video stream", "video:")):
        return "download_video"
    if any(token in lower for token in ("解析", "获取视频信息", "获取aid", "获取 cid", "fetching info", "parsing")):
        return "resolving"
    if any(token in lower for token in ("写入索引", "校验产物", "整理文件", "finalizing")):
        return "finalizing"
    if PERCENT_RE.search(line) or SPEED_RE.search(line):
        return fallback if fallback.startswith("download_") else "downloading"
    return fallback


class BbdownProgressParser:
    """Incrementally parse BBDown/FFmpeg console output.

    BBDown versions vary in wording, so the parser deliberately treats progress as
    best effort.  Unknown stages are exposed as indeterminate rather than inventing
    a percentage.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._phase = "resolving"
        self._last_signature: tuple[Any, ...] | None = None

    def feed(self, text: str) -> list[ProgressEvent]:
        cleaned = clean_terminal_text(text)
        if not cleaned:
            return []
        combined = self._buffer + cleaned
        parts = re.split(r"[\r\n]+", combined)
        ended = bool(re.search(r"[\r\n]$", combined))
        self._buffer = "" if ended else parts.pop()
        events: list[ProgressEvent] = []
        for part in parts:
            event = self._parse_line(part)
            if event is not None:
                events.append(event)
        # Some programs update a line without immediately writing a delimiter.
        if self._buffer and ("%" in self._buffer or len(self._buffer) > 240):
            event = self._parse_line(self._buffer)
            if event is not None:
                events.append(event)
        return events

    def flush(self) -> list[ProgressEvent]:
        if not self._buffer:
            return []
        text, self._buffer = self._buffer, ""
        event = self._parse_line(text)
        return [event] if event is not None else []

    def _parse_line(self, raw: str) -> ProgressEvent | None:
        line = " ".join(str(raw or "").strip().split())
        if not line:
            return None
        phase = _detect_phase(line, self._phase)
        self._phase = phase

        percent: float | None = None
        matches = list(PERCENT_RE.finditer(line))
        if matches:
            percent = max(0.0, min(100.0, float(matches[-1].group(1))))

        downloaded = total = None
        size_match = SIZE_PAIR_RE.search(line)
        if size_match:
            downloaded = _unit_bytes(size_match.group("done"), size_match.group("done_unit"))
            total = _unit_bytes(size_match.group("total"), size_match.group("total_unit"))
            if percent is None and downloaded is not None and total and total > 0:
                percent = max(0.0, min(100.0, downloaded * 100.0 / total))

        speed_text = ""
        speed_match = SPEED_RE.search(line)
        if speed_match:
            speed_text = f"{speed_match.group('value')} {speed_match.group('unit')}/s"

        eta_text = ""
        eta_match = ETA_RE.search(line)
        if eta_match:
            eta_text = eta_match.group("eta").strip()

        current_part = part_total = None
        part_match = PART_RE.search(line)
        if part_match:
            current_part = int(part_match.group("current"))
            part_total = int(part_match.group("total"))

        meaningful = (
            phase != "resolving"
            or percent is not None
            or bool(speed_text)
            or bool(eta_text)
            or current_part is not None
            or any(token in line.lower() for token in ("解析", "获取", "fetch", "parse"))
        )
        if not meaningful:
            return None

        event = ProgressEvent(
            phase=phase,
            phase_label=PHASE_LABELS.get(phase, phase),
            progress_percent=round(percent, 2) if percent is not None else None,
            speed_text=speed_text,
            eta_text=eta_text,
            downloaded_bytes=downloaded,
            total_bytes=total,
            current_part=current_part,
            part_total=part_total,
            message=line[-500:],
        )
        signature = (
            event.phase,
            event.progress_percent,
            event.speed_text,
            event.eta_text,
            event.downloaded_bytes,
            event.total_bytes,
            event.current_part,
            event.part_total,
            event.message,
        )
        if signature == self._last_signature:
            return None
        self._last_signature = signature
        return event
