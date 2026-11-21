"""Persistent one-invocation Apple signing circuit breaker.

No raw Apple auth output, credentials, or email addresses are persisted.
The reservation is created BEFORE AltServer starts; crashes remain blocked.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
from . import config

FILE = config.STATE / "sideloader-signing-block.json"
LOCK = config.STATE / ".sideloader-signing-block.lock"


def _identity():
    email = config.read().get("APPLE_ID", "").strip().casefold()
    return hashlib.sha256(email.encode()).hexdigest() if email else ""


def _read():
    try:
        value = json.loads(FILE.read_text())
        if not isinstance(value, dict):
            raise ValueError("unexpected guard contents")
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        return {"account": _identity(), "blocked": True, "code": "guard_state_unreadable",
                "reason": "safety_state", "message": "The signing safety state cannot be read safely.",
                "action": "Review local permissions before explicitly resuming signing.",
                "since": int(time.time())}


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


def _mutex():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK, "a+")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def status():
    record = _read()
    if not record:
        return {"blocked": False}
    # A different Apple Account cannot silently reset a failure or interrupted
    # attempt. Only the explicit resume API can clear the global reservation.
    if record.get("account") != _identity():
        return {"blocked": True, "code": "previous_account_attempt",
                "reason": "account_changed",
                "message": "An earlier Apple Account signing attempt is still paused.",
                "action": "After confirming the new account is accessible, explicitly resume to permit one manual attempt.",
                "since": record.get("since", 0)}
    if record.get("phase") == "running":
        return {"blocked": True, "code": "attempt_in_progress",
                "reason": "signing_reserved",
                "message": "One AltServer signing attempt has been reserved. It may still be running or may have been interrupted.",
                "action": "Do not start another attempt while signing is running. If it terminated unexpectedly, review Activity and explicitly resume.",
                "since": record.get("since", 0)}
    return {k: record[k] for k in
            ("blocked", "code", "reason", "message", "action", "since") if k in record}


def assert_allowed():
    result = status()
    if result.get("blocked"):
        raise RuntimeError("Signing paused: " + result.get("message", "Unknown failure")
                           + " " + result.get("action", "Review Activity before resuming."))


def _classify(output, rc):
    text = output.lower()
    if "-20209" in text or "locked for security reasons" in text:
        return ("-20209", "account_locked", "Apple reports that this account is locked.",
                "Unlock the account using Apple account recovery before explicitly resuming.")
    if "-22406" in text or "enter the correct password for this apple account" in text:
        return ("-22406", "password_rejected",
                "AltServer rejected the supplied Apple Account password (-22406). An app-specific password was not accepted by this signing attempt.",
                "Do not retry app-specific passwords for this AltServer workflow. Use the regular Apple Account password only after checking the signing setup, then explicitly authorize one attempt.")
    if "-36607" in text or "unable to sign you in to your apple account. try again later" in text:
        return ("-36607", "apple_authentication_unavailable",
                "AltServer could not complete Apple Account sign-in (-36607). The exact cause is not established; it may involve Apple's authentication service or anisette.",
                "Avoid repeated attempts. Confirm the account on account.apple.com and inspect anisette and Copy Diagnostics before manually resuming.")
    if "-80046" in text:
        return ("-80046", "signing_failure",
                "AltServer failed with -80046; the precise Apple authentication cause isn't established.",
                "Review Copy Diagnostics and signing backend compatibility before resuming.")
    if "-80045" in text:
        return ("-80045", "signing_failure", "AltServer reported Apple signing error -80045.",
                "Check anisette identity and account before resuming.")
    if "-80043" in text:
        return ("-80043", "signing_failure", "AltServer reported Apple signing error -80043 (anisette identity rejected).",
                "Ensure anisette v3 (new.ani.sidestore.io) is configured before resuming.")
    if "verification failed" in text or "invalid verification" in text or "status code: 401" in text:
        return ("verification_failed", "verification", "Apple Account verification was unsuccessful.",
                "Confirm account access and the 2FA code before explicitly resuming.")
    if "timed out" in text or int(rc) == 124:
        return ("timeout", "timeout", "AltServer signing or installation timed out.",
                "Inspect the connection and signing logs before explicitly resuming.")
    if int(rc) < 0 or int(rc) in (130, 137, 143) or "terminated" in text:
        return ("interrupted", "interrupted", "The signing process was interrupted before a verified installation.",
                "Review Activity and explicitly resume only when the previous process has stopped.")
    return ("install_failed", "installation", "The signing/install attempt ended without a verified app installation.",
            "Read Activity diagnostics for the actual error and correct it before resuming.")


def begin():
    """Atomically reserve exactly one AltServer invocation; returns a secret-ish token.

    The token is not an Apple credential. It prevents a stale child from
    clearing another attempt's reservation.
    """
    with _mutex():
        assert_allowed()
        key = _identity()
        if not key:
            raise RuntimeError("Save an Apple Account before installing")
        token = secrets.token_hex(20)
        _write({"account": key, "phase": "running", "blocked": True,
                "token": token, "since": int(time.time())})
        return token


def _owns(record, token):
    return bool(token and record.get("token") == token and record.get("account") == _identity())


def succeeded(token):
    """Release only after the installed app's new profile is verified."""
    with _mutex():
        record = _read()
        if record.get("phase") != "running" or not _owns(record, token):
            raise RuntimeError("Cannot confirm a signing attempt that is not reserved by this job")
        FILE.unlink(missing_ok=True)
    return {"blocked": False}


def failed(output, rc=1, token=None):
    """Persist a failure; PTY job output may refine a generic shell error.

    An already-blocked account never gets silently rearmed. Failures from
    unreserved/background jobs cannot overwrite a different account's lock.
    """
    with _mutex():
        old = _read()
        if not old:
            # Legacy runs started before the new reservation was deployed.
            old = {"account": _identity(), "since": int(time.time())}
        if old.get("account") != _identity():
            return status()
        if old.get("phase") == "running" and not _owns(old, token):
            # PTY can refine once the shell wrote a generic failure, but it
            # cannot finalize a running reservation without its token.
            return status()
        code, reason, message, action = _classify(output, rc)
        if old.get("blocked") and old.get("phase") != "running":
            if old.get("code") != "install_failed" or code == "install_failed":
                return status()
        _write({"account": _identity(), "blocked": True, "phase": "failed",
                "code": code, "reason": reason, "message": message,
                "action": action, "since": old.get("since", int(time.time()))})
    return status()



def cancelled_2fa_timeout():
    """Classify an expired, unanswered 2FA prompt as a local cancellation.

    Keep signing paused pending explicit user resume; an Apple request already
    happened, so this must never silently authorize another request. Do not
    replace any specific Apple error already recorded by the child process.
    """
    with _mutex():
        old = _read()
        if old.get("account") != _identity():
            return status()
        if old.get("phase") not in ("running", "failed"):
            return status()
        if old.get("phase") == "failed" and old.get("code") != "install_failed":
            return status()
        _write({"account": _identity(), "blocked": True, "phase": "cancelled",
                "code": "2fa_timeout", "reason": "user_cancelled",
                "message": "Apple verification was not entered within 60 seconds. SideLoader cancelled the local signing process.",
                "action": "No automatic retry. Confirm account access before explicitly permitting one new attempt.",
                "since": old.get("since", int(time.time()))})
    return status()


def resume():
    with _mutex():
        # Called only through the explicit authenticated application API.
        FILE.unlink(missing_ok=True)
    return {"ok": True, "message": "Signing explicitly resumed. One new installation may be attempted."}


def _cli():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: retry_guard check|begin|success TOKEN|failed FILE RC TOKEN")
    command = sys.argv[1]
    if command == "check":
        try:
            assert_allowed()
            return 0
        except RuntimeError as exc:
            print("SIGNING STOPPED:", exc)
            return 73
    if command == "begin" and len(sys.argv) == 2:
        try:
            print(begin())
            return 0
        except RuntimeError as exc:
            print("SIGNING STOPPED:", exc, file=sys.stderr)
            return 73
    if command == "success" and len(sys.argv) == 3:
        succeeded(sys.argv[2])
        return 0
    if command == "failed" and len(sys.argv) in (4, 5):
        path = Path(sys.argv[2])
        try:
            output = path.read_text(errors="replace")[-30000:]
        except OSError:
            output = ""
        result = failed(output, int(sys.argv[3]), sys.argv[4] if len(sys.argv) == 5 else None)
        print("SIGNING PAUSED:", result.get("message", "Signing failed"))
        print("NEXT STEP:", result.get("action", "Review Activity before resuming."))
        return 0
    raise SystemExit("Unsupported signing safety operation")


if __name__ == "__main__":
    sys.exit(_cli())