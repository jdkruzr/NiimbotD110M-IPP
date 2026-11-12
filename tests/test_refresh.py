import importlib.util
from pathlib import Path
import unittest
from unittest import mock
import tempfile, os, json, fcntl, io
from contextlib import redirect_stdout
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('refresh',ROOT/'ipp/refresh.py');refresh=importlib.util.module_from_spec(spec);spec.loader.exec_module(refresh)
spec=importlib.util.spec_from_file_location('copies',ROOT/'scripts/fix-cups-image-copies.py');copies=importlib.util.module_from_spec(spec);spec.loader.exec_module(copies)

class FakeSocket:
    def __init__(self,chunks):self.chunks=iter(chunks);self.sent=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def connect(self,address):pass
    def sendall(self,packet):self.sent.append(packet)
    def settimeout(self,value):pass
    def recv(self,count):return next(self.chunks,b'')

class RefreshTests(unittest.TestCase):
    def test_fragmented_read_only_query(self):
        data=bytes.fromhex('1074044b00000100000000')
        stream=refresh.frame(0xc2,b'\x03')+refresh.frame(0xa0,b'\x01')+refresh.frame(0xd9,data)
        sock=FakeSocket([stream[i:i+3] for i in range(0,len(stream),3)])
        self.assertEqual(refresh.query(sock),{'lidClosed':True,'paperInserted':True,'paperRfidSuccess':True})
        self.assertEqual(sock.sent,[bytes.fromhex('035555c10101c1aaaa'),bytes.fromhex('5555dc0104d9aaaa')])

    def test_rejects_short_heartbeat(self):
        with self.assertRaises(ValueError):refresh.sensors(b'\0'*8)

    def test_bad_checksum_cannot_report_ready(self):
        packet=bytearray(refresh.frame(0xd9,b'\0'*11));packet[-3]^=1
        sock=FakeSocket([refresh.frame(0xc2,b'\x03'),packet])
        with self.assertRaises(ConnectionError):refresh.query(sock)

    def test_open_cover_and_absent_paper(self):
        observed=refresh.sensors(bytes.fromhex('1074044b01010000000000'))
        self.assertEqual(observed,{'lidClosed':False,'paperInserted':False,'paperRfidSuccess':False})

    def test_refresh_preserves_uncertain_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'niimbot';state.mkdir()
            config=state/'config.json';config.write_text(json.dumps({'address':'08:85:2D:07:26:16','channel':1}))
            journal=state/'niimbot-job-test.json';journal.write_text('{"state":"uncertain"}')
            sock=FakeSocket([refresh.frame(0xc2,b'\x03'),refresh.frame(0xd9,bytes.fromhex('1074044b00000100000000'))])
            with mock.patch.dict(os.environ,{'XDG_STATE_HOME':tmp,'XDG_CONFIG_HOME':tmp,'XDG_RUNTIME_DIR':tmp}),mock.patch.object(refresh.socket,'socket',return_value=sock),redirect_stdout(io.StringIO()) as output:
                refresh.main()
            self.assertTrue(json.loads(output.getvalue())['recoveryPending'])
            self.assertEqual(journal.read_text(),'{"state":"uncertain"}')
            self.assertEqual((state/'refresh-status.txt').read_text().splitlines()[0].split()[-1],'6')

    def test_busy_supervisor_prevents_bluetooth_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'niimbot';state.mkdir()
            with (state/'supervisor.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                with mock.patch.dict(os.environ,{'XDG_STATE_HOME':tmp}),mock.patch.object(refresh.socket,'socket') as sock:
                    with self.assertRaisesRegex(RuntimeError,'active'):refresh.main()
                    sock.assert_not_called()

class QueueCopiesTests(unittest.TestCase):
    text='*cupsManualCopies: True\n*cupsFilter2: "image/png image/png 0 -"\n*cupsFilter2: "image/jpeg image/jpeg 0 -"\n*cupsFilter2: "image/urf image/urf 100 -"\n'
    def test_only_passthrough_removed_and_fix_is_idempotent(self):
        fixed=copies.fix(self.text)
        self.assertEqual(fixed,'*cupsManualCopies: True\n*cupsFilter2: "image/jpeg image/jpeg 0 -"\n*cupsFilter2: "image/urf image/urf 100 -"\n')
        self.assertEqual(copies.fix(fixed),fixed)
    def test_hardware_copy_queue_preserved(self):
        text=self.text.replace('True','False');self.assertEqual(copies.fix(text),text)
    def test_no_raster_filter_refused(self):
        with self.assertRaises(ValueError):copies.fix('*cupsManualCopies: True\n')

if __name__=='__main__':unittest.main()
