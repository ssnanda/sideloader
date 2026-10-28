"""SideLoader Apple Account lifecycle and evidence-based verification state.

Saving credentials is never treated as successful Apple authentication.
A successful on-device app install is the only current verification signal.
"""
import hashlib
import json
import os
import shutil
import sys
import time

from . import config

def verified_file():
    return config.STATE / "sideloader-apple-verification.json"


def _account_key(email):
    email = str(email or "").strip().casefold()
    return hashlib.sha256(email.encode("utf-8")).hexdigest() if email else ""


def _clear_cache():
    """Prevent a previous account's signing identity being reused."""
    cache = config.DATA / "AltServerData"
    if cache.is_symlink() or (cache.exists() and not cache.is_dir()):
        raise RuntimeError("Unexpected signing-cache path; account was not changed")
    if cache.is_dir():
        try:
            shutil.rmtree(cache)
        except OSError as exc:
            raise RuntimeError("Could not clear old signing cache; account was not changed") from exc


def _invalidate():
    verified_file().unlink(missing_ok=True)


def verification():
    cfg = config.read()
    if not cfg.get("APPLE_ID") or not cfg.get("APPLE_PASSWORD"):
        return {"state": "missing", "message": "Enter an Apple Account and password."}
    from . import retry_guard
    blocked = retry_guard.status()
    if blocked.get("blocked"):
        return {"state": "failed", "code": blocked.get("code", "unknown"),
                "message": blocked.get("message", "Apple signing failed."),
                "action": blocked.get("action", "Review Activity before retrying.")}
    try:
        record = json.loads(verified_file().read_text())
    except (FileNotFoundError, OSError, ValueError):
        record = {}
    if record.get("account") == _account_key(cfg["APPLE_ID"]) and record.get("verified_at"):
        return {"state": "verified", "verified_at": record["verified_at"],
                "message": "Verified by a successful sign and confirmed app installation."}
    return {"state": "unverified",
            "message": "Credentials saved but Apple has not authenticated this account through SideLoader."}


def is_verified():
    return verification()["state"] == "verified"


def mark_verified():
    cfg = config.read()
    key = _account_key(cfg.get("APPLE_ID", ""))
    if not key:
        return
    verified_file().parent.mkdir(parents=True, exist_ok=True)
    tmp = verified_file().with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"account": key, "verified_at": int(time.time())}, f)
        os.replace(tmp, verified_file())
    finally:
        tmp.unlink(missing_ok=True)


def save_account(app, data):
    email = str(data.get("apple_id", "")).strip()
    if "@" not in email or len(email) > 254 or any(c.isspace() for c in email):
        raise ValueError("Enter the Apple Account email address.")
    cfg = config.read()
    new_password = str(data.get("password") or "")
    changed_email = email.casefold() != cfg["APPLE_ID"].strip().casefold()
    if not new_password and (changed_email or not cfg["APPLE_PASSWORD"]):
        raise ValueError("Enter the new account's password; the old account password cannot be reused.")
    changed_password = bool(new_password and new_password != cfg["APPLE_PASSWORD"])
    changed = changed_email or changed_password
    app.idle()
    if changed:
        _clear_cache()
        _invalidate()
    values = {"APPLE_ID": email}
    if new_password:
        values["APPLE_PASSWORD"] = new_password
    if changed:
        # Prevent scheduled Apple requests until the first deliberate installation succeeds.
        values["AUTO_CHECK"] = "0"
    config.update(values)
    return {"ok": True, "verification": verification(),
            "message": "Saved; Apple sign-in not yet verified. Automatic renewal paused." if changed
                       else "Account settings retained."}


def forget_account(app):
    app.idle()
    _clear_cache()
    _invalidate()
    config.update({"APPLE_ID": "", "APPLE_PASSWORD": "", "AUTO_CHECK": "0"})
    return {"ok": True}


def _cli():
    if sys.argv[1:] == ["verified"]:
        mark_verified()
        return 0
    raise SystemExit("Usage: python3 -m sideloop.account verified")


if __name__ == "__main__":
    sys.exit(_cli())
