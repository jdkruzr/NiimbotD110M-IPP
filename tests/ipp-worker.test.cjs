const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawnSync}=require('node:child_process');
for(const valid of [true,false])test(valid?'IPP worker completes validated fake raster':'IPP worker rejects malformed raster before connecting',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'niimbot-test-'));
 try{
  const raster=path.join(dir,'page.raw');fs.writeFileSync(raster,Buffer.alloc(valid?30720:5,255));
  const manifest=path.join(dir,'job.json');fs.writeFileSync(manifest,JSON.stringify({version:1,pages:[raster]}));
  const result=spawnSync('node',['ipp/worker.cjs',manifest],{encoding:'utf8',env:{...process.env,NIIMBOT_FAKE:'1'}});
  const events=result.stdout.trim().split('\n').map(JSON.parse);
  assert.equal(result.status,valid?0:1);
  assert.equal(events.at(-1).type,valid?'completed':'error');
  if(valid)assert.equal(events.at(-1).confirmedPages,1);
  else assert.equal(events.length,1);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
