const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
async function adapter(canvas,serve=()=>({ok:true,result:[]})){
 const calls=[],listeners=new Map();
 const window={structuredClone:globalThis.structuredClone,crypto:require('node:crypto').webcrypto,
  ARCHHUB_BOOT:{token:'fixture',csrf:'fixture'},document:{hidden:true,addEventListener(){}},
  addEventListener(name,fn){listeners.set(name,fn);},dispatchEvent(){},
  ArchHubStudioAuthority:{create:({get})=>({load:()=>get('/api/universal/canvas')})}};
 const fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
  const data=url==='/api/universal/canvas'?canvas:await serve(url,body);
  return {ok:data.ok!==false,status:data.ok===false?409:200,json:async()=>data};
 };
 const context={window,document:window.document,fetch,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
  setTimeout,clearTimeout,setInterval,clearInterval,URLSearchParams,AbortSignal:globalThis.AbortSignal,console};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../nodelang/studio/api.js'),'utf8'),context);
 await window.ArchHubAPI.ready;await new Promise(resolve=>setTimeout(resolve,0));
 return {api:window.ArchHubAPI,calls};
}
const graph=nodes=>({root:'graph',scope:{current:'graph'},nodes,wires:[],catalog:[],workshops:[{root:'workshop'}]});
test('multi-node failure restores prior successful edits using the existing property owner',async()=>{
 const property=(id,value)=>({id,label:id,ports:[],properties:[{label:'value',value,relation:id+'-value',editable:true}]});
 const canvas=graph([property('one',1),property('two',2)]),writes=[];
 const {api}=await adapter(canvas,(url,body)=>{
  if(url==='/api/universal/set-property'){
   writes.push([body.relation,body.value]);
   if(body.relation==='two-value')return {ok:false,error:'Second owner refused'};
   canvas.nodes[0].properties[0].value=Number(body.value);return {ok:true};
  }
  return {ok:true,result:[]};
 });
 await assert.rejects(api.setMultipleNodeParameters(['one','two'],'value',9),/Second owner refused.*rolled back/);
 assert.deepEqual(writes,[['one-value','9'],['two-value','9'],['one-value','1']]);
 assert.equal(canvas.nodes[0].properties[0].value,1);assert.equal(canvas.nodes[1].properties[0].value,2);
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
 const {api}=await adapter(canvas,(url,body)=>{
  if(body?.function==='getAgentSurface')return held;
  if(body?.function==='getGraphMetadata')return {ok:true,result:{documentation:'Old graph instructions'}};
  return {ok:true,result:[]};
 });
 const reading=api.refreshAgentSurface();
 canvas.root='other';canvas.scope.current='other';
 await api.selectGraph('other');
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

test('Results export uses the selected pinned output and preserves CSV quoting',async()=>{
 const canvas=graph([{id:'node',label:'Output',ports:[],pinned:true,properties:[{label:'pinned_output',value:JSON.stringify([{value:'a,"b"'}])}],output:[{value:'original'}]}]);
 const {api}=await adapter(canvas);const exported=await api.exportData('Results','node');
 assert.equal(exported.content,'"value"\r\n"a,""b"""');
});

test('malformed project reads retain confirmed schedule and template lists',async()=>{
 const {api}=await adapter(graph([]),(url,body)=>url==='/api/universal/canvas-op'?{ok:true}:{ok:true,result:[]});
 await assert.rejects(api.refreshProjects(),/invalid schedule or template list/);
 assert.equal(Array.isArray(api.getSnapshot().schedules),true);
 assert.equal(Array.isArray(api.getSnapshot().templates),true);
});

test('graph documentation retains its established metadata owner after Rest integration',async()=>{
 const {api,calls}=await adapter(graph([]),(url,body)=>{
  if(body?.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body?.function==='getGraphMetadata')return {ok:true,result:{documentation:'Saved instructions'}};
  return {ok:true,result:[]};
 });
 await api.updateGraph('graph',{documentation:'Saved instructions'});
 assert.equal(calls.filter(call=>call.body?.function==='setGraphMetadata').length,1);
 assert.equal(api.getSnapshot().graph.documentation,'Saved instructions');
});

test('host availability has its own read while the Watcher keeps its execution owner',async()=>{
 const {api,calls}=await adapter(graph([]),(url)=>url==='/api/universal/hosts'?{ok:true,operations:[]}:{ok:true,result:[]});
 await assert.rejects(api.checkWatcherSource(),/Add a Watcher node/);
 assert.deepEqual(JSON.parse(JSON.stringify(await api.readHostAvailability())),{ok:true,operations:[]});
 assert.equal(calls.filter(call=>call.url==='/api/universal/hosts').length,1);
});
