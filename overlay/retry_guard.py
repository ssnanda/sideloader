"""Persist a one-attempt signing circuit breaker, scoped to the current Apple Account.

This is not an Apple authentication replacement. It only prevents retries after
an unsuccessful signing attempt. Never store the password or raw AltServer output.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from . import config

FILE = config.STATE / "sideloader-signing-block.json"
LOCK = config.STATE / ".sideloader-signing-block.lock"


def _identity():
    email = config.read().get("APPLE_ID", "").strip().casefold()
    return hashlib.sha256(email.encode("utf-8")).hexdigest() if email else ""


def _read():
    try:
        value = json.loads(FILE.read_text())
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        return {"account": _identity(), "blocked": True,
                "code": "guard_state_unreadable", "reason": "safety_state",
                "message": "The stored signing safety state cannot be read safely.",
                "action": "Review local data permissions, then explicitly resume signing.",
                "since": int(time.time())}


def status():
    record = _read()
    if not record or record.get("account") != _identity():
        return {"blocked": False}
    return {key: record[key] for key in
            ("blocked", "code", "reason", "message", "action", "since")
            if key in record}


def assert_allowed():
    state = status()
    if state.get("blocked"):
        raise RuntimeError(
            "Signing paused after a previous failure: " + state.get("message", "Unknown error")
            + ". " + state.get("action", "Review Activity and explicitly resume signing.")
        )


def _classify(output, rc):
    text = output.lower()
    if "-20209" in text or "locked for security reasons" in text:
        return ("-20209", "account_locked", "Apple reports this account is locked.",
                "Unlock the account at iforgot.apple.com or replace it in Step 2; then explicitly resume.")
    if "-36607" in text or "unable to sign you in to your apple account. try again later" in text:
        return ("-36607", "apple_authentication_unavailable",
                "AltServer could not complete Apple Account sign-in (-36607). The reason is not confirmed; it may involve Apple's authentication service or anisette.",
                "Do not retry in a loop. Confirm the account works at account.apple.com, inspect the configured anisette service, and review Copy Diagnostics. Resume manually only after checking the cause.")
    if "-80046" in text:
        return ("-80046", "signing_failure", "AltServer failed with -80046 after contacting Apple; the exact cause is not established.",
                "Review Copy Diagnostics and signing backend compatibility before explicitly resuming.")
    if "-80045" in text:
        return ("-80045", "signing_failure", "AltServer reported an Apple signing or authentication error (-80045).",
                "Check the Apple Account and signing backend before explicitly resuming.")
    if "verification failed" in text or "invalid verification" in text:
        return ("verification_failed", "verification", "Apple account verification was unsuccessful.",
                "Confirm the Apple Account and 2FA on Apple's website before explicitly resuming.")
    if "timed out" in text or int(rc) == 124:
        return ("timeout", "timeout", "Signing or installation timed out.",
                "Check the iPhone connection and Activity diagnostics before explicitly resuming.")
    return ("install_failed", "installation", "The signing/install attempt ended unsuccessfully.",
            "Read Activity diagnostics for the actual error and correct it before explicitly resuming.")


def _write(record):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = FILE.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)
        os.replace(temp, FILE)
    finally:
        temp.unlink(missing_ok=True)


def failed(output, rc=1):
    # The first failure stops further attempts; later classification can refine
    # a generic failure, never re-open or increment retry counts.
    if not _identity():
        return status()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old = _read()
        code, reason, message, action = _classify(output, rc)
        if old.get("blocked") and old.get("account") == _identity():
            # A PTY's final log may reveal a specific error missed by the shell.
            if old.get("code") != "install_failed" or code == "install_failed":
                return status()
        _write({"account": _identity(), "blocked": True, "code": code,
                "reason": reason, "message": message, "action": action,
                "since": old.get("since", int(time.time())) if old.get("account") == _identity()
                         else int(time.time())})
    return status()


def resume():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if FILE.exists():
            FILE.unlink()
    return {"ok": True, "message": "Signing resumed. The next installation is one new attempt."}


def _cli():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: retry_guard.py check|failed <log-file> <exit-code>")
    command = sys.argv[1]
    if command == "check":
        try:
            assert_allowed()
        except RuntimeError as exc:
            print("SIGNING STOPPED:", exc)
            return 73
        return 0
    if command == "failed" and len(sys.argv) == 4:
        path = Path(sys.argv[2])
        try:
            output = path.read_text(errors="replace")[-30000:]
        except OSError:
            output = ""
        result = failed(output, int(sys.argv[3]))
        print("SIGNING PAUSED:", result.get("message", "Signing failed"))
        print("NEXT STEP:", result.get("action", "Review Activity before resuming."))
        return 0
    raise SystemExit("Unknown signing guard action")


if __name__ == "__main__":
    sys.exit(_cli())
