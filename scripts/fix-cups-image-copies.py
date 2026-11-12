#!/usr/bin/env python3
"""Remove PNG passthrough from a CUPS-generated raster queue PPD.

CUPS marks these queues ManualCopies but its zero-cost PNG passthrough
cannot expand copies. Let the installed image-to-raster filters do that work.
"""
import sys
from pathlib import Path


def fix(text):
    if '*cupsManualCopies: True' not in text:
        return text
    lines = text.splitlines(keepends=True)
    if not any(line.startswith('*cupsFilter2:') and ('image/urf' in line or 'image/pwg-raster' in line) for line in lines):
        raise ValueError('No driverless raster output filter; refusing to alter queue')
    passthrough = {'*cupsFilter2: "image/png image/png 0 -"'}
    return ''.join(line for line in lines if line.strip() not in passthrough)


if __name__ == '__main__':
    source, target = map(Path, sys.argv[1:])
    target.write_text(fix(source.read_text()))
