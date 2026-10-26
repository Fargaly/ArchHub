const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'../..'), studio=path.join(root,'01.APP/nodelang/studio');
const baseline=process.env.FIXCANVAS_BASELINE==='1';
const read=name=>baseline ? execFileSync('git',['show','4d8dd06b:01.APP/nodelang/studio/'+name],{cwd:root,encoding:'utf8',maxBuffer:5*1024*1024}) : fs.readFileSync(path.join(studio,name),'utf8');
const script=name=>name.endsWith('.jsx') ? baseline ? require('esbuild').transformSync(read(name),{loader:'jsx'}).code : fs.readFileSync(path.join(studio,'compiled',name.replaceAll('/','-').replace('.jsx','.js')),'utf8') : read(name);
test('30 shell tab returns preserve the actual Canvas, viewport, selection and draft without graph requests',async t=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1496,height:960}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<div id="root" style="height:100vh;display:grid"></div>'}));
  await page.goto('http://fixcanvas.test');
  await page.addStyleTag({content:read('style.css')+'html,body{margin:0;height:100%}'});
  for(const name of ['vendor/react.js','vendor/react-dom.js','tokens.jsx','ds/index.jsx','icons.jsx'])await page.addScriptTag({content:script(name)});
  await page.evaluate(()=>{
    window.calls=[];
    const prop={label:'value',value:'initial',editable:true,editor:'text',relation:'value'};
    let raw={ok:true,application_root:'app',canvas_root:'top',revision:4,scope:{current:'nested',current_label:'Fixture'},
      viewport:{zoom:1},authorization:{subject:'owner',session:'view'},nodes:Array.from({length:50},(_,i)=>({id:'n'+i,label:'Node '+i,kind:'Input',category:'Input',x:80+i%10*300,y:80+Math.floor(i/10)*220,properties:[{...prop,relation:'value'+i}],ports:[]})),wires:[],catalog:[]};
    window.fetch=async(url,init={})=>{
      const call={url,time:window.performance.now(),body:init.body?JSON.parse(init.body):null};window.calls.push(call);
      if(url==='/api/universal/set-property')return new Promise(resolve=>{window.releaseDraft=()=>{raw={...raw,revision:raw.revision+1,nodes:raw.nodes.map(n=>({...n,properties:n.properties.map(p=>p.relation===call.body.relation?{...p,value:call.body.value}:p)}))};resolve({ok:true,status:200,json:async()=>raw});};});
      let data={ok:true,result:[],providers:[],agents:[],items:[],workspaces:[],templates:[]};
      if(url==='/api/universal/session')data={token:'fixture',csrf:'fixture'};
      else if(url==='/api/universal/canvas'||url.startsWith('/api/universal/canvas?'))data=url.includes('screen=home')?{...raw,nodes:[],canvas_deferred:true}:url.includes('since_revision')?{ok:true,unchanged:true,revision:raw.revision,scope:'nested',graph_id:'app'}:raw;
      else if(url==='/api/universal/gesture'){raw={...raw,revision:raw.revision+1,viewport:{...raw.viewport,...call.body.viewport}};data=raw;}
      else if(url.startsWith('/api/universal/graphs'))data={ok:true,graphs:[{id:'nested',title:'Fixture'}],current_graph:'nested'};
      else if(url==='/api/universal/graph-open'){if(window.holdGraph){window.graphOpenWaiting=true;await new Promise(resolve=>{window.releaseGraph=resolve;});}raw={...raw,revision:raw.revision+1,scope:{...raw.scope,current:call.body.root}};data={ok:true,canvas:raw};}
      call.bytes=JSON.stringify(data).length;call.finished=window.performance.now();return {ok:true,status:200,json:async()=>data};
    };
  });
  for(const name of ['studio-authority.js','api.js'])await page.addScriptTag({content:script(name)});
  await page.evaluate(async()=>{await window.ArchHubAPI.ready;});
  await page.addScriptTag({content:script('ui.jsx')});
  await page.evaluate(()=>{Object.assign(window.UI,{Home:()=>null,Workshop:()=>null,Settings:()=>null,Composer:()=>null,AccountIdentity:()=>null,BaboomSprite:()=>null,GraphProperties:()=>null,NodeRunPolicy:()=>null,MixedProperties:()=>null,CapabilityRows:()=>null});});
  for(const name of ['ds_library.jsx','ds_screens.jsx','context-menus.jsx','app.jsx'])await page.addScriptTag({content:script(name)});
  await page.getByRole('button',{name:'Canvas',exact:true}).click();
  await page.locator('.node-canvas').waitFor();
  await page.waitForTimeout(200);
  await page.evaluate(()=>{
    window.heldCanvas=document.querySelector('.node-canvas');
    window.loadingFrames=0;window.returnTimes=[];
    const frame=()=>{if([...document.querySelectorAll('[data-screen="canvas"]')].some(n=>n.getBoundingClientRect().width&&/Loading your graph|Opening your graph/.test(n.textContent)))window.loadingFrames++;window.frameId=requestAnimationFrame(frame);};window.frameId=requestAnimationFrame(frame);
  });
  await page.locator('[data-graph-node="n0"] .node-header').click();
  const canvas=page.locator('.node-canvas');await canvas.press('+');
  await page.locator('[data-graph-node="n0"] input').fill('unconfirmed draft');
  const before=await page.locator('.node-canvas > div[style*="scale"]').getAttribute('style');
  await page.getByRole('button',{name:'Home',exact:true}).click();
  await page.evaluate(()=>{window.calls=[];});
  await page.getByRole('button',{name:'Canvas',exact:true}).click();
  for(let i=0;i<29;i++){
    await page.getByRole('button',{name:i%2?'Home':'Workshop',exact:true}).click();
    await page.evaluate(async()=>{const started=window.performance.now();[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='Canvas').click();await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));window.returnTimes.push(window.performance.now()-started);});
  }
  const result=await page.evaluate(()=>({same:window.heldCanvas===document.querySelector('.node-canvas'),loadingFrames:window.loadingFrames,
    graphCalls:window.calls.filter(c=>(/\/canvas(?:\?|$)|\/graph-open/.test(c.url))&&!c.url.includes('since_revision')),
    freshnessCalls:window.calls.filter(c=>c.url.includes('since_revision')),calls:window.calls,returns:window.returnTimes,
    selected:document.querySelector('[data-graph-node="n0"] [data-ds-node]')?.style.outline,
    draft:document.querySelector('[data-graph-node="n0"] input')?.value,nodes:document.querySelectorAll('[data-graph-node]').length}));
  const after=await page.locator('.node-canvas > div[style*="scale"]').getAttribute('style');
  if(process.env.FIXCANVAS_EVIDENCE){await page.screenshot({path:path.join(process.env.FIXCANVAS_EVIDENCE,baseline?'BEFORE.png':'AFTER.png')});fs.writeFileSync(path.join(process.env.FIXCANVAS_EVIDENCE,baseline?'RED-RENDERED.json':'GREEN-RENDERED.json'),JSON.stringify({...result,before,after,errors},null,2));}
  assert.deepEqual(errors,[]);assert.equal(result.same,true,JSON.stringify(result));assert.equal(result.loadingFrames,0);
  assert.equal(result.graphCalls.length,0,JSON.stringify(result.graphCalls));assert.equal(after,before);assert.equal(result.nodes,50);
  assert.equal(result.draft,'unconfirmed draft');assert.match(result.selected,/2px/);
  assert.ok(result.freshnessCalls.every(c=>c.bytes<=1024));
  await page.evaluate(()=>window.releaseDraft());
  await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes[0].params.value==='unconfirmed draft');
  await page.evaluate(()=>{window.holdGraph=true;window.switching=window.ArchHubAPI.selectGraph('other');});
  await page.waitForFunction(()=>window.graphOpenWaiting);
  assert.equal(await page.locator('.node-canvas').evaluate(el=>!!el.closest('[inert]')),true,'old document is inert while another graph opens');
  await page.evaluate(async()=>{window.releaseGraph();await window.switching;});
  assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graphOpening),false);

});
