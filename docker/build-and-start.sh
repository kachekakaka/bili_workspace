#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

"$ROOT/docker/ensure-env.sh"
"$ROOT/docker/verify-config.sh"
ENV_FILE="$ROOT/docker/.env"

if docker compose version >/dev/null 2>&1; then
  compose() { docker compose --env-file "$ENV_FILE" "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
  compose() { docker-compose --env-file "$ENV_FILE" "$@"; }
else
  echo "[ERROR] Docker Compose is unavailable." >&2
  exit 1
fi

compose build --pull
compose up -d
compose ps

echo "[OK] bili-workspace is starting. Check logs with: docker compose --env-file docker/.env logs -f --tail=100"
