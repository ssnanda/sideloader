#!/usr/bin/env python3
"""Add generated username + password authentication to Sideloop."""

import sys
from pathlib import Path


if len(sys.argv) != 2:
    raise SystemExit("Usage: patch-local-login.py <sideloop-checkout>")

package = Path(sys.argv[1]) / "sideloop"
auth = package / "auth.py"
server = package / "server.py"
index = package / "index.html"


def replace_once(path, old, new, label):
    text = path.read_text()
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"Local login patch {label}: expected one anchor, found {count}"
        )
    path.write_text(text.replace(old, new, 1))


replace_once(
    auth,
    "def has_password():\n    return bool(_load())\n",
    "def has_password():\n    c = _load()\n    return bool(c.get(\"username\") and c.get(\"hash\"))\n\n\ndef username():\n    return str(_load().get(\"username\") or \"\")\n",
    "username accessor",
)
replace_once(
    auth,
    "def set_password(password):\n",
    "def set_password(password, username=\"\"):\n",
    "password setter signature",
)
replace_once(
    auth,
    '        json.dump({"salt": salt, "hash": _hash(password, salt), "secret": secrets.token_hex(32)}, f)\n',
    '        json.dump({"username": username, "salt": salt, "hash": _hash(password, salt), "secret": secrets.token_hex(32)}, f)\n',
    "stored username",
)
replace_once(
    auth,
    "def check_password(password):\n    c = _load()\n    return bool(c) and hmac.compare_digest(_hash(password, c[\"salt\"]), c[\"hash\"])\n",
    "def check_password(username, password):\n    c = _load()\n    return (bool(c) and hmac.compare_digest(str(username), str(c.get(\"username\") or \"\"))\n            and hmac.compare_digest(_hash(password, c[\"salt\"]), c[\"hash\"]))\n",
    "credential check",
)
replace_once(
    server,
    'return self.send(200, {"has_password": auth.has_password(), "logged_in": self.authed()})',
    'return self.send(200, {"has_password": auth.has_password(), "username": auth.username(), "logged_in": self.authed()})',
    "auth status username",
)
replace_once(
    server,
    '                auth.set_password(str(data["password"]))\n',
    '                username = str(data.get("username", "")).strip()\n                if not username:\n                    return self.error(400, "username is required")\n                auth.set_password(str(data["password"]), username)\n',
    "setup username",
)
replace_once(
    server,
    '                if auth.check_password(str(data.get("password", ""))):\n',
    '                if auth.check_password(str(data.get("username", "")), str(data.get("password", ""))):\n',
    "login username",
)
replace_once(
    index,
    '  if (!a.has_password) return renderAuth(true);\n  if (!a.logged_in) return renderAuth(false);',
    '  if (!a.has_password) return renderAuth(true, a.username);\n  if (!a.logged_in) return renderAuth(false, a.username);',
    "auth username handoff",
)
replace_once(
    index,
    "function renderAuth(first) {",
    "function renderAuth(first, username = \"\") {",
    "auth renderer username",
)
replace_once(
    index,
    '    <form id="authf">\n      <div class="list"><div class="cell"><input class="fi" style="text-align:left;color:var(--label)" id="pw" type="password"',
    '    <form id="authf">\n      <div class="list"><div class="cell"><input class="fi" style="text-align:left;color:var(--label)" id="user" type="text" placeholder="Username" autocomplete="username" required value="${esc(username)}"></div>\n      <div class="cell"><input class="fi" style="text-align:left;color:var(--label)" id="pw" type="password"',
    "username field",
)
replace_once(
    index,
    '    try { await api(first ? "/api/auth/setup" : "/api/auth/login", {json:{password:$("#pw").value}}); boot(); }',
    '    try { await api(first ? "/api/auth/setup" : "/api/auth/login", {json:{username:$("#user").value,password:$("#pw").value}}); boot(); }',
    "username submission",
)

print("Generated local username and password login installed.")
