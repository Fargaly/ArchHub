const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const base=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const read=name=>fs.readFileSync(path.join(base,name),'utf8');
const pause=()=>new Promise(resolve=>setTimeout(resolve,5));
async function mount(name,props={},server=()=>({ok:true,result:[]})){
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/',runScripts:'outside-only'}),w=dom.window,posts=[];
 Object.defineProperty(w.document,'hidden',{value:true});w.structuredClone=globalThis.structuredClone;w.ARCHHUB_BOOT={home_load_ms:60000,token:'fixture',csrf:'fixture'};
 w.fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;if(body)posts.push({url,body});
  let data={ok:true};
  if(url==='/api/universal/canvas')data={root:'graph',scope:{current:'graph'},nodes:[{id:'node',label:'Actual output',ports:[],properties:[],output:[{value:7}]}],wires:[],catalog:[],workshops:[{root:'workshop'}]};
  else if(url==='/api/universal/workshop')data=await server(body);
  else if(url==='/api/universal/brain-export')data={ok:true,facts:{folders:[{label:'User',facts:[{id:'fact',body:'A real fixture fact',kind:'fact'}]}]}};
  return {ok:data.ok!==false,status:data.ok===false?409:200,json:async()=>data};
 };
 w.ArchHubStudioAuthority={create:({get})=>({load:()=>get('/api/universal/canvas')})};
 for(const f of ['vendor/react.js','vendor/react-dom.js','vendor/babel.js','api.js'])w.eval(read(f));
 await w.ArchHubAPI.ready;
 const R=w.React,api=w.ArchHubAPI,events=[];
 const app={act:fn=>Promise.resolve().then(fn).catch(error=>{events.push(error.message);return null;}),go:route=>events.push(route),show:kind=>events.push(kind),download:()=>{},confirm:()=>{}};
 w.UI={api,A:{},D:{Toggle:()=>null},useApp:()=>app,useData:()=>R.useSyncExternalStore(api.subscribe,api.getSnapshot,api.getSnapshot),
  Btn:({sm,p,ghost,...props})=>R.createElement('button',props),Card:props=>R.createElement('section',props),Chip:props=>R.createElement('span',props),
  Heading:({title,children})=>R.createElement('header',null,title,children),Table:({rows})=>R.createElement('pre',null,JSON.stringify(rows)),
  ResearchReview:()=>null,DecisionResult:()=>null};
 w.AHIcon=()=>null;
 const source={'AgentChannel':'agent-states.jsx','NodeOutput':'agent-states.jsx','Brain':'brain.jsx'}[name];
 w.eval(w.Babel.transform(read(source),{presets:['react']}).code);
 for(const helper of ['UncertainLinks','IntakeRules','BrainControls','BrainSuggestions'])w.UI[helper]??=()=>null;
 const root=w.ReactDOM.createRoot(w.document.getElementById('root'));root.render(R.createElement(w.UI[name],props));
 const until=async predicate=>{for(let i=0;i<200&&!predicate();i++)await pause();assert.ok(predicate(),'render reaches expected state');};
 await until(()=>w.document.querySelector('section,main,div.grid'));
 const button=label=>[...w.document.querySelectorAll('button')].find(b=>b.textContent.trim()===label);
 return {w,api,posts,events,until,button,close(){root.unmount();dom.window.close();}};
}
test('registered channel callback renders the owner error and retries the exact client',async()=>{
 let failures=true;
 const v=await mount('AgentChannel',{id:'codex'},body=>body.action==='agent-channel'?(failures?{ok:false,error:'Client stopped. Restart that client and retry.'}:{ok:true,result:{state:'registered',hooks:{state:'configured'}}}):{ok:true,result:[]});
 try{
  v.button('Check channel').click();await v.until(()=>v.w.document.querySelector('[role="alert"]'));
  assert.match(v.w.document.body.textContent,/Client stopped/);failures=false;
  v.button('Retry channel action').click();await v.until(()=>v.w.document.body.textContent.includes('registered'));
  const reads=v.posts.filter(p=>p.body.function==='getAgentChannel');assert.equal(reads.length,2);assert.deepEqual(JSON.parse(JSON.stringify(reads[0].body.args)),['codex']);
 }finally{v.close();}
});
test('NodeOutput reads real adapter rows and JSON without assuming a synchronous array is a promise',async()=>{
 const v=await mount('NodeOutput',{id:'node'});
 try{await v.until(()=>v.w.document.body.textContent.includes('Output loaded.'));assert.match(v.w.document.body.textContent,/7/);
  v.button('JSON').click();await v.until(()=>v.w.document.querySelector('textarea'));assert.equal(JSON.parse(v.w.document.querySelector('textarea').value)[0].value,7);
 }finally{v.close();}
});
test('Brain refresh projects only facts returned by the existing Brain export owner',async()=>{
 const v=await mount('Brain');try{await v.until(()=>v.w.document.body.textContent.includes('A real fixture fact'));
 assert.equal(v.api.getKnowledgeGraph().nodes[0].type,'Memory');assert.equal(v.api.getKnowledgeGraph().edges.length,0);
 }finally{v.close();}
});
test('unknown command is refused before calling an owner',async()=>{
 const v=await mount('AgentChannel',{id:'codex'});try{const before=v.posts.length;assert.throws(()=>v.api.executeAction('invented',{act:fn=>fn()}),/Unknown action/);assert.equal(v.posts.length,before);}finally{v.close();}
});
