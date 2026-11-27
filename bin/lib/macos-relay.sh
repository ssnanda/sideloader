#!/usr/bin/env bash
# Keep the USB mux socket accessible to Docker Desktop's opt-in host networking,
# while binding the Python TCP relay ONLY to the Mac loopback interface.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LABEL="local.minisideload.usbmux-relay"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCOPE="gui/$(id -u)"
RELAY="$ROOT_DIR/bin/lib/usbmux-relay.py"
# Read by SideLoader (mounted at /data) to explain "offline" iPhones.
STATUS_FILE="$ROOT_DIR/build/sideloop/data/host-devices.json"
case "${1:-}" in
  install)
    PYTHON="$(command -v python3 || true)"
    [[ -n "$PYTHON" ]] || { echo 'Missing required tool: python3' >&2; exit 1; }
    [[ -f "$RELAY" ]] || { echo "Missing USB relay: $RELAY" >&2; exit 1; }
    [[ -S /var/run/usbmuxd ]] || { echo 'Missing /var/run/usbmuxd socket' >&2; exit 1; }
    mkdir -p "$HOME/Library/LaunchAgents"
    if [[ -e "$PLIST" ]]; then
      launchctl bootout "$SCOPE" "$PLIST" >/dev/null 2>&1 || true
    fi
    "$PYTHON" - "$PLIST" "$LABEL" "$PYTHON" "$RELAY" "$STATUS_FILE" <<'PY'
import plistlib
import sys

path, label, python, relay, status_file = sys.argv[1:]
config = {
    "Label": label,
    "ProgramArguments": [
        python,
        "-u",
        relay,
        "--host",
        "127.0.0.1",
        "--port",
        "27015",
        "--socket",
        "/var/run/usbmuxd",
        "--status-file",
        status_file,
    ],
    "RunAtLoad": True,
    "KeepAlive": True,
    "ProcessType": "Background",
    "ThrottleInterval": 5,
}
with open(path, "wb") as handle:
    plistlib.dump(config, handle, sort_keys=False)
PY
    chmod 600 "$PLIST"
    launchctl bootstrap "$SCOPE" "$PLIST"
    echo 'macOS Python USB relay installed. Listening on 127.0.0.1:27015 only.'
    ;;
  uninstall)
    if [[ -f "$PLIST" ]]; then
      launchctl bootout "$SCOPE" "$PLIST" >/dev/null 2>&1 || true
      # Remove our own LaunchAgent silently; avoid Finder/Trash UI prompts.
      rm -f -- "$PLIST"
    fi
    echo 'macOS USB relay removed.'
    ;;
  *) echo "Usage: $0 install|uninstall" >&2; exit 2 ;;
esac
