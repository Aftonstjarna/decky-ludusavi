import json
from pathlib import Path
import tempfile
import unittest
from sandbox_api import Sandbox, GAMES

class FileManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'.savehaven.json').write_text(json.dumps({'kind':'savehaven-demo-sandbox','demo':True}))
        for game in GAMES.values():
            (self.root/game).mkdir()
            (self.root/game/'sample-save.json').write_text('{"level":1}')
        self.store = Sandbox(self.root)
    def tearDown(self):
        self.temp.cleanup()
    def request(self, action, **extra):
        return {'id':'ds3','action':action,'revision':self.store.listing()['files'][0]['revision'],**extra}
    def test_edit_restore_and_history(self):
        result=self.store.action(self.request('save',content='{"level":2}'))
        self.assertEqual(json.loads(self.store.file('ds3').read_text()),{'level':2})
        self.store.action(self.request('restore',backup=result['previousVersion']))
        self.assertEqual(json.loads(self.store.file('ds3').read_text()),{'level':1})
        self.assertEqual(len(self.store.listing()['files'][0]['backups']),2)
    def test_stale_edit(self):
        r=self.request('save',content='{}');self.store.file('ds3').write_text('{"level":3}')
        with self.assertRaises(ValueError):self.store.action(r)
        self.assertEqual(json.loads(self.store.file('ds3').read_text()),{'level':3})
    def test_invalid_json_preserves_file(self):
        with self.assertRaises(ValueError):self.store.action(self.request('save',content='not JSON'))
        self.assertEqual(self.store.file('ds3').read_text(),'{"level":1}')
        self.assertFalse((self.root/'.backups').exists())
    def test_path_traversal(self):
        with self.assertRaises(ValueError):self.store.action(self.request('restore',backup='../outside.json'))
        with self.assertRaises(ValueError):self.store.action({'id':'../outside','action':'backup'})
    def test_symlink(self):
        p=self.store.file('ds3');p.unlink();p.symlink_to(self.root/'Arx Fatalis/sample-save.json')
        with self.assertRaises(ValueError):self.store.listing()
    def test_marker(self):
        (self.root/'.savehaven.json').write_text('{}')
        with self.assertRaises(ValueError):self.store.action({'id':'ds3','action':'backup'})
    def test_manual_backup_does_not_modify(self):
        self.store.action(self.request('backup'))
        self.assertEqual(self.store.file('ds3').read_text(),'{"level":1}')
        self.assertEqual(len(self.store.listing()['files'][0]['backups']),1)

if __name__=='__main__':unittest.main()
