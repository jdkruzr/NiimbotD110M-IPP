const {test}=require('node:test');
const assert=require('node:assert/strict');
const {runBoundedJob,pollPages}=require('../research/niimblue-node/dist/job-control.js');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
test('waits for page count despite 100 percent progress, with no overlapping polls',async()=>{
 let polls=0,inFlight=0,max=0;
 await runBoundedJob(500,signal=>pollPages(signal,1,async()=>{
  max=Math.max(max,++inFlight);await pause(4);inFlight--;
  return {page:++polls===3?1:0,pagePrintProgress:100,pageFeedProgress:100};
 },1),async()=>assert.fail('unexpected disconnect'));
 assert.equal(polls,3);assert.equal(max,1);
});
test('responsive but stalled printer hits deadline and disconnects once',async()=>{
 let disconnects=0;
 await assert.rejects(runBoundedJob(20,s=>pollPages(s,1,async()=>({page:0}),1),async()=>{disconnects++;}),/UNKNOWN/);
 await pause(5);assert.equal(disconnects,1);
});
test('rejects a concurrent job',async()=>{
 const job=runBoundedJob(500,async()=>{await pause(15);},async()=>{});
 await assert.rejects(runBoundedJob(500,async()=>{},async()=>{}),/already active/);
 await job;
});
test('transport failure propagates with cleanup',async()=>{
 await assert.rejects(runBoundedJob(500,s=>pollPages(s,1,async()=>{throw new Error('link lost')}),async()=>{}),/link lost/);
});
test('cancellation stops further polling and closes connection',async()=>{
 let count=0,closed=false;
 const job=runBoundedJob(500,s=>pollPages(s,1,async()=>{count++;return {page:0}},5),async()=>{closed=true});
 await pause(10);process.emit('SIGINT');await assert.rejects(job,/cancelled/);
 const last=count;await pause(15);assert.equal(count,last);assert.ok(closed);
});
