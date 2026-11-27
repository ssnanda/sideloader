#!/usr/bin/env python3
"""Account settings (username + password change) and timing/debug view.

Server:
  * Sign-in ignores leading/trailing spaces in the username (iOS keyboard
    suggestions append one; generated usernames never contain spaces).
  * Each sign-in attempt is recorded in memory (last 20) and printed to the
    container log with the failure reason (username vs password mismatch) and
    the received lengths. Passwords are never logged or returned.
  * POST /api/auth/password changes the password after checking the current
    one. Rotating the session secret signs out every other browser/TapTether;
    this browser receives a fresh session.
  * GET /api/debug (signed in) returns the sign-in attempts and a per-part
    timing breakdown of the last /api/state call.

UI:
  * Settings menu shows the signed-in username, Change password, and
    Timing & debug.
  * The sign-in button shows an elapsed timer until the dashboard renders.
  * api() records the duration of every request made by this browser.

Must run after patch-local-login.py (it anchors on the username login).
"""

import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: patch-account-debug.py <sideloop-checkout>")

package = Path(sys.argv[1]) / "sideloop"
server = package / "server.py"
index = package / "index.html"
MARK = "SideLoader account + debug v1"


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Account/debug patch {label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------- server.py
s = server.read_text()
if MARK not in s:
    # Clients that omit Content-Length (dart:io/TapTether by default) send a
    # chunked body; reading Content-Length alone saw "{}" and rejected logins.
    s = replace_once(
        s,
        '        def json(self):\n'
        '            n = int(self.headers.get("Content-Length") or 0)\n',
        '        def json(self):\n'
        '            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():\n'
        '                body = b""\n'
        '                while True:\n'
        '                    size = int(self.rfile.readline(64).split(b";")[0].strip() or b"0", 16)\n'
        '                    if size == 0:\n'
        '                        while self.rfile.readline(1024) not in (b"\\r\\n", b"\\n", b""):\n'
        '                            pass\n'
        '                        break\n'
        '                    if len(body) + size > MAX_JSON:\n'
        '                        raise ValueError("request too large")\n'
        '                    body += self.rfile.read(size)\n'
        '                    self.rfile.readline(8)\n'
        '                return json.loads(body or b"{}")\n'
        '            n = int(self.headers.get("Content-Length") or 0)\n',
        "chunked request bodies",
    )
    s = replace_once(
        s,
        '                if auth.check_password(str(data.get("username", "")), str(data.get("password", ""))):\n'
        '                    return self.login(auth.new_session())\n'
        '                time.sleep(1)\n'
        '                return self.error(401, "wrong password")\n',
        '                raw_user = str(data.get("username", ""))\n'
        '                password = str(data.get("password", ""))\n'
        '                ok = auth.check_password(raw_user.strip(), password)\n'
        '                _sl_auth_event(self, ok, raw_user, password)\n'
        '                if ok:\n'
        '                    return self.login(auth.new_session())\n'
        '                time.sleep(1)\n'
        '                return self.error(401, "wrong password")\n',
        "login attempt recording",
    )
    s = replace_once(
        s,
        '            if path not in routes:\n                return self.error(404, "not found")\n',
        '            if path == "/api/auth/password":\n'
        '                current = str(data.get("current_password", ""))\n'
        '                new = str(data.get("new_password", ""))\n'
        '                if not auth.check_password(auth.username(), current):\n'
        '                    time.sleep(1)\n'
        '                    return self.error(403, "current password is wrong")\n'
        '                if new != new.strip():\n'
        '                    return self.error(400, "remove leading or trailing spaces")\n'
        '                if not 8 <= len(new) <= 256:\n'
        '                    return self.error(400, "use 8 to 256 characters")\n'
        '                auth.set_password(new, auth.username())\n'
        '                print(time.strftime("%H:%M:%S"), "auth: password changed; other sessions signed out", flush=True)\n'
        '                return self.login(auth.new_session())\n'
        '            if path not in routes:\n                return self.error(404, "not found")\n',
        "password change route",
    )
    s = replace_once(
        s,
        '            if path == "/api/state":\n                return self.send(200, app.state())\n',
        '            if path == "/api/debug":\n'
        '                return self.send(200, {"auth_events": list(_SL_AUTH_EVENTS),\n'
        '                                       "state_timing": dict(_SL_STATE_TIMING)})\n'
        '            if path == "/api/state":\n                return self.send(200, app.state())\n',
        "debug route",
    )
    s = s.rstrip("\n") + f'''


# {MARK} start
import collections as _sl_collections

_SL_AUTH_EVENTS = _sl_collections.deque(maxlen=20)
_SL_STATE_TIMING = {{}}


def _sl_auth_event(handler, ok, raw_user, password):
    expected = auth.username()
    user = raw_user.strip()
    if ok:
        result = "ok" + (" (spaces trimmed from username)" if user != raw_user else "")
    elif user != expected:
        result = "username mismatch"
    else:
        result = "password mismatch"
    event = {{
        "at": int(time.time()),
        "client": handler.client_address[0],
        "agent": (handler.headers.get("User-Agent") or "")[:80],
        "result": result,
        "username_length": len(raw_user),
        "password_length": len(password),
    }}
    _SL_AUTH_EVENTS.append(event)
    print(time.strftime("%H:%M:%S"), "auth: sign-in", result, "from", event["client"],
          f"user_len={{len(raw_user)}} pw_len={{len(password)}}", repr(event["agent"]), flush=True)


def _sl_timed(name, fn):
    def run(*args, **kwargs):
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            _SL_STATE_TIMING[name] = round((time.perf_counter() - started) * 1000)
    return run


# App.state() resolves these names at call time, so rebinding times each part.
enrich_apps = _sl_timed("installed_apps", enrich_apps)
verification = _sl_timed("account_verification", verification)
altserver_status = _sl_timed("altserver_build", altserver_status)
sideloop_status = _sl_timed("sideloop_build", sideloop_status)
retry_guard.status = _sl_timed("signing_guard", retry_guard.status)
remote_altkeeper.enrich_state = _sl_timed("remote_altkeeper", remote_altkeeper.enrich_state)
_sl_state = App.state


def _sl_state_with_timing(self):
    started = time.perf_counter()
    try:
        return _sl_state(self)
    finally:
        total = round((time.perf_counter() - started) * 1000)
        parts = sum(v for k, v in _SL_STATE_TIMING.items() if k not in ("total", "other"))
        _SL_STATE_TIMING["total"] = total
        _SL_STATE_TIMING["other"] = max(0, total - parts)


App.state = _sl_state_with_timing
# {MARK} end
'''
    server.write_text(s)

# ---------------------------------------------------------------- index.html
h = index.read_text()
if MARK not in h:
    h = replace_once(
        h,
        'async function api(path, opts={}) {\n',
        '''// SideLoader account + debug: request timings and signed-in user.
const slTimings = []; let slUser = "", slLoginMs = null;
function slTrace(method, path, status, t0) {
  slTimings.unshift({at: new Date().toLocaleTimeString(), method, path: path.split("?")[0], status, ms: Math.round(performance.now() - t0)});
  if (slTimings.length > 60) slTimings.length = 60;
}
async function api(path, opts={}) {
''',
        "timing helpers",
    )
    h = replace_once(
        h,
        '  const r = await fetch(path, o);\n',
        '''  const t0 = performance.now();
  let r;
  try { r = await fetch(path, o); }
  catch (e) { slTrace(o.method || "GET", path, "network error", t0); throw e; }
  slTrace(o.method || "GET", path, r.status, t0);
''',
        "api timing",
    )
    h = replace_once(
        h,
        '  const a = await api("/api/auth");\n',
        '  const a = await api("/api/auth");\n  slUser = a.username || "";\n',
        "signed-in user",
    )
    h = replace_once(
        h,
        '    try { await api(first ? "/api/auth/setup" : "/api/auth/login", {json:{username:$("#user").value,password:$("#pw").value}}); boot(); }\n'
        '    catch (err) { const n = $("#autherr"); n.textContent = err.message; n.classList.remove("hidden"); }\n',
        '''    const btn = e.target.querySelector("button"), label = btn.textContent, t0 = performance.now();
    const tick = () => { btn.textContent = `Signing in… ${((performance.now() - t0) / 1000).toFixed(1)}s`; };
    btn.disabled = true; tick();
    const timer = setInterval(tick, 100);
    try {
      await api(first ? "/api/auth/setup" : "/api/auth/login", {json:{username:$("#user").value.trim(),password:$("#pw").value}});
      await boot();
      slLoginMs = Math.round(performance.now() - t0);
    }
    catch (err) { const n = $("#autherr"); if (n) { n.textContent = `${err.message} (${((performance.now() - t0) / 1000).toFixed(1)}s)`; n.classList.remove("hidden"); } }
    finally { clearInterval(timer); if (btn.isConnected) { btn.disabled = false; btn.textContent = label; } }
''',
        "sign-in timer",
    )
    h = replace_once(
        h,
        '<nav><a href="/sources">Sources</a><a href="/roadmap">Roadmap</a></nav>',
        '<nav><span class="sl-account-user">Signed in as <b>${esc(slUser || "unknown")}</b></span>'
        '<button type="button" id="sl-password">Change password</button>'
        '<button type="button" id="sl-debug">Timing &amp; debug</button>'
        '<a href="/sources">Sources</a><a href="/roadmap">Roadmap</a></nav>',
        "settings account entries",
    )
    h = replace_once(
        h,
        '  $("#signout").onclick = async () => { await api("/api/auth/logout", {json:{}}); boot(); };\n',
        '  $("#signout").onclick = async () => { await api("/api/auth/logout", {json:{}}); boot(); };\n  slWireAccount();\n',
        "settings wiring",
    )
    h = replace_once(
        h,
        'async function refresh() { S = await api("/api/state"); }\n',
        r'''async function refresh() { S = await api("/api/state"); }
function slDialog(html) {
  document.querySelector("#sl-dialog")?.remove();
  const d = document.createElement("dialog");
  d.id = "sl-dialog"; d.className = "sl-dialog"; d.innerHTML = html;
  document.body.append(d);
  d.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => d.close()));
  d.addEventListener("close", () => d.remove());
  d.showModal();
  return d;
}
function slWireAccount() {
  const close = el => { const m = el.closest("details"); if (m) m.open = false; };
  const pw = $("#sl-password"), dbg = $("#sl-debug");
  if (pw) pw.onclick = () => { close(pw); slPasswordDialog(); };
  if (dbg) dbg.onclick = () => { close(dbg); slDebugDialog(); };
}
function slPasswordDialog() {
  const d = slDialog(`<form id="sl-pwf"><h3>Change password</h3>
    <p class="sl-dialog-user">User <b>${esc(slUser)}</b></p>
    <input type="text" autocomplete="username" value="${esc(slUser)}" style="display:none" readonly>
    <input class="fi" id="sl-pw-cur" type="password" autocomplete="current-password" placeholder="Current password" required>
    <input class="fi" id="sl-pw-new" type="password" autocomplete="new-password" placeholder="New password (8+ characters)" minlength="8" maxlength="256" required>
    <input class="fi" id="sl-pw-new2" type="password" autocomplete="new-password" placeholder="Repeat new password" minlength="8" maxlength="256" required>
    <div class="err hidden" id="sl-pw-err"></div>
    <details class="sl-dialog-note"><summary>What happens</summary>Other browsers and TapTether are signed out. Sign in there again with the new password.</details>
    <div class="sl-dialog-actions"><button type="button" class="navbtn" data-close>Cancel</button><button class="btn">Save</button></div></form>`);
  d.querySelector("#sl-pwf").onsubmit = async e => {
    e.preventDefault();
    const err = d.querySelector("#sl-pw-err");
    const fail = m => { err.textContent = m; err.classList.remove("hidden"); };
    const cur = d.querySelector("#sl-pw-cur").value, nw = d.querySelector("#sl-pw-new").value;
    if (nw !== d.querySelector("#sl-pw-new2").value) return fail("New passwords do not match");
    if (nw.trim() !== nw) return fail("Remove leading or trailing spaces");
    try { await api("/api/auth/password", {json:{current_password:cur, new_password:nw}}); d.close(); toast("Password changed"); }
    catch (x) { fail(x.message); }
  };
}
function slTable(head, rows) {
  if (!rows.length) return '<p class="sl-dbg-empty">None yet</p>';
  return '<table class="sl-dbg"><tr>' + head.map(c => `<th>${esc(c)}</th>`).join("") + "</tr>" +
    rows.map(r => "<tr>" + r.map(c => `<td>${esc(String(c))}</td>`).join("") + "</tr>").join("") + "</table>";
}
function slDebugDialog() {
  const d = slDialog(`<h3>Timing &amp; debug</h3><div id="sl-dbg-body">Loading…</div>
    <div class="sl-dialog-actions"><button type="button" class="navbtn" id="sl-dbg-refresh">Refresh</button>
    <button type="button" class="navbtn" id="sl-dbg-copy">Copy</button><button type="button" class="btn" data-close>Close</button></div>`);
  let text = "";
  const load = async () => {
    let server;
    try { server = await api("/api/debug"); } catch (x) { server = {error: x.message}; }
    const time = ts => new Date(ts * 1000).toLocaleTimeString();
    const sections = [
      ["Last sign-in (this browser)", ["Total"], [[slLoginMs == null ? "not measured" : `${slLoginMs} ms`]]],
      ["/api/state parts (server, last call)", ["Part", "ms"], Object.entries(server.state_timing || {}).sort((a, b) => b[1] - a[1])],
      ["Requests (this browser, newest first)", ["Time", "Method", "Path", "Status", "ms"], slTimings.slice(0, 25).map(r => [r.at, r.method, r.path, r.status, r.ms])],
      ["Sign-in attempts (server, newest first)", ["Time", "Client", "Result", "User len", "Pass len", "App"],
        (server.auth_events || []).slice().reverse().map(a => [time(a.at), a.client, a.result, a.username_length, a.password_length, a.agent])],
    ];
    d.querySelector("#sl-dbg-body").innerHTML = (server.error ? `<div class="err">${esc(server.error)}</div>` : "") +
      sections.map(([t, head, rows]) => `<h4>${esc(t)}</h4>` + slTable(head, rows)).join("");
    text = sections.map(([t, head, rows]) => t + "\n" + [head, ...rows].map(r => r.join("\t")).join("\n")).join("\n\n");
  };
  d.querySelector("#sl-dbg-refresh").onclick = load;
  d.querySelector("#sl-dbg-copy").onclick = async () => {
    try { await navigator.clipboard.writeText(text); }
    catch { const t = document.createElement("textarea"); t.value = text; d.append(t); t.select(); document.execCommand("copy"); t.remove(); }
    d.querySelector("#sl-dbg-copy").textContent = "Copied";
  };
  load();
}
''',
        "account dialogs",
    )
    css = f'''
/* {MARK} */
.sl-settings-menu nav button{{display:block;width:100%;text-align:left;padding:10px 12px;border:0;border-radius:8px;background:none;color:var(--blue);font:inherit;font-size:14px;cursor:pointer}}
.sl-settings-menu nav button:hover,.sl-settings-menu nav button:focus{{background:var(--fill)}}
.sl-account-user{{display:block;padding:6px 12px 8px;margin-bottom:4px;border-bottom:1px solid var(--sep);color:var(--label-2);font-size:12px;word-break:break-all}}
.sl-account-user b{{color:var(--label);font-family:var(--mono)}}
.sl-dialog{{width:min(680px,calc(100% - 24px));max-height:88vh;padding:16px;border:1px solid var(--sep);border-radius:14px;background:var(--cell);color:var(--label)}}
.sl-dialog::backdrop{{background:var(--scrim)}}
.sl-dialog h3{{margin:0 0 8px;font-size:17px}}
.sl-dialog h4{{margin:12px 0 4px;font-size:12px;color:var(--label-2);text-transform:uppercase;letter-spacing:.03em}}
.sl-dialog form{{display:grid;gap:8px}}
.sl-dialog-user{{margin:0;font-size:13px;color:var(--label-2)}}
.sl-dialog-user b{{color:var(--label);font-family:var(--mono)}}
.sl-dialog .fi{{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--sep);border-radius:10px;background:var(--bg);color:var(--label);text-align:left;font-size:15px}}
.sl-dialog-note{{font-size:12px;color:var(--label-2)}}
.sl-dialog-actions{{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}}
.sl-dialog-actions .btn{{width:auto;margin:0;padding:8px 18px}}
#sl-dbg-body{{overflow:auto;max-height:62vh}}
.sl-dbg{{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px}}
.sl-dbg th,.sl-dbg td{{padding:3px 8px 3px 0;border-bottom:1px solid var(--sep);text-align:left;white-space:nowrap}}
.sl-dbg th{{color:var(--label-2);font-weight:600}}
.sl-dbg-empty{{margin:0;font-size:12px;color:var(--label-2)}}
'''
    if h.count("</style>") != 1:
        raise SystemExit("Account/debug patch: stylesheet boundary changed")
    h = h.replace("</style>", css + "\n</style>", 1)
    index.write_text(h)

print("Account settings (username, password change) and timing/debug view installed.")
