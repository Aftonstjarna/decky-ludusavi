import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from centralize import candidates,inventory,relocate
from live_backend import LiveBackend,LiveService

BINARY=Path.home()/'Games/Tools/ludusavi'

class CentralizationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.source=self.base/'game/saves';self.source.mkdir(parents=True)
        (self.source/'slot.sav').write_bytes(b'original')
        self.root=self.base/'Saves';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()
    def test_move_preserves_original_and_links_directory(self):
        original=inventory(self.source)
        result=relocate(self.source,self.root,'Game',self.base/'journal',original)
        self.assertTrue(self.source.is_symlink());self.assertEqual(inventory(Path(result['recovery'])),original)
        self.assertEqual(inventory(self.source.resolve()),original)
        (self.source/'slot2.sav').write_bytes(b'next')
        self.assertTrue((Path(result['destination'])/'slot2.sav').exists())
    def test_changed_save_is_not_moved(self):
        original=inventory(self.source);(self.source/'slot.sav').write_bytes(b'changed')
        with self.assertRaises(ValueError):relocate(self.source,self.root,'Game',self.base/'journal',original)
        self.assertFalse(self.source.is_symlink())
    def test_failed_symlink_rolls_original_back(self):
        with patch.object(Path,'symlink_to',side_effect=OSError('failure')):
            with self.assertRaises(OSError):relocate(self.source,self.root,'Game',self.base/'journal',inventory(self.source))
        self.assertEqual((self.source/'slot.sav').read_bytes(),b'original');self.assertFalse(self.source.is_symlink())
    def test_mixed_folder_is_not_a_candidate(self):
        files={str(self.source/'slot.sav'):{'bytes':8}}
        self.assertIn(self.source,candidates(files,self.root))
        (self.source/'unrelated.txt').write_text('not backed up')
        self.assertEqual(candidates(files,self.root),{})
    def test_symlinks_are_not_moved(self):
        (self.source/'link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):inventory(self.source)

@unittest.skipUnless(BINARY.exists(),'Native Ludusavi required')
class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        binary=self.home/'Games/Tools/ludusavi';binary.parent.mkdir(parents=True);binary.symlink_to(BINARY)
        root=self.home/'Saves';root.mkdir();(root/'.savehaven.json').write_text('{"kind":"savehaven-live"}')
        self.source=self.home/'test-game/saves';self.source.mkdir(parents=True);(self.source/'slot.sav').write_bytes(b'binary\x00data'*100)
        config=self.home/'.config/ludusavi';config.mkdir(parents=True)
        (config/'manifest.yaml').write_text('Cloud Game:\n  cloud:\n    steam: true\n  steam:\n    id: 123\n  files: {}\n')
        backup=str(self.home/'second-disk/backups')
        (config/'config.yaml').write_text(json.dumps({'manifest':{'enable':True},'roots':[],'release':{'check':False},'cloud':{'synchronize':False},'backup':{'path':backup,'filter':{'cloud':{'exclude':True,'steam':True}},'retention':{'full':3,'differential':0}},'restore':{'path':backup},'customGames':[{'name':'Test (Non-Steam)','files':[str(self.source)]}]}))
        self.backend=LiveBackend(self.home)
    def tearDown(self):self.backend.close();self.temp.cleanup()
    def test_native_backup_centralization_and_native_restore(self):
        original=(self.source/'slot.sav').read_bytes()
        preview=self.backend.execute({'action':'preview','games':['Test (Non-Steam)']})
        self.assertIn('Test (Non-Steam)',preview['games']);self.assertFalse(self.source.is_symlink())
        result=self.backend.execute({'action':'backup','games':['Test (Non-Steam)']})
        self.assertTrue(self.source.is_symlink());self.assertEqual(len(result['centralized']),1)
        versions=self.backend.execute({'action':'backups','games':['Test (Non-Steam)']})
        version=versions['games']['Test (Non-Steam)']['backups'][0]['name']
        (self.source/'slot.sav').write_bytes(b'changed')
        self.backend.execute({'action':'restore-preview','games':['Test (Non-Steam)'],'backup':version})
        self.assertEqual((self.source/'slot.sav').read_bytes(),b'changed')
        self.backend.execute({'action':'restore','games':['Test (Non-Steam)'],'backup':version})
        self.assertEqual((self.source/'slot.sav').read_bytes(),original)
        self.assertTrue(list((self.backend.state_dir/'before-restore').iterdir()))
    def test_cloud_filter_applies_to_named_hook_backups(self):
        self.assertFalse(self.backend.allowed('Cloud Game'))
        result=self.backend.execute({'action':'backup','games':['Cloud Game']})
        self.assertEqual(result['excluded'],['Cloud Game'])
        self.assertTrue(self.backend.allowed('Test (Non-Steam)'))
    def test_start_does_not_scan_and_exit_is_targeted(self):
        self.backend.settings['aliases']['123']='Test (Non-Steam)'
        self.backend.hook({'appId':'123','event':'start'})
        self.assertEqual(self.backend.scan_count,0)
        self.backend.hook({'appId':'123','event':'exit'});self.backend.jobs.join()
        self.assertIsNone(self.backend.error)
        self.assertTrue(self.source.is_symlink());self.assertEqual(self.backend.scan_count,1)
        self.assertFalse(self.backend.hook({'appId':'123','event':'exit'})['queued'])
    def test_plugin_service_starts_and_stops_web_listener(self):
        self.backend.close()
        service=LiveService(self.home,Path(__file__).resolve().parents[1]/'web',port=0)
        service.start()
        import urllib.request
        port=service.server.server_port
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/live') as r:self.assertTrue(json.load(r)['live'])
        service.close()
        self.assertFalse(service.thread.is_alive());self.assertFalse(service.automation.thread.is_alive())
        import socket
        with socket.socket() as sock:self.assertNotEqual(sock.connect_ex(('127.0.0.1',port)),0)
        self.backend=LiveBackend(self.home)
    def test_native_zip_export(self):
        result=self.backend.execute({'action':'export','games':['Test (Non-Steam)']})
        import zipfile
        with zipfile.ZipFile(self.backend.state_dir/'exports'/result['export']) as z:
            self.assertIsNone(z.testzip());self.assertTrue(any(n.endswith('.zip') for n in z.namelist()));self.assertTrue(any(n.endswith('mapping.yaml') for n in z.namelist()))
        self.assertFalse(self.source.is_symlink())

if __name__=='__main__':unittest.main()
