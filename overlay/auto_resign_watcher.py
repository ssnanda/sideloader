"""Automatic renewal and source updates for apps installed on registered iPhones."""
# SideLoader canonical watcher (legacy watcher patches detect this line).
import re
import threading
import time

from . import config, retry_guard, store
from .account import is_verified
from .config import APPS
from .jobs import run_capture
from .log import log

# Re-sign as soon as fewer than six of the seven signing days remain, so each
# app renews about once a day and a phone away from home has days of slack.
RENEW_BEFORE_SECONDS = 6 * 24 * 60 * 60
CHECK_INTERVAL = 15 * 60
IDLE_INTERVAL = 60 * 60
UPDATE_INTERVAL = 6 * 60 * 60
UPDATE_RETRY = 24 * 60 * 60
ARRIVAL_DEBOUNCE = 5 * 60
RUN_TIMEOUT = 6 * 60 * 60


def configured(cfg=None):
    cfg = cfg or config.read()
    return bool(cfg["APPLE_ID"] and cfg["APPLE_PASSWORD"] and store.device_ids() and store.app_ids())


class _NoIdleCheck:
    """Sources.install() asks the app to be idle; the watcher owns the auto job."""

    def idle(self):
        return None


class Watcher:
    def __init__(self, jobs, health):
        self.jobs, self.health = jobs, health
        self.next_run = time.time() + 120
        self.next_update = time.time() + 300
        self.update_requested = False
        self.failed_updates = {}
        self.last_poke = {}
        self.queue = set()
        self.lock = threading.Lock()
        self.status = {"paused": "", "last_run": None, "last_rc": None, "last_message": "",
                       "last_updates": [], "last_kick": None}

    def due_targets(self, devices=None):
        """Return every assigned app/device pair with under six days left.

        A saved expiry is required. Missing expiries are handled by the user's
        read-only device scan, rather than triggering an unsolicited Apple login.
        refresh.sh independently confirms the app still exists on the phone
        before it signs, so stale assignments cannot reinstall removed apps.
        """
        now = time.time()
        allowed = set(devices or [])
        targets = []
        for app_id in store.app_ids():
            for udid in store.app_devices(app_id):
                if allowed and udid not in allowed:
                    continue
                expiry = store.read_state(APPS / app_id / "state" / udid)["expiry"]
                if expiry and expiry - now <= RENEW_BEFORE_SECONDS:
                    targets.append((expiry, app_id, udid))
        return sorted(targets)

    def update_targets(self, devices=None):
        """Saved apps whose saved source lists a strictly newer version."""
        from .sources import Sources, version_is_newer

        allowed = set(devices or [])
        saved = set(store.app_ids())
        now = time.time()
        found, seen = [], set()
        for source in Sources().list()["sources"]:
            for item in source.get("apps", []):
                bundle = item["bundleIdentifier"]
                app_id = re.sub(r"[^A-Za-z0-9._-]", "_", bundle)[:120]
                if app_id not in saved or app_id in seen:
                    continue
                view = store.app_view(app_id)
                if not version_is_newer(item["version"], view["version"],
                                        item.get("buildVersion", ""), view.get("build", "")):
                    continue
                key = f"{app_id}@{item['version']}+{item.get('buildVersion', '')}"
                if now - self.failed_updates.get(key, 0) < UPDATE_RETRY:
                    continue
                devices_for_app = [u for u in store.app_devices(app_id) if not allowed or u in allowed]
                if devices_for_app:
                    seen.add(app_id)
                    found.append({"source": source["id"], "bundle": bundle, "app_id": app_id,
                                  "version": item["version"], "key": key, "devices": devices_for_app})
        return found

    def due(self):
        return bool(self.due_targets())

    def schedule(self):
        self.next_run = time.time() + (CHECK_INTERVAL if self.due() else IDLE_INTERVAL)

    def poke(self, udid):
        now = time.time()
        with self.lock:
            if now - self.last_poke.get(udid, 0) < ARRIVAL_DEBOUNCE:
                return
            self.last_poke[udid] = now
            self.queue.add(udid)
        log(f"watcher: {store.device_name(udid)} came online")

    def kick(self, udid=None):
        """A signed-in client (TapTether) reports the phone is on this network."""
        with self.lock:
            if udid:
                self.queue.add(udid)
            else:
                self.next_run = 0
            self.update_requested = True
            self.status["last_kick"] = int(time.time())
        log(f"watcher: check requested{' for ' + store.device_name(udid) if udid else ''}")

    def status_view(self):
        due = [{"app": a, "device": store.device_name(u), "expiry": int(e)}
               for e, a, u in self.due_targets()]
        with self.lock:
            return {**self.status, "running": bool(self.jobs.auto and self.jobs.auto.running),
                    "next_run": int(self.next_run), "next_update_check": int(self.next_update),
                    "renew_below_days": RENEW_BEFORE_SECONDS // 86400, "due": due}

    def _pause(self, reason):
        with self.lock:
            self.queue.clear()
            self.update_requested = False
            self.status["paused"] = reason
        self.schedule()

    def loop(self):
        while True:
            time.sleep(5)
            now = time.time()
            timer = now >= self.next_run
            with self.lock:
                queued = sorted(self.queue)
                update_due = self.update_requested or now >= self.next_update
            if not timer and not queued and not update_due:
                continue
            cfg = config.read()
            if cfg["AUTO_CHECK"] != "1":
                self._pause("automatic renewal is turned off")
                continue
            if not configured(cfg):
                self._pause("Apple account, iPhone or app not set up")
                continue
            if not is_verified():
                self._pause("waiting for one successful manual install")
                continue
            if retry_guard.status().get("blocked"):
                self._pause(retry_guard.status().get("message") or "signing paused after a failed attempt")
                continue
            with self.lock:
                self.status["paused"] = ""
            targets = self.due_targets(None if timer else queued) if (timer or queued) else []
            updates = []
            if update_due:
                with self.lock:
                    self.update_requested = False
                self.next_update = now + UPDATE_INTERVAL
                try:
                    updates = self.update_targets(None if not queued else queued)
                except Exception as exc:  # network/source errors must not stop renewals
                    log(f"watcher: update check failed: {exc}")
            with self.lock:
                self.queue.clear()
            if not targets and not updates:
                self.schedule()
                continue
            job = self.jobs.claim_auto()
            if not job:
                continue
            updated, results = set(), []
            try:
                from .sources import Sources
                for update in updates:
                    if retry_guard.status().get("blocked"):
                        break
                    job.say(f"Update {update['bundle']} to {update['version']}")
                    try:
                        # Downloads the newest IPA, refuses a bundle mismatch,
                        # and refuses when the app is no longer on the phone.
                        Sources().install({"source": update["source"], "bundleIdentifier": update["bundle"],
                                           "device": update["devices"][0], "reinstall_latest": True,
                                           "install_now": False}, _NoIdleCheck())
                    except (ValueError, RuntimeError, OSError) as exc:
                        job.say(f"✗ update {update['bundle']} not downloaded: {exc}")
                        self.failed_updates[update["key"]] = time.time()
                        results.append(f"{update['bundle']} {update['version']}: {exc}")
                        continue
                    for udid in update["devices"]:
                        # --force: an update installs even when the signature is
                        # not due; --auto still skips apps removed from the phone.
                        run_capture(job, ["refresh.sh", "--auto", "--force", "--app", update["app_id"],
                                          "--device", udid], RUN_TIMEOUT)
                        if job.rc:
                            self.failed_updates[update["key"]] = time.time()
                            results.append(f"{update['bundle']} {update['version']}: signing failed")
                            break
                        updated.add((update["app_id"], udid))
                        results.append(f"{update['bundle']} {update['version']}: installed")
                    if job.rc:
                        break
                for _expiry, app_id, udid in targets:
                    if job.rc or retry_guard.status().get("blocked"):
                        break
                    if (app_id, udid) in updated:
                        continue
                    # The watcher decides due-ness with second precision;
                    # refresh.sh's whole-day threshold would otherwise skip it.
                    run_capture(job, ["refresh.sh", "--auto", "--force", "--app", app_id, "--device", udid],
                                RUN_TIMEOUT)
            finally:
                job.ended = time.time()
                with self.lock:
                    self.status.update({"last_run": int(job.ended), "last_rc": job.rc or 0,
                                        "last_message": job.lines[-1] if job.lines else "",
                                        "last_updates": results})
                if job.lines:
                    log("watcher:", job.lines[-1])
                self.schedule()
                self.health.scan()
