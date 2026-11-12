#!/usr/bin/env python3
"""Run the existing NiimBlue serial CLI through a userspace RFCOMM/PTTY bridge.

The channel must come from SDP discovery. No privileged /dev/rfcomm binding.
The watchdog is a last resort: expiry means physical completion is unknown.
"""
import argparse
import json
import sys
import fcntl
import re
import os
from pathlib import Path
import pty
import select
import socket
import subprocess
import time
import tty


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--address', required=True)
    p.add_argument('--channel', type=int, required=True)
    p.add_argument('--deadline', type=float, default=60)
    p.add_argument('cli', nargs=argparse.REMAINDER)
    a = p.parse_args()
    if not 1 <= a.channel <= 30 or a.deadline <= 0 or not a.cli:
        p.error('Provide a valid discovered channel, positive deadline, and CLI command')
    if a.cli[0] not in ('info', 'rfid', 'print', 'worker'):
        p.error('Only info, rfid, print, and worker are supported')
    if any(x in a.cli for x in ('-a', '--address', '-t', '--transport')):
        p.error('Transport and serial address are supplied by this bridge')
    if not re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}', a.address):
        p.error('Invalid Bluetooth address')
    root = Path(__file__).resolve().parent.parent
    locks = Path(os.environ.get('XDG_RUNTIME_DIR', str(Path.home()/'.cache'))) / 'niimbot-locks'
    locks.mkdir(parents=True, exist_ok=True)
    lock = (locks / (a.address.lower().replace(':', '-') + '.lock')).open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        p.error('Another connection to this printer is already active')
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(10)
    child = None
    master = slave = None
    try:
        s.connect((a.address, a.channel))
        master, slave = pty.openpty()
        tty.setraw(slave)
        command = ['node', str(root/'research/niimblue-node/cli.mjs'), *a.cli,
                   '-t', 'serial', '-a', os.ttyname(slave)]
        if a.cli[0] == 'worker':
            command = ['node', str(root/'ipp/worker.cjs'), a.cli[1], os.ttyname(slave)]
        child = subprocess.Popen(command)
        until = time.monotonic() + a.deadline
        while child.poll() is None:
            if time.monotonic() >= until:
                raise TimeoutError('Watchdog expired; physical print completion is UNKNOWN; do not automatically retry')
            readable, _, _ = select.select([s, master], [], [], .1)
            for fd in readable:
                if fd is s:
                    data = s.recv(65536)
                    if not data:
                        raise ConnectionError('Printer disconnected; physical completion may be unknown')
                    while data:
                        data = data[os.write(master, data):]
                else:
                    data = os.read(master, 65536)
                    if data:
                        s.sendall(data)
        return child.returncode
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        s.close()
        lock.close()
        for fd in (master, slave):
            if fd is not None:
                os.close(fd)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, TimeoutError, ConnectionError) as error:
        if 'worker' in sys.argv:
            print(json.dumps({'version': 1, 'type': 'error', 'message': str(error)}), flush=True)
        else:
            print(str(error), file=sys.stderr)
        raise SystemExit(1)
