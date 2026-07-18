import hashlib
from pathlib import Path

from app.integrity import verify_tool_manifest


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tool_manifest_detects_tampering(tmp_env):
    manifest = tmp_env.bbdown_dir / "checksums.sha256"
    manifest.write_text(
        f"{_sha(tmp_env.bbdown_dir / 'BBDown.exe')}  BBDown.exe\n"
        f"{_sha(tmp_env.bbdown_dir / 'ffmpeg/bin/ffmpeg.exe')}  ffmpeg/bin/ffmpeg.exe\n",
        encoding="utf-8",
    )
    assert verify_tool_manifest(tmp_env.bbdown_dir).ok is True
    (tmp_env.bbdown_dir / "BBDown.exe").write_bytes(b"changed")
    status = verify_tool_manifest(tmp_env.bbdown_dir)
    assert status.checked is True
    assert status.ok is False
    assert any("哈希不匹配" in error for error in status.errors)


def test_tool_manifest_requires_both_executables(tmp_env):
    manifest = tmp_env.bbdown_dir / "checksums.sha256"
    manifest.write_text(
        f"{_sha(tmp_env.bbdown_dir / 'BBDown.exe')}  BBDown.exe\n",
        encoding="utf-8",
    )
    status = verify_tool_manifest(tmp_env.bbdown_dir)
    assert status.checked is True
    assert status.ok is False
    assert any("缺少必需条目" in error for error in status.errors)


def test_tool_manifest_accepts_linux_binary_names(tmp_path):
    bbdown = tmp_path / "BBDown"
    ffmpeg = tmp_path / "ffmpeg"
    bbdown.write_bytes(b"linux-bbdown")
    ffmpeg.write_bytes(b"linux-ffmpeg")
    (tmp_path / "checksums.sha256").write_text(
        f"{_sha(bbdown)}  BBDown\n{_sha(ffmpeg)}  ffmpeg\n",
        encoding="utf-8",
    )
    status = verify_tool_manifest(tmp_path)
    assert status.checked is True
    assert status.ok is True


def test_windows_batch_files_use_crlf():
    root = Path(__file__).resolve().parents[1]
    paths = sorted(root.glob("*.bat")) + sorted((root / "BBDown_portable").glob("*.bat"))
    assert paths, "未找到 Windows 批处理文件"
    for path in paths:
        data = path.read_bytes()
        assert b"\r\n" in data, f"{path.name} 未使用 CRLF"
        assert b"\n" not in data.replace(b"\r\n", b""), f"{path.name} 含裸 LF"
        assert not data.startswith(b"\xef\xbb\xbf"), f"{path.name} 不应带 UTF-8 BOM"
