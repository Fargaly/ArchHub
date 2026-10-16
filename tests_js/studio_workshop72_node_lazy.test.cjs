const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('./studio_ds_context.cjs');
const {createHash, webcrypto} = require('node:crypto');
const {mountWorkshopNode, read, slice} = require('./workshop72_node_helpers.cjs');
function fixture({count=7, input='elements', output='labels'} = {}) {
  const node = {id:'room-real',cat:'workshop',title:'Label selected elements',x:40,y:70,
    members:[{id:'agent-real-a',title:'Assigned agent'},{id:'agent-real-b',title:'Review agent'}],
    ins:[{id:'elements-in',label:input,t:'object',multiple:true,connectable:true}],
    outs:[{id:'labels-out',label:output,t:'text',multiple:true,connectable:true}]};
  const authorization={subject:'human-real',session:'view-real'};
  const state = {canvas:{graph_id:'graph-real',root:'scope-real',authorization},workshops:[{root:node.id,label:node.title}],
    workshop:{root:node.id,ok:true,self:'human-real',participants:[
      {root:'agent-real-a',label:'Assigned agent',is_agent:true,attached:true,connected:true},
      {root:'agent-real-b',label:'Review agent',is_agent:true,attached:true,connected:true}],messages:[]},
    nativeWork:{root:node.id,scope:'scope-real',owner:'human-real',view:'view-real',work:'work-real',state:'awaiting_approval',approved:false,
      result_count:count,output_label:output,input_digest:'b'.repeat(64)},
    topology:{canvas:{application_root:'graph-real',scope:{current:'scope-real'},authorization},graph:{nodes:[node,{id:'work-real',engine:'work',title:node.title,status:'awaiting_approval'},
      {id:'agent-real-a',title:'Assigned agent',group:node.id},{id:'agent-real-b',title:'Review agent',group:node.id}],wires:[]}}};
  return {node,state};
}
test('WORKSHOP-72 mounted node uses the plate header, width, tile stack and real status/count', async () => {
  const fx=fixture();
  fx.state.workshop.participants[0]={...fx.state.workshop.participants[0],label:'Claude Code',runtime:'claude'};
  fx.state.workshop.participants[1]={...fx.state.workshop.participants[1],label:'Codex',runtime:'codex'};
  fx.state.workshop.assignments=[{work:'work-real',agent_session:'agent-real-a'}];
  fx.state.workshop.workflows=[{root:'flow-real',title:'Label plan',approval:{current:true},nodes:[]}];
  fx.state.workshop.reviews=[{workflow:'flow-real',judged_by:'agent-real-b'}];
  fx.state.workshop.participants.push({root:'agent-real-c',label:'Unassigned agent',is_agent:true,attached:true,connected:true});
  const ui = await mountWorkshopNode(fx);
  try {
    const appStyle=ui.doc.createElement('style');appStyle.textContent='* {box-sizing:border-box;}';ui.doc.head.append(appStyle);ui.container.style.lineHeight='1.5';
    const face=ui.doc.querySelector('[data-workshop-node-face]');
    assert.equal(ui.win.getComputedStyle(face).lineHeight,'normal');
    assert.equal(ui.win.getComputedStyle(ui.container.firstElementChild).width,'320px');
    assert.equal(ui.win.getComputedStyle(face).borderRadius,'10px');
    assert.equal(face.getAttribute('data-workshop-id'),'room-real');
    assert.equal(ui.doc.querySelector('[data-workshop-node-title]').textContent,'Label selected elements');
    assert.equal(ui.doc.querySelectorAll('[data-workshop-node-member]').length,2);
    assert.deepEqual([...ui.doc.querySelectorAll('[data-workshop-node-member]')].map(tile=>tile.dataset.workshopParticipantRoot),
      ['agent-real-a','agent-real-b'],'only actual assigned agent and actual reviewer form the task stack');
    assert.deepEqual([...ui.doc.querySelectorAll('[data-workshop-node-member]')].map(tile=>tile.textContent),
      ['C','X'],'shared agent initials reproduce the window and plate');
    assert.equal(ui.doc.querySelector('[data-workshop-node-status]').textContent,'Waits for you · 7 labels');
    assert.equal(ui.doc.querySelectorAll('textarea,input,select').length,0);
    assert.equal(ui.doc.querySelectorAll('button:not([data-socket-port])').length,1);
    const review=ui.doc.querySelector('[data-workshop-node-review]');
    assert.equal(ui.win.getComputedStyle(review).height,'26px');
    assert.equal(ui.win.getComputedStyle(review).fontSize,'13px');
    assert.equal(ui.calls.length,0,'rendering the canvas neither fetches agents nor opens/sends a conversation');
  } finally {await ui.close();}
});
test('WORKSHOP-72 typed node ports are the actual graph interfaces and call the existing socket route', async () => {
  const ui=await mountWorkshopNode(fixture({input:'surfaces',output:'reports'}));
  try {
    const ports=[...ui.doc.querySelectorAll('[data-socket-port]')];
    assert.deepEqual(ports.map(el=>[el.dataset.socketPort,el.dataset.socketLabel,el.dataset.socketType]),
      [['elements-in','surfaces','object'],['labels-out','reports','text']]);
    assert.deepEqual(ports.map(el=>el.dataset.socketShape),['diamond','diamond']);
    await ui.click(ports[0]);
    assert.equal(ui.calls[0][0],'socket');assert.equal(ui.calls[0][1].id,'elements-in');assert.equal(ui.calls[0][2],'in');
    assert.equal(ui.doc.querySelector('[data-workshop-node-status]').textContent,'Waits for you · 7 reports');
  } finally {await ui.close();}
});
test('WORKSHOP-72 Review reaches the same window identity at its approval; double-click opens that window', async () => {
  const ui=await mountWorkshopNode(fixture());
  try {
    await ui.click(ui.doc.querySelector('[data-workshop-node-review]'));
    assert.deepEqual(JSON.parse(JSON.stringify(ui.navigation)),[{root:'room-real',work:'work-real'}]);
    await ui.mouse(ui.doc.querySelector('[data-workshop-node-face]'),'dblclick',60,90);
    assert.equal(ui.navigation[1],'room-real');
    assert.equal(ui.calls.length,0,'opening is navigation; the mounted window owns the single transport read');
  } finally {await ui.close();}
});
test('WORKSHOP-72 agent tile drag-out preserves agent identity and uses remove-member machinery exactly once', async () => {
  const ui=await mountWorkshopNode({...fixture(),screenToCanvasPoint:(x,y)=>({x:x/2,y:y/2})});
  try {
    ui.container.firstElementChild.getBoundingClientRect=()=>({left:20,right:340,top:20,bottom:170});
    const tile=ui.doc.querySelector('[data-workshop-node-member]');
    await ui.mouse(tile,'mousedown',40,40);
    await ui.mouse(ui.doc,'mousemove',400,200);
    await ui.mouse(ui.doc,'mouseup',400,200);
    await ui.mouse(ui.doc,'mouseup',400,200);
    assert.deepEqual(JSON.parse(JSON.stringify(ui.calls)),[['memberLeave','agent-real-a','room-real',{x:200,y:100}]]);
  } finally {await ui.close();}
});
test('WORKSHOP-72 node and window selector read one store and update from its real snapshot', async () => {
  const fx=fixture(),ui=await mountWorkshopNode(fx);
  try {
    const projection=ui.model();
    assert.equal(ui.doc.querySelector('[data-workshop-node-title]').textContent,projection.title);
    assert.equal(ui.doc.querySelector('[data-workshop-node-face]').dataset.workshopId,projection.id);
    assert.equal(ui.doc.querySelector('[data-workshop-node-face]').dataset.workshopApproval,projection.approval.work);
    fx.state.nativeWork={...fx.state.nativeWork,result_count:9};
    await ui.draw({state:fx.state});
    assert.equal(ui.doc.querySelector('[data-workshop-node-status]').textContent,'Waits for you · 9 labels');
    assert.equal(ui.model().count,9);
  } finally {await ui.close();}
});
test('WORKSHOP-72 unavailable authority never invents counts, participants, approval or a node composer', async () => {
  const fx=fixture();fx.state.workshop=null;fx.state.nativeWork=null;fx.state.topology.graph.nodes=[fx.node];
  const ui=await mountWorkshopNode(fx);
  try {
    assert.equal(ui.doc.querySelector('[data-workshop-node-status]').textContent,'Unavailable');
    assert.doesNotMatch(ui.doc.querySelector('[data-workshop-node-face]').textContent,/Not available yet/);
    assert.equal(ui.doc.querySelectorAll('[data-workshop-node-member],[data-workshop-node-review],textarea').length,0);
    assert.doesNotMatch(ui.doc.querySelector('[data-workshop-node-face]').textContent,/\d+ (?:tags|labels)/);
  } finally {await ui.close();}
});
async function loaderFixture({stale=false}={}) {
  const loader=read('nodelang/studio/studio.html'),{JSDOM}=await import('jsdom');
  const dom=new JSDOM('<div id="studio-boot"></div>',{url:'http://127.0.0.1/'}),win=dom.window;
  Object.defineProperty(win,'crypto',{value:webcrypto});
  const names=vm.runInNewContext(loader.match(/const names = (\[[\s\S]+?\]);/)[1]);
  const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
  const sources=new Map(),scripts=[],fetches=[];
  const files=names.map(source=>{
    const bytes=Buffer.from('// '+source),hash=digest(bytes),compiled=Buffer.from('/* '+source+' */');sources.set(source,bytes);
    return {source,output:source.replace(/\//g,'-').replace(/\.jsx$/,'.js'),source_bytes:bytes.length,source_sha256:hash,
      bytes:compiled.length,sha256:digest(compiled),integrity:'sha256-'+createHash('sha256').update(compiled).digest('base64')};
  });
  if(stale)sources.set('studio-workshop.jsx',Buffer.from('// changed'));
  const manifest=Buffer.from(JSON.stringify({format:1,files}));
  const fetch=async url=>{
    const name=url.replace('/studio/','');fetches.push(name);
    const value=name==='compiled/manifest.json'?manifest:sources.get(name);let used=false;
    return {ok:!!value,body:value?{getReader:()=>({read:async()=>used?{done:true}:(used=true,{done:false,value:new Uint8Array(value)}),
      releaseLock(){},cancel:async()=>{}})}:null};
  };
  win.document.body.appendChild=tag=>{
    scripts.push({src:tag.src,integrity:tag.integrity});
    if(tag.src.includes('/studio-workshop.js?'))win.WorkshopView=()=>null;
    tag.onload();return tag;
  };
  const context=vm.createContext({window:win,document:win.document,crypto:webcrypto,fetch,TextDecoder,Uint8Array,
    btoa:value=>Buffer.from(value,'binary').toString('base64'),boot:win.document.getElementById('studio-boot'),studioMount:undefined});
  vm.runInContext(slice(loader,'function mountStudio()','\n  try {')+'\nglobalThis.mount=mountStudio;',context);
  await context.mount();
  return {win,fetches,scripts,close:()=>win.close()};
}
test('WORKSHOP-72 actual loader fetches no Workshop face or agent scripts at app startup',async()=>{
  const ui=await loaderFixture();try{
    assert.ok(ui.fetches.includes('studio-lm.jsx'));
    assert.equal(ui.fetches.some(name=>/workshop-(?:board|workshop)|studio-workshop/.test(name)),false);
    assert.equal(ui.scripts.some(tag=>/workshop/.test(tag.src)),false);
  }finally{ui.close();}
});
test('WORKSHOP-72 first open loads and integrity-checks lazy scripts once and retains loader promise',async()=>{
  const ui=await loaderFixture();try{
    const first=ui.win.ARCHHUB_LOAD_WORKSHOP(),second=ui.win.ARCHHUB_LOAD_WORKSHOP();
    assert.equal(first,second);assert.equal(await first,ui.win.WorkshopView);
    assert.deepEqual(ui.fetches.filter(name=>name.includes('workshop')),['workshop-board.jsx','studio-workshop.jsx']);
    const tags=ui.scripts.filter(tag=>tag.src.includes('workshop'));
    assert.equal(tags.length,2);assert.ok(tags.every(tag=>/^sha256-/.test(tag.integrity)));
    await ui.win.ARCHHUB_LOAD_WORKSHOP();assert.equal(ui.scripts.filter(tag=>tag.src.includes('workshop')).length,2);
  }finally{ui.close();}
});
test('WORKSHOP-72 stale lazy source is refused before its compiled script or window can run',async()=>{
  const ui=await loaderFixture({stale:true});try{
    await assert.rejects(ui.win.ARCHHUB_LOAD_WORKSHOP(),/Studio build is stale: studio-workshop\.jsx/);
    assert.equal(ui.scripts.filter(tag=>tag.src.includes('/studio-workshop.js')).length,0);
    assert.equal(ui.win.WorkshopView,undefined);
  }finally{ui.close();}
});
test('WORKSHOP-72 actual app Frame and Workspace remove duplicate rails, tabs, inspector and composer chrome',async()=>{
  const {JSDOM}=await import('jsdom'),dom=new JSDOM('<div id="root"></div>',{url:'http://127.0.0.1/'});
  const win=dom.window,oldWindow=global.window,oldDocument=global.document;
  global.window=win;global.document=win.document;global.IS_REACT_ACT_ENVIRONMENT=true;
  const React=require('react'),{createRoot}=require('react-dom/client'),{transformSync}=require('esbuild');
  const fx=fixture();fx.state.canvas.graph_id='graph-real';fx.state.topology.graph.wires=[];
  const context=vm.createContext({React,window:win,document:win.document,console,
    useWorkshopProjection:()=>fx.state,useStudioProjection:()=>({graph:fx.state.topology.graph}),workshopWaitingItems:()=>[],
    studioCanvasScope:()=>'',WORKSHOP_UNAVAILABLE_ROOT:'studio:workshop-unavailable',LM_SESSIONS:[],LM_GRAPH:{nodes:[],wires:[]}});
  vm.runInContext(read('nodelang/studio/tokens.jsx'),context);context.LM=win.AH;
  vm.runInContext(transformSync(read('nodelang/studio/shared-data.jsx'),{loader:'jsx'}).code,context);
  win.WorkshopView=()=>React.createElement('section',{'data-actual-workshop-window':''},'Workshop');
  const source=read('nodelang/studio/studio-lm.jsx');
  vm.runInContext(transformSync(slice(source,'const Frame =','const isHistoryNode =')+
    slice(source,'const useNodeLibrary =','// ─── Library panel')+slice(source,'const useDeferredCanvas =','const modelRoute =')+'\nglobalThis.Frame=Frame;globalThis.Workspace=Workspace;',{loader:'jsx'}).code,context);
  const root=createRoot(win.document.getElementById('root'));
  try{
    await React.act(async()=>root.render(React.createElement(context.Frame,{workshopWindow:true},
      React.createElement(context.Workspace,{session:{id:'graph-real'},view:{mode:'chat',conversationRoot:'room-real'},updateView:()=>{}}))));
    const workspace=win.document.querySelector('[data-workspace-main]');
    assert.equal(workspace.style.gridTemplateColumns,'minmax(0, 1fr)');assert.equal(workspace.style.gridTemplateRows,'1fr');
    assert.equal(win.document.querySelectorAll('[data-app-frame],[data-actual-workshop-window]').length,2);
    assert.equal(win.document.querySelectorAll('[data-workspace-frame] nav,[data-workspace-frame] footer,[data-workspace-frame] button,textarea,[role="tablist"],[data-left-panel]').length,0);
    assert.equal(win.document.querySelectorAll('[data-app-rail]').length,1);
    assert.equal(win.document.querySelectorAll('[data-app-status]').length,1);
  }finally{
    await React.act(async()=>root.unmount());win.close();global.window=oldWindow;global.document=oldDocument;delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});
test('WORKSHOP-72 no-graph Workshop tool opens the same lazy window with an honest unavailable descriptor',async()=>{
  const {JSDOM}=await import('jsdom'),dom=new JSDOM('<div id="root"></div>');const win=dom.window;
  const oldWindow=global.window,oldDocument=global.document;global.window=win;global.document=win.document;
  global.IS_REACT_ACT_ENVIRONMENT=true;
  const React=require('react'),{createRoot}=require('react-dom/client'),{transformSync}=require('esbuild');
  const state={workshops:[]},context=vm.createContext({React,window:win,document:win.document,console,
    useWorkshopProjection:()=>state,usePersonalTheme:()=>null,useToolHubProjection:()=>null,
    toolRowsFromOwners:()=>[],firstToolTab:()=>'',WORKSHOP_UNAVAILABLE_ROOT:'studio:workshop-unavailable'});
  vm.runInContext(read('nodelang/studio/tokens.jsx'),context);context.LM=win.AH;
  vm.runInContext(transformSync(read('nodelang/studio/shared-data.jsx'),{loader:'jsx'}).code,context);
  let received;win.WorkshopView=props=>{received=props;return React.createElement('div',{'data-unavailable-workshop':''},'Not available yet');};
  const source=read('nodelang/studio/studio-lm.jsx');
  vm.runInContext(transformSync(slice(source,'const LazyWorkshopWindow =','const Workspace =')+
    slice(source,'const ToolMainView =','// ──────────────────────── WORKSPACE')+'\nglobalThis.ToolMainView=ToolMainView;',{loader:'jsx'}).code,context);
  const root=createRoot(win.document.getElementById('root'));
  try{
    await React.act(async()=>root.render(React.createElement(context.ToolMainView,{view:{id:'workshop'}})));
    assert.equal(received.state,state);assert.equal(received.descriptor.unavailable,true);
    assert.equal(received.descriptor.native_work_available,false);assert.equal(win.document.querySelectorAll('h1,[data-tool-tab]').length,0);
    assert.equal(win.document.querySelector('[data-unavailable-workshop]').textContent,'Not available yet');
  }finally{await React.act(async()=>root.unmount());win.close();global.window=oldWindow;global.document=oldDocument;delete global.IS_REACT_ACT_ENVIRONMENT;}
});
test('WORKSHOP-72 wire endpoints and group bounds use the actual 320px Workshop card width',()=>{
  const source=read('nodelang/studio/studio-lm.jsx');
  const box=slice(source,'const canvasNodeBox =','const isSessionNodeShape =');
  const context=vm.createContext({isWorkshopGraphNode:n=>n.cat==='workshop'});
  vm.runInContext(box+'\nglobalThis.box=canvasNodeBox;',context);
  const node=fixture().node;
  assert.equal(context.box(node,{}).w,320);
  const sourceLine=source.match(/const sourceWidth = ([\s\S]*?);/)[1];
  const width=vm.runInNewContext(sourceLine,{fromNode:node,isWorkshopGraphNode:n=>n.cat==='workshop',expanded:{},
    NODE_CARD_W:224,nodeIsWatch:()=>false});
  assert.equal(width,320,'output wire begins at the face right edge rather than the generic card width');
});
test('WORKSHOP-72 mere transcript participation cannot fabricate a draggable graph membership',async()=>{
  const fx=fixture();fx.node.members=[];
  fx.state.topology.graph.nodes=fx.state.topology.graph.nodes.filter(row=>!row.id.startsWith('agent-real-'));
  const ui=await mountWorkshopNode(fx);
  try{
    const tile=ui.doc.querySelector('[data-workshop-node-member]');
    assert.equal(tile.dataset.workshopMemberDraggable,'false');assert.equal(ui.model().members[0].graph_member_id,null);
    await ui.mouse(tile,'mousedown',40,40);await ui.mouse(ui.doc,'mousemove',500,200);await ui.mouse(ui.doc,'mouseup',500,200);
    assert.equal(ui.calls.length,0,'participation is not a membership mutation grant');
  }finally{await ui.close();}
});
test('WORKSHOP-72 explicit session/account alias drags the admitted graph member, preserves raw route root and uses actual group root',async()=>{
  const fx=fixture();fx.node.id='workbench-real';fx.node.members=[{id:'account-agent-real',title:'Assigned agent'}];
  fx.state.workshops[0].node_root='workbench-real';
  fx.state.workshop.participants=[{root:'runtime-session-real',app_root:'account-agent-real',label:'Assigned agent',is_agent:true,attached:true,connected:true}];
  fx.state.topology.graph.nodes=[fx.node,{id:'work-real',engine:'work',title:fx.node.title},
    {id:'account-agent-real',title:'Assigned agent',group:'workbench-real'}];
  const ui=await mountWorkshopNode(fx);
  try{
    ui.container.firstElementChild.getBoundingClientRect=()=>({left:20,right:340,top:20,bottom:170});
    const tile=ui.doc.querySelector('[data-workshop-node-member]');
    assert.equal(tile.dataset.workshopNodeMember,'account-agent-real');
    assert.equal(tile.dataset.workshopParticipantRoot,'runtime-session-real');
    assert.equal(ui.doc.querySelector('[data-workshop-node-face]').dataset.workshopId,'room-real');
    assert.equal(ui.model().members[0].id,'runtime-session-real','composer route identity is untouched');
    await ui.mouse(tile,'mousedown',40,40);await ui.mouse(ui.doc,'mousemove',500,200);await ui.mouse(ui.doc,'mouseup',500,200);
    assert.deepEqual(JSON.parse(JSON.stringify(ui.calls)),[['memberLeave','account-agent-real','workbench-real',{x:500,y:200}]]);
    await ui.click(ui.doc.querySelector('[data-workshop-node-review]'));
    assert.deepEqual(JSON.parse(JSON.stringify(ui.navigation)),[{root:'room-real',work:'work-real'}]);
  }finally{await ui.close();}
});
test('WORKSHOP-72 a connection without the existing moveMember capability keeps admitted agent drag disabled',async()=>{
  const ui=await mountWorkshopNode(fixture());
  try{
    delete ui.win.ARCHHUB_EXISTING_WORKSHOP.moveMember;await ui.draw();
    const tile=ui.doc.querySelector('[data-workshop-node-member]');
    assert.equal(tile.dataset.workshopMemberDraggable,'false');assert.match(tile.title,/Unavailable/);
    assert.doesNotMatch(tile.title,/Not available yet/);
    await ui.mouse(tile,'mousedown',40,40);await ui.mouse(ui.doc,'mousemove',500,200);await ui.mouse(ui.doc,'mouseup',500,200);
    assert.equal(ui.calls.length,0);
  }finally{await ui.close();}
});
test('WORKSHOP-72 conflicting group evidence cannot drag an agent from another group',async()=>{
  const fx=fixture();fx.state.topology.graph.nodes.find(row=>row.id==='agent-real-a').group='other-real-group';
  const ui=await mountWorkshopNode(fx);
  try{
    const tile=ui.doc.querySelector('[data-workshop-node-member="agent-real-a"]');
    assert.equal(tile.dataset.workshopMemberDraggable,'false');
    await ui.mouse(tile,'mousedown',40,40);await ui.mouse(ui.doc,'mousemove',500,200);await ui.mouse(ui.doc,'mouseup',500,200);
    assert.equal(ui.calls.length,0);
  }finally{await ui.close();}
});
test('WORKSHOP-72 an admitted uncategorized workbench renders the real face through descriptor node_root, without title inference',async()=>{
  const fx=fixture();fx.node.id='workbench-real';fx.node.cat='logic';fx.node.title='General workbench';
  fx.state.workshops[0].node_root=fx.node.id;
  fx.state.topology.graph.nodes.filter(row=>row.id.startsWith('agent-real-')).forEach(row=>row.group=fx.node.id);
  const ui=await mountWorkshopNode(fx);
  try{
    assert.ok(ui.doc.querySelector('[data-workshop-node-face]'));
    assert.equal(ui.doc.querySelector('[data-workshop-node-face]').dataset.workshopId,'room-real');
    assert.equal(ui.win.getComputedStyle(ui.container.firstElementChild).width,'320px');
    await ui.mouse(ui.doc.querySelector('[data-workshop-node-face]'),'dblclick',60,90);
    assert.equal(ui.navigation[0],'room-real');
    fx.state.workshops=[];fx.node.title='Workshop';fx.node.has_conversation=true;
    await ui.draw({state:fx.state,node:{...fx.node}});
    assert.equal(ui.doc.querySelector('[data-workshop-node-face]'),null,'the title alone cannot assign a Workshop role');
  }finally{await ui.close();}
});
