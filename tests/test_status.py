import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('niimbot_status',Path(__file__).resolve().parents[1]/'ipp/status.py')
status=importlib.util.module_from_spec(spec);spec.loader.exec_module(status)

class StatusMapping(unittest.TestCase):
    def test_verified_cover_and_rfid_errors(self):
        self.assertEqual(status.error_status({'reasonId':1})[0],1)
        reason,message=status.error_status({'reasonId':20})
        self.assertEqual(reason,3)
        self.assertIn('RFID',message)
        self.assertNotIn('empty',message)

    def test_unknown_code_not_promoted_to_feed_error(self):
        reason,message=status.error_status({'reasonId':8,'message':'raw code 8'})
        self.assertEqual((reason,message),(7,'raw code 8'))
        self.assertEqual(status.error_status({'reasonId':True})[0],7)

    def test_transport_failures_are_distinct(self):
        self.assertEqual(status.error_status({'category':'offline'})[0],4)
        reason,message=status.error_status({'category':'link'})
        self.assertEqual(reason,5);self.assertIn('partial',message)

    def test_snapshot_preserves_count_and_sanitizes_framing(self):
        with tempfile.TemporaryDirectory() as folder:
            status.publish(folder,1,5,'lost\nlink\rstill partial')
            self.assertEqual((Path(folder)/'status.txt').read_text(),'1 1 5\nlost link still partial\n')
            self.assertFalse((Path(folder)/'status.tmp').exists())

if __name__=='__main__':unittest.main()
