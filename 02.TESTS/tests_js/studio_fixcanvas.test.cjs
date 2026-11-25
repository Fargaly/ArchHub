// FIXCANVAS on the session-file owner (D-014 NOGRAPH, SPEC 3.1 "a document is a file", owner session_files).
// Each case keeps the guarantee it had on the graph adapter: one save per edit, no re-read after an edit,
// an older acknowledgement never overwrites a newer local edit, refusals stay refused, and freshness is one cheap read.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const structuredClone=globalThis.structuredClone;
const PATH='C:/isolated/nested.archhub', TOP='C:/isolated/top.archhub';

const document_=(id='doc-nested',title='Nested')=>({format:'archhub',version:1,id,title,
  nodes:[{id:'a',type:'param.number',title:'Number',params:{value:1},paramDefs:[{id:'value',name:'value',type:'number'}],
     ports:{source:[{id:'out',type:'number'}],target:[]},position:{x:10,y:20}},
    {id:'b',type:'script.python',title:'Expression',params:{kind:'pure',code:''},
     ports:{source:[{id:'result',type:'text'}],target:[{id:'in',type:'number'}]},position:{x:300,y:20}},
    {id:'c',type:'thing.agent',title:'Agent',fixed:true,params:{reference:'held'},ports:{source:[],target:[]},position:{x:600,y:20}}],
  wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom:1},properties:{revision:4}});

async function mount({holdSave=null,refuseParam=false,slowDiscovery=null,cloud=null,holdValidate=null,subject=null}={}) {
  const calls=[], timers=[], files={[PATH]:document_(),[TOP]:document_('doc-top','Top')};
  let revision=4;
  const who=subject||{id:'fixcanvas-fixture'};
  const context = vm.createContext({console,structuredClone,URLSearchParams,AbortSignal,setTimeout,clearTimeout,
    CustomEvent:class {constructor(type, options){this.type=type;this.detail=options?.detail;}},
    document:{hidden:false,addEventListener(){}},crypto:{randomUUID:()=>'id-'+calls.length},
    requestAnimationFrame:fn=>setTimeout(fn,0),cancelAnimationFrame:clearTimeout,
    sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    ARCHHUB_BOOT:{token:'fixture',csrf:'fixture'},addEventListener(){},dispatchEvent(){},
    setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval(){},
    fetch:async(url,init={})=>{
      const body=init.body?JSON.parse(init.body):null;calls.push({url,body});
      let data={ok:true,result:[],providers:[],agents:[],items:[],workspaces:[],templates:[],sessions:[],directory:'mem'},status=200;
      // Desktop work needs a verified ArchHub account (cd19d5d4); this fixture is signed in.
      if(url==='/api/universal/desktop-access')data={ok:true,admitted:true,state:'admitted',subject:who.id};
      else if(url==='/api/commands')data={commands:[]};  // The command owner serves the menu catalogue at startup (f8b5feea).
      else if(url==='/api/universal/cloud-session'&&cloud)data=await cloud;
      else if(url==='/api/universal/application-update'&&slowDiscovery)data=await slowDiscovery;
      else if(url==='/api/session-files'){
        const action=body.action;
        if(action==='initial')data={ok:true,document:structuredClone(files[PATH]),path:PATH};
        else if(action==='open')data={ok:true,document:structuredClone(files[body.path]),path:body.path};
        else if(action==='validate'){if(holdValidate?.enabled)await holdValidate.promise;data={ok:true,document:body.document};}
        else if(action==='head')data={ok:true,revision};
        else if(action==='read')data={ok:true,document:{...structuredClone(files[PATH]),properties:{revision}},revision,by:'agent'};
        else if(action==='solve')data={ok:true,results:{},solved:[],stale:[],ms:0};
        else if(action==='param-op'){
          if(refuseParam){status=400;data={ok:false,error:'invalid parameter'};}
          else {const [id,key,value]=body.args,doc=structuredClone(body.document);doc.nodes.find(n=>n.id===id).params[key]=Number(value);data={ok:true,document:doc,changed:[id]};}
        } else if(action==='autosave'){
          if(holdSave?.enabled){holdSave.enabled=false;await holdSave.promise;}
          revision++;data={ok:true,path:body.path,revision,document:{...body.document,properties:{...body.document.properties,revision}}};
        }
      }
      return {ok:status===200,status,headers:{get:()=>null},json:async()=>data};
    }});
  context.window=context;
  for(const name of ['studio-authority.js','api.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio',name),'utf8'),context);
  await context.ArchHubAPI.ready;
  await new Promise(resolve=>setTimeout(resolve,30));
  calls.length=0;
  return {api:context.ArchHubAPI,calls,timers,bump:()=>{revision++;}};
}
// Session-file owner requests, without the page's edit-state report (an update hold, not a document read or write).
const actions=calls=>calls.filter(c=>c.url==='/api/session-files'&&c.body.action!=='edit_state').map(c=>c.body.action);
const of=(calls,action)=>calls.filter(c=>c.url==='/api/session-files'&&c.body.action===action);
const reads=calls=>calls.filter(c=>c.url==='/api/session-files'&&['initial','open','read'].includes(c.body.action));
const settle=()=>new Promise(resolve=>setTimeout(resolve,400));  // past the solve and autosave debounce
const node=(api,id)=>api.getSnapshot().graph.nodes.find(n=>n.id===id);
const saved=(call,id)=>call.body.document.nodes.find(n=>n.id===id);

test('nested Canvas move saves through the real adapter with one mutation and no graph re-read',async()=>{
  const {api,calls}=await mount();
  await api.moveNodes({a:{x:80,y:90}});
  assert.equal(node(api,'a').x,80);
  await settle();
  assert.deepEqual(actions(calls),['autosave'],JSON.stringify(calls));
  assert.equal(of(calls,'autosave')[0].body.path,PATH);
  assert.deepEqual(saved(of(calls,'autosave')[0],'a').position,{x:80,y:90});
});
test('parameter and wire acknowledgements update the graph without a full GET',async()=>{
  const {api,calls}=await mount();
  await api.setNodeParam('a','value',7);
  assert.deepEqual(actions(calls),['param-op'],JSON.stringify(calls));
  assert.equal(node(api,'a').params.value,7);
  calls.length=0;
  await api.connectSockets({from:'a',fromPort:'out',to:'b',toPort:'in'});
  assert.deepEqual(actions(calls),[],JSON.stringify(calls));
  assert.equal(api.getSnapshot().graph.wires.length,1);
  await settle();
  assert.equal(reads(calls).length,0);assert.equal(of(calls,'autosave').length,1);
});
test('Canvas bootstrap reuses an admitted full graph without reopening or refreshing unrelated owners',async()=>{
  const {api,calls}=await mount();
  await api.refreshProjects({userCanvas:true});
  assert.equal(calls.length,0,JSON.stringify(calls));
});

test('overlapping first Canvas opens share one graph request',async()=>{
 const {api,calls}=await mount();
 await Promise.all([api.refreshProjects({userCanvas:true}),api.refreshProjects({userCanvas:true})]);
 // The startup file was read once at boot; showing the Canvas again reads nothing.
 assert.equal(reads(calls).length,0);
 assert.equal(api.getSnapshot().graph.id,'doc-nested');
});

test('overlapping moves each confirm once without adopting an older acknowledgement',async()=>{
 let release;const holdSave={enabled:true,promise:new Promise(resolve=>{release=resolve;})};
 const {api,calls}=await mount({holdSave});
 await api.moveNodes({a:{x:80,y:90}});
 await settle();  // the first save is in flight
 await api.moveNodes({b:{x:400,y:50}});
 release();await settle();
 const saves=of(calls,'autosave');
 assert.equal(saves.length,2);
 assert.equal(saved(saves[0],'a').position.x,80);assert.equal(saved(saves[0],'b').position.x,300);
 assert.equal(saved(saves[1],'b').position.x,400);
 assert.equal(node(api,'a').x,80);
 assert.equal(node(api,'b').x,400,'the older acknowledgement does not move b back');
 assert.equal(reads(calls).length,0);
});

test('parameter and move share one authority queue and both acknowledgements confirm',async()=>{
 const {api,calls}=await mount();
 await Promise.all([api.setNodeParam('a','value',8),api.moveNodes({b:{x:400,y:50}})]);
 await settle();
 assert.equal(of(calls,'param-op').length,1);
 const saves=of(calls,'autosave');assert.equal(saves.length,1);
 assert.equal(saved(saves[0],'a').params.value,8);assert.equal(saved(saves[0],'b').position.x,400);
 assert.equal(node(api,'a').params.value,8);
 assert.equal(node(api,'b').x,400);
});

test('concurrent parameter and move deltas merge against the queued authority revision',async()=>{
 let release;const holdSave={enabled:true,promise:new Promise(resolve=>{release=resolve;})};
 const {api,calls}=await mount({holdSave});
 await api.setNodeParam('a','value',8);
 await settle();  // the parameter save is in flight
 await api.moveNodes({b:{x:400,y:50}});
 release();await settle();
 const saves=of(calls,'autosave');
 assert.deepEqual(saves.map(c=>c.body.base_revision),[4,5],'the second save builds on the acknowledged revision');
 assert.equal(saved(saves[1],'a').params.value,8);assert.equal(saved(saves[1],'b').position.x,400);
 assert.equal(node(api,'a').params.value,8);
 assert.equal(node(api,'b').x,400);
});

test('delayed initial account discovery preserves the already authorized Canvas',async()=>{
 let release;const cloud=new Promise(resolve=>{release=resolve;});
 const {api,calls}=await mount({cloud});api.setActiveSurface('canvas');
 const graph=api.getSnapshot().graph;
 release({signed_in:true,email:'owner@example.test'});
 await new Promise(resolve=>setTimeout(resolve,30));
 assert.equal(api.getSnapshot().graph.scopeKey,graph.scopeKey);
 assert.equal(api.getSnapshot().graph.nodes.length,graph.nodes.length);
 assert.equal(reads(calls).length,0);
});

test('saved graph opens once even while background graph discovery is pending',async()=>{
 const {api,calls}=await mount({slowDiscovery:new Promise(()=>{})});
 await api.selectGraph(TOP);
 assert.equal(api.getSnapshot().graph.id,'doc-top');
 // Every document read is that one open; leaving the startup file may save it, it is never read again.
 assert.deepEqual(reads(calls).map(c=>c.body.action),['open']);assert.equal(of(calls,'open')[0].body.path,TOP);
});

test('a refused parameter remains refused without automatically replaying the write',async()=>{
 const {api,calls}=await mount({refuseParam:true});
 await assert.rejects(api.setNodeParam('a','value',8),/invalid parameter/);
 await settle();
 assert.deepEqual(actions(calls),['param-op']);
 assert.equal(node(api,'a').params.value,1);
});

test('native typed wire uses its current graph interaction in one mutation',async()=>{
 const {api,calls}=await mount();
 assert.equal(node(api,'a').outputs[0].type,'number');assert.equal(node(api,'b').inputs[0].type,'number');
 await assert.rejects(api.connectSockets({from:'b',fromPort:'result',to:'a',toPort:'param:value'}),/Wrong type.*Insert Convert/);
 await api.connectSockets({from:'a',fromPort:'out',to:'b',toPort:'in'});
 assert.equal(api.getSnapshot().graph.wires.length,1);
 await settle();
 const saves=of(calls,'autosave');assert.equal(saves.length,1);
 assert.deepEqual(saves[0].body.document.wires.map(w=>[w.from,w.to]),[[{node:'a',socket:'out'},{node:'b',socket:'in'}]]);
});

test('a no-longer-editable parameter retains its explicit refusal without a graph read',async()=>{
 const {api,calls}=await mount();
 assert.equal(api.getNodeParameters('c').find(p=>p.key==='reference').editable,false);
 await assert.rejects(api.setNodeParam('c','reference','changed'),/read-only/);
 await settle();
 assert.deepEqual(actions(calls),[]);
 assert.equal(node(api,'c').params.reference,'held');
});


test('account change clears previous private view before a delayed or refused reload',async()=>{
 const subject={id:'previous-account'};
 let reject;const holdValidate={enabled:false,promise:new Promise((_,r)=>{reject=r;})};
 const {api}=await mount({subject,holdValidate});
 const previous=api.getSnapshot();previous.tasks.push({id:'private-task'});previous.billing={invoices:['private-invoice']};
 await api.updateGraph('doc-nested',{documentation:'private graph notes'});
 holdValidate.enabled=true;subject.id='next-account';
 const changing=api.refreshDesktopAccess(true);
 await new Promise(r=>setTimeout(r,20));
 assert.equal(api.getSnapshot().graph.documentation||'','');assert.equal(api.getSnapshot().graph.name,'');assert.equal(api.getSnapshot().billing?.invoices?.length||0,0);assert.equal(api.getSnapshot().profile.email,'');
 assert.equal(api.getSnapshot().tasks.length,0);assert.equal(api.getSnapshot().graph.nodes.length,0);
 reject(Error('reload refused'));await changing;
 assert.equal(api.getSnapshot().desktopAccess.ready,false,'a refused reload is not shown as a ready desktop');
 assert.equal(api.getSnapshot().tasks.length,0);assert.equal(api.getSnapshot().graph.nodes.length,0);
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
 await Promise.all([api.selectGraph(TOP),api.refreshProjects({userCanvas:true})]);
 assert.equal(api.getSnapshot().graph.id,'doc-top');assert.equal(api.getSnapshot().graphOpening,false);
 assert.equal(of(calls,'open').length,1);
 assert.equal(of(calls,'read').length,0);
});


test('native wire resolves the exact dropped socket from the shared scoped target table',async()=>{
 const {api,calls}=await mount();
 const group=await api.groupNodes(['b']);
 assert.ok(group.inputs.some(p=>p.id==='in:b:in'));
 await api.connectSockets({from:'a',fromPort:'out',to:group.id,toPort:'in:b:in'});
 const wires=api.getSessionDocument().wires;
 assert.equal(wires.length,1);assert.deepEqual([wires[0].to.node,wires[0].to.socket],['b','in'],'the file keeps the real member socket');
 assert.equal(reads(calls).length,0);
});


test('visible Canvas combines scheduling and conditional freshness in one timer request',async()=>{
 const {api,calls,timers,bump}=await mount();api.subscribe(()=>{});api.setActiveSurface('canvas');
 await Promise.all(timers.map(timer=>timer()));await new Promise(r=>setTimeout(r,30));
 assert.equal(of(calls,'head').length,1);assert.equal(of(calls,'head')[0].body.path,PATH);
 assert.equal(reads(calls).length,0,'an unchanged file is not read again');
 calls.length=0;bump();
 await Promise.all(timers.map(timer=>timer()));await new Promise(r=>setTimeout(r,30));
 assert.deepEqual(actions(calls),['head','read'],'a newer revision is read once');
});
