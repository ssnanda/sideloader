#!/usr/bin/env python3
"""Add one-failure signing circuit breaker, persistent status, and progress."""
from pathlib import Path
import sys
if len(sys.argv) != 3:
    sys.exit("Usage: patch-retry-guard.py <checkout> <overlay-dir>")
root, overlays = Path(sys.argv[1]), Path(sys.argv[2])
pkg = root / "sideloop"
(pkg / "retry_guard.py").write_bytes((overlays / "retry_guard.py").read_bytes())

def replace(path, before, after, name):
    s = path.read_text()
    if after in s:
        return
    count = s.count(before)
    if count != 1:
        sys.exit(f"Signing safety patch {name}: expected 1 anchor, got {count}")
    path.write_text(s.replace(before, after, 1))

server = pkg / "server.py"
replace(server,
    "from .account import forget_account",
    "from .account import forget_account\nfrom . import retry_guard",
    "server import")
replace(server,
    '            "job": self.jobs.current.view() if self.jobs.current else None,',
    '            "job": self.jobs.current.view() if self.jobs.current else None,\n'
    '            "signing_guard": retry_guard.status(),',
    "server state")
replace(server,
    '    def refresh(self, data):\n        if not configured():',
    '    def refresh(self, data):\n        retry_guard.assert_allowed()\n        if not configured():',
    "manual install preflight")
replace(server,
    '    def recheck(self, data):',
    '    def signing_resume(self, data):\n'
    '        self.idle()\n'
    '        if not data.get("acknowledge"):\n'
    '            raise ValueError("confirm that you reviewed the signing failure")\n'
    '        return retry_guard.resume()\n\n'
    '    def recheck(self, data):',
    "explicit resume")
replace(server,
    '            "/api/refresh": self.refresh,',
    '            "/api/refresh": self.refresh,\n'
    '            "/api/signing/resume": self.signing_resume,',
    "resume route")
watcher = pkg / "watcher.py"
replace(watcher,
    "from . import config, store",
    "from . import config, store, retry_guard",
    "watcher import")
replace(watcher,
    '            job = self.jobs.claim_auto()',
    '''            # Never retry failed Apple signing automatically.
            if retry_guard.status().get("blocked"):
                with self.lock:
                    self.queue.clear()
                self.schedule()
                continue
            job = self.jobs.claim_auto()''',
    "watcher safety")
jobs = pkg / "jobs.py"
replace(jobs,
    '    job.rc = os.waitstatus_to_exitcode(status)\n    if job.partial.strip():\n        job.say("")',
    '''    job.rc = os.waitstatus_to_exitcode(status)
    if job.partial.strip():
        job.say("")
    # Interactive PTY output is not captured by the shell's temporary log.
    # Refine a generic failure with the actual AltServer error after exit.
    if job.rc and argv and argv[0] == "refresh.sh" and "--recheck" not in argv:
        from . import retry_guard
        retry_guard.failed("\\n".join(job.lines[-100:]), job.rc)''',
    "PTY error classification")
shell = root / "scripts" / "refresh.sh"
replace(shell,
    'log "signing and installing $(basename "$IPA_PATH") on $DEVICE_UDID"',
    '''log "STAGE 1/4: Checking signing safety lock. No Apple request has been sent."
if ! python3 -m sideloop.retry_guard check; then
  log "STOPPED: a previous signing attempt failed; review Activity and explicitly resume before retrying."
  record blocked "signing paused after a failed attempt"
  exit 73
fi
log "STAGE 2/4: iPhone reachable and IPA ready. Preparing Apple developer signing."
log "STAGE 3/4: Asking AltServer to sign and install. One 2FA code may be required."
log "signing and installing $(basename "$IPA_PATH") on $DEVICE_UDID"''',
    "signing stages")
replace(shell,
    'if (( rc == 0 )) && [[ "$(app_state)" == installed ]] && stamp_success; then',
    'log "STAGE 4/4: AltServer exited $rc; checking the installed app and provisioning profile."\n'
    'if (( rc == 0 )) && [[ "$(app_state)" == installed ]] && stamp_success; then',
    "installation verification")
replace(shell,
    'n=$(( $(read_fails) + 1 )); echo "$n" > "$FAILS"',
    '''# Pause all further signing attempts on the first failed attempt.
# Keep only classified error and action; never save raw auth output.
python3 -m sideloop.retry_guard failed "$out" "$rc" || true
n=$(( $(read_fails) + 1 )); echo "$n" > "$FAILS"''',
    "persist stop on failure")
index = pkg / "index.html"
# Older persistent checkouts already contain the warning banner, so the
# usual one-time insertion anchor is gone. Migrate its condition in place.
old_warning = 'return `${S.signing_guard?.blocked ? `<div class="sect"'
new_warning = 'return `${S.signing_guard?.blocked && (S.signing_guard.code !== "attempt_in_progress" || !S.job?.running) ? `<div class="sect"'
source = index.read_text()
if old_warning in source:
    index.write_text(source.replace(old_warning, new_warning, 1))
replace(index,
    'return `${settingsView()}${autoCard}${issues.map(',
    '''return `${S.signing_guard?.blocked && (S.signing_guard.code !== "attempt_in_progress" || !S.job?.running) ? `<div class="sect" style="border:1px solid #c93434;padding:14px;border-radius:12px">
  <div style="font-weight:700;color:#c93434">Signing paused — no automatic retries</div>
  <p style="margin:8px 0">${esc(S.signing_guard.message || "The previous signing/install attempt failed.")}</p>
  <p style="margin:8px 0">${esc(S.signing_guard.action || "Review Activity and Copy Diagnostics.")}</p>
  <small>Code: ${esc(S.signing_guard.code || "unknown")} · Last failure ${new Date((S.signing_guard.since || 0)*1000).toLocaleString()}</small>
  <button type="button" class="cell action" id="sideloader-resume" style="margin-top:10px">Issue resolved — allow one new attempt</button>
</div>` : ""}${settingsView()}${autoCard}${issues.map(''',
    "visible signing status")
replace(index,
    '  on("sideloader-remove-account", "onclick",',
    '''  if (S.signing_guard?.blocked) {
    root.querySelectorAll("[data-sign], #signall").forEach(b => b.disabled = true);
  }
  on("sideloader-resume", "onclick", () => {
    if (!window.confirm("Resume only after resolving the failure. One new signing attempt will be allowed; another failure pauses signing again. Continue?")) return;
    act(() => api("/api/signing/resume", {json:{acknowledge:true}}), "Signing resumed; one new attempt permitted");
  });
  on("sideloader-remove-account", "onclick",''',
    "manual resume UI")
# A code-entry timeout is an explicit local cancellation, not an Apple
# authentication failure. Keep the lock against automatic retries.
page = index.read_text()
page = page.replace('>Signing paused — no automatic retries</div>',
                    '>${S.signing_guard?.code === "2fa_timeout" ? "Verification cancelled — no automatic retry" : "Signing paused — no automatic retries"}</div>')
page = page.replace(' · Last failure ${new Date((S.signing_guard.since || 0)*1000).toLocaleString()}',
                    ' · Since ${new Date((S.signing_guard.since || 0)*1000).toLocaleString()}')
index.write_text(page)

print("Signing safety overlay applied, including persisted failure lock and progress messages.")
