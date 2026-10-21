/* Source-runtime DOM courts; no release build, app process or desktop profile. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
const studio = path.join(__dirname, '../../01.APP/nodelang/studio');
const baselineRef = process.env.MAINFIX_BASELINE === '1' ? 'ce671c2e' : process.env.MAINFIX_BASELINE;
const baseline = !!baselineRef && baselineRef !== '0';
const read = name => baseline ? require('node:child_process').execFileSync('git',
  ['show',baselineRef+':01.APP/nodelang/studio/'+name],{encoding:'utf8',maxBuffer:8*1024*1024}) :
  fs.readFileSync(path.join(studio, name), 'utf8');
const babel = vm.createContext({});
vm.runInContext(read('vendor/babel.js'), babel);
const names = ['tokens.jsx','ds/index.jsx','design-canvas.jsx','shared-data.jsx','studio-suite.jsx',
  'param-types.jsx','studio-params.jsx','studio-mobile.jsx','studio-account.jsx','node-registry.jsx',
  'brain-model.jsx','workshop-board.jsx','studio-workshop.jsx','studio-lm.jsx'];
const code = new Map(names.map(name => [name, babel.Babel.transform(read(name), {
  presets:['react','env'], plugins:['transform-class-properties','transform-object-rest-spread','transform-flow-strip-types'],
  targets:{}, sourceMaps:false}).code]));
async function loaderFixture() {
  const Module = require('node:module');
  const filename=path.join(__dirname,'studio_workshop72_node_lazy.test.cjs');
  const harness=new Module(filename,module);harness.filename=filename;harness.paths=module.paths;
  const realRequire=harness.require.bind(harness);
  let context;
  harness.require=name=>name==='node:test'?{test:()=>{}}:name==='./studio_ds_context.cjs' ?
    {...realRequire(name),createContext:values=>(context=vm.createContext(values))} : name==='./workshop72_node_helpers.cjs' ?
    {...realRequire(name),read:file=>baseline && file==='01.APP/nodelang/studio/studio.html' ? read('studio.html') :
      fs.readFileSync(path.join(__dirname,'..',file),'utf8')} : realRequire(name);
  harness._compile(fs.readFileSync(filename,'utf8')+'\nmodule.exports={loaderFixture};',filename);
  const fixture=await harness.exports.loaderFixture();
  return {...fixture,context};
}
async function mounted(options = {}) {
  const {deferredWorkshop = false, failCanvas = false} = options;
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53941/',runScripts:'outside-only',pretendToBeVisual:true});
  const w = dom.window, listeners = new Set();
  const graph = {nodes:[{id:'think-a',title:'Think A',cat:'ai',engine:'library.think',live:true,x:20,y:20,w:180,h:110,
    params:[{k:'model',v:'openrouter/free',editable:true}],ins:[],outs:[]}],wires:[]};
  const canvas = {graph_id:'graph-a',application_root:'graph-a',root:'scope-a',scope:{current:'scope-a'},revision:1,
    authorization:{subject:'owner-a',session:'view-a'}};
  const snapshot = {canvas,workshops:[{root:'room-a',label:'Workshop',is_general:true}],
    topology:{canvas,graph,selected:null}};
  let published = snapshot;
  const publish = () => {
    published = {...snapshot,canvas:{...snapshot.canvas},topology:{...snapshot.topology,canvas:{...snapshot.topology.canvas}}};
    listeners.forEach(fn=>fn());
  };
  let canvasLoads = 0;
  w.ARCHHUB_LIVE = {sessions:[{id:'graph-a',title:'Mine',state:'idle'}],currentGraph:'graph-a',graph,hosts:[],connectors:[],skills:[],memory:[]};
  w.ARCHHUB_BOOT = {open_graph:deferredWorkshop ? null : 'graph-a'};
  w.ARCHHUB_EXISTING_WORKSHOP = {getSnapshot:()=>published,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},
    readProviders:async()=>[{id:'nvidia',name:'NVIDIA',state:'no key'}],
    watchApplicationUpdate:()=>()=>{}};
  if (deferredWorkshop) {
    canvas.canvas_deferred = true;
    snapshot.workshops = [];
    w.ARCHHUB_LOAD_CANVAS = async () => {
      if (canvas.canvas_deferred !== true) return canvas;
      canvasLoads++;
      if (failCanvas && canvasLoads === 1) throw new Error('Canvas connection unavailable');
      canvas.canvas_deferred = false;
      snapshot.workshops = [{root:'room-a',label:'Workshop',is_general:true}];
      publish();
      return canvas;
    };
    w.ARCHHUB_EXISTING_WORKSHOP.openWorkshop = async root => {
      snapshot.workshop = {root,graph_id:canvas.graph_id,scope_root:canvas.root,revision:1,
        self:'owner-a',participants:[{root:'agent-a',label:'Agent A',is_agent:true}],
        messages:[{root:'mail-a',sender_root:'agent-a',body:'Real shared mailbox message'}],can_send:true};
      publish();
      return snapshot.workshop;
    };
  }
  w.matchMedia = ()=>({matches:false,addEventListener(){},removeEventListener(){}});
  w.fetch = async url => ({ok:true,json:async()=>String(url).includes('/models') ?
    {ok:true,groups:[],selected_route:'openrouter/free',default_model:{name:'Free',route:'openrouter/free'}} : {ok:true,tools:[],items:[]}});
  w.eval(read('vendor/react.js')); w.eval(read('vendor/react-dom.js'));
  for (const name of names) if (!['workshop-board.jsx','studio-workshop.jsx'].includes(name)) w.eval(code.get(name));
  w.ARCHHUB_LOAD_WORKSHOP = async()=>{
    for(const name of ['workshop-board.jsx','studio-workshop.jsx']) w.eval(code.get(name));
    return w.WorkshopView;
  };
  w.eval('window.__root=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__root.render(React.createElement(StudioLM)));');
  const flush = fn=>w.ReactDOM.flushSync(fn);
  const settle = async()=>{for(let i=0;i<8;i++)await new Promise(r=>w.setTimeout(r,10));};
  const rail = async name=>{flush(()=>w.document.querySelector(`[data-app-rail] [aria-label="${name}"]`).click());await settle();};
  const type=(input,value)=>flush(()=>{
    Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype,'value').set.call(input,value);
    input.dispatchEvent(new w.Event('input',{bubbles:true}));
  });
  return {w,doc:w.document,rail,settle,flush,type,snapshot,get canvasLoads(){return canvasLoads;},
    publish(){flush(publish);},select(id){snapshot.topology={...snapshot.topology,selected:id,
    canvas:{...canvas,selection:id?[id]:[]}};flush(publish);},
    close(){flush(()=>w.__root.unmount());w.close();}};
}
test('MAINFIX Workshop rail resolves the real lazy face on a fresh profile', async()=>{
  const ui=await mounted();
  try {await ui.rail('Workshop');const face=ui.doc.querySelector('[data-workshop72]');assert.ok(face,ui.doc.body.textContent);
    assert.ok(face.querySelector('textarea[aria-label="Workshop message"]'));
    assert.ok(face.querySelectorAll('[data-workshop-primary]').length>=2,'Workshop owns its New task and Send controls');
    assert.equal(ui.doc.querySelector('[data-workshop-loading]'),null);
  } finally {ui.close();}
});
test('MAINFIX Workshop opens its deferred Home scope and draws the shared mailbox message',async()=>{
  const ui=await mounted({deferredWorkshop:true});
  try {
    assert.equal(ui.canvasLoads,0,'Home does not load the deferred canvas');
    await ui.rail('Workshop');await ui.settle();
    assert.match(ui.doc.querySelector('[data-workshop72]').textContent,/Real shared mailbox message/);
    assert.equal(ui.snapshot.workshop.root,'room-a');
    assert.equal(ui.snapshot.topology.canvas.canvas_deferred,false);
    assert.equal(ui.canvasLoads,1);
    ui.snapshot.workshops=[{root:'room-b',label:'Different room',is_general:true}];
    ui.publish();await ui.settle();
    assert.doesNotMatch(ui.doc.querySelector('[data-workshop72]').textContent,/Different room/,
      'a refreshed descriptor cannot silently switch the opened mailbox');
  } finally {ui.close();}
});
test('MAINFIX deferred Workshop reports a failed canvas read and Retry opens the mailbox',async()=>{
  const ui=await mounted({deferredWorkshop:true,failCanvas:true});
  try {
    await ui.rail('Workshop');await ui.settle();
    assert.match(ui.doc.body.textContent,/Canvas connection unavailable/);
    const retry=[...ui.doc.querySelectorAll('button')].find(row=>/retry/i.test(row.textContent));
    assert.ok(retry);ui.flush(()=>retry.click());await ui.settle();await ui.settle();
    assert.match(ui.doc.querySelector('[data-workshop72]').textContent,/Real shared mailbox message/);
    assert.equal(ui.canvasLoads,2);
  } finally {ui.close();}
});
test('MAINFIX Workshop retries a failed lazy asset load without restarting Studio',async()=>{
  const ui=await loaderFixture();
  try {
    const append=ui.win.document.body.appendChild;
    let fail=true;
    ui.win.document.body.appendChild=tag=>{
      if(fail&&tag.src.includes('workshop')){fail=false;tag.onerror();return tag;}
      return append(tag);
    };
    await assert.rejects(ui.win.ARCHHUB_LOAD_WORKSHOP(),/compiled asset/);
    const view=await ui.win.ARCHHUB_LOAD_WORKSHOP();
    assert.equal(view,ui.win.WorkshopView);
  } finally {ui.close();}
});
for(const stage of ['fetch','body','script']) test('MAINFIX Workshop cancels a pending '+stage+' and retries a fresh load',{timeout:5000},async()=>{
  const ui=await loaderFixture();
  try {
    const originalFetch=ui.context.fetch,originalAppend=ui.win.document.body.appendChild;
    let held,oldLoad,oldError,once=true,entered=false,readerReleased=0;
    const pending=signal=>new Promise((resolve,reject)=>{
      if(signal?.aborted) reject(signal.reason);
      else signal?.addEventListener('abort',()=>reject(signal.reason),{once:true});
    });
    ui.context.fetch=async(url,options)=>{
      if(stage!=='script'&&once&&url.includes('workshop-board')) {
        once=false;
        if(stage==='fetch') {entered=true;return pending(options?.signal);}
        const reader={read:()=>{entered=true;return pending(options?.signal);},releaseLock(){readerReleased++;},cancel:async()=>{}};
        return {ok:true,body:{getReader:()=>reader}};
      }
      return originalFetch(url,options);
    };
    ui.win.document.body.appendChild=tag=>{
      if(stage==='script'&&once&&tag.src.includes('workshop')) {
        once=false;entered=true;held=tag;oldLoad=tag.onload;oldError=tag.onerror;
        return ui.win.Node.prototype.appendChild.call(ui.win.document.body,tag);
      }
      return originalAppend(tag);
    };
    const controller=new ui.win.AbortController();
    const first=ui.win.ARCHHUB_LOAD_WORKSHOP({signal:controller.signal});
    const outcome=first.then(()=> 'loaded',()=> 'cancelled');
    for(let turn=0;turn<100&&!entered;turn++) await new Promise(resolve=>setTimeout(resolve,2));
    assert.equal(entered,true,'the real loader entered the pending '+stage);
    controller.abort(new Error('Workshop did not answer. Retry opening it.'));
    ui.context.fetch=originalFetch;ui.win.document.body.appendChild=originalAppend;
    const retry=ui.win.ARCHHUB_LOAD_WORKSHOP({signal:new ui.win.AbortController().signal});
    assert.notEqual(retry,first,'immediate retry replaces the cancelled cached attempt');
    assert.equal(await Promise.race([outcome,new Promise(resolve=>setTimeout(()=>resolve('pending'),80))]),'cancelled');
    if(stage==='body') assert.equal(readerReleased,1,'cancelled response releases its reader');
    if(held) assert.equal(held.isConnected,false,'cancelled pending script is detached');
    assert.equal(await retry,ui.win.WorkshopView);
    oldLoad?.();oldError?.();
    await Promise.resolve();
    assert.equal(ui.win.ARCHHUB_LOAD_WORKSHOP(),retry,'late old callbacks cannot discard the successful retry');
  } finally {ui.close();}
});
test('MAINFIX pre-cancelled Workshop does not fetch or append lazy assets',{timeout:5000},async()=>{
  const ui=await loaderFixture();
  try {
    const controller=new ui.win.AbortController();controller.abort(new Error('Opening was cancelled'));
    await assert.rejects(ui.win.ARCHHUB_LOAD_WORKSHOP({signal:controller.signal}),/cancelled/);
    assert.equal(ui.fetches.filter(name=>name.includes('workshop')).length,0);
    assert.equal(ui.scripts.filter(tag=>tag.src.includes('workshop')).length,0);
  } finally {ui.close();}
});
test('MAINFIX Workshop timeout cancels its request and its visible Retry opens the real face',async()=>{
  const ui=await mounted();
  try {
    const load=ui.w.ARCHHUB_LOAD_WORKSHOP,signals=[];
    ui.w.ARCHHUB_LOAD_WORKSHOP=options=>{
      signals.push(options?.signal);
      if(signals.length>2) return load();
      return new Promise((resolve,reject)=>options?.signal?.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    };
    await ui.rail('Workshop');
    await new Promise(resolve=>ui.w.setTimeout(resolve,2000));await ui.settle();
    assert.equal(signals[0]?.aborted,true);
    const retry=[...ui.doc.querySelectorAll('button')].find(button=>/retry/i.test(button.textContent));
    assert.ok(retry,ui.doc.body.textContent);
    assert.match(ui.doc.body.textContent,/Workshop did not answer/);
    ui.flush(()=>retry.click());await ui.settle();
    assert.equal(signals.length,2);assert.notEqual(signals[0],signals[1]);
    await new Promise(resolve=>ui.w.setTimeout(resolve,2000));await ui.settle();
    assert.equal(signals[1]?.aborted,true,'a second timeout cancels its own retry');
    const retryAgain=[...ui.doc.querySelectorAll('button')].find(button=>/retry/i.test(button.textContent));
    assert.ok(retryAgain,ui.doc.body.textContent);
    ui.flush(()=>retryAgain.click());await ui.settle();
    assert.equal(signals.length,3);assert.notEqual(signals[1],signals[2]);
    assert.ok(ui.doc.querySelector('[data-workshop72]'),ui.doc.body.textContent);
  } finally {ui.close();}
});
test('MAINFIX leaving a pending Workshop cancels only that opening attempt',async()=>{
  const ui=await mounted();
  try {
    let signal;
    ui.w.ARCHHUB_LOAD_WORKSHOP=options=>{
      signal=options?.signal;
      return new Promise((resolve,reject)=>signal?.addEventListener('abort',()=>reject(signal.reason),{once:true}));
    };
    await ui.rail('Workshop');await ui.rail('Canvas');
    assert.equal(signal?.aborted,true);
    assert.equal(ui.doc.querySelector('[data-workshop-loading]'),null);
    assert.ok(ui.doc.querySelector('input[aria-label="Ask selection"],textarea,input[placeholder^="Reply"]'));
  } finally {ui.close();}
});
test('MAINFIX selection composer remains visible in Properties and follows the selected node',async()=>{
  const ui=await mounted();
  try {await ui.rail('Canvas');ui.select('think-a');await ui.settle();
    assert.ok(ui.doc.querySelector('input[aria-label="Ask selection"]'),'1030 single-line composer remains in Properties');
    assert.match(ui.doc.querySelector('[title^="Choose agent for "]').textContent,/Think A/);
    ui.select(null);await ui.settle();
    assert.doesNotMatch(ui.doc.querySelector('[title^="Choose agent for "]').textContent,/Think A/);
  } finally {ui.close();}
});
test('MAINFIX existing Providers and standing instruction are reachable through Settings groups',async()=>{
  const ui=await mounted();
  try {await ui.rail('Settings');
    const nav=settingsNavigator({doc:ui.doc,flush:ui.flush,settle:ui.settle});
    const providers=await nav.tab('Providers');
    assert.match(providers.textContent,/NVIDIA/i);
    const profile=await nav.tab('Profile');
    assert.match(profile.textContent,/standing instruction/i);
    const edit=[...profile.querySelectorAll('button')].find(button=>/edit raw prompt/i.test(button.textContent));
    assert.ok(edit);
    const saved=[];
    ui.w.prompt=()=> 'MAINFIX instruction';
    ui.w.ARCHHUB_REMEMBER=async value=>{saved.push(value);};
    ui.flush(()=>edit.click());await ui.settle();
    assert.deepEqual(saved,['SYSTEM PROMPT: MAINFIX instruction']);
    assert.match(edit.textContent,/saved to the brain/i);
  } finally {ui.close();}
});
test('MAINFIX selected-node send replies and never opens the model picker',async()=>{
  const ui=await mounted(),calls=[];
  ui.w.ARCHHUB_AGENT=async(...args)=>{calls.push(args);return {answer:'MAINFIX node reply'};};
  try {
    await ui.rail('Canvas');ui.select('think-a');await ui.settle();
    const input=ui.doc.querySelector('input[aria-label="Ask selection"]');
    ui.type(input,'reply to this node');
    ui.flush(()=>input.dispatchEvent(new ui.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    await ui.settle();
    assert.equal(calls.length,1);assert.equal(calls[0][2].node,'think-a');
    assert.equal(calls[0][1],'openrouter/free');
    assert.match(ui.doc.body.textContent,/MAINFIX node reply/);
    assert.equal(ui.doc.querySelector('[role="dialog"][aria-label="Choose a model"]'),null);
    ui.flush(()=>input.closest('[data-ds-composer]').querySelector('[data-model-indicator]').click());
    await ui.settle();
    assert.ok(ui.doc.querySelector('[role="dialog"][aria-label="Choose a model"]'));
  } finally {ui.close();}
});
test('MAINFIX absent node-send handler leaves a visible error and retains the draft',async()=>{
  const ui=await mounted();
  try {
    await ui.rail('Canvas');ui.select('think-a');await ui.settle();
    const input=ui.doc.querySelector('input[aria-label="Ask selection"]');
    ui.type(input,'keep this request');
    ui.flush(()=>input.dispatchEvent(new ui.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    await ui.settle();
    assert.equal(input.value,'keep this request');
    assert.match(ui.doc.body.textContent,/Sending is unavailable/);
    const visibleStatus=input.closest('[data-ds-composer]').querySelector('[data-chat-turn=error]');
    assert.match(visibleStatus.textContent,/Sending is unavailable/,'the verifier reads the actual composer error owner');
    assert.equal(ui.doc.querySelector('[role="dialog"][aria-label="Choose a model"]'),null);
  } finally {ui.close();}
});
test('MAINFIX Chats, Library and leaving Workshop retain a reply composer', async()=>{
  const ui=await mounted();
  try {for(const name of ['Chats','Library','Workshop','Canvas']){
    await ui.rail(name);
    assert.ok(ui.doc.querySelector('input[aria-label="Ask selection"],textarea,input[placeholder^="Reply"]'),name+' must have a composer');
  }} finally {ui.close();}
});
