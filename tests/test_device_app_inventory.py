import importlib.util
from pathlib import Path
import plistlib
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('device_app_inventory_test',Path(__file__).resolve().parents[1]/'overlay'/'device_app_inventory.py')
lib=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)
UDID='00008160-00052C6E1821400A'
BUNDLE='com.example.myapp'

class DeviceAppInventoryTests(unittest.TestCase):
    def test_xml_list_parsing_does_not_mislabel_appstore_apps(self):
        data=plistlib.dumps([{'CFBundleIdentifier':BUNDLE,'CFBundleDisplayName':'My Xcode App',
                               'SignerIdentity':'Apple Development: Test Team',
                               'CFBundleShortVersionString':'1.2'},
                              {'CFBundleIdentifier':'com.apple.storeapp','CFBundleName':'Store App'},
                              {'CFBundleIdentifier':'no space!', 'CFBundleName':'Bad'}])
        apps=lib.parse_apps(b'Complete\n'+data)
        self.assertEqual(len(apps),2)
        x=next(x for x in apps if x['bundle_id']==BUNDLE)
        self.assertIn('Developer signed',x['origin'])
        store=next(x for x in apps if x['bundle_id']=='com.apple.storeapp')
        self.assertEqual(store['origin'],'Origin not reported')

    def test_xml_dictionary_style(self):
        apps=lib.parse_apps(plistlib.dumps({BUNDLE:{'CFBundleIdentifier':BUNDLE,'CFBundleName':'TapTether'}}))
        self.assertEqual(len(apps),1)
        self.assertEqual(apps[0]['name'],'TapTether')

    def test_missing_inventory_never_claims_no_apps(self):
        with self.assertRaises(RuntimeError):lib.parse_apps(b'No iPhone online')
        with patch.object(lib,'_exec',return_value=subprocess.CompletedProcess([],1,stdout=b'',stderr=b'Offline')):
            with self.assertRaises(RuntimeError):lib.inventory(UDID)

    def test_read_only_inventory_without_apple_requests(self):
        data=plistlib.dumps([{'CFBundleIdentifier':BUNDLE}])
        calls=[]
        def runner(args,timeout=30):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,stdout=data,stderr=b'')
        with patch.object(lib,'_exec',side_effect=runner):
            apps=lib.inventory(UDID)
        self.assertEqual(apps[0]['bundle_id'],BUNDLE)
        self.assertEqual(calls[0][:3],['ideviceinstaller','-u',UDID])
        self.assertNotIn('AltServer',str(calls))

    def test_explicit_uninstall_only_for_current_inventory(self):
        class FakeApp:
            def idle(self):pass
        calls=[]
        def runner(args,timeout=30):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,stdout=b'',stderr=b'')
        with patch.object(lib,'inventory',return_value=[{'bundle_id':BUNDLE}]),patch.object(lib,'_exec',side_effect=runner):
            result=lib.remove_apps(FakeApp(),UDID,[BUNDLE])
        self.assertEqual(result['removed'],[BUNDLE])
        self.assertEqual(calls[0],['ideviceinstaller','-u',UDID,'uninstall',BUNDLE])
        with patch.object(lib,'inventory',return_value=[]):
            with self.assertRaises(ValueError):lib.remove_apps(FakeApp(),UDID,[BUNDLE])

    def test_bad_identifiers_refused(self):
        class FakeApp:
            def idle(self):pass
        for arr in ([],['com.example.a','com.example.a'],['bad; rm -rf /'],[BUNDLE]*26):
            with self.assertRaises(ValueError):lib.remove_apps(FakeApp(),UDID,arr)
        with self.assertRaises(ValueError):lib.inventory('bad')

if __name__=='__main__':unittest.main()