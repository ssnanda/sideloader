"""Check actual iOS installed-app inventory (not provisioning profiles)."""
import json
import plistlib
import re
import subprocess
import threading
import time

CACHE_SECONDS = 45
_cache = {}
_lock = threading.Lock()
UDID_PATTERN = re.compile(r'^[0-9A-Fa-f-]{20,64}$')
BUNDLE_PATTERN = re.compile(r'^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$')
TEAM_ID_PATTERN = re.compile(r'^[A-Z0-9]{10}$')


def _run(argv, timeout=18):
    return subprocess.run(argv, capture_output=True, timeout=timeout, check=False)


def _connection_modes(udid):
    try:
        usb = _run(['idevice_id', '-l'], timeout=6)
        wifi = _run(['idevice_id', '-n'], timeout=6)
    except (OSError, subprocess.TimeoutExpired):
        return [False, True]
    available = []
    if usb.returncode == 0 and udid.lower() in usb.stdout.decode('utf-8', 'replace').lower().split():
        available.append(False)
    if wifi.returncode == 0 and udid.lower() in wifi.stdout.decode('utf-8', 'replace').lower().split():
        available.append(True)
    return available or [False, True]


def _matches_signed_bundle(installed_bundle, source_bundle):
    """Match an IPA ID or AltServer's free-team suffixed installed ID."""
    if installed_bundle == source_bundle:
        return True
    prefix = source_bundle + '.'
    return (isinstance(installed_bundle, str)
            and installed_bundle.startswith(prefix)
            and TEAM_ID_PATTERN.fullmatch(installed_bundle[len(prefix):]) is not None)


def _parse_inventory(payload, bundle):
    # Debian releases print optional progress banners before the XML plist.
    start = payload.find(b'<?xml')
    if start < 0:
        start = payload.find(b'<plist')
    if start < 0:
        raise ValueError('installed-app list did not contain an XML plist')
    end = payload.rfind(b'</plist>')
    if end < start:
        raise ValueError('installed-app plist incomplete')
    data = plistlib.loads(payload[start:end + len(b'</plist>')])
    entries = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
    return any(isinstance(row, dict)
               and _matches_signed_bundle(row.get('CFBundleIdentifier'), bundle)
               for row in entries)


def probe(udid, bundle, use_cache=True):
    """installed/missing/unknown; never call missing for a connection failure."""
    if not UDID_PATTERN.fullmatch(udid or '') or not BUNDLE_PATTERN.fullmatch(bundle or ''):
        return {'state': 'unknown', 'reason': 'invalid device or bundle identifier'}
    key = (udid.lower(), bundle)
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if use_cache and entry and now - entry[0] < CACHE_SECONDS:
            return dict(entry[1])
    result = {'state': 'unknown', 'reason': 'could not read installed apps'}
    for network in _connection_modes(udid):
        argv = ['ideviceinstaller', '-u', udid]
        if network:
            argv.append('-n')
        # AltServer appends the Apple Team ID to free-development bundle IDs.
        # ideviceinstaller's server-side bundle filter is exact, so filtering
        # by the source IPA ID would hide the installed suffixed application.
        argv += ['list', '--user', '--xml']
        try:
            response = _run(argv)
            if response.returncode:
                continue
            found = _parse_inventory(response.stdout, bundle)
            result = {'state': 'installed' if found else 'missing'}
            break
        except (OSError, subprocess.TimeoutExpired, ValueError, plistlib.InvalidFileException):
            continue
    with _lock:
        _cache[key] = (now, result)
    return dict(result)


def enrich_apps(apps, live):
    for app in apps:
        for target in app.get('targets', []):
            device = live.get(target['udid'].lower())
            if not device or not device.get('reachable'):
                target['installation'] = {'state': 'offline'}
            else:
                target['installation'] = probe(target['udid'], app['bundle_id'])
    return apps


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('udid')
    parser.add_argument('bundle')
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()
    print(probe(args.udid, args.bundle, use_cache=not args.no_cache)['state'])


if __name__ == '__main__':
    main()
