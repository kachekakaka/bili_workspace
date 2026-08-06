from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from app import __version__
from tools import build_integrated_runtime as builder

ROOT = Path(__file__).resolve().parent.parent


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_builder_pins_official_sources_and_regular_git_size_limit() -> None:
    source = _text("tools/build_integrated_runtime.py")
    assert builder.RUNTIME_BUNDLE_VERSION == "0.5.6"
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
    assert source.count('"runtime_bundle_version": RUNTIME_BUNDLE_VERSION') == 3
    assert '"bili_workspace_version":' not in source


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
    verify = _text("verify.bat")
    bootstrap_cmd = _text("scripts/windows/bootstrap-runtime.bat")
    bootstrap_ps = _text("scripts/windows/bootstrap-portable.ps1")
    test_run_ps = _text("scripts/windows/new-test-run.ps1")

    assert r"vendor\windows\runtime-manifest.json" in prepare
    assert r'set "PY=%ROOT%\.runtime\python\python.exe"' in prepare
    assert r"scripts\windows\prepare-runtime.bat" in start
    assert r"scripts\windows\bootstrap-runtime.bat" in verify
    assert r"scripts\windows\new-test-run.ps1" in verify
    assert "-m tools.server_instance" in start
    assert 'set "BROWSER_URL=%OPEN_URL%?fresh=' in start
    assert "浏览器不会再自动打开旧服务" in start
    assert 'if /I "%BILI_VERIFY_NO_PAUSE%"=="1"' in verify
    assert "bootstrap-portable.ps1" in bootstrap_cmd
    assert ".venv" not in prepare
    assert "runtime_manifest.sha256" in bootstrap_ps
    assert "Resolve-ManifestPack" in bootstrap_ps
    assert "运行包大小与清单不匹配" in bootstrap_ps
    assert "Get-FileHash" not in bootstrap_ps
    assert "System.Security.Cryptography.SHA256" in bootstrap_ps
    assert "BBDown.exe 冒烟测试失败" in bootstrap_ps
    assert "VerificationRunRoot" in bootstrap_ps
    assert "runtime_bundle_version" in bootstrap_ps
    assert "bili_workspace_version" in bootstrap_ps
    assert (
        "schema 1 集成运行时清单不得同时写入 runtime_bundle_version"
        in bootstrap_ps
    )
    assert (
        "schema 2 集成运行时清单不得继续写入 bili_workspace_version"
        in bootstrap_ps
    )
    assert ".bili-workspace-test-root.json" in test_run_ps
    assert ".bili-workspace-test-run.json" in test_run_ps
    assert "--basetemp" in verify
    assert "rmdir /s /q" not in verify.lower()
    for entrypoint in (prepare, start, verify):
        assert 'set "PYTHONUTF8=1"' in entrypoint
        assert 'set "PYTHONIOENCODING=utf-8"' in entrypoint


def test_runtime_builder_workflow_uploads_artifact_without_repository_writes() -> None:
    workflow = _text(".github/workflows/build-integrated-runtime.yml")
    attributes = _text(".gitattributes")
    assert "contents: read" in workflow
    assert "tools/build_integrated_runtime.py" in workflow
    assert "requirements/dev.lock" in workflow
    assert "python-runtime.pack" in workflow
    assert "media-runtime.pack" in workflow
    assert "scripts/windows/bootstrap-runtime.bat" in workflow
    assert "scripts/windows/prepare-runtime.bat" not in workflow
    assert "BILI_VERIFY_REQUIRE_NODE" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "git commit" not in workflow
    assert "git push" not in workflow
    assert "git lfs" not in workflow.lower()
    assert "*.pack filter=lfs" not in attributes


def test_docker_defaults_to_local_build_without_registry_publication() -> None:
    compose = _text("docker/compose.yaml")
    workflow = _text(".github/workflows/docker-image.yml")
    env_default = _text("docker/.env.default")
    dockerfile = _text("docker/Dockerfile")
    assert "bili-workspace:local" in compose
    assert "build:" in compose
    assert "context: .." in compose
    assert "dockerfile: docker/Dockerfile" in compose
    assert "linux/amd64,linux/arm64" in workflow
    assert "push: false" in workflow
    assert "packages: write" not in workflow
    assert "docker/login-action" not in workflow
    assert "BUILD_LOCAL=true" in env_default
    assert "BILI_IMAGE=bili-workspace:local" in env_default
    assert "compose.build.yaml" not in _text("docker/build-and-start.sh")
    assert "requirements/runtime.lock" in dockerfile


def test_runtime_manifest_shape_when_generated(tmp_path: Path) -> None:
    python_pack = tmp_path / "python-runtime.pack"
    media_pack = tmp_path / "media-runtime.pack"
    python_pack.write_bytes(b"python")
    media_pack.write_bytes(b"media")
    manifest = builder.build_runtime_manifest(python_pack, media_pack)
    path = tmp_path / "runtime-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    generated = json.loads(path.read_text())
    assert generated["schema_version"] == 2
    assert generated["runtime_bundle_version"] == "0.5.6"
    assert "bili_workspace_version" not in generated
    assert generated["packs"]["python"]["path"].endswith(".pack")
    assert generated["packs"]["python"]["sha256"] == hashlib.sha256(
        b"python"
    ).hexdigest()


def test_checked_runtime_manifest_is_decoupled_from_application_version() -> None:
    manifest = json.loads(_text("vendor/windows/runtime-manifest.json"))
    assert __version__ == "0.7.0"
    assert manifest["schema_version"] == 2
    assert manifest["runtime_bundle_version"] == "0.5.6"
    assert "bili_workspace_version" not in manifest
    assert manifest["packs"]["python"] == {
        "path": "vendor/windows/python-runtime.pack",
        "sha256": (
            "0b20c48727a144520f8fd1676a2252079fe14c4483df669c5490ba54d36f1313"
        ),
        "size": 29284760,
    }
    assert manifest["packs"]["media"] == {
        "path": "vendor/windows/media-runtime.pack",
        "sha256": (
            "1b8ac6956c7e08110b477c8a132709a10c0d0c75360c14954397c11b3c836632"
        ),
        "size": 39154660,
    }
