'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const read=name=>fs.readFileSync(path.join(studio,name),'utf8');
async function adapter(tasks=[],library,hosts=()=>({hosts:[]}),overrides={}){
 const requests=[],timers=new Map();let nextTimer=0;
 const window={ARCHHUB_BOOT:{token:'fixture',csrf:'fixture'},structuredClone:globalThis.structuredClone,crypto:require('node:crypto').webcrypto,Uint8Array:globalThis.Uint8Array,addEventListener(){},dispatchEvent(){},setInterval:fn=>{timers.set(++nextTimer,fn);return nextTimer;},clearInterval:id=>timers.delete(id)};
 const canvas={revision:0,root:'graph',scope:{current:'graph'},nodes:[],wires:[],catalog:[],workshops:[{root:'room'}],interaction_projection:{bindings:[{control:'graph',acknowledgement_mode:'topology-delta-v1'},{control:'new-group',acknowledgement_mode:'topology-delta-v1'}]}};
 window.ArchHubStudioAuthority={create:({get,post})=>({load:()=>get('/api/universal/canvas'),composition:()=>Promise.resolve(canvas),open:root=>{canvas.root=root;canvas.scope.current=root;return post('/api/universal/interaction',{control:root,event_facts:[],projection_mode:'topology-delta-v1'});}})};
 const context={window,document:{hidden:true,addEventListener(){}},console,URLSearchParams,TextEncoder,AbortSignal,setTimeout,clearTimeout,CustomEvent:class{},sessionStorage:{getItem:()=>null},
  fetch:async(url,options={})=>{
   const body=options.body?JSON.parse(options.body):{};requests.push({url,body});
   let data={ok:true};
   if(url==='/api/universal/canvas')data=canvas;
   if(url==='/api/universal/graphs?screen=home')data={graphs:[]};
   if(url==='/api/universal/workshop')data.result=body.function==='getAgentSurface'?{agentProfiles:{},learning:{layers:{}}}:body.function==='getGraphMetadata'?{}:body.function==='listWorkshopMessages'?{messages:[]}:body.function==='listTasks'?tasks:body.function==='listAgentsWorking'?[{id:'codex',sessions:[{root:'declared',request_id:'untracked',task:'Actual declared task',status:'working'}]}]:[];
   if(url==='/api/universal/canvas-op')data.result=body.op==='list_skills'?[{id:'saved',title:'Saved workflow',chain:['Value'],runs:null,recipe:{nodes:[],wires:[]}}]:[];
   if(url==='/api/universal/node-library?templates=1')data.templates=[{id:'starter',title:'Stored starter',run_count:0,children:[{title:'Value',engine:'data.constant',params:{value:'hello'}}]}];
   if(url==='/api/universal/node-library?templates=1'&&library)data=typeof library==='function'?await library():library;
   if(url==='/api/universal/node-create')data={ok:true,root:'new-group',children:['new-child']};
   if(url==='/api/universal/hosts')data=await hosts();
   if(url==='/api/universal/interaction')data=canvas;
   if(url==='/api/universal/run-graph')data={ran:1,revision:3,results:{'new-child':{value:'hello'}}};
   if(Object.hasOwn(overrides,url))data=await overrides[url](body);
   return {ok:true,status:200,json:async()=>data};
  }};
 require('node:vm').runInNewContext(read('api.js'),context);
 await window.ArchHubAPI.ready;
 await window.ArchHubAPI.refreshProjects();
 return {api:window.ArchHubAPI,requests,document:context.document,poll:async()=>{for(const fn of [...timers.values()])await fn();}};
}

test('Home hydrates stored zero-run starters and saved skills from their existing owners',async()=>{
 const {api,requests}=await adapter([],undefined,undefined,{});
 assert.ok(requests.some(row=>row.url==='/api/universal/node-library?templates=1'));
 assert.deepEqual(JSON.parse(JSON.stringify(api.getSnapshot().templates.map(t=>[t.id,t.runs]))),[['starter',0],['saved',null]]);
 const opened=await api.openTemplateGraph('starter');
 assert.equal(opened.root,'new-group');
 assert.deepEqual(JSON.parse(JSON.stringify(opened.nodes)),['new-child']);
 assert.deepEqual(requests.find(row=>row.url==='/api/universal/node-create').body,{template:'starter',expected_scope:'graph'});
 await api.openTemplateGraph('saved');
 assert.ok(requests.some(row=>row.url==='/api/universal/canvas-op'&&row.body.op==='open_skill'&&row.body.args[0]==='saved'));
});

test('declared agent work stays visible without a Work card and is never counted twice',async()=>{
 const tasks=[],{api}=await adapter(tasks,undefined,undefined,{});
 await api.listAgentsWorking();
 assert.equal(api.getSnapshot().declaredTasks[0].title,'Actual declared task');
 assert.equal(api.getSnapshot().declaredTasks[0].id,'declared');
 tasks.push({id:'work',status:'WIP',declarations:[{root:'declared'}]});
 await api.listTasks();
 assert.equal(api.getSnapshot().declaredTasks.length,0);
});

test('a failed or malformed starter read never blocks the existing Canvas or saved skills',async()=>{
 for(const library of [{ok:true},async()=>{throw Error('Starter owner unavailable');}]){
  const {api}=await adapter([],library,undefined,{});
  assert.equal(api.getSnapshot().graph.id,'graph');
  assert.equal(api.getSnapshot().templates[0].id,'saved');
  assert.ok(api.getSnapshot().templateError);
  await api.refreshProjects();
  assert.equal(api.getSnapshot().graph.id,'graph');
 }
});

test('a pending host probe becomes a visible connected program on the existing polling cadence',async()=>{
 let host={connectors:[],probing:true};
 const {api,document,poll}=await adapter([],undefined,()=>host,{});
 await api.readHostAvailability();assert.equal(api.getSnapshot().hostsProbing,true);
 document.hidden=false;const close=api.subscribe(()=>{});
 try{
  host={connectors:[{id:'revit',name:'Revit',state:'connected',detail:'Fixture.rvt'}],probing:false};
  await poll();
  assert.equal(api.getSnapshot().hostsProbing,false);
  assert.equal(api.getSnapshot().hosts[0].detail,'Fixture.rvt');
 }finally{close();}
});

test('library Start and Schedule enter the existing composition before evaluating executable nodes',async()=>{
 const {api,requests}=await adapter([],undefined,undefined,{});
 await api.startTemplate('starter');
 const run=requests.findIndex(row=>row.url==='/api/universal/run-graph');
 assert.deepEqual(requests.find(row=>row.url==='/api/universal/interaction').body,{control:'new-group',projection_mode:'topology-delta-v1'});
 assert.ok(requests.findIndex(row=>row.url==='/api/universal/interaction')<run);
 assert.deepEqual(requests[run].body,{roots:['new-child']});
 await api.addSchedule('starter','08:00');
 assert.deepEqual(requests.find(row=>row.body.op==='add_schedule').body.args,[['new-child'],'08:00']);
});

test('failed graph navigation clears the new declaration projection immediately',async()=>{
 const {api}=await adapter([],undefined,undefined,{'/api/universal/graph-open':()=>{throw Error('Graph refused');}});
 await api.listAgentsWorking();assert.equal(api.getSnapshot().declaredTasks.length,1);
 await assert.rejects(api.selectGraph('missing'),/Graph refused/);
 assert.equal(api.getSnapshot().declaredTasks.length,0);
});
test('Connections reads the existing owners and shows actual host and saved account names',async()=>{
 const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,calls=[],routes=[];
 try{
  w.eval(read('vendor/react.js'));w.eval(read('vendor/react-dom.js'));w.eval(read('compiled/tokens.js'));
  const h=w.React.createElement;
  w.AHIcon=()=>null;
  w.UI={A:w.AH,D:{},api:{refreshSocialConnections:async()=>calls.push('connections'),readHostAvailability:async()=>calls.push('hosts'),refreshSettingsControls:async()=>calls.push('credentials')},
   useData:()=>({profile:{id:'account'},connections:[],secrets:[{id:'named-account',name:'My connected office',provider:'office',disconnectable:false}],hosts:[{id:'revit',name:'Revit',state:'connected',detail:'Actual fixture.rvt'}]}),
   useApp:()=>({go:route=>routes.push(route),show:()=>{}}),
   Btn:({children,...props})=>h('button',props,children),Card:({children,...props})=>h('section',props,children),Empty:({children})=>h('p',null,children),
   useRegisteredActions:(actions,handlers)=>({actionState:{},runAction:(name,...args)=>handlers[actions[name]](...args)}),RegisteredActionStatus:()=>null};
  w.eval(read('compiled/ds_settings3.js'));
  w.ReactDOM.createRoot(w.document.getElementById('root')).render(h(w.UI.Connections));
  for(let i=0;i<50&&(!w.document.querySelector('section')||calls.length<3);i++)await new Promise(r=>setTimeout(r,5));
  assert.match(w.document.body.textContent,/Revit/);
  assert.match(w.document.body.textContent,/Actual fixture.rvt/);
  assert.match(w.document.body.textContent,/My connected office/);
  assert.deepEqual(calls.sort(),['connections','credentials','hosts']);
  [...w.document.querySelectorAll('button')].find(b=>b.textContent==='Open').click();
  assert.deepEqual(routes,['watcher']);
 }finally{w.close();}
});


test('current interaction acknowledgement hydrates the existing canvas without replaying its write',async()=>{
 const {api,requests}=await adapter([],undefined,undefined,{'/api/universal/interaction':()=>({ok:true,projection_mode:'topology-delta-v1',committed_revision:0})});
 await api.startTemplate('starter');
 assert.equal(requests.filter(r=>r.url==='/api/universal/interaction').length,2);
 assert.ok(requests.filter(r=>r.url==='/api/universal/canvas').length>=3);
});

test('a completed template run never restores over a later deliberate graph navigation',async()=>{
 let begin,release;const entered=new Promise(resolve=>{begin=resolve;});
 const {api,requests}=await adapter([],undefined,undefined,{'/api/universal/run-graph':async()=>{begin();await new Promise(resolve=>{release=resolve;});return {ran:1,revision:3,results:{}};}});
 const running=api.startTemplate('starter');await entered;await api.selectGraph('other');release();await running;
 assert.deepEqual(requests.filter(row=>row.url==='/api/universal/interaction').map(row=>row.body.control),['new-group']);
});
