#!/usr/bin/env python3
"""Decode this session's SPP channel from Android btsnoop H4 records."""
import json,struct,sys
from pathlib import Path
b=Path(sys.argv[1]).read_bytes();assert b[:8]==b'btsnoop\0'
assert struct.unpack_from('>II',b,8)==(1,1002)
p=16;acl={};streams={0:bytearray(),1:bytearray()};frames=[]
while p+24<=len(b):
 _,size,flags,_,stamp=struct.unpack_from('>IIIIQ',b,p);p+=24;d=b[p:p+size];p+=size
 if len(d)<5 or d[0]!=2:continue
 handle,n=struct.unpack_from('<HH',d,1);key=(flags&1,handle&4095);pb=(handle>>12)&3
 if pb in (0,2):acl[key]=bytearray(d[5:])
 elif key in acl:acl[key].extend(d[5:])
 else:continue
 a=acl[key]
 if len(a)<4:continue
 length,cid=struct.unpack_from('<HH',a)
 if len(a)<4+length:continue
 del acl[key]
 if cid not in (0x51,0x41):continue
 r=a[4:4+length]
 if len(r)<4 or (r[1]&0xef)!=0xef or r[0]>>2!=2:continue
 length=r[2]>>1;off=3
 if not r[2]&1:length|=r[3]<<7;off+=1
 if r[1]&0x10:off+=1
 assert off+length<=len(r)
 stream=streams[flags&1];stream.extend(r[off:off+length])
 while len(stream)>=7:
  idx=stream.find(b'\x55\x55')
  if idx<0:del stream[:-1];break
  if idx:del stream[:idx]
  if len(stream)<4:break
  n=stream[3]+7
  if len(stream)<n:break
  f=bytes(stream[:n]);check=0
  for v in f[2:-3]:check^=v
  if f[-2:]!=b'\xaa\xaa' or check!=f[-3]:del stream[0];continue
  del stream[:n];frames.append({'direction':'rx' if flags&1 else 'tx','timestamp':stamp,'command':f[2],'data':f[4:-3].hex(),'frame':f.hex()})
Path(sys.argv[2]).write_text(json.dumps(frames,indent=2)+'\n')
print('validated frames',len(frames))
for f in frames:
 if f['direction']=='tx' and f['command'] in (1,19,33,35,227,243):print(f['command'],f['data'])
