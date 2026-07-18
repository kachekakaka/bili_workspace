import json
from pathlib import Path

import pytest

from app.index_store import IndexStore, UnsafeIndexPathError


def _metadata(base: Path, file: Path):
    stat = file.stat()
    return [{"path": file.relative_to(base).as_posix(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}]


def test_put_validate_and_remove_directory(tmp_path):
    store = IndexStore(tmp_path)
    directory = tmp_path / "items" / "BV1abc"
    directory.mkdir(parents=True)
    video = directory / "demo.mp4"
    video.write_bytes(b"x")
    store.put(
        "BV1abc",
        title="demo",
        path="items/BV1abc",
        files=_metadata(tmp_path, video),
    )
    assert store.has("BV1abc")
    assert store.remove_entry_and_files("BV1abc") is True
    assert not directory.exists()
    assert not store.has("BV1abc")


def test_stale_entry_is_not_valid(tmp_path):
    store = IndexStore(tmp_path)
    directory = tmp_path / "items" / "BV2"
    directory.mkdir(parents=True)
    video = directory / "p1.mp4"
    video.write_bytes(b"1")
    store.put("BV2", title="multi", path="items/BV2", files=_metadata(tmp_path, video))
    video.unlink()
    assert store.has("BV2") is False


def test_path_traversal_cannot_delete_outside(tmp_path):
    download = tmp_path / "downloads"
    download.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    (download / ".bili_index.json").write_text(
        json.dumps({"BVbad": {"path": "../victim.txt", "files": []}}),
        encoding="utf-8",
    )
    store = IndexStore(download)
    with pytest.raises(UnsafeIndexPathError):
        store.remove_entry_and_files("BVbad")
    assert victim.read_text(encoding="utf-8") == "keep"
    assert store.get("BVbad") is not None


def test_absolute_path_cannot_be_stored(tmp_path):
    store = IndexStore(tmp_path)
    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")
    with pytest.raises(ValueError):
        store.put(
            "BVbad",
            title="x",
            path=str(video),
            files=[{"path": str(video), "size": 1}],
        )


def test_corrupt_index_is_preserved_and_backup_used(tmp_path):
    store = IndexStore(tmp_path)
    for key in ("A", "B"):
        directory = tmp_path / "items" / key
        directory.mkdir(parents=True)
        video = directory / f"{key}.mp4"
        video.write_bytes(key.encode())
        store.put(key, title=key, path=f"items/{key}", files=_metadata(tmp_path, video))
    (tmp_path / ".bili_index.json").write_text("{broken", encoding="utf-8")
    recovered = IndexStore(tmp_path)
    assert recovered.get("A") is not None
    assert list(tmp_path.glob(".bili_index.json.corrupt-*"))


def test_windows_style_paths_are_rejected_portably(tmp_path):
    store = IndexStore(tmp_path)
    for malicious in (r"C:\\victim.txt", r"C:victim.txt", r"\\server\\share\\x", r"..\\victim.txt"):
        with pytest.raises(ValueError):
            store.put("bad", title="bad", path=malicious, files=[])


def test_recorded_file_must_be_inside_entry_target(tmp_path):
    store = IndexStore(tmp_path)
    target = tmp_path / "items" / "safe"
    target.mkdir(parents=True)
    outside = tmp_path / "items" / "other.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(UnsafeIndexPathError):
        store.put(
            "BVbadfile",
            title="bad",
            path="items/safe",
            files=_metadata(tmp_path, outside),
        )
