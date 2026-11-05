import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import path from 'node:path';
const config=JSON.parse(readFileSync(0,'utf8'));
const require=createRequire(path.join(process.env.ARCHHUB_NODE_MODULES,'playwright/package.json'));
const {chromium}=require('playwright');
const browser=await chromium.launch({headless:true,channel:'chromium'});
try {
 const page=await browser.newPage();
 await page.route('**/*',route=>new URL(route.request().url()).origin===new URL(config.url).origin?route.continue():route.abort());
 await page.goto(config.url);
 await page.waitForFunction(()=>window.ArchHubAPI);
 await page.evaluate(()=>window.ArchHubAPI.ready);
 await page.evaluate(file=>window.ArchHubAPI.openSession(file),config.path);
 assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().wires.map(w=>w.id)),['w00','w01']);
 for(let i=0;i<2;i++){
  await page.evaluate(async i=>{
   const api=window.ArchHubAPI;
   await api.deleteWire('w0'+i);
   await api.connectSockets({from:'file'+i,fromPort:'value',to:'read'+i,toPort:'path'});
  },i);
 }
 assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().wires.length),2);
 const saved=await page.evaluate(()=>window.ArchHubAPI.saveSession());
 await page.evaluate(file=>window.ArchHubAPI.openSession(file),saved.path);
 assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().wires.length),2);
 console.log('FILE->PATH compiled Studio: saved links reopened; both rewired and saved/reopened');
} finally {await browser.close();}
