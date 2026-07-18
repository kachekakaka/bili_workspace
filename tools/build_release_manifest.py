from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "RELEASE_MANIFEST.sha256"
SKIP_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    ".cache",
    ".server",
    ".tmp",
    ".v05_state",
    ".ruff_cache",
    ".mypy_cache",
}
SKIP_NAMES = {
    MANIFEST,
    "BBDown.data",
    "bootstrap-token.txt",
    ".env",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def include(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
        return False
    if path.name.endswith((".db-wal", ".db-shm", ".tmp", ".log")):
        return False
    if rel.parts and rel.parts[0] == "downloads":
        return False
    if rel.as_posix() in {
        "config.json", "config.json.bak",
        "config/config.json", "config/config.json.bak",
        "config/runtime.env", "config/runtime.env.bak",
        "docker/.env", "docker/.env.bak",
    }:
        return False
    return path.is_file() and not path.is_symlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the immutable release SHA-256 manifest"
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    rows: list[str] = []
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    for path in paths:
        if include(root, path):
            rows.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    destination = root / MANIFEST
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(rows)} entries to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
