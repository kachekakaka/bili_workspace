#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DEFAULT_FILE="$ROOT/docker/.env.default"
ACTUAL_FILE="$ROOT/docker/.env"

[ -f "$DEFAULT_FILE" ] || { echo "[ERROR] Missing $DEFAULT_FILE" >&2; exit 1; }
if [ -L "$ACTUAL_FILE" ]; then
  echo "[ERROR] docker/.env must not be a symbolic link" >&2
  exit 1
fi
if [ ! -e "$ACTUAL_FILE" ]; then
  cp "$DEFAULT_FILE" "$ACTUAL_FILE"
  chmod 600 "$ACTUAL_FILE" 2>/dev/null || true
  echo "[INFO] Created docker/.env from docker/.env.default"
  exit 0
fi
[ -f "$ACTUAL_FILE" ] || { echo "[ERROR] docker/.env is not a regular file" >&2; exit 1; }

missing_file="${ACTUAL_FILE}.missing.$$"
: > "$missing_file"
trap 'rm -f "$missing_file"' EXIT HUP INT TERM
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|'#'*) continue ;;
  esac
  key=${line%%=*}
  case "$key" in
    ''|*[!A-Za-z0-9_]*) continue ;;
  esac
  if ! grep -Eq "^[[:space:]]*${key}=" "$ACTUAL_FILE"; then
    printf '%s\n' "$line" >> "$missing_file"
  fi
done < "$DEFAULT_FILE"

if [ -s "$missing_file" ]; then
  {
    printf '\n# Added automatically from the newer .default template.\n'
    cat "$missing_file"
  } >> "$ACTUAL_FILE"
  echo "[INFO] Added new settings to docker/.env without replacing existing values"
fi
