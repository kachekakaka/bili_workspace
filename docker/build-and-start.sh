#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

"$ROOT/docker/ensure-env.sh"
"$ROOT/docker/verify-config.sh"
ENV_FILE="$ROOT/docker/.env"
COMPOSE_FILE="$ROOT/docker/compose.yaml"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

if docker compose version >/dev/null 2>&1; then
  compose() {
    docker compose --project-directory "$ROOT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  }
elif command -v docker-compose >/dev/null 2>&1; then
  compose() {
    docker-compose --project-directory "$ROOT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  }
else
  echo "[ERROR] Docker Compose is unavailable." >&2
  exit 1
fi

case "${BUILD_LOCAL:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    compose build --pull
    compose up -d
    compose ps
    ;;
  *)
    compose pull
    compose up -d
    compose ps
    ;;
esac

echo "[OK] bili-workspace is starting. Check logs with: docker compose --project-directory '$ROOT' --env-file '$ENV_FILE' -f '$COMPOSE_FILE' logs -f --tail=100"
