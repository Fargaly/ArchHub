const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const xyflow = require('./studio_xyflow.cjs'); // CANVASXY: the canvas runs on the bundled xyflow
const root = path.resolve(__dirname,'../..'), studio=path.join(root,'01.APP/nodelang/studio');
const commandRegistry = JSON.parse(fs.readFileSync(path.join(root, '.cache/testiso-commandregistry/commands.json'), 'utf8'));
const baseline=process.env.FIXCANVAS_BASELINE==='1';
const read=name=>baseline ? execFileSync('git',['show','4d8dd06b:01.APP/nodelang/studio/'+name],{cwd:root,encoding:'utf8',maxBuffer:5*1024*1024}) : fs.readFileSync(path.join(studio,name),'utf8');
const script=name=>name.endsWith('.jsx') ? baseline ? require('esbuild').transformSync(read(name),{loader:'jsx'}).code : fs.readFileSync(path.join(studio,'compiled',name.replaceAll('/','-').replace('.jsx','.js')),'utf8') : read(name);
test('30 shell tab returns preserve the actual Canvas, viewport, selection and draft without graph requests',async t=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1496,height:960}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<div id="root" style="height:100vh;display:grid"></div>'}));
  // api.js reads crypto.randomUUID at load (d2535174); the app always runs in a secure context, so the fixture page does too.
  await page.goto('https://fixcanvas.test');
  await page.addStyleTag({content:xyflow.css()+read('style.css')+'html,body{margin:0;height:100%}'});
  for(const name of ['vendor/react.js','vendor/react-dom.js','xyflow','tokens.jsx','ds/index.jsx','icons.jsx'])await page.addScriptTag({content:name==='xyflow'?xyflow.script():script(name)});
  await page.addScriptTag({path:path.join(studio,'compiled/react-resizable-panels.js')});
  // D-014 NOGRAPH: the Canvas is the open session file (owner session_files); a parameter edit is the owner's param-op.
  await page.evaluate(commands=>{
    window.calls=[];
    const file=(id,title,count)=>({format:'archhub',version:1,id,title,viewport:{x:0,y:0,zoom:1},groups:[],notes:[],wires:[],properties:{revision:4},
      nodes:Array.from({length:count},(_,i)=>({id:'n'+i,type:'param.text',title:'Node '+i,params:{value:'initial'},paramDefs:[{id:'value',name:'value',type:'text'}],ports:{source:[],target:[]},position:{x:80+i%10*300,y:80+Math.floor(i/10)*220}}))});
    let revision=4;
    window.fetch=async(url,init={})=>{
      const call={url,time:window.performance.now(),body:init.body?JSON.parse(init.body):null};window.calls.push(call);
      const action=url==='/api/session-files'?call.body.action:null;
      if(action==='param-op')return new Promise(resolve=>{window.releaseDraft=()=>{const [id,key,value]=call.body.args,document=window.structuredClone(call.body.document);document.nodes.find(n=>n.id===id).params[key]=value;resolve({ok:true,status:200,json:async()=>({ok:true,document,changed:[id]})});};});
      let data={ok:true,result:[],providers:[],agents:[],items:[],workspaces:[],templates:[]};
      if(url==='/api/commands')data=commands;
      // Desktop work needs a verified ArchHub account (cd19d5d4); this fixture is signed in.
      else if(url==='/api/universal/desktop-access')data={ok:true,admitted:true,state:'admitted',subject:'fixcanvas-fixture'};
      else if(url==='/api/universal/session')data={token:'fixture',csrf:'fixture'};
      else if(action==='initial')data={ok:true,document:file('nested','Fixture',50),path:'C:/isolated/fixture.archhub'};
      else if(action==='catalogue')data={ok:true,items:[],sessions:[],directory:'mem'};
      else if(action==='validate')data={ok:true,document:call.body.document};
      else if(action==='solve')data={ok:true,results:{},solved:[],stale:[],ms:0};
      else if(action==='head')data={ok:true,revision};
      else if(action==='autosave'){revision++;data={ok:true,path:call.body.path,revision,document:{...call.body.document,properties:{...call.body.document.properties,revision}}};}
      else if(action==='open'){if(window.holdGraph){window.graphOpenWaiting=true;await new Promise(resolve=>{window.releaseGraph=resolve;});}data={ok:true,document:file('other','Other',1),path:call.body.path};}
      call.bytes=JSON.stringify(data).length;call.finished=window.performance.now();return {ok:true,status:200,json:async()=>data};
    };
  },commandRegistry);
  for(const name of ['studio-authority.js','api.js'])await page.addScriptTag({content:script(name)});
  await page.evaluate(async()=>{await window.ArchHubAPI.ready;});
  await page.addScriptTag({content:script('ui.jsx')});
  await page.addScriptTag({content:script('answer-widgets.jsx')});
  // The shell header reads Home's row counts (UI.homeRows); the Home screen itself stays a stub below.
  await page.addScriptTag({content:script('ds_home2.jsx')});
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
  const before=await page.locator('.node-canvas .react-flow__viewport').getAttribute('style');
  await page.getByRole('button',{name:'Home',exact:true}).click();
  await page.evaluate(()=>{window.calls=[];});
  await page.getByRole('button',{name:'Canvas',exact:true}).click();
  for(let i=0;i<29;i++){
    // The shell rail is Home and Canvas; the Workshop is a dock panel (founder design), so the other screen left for is Settings.
    await page.getByRole('button',{name:i%2?'Home':'Settings',exact:true}).click();
    await page.evaluate(async()=>{const started=window.performance.now();[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='Canvas').click();await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));window.returnTimes.push(window.performance.now()-started);});
  }
  const result=await page.evaluate(()=>({same:window.heldCanvas===document.querySelector('.node-canvas'),loadingFrames:window.loadingFrames,
    graphCalls:window.calls.filter(c=>c.url==='/api/session-files'&&['initial','open','read'].includes(c.body.action)),
    freshnessCalls:window.calls.filter(c=>c.url==='/api/session-files'&&c.body.action==='head'),calls:window.calls,returns:window.returnTimes,
    selected:document.querySelector('[data-graph-node="n0"] [data-ds-node]')?.style.outline,
    draft:document.querySelector('[data-graph-node="n0"] input')?.value,nodes:document.querySelectorAll('[data-graph-node]').length}));
  const after=await page.locator('.node-canvas .react-flow__viewport').getAttribute('style');
  if(process.env.FIXCANVAS_EVIDENCE){await page.screenshot({path:path.join(process.env.FIXCANVAS_EVIDENCE,baseline?'BEFORE.png':'AFTER.png')});fs.writeFileSync(path.join(process.env.FIXCANVAS_EVIDENCE,baseline?'RED-RENDERED.json':'GREEN-RENDERED.json'),JSON.stringify({...result,before,after,errors},null,2));}
  assert.deepEqual(errors,[]);assert.equal(result.same,true,JSON.stringify(result));assert.equal(result.loadingFrames,0);
  assert.equal(result.graphCalls.length,0,JSON.stringify(result.graphCalls));assert.equal(after,before);assert.equal(result.nodes,50);
  assert.equal(result.draft,'unconfirmed draft');assert.match(result.selected,/2px/);
  assert.ok(result.freshnessCalls.every(c=>c.bytes<=1024));
  await page.evaluate(()=>window.releaseDraft());
  await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes[0].params.value==='unconfirmed draft');
  await page.evaluate(()=>{window.holdGraph=true;window.switching=window.ArchHubAPI.selectGraph('C:/isolated/other.archhub');});
  await page.waitForFunction(()=>window.graphOpenWaiting);
  assert.equal(await page.locator('.node-canvas').evaluate(el=>!!el.closest('[inert]')),true,'old document is inert while another graph opens');
  await page.evaluate(async()=>{window.releaseGraph();await window.switching;});
  assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graphOpening),false);

});
