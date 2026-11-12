#!/usr/bin/env python3
"""Read candidate app mappings through rooted ADB; save only plausible DEX files.

No injection, ptrace attachment, process suspension, or target-memory writes.
This first pass requires intact standard DEX headers (versions 035 through 040).
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--pid', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--include-allocators', action='store_true')
    parser.add_argument('--recover-headers', action='store_true',
                        help='Also locate DEX structures with missing magic; preserve bytes verbatim')
    args = parser.parse_args()
    if args.pid <= 0:
        parser.error('PID must be positive')
    args.output.mkdir(parents=True, exist_ok=False)

    def read(command, timeout=30):
        return subprocess.run(['adb', '-s', args.serial, 'exec-out', 'su', '-c', command],
                              capture_output=True, check=True, timeout=timeout).stdout

    cmdline = read(f'cat /proc/{args.pid}/cmdline').split(b'\0')[0].decode()
    if cmdline != 'com.gengcon.android.jccloudprinter':
        raise RuntimeError(f'Refusing unexpected process: {cmdline}')
    maps = read(f'cat /proc/{args.pid}/maps').decode()
    (args.output / 'maps.txt').write_text(maps)
    report = {'pid': args.pid, 'process': cmdline, 'files': [], 'errors': [],
              'bytes_scanned': 0, 'ranges_skipped': []}
    candidates = []
    for line in maps.splitlines():
        parts = line.split(maxsplit=5)
        start, end = (int(x, 16) for x in parts[0].split('-'))
        name = parts[5] if len(parts) > 5 else ''
        eligible = not name or (args.include_allocators and name.startswith('[anon:scudo:'))
        if not parts[1].startswith('r') or not eligible:
            continue
        if end - start > 96 * 1024 * 1024:
            report['ranges_skipped'].append(line)
            continue
        candidates.append((start, end, name))
    # Large unnamed mappings are common locations for restored DEX containers.
    candidates.sort(key=lambda r: r[1] - r[0], reverse=True)
    seen = set()
    print(f'Scanning {len(candidates)} candidate mappings', flush=True)
    try:
        for index, (start, end, name) in enumerate(candidates):
            try:
                data = read(f'dd if=/proc/{args.pid}/mem bs=1048576 skip={start} '
                            f'count={end-start} iflag=skip_bytes,count_bytes status=none')
                report['bytes_scanned'] += len(data)
                offsets = {match.start() for match in re.finditer(rb'dex\n0(?:3[5-9]|40)\x00', data)}
                if args.recover_headers:
                    offsets.update(match.start() - 36 for match in
                                   re.finditer(b'\x70\x00\x00\x00\x78\x56\x34\x12', data)
                                   if match.start() >= 36)
                for offset in sorted(offsets):
                    if len(data) - offset < 112:
                        continue
                    size, header, endian = struct.unpack_from('<III', data, offset + 32)
                    if header != 112 or endian != 0x12345678 or not 112 <= size <= 64 * 1024 * 1024:
                        continue
                    # Validate fixed-size ID tables against the declared file extent.
                    valid = True
                    for at, stride in [(56,4),(64,4),(72,12),(80,8),(88,8),(96,32)]:
                        count, table = struct.unpack_from('<II', data, offset + at)
                        if count and (table < 112 or table + count * stride > size):
                            valid = False
                    if not valid:
                        continue
                    classes, classes_offset, data_size, data_offset = struct.unpack_from('<IIII', data, offset + 96)
                    if not classes or data_size + data_offset != size or data_offset < 112:
                        continue
                    address = start + offset
                    if offset + size <= len(data):
                        dex = data[offset:offset + size]
                    else:
                        dex = read(f'dd if=/proc/{args.pid}/mem bs=1048576 skip={address} '
                                   f'count={size} iflag=skip_bytes,count_bytes status=none')
                    if len(dex) != size:
                        continue
                    sha = hashlib.sha256(dex).hexdigest()
                    if sha in seen:
                        continue
                    seen.add(sha)
                    filename = f'{address:x}-{sha[:12]}.dex'
                    (args.output / filename).write_bytes(dex)
                    item = {'file': filename, 'address': hex(address), 'size': size,
                            'magic_hex': dex[:8].hex(),
                            'mapping_name': name, 'sha256': sha,
                            'class_defs': struct.unpack_from('<I', dex, 96)[0],
                            'sha1_matches': hashlib.sha1(dex[32:]).digest() == dex[12:32],
                            'adler32_matches': zlib.adler32(dex[12:]) == struct.unpack_from('<I', dex, 8)[0]}
                    report['files'].append(item)
                    print(json.dumps(item), flush=True)
            except (subprocess.SubprocessError, OSError) as exc:
                report['errors'].append({'address': hex(start), 'error': str(exc)})
            if index % 40 == 0:
                print(f'{index + 1}/{len(candidates)} ranges; {len(seen)} unique DEX files', flush=True)
    finally:
        (args.output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Done: {len(seen)} unique DEX files; {report["bytes_scanned"]} bytes inspected', flush=True)


if __name__ == '__main__':
    main()
