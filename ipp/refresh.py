#!/usr/bin/env python3
"""Read D110M sensors over RFCOMM; never send print, feed, or reset commands."""
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import sys
import time


def frame(command, data):
    packet = bytes([command, len(data)])+data
    checksum = 0
    for value in packet:
        checksum ^= value
    return b'\x55\x55'+packet+bytes([checksum])+b'\xaa\xaa'


class Reader:
    def __init__(self, sock, deadline):
        self.sock, self.deadline, self.buffer = sock, deadline, bytearray()

    def response(self, command):
        while True:
            while len(self.buffer) >= 7:
                if self.buffer[:2] != b'\x55\x55':
                    del self.buffer[0]
                    continue
                length = self.buffer[3]+7
                if len(self.buffer) < length:
                    break
                candidate = bytes(self.buffer[:length])
                checksum = 0
                for value in candidate[2:-3]:
                    checksum ^= value
                if checksum != candidate[-3] or candidate[-2:] != b'\xaa\xaa':
                    del self.buffer[0]
                    continue
                del self.buffer[:length]
                if candidate[2] == command:
                    return candidate[4:-3]
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Status query timed out')
            self.sock.settimeout(min(remaining, 5))
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('Printer disconnected during status query')
            self.buffer.extend(chunk)


def sensors(data):
    if len(data) < 9:
        raise ValueError('Incomplete heartbeat response; status unknown')
    return {'lidClosed': data[4] == 0, 'paperInserted': data[5] == 0,
            'paperRfidSuccess': data[6] != 0}


def query(sock):
    reader = Reader(sock, time.monotonic()+15)
    sock.sendall(b'\x03'+frame(0xc1,b'\x01'))
    reader.response(0xc2)
    sock.sendall(frame(0xdc,b'\x04'))
    return sensors(reader.response(0xd9))


def cache(state, reason, message):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary=state/'refresh.tmp'
    temporary.write_text(f'1 {time.time_ns()} {reason}\n'+ ' '.join(message.split())+'\n')
    os.replace(temporary,state/'refresh-status.txt')


def main():
    with ExitStack() as stack:
        return refresh(stack)


def refresh(stack):
    state=Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'niimbot'
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Share the supervisor lock so refresh cannot race a print or acknowledgement.
    execution=stack.enter_context((state/'supervisor.lock').open('a'))
    try:
        fcntl.flock(execution,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('A print job is active; wait until it finishes before refreshing')
    config=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'niimbot/config.json'
    settings=json.loads(config.read_text())
    address=settings['address'];channel=settings['channel']
    if not re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}',address) or type(channel) is not int or not 1<=channel<=30:
        raise ValueError('Invalid configured Bluetooth address or channel')
    locks=Path(os.environ.get('XDG_RUNTIME_DIR',str(Path.home()/'.cache')))/'niimbot-locks'
    locks.mkdir(parents=True,exist_ok=True)
    connection=stack.enter_context((locks/(address.lower().replace(':','-')+'.lock')).open('a'))
    try:
        fcntl.flock(connection,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Printer connection is busy; no refresh attempted')
    try:
        with socket.socket(socket.AF_BLUETOOTH,socket.SOCK_STREAM,socket.BTPROTO_RFCOMM) as sock:
            sock.settimeout(5);sock.connect((address,channel));observed=query(sock)
    except (OSError,ValueError) as error:
        cache(state,7 if isinstance(error,ValueError) else 4,'Status refresh failed: '+str(error));raise
    reason,message=0,'Lid closed; paper detected; roll RFID readable.'
    if not observed['lidClosed']:reason,message=1,'Printer lid is open.'
    elif not observed['paperInserted']:reason,message=2,'Paper not detected. Check the feed path.'
    elif not observed['paperRfidSuccess']:reason,message=3,'Roll RFID tag is unreadable.'
    recovery=False
    for journal in state.glob('niimbot-job-*.json'):
        try:pending=json.loads(journal.read_text()).get('state') in ('starting','transmitting','uncertain')
        except (OSError,ValueError):pending=True
        recovery |= pending
    if recovery:reason,message=6,'Sensors refreshed, but a prior print needs explicit recovery acknowledgement.'
    cache(state,reason,message)
    print(json.dumps({'observedAt':time.time(),**observed,'recoveryPending':recovery,'message':message}))

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(str(error),file=sys.stderr);sys.exit(1)
