#!/usr/bin/env python3
"""Bake AltServer revision into Docker image; show actual running image version.

Applies after all other overlays. Does not change existing pairing or IPA data.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: patch-backend-info.py <checkout> <overlay-dir>")
checkout, overlay = Path(sys.argv[1]), Path(sys.argv[2])
package = checkout / "sideloop"
(package / "backend_info.py").write_bytes((overlay / "backend_info.py").read_bytes())


def replace(path, old, new, label):
    source = path.read_text()
    if new in source:
        return
    matches = source.count(old)
    if matches != 1:
        sys.exit(f"Cannot safely patch AltServer backend {label}: expected 1 anchor, got {matches}")
    path.write_text(source.replace(old, new, 1))


docker = checkout / "Dockerfile"
metadata_marker = "# SideLoader AltServer-Linux build provenance v1"
if metadata_marker not in docker.read_text():
    replace(docker, "FROM debian:trixie-slim", '''# SideLoader AltServer-Linux build provenance v1
# The revision was checked against ALTSERVER_REV earlier in the builder stage.
RUN cd /src && actual_rev="$(git rev-parse HEAD)" && \\
    test "$actual_rev" = "$ALTSERVER_REV" && \\
    printf '{"name":"AltServer-Linux NG","ref":"ng","revision":"%s","built_at":"%s"}\\n' \\
      "$actual_rev" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /AltServer-build.json

FROM debian:trixie-slim''', "builder revision provenance")
replace(docker,
        "COPY --from=altserver /AltServer /usr/local/bin/AltServer",
        "COPY --from=altserver /AltServer /usr/local/bin/AltServer\n"
        "COPY --from=altserver /AltServer-build.json /etc/sideloader/altserver-build.json",
        "runtime build manifest")
# Always compile the verified pinned commit, even if the upstream NG branch
# moves after SideLoader is released. Never silently build an untested HEAD.
replace(docker,
        '&& cd /src && test "$(git rev-parse HEAD)" = "$ALTSERVER_REV" && git apply /tmp/patches/*.patch',
        '&& cd /src && git fetch -q --depth 1 origin "$ALTSERVER_REV" \\\n'
        ' && git checkout -q --detach "$ALTSERVER_REV" \\\n'
        ' && git submodule update -q --init --recursive --depth 1 \\\n'
        ' && test "$(git rev-parse HEAD)" = "$ALTSERVER_REV" && git apply /tmp/patches/*.patch',
        'git checkout -q --detach "$ALTSERVER_REV"')


server = package / "server.py"
if 'from .backend_info import status as altserver_status, check_updates as altserver_updates' not in server.read_text():
    replace(server,
            "from .account import verification, save_account",
            "from .account import verification, save_account\nfrom .backend_info import status as altserver_status, check_updates as altserver_updates",
            "backend inspector import")
replace(server,
        '            "account_verification": verification(),',
        '            "account_verification": verification(),\n'
        '            "altserver_build": altserver_status(),',
        "backend provenance state")

# This is the Apple ID that refresh.sh ACTUALLY passes to AltServer, not
# merely the email that happened to be shown in the settings form.
refresh = checkout / "scripts" / "refresh.sh"
replace(refresh,
    'log "STAGE 3/4: Asking AltServer to sign and install. One 2FA code may be required."',
    'log "STAGE 3/4: Asking AltServer to sign and install. One 2FA code may be required."\n'
    'log "Apple Account passed to AltServer (-a): ${APPLE_ID}"',
    "runtime signing identity in log")

if '    def altserver_check_updates(self, data):' not in server.read_text():
    replace(server,
            '    def signing_resume(self, data):',
            '    def altserver_check_updates(self, data):\n'
            '        return altserver_updates()\n\n'
            '    def signing_resume(self, data):',
            "read-only update check API")
if '"/api/altserver/check-updates": self.altserver_check_updates' not in server.read_text():
    replace(server,
            '            "/api/signing/resume": self.signing_resume,',
            '            "/api/signing/resume": self.signing_resume,\n'
            '            "/api/altserver/check-updates": self.altserver_check_updates,',
            "update check route")

index = package / "index.html"
marker = "/* SideLoader backend provenance display v1 */"
if marker not in index.read_text():
    header = "function settingsView() {"
    helper = '''/* SideLoader backend provenance display v1 */
let altserverUpdateInfo = null, altserverChecking = false;
function altserverBackendCard() {
  const b = S.altserver_build || {};
  const pinned = b.status === "pinned";
  const check = altserverUpdateInfo;
  const version = b.revision ? `${esc(b.ref || "unknown")} @ ${esc(b.revision.slice(0, 12))}` : "Version unknown";
  const verification = pinned ? "Pinned revision confirmed" : b.status === "unexpected" ? "Unexpected build revision" : "Build not verified";
  return `<div class="sect">
    <div class="shead"><h3>AltServer-Linux signing backend</h3><span class="badge ${pinned ? "ok" : "warn"}">${verification}</span></div>
    <div class="list">
      <div class="cell ind"><span class="k">Installed backend<span class="sub">${esc(b.name || "AltServer-Linux NG")}</span></span><span>${version}</span><button type="button" class="cap" id="sideloader-altserver-updates" ${altserverChecking ? "disabled" : ""}>${altserverChecking ? "Checking…" : "Check for updates"}</button></div>
      <div class="cell ind"><span class="k">Expected revision</span><span>${esc((b.expected_revision || "unknown").slice(0, 12))}</span></div>
      <div class="cell ind"><span class="k">Built at (UTC)</span><span>${esc(b.built_at || "unknown")}</span></div>
      <div class="cell ind"><span class="k">Binary SHA-256<span class="sub">Fingerprint of the executable inside this Docker container</span></span><span>${esc(b.binary_sha256 ? b.binary_sha256.slice(0, 16) : "unavailable")}</span></div>
    </div>
    ${check ? `<div class="foot"><b>${check.status === "up_to_date" ? "Up to date" : check.status === "update_available" ? "New upstream revision available" : check.status === "unavailable" ? "Update check unavailable" : "Update status: " + esc(check.status)}</b>
      <div>${esc(check.message)}</div>
      <div>Latest NG: ${esc(check.latest_revision ? check.latest_revision.slice(0, 12) : "unknown")} ${check.latest_date ? "· " + esc(check.latest_date) : ""} · Checked: ${esc(check.checked_at || "unknown")}</div>
      ${check.status === "update_available" ? `<div>Updating is intentionally manual and requires a tested SideLoader revision, followed by a local Docker rebuild. Checking does not update AltServer.</div>` : ""}
    </div>` : ""}
    <div class="foot">${esc(b.message || "Unable to check the signing backend.")} The version indicates what Docker actually runs, not whether Apple will accept this account. Source: <a href="https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng" target="_blank" rel="noopener noreferrer">Maintained NG fork</a>, not NyaMisty's older repository.</div>
  </div>`;
}
'''
    replace(index, header, helper + header, "backend card function")
replace(index,
        '  <div class="setup-heading">SETTINGS · OPTIONAL</div>',
        '  ${altserverBackendCard()}\n  <div class="setup-heading">SETTINGS · OPTIONAL</div>',
        "backend card position")
replace(index,
        '  on("sideloader-remove-account", "onclick",',
        '''  on("sideloader-altserver-updates", "onclick", () => {
    if (altserverChecking) return;
    altserverChecking = true;
    render();
    act(async () => {
      try {
        altserverUpdateInfo = await api("/api/altserver/check-updates", {json:{}});
      } finally {
        altserverChecking = false;
      }
    });
  });
  on("sideloader-remove-account", "onclick",''',
        'on("sideloader-altserver-updates", "onclick"')

# Prominent links beside the installed AltServer version. The responsive
# overlay wraps the version in a new element, so a future build must NOT
# expect its old <span>${version}</span> anchor.
# Detect a complete installation first, rejecting partial/ambiguous markup.
source = index.read_text()
source_link = 'aria-label="Open maintained AltServer-Linux NG source on GitHub">GitHub source</a>'
commits_link = 'aria-label="View recent AltServer-Linux NG commits">Recent commits</a>'
count_source = source.count(source_link)
count_commits = source.count(commits_link)
if count_source == 1 and count_commits == 1:
    if (source.count('id="sideloader-altserver-updates"') != 1 or
            not any(version in source for version in (
                '<span>${version}</span>',
                '<span class="sideloader-backend-version">${version}</span>'))):
        sys.exit("AltServer upstream links exist but version/update controls are inconsistent")
    print("AltServer upstream links already installed; preserving responsive layout.")
elif count_source or count_commits:
    sys.exit("AltServer upstream links are partially installed; refusing to duplicate them")
else:
    replace(index,
            '<span>${version}</span><button type="button" class="cap" id="sideloader-altserver-updates"',
            '<span>${version}</span>'
            '<a class="cap" href="https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng" '
            'target="_blank" rel="noopener noreferrer" aria-label="Open maintained AltServer-Linux NG source on GitHub">GitHub source</a>'
            '<a class="cap" href="https://github.com/jaakkopalvaila/AltServer-Linux/commits/ng" '
            'target="_blank" rel="noopener noreferrer" aria-label="View recent AltServer-Linux NG commits">Recent commits</a>'
            '<button type="button" class="cap" id="sideloader-altserver-updates"',
            "prominent upstream repository and commit links")

print("Pinned AltServer-Linux NG provenance and safe manual GitHub update checks exposed in Apps UI.")