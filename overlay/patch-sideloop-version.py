#!/usr/bin/env python3
"""Stamp the Sideloop upstream commit + SideLoader overlay version in Docker.

Must run after SideLoader's backend patch; safe on previously patched checkouts.
No runtime user data is removed or accessed.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 4:
    sys.exit("Usage: patch-sideloop-version.py <checkout> <overlay-dir> <side-loader-version-file>")
checkout, overlay, version_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
package = checkout / "sideloop"
(package / "sideloop_info.py").write_bytes((overlay / "sideloop_info.py").read_bytes())


def replace(path, old, new, label):
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        sys.exit(f"Sideloop version patch {label}: unexpected upstream layout")
    path.write_text(source.replace(old, new, 1))


try:
    sha = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip().lower()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("Invalid Sideloop commit")
    side_version = version_file.read_text().strip()
    if not side_version:
        raise ValueError("SideLoader VERSION is empty")
except (subprocess.CalledProcessError, FileNotFoundError, ValueError, OSError) as e:
    sys.exit(f"Cannot stamp Sideloop provenance: {e}")

manifest = {
    "repository": "filippofinke/sideloop",
    "upstream_revision": sha,
    "sideloader_version": side_version,
    "overlays_applied": True,
    "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
(package / "sideloop-build.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")

server = package / "server.py"
if 'from .sideloop_info import status as sideloop_status' not in server.read_text():
    replace(server,
            'from .backend_info import status as altserver_status, check_updates as altserver_updates',
            'from .backend_info import status as altserver_status, check_updates as altserver_updates\n'
            'from .sideloop_info import status as sideloop_status',
            "server import")
replace(server,
        '            "altserver_build": altserver_status(),',
        '            "altserver_build": altserver_status(),\n'
        '            "sideloop_build": sideloop_status(),',
        "state field")
index = package / "index.html"
marker = "/* SideLoader Sideloop core build display v1 */"
if marker not in index.read_text():
    replace(index, 'function altserverBackendCard()', '''/* SideLoader Sideloop core build display v1 */
function sideloopCoreCard() {
  const b = S.sideloop_build || {};
  const known = b.status === "identified";
  const sha = b.revision ? esc(b.revision.slice(0, 12)) : "unknown";
  return `<div class="sect">
    <div class="shead"><h3>Sideloop core</h3><span class="badge ${known ? "ok" : "warn"}">${known ? "Version identified" : "Build version unknown"}</span></div>
    <div class="list">
      <div class="cell ind"><span class="k">Upstream source<span class="sub">filippofinke/sideloop + SideLoader patches</span></span><span>${sha}</span><a class="cap" href="https://github.com/filippofinke/sideloop" target="_blank" rel="noopener noreferrer">GitHub</a></div>
      <div class="cell ind"><span class="k">SideLoader overlay version</span><span>${esc(b.side_loader_version || "unknown")}</span></div>
      <div class="cell ind"><span class="k">Build prepared (UTC)</span><span>${esc(b.prepared_at || "unknown")}</span></div>
    </div>
    <div class="foot">${esc(b.message || "Sideloop build identity unavailable.")} This identifies the core running in Docker after the next successful rebuild, not the latest upstream version.</div>
  </div>`;
}
function altserverBackendCard()''', "Sideloop card helper")
replace(index,
        '  ${altserverBackendCard()}',
        '  ${sideloopCoreCard()}\n  ${altserverBackendCard()}',
        "place card by AltServer version")
print(f"Sideloop build provenance stamped: {sha[:12]} + SideLoader {side_version} (Docker rebuild required)")