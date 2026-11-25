'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {randomUUID}=require('node:crypto');
const {ReadableStream}=require('node:stream/web');
const {structuredClone}=globalThis;const {setImmediate}=require('node:timers');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
// UI contract fixture only: the real pinned cloud decision has its own backend and installed courts.
function fixture(storage=new Map(),previousView=null){
 const calls=[],events=new Map();
 let signin={phase:'pending'};
 let pendingStatus=null;let access={ok:true,admitted:false,state:'signed_out',subject:null,email:null},refuse=false;
 const file={format:'archhub',version:1,id:'fixture-A',title:'Private A',nodes:[],wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom:1},properties:{revision:1}};
 const localStorage={get length(){return storage.size;},key:i=>[...storage.keys()][i]||null,getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
 const context={console,structuredClone,URL,URLSearchParams,AbortSignal,TextDecoder,TextEncoder,ReadableStream,Headers,Event,
  setTimeout,clearTimeout,setInterval:()=>0,clearInterval(){},requestAnimationFrame:fn=>setTimeout(fn,0),cancelAnimationFrame:clearTimeout,
  CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail;}},
  document:{hidden:true,addEventListener(){},querySelector:()=>null},crypto:{randomUUID},localStorage,
  performance:{getEntriesByType:()=>[{type:'reload'}]},sessionStorage:{getItem:key=>key==='archhub.editView'?previousView:null,setItem(){},removeItem(){}},ARCHHUB_BOOT:{token:'fixture',csrf:'fixture'},
  addEventListener:(name,fn)=>{if(!events.has(name))events.set(name,[]);events.get(name).push(fn);},dispatchEvent:event=>{for(const fn of events.get(event.type)||[])fn(event);},
  fetch:async(url,init={})=>{
   const body=init.body?JSON.parse(init.body):null;calls.push({url,body,headers:new Headers(init.headers)});
   let data={ok:true,result:[],items:[],recent:[],directory:'fixture',sessions:[],messages:[],agents:[],providers:[]},status=200;
   if(url==='/api/universal/desktop-access'){const captured=access;if(pendingStatus)await pendingStatus;data=captured;}
   else if(url==='/api/universal/cloud-signout'){access={ok:true,admitted:false,state:'signed_out',subject:null,email:null};data=access;}
   else if(url==='/api/universal/cloud-signin')data={ok:true,...signin};
   else if(refuse){status=503;data={ok:false,code:'desktop_access_required',state:'unavailable',error:'Connection unavailable'};}
   else if(url==='/api/commands')data={commands:[]};
   else if(url==='/api/session-files'&&body?.action==='initial')data={ok:true,document:access.subject==='B'?{...structuredClone(file),id:'fixture-B',title:'Untitled'}:structuredClone(file),path:access.subject==='B'?'':'C:/fixture/A.archhub'};
   else if(url==='/api/session-files'&&body?.action==='validate')data={ok:true,document:body.document};
   else if(url==='/api/session-files'&&['save','autosave'].includes(body?.action))data={ok:true,document:body.document,path:body.path||'C:/fixture/new.archhub',revision:2};
   else if(url==='/api/universal/settings-action'&&body?.function==='readLibraryCollapsed')data={ok:true,result:{libraryCollapsed:[]}};
   else if(url==='/api/universal/settings-action'&&body?.function==='readKeybindings')data={ok:true,result:{keybindings:{},keyboardCommands:[]}};
   else if(url==='/api/universal/settings-action'&&body?.function==='readWatching')data={ok:true,result:{capability:true,reason:'',watching:access.subject==='A'?[{id:'grant-0001-abcdef',state:'shared',updated:null,expires:null}]:[]}};
   if(url==='/api/router/chat'&&status===200)return {ok:true,status,body:new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode('data: '+JSON.stringify({result:{ok:true,answer:'Fixture streamed answer'}})+'\n\n'));controller.close();}})};
   return {ok:status<400,status,headers:new Headers(),json:async()=>data};
  }};
 context.window=context;vm.createContext(context);
 for(const name of ['studio-authority.js','api.js'])vm.runInContext(fs.readFileSync(path.join(studio,name),'utf8'),context,{filename:name});
 return {context,api:context.ArchHubAPI,calls,storage,signin:value=>{signin=value;},holdStatus:()=>{let release;pendingStatus=new Promise(resolve=>{release=()=>{pendingStatus=null;resolve();};});return release;},set:subject=>{access=subject?{ok:true,admitted:true,state:'admitted',subject,email:subject+'@example.test'}:{ok:true,admitted:false,state:'unavailable',subject:null,email:null};},refuse:value=>{refuse=value;},close:()=>context.dispatchEvent(new Event('offline'))};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('initial desktop admission does not load work or expose a document',async()=>{
 const f=fixture();await settle();assert.equal(f.api.getSessionDocument(),null);assert.equal(f.api.getSnapshot().desktopAccess.admitted,false);
 assert(f.calls.every(call=>call.url==='/api/universal/desktop-access'));
 f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;
 assert.equal(f.api.getSessionDocument().id,'fixture-A');
 assert(f.calls.filter(call=>!call.url.endsWith('/desktop-access')).every(call=>call.headers.get('X-ArchHub-Desktop-Subject')==='A'));
 f.close();
});
test('disconnect preserves dirty document and rejects edits without replaying a write on reconnect',async()=>{
 const f=fixture();f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;
 await f.api.addNote('UNSAVED A',{x:10,y:20});const held=f.api.getSessionDocument();f.close();f.set(null);
 assert.equal(f.api.getSessionDocument(),null);await assert.rejects(f.api.addNote('DENIED',{x:0,y:0}));
 const writes=f.calls.filter(call=>['save','autosave'].includes(call.body?.action)).length;
 f.set('A');await f.api.refreshDesktopAccess(true);assert.deepEqual(f.api.getSessionDocument(),held);
 assert.equal(f.calls.filter(call=>['save','autosave'].includes(call.body?.action)).length,writes);f.close();
});
test('real refusal code locks immediately, and account switching quarantines old document and view',async()=>{
 const f=fixture();f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;
 await f.api.addNote('PRIVATE A',{x:1,y:1});f.api.rememberDesktopView({route:'settings/Projects'});const held=f.api.getSessionDocument();
 f.refuse(true);await assert.rejects(f.api.listWorkspaces());assert.equal(f.api.getSnapshot().desktopAccess.admitted,false);f.refuse(false);
 f.set('B');await f.api.refreshDesktopAccess(true);assert.notEqual(f.api.getSessionDocument().id,held.id);assert(!JSON.stringify(f.api.getSnapshot()).includes('PRIVATE A'));
 f.set('A');await f.api.refreshDesktopAccess(true);assert.deepEqual(f.api.getSessionDocument(),held);assert.equal(f.api.readDesktopView().route,'settings/Projects');f.close();
});

test('closing A then launching B preserves A recovery bytes without automatically exposing them',async()=>{
 const storage=new Map(),a=fixture(storage);a.set('A');await a.api.refreshDesktopAccess(true);await a.api.ready;
 await a.api.addNote('PRIVATE CLOSED A',{x:1,y:1});a.close();a.context.dispatchEvent(new Event('pagehide'));
 const saved=[...storage].filter(([key])=>key.startsWith('archhub.draft.'));assert(saved.length);assert(saved.some(([_key,value])=>value.includes('PRIVATE CLOSED A')));
 const oldView=JSON.parse(saved[0][1]).view;const b=fixture(storage,oldView);b.set('B');await b.api.refreshDesktopAccess(true);await b.api.ready;await b.api.recoverLocalWork();
 assert(!JSON.stringify(b.api.getSnapshot()).includes('PRIVATE CLOSED A'));
 for(const [key,value]of saved)assert.equal(storage.get(key),value);assert(!b.calls.some(call=>call.body?.action==='edit_state'&&call.body.retire===oldView));b.close();
});

test('the shipped streamed composer carries the subject and consumes a real refusal code',async()=>{
 const f=fixture();f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;
 assert.equal((await f.api.sendToBaboom('Synthetic stream')).answer,'Fixture streamed answer');
 assert.equal(f.calls.find(call=>call.url==='/api/router/chat').headers.get('X-ArchHub-Desktop-Subject'),'A');
 await f.api.addNote('Pagehide subject',{x:1,y:1});f.context.dispatchEvent(new Event('pagehide'));assert.equal(f.calls.findLast(call=>call.body?.action==='autosave').headers.get('X-ArchHub-Desktop-Subject'),'A');
 f.refuse(true);await assert.rejects(f.api.sendToBaboom('Refused stream'));assert.equal(f.api.getSnapshot().desktopAccess.admitted,false);f.close();
});
test('a late prior status cannot unlock after signout or overwrite a newer account',async()=>{
 const f=fixture();f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;
 const release=f.holdStatus(),old=f.api.refreshDesktopAccess(true);await settle();
 const logout=f.api.signIn(false);await settle();release();await Promise.all([old,logout]);assert.equal(f.api.getSnapshot().desktopAccess.admitted,false);
 f.set('B');await f.api.refreshDesktopAccess(true);assert.equal(f.api.getSnapshot().desktopAccess.subject,'B');f.close();
});

test('locked sign-in reports dispatch failure safely and retries without granting access',async()=>{
 const f=fixture();await settle();
 f.signin({phase:'failed',error_code:'browser_open_failed',error:'private provider details'});
 await f.api.signIn(true);
 const access=()=>f.api.getSnapshot().desktopAccess;
 assert.match(access().notice,/default browser.*Retry/);
 assert.equal(access().signingIn,false);
 f.signin({phase:'waiting'});
 await f.api.signIn(true);
 assert.equal(access().notice,'');
 assert.equal(access().signingIn,true);
 assert.equal(access().admitted,false);
 assert.equal(f.api.getSessionDocument(),null);
 assert.equal(f.calls.filter(c=>c.url.endsWith('/cloud-signin')&&c.body).length,2);
 f.signin({phase:'failed',error:'private provider details'});
 await f.api.refreshDesktopAccess(true);
 assert.equal(access().notice,'Sign-in failed. Choose Retry to sign in again.');
});

test('first admitted Home reads shared-with-you once per account, and an account switch reads again',async()=>{
 const f=fixture();f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;await settle();await settle();
 const reads=()=>f.calls.filter(call=>call.body?.function==='readWatching');
 assert.equal(reads().length,1,'first Home must read shared sessions without opening Account');
 assert.equal(reads()[0].headers.get('X-ArchHub-Desktop-Subject'),'A');
 assert.deepEqual(f.api.getSnapshot().watching.watching.map(row=>row.id),['grant-0001-abcdef']);
 await f.api.refreshDesktopAccess(true);await f.api.refreshDesktopAccess(true);await settle();
 assert.equal(reads().length,1,'the same account does not read again in the background');
 f.set('B');await f.api.refreshDesktopAccess(true);await f.api.ready;await settle();await settle();
 assert.equal(reads().length,2);assert.equal(reads()[1].headers.get('X-ArchHub-Desktop-Subject'),'B');
 assert.deepEqual(f.api.getSnapshot().watching.watching,[],'B never sees A\'s shared sessions');
 f.close();
});

test('optional 15000 ms update status timeout preserves a concurrent workspace read and its admitted subject', async t => {
 const f=fixture();
 t.after(f.close);
 f.set('A'); await f.api.refreshDesktopAccess(true); await f.api.ready;
 const fetch=f.context.fetch;
 let release;
 const hold=new Promise(resolve=>{release=resolve;});
 const observed=[];
 const timeouts=[];
 let aborted;
 f.context.AbortSignal=class extends AbortSignal {
  static timeout(ms){timeouts.push(ms);return AbortSignal.timeout(ms);}
 };
 f.context.fetch=async(url,init)=>{
  if(url==='/api/universal/workspace-roots'){
   observed.push(new Headers(init.headers).get('X-ArchHub-Desktop-Subject'));
   await hold;
   return {ok:true,status:200,headers:new Headers(),json:async()=>({ok:true,roots:[{root_id:'qa',label:'QA workspace'}]})};
  }
  if(url==='/api/universal/application-update'){
   observed.push(new Headers(init.headers).get('X-ArchHub-Desktop-Subject'));
   assert(init.signal instanceof AbortSignal);
   await new Promise((resolve,reject)=>init.signal.addEventListener('abort',()=>{aborted=init.signal.reason;reject(aborted);},{once:true}));
  }
  return fetch(url,init);
 };
 // Native AbortSignal timers do not keep the Node test process alive.
 const keepAlive=setTimeout(()=>{},20000);
 t.after(()=>clearTimeout(keepAlive));
 const workspace=f.api.listWorkspaces();
 try{
  await f.api.refreshApplicationUpdate().catch(error=>{assert.equal(error.cause?.name,'TimeoutError');});
 } finally {release();}
 const items=await workspace;
 assert.equal(aborted?.name,'TimeoutError');
 assert.equal(items.find(row=>row.id==='qa').name,'QA workspace');
 assert(timeouts.length>0 && timeouts.every(ms=>ms===15000));
 assert(observed.length>=2 && observed.every(subject=>subject==='A'));
 assert.equal(f.api.getSnapshot().desktopAccess.subject,'A');
 assert.equal(f.api.getSnapshot().desktopAccess.admitted,true);
});

test('a rejected network request preserves admission and subsequent workspace reads',async t=>{
 const f=fixture();
 t.after(f.close);
 f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;
 const fetch=f.context.fetch;
 f.context.fetch=()=>Promise.reject(new TypeError('fixture network failure'));
 await assert.rejects(f.api.listWorkspaces());
 assert.equal(f.api.getSnapshot().desktopAccess.admitted,true);
 assert.equal(f.api.getSnapshot().desktopAccess.subject,'A');
 f.context.fetch=fetch;
 assert(Array.isArray(await f.api.listWorkspaces()));
});

for(const state of ['signed_out','session_invalid']){
 test('authoritative '+state+' refusal locks the previously admitted workspace',async t=>{
  const f=fixture();t.after(f.close);
  f.set('A');await f.api.refreshDesktopAccess(true);await f.api.ready;
  f.context.fetch=async()=>({ok:false,status:401,headers:new Headers(),
   json:async()=>({ok:false,code:'desktop_access_required',state,error:'Fixture access refused'})});
  await assert.rejects(f.api.listWorkspaces(),/Fixture access refused/);
  const access=f.api.getSnapshot().desktopAccess;
  assert.equal(access.admitted,false);assert.equal(access.state,state);
  assert.equal(f.api.getSessionDocument(),null);
 });
}
