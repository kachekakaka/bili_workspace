from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_dockerfile_bundles_runtime_and_fixed_bbdown_release():
    dockerfile = _text("Dockerfile")
    assert "python:3.13-slim-bookworm" in dockerfile
    assert "BBDOWN_VERSION=1.6.3" in dockerfile
    assert "BBDown_${BBDOWN_VERSION}_${BBDOWN_RELEASE_DATE}_linux-${asset_arch}.zip" in dockerfile
    assert "apt-get install" in dockerfile and "ffmpeg" in dockerfile
    assert "USER 1000:1000" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "BBDown.data" in dockerfile


def test_compose_separates_config_userdata_and_downloads():
    compose = _text("compose.yaml")
    for target in ("/data/config", "/data/userdata", "/downloads"):
        assert f"target: {target}" in compose
    assert "target: /data/media" not in compose
    assert "BILI_DATABASE_PATH: /data/userdata/bili_workspace.db" in compose
    assert "BILI_AUTH_REQUIRED: \"true\"" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "docker.sock" not in compose
    assert "privileged:" not in compose


def test_entrypoint_preserves_credentials_and_rejects_unwritable_volumes():
    entrypoint = _text("docker/entrypoint.sh")
    assert "BBDown.data" not in entrypoint
    assert "Directory is not writable" in entrypoint
    assert "copy_if_changed /opt/bbdown/BBDown" in entrypoint
    assert "${BILI_USERDATA_DIR:-/data/userdata}" in entrypoint
    assert "${BILI_MEDIA_DIR:-/downloads}" in entrypoint
    assert "exec \"$@\"" in entrypoint


def test_default_environment_files_do_not_contain_real_secrets():
    local_env = _text(".env.default")
    docker_env = _text("docker/.env.default")
    combined = local_env + "\n" + docker_env
    assert "BOOTSTRAP_TOKEN=" in docker_env
    assert "USERDATA_DIR=" in docker_env
    assert "SESSDATA=" not in combined
    assert "bili_jct=" not in combined
    assert "PUBLIC_BASE_URL=" in docker_env
    assert "COOKIE_SECURE=false" in docker_env
    assert "ENABLE_HSTS=false" in docker_env
    assert not (ROOT / ".env").is_file() or ".env" in _text(".gitignore")
    assert not (ROOT / "docker" / ".env").is_file() or "docker/.env" in _text(".gitignore")


def test_qnap_helper_scripts_are_present_and_hardened():
    verify = (ROOT / "docker" / "verify-config.sh").read_text(encoding="utf-8")
    start = (ROOT / "docker" / "build-and-start.sh").read_text(encoding="utf-8")
    entry = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "TRUSTED_HOSTS must not contain *" in verify
    assert "docker compose --env-file" in verify
    assert "build --pull" in start
    assert "DOTNET_BUNDLE_EXTRACT_BASE_DIR" in entry
    assert 'exec "$@"' in entry


def test_docker_runtime_directories_are_explicit():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for value in (
        "BILI_USERDATA_DIR=/data/userdata",
        "BILI_DATABASE_PATH=/data/userdata/bili_workspace.db",
        "BILI_MEDIA_DIR=/downloads",
        "HOME=/data/userdata/home",
        "XDG_CACHE_HOME=/data/userdata/cache",
        "DOTNET_BUNDLE_EXTRACT_BASE_DIR=/data/userdata/cache/dotnet",
        "TMPDIR=/data/userdata/tmp",
    ):
        assert value in dockerfile
    assert "DOTNET_BUNDLE_EXTRACT_BASE_DIR: /data/userdata/cache/dotnet" in compose


def test_current_persistence_documentation_matches_runtime_layout():
    current_docs = (
        "README.md",
        "docs/README.md",
        "docs/QNAP_Docker部署指南.md",
        "docs/需求落实清单.md",
        "docs/产品需求与架构基线.md",
        "config/README.md",
        "userdata/README.md",
    )
    for name in current_docs:
        content = _text(name)
        for target in ("/data/config", "/data/userdata", "/downloads"):
            assert target in content, f"{name} 缺少 {target}"
        for legacy in ("/data/media", "/data/cache", "/data/tmp"):
            assert legacy not in content, f"{name} 仍引用旧目录 {legacy}"

    readme = _text("README.md")
    for directory in ("config/", "userdata/", "downloads/"):
        assert directory in readme
    assert "docs/README.md" in readme
    assert "userdata/README.md" in readme
    assert "!userdata/README.md" in _text(".gitignore")
