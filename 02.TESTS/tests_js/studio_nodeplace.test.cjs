'use strict';
const {setImmediate}=require('node:timers');
const xyflow=require('./studio_xyflow.cjs'); // CANVASXY: the canvas runs on the bundled xyflow
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
async function adapter(account, responses={}){
 const requests=[],events=new Map();
 const window={ARCHHUB_AUTHORITY:{},structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{home_load_ms:60000,token:'local-lease',csrf:'csrf'},
  Uint8Array:globalThis.Uint8Array,dispatchEvent(e){events.get(e.type)?.(e);},addEventListener(name,fn){events.set(name,fn);},AH:{inkSoft:'#888'},crypto:require('node:crypto')};
 window.ArchHubStudioAuthority={create:({get,post:send})=>{let held;const post=async(...args)=>{const result=await send(...args);held=Array.isArray(result.nodes)?result:await get('/api/universal/canvas');return result;};return ({getSnapshot:()=>({canvas:held}),clear:()=>{held=null;},adopt:async result=>held=result,transact:async action=>held=await action(),load:async()=>held=await get('/api/universal/canvas'),create:spec=>post('/fixture/create',spec),remove:id=>post('/fixture/remove',{id}),move:(id,point)=>post('/fixture/move',{id,point})})}};
 const context={window,setTimeout,clearTimeout,document:{hidden:true,addEventListener(){}},
  CustomEvent:class {constructor(type,options){this.type=type;this.detail=options?.detail;}},sessionStorage:{getItem(){return null;}},URLSearchParams,TextEncoder:globalThis.TextEncoder,AbortSignal:globalThis.AbortSignal,console,
  fetch:async(url,options)=>{
   requests.push({url,body:options.body&&JSON.parse(options.body)});
   let data={ok:true};
   if(url==='/api/universal/canvas')data={root:'canvas',nodes:[],wires:[],
    authorization:{principal:'local-process',display_name:'Local transport'}};
   if(url==='/api/universal/cloud-session')data={...account};
   if(Object.hasOwn(responses,url))data=await (typeof responses[url]==='function'?responses[url](options.body&&JSON.parse(options.body)):responses[url]);
   if(url==='/api/universal/cloud-signin'&&options.body)Object.assign(account,
    {signed_in:true,email:'user@example.test',user_id:'account-1',display_name:'Account user'});
   if(url==='/api/universal/cloud-signout')Object.assign(account,{signed_in:false,email:''});
   return {ok:true,status:200,json:async()=>data};
  }};
 const source=process.env.NODEPLACE_BASELINE==='1'?require('node:child_process').execFileSync('git',['show','origin/main:01.APP/nodelang/studio/api.js'],{cwd:path.resolve(__dirname,'../..'),encoding:'utf8'}):fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/api.js'),'utf8');
 vm.runInNewContext(source,context);
 await window.ArchHubAPI.ready;
 return {api:window.ArchHubAPI,requests,window,document:context.document};
}

test('NODEPLACE wide graph inserts in visible viewport, not past the last node',async()=>{
 const canvas={root:'g',nodes:[{id:'far',label:'Far',x:12000,y:200,properties:[],ports:[]}],wires:[],catalog:[{id:'def',name:'Number',descriptor:{engine:'data.constant'}}]};
 const {api,requests,window}=await adapter({signed_in:false},{'/api/universal/canvas':canvas});
 window.addEventListener('archhub:canvas-insertion',e=>{e.detail.point={x:400,y:300,w:224,h:160};});
 await api.addNode('def');
 const point=requests.find(r=>r.url==='/api/universal/node-create').body;
 assert.ok(point.x>=0&&point.x+224<=1024&&point.y>=0&&point.y+160<=768,JSON.stringify(point)+' is outside viewport');
});

const {transformSync}=require('esbuild'),{chromium}=require('playwright');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const readCanvas=name=>fs.readFileSync(path.join(studio,name),'utf8');
const node = (id, i, parent = null) => ({id, title:['Level','Doors of level','Untagged only','Tag doors'][i % 4], kind:['Input','Host','Filter','Document'][i % 4],
  x:0, y:0, parent, children:[], status:i % 4 === 3 ? 'Waiting for approval' : 'Done', params:{Level:'L3'}, defaults:{},
  inputs:[{id:'in',name:'level',type:'text'}],outputs:[{id:'out',name:'doors',type:'elements',list:true}]});
const fixture = () => {
  const nodes = Array.from({length:12},(_,i)=>node('n'+i,i,'g'+Math.floor(i/4)));
  const groups = Array.from({length:3},(_,i)=>({id:'g'+i,title:['Revit','CAD Lines','Studio'][i],kind:'Group',x:0,y:0,status:'Idle',params:{},defaults:{},inputs:[],outputs:[],children:nodes.filter(n=>n.parent==='g'+i).map(n=>n.id)}));
  return {id:'fixture',name:'Canvas look fixture',nodes:[...groups,...nodes],wires:nodes.filter((_,i)=>i%4!==3).map((n,i)=>({id:'w'+i,from:n.id,to:'n'+(Number(n.id.slice(1))+1),fromPort:'out',toPort:'in',type:'elements'}))};
};
const overlaps = (a,b) => a.x < b.x+b.width && b.x < a.x+a.width && a.y < b.y+b.height && b.y < a.y+a.height;

async function mount(t, graph = fixture()) {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  t.after(()=>browser.close());
  const page = await browser.newPage({viewport:{width:1496,height:960}}), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>r.fulfill({contentType:'text/html',body:'<div id="root" style="display:grid;height:100vh"></div>'}));
  await page.goto('http://canvaslook.test/');
  await page.addStyleTag({content:xyflow.css()+readCanvas('style.css')+'html,body{margin:0;height:100%}'});
  for(const name of ['vendor/react.js','vendor/react-dom.js','xyflow','tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx'])
    await page.addScriptTag({content:name.endsWith('.jsx')?transformSync(readCanvas(name),{loader:'jsx'}).code:name==='xyflow'?xyflow.script():readCanvas(name)});
  await page.evaluate(graph=>{
    const R=window.React,h=R.createElement;
    let state={revision:1,graph,settings:[],workspaces:[],catalogue:[{id:'level',name:'Level',description:'A level value',family:'Get',output:'text',descriptor:{engine:'Input'}},
      {id:'host',name:'Doors of level',description:'Read doors from Revit',family:'Host',output:'elements',descriptor:{engine:'Host'}},
      {id:'filter',name:'Untagged only',description:'Keep rows where a rule is true',family:'Change',output:'elements',descriptor:{engine:'Filter'}},
      {id:'document',name:'Tag doors',description:'Write tags to the document',family:'Send',output:'elements',descriptor:{engine:'Document'}}],templates:[],runs:[],mods:[]};
    const listeners=new Set();
    window.fixtureCalls=[];
    const publish=()=>{state={...state,revision:state.revision+1};listeners.forEach(f=>f());};
    window.fixtureState=()=>state;
    const api={refreshProjects:async()=>{},getSnapshot:()=>state,getNodeParameters:()=>[],setSetting:async()=>{},
      addNode:async(id,position)=>{window.fixtureCalls.push({action:'add',id,position});const n={...state.graph.nodes.find(n=>!n.children.length),id:'added',title:'Level',parent:null,children:[],...position};state.graph={...state.graph,nodes:[...state.graph.nodes,n]};publish();return n;},
      moveNodes:async positions=>{window.fixtureCalls.push({action:'move',positions});state.graph={...state.graph,nodes:state.graph.nodes.map(n=>({...n,...positions[n.id]}))};publish();}};
    window.UI={...window.UI,A:window.AH,D:window.AH_DS,api,Chip:({children})=>h('span',null,children),Empty:({children})=>h('p',null,children),
      useData:()=>R.useSyncExternalStore(f=>{listeners.add(f);return()=>listeners.delete(f);},()=>state),useApp:()=>window.fixtureApp,
      GraphProperties:()=>null,NodeRunPolicy:()=>null,MixedProperties:()=>null,CompositeParameters:()=>null};
    window.mountFixture=()=>{
      function App(){const [libraryOpen,setLibraryOpen]=R.useState(false),[selectedNodeId,setSelectedNodeId]=R.useState(null);
        window.fixtureApp={libraryOpen,setLibraryOpen,selectedNodeId,setSelectedNodeId,act:f=>Promise.resolve(f()),show(){},go(){}};
        return h(window.UI.Canvas);}
      window.ReactDOM.createRoot(document.getElementById('root')).render(h(App));
    };
  },graph);
  for(const name of ['ds_library.jsx','ds_screens.jsx'])await page.addScriptTag({content:transformSync(readCanvas(name),{loader:'jsx'}).code});
  await page.evaluate(()=>window.mountFixture());
  await page.locator('[data-graph-node]').first().waitFor({timeout:5000});
  await page.waitForTimeout(120);
  t.after(()=>assert.deepEqual(errors,[],'no browser errors'));
  return page;
}

async function placement(page,reserved=[]) {
 return page.evaluate(reserved=>{
  const detail={reserved,point:null,error:null};window.dispatchEvent(new CustomEvent('archhub:canvas-insertion',{detail}));
  const area=document.querySelector('.node-canvas'),r=area.getBoundingClientRect(),world=area.querySelector('.react-flow__viewport'),m=new window.DOMMatrix(window.getComputedStyle(world).transform);
  const boxes=[...area.querySelectorAll('[data-graph-node]')].map(el=>({id:el.dataset.graphNode,...el.getBoundingClientRect().toJSON()}));
  return {detail,overlays:[...area.closest('[data-screen="canvas"]').querySelectorAll('[data-canvas-overlay]')].map(el=>el.getBoundingClientRect().toJSON()),area:r.toJSON(),matrix:{x:m.e,y:m.f,z:m.a},boxes};
 },reserved);
}
function checkPoint(result) {
 const {detail:{point,error},area,matrix:m,boxes}=result;assert.equal(error,null);assert.ok(point);
 const r={x:area.x+m.x+point.x*m.z,y:area.y+m.y+point.y*m.z,width:point.w*m.z,height:point.h*m.z};
 assert.ok(r.x>=area.x-.01&&r.y>=area.y-.01&&r.x+r.width<=area.right+.01&&r.y+r.height<=area.bottom+.01,'full reserved card inside viewport');
 for(const b of [...boxes,...result.overlays])assert.ok(!overlaps(r,b),'new card avoids '+(b.id||'canvas controls'));
 return point;
}
test('NODEPLACE actual Canvas centres, avoids occupied/repaired cards, follows selection and current pan/zoom',async t=>{
 const graph=fixture();graph.nodes=graph.nodes.filter(n=>!n.children.length).slice(0,2).map((n,i)=>({...n,parent:null,x:i*5000,y:200}));graph.wires=[];
 const page=await mount(t,graph);let result=await placement(page),point=checkPoint(result);
 assert.ok(Math.abs(point.x+point.w/2-(result.area.width/2-result.matrix.x)/result.matrix.z)<.01,'preferred centre');
 // Reserve centre before the first asynchronous create resolves.
 const second=checkPoint(await placement(page,[point]));assert.ok(!overlaps({...point,width:point.w,height:point.h},{...second,width:second.w,height:second.h}));
 await page.locator('[data-graph-node="n0"] .node-header').click();
 result=await placement(page);checkPoint(result);
 const selected=result.boxes.find(b=>b.id==='n0'),m=result.matrix;
 assert.ok(Math.abs(result.detail.point.x-((selected.x-result.area.x-m.x)/m.z+280))<.01,'beside selected');
 await page.locator('.node-canvas .react-flow__pane').evaluate(el=>{const r=el.getBoundingClientRect();el.dispatchEvent(new window.WheelEvent('wheel',{bubbles:true,cancelable:true,clientX:r.x+r.width*.7,clientY:r.y+r.height*.7,deltaX:300,deltaY:120}));});await page.waitForTimeout(60);
 checkPoint(await placement(page));


});
test('NODEPLACE occupied centre uses actual tall DOM bounds and finds the nearest free spot outside a saturated view',async t=>{
 const page=await mount(t,fixture());
 const result=await placement(page);checkPoint(result);
 const full={x:-1e6,y:-1e6,w:2e6,h:2e6};const blocked=await placement(page,[full]);
 assert.equal(blocked.detail.error,null);assert.ok(blocked.detail.point);
 const p=blocked.detail.point;assert.ok(!overlaps({x:p.x,y:p.y,width:p.w,height:p.h},{x:full.x,y:full.y,width:full.w,height:full.h}));
 assert.ok(p.offscreen);assert.deepEqual(blocked.matrix,result.matrix,'placement leaves pan and zoom unchanged');

});
test('NODEPLACE explicit drops bypass placement and failed creation releases the reservation',async()=>{
 let fail=true;
 const canvas={root:'g',nodes:[],wires:[],catalog:[{id:'def',name:'Number',descriptor:{engine:'data.constant'}}]};
 const {api,requests,window}=await adapter({signed_in:false},{'/api/universal/canvas':canvas,'/api/universal/node-create':()=>{if(fail)throw Error('refused');return {ok:true};}});
 const reservations=[];window.addEventListener('archhub:canvas-insertion',e=>{reservations.push(e.detail.reserved.length);e.detail.point={x:400,y:300,w:224,h:160};});
 await assert.rejects(api.addNode('def'),/refused/);fail=false;await api.addNode('def');await api.addNode('def',{x:0,y:-25});
 assert.deepEqual(reservations,[0,0]);assert.equal(requests.filter(r=>r.url==='/api/universal/node-create').at(-1).body.y,-25);
});

async function mountReal(t) {
 const browser=await chromium.launch({channel:'chrome',headless:true});t.after(()=>browser.close());
 const page=await browser.newPage({viewport:{width:1800,height:1200}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<div id="root" style="display:grid;height:100vh"></div>');await page.addStyleTag({content:xyflow.css()+readCanvas('style.css')+'html,body{margin:0;height:100%}'});
 for(const name of ['vendor/react.js','vendor/react-dom.js','xyflow','tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx'])await page.addScriptTag({content:name.endsWith('.jsx')?transformSync(readCanvas(name),{loader:'jsx'}).code:name==='xyflow'?xyflow.script():readCanvas(name)});
 await page.evaluate(()=>{
  window.ARCHHUB_AUTHORITY={};window.ARCHHUB_BOOT={token:'fixture',csrf:'fixture'};
  window.realCanvas={root:'g',nodes:[{id:'far',label:'Far',x:12000,y:200,properties:[],ports:[]}],wires:[],catalog:[{id:'def',name:'Number',descriptor:{engine:'data.constant'}},{id:'tall',name:'Tall',descriptor:{engine:'data.constant'}}]};
  window.realRequests=[];window.fetch=async(url,options={})=>{
   const body=options.body&&JSON.parse(options.body);window.realRequests.push({url,body});let data={ok:true};
   if(url.startsWith('/api/universal/canvas'))data=window.realCanvas;
   if(url==='/api/universal/canvas-op')data={ok:true,result:body.op==='project_state'?{versions:[],modelReview:{}}:[]};
   if(url==='/api/universal/node-create'){
    const id='added-'+window.realCanvas.nodes.length;
    window.realCanvas.nodes.push({id,label:body.title,x:body.x,y:body.y,properties:body.title==='Tall'?Array.from({length:7},(_,i)=>({label:'p'+i,value:'value',editable:true})):[],ports:[]});data={ok:true,root:id};
   }
   if(url==='/fixture/move'){Object.assign(window.realCanvas.nodes.find(n=>n.id===body.id),body.point);}
   if(url==='/fixture/remove')window.realCanvas.nodes=window.realCanvas.nodes.filter(n=>n.id!==body.id);
   return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(data))};
  };
  window.ArchHubStudioAuthority={create:({get,post:send})=>{let held;const post=async(...args)=>{const result=await send(...args);held=Array.isArray(result.nodes)?result:await get('/api/universal/canvas');return result;};return ({getSnapshot:()=>({canvas:held}),clear:()=>{held=null;},adopt:async result=>held=result,transact:async action=>held=await action(),load:async()=>held=await get('/api/universal/canvas'),move:(id,point)=>post('/fixture/move',{id,point}),remove:id=>post('/fixture/remove',{id})})}};
 });
 await page.addScriptTag({content:readCanvas('api.js')});await page.evaluate(()=>window.ArchHubAPI.ready);
 await page.evaluate(()=>{
  const R=window.React,h=R.createElement,api=window.ArchHubAPI;
  window.UI={...window.UI,A:window.AH,D:window.AH_DS,api,Chip:({children})=>h('span',null,children),Empty:({children})=>h('p',null,children),
   useData:()=>{const s=R.useSyncExternalStore(api.subscribe,api.getSnapshot);return {...s,graphs:[{id:'system'},...s.graphs]};},useApp:()=>window.realApp,
   GraphProperties:()=>null,NodeRunPolicy:()=>null,MixedProperties:()=>null,CompositeParameters:()=>null};
  window.mountReal=()=>{function App(){const [libraryOpen,setLibraryOpen]=R.useState(false),[selectedNodeId,setSelectedNodeId]=R.useState(null);window.realApp={libraryOpen,setLibraryOpen,selectedNodeId,setSelectedNodeId,act:f=>Promise.resolve(f()),show(){},go(){}};return h(window.UI.Canvas);}window.realRoot=R.createElement(App);window.realDOMRoot=window.ReactDOM.createRoot(document.getElementById('root'));window.realDOMRoot.render(window.realRoot);};
 });
 for(const name of ['ds_library.jsx','ds_screens.jsx'])await page.addScriptTag({content:transformSync(readCanvas(name),{loader:'jsx'}).code});
 await page.evaluate(()=>window.mountReal());await page.waitForTimeout(200);await page.locator('[data-graph-node]').first().waitFor({timeout:3000});await page.waitForTimeout(120);
 t.after(()=>assert.deepEqual(errors,[]));return page;
}
async function checkAdded(page) {
 const {area,boxes,overlays}=await placement(page);const added=boxes.filter(b=>b.id.startsWith('added'));
 for(const b of added){assert.ok(b.x>=area.x-.01&&b.y>=area.y-.01&&b.right<=area.right+.01&&b.bottom<=area.bottom+.01,'actual '+b.id+' fully visible');for(const other of [...boxes,...overlays])if(other.id!==b.id)assert.ok(!overlaps(b,other),b.id+' avoids '+other.id);}
}
test('NODEPLACE real API plus Canvas: concurrent and same-turn adds, tall card, explicit drop and unmount',async t=>{
 const page=await mountReal(t);
 await page.locator('[data-graph-node="far"] .node-header').click();
 await page.evaluate(async()=>{await Promise.all([window.ArchHubAPI.addNode('def'),window.ArchHubAPI.addNode('def')]);await window.ArchHubAPI.addNode('def');await window.ArchHubAPI.addNode('tall');});
 await page.waitForTimeout(80);await checkAdded(page);
 assert.equal(await page.locator('[data-graph-node^="added"]').count(),4);
 if(process.env.CANVASLOOK_EVIDENCE){
  const output=fs.mkdtempSync(path.join(process.env.TEMP||require('node:os').tmpdir(),'NODEPLACE-'));
  t.after(()=>fs.rmSync(output,{recursive:true,force:true}));
  await page.screenshot({path:path.join(output,'NODEPLACE.png')});
  assert.deepEqual(fs.readdirSync(output),['NODEPLACE.png']);
 }
 assert.equal(await page.evaluate(()=>window.realRequests.find(r=>r.url==='/api/universal/node-create').body.x),12280,'real insertion beside selected node');
 await page.evaluate(()=>window.ArchHubAPI.addNode('def',{x:-40,y:25}));
 assert.deepEqual(await page.evaluate(()=>window.realRequests.filter(r=>r.url==='/api/universal/node-create').at(-1).body),{title:'Number',engine:'data.constant',x:-40,y:25});
 await page.evaluate(()=>window.realDOMRoot.unmount());
 assert.equal(await page.evaluate(()=>{const detail={reserved:[],point:null,error:null};window.dispatchEvent(new CustomEvent('archhub:canvas-insertion',{detail}));return detail.point;}),null,'unmount removes viewport owner');
});

test('NODEPLACE concurrent revision-root creations return their own selected node',async()=>{
 let release,started;const held=new Promise(r=>release=r),ready=new Promise(r=>started=r);let next=0;
 const canvas={root:'g',nodes:[],wires:[],catalog:[{id:'def',name:'Number',revision_root:'rev'}]};
 const {api}=await adapter({signed_in:false},{'/api/universal/canvas':canvas,'/fixture/create':async body=>{
  const id='created-'+next++;canvas.nodes.push({id,label:id,x:body.x,y:body.y,properties:[],ports:[]});canvas.selected=id;
  if(id==='created-0'){started();await held;}return {ok:true,selected:id};
 }});
 const first=api.addNode('def');await ready;const second=api.addNode('def');release();
 const results=await Promise.all([first,second]);assert.deepEqual(results.map(n=>n.id),['created-0','created-1']);
});
test('NODEPLACE bounded rendering wait does not move a node after navigation',async()=>{
 const canvas={root:'g',nodes:[],wires:[],catalog:[{id:'def',name:'Number',descriptor:{engine:'data.constant'}}]};
 const {api,window,document,requests}=await adapter({signed_in:false},{'/api/universal/canvas':canvas,'/api/universal/node-create':body=>{canvas.nodes.push({id:'made',label:'Number',x:body.x,y:body.y,properties:[],ports:[]});return {ok:true,root:'made'};}});
 document.hidden=false;let frames=0;window.requestAnimationFrame=()=>{frames++;};let calls=0;
 window.addEventListener('archhub:canvas-insertion',e=>{calls++;e.detail.point={x:400,y:300,w:224,h:160};});
 const made=api.addNode('def');while(!frames)await new Promise(r=>setImmediate(r));
 await api.selectGraph('other').catch(()=>{});await made;
 assert.equal(calls,1,'stale graph does not get post-create placement');assert.equal(requests.some(r=>r.url==='/fixture/remove'||r.url==='/fixture/move'),false);
});
test('NODEPLACE actual-height overflow keeps the new node and reports direction without deleting',async()=>{
 const canvas={root:'g',nodes:[],wires:[],catalog:[{id:'def',name:'Number',descriptor:{engine:'data.constant'}}]};
 const {api,window,document,requests}=await adapter({signed_in:false},{'/api/universal/canvas':canvas,'/api/universal/node-create':body=>{canvas.nodes.push({id:'made',label:'Number',x:body.x,y:body.y,properties:[],ports:[]});return {ok:true,root:'made'};},'/fixture/move':body=>{Object.assign(canvas.nodes.find(n=>n.id===body.id),body.point);return {ok:true};}});
 document.hidden=false;window.requestAnimationFrame=fn=>setTimeout(fn,0);
 const notices=[];window.addEventListener('archhub:notice',e=>notices.push(e.detail.message));
 window.addEventListener('archhub:canvas-insertion',e=>{e.detail.point=e.detail.nodeId?{x:1100,y:300,w:224,h:900,offscreen:'right'}:{x:400,y:300,w:224,h:160};});
 const made=await api.addNode('def');assert.equal(made.id,'made');assert.equal(canvas.nodes.length,1);
 assert.equal(canvas.nodes[0].x,1100);assert.equal(requests.some(r=>r.url==='/fixture/remove'),false);
 assert.deepEqual(notices.filter(n=>n.startsWith('Added off-screen')),['Added off-screen — right']);
});

test('NODEPLACE full viewport still creates through real API and Canvas without removal or camera movement',async t=>{
 const page=await mountReal(t);
 await page.evaluate(()=>{const area=document.querySelector('.node-canvas');area.style.width='180px';area.style.height='120px';window.nodeplaceNotices=[];window.addEventListener('archhub:notice',e=>window.nodeplaceNotices.push(e.detail.message));});
 const before=await placement(page);
 const made=await page.evaluate(()=>window.ArchHubAPI.addNode('def'));
 const after=await placement(page);assert.deepEqual(after.matrix,before.matrix);
 assert.ok(made.id);assert.equal(await page.locator('[data-graph-node^="added"]').count(),1);
 const data=await page.evaluate(()=>({requests:window.realRequests,notices:window.nodeplaceNotices}));
 assert.equal(data.requests.filter(r=>r.url==='/api/universal/node-create').length,1);
 assert.equal(data.requests.some(r=>r.url==='/fixture/remove'),false);
 assert.match(data.notices.at(-1),/^Added off-screen — (left|right|above|below)/);
 const added=after.boxes.find(b=>b.id===made.id);
 for(const b of [...after.boxes,...after.overlays])if(b.id!==made.id)assert.ok(!overlaps(added,b));
});
