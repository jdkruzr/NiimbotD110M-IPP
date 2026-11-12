"""Isolated IPP failure tests: no CUPS queues, Bluetooth, or live-service changes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]

class IppSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.log=(self.base/'service.log').open('w')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.env=dict(os.environ,NIIMBOT_FAKE='1',NIIMBOT_FAKE_SCENARIO='stall',
                      NIIMBOT_PORT=str(self.port),NIIMBOT_SPOOL=str(self.base),XDG_STATE_HOME=str(self.base/'state'))
        self.service=None;self.start()

    def tearDown(self):
        if self.service and self.service.poll() is None:
            self.service.terminate()
            try:self.service.wait(timeout=5)
            except subprocess.TimeoutExpired:self.service.kill();self.service.wait()
        self.log.close();self.tmp.cleanup()

    def start(self):
        self.service=subprocess.Popen([str(ROOT/'ipp/niimbot-ipp')],cwd=ROOT,env=self.env,stdout=self.log,stderr=self.log)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1',self.port),timeout=.1):return
            except OSError:time.sleep(.02)
        self.fail('Service failed to listen')

    def ipp(self, operation, extra='', expect=''):
        text='''{ OPERATION %s
GROUP operation-attributes-tag
ATTR charset attributes-charset utf-8
ATTR language attributes-natural-language en
ATTR uri printer-uri $uri
%s
STATUS successful-ok
%s
}\n'''%(operation,extra,expect)
        test=self.base/'request.test';test.write_text(text)
        result=subprocess.run(['ipptool','-tv','-f',str(ROOT/'fixtures/calibration-12x40.png'),
                               f'ipp://localhost:{self.port}/ipp/print',str(test)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout

    def submit(self):
        self.ipp('Print-Job','ATTR mimeMediaType document-format image/png\nFILE $filename')

    def journals(self):
        return list((self.base/'state/niimbot').glob('niimbot-job-*.json'))

    def wait_for(self, predicate):
        for _ in range(150):
            if predicate():return
            time.sleep(.02)
        self.fail('Timed out waiting for state transition')

    def test_cancel_active_ipp_job(self):
        self.submit()
        self.wait_for(lambda:any(json.loads(p.read_text())['state']=='transmitting' for p in self.journals()))
        self.ipp('Get-Job-Attributes','ATTR integer job-id 1','EXPECT job-impressions-completed WITH-VALUE 0')
        self.ipp('Cancel-Job','ATTR integer job-id 1')
        self.wait_for(lambda:any(json.loads(p.read_text())['state']=='uncertain' for p in self.journals()))
        self.ipp('Get-Job-Attributes','ATTR integer job-id 1','EXPECT job-state WITH-VALUE 7 REPEAT-NO-MATCH REPEAT-LIMIT 5')
        self.assertIsNone(self.service.poll())

    def test_service_sigkill_and_restart_do_not_replay(self):
        self.submit()
        self.wait_for(lambda:any(json.loads(p.read_text())['state']=='transmitting' for p in self.journals()))
        self.service.kill();self.service.wait(timeout=5)
        self.wait_for(lambda:any(json.loads(p.read_text())['state']=='uncertain' for p in self.journals()))
        before={p.name:p.read_text() for p in self.journals()}
        self.start();self.submit()
        time.sleep(.5)
        self.ipp('Get-Job-Attributes','ATTR integer job-id 1','EXPECT job-state WITH-VALUE 8')
        self.assertEqual(before,{p.name:p.read_text() for p in self.journals()})

    def test_crash_after_completed_job_still_holds_resubmission(self):
        self.service.terminate();self.service.wait(timeout=5)
        self.env['NIIMBOT_FAKE_SCENARIO']='success';self.start();self.submit()
        self.wait_for(lambda:any(json.loads(p.read_text())['state']=='completed' for p in self.journals()))
        self.service.kill();self.service.wait(timeout=5)
        before={p.name:p.read_text() for p in self.journals()}
        self.start();self.submit();time.sleep(.3)
        self.ipp('Get-Job-Attributes','ATTR integer job-id 1','EXPECT job-state WITH-VALUE 8')
        self.assertTrue((self.base/'recovery-required').exists())
        self.assertEqual(before,{p.name:p.read_text() for p in self.journals()})

    def configure_scenario(self, scenario):
        self.service.terminate();self.service.wait(timeout=5)
        self.scenario_file=self.base/'scenario'
        self.scenario_file.write_text(scenario)
        self.env['NIIMBOT_FAKE_SCENARIO_FILE']=str(self.scenario_file)
        self.start()

    def test_physical_progress_survives_partial_failure(self):
        self.configure_scenario('partial-link')
        self.ipp('Print-Job','ATTR mimeMediaType document-format image/png\nGROUP job-attributes-tag\nATTR integer copies 2\nFILE $filename')
        self.ipp('Get-Job-Attributes','ATTR integer job-id 1','EXPECT job-state WITH-VALUE 8 REPEAT-NO-MATCH REPEAT-LIMIT 5\nEXPECT job-impressions-completed WITH-VALUE 1')
        self.ipp('Get-Printer-Attributes',expect='EXPECT printer-state-reasons WITH-VALUE offline')

    def test_cover_error_is_visible_in_ipp(self):
        self.configure_scenario('cover');self.submit()
        self.ipp('Get-Job-Attributes','ATTR integer job-id 1','EXPECT job-state WITH-VALUE 8 REPEAT-NO-MATCH REPEAT-LIMIT 5\nEXPECT job-impressions-completed WITH-VALUE 0\nEXPECT job-state-message WITH-VALUE /lid/')
        self.ipp('Get-Printer-Attributes',expect='EXPECT printer-state-reasons WITH-VALUE cover-open')

    def test_offline_reason_clears_after_success(self):
        self.configure_scenario('offline');self.submit()
        self.ipp('Get-Job-Attributes','ATTR integer job-id 1','EXPECT job-state WITH-VALUE 8 REPEAT-NO-MATCH REPEAT-LIMIT 5\nEXPECT job-impressions-completed WITH-VALUE 0')
        self.ipp('Get-Printer-Attributes',expect='EXPECT printer-state-reasons WITH-VALUE offline')
        self.scenario_file.write_text('success');self.submit()
        self.ipp('Get-Job-Attributes','ATTR integer job-id 2','EXPECT job-state WITH-VALUE 9 REPEAT-NO-MATCH REPEAT-LIMIT 5\nEXPECT job-impressions-completed WITH-VALUE 1')
        self.ipp('Get-Printer-Attributes',expect='EXPECT printer-state-reasons WITH-VALUE none')

if __name__=='__main__':unittest.main()
