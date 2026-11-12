const {test}=require('node:test');const assert=require('node:assert/strict');
const lib=require('../research/niimblue-node/node_modules/@mmote/niimbluelib');
class Feed extends lib.NiimbotAbstractClient { feed(b){this.processRawPacket(b);} }
const frames=['5555c20103c0aaaa','55554802091053aaaa','5555b5103030232800c80000000a00030112ee0092aaaa'];
test('installed library reassembles fragmented and coalesced printer responses',()=>{
 const client=new Feed(),got=[];client.on('packetreceived',e=>got.push(Buffer.from(e.packet.toBytes()).toString('hex')));
 const all=Buffer.from(frames.join(''),'hex');
 for(let i=0;i<all.length;i+=3)client.feed(all.subarray(i,i+3));
 assert.deepEqual(got,frames);
 const other=new Feed(),combined=[];other.on('packetreceived',e=>combined.push(e.packet.command));other.feed(all);
 assert.deepEqual(combined,[0xc2,0x48,0xb5]);
});
test('installed library rejects corrupted response checksum',()=>{
 const raw=Buffer.from(frames[1],'hex');raw[raw.length-3]^=1;
 assert.throws(()=>lib.PacketParser.parsePacketBundle(raw));
});
