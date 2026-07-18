from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEFAULT_GROUP = "未分组"
MAX_GROUP_LENGTH = 60

_INVALID_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SPACE_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"-{2,}")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class GroupName:
    display: str
    folder: str
    changed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"display": self.display, "folder": self.folder, "changed": self.changed}


def normalize_group(value: str | None, *, default: str = DEFAULT_GROUP) -> GroupName:
    original = str(value or "").strip()
    text = unicodedata.normalize("NFKC", original or default)
    text = _INVALID_RE.sub("-", text)
    text = _SPACE_RE.sub(" ", text)
    text = _DASH_RE.sub("-", text)
    text = text.strip(" .-")
    if not text or text in {".", ".."}:
        text = default
    base_name, dot, suffix = text.partition(".")
    if base_name.upper() in _WINDOWS_RESERVED:
        text = f"{base_name}-分组{dot}{suffix}"
    text = text[:MAX_GROUP_LENGTH].rstrip(" .-") or default
    return GroupName(display=text, folder=text, changed=text != original)
