#!/usr/bin/env bash
# Keep the USB mux socket accessible to Docker Desktop's opt-in host networking,
# while binding the TCP proxy ONLY to the Mac loopback interface.
set -euo pipefail
LABEL="local.minisideload.usbmux-relay"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCOPE="gui/$(id -u)"
case "${1:-}" in
  install)
    SOCAT="$(command -v socat || true)"
    [[ -n "$SOCAT" ]] || { echo 'socat not installed (brew install socat)' >&2; exit 1; }
    [[ -S /var/run/usbmuxd ]] || { echo 'Missing /var/run/usbmuxd socket' >&2; exit 1; }
    mkdir -p "$HOME/Library/LaunchAgents"
    if [[ -e "$PLIST" ]]; then
      launchctl bootout "$SCOPE" "$PLIST" >/dev/null 2>&1 || true
    fi
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array>
<string>$SOCAT</string>
<string>TCP-LISTEN:27015,bind=127.0.0.1,reuseaddr,fork</string>
<string>UNIX-CONNECT:/var/run/usbmuxd</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
</dict></plist>
EOF
    chmod 600 "$PLIST"
    launchctl bootstrap "$SCOPE" "$PLIST"
    echo 'macOS USB relay installed. Listening on 127.0.0.1:27015 only.'
    ;;
  uninstall)
    if [[ -f "$PLIST" ]]; then
      launchctl bootout "$SCOPE" "$PLIST" >/dev/null 2>&1 || true
      rm -f "$PLIST"
    fi
    echo 'macOS USB relay removed.'
    ;;
  *) echo "Usage: $0 install|uninstall" >&2; exit 2 ;;
esac
