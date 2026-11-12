import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env = dict(os.environ, XDG_STATE_HOME=str(self.base/'state'), NIIMBOT_FAKE='1')
        self.children = []

    def tearDown(self):
        for p in self.children:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()
            p.stderr.close()
        self.tmp.cleanup()

    def start(self, name='one', scenario='success'):
        folder = self.base/('niimbot-job-'+name)
        folder.mkdir(exist_ok=True)
        (folder/'1.raw').write_bytes(bytes([255])*30720)
        p = subprocess.Popen(['python3', str(ROOT/'ipp/supervise.py'), str(folder), '1'],
                             env=dict(self.env, NIIMBOT_FAKE_SCENARIO=scenario),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(p)
        return p

    def record(self, name='one'):
        return json.loads((self.base/'state/niimbot'/('niimbot-job-'+name+'.json')).read_text())

    def transmitting(self, p):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            try:
                if self.record()['state']=='transmitting':
                    return
            except (FileNotFoundError, ValueError):
                pass
            if p.poll() is not None:
                self.fail(p.communicate())
            time.sleep(.02)
        self.fail('worker did not start')

    def test_success_and_same_job_not_replayed(self):
        p=self.start(); self.assertEqual(p.wait(timeout=5),0)
        self.assertEqual(self.record()['state'],'completed')
        p=self.start(); self.assertNotEqual(p.wait(timeout=5),0)
        self.assertEqual(self.record()['state'],'completed')

    def test_offline_is_terminal_without_recovery_hold(self):
        p=self.start(scenario='offline'); self.assertNotEqual(p.wait(timeout=5),0)
        self.assertEqual(self.record()['state'],'failed-before-transmission')
        self.assertEqual(self.start('two').wait(timeout=5),0)

    def test_link_loss_blocks_new_jobs_until_explicit_acknowledgement(self):
        p=self.start(scenario='link-loss');self.assertNotEqual(p.wait(timeout=5),0)
        self.assertEqual(self.record()['state'],'uncertain')
        self.assertNotEqual(self.start('two').wait(timeout=5),0)
        subprocess.run(['python3',str(ROOT/'ipp/supervise.py'),'recover','--acknowledge','niimbot-job-one.json'],env=self.env,check=True)
        self.assertEqual(self.start('three').wait(timeout=5),0)

    def test_missing_completion_is_not_success(self):
        self.assertNotEqual(self.start(scenario='missing-completion').wait(timeout=5),0)
        self.assertEqual(self.record()['state'],'uncertain')

    def test_deadline_stops_stalled_worker(self):
        self.env['NIIMBOT_FAKE_TIMEOUT']='0.2'
        self.assertNotEqual(self.start(scenario='stall').wait(timeout=5),0)
        self.assertEqual(self.record()['state'],'uncertain')

    def test_cancel_stalled_worker_and_lock(self):
        p=self.start(scenario='stall');self.transmitting(p)
        self.assertNotEqual(self.start('two').wait(timeout=5),0)
        p.send_signal(signal.SIGTERM);self.assertNotEqual(p.wait(timeout=5),0)
        self.assertEqual(self.record()['state'],'uncertain')
        self.assertNotEqual(self.start('three').wait(timeout=5),0)

    def test_supervisor_sigkill_stops_worker_and_keeps_recovery_hold(self):
        p=self.start(scenario='stall');self.transmitting(p)
        child_ids=Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()
        self.assertTrue(child_ids)
        p.kill();p.wait(timeout=5)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            alive=[]
            for child in child_ids:
                stat=Path(f'/proc/{child}/stat')
                if stat.exists() and stat.read_text().split()[2]!='Z':alive.append(child)
            if not alive:break
            time.sleep(.02)
        self.assertFalse(alive)
        self.assertEqual(self.record()['state'],'transmitting')
        self.assertNotEqual(self.start('two').wait(timeout=5),0)

if __name__=='__main__':unittest.main()
