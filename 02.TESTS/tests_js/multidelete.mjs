import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import os from 'node:os';
import {readFileSync, readdirSync} from 'node:fs';
import path from 'node:path';
const config = JSON.parse(readFileSync(0, 'utf8'));
// Resolve the account cache even when pytest isolates the profile environment.
const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
const shell = readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a,b) => Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
const full = readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort((a,b) => Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
const executablePath = path.join(cache, shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe');
const browser = await chromium.launch({headless: true, executablePath});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const input=await page.context().newCDPSession(page);
  const key=async(name,code,modifiers=0)=>{
    await input.send('Input.dispatchKeyEvent',{type:'keyDown',key:name,windowsVirtualKeyCode:code,modifiers});
    await input.send('Input.dispatchKeyEvent',{type:'keyUp',key:name,windowsVirtualKeyCode:code,modifiers});
  };
  page.on('pageerror', error => console.log('Studio error:', error.message));
  await page.route('**/*', route => new URL(route.request().url()).origin === new URL(config.url).origin ? route.continue() : route.abort());
  await page.goto(config.url);
  await page.waitForFunction(() => window.ArchHubAPI);
  await page.evaluate(() => window.ArchHubAPI.ready);
  await page.locator('.dx-task').filter({hasText:'Multi-delete test'}).click();
  await page.getByRole('region',{name:'Resumed session'}).getByRole('button',{name:'Open its Canvas',exact:true}).click();
  await page.locator('[data-graph-node="list"]').waitFor();
  const before = await page.evaluate(() => {
    const d = window.ArchHubAPI.getSessionDocument();
    return {nodes:d.nodes.map(({result,...n})=>n),wires:d.wires,groups:d.groups};
  });
  let releaseDeletedSave;
  let deletedSaveSeen;
  const deletedSave = new Promise(resolve => { deletedSaveSeen=resolve; });
  await page.route('**/api/session-files',async route=>{
    const body=route.request().postDataJSON();
    if(body.action==='autosave'&&body.document.nodes.length===0&&!releaseDeletedSave){
      const response=await route.fetch();
      const resume=new Promise(resolve=>{releaseDeletedSave=resolve;});
      deletedSaveSeen();
      await resume;
      await route.fulfill({response});
    }else await route.continue();
  });
  const canvas = page.getByLabel('Workflow canvas', {exact:true});
  await canvas.focus();
  await key('a',65,2);
  await key('Delete',46);
  await page.getByRole('button',{name:'Confirm',exact:true}).click();
  await page.waitForFunction(() => window.ArchHubAPI.getSessionDocument().nodes.length === 0);
  await deletedSave;
  await key('z',90,2);
  releaseDeletedSave();
  await page.waitForFunction(() => window.ArchHubAPI.getSessionDocument().nodes.length > 0);
  await page.evaluate(()=>window.ArchHubAPI.saveSession());
  const restored = await page.evaluate(() => {
    const d=window.ArchHubAPI.getSessionDocument();
    return {nodes:d.nodes.map(({result,...n})=>n),wires:d.wires,groups:d.groups};
  });
  assert.deepEqual(restored,before,'one Undo must restore the whole selection exactly');
  await page.locator('[data-graph-node="list"]').waitFor();
  await key('z',90,10);
  await page.waitForFunction(() => window.ArchHubAPI.getSessionDocument().nodes.length === 0);
  await page.waitForFunction(() => document.querySelectorAll('[data-graph-node]').length === 0);
  assert.equal(await page.locator('[data-graph-node]').count(),0);
  await key('z',90,2);
  await page.locator('[data-graph-node="list"]').waitFor();
  await canvas.focus();
  await key('Escape',27);
  await page.evaluate(()=>new Promise(requestAnimationFrame));
  const selectWire=async(index)=>{
    await page.locator('.react-flow__edge').nth(index).focus();
    await key('Enter',13);
  };
  await selectWire(0);
  await input.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Shift',code:'ShiftLeft',windowsVirtualKeyCode:16,modifiers:8});
  await selectWire(1);
  await input.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Shift',code:'ShiftLeft',windowsVirtualKeyCode:16,modifiers:0});
  await canvas.focus();
  await key('Delete',46);
  await page.getByRole('button',{name:'Confirm',exact:true}).click();
  await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().wires.length===0);
  assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.length),3);
  await key('z',90,2);
  await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().wires.length===2);
  assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().wires),before.wires);
  await selectWire(0);
  await key('Escape',27);
  await canvas.focus();
  await page.evaluate(()=>new Promise(requestAnimationFrame));
  await key('Delete',46);
  assert.equal(await page.getByRole('button',{name:'Confirm',exact:true}).count(),0);
  assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().wires.length),2);
  console.log('MULTI-DELETE rendered wires: two selected wires removed in one step; one Undo restored endpoints; Escape cleared selection');
  console.log('MULTI-DELETE rendered: Delete removed all; one Undo restored identical ids/endpoints/types/params; Redo removed all');
} finally { await browser.close(); }
