# syntax=docker/dockerfile:1.7
FROM python:3.13-slim-bookworm

ARG TARGETARCH
ARG BBDOWN_VERSION=1.6.3
ARG BBDOWN_RELEASE_DATE=20240814

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BILI_APP_MODE=docker \
    BILI_CONFIG_DIR=/data/config \
    BILI_USERDATA_DIR=/data/userdata \
    BILI_DATABASE_PATH=/data/userdata/bili_workspace.db \
    BILI_MEDIA_DIR=/downloads \
    BILI_CACHE_DIR=/data/userdata/cache \
    BILI_TEMP_DIR=/data/userdata/tmp \
    BILI_BBDOWN_DIR=/data/config/bbdown \
    BILI_HOST=0.0.0.0 \
    BILI_PORT=3398 \
    BILI_AUTH_REQUIRED=true \
    HOME=/data/userdata/home \
    XDG_CACHE_HOME=/data/userdata/cache \
    DOTNET_BUNDLE_EXTRACT_BASE_DIR=/data/userdata/cache/dotnet \
    TMPDIR=/data/userdata/tmp \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl ffmpeg libicu72 tini unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/runtime.lock /app/requirements-runtime.lock
RUN python -m pip install --no-cache-dir -r /app/requirements-runtime.lock

# Pull the official, fixed BBDown v1.6.3 Linux release matching the build
# architecture. The build fails if the archive, executable, or smoke test is
# invalid. BBDown is copied into the writable config volume by entrypoint so
# its BBDown.data credential file never lives in an image layer.
RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64|x86_64) asset_arch='x64' ;; \
      arm64|aarch64) asset_arch='arm64' ;; \
      *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    archive="BBDown_${BBDOWN_VERSION}_${BBDOWN_RELEASE_DATE}_linux-${asset_arch}.zip"; \
    url="https://github.com/nilaoda/BBDown/releases/download/${BBDOWN_VERSION}/${archive}"; \
    mkdir -p /opt/bbdown /tmp/bbdown; \
    curl --fail --location --retry 4 --retry-all-errors --connect-timeout 20 \
      --output "/tmp/${archive}" "$url"; \
    unzip -q "/tmp/${archive}" -d /tmp/bbdown; \
    bbdown_bin="$(find /tmp/bbdown -type f -name BBDown -print -quit)"; \
    test -n "$bbdown_bin"; \
    install -m 0755 "$bbdown_bin" /opt/bbdown/BBDown; \
    /opt/bbdown/BBDown --help >/tmp/bbdown-help.txt 2>&1; \
    test -s /tmp/bbdown-help.txt; \
    printf '%s\n' '#!/bin/sh' 'exec /usr/bin/ffmpeg "$@"' > /opt/bbdown/ffmpeg; \
    chmod 0755 /opt/bbdown/ffmpeg; \
    cd /opt/bbdown; sha256sum BBDown ffmpeg > checksums.sha256; \
    rm -rf "/tmp/${archive}" /tmp/bbdown /tmp/bbdown-help.txt

COPY app /app/app
COPY web /app/web
COPY config /app/config
COPY .env.default /app/.env.default
COPY THIRD_PARTY_NOTICES.md /app/THIRD_PARTY_NOTICES.md
COPY LICENSES /app/LICENSES
COPY docker/entrypoint.sh /usr/local/bin/bili-workspace-entrypoint
COPY docker/healthcheck.py /app/docker/healthcheck.py

RUN chmod 0755 /usr/local/bin/bili-workspace-entrypoint \
    && groupadd --gid 1000 bili \
    && useradd --uid 1000 --gid 1000 --home-dir /nonexistent --shell /usr/sbin/nologin bili \
    && mkdir -p /data/config /data/userdata /downloads \
    && chown -R 1000:1000 /data /downloads

USER 1000:1000
EXPOSE 3398
VOLUME ["/data/config", "/data/userdata", "/downloads"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/app/docker/healthcheck.py"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/bili-workspace-entrypoint"]
CMD ["python", "-m", "app"]
