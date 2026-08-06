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

image="${BILI_IMAGE:-bili-workspace:local}"

case "${BUILD_LOCAL:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    compose build --pull
    compose up -d --no-build
    ;;
  0|false|FALSE|no|NO|off|OFF)
    case "${PULL_IMAGE:-true}" in
      1|true|TRUE|yes|YES|on|ON)
        compose pull
        ;;
      0|false|FALSE|no|NO|off|OFF)
        if ! docker image inspect "$image" >/dev/null 2>&1; then
          echo "[ERROR] Imported image is not available locally: $image" >&2
          echo "[ERROR] Import the offline package with Container Station or docker load first." >&2
          exit 1
        fi
        ;;
      *)
        echo "[ERROR] PULL_IMAGE must be true or false" >&2
        exit 1
        ;;
    esac
    compose up -d --no-build
    ;;
  *)
    echo "[ERROR] BUILD_LOCAL must be true or false" >&2
    exit 1
    ;;
esac

compose ps

echo "[OK] bili-workspace is starting. Check logs with: docker compose --project-directory '$ROOT' --env-file '$ENV_FILE' -f '$COMPOSE_FILE' logs -f --tail=100"
