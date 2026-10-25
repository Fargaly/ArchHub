const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {mountStudio,root}=require('./studio_home3_helpers.cjs');
const fresh=()=>JSON.parse(fs.readFileSync(path.join(root,'05.EVIDENCE/tpl_fresh_templates.json'),'utf8'));

test('production template edit adapter writes through the admitted owner and fences a changed account',async()=>{
 const vm=require('node:vm'),context=vm.createContext({URLSearchParams,TextEncoder});
 vm.runInContext(fs.readFileSync(path.join(root,'01.APP/nodelang/studio/studio-existing-workshop.js'),'utf8'),context);
 const calls=[];let resolve;
 const api=context.ArchHubExistingWorkshop.create({get:async()=>({}),post:async(url,body)=>{
  calls.push({url,body});return await new Promise(done=>resolve=done);
 }});
 const canvas={graph_id:'graph-a',root:'scope-a',revision:1,authorization:{subject:'owner-a',session:'view-a'},workshops:[]};
 api.setCanvas(canvas);
 const saving=api.editHomeTemplate('tpl-sheet-register',{delete:true});
 assert.equal(calls[0].url,'/api/universal/node-create');
 assert.deepEqual(JSON.parse(JSON.stringify(calls[0].body)),{template:'tpl-sheet-register',delete:true});
 resolve({ok:true,template:'tpl-sheet-register',revision:2});await saving;
 const stale=api.editHomeTemplate('tpl-sheet-register',{delete:true});
 api.setCanvas({...canvas,authorization:{subject:'owner-b',session:'view-b'}});
 resolve({ok:true,template:'tpl-sheet-register',revision:3});await assert.rejects(stale,/workspace changed/);
});

const plate082=path.join(root,'design/ARCHHUB-CLD-DES-DSYS-082-2026-10-13_5.6b_home2.png');
test('fresh Home render beside the 082 plate',{skip:!fs.existsSync(plate082) && 'the 082 plate image lives in the design handoff, not in the repo'},async()=>{
 const ui=await mountStudio({templates:fresh(),hosts:[],snapshot:{nativeWork:null}});
 let browser;
 try{
  await ui.settle();await ui.settle();
  const {chromium}=require('playwright');
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1496,height:959},deviceScaleFactor:1});
  // Let the production AppBoot finish before freezing the mounted DOM.
  await new Promise(resolve=>ui.win.setTimeout(resolve,2150));
  const home=ui.doc.querySelector('[data-home-page]');assert.ok(home);
  assert.equal(home.querySelectorAll('[data-home-template]').length,fresh().length);
  assert.doesNotMatch(ui.doc.body.textContent,/Opening workspace/);
  await page.setContent(ui.doc.documentElement.outerHTML);
  await page.addStyleTag({content:'html,body,#root{margin:0;width:100%;height:100%;overflow:hidden}*{box-sizing:border-box}button,input,textarea{font:inherit}'});
  await page.locator('[data-home-templates]').waitFor({state:'visible'});
  assert.equal(await page.locator('[data-home-template]').count(),fresh().length);
  assert.equal(await page.locator('[data-home-template]').first().isVisible(),true);
  assert.doesNotMatch(await page.locator('body').innerText(),/Opening workspace/);
  await page.screenshot({path:path.join(root,'05.EVIDENCE/tpl_home_fresh.png')});
  const data=file=>'data:image/png;base64,'+fs.readFileSync(path.join(root,file)).toString('base64');
  await page.setViewportSize({width:1800,height:620});
  await page.setContent(`<body style="margin:0;background:#0c0c0f;color:#ddd;font:16px sans-serif"><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><section><p>TPL · fresh profile · real counts start at zero</p><img style="width:100%" src="${data('05.EVIDENCE/tpl_home_fresh.png')}"></section><section><p>082 design plate · layout reference (sample activity)</p><img style="width:100%" src="${data('design/ARCHHUB-CLD-DES-DSYS-082-2026-10-13_5.6b_home2.png')}"></section></div>`);
  await page.screenshot({path:path.join(root,'05.EVIDENCE/tpl_home_comparison.png')});
  assert.equal(await page.locator('img').count(),2);
 }finally{if(browser)await browser.close();ui.close();}
});
