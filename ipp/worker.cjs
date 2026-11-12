'use strict';
// Version 1 local worker interface. Raster files are 96x320, 8-bit white=255.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const base = path.join(root, 'research/niimblue-node');
const {initClient, printImages} = require(base + '/dist/utils.js');
const {ImageEncoder} = require(base + '/dist/image_encoder.js');
const sharp = require(base + '/node_modules/sharp');
const {PageColorType} = require(base + '/node_modules/@mmote/niimbluelib');
const emit = (type, data={}) => process.stdout.write(JSON.stringify({version:1,type,...data})+'\n');
console.log = (...args) => console.error(...args);
async function main() {
 const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
 if (manifest.version !== 1 || !Array.isArray(manifest.pages) || !manifest.pages.length || manifest.pages.length > 100)
  throw Error('Invalid manifest');
 const pages=[];
 for (const file of manifest.pages) {
  const bytes=fs.readFileSync(file);
  if (bytes.length !== 96*320) throw Error('Invalid raster dimensions');
  pages.push({encoded:await ImageEncoder.encodeImage(sharp(bytes,{raw:{width:96,height:320,channels:1}}),PageColorType.SingleColor,'top'),quantity:1});
 }
 if (process.env.NIIMBOT_FAKE === '1') {
  const scenario=process.env.NIIMBOT_FAKE_SCENARIO_FILE ? fs.readFileSync(process.env.NIIMBOT_FAKE_SCENARIO_FILE,'utf8').trim() : process.env.NIIMBOT_FAKE_SCENARIO || 'success';
  emit('connected',{simulated:true});
  if(scenario==='offline') throw Object.assign(Error('Simulated connection failure'),{category:'offline'});
  emit('transmitting',{simulated:true});
  if(scenario==='cover') throw Object.assign(Error('CoverOpen'),{reasonId:1});
  if(scenario==='rfid') throw Object.assign(Error('WriteRfidFail'),{reasonId:20});
  if(scenario==='unknown') throw Object.assign(Error('Unmapped printer error 8'),{reasonId:8});
  if(scenario==='partial-link') {emit('progress',{confirmedPages:1}); await new Promise(r=>setTimeout(r,500)); throw Object.assign(Error('Simulated link loss'),{category:'link'});}
  if(scenario==='stall') await new Promise(()=>setInterval(()=>{},1000));
  if(scenario==='link-loss') { emit('progress',{confirmedPages:0}); throw Error('Simulated link loss'); }
  pages.forEach((_,i)=>emit('progress',{confirmedPages:i+1}));
  if(scenario!=='missing-completion') emit('completed',{confirmedPages:pages.length,simulated:true});
  return;
 }
 const client=initClient('serial',process.argv[3],false);
 try {
  await client.connect();
  const info=client.getPrinterInfo();
  if(info.modelId!==2320 || info.printheadWidth!==96 || client.getPrintTaskType()!=='D110M_V4')
   throw Error('Printer profile mismatch');
  emit('connected');
  client.on('heartbeat', e => {
    const h=client.getHeartbeatData();
    emit('status',{lidClosed:h.lidClosed,paperInserted:h.paperInserted,paperRfidSuccess:h.paperRfidSuccess});
  });
  client.on('printprogress', e=>emit('progress',{confirmedPages:e.page}));
  emit('transmitting');
  await printImages(client,'D110M_V4',pages,{density:3,labelType:1});
  emit('completed',{confirmedPages:pages.length});
 } finally {if(client.isConnected()) await client.disconnect();}
}
main().catch(error=>{emit('error',{message:error.message,reasonId:error.reasonId,category:error.category});process.exitCode=1;});
