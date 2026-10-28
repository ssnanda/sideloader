#!/usr/bin/env python3
"""Add protected, explicit Clear old logs action to Activity (repeatable)."""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: patch-log-maintenance.py <sideloop-checkout> <overlay-dir>")
checkout, overlay = Path(sys.argv[1]), Path(sys.argv[2])
server = checkout / "sideloop" / "server.py"
index = checkout / "sideloop" / "index.html"


def replace(text, old, new, label):
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        sys.exit(f"Clear logs patch {label}: expected 1 anchor, found {count}")
    return text.replace(old, new, 1)


s = server.read_text()
s = replace(s,
    "from . import retry_guard\nfrom .account import verification, save_account",
    "from . import retry_guard\nfrom . import log_maintenance\nfrom .account import verification, save_account",
    "server import")
s = replace(s,
    "    def signing_resume(self, data):",
    "    def clear_activity_logs(self, data):\n"
    "        if data.get('acknowledge') is not True:\n"
    "            raise ValueError('Please confirm clearing the old Activity logs.')\n"
    "        return log_maintenance.clear_history(self)\n\n"
    "    def signing_resume(self, data):",
    "clear handler")
s = replace(s,
    '            "/api/signing/resume": self.signing_resume,',
    '            "/api/signing/resume": self.signing_resume,\n'
    '            "/api/logs/clear": self.clear_activity_logs,',
    "protected POST route")

h = index.read_text()
h = replace(h,
    '<button class="cell action" type="button" id="sideloader-copy-diagnostics">Copy Diagnostics</button><pre class="logs" id="logs">',
    '<button class="cell action" type="button" id="sideloader-copy-diagnostics">Copy Diagnostics</button>'
    '<button class="cell action" type="button" id="sideloader-clear-logs" style="color:var(--red)">Clear old logs</button>'
    '<pre class="logs" id="logs">',
    "Activity delete button")
h = replace(h,
    '  on("reload", "onclick", loadLogs);',
    '''  on("reload", "onclick", loadLogs);
  on("sideloader-clear-logs", "onclick", () => {
    if (!window.confirm("Permanently delete old Activity/signing logs and completed job output? This cannot be undone. Saved IPAs, device pairing, Apple Account settings and the signing safety lock will NOT be deleted. Cannot clear during an active job.")) return;
    act(async () => {
      await api("/api/logs/clear", {json:{acknowledge:true}});
      await loadLogs();
    }, "Old Activity logs deleted. Signing lock preserved.");
  });''',
    "button event")

# Validate all anchors before writing ANY files: a failed migration does not
# leave a half-added endpoint or half-added UI.
server.write_text(s)
index.write_text(h)
(checkout / "sideloop" / "log_maintenance.py").write_bytes((overlay / "log_maintenance.py").read_bytes())
print("Activity clear-log button and authenticated API installed (repeatable; safety lock preserved).")