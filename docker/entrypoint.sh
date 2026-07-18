#!/bin/sh
set -eu

umask 077

for directory in \
  "${BILI_CONFIG_DIR:-/data/config}" \
  "${BILI_USERDATA_DIR:-/data/userdata}" \
  "${BILI_MEDIA_DIR:-/downloads}" \
  "${BILI_CACHE_DIR:-/data/userdata/cache}" \
  "${BILI_TEMP_DIR:-/data/userdata/tmp}"; do
  mkdir -p "$directory"
  if [ ! -w "$directory" ]; then
    echo "[fatal] Directory is not writable by container user $(id -u):$(id -g): $directory" >&2
    echo "[fatal] Fix the QNAP shared-folder permissions or PUID/PGID mapping." >&2
    exit 73
  fi
done

mkdir -p "${HOME:-/data/userdata/home}" "${XDG_CACHE_HOME:-/data/userdata/cache}" \
  "${DOTNET_BUNDLE_EXTRACT_BASE_DIR:-/data/userdata/cache/dotnet}" "${TMPDIR:-/data/userdata/tmp}"

bbdown_dir="${BILI_BBDOWN_DIR:-${BILI_CONFIG_DIR:-/data/config}/bbdown}"
mkdir -p "$bbdown_dir"
if [ ! -w "$bbdown_dir" ]; then
  echo "[fatal] BBDown credential directory is not writable: $bbdown_dir" >&2
  exit 73
fi

copy_if_changed() {
  source_file="$1"
  target_file="$2"
  mode="$3"
  if [ ! -f "$target_file" ] || ! cmp -s "$source_file" "$target_file"; then
    temp_file="${target_file}.new.$$"
    cp "$source_file" "$temp_file"
    chmod "$mode" "$temp_file"
    mv -f "$temp_file" "$target_file"
  fi
}

copy_if_changed /opt/bbdown/BBDown "$bbdown_dir/BBDown" 0755
copy_if_changed /opt/bbdown/ffmpeg "$bbdown_dir/ffmpeg" 0755
copy_if_changed /opt/bbdown/checksums.sha256 "$bbdown_dir/checksums.sha256" 0644

# Configuration and BBDown credentials live in /data/config; SQLite, indexes,
# task logs and caches live in /data/userdata; completed media live in /downloads.
# The immutable application and runtime are supplied by the image.
exec "$@"
