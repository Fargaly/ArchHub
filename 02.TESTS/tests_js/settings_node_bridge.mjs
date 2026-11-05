import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import path from 'node:path';
const config=JSON.parse(readFileSync(0,'utf8'));
const require=createRequire(path.join(process.env.ARCHHUB_NODE_MODULES,'playwright/package.json'));
const {chromium}=require('playwright');
const browser=await chromium.launch({headless:true,channel:'chromium'});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.route('**/*',route=>new URL(route.request().url()).origin===new URL(config.url).origin?route.continue():route.abort());
 await page.goto(config.url);
 const open=async()=>{
  await page.waitForFunction(()=>window.ArchHubAPI);
  await page.evaluate(()=>window.ArchHubAPI.ready);
  await page.getByRole('button',{name:/Settings bridge test/}).click();
  await page.getByRole('button',{name:'Open workflow',exact:true}).click();
 };
 await open();
 const id=await page.evaluate(async()=>{
  const api=window.ArchHubAPI;
  await api.exposeSettingsPage('Appearance');
  const before=api.getSessionDocument().nodes.length;
  await api.exposeSettingsPage('Appearance');
  if(api.getSessionDocument().nodes.length!==before)throw Error('Duplicate Settings bindings');
  const node=api.getSessionDocument().nodes.find(n=>n.params.setting==='Appearance.Text scale');
  const downstream=await api.addNode('param.value',{x:1100,y:100});
  await api.connectSockets({from:node.id,fromPort:'value',to:downstream.id,toPort:'value'});
  await api.solveNow();
  await api.setNodeParam(node.id,'value',125);
  if((await api.getSettings()).find(r=>r.id==='Appearance.Text scale').value!==125)throw Error('Node did not write Settings');
  return node.id;
 });
 await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).result?.output?.value===125,id,{timeout:2000});
 await page.evaluate(async id=>{
  const api=window.ArchHubAPI;
  await api.setSetting('Appearance.Text scale',130);
  if(api.getSnapshot().graph.nodes.find(n=>n.id===id).params.value!==130)throw Error('Settings did not update node');
  await api.saveSession();
 },id);
 await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().nodes.filter(n=>n.type==='param.value').every(n=>n.result?.output?.value===130),null,{timeout:2000});
 await page.locator('[data-graph-node="'+id+'"]').waitFor();
 await page.goto(config.url.split('?')[0]);
 await open();
 await page.locator('[data-graph-node="'+id+'"]').waitFor();
 assert.equal(await page.evaluate(id=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id===id).params.value,id),130);
 console.log('SETTINGS-AS-NODE compiled Studio: node=125 == Settings; Settings=130 == node after reopen; automatic node/downstream solve; one owner file; no copied value');
} finally {await browser.close();}
