from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import zipfile
from pathlib import Path

import pytest

from bili_workspace_launcher.cli import _verify_tool_record
from tools.build_ffmpeg_windows import (
    BUILDER_BASE_IMAGE,
    BUILD_SCRIPT,
    DEBIAN_SNAPSHOT,
    DOCKERFILE,
    FFMPEG_RELEASE_KEY_FINGERPRINT,
    FFMPEG_RELEASE_KEY_NAME,
    FFMPEG_RELEASE_KEY_URL,
    FFMPEG_SIGNATURE_NAME,
    FFMPEG_SIGNATURE_URL,
    FFMPEG_SOURCE_NAME,
    FFMPEG_SOURCE_URL,
    REQUIRED_CONFIGURATION,
)
from tools.build_launcher import (
    _parse_ffmpeg_version_output,
    _publish_candidate,
    _verify_ffmpeg_source_evidence,
    _validate_pe_amd64,
)
from tools.prepare_launcher_resources import (
    FFMPEG_SOURCE_MEMBER,
    FFMPEG_SOURCE_EVIDENCE_MEMBER,
    _scan_source,
    assemble_bundle,
    collect_license_materials,
    download,
    safe_extract_zip,
)


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _fake_ffmpeg_build(path: Path) -> Path:
    path.mkdir()
    files = {
        "ffmpeg.exe": b"fake-ffmpeg",
        "LICENSE.md": b"FFmpeg test license\n",
        "COPYING.LGPLv2.1": b"LGPL 2.1 test license\n",
        "buildconf.txt": (" ".join(sorted(REQUIRED_CONFIGURATION)) + "\n").encode(),
        "toolchain-packages.txt": b"gcc=1\ngcc-mingw-w64-x86-64=1\nlibc6-dev=1\n",
        "pe-imports.txt": b"KERNEL32.dll\n",
        "build-evidence.json": b'{"status":"verified"}\n',
    }
    for name, content in files.items():
        (path / name).write_bytes(content)
    return path


def _fake_fixed_file(path: Path, content: bytes) -> tuple[Path, int, str]:
    path.write_bytes(content)
    return path, len(content), hashlib.sha256(content).hexdigest()


def test_archive_traversal_is_rejected(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "bad.zip", {"../escape.txt": b"bad"})
    with pytest.raises(ValueError, match="不安全"):
        safe_extract_zip(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("name", ("payload.txt:stream", "CON.txt", "folder./file.txt"))
def test_archive_windows_special_paths_are_rejected(tmp_path: Path, name: str) -> None:
    archive = _zip(tmp_path / "bad-windows-path.zip", {name: b"bad"})
    with pytest.raises(ValueError, match="不安全"):
        safe_extract_zip(archive, tmp_path / "out")


class DownloadResponse:
    def __init__(self, payload: bytes, content_length: str | None) -> None:
        self._stream = io.BytesIO(payload)
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self._stream.read(size)


def test_fixed_download_rejects_declared_or_streamed_oversize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "cache" / "asset.zip"
    digest = hashlib.sha256(b"abc").hexdigest()
    monkeypatch.setattr(
        "tools.prepare_launcher_resources.urllib.request.urlopen",
        lambda *_args, **_kwargs: DownloadResponse(b"abc", "4"),
    )
    with pytest.raises(RuntimeError, match="响应大小不匹配"):
        download("https://example.test/asset", digest, 3, destination, retries=1)
    assert not destination.exists()
    assert not destination.with_suffix(".zip.part").exists()

    monkeypatch.setattr(
        "tools.prepare_launcher_resources.urllib.request.urlopen",
        lambda *_args, **_kwargs: DownloadResponse(b"abcd", None),
    )
    with pytest.raises(RuntimeError, match="超过固定大小"):
        download("https://example.test/asset", digest, 3, destination, retries=1)
    assert not destination.exists()
    assert not destination.with_suffix(".zip.part").exists()


def test_bundle_contains_fixed_tools_and_secret_free_docker_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bbdown = _zip(tmp_path / "bbdown.zip", {"release/BBDown.exe": b"bbdown"})
    ffmpeg_build = _fake_ffmpeg_build(tmp_path / "ffmpeg-build")
    source, source_size, source_sha = _fake_fixed_file(tmp_path / "ffmpeg.tar.xz", b"source")
    signature, signature_size, signature_sha = _fake_fixed_file(tmp_path / "ffmpeg.asc", b"sig")
    release_key, key_size, key_sha = _fake_fixed_file(tmp_path / "ffmpeg-key.asc", b"key")
    monkeypatch.setattr(
        "tools.prepare_launcher_resources.validate_ffmpeg_output", lambda _path: {}
    )
    target = assemble_bundle(
        target=tmp_path / "bundle",
        bbdown_archive=bbdown,
        ffmpeg_build=ffmpeg_build,
        ffmpeg_source=source,
        ffmpeg_signature=signature,
        ffmpeg_release_key=release_key,
        expected_bbdown_sha256=hashlib.sha256(bbdown.read_bytes()).hexdigest(),
        expected_ffmpeg_source_sha256=source_sha,
        expected_ffmpeg_source_size=source_size,
        expected_ffmpeg_signature_sha256=signature_sha,
        expected_ffmpeg_signature_size=signature_size,
        expected_ffmpeg_release_key_sha256=key_sha,
        expected_ffmpeg_release_key_size=key_size,
    )
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    assert len(manifest["build_id"]) == 12
    assert "windows-tools/BBDown.exe" in files
    assert "windows-tools/ffmpeg/bin/ffmpeg.exe" in files
    assert "windows-tools/LICENSES/FFmpeg.COPYING.LGPLv2.1.txt" in files
    assert "THIRD_PARTY_SOURCES/ffmpeg-7.1.1.tar.xz" in files
    assert "THIRD_PARTY_SOURCES/ffmpeg-builder.Dockerfile" in files
    assert "docker-context/docker/Dockerfile" in files
    assert "docker-context/app/defaults/runtime.env.default" in files
    assert not any(Path(name).name in {".env", "BBDown.data", "launcher.json"} for name in files)


def test_resource_scan_rejects_embedded_bilibili_credentials(tmp_path: Path) -> None:
    source = tmp_path / "source"
    tools = source / "windows-tools"
    ffmpeg = tools / "ffmpeg" / "bin"
    ffmpeg.mkdir(parents=True)
    (tools / "BBDown.exe").write_bytes(b"fake")
    (ffmpeg / "ffmpeg.exe").write_bytes(b"fake")
    (source / "application.txt").write_text(
        "SESSDATA=" + "realistic-secret-value", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="登录凭据"):
        _scan_source(source)


def test_installed_license_manifest_records_file_identity(tmp_path: Path) -> None:
    manifest_path = collect_license_materials(
        tmp_path / "licenses",
        expected_distributions={"pytest": pytest.__version__},
        python_license=Path(__file__),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["packages"]
    for entry in manifest["packages"]:
        license_path = manifest_path.parent / entry["path"]
        assert license_path.stat().st_size == entry["size"]
        assert hashlib.sha256(license_path.read_bytes()).hexdigest() == entry["sha256"]


def test_pyside_license_collection_requires_fixed_official_source_texts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {
        "GPL-3.0-only.txt": b"GNU GENERAL PUBLIC LICENSE Version 3\n",
        "LGPL-3.0-only.txt": b"GNU LESSER GENERAL PUBLIC LICENSE Version 3\n",
        "Qt-GPL-exception-1.0.txt": b"Qt GPL exception version 1.0\n",
    }
    identities = {
        name: {
            "url": f"https://example.test/{name}",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for name, payload in payloads.items()
    }
    monkeypatch.setattr(
        "tools.prepare_launcher_resources.PYSIDE_LICENSE_TEXTS", identities
    )
    sources: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = tmp_path / name
        path.write_bytes(payload)
        sources[name] = path

    manifest_path = collect_license_materials(
        tmp_path / "pyside-licenses",
        expected_distributions={"PySide6": "6.11.1"},
        python_license=Path(__file__),
        pyside_license_files=sources,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    official = {
        entry["source_path"]: entry
        for entry in manifest["packages"]
        if entry["source_path"].startswith("qtpyside-v6.11.1/")
    }
    assert set(official) == {
        f"qtpyside-v6.11.1/LICENSES/{name}" for name in payloads
    }
    assert manifest["contains_lgplv3_text"] is True


def test_pe_validator_accepts_only_amd64(tmp_path: Path) -> None:
    path = tmp_path / "candidate.exe"
    payload = bytearray(256)
    payload[:2] = b"MZ"
    payload[0x3C:0x40] = struct.pack("<I", 128)
    payload[128:132] = b"PE\0\0"
    payload[132:134] = struct.pack("<H", 0x8664)
    path.write_bytes(payload)
    _validate_pe_amd64(path)
    payload[132:134] = struct.pack("<H", 0x014C)
    path.write_bytes(payload)
    with pytest.raises(RuntimeError, match="AMD64"):
        _validate_pe_amd64(path)

    path.write_bytes(payload[:133])
    with pytest.raises(RuntimeError, match="Machine"):
        _validate_pe_amd64(path)


def test_ffmpeg_license_gate_requires_fixed_lgpl_source_build() -> None:
    configuration = " ".join(sorted(REQUIRED_CONFIGURATION))
    valid = _parse_ffmpeg_version_output(
        f"ffmpeg version 7.1.1-bili-workspace Copyright\nconfiguration: {configuration}\n"
    )
    assert valid["license_mode"] == "LGPL-2.1-or-later"
    with pytest.raises(RuntimeError, match="禁止的许可选项"):
        _parse_ffmpeg_version_output(
            "ffmpeg version 7.1.1-bili-workspace Copyright\n"
            f"configuration: {configuration} --enable-nonfree\n"
        )
    with pytest.raises(RuntimeError, match="外部库"):
        _parse_ffmpeg_version_output(
            "ffmpeg version 7.1.1-bili-workspace Copyright\n"
            f"configuration: {configuration} --enable-libx264\n"
        )
    with pytest.raises(RuntimeError, match="缺少构建选项"):
        _parse_ffmpeg_version_output(
            "ffmpeg version 7.1.1-bili-workspace Copyright\n"
            "configuration: --disable-autodetect\n"
        )


def test_ffmpeg_distribution_gate_requires_matching_corresponding_source_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resource_dir = tmp_path / "bundle"
    source_root = resource_dir / "source"
    ffmpeg = source_root / "windows-tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    ffmpeg.parent.mkdir(parents=True)
    ffmpeg.write_bytes(b"fixed-ffmpeg")
    configuration = " ".join(sorted(REQUIRED_CONFIGURATION))
    verification = {
        "ffmpeg": {
            "version_line": "ffmpeg version 7.1.1-bili-workspace test",
            "configuration": configuration,
            "license_mode": "LGPL-2.1-or-later",
            "output_sha256": "b" * 64,
            "sha256": hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
        }
    }
    with pytest.raises(RuntimeError, match="缺少 FFmpeg"):
        _verify_ffmpeg_source_evidence(resource_dir, verification)

    evidence_path = resource_dir / "source" / Path(*FFMPEG_SOURCE_EVIDENCE_MEMBER.split("/"))
    evidence_path.parent.mkdir(parents=True)
    source_bytes = b"official-source"
    signature_bytes = b"official-signature"
    key_bytes = b"official-release-key"
    source_path = source_root / Path(*FFMPEG_SOURCE_MEMBER.split("/"))
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source_bytes)
    signature_path = source_path.parent / FFMPEG_SIGNATURE_NAME
    signature_path.write_bytes(signature_bytes)
    key_path = source_path.parent / FFMPEG_RELEASE_KEY_NAME
    key_path.write_bytes(key_bytes)
    monkeypatch.setattr(
        "tools.build_launcher.FFMPEG_SOURCE_SIZE", len(source_bytes)
    )
    monkeypatch.setattr(
        "tools.build_launcher.FFMPEG_SOURCE_SHA256",
        hashlib.sha256(source_bytes).hexdigest(),
    )
    monkeypatch.setattr(
        "tools.build_launcher.FFMPEG_SIGNATURE_SIZE", len(signature_bytes)
    )
    monkeypatch.setattr(
        "tools.build_launcher.FFMPEG_SIGNATURE_SHA256",
        hashlib.sha256(signature_bytes).hexdigest(),
    )
    monkeypatch.setattr(
        "tools.build_launcher.FFMPEG_RELEASE_KEY_SIZE", len(key_bytes)
    )
    monkeypatch.setattr(
        "tools.build_launcher.FFMPEG_RELEASE_KEY_SHA256",
        hashlib.sha256(key_bytes).hexdigest(),
    )

    recipe_root = source_root / "THIRD_PARTY_SOURCES"
    recipe_files: dict[str, dict[str, object]] = {}
    for recipe_source in (DOCKERFILE, BUILD_SCRIPT):
        target = recipe_root / recipe_source.name
        target.write_bytes(recipe_source.read_bytes())
        recipe_files[target.name] = {
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "size": target.stat().st_size,
        }
    artifact_paths = {
        "ffmpeg.exe": ffmpeg,
        "LICENSE.md": source_root / "windows-tools" / "LICENSES" / "FFmpeg.LICENSE.md",
        "COPYING.LGPLv2.1": source_root
        / "windows-tools"
        / "LICENSES"
        / "FFmpeg.COPYING.LGPLv2.1.txt",
        "buildconf.txt": recipe_root / "ffmpeg-build" / "buildconf.txt",
        "pe-imports.txt": recipe_root / "ffmpeg-build" / "pe-imports.txt",
        "toolchain-packages.txt": recipe_root / "ffmpeg-build" / "toolchain-packages.txt",
    }
    artifact_text = {
        "LICENSE.md": "FFmpeg test license\n",
        "COPYING.LGPLv2.1": "LGPL test license\n",
        "buildconf.txt": f"{configuration}\n",
        "pe-imports.txt": "KERNEL32.dll\n",
        "toolchain-packages.txt": "gcc=1\ngcc-mingw-w64-x86-64=1\nlibc6-dev=1\n",
    }
    for name, path in artifact_paths.items():
        if name != "ffmpeg.exe":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(artifact_text[name], encoding="utf-8")
    artifacts = {
        name: {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for name, path in artifact_paths.items()
    }
    evidence = {
        "schema_version": 1,
        "status": "verified",
        "target": "windows-amd64",
        "license_mode": "LGPL-2.1-or-later",
        "binary": {
            "path": "ffmpeg.exe",
            "sha256": hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
            "size": ffmpeg.stat().st_size,
        },
        "source": {
            "name": FFMPEG_SOURCE_NAME,
            "url": FFMPEG_SOURCE_URL,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size": len(source_bytes),
            "embedded_path": FFMPEG_SOURCE_MEMBER,
            "signature": {
                "name": FFMPEG_SIGNATURE_NAME,
                "url": FFMPEG_SIGNATURE_URL,
                "sha256": hashlib.sha256(signature_bytes).hexdigest(),
                "size": len(signature_bytes),
            },
            "release_key": {
                "name": FFMPEG_RELEASE_KEY_NAME,
                "url": FFMPEG_RELEASE_KEY_URL,
                "sha256": hashlib.sha256(key_bytes).hexdigest(),
                "size": len(key_bytes),
                "fingerprint": FFMPEG_RELEASE_KEY_FINGERPRINT,
            },
        },
        "recipe": {
            "base_image": BUILDER_BASE_IMAGE,
            "debian_snapshot": DEBIAN_SNAPSHOT,
            "configuration": configuration,
            "files": recipe_files,
            "toolchain_packages": [
                "gcc=1",
                "gcc-mingw-w64-x86-64=1",
                "libc6-dev=1",
            ],
            "pe_imports": ["KERNEL32.dll"],
        },
        "artifacts": artifacts,
    }
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence_bytes = evidence_path.read_bytes()
    (resource_dir / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    FFMPEG_SOURCE_EVIDENCE_MEMBER: {
                        "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                        "size": len(evidence_bytes),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = _verify_ffmpeg_source_evidence(resource_dir, verification)
    assert result["source_count"] == 1

    evidence["recipe"]["configuration"] = "--enable-gpl"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(RuntimeError, match="实际版本、配置或许可模式"):
        _verify_ffmpeg_source_evidence(resource_dir, verification)


def test_exe_self_check_tool_record_requires_embedded_ffmpeg_source_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    bbdown = source / "windows-tools" / "BBDown.exe"
    ffmpeg = source / "windows-tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    bbdown.parent.mkdir(parents=True)
    ffmpeg.parent.mkdir(parents=True)
    bbdown.write_bytes(b"bbdown")
    ffmpeg.write_bytes(b"ffmpeg")
    evidence = source / "THIRD_PARTY_LICENSES" / "FFmpeg.SOURCE.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"status":"verified"}\n', encoding="utf-8")
    record = {
        "schema_version": 1,
        "bbdown": {
            "version": "1.6.3",
            "sha256": hashlib.sha256(bbdown.read_bytes()).hexdigest(),
        },
        "ffmpeg": {
            "version_line": "ffmpeg version 7.1.1-bili-workspace test",
            "configuration": " ".join(sorted(REQUIRED_CONFIGURATION)),
            "license_mode": "LGPL-2.1-or-later",
            "sha256": hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
            "compatible_transcode": {
                "video_encoder": "h264_mf",
                "audio_encoder": "aac",
                "pixel_format": "nv12",
                "software_only": True,
                "container": "mp4",
                "output_size": 1234,
                "output_sha256": "a" * 64,
                "encoder_help_sha256": "b" * 64,
            },
        },
        "ffmpeg_source_evidence": {
            "schema_version": 1,
            "path": FFMPEG_SOURCE_EVIDENCE_MEMBER,
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "source_count": 1,
        },
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"tool_verification": record}), encoding="utf-8")

    _verify_tool_record(manifest, source)

    evidence.write_text('{"status":"tampered"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="许可边界"):
        _verify_tool_record(manifest, source)


def test_candidate_publish_restores_exe_and_record_if_final_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / "staging.exe"
    destination = tmp_path / "dist" / "candidate.exe"
    record_path = tmp_path / "current-build.json"
    destination.parent.mkdir()
    staging.write_bytes(b"new-exe")
    destination.write_bytes(b"old-exe")
    record_path.write_text('{"old": true}\n', encoding="utf-8")

    real_replace = os.replace
    calls = 0

    def fail_record_commit(source, target):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected record commit failure")
        return real_replace(source, target)

    monkeypatch.setattr("tools.build_launcher.os.replace", fail_record_commit)
    with pytest.raises(OSError, match="injected"):
        _publish_candidate(
            staging_executable=staging,
            destination=destination,
            record_path=record_path,
            record={"schema_version": 1},
        )
    assert destination.read_bytes() == b"old-exe"
    assert staging.read_bytes() == b"new-exe"
    assert json.loads(record_path.read_text(encoding="utf-8")) == {"old": True}
    assert not list(tmp_path.rglob("*.bak"))


def test_candidate_publish_verifies_exe_record_identity(tmp_path: Path) -> None:
    staging = tmp_path / "staging.exe"
    destination = tmp_path / "dist" / "candidate.exe"
    record_path = tmp_path / "current-build.json"
    payload = b"new-exe"
    staging.write_bytes(payload)
    record = {
        "schema_version": 1,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    _publish_candidate(
        staging_executable=staging,
        destination=destination,
        record_path=record_path,
        record=record,
    )

    assert destination.read_bytes() == payload
    assert json.loads(record_path.read_text(encoding="utf-8")) == record


def test_candidate_publish_rejects_in_use_exe_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / "staging.exe"
    destination = tmp_path / "dist" / "candidate.exe"
    record_path = tmp_path / "current-build.json"
    destination.parent.mkdir()
    staging.write_bytes(b"new-exe")
    destination.write_bytes(b"old-exe")
    record_path.write_text('{"old": true}\n', encoding="utf-8")
    monkeypatch.setattr("tools.build_launcher._windows_file_use_count", lambda _path: 3)

    with pytest.raises(RuntimeError, match="3 个进程使用"):
        _publish_candidate(
            staging_executable=staging,
            destination=destination,
            record_path=record_path,
            record={"schema_version": 1},
        )

    assert destination.read_bytes() == b"old-exe"
    assert staging.read_bytes() == b"new-exe"
    assert json.loads(record_path.read_text(encoding="utf-8")) == {"old": True}
    assert not list(tmp_path.rglob("*.bak"))
    assert not list(tmp_path.rglob("*.new"))


def test_resource_bundle_publish_failure_restores_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bbdown = _zip(tmp_path / "bbdown.zip", {"release/BBDown.exe": b"bbdown"})
    ffmpeg_build = _fake_ffmpeg_build(tmp_path / "ffmpeg-build")
    source, source_size, source_sha = _fake_fixed_file(tmp_path / "ffmpeg.tar.xz", b"source")
    signature, signature_size, signature_sha = _fake_fixed_file(tmp_path / "ffmpeg.asc", b"sig")
    release_key, key_size, key_sha = _fake_fixed_file(tmp_path / "ffmpeg-key.asc", b"key")
    monkeypatch.setattr(
        "tools.prepare_launcher_resources.validate_ffmpeg_output", lambda _path: {}
    )
    arguments = {
        "target": tmp_path / "bundle",
        "bbdown_archive": bbdown,
        "ffmpeg_build": ffmpeg_build,
        "ffmpeg_source": source,
        "ffmpeg_signature": signature,
        "ffmpeg_release_key": release_key,
        "expected_bbdown_sha256": hashlib.sha256(bbdown.read_bytes()).hexdigest(),
        "expected_ffmpeg_source_sha256": source_sha,
        "expected_ffmpeg_source_size": source_size,
        "expected_ffmpeg_signature_sha256": signature_sha,
        "expected_ffmpeg_signature_size": signature_size,
        "expected_ffmpeg_release_key_sha256": key_sha,
        "expected_ffmpeg_release_key_size": key_size,
    }
    target = assemble_bundle(**arguments)
    before = {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }

    real_replace = os.replace
    calls = 0

    def fail_publish(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected resource publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr("tools.prepare_launcher_resources.os.replace", fail_publish)
    with pytest.raises(OSError, match="injected"):
        assemble_bundle(**arguments)

    after = {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not list(tmp_path.glob(".bundle.*"))
