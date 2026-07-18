from pathlib import Path

import pytest

from app.path_safety import UnsafePathError
from app.platform_actions import resolve_output_folder


def test_resolve_output_folder_accepts_safe_file_and_directory(tmp_path: Path):
    folder = tmp_path / "items" / "BVsafe"
    folder.mkdir(parents=True)
    file = folder / "demo.mp4"
    file.write_bytes(b"x")
    assert resolve_output_folder(tmp_path, "items/BVsafe") == folder.resolve()
    assert resolve_output_folder(tmp_path, "items/BVsafe/demo.mp4") == folder.resolve()


def test_resolve_output_folder_rejects_traversal(tmp_path: Path):
    victim = tmp_path.parent / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    with pytest.raises(UnsafePathError):
        resolve_output_folder(tmp_path, "../victim.txt")
