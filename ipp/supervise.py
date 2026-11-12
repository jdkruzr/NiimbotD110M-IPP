#!/usr/bin/env python3
"""Bounded one-shot worker supervisor. Never replays physical jobs."""
import json, os, pathlib, signal, subprocess, sys, time, selectors
root=pathlib.Path(__file__).resolve().parent.parent
folder=pathlib.Path(sys.argv[1]); copies=int(sys.argv[2])
pages=sorted(folder.glob('*.raw'),key=lambda p:int(p.stem))*copies
if not 1<=len(pages)<=100: raise SystemExit('Invalid physical label count')
manifest=folder/'manifest.json';manifest.write_text(json.dumps({'version':1,'pages':[str(p) for p in pages]}))
config=pathlib.Path(os.environ.get('XDG_CONFIG_HOME',str(pathlib.Path.home()/'.config')))/'niimbot/config.json'
fake=os.environ.get('NIIMBOT_FAKE')=='1'
if fake: command=['node',str(root/'ipp/worker.cjs'),str(manifest)]
else:
 c=json.loads(config.read_text())
 command=['python3',str(root/'scripts/niimblue-classic.py'),'--address',c['address'],'--channel',str(c['channel']),'--deadline',str(15+30*len(pages)),'worker',str(manifest)]
state=pathlib.Path(os.environ.get('XDG_STATE_HOME',str(pathlib.Path.home()/'.local/state')))/'niimbot'
state.mkdir(parents=True,exist_ok=True,mode=0o700)
journal=state/(folder.name+'.json')
def record(status):
 with journal.open('w') as f:
  json.dump({'state':status,'time':time.time()},f);f.flush();os.fsync(f.fileno())
record('uncertain')
p=subprocess.Popen(command,start_new_session=True,stdout=subprocess.PIPE)
def cancel(*_):
 os.killpg(p.pid,signal.SIGTERM)
 try:p.wait(timeout=3)
 except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
 record('cancelled-possibly-partial');sys.exit(1)
signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ)
buffer=b'';completed=False;until=time.monotonic()+25+30*len(pages)
while selector.get_map():
 if time.monotonic()>until:cancel()
 for key,_ in selector.select(.1):
  chunk=os.read(key.fd,4096)
  if not chunk:selector.unregister(key.fileobj);continue
  buffer+=chunk
  while b'\n' in buffer:
   row,buffer=buffer.split(b'\n',1)
   print(row.decode(errors='replace'),flush=True)
   try:event=json.loads(row)
   except ValueError:continue
   if event.get('type')=='completed':completed=event.get('confirmedPages')==len(pages)
   if event.get('type')=='error':
    (folder/'error.txt').write_text(event.get('message','Unknown printer error'))
code=p.wait(timeout=5)
record('completed' if code==0 and completed else 'failed-possibly-partial')
sys.exit(0 if code==0 and completed else 1)
