#!/usr/bin/env bash
# Build and run SideLoader on macOS or Ubuntu. The checkout, IPA cache, and
# runtime state stay in ignored build/sideloop/ (never synced to GitHub).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
UPSTREAM="$ROOT_DIR/build/sideloop"
UPSTREAM_REPO='https://github.com/filippofinke/sideloop.git'
START=true
OPEN=false
LOGS=false

usage() {
  cat <<'USAGE'
Build SideLoader's Docker server locally on macOS or Ubuntu.

Usage: ./bin/build-docker.sh [--no-start] [--open] [--logs] [--help]

  (no args)    Clone upstream into build/ if missing, apply the source overlay,
               validate Docker networking, build and start the server.
  --no-start   Build the Docker image but don't start or restart containers.
  --open       Open the local dashboard in the default browser after starting.
  --logs       Follow container logs after starting; Ctrl-C stops log viewing.
  --help       Show this help.

The upstream checkout and all persistent data stay in ignored build/.
The upstream is never upgraded automatically on subsequent builds.
This script is local-only: it never pushes to GitHub or runs GitHub Actions.
USAGE
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-start) START=false ;;
    --open) OPEN=true ;;
    --logs) LOGS=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done
if [[ "$START" != true && ( "$OPEN" == true || "$LOGS" == true ) ]]; then
  echo '--open and --logs require the server to start.' >&2; exit 2
fi
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 1; }; }
for tool in git docker python3; do need "$tool"; done
docker compose version >/dev/null 2>&1 || { echo 'Docker Compose v2 is required.' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Start Docker Desktop or Docker Engine first.' >&2; exit 1; }

case "$(uname -s)" in
  Darwin)
    [[ -S /var/run/usbmuxd ]] || { echo 'Missing /var/run/usbmuxd socket (Apple Mobile Device service).' >&2; exit 1; }
    OVERRIDE="$ROOT_DIR/deploy/mac-host.yml"
    echo 'macOS requires Docker Desktop 4.34+ with Settings > Resources > Network > host networking enabled.'
    ;;
  Linux)
    OVERRIDE="$ROOT_DIR/deploy/ubuntu-host.yml"
    [[ -e /dev/bus/usb ]] || echo 'Warning: USB devices not present; initial USB pairing may fail.' >&2
    ;;
  *) echo 'This build supports only macOS and Ubuntu/Linux.' >&2; exit 1 ;;
esac

# No build or runtime artifacts are checked into Git. Keep the upstream version
# stable between runs to avoid surprising signing/provisioning regressions.
if [[ ! -d "$UPSTREAM/.git" ]]; then
  [[ ! -e "$UPSTREAM" ]] || { echo "Not a Git checkout: $UPSTREAM" >&2; exit 1; }
  mkdir -p "$ROOT_DIR/build"
  git clone --depth 1 "$UPSTREAM_REPO" "$UPSTREAM"
else
  echo 'Using existing upstream checkout (no automatic upstream pull).'
fi
if [[ ! -f "$UPSTREAM/.env" ]]; then
  printf 'TZ=%s\n' "${TZ:-America/New_York}" > "$UPSTREAM/.env"
  chmod 600 "$UPSTREAM/.env"
fi
mkdir -p "$UPSTREAM/data"
chmod 700 "$UPSTREAM/data"
python3 "$ROOT_DIR/overlay/patch-upstream.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 -m py_compile "$UPSTREAM/sideloop/server.py" "$UPSTREAM/sideloop/sources.py"
compose=( docker compose -f "$UPSTREAM/docker-compose.yml" -f "$OVERRIDE" )
"${compose[@]}" config --quiet || { echo 'Docker Compose configuration is invalid.' >&2; exit 1; }

if [[ "$START" == true && "$(uname -s)" == Darwin ]]; then
  "$ROOT_DIR/bin/lib/macos-relay.sh" install
fi
if [[ "$START" == true ]]; then
  "${compose[@]}" up --detach --build --remove-orphans
else
  "${compose[@]}" build
fi
printf '\nSideLoader version: %s\n' "$(cat "$ROOT_DIR/VERSION")"
printf 'Local build: %s\n' "$UPSTREAM"
printf 'GitHub: unchanged (no push or GitHub Actions).\n'
if [[ "$START" == true ]]; then
  printf 'Dashboard: http://localhost:38080\n'
  printf 'iPhone on same Wi-Fi: http://<server-LAN-IP>:38080\n'
  printf 'AltStore sources: http://localhost:38080/sources\n'
  printf 'Runtime data is preserved across builds in build/sideloop/data/.\n'
  if [[ "$OPEN" == true ]]; then
    case "$(uname -s)" in
      Darwin) open 'http://localhost:38080' ;;
      Linux) command -v xdg-open >/dev/null && xdg-open 'http://localhost:38080' || true ;;
    esac
  fi
  if [[ "$LOGS" == true ]]; then "${compose[@]}" logs -f app; fi
else
  printf 'Docker images built; existing containers were not started or restarted.\n'
fi
