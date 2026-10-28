#!/usr/bin/env bash
# Stop SideLoader's Docker services and macOS USB relay. Preserve data unless
# the caller explicitly confirms a purge; never remove an iPhone application.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT_DIR/build/sideloop"
PURGE_DATA=false
REMOVE_IMAGE=false
ASSUME_YES=false

usage() {
  cat <<'HELP'
Uninstall the local SideLoader server on macOS or Ubuntu/Linux.

Usage: ./bin/uninstall.sh [--purge-data] [--remove-image] [--yes] [--help]

  (no args)       Stop and remove SideLoader Docker containers and its macOS
                  USB relay. Preserve IPAs, device pairing, Apple settings,
                  GitHub source/token data, signing state, and Docker images.
  --purge-data    ALSO permanently delete build/sideloop/data, the saved .env,
                  and the project's anisette Docker volume.
  --remove-image  ALSO remove the locally tagged 'sideloop' Docker image.
  --yes           Confirm destructive optional actions without prompting.
  --help          Show this help.

The Git repository, upstream source checkout, and files installed on an
actual iPhone are never deleted. You can run this script more than once.
HELP
}

while (($#)); do
  case "$1" in
    --purge-data) PURGE_DATA=true ;;
    --remove-image) REMOVE_IMAGE=true ;;
    --yes) ASSUME_YES=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$(uname -s)" in
  Darwin) PLATFORM=mac; OVERRIDE="$ROOT_DIR/deploy/mac-host.yml" ;;
  Linux) PLATFORM=linux; OVERRIDE="$ROOT_DIR/deploy/ubuntu-host.yml" ;;
  *) echo 'Uninstall supports macOS or Linux only.' >&2; exit 1 ;;
esac

# Never follow an unexpected symlink when removing a checkout's secrets.
if [[ -L "$UPSTREAM" ]]; then
  echo 'Refusing to uninstall: build/sideloop is a symlink.' >&2
  exit 1
fi
if [[ "$PURGE_DATA" == true && -L "$UPSTREAM/data" ]]; then
  echo 'Refusing to purge: build/sideloop/data is a symlink.' >&2
  exit 1
fi

if [[ "$PURGE_DATA" == true || "$REMOVE_IMAGE" == true ]]; then
  if [[ "$ASSUME_YES" != true ]]; then
    if [[ ! -t 0 ]]; then
      echo 'Destructive options require interactive confirmation or --yes.' >&2
      exit 2
    fi
    echo 'WARNING: the selected options will permanently delete SideLoader data and/or its Docker image.'
    read -r -p 'Type DELETE to continue: ' answer
    if [[ "$answer" != DELETE ]]; then
      echo 'Uninstall cancelled; no changes made.'
      exit 1
    fi
  fi
fi

if [[ -f "$UPSTREAM/docker-compose.yml" ]]; then
  command -v docker >/dev/null 2>&1 || { echo 'Docker is required to stop the SideLoader containers.' >&2; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo 'Docker Compose v2 is required.' >&2; exit 1; }
  docker info >/dev/null 2>&1 || { echo 'Start Docker Engine or Docker Desktop first.' >&2; exit 1; }
  [[ -f "$OVERRIDE" ]] || { echo "Missing SideLoader compose override: $OVERRIDE" >&2; exit 1; }
  echo 'Removing SideLoader (sideloop) Docker containers...'
  options=(down --remove-orphans)
  if [[ "$PURGE_DATA" == true ]]; then options+=(--volumes); fi
  (cd "$UPSTREAM" && docker compose -p sideloop -f docker-compose.yml -f "$OVERRIDE" "${options[@]}")
else
  echo 'SideLoader Docker checkout not found; nothing to stop via Compose.'
fi

if [[ "$PLATFORM" == mac ]]; then
  "$ROOT_DIR/bin/lib/macos-relay.sh" uninstall
fi

if [[ "$REMOVE_IMAGE" == true ]]; then
  command -v docker >/dev/null 2>&1 || { echo 'Docker is required to remove the image.' >&2; exit 1; }
  if docker image inspect sideloop >/dev/null 2>&1; then
    echo 'Removing locally tagged SideLoader image (sideloop)...'
    docker image rm sideloop
  else
    echo 'SideLoader image not present; nothing to remove.'
  fi
fi

if [[ "$PURGE_DATA" == true ]]; then
  if [[ -d "$UPSTREAM" ]]; then
    echo 'Permanently removing SideLoader saved data and .env...'
    rm -rf -- "$UPSTREAM/data"
    rm -f -- "$UPSTREAM/.env"
  fi
  echo 'Saved SideLoader data purged. The upstream source checkout is retained.'
else
  echo 'Saved IPA files, pairing, credentials, sources, signing data and Docker volumes were preserved.'
fi

echo 'SideLoader local server uninstalled. No iPhone apps were removed.'