from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from app.progress import clean_terminal_text

ALLOWED_MIN_HEIGHTS = frozenset({0, 360, 480, 720, 1080, 1440, 2160, 4320})
DEFAULT_MIN_HEIGHT = 1080

_TRACK_RE = re.compile(r"(?<!\d)(?P<index>\d+)\.\s+(?P<body>(?:\[[^\]]*\]\s*){3,})")
_SELECTED_RE = re.compile(r"\[视频\]\s*(?P<body>(?:\[[^\]]*\]\s*){3,})")
_TOKEN_RE = re.compile(r"\[([^\]]*)\]")
_BLOCK_RE = re.compile(r"共计\s*(\d+)\s*条视频流")
_RESOLUTION_RE = re.compile(r"(?P<w>\d{3,5})\s*[x×X]\s*(?P<h>\d{3,5})")
_KBPS_RE = re.compile(r"(?P<value>[\d.]+)\s*kbps", re.IGNORECASE)
_TITLE_PATTERNS = (
    re.compile(r"(?:视频标题|作品标题|标题)\s*[:：]\s*(.+)$", re.IGNORECASE),
    re.compile(r"(?:Video\s*Title|Title)\s*[:：]\s*(.+)$", re.IGNORECASE),
)


class QualityError(ValueError):
    pass


@dataclass(frozen=True)
class VideoTrack:
    index: int
    dfn: str
    resolution: str
    width: int | None
    height: int | None
    codec: str
    fps: str
    bandwidth_kbps: int | None
    size_text: str
    part: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityDecision:
    parts: list[dict[str, Any]]
    dfn_priority: str
    highest_height: int | None
    highest_label: str
    summary: str
    title_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "parts": self.parts,
            "dfn_priority": self.dfn_priority,
            "highest_height": self.highest_height,
            "highest_label": self.highest_label,
            "summary": self.summary,
            "title_hint": self.title_hint,
        }


def validate_min_height(value: int | None, *, default: int = DEFAULT_MIN_HEIGHT) -> int:
    result = default if value is None else int(value)
    if result not in ALLOWED_MIN_HEIGHTS:
        allowed = ", ".join(str(item) for item in sorted(ALLOWED_MIN_HEIGHTS))
        raise QualityError(f"最低清晰度只支持: {allowed}")
    return result


def height_label(height: int | None) -> str:
    if height is None:
        return "未知"
    if height == 0:
        return "不限制"
    labels = {4320: "8K", 2160: "4K", 1440: "2K / 1440P"}
    return labels.get(height, f"{height}P")


def _height_from_label(value: str) -> int | None:
    text = str(value or "").upper().replace(" ", "")
    if "8K" in text:
        return 4320
    if "4K" in text:
        return 2160
    if "2K" in text:
        return 1440
    matches = [int(item) for item in re.findall(r"(?<!\d)(360|480|720|1080|1440|2160|4320)P?", text)]
    return max(matches) if matches else None


def _resolution(value: str, dfn: str) -> tuple[int | None, int | None, int | None]:
    match = _RESOLUTION_RE.search(str(value or ""))
    if match:
        width, height = int(match.group("w")), int(match.group("h"))
        quality_height = min(width, height)
        if quality_height < 300:
            quality_height = max(width, height)
        return width, height, quality_height
    return None, None, _height_from_label(dfn)


def _track_from_tokens(tokens: list[str], *, index: int, part: int) -> VideoTrack | None:
    if len(tokens) < 3:
        return None
    dfn = tokens[0].strip()
    resolution = tokens[1].strip()
    codec = tokens[2].strip()
    fps = tokens[3].strip() if len(tokens) > 3 else ""
    bandwidth = None
    size_text = ""
    for token in tokens[4:]:
        match = _KBPS_RE.search(token)
        if match:
            try:
                bandwidth = int(float(match.group("value")))
            except ValueError:
                bandwidth = None
        if token.strip().startswith("~") or any(unit in token.upper() for unit in (" MB", " GB", " MIB", " GIB")):
            size_text = token.strip()
    width, raw_height, quality_height = _resolution(resolution, dfn)
    return VideoTrack(
        index=index,
        dfn=dfn,
        resolution=resolution,
        width=width,
        height=quality_height if quality_height is not None else raw_height,
        codec=codec,
        fps=fps,
        bandwidth_kbps=bandwidth,
        size_text=size_text,
        part=part,
    )


def parse_track_line(line: str, *, part: int = 1) -> VideoTrack | None:
    match = _TRACK_RE.search(clean_terminal_text(line))
    if not match:
        return None
    tokens = _TOKEN_RE.findall(match.group("body"))
    return _track_from_tokens(tokens, index=int(match.group("index")), part=part)


def parse_selected_line(line: str, *, part: int = 1) -> VideoTrack | None:
    match = _SELECTED_RE.search(clean_terminal_text(line))
    if not match:
        return None
    tokens = _TOKEN_RE.findall(match.group("body"))
    return _track_from_tokens(tokens, index=-1, part=part)


def _extract_title(lines: Iterable[str]) -> str:
    for raw in lines:
        line = " ".join(clean_terminal_text(raw).strip().split())
        for pattern in _TITLE_PATTERNS:
            match = pattern.search(line)
            if match:
                value = match.group(1).strip().strip('"')
                if value:
                    return value[:300]
    return ""


def parse_track_blocks(output: str) -> tuple[list[list[VideoTrack]], str]:
    lines = re.split(r"[\r\n]+", clean_terminal_text(output))
    blocks: list[list[VideoTrack]] = []
    current: list[VideoTrack] = []
    part = 1
    saw_marker = False
    for raw in lines:
        if _BLOCK_RE.search(raw):
            if current:
                blocks.append(current)
                part += 1
                current = []
            saw_marker = True
            continue
        track = parse_track_line(raw, part=part)
        if track is not None:
            current.append(track)
    if current:
        blocks.append(current)
    if not blocks and not saw_marker:
        fallback = [track for line in lines if (track := parse_track_line(line, part=1))]
        if fallback:
            blocks = [fallback]
    return blocks, _extract_title(lines)


def _normalize_quality(value: str) -> str:
    return re.sub(r"[\s·・_\-/]+", "", str(value or "")).casefold()


def quality_labels_match(expected: str, actual: str) -> bool:
    """Compare BBDown quality labels while ignoring harmless spacing/separators."""
    left = _normalize_quality(expected)
    right = _normalize_quality(actual)
    return bool(left and right and left == right)


def _track_key(track: VideoTrack) -> tuple[int, int, int, str]:
    return (
        int(track.height or -1),
        int(track.bandwidth_kbps or -1),
        _height_from_label(track.dfn) or -1,
        track.dfn.casefold(),
    )


def _dedupe_priority(values: Iterable[str]) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = _normalize_quality(text)
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return ",".join(result)


def decide_quality(
    output: str,
    *,
    min_height: int,
    preferred_quality: str = "",
    fallback_priority: str = "",
) -> QualityDecision:
    min_height = validate_min_height(min_height, default=DEFAULT_MIN_HEIGHT)
    blocks, title_hint = parse_track_blocks(output)
    if not blocks:
        raise QualityError("未能从 BBDown 信息输出中识别视频清晰度，已停止以避免误下低清晰度")

    preferred_key = _normalize_quality(preferred_quality)
    part_rows: list[dict[str, Any]] = []
    chosen_tracks: list[VideoTrack] = []
    all_tracks = [track for block in blocks for track in block]
    for part_no, block in enumerate(blocks, start=1):
        candidates = block
        if preferred_key:
            candidates = [track for track in block if _normalize_quality(track.dfn) == preferred_key]
            if not candidates:
                available = "、".join(track.dfn for track in sorted(block, key=_track_key, reverse=True)[:8])
                raise QualityError(
                    f"第 {part_no} 部分没有指定清晰度“{preferred_quality}”；可用：{available or '未知'}"
                )
        chosen = max(candidates, key=_track_key)
        if min_height > 0 and chosen.height is None:
            raise QualityError(f"第 {part_no} 部分无法确认分辨率，已停止以避免误下低清晰度")
        if min_height > 0 and int(chosen.height or 0) < min_height:
            raise QualityError(
                f"第 {part_no} 部分最高/指定清晰度为 {chosen.dfn}（{chosen.resolution or height_label(chosen.height)}），"
                f"低于最低要求 {height_label(min_height)}，任务已停止"
            )
        chosen_tracks.append(chosen)
        sorted_tracks = sorted(block, key=_track_key, reverse=True)
        part_rows.append(
            {
                "part": part_no,
                "available": [track.to_dict() for track in sorted_tracks],
                "selected": chosen.to_dict(),
            }
        )

    highest = max(all_tracks, key=_track_key)
    priority = _dedupe_priority(
        [track.dfn for track in chosen_tracks]
        + [track.dfn for track in sorted(all_tracks, key=_track_key, reverse=True)]
        + str(fallback_priority or "").split(",")
    )
    selected_labels = []
    for track in chosen_tracks:
        text = track.dfn or track.resolution or height_label(track.height)
        if text not in selected_labels:
            selected_labels.append(text)
    summary = " / ".join(selected_labels)
    if len(chosen_tracks) > 1:
        summary += f" · {len(chosen_tracks)} 个分段"
    return QualityDecision(
        parts=part_rows,
        dfn_priority=priority,
        highest_height=highest.height,
        highest_label=highest.dfn or height_label(highest.height),
        summary=summary or "已识别视频流",
        title_hint=title_hint,
    )


class SelectedTrackParser:
    def __init__(self) -> None:
        self._buffer = ""
        self._part = 1

    def feed(self, text: str) -> list[VideoTrack]:
        cleaned = clean_terminal_text(text)
        combined = self._buffer + cleaned
        parts = re.split(r"[\r\n]+", combined)
        ended = bool(re.search(r"[\r\n]$", combined))
        self._buffer = "" if ended else parts.pop()
        result: list[VideoTrack] = []
        for line in parts:
            track = parse_selected_line(line, part=self._part)
            if track is not None:
                result.append(track)
                self._part += 1
        return result

    def flush(self) -> list[VideoTrack]:
        if not self._buffer:
            return []
        text, self._buffer = self._buffer, ""
        track = parse_selected_line(text, part=self._part)
        if track is None:
            return []
        self._part += 1
        return [track]
