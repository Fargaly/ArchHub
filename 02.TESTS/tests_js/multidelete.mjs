import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import path from 'node:path';
const config = JSON.parse(readFileSync(0, 'utf8'));
const require = createRequire(path.join(process.env.ARCHHUB_NODE_MODULES, 'playwright/package.json'));
const {chromium} = require('playwright');
const browser = await chromium.launch({headless:true, channel:'chromium'});
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
  await page.getByRole('button', {name:/Multi-delete test/}).click();
  await page.getByRole('button', {name:'Open workflow',exact:true}).click();
  await page.locator('[data-graph-node="list"]').waitFor();
  const before = await page.evaluate(() => {
    const d = window.ArchHubAPI.getSessionDocument();
    return {nodes:d.nodes.map(({result,...n})=>n),wires:d.wires,groups:d.groups};
  });
  const canvas = page.getByLabel('Workflow canvas', {exact:true});
  await canvas.focus();
  await key('a',65,2);
  await key('Delete',46);
  await page.getByRole('button',{name:'Confirm',exact:true}).click();
  await page.waitForFunction(() => window.ArchHubAPI.getSessionDocument().nodes.length === 0);
  await key('z',90,2);
  await page.waitForFunction(() => window.ArchHubAPI.getSessionDocument().nodes.length > 0);
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
  console.log('MULTI-DELETE rendered: Delete removed all; one Undo restored identical ids/endpoints/types/params; Redo removed all');
} finally { await browser.close(); }
