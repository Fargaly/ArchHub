const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const structuredClone=globalThis.structuredClone;

async function mount({cloud, saved, initialScope, slowDiscovery, refuseProperty=false,nativeWire=false,readOnly=false,deferredHome=false,delta=false,readCanvas=null,nativeGlobal=false}={}) {
  const calls = [], timers = [];
  let raw = {ok:true, application_root:'app', canvas_root:'top', revision:4,
    scope:{current:initialScope||'nested',current_label:'Nested graph'}, authorization:{subject:'owner'},
    nodes:[{id:'a',label:'Number',x:10,y:20,properties:[{label:'value',value:1,editable:true,editor:'number',relation:'value'}],
      ports:[{id:'out',name:'value',side:'source',value_type:'number',connectable:true}]},
      {id:'b',label:'Expression',x:300,y:20,properties:[],ports:[{id:'in',name:'a',side:'target',value_type:'number',connectable:true}]}],wires:[]};
  Object.assign(raw,{catalog:[],catalog_sections:[],configuration:{design_system:{control_catalog:{controls:[]}}}});
  if(readOnly)raw.nodes[0].properties[0].editable=false;
  if(nativeWire){raw.interaction_projection={bindings:[{control:'connect-control',projection_mode:'topology-delta-v1',interaction:'connect-interaction',event:'connect-event'}]};Object.assign(raw.nodes[0].ports[0],{connect_control:'connect-control',connect_event_fact_input:'candidate',connect_choices:[{owner:'b',id:'in'}]});}
  if(nativeGlobal){raw.topology_targets=raw.nodes[0].ports[0].connect_choices;delete raw.nodes[0].ports[0].connect_choices;}
  const store = new Map();
  const context = vm.createContext({console,structuredClone,URLSearchParams,AbortSignal,setTimeout,clearTimeout,
    CustomEvent:class {constructor(type, options){this.type=type;this.detail=options?.detail;}},
    document:{hidden:false,addEventListener(){}},crypto:{randomUUID:()=>String(calls.length)},
    sessionStorage:{getItem:key=>store.get(key)||(saved&&key==='archhub.studio.session'?JSON.stringify({lastGraphId:saved}):null),setItem:(key,value)=>store.set(key,value)},
    ARCHHUB_BOOT:{token:'fixture',csrf:'fixture'},addEventListener(){},dispatchEvent(){},
    setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval(){},
    fetch:async(url,init={})=>{
      if(readCanvas?.enabled&&url.startsWith('/api/universal/canvas'))return await readCanvas.promise;
      const body=init.body?JSON.parse(init.body):null;calls.push({url,body});
      let data={ok:true,result:[],providers:[],agents:[],items:[],workspaces:[],templates:[]},status=200;
      if(url==='/api/universal/cloud-session'&&cloud)data=await cloud;
      else if(url==='/api/universal/application-update'&&slowDiscovery)data=await slowDiscovery;
      else if(url.startsWith('/api/universal/canvas?')||url==='/api/universal/canvas')data=deferredHome&&url.includes('screen=home')?{...structuredClone(raw),nodes:[],canvas_deferred:true}:structuredClone(raw);
      else if(url==='/api/universal/canvas-op'&&body?.op==='scheduler_tick')data={ok:true,result:[],unchanged:true,revision:raw.revision,scope:raw.scope.current,graph_id:raw.application_root};
      else if(url.startsWith('/api/universal/graphs'))data={ok:true,graphs:[{id:'top',title:'System'},{id:'nested',title:'Nested'}],current_graph:'nested'};
      else if(url==='/api/universal/graph-open'){raw={...raw,revision:raw.revision+1,scope:{...raw.scope,current:body.root}};data={ok:true,canvas:raw};}
      else if(url==='/api/universal/gesture'){
        if(body.expected_scope!=='nested'){status=400;data={ok:false,error:'canvas scope changed before layout save'};}
        else {raw={...raw,revision:raw.revision+1,nodes:raw.nodes.map(n=>({...n,...body.positions?.[n.id]}))};data=structuredClone(raw);}
      } else if(url==='/api/universal/connect'){
        assert.equal(body.expected_scope,'nested');raw={...raw,revision:raw.revision+1,wires:[{id:'wire',source:'a',target:'b',source_interface:'out',target_interface:'in'}]};data=structuredClone(raw);
      } else if(url==='/api/universal/interaction'&&nativeWire){
        assert.equal(body.control,'connect-control');assert.equal(body.projection_mode,'topology-delta-v1');assert.deepEqual(body.event_facts,[{input:'candidate',value:0}]);raw={...raw,revision:raw.revision+1,wires:[{id:'native-wire',source:'a',target:'b',source_interface:'out',target_interface:'in'}]};data=structuredClone(raw);
      } else if(url==='/api/universal/set-property'){
        if(refuseProperty){status=400;data={ok:false,error:'invalid parameter'};}else{raw={...raw,revision:raw.revision+1,nodes:raw.nodes.map(n=>n.id==='a'?{...n,properties:n.properties.map(p=>({...p,value:Number(body.value)}))}:n)};data=structuredClone(raw);}
      }
      if(delta&&status===200&&body?.projection_mode==='interaction-delta-v1')data={
        ok:true,projection_mode:'interaction-delta-v1',base_revision:body.projection_revision,
        revision:raw.revision,scope:raw.scope,node_count:raw.nodes.length,wire_count:raw.wires.length,
        node_states:[],wire_states:[],node_patches:structuredClone(raw.nodes),wire_patches:[],
        control_state:raw.configuration.design_system.control_catalog,configuration_state:{}};
      return {ok:status===200,status,json:async()=>data};
    }});
  context.window=context;
  for(const name of ['studio-authority.js','api.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio',name),'utf8'),context);
  await context.ArchHubAPI.ready;
  await new Promise(resolve=>setTimeout(resolve,30));
  calls.length=0;
  return {api:context.ArchHubAPI,calls,timers};
}

test('nested Canvas move saves through the real adapter with one mutation and no graph re-read',async()=>{
  const {api,calls}=await mount();
  await api.moveNodes({a:{x:80,y:90}});
  assert.equal(calls.length,1,JSON.stringify(calls));
  assert.equal(calls[0].body.expected_scope,'nested');
  assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').x,80);
});
test('parameter and wire acknowledgements update the graph without a full GET',async()=>{
  const {api,calls}=await mount();
  await api.setNodeParam('a','value',7);
  assert.equal(calls.length,1,JSON.stringify(calls));
  assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').params.value,7);
  calls.length=0;
  await api.connectSockets({from:'a',fromPort:'out',to:'b',toPort:'in'});
  assert.equal(calls.length,1,JSON.stringify(calls));
  assert.equal(api.getSnapshot().graph.wires.length,1);
});
test('Canvas bootstrap reuses an admitted full graph without reopening or refreshing unrelated owners',async()=>{
  const {api,calls}=await mount();
  await api.refreshProjects({userCanvas:true});
  assert.equal(calls.length,0,JSON.stringify(calls));
});

test('overlapping first Canvas opens share one graph request',async()=>{
 const {api,calls}=await mount({deferredHome:true});
 await Promise.all([api.refreshProjects({userCanvas:true}),api.refreshProjects({userCanvas:true})]);
 assert.equal(calls.filter(c=>c.url==='/api/universal/canvas').length,1);
});

test('overlapping moves each confirm once without adopting an older acknowledgement',async()=>{
 const {api,calls}=await mount();
 await Promise.all([api.moveNodes({a:{x:80,y:90}}),api.moveNodes({b:{x:400,y:50}})]);
 assert.equal(calls.length,2);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').x,80);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='b').x,400);
});

test('parameter and move share one authority queue and both acknowledgements confirm',async()=>{
 const {api,calls}=await mount();
 await Promise.all([api.setNodeParam('a','value',8),api.moveNodes({b:{x:400,y:50}})]);
 assert.equal(calls.length,2);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').params.value,8);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='b').x,400);
});

test('concurrent parameter and move deltas merge against the queued authority revision',async()=>{
 const {api,calls}=await mount({delta:true});
 await Promise.all([api.setNodeParam('a','value',8),api.moveNodes({b:{x:400,y:50}})]);
 assert.equal(calls.length,2);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').params.value,8);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='b').x,400);
});

test('delayed initial account discovery preserves the already authorized Canvas',async()=>{
 let release;const cloud=new Promise(resolve=>{release=resolve;});
 const {api,calls}=await mount({cloud});api.setActiveSurface('canvas');
 const graph=api.getSnapshot().graph;
 release({signed_in:true,email:'owner@example.test'});
 await new Promise(resolve=>setTimeout(resolve,30));
 assert.equal(api.getSnapshot().graph.scopeKey,graph.scopeKey);
 assert.equal(api.getSnapshot().graph.nodes.length,graph.nodes.length);
 assert.equal(calls.filter(c=>c.url.startsWith('/api/universal/canvas')).length,0);
});

test('saved graph opens once even while background graph discovery is pending',async()=>{
 const {api,calls}=await mount({saved:'nested',initialScope:'top',slowDiscovery:new Promise(()=>{})});
 await api.refreshProjects({userCanvas:true});
 assert.equal(api.getSnapshot().graph.id,'nested');
 assert.deepEqual(calls.map(c=>c.url),['/api/universal/graph-open']);
});

test('a refused parameter remains refused without automatically replaying the write',async()=>{
 const {api,calls}=await mount({refuseProperty:true});
 await assert.rejects(api.setNodeParam('a','value',8),/invalid parameter/);
 assert.equal(calls.length,1);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').params.value,1);
});

test('native typed wire uses its current graph interaction in one mutation',async()=>{
 const {api,calls}=await mount({nativeWire:true});
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').outputs[0].connect_choices[0].interface,'in');
 await api.connectSockets({from:'a',fromPort:'out',to:'b',toPort:'in'});
 assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/universal/interaction');
 assert.equal(api.getSnapshot().graph.wires.length,1);
});

test('a no-longer-editable parameter retains its explicit refusal without a graph read',async()=>{
 const {api,calls}=await mount({readOnly:true});
 const result=await api.setNodeParam('a','value',8);
 assert.equal(result.ok,false);assert.equal(calls.length,0);
 assert.equal(api.getSnapshot().graph.nodes.find(n=>n.id==='a').params.value,1);
});


test('account change clears previous private view before a delayed or refused reload',async()=>{
 const cloud={signed_in:true,email:'previous@example.test'},readCanvas={enabled:false};
 const {api}=await mount({cloud,readCanvas});
 const previous=api.getSnapshot();previous.tasks.push({id:'private-task'});previous.graph.documentation='private graph notes';previous.billing={invoices:['private-invoice']};
 let reject;readCanvas.promise=new Promise((_,r)=>{reject=r;});readCanvas.enabled=true;cloud.email='next@example.test';
 const changing=api.syncAccount();const refused=assert.rejects(changing,/reload refused/);
 await new Promise(r=>setTimeout(r,20));
 assert.equal(api.getSnapshot().graph.documentation||'','');assert.equal(api.getSnapshot().graph.name,'');assert.equal(api.getSnapshot().billing?.invoices?.length||0,0);assert.equal(api.getSnapshot().profile.email,'');
 assert.equal(api.getSnapshot().tasks.length,0);assert.equal(api.getSnapshot().graph.nodes.length,0);
 reject(Error('reload refused'));await refused;
 assert.equal(api.getSnapshot().tasks.length,0);
});


test('shared sparse delta preserves metadata and validates history splice identity',()=>{
 const context=vm.createContext({});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/studio-authority.js'),'utf8'),context);
 const merge=context.ArchHubStudioAuthority.mergeProjectionDelta;
 const base={revision:4,scope:{current:'nested'},nodes:[{id:'n',ports:[{id:'p'}],params:[{value:'old'}]}],wires:[],
   configuration:{design_system:{control_catalog:{controls:[]}}},
   interaction_projection:{revision:4,bindings:[{control:'n'}]},
   action_history:{root:'h',transactions:[{root:'old'}]}};
 const delta={projection_mode:'interaction-delta-v1',retained_fields:['scope'],base_revision:4,revision:5,node_count:1,wire_count:0,
   node_states:[],wire_states:[],node_patches:[{id:'n',params:[{value:'new'}]}],wire_patches:[],
   control_state:{controls:[]},configuration_state:{},interaction_projection:{revision:5},
   action_history:{root:'h',transactions_patch:{base_count:1,remove:0,prepend:[{root:'new'}],count:2}}};
 const result=merge(delta,base);
 assert.equal(result.nodes[0].ports,base.nodes[0].ports);assert.equal(result.nodes[0].params[0].value,'new');
 assert.equal(result.interaction_projection.bindings,base.interaction_projection.bindings);
 assert.equal(result.scope,base.scope);assert.equal(result.action_history.transactions[1].root,'old');
 assert.equal(result.action_history.transactions_patch,undefined);
 assert.throws(()=>merge({...delta,action_history:{transactions_patch:{base_count:1,remove:1,prepend:[{}],count:1}}},base),/identities/);
 assert.throws(()=>merge({...delta,action_history:{transactions_patch:{base_count:2,remove:0,prepend:[],count:2}}},base),/held history/);
 assert.throws(()=>merge({...delta,action_history:{transactions_patch:{base_count:1,remove:0,prepend:[{root:'old'}],count:2}}},base),/identities/);
});


test('same-scope bootstrap does not cancel an explicit graph switch or reread its acknowledgement',async()=>{
 const {api,calls}=await mount();
 await Promise.all([api.selectGraph('top'),api.refreshProjects({userCanvas:true})]);
 assert.equal(api.getSnapshot().graph.id,'top');assert.equal(api.getSnapshot().graphOpening,false);
 assert.equal(calls.filter(c=>c.url==='/api/universal/graph-open').length,1);
 assert.equal(calls.filter(c=>c.url==='/api/universal/canvas').length,0);
});


test('native wire resolves the exact dropped socket from the shared scoped target table',async()=>{
 const {api,calls}=await mount({nativeWire:true,nativeGlobal:true});
 await api.connectSockets({from:'a',fromPort:'out',to:'b',toPort:'in'});
 assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/universal/interaction');
 assert.equal(api.getSnapshot().graph.wires.length,1);
});


test('visible Canvas combines scheduling and conditional freshness in one timer request',async()=>{
 const {api,calls,timers}=await mount();api.subscribe(()=>{});api.setActiveSurface('canvas');
 await Promise.all(timers.map(timer=>timer()));
 const polls=calls.filter(c=>c.url==='/api/universal/canvas-op'&&c.body.op==='scheduler_tick');
 assert.equal(polls.length,1);assert.equal(polls[0].body.since_revision,4);
 assert.equal(calls.filter(c=>c.url.startsWith('/api/universal/canvas?')||c.url==='/api/universal/canvas').length,0);
});
