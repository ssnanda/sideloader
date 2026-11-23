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
SUCCESS = '  python3 -m sideloop.retry_guard success "$attempt_token"\n'
if SUCCESS not in source:
    # Detect by its own line: patch-apple-verification.py inserts after the
    # same anchor, so "anchor + this line" is never adjacent on later builds.
    replace('  log "OK $msg"; record ok "$msg"\n',
            '  log "OK $msg"; record ok "$msg"\n' + SUCCESS,
            "release only after verified installation")

# Repair persistent checkouts where repeat builds stacked these insertions.
# A second `retry_guard success` raises after the first released the
# reservation, turning a verified install into a failed job (and pausing
# signing). Rebuild each region in its canonical single-copy form.
import re
OK = '  log "OK $msg"; record ok "$msg"\n'
VERIFIED = ('  # Only a verified installation proves the account worked with AltServer.\n'
            '  python3 -m sideloop.account verified || log "WARNING: could not persist account verification status"\n')
stacked = re.compile(re.escape(OK) + '(?:' + re.escape(SUCCESS) + '|' +
                     '|'.join(re.escape(line + '\n') for line in VERIFIED.splitlines()) + ')+')
matches = stacked.findall(source)
if len(matches) != 1:
    sys.exit(f"Single-attempt patch success block: expected 1, got {len(matches)}")
source = source.replace(matches[0], OK + SUCCESS + (VERIFIED if VERIFIED in matches[0] else ''), 1)

STAGES = '''log "STAGE 1/4: Checking signing safety lock. No Apple request has been sent."
if ! python3 -m sideloop.retry_guard check; then
  log "STOPPED: a previous signing attempt failed; review Activity and explicitly resume before retrying."
  record blocked "signing paused after a failed attempt"
  exit 73
fi
log "STAGE 2/4: iPhone reachable and IPA ready. Preparing Apple developer signing."
log "STAGE 3/4: Asking AltServer to sign and install. One 2FA code may be required."
'''
first = source.find(STAGES)
if first >= 0:
    head, tail = source[:first + len(STAGES)], source[first + len(STAGES):]
    source = head + tail.replace(STAGES, '')

FAILED_COMMENT = ('# Pause all further signing attempts on the first failed attempt.\n'
                  '# Keep only classified error and action; never save raw auth output.\n')
TOKENED = 'python3 -m sideloop.retry_guard failed "$out" "$rc" "$attempt_token" || true\n'
UNTOKENED = 'python3 -m sideloop.retry_guard failed "$out" "$rc" || true\n'
if TOKENED in source:
    source = source.replace(FAILED_COMMENT + UNTOKENED, '').replace(UNTOKENED, '')

# iOS may publish a successful installation a few seconds after AltServer
# exits. Retry only the local inventory/profile checks before declaring an
# install failure; this does not contact Apple or launch AltServer again.
old_result = '''log "STAGE 4/4: AltServer exited $rc; checking the installed app and provisioning profile."
if (( rc == 0 )) && [[ "$(app_state)" == installed ]] && stamp_success; then'''
prior_wait_result = '''verify_completed_install() {
  local attempt
  for attempt in {1..15}; do
    if [[ "$(app_state)" == installed ]] && stamp_success; then return 0; fi
    (( attempt < 15 )) && sleep 2
  done
  return 1
}

log "STAGE 4/4: AltServer exited $rc; waiting for iOS to confirm the installed app and profile."
if (( rc == 0 )) && verify_completed_install; then'''
new_result = '''verify_completed_install() {
  local attempt
  for attempt in {1..15}; do
    if [[ "$(app_state)" == installed ]] && stamp_success; then return 0; fi
    (( attempt < 15 )) && sleep 2
  done
  return 1
}

ALTSERVER_DONE="$(now)"
log "STAGE 4/4: AltServer exited $rc after $(( ALTSERVER_DONE - RUN_START ))s; waiting for iOS to confirm the installed app and profile."
if (( rc == 0 )) && verify_completed_install; then'''
if 'ALTSERVER_DONE="$(now)"' not in source:
    if source.count(old_result) == 1:
        source = source.replace(old_result, new_result, 1)
    elif source.count(prior_wait_result) == 1:
        # Releases before phase timing already had safe local polling. Replace
        # that complete historical block so persistent checkouts converge on
        # the canonical timed form without duplicating the helper function.
        source = source.replace(prior_wait_result, new_result, 1)
    elif 'STAGE 4/4:' in source:
        sys.exit("Single-attempt patch verification wait: unrecognized Stage 4 block")

timing_anchor = 'if (( rc == 0 )) && verify_completed_install; then\n  msg="refreshed, valid until'
timed_anchor = ('if (( rc == 0 )) && verify_completed_install; then\n'
                '  log "Installation verified after $(( $(now) - ALTSERVER_DONE ))s '
                '(total $(( $(now) - RUN_START ))s)"\n'
                '  msg="refreshed, valid until')
if timed_anchor not in source:
    if source.count(timing_anchor) != 1:
        sys.exit(f"Single-attempt patch timing: expected 1 anchor, got {source.count(timing_anchor)}")
    source = source.replace(timing_anchor, timed_anchor, 1)

# Describe the required replacement install accurately without changing the
# legacy block used above to find and collapse duplicate stage insertions.
source = source.replace(
    'log "STAGE 3/4: Asking AltServer to sign and install. One 2FA code may be required."',
    'log "STAGE 3/4: Asking AltServer to sign and reinstall the refreshed app. One 2FA code may be required."',
    1)

if source.count(SUCCESS) != 1:
    sys.exit(f"Single-attempt patch: success call appears {source.count(SUCCESS)} times; refusing to write")
for line, label in ((TOKENED, 'failure'), ('python3 -m sideloop.retry_guard check', 'safety check')):
    if source.count(line) > 1:
        sys.exit(f"Single-attempt patch: {label} call appears {source.count(line)} times; refusing to write")
shell.write_text(source)
print("Single AltServer attempt reserved before launch; interrupted attempts stay blocked.")
