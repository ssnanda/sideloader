"""Remove SideLoader's stored Apple sign-in without deleting app/device data."""
import shutil
from . import config


def forget_account(app):
    # Refuse removal while a signing or recheck job is running.
    app.idle()
    cache = config.DATA / "AltServerData"
    if cache.is_symlink() or (cache.exists() and not cache.is_dir()):
        raise RuntimeError("Unexpected signing-cache path; account was not changed")
    try:
        if cache.is_dir():
            shutil.rmtree(cache)
    except OSError as exc:
        raise RuntimeError("Could not clear signing cache; account was not changed") from exc
    # Do not remove saved device pairings, apps, dashboard password or history.
    config.update({"APPLE_ID": "", "APPLE_PASSWORD": "", "AUTO_CHECK": "0"})
    return {"ok": True}
