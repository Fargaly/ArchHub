const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {transformSync} = require('esbuild');
const createRoot = el => require('react-dom/client').createRoot(el);
const React = require('react');
const {fixture} = require('./workshop72_fixture.cjs');
const {mounted, read, text} = require('./workshop72_regression_helpers.cjs');
const {mountWorkshopNode} = require('./workshop72_node_helpers.cjs');
const source = read('01.APP/nodelang/studio/studio-lm.jsx');
const slice = (a,b) => source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const banned = /Not available yet|not read|Unversioned build|127\.0\.0\.1|%TEMP%|AppData[\\/]|accent_dim|l_bg|members: \d+ · status: available/i;

test('SCREENS1 Workshop uses DS composer, empty state and live changing task rows',async()=>{
  const f=fixture(),ui=await mounted(f.state,f.authority);
  try {
    assert.ok(ui.doc.querySelector('[data-ds-composer][data-workshop72-composer]'));
    f.state.workshop.workflows[0].title='Store revision changed the task';
    await ui.render();
    assert.match(text(ui.doc.querySelector('[data-workshop72-list]')),/Store revision changed the task/);
    assert.doesNotMatch(text(ui.doc.body),banned);
    f.state.workshop.messages=[];f.state.workshop.workflows=[];f.state.nativeWork=null;
    await ui.render();
    assert.equal(ui.doc.querySelectorAll('textarea').length,1);
    assert.match(text(ui.doc.querySelector('[data-workshop-empty][role=status]')),/What should the agents do\?/);
    assert.equal(ui.doc.querySelectorAll('[data-workshop-task-row]').length,0);
    assert.doesNotMatch(text(ui.doc.body),banned);
  } finally {await ui.close();}
});

test('SCREENS1 selected workflow keeps its explicitly scoped founder prompt and excludes foreign work',async()=>{
  const f=require('./workshop77_plate_fixture.cjs').plateFixture();
  f.state.workshop.messages.push({root:'foreign',sender_root:'owner-a',work_root:'work:mail0001',body:'Foreign task prompt'});
  const authority={getSnapshot:()=>f.state,subscribe:()=>()=>{}};
  const ui=await mounted(f.state,authority,{sel:{task:f.work}});
  try {
    assert.match(text(ui.doc.querySelector('[data-user-bubble]')),/Tag the untagged doors on Level 3/);
    assert.doesNotMatch(text(ui.doc.querySelector('[data-workshop72-thread]')),/Foreign task prompt/);
  } finally {await ui.close();}
});

test('SCREENS1 board has exactly the five F29 column labels and reads changed store tasks',async()=>{
  const f=fixture(),ui=await mounted(f.state,f.authority);
  const host=ui.doc.createElement('div');ui.doc.body.append(host);const root=createRoot(host);
  try {
    const tasks=[{work:'work:test',title:'Store supplied board task',boardLane:'planned'}];
    const paint=()=>ui.act(()=>root.render(React.createElement(ui.win.WorkshopBoardView,{tasks,agents:[]})));
    await paint();
    assert.deepEqual([...host.querySelectorAll('[data-workshop-lane] h3')].map(text),['PLANNED','WIP','IN REVIEW','DONE','ARCHIVED']);
    assert.match(text(host),/Store supplied board task/);
    tasks[0].title='Store changed board task';await paint();assert.match(text(host),/Store changed board task/);
    tasks.splice(0);await paint();assert.equal(host.querySelectorAll('[data-workshop-board-card]').length,0);
  } finally {await ui.act(()=>root.unmount());await ui.close();}
});

test('SCREENS1 canvas Workshop face uses shared Card with the same live identity and no eager reads',async()=>{
  const f=fixture(),ui=await mountWorkshopNode({state:f.state,node:f.node});
  try {assert.ok(ui.doc.querySelector('[data-ds-card][data-workshop-node-face]'));assert.equal(ui.calls.length,0);assert.doesNotMatch(text(ui.doc.body),banned);}
  finally {await ui.close();}
});

test('SCREENS1 Library canvas uses DS Node, real socket routes and changing graph data',async()=>{
  const f=fixture();
  const node={id:'stored-node',title:'Stored graph node',cat:'shape',x:20,y:70,params:[],
    ins:[{id:'actual-input',label:'Store input',t:'text',connectable:true}],outs:[]};
  const ui=await mountWorkshopNode({state:f.state,node,libraryMode:true});
  try {
    assert.ok(ui.doc.querySelector('[data-library-canvas-node]'));
    assert.match(text(ui.doc.body),/Stored graph node.*Store input/);
    assert.equal(ui.calls.length,0);
    const socket=ui.doc.querySelector('[role=button]');assert.equal(socket.getAttribute('aria-label'),'Connect input Store input');
    await ui.click(socket);
    await ui.act(()=>socket.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:'Enter',bubbles:true})));
    assert.equal(ui.calls.length,2,'same input socket route works from pointer and keyboard');
    assert.equal(ui.calls.at(-1)[1].id,'actual-input');assert.equal(ui.calls.at(-1)[2],'in');
    await ui.draw({node:{...node,title:'Changed graph title',ins:[]}});
    assert.match(text(ui.doc.body),/Changed graph title/);assert.doesNotMatch(text(ui.doc.body),/Store input/);
  } finally {await ui.close();}
});

test('SCREENS1 plate Properties retains numeric, wired and socket-only parameter guards',async()=>{
  const f=fixture(),ui=await mounted(f.state,f.authority),writes=[];
  const host=ui.doc.createElement('div');ui.doc.body.append(host);const root=createRoot(host);
  try {
    ui.win.ARCHHUB_SET_PROP=async(rel,value)=>{writes.push([rel,value]);return {ok:true};};
    ui.win.HTMLElement.prototype.setPointerCapture=()=>{};ui.win.HTMLElement.prototype.releasePointerCapture=()=>{};
    const ctx=vm.createContext({React,window:ui.win,document:ui.doc,console,setTimeout,clearTimeout,CustomEvent:ui.win.CustomEvent});
    for(const file of ['param-types.jsx','studio-params.jsx'])vm.runInContext(transformSync(read('01.APP/nodelang/studio/'+file),{loader:'jsx'}).code,ctx);
    const node={id:'guard-node',live:true,params:[{k:'threshold',label:'Threshold',type:'number',v:3,rel:'threshold-value'},
      {k:'geometry',label:'Geometry',type:'elements',v:null,rel:'geometry-value'}, {k:'advanced_only',label:'Advanced value',type:'text',v:'stored',page:'Advanced',rel:'advanced-value'}]};
    await ui.act(()=>root.render(React.createElement(ui.win.NodeInspector,{node,plate:true})));
    const numeric=host.querySelector('[data-param-key=threshold] [title^="Drag to scrub"]');assert.ok(numeric);
    await ui.act(()=>{numeric.dispatchEvent(new ui.win.Event('pointerdown',{bubbles:true}));numeric.dispatchEvent(new ui.win.Event('pointerup',{bubbles:true}));});
    const input=host.querySelector('[data-param-key=threshold] input');assert.ok(input);
    await ui.act(()=>{Object.getOwnPropertyDescriptor(ui.win.HTMLInputElement.prototype,'value').set.call(input,'17.5');input.dispatchEvent(new ui.win.Event('input',{bubbles:true}));});
    await ui.act(()=>input.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:'Enter',bubbles:true})));
    await ui.act(()=>new Promise(resolve=>setTimeout(resolve,0)));
    const typed=vm.runInContext("PM_EDITS.get('guard-node').vals.threshold",ctx);assert.equal(typed,17.5);assert.equal(typeof typed,'number');
    assert.equal(writes.at(-1)[1],'17.5','scalar-cell save route retains its existing string contract');
    assert.equal(host.querySelectorAll('[data-param-key=geometry] input, [data-param-key=geometry] textarea').length,0,'socket-only values cannot accept literals');
    const threshold=host.querySelector('[data-param-key=threshold]');
    await ui.click(threshold.querySelector('button[title="Row actions"]'));
    const expose=[...threshold.querySelectorAll('button')].find(b=>text(b)==='⇄ expose');assert.ok(expose);await ui.click(expose);
    assert.match(text(host.querySelector('[data-param-key=threshold]')),/graph input/);
    assert.equal(host.querySelectorAll('[data-param-key=threshold] input').length,0,'wired numbers stay read-only');
    await ui.click([...host.querySelectorAll('[aria-label="Parameter pages"] button')].find(b=>text(b)==='Advanced'));
    assert.ok(host.querySelector('[data-param-key=advanced_only] input'),'saved parameter pages remain reachable');
  } finally {await ui.act(()=>root.unmount());await ui.close();}
});

test('SCREENS1 one Library renderer owns panel and overlay; live catalogue refresh, add and empty work',async()=>{
  const f=fixture(),ui=await mounted(f.state,f.authority);
  const host=ui.doc.createElement('div');ui.doc.body.append(host);const root=createRoot(host),added=[];
  let projected={library:[]};
  try {
    const win=ui.win;win.AH_LIBRARY=[{cat:'shape',items:[{id:'one',title:'Store Filter',sub:'Store description',engine:'live.filter',ports:{source:[],target:[]}}]}];
    const context=vm.createContext({React,window:win,document:ui.doc,LM:win.AH,setTimeout,clearTimeout,
      studioCategory:()=>({label:'SHAPE',icon:'⧩',col:win.AH.warn}),useStudioProjection:()=>projected,
      useWorkshopProjection:()=>f.state,useToolHubProjection:()=>({waiting:[]}),workshopWaitingItems:()=>[]});
    const code=slice('const visibleLibraryGroups =','const withHistoryLibrary =')+
      slice('const useNodeLibrary =','// ─── Skills panel')+
      slice('const NodeLibrary = ({ onClose, addNodeFromLibrary','// ──────────────────────── NODE RAIL')+
      '\nglobalThis.Panel=NodesPanel;globalThis.Dialog=NodeLibrary;';
    vm.runInContext(transformSync(code,{loader:'jsx'}).code,context);
    const paint=(dialog=false)=>ui.act(()=>root.render(React.createElement(dialog?context.Dialog:context.Panel,{addNodeFromLibrary:item=>added.push(item),onClose:()=>added.push('closed')})));
    await paint();assert.equal(host.querySelector('[placeholder^="Search "]').placeholder,'Search 1 nodes');
    assert.equal(host.querySelector('[data-library-panel]')?.dataset.libraryPanel,'');
    assert.equal(host.querySelector('[data-panel-home]'),null);assert.doesNotMatch(text(host),/^Nodes/);
    assert.match(text(host),/Store Filter/);await ui.click(host.querySelector('[data-library-row]'));assert.equal(added[0].id,'one');
    win.AH_LIBRARY=[{cat:'shape',items:[{id:'two',title:'Changed catalogue',engine:'live.changed'}]}];await paint();
    assert.match(text(host),/Changed catalogue/);assert.doesNotMatch(text(host),/Store Filter/);
    await paint(true);assert.equal(host.querySelectorAll('[data-library-panel]').length,1);
    await ui.click(host.querySelector('[data-library-row]'));assert.equal(added.at(-2).id,'two');assert.equal(added.at(-1),'closed');
    win.AH_LIBRARY=[];await paint();assert.equal(host.querySelectorAll('[data-library-row]').length,0);assert.match(text(host),/No nodes yet/);
    assert.doesNotMatch(text(host),banned);
    // Awaited inserts admit once, retain a refused dialog and fence a retired one.
    win.AH_LIBRARY=[{cat:'shape',items:[{id:'pending',title:'Pending insert',engine:'live.insert'}]}];
    let answer,creates=0,closes=0;
    const deferred=()=>new Promise(resolve=>{answer=resolve;creates++;});
    const drawPending=key=>ui.act(()=>root.render(React.createElement(context.Dialog,{key,onClose:()=>closes++,addNodeFromLibrary:deferred})));
    await drawPending('first');
    const row=host.querySelector('[data-library-row]');
    await ui.act(()=>{row.click();row.click();});
    assert.equal(creates,1);assert.equal(host.querySelector('[data-library-row]').disabled,true);
    await ui.act(()=>answer(false));assert.equal(closes,0);assert.match(text(host),/Node not added/);
    await ui.act(()=>host.querySelector('[data-library-row]').click());assert.equal(creates,2);
    await ui.act(()=>root.render(null));await ui.act(()=>answer(true));assert.equal(closes,0,'retired dialog cannot close its successor');
  } finally {await ui.act(()=>root.unmount());await ui.close();}
});
