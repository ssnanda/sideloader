#!/usr/bin/env python3
"""Move signing/2FA prompts from native dialogs and modal scrim to Apps screen.

Run AFTER patch-apps-dashboard.py and patch-apple-2fa-safety.py.
Idempotent against the persistent /build/sideloop checkout. Does not modify
any account credentials, device pairing, IPA content or signing locks.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: patch-screen-flow.py <sideloop-checkout> <overlay-dir>")
checkout, overlay = Path(sys.argv[1]), Path(sys.argv[2])
index = checkout / "sideloop" / "index.html"
page = index.read_text()


def replace_once(before, after, what):
    global page
    if after in page:
        return
    count = page.count(before)
    if count != 1:
        sys.exit(f"Screen flow patch {what}: expected one anchor, got {count}")
    page = page.replace(before, after, 1)


# Preserve the 2FA form source so the earlier safety overlay stays idempotent
# on repeated builds; never execute the old modal renderer.
replace_once(
    "function renderSheet() {\n",
    'function renderSheet() {\n'
    '  // SideLoader screen flow: legacy modal intentionally disabled.\n'
    '  if (sheetHost.firstChild) sheetHost.replaceChildren();\n'
    '  return;\n',
    "disable signing modal"
)

# Keep the Apps tab visible but switch its content to an entire new screen
# for confirmations, progress, code entry, failure and completion.
activity_route = ('view === "apps" ? (slFlow ? slScreenView() : appsView()) '
                  ': (slFlow?.screenView === "activity" ? slScreenView() : activityView())')
# Migrate an already locally patched dashboard without requiring a reset.
page = page.replace(
    'view === "apps" ? (slFlow ? slScreenView() : appsView()) : activityView()',
    activity_route
)
replace_once(
    'view === "apps" ? appsView() : activityView()',
    activity_route,
    "screen navigation"
)

# The existing job launcher was changed by the Apps dashboard overlay. Route
# pairing and the read-only installed-app check into the same in-page screen.
inline_launcher = 'function startJob(path, body={}) { return slStartJob(path, body); }'
if inline_launcher not in page:
    start = page.find("async function startJob(path, body={}) {")
    if start < 0:
        start = page.find("function startJob(path, body={}) {")
    end = page.find("\nfunction wire() {", start)
    if start < 0 or end < 0:
        sys.exit("Screen flow patch: cannot locate the job launcher")
    page = page[:start] + inline_launcher + page[end:]

# Render wires legacy handlers first, then overwrite only actions that formerly
# called window.confirm() with the in-page confirmation screen's handlers.
replace_once(
    "}\nfunction upload(f) {",
    "  slWireScreen();\n}\nfunction upload(f) {",
    "install screen events"
)

# A background signing job can receive an Apple code while no Apps flow is
# open. Move to the Apps code screen without requiring an Activity visit.
replace_once(
    "    if (S.job && S.job.running) watched.add(S.job.id);",
    '''    if (S.job && S.job.running) watched.add(S.job.id);
    if (S.job?.running && S.job.needs_input && S.job.accepts_input &&
        S.job.kind === "refresh" && (!slFlow || slFlow.mode !== "job")) {
      slFlow = {mode:"job",jobId:S.job.id,title:S.job.title||"Apple verification"};
      view = "apps";
      history.replaceState(null,"","#apps");
      lastPage = null;
    }''',
    "automatically show active verification"
)

# Poll the live job promptly when the trusted-device challenge arrives.
# Backend requests are read-only; no new Apple sign-in or OTP request occurs.
if 'pollT = setTimeout(poll,' in page:
    replace_once(
        'pollT = setTimeout(poll, busy ? 1500 : 8000);',
        'pollT = setTimeout(poll, busy ? (S.job?.needs_input ? 500 : 800) : 8000);',
        'verification screen latency'
    )

# Returning to the dashboard while an install is running restores its screen.
boot_start = page.find("async function boot() {")
boot_end = page.find("\nfunction renderAuth(", boot_start)
if boot_start < 0 or boot_end < 0:
    sys.exit("Screen flow patch: cannot locate dashboard boot")
boot = page[boot_start:boot_end]
restore = '  if (S.job?.running && S.job.kind === "refresh" && !slFlow) slFlow = {mode:"job",jobId:S.job.id,title:S.job.title};'
if restore not in boot:
    if boot.count("  await refresh();") != 1:
        sys.exit("Screen flow patch: expected one boot state refresh")
    boot = boot.replace("  await refresh();", "  await refresh();\n" + restore, 1)
    page = page[:boot_start] + boot + page[boot_end:]

css = (overlay / "screen-flow.css").read_text()
if "/* SideLoader in-page workflow v1" not in page:
    replace_once("</style>", "\n" + css + "\n</style>", "inline workflow styles")

# All insertion requirements validated before touching disk.
index.write_text(page)
print("SideLoader in-page Apps flow installed: no modal signing or 2FA popup.")
