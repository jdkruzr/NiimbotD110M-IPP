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
  emit('connected',{simulated:true});
  pages.forEach((_,i)=>emit('progress',{confirmedPages:i+1}));
  emit('completed',{confirmedPages:pages.length,simulated:true});return;
 }
 const client=initClient('serial',process.argv[3],false);
 try {
  await client.connect();
  const info=client.getPrinterInfo();
  if(info.modelId!==2320 || info.printheadWidth!==96 || client.getPrintTaskType()!=='D110M_V4')
   throw Error('Printer profile mismatch');
  emit('connected');
  client.on('printprogress', e=>emit('progress',{confirmedPages:e.page}));
  emit('transmitting');
  await printImages(client,'D110M_V4',pages,{density:3,labelType:1});
  emit('completed',{confirmedPages:pages.length});
 } finally {if(client.isConnected()) await client.disconnect();}
}
main().catch(error=>{emit('error',{message:error.message});process.exitCode=1;});
