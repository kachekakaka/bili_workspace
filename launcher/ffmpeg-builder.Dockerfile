# amd64 manifest of debian:bookworm-slim. Keep this digest synchronized with
# tools/build_ffmpeg_windows.py so the build record can verify the recipe.
FROM debian@sha256:362e64223cc0da95422b3b13c045186fc0a81250e765d31c025fbddf257f6143 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20260803T000000Z

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf '%s\n' \
      'Acquire::Check-Valid-Until "false";' \
      'Acquire::Retries "3";' \
      > /etc/apt/apt.conf.d/99bili-snapshot \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      gcc \
      gcc-mingw-w64-x86-64 \
      gnupg \
      libc6-dev \
      make \
      nasm \
      pkg-config \
      xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY ffmpeg-7.1.1.tar.xz ffmpeg-7.1.1.tar.xz.asc ffmpeg-devel.asc /input/
COPY build-ffmpeg-windows.sh /usr/local/bin/build-ffmpeg-windows

RUN chmod 0755 /usr/local/bin/build-ffmpeg-windows \
    && /usr/local/bin/build-ffmpeg-windows

FROM scratch AS export
COPY --from=builder /output/ /
