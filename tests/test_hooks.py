import time
from unittest.mock import patch
import unittest
import test_automation as fixtures

class HookTests(unittest.TestCase):
    setUp = fixtures.AutomationTests.setUp
    tearDown = fixtures.AutomationTests.tearDown
    def map(self,ident,appid):
        self.auto.action({'action':'rule','id':ident,'appId':appid})
    def test_idle_and_start_do_not_scan(self):
        self.map('port','123')
        with patch.object(self.auto,'scan_ludusavi',wraps=self.auto.scan_ludusavi) as scan:
            self.auto.hook({'appId':'123','event':'start','name':'Test'})
            time.sleep(.15)
            self.assertEqual(scan.call_count,0)
            self.assertEqual(self.auto.scan_count,0)
    def test_exit_scans_only_affected_game_and_mirrors(self):
        self.map('port','123')
        with patch.object(self.auto,'scan_ludusavi',wraps=self.auto.scan_ludusavi) as scan:
            self.auto.hook({'appId':'123','event':'start'})
            self.auto.hook({'appId':'123','event':'exit'})
            self.auto.jobs.join()
            self.assertEqual(scan.call_count,1)
            self.assertEqual([e['id'] for e in scan.call_args.args[0]],['port'])
            self.assertTrue((self.auto.sources/'port/saves').is_symlink())
            self.assertTrue((self.auto.mirror/'current/Managed/port/save.json').exists())
    def test_cloud_and_unknown_skipped_before_ludusavi(self):
        self.map('cloud','234');self.map('unknown','345')
        with patch.object(self.auto,'scan_ludusavi',wraps=self.auto.scan_ludusavi) as scan:
            for appid in ['234','345']:
                self.auto.hook({'appId':appid,'event':'exit'})
            self.auto.jobs.join();self.assertEqual(scan.call_count,0)
    def test_duplicate_exit_coalesced(self):
        self.map('port','123')
        self.auto.hook({'appId':'123','event':'exit'});self.auto.jobs.join()
        self.auto.hook({'appId':'123','event':'exit'});self.auto.jobs.join()
        self.assertEqual(self.auto.scan_count,1)
    def test_paused_exit_does_not_queue(self):
        self.map('port','123');self.auto.action({'action':'enabled','enabled':False})
        result=self.auto.hook({'appId':'123','event':'exit'})
        self.assertEqual(result['queued'],[]);self.assertEqual(self.auto.scan_count,0)
    def test_unmapped_event_only_records_review(self):
        result=self.auto.hook({'appId':'987','event':'exit','name':'Unknown game'})
        self.assertFalse(result['mapped']);self.assertEqual(self.auto.scan_count,0)
        self.assertIn('987',self.auto.unmapped)
    def test_running_game_is_not_moved_by_manual_scan(self):
        self.map('port','123');self.auto.hook({'appId':'123','event':'start'})
        self.auto.cycle(force=True,ids=['port'])
        self.assertEqual(self.auto.scan_count,0)
        self.assertFalse((self.auto.sources/'port/saves').is_symlink())
