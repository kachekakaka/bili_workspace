#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

"$ROOT/docker/ensure-env.sh"
"$ROOT/docker/verify-config.sh"
ENV_FILE="$ROOT/docker/.env"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

if docker compose version >/dev/null 2>&1; then
  compose() { docker compose --env-file "$ENV_FILE" "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
  compose() { docker-compose --env-file "$ENV_FILE" "$@"; }
else
  echo "[ERROR] Docker Compose is unavailable." >&2
  exit 1
fi

case "${BUILD_LOCAL:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    compose -f compose.yaml -f compose.build.yaml build --pull
    compose -f compose.yaml -f compose.build.yaml up -d
    compose -f compose.yaml -f compose.build.yaml ps
    ;;
  *)
    compose -f compose.yaml pull
    compose -f compose.yaml up -d
    compose -f compose.yaml ps
    ;;
esac

echo "[OK] bili-workspace is starting. Check logs with: docker compose --env-file docker/.env logs -f --tail=100"
