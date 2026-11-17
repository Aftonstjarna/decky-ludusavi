import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from sandbox_api import Sandbox, GAMES
from automation import Automation

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'SaveDemo';self.root.mkdir()
        (self.root/'.savehaven.json').write_text(json.dumps({'kind':'savehaven-demo-sandbox','demo':True}))
        for name in GAMES.values():
            (self.root/name).mkdir();(self.root/name/'sample-save.json').write_text('{"level":1}')
        self.auto=Automation(Sandbox(self.root));self.auto.settle_seconds=0;self.auto.start()
    def tearDown(self):
        self.auto.shutdown();self.temp.cleanup()
    def run_cycles(self):
        self.auto.cycle();self.assertIsNone(self.auto.error)
        self.auto.cycle();self.assertIsNone(self.auto.error)
    def test_ludusavi_detection_filter_link_and_mirror(self):
        self.run_cycles()
        self.assertTrue((self.auto.sources/'port/saves').is_symlink())
        self.assertTrue((self.auto.sources/'gog/saves').is_symlink())
        self.assertFalse((self.auto.sources/'cloud/saves').is_symlink())
        self.assertFalse((self.auto.sources/'unknown/saves').is_symlink())
        self.assertEqual((self.auto.sources/'port/saves/save.json').read_bytes(),(self.root/'Managed/port/save.json').read_bytes())
        self.assertTrue((self.auto.mirror/'current/Managed/port/save.json').exists())
        self.assertFalse((self.auto.mirror/'current/Managed/cloud').exists())
        self.assertEqual(len(self.auto.status()['entries']),7)
    def test_original_path_write_mirrors_and_keeps_version(self):
        self.run_cycles();old=(self.root/'Managed/port/save.json').read_bytes()
        self.auto.action({'action':'sample-start','id':'port'})
        self.auto.action({'action':'simulate','id':'port'})
        self.assertEqual(old,(self.auto.mirror/'current/Managed/port/save.json').read_bytes())
        self.auto.action({'action':'sample-exit','id':'port'});self.auto.jobs.join()
        central=(self.root/'Managed/port/save.json').read_bytes()
        self.assertNotEqual(central,old)
        self.assertEqual(central,(self.auto.mirror/'current/Managed/port/save.json').read_bytes())
        self.assertTrue(any(p.read_bytes()==old for p in (self.auto.mirror/'versions').glob('*/Managed/port/save.json')))
    def test_explicit_cloud_exception_and_unknown_review(self):
        self.run_cycles();self.auto.action({'action':'rule','id':'cloud','override':'include'})
        self.auto.enqueue(['cloud']);self.auto.jobs.join()
        self.assertTrue((self.auto.sources/'cloud/saves').is_symlink())
        self.assertFalse((self.auto.sources/'unknown/saves').is_symlink())
    def test_disabled_does_not_migrate(self):
        self.auto.action({'action':'enabled','enabled':False})
        self.auto.cycle();self.auto.cycle()
        self.assertFalse((self.auto.sources/'port/saves').is_symlink())
    def test_collision_preserves_original(self):
        dest=self.root/'Managed/port';dest.mkdir(parents=True);(dest/'keep.json').write_text('mine')
        self.auto.cycle()
        self.assertIn('Destination already exists',self.auto.error)
        self.assertFalse((self.auto.sources/'port/saves').is_symlink())
        self.assertEqual((dest/'keep.json').read_text(),'mine')
        self.assertEqual(next(r for r in self.auto.rows if r['id']=='port')['state'],'Error')
    def test_zip_contains_current_backups_and_no_sources(self):
        self.run_cycles();name,data=self.auto.export()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIsNone(z.testzip());self.assertIn('Managed/port/save.json',z.namelist())
            self.assertIn('export-manifest.json',z.namelist())
            self.assertTrue(any(n.startswith('.migration-backups/') for n in z.namelist()))
            self.assertFalse(any(n.startswith('/') or '..' in Path(n).parts for n in z.namelist()))
        self.assertEqual(data,(self.root/'.exports'/name).read_bytes())
    def test_restart_recognizes_links(self):
        self.run_cycles();restart=Automation(Sandbox(self.root));restart.cycle()
        self.assertIsNone(restart.error)
        self.assertTrue((restart.sources/'port/saves').is_symlink())
    def test_changed_original_link_is_rejected(self):
        self.run_cycles();src=self.auto.sources/'port/saves';src.unlink();src.symlink_to(self.root/'Arx Fatalis')
        self.auto.cycle();self.assertIn('differs',self.auto.error)
    def test_mirror_symlink_is_rejected(self):
        self.run_cycles();target=self.auto.mirror/'current/Managed/port/save.json';target.unlink();target.symlink_to(self.root/'Arx Fatalis/sample-save.json')
        self.auto.cycle();self.assertIn('symlink',self.auto.error)

if __name__=='__main__':unittest.main()
