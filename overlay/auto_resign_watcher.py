"""Automatic renewal for installed apps nearing provisioning expiry."""
import threading
import time

from . import config, retry_guard, store
from .account import is_verified
from .config import APPS
from .jobs import run_capture
from .log import log

RENEW_BEFORE_SECONDS = 6 * 60 * 60
CHECK_INTERVAL = 15 * 60
IDLE_INTERVAL = 60 * 60
ARRIVAL_DEBOUNCE = 5 * 60
RUN_TIMEOUT = 6 * 60 * 60


def configured(cfg=None):
    cfg = cfg or config.read()
    return bool(cfg["APPLE_ID"] and cfg["APPLE_PASSWORD"] and store.device_ids() and store.app_ids())


class Watcher:
    def __init__(self, jobs, health):
        self.jobs, self.health = jobs, health
        self.next_run = time.time() + 120
        self.last_poke = {}
        self.queue = set()
        self.lock = threading.Lock()

    def due_targets(self, devices=None):
        """Return every assigned app/device pair due within six hours.

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

    def loop(self):
        while True:
            time.sleep(5)
            timer = time.time() >= self.next_run
            with self.lock:
                queued = sorted(self.queue)
            if not timer and not queued:
                continue
            cfg = config.read()
            if cfg["AUTO_CHECK"] != "1" or not configured(cfg) or not is_verified():
                with self.lock:
                    self.queue.clear()
                self.schedule()
                continue
            if retry_guard.status().get("blocked"):
                with self.lock:
                    self.queue.clear()
                self.schedule()
                continue
            targets = self.due_targets(None if timer else queued)
            with self.lock:
                self.queue.clear()
            if not targets:
                self.schedule()
                continue
            job = self.jobs.claim_auto()
            if not job:
                continue
            try:
                for _expiry, app_id, udid in targets:
                    if retry_guard.status().get("blocked"):
                        break
                    run_capture(job, ["refresh.sh", "--auto", "--app", app_id, "--device", udid], RUN_TIMEOUT)
                    if job.rc:
                        break
            finally:
                job.ended = time.time()
                if job.lines:
                    log("watcher:", job.lines[-1])
                self.schedule()
                self.health.scan()
