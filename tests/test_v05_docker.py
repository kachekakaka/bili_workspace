from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_dockerfile_bundles_runtime_and_fixed_bbdown_release():
    dockerfile = _text("docker/Dockerfile")
    assert (
        "python:3.11.15-slim-bookworm@sha256:"
        "d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3"
        in dockerfile
    )
    assert "BBDOWN_VERSION=1.6.3" in dockerfile
    assert "BBDown_${BBDOWN_VERSION}_${BBDOWN_RELEASE_DATE}_linux-${asset_arch}.zip" in dockerfile
    assert "apt-get install" in dockerfile and "ffmpeg" in dockerfile
    assert dockerfile.index('mkdir -p "$TMPDIR"') < dockerfile.index("apt-get install")
    assert "USER 1000:1000" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "BBDown.data" in dockerfile


def test_compose_separates_config_userdata_and_downloads():
    compose = _text("docker/compose.yaml")
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
    assert 'user: "${PUID:-1000}:${PGID:-100}"' in compose


def test_entrypoint_preserves_credentials_and_rejects_unwritable_volumes():
    entrypoint = _text("docker/entrypoint.sh")
    assert "BBDown.data" not in entrypoint
    assert "Refusing to run with root UID or GID" in entrypoint
    assert "Directory is not writable" in entrypoint
    assert "copy_if_changed /opt/bbdown/BBDown" in entrypoint
    assert "${BILI_USERDATA_DIR:-/data/userdata}" in entrypoint
    assert "${BILI_MEDIA_DIR:-/downloads}" in entrypoint
    assert "exec \"$@\"" in entrypoint


def test_default_environment_files_do_not_contain_real_secrets():
    local_env = _text("app/defaults/runtime.env.default")
    docker_env = _text("docker/.env.default")
    combined = local_env + "\n" + docker_env
    assert "BOOTSTRAP_TOKEN=" in docker_env
    assert "USERDATA_DIR=" in docker_env
    assert "SESSDATA=" not in combined
    assert "bili_jct=" not in combined
    assert "PUBLIC_BASE_URL=" in docker_env
    assert "COOKIE_SECURE=false" in docker_env
    assert "ENABLE_HSTS=false" in docker_env
    assert "PULL_IMAGE=true" in docker_env
    assert not (ROOT / ".env").is_file() or ".env" in _text(".gitignore")
    assert not (ROOT / "docker" / ".env").is_file() or "docker/.env" in _text(".gitignore")


def test_qnap_helper_scripts_are_present_and_hardened():
    verify = (ROOT / "docker" / "verify-config.sh").read_text(encoding="utf-8")
    start = (ROOT / "docker" / "build-and-start.sh").read_text(encoding="utf-8")
    entry = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "TRUSTED_HOSTS must not contain *" in verify
    assert "PUID and PGID must both be non-zero" in verify
    assert '"$(id -u)" -eq 0' in entry
    assert '"$(id -g)" -eq 0' in entry
    assert "docker compose --project-directory" in verify
    assert "build --pull" in start
    assert 'case "${PULL_IMAGE:-true}"' in start
    assert 'docker image inspect "$image"' in start
    assert "compose up -d --no-build" in start
    assert "Imported image is not available locally" in start
    assert "docker/compose.yaml" in start
    assert "DOTNET_BUNDLE_EXTRACT_BASE_DIR" in entry
    assert 'exec "$@"' in entry


def test_docker_runtime_directories_are_explicit():
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8")
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
    persistence_detail_docs = (
        "docs/需求文档.md",
        "docs/设计文档.md",
        "docs/字段契约.md",
        "docs/运维/Docker镜像打包与离线交付.md",
    )
    for name in persistence_detail_docs:
        content = _text(name)
        for target in ("/data/config", "/data/userdata", "/downloads"):
            assert target in content, f"{name} 缺少 {target}"

    navigation_docs = {
        "README.md": ("docs/README.md", "docs/运维/README.md"),
        "docs/README.md": ("字段契约.md", "运维/README.md"),
    }
    for name, entries in navigation_docs.items():
        content = _text(name)
        for entry in entries:
            assert entry in content, f"{name} 缺少专责文档入口 {entry}"

    for name in (*navigation_docs, *persistence_detail_docs):
        content = _text(name)
        for legacy in ("/data/media", "/data/cache", "/data/tmp"):
            assert legacy not in content, f"{name} 仍引用旧目录 {legacy}"

    readme = _text("README.md")
    for directory in ("config/", "userdata/", "downloads/"):
        assert directory in readme
    assert "docs/README.md" in readme
    assert "userdata/*" in _text(".gitignore")


def test_docker_packaging_guide_covers_offline_image_import():
    guide = _text("docs/运维/Docker镜像打包与离线交付.md")
    for token in (
        "Container Station",
        "docker load",
        "sha256sum",
        "PULL_IMAGE=false",
        "--no-build",
    ):
        assert token in guide
    assert not (ROOT / "docs" / "运维" / "QNAP_Docker部署指南.md").exists()
