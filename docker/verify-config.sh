#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
"$ROOT/docker/ensure-env.sh"
ENV_FILE="$ROOT/docker/.env"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

required="CONFIG_DIR MEDIA_DIR CACHE_DIR TEMP_DIR PUID PGID"
for name in $required; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "[ERROR] $name is empty in docker/.env" >&2
    exit 1
  fi
done

case "${TRUSTED_HOSTS:-}" in
  *\**) echo "[ERROR] TRUSTED_HOSTS must not contain *" >&2; exit 1 ;;
esac
case "${TRUSTED_PROXY_IPS:-}" in
  *\**) echo "[ERROR] TRUSTED_PROXY_IPS must not contain *" >&2; exit 1 ;;
esac
case "${PUBLIC_BASE_URL:-}" in
  '') : ;;
  https://*) : ;;
  *) echo "[ERROR] PUBLIC_BASE_URL must be blank or use https://" >&2; exit 1 ;;
esac
case "${PUID}:${PGID}" in
  *[!0-9:]*|:|*:|:* ) echo "[ERROR] PUID and PGID must be numeric" >&2; exit 1 ;;
esac
case "${HTTP_PORT:-3398}" in
  ''|*[!0-9]*) echo "[ERROR] HTTP_PORT must be numeric" >&2; exit 1 ;;
esac
if [ "${HTTP_PORT:-3398}" -lt 1 ] || [ "${HTTP_PORT:-3398}" -gt 65535 ]; then
  echo "[ERROR] HTTP_PORT must be between 1 and 65535" >&2
  exit 1
fi

for path in "$CONFIG_DIR" "$MEDIA_DIR" "$CACHE_DIR" "$TEMP_DIR"; do
  if [ ! -d "$path" ]; then
    echo "[ERROR] mapped directory does not exist: $path" >&2
    exit 1
  fi
  if [ ! -w "$path" ]; then
    echo "[ERROR] current account cannot write mapped directory: $path" >&2
    exit 1
  fi
done

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$ENV_FILE" config >/dev/null
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose --env-file "$ENV_FILE" config >/dev/null
  else
    echo "[ERROR] Docker is installed but Compose is unavailable" >&2
    exit 1
  fi
else
  echo "[WARN] Docker command not found; only env and directory checks were performed." >&2
fi

echo "[OK] QNAP Docker configuration passed static checks."
