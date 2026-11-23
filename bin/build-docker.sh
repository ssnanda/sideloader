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
NO_CACHE=false
BUMP=true
BUMP_ARGS=()
RESET_USER=false

usage() {
  cat <<'USAGE'
Build SideLoader's Docker server locally on macOS or Ubuntu.

Usage: ./bin/build-docker.sh [--no-start] [--open] [--logs] [--no-cache]
                              [--reset-user]
                              [--skip-bump] [--no-push] [--help]

  (no args)    If the checkout has uncommitted changes, run bin/bump-version.sh
               first (interactive), then clone upstream into build/ if missing,
               apply the source overlay, validate Docker networking, build and
               start the server.
  --no-start   Build the Docker image but don't start or restart containers.
  --open       Open the local dashboard in the default browser after starting.
  --logs       Follow container logs after starting; Ctrl-C stops log viewing.
  --no-cache   Force Docker to rebuild all image layers rather than reuse cache.
  --reset-user Generate a new dashboard username and password, invalidating all sessions.
  --skip-bump  Build pending changes without running bump-version.sh.
  --no-push    Pass --no-push to bump-version.sh (commit locally only).
  --help       Show this help.

The upstream checkout and all persistent data stay in ignored build/.
The upstream is never upgraded automatically on subsequent builds.
Builds run locally only. The automatic bump-version.sh step commits and (unless
--no-push) pushes pending changes after its own confirmation prompt.
USAGE
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-start) START=false ;;
    --open) OPEN=true ;;
    --logs) LOGS=true ;;
    --no-cache) NO_CACHE=true ;;
    --reset-user) RESET_USER=true ;;
    --skip-bump) BUMP=false ;;
    --no-push) BUMP_ARGS+=(--no-push) ;;
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

# Pending edits: version/commit them first so the image reports the right
# VERSION. bump-version.sh prompts before changing anything; cancelling there
# continues the build with the uncommitted changes.
if [[ "$BUMP" == true && -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'Uncommitted changes detected; running bump-version.sh before building.'
  "$ROOT_DIR/bin/bump-version.sh" ${BUMP_ARGS[@]+"${BUMP_ARGS[@]}"}
fi

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
credential_args=()
if [[ "$RESET_USER" == true ]]; then credential_args+=(--reset); fi
IFS=$'\t' read -r SIDELOADER_USER NEW_LOGIN_PASSWORD < <(
  python3 "$ROOT_DIR/overlay/local_credentials.py" "$UPSTREAM/data/ui.json" "${credential_args[@]}"
)
if [[ -n "$NEW_LOGIN_PASSWORD" ]]; then
  printf '\nNew SideLoader login (shown once - save it now):\n'
  printf '  Username: %s\n' "$SIDELOADER_USER"
  printf '  Password: %s\n\n' "$NEW_LOGIN_PASSWORD"
fi
python3 "$ROOT_DIR/overlay/patch-upstream.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-v2.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-navigation.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-device-health.py" "$UPSTREAM"
python3 "$ROOT_DIR/overlay/patch-github.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-retry-guard.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-apple-verification.py" "$UPSTREAM"
python3 "$ROOT_DIR/overlay/patch-install-workflow.py" "$UPSTREAM"
python3 "$ROOT_DIR/overlay/patch-backend-info.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-sideloop-version.py" "$UPSTREAM" "$ROOT_DIR/overlay" "$ROOT_DIR/VERSION"
python3 "$ROOT_DIR/overlay/patch-responsive-ui.py" "$UPSTREAM"
python3 "$ROOT_DIR/overlay/patch-one-attempt.py" "$UPSTREAM"
python3 "$ROOT_DIR/overlay/patch-log-maintenance.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-apps-dashboard.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-apple-2fa-safety.py" "$UPSTREAM"
python3 "$ROOT_DIR/overlay/patch-auto-resign.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-screen-flow.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-android.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-top-navigation.py" "$UPSTREAM" "$ROOT_DIR/overlay"
python3 "$ROOT_DIR/overlay/patch-local-login.py" "$UPSTREAM"
python3 -m py_compile "$UPSTREAM/sideloop/server.py" "$UPSTREAM/sideloop/auth.py" "$UPSTREAM/sideloop/sources.py" "$UPSTREAM/sideloop/installed.py" "$UPSTREAM/sideloop/diagnostics.py" "$UPSTREAM/sideloop/github_sources.py" "$UPSTREAM/sideloop/github_scan.py" "$UPSTREAM/sideloop/retry_guard.py" "$UPSTREAM/sideloop/account.py" "$UPSTREAM/sideloop/backend_info.py" "$UPSTREAM/sideloop/sideloop_info.py" "$UPSTREAM/sideloop/device_app_inventory.py" "$UPSTREAM/sideloop/android.py" "$UPSTREAM/sideloop/watcher.py"
compose=( docker compose -f "$UPSTREAM/docker-compose.yml" -f "$OVERRIDE" )
"${compose[@]}" config --quiet || { echo 'Docker Compose configuration is invalid.' >&2; exit 1; }

if [[ "$START" == true && "$(uname -s)" == Darwin ]]; then
  "$ROOT_DIR/bin/lib/macos-relay.sh" install
fi
# Android over USB on macOS goes through the Mac's adb server (see
# deploy/mac-host.yml). Start it if platform-tools is installed; never install.
if [[ "$START" == true && "$(uname -s)" == Darwin ]]; then
  if command -v adb >/dev/null 2>&1; then
    adb start-server >/dev/null 2>&1 && echo 'Mac adb server running (Android USB + Wi-Fi).' \
      || echo 'Warning: could not start the Mac adb server; Android USB unavailable.' >&2
  else
    echo 'Android USB needs adb on the Mac (Android platform-tools); Wi-Fi install still works.'
  fi
fi
printf '\nAll SideLoader source overlays validated.\n'
printf 'Sideloop upstream base: %s (plus SideLoader overlays %s)\n' "$(git -C "$UPSTREAM" rev-parse --short HEAD)" "$(cat "$ROOT_DIR/VERSION")"
if [[ "$NO_CACHE" == true ]]; then
  echo 'Starting a FULL Docker image rebuild (--no-cache).'
  "${compose[@]}" build --no-cache
  if [[ "$START" == true ]]; then
    echo 'Starting newly rebuilt Docker image...'
    "${compose[@]}" up --detach --no-build --remove-orphans
  fi
elif [[ "$START" == true ]]; then
  echo 'Building changed Docker image layers and starting the container (Docker cache enabled)...'
  "${compose[@]}" up --detach --build --remove-orphans
else
  echo 'Building Docker image (Docker cache enabled)...'
  "${compose[@]}" build
fi
printf 'Local build: %s\n' "$UPSTREAM"
printf 'GitHub Actions: not used (local build).\n'

login_summary() {
  printf '\n================================================================\n'
  printf '  SideLoader v%s\n' "$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")"
  printf '  URL:      http://localhost:38080\n'
  printf '  Username: %s\n' "$SIDELOADER_USER"
  if [[ -n "$NEW_LOGIN_PASSWORD" ]]; then
    printf '  Password: %s   (shown once - save it now)\n' "$NEW_LOGIN_PASSWORD"
  else
    printf '  Password: unchanged (shown only when created or reset)\n'
  fi
  printf '  Reset:    ./bin/build-docker.sh --reset-user\n'
  printf '================================================================\n'
}

if [[ "$START" == true ]]; then
  printf 'iPhone on same Wi-Fi: http://<server-LAN-IP>:38080\n'
  printf 'AltStore sources: http://localhost:38080/sources\n'
  printf 'Runtime data is preserved across builds in build/sideloop/data/.\n'
  printf 'Docker project status:\n'
  "${compose[@]}" ps
  login_summary
  if [[ "$OPEN" == true ]]; then
    case "$(uname -s)" in
      Darwin) open 'http://localhost:38080' ;;
      Linux) command -v xdg-open >/dev/null && xdg-open 'http://localhost:38080' || true ;;
    esac
  fi
  if [[ "$LOGS" == true ]]; then "${compose[@]}" logs -f app; fi
else
  printf 'Docker images built; existing containers were not started or restarted.\n'
  login_summary
fi
