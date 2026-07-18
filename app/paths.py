from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def resolve_path(value: str | Path, *, base: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return ((base or ROOT) / path).resolve()
