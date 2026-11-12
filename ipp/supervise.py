#!/usr/bin/env python3
"""One-shot print supervision with durable uncertainty and explicit recovery."""
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
UNCERTAIN = {'starting', 'transmitting', 'uncertain'}


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def stop_group(child):
    if child is None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # The leader may have exited while a descendant is still alive.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def main():
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'niimbot'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (state/'supervisor.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another job is active; recovery and printing are locked')
    # Keep the lock alive until the process exits.
    folder = None if sys.argv[1] == 'recover' else Path(sys.argv[1])
    records = []
    for path in state.glob('niimbot-job-*.json'):
        try:
            value = json.loads(path.read_text())
        except (ValueError, OSError):
            value = {'state': 'uncertain'}
        if value.get('state') in UNCERTAIN:
            records.append((path, value))
    if folder is None:
        if len(sys.argv) == 2:
            for path, value in records:
                print(path.name, value.get('state'))
            return 0
        if len(sys.argv) != 4 or sys.argv[2] != '--acknowledge':
            raise RuntimeError('Usage: supervise.py recover [--acknowledge JOURNAL_NAME]')
        for path, value in records:
            if path.name == sys.argv[3]:
                atomic_json(path, {**value, 'state': 'acknowledged', 'acknowledgedAt': time.time()})
                return 0
        raise RuntimeError('No matching uncertain job; nothing acknowledged')
    if records:
        raise RuntimeError('Prior job may have printed; run supervise.py recover and explicitly acknowledge it before resubmitting')
    pages = sorted(folder.glob('*.raw'), key=lambda p: int(p.stem))
    if sys.argv[2:] != ['1'] or not 1 <= len(pages) <= 100:
        raise RuntimeError('Expected 1..100 already-expanded raster pages')
    manifest = folder/'manifest.json'
    manifest.write_text(json.dumps({'version': 1, 'pages': [str(p) for p in pages]}))
    fake = os.environ.get('NIIMBOT_FAKE') == '1'
    if fake:
        command = [os.environ.get('NIIMBOT_NODE', 'node'), str(ROOT/'ipp/worker.cjs'), str(manifest)]
    else:
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'niimbot/config.json'
        settings = json.loads(config.read_text())
        command = ['python3', str(ROOT/'scripts/niimblue-classic.py'), '--address', settings['address'],
                   '--channel', str(settings['channel']), '--deadline', str(15+30*len(pages)), 'worker', str(manifest)]
    journal = state/(folder.name+'.json')
    if journal.exists():
        raise RuntimeError('Job already attempted; refusing automatic replay')
    child = None
    cancelled = False
    transmitted = False
    completed = False
    failed = False
    confirmed = 0
    parent = os.getppid()

    def cancel(*_):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)

    def record(status):
        atomic_json(journal, {'state': status, 'time': time.time(), 'confirmedPages': confirmed,
                              'expectedPages': len(pages), 'simulated': fake})

    record('starting')
    try:
        if cancelled:
            raise RuntimeError('Cancelled before connecting')
        guarded = ['python3', str(ROOT/'scripts/process_guard.py'), str(os.getpid()), *command]
        child = subprocess.Popen(guarded, start_new_session=True, stdout=subprocess.PIPE)
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        buffer = b''
        budget = float(os.environ.get('NIIMBOT_FAKE_TIMEOUT', 25+30*len(pages))) if fake else 25+30*len(pages)
        until = time.monotonic()+budget
        while selector.get_map():
            if cancelled or os.getppid() != parent:
                raise RuntimeError('Cancelled or service exited; physical output may be partial')
            if time.monotonic() > until:
                raise RuntimeError('Print deadline exceeded; physical output may be partial')
            for key, _ in selector.select(.1):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer += chunk
                if len(buffer) > 65536:
                    raise RuntimeError('Worker event exceeds limit')
                while b'\n' in buffer:
                    row, buffer = buffer.split(b'\n', 1)
                    event = json.loads(row)
                    if event.get('version') != 1:
                        raise RuntimeError('Invalid worker event version')
                    kind = event.get('type')
                    if kind == 'transmitting':
                        transmitted = True
                        record('transmitting')
                    elif kind in ('progress', 'completed'):
                        count = event.get('confirmedPages')
                        if type(count) is not int or not confirmed <= count <= len(pages):
                            raise RuntimeError('Invalid physical page count')
                        confirmed = count
                        if kind == 'completed':
                            completed = count == len(pages)
                    elif kind == 'error':
                        failed = True
                        (folder/'error.txt').write_text(str(event.get('message', 'Unknown printer error')))
                    print(row.decode(), flush=True)
        code = child.wait(timeout=3)
        if cancelled or code != 0 or failed or not completed or buffer:
            raise RuntimeError('Job did not confirm successful physical completion; inspect printer before retrying')
        record('completed')
        return 0
    except BaseException:
        stop_group(child)
        record('failed-before-transmission' if child is None or (failed and not transmitted) else 'uncertain')
        raise
    finally:
        if child is not None:
            child.stdout.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        if len(sys.argv) > 1 and sys.argv[1] != 'recover':
            path = Path(sys.argv[1])/'error.txt'
            if not path.exists():
                path.write_text(str(error))
        print(json.dumps({'version': 1, 'type': 'error', 'message': str(error)}), flush=True)
        sys.exit(1)
