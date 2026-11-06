import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import os from 'node:os';
import {readFileSync, readdirSync} from 'node:fs';
import path from 'node:path';
const config=JSON.parse(readFileSync(0,'utf8'));
// Resolve the account cache even when pytest isolates the profile environment.
const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
const shell = readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a,b) => Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
const full = readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort((a,b) => Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
const executablePath = path.join(cache, shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe');
const browser = await chromium.launch({headless: true, executablePath});
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
