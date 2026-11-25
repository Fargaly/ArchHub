const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
// D-014 NOGRAPH: the open canvas is a session file (owner session_files); the graph projection stays for System.
const PATH='C:/isolated/agents.archhub';
const sessionFile=(nodes=[],id='graph')=>({format:'archhub',version:1,id,title:id,nodes,wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom:1},properties:{revision:1}});
const files=(file,session)=>async body=>{
 const own=session&&await session(body);if(own)return own;
 if(body.action==='initial')return {ok:true,document:file,path:PATH};
 if(body.action==='validate')return {ok:true,document:body.document};
 if(body.action==='autosave')return {ok:true,path:body.path,revision:(body.document.properties?.revision||0)+1,document:body.document};
 if(body.action==='solve')return {ok:true,results:{},solved:[],stale:[],ms:0};
 if(body.action==='param-op'){const [id,key,value]=body.args,document=globalThis.structuredClone(body.document);document.nodes.find(n=>n.id===id).params[key]=value;return {ok:true,document,changed:[id]};}
 return {ok:true};
};
async function adapter(canvas,serve=()=>({ok:true,result:[]}),file=sessionFile(),session=null){
 const sessions=files(file,session);
 const calls=[],listeners=new Map();
 const window={structuredClone:globalThis.structuredClone,crypto:require('node:crypto').webcrypto,
  ARCHHUB_BOOT:{home_load_ms:60000,token:'fixture',csrf:'fixture'},document:{hidden:true,addEventListener(){}},
  addEventListener(name,fn){listeners.set(name,fn);},dispatchEvent(){},
  ArchHubStudioAuthority:{create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}}};
 const fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
  // Desktop work needs a verified ArchHub account (cd19d5d4); this fixture is signed in.
  const data=url==='/api/universal/desktop-access'?{ok:true,admitted:true,state:'admitted',subject:'agents-fixture'}:url==='/api/commands'?{commands:[]}:url==='/api/universal/canvas'?canvas:url==='/api/session-files'?await sessions(body):await serve(url,body);
  return {ok:data.ok!==false,status:data.ok===false?409:200,json:async()=>data};
 };
 const context={window,document:window.document,fetch,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
  setTimeout,clearTimeout,setInterval,clearInterval,URLSearchParams,AbortSignal:globalThis.AbortSignal,console};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../01.APP/nodelang/studio/api.js'),'utf8'),context);
 await window.ArchHubAPI.ready;await new Promise(resolve=>setTimeout(resolve,0));
 return {api:window.ArchHubAPI,calls};
}
const graph=nodes=>({root:'graph',scope:{current:'graph'},nodes,wires:[],catalog:[],workshops:[{root:'workshop'}]});
test('multi-node failure restores prior successful edits using the existing property owner',async()=>{
 const property=(id,value)=>({id,type:'param.number',title:id,params:{value},paramDefs:[{id:'value',name:'value',type:'number'}],ports:{source:[],target:[]},position:{x:0,y:0}});
 const writes=[];
 const {api}=await adapter(graph([]),undefined,sessionFile([property('one',1),property('two',2)]),body=>{
  if(body.action!=='param-op')return null;
  writes.push([body.args[0],body.args[2]]);
  return body.args[0]==='two'?{ok:false,error:'Second owner refused'}:null;
 });
 await assert.rejects(api.setMultipleNodeParameters(['one','two'],'value',9),/Second owner refused.*rolled back/);
 assert.deepEqual(writes,[['one',9],['two',9],['one',1]]);
 const held=api.getSessionDocument().nodes;
 assert.equal(held[0].params.value,1);assert.equal(held[1].params.value,2);
});
test('Brain requests its real held count rather than exporting a silently truncated page',async()=>{
 const {api,calls}=await adapter(graph([]),(url,body)=>url==='/api/universal/brain-export'?
  {ok:true,facts:{held:2,total:body.limit===2?2:1,folders:[{label:'User',facts:(body.limit===2?[1,2]:[1]).map(n=>({id:String(n),body:'fact '+n,kind:'fact'}))}]}}:{ok:true,result:[]});
 const rows=await api.refreshBrain();assert.equal(rows.length,2);
 const reads=calls.filter(row=>row.url==='/api/universal/brain-export');assert.deepEqual(reads.map(row=>row.body),[{}, {limit:rows.length}]);
 assert.equal(api.getKnowledgeGraph().nodes[0].type,'Memory');
});

test('Social memory uses the complete Brain reader and preserves fact kinds',async()=>{
 const {api,calls}=await adapter(graph([]),(url,body)=>url==='/api/universal/brain-export'?
  {ok:true,facts:{held:2,total:body.limit===2?2:1,folders:[{label:'User',facts:(body.limit===2?[1,2]:[1]).map(n=>({id:String(n),body:'fact '+n,kind:'mandate'}))}]}}:{ok:true,result:[]});
 assert.equal((await api.refreshSocialMemory()).length,2);
 assert.deepEqual(calls.filter(row=>row.url==='/api/universal/brain-export').map(row=>row.body),[{}, {limit:2}]);
 assert.equal(api.getKnowledgeGraph().nodes[0].type,'Preference');
});

test('Settings Brain export uses the same complete reader as the Brain screen',async()=>{
 const {api}=await adapter(graph([]),(url,body)=>url==='/api/universal/brain-export'?
  {ok:true,facts:{held:2,total:body.limit===2?2:1,folders:[{label:'User',facts:(body.limit===2?[1,2]:[1]).map(n=>({id:String(n),body:'fact '+n,kind:'fact'}))}]}}:{ok:true,result:[]});
 const exported=await api.exportData('Brain');
 assert.equal(JSON.parse(exported.content).length,2);
 assert.equal(api.getSnapshot().brain.length,2);
});

test('Agent surface read cannot publish metadata after the graph changes',async()=>{
 let finish;
 const held=new Promise(resolve=>{finish=resolve;});
 const canvas=graph([]);
 const {api,calls}=await adapter(canvas,(url,body)=>{
  if(body?.function==='getAgentSurface')return held;
  if(body?.function==='getGraphMetadata')return {ok:true,result:{documentation:'Old graph instructions'}};
  return {ok:true,result:[]};
 },sessionFile(),body=>body.action==='open'?{ok:true,document:sessionFile([],'other'),path:'C:/isolated/other.archhub'}:null);
 const reading=api.refreshAgentSurface();
 while(!calls.some(call=>call.body?.function==='getAgentSurface'))await new Promise(resolve=>setTimeout(resolve,1));  // the read is in flight
 await api.selectGraph('C:/isolated/other.archhub');
 finish({ok:true,result:{agentProfiles:{},learning:{layers:{}}}});
 await reading;
 assert.equal(api.getSnapshot().graph.id,'other');
 assert.notEqual(api.getSnapshot().graph.documentation,'Old graph instructions');
});
test('registered commands use the exact owner method and UI navigation remains in useApp',async()=>{
 const {api,calls}=await adapter(graph([]),(url,body)=>body?.function==='getAgentChannel'?{ok:true,result:{state:'registered'}}:{ok:true,result:[]});
 const result=await api.executeAction('getAgentChannel',{act:fn=>fn()},'codex');assert.equal(result.state,'registered');
 assert.equal(calls.filter(row=>row.body?.function==='getAgentChannel')[0].body.args[0],'codex');
 const routes=[];api.executeAction('ui.go',{go:route=>routes.push(route)},'canvas');assert.deepEqual(routes,['canvas']);
 assert.throws(()=>api.executeAction('invented',{act:fn=>fn()}),/Unknown action/);
});

// Pinned outputs have no session-file owner yet (setPinnedOutput answers not_available): an open item, not a removal.
test('Results export uses the selected node output and preserves CSV quoting',async()=>{
 const file=sessionFile([{id:'node',type:'script.python',title:'Output',params:{kind:'pure',code:''},ports:{source:[],target:[]},position:{x:0,y:0},result:{status:'Done',output:[{value:'a,"b"'}]}},
  {id:'other',type:'script.python',title:'Other',params:{kind:'pure',code:''},ports:{source:[],target:[]},position:{x:0,y:0},result:{status:'Done',output:[{value:'other'}]}}]);
 const {api}=await adapter(graph([]),undefined,file);const exported=await api.exportData('Results','node');
 assert.equal(exported.content,'"value"\r\n"a,""b"""');
});

test('malformed project reads retain confirmed schedule and template lists',async()=>{
 const {api}=await adapter(graph([]),(url,body)=>url==='/api/universal/canvas-op'?{ok:true}:{ok:true,result:[]});
 // Schedules and templates are re-read after a schedule change (refreshProjects now only re-shows the open file).
 await assert.rejects(api.setScheduleEnabled('schedule',true),/invalid schedule or template list/);
 assert.equal(Array.isArray(api.getSnapshot().schedules),true);
 assert.equal(Array.isArray(api.getSnapshot().templates),true);
});

// D-014: graph documentation is a property of the session file, saved by its one owner (session_files).
test('graph documentation retains its established metadata owner after Rest integration',async()=>{
 const {api,calls}=await adapter(graph([]),(url,body)=>{
  if(body?.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body?.function==='getGraphMetadata')return {ok:true,result:{}};
  return {ok:true,result:[]};
 });
 await api.updateGraph('graph',{documentation:'Saved instructions'});
 assert.equal(api.getSnapshot().graph.documentation,'Saved instructions');
 await new Promise(resolve=>setTimeout(resolve,400));  // past the autosave debounce
 const saves=calls.filter(call=>call.url==='/api/session-files'&&call.body.action==='autosave');
 assert.equal(saves.length,1);assert.equal(saves[0].body.document.properties.documentation,'Saved instructions');
 assert.equal(calls.filter(call=>call.body?.function==='setGraphMetadata').length,0,'no second owner');
});

test('host availability has its own read while the Watcher keeps its execution owner',async()=>{
 const {api,calls}=await adapter(graph([]),(url)=>url==='/api/universal/hosts'?{ok:true,operations:[]}:{ok:true,result:[]});
 await assert.rejects(api.checkWatcherSource(),/Add a Watcher node/);
 assert.deepEqual(JSON.parse(JSON.stringify(await api.readHostAvailability())),{ok:true,operations:[]});
 assert.equal(calls.filter(call=>call.url==='/api/universal/hosts').length,1);
});
