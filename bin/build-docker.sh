#!/usr/bin/env bash
# No arguments: clone upstream if needed, apply sources integration, build and run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/build/sideloop"
UPSTREAM_REPO='https://github.com/filippofinke/sideloop.git'
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Missing '$1'."; }
need git; need docker; need python3
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 required.'
docker info >/dev/null 2>&1 || fail 'Start Docker Desktop/Engine first.'
OS="$(uname -s)"
case "$OS" in
  Darwin)
    need socat
    [[ -S /var/run/usbmuxd ]] || fail 'Apple usbmuxd socket not found at /var/run/usbmuxd.'
    echo 'macOS: Docker Desktop 4.34+ → Settings → Resources → Network → Enable host networking.'
    echo 'macOS: Restart Docker Desktop after enabling it. The build needs this setting.'
    OVERRIDE="$ROOT/deploy/mac-host.yml"
    ;;
  Linux)
    [[ -e /dev/bus/usb ]] || echo 'WARNING: /dev/bus/usb absent. USB pairing may fail.' >&2
    OVERRIDE="$ROOT/deploy/ubuntu-host.yml"
    ;;
  *) fail 'Only Ubuntu/Linux and macOS are supported.' ;;
esac
if [[ ! -d "$UPSTREAM/.git" ]]; then
  [[ ! -e "$UPSTREAM" ]] || fail "$UPSTREAM exists but is not a Git checkout."
  mkdir -p "$ROOT/build"
  git clone --depth 1 "$UPSTREAM_REPO" "$UPSTREAM"
else
  echo 'Using existing upstream checkout to avoid unexpected upgrades.'
fi
if [[ ! -f "$UPSTREAM/.env" ]]; then
  printf 'TZ=%s\n' "${TZ:-America/New_York}" > "$UPSTREAM/.env"
  chmod 600 "$UPSTREAM/.env"
fi
mkdir -p "$UPSTREAM/data"
chmod 700 "$UPSTREAM/data"
python3 "$ROOT/overlay/patch-upstream.py" "$UPSTREAM" "$ROOT/overlay"
# Syntax and Compose checks before a potentially expensive Docker build.
python3 -m py_compile "$UPSTREAM/sideloop/server.py" "$UPSTREAM/sideloop/sources.py"
compose=( docker compose -f "$UPSTREAM/docker-compose.yml" -f "$OVERRIDE" )
"${compose[@]}" config --quiet || fail 'Docker Compose networking configuration failed.'
if [[ "$OS" == Darwin ]]; then
  "$ROOT/bin/lib/macos-relay.sh" install
fi
"${compose[@]}" up --detach --build --remove-orphans
printf '\nSideLoader dashboard: http://localhost:38080\n'
printf 'On iPhone (same Wi-Fi): http://<server-LAN-IP>:38080\n'
printf 'AltStore JSON sources: http://localhost:38080/sources\n'
printf 'Set your dashboard password before adding your Apple ID and three IPAs.\n'
