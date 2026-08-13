from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT


def application_root() -> Path:
    """Return the immutable application-resource root for this process."""

    override = os.getenv("BILI_APP_RESOURCE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        frozen_root = Path(getattr(sys, "_MEIPASS")).resolve()
        launcher_context = frozen_root / "resources" / "source" / "docker-context"
        return launcher_context if launcher_context.is_dir() else frozen_root
    return ROOT


def defaults_dir() -> Path:
    return application_root() / "app" / "defaults"


def web_dir() -> Path:
    return application_root() / "web"


def resolve_path(value: str | Path, *, base: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return ((base or ROOT) / path).resolve()
