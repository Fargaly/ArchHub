const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {transformSync}=require('esbuild');
const {setImmediate}=require('node:timers');
const {structuredClone}=globalThis;
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');

test('the existing Task used by Workshop and Board renders runtime facts and honest flags',()=>{
 const window={ArchHubAPI:{executeAction:()=>{}},UI:{A:{warn:'#fc0'},D:{dot:()=>null},
  useApp:()=>({}),Av:()=>null,Btn:()=>null,Card:()=>null,Chip:()=>null,Composer:()=>null,ApprovalCard:()=>null,Empty:()=>null}};
 vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio,'ds_workshop3.jsx'),'utf8'),{loader:'jsx'}).code,{window,React});
 const task={id:'work:fixture',title:'Existing Work',status:'WIP',owner:'codex',steps:[{status:'done'},{status:'pending'}],activity:{
  sessions:[{provider:'codex',session:'codex-fixture',tool:'apply_patch',file:'01.APP/OWNED.py',state:'working'},
   {provider:'claude',session:'claude-fixture',tool:'Edit',file:'01.APP/OWNED.py',state:'turn_ended'}],
  ownership:'known',touched_after_install:true,stale:true,limited:false,unavailable:false}};
 const html=renderToStaticMarkup(React.createElement(window.UI.Task,{task,on:true,select:()=>{}}));
 assert.match(html,/data-agent-activity/);assert.match(html,/codex · apply_patch · 01.APP\/OWNED.py · Working/);
 assert.match(html,/claude · Edit · 01.APP\/OWNED.py · Turn ended/);
 assert.match(html,/Touched after install/);assert.match(html,/Re-verify row status/);
 assert.match(html,/draggable="true"/);assert.match(html,/aria-selected="true"/);
 assert.match(html,/aria-valuenow="1"/);assert.match(html,/aria-valuemax="2"/);
 assert.doesNotMatch(html,/Installed|Reported done/);
 const unknown=renderToStaticMarkup(React.createElement(window.UI.Task,{task:{...task,activity:{sessions:[],ownership:'unknown',limited:true}},select:()=>{}}));
 assert.match(unknown,/Activity unknown · no owned files/);assert.match(unknown,/Observation incomplete/);
});

test('the existing five-second timer refreshes Work rows while provider discovery is pending',async()=>{
 let observed='tool-a', hold=false, release;
 const timers=[];
 const binding={root:'app:workshop',is_general:true};
 const canvas={ok:true,root:'graph:fixture',graph_id:'fixture',nodes:[],revision:1,
  workshop_scope:{root:'graph:fixture',workshops:[binding]}};
 const window={structuredClone,crypto:require('node:crypto').webcrypto,AH:{inkSoft:'#999'},
  ARCHHUB_BOOT:{home_load_ms:60000,token:'fixture',csrf:'fixture'},
  addEventListener:()=>{},dispatchEvent:()=>{},clearInterval:()=>{},
  setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length;},
  ArchHubStudioAuthority:{create:({get})=>({load:()=>get('/api/universal/canvas')})}};
 const context=vm.createContext({window,console,setTimeout,clearTimeout,AbortSignal,URLSearchParams,CustomEvent:class{},
  document:{hidden:false,addEventListener:()=>{}},fetch:async(url,options)=>{
   if(url==='/api/universal/providers'&&hold)await new Promise(resolve=>{release=resolve;});
   const body=options?.body?JSON.parse(options.body):{};
   const result=url==='/api/universal/canvas'?canvas:url==='/api/universal/providers'?{providers:[]}:
    url==='/api/universal/mods'?{ok:true,mods:{rows:[]}}:
    body.function==='listTasks'?{ok:true,result:[{id:'work:fixture',title:'Work',activity:{sessions:[{tool:observed}]}}]}:
    body.function==='listWorkshopMessages'?{ok:true,result:{messages:[]}}:
    {ok:true,result:[]};
   return {ok:true,status:200,json:async()=>result};
  }});
 vm.runInContext(fs.readFileSync(path.join(studio,'api.js'),'utf8'),context);
 const api=window.ArchHubAPI;
 await api.ready;
 const unsubscribe=api.subscribe(()=>{});
 await api.listTasks();
 assert.equal(api.getSnapshot().tasks[0].activity.sessions[0].tool,'tool-a');
 // Finish boot discovery before holding its next provider request.
 for(let i=0;i<20;i++)await new Promise(resolve=>setImmediate(resolve));
 hold=true;
 const timer=timers.findLast(row=>row.ms===5000);
 const first=timer.fn();
 for(let i=0;i<20&&!release;i++)await new Promise(resolve=>setImmediate(resolve));
 assert.equal(typeof release,'function');
 observed='tool-b';
 await timer.fn();
 assert.equal(api.getSnapshot().tasks[0].activity.sessions[0].tool,'tool-b');
 hold=false;release();await first;
 unsubscribe();
});
