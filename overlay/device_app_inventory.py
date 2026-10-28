"""Read and explicitly uninstall iPhone user apps without invoking Apple signing.

This can include App Store apps: installation origin is not always available.
Never infer that every app listed by ideviceinstaller is developer-signed.
"""
from pathlib import Path
import plistlib
import re
import subprocess
import threading

UDID = re.compile(r"^[0-9A-Fa-f-]{20,64}$")
BUNDLE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")
MAX_OUTPUT = 8 * 1024 * 1024
_MUTEX = threading.Lock()


def _exec(args, timeout=30):
    return subprocess.run(args, capture_output=True, timeout=timeout, check=False)


def _read_plist(data):
    if len(data) > MAX_OUTPUT:
        raise ValueError('iPhone app inventory exceeds maximum response size')
    start = data.find(b'<?xml')
    if start < 0:
        start = data.find(b'<plist')
    end = data.rfind(b'</plist>')
    if start < 0 or end < start:
        raise RuntimeError('iPhone did not return a valid app inventory')
    info = plistlib.loads(data[start:end + 8])
    if isinstance(info, dict):
        entries = list(info.values())
    elif isinstance(info, list):
        entries = info
    else:
        raise ValueError('unexpected iPhone app inventory format')
    return entries


def _origin(row):
    # 'User' means user-installed (including App Store), NOT sideloaded.
    signer = str(row.get('SignerIdentity') or row.get('SignerIdentityName') or '')
    if any(x in signer.lower() for x in ('apple development:', 'iphone developer:',
                                         'apple distribution:', 'iphone distribution:')):
        return 'Developer signed (reported)'
    return 'Origin not reported'


def parse_apps(data):
    found = {}
    for row in _read_plist(data):
        if not isinstance(row, dict):
            continue
        bundle = row.get('CFBundleIdentifier') or row.get('BundleIdentifier')
        if not isinstance(bundle, str) or not BUNDLE.fullmatch(bundle):
            continue
        if bundle in found:
            continue
        name = row.get('CFBundleDisplayName') or row.get('CFBundleName') or bundle
        version = row.get('CFBundleShortVersionString') or ''
        found[bundle] = {'bundle_id': bundle, 'name': str(name)[:160],
                         'version': str(version)[:64], 'origin': _origin(row),
                         'installed': True}
    return sorted(found.values(), key=lambda x: (x['name'].lower(), x['bundle_id']))


def inventory(udid):
    """A read-only query; no signing or Apple login. Raises on offline/error."""
    if not isinstance(udid, str) or not UDID.fullmatch(udid):
        raise ValueError('invalid device identifier')
    last = 'The iPhone is not responding to an installed-app query.'
    for network in (False, True):
        args = ['ideviceinstaller', '-u', udid]
        if network:
            args.append('-n')
        args += ['list', '--user', '--xml']
        try:
            response = _exec(args)
            if response.returncode == 0:
                return parse_apps(response.stdout)
            last = response.stderr.decode('utf-8', 'replace')[:250] or last
        except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException,
                ValueError, RuntimeError) as err:
            last = str(err)[:250]
    raise RuntimeError('Cannot scan the iPhone: ' + last)


def remove_apps(app, udid, bundle_ids):
    """Remove only explicitly approved, currently installed user apps.

    No AltServer calls. Recheck current inventory before each removal, fail
    closed on an offline device, and serialize uninstall batches.
    """
    if not isinstance(bundle_ids, list) or not 1 <= len(bundle_ids) <= 25:
        raise ValueError('choose 1–25 installed apps')
    if len(set(bundle_ids)) != len(bundle_ids) or any(not isinstance(x, str) or
                                                       not BUNDLE.fullmatch(x) for x in bundle_ids):
        raise ValueError('invalid or duplicate app bundle IDs')
    if not UDID.fullmatch(str(udid)):
        raise ValueError('invalid device identifier')
    if not _MUTEX.acquire(blocking=False):
        raise RuntimeError('another iPhone app removal is already running')
    try:
        app.idle()  # Refuse deletion while signing or pairing jobs are running.
        installed = {x['bundle_id'] for x in inventory(udid)}
        missing = set(bundle_ids) - installed
        if missing:
            raise ValueError('Selected apps are no longer confirmed on this iPhone: ' + ', '.join(sorted(missing)))
        removed = []
        for bundle in bundle_ids:
            app.idle()
            try:
                result = _exec(['ideviceinstaller', '-u', udid, 'uninstall', bundle], timeout=75)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise RuntimeError('App removal stopped after ' + str(len(removed)) +
                                   ' apps; inspect the device and rescan: ' + str(e)) from e
            if result.returncode:
                raise RuntimeError('App removal failed after ' + str(len(removed)) +
                                   ' apps; rescan before retrying. Last bundle: ' + bundle)
            removed.append(bundle)
        return {'removed': removed, 'count': len(removed),
                'note': 'Device apps removed; SideLoader IPA files and signing lock unchanged.'}
    finally:
        _MUTEX.release()