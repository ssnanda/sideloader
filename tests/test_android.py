"""Offline tests for Android APK mode: manifest parsing, adb output, repos, patch."""
import importlib.util
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = 'sample_sideloader_android'
pkg = types.ModuleType(PKG)
pkg.__path__ = []
config = types.ModuleType(PKG + '.config')
sys.modules.update({PKG: pkg, PKG + '.config': config})
for name in ('github_sources', 'android'):
    spec = importlib.util.spec_from_file_location(f'{PKG}.{name}', ROOT / f'overlay/{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
android = sys.modules[PKG + '.android']


def axml(package='com.example.app', version_code=112, version_name='1.3.9', drop_names=False):
    """Build a minimal aapt2-style binary AndroidManifest.xml."""
    strings = ['' if drop_names else 'versionCode', '' if drop_names else 'versionName',
               'package', 'manifest', package, version_name]
    body = b''.join(bytes([len(x), len(x)]) + x.encode() + b'\0' for x in strings)
    offsets, pos = [], 0
    for x in strings:
        offsets.append(pos)
        pos += len(x) + 3
    body += b'\0' * (-len(body) % 4)
    start = 28 + 4 * len(strings)
    pool = struct.pack('<HHIIIIII', 1, 28, start + len(body), len(strings), 0, 0x100, start, 0)
    pool += struct.pack(f'<{len(strings)}I', *offsets) + body
    resmap = struct.pack('<HHI', 0x0180, 8, 16) + struct.pack('<II', 0x0101021B, 0x0101021C)
    attrs = [  # ns, name, raw, size, res0, type, data
        (0xFFFFFFFF, 0, 0xFFFFFFFF, 8, 0, 0x10, version_code),
        (0xFFFFFFFF, 1, 5, 8, 0, 0x03, 5),
        (0xFFFFFFFF, 2, 4, 8, 0, 0x03, 4),
    ]
    element = struct.pack('<IIIIHHHHHH', 0, 0xFFFFFFFF, 0xFFFFFFFF, 3, 20, 20, len(attrs), 0, 0, 0)
    element += b''.join(struct.pack('<IIIHBBI', *a) for a in attrs)
    chunk = struct.pack('<HHI', 0x0102, 16, 8 + len(element)) + element
    content = pool + resmap + chunk
    return struct.pack('<HHI', 3, 8, 8 + len(content)) + content


class ManifestTests(unittest.TestCase):
    def test_reads_package_and_versions(self):
        self.assertEqual(android.parse_manifest(axml()),
                         {'versionCode': 112, 'versionName': '1.3.9', 'package': 'com.example.app'})

    def test_uses_resource_ids_when_attribute_names_are_stripped(self):
        info = android.parse_manifest(axml(drop_names=True))
        self.assertEqual((info['versionCode'], info['versionName']), (112, '1.3.9'))

    def test_rejects_invalid_package_and_non_apk(self):
        with self.assertRaises(ValueError):
            android.parse_manifest(axml(package='nodots'))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'x.apk'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('classes.dex', b'')
            with self.assertRaisesRegex(ValueError, 'not an Android APK'):
                android.inspect_apk(path)
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('AndroidManifest.xml', axml())
            self.assertEqual(android.inspect_apk(path)['package'], 'com.example.app')


class AdbOutputTests(unittest.TestCase):
    def test_devices(self):
        out = ('List of devices attached\n'
               '192.168.1.20:41234    device product:panther model:Pixel_7 device:panther transport_id:3\n'
               '192.168.1.21:5555     unauthorized transport_id:4\n')
        rows = android.parse_devices(out)
        self.assertEqual(rows[0]['model'], 'Pixel 7')
        self.assertEqual([r['state'] for r in rows], ['device', 'unauthorized'])

    def test_usb_and_wifi_transports(self):
        out = ('List of devices attached\n'
               'R5CT1234ABC  device usb:1-1 product:a54 model:SM_A546E device:a54x transport_id:1\n'
               'R5CT9999XYZ  unauthorized usb:1-2 transport_id:2\n'
               '192.168.1.20:41234 device product:p model:Pixel_7 device:p transport_id:3\n'
               'adb-1A2B._adb-tls-connect._tcp device product:p model:Pixel_7 transport_id:4\n')
        self.assertEqual([r['transport'] for r in android.parse_devices(out)], ['usb', 'usb', 'wifi', 'wifi'])

    def test_external_server_preferred_then_local_fallback(self):
        with patch.dict(android.os.environ, {'SIDELOADER_ADB_SERVER': '127.0.0.1:5037'}):
            with patch.object(android, '_reachable', return_value=True):
                self.assertEqual(android.server()['mode'], 'external')
            with patch.object(android, '_reachable', return_value=False):
                srv = android.server()
                self.assertEqual((srv['mode'], srv['port'], srv['external']), ('local', 5038, '127.0.0.1:5037'))
        with patch.dict(android.os.environ, {'SIDELOADER_ADB_SERVER': ''}):
            self.assertEqual(android.server()['mode'], 'local')

    def test_local_server_started_without_pipes(self):
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                patch.object(android, '_reachable', return_value=False), \
                patch.object(android.subprocess, 'run', side_effect=lambda argv, **kw: calls.append((argv, kw)) or
                             types.SimpleNamespace(returncode=0, stdout='List of devices attached\n', stderr='')):
            config.DATA = Path(d)
            android.adb('devices', srv={'mode': 'local', 'host': '127.0.0.1', 'port': 5038})
        start, run = calls
        self.assertEqual(start[0][1:], ['start-server'])
        self.assertIs(start[1]['stdout'], android.subprocess.DEVNULL)
        self.assertEqual(run[0][1:5], ['-H', '127.0.0.1', '-P', '5038'])

    def test_serial_validation(self):
        self.assertEqual(android._serial('R5CT1234ABC'), 'R5CT1234ABC')
        for bad in ('', '-s', 'a b', 'x;rm'):
            with self.assertRaises(ValueError):
                android._serial(bad)

    def test_mdns_and_packages(self):
        mdns = ('List of discovered mdns services\n'
                'adb-1A2B\t_adb-tls-connect._tcp\t192.168.1.20:41234\n'
                'adb-1A2B\t_adb-tls-pairing._tcp\t192.168.1.20:37000\n')
        self.assertEqual(android.parse_mdns(mdns), [{'name': 'adb-1A2B', 'address': '192.168.1.20:41234'}])
        pkgs = android.parse_packages('package:com.a versionCode:7 installer=null\n'
                                      'package:com.b  installer=com.android.vending\npackage:com.c\n')
        self.assertEqual(pkgs, {'com.a': {'versionCode': 7, 'installer': None},
                                'com.b': {'versionCode': None, 'installer': 'com.android.vending'},
                                'com.c': {'versionCode': None, 'installer': None}})

    def test_wifi_ipv4_from_route_or_wlan_address(self):
        self.assertEqual(android._wifi_ipv4('1.1.1.1 via 192.168.1.1 dev wlan0 src 192.168.1.44 uid 2000'),
                         '192.168.1.44')
        self.assertEqual(android._wifi_ipv4('', 'inet 10.0.0.8/24 brd 10.0.0.255 scope global wlan0'),
                         '10.0.0.8')
        self.assertIsNone(android._wifi_ipv4('', 'inet6 fe80::1/64'))

    def test_address_and_code_validation(self):
        for bad in ('192.168.1.20', '192.168.1.20:0', '192.168.1.20:70000', 'a b:5555', '-x:5555'):
            with self.assertRaises(ValueError):
                android._address(bad, 'x')
        with self.assertRaisesRegex(ValueError, '6-digit'):
            android.pair({'address': '192.168.1.20:37000', 'code': '12a456'})

    def test_pair_hides_code_in_failure(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(android, 'adb', return_value=(1, 'Failed: wrong code 123456')):
            config.DATA = Path(d)
            with self.assertRaises(RuntimeError) as ctx:
                android.pair({'address': '192.168.1.20:37000', 'code': '123456'})
        self.assertNotIn('123456', str(ctx.exception))


class SourceAndImportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config.DATA = Path(directory.name)

    def test_altstore_android_entries(self):
        obj = {'name': 'AJ Ops', 'apps': [
                   {'name': 'Front', 'android': {'packageName': 'com.x.front', 'version': '2.0',
                                                 'buildVersion': '20', 'downloadURL': 'front.apk'}}],
               'android': {'name': 'AJ Ops', 'packageName': 'com.itspector.ajops', 'version': '1.3.15',
                           'buildVersion': '118', 'type': 'apk',
                           'downloadURL': 'https://github.com/o/r/releases/download/android-latest/a.apk'}}
        rows = android.source_entries(obj, 'https://raw.githubusercontent.com/o/r/main/altstore.json')
        self.assertEqual([(r['name'], r['package'], r['versionCode'], r['origin']) for r in rows],
                         [('AJ Ops', 'com.itspector.ajops', 118, 'source'), ('Front', 'com.x.front', 20, 'source')])
        self.assertEqual(rows[1]['url'], 'https://raw.githubusercontent.com/o/r/main/front.apk')
        bad = {'android': [{'type': 'aab', 'downloadURL': 'https://x/a.aab'},
                           {'downloadURL': 'http://insecure/a.apk'}, {'name': 'no url'}]}
        self.assertEqual(android.source_entries(bad, 'https://x/'), [])

    def test_import_list_and_remove(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('AndroidManifest.xml', axml())
        raw = data.getvalue()
        row = android.import_apk(io.BytesIO(raw), len(raw), 'My App.apk')['apk']
        self.assertEqual((row['name'], row['package'], row['versionCode']), ('My App', 'com.example.app', 112))
        self.assertEqual([r['id'] for r in android.imported()['apks']], [row['id']])
        android.remove_imported({'id': row['id']})
        self.assertEqual(android.imported()['apks'], [])
        with self.assertRaises(ValueError):
            android.import_apk(io.BytesIO(b'not a zip'), 9, 'x.apk')
        with self.assertRaises(ValueError):
            android.import_apk(io.BytesIO(raw), len(raw) + 10, 'short.apk')

    def test_uninstall_requires_acknowledgement_and_valid_package(self):
        with self.assertRaises(ValueError):
            android.uninstall({'package': 'com.example.app', 'device': 'R5CT1'})
        with self.assertRaises(ValueError):
            android.uninstall({'package': 'bad name', 'acknowledge': True})


class RepoTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config.DATA = Path(directory.name)

    def test_repos_from_sources_and_extra(self):
        android.add_repo({'url': 'https://github.com/ssnanda/droidapp'})
        android.add_repo({'url': 'https://github.com/SSNANDA/DroidApp/'})  # duplicate
        found = android.repos(['https://raw.githubusercontent.com/ssnanda/ajopsios/refs/heads/main/altstore.json',
                               'github://ssnanda/private/altstore.json', 'https://example.com/a.json'])
        self.assertEqual(found, [('ssnanda', 'ajopsios'), ('ssnanda', 'droidapp'), ('ssnanda', 'private')])
        android.remove_repo({'owner': 'ssnanda', 'repo': 'droidapp'})
        self.assertNotIn(('ssnanda', 'droidapp'), android.repos([]))
        with self.assertRaises(ValueError):
            android.add_repo({'url': 'https://gitlab.com/a/b'})

    def test_latest_release_apks(self):
        releases = [{'draft': True, 'assets': [{'id': 9, 'name': 'draft.apk'}]},
                    {'tag_name': 'android-latest', 'assets': [
                        {'id': 5, 'name': 'app-release.apk', 'size': 3, 'updated_at': 't',
                         'browser_download_url': 'https://github.com/o/r/releases/download/android-latest/app-release.apk'},
                        {'id': 6, 'name': 'notes.txt'}]},
                    {'tag_name': 'old', 'assets': [{'id': 1, 'name': 'old.apk'}]}]
        with patch.object(android.github_sources, 'read_json', return_value=releases):
            apps, warning = android._repo_apks('o', 'r', '')
        self.assertEqual(warning, '')
        self.assertEqual([(a['id'], a['name'], a['tag']) for a in apps], [('5', 'r', 'android-latest')])


SERVER = '''from . import auth, config, ipa, pairing, store
class App:
    def __init__(self, jobs, health, muxers):
        self.sources = Sources()
    def routes(self):
        return {
            "/api/recheck": self.recheck,
        }


def handler(app):
    class Handler:
        def do_GET(self):
            path, _, query = self.path.partition("?")
            self.error(404, "not found")

        def do_POST(self):
            pass

        def do_PUT(self):
            pass

    return Handler
'''
PAGE = '''<html><head><style>
body{}
</style></head><body><script>
function appsView() {
  return "apple";
}
function wire() {
  const on = 1;
}
</script></body></html>'''
DOCKER = '''RUN apt-get update \\
 && apt-get install -y --no-install-recommends \\
      libimobiledevice-utils ideviceinstaller usbmuxd openssl python3 curl ca-certificates coreutils tzdata \\
 && rm -rf /var/lib/apt/lists/*
'''


class PatchTests(unittest.TestCase):
    def run_patch(self, root):
        return subprocess.run([sys.executable, str(ROOT / 'overlay/patch-android.py'), str(root), str(ROOT / 'overlay')],
                              capture_output=True, text=True)

    def test_patch_is_repeatable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'sideloop').mkdir()
            (root / 'sideloop/server.py').write_text(SERVER)
            (root / 'sideloop/index.html').write_text(PAGE)
            (root / 'Dockerfile').write_text(DOCKER)
            self.assertEqual(self.run_patch(root).returncode, 0)
            first = [(root / p).read_text() for p in ('sideloop/server.py', 'sideloop/index.html', 'Dockerfile')]
            self.assertEqual(self.run_patch(root).returncode, 0)
            second = [(root / p).read_text() for p in ('sideloop/server.py', 'sideloop/index.html', 'Dockerfile')]
            self.assertEqual(first, second)
            server, page, docker = second
            self.assertIn('from . import android\n', server)
            self.assertEqual(server.count('"/api/android/install"'), 1)
            self.assertEqual(server.count('if path.startswith("/api/android/"):'), 1)
            self.assertEqual(server.count('== "/api/apk"'), 1)
            self.assertIn('"/api/android/uninstall"', server)
            self.assertEqual(page.count('/* SideLoader Android v1 start */'), 1)
            self.assertEqual(page.count('/* SideLoader Android v1 css start */'), 1)
            self.assertIn('if (!slPlatformInner) return slPlatformView();', page)
            self.assertIn('androidWire(); /* SideLoader Android wire */', page)
            self.assertIn('coreutils tzdata adb \\', docker)
            self.assertTrue((root / 'sideloop/android.py').exists())

    def test_migrates_v1_routes(self):
        v1 = SERVER.replace('            "/api/recheck": self.recheck,\n',
            '            "/api/android/pair": android.pair,\n'
            '            "/api/android/connect": android.connect,\n'
            '            "/api/android/disconnect": android.disconnect,\n'
            '            "/api/android/install": lambda data: android.install(data, self.sources._urls()),\n'
            '            "/api/android/repos/add": android.add_repo,\n'
            '            "/api/android/repos/remove": android.remove_repo,\n'
            '            "/api/recheck": self.recheck,\n')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'sideloop').mkdir()
            (root / 'sideloop/server.py').write_text(v1)
            (root / 'sideloop/index.html').write_text(PAGE)
            (root / 'Dockerfile').write_text(DOCKER)
            self.assertEqual(self.run_patch(root).returncode, 0)
            server = (root / 'sideloop/server.py').read_text()
            self.assertEqual(server.count('"/api/android/pair"'), 1)
            self.assertIn('"/api/android/imported/remove"', server)

    def test_refuses_without_sources_api(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'sideloop').mkdir()
            (root / 'sideloop/server.py').write_text(SERVER.replace('self.sources = Sources()', ''))
            (root / 'sideloop/index.html').write_text(PAGE)
            (root / 'Dockerfile').write_text(DOCKER)
            result = self.run_patch(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'sideloop/index.html').read_text(), PAGE)


if __name__ == '__main__':
    unittest.main()
