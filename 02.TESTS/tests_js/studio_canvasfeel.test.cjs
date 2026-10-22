'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {transformSync} = require('esbuild');
const {JSDOM} = require('jsdom');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const readSource=name=>process.env.CANVASFEEL_BASELINE==='1'
  ? require('node:child_process').execFileSync('git',['show','HEAD:01.APP/nodelang/studio/'+name],{cwd:path.resolve(studio,'../../..'),encoding:'utf8'})
  : fs.readFileSync(path.join(studio,name),'utf8');
const source = transformSync(readSource('ds_screens.jsx'), {loader:'jsx'}).code;
const nodes = () => ['a','b','c'].map((id,i) => ({id,title:id,kind:'Node',x: i*310-180,y:i*140-80,
  status:'',params:{},defaults:{},inputs:[{id:'in',name:'input',type:'number'}],outputs:[]}));

async function mount(t) {
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window, d=w.document, moved=[], saved=[];
  w.eval(fs.readFileSync(path.join(studio,'vendor/react.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(studio,'vendor/react-dom.js'),'utf8'));
  const R=w.React, h=R.createElement;
  const zoomSetting=value=>({id:'relation-theme-zoom:zoom',page:'Appearance',label:'Zoom percentage',key:'zoom',value});
  let snapshot={revision:1,graph:{id:'mine',name:'My graph',nodes:nodes(),wires:[]},settings:[zoomSetting(80)],workspaces:[]};
  const listeners=new Set();let releaseSave=null;
  const publishZoom=value=>{snapshot={...snapshot,settings:[zoomSetting(value)],revision:snapshot.revision+1};listeners.forEach(f=>f());};
  const api={refreshProjects:async()=>{},getSnapshot:()=>snapshot, getNodeParameters:()=>[],moveNodes:p=>moved.push(p),setSetting:async(id,value)=>{
    saved.push({id,value});if(releaseSave)await new Promise(resolve=>{releaseSave=resolve;});publishZoom(value);
  }};
  const app={libraryOpen:false,selectedNodeId:null,setSelectedNodeId(){},act:f=>Promise.resolve(f()),show(){},go(){}};
  const Btn=({children,onClick,title,disabled,...p})=>h('button',{'aria-label':p['aria-label'],disabled,title,onClick},children);
  const Node=({children,title,headerProps,selected,ins=[],outs=[],renderPort})=>h('article',{'data-selected':String(selected)},h('header',headerProps,title),
    ...ins.map((p,i)=>renderPort?.(p,i,'in')),...outs.map((p,i)=>renderPort?.(p,i,'out')),children);
  w.UI={A:{accent:'#f90',line:'#333'},D:{Node,Socket:()=>null,Toggle:()=>null},api,useData:()=>R.useSyncExternalStore(f=>{listeners.add(f);return()=>listeners.delete(f);},()=>snapshot),useApp:()=>app,Btn,Chip:({children})=>h('span',null,children),
    GraphProperties:()=>null,NodeRunPolicy:()=>null,MixedProperties:()=>null,Table:()=>null};
  w.AHIcon=()=>null;
  w.registerActions=(map,handlers)=>{w.executeAction=(id,scope,e)=>handlers[map[id]](scope,e);};
  w.HTMLElement.prototype.setPointerCapture=function(){};
  const rect=(x,y,width,height)=>({x,y,left:x,top:y,right:x+width,bottom:y+height,width,height});
  function viewport(){
    const world=d.querySelector('.node-canvas')?.querySelector(':scope > div[style*="scale"]');
    const m=world?.style.transform.match(/translate\(([-.\de]+)px,\s*([-.\de]+)px\) scale\(([-.\de]+)\)/);
    return m?{x:+m[1],y:+m[2],z:+m[3]}:{x:0,y:0,z:.8};
  }
  w.HTMLElement.prototype.getBoundingClientRect=function(){
    if(this.classList.contains('node-canvas'))return rect(100,70,900,620);
    if(this.hasAttribute('data-graph-node')) {const p=viewport();return rect(100+p.x+parseFloat(this.style.left)*p.z,70+p.y+parseFloat(this.style.top)*p.z,250*p.z,240*p.z);}
    return rect(0,0,0,0);
  };
  Object.defineProperties(w.HTMLElement.prototype,{clientWidth:{get(){return this.classList.contains('node-canvas')?900:250;}},clientHeight:{get(){return this.classList.contains('node-canvas')?620:240;}}});
  w.eval(source);
  const root=w.ReactDOM.createRoot(d.getElementById('root'));
  const flush=f=>w.ReactDOM.flushSync(f);
  flush(()=>root.render(h(w.UI.Canvas)));
  await new Promise(r=>w.setTimeout(r,25));
  flush(()=>{});
  const area=d.querySelector('.node-canvas');assert.ok(area,'real Canvas mounted');
  await new Promise(r=>w.setTimeout(r,100));
  const emit=async(el,type,p={})=>{flush(()=>{
    const Event=type==='wheel'?w.WheelEvent:type.startsWith('key')?w.KeyboardEvent:w.MouseEvent;
    const event=new Event(type,{bubbles:true,cancelable:true,button:0,...p});
    if(type.startsWith('pointer'))Object.defineProperties(event,{pointerId:{value:p.pointerId??1},pointerType:{value:p.pointerType??'mouse'}});
    el.dispatchEvent(event);
  }); await new Promise(r=>w.setTimeout(r,5)); flush(()=>{}); };
  t.after(()=>{flush(()=>root.unmount());w.close();});
  return {w,d,area,viewport,emit,moved,saved,publishZoom,setNodes:rows=>{
    snapshot={...snapshot,graph:{...snapshot.graph,nodes:rows},revision:snapshot.revision+1};listeners.forEach(f=>f());
  },holdSave:()=>{releaseSave=true;},releaseSave:()=>{const release=releaseSave;releaseSave=null;release();}};
}
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);

test('wheel zoom keeps the graph point under an off-origin cursor fixed; modified wheel pans',async t=>{
  const s=await mount(t),before=s.viewport(),cursor={x:370,y:260};
  await s.emit(s.area,'wheel',{clientX:470,clientY:330,deltaY:-120});
  const after=s.viewport();assert.ok(after.z>before.z,'plain wheel must zoom');
  close((cursor.x-before.x)/before.z,(cursor.x-after.x)/after.z);
  close((cursor.y-before.y)/before.z,(cursor.y-after.y)/after.z);
  await s.emit(s.area,'keydown',{key:'Control'});
  await s.emit(s.area,'wheel',{ctrlKey:true,deltaX:12,deltaY:35});
  const pan=s.viewport();close(pan.z,after.z);close(pan.x,after.x-12);close(pan.y,after.y-35);
  await s.emit(s.area,'keyup',{key:'Control'});
  await s.emit(s.area,'wheel',{shiftKey:true,deltaY:20});assert.equal(s.viewport().z,pan.z);
});
test('a 3 px pointer move is a click and never moves or saves a node',async t=>{
  const s=await mount(t),head=s.d.querySelector('[data-graph-node="a"] header');
  const left=s.d.querySelector('[data-graph-node="a"]').style.left;
  await s.emit(head,'pointerdown',{clientX:200,clientY:170});
  await s.emit(head,'pointermove',{clientX:203,clientY:170});
  assert.equal(s.d.querySelector('[data-graph-node="a"]').style.left,left);
  await s.emit(head,'pointerup',{clientX:203,clientY:170});assert.equal(s.moved.length,0);
  const current=s.d.querySelector('[data-graph-node="a"] header');
  await s.emit(current,'pointerdown',{clientX:200,clientY:170});
  await s.emit(current,'pointermove',{clientX:210,clientY:170});
  await s.emit(current,'pointerup',{clientX:210,clientY:170});
  assert.equal(s.moved.length,1,'a deliberate drag must still save once');
});
test('Shift drag selects two intersecting nodes and preserves graph positions',async t=>{
  const s=await mount(t);
  // First two cards in the viewport at its starting zoom, excluding the third.
  await s.emit(s.area,'pointerdown',{shiftKey:true,clientX:-60,clientY:-10});
  await s.emit(s.area,'pointermove',{shiftKey:true,clientX:430,clientY:400});
  await s.emit(s.area,'pointerup',{shiftKey:true,clientX:430,clientY:400});
  const selected=[...s.d.querySelectorAll('[data-graph-node]')].filter(el=>el.querySelector('[data-selected="true"]')).map(el=>el.dataset.graphNode);
  assert.deepEqual(selected,['a','b']);assert.equal(s.moved.length,0);
});
test('double click empty canvas fits every card including negative coordinates',async t=>{
  const s=await mount(t);await s.emit(s.area,'dblclick',{clientX:800,clientY:600});
  for(const el of s.d.querySelectorAll('[data-graph-node]')) {
    const r=el.getBoundingClientRect(),a=s.area.getBoundingClientRect();
    assert.ok(r.left>=a.left && r.top>=a.top && r.right<=a.right && r.bottom<=a.bottom,el.dataset.graphNode+' must fit');
  }
});
test('middle and Space drags pan over cards without selecting or moving nodes',async t=>{
  const s=await mount(t),head=s.d.querySelector('header'),before=s.viewport();
  await s.emit(head,'pointerdown',{button:1,clientX:200,clientY:170});await s.emit(s.area,'pointermove',{clientX:240,clientY:195});await s.emit(s.area,'pointerup');
  close(s.viewport().x,before.x+40);close(s.viewport().y,before.y+25);
  await s.emit(s.area,'keydown',{key:' '});
  const pan=s.viewport();await s.emit(head,'pointerdown',{clientX:200,clientY:170});await s.emit(s.area,'pointermove',{clientX:230,clientY:190});await s.emit(s.area,'pointerup');
  close(s.viewport().x,pan.x+30);assert.equal(s.moved.length,0);
});
test('keyboard and toolbar zoom share percentage and persist through settings after settling',async t=>{
  const s=await mount(t);
  s.area.dispatchEvent(new s.w.KeyboardEvent('keydown',{key:'0',bubbles:true,cancelable:true}));
  await new Promise(r=>s.w.setTimeout(r,20));close(s.viewport().z,1);
  await s.emit(s.d.querySelector('[aria-label="Zoom in"]'),'click');assert.ok(s.viewport().z>1);
  await new Promise(r=>s.w.setTimeout(r,450));
  assert.equal(s.saved.at(-1)?.id,'relation-theme-zoom:zoom');
  assert.equal(s.saved.at(-1)?.value,Math.round(s.viewport().z*100));
  assert.ok(s.d.querySelector('.canvas-toolbar').textContent.includes(Math.round(s.viewport().z*100)+'%'));
});

async function adapter({current='mine',graphs=[{id:'system'},{id:'mine'}],refuse=false,stored={},beforeOpen=async()=>{}}={}) {
  const vm=require('node:vm'),calls=[];
  let root='system';
  let viewport={zoom:.8,pan_x:12,pan_y:24};
  const canvas=()=>({root,scope:{current:root},nodes:[],wires:[],catalog:[],viewport});
  const sessionStorage={getItem:key=>stored[key]||null,setItem:(key,value)=>{stored[key]=value;}};
  const window={structuredClone:globalThis.structuredClone,crypto:require('node:crypto').webcrypto,ARCHHUB_BOOT:{token:'fixture',csrf:'fixture'},
    document:{hidden:true,addEventListener(){}},addEventListener(){},dispatchEvent(){},
    ArchHubStudioAuthority:{create:({get})=>({load:()=>get('/api/universal/canvas')})}};
  const fetch=async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
    let data={ok:true,result:[],mods:{rows:[]}};
    if(url==='/api/universal/canvas')data=canvas();
    if(url==='/api/universal/graphs?screen=home')data={ok:true,graphs,current_graph:current};
    if(url==='/api/universal/graph-open'){
      await beforeOpen(body.root);
      if(refuse)data={ok:false,error:'Graph no longer admitted'};
      else {root=body.root;current=root;data={ok:true};}
    }
    if(url==='/api/universal/gesture'){viewport={...viewport,...body.viewport};data={ok:true};}
    return {ok:data.ok!==false,status:data.ok===false?409:200,json:async()=>data};
  };
  vm.runInNewContext(readSource('api.js'),{window,document:window.document,fetch,
    sessionStorage,CustomEvent:class{},setTimeout,clearTimeout,URLSearchParams,AbortSignal,console});
  await window.ArchHubAPI.ready;await new Promise(r=>setTimeout(r,5));
  return {api:window.ArchHubAPI,calls};
}
test('Canvas opens the last admitted graph from the existing graph list without creating a graph',async()=>{
  const {api,calls}=await adapter();await api.refreshProjects();
  assert.equal(api.getSnapshot().graph.id,'mine');
  assert.equal(calls.filter(c=>c.url==='/api/universal/graph-open').length,1);
  assert.equal(calls.some(c=>c.url==='/api/universal/graph-create'),false);
  await api.refreshProjects();
  assert.equal(calls.filter(c=>c.url==='/api/universal/graph-open').length,1,'same graph is never reopened');
});
test('last user graph survives reopening Canvas when the server view starts at System',async()=>{
  const stored={};const first=await adapter({current:'system',stored});await first.api.selectGraph('mine');
  assert.equal(JSON.parse(stored['archhub.studio.session']).lastGraphId,'mine');
  const reopened=await adapter({current:'system',stored});await reopened.api.refreshProjects();
  assert.equal(reopened.api.getSnapshot().graph.id,'mine');
  const stale=await adapter({current:'system',stored,graphs:[{id:'system'}]});await stale.api.refreshProjects();
  assert.equal(stale.calls.some(c=>c.url==='/api/universal/graph-open'),false);
});
test('explicit navigation wins over an automatic graph restore already in flight',async()=>{
  let release,started;
  const entered=new Promise(resolve=>{started=resolve;});
  const s=await adapter({graphs:[{id:'system'},{id:'mine'},{id:'other'}],beforeOpen:async id=>{if(id==='mine'){started();await new Promise(resolve=>{release=resolve;});}}});
  const restored=s.api.refreshProjects();await entered;
  const selected=s.api.selectGraph('other');release();await Promise.all([restored,selected]);
  assert.equal(s.api.getSnapshot().graph.id,'other');
  assert.deepEqual(s.calls.filter(c=>c.url==='/api/universal/graph-open').map(c=>c.body.root),['mine','other']);
});
test('Appearance percentage reads and saves the existing viewport through its gesture owner',async()=>{
  const {api,calls}=await adapter();
  const setting=api.getSnapshot().settings.find(row=>row.page==='Appearance'&&row.label==='Zoom percentage');
  assert.equal(setting?.value,80);await api.setSetting(setting.id,125);
  assert.equal(api.getSnapshot().settings.find(row=>row.id===setting.id).value,125);
  const call=calls.find(c=>c.url==='/api/universal/gesture');
  assert.deepEqual(call.body.viewport,{zoom:1.25,pan_x:12,pan_y:24});
  await assert.rejects(api.setSetting(setting.id,-10),/positive zoom/);
  const reset=await api.resetPage('Appearance');assert.equal(reset.ok,true);
  assert.equal(api.getSnapshot().settings.find(row=>row.id===setting.id).value,125,'a theme reset leaves the view alone when its owner exposes no reset default');
});
test('stale graph-list selection never opens an unlisted graph; a refused restore is visible',async()=>{
  const stale=await adapter({current:'deleted'});await stale.api.refreshProjects();
  assert.equal(stale.calls.some(c=>c.url==='/api/universal/graph-open'),false);
  const denied=await adapter({refuse:true});await assert.rejects(denied.api.refreshProjects(),/Graph no longer admitted/);
});
test('pinch wheels and two touch pointers zoom at their centre',async t=>{
  const s=await mount(t),before=s.viewport();
  await s.emit(s.area,'wheel',{ctrlKey:true,clientX:420,clientY:300,deltaY:-15});
  assert.ok(s.viewport().z>before.z,'pinch wheel without a physical Ctrl press zooms');
  const v=s.viewport();
  await s.emit(s.area,'pointerdown',{pointerType:'touch',pointerId:1,clientX:300,clientY:250});
  await s.emit(s.area,'pointerdown',{pointerType:'touch',pointerId:2,clientX:500,clientY:250});
  await s.emit(s.area,'pointermove',{pointerType:'touch',pointerId:2,clientX:600,clientY:250});
  const after=s.viewport();close(after.z,v.z*1.5);
  close((400-100-v.x)/v.z,(450-100-after.x)/after.z);
  await s.emit(s.area,'pointerup',{pointerType:'touch',pointerId:2});
});
test('Shift+1 uses the physical digit key; editable controls keep keyboard input',async t=>{
  const s=await mount(t);
  await s.emit(s.area,'keydown',{key:'!',code:'Digit1',shiftKey:true});
  for(const el of s.d.querySelectorAll('[data-graph-node]'))assert.ok(el.getBoundingClientRect().left>=100);
  const input=s.d.createElement('input');s.area.append(input);const before=s.viewport();
  await s.emit(input,'keydown',{key:'0'});assert.deepEqual(s.viewport(),before);
});
test('settings echoes from a slow save never rewind a newer gesture; external settings update the toolbar',async t=>{
  const s=await mount(t);s.holdSave();
  await s.emit(s.area,'wheel',{clientX:420,clientY:300,deltaY:-80});
  await new Promise(r=>s.w.setTimeout(r,340));assert.equal(s.saved.length,1);
  await s.emit(s.area,'wheel',{clientX:420,clientY:300,deltaY:-80});const latest=s.viewport();
  s.releaseSave();await new Promise(r=>s.w.setTimeout(r,50));
  close(s.viewport().z,latest.z);
  await new Promise(r=>s.w.setTimeout(r,400));assert.equal(s.saved.at(-1).value,Math.round(latest.z*100));
  s.publishZoom(65);await new Promise(r=>s.w.setTimeout(r,30));close(s.viewport().z,.65);
  assert.ok(s.d.querySelector('.canvas-toolbar').textContent.includes('65%'));
});
test('Fit and wheel share the owner zoom limits, including a graph wider than the minimum view',async t=>{
  const s=await mount(t);s.setNodes(nodes().map((n,i)=>({...n,x:i*10000,y:0})));
  await new Promise(r=>s.w.setTimeout(r,20));await s.emit(s.area,'dblclick');
  close(s.viewport().z,.1);
  await s.emit(s.area,'wheel',{clientX:500,clientY:300,deltaY:-1});
  assert.ok(s.viewport().z>.1&&s.viewport().z<.11,'one wheel step must not jump back to the old 20% clamp');
});
test('a pinch starting on a captured socket releases both pointers before the next pinch',async t=>{
  const s=await mount(t),socket=s.d.querySelector('[data-endpoint]');
  await s.emit(socket,'pointerdown',{pointerType:'touch',pointerId:1,clientX:300,clientY:250});
  await s.emit(s.area,'pointerdown',{pointerType:'touch',pointerId:2,clientX:500,clientY:250});
  await s.emit(socket,'pointerup',{pointerType:'touch',pointerId:1,clientX:300,clientY:250});
  await s.emit(s.area,'pointerup',{pointerType:'touch',pointerId:2,clientX:500,clientY:250});
  const before=s.viewport();
  await s.emit(s.area,'pointerdown',{pointerType:'touch',pointerId:3,clientX:300,clientY:250});
  await s.emit(s.area,'pointerdown',{pointerType:'touch',pointerId:4,clientX:500,clientY:250});
  await s.emit(s.area,'pointermove',{pointerType:'touch',pointerId:4,clientX:600,clientY:250});
  close(s.viewport().z,before.z*1.5);
});
