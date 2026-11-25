const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

async function researchAdapter(engine='research.weighted'){
 let run={output:[{id:'linked-row',score:0.75}],preset:{criteria:'[]'}},review={items:{}},refused=false;
 let sources=[{sourceId:'real-evidence',excerpt:'original',status:'Included'}];
 const canvas=()=>({root:'canvas',nodes:[{id:'research-node',properties:[
  {label:'engine',value:engine},{label:'research_run',value:JSON.stringify(run)},
  {label:'research_review',value:JSON.stringify(review)}]}],wires:[],
  workshop_scope:{root:'canvas',workshops:[{root:'workshop',is_general:true}]}});
 // D-014: Run goes through the session-file owner; the node's engine (library_engines) is its research owner.
 const file={format:'archhub',version:1,id:'research',title:'Research',nodes:[{id:'research-node',type:engine,title:'Research',
  params:{criteria:'[]',method:'TOPSIS'},ports:{source:[{id:'out',type:'list'}],target:[]},position:{x:0,y:0}}],
  wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom:1},properties:{revision:1}};
 const result=await adapter({signed_in:false},{'/api/universal/canvas':canvas,
  '/api/session-files':body=>body.action==='initial'?{ok:true,document:file,path:'C:/isolated/research.archhub'}
   :body.action==='validate'?{ok:true,document:body.document}
   :body.action==='autosave'?{ok:true,path:body.path,revision:2,document:body.document}
   :body.action==='solve'?{ok:true,results:{},solved:[],stale:[],ms:0}
   :body.action==='run'?{ok:true,succeeded:true,revision:3,results:{'research-node':{status:'Done',output:run.output}}}:{ok:true},
  '/api/universal/workshop':body=>{
   if(body.function==='listTasks')return {ok:true,result:[{id:'work',messages:[{id:'answer',sources}]}]};
   if(body.function==='listAgentsWorking'||body.function==='listApprovals')return {ok:true,result:[]};
   if(refused)return {ok:false,error:'Unknown research kind; existing result retained'};
   if(body.function==='correctAnswerSource'){
    sources=[{...sources[0],...body.args[2]}];return {ok:true,result:{id:'answer',sources,sourceRevisions:[{revision:1,sources}]}};
   }
   if(body.function==='setResearchReview')review={items:{'linked-row':body.args[1].state}};
   return {ok:true,result:{id:'research-node',...run,review}};
  }});
 return {...result,refuse:()=>{refused=true;},setOutput:value=>{run={...run,output:value};}};
}

test('RESEARCHNODES runValuation routes Run to weighted owner and projects graph readback',async()=>{
 const {api,requests}=await researchAdapter();
 assert.equal(api.supportsAction('runValuation'),true);
 const result=await api.runNode('research-node');
 assert.equal(result.results['research-node'].output[0].id,'linked-row');
 assert.equal(api.getSnapshot().graph.nodes[0].output[0].score,0.75);
 const sent=requests.find(row=>row.url==='/api/session-files'&&row.body.action==='run').body;
 assert.deepEqual(sent.roots,['research-node']);assert.equal(sent.document.nodes[0].type,'research.weighted');
});

test('RESEARCHNODES setResearchReview sends item state and restores persisted review',async()=>{
 const {api,requests}=await researchAdapter();
 await api.setResearchReview('research-node',{item:'linked-row',state:'excluded'});
 assert.equal(api.getSnapshot().graph.nodes[0].review.items['linked-row'],'excluded');
 assert.deepEqual(requests.find(row=>row.body?.function==='setResearchReview').body.args,
  ['research-node',{item:'linked-row',state:'excluded'}]);
 await api.setResearchReview('research-node',{usePreset:true});
 assert.deepEqual(requests.filter(row=>row.body?.function==='setResearchReview')[1].body.args,
  ['research-node',{usePreset:true}]);
});

test('RESEARCHNODES runResearchNode uses registered text executor route and confirmed output',async()=>{
 const {api,requests,setOutput}=await researchAdapter('text.ops');setOutput('real text result');
 assert.equal((await api.runNode('research-node')).results['research-node'].output,'real text result');
 assert.equal(api.getSnapshot().graph.nodes[0].output,'real text result');
 const sent=requests.find(row=>row.url==='/api/session-files'&&row.body.action==='run').body;
 assert.deepEqual(sent.roots,['research-node']);assert.equal(sent.document.nodes[0].type,'text.ops');
});

test('RESEARCHNODES runSpecialNode stays hidden with no registered semantic owner',async()=>{
 const {api,requests}=await researchAdapter();const count=requests.length;
 assert.equal(api.supportsAction('runSpecialNode'),false);
 await api.runSpecialNode('translation');
 assert.equal(requests.length,count);
});

test('RESEARCHNODES correctAnswerSource binds exact message and refreshes source revisions',async()=>{
 const {api,requests}=await researchAdapter();
 const corrected=await api.correctAnswerSource('answer',0,{excerpt:'corrected',status:'Corrected'});
 assert.equal(corrected.sourceRevisions[0].revision,1);
 assert.equal(api.getSnapshot().tasks[0].messages[0].sources[0].excerpt,'corrected');
 assert.deepEqual(requests.find(row=>row.body?.function==='correctAnswerSource').body.args,
  ['answer',0,{excerpt:'corrected',status:'Corrected'}]);
});

test('RESEARCHNODES refusal retains confirmed graph output',async()=>{
 const {api,refuse}=await researchAdapter();const before=api.getSnapshot().graph;
 refuse();await assert.rejects(()=>api.runValuation('research-node'),/Unknown research kind/);
 assert.equal(api.getSnapshot().graph,before);
});

async function adapter(account, responses={}){
 const requests=[],events=new Map();
 const window={ARCHHUB_AUTHORITY:{},structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{home_load_ms:60000,token:'local-lease',csrf:'csrf'},
  Uint8Array:globalThis.Uint8Array,dispatchEvent(e){events.get(e.type)?.(e);},addEventListener(name,fn){events.set(name,fn);},AH:{inkSoft:'#888'},crypto:require('node:crypto')};
 window.ArchHubStudioAuthority={create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}};
 const context={window,setTimeout,clearTimeout,document:{hidden:true,addEventListener(){}},
  CustomEvent:class {},sessionStorage:{getItem(){return null;}},URLSearchParams,TextEncoder:globalThis.TextEncoder,AbortSignal:globalThis.AbortSignal,console,
  fetch:async(url,options)=>{
   requests.push({url,body:options.body&&JSON.parse(options.body)});
   let data={ok:true};
   if(url==='/api/universal/canvas')data={root:'canvas',nodes:[],wires:[],
    authorization:{principal:'local-process',display_name:'Local transport'}};
   if(url==='/api/universal/cloud-session')data={...account};
   // Desktop work needs a verified ArchHub account (cd19d5d4); this fixture is signed in.
   if(url==='/api/universal/desktop-access')data={ok:true,admitted:true,state:'admitted',subject:'research-fixture'};
   // The command owner serves the menu catalogue at startup (f8b5feea).
   if(url==='/api/commands')data={commands:[]};
   if(Object.hasOwn(responses,url))data=await (typeof responses[url]==='function'?responses[url](options.body&&JSON.parse(options.body)):responses[url]);
   if(url==='/api/universal/cloud-signin'&&options.body)Object.assign(account,
    {signed_in:true,email:'user@example.test',user_id:'account-1',display_name:'Account user'});
   if(url==='/api/universal/cloud-signout')Object.assign(account,{signed_in:false,email:''});
   return {ok:true,status:200,json:async()=>data};
  }};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/api.js'),'utf8'),context);
 await window.ArchHubAPI.ready;
 return {api:window.ArchHubAPI,requests,window};
}
