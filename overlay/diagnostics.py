"""Printable, privacy-filtered support report for SideLoader."""
import datetime
import re
from . import config, store
from .installed import enrich_apps

SENSITIVE_LINE = re.compile(r'(?:^\s*\d{6,8}\s*$|(?:verification|two.?factor|2fa|code)\D{0,30}\d{6,8}|X-Apple-|X-Mme-|X-MMe-|HMAC_OUT|One-Time Password|MachineID|^Byte:|^Value\s*:|^Data\s*:|Authorization:|Bearer |session.?token|Cookie:)', re.I)
UDID = re.compile(r'(?<![A-Za-z0-9])[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{12,60}(?![A-Za-z0-9])')
EMAIL = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
IP = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')


def scrub(line, secrets=()):
    line = str(line).strip()[:600]
    if SENSITIVE_LINE.search(line):
        return '[sensitive signing output omitted]'
    for secret in secrets:
        if secret:
            line = line.replace(secret, '[REDACTED]')
    line = EMAIL.sub('[APPLE_ID]', line)
    line = UDID.sub('[DEVICE_ID]', line)
    line = IP.sub('[IP_ADDRESS]', line)
    return line


def report(app):
    cfg = config.read()
    state = app.state()  # Includes verified install states or offline/unknown.
    secrets = (cfg.get('APPLE_PASSWORD', ''), cfg.get('APPLE_ID', ''))
    lines = [
        'SideLoader diagnostic report (sanitized)',
        'UTC: ' + datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'NOTE: Diagnostic errors are not proof of an installed app.',
        'Services: device_mux=' + str(state['services']['muxer']) + ', anisette=' + str(state['services']['anisette']),
        'Auto refresh: ' + str(state['config']['auto_check']),
        'Registered devices: ' + str(len(state['registered'])),
        'Signing safety: blocked=' + str(bool(state.get('signing_guard', {}).get('blocked'))) +
            ' code=' + str(state.get('signing_guard', {}).get('code', 'none')) +
            ' reason=' + str(state.get('signing_guard', {}).get('reason', 'none')),
        '', 'App inventory:',
    ]
    for entry in state['apps']:
        lines.append('- ' + scrub(entry['name'], secrets) + ' (' + scrub(entry['bundle_id'], secrets) + ')')
        for target in entry.get('targets', []):
            sign = target.get('signature', {})
            install = target.get('installation', {}).get('state', 'unknown')
            last = sign.get('last_run') or {}
            lines.append('  device=' + scrub(target['name'], secrets) + ' installed=' + install +
                         ' cached_profile_expiry=' + str(sign.get('expiry') or 'none') +
                         ' last_result=' + str(last.get('result', 'none')))
    lines += ['', 'Latest signing log (last 250 lines):']
    try:
        raw = (config.STATE / 'refresh.log').read_text(errors='replace').splitlines()[-250:]
    except OSError:
        raw = []
    if not raw:
        lines.append('(no saved Activity/signing logs)')
    for ln in raw:
        clean = scrub(ln, secrets)
        if clean != '[sensitive signing output omitted]':
            lines.append(clean)
    for job_name, job in (('Manual job', app.jobs.current), ('Automatic job', app.jobs.auto)):
        if job:
            lines += ['', job_name + ': ' + scrub(job.title, secrets)]
            for ln in job.view(0).get('lines', [])[-120:]:
                clean = scrub(ln, secrets)
                if clean != '[sensitive signing output omitted]':
                    lines.append(clean)
    if any('-80046' in ln for ln in lines):
        lines += ['', 'HINT: -80046 after 2FA is commonly a Mac-anisette / Apple app-token issue, not proof of a Wi-Fi failure.']
    return '\n'.join(lines) + '\n'
