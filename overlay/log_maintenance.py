"""Explicitly clear only SideLoader's old user-visible Activity/signing logs.

Never change the one-attempt reservation, previous result metadata, accounts,
profiles, IPA cache, pairing or application state. Never clear a running job.
"""
import os
from pathlib import Path
import secrets

from . import config


def clear_history(app):
    # Take the Jobs manager lock too: no new manual or automatic job may
    # start between the idle check and replacing the log.
    app.idle()
    with app.jobs.lock:
        if app.jobs.busy():
            raise RuntimeError("A signing job is running; logs cannot be cleared")
        path = config.STATE / "refresh.log"
        if path.is_symlink():
            raise ValueError("Activity log is a symlink; refusing to clear it")
        if path.exists() and not path.is_file():
            raise ValueError("Activity log is not a regular file")
        size = path.stat().st_size if path.exists() else 0
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.parent / (".sideloader-clear-log-" + secrets.token_hex(8))
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.close(fd)
            # Replace the log atomically without following symlinks.
            if path.is_symlink():
                raise ValueError("Activity log changed to a symlink; refusing to clear it")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

        # Copy Diagnostics also includes completed job lines from memory.
        # Keep the job object and exit status, only empty the old output.
        for job in (app.jobs.current, app.jobs.auto):
            if job is None:
                continue
            with job.lock:
                job.lines.clear()
                job.partial = ""
    return {"ok": True, "cleared_bytes": size,
            "message": "Old Activity logs cleared. Signing safety lock and app/device records preserved."}