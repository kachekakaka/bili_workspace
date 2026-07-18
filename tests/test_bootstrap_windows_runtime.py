from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from tools import bootstrap_windows_runtime as runtime


def _build_runtime_zip(path: Path, files: dict[str, bytes]) -> str:
    rows = []
    for name, payload in sorted(files.items()):
        rows.append(f"{hashlib.sha256(payload).hexdigest()}  {name}")
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        archive.writestr("runtime_manifest.sha256", "\n".join(rows) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verify_and_install_runtime_archive(monkeypatch, tmp_path: Path) -> None:
    archive = tmp_path / "runtime.zip"
    files = {
        "BBDown_portable/BBDown.exe": b"bbdown",
        "BBDown_portable/ffmpeg/bin/ffmpeg.exe": b"ffmpeg",
        "wheelhouse/demo-1.0-py3-none-any.whl": b"wheel",
        "LICENSES/BBDown.LICENSE.txt": b"license",
    }
    digest = _build_runtime_zip(archive, files)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(runtime, "ROOT", root)
    monkeypatch.setattr(runtime, "RUNTIME_SHA256", digest)
    monkeypatch.setattr(
        runtime,
        "EXPECTED_TOOL_HASHES",
        {
            "BBDown.exe": hashlib.sha256(b"bbdown").hexdigest(),
            "ffmpeg/bin/ffmpeg.exe": hashlib.sha256(b"ffmpeg").hexdigest(),
        },
    )

    installed = runtime.install_archive(archive, overwrite=False)

    assert len(installed) == len(files)
    for name, payload in files.items():
        assert (root / name).read_bytes() == payload
    assert (root / "BBDown_portable/checksums.sha256").is_file()
    assert (root / ".windows_runtime_manifest.sha256").is_file()


def test_runtime_archive_rejects_path_traversal(monkeypatch, tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../BBDown.exe", b"bad")
        output.writestr("runtime_manifest.sha256", "")
    monkeypatch.setattr(runtime, "RUNTIME_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="不安全路径"):
        runtime.verify_archive(archive)


def test_runtime_archive_rejects_manifest_mismatch(monkeypatch, tmp_path: Path) -> None:
    archive = tmp_path / "mismatch.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("BBDown_portable/BBDown.exe", b"real")
        output.writestr(
            "runtime_manifest.sha256",
            f"{'0' * 64}  BBDown_portable/BBDown.exe\n",
        )
    monkeypatch.setattr(runtime, "RUNTIME_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="内部文件哈希"):
        runtime.verify_archive(archive)


def test_choose_archive_prefers_explicit(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    explicit = tmp_path / "custom.zip"
    explicit.write_bytes(b"x")
    monkeypatch.setattr(runtime, "ROOT", root)
    assert runtime.choose_archive(explicit) == explicit.resolve()
