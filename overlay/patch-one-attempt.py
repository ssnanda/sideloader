#!/usr/bin/env python3
"""Reserve one persistent Apple-signing invocation before AltServer starts.

Run AFTER the original signing safety and account patches. Repeatable on an
already patched, persistent Sideloop checkout. Does not touch /data.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    sys.exit("Usage: patch-one-attempt.py <sideloop-checkout>")
root = Path(sys.argv[1])
shell = root / "scripts" / "refresh.sh"
source = shell.read_text()


def replace(before, after, label):
    global source
    if after in source:
        return
    n = source.count(before)
    if n != 1:
        sys.exit(f"Single-attempt patch {label}: {n} expected anchors")
    source = source.replace(before, after, 1)


replace('out="$(mktemp)"\n',
        '''out="$(mktemp)"
# Atomically reserve a single AltServer invocation BEFORE any network request.
# If Docker exits, the job is cancelled or this shell is terminated, the
# reservation remains blocked. It cannot be silently retried by the scheduler.
if ! attempt_token="$(python3 -m sideloop.retry_guard begin)"; then
  rm -f "$out"
  log "STOPPED: signing already attempted, running or blocked; review Activity before authorizing another run"
  record blocked "single signing attempt already reserved or paused"
  exit 73
fi
log "One AltServer invocation reserved; no further attempts will launch without a verified success or explicit resume"
''', "reserve before AltServer")
replace('python3 -m sideloop.retry_guard failed "$out" "$rc" || true',
        'python3 -m sideloop.retry_guard failed "$out" "$rc" "$attempt_token" || true',
        "error must refer to reserved invocation")
replace('  log "OK $msg"; record ok "$msg"',
        '  log "OK $msg"; record ok "$msg"\n'
        '  python3 -m sideloop.retry_guard success "$attempt_token"',
        "release only after verified installation")
shell.write_text(source)
print("Single AltServer attempt reserved before launch; interrupted attempts stay blocked.")