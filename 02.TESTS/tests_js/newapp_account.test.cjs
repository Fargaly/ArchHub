const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

async function adapter(account, responses={}){
 const requests=[],events=new Map();
 const window={ARCHHUB_AUTHORITY:{},structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{token:'local-lease',csrf:'csrf'},
  Uint8Array:globalThis.Uint8Array,dispatchEvent(e){events.get(e.type)?.(e);},addEventListener(name,fn){events.set(name,fn);},AH:{inkSoft:'#888'},crypto:require('node:crypto')};
 window.ArchHubStudioAuthority={create:({get})=>({load:()=>get('/api/universal/canvas')})};
 const context={window,document:{hidden:true,addEventListener(){}},
  CustomEvent:class {},sessionStorage:{getItem(){return null;}},URLSearchParams,TextEncoder:globalThis.TextEncoder,AbortSignal:globalThis.AbortSignal,console,
  fetch:async(url,options)=>{
   requests.push({url,body:options.body&&JSON.parse(options.body)});
   let data={ok:true};
   if(url==='/api/universal/canvas')data={root:'canvas',nodes:[],wires:[],
    authorization:{principal:'local-process',display_name:'Local transport'}};
   if(url==='/api/universal/cloud-session')data={...account};
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

test('unfinished controls use actual adapter availability without invoking an action',async()=>{
 const {api,requests}=await adapter({signed_in:false});const count=requests.length;
 assert.equal(api.supportsAction('startVoiceInput'),false);
 assert.equal(api.supportsAction('signInProvider'),false);
 assert.equal(api.supportsAction('reviewProofRow'),false);
 assert.equal(api.supportsAction('signIn'),true);
 assert.equal(api.supportsAction('setProviderEnabled'),true);
 assert.equal(api.supportsAction('missing-action'),false);
 assert.equal(api.supportsAction('archiveActivity'),true);
 assert.equal(api.supportsAction('ensureDependency'),true);
 assert.equal(api.supportsAction('decline'),false);
 assert.equal(api.supportsAction('approve','session'),false);
 for(const name of ['runValuation','setApprovalRubric','correctAnswerSource','setResearchReview','stampOutput','runSpecialNode','setTranscriptPass','startVoiceInput','stopVoiceInput','speak','setDesktopProgram','offerDesktopAction','prepareDesktopAction','settleTimesheet','postponeApproval','resumeApproval','contestDecision','setScheduleResponsibility','reviewScheduledWork','runResearchNode','importHostSkill','inspectConnectorBundle','configureConnectorBundle','installConnectorBundle','setHostSkillEnabled','auditHostSkill','refreshApproval','addDimension','reviewProofRow','setWatcherView','signInProvider','editWall','addMark','addComment','proposeWatcherEdit','discardWatcherChanges','setWatcherHost','changePlan'])assert.equal(api.supportsAction(name),false,name);
 assert.equal(requests.length,count);
});

test('unfinished controls and modal launchers are omitted from the rendered design',async()=>{
 const {api}=await adapter({signed_in:false},{'/api/universal/providers':{providers:[{id:'codex',name:'Codex',enabled:true,signedIn:true}]}});
 await api.listProviders();
 const {JSDOM}=require('jsdom');
 const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,studio=path.join(__dirname,'../../01.APP/nodelang/studio');
 const snapshot={...api.getSnapshot(),approvals:[{id:'review',title:'Review',status:'pending',kind:'model',rows:[]}],connections:[{id:'youtube',name:'YouTube',connected:true}],hostSkills:[]};
 w.ArchHubAPI={...api,getSnapshot:()=>snapshot};w.matchMedia=()=>({matches:false});
 for(const name of ['vendor/react.js','vendor/react-dom.js','vendor/babel.js'])w.eval(fs.readFileSync(path.join(studio,name),'utf8'));
 for(const name of ['tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx','ds_baboom.jsx','ds_settings3.jsx','workflow-states.jsx','agent-states.jsx','answer-widgets.jsx'])w.eval(w.Babel.transform(fs.readFileSync(path.join(studio,name),'utf8'),{presets:['react']}).code);
 const root=w.ReactDOM.createRoot(w.document.getElementById('root'));
 const render=(component,props={})=>w.ReactDOM.flushSync(()=>root.render(w.React.createElement(w.UI.Ctx.Provider,{value:{act:fn=>fn()}},w.React.createElement(component,props))));
 try{
  render(w.UI.Providers);
  assert.equal(w.document.querySelector('[aria-label="Codex signed in"]'),null);
  assert.ok(w.document.querySelector('[aria-label="Codex enabled"]'));
  render(w.UI.Composer);
  assert.equal(w.document.querySelector('[title="Talk · F2"]'),null);
  assert.ok(w.document.querySelector('[aria-label="Send ↵"]'));
  render(w.UI.ApprovalCard,{id:'review'});
  assert.doesNotMatch(w.document.body.textContent,/Decline|Postpone|Approve similar/);
  assert.match(w.document.body.textContent,/Approve once/);
  render(w.UI.Storage);
  assert.match(w.document.body.textContent,/Archive old activity/);
  assert.match(w.document.body.textContent,/Back up now/);
  render(w.UI.Connections);
  assert.equal(w.document.querySelector('[aria-label="YouTube read"]'),null);
  assert.equal(w.document.querySelector('[aria-label="YouTube reply"]'),null);
  assert.equal(w.document.querySelector('[aria-label="YouTube post"]'),null);
  assert.ok(w.document.querySelector('[aria-label="Open"]'));
  render(w.UI.HomeAwareness);
  assert.doesNotMatch(w.document.body.textContent,/Timesheet draft/);
  render(w.UI.HostSkills);
  assert.equal(w.document.querySelector('[aria-label="Import skill"]'),null);
  render(w.UI.ActionEvidence,{id:'review'});
  assert.doesNotMatch(w.document.body.textContent,/Request another review/);
 }finally{root.unmount();dom.window.close();}
});

test('OPS projects actions call their owner and retain confirmed state on refusal',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas-op':body=>{
  if(body.op==='add_interface_element')return {ok:true,result:{id:'ui-real'}};
  if(body.op==='project_state')return {ok:true,result:{versions:[],modelReview:{operation:'',results:[],issues:[]},dismissed:[]}};
  return {ok:false,error:'Refresh the actual owner and retry.'};
 }});
 const made=await api.addInterfaceElement('Button');
 assert.equal(made.id,'ui-real');
 assert.deepEqual(requests.find(r=>r.body?.op==='add_interface_element').body.args,['Button']);
 const before=api.getSnapshot().graph;
 await assert.rejects(()=>api.saveGraphVersion(),/actual owner/);
 assert.equal(api.getSnapshot().graph,before);
});

test('OPS compatible nodes use confirmed socket metadata and converter calls preserve wire identity',async()=>{
 const endpoint={id:'source',side:'out',port:'socket'};
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas':{root:'canvas',nodes:[{id:'source',properties:[],ports:[{id:'socket',side:'source',value_type:'text'}]}],wires:[]},
  '/api/universal/canvas-op':body=>({ok:true,result:body.op==='library_ports'?[{id:'text-item',title:'Text node',ports:{target:[{id:'in',type:'text'}]}},{id:'number-item',title:'Number node',ports:{target:[{id:'in',type:'number'}]}}]:{id:'actual-node'}})});
 await api.refreshLibraryPorts();assert.deepEqual(Array.from(api.compatibleNodes(endpoint),r=>r.id),['text-item']);
 await api.addCompatibleNode(endpoint,'text-item',{x:10,y:20});await api.insertConvert({id:'wire-real'});
 assert.deepEqual(requests.find(r=>r.body?.op==='add_compatible_node').body.args,[endpoint,'text-item',{x:10,y:20}]);
 assert.deepEqual(requests.find(r=>r.body?.op==='insert_convert').body.args,['wire-real']);
});

test('OPS history review community and MCP project the returned owner data',async()=>{
 const metadata={versions:[{id:'version-1'}],modelReview:{operation:'Naming Check',results:[{detail:'Actual result'}],issues:[]},dismissed:['suggestion']};
 const community={peers:[{id:'peer',subscribed:true}],patterns:[]};
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas-op':body=>{
  if(body.op==='project_state')return {ok:true,result:metadata};
  if(body.op==='mcp_servers')return {ok:true,result:[{id:'server',status:'Negotiated',tools:[]}]};
  if(['community_state','subscribe_community','review_community_pattern'].includes(body.op))return {ok:true,result:community};
  if(body.op==='review_model')return {ok:true,result:{run:{ran:1,revision:9,results:{node:'Checked'}},modelReview:metadata.modelReview}};
  if(body.op==='import_mcp_tool')return {ok:false,error:'Open this admitted tool in its Workshop work'};
  return {ok:true,result:{id:'confirmed'}};
 }});
 await api.saveGraphVersion();await api.restoreGraphVersion('version-1');
 assert.equal(api.getSnapshot().graph.versions[0].id,'version-1');
 await api.reviewModel('Naming Check');assert.equal(api.getSnapshot().modelReview.results[0].detail,'Actual result');
 await api.updateReviewIssue('issue',{status:'Closed'});await api.dismissSuggestion('suggestion');
 await api.subscribeCommunity('peer');await api.reviewCommunityPattern('pattern','Accept');
 assert.equal(api.getSnapshot().community.peers[0].subscribed,true);
 await api.discoverMcpTools('server','Tools');await api.reconnectMcp('server');
 assert.equal(api.getSnapshot().mcpServers[0].id,'server');
 await assert.rejects(()=>api.importMcpTool('server','tool'),/Workshop work/);
 const operations=requests.filter(r=>r.body?.op).map(r=>r.body.op);
 for(const name of ['save_graph_version','restore_graph_version','review_model','update_review_issue','dismiss_suggestion','subscribe_community','review_community_pattern','discover_mcp_tools','reconnect_mcp','import_mcp_tool'])assert.ok(operations.includes(name),name);
});

test('OPS mod actions preserve the native review digest and refresh from the package owner',async()=>{
 const calls=[];
 const mod={id:'rows',name:'Rows',nodes:[],enabled:true};
 const {api}=await adapter({signed_in:false},{'/api/universal/mods':body=>{
  calls.push(body);
  if(body.action==='browse')return {ok:true,path:'C:/FIXTURE/PACKAGE'};
  if(body.action==='review')return {ok:true,review:{...mod,digest:'actual-manifest-digest'}};
  return {ok:true,mod,mods:{rows:body.action==='remove'?[]:[mod]}};
 }});
 const review=await api.inspectMod();await api.installMod(review.id);
 assert.deepEqual(calls.find(r=>r.action==='install'),{action:'install',path:'C:/FIXTURE/PACKAGE',reviewed_digest:'actual-manifest-digest'});
 await api.retryMod('rows');await api.setModEnabled('rows',false);await api.removeMod('rows');
 assert.equal(api.getSnapshot().mods.length,0);
 for(const action of ['browse','review','install','retry','enable','remove'])assert.ok(calls.some(r=>r.action===action),action);
});

test('OPS research reads captured content checks license and saves the actual decision',async()=>{
 let row={id:'source',title:'Source',source:'C:/FIXTURE/LICENSE.md',sha256:'digest',summary:'Actual content',transcript:['MIT License']};
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/social-surface':body=>{
  if(body.op==='check_research_license')row={...row,licenseStatus:'MIT License',licenseEvidence:['MIT License']};
  if(body.op==='save_research_decision')row={...row,...body.args[1],status:'Decision recorded'};
  return {ok:true,result:row,state:{social:{research:[row]}}};
 }});
 await api.readResearchSource(row.source);await api.checkResearchLicense();
 await api.saveResearchDecision({decision:'Learn only',license:'MIT',why:'Use this measured pattern'});
 assert.equal(api.getSnapshot().learning.research.why,'Use this measured pattern');
 assert.equal(api.getSnapshot().docs.find(d=>d.id==='source').bookSource,row.source);
 assert.deepEqual(requests.find(r=>r.body?.op==='read_content_source').body.args,['File',row.source]);
});

test('OPS refused adoption work remains retryable and only a confirmed Work is linked',async()=>{
 let refused=true;
 let row={id:'source',source:'C:/FIXTURE/LICENSE.md',title:'LICENSE',summary:'MIT License',sha256:'source-digest',licenseEvidence:['MIT License']};
 const {api}=await adapter({signed_in:false},{'/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshops:[{root:'room'}]},
  '/api/universal/social-surface':body=>{
   if(body.op==='save_research_decision')row={...row,...body.args[1]};
   if(body.op==='bind_research_work')row={...row,work:body.args[1],status:'Application work queued; not applied'};
   return {ok:true,result:row,state:{social:{research:[row]}}};
  },
  '/api/universal/workshop':body=>({ok:!refused||body.function==='listTasks',error:'Agent unavailable; retry',result:body.function==='listTasks'?[]:{id:'real-work'}})});
 await api.readResearchSource(row.source);
 const decision={decision:'Adopt',license:'MIT',why:'Fit the captured pattern'};
 await assert.rejects(()=>api.saveResearchDecision(decision),/Agent unavailable/);
 assert.equal(api.getSnapshot().learning.research.decision,'Adopt');assert.equal(api.getSnapshot().learning.research.work,undefined);
 refused=false;await api.saveResearchDecision(decision);
 assert.equal(api.getSnapshot().learning.research.work,'real-work');
 assert.match(api.getSnapshot().learning.research.status,/not applied/);
});

test('OPS share and memory proposals return real Workshop tasks rather than invented approvals',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshops:[{root:'room'}]},
  '/api/universal/workshop':body=>({ok:true,result:body.function==='listTasks'?[]:{id:'work-1',status:'queued'}})});
 api.getSnapshot().mods.push({id:'mod-1',name:'Actual package'});
 api.getSnapshot().suggestions.push({id:'suggestion',text:'Actual suggestion'});
 for(const result of [await api.proposeCommunityShare({title:'Pattern',scope:'Office',redact:true}),await api.shareMod('mod-1'),await api.proposeMemory('suggestion')])assert.equal(result.status,'queued');
 assert.equal(api.getSnapshot().approvals.length,0);
 assert.equal(requests.filter(r=>r.body?.function==='sendToBaboom').length,3);
});

test('OPS file picker cancellation and refused sends retain the attachment draft',async()=>{
 let refused=true,picked='C:/FIXTURE/SOURCE.md';
 const file={id:'file-node',name:'SOURCE.md',path:picked,kind:'Project file'};
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshops:[{root:'room'}]},
  '/api/universal/pick-file':()=>({ok:true,path:picked}),
  '/api/universal/canvas-op':body=>({ok:true,result:body.op==='project_files'?[file]:file}),
  '/api/universal/workshop':body=>({ok:!refused||body.function==='listTasks',error:'Choose an available agent',result:body.function==='listTasks'?[]:{id:'work-real'}})});
 const made=await api.addFile();api.addComposerAttachment(made.id);
 await assert.rejects(()=>api.sendToBaboom('Read it'),/available agent/);
 assert.equal(api.getSnapshot().composerAttachments.length,1);
 refused=false;await api.sendToBaboom('Read it');
 assert.equal(api.getSnapshot().composerAttachments.length,0);
 assert.ok(requests.find(r=>r.body?.function==='sendToBaboom').body.args[0].includes(file.path));
 picked='';assert.equal(await api.addFile(),null);
});

test('a local transport lease never becomes the account profile',async()=>{
 const {api}=await adapter({signed_in:false,email:''});
 await api.syncAccount();
 const profile=api.getSnapshot().profile;
 assert.equal(profile.signedIn,false);
 assert.notEqual(profile.id,'local-process');
 assert.notEqual(profile.name,'Local transport');
});

test('one-click sign-in and sign-out project the account owner answer',async()=>{
 const {api,requests}=await adapter({signed_in:false,email:''});
 await api.signIn();
 const profile=api.getSnapshot().profile;
 assert.equal(profile.signedIn,true);
 assert.equal(profile.id,'account-1');
 assert.equal(profile.name,'Account user');
 assert.deepEqual(requests.find(row=>row.url==='/api/universal/cloud-signin'&&row.body).body,{method:'google'});
 await api.signIn(false);
 assert.equal(api.getSnapshot().profile.signedIn,false);
 assert.equal(api.getSnapshot().profile.email,'');
 assert.equal(api.getSnapshot().profile.id,'');
});

test('workspace picker registers the absolute native path and re-reads the catalogue',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/workspace-roots':body=>body?.action==='browse'?{ok:true,path:'C:/WORK'}:{ok:true,roots:[]}});
 await api.addWorkspace();
 const writes=requests.filter(r=>r.url==='/api/universal/workspace-roots').map(r=>r.body);
 const start=writes.findIndex(body=>body?.action==='browse');
 assert.deepEqual(writes.filter(body=>body?.action!=='list'),[{action:'browse'},{action:'register',path:'C:/WORK',privacy:'private',profile:'client'}]);
 assert.equal(writes.at(-1).action,'list');
 assert.ok(start>=0);
});

test('cancelled native folder selection never registers a workspace',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/workspace-roots':{ok:true,path:'',roots:[]}});
 assert.equal(await api.addWorkspace(),null);
 assert.equal(requests.some(r=>r.body?.action==='register'),false);
});

test('Docs retains generated guides and node documentation from the running owner',async()=>{
 const {api}=await adapter({signed_in:false},{'/api/universal/canvas':{root:'canvas',nodes:[],wires:[],documentation:{
  tutorials:[{id:'account-web',title:'Account',description:'Sign in',text:'# Account\nUse browser sign-in.'}],
  nodes:[{id:'node-doc',category:'Get',title:'Read',detail:'Read connected state.'}]
 }}});
 const docs=api.getDocs();
 assert.equal(docs.length,2);
 assert.equal(docs.find(d=>d.id==='account-web').route,'settings/Account');
 assert.deepEqual(Array.from(docs.find(d=>d.id==='account-web').steps),['# Account','Use browser sign-in.']);
 assert.equal(docs.find(d=>d.id==='node-doc').summary,'Read connected state.');
});


test('Canvas facade translates node flags and constrained runs to their real route shapes',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas-op':body=>({ok:true,result:body.op==='run_to_here'?{roots:['upstream','target'],frozen_kept:['held']}:{id:'node',frozen:true,pinned:false}})});
 await api.setNodeFlags('node',{frozen:true});
 const flag=requests.find(row=>row.url==='/api/universal/canvas-op'&&row.body.op==='set_node_flags');
 assert.deepEqual(flag.body,{op:'set_node_flags',args:['node',true,null]});
 await api.runToHere('target');
 assert.deepEqual(requests.find(row=>row.url==='/api/universal/run-graph').body,{roots:['upstream','target']});
});

test('a fully frozen run-to-here plan never falls through to run the whole graph',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas-op':{ok:true,result:{roots:[],frozen_kept:['target']}}});
 await api.runToHere('target');
 assert.equal(requests.some(row=>row.url==='/api/universal/run-graph'),false);
});

test('update status is read from the existing lifecycle and never inferred from graph configuration',async()=>{
 const {api}=await adapter({signed_in:false},{'/api/universal/application-update':{ok:true,
  state:'ready',current_build:'installed',available_build:'next',restart_supported:true,detail:'Verified download'}});
 await api.refreshApplicationUpdate();
 const update=api.getSnapshot().update;
 assert.equal(update.installed,'installed');assert.equal(update.next,'next');
 assert.equal(update.available,true);assert.equal(update.detail,'Verified download');
});

test('check, restart and confirmation use the existing update actions',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/application-update':body=>({ok:true,
  state:body?.action==='reload'?'restarting':body?.action==='acknowledge'?'idle':'ready',current_build:'installed',available_build:body?.action==='acknowledge'?null:'next',restart_supported:true})});
 await api.checkForUpdates();await api.installUpdate();await api.acknowledgeUpdate();
 assert.deepEqual(requests.filter(r=>r.url==='/api/universal/application-update'&&r.body).map(r=>r.body),
  [{action:'check'},{action:'reload'},{action:'acknowledge'}]);
 assert.equal(api.getSnapshot().update.available,false);
});

test('failed update checks and missing desktop lifecycle never offer restart',async()=>{
 for(const status of [{state:'failed',detail:'Feed unreachable',restart_supported:true},
  {state:'ready',available_build:'next',restart_supported:false}]){
  const {api,requests}=await adapter({signed_in:false},{'/api/universal/application-update':{ok:true,current_build:'installed',...status}});
  await api.refreshApplicationUpdate();
  assert.equal(api.getSnapshot().update.available,false);
  await assert.rejects(()=>api.installUpdate());
  assert.equal(requests.some(r=>r.body?.action==='reload'),false);
 }
});

test('a native ready notification refreshes the approved design without the retired transport',async()=>{
 let ready=false;
 const {api,window,requests}=await adapter({signed_in:false},{'/api/universal/application-update':()=>({ok:true,
  state:ready?'ready':'idle',current_build:'installed',available_build:ready?'next':null,restart_supported:true})});
 await api.refreshApplicationUpdate();const before=requests.length;ready=true;
 window.dispatchEvent({type:'archhub:update-ready'});
 for(let tick=0;tick<20&&!api.getSnapshot().update.available;tick++)await new Promise(resolve=>globalThis.setImmediate(resolve));
 assert.equal(api.getSnapshot().update.available,true);
 assert.ok(requests.slice(before).some(r=>r.url==='/api/universal/application-update'&&!r.body));
});

test('a stale status read cannot erase a newer checked release',async()=>{
 let release,hold=false;
 const {api}=await adapter({signed_in:false},{'/api/universal/application-update':body=>
  body?{ok:true,state:'ready',available_build:'next',current_build:'installed',restart_supported:true}:
  hold?new Promise(resolve=>{release=resolve;}):{ok:true,state:'idle',current_build:'installed',restart_supported:true}});
 await api.refreshApplicationUpdate();hold=true;
 const old=api.refreshApplicationUpdate();
 await api.checkForUpdates();
 release({ok:true,state:'idle',current_build:'installed',restart_supported:true});await old;
 assert.equal(api.getSnapshot().update.available,true);assert.equal(api.getSnapshot().update.next,'next');
});

test('a refused restart is not replayed and clears the stale ready offer',async()=>{
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/application-update':body=>body?
  {ok:false,error:'A Workshop job is running'}:{ok:true,state:'ready',available_build:'next',current_build:'installed',restart_supported:true}});
 await api.refreshApplicationUpdate();
 await assert.rejects(()=>api.installUpdate(),/Workshop job/);
 assert.equal(api.getSnapshot().update.available,false);
 await assert.rejects(()=>api.installUpdate(),/Workshop job/);
 assert.equal(requests.filter(r=>r.body?.action==='reload').length,1);
});

// WIRE-projects: targeted real-browser and existing-owner checks.
{
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {spawn}=require('node:child_process');
const studio=path.join(__dirname,'../../01.APP/nodelang/studio');
const compiler={exports:{}};compiler.module={exports:compiler.exports};
vm.runInNewContext(fs.readFileSync(path.join(studio,'vendor/babel.js'),'utf8'),compiler);
const Babel=compiler.exports;
let browser,processHandle,sequence=0;
const pending=new Map();
const fixture=path.resolve(__dirname,'../../FIXTURE');
const profile=path.join(fixture,'BROWSER');
function command(method,params={},sessionId=undefined){
 return new Promise((resolve,reject)=>{
  const id=++sequence;pending.set(id,{resolve,reject});
  browser.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
 });
}
before(async()=>{
 const executable=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
 assert.ok(executable,'An installed headless browser is required; no dependencies are installed.');
 assert.ok(profile.startsWith(fixture+path.sep));fs.mkdirSync(profile,{recursive:true});
 processHandle=spawn(executable,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:['ignore','ignore','pipe']});
 const endpoint=await new Promise((resolve,reject)=>{
  let output='';processHandle.stderr.on('data',chunk=>{output+=chunk;const match=output.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match)resolve(match[1]);});processHandle.once('error',reject);
 });
 browser=new globalThis.WebSocket(endpoint);
 await new Promise((resolve,reject)=>{browser.addEventListener('open',resolve,{once:true});browser.addEventListener('error',reject,{once:true});});
 browser.addEventListener('message',event=>{
  const result=JSON.parse(event.data),request=pending.get(result.id);if(!request)return;
  pending.delete(result.id);if(result.error)request.reject(Error(result.error.message));else request.resolve(result.result);
 });
});
after(async()=>{
 if(browser){const exited=new Promise(resolve=>processHandle.once('exit',resolve));await command('Browser.close');await exited;browser.close();}
 if(fs.existsSync(profile)){assert.ok(path.resolve(profile).startsWith(fixture+path.sep));fs.rmSync(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});}
});
async function screen(files,data,methods='{}'){
 const {targetId}=await command('Target.createTarget',{url:'about:blank'});
 const {sessionId}=await command('Target.attachToTarget',{targetId,flatten:true});
 const evaluate=async expression=>{
  const result=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},sessionId);
  if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
  return result.result?.value;
 };
 const load=async name=>{
  const source=fs.readFileSync(path.join(studio,name),'utf8');
  await evaluate((name.endsWith('.jsx')?Babel.transform(source,{presets:['react']}).code:source)+'\n;void 0;');
 };
 await load('vendor/react.js');await load('vendor/react-dom.js');
 await evaluate(`document.body.innerHTML='<div id="root"></div>'; const testData=${JSON.stringify(data)}; let refused=true; window.ArchHubAPI={getSnapshot:()=>testData,subscribe:()=>()=>{},...(${methods})};`);
 for(const name of ['tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx',...[files].flat()])await load(name);
 await evaluate(`const calls=[],errors=[];const u={act:fn=>Promise.resolve().then(fn).then(result=>result?.ok===false?null:result).catch(failure=>{errors.push(failure.message);return null;}),go:route=>calls.push(['go',route]),show:(...args)=>calls.push(['show',...args]),download:(...args)=>calls.push(['download',...args]),confirm:(title,fn)=>fn()};const root=ReactDOM.createRoot(document.getElementById('root'));function render(Component,props={}){ReactDOM.flushSync(()=>root.render(React.createElement(UI.Ctx.Provider,{value:u},React.createElement(Component,props))));}async function click(element){if(!element)throw Error('Control missing');element.click();await new Promise(resolve=>setTimeout(resolve,25));}`);
 return {evaluate,close:()=>command('Target.closeTarget',{targetId})};
}
test('OPS real browser MCP load errors retry and refused imports preserve the current screen',async()=>{
 const {api}=await adapter({signed_in:false});
 const s=await screen(['answer-widgets.jsx','integration-states.jsx'],api.getSnapshot(),`{
  refreshMcpServers:async()=>{if(refused)throw Error('Reconnect the actual tool server');const rows=[{id:'actual-server',name:'Actual server',status:'Negotiated',tools:[{id:'actual-tool',name:'Actual tool'}]}];testData.mcpServers=rows;return rows;},
  importMcpTool:async()=>{throw Error('Open this tool in its Workshop work');}
 }`);
 try{
  const failure=await s.evaluate(`(async()=>{render(UI.McpTools);await new Promise(resolve=>setTimeout(resolve,30));return document.body.textContent;})()`);
  assert.match(failure,/Reconnect the actual tool server/);
  assert.equal(await s.evaluate(`document.querySelector('[aria-label="Retry"]')?.tagName`),'BUTTON');
  const loaded=await s.evaluate(`(async()=>{refused=false;await click(document.querySelector('[aria-label="Retry"]'));return document.body.textContent;})()`);
  assert.match(loaded,/Actual tool/);
  const result=await s.evaluate(`(async()=>{await click(document.querySelector('[aria-label="Import Actual tool"]'));return {calls,errors};})()`);
  assert.deepEqual(result.calls,[]);assert.match(result.errors[0],/Workshop work/);
 }finally{await s.close();}
});
test('registered graph control keeps the current screen on refusal and opens after confirmation',async()=>{
 const s=await screen('project-tools.jsx',{graphs:[{id:'g',name:'My graph',nodes:[]}],graph:{name:'My graph',versions:[]}},`{selectGraph:async id=>{if(id!=='g')throw Error('Wrong graph');if(refused)throw Error('Graph changed. Refresh and retry.');return {id};}}`);
 try{
  const rejected=await s.evaluate(`(async()=>{render(UI.GraphManager);await click(document.querySelector('button.fill'));return {calls,errors};})()`);
  assert.deepEqual(rejected.calls,[]);assert.match(rejected.errors[0],/Refresh/);
  const accepted=await s.evaluate(`(async()=>{refused=false;await click(document.querySelector('button.fill'));return calls;})()`);
  assert.deepEqual(accepted,[['go','canvas']]);
 }finally{await s.close();}
});
test('Library uses the catalogue identity and closes only after the owner confirms',async()=>{
 const s=await screen('ds_library.jsx',{catalogue:[{id:'definition-id',name:'Readable label',family:'Get',description:'Reads data'}],templates:[],runs:[],graph:{name:'Graph'},mods:[]},`{addNode:async id=>{if(id!=='definition-id')throw Error('Wrong catalogue identity');return refused?{ok:false}:{id:'made'};}}`);
 try{
  const rejected=await s.evaluate(`(async()=>{let closed=0;window.readClosed=()=>closed;render(UI.LibraryShelf,{onClose:()=>closed++});await click(document.querySelector('[aria-label="Add Readable label"]'));return closed;})()`);
  assert.equal(rejected,0);
  const accepted=await s.evaluate(`(async()=>{refused=false;await click(document.querySelector('[aria-label="Add Readable label"]'));return readClosed();})()`);
  assert.equal(accepted,1);
 }finally{await s.close();}
});
test('DS forwards a native button callback exactly once',async()=>{
 const s=await screen('docs.jsx',{docs:[],catalogue:[],bookGlossary:[]});
 try{assert.equal(await s.evaluate(`(async()=>{let activated=0;render(AH_DS.Btn,{onClick:()=>activated++,children:'Press'});await click(document.querySelector('button'));return activated;})()`),1);}
 finally{await s.close();}
});
test('Watcher draws only the confirmed source and exposes retry on failure',async()=>{
 const s=await screen(['ds_home2.jsx','surfaces.jsx'],{watcher:{status:'empty',geometry:{walls:[]}},graph:{name:'Work',nodes:[]},settings:[]},`{checkWatcherSource:async()=>{if(refused)throw Error('Source changed. Run its input again.');testData.watcher={status:'loaded',host:'Actual source',geometry:{walls:[[10,20,30,40]]}};return {lines:{watcher:[[10,20,30,40]]}};}}`);
 try{
  const error=await s.evaluate(`(async()=>{render(UI.Watcher);await click([...document.querySelectorAll('button')].find(b=>b.textContent==='Run to here'));return document.querySelector('[role="alert"]').textContent;})()`);
  assert.match(error,/Source changed/);
  const drawing=await s.evaluate(`(async()=>{refused=false;await click([...document.querySelectorAll('button')].find(b=>b.textContent==='Retry source'));const svg=document.querySelector('svg[aria-label="Actual source"]');return {count:svg.querySelectorAll('path').length,path:svg.querySelector('path').getAttribute('d')};})()`);
  assert.deepEqual(drawing,{count:1,path:'M10 20L30 40'});
 }finally{await s.close();}
});
test('office seat draft does not change billing while typing and requests confirmation before applying',async()=>{
 const s=await screen('project-tools.jsx',{profile:{signedIn:true,id:'owner',plan:'studio'},usage:{seats:2},runs:[],people:[]},`{refreshCompany:async()=>({seat_limit:2}),setAccountSeats:async seats=>{calls.push(['seats',seats]);return {seat_limit:seats};}}`);
 try{
  const result=await s.evaluate(`(async()=>{u.confirm=(title,fn)=>{calls.push(['confirm',title]);return fn();};render(UI.AccountUsage);await new Promise(resolve=>setTimeout(resolve,25));const input=document.querySelector('[aria-label="Office seats"]');input.value='3';input.dispatchEvent(new Event('input',{bubbles:true}));const before=calls.length;input.dispatchEvent(new FocusEvent('focusout',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,25));return {before,calls,value:input.value};})()`);
  assert.equal(result.before,0);
  assert.match(result.calls[0][1],/3 seats/);
  assert.deepEqual(result.calls[1],['seats',3]);
  assert.equal(result.value,'2');
 }finally{await s.close();}
});

async function adapter(canvasSource={root:'g',nodes:[],wires:[]}) {
 const requests=[],w={structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{token:'lease',csrf:'csrf'},addEventListener(){},dispatchEvent(){},AH:{},crypto:require('node:crypto')};
 let fail=false;
 w.ArchHubStudioAuthority={create:({get})=>({load:()=>get('/api/universal/canvas')})};
 vm.runInNewContext(fs.readFileSync(path.join(studio,'api.js'),'utf8'),{window:w,document:{hidden:true,addEventListener(){}},CustomEvent:class{},URLSearchParams,AbortSignal:globalThis.AbortSignal,console,
  fetch:async(url,options)=>{
   const body=options.body&&JSON.parse(options.body);requests.push({url,body});let result={ok:true};
   if(url==='/api/universal/canvas')result=canvasSource;
   if(url==='/api/universal/wire-property')canvasSource.wires.find(wire=>wire.id===body.wire).params=[{label:body.label,relation:'condition-relation',value:body.value}];
   if(url==='/api/universal/set-property')for(const wire of canvasSource.wires)for(const parameter of wire.params||[])if(parameter.relation===body.relation)parameter.value=body.value;
   if(url==='/api/universal/canvas-op')result=fail?{ok:false,error:'Recipe YAML is invalid. Correct it and retry.'}:{ok:true,result:body.op==='project_schedules'||body.op==='list_skills'?[]:{nodes:['n'],wires:[]}};
   return {ok:!fail,status:fail?400:200,json:async()=>result};
  }});
 await w.ArchHubAPI.ready;
 return {api:w.ArchHubAPI,requests,refuse:()=>{fail=true;}};
}

test('YAML reaches the existing owner unchanged and owner rejection remains a rejection',async()=>{
 const {api,requests,refuse}=await adapter();
 const yaml='nodes:\n  - engine: library.think\nwires: []';
 const result=await api.importRecipe(yaml);assert.equal(result.nodes[0],'n');
 assert.deepEqual(requests.find(r=>r.body?.op==='import_recipe').body,{op:'import_recipe',args:[yaml]});
 refuse();await assert.rejects(api.importRecipe('nodes: ['),/Correct it and retry/);
});

test('schedule and skill mutations use canvas-op and refresh confirmed owner projections',async()=>{
 const {api,requests}=await adapter();
 await api.setScheduleTime('schedule','09:30');await api.saveSkill('Workflow');
 assert.deepEqual(requests.find(r=>r.body?.op==='set_schedule_time').body.args,['schedule','09:30']);
 assert.ok(requests.filter(r=>r.body?.op==='list_skills').length>=2);
 assert.ok(requests.filter(r=>r.body?.op==='project_schedules').length>=2);
});

test('wire rule edits update the evaluator condition and reuse its confirmed relation',async()=>{
 const {api,requests}=await adapter({root:'g',nodes:[],wires:[{id:'wire',source:'a',target:'b',params:[]}]});
 await api.setWireRule('wire','value > 1');
 assert.deepEqual(requests.find(row=>row.url==='/api/universal/wire-property').body,{wire:'wire',label:'condition',value:'value > 1'});
 assert.equal(api.getSnapshot().graph.wires[0].rule,'value > 1');
 await api.setWireRule('wire','value > 2');
 assert.deepEqual(requests.find(row=>row.url==='/api/universal/set-property').body,{relation:'condition-relation',value:'value > 2'});
 assert.equal(api.getSnapshot().graph.wires[0].rule,'value > 2');
});

}
// WIRE-projects end
test('WIRE-rest absent canvas commands reject with a repair action and do not synthesize state',async()=>{
 const {api,requests}=await adapter({signed_in:false});
 await assert.rejects(()=>api.createCommunityGroup('Test group'),/System graph/);
 assert.equal(api.getSnapshot().community.groups.length,0);
 assert.ok(requests.filter(r=>r.url==='/api/universal/canvas').length>1);
 assert.equal(requests.some(r=>r.url==='/api/universal/interaction'),false);
});

test('WIRE-rest command uses the admitted control, current revision and typed submitted facts',async()=>{
 const canvas={root:'canvas',revision:'rev-7',nodes:[],wires:[],scope:{current:'scope-1'},interaction_projection:{bindings:[
  {control:'createCommunityGroup',interaction:'command-1',event:'activate',event_facts:[{source:'submitted',input:'name'}]}
 ]}};
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas':canvas,
  '/api/universal/interaction':{ok:true,result:{id:'group-1',name:'Test group'}}});
 const result=await api.createCommunityGroup('Test group');
 assert.equal(result.id,'group-1');
 const write=requests.find(r=>r.url==='/api/universal/interaction').body;
 assert.equal(write.control,'createCommunityGroup');assert.equal(write.interaction,'command-1');
 assert.equal(write.expected_scope,'scope-1');assert.equal(write.revision,'rev-7');
 assert.deepEqual(write.event_facts,[{input:'name',value:'Test group'}]);assert.ok(write.command_id);
});

test('WIRE-rest owner refusal propagates without a write retry or fabricated group',async()=>{
 const canvas={root:'canvas',revision:7,nodes:[],wires:[],interaction_projection:{bindings:[
  {control:'createCommunityGroup',interaction:'command-1',event:'activate',event_facts:[{source:'submitted',input:'name'}]}
 ]}};
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas':canvas,
  '/api/universal/interaction':{ok:false,error:'Membership requires owner review'}});
 await assert.rejects(()=>api.createCommunityGroup('Test group'),/Membership requires owner review/);
 assert.equal(requests.filter(r=>r.url==='/api/universal/interaction').length,1);
 assert.equal(api.getSnapshot().community.groups.length,0);
});

async function restScreen(component, api, state, props={}) {
 const {JSDOM}=require('jsdom');
 const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
 const win=dom.window;
 for(const vendorFile of ['react.js','react-dom.js','babel.js'])win.eval(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/vendor',vendorFile),'utf8'));
 const React=win.React;
 const element=tag=>({children,...props})=>React.createElement(tag,props,children);
 const navigation=[];
 const u={go:route=>navigation.push(route),show:(name,data)=>navigation.push({name,data}),advanced:false};
 win.AHIcon=()=>null;
 win.UI={api,A:{ok:'green',warn:'orange',inkSoft:'gray'},D:{Toggle:({checked,onCheckedChange,label})=>React.createElement('input',{type:'checkbox',checked,'aria-label':label,onChange:event=>onCheckedChange(event.target.checked)})},
  useData:()=>state,useApp:()=>u,Btn:({p,sm,ghost,danger,...props})=>React.createElement('button',props),Card:element('section'),Chip:element('span'),
  Heading:({title,children})=>React.createElement('header',null,title,children),Empty:element('p'),Table:({rows})=>React.createElement('pre',null,JSON.stringify(rows)),SettingControl:()=>null,Av:()=>null};
 for(const screenFile of ['answer-widgets.jsx','community-tools.jsx','decision-results.jsx','canvas-states.jsx','watcher-controls.jsx','desktop.jsx','ds_watch_edit.jsx','routing.jsx','xray.jsx','context-menus.jsx']){
  win.eval(win.Babel.transform(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio',screenFile),'utf8'),{presets:['react']}).code);
 }
 for(const surfaceName of ['RefineComparison','ModelAvailability','HealthHistory','XrayLayers','Research','GraphMetadata','CapabilitySettings'])if(!win.UI[surfaceName])win.UI[surfaceName]=()=>null;
 const root=win.ReactDOM.createRoot(win.document.getElementById('root'));
 root.render(React.createElement(win.UI[component],props));
 const settle=()=>new Promise(resolve=>globalThis.setTimeout(resolve,20));await settle();
 return {win,root,navigation,settle,close(){root.unmount();dom.window.close();}};
}

test('WIRE-rest rendered Desktop shows waiting, real refusal, retry and the owner result',async()=>{
 const {api}=await adapter({signed_in:false});let calls=0,release;
 const screen=await restScreen('DesktopScene',{...api,getDesktopCompanion:()=>{calls++;return calls===1?new Promise(resolve=>{release=resolve;}):Promise.resolve({ok:true,status:'running',message:'Native owner frame 17'});}},api.getSnapshot());
 try{
  const click=text=>{const button=[...screen.win.document.querySelectorAll('button')].find(b=>b.textContent===text);assert.ok(button,text);button.click();};
  click('Read companion state');await screen.settle();
  assert.match(screen.win.document.body.textContent,/Waiting for the owner/);
  assert.equal(screen.win.document.querySelector('button').disabled,true);
  release({ok:false,error:'Host refused: choose the active program in Connections'});await screen.settle();
  assert.match(screen.win.document.querySelector('[role="alert"]').textContent,/choose the active program/);
  assert.equal(calls,1);click('Retry action');await screen.settle();
  assert.match(screen.win.document.body.textContent,/Native owner frame 17/);assert.equal(calls,2);
  click('BABOOM settings');assert.deepEqual(screen.navigation,['settings/BABOOM']);
 }finally{screen.close();}
});

test('WIRE-rest rendered Watcher reads connector owner evidence and opens existing Connections',async()=>{
 const {api}=await adapter({signed_in:false});let calls=0;
 const screen=await restScreen('Watcher',{...api,readHostAvailability:async()=>{calls++;return {ok:true,operations:[{host:'revit',operation:'read',status:'available',reason:'Broker observed'}]};}},api.getSnapshot());
 try{
  [...screen.win.document.querySelectorAll('button')].find(b=>b.textContent==='Read source').click();await screen.settle();
  assert.equal(calls,1);assert.match(screen.win.document.body.textContent,/Broker observed/);
  [...screen.win.document.querySelectorAll('button')].find(b=>b.textContent==='Connections').click();
  assert.deepEqual(screen.navigation,['settings/Connections']);
 }finally{screen.close();}
});

test('WIRE-rest command rejects a changed input schema before posting',async()=>{
 const canvas={root:'canvas',nodes:[],wires:[],interaction_projection:{bindings:[{control:'createCommunityGroup',interaction:'i',event:'activate',event_facts:[]}]}};
 const {api,requests}=await adapter({signed_in:false},{'/api/universal/canvas':canvas});
 await assert.rejects(()=>api.createCommunityGroup('Group'),/input schema changed/);
 assert.equal(requests.some(r=>r.url==='/api/universal/interaction'),false);
});

test('WIRE-rest rendered community preserves rejected drafts and executes its registered owner callback',async()=>{
 const {api}=await adapter({signed_in:false});let calls=0;
 const screen=await restScreen('CommunityTools',{...api,createCommunityGroup:async(name)=>{calls++;assert.equal(name,'Retained group');throw Error('Choose a community owner in System graph');}},api.getSnapshot());
 try{
  const input=screen.win.document.querySelector('[aria-label="Community group name"]');
  Object.getOwnPropertyDescriptor(screen.win.HTMLInputElement.prototype,'value').set.call(input,'Retained group');
  input.dispatchEvent(new screen.win.Event('input',{bubbles:true}));await screen.settle();
  const create=[...screen.win.document.querySelectorAll('button')].find(b=>b.textContent==='Create group');
  assert.equal(create.disabled,false);create.click();await screen.settle();
  assert.equal(calls,1);assert.equal(input.value,'Retained group');
  assert.match(screen.win.document.querySelector('[role="alert"]').textContent,/Choose a community owner/);
 }finally{screen.close();}
});

test('WIRE-rest rendered owned screens mount against the real empty snapshot and keep navigation usable',async()=>{
 const {api}=await adapter({signed_in:false});
 for(const component of ['GraphProperties','RefineComparison','Routing','Xray','WatcherDimensions']){
  const screen=await restScreen(component,api,api.getSnapshot());
  try{assert.ok(screen.win.document.getElementById('root').textContent.length>0,component);}
  finally{screen.close();}
 }
});

test('WIRE-rest context menu keeps a refused owner action and Retry inside the menu',async()=>{
 const {api}=await adapter({signed_in:false});let calls=0;
 const state=api.getSnapshot();state.graph.nodes=[{id:'node-1',title:'Actual node',inputs:[],outputs:[]}];
 const screen=await restScreen('ContextMenu',{...api,setPortVisibility:async()=>{calls++;throw Error('Port visibility owner refused this selection');}},state,{kind:'Port menu',nodeId:'node-1',port:'out',close(){}});
 try{
  [...screen.win.document.querySelectorAll('button')].find(b=>b.textContent.includes('Faint wires')).click();await screen.settle();
  const menu=screen.win.document.querySelector('[role="menu"]');
  assert.match(menu.querySelector('[role="alert"]').textContent,/Port visibility owner refused/);
  [...menu.querySelectorAll('button')].find(b=>b.textContent==='Retry action').click();await screen.settle();
  assert.equal(calls,2);
 }finally{screen.close();}
});

test('WIRE-rest boot failure renders its actual error and retry reloads only once',async()=>{
 const {JSDOM}=require('jsdom');
 const html=fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/studio.html'),'utf8');
 const dom=new JSDOM(html);let reloads=0;
 try{
  const scripts=dom.window.document.querySelectorAll('script');
  vm.runInNewContext(scripts[scripts.length-1].textContent,{document:dom.window.document,window:{location:{reload(){reloads++;}}},fetch:async()=>({ok:false}),TextDecoder,Uint8Array:globalThis.Uint8Array});
  await new Promise(resolve=>globalThis.setImmediate(resolve));
  const boot=dom.window.document.getElementById('studio-boot');
  assert.equal(boot.getAttribute('role'),'alert');assert.match(boot.textContent,/Studio build asset is missing/);
  const retry=boot.querySelector('button');retry.click();retry.click();
  assert.equal(reloads,1);assert.equal(retry.disabled,true);
 }finally{dom.window.close();}
});




async function buttonsAdapter(extra={},replies={}){
 const calls=[],events=new Map(),canvas={root:'graph',scope:{current:'graph'},nodes:[],wires:[],catalog:[],workshops:[{root:'workshop'}]};
 const window={structuredClone:globalThis.structuredClone,crypto:require('node:crypto').webcrypto,
  ARCHHUB_BOOT:{token:'fixture',csrf:'fixture'},document:{hidden:true,addEventListener(){}},
  addEventListener:(name,fn)=>events.set(name,fn),dispatchEvent(){},...extra};
 window.ArchHubStudioAuthority={create:({get})=>({load:()=>get('/api/universal/canvas')})};
 const fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
  const data=Object.hasOwn(replies,url)?await replies[url](body):url==='/api/universal/canvas'?canvas:url==='/api/universal/settings-action'?
   {ok:true,result:{dependencies:[{id:body.args[0],state:'Ready'}]}}:{ok:true,result:[]};
  return {ok:true,status:200,json:async()=>data};
 };
 const context={window,document:window.document,fetch,CustomEvent:class{},
  setTimeout,clearTimeout,setInterval,clearInterval,URLSearchParams,AbortSignal:globalThis.AbortSignal,console};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../01.APP/nodelang/studio/api.js'),'utf8'),context);
 await window.ArchHubAPI.ready;await new Promise(resolve=>require('node:timers').setImmediate(resolve));
 return {api:window.ArchHubAPI,calls,window,events};
}
test('startVoiceInput: native capture delivers reviewed text and completes listening',async()=>{
 let finish,starts=0;const statuses=[],transcripts=[];
 const {api}=await buttonsAdapter({ARCHHUB_VOICE_START:()=>{starts++;return new Promise(resolve=>finish=resolve);},ARCHHUB_VOICE_STOP:async()=>({ok:true})});
 assert.equal(api.supportsAction('startVoiceInput'),true);
 const pending=api.startVoiceInput({onStatus:v=>statuses.push(v),onTranscript:v=>transcripts.push(v)});
 assert.equal(starts,1);assert.deepEqual(statuses,[true]);
 await assert.rejects(api.startVoiceInput(),/Finish the current/);
 finish({ok:true,text:'review the plan'});assert.equal((await pending).ok,true);
 assert.deepEqual(transcripts,['review the plan']);assert.deepEqual(statuses,[true,false]);
});
test('stopVoiceInput: cancelling native capture sends no transcript',async()=>{
 let finish,stops=0;const transcripts=[],statuses=[];
 const {api}=await buttonsAdapter({ARCHHUB_VOICE_START:()=>new Promise(resolve=>finish=resolve),ARCHHUB_VOICE_STOP:async()=>{stops++;finish({ok:true,cancelled:true});return {ok:true};}});
 const capture=api.startVoiceInput({onTranscript:v=>transcripts.push(v),onStatus:v=>statuses.push(v)});
 await api.stopVoiceInput();await capture;assert.equal(stops,1);assert.deepEqual(transcripts,[]);assert.deepEqual(statuses,[true,false]);
});
test('voice errors close listening and permit retry without claiming a transcript',async()=>{
 const errors=[],statuses=[];let attempts=0;
 const {api}=await buttonsAdapter({ARCHHUB_VOICE_START:async()=>{attempts++;throw Error('Windows recognizer unavailable');},ARCHHUB_VOICE_STOP:async()=>({ok:true})});
 for(let i=0;i<2;i++)assert.equal((await api.startVoiceInput({onStatus:v=>statuses.push(v),onError:v=>errors.push(v)})).ok,false);
 assert.equal(attempts,2);assert.deepEqual(errors,['Windows recognizer unavailable','Windows recognizer unavailable']);assert.deepEqual(statuses,[true,false,true,false]);
});
test('speech availability follows host capability without weakening the bound-action guard',async()=>{
 const {api,window,events}=await buttonsAdapter();let notices=0;api.subscribe(()=>notices++);
 for(const name of ['startVoiceInput','stopVoiceInput','speak'])assert.equal(api.supportsAction(name),false);
 window.ARCHHUB_VOICE_START=async()=>({ok:true,text:'one'});window.ARCHHUB_VOICE_STOP=async()=>({ok:true});
 events.get('archhub:capabilities')();assert.ok(notices>0);assert.equal(api.supportsAction('startVoiceInput'),true);
 assert.equal(api.supportsAction('invented'),false);assert.equal(api.supportsAction('approve','session'),false);
});
test('speak: invokes platform synthesis and reports completion only on its completion event',async()=>{
 let utterance;const {api}=await buttonsAdapter({SpeechSynthesisUtterance:class{constructor(text){this.text=text;}},speechSynthesis:{speak:value=>{utterance=value;}}});
 assert.equal(api.supportsAction('speak'),true);let done=false;
 const speaking=api.speak('review the plan').then(()=>done=true);await Promise.resolve();
 assert.equal(utterance.text,'review the plan');assert.equal(done,false);utterance.onend();await speaking;assert.equal(done,true);
 const failed=api.speak('retry');utterance.onerror({error:'audio-busy'});await assert.rejects(failed,/audio-busy/);
 assert.throws(()=>api.speak(''),/characters/);
});
test('ensureDependency: posts existing Settings owner command and publishes confirmed inventory',async()=>{
 const {api,calls}=await buttonsAdapter();assert.equal(api.supportsAction('ensureDependency'),true);
 await api.ensureDependency('codex');const call=calls.find(x=>x.body?.function==='ensureDependency');
 assert.deepEqual(call,{url:'/api/universal/settings-action',body:{function:'ensureDependency',args:['codex']}});
 assert.equal(api.getSnapshot().dependencies[0].state,'Ready');
});

for(const name of ["runValuation", "correctAnswerSource", "setResearchReview", "stampOutput", "runSpecialNode", "setTranscriptPass", "settleTimesheet", "runResearchNode", "signInProvider", "changePlan"])test(name+': remains hidden without an executing owner',async()=>{
 const {api,calls}=await buttonsAdapter();const count=calls.length;assert.equal(api.supportsAction(name),false);
 const result=await api[name]();assert.equal(result.ok,false);assert.equal(result.status,'not_connected');assert.equal(calls.length,count);
});

async function hostskillsAdapter() {
 const row={id:'skill',name:'Dimensions',host:'Revit',format:'SKILL.md',enabled:false,scripts:[],network:false,audit:'Needs access review',description:'Check dimensions'};
 const bundle={id:'bundle',name:'Measure',description:'Local package',tools:[{name:'measure'}],config:[{key:'precision',label:'Precision',type:'number',value:2}],status:'Ready for review',installed:false};
 let fail=false,owner=true,cards=[];
 const methods=[];
 const rig=await adapter({signed_in:false},{
  '/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshop_scope:{root:'canvas',workshops:[{root:'workshop',is_general:true}]}},
  '/api/universal/workshop':body=>{
   if(body.function==='listTasks')return {result:[]};
   if(body.function==='listApprovals')return {result:globalThis.structuredClone(cards)};
   if(body.function==='readWatcher')return {result:{ok:false}};
   if(body.function==='readHostSkills')return {result:owner?{owner:'host-owner',hostSkills:[{...row}],connectorBundles:[{...bundle}],connectorBundle:{...bundle}}:{ok:false}};
   methods.push(body);
   if(fail)return {ok:false,error:'Exact digest changed'};
   if(body.function==='importHostSkill')return {result:{...row}};
   if(body.function==='inspectConnectorBundle')return {result:{...bundle}};
   if(body.function==='configureConnectorBundle'){bundle.config=[{...bundle.config[0],value:body.args[2]}];return {result:{...bundle}};}
   if(body.function==='auditHostSkill'){row.audit='Access findings recorded';return {result:{...row}};}
   if(body.function==='setHostSkillEnabled'&&!body.args[1]){row.enabled=false;return {result:{...row}};}
   if(['installConnectorBundle','setHostSkillEnabled'].includes(body.function)){
    cards=[{id:'package-review',approvalKind:'hostskills',input_digest:'sealed-digest',status:'pending',rows:[],action:body.function}];return {result:{...cards[0]}};
   }
   if(body.function==='decideHostSkill'){
    cards[0].status=body.args[2]==='approve'?'approved':'declined';
    if(body.args[2]==='approve'){if(cards[0].action==='installConnectorBundle'){bundle.installed=true;bundle.status='Installed';}else row.enabled=true;}
    return {result:{...cards[0]}};
   }
   return {result:{ok:false}};
  }
 });
 rig.window.btoa=value=>Buffer.from(value,'binary').toString('base64');
 await rig.api.listTasks();
 return {...rig,methods,refuse:()=>fail=true,loseOwner:()=>owner=false};
}

for(const [name,args] of [
 ['importHostSkill',[{host:'Revit',text:'---\nname: dimensions\n---\nInstructions'}]],
 ['inspectConnectorBundle',[{name:'fixture.json',base64:'e30='}]],
 ['configureConnectorBundle',['precision',4]],['installConnectorBundle',[]],
 ['setHostSkillEnabled',['skill',true]],['auditHostSkill',['skill']]
])test('HOSTSKILLS '+name+' executes owner and publishes confirmed graph projection',async()=>{
 const rig=await hostskillsAdapter();assert.equal(rig.api.supportsAction(name),true);
 const result=await rig.api[name](...args),call=rig.methods.find(r=>r.function===name);
 assert.ok(result.id);assert.equal(call.root,'workshop');assert.equal(call.scope,'canvas');
 const expected=name==='configureConnectorBundle'?['bundle',...args]:name==='installConnectorBundle'?['bundle']:args;
 assert.deepEqual(globalThis.structuredClone(call.args),expected);
 if(name==='setHostSkillEnabled')assert.equal(rig.api.getSnapshot().hostSkills[0].enabled,false);
 if(name==='installConnectorBundle')assert.equal(rig.api.getSnapshot().connectorBundle.installed,false);
});

test('HOSTSKILLS one approval activates once and stale refusal preserves confirmed projection',async()=>{
 const rig=await hostskillsAdapter();await rig.api.installConnectorBundle();
 assert.equal(rig.api.getSnapshot().approvals.length,1);assert.equal(rig.api.supportsAction('decline'),true);
 await rig.api.approve('package-review');
 assert.equal(rig.api.getSnapshot().connectorBundle.installed,true);
 const call=rig.methods.find(r=>r.function==='decideHostSkill');
 assert.deepEqual(globalThis.structuredClone(call.args),['package-review','sealed-digest','approve']);
 const before=globalThis.structuredClone(rig.api.getSnapshot().hostSkills);
 rig.refuse();await assert.rejects(()=>rig.api.auditHostSkill('skill'),/digest changed/);
 assert.deepEqual(globalThis.structuredClone(rig.api.getSnapshot().hostSkills),before);
});

test('HOSTSKILLS unavailable owner hides all six and a local file preserves upload bytes',async()=>{
 const rig=await hostskillsAdapter(),bytes=Buffer.from('{"name":"measure"}');
 await rig.api.inspectConnectorBundle({name:'fixture.json',arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)});
 const call=rig.methods.find(r=>r.function==='inspectConnectorBundle');
 assert.equal(Buffer.from(call.args[0].base64,'base64').toString(),bytes.toString());
 rig.loseOwner();await rig.api.readHostSkills();const count=rig.methods.length;
 for(const name of ['importHostSkill','inspectConnectorBundle','configureConnectorBundle','installConnectorBundle','setHostSkillEnabled','auditHostSkill']){
  assert.equal(rig.api.supportsAction(name),false);await assert.rejects(()=>rig.api[name](),/owner unavailable/);
 }
 assert.equal(rig.methods.length,count);
});

test('HOSTSKILLS existing rendered controls invoke package owner actions',async()=>{
 const rig=await hostskillsAdapter(),{JSDOM}=require('jsdom');
 const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;
 const studio=path.join(__dirname,'../../01.APP/nodelang/studio');
 for(const vendor of ['react.js','react-dom.js','babel.js'])w.eval(fs.readFileSync(path.join(studio,'vendor',vendor),'utf8'));
 const R=w.React,opened=[],u={act:fn=>fn(),show:(name,data)=>opened.push({name,data})};
 w.AHIcon=()=>null;w.ArchHubAPI=rig.api;
 const element=tag=>({children,...props})=>R.createElement(tag,props,children);
 w.UI={api:rig.api,A:{},D:{Toggle:({label,checked,onCheckedChange})=>R.createElement('button',{'aria-label':label,onClick:()=>onCheckedChange(!checked)})},
  useData:()=>R.useSyncExternalStore(rig.api.subscribe,rig.api.getSnapshot),useApp:()=>u,
  Btn:({p,sm,ghost,...props})=>R.createElement('button',props),Card:element('section'),Chip:element('span')};
 w.eval(w.Babel.transform(fs.readFileSync(path.join(studio,'agent-states.jsx'),'utf8'),{presets:['react']}).code);
 const root=w.ReactDOM.createRoot(w.document.getElementById('root'));
 const settle=()=>new Promise(resolve=>setTimeout(resolve,30));
 const render=async(component,props={})=>{root.render(R.createElement(component,props));await settle();};
 const click=async label=>{const button=[...w.document.querySelectorAll('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label);assert.ok(button,label);button.click();await settle();};
 try{
  await render(w.UI.HostSkills);await click('Import skill');assert.equal(opened.at(-1).name,'Import skill');
  await click('Enable skill Dimensions');assert.ok(rig.methods.find(m=>m.function==='setHostSkillEnabled'));
  await render(w.UI.HostSkill,{id:'skill'});await click('Review access');assert.equal(rig.api.getSnapshot().hostSkills[0].audit,'Access findings recorded');
  await render(w.UI.ConnectorBundle);
  assert.ok(w.document.querySelector('[aria-label="Precision"]'));
  const input=w.document.querySelector('[aria-label="Choose connector bundle"]'),bytes=Buffer.from('{}');
  Object.defineProperty(input,'files',{configurable:true,value:[{name:'fixture.json',arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)}]});
  input.dispatchEvent(new w.Event('change',{bubbles:true}));await settle();
  assert.ok(rig.methods.find(m=>m.function==='inspectConnectorBundle'));
  await click('Install reviewed bundle');assert.ok(rig.methods.find(m=>m.function==='installConnectorBundle'));
  assert.equal(rig.api.getSnapshot().connectorBundle.installed,false);
 }finally{root.unmount();dom.window.close();}
});

test('HOSTSKILLS a graph switch during local file read refuses before upload',async()=>{
 const rig=await hostskillsAdapter();let release;
 const reading=new Promise(resolve=>release=resolve);
 const pending=rig.api.inspectConnectorBundle({name:'fixture.json',arrayBuffer:()=>reading});
 await rig.api.selectGraph('another-graph');
 release(new ArrayBuffer(0));
 await assert.rejects(()=>pending,/graph changed/);
 assert.equal(rig.methods.filter(m=>m.function==='inspectConnectorBundle').length,0);
});

function dialogHarness(){
 const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio'),babel={};
 vm.runInNewContext(fs.readFileSync(path.join(studio,'vendor/babel.js'),'utf8'),babel);
 let slots=[],cursor=0,effect,cleanup,callbacks,stops=0;const writes=[],errors=[],handlers={};
 const api={supportsAction:()=>true,startVoiceInput:options=>{callbacks=options;options.onStatus(true);return Promise.resolve({ok:true});},stopVoiceInput:async()=>{stops++;throw Error('Native stop refused');}};
 const u={act:fn=>Promise.resolve().then(fn).catch(failure=>{errors.push(failure.message);return null;})};
 const element={querySelector:()=>null,addEventListener(){},removeEventListener(){}};
 const React={Component:class{},Fragment:'fragment',useState(value){const i=cursor++;if(!(i in slots))slots[i]=value;return [slots[i],next=>{slots[i]=next;writes.push([i,next]);}];},
  useRef(value){const i=cursor++;if(!(i in slots))slots[i]={current:value};return slots[i];},useLayoutEffect:fn=>effect=fn,
  createElement(type,props,...children){if(props?.ref)props.ref.current=element;return {type,props:props||{},children};}};
 const window={UI:{api,useData:()=>({}),useApp:()=>u,A:{},Btn:'Btn'},ReactDOM:{createRoot:()=>({render(){}})},
  registerActions:(names,functions)=>{for(const [name,key]of Object.entries(names))handlers[name]=functions[key];},
  executeAction:(name,scope,event)=>handlers[name](scope,event)};
 const source=fs.readFileSync(path.join(studio,'app.jsx'),'utf8').replace('window.ReactDOM.createRoot','window.BUTTONS_DIALOG = Dialog; window.ReactDOM.createRoot');
 const context=vm.createContext({window,React,document:{getElementById:()=>null},console});
 vm.runInContext(babel.Babel.transform(source,{presets:['react'],sourceType:'script'}).code,context);
 const render=kind=>{cursor=0;const tree=window.BUTTONS_DIALOG({modal:{kind},close(){}});cleanup=effect();return tree;};
 return {render,api,handlers,window,writes,errors,u,get callbacks(){return callbacks;},get stops(){return stops;},cleanup:()=>cleanup()};
}
function nodes(tree){return tree&&typeof tree==='object'?[tree,...(tree.children||[]).flatMap(child=>Array.isArray(child)?child.flatMap(nodes):nodes(child))]:[];}
function text(tree){return tree&&typeof tree==='object'?(tree.children||[]).map(child=>Array.isArray(child)?child.map(text).join(''):text(child)).join(''):String(tree??'');}
test('Talk close cancels capture and late callbacks cannot edit a replacement dialog',async()=>{
 const h=dialogHarness();const tree=h.render('Talk');const start=nodes(tree).find(n=>n.type==='Btn'&&text(n).includes('Start talking'));
 assert.ok(start);await start.props.onClick({});const callbacks=h.callbacks;assert.ok(callbacks);
 h.cleanup();h.render('Other dialog');const writes=h.writes.length;
 callbacks.onTranscript('late transcript');callbacks.onStatus(false);callbacks.onError('late error');
 await new Promise(resolve=>require('node:timers').setImmediate(resolve));assert.equal(h.writes.length,writes);assert.equal(h.stops,1);assert.deepEqual(h.errors,['Native stop refused']);
});
test('Talk Stop handles native rejection without falsely clearing listening',async()=>{
 const h=dialogHarness();let listening=true;
 await h.handlers['appShell.Control.88']({api:h.api,u:h.u,listening,setListening:()=>listening=false,talk:()=>assert.fail('already listening')},{});
 assert.equal(listening,true);assert.deepEqual(h.errors,['Native stop refused']);
});


// APPROVALS: execute the adapter against an answering owner; no source-text proof.
async function approvalAdapter() {
 const card={id:'decision-1',delegation:'decision-1',work:'work-1',input_digest:'d'.repeat(64),
  title:'Reviewed request',approvalKind:'social',kind:'qc',status:'pending',rows:[{element:'post',before:'Not executed',after:'Exact request'}],rubric:{}};
 let latest=globalThis.structuredClone(card),failure=null;
 const methods=[];
 const rig=await adapter({signed_in:false},{
  '/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshop_scope:{root:'canvas',workshops:[{root:'workshop',is_general:true}]}},
  '/api/universal/workshop':body=>{
   if(body.function==='listTasks')return {result:[]};
   if(body.function==='listApprovals')return {result:[globalThis.structuredClone(latest)]};
   methods.push(body);
   if(failure)return {result:{ok:false,error:failure}};
   if(body.function==='postponeApproval')latest.status='postponed';
   if(body.function==='resumeApproval')latest.status='pending';
   if(body.function==='contestDecision')latest.status='contested';
   if(body.function==='reviewProofRow')latest.rows[body.args[1]].decision=body.args[2];
   if(body.function==='setApprovalRubric')latest.rubric[body.args[1]]=body.args[2];
   if(body.function==='refreshApproval')latest={...card,id:'decision-2',delegation:'decision-2'};
   return {result:globalThis.structuredClone(latest)};
  }
 });
 await rig.api.listTasks();
 return {...rig,methods,refuse:message=>failure=message};
}
for(const [name,args,status] of [
 ['postponeApproval',['decision-1'],'postponed'],
 ['resumeApproval',['decision-1'],'pending'],
 ['contestDecision',['decision-1','Recheck the exact source'],'contested'],
 ['refreshApproval',['decision-1'],'pending'],
 ['reviewProofRow',['decision-1',0,'Reject'],'pending'],
 ['setApprovalRubric',['decision-1','Target and revision match',false],'pending']
])test('APPROVALS '+name+': executes the Workshop owner and reads back its state',async()=>{
 const {api,methods}=await approvalAdapter();
 assert.equal(api.supportsAction(name),true);
 const result=await api[name](...args);
 const call=methods.find(row=>row.function===name);
 assert.equal(call.action,'data-api');assert.equal(call.root,'workshop');assert.equal(call.scope,'canvas');
 assert.deepEqual(call.args,args);
 assert.equal(result.status,status);
 const saved=api.getSnapshot().approvals.find(row=>row.id===result.id);
 assert.equal(saved.status,status);
 if(name==='reviewProofRow')assert.equal(saved.rows[0].decision,'Reject');
 if(name==='setApprovalRubric')assert.equal(saved.rubric['Target and revision match'],false);
 if(name==='refreshApproval')assert.equal(saved.id,'decision-2');
});

test('APPROVALS owner refusal preserves the confirmed projection',async()=>{
 const {api,requests,refuse}=await approvalAdapter();
 const before=api.getSnapshot().approvals;
 refuse("The exact request changed. Refresh its review.");
 await assert.rejects(()=>api.postponeApproval("decision-1"),/exact request changed/);
 assert.deepEqual(api.getSnapshot().approvals,before);
 // A new adapter owner failure is exercised with no Workshop binding.
 const absent=await adapter({signed_in:false});
 assert.equal(absent.api.supportsAction('postponeApproval'),false);
 await assert.rejects(()=>absent.api.postponeApproval('decision-1'),/not confirmed|unavailable/);
 assert.deepEqual(api.getSnapshot().approvals,before);
 assert.ok(requests.some(row=>row.body?.function==='listApprovals'));
});


test('APPROVALS rendered shared card buttons execute the exact review identity',async()=>{
 const rig=await approvalAdapter(),api=rig.api,studio=path.resolve(__dirname,'../../01.APP/nodelang/studio'),babel={};
 vm.runInNewContext(fs.readFileSync(path.join(studio,'vendor/babel.js'),'utf8'),babel);
 const handlers={};
 const u={act:fn=>fn(),show(){}};
 const React={createContext:()=>({}),useContext:()=>u,useSyncExternalStore:()=>({...api.getSnapshot(),files:[],watcher:{view:''}}),
  useState:value=>[value,()=>{}],createElement:(type,props,...children)=>({type,props:props||{},children}),Fragment:'fragment'};
 const window={ArchHubAPI:api,AH:{},AH_DS:{},UI:{},
  registerActions:(names,functions)=>{for(const [name,key]of Object.entries(names))handlers[name]=functions[key];},
  executeAction:(name,...args)=>handlers[name](...args)};
 const context=vm.createContext({window,React,console});
 vm.runInContext(babel.Babel.transform(fs.readFileSync(path.join(studio,'ui.jsx'),'utf8'),{presets:['react']}).code,context);
 const button=(tree,label)=>nodes(tree).find(n=>text(n)===label&&typeof n.props?.onClick==='function');
 let tree=window.UI.ApprovalCard({id:'decision-1'});
 assert.ok(button(tree,'Postpone'));
 await button(tree,'Reject row 1').props.onClick({});
 assert.equal(api.getSnapshot().approvals[0].rows[0].decision,'Reject');
 await button(tree,'Accept row 1').props.onClick({});
 await button(tree,'Postpone').props.onClick({});
 tree=window.UI.ApprovalCard({id:'decision-1'});
 assert.ok(button(tree,'Resume review'));
 await button(tree,'Resume review').props.onClick({});
 assert.equal(api.getSnapshot().approvals[0].status,'pending');
 await api.contestDecision('decision-1','Review this decision');
 tree=window.UI.ApprovalCard({id:'decision-1'});
 assert.ok(button(tree,'Review latest'));
 await button(tree,'Review latest').props.onClick({});
 assert.equal(api.getSnapshot().approvals[0].id,'decision-2');
});


// WATCHER: answering owner, durable-state projection and actual rendered gestures.
async function watcherAdapter() {
 const held={owner:'watcher-owner',host:'Revit',view:'Level 1',views:['Level 1','Level 2'],elementId:'unique-wall',elementLabel:'Wall',sourceRevision:'r1',
  wallY:510,pendingY:530,marks:[],comments:[],dimensions:[],lengthMm:12900,thicknessMm:200,geometry:{outline:[],walls:[[120,510,980,510]],doors:[],tags:[]},status:'loaded'};
 let failure=null,cards=[],writes=0,readOwner=true;
 const methods=[];
 const rig=await adapter({signed_in:false},{
  '/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshop_scope:{root:'canvas',workshops:[{root:'workshop',is_general:true}]}},
  '/api/universal/workshop':body=>{
   if(body.function==='listTasks')return {result:[]};
   if(body.function==='listApprovals')return {result:globalThis.structuredClone(cards)};
   if(body.function==='readWatcher')return {result:readOwner?globalThis.structuredClone(held):{ok:false,error:'Watcher owner unavailable'}};
   methods.push(body);if(failure)return {result:{ok:false,error:failure}};
   const args=body.args;
   if(body.function==='setWatcherHost')held.host=args[0];
   if(body.function==='setWatcherView')held.view=args[0];
   if(body.function==='editWall')held.pendingY=args[0];
   if(body.function==='addDimension')held.dimensions.push({...args[0],id:'dimension',valueMm:1500});
   if(body.function==='addMark')held.marks.push({...args[0],id:'mark'});
   if(body.function==='addComment')held.comments.push({...args[0],id:'comment'});
   if(body.function==='discardWatcherChanges')held.pendingY=held.wallY;
   if(body.function==='proposeWatcherEdit'){
    if(!cards.length)cards=[{id:'proposal',approvalKind:'watcher',input_digest:'digest',status:'pending',rows:[]}];
    return {result:globalThis.structuredClone(cards[0])};
   }
   if(body.function==='decideWatcherEdit'){
    if(args[2]==='approve'){writes++;held.wallY=held.pendingY;cards[0].status='approved';}
    else cards[0].status='declined';
    return {result:globalThis.structuredClone(cards[0])};
   }
   return {result:globalThis.structuredClone(held)};
  }
 });
 await rig.api.listTasks();
 return {...rig,methods,writes:()=>writes,refuse:value=>failure=value,loseOwner:()=>readOwner=false};
}
for(const [name,args] of [
 ['setWatcherHost',['AutoCAD']],['setWatcherView',['Level 2']],
 ['addDimension',[{from:{x:0,y:0},to:{x:100,y:0}}]],['editWall',[540]],
 ['addMark',[{tool:'Mark',points:[{x:0,y:0},{x:10,y:10}]}]],
 ['addComment',[{text:'Keep clear',x:1,y:2,element:'unique-wall'}]],
 ['proposeWatcherEdit',[]],['discardWatcherChanges',[]]
])test('WATCHER '+name+' executes the admitted owner and reads confirmed state',async()=>{
 const rig=await watcherAdapter();assert.equal(rig.api.supportsAction(name),true);
 const result=await rig.api[name](...args),call=rig.methods.find(row=>row.function===name);
 assert.deepEqual(globalThis.structuredClone(call.args),args);assert.equal(call.root,'workshop');assert.equal(call.scope,'canvas');
 if(name==='proposeWatcherEdit')assert.equal(rig.api.getSnapshot().approvals[0].id,result.id);
 else assert.deepEqual(rig.api.getSnapshot().watcher.owner,result.owner);
 assert.equal(rig.writes(),0);
});

test('WATCHER owner refusal preserves projection; approve is the only host effect',async()=>{
 const rig=await watcherAdapter(),before=globalThis.structuredClone(rig.api.getSnapshot().watcher);
 rig.refuse('Source revision changed');await assert.rejects(()=>rig.api.editWall(560),/Source revision changed/);
 assert.deepEqual(globalThis.structuredClone(rig.api.getSnapshot().watcher),before);assert.equal(rig.writes(),0);
 rig.refuse(null);const card=await rig.api.proposeWatcherEdit();assert.equal(rig.writes(),0);
 await rig.api.approve(card.id);assert.equal(rig.writes(),1);assert.equal(rig.api.getSnapshot().watcher.wallY,530);
});

test('WATCHER rendered tools persist gestures and open the exact approval',async()=>{
 const rig=await watcherAdapter(),{JSDOM}=require('jsdom');
 const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true}),win=dom.window;
 const studio=path.join(__dirname,'../../01.APP/nodelang/studio');
 for(const vendor of ['react.js','react-dom.js','babel.js'])win.eval(fs.readFileSync(path.join(studio,'vendor',vendor),'utf8'));
 win.AHIcon=()=>null;
 const R=win.React,opened=[],element=tag=>({children,...props})=>R.createElement(tag,props,children);
 win.DOMPoint=class{constructor(x,y){this.x=x;this.y=y;}matrixTransform(){return this;}};
 win.SVGElement.prototype.getScreenCTM=()=>({inverse:()=>({})});win.SVGElement.prototype.setPointerCapture=()=>{};
 win.UI={bindActions:(names,handlers)=>(id,...args)=>handlers[names[id]](...args),api:rig.api,useData:()=>R.useSyncExternalStore(rig.api.subscribe,rig.api.getSnapshot),useApp:()=>({show:(name,data)=>opened.push({name,data}),go:()=>{}}),
  useAction:()=>{const [state,setState]=R.useState('idle');return {state,run:async fn=>{setState('waiting');try{return await fn();}finally{setState('idle');}}};},
  ActionStatus:()=>null,Btn:({p,sm,ghost,...props})=>R.createElement('button',props),Card:element('section'),Heading:element('header')};
 win.eval(win.Babel.transform(fs.readFileSync(path.join(studio,'answer-widgets.jsx'),'utf8'),{presets:['react']}).code);
 win.eval(win.Babel.transform(fs.readFileSync(path.join(studio,'ds_watch_edit.jsx'),'utf8'),{presets:['react']}).code);
 const root=win.ReactDOM.createRoot(win.document.getElementById('root'));
 const settle=()=>new Promise(resolve=>setTimeout(resolve,30));
 root.render(R.createElement(win.UI.Watcher));await settle();
 const button=label=>[...win.document.querySelectorAll('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label);
 const click=async label=>{assert.ok(button(label),label);button(label).click();await settle();};
 const gesture=async()=>{const svg=win.document.querySelector('svg');for(const [type,x,y] of [['pointerdown',120,510],['pointermove',150,520],['pointerup',220,530]]){svg.dispatchEvent(new win.MouseEvent(type,{bubbles:true,button:0,clientX:x,clientY:y}));await settle();}};
 try{
  await click('AutoCAD');assert.equal(rig.api.getSnapshot().watcher.host,'AutoCAD');
  const select=win.document.querySelector('select');select.value='Level 2';select.dispatchEvent(new win.Event('change',{bubbles:true}));await settle();
  assert.equal(rig.api.getSnapshot().watcher.view,'Level 2');
  await click('Dimension · D');await gesture();assert.equal(rig.api.getSnapshot().watcher.dimensions.length,1);
  await click('Mark · M');await gesture();assert.equal(rig.api.getSnapshot().watcher.marks.length,1);
  await click('Comment · C');await gesture();assert.equal(opened.at(-1).name,'Add comment');assert.equal(opened.at(-1).data.element,'unique-wall');
  const registrations={};
  win.registerActions=(names,handlers)=>{for(const [name,key] of Object.entries(names))registrations[name]=handlers[key];};
  const actualDOM=win.ReactDOM;win.ReactDOM={createRoot:()=>({render(){}})};
  win.eval(win.Babel.transform(fs.readFileSync(path.join(studio,'app.jsx'),'utf8'),{presets:['react']}).code);
  win.ReactDOM=actualDOM;
  await registrations['appShell.AddComment.77']({api:rig.api,m:opened.at(-1).data,saved:fn=>fn(),text:'Keep clear'});
  assert.equal(rig.api.getSnapshot().watcher.comments[0].text,'Keep clear');

  await click('Edit · E');await gesture();assert.equal(rig.api.getSnapshot().watcher.pendingY,550);
  await click('Apply to AutoCAD');assert.equal(opened.at(-1).name,'Approve');assert.equal(opened.at(-1).data.id,'proposal');assert.equal(rig.writes(),0);
  await click('Discard changes');assert.equal(rig.api.getSnapshot().watcher.pendingY,510);
  rig.refuse('Source revision changed');await click('AutoCAD');assert.match(win.document.querySelector('[role=alert]').textContent,/Source revision changed/);
  rig.refuse(null);await click('Retry action');assert.equal(win.document.querySelector('[role=alert]'),null);assert.match(win.document.body.textContent,/Watcher saved/);
 }finally{root.unmount();dom.window.close();}
});


test('WATCHER losing the graph owner clears source geometry and private annotations',async()=>{
 const rig=await watcherAdapter();
 await rig.api.addComment({text:'Private',x:120,y:510,element:'unique-wall'});
 rig.loseOwner();await rig.api.selectGraph('another-graph');
 const state=rig.api.getSnapshot().watcher;
 assert.equal(rig.api.supportsAction('editWall'),false);
 assert.equal(state.host,'');assert.equal(state.elementId,undefined);
 assert.equal(state.comments.length,0);assert.equal(state.marks.length,0);assert.equal(state.dimensions.length,0);
});

// DESKTOP: owner answers first; every control uses the same scoped Workshop.
async function desktopAdapter(){
 const held={owner:'desktop-owner',program:'',stage:'Watching',instance:null,offers:[],proposal:null,taskId:null,
  schedules:[{id:'schedule-1',title:'Daily',operation:'Workflow',responsibility:'',selfReview:true,owner:'account-1'}]};
 let cards=[],failure=null,owner=true,writes=0;const methods=[];
 const rig=await adapter({signed_in:false},{
  '/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshop_scope:{root:'canvas',workshops:[{root:'workshop',is_general:true}]}},
  '/api/universal/workshop':body=>{
   if(body.function==='listTasks')return {result:[]};
   if(body.function==='listApprovals')return {result:globalThis.structuredClone(cards)};
   if(body.function==='readDesktop')return {result:owner?globalThis.structuredClone(held):{ok:false,error:'Owner unavailable'}};
   if(!['setDesktopProgram','offerDesktopAction','prepareDesktopAction','setScheduleResponsibility','reviewScheduledWork','decideDesktopAction'].includes(body.function))return {result:[]};
   methods.push(body);if(failure)return {result:{ok:false,error:failure}};
   const args=body.args;
   if(body.function==='setDesktopProgram')Object.assign(held,{program:args[0],instance:48884});
   if(body.function==='offerDesktopAction')Object.assign(held,{stage:'Offering',offers:[{action:'read',title:'Read selected geometry',payload:{source:{element:{id:'wall-1',label:'Wall 1'}}}}]});
   if(body.function==='setScheduleResponsibility'){Object.assign(held.schedules[0],args[1]);return {result:globalThis.structuredClone(held.schedules[0])};}
   if(['prepareDesktopAction','reviewScheduledWork'].includes(body.function)){
    const kind=body.function==='prepareDesktopAction'?'desktop':'schedule',id=kind+'-card';
    if(!cards.some(c=>c.id===id))cards.push({id,approvalKind:kind,input_digest:'exact-'+kind,status:'pending',rows:[]});
    if(kind==='desktop')Object.assign(held,{stage:'Needs OK',taskId:id});
    return {result:globalThis.structuredClone(cards.find(c=>c.id===id))};
   }
   if(body.function==='decideDesktopAction'){
    const card=cards.find(c=>c.id===args[0]);assert.equal(args[1],card.input_digest);
    if(args[2]==='approve'){if(card.approvalKind==='desktop')writes++;card.status='approved';held.stage='Applied';}
    else card.status='declined';return {result:globalThis.structuredClone(card)};
   }
   return {result:globalThis.structuredClone(held)};
  }});
 await rig.api.listTasks();
 return {...rig,methods,writes:()=>writes,refuse:v=>failure=v,loseOwner:()=>owner=false};
}
for(const [name,args] of [['setDesktopProgram',['Revit']],['offerDesktopAction',[]],['prepareDesktopAction',[]],
 ['setScheduleResponsibility',['schedule-1',{responsibility:'Review output',selfReview:false}]],['reviewScheduledWork',['schedule-1']]])
 test('DESKTOP '+name+' dispatches the exact scoped owner and reads back',async()=>{
  const rig=await desktopAdapter();assert.equal(rig.api.supportsAction(name),true);
  await rig.api[name](...args);const call=rig.methods.find(r=>r.function===name);
  assert.equal(call.action,'data-api');assert.equal(call.root,'workshop');assert.equal(call.scope,'canvas');
  assert.deepEqual(call.args,args);assert.equal(rig.writes(),0);
  if(name==='setScheduleResponsibility')assert.equal(rig.api.getSnapshot().schedules[0].responsibility,'Review output');
 });
test('DESKTOP approval and denial use one card digest; schedule review never replays a run',async()=>{
 const rig=await desktopAdapter(),card=await rig.api.prepareDesktopAction();assert.equal(rig.writes(),0);
 assert.equal((await rig.api.prepareDesktopAction()).id,card.id);
 await rig.api.approve(card.id);assert.equal(rig.writes(),1);
 const review=await rig.api.reviewScheduledWork('schedule-1');await rig.api.approve(review.id);assert.equal(rig.writes(),1);
 const other=await desktopAdapter(),declined=await other.api.prepareDesktopAction();await other.api.decline(declined.id);assert.equal(other.writes(),0);
});
test('DESKTOP missing owner and backend refusal preserve confirmed state',async()=>{
 const rig=await desktopAdapter(),before=globalThis.structuredClone(rig.api.getSnapshot().desktop);
 rig.refuse('Source changed');await assert.rejects(()=>rig.api.offerDesktopAction(),/Source changed/);
 assert.deepEqual(globalThis.structuredClone(rig.api.getSnapshot().desktop),before);
 rig.loseOwner();await rig.api.readDesktop();assert.equal(rig.api.supportsAction('prepareDesktopAction'),false);
 await assert.rejects(()=>rig.api.prepareDesktopAction(),/unavailable/);
 assert.equal(rig.api.getSnapshot().desktop.program,'');
});
test('DESKTOP rendered existing scene exposes the three owner-bound controls and opens its exact approval',async()=>{
 const rig=await desktopAdapter(),studio=path.resolve(__dirname,'../../01.APP/nodelang/studio'),babel={};
 vm.runInNewContext(fs.readFileSync(path.join(studio,'vendor/babel.js'),'utf8'),babel);
 const shown=[],u={go(){},show:(...args)=>shown.push(args)};
 const React={useState:v=>[v,()=>{}],createElement:(type,props,...children)=>({type,props:props||{},children}),Fragment:'fragment'};
 const window={UI:{api:rig.api,useApp:()=>u,useData:()=>rig.api.getSnapshot(),useAction:()=>({run:fn=>fn()}),
  Heading:'Heading',Empty:'Empty',Btn:'Btn',Card:'Card',Chip:'Chip',bindActions:(map,handlers)=>(id,...args)=>handlers[map[id]](...args),ActionStatus:'ActionStatus'}};
 const context=vm.createContext({window,React,console});
 vm.runInContext(babel.Babel.transform(fs.readFileSync(path.join(studio,'desktop.jsx'),'utf8'),{presets:['react']}).code,context);
 let tree=window.UI.DesktopScene();const select=nodes(tree).find(n=>n.props?.['aria-label']==='Working in');assert.ok(select);
 await select.props.onChange({target:{value:'Revit'}});
 tree=window.UI.DesktopScene();await nodes(tree).find(n=>n.type==='Btn'&&text(n)==='Suggest').props.onClick();
 tree=window.UI.DesktopScene();await nodes(tree).find(n=>n.type==='Btn'&&text(n)==='Prepare the change').props.onClick();
 assert.deepEqual(globalThis.structuredClone(shown),[['Approve',{id:'desktop-card'}]]);assert.equal(rig.writes(),0);
});

for(const name of ['setDesktopProgram','offerDesktopAction','prepareDesktopAction','setScheduleResponsibility','reviewScheduledWork'])
 test('DESKTOP '+name+' stays hidden until its owner answers',async()=>{
  const {api,requests}=await adapter({signed_in:false});const calls=()=>requests.filter(row=>row.body?.function===name).length,count=calls();
  assert.equal(api.supportsAction(name),false);
  await assert.rejects(()=>api[name](),/unavailable/);assert.equal(calls(),count);
 });

test('DESKTOP rendered schedule responsibility saves partial changes and opens the finished-run card',async()=>{
 const rig=await desktopAdapter(),studio=path.resolve(__dirname,'../../01.APP/nodelang/studio'),babel={};
 vm.runInNewContext(fs.readFileSync(path.join(studio,'vendor/babel.js'),'utf8'),babel);
 const shown=[],u={show:(...args)=>shown.push(args)};
 const React={createElement:(type,props,...children)=>({type,props:props||{},children}),Fragment:'fragment'};
 const window={ArchHubAPI:{executeAction:(name,user,...args)=>name==='ui.show'?user.show(...args):rig.api[name](...args)},
  UI:{api:rig.api,useApp:()=>u,useData:()=>rig.api.getSnapshot(),D:{Toggle:'Toggle'},Btn:'Btn',Card:'Card',Chip:'Chip',Heading:'Heading',Table:'Table'}};
 const context=vm.createContext({window,React,console});
 vm.runInContext(babel.Babel.transform(fs.readFileSync(path.join(studio,'workflow-states.jsx'),'utf8'),{presets:['react']}).code,context);
 let tree=window.UI.ScheduleResponsibility({id:'schedule-1'});
 await nodes(tree).find(n=>n.props?.['aria-label']==='Responsibility Daily').props.onChange({target:{value:'Check the actual output'}});
 tree=window.UI.ScheduleResponsibility({id:'schedule-1'});
 await nodes(tree).find(n=>n.type==='Toggle').props.onCheckedChange(false);
 assert.equal(rig.api.getSnapshot().schedules[0].responsibility,'Check the actual output');
 assert.equal(rig.api.getSnapshot().schedules[0].selfReview,false);
 await nodes(tree).find(n=>n.type==='Btn'&&text(n)==='Review lesson').props.onClick();
 assert.deepEqual(globalThis.structuredClone(shown),[['Approve',{id:'schedule-card'}]]);
 rig.loseOwner();await rig.api.readDesktop();tree=window.UI.ScheduleResponsibility({id:'schedule-1'});
 assert.equal(nodes(tree).some(n=>n.type==='Btn'||n.type==='input'||n.type==='select'||n.type==='Toggle'),false);
});

for(const [name,args,result,key,expected] of [
 ['setProviderModel',['ollama','ollama/model'],{providerPreferences:{ollama:'ollama/model'}},'providerPreferences',{ollama:'ollama/model'}],
 ['disconnectSecret',['social-entry'],{ok:true,state:'removed',provider_token_revoked:false,secrets:[]},'secrets',[]],
 ['setCompanionState',[{mode:'listening',x:20,y:30,pinned:true}],{companion:{mode:'listening',x:20,y:30,pinned:true}},'companion',{mode:'listening',x:20,y:30,pinned:true}],
 ['exposeSettingsPage',['Appearance'],{id:'owner-node',page:'Appearance'},null,null],
])test('SETTINGS '+name+': executes the existing Settings owner and publishes readback',async()=>{
 const {api,calls}=await buttonsAdapter({}, {
  '/api/universal/settings-action':body=>({ok:true,result:body.function==='readControls'?{companion:{mode:'idle'},secrets:[],providerPreferences:{},providerModels:{}}:result}),
  '/api/universal/social-connections':()=>({items:[]})
 });
 assert.equal(api.supportsAction(name),true);assert.equal(api.supportsAction('signInProvider'),false);
 calls.length=0;const answer=await api[name](...args);
 const command=calls.find(c=>c.body?.function===name);
 assert.deepEqual(command,{url:'/api/universal/settings-action',body:{function:name,args}});
 assert.equal(answer.id||answer.state||answer.companion?.mode||answer.providerPreferences?.ollama,
  result.id||result.state||result.companion?.mode||result.providerPreferences?.ollama);
 if(key)assert.deepEqual(JSON.parse(JSON.stringify(api.getSnapshot()[key])),expected);
 if(name==='exposeSettingsPage')assert.ok(calls.some(c=>c.url==='/api/universal/canvas'));
});

test('SETTINGS readNotification: binds Workshop source and uses durable receipt readback',async()=>{
 const {api,calls}=await buttonsAdapter({}, {
  '/api/universal/settings-action':()=>({ok:true,result:{secrets:[],providerPreferences:{},providerModels:{},companion:{mode:'idle'}}}),
  '/api/universal/workshop':body=>({ok:true,result:body.function==='readNotification'?{receipt:'receipt-node',notifications:[{id:'message',read:true}]}:[]})
 });
 assert.equal(api.supportsAction('readNotification'),true);calls.length=0;
 await api.readNotification('message');const command=calls.find(c=>c.body?.function==='readNotification');
 assert.equal(command.url,'/api/universal/workshop');assert.deepEqual(command.body.args,['message']);
 assert.equal(command.body.root,'workshop');assert.equal(command.body.scope,'graph');
 assert.equal(api.getSnapshot().notifications[0].read,true);
});

test('SETTINGS refusal preserves confirmed companion state',async()=>{
 let refused=false;
 const {api}=await buttonsAdapter({}, {'/api/universal/settings-action':body=>({ok:true,result:
  body.function==='readControls'?{companion:{mode:'idle',pinned:false},secrets:[],providerPreferences:{},providerModels:{}}:
  refused?{ok:false,message:'Position refused'}:{companion:{mode:'idle',pinned:true}}})});
 await api.setCompanionState({pinned:true});refused=true;
 await assert.rejects(api.setCompanionState({pinned:false}),/Position refused/);
 assert.equal(api.getSnapshot().companion.pinned,true);
});

test('SETTINGS slow control read cannot overwrite a confirmed companion write',async()=>{
 let release,delay=false;
 const initial={companion:{mode:'idle',pinned:false},secrets:[],providerPreferences:{},providerModels:{}};
 const {api}=await buttonsAdapter({}, {'/api/universal/settings-action':async body=>({ok:true,result:
  body.function==='readControls'?(delay?await new Promise(resolve=>release=()=>resolve(initial)):initial):{companion:{mode:'idle',pinned:true}}})});
 delay=true;const read=api.refreshSettingsControls();await Promise.resolve();
 await api.setCompanionState({pinned:true});release();await read;
 assert.equal(api.getSnapshot().companion.pinned,true);
});
