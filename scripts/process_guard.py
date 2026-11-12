#!/usr/bin/env python3
"""Linux child lifetime guard: parent death closes transport even after SIGKILL."""
import ctypes
import os
import signal
import sys

parent = int(sys.argv[1])
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
    sys.exit(125)
os.execvp(sys.argv[2], sys.argv[2:])
