from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools import build_integrated_runtime as builder

ROOT = Path(__file__).resolve().parent.parent


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_builder_pins_official_sources_and_regular_git_size_limit() -> None:
    assert builder.VERSION == "0.5.6"
    assert builder.PYTHON_VERSION == "3.13.14"
    assert builder.PYTHON_EMBED_URL.startswith("https://www.python.org/ftp/python/")
    assert len(builder.PYTHON_EMBED_SHA256) == 64
    assert builder.BBDOWN_URL.startswith(
        "https://github.com/nilaoda/BBDown/releases/download/1.6.3/"
    )
    assert len(builder.BBDOWN_SHA256) == 64
    assert builder.FFMPEG_WHEEL_URL.startswith("https://files.pythonhosted.org/")
    assert len(builder.FFMPEG_WHEEL_SHA256) == 64
    assert builder.MAX_PACK_BYTES == 100 * 1024 * 1024


@pytest.mark.parametrize(
    "name", ["../evil", "/absolute", "C:/evil", "a/../../evil", "./evil"]
)
def test_builder_rejects_unsafe_archive_paths(name: str) -> None:
    with pytest.raises(ValueError):
        builder.safe_member(name)


def test_builder_writes_deterministic_pack_and_internal_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "hello.txt").write_text("hello", encoding="utf-8")
    builder.write_internal_manifest(source)
    pack = tmp_path / "runtime.pack"
    builder.deterministic_zip(source, pack)
    with zipfile.ZipFile(pack) as archive:
        assert set(archive.namelist()) == {"hello.txt", "runtime_manifest.sha256"}
        expected = hashlib.sha256(b"hello").hexdigest()
        assert (
            archive.read("runtime_manifest.sha256").decode()
            == f"{expected}  hello.txt\n"
        )


def test_windows_entrypoints_use_repository_integrated_runtime() -> None:
    prepare = _text("scripts/windows/prepare-runtime.bat")
    start = _text("start.bat")
    update = _text("update.bat")
    verify = _text("verify.bat")
    bootstrap_cmd = _text("scripts/windows/bootstrap-runtime.bat")
    bootstrap_ps = _text("scripts/windows/bootstrap-portable.ps1")

    assert r"vendor\windows\runtime-manifest.json" in prepare
    assert r'set "PY=%ROOT%\.runtime\python\python.exe"' in prepare
    assert r"scripts\windows\prepare-runtime.bat" in start
    assert r"scripts\windows\prepare-runtime.bat" in verify
    assert "-m tools.server_instance" in start
    assert 'set "BROWSER_URL=%OPEN_URL%?fresh=' in start
    assert "浏览器不会再自动打开旧服务" in start
    assert 'set "BILI_VERIFY_NO_PAUSE=1"' in update
    assert 'start "" "%~dp0start.bat"' in update
    assert 'if /I "%BILI_VERIFY_NO_PAUSE%"=="1"' in verify
    assert "bootstrap-portable.ps1" in bootstrap_cmd
    assert ".venv" not in prepare
    assert "runtime_manifest.sha256" in bootstrap_ps
    assert "Get-FileHash" not in bootstrap_ps
    assert "System.Security.Cryptography.SHA256" in bootstrap_ps
    assert "BBDown.exe 冒烟测试失败" in bootstrap_ps
    for entrypoint in (prepare, start, verify):
        assert 'set "PYTHONUTF8=1"' in entrypoint
        assert 'set "PYTHONIOENCODING=utf-8"' in entrypoint


def test_runtime_builder_workflow_has_write_permission_and_no_lfs_dependency() -> None:
    workflow = _text(".github/workflows/build-integrated-runtime.yml")
    attributes = _text(".gitattributes")
    assert "contents: write" in workflow
    assert "tools/build_integrated_runtime.py" in workflow
    assert "requirements/dev.lock" in workflow
    assert "python-runtime.pack" in workflow
    assert "media-runtime.pack" in workflow
    assert "scripts/windows/prepare-runtime.bat" in workflow
    assert "git push origin HEAD:main" in workflow
    assert "git lfs" not in workflow.lower()
    assert "*.pack filter=lfs" not in attributes


def test_docker_defaults_to_prebuilt_multi_architecture_ghcr_image() -> None:
    compose = _text("docker/compose.yaml")
    workflow = _text(".github/workflows/docker-image.yml")
    env_default = _text("docker/.env.default")
    dockerfile = _text("docker/Dockerfile")
    assert "ghcr.io/kachekakaka/bili_workspace:latest" in compose
    assert "build:" in compose
    assert "context: .." in compose
    assert "dockerfile: docker/Dockerfile" in compose
    assert "linux/amd64,linux/arm64" in workflow
    assert "packages: write" in workflow
    assert "BUILD_LOCAL=false" in env_default
    assert "compose.build.yaml" not in _text("docker/build-and-start.sh")
    assert "requirements/runtime.lock" in dockerfile


def test_runtime_manifest_shape_when_generated(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "platform": "windows-x64",
        "packs": {
            "python": {
                "path": "vendor/windows/python-runtime.pack",
                "sha256": "a" * 64,
            },
            "media": {
                "path": "vendor/windows/media-runtime.pack",
                "sha256": "b" * 64,
            },
        },
    }
    path = tmp_path / "runtime-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert json.loads(path.read_text())["packs"]["python"]["path"].endswith(".pack")
