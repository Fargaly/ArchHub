const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

const signedInAccount={signed_in:true,email:'court-user@example.test',user_id:'court-user'};
function desktopAccess(account=signedInAccount){
 return account.signed_in
  ? {ok:true,admitted:true,state:'admitted',subject:account.user_id,email:account.email}
  : {ok:true,admitted:false,state:'signed_out',subject:null,email:null};
}

test('CLOUD404 account and control availability survive both refresh orders and recover',async()=>{
 const account={...signedInAccount};
 const message='Signed in. Office invitations unavailable until the cloud service is updated.';
 let accountErrors={officeInvitations:message},controlErrors={secrets:'Connected account unavailable'};
 const {api}=await adapter(account,{'/api/universal/settings-action':body=>({ok:true,result:
  body.function==='read'?{profile:{plan:'Personal'},officeInvitations:[],controlErrors:accountErrors}:{controlErrors}})});
 await new Promise(resolve=>globalThis.setImmediate(resolve));
 await api.refreshSettingsAccount();await api.refreshSettingsControls();
 assert.equal(api.getSnapshot().profile.signedIn,true);
 assert.equal(api.getSnapshot().profile.plan,'Personal');
 assert.equal(api.getSnapshot().controlErrors.officeInvitations,message);
 assert.equal(api.getSnapshot().controlErrors.secrets,'Connected account unavailable');
 await api.refreshSettingsAccount();
 assert.equal(api.getSnapshot().controlErrors.secrets,'Connected account unavailable');
 controlErrors={};await api.refreshSettingsControls();
 assert.equal(api.getSnapshot().controlErrors.secrets,undefined);
 assert.equal(api.getSnapshot().controlErrors.officeInvitations,message);
 controlErrors={providerModels:'Model catalogue unavailable'};await api.refreshSettingsControls();
 accountErrors={};await api.refreshSettingsAccount();
 assert.equal(api.getSnapshot().controlErrors.officeInvitations,undefined);
 assert.equal(api.getSnapshot().controlErrors.providerModels,'Model catalogue unavailable');
 account.signed_in=false;account.email='';await api.refreshDesktopAccess();
 assert.equal(api.getSnapshot().desktopAccess.state,'signed_out');
 assert.equal(api.getSnapshot().controlErrors,undefined);
});

async function adapter(account, responses={}){
 const requests=[],events=new Map();
 const window={ARCHHUB_AUTHORITY:{},structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{home_load_ms:60000,token:'local-lease',csrf:'csrf'},
  Uint8Array:globalThis.Uint8Array,cancelAnimationFrame(){},dispatchEvent(e){events.get(e.type)?.(e);},addEventListener(name,fn){events.set(name,fn);},AH:{inkSoft:'#888'},crypto:require('node:crypto')};
 window.ArchHubStudioAuthority={create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}};
 const context={window,setTimeout,clearTimeout,document:{hidden:true,addEventListener(){}},
  CustomEvent:class {},sessionStorage:{getItem(){return null;}},URLSearchParams,TextEncoder:globalThis.TextEncoder,TextDecoder:globalThis.TextDecoder,AbortSignal:globalThis.AbortSignal,console,
  fetch:async(url,options)=>{
   requests.push({url,body:options.body&&JSON.parse(options.body)});
   let data={ok:true};
   if(url==='/api/commands')data={commands:[]};
   if(url==='/api/universal/canvas')data={root:'canvas',nodes:[],wires:[],
    authorization:{principal:'local-process',display_name:'Local transport'}};
   if(url==='/api/universal/desktop-access')data=desktopAccess(account);
   if(url==='/api/universal/cloud-session')data={...account};
   if(url==='/api/universal/cloud-signin'&&!options.body)data={ok:true,phase:account.signed_in?'done':'idle'};
   if(Object.hasOwn(responses,url))data=await (typeof responses[url]==='function'?responses[url](options.body&&JSON.parse(options.body)):responses[url]);
   if(url==='/api/universal/cloud-signin'&&options.body)Object.assign(account,
    {signed_in:true,email:'user@example.test',user_id:'account-1',display_name:'Account user'});
   if(url==='/api/universal/cloud-signout')Object.assign(account,{signed_in:false,email:''});
   // The model router answers a chat as a stream (/api/router/chat), or refuses it.
   if(url==='/api/router/chat'){const sent={value:false};return {ok:data.ok!==false,status:data.ok===false?409:200,json:async()=>data,
    body:{getReader:()=>({read:async()=>{if(sent.value)return {done:true,value:undefined};sent.value=true;return {done:false,value:new TextEncoder().encode('data: '+JSON.stringify({result:data.result||{answer:'ok'}})+'\n\n')};},releaseLock(){}})}};}
   return {ok:true,status:200,json:async()=>data};
  }};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/api.js'),'utf8'),context);
 if(account.signed_in)await window.ArchHubAPI.ready;
 else await window.ArchHubAPI.refreshDesktopAccess();
 return {api:window.ArchHubAPI,requests,window};
}

test('unfinished controls use actual adapter availability without invoking an action',async()=>{
 const {api,requests}=await adapter({...signedInAccount});const count=requests.length;
 assert.equal(api.supportsAction('startVoiceInput'),false);
 assert.equal(api.supportsAction('changePlan'),false);
 assert.equal(api.supportsAction('reviewProofRow'),false);
 assert.equal(api.supportsAction('signIn'),true);
 assert.equal(api.supportsAction('setProviderEnabled'),true);
 assert.equal(api.supportsAction('missing-action'),false);
 assert.equal(api.supportsAction('archiveActivity'),true);
 assert.equal(api.supportsAction('ensureDependency'),true);
 assert.equal(api.supportsAction('decline'),false);
 assert.equal(api.supportsAction('approve','session'),false);
 // runValuation, correctAnswerSource, setResearchReview, runResearchNode (RESEARCHNODES) and signInProvider (CUSTOMMCP) have owners now.
 for(const name of ['setApprovalRubric','stampOutput','runSpecialNode','setTranscriptPass','startVoiceInput','stopVoiceInput','speak','setDesktopProgram','offerDesktopAction','prepareDesktopAction','settleTimesheet','postponeApproval','resumeApproval','contestDecision','setScheduleResponsibility','reviewScheduledWork','importHostSkill','inspectConnectorBundle','configureConnectorBundle','installConnectorBundle','setHostSkillEnabled','auditHostSkill','refreshApproval','addDimension','reviewProofRow','setWatcherView','editWall','addMark','addComment','proposeWatcherEdit','discardWatcherChanges','setWatcherHost','changePlan'])assert.equal(api.supportsAction(name),false,name);
 assert.equal(requests.length,count);
});

test('unfinished controls and modal launchers are omitted from the rendered design',async()=>{
 const {api}=await adapter({...signedInAccount},{'/api/universal/providers':{providers:[{id:'codex',name:'Codex',enabled:true,signedIn:true}]}});
 await api.listProviders();
 const {JSDOM}=require('jsdom');
 const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,studio=path.join(__dirname,'../../01.APP/nodelang/studio');
 const snapshot={...api.getSnapshot(),approvals:[{id:'review',title:'Review',status:'pending',kind:'model',rows:[]}],connections:[{id:'youtube',name:'YouTube',connected:true}],hostSkills:[]};
 w.ArchHubAPI={...api,getSnapshot:()=>snapshot};w.matchMedia=()=>({matches:false});w.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};
 for(const name of ['vendor/react.js','vendor/react-dom.js','vendor/babel.js'])w.eval(fs.readFileSync(path.join(studio,name),'utf8'));
 for(const name of ['tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx','ds_settings3.jsx','workflow-states.jsx','agent-states.jsx','answer-widgets.jsx'])w.eval(w.Babel.transform(fs.readFileSync(path.join(studio,name),'utf8'),{presets:['react']}).code);
 const root=w.ReactDOM.createRoot(w.document.getElementById('root'));
 const render=(component,props={})=>w.ReactDOM.flushSync(()=>root.render(w.React.createElement(w.UI.Ctx.Provider,{value:{act:fn=>fn(),composerDraft:{text:'',revision:0},setComposerDraft(){}}},w.React.createElement(component,props))));
 try{
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
  render(w.UI.ActionEvidence,{id:'review'});
  assert.doesNotMatch(w.document.body.textContent,/Request another review/);
 }finally{root.unmount();dom.window.close();}
});

test('Interface Studio refuses placement without a workflow and keeps the current projection',async()=>{
 const {api,requests}=await adapter({...signedInAccount},{'/api/commands':{commands:[]}});
 const before=api.getSnapshot().graph;
 await assert.rejects(()=>api.addInterfaceElement('Button'),/Open a workflow/);
 assert.equal(requests.some(r=>r.body?.op==='add_interface_element'),false);
 assert.equal(api.getSnapshot().graph,before);
});


test('Interface Studio preserves the newer file readback when an older placement finishes late',async()=>{
 const path='C:/isolated/interface.archhub';
 const document=revision=>({format:'archhub',version:1,id:'draft',title:'Interface',properties:{revision},
  nodes:['one','two'].slice(0,revision).map(id=>({id,item:'ui_element',type:'data.constant',title:'Button',
   position:{x:80,y:100},params:{element:'Button',label:id}})),wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom:1}});
 let revision=0,readCount=0,releaseOld,markOld;
 const oldStarted=new Promise(resolve=>{markOld=resolve;});
 const oldRead=new Promise(resolve=>{releaseOld=resolve;});
 const {api}=await adapter({...signedInAccount},{
  '/api/commands':{commands:[]},
  '/api/session-files':async body=>{
   if(body.action==='initial')return {ok:true,document:document(0),path};
   if(body.action==='catalogue')return {ok:true,directory:'C:/isolated',sessions:[],recent:[],
    items:[{id:'ui_element',engine:'data.constant',title:'UI element',cat:'input',params:{},ports:{source:[],target:[]}}]};
   if(body.action==='head')return {ok:true,revision};
   if(body.action==='read'){
    const count=++readCount;
    if(count===1){markOld();await oldRead;}
    return {ok:true,document:document(count),revision:count};
   }
   return {ok:true};
  },
  '/api/universal/canvas-op':body=>{
   assert.deepEqual(body.args,['Button',path]);
   return {ok:true,result:{id:++revision===1?'one':'two'}};
  }
 });
 const older=api.addInterfaceElement('Button');
 try{
  await oldStarted;
  assert.equal((await api.addInterfaceElement('Button')).id,'two');
 }finally{releaseOld();await older;}
 assert.deepEqual(Array.from(api.getSnapshot().graph.nodes,n=>[n.id,n.kind]),[['one','UI element'],['two','UI element']]);
});

test('OPS history review community and MCP project the returned owner data',async()=>{
 const metadata={versions:[{id:'version-1'}],modelReview:{operation:'Naming Check',results:[{detail:'Actual result'}],issues:[]},dismissed:['suggestion']};
 const community={peers:[{id:'peer',subscribed:true}],patterns:[]};
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/canvas-op':body=>{
  if(body.op==='project_state')return {ok:true,result:metadata};
  if(body.op==='mcp_servers')return {ok:true,result:[{id:'server',status:'Negotiated',tools:[]}]};
  if(['community_state','subscribe_community','review_community_pattern'].includes(body.op))return {ok:true,result:community};
  if(body.op==='import_mcp_tool')return {ok:false,error:'Open this admitted tool in its Workshop work'};
  return {ok:true,result:{id:'confirmed'}};
 }});
 await assert.rejects(api.reviewModel('Naming Check'),/unavailable/);
 await assert.rejects(api.reviewModel('Clash & Issues',{document:'wrong'}),/workflow changed/);
 await api.updateReviewIssue('issue',{status:'Closed'});await api.dismissSuggestion('suggestion');
 await api.subscribeCommunity('peer');await api.reviewCommunityPattern('pattern','Accept');
 assert.equal(api.getSnapshot().community.peers[0].subscribed,true);
 await api.discoverMcpTools('server','Tools');await api.reconnectMcp('server');
 assert.equal(api.getSnapshot().mcpServers[0].id,'server');
 const operations=requests.filter(r=>r.body?.op).map(r=>r.body.op);
 for(const name of ['update_review_issue','dismiss_suggestion','subscribe_community','review_community_pattern','discover_mcp_tools','reconnect_mcp'])assert.ok(operations.includes(name),name);
});

test('OPS mod actions preserve the native review digest and refresh from the package owner',async()=>{
 const calls=[];
 const mod={id:'rows',name:'Rows',nodes:[],enabled:true};
 const {api}=await adapter({...signedInAccount},{'/api/universal/mods':body=>{
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
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/social-surface':body=>{
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
 const {api}=await adapter({...signedInAccount},{'/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshops:[{root:'room'}]},
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
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshops:[{root:'room'}]},
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
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshops:[{root:'room'}]},
  '/api/universal/pick-file':()=>({ok:true,path:picked}),
  '/api/universal/canvas-op':body=>({ok:true,result:body.op==='project_files'?[file]:file}),
  '/api/router/chat':()=>refused?{ok:false,error:'Choose an available agent'}:{ok:true,result:{answer:'Read'}},
  '/api/universal/workshop':body=>({ok:true,result:body.function==='listTasks'?[]:{id:'work-real'}})});
 const made=await api.addFile();api.addComposerAttachment(made.id);
 await assert.rejects(()=>api.sendToBaboom('Read it'),/available agent/);
 assert.equal(api.getSnapshot().composerAttachments.length,1);
 refused=false;await api.sendToBaboom('Read it');
 assert.equal(api.getSnapshot().composerAttachments.length,0);
 assert.ok(requests.filter(r=>r.url==='/api/router/chat').at(-1).body.prompt.includes(file.path));
 picked='';assert.equal(await api.addFile(),null);
});

test('a local transport lease never becomes the account profile',async()=>{
 const {api}=await adapter({signed_in:false,email:''});
 await assert.rejects(()=>api.syncAccount(),/Sign in to archhub.io/);
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
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/workspace-roots':body=>body?.action==='browse'?{ok:true,path:'C:/WORK'}:{ok:true,roots:[]}});
 await api.addWorkspace();
 const writes=requests.filter(r=>r.url==='/api/universal/workspace-roots').map(r=>r.body);
 const start=writes.findIndex(body=>body?.action==='browse');
 assert.deepEqual(writes.filter(body=>body?.action!=='list'),[{action:'browse'},{action:'register',path:'C:/WORK',privacy:'private',profile:'client'}]);
 assert.equal(writes.at(-1).action,'list');
 assert.ok(start>=0);
});

test('cancelled native folder selection never registers a workspace',async()=>{
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/workspace-roots':{ok:true,path:'',roots:[]}});
 const cancelled=await api.addWorkspace();
 assert.equal(cancelled.cancelled,true);
 assert.equal(cancelled.message,'No workspace was added.');
 assert.equal(requests.some(r=>r.body?.action==='register'),false);
});

test('Docs retains generated guides and the glossary from the documentation owner',async()=>{
 const {api}=await adapter({...signedInAccount},{'/api/documentation':{tutorials:[{id:'account-web',title:'Account',description:'Sign in',text:'# Account\nUse browser sign-in.'}],
  glossary:[{term:'Node',definition:'One block on the canvas.'}]}});
 const docs=await api.refreshDocs();
 assert.equal(docs.length,1);
 assert.equal(docs.find(d=>d.id==='account-web').route,'settings/Account');
 assert.deepEqual(Array.from(docs.find(d=>d.id==='account-web').steps),['# Account','Use browser sign-in.']);
 assert.deepEqual(Array.from(api.getSnapshot().bookGlossary),['| Node | One block on the canvas. |']);
});


test('update status is read from the existing lifecycle and never inferred from graph configuration',async()=>{
 const {api}=await adapter({...signedInAccount},{'/api/universal/application-update':{ok:true,
  state:'ready',current_build:'installed',available_build:'next',restart_supported:true,detail:'Verified download'}});
 await api.refreshApplicationUpdate();
 for(let i=0;i<200&&api.getSnapshot().update.installed!=='installed';i++)await new Promise(resolve=>setTimeout(resolve,5));
 const update=api.getSnapshot().update;
 assert.equal(update.installed,'installed');assert.equal(update.next,'next');
 assert.equal(update.available,true);assert.equal(update.detail,'Verified download');
});

test('check, restart and confirmation use the existing update actions',async()=>{
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/application-update':body=>({ok:true,
  state:body?.action==='reload'?'restarting':body?.action==='acknowledge'?'idle':'ready',current_build:'installed',available_build:body?.action==='acknowledge'?null:'next',restart_supported:true})});
 await api.checkForUpdates();await api.installUpdate();await api.acknowledgeUpdate();
 assert.deepEqual(requests.filter(r=>r.url==='/api/universal/application-update'&&r.body).map(r=>r.body),
  [{action:'check'},{action:'reload'},{action:'acknowledge'}]);
 assert.equal(api.getSnapshot().update.available,false);
});

test('failed update checks and missing desktop lifecycle never offer restart',async()=>{
 for(const status of [{state:'failed',detail:'Feed unreachable',restart_supported:true},
  {state:'ready',available_build:'next',restart_supported:false}]){
  const {api,requests}=await adapter({...signedInAccount},{'/api/universal/application-update':{ok:true,current_build:'installed',...status}});
  await api.refreshApplicationUpdate();
  assert.equal(api.getSnapshot().update.available,false);
  await assert.rejects(()=>api.installUpdate());
  assert.equal(requests.some(r=>r.body?.action==='reload'),false);
 }
});

test('a native ready notification refreshes the approved design without the retired transport',async()=>{
 let ready=false;
 const {api,window,requests}=await adapter({...signedInAccount},{'/api/universal/application-update':()=>({ok:true,
  state:ready?'ready':'idle',current_build:'installed',available_build:ready?'next':null,restart_supported:true})});
 await api.refreshApplicationUpdate();const before=requests.length;ready=true;
 window.dispatchEvent({type:'archhub:update-ready'});
 for(let tick=0;tick<20&&!api.getSnapshot().update.available;tick++)await new Promise(resolve=>globalThis.setImmediate(resolve));
 assert.equal(api.getSnapshot().update.available,true);
 assert.ok(requests.slice(before).some(r=>r.url==='/api/universal/application-update'&&!r.body));
});

test('a stale status read cannot erase a newer checked release',async()=>{
 let release,hold=false;
 const {api}=await adapter({...signedInAccount},{'/api/universal/application-update':body=>
  body?{ok:true,state:'ready',available_build:'next',current_build:'installed',restart_supported:true}:
  hold?new Promise(resolve=>{release=resolve;}):{ok:true,state:'idle',current_build:'installed',restart_supported:true}});
 // Let the startup status read finish before holding the deliberate stale read.
 await new Promise(resolve=>globalThis.setImmediate(resolve));
 await api.refreshApplicationUpdate();hold=true;
 const old=api.refreshApplicationUpdate();
 await api.checkForUpdates();
 release({ok:true,state:'idle',current_build:'installed',restart_supported:true});await old;
 assert.equal(api.getSnapshot().update.available,true);assert.equal(api.getSnapshot().update.next,'next');
});

test('a refused restart clears the stale offer; each explicit retry asks the guard again',async()=>{
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/application-update':body=>body?
  {ok:false,error:'A Workshop job is running'}:{ok:true,state:'ready',available_build:'next',current_build:'installed',restart_supported:true}});
 await api.refreshApplicationUpdate();
 for(let i=0;i<200&&api.getSnapshot().update.installed!=='installed';i++)await new Promise(resolve=>setTimeout(resolve,5));
 await assert.rejects(()=>api.installUpdate(),/Workshop job/);
 // A refusal is temporary: the guard is read again and the offer (and its Update control) stays reachable.
 assert.equal(api.getSnapshot().update.available,true);
 assert.notEqual(api.getSnapshot().update.state,'failed');
 // Still busy: the second click reaches the guard and shows its current reason, not a replayed one.
 await assert.rejects(()=>api.installUpdate(),/Workshop job/);
 assert.equal(requests.filter(r=>r.body?.action==='reload').length,2);
 // A double click sends one restart request; the second waits behind the first.
 const both=await Promise.allSettled([api.installUpdate(),api.installUpdate()]);
 assert.equal(both.every(result=>result.status==='rejected'),true);
 assert.equal(requests.filter(r=>r.body?.action==='reload').length,3);
});

test('after a busy refusal, the next click installs once the agents are idle',async()=>{
 let busy=true;
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/application-update':body=>body?
  (busy?{ok:false,error:'deferred: pid 7888: 2 call(s) in flight'}:{ok:true,state:'restarting',current_build:'installed',restart_supported:true}):
  {ok:true,state:'ready',available_build:'next',current_build:'installed',restart_supported:true}});
 await api.refreshApplicationUpdate();
 for(let i=0;i<200&&api.getSnapshot().update.installed!=='installed';i++)await new Promise(resolve=>setTimeout(resolve,5));
 await assert.rejects(()=>api.installUpdate(),/in flight/);
 busy=false;
 await api.installUpdate();
 assert.equal(requests.filter(r=>r.body?.action==='reload').length,2);
 assert.equal(api.getSnapshot().update.state,'restarting');
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
 // The bundled Playwright Chromium, as the other rendered tests use; the installed Chrome never answered under the test queue.
 const cache=process.env.PLAYWRIGHT_BROWSERS_PATH||path.join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright');
 const newest=pattern=>(fs.existsSync(cache)?fs.readdirSync(cache):[]).filter(name=>pattern.test(name)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
 const shell=newest(/^chromium_headless_shell-\d+$/),full=newest(/^chromium-\d+$/);
 const executable=shell||full?path.join(cache,shell||full,shell?'chrome-headless-shell-win64/chrome-headless-shell.exe':'chrome-win64/chrome.exe'):'';
 assert.ok(executable&&fs.existsSync(executable),'The bundled Playwright Chromium is required.');
 assert.ok(profile.startsWith(fixture+path.sep));fs.mkdirSync(profile,{recursive:true});
 processHandle=spawn(executable,['--headless=new','--disable-default-apps','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:['ignore','ignore','pipe']});
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
 const {api}=await adapter({...signedInAccount});
 const s=await screen(['answer-widgets.jsx','integration-states.jsx'],api.getSnapshot(),`{
  refreshMcpServers:async()=>{if(refused)throw Error('Reconnect the actual tool server');const rows=[{id:'actual-server',name:'Actual server',status:'Negotiated',tools:[{id:'actual-tool',name:'Actual tool'}]}];testData.mcpServers=rows;return rows;},
  importMcpTool:async()=>{throw Error('Open this tool in its Workshop work');},
  // Import adds the tool to this window's open file (sw019): the screen names that file first.
  getSessionDocument:()=>({id:'open-file',properties:{}}),getSessionPath:()=>'/fixture/open.archhub'
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
test('Library uses the catalogue identity and stays open until explicitly closed',async()=>{
 const s=await screen('ds_library.jsx',{catalogue:[{id:'definition-id',name:'Readable label',family:'Get',description:'Reads data'}],templates:[],runs:[],graph:{name:'Graph'},mods:[]},`{addNode:async id=>{if(id!=='definition-id')throw Error('Wrong catalogue identity');return refused?{ok:false}:{id:'made'};}}`);
 try{
  const rejected=await s.evaluate(`(async()=>{let closed=0;window.readClosed=()=>closed;render(UI.LibraryShelf,{onClose:()=>closed++});await click(document.querySelector('[aria-label="Add Readable label"]'));return closed;})()`);
  assert.equal(rejected,0);
  const accepted=await s.evaluate(`(async()=>{refused=false;await click(document.querySelector('[aria-label="Add Readable label"]'));return readClosed();})()`);
  assert.equal(accepted,0,'CANVASLOOK keeps the shelf beside the canvas after a confirmed add');
  const closed=await s.evaluate(`(async()=>{await click(document.querySelector('[aria-label="Collapse library"]'));return readClosed();})()`);
  assert.equal(closed,1);
 }finally{await s.close();}
});
test('DS forwards a native button callback exactly once',async()=>{
 const s=await screen('docs.jsx',{docs:[],catalogue:[],bookGlossary:[]});
 try{assert.equal(await s.evaluate(`(async()=>{let activated=0;render(AH_DS.Btn,{onClick:()=>activated++,children:'Press'});await click(document.querySelector('button'));return activated;})()`),1);}
 finally{await s.close();}
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
 const requests=[],w={structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{home_load_ms:60000,token:'lease',csrf:'csrf'},addEventListener(){},dispatchEvent(){},AH:{},crypto:require('node:crypto')};
 let fail=false;
 w.ArchHubStudioAuthority={create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}};
 vm.runInNewContext(fs.readFileSync(path.join(studio,'api.js'),'utf8'),{window:w,setTimeout,clearTimeout,document:{hidden:true,addEventListener(){}},CustomEvent:class{},URLSearchParams,AbortSignal:globalThis.AbortSignal,console,
  fetch:async(url,options)=>{
   const body=options.body&&JSON.parse(options.body);requests.push({url,body});let result={ok:true};
   if(url==='/api/commands')return {ok:true,status:200,json:async()=>({commands:[]})};
   if(url==='/api/universal/desktop-access')result=desktopAccess();
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
 const {api,requests}=await fileAdapter();
 await api.openSession('/fixture/scheduled.archhub');
 await api.setScheduleTime('schedule','09:30');await api.saveSkill('Workflow');
 assert.deepEqual(requests.find(r=>r.body?.op==='set_schedule_time').body.args,['schedule','09:30']);
 // A schedule edit refreshes the project owners; Save skill saves the open file and re-reads the Library catalogue.
 assert.ok(requests.some(r=>r.body?.op==='list_skills')&&requests.some(r=>r.body?.op==='project_schedules'));
 const save=requests.findIndex(r=>r.url==='/api/session-files'&&r.body.document?.title==='Workflow');
 assert.ok(save>=0,'the skill is the saved open file');
 assert.ok(requests.slice(save).some(r=>r.body?.action==='catalogue'),'the Library re-reads its catalogue after the save');
});

test('wire rule edits check the rule with the file owner and keep it on the open file\'s wire',async()=>{
 const wire={id:'wire',from:{node:'a',socket:'out'},to:{node:'b',socket:'in'}};
 const {api,requests}=await fileAdapter({document:{format:'archhub',version:1,id:'doc-w',title:'Wires',nodes:[],wires:[wire],groups:[],notes:[],properties:{}}});
 await api.openSession('/fixture/wires.archhub');
 await api.setWireRule('wire','value > 1');
 assert.equal(requests.find(r=>r.body?.action==='wire-rule').body.rule,'value > 1');
 assert.equal(api.getSessionDocument().wires[0].rule,'value > 1');
 await api.setWireRule('wire','value > 2');
 assert.equal(api.getSessionDocument().wires[0].rule,'value > 2');
});
}
// WIRE-projects end
test('WIRE-rest absent canvas commands reject with a repair action and do not synthesize state',async()=>{
 const {api,requests}=await adapter({...signedInAccount});
 await assert.rejects(()=>api.createCommunityGroup('Test group'),/System graph/);
 assert.equal(api.getSnapshot().community.groups.length,0);
 assert.equal(requests.some(r=>r.url==='/api/universal/interaction'),false);
});

test('WIRE-rest command uses the admitted control, current revision and typed submitted facts',async()=>{
 const canvas={root:'canvas',revision:'rev-7',nodes:[],wires:[],scope:{current:'scope-1'},interaction_projection:{bindings:[
  {control:'createCommunityGroup',interaction:'command-1',event:'activate',event_facts:[{source:'submitted',input:'name'}]}
 ]}};
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/canvas':canvas,
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
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/canvas':canvas,
  '/api/universal/interaction':{ok:false,error:'Membership requires owner review'}});
 await assert.rejects(()=>api.createCommunityGroup('Test group'),/Membership requires owner review/);
 assert.equal(requests.filter(r=>r.url==='/api/universal/interaction').length,1);
 assert.equal(api.getSnapshot().community.groups.length,0);
});

// The command owner's /api/commands payload (command_registry.payload), read once in a throwaway profile.
let registry=null;
function commandRegistry(){
 if(registry)return registry;
 const os=require('node:os'),{execFileSync}=require('node:child_process');
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'account-registry-'));
 try{
  const env={...process.env,LOCALAPPDATA:profile,APPDATA:profile,USERPROFILE:profile};
  const script="import json,sys;sys.path.insert(0,'.');from nodelang.command_registry import payload;print(json.dumps(payload()))";
  registry=JSON.parse(execFileSync(process.env.ARCHHUB_PYTHON||'python',['-I','-B','-c',script],{cwd:path.join(__dirname,'../../01.APP'),env,windowsHide:true,encoding:'utf8'}));
 }finally{fs.rmSync(profile,{recursive:true,force:true});}
 return registry;
}

async function restScreen(component, api, state, props={}) {
 const {JSDOM}=require('jsdom');
 const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
 const win=dom.window;
 for(const vendorFile of ['react.js','react-dom.js','babel.js'])win.eval(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/vendor',vendorFile),'utf8'));
 const React=win.React;
 const element=tag=>({children,...props})=>React.createElement(tag,props,children);
 const navigation=[];
 if(component==='NodeDetails')win.ArchHubAPI=api;
 const u={go:route=>navigation.push(route),show:(name,data)=>navigation.push({name,data}),setSelectedNodeId:id=>navigation.push({select:id}),advanced:false};
 win.AHIcon=()=>null;
 // Menus are the command owner's projection (/api/commands), read from that owner itself so this file runs on its own.
 win.ArchHubCommandRegistry=commandRegistry();
 // productLabel is ui.jsx's label translator (aba0f4be); English settings return the label unchanged.
 win.UI={api,productLabel:label=>label,A:{ok:'green',warn:'orange',inkSoft:'gray'},D:{Toggle:({checked,onCheckedChange,label})=>React.createElement('input',{type:'checkbox',checked,'aria-label':label,onChange:event=>onCheckedChange(event.target.checked)})},
  useData:()=>state,useApp:()=>u,Btn:({p,sm,ghost,danger,...props})=>React.createElement('button',props),Card:element('section'),Chip:element('span'),
  Heading:({title,children})=>React.createElement('header',null,title,children),Empty:element('p'),Table:({rows})=>React.createElement('pre',null,JSON.stringify(rows)),SettingControl:()=>null,Av:()=>null};
 for(const screenFile of ['answer-widgets.jsx','community-tools.jsx','decision-results.jsx','canvas-states.jsx','watcher-controls.jsx','desktop.jsx','context-menus.jsx',...(component==='NodeDetails'?['workflow-states.jsx']:[])]){
  win.eval(win.Babel.transform(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio',screenFile),'utf8'),{presets:['react']}).code);
 }
 for(const surfaceName of ['RefineComparison','ModelAvailability','HealthHistory','XrayLayers','Research','GraphMetadata','CapabilitySettings'])if(!win.UI[surfaceName])win.UI[surfaceName]=()=>null;
 const root=win.ReactDOM.createRoot(win.document.getElementById('root'));
 root.render(React.createElement(win.UI[component],props));
 const settle=()=>new Promise(resolve=>globalThis.setTimeout(resolve,20));await settle();
 return {win,root,navigation,settle,close(){root.unmount();dom.window.close();}};
}

test('WIRE-rest rendered Desktop shows waiting, real refusal, retry and the owner result',async()=>{
 const {api}=await adapter({...signedInAccount});let calls=0,release;
 const screen=await restScreen('DesktopScene',{...api,getDesktopCompanion:()=>{calls++;return calls===1?new Promise(resolve=>{release=resolve;}):Promise.resolve({ok:true,status:'running',message:'Native owner frame 17'});}},api.getSnapshot());
 try{
  const click=text=>{const button=[...screen.win.document.querySelectorAll('button')].find(b=>b.textContent===text);assert.ok(button,text);button.click();};
  click('Read companion state');await screen.settle();
  assert.match(screen.win.document.body.textContent,/Waiting for the owner/);
  assert.equal(screen.win.document.querySelector('button').disabled,true);
  release({ok:false,error:'Host refused: choose the active program in Connections'});await screen.settle();
  assert.match(screen.win.document.querySelector('[role="alert"]').textContent,/choose the active program/);
  assert.equal(calls,1);click('Retry action');
  for(let attempt=0;attempt<50&&!screen.win.document.body.textContent.includes('Native owner frame 17');attempt++)await screen.settle();
  assert.match(screen.win.document.body.textContent,/Native owner frame 17/);assert.equal(calls,2);
  click('BABOOM settings');assert.deepEqual(screen.navigation,['settings/BABOOM']);
 }finally{screen.close();}
});


test('WIRE-rest command rejects a changed input schema before posting',async()=>{
 const canvas={root:'canvas',nodes:[],wires:[],interaction_projection:{bindings:[{control:'createCommunityGroup',interaction:'i',event:'activate',event_facts:[]}]}};
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/canvas':canvas});
 await assert.rejects(()=>api.createCommunityGroup('Group'),/input schema changed/);
 assert.equal(requests.some(r=>r.url==='/api/universal/interaction'),false);
});

test('WIRE-rest rendered community preserves rejected drafts and executes its registered owner callback',async()=>{
 const {api}=await adapter({...signedInAccount});let calls=0;
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
 const {api}=await adapter({...signedInAccount});
 for(const component of ['GraphProperties','RefineComparison','WatcherDimensions']){
  const screen=await restScreen(component,api,api.getSnapshot());
  try{assert.ok(screen.win.document.getElementById('root').textContent.length>0,component);}
  finally{screen.close();}
 }
});

test('WIRE-rest context menu keeps a refused owner action and Retry inside the menu',async()=>{
 const {api}=await adapter({...signedInAccount});let calls=0;
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
  ARCHHUB_BOOT:{home_load_ms:60000,token:'fixture',csrf:'fixture'},document:{hidden:true,addEventListener(){}},
  addEventListener:(name,fn)=>events.set(name,fn),dispatchEvent(){},...extra};
 window.ArchHubStudioAuthority={create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}};
 const fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
  const data=Object.hasOwn(replies,url)?await replies[url](body):url==='/api/universal/desktop-access'?desktopAccess():url==='/api/commands'?{commands:[]}:url==='/api/universal/canvas'?canvas:url==='/api/universal/settings-action'?
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
 assert.deepEqual(call,{url:'/api/universal/settings-action',body:{function:'ensureDependency',args:['codex'],context:{session:'',surface:'home'}}});
 assert.equal(api.getSnapshot().dependencies[0].state,'Ready');
});

// runValuation, correctAnswerSource, setResearchReview and runResearchNode have owners now (RESEARCHNODES; proven in research_actions.test.cjs).
for(const name of ["stampOutput", "runSpecialNode", "setTranscriptPass", "settleTimesheet", "changePlan"])test(name+': remains hidden without an executing owner',async()=>{
 const {api,calls}=await buttonsAdapter();const count=calls.length;assert.equal(api.supportsAction(name),false);
 const result=await api[name]();assert.equal(result.ok,false);assert.equal(result.status,'not_connected');assert.equal(calls.length,count);
});

async function hostskillsAdapter() {
 const row={id:'skill',name:'Dimensions',host:'Revit',format:'SKILL.md',enabled:false,scripts:[],network:false,audit:'Needs access review',description:'Check dimensions'};
 const bundle={id:'bundle',name:'Measure',description:'Local package',tools:[{name:'measure'}],config:[{key:'precision',label:'Precision',type:'number',value:2}],status:'Ready for review',installed:false};
 let fail=false,owner=true,cards=[];
 const methods=[];
 const file=path=>({format:'archhub',version:1,id:'doc:'+path,title:path||'Untitled',nodes:[],wires:[],groups:[],notes:[],properties:{}});
 const rig=await adapter({...signedInAccount},{
  // The open file's owner: each path opens as its own document (D-014), so a switch is a real adoptFile.
  '/api/session-files':body=>body.action==='catalogue'?{ok:true,items:[],sessions:[],directory:'/fixture'}:
   body.action==='open'?{ok:true,document:file(body.path),path:body.path}:{ok:true,document:body.document||file(''),path:body.path||'',revision:1},
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
   if(body.function==='answerApproval'){
    cards[0].status=body.args[3]==='approve'?'approved':'declined';
    if(body.args[3]==='approve'){if(cards[0].action==='installConnectorBundle'){bundle.installed=true;bundle.status='Installed';}else row.enabled=true;}
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
 assert.ok(result.id);assert.equal(call.root,'app:workshop');assert.equal(call.scope,'app:workshop');
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
 const call=rig.methods.find(r=>r.function==='answerApproval');
 assert.deepEqual(globalThis.structuredClone(call.args),['hostskills','package-review','sealed-digest','approve']);
 const before=globalThis.structuredClone(rig.api.getSnapshot().hostSkills);
 rig.refuse();await assert.rejects(()=>rig.api.auditHostSkill('skill'),/digest changed/);
 assert.deepEqual(globalThis.structuredClone(rig.api.getSnapshot().hostSkills),before);
});

test('HOSTSKILLS unavailable owner hides all six and a local file preserves upload bytes',async()=>{
 const rig=await hostskillsAdapter(),bytes=Buffer.from('{"name":"measure"}');
 await rig.api.inspectConnectorBundle({name:'fixture.json',arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)});
 const call=rig.methods.find(r=>r.function==='inspectConnectorBundle');
 assert.equal(Buffer.from(call.args[0].base64,'base64').toString(),bytes.toString());
 // Finish the initial Home notifications read before counting blocked host actions.
 await new Promise(resolve=>globalThis.setImmediate(resolve));
 rig.loseOwner();await rig.api.readHostSkills();const count=rig.methods.length;
 for(const name of ['importHostSkill','inspectConnectorBundle','configureConnectorBundle','installConnectorBundle','setHostSkillEnabled','auditHostSkill']){
  assert.equal(rig.api.supportsAction(name),false);await assert.rejects(()=>rig.api[name](),/owner unavailable/);
 }
 assert.equal(rig.methods.length,count);
});


test('HOSTSKILLS a file switch during a local package read refuses before upload',async()=>{
 const rig=await hostskillsAdapter();
 await rig.api.openSession('/fixture/first.archhub');
 assert.equal(rig.api.getSessionDocument().id,'doc:/fixture/first.archhub');
 let release;const reading=new Promise(resolve=>release=resolve);
 const pending=rig.api.inspectConnectorBundle({name:'fixture.json',arrayBuffer:()=>reading});
 await rig.api.openSession('/fixture/second.archhub');
 assert.equal(rig.api.getSessionDocument().id,'doc:/fixture/second.archhub');
 release(new ArrayBuffer(0));
 await assert.rejects(()=>pending,/graph changed/);
 assert.equal(rig.methods.filter(m=>m.function==='inspectConnectorBundle').length,0,'no inspection is submitted after the switch');
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
 const window={UI:{api,useData:()=>({}),useApp:()=>u,useAction:()=>({state:'idle',run:fn=>fn()}),A:{},Btn:'Btn'},ReactDOM:{createRoot:()=>({render(){}})},
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
 const rig=await adapter({...signedInAccount},{
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
 assert.equal(call.action,'data-api');assert.equal(call.root,'app:workshop');assert.equal(call.scope,'app:workshop');
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
 const absent=await adapter({...signedInAccount});
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
 const rig=await adapter({...signedInAccount},{
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
   if(body.function==='answerApproval'){
    if(args[3]==='approve'){writes++;held.wallY=held.pendingY;cards[0].status='approved';}
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
 assert.deepEqual(globalThis.structuredClone(call.args),args);assert.equal(call.root,'app:workshop');assert.equal(call.scope,'app:workshop');
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



// DESKTOP: owner answers first; every control uses the same scoped Workshop.
async function desktopAdapter(){
 const held={owner:'desktop-owner',program:'',stage:'Watching',instance:null,offers:[],proposal:null,taskId:null,
  schedules:[{id:'schedule-1',title:'Daily',operation:'Workflow',responsibility:'',selfReview:true,owner:'account-1'}]};
 let cards=[],failure=null,owner=true,writes=0;const methods=[];
 const rig=await adapter({...signedInAccount},{
  '/api/universal/canvas':{root:'canvas',nodes:[],wires:[],workshop_scope:{root:'canvas',workshops:[{root:'workshop',is_general:true}]}},
  '/api/universal/workshop':body=>{
   if(body.function==='listTasks')return {result:[]};
   if(body.function==='listApprovals')return {result:globalThis.structuredClone(cards)};
   if(body.function==='readDesktop')return {result:owner?globalThis.structuredClone(held):{ok:false,error:'Owner unavailable'}};
   if(!['setDesktopProgram','offerDesktopAction','prepareDesktopAction','setScheduleResponsibility','reviewScheduledWork','answerApproval'].includes(body.function))return {result:[]};
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
   if(body.function==='answerApproval'){
    const card=cards.find(c=>c.id===args[1]);assert.equal(args[0],card.approvalKind);assert.equal(args[2],card.input_digest);
    if(args[3]==='approve'){if(card.approvalKind==='desktop')writes++;card.status='approved';held.stage='Applied';}
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
  assert.equal(call.action,'data-api');assert.equal(call.root,'app:workshop');assert.equal(call.scope,'app:workshop');
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
  const {api,requests}=await adapter({...signedInAccount});const calls=()=>requests.filter(row=>row.body?.function===name).length,count=calls();
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

// setProviderModel left this table: the provider's model is the model_router owner's (settings/router.json), not a Settings action.
for(const [name,args,result,key,expected] of [
 ['disconnectSecret',['social-entry'],{ok:true,state:'removed',provider_token_revoked:false,secrets:[]},'secrets',[]],
 ['setCompanionState',[{mode:'listening',x:20,y:30,pinned:true}],{companion:{mode:'listening',x:20,y:30,pinned:true}},'companion',{mode:'listening',x:20,y:30,pinned:true}],
 ['exposeSettingsPage',['Appearance'],{id:'owner-node',page:'Appearance'},null,null],
])test('SETTINGS '+name+': executes the existing Settings owner and publishes readback',async()=>{
 const {api,calls}=await buttonsAdapter({}, {
  '/api/universal/settings-action':body=>({ok:true,result:body.function==='readControls'?{companion:{mode:'idle'},secrets:[],providerPreferences:{},providerModels:{}}:result}),
  '/api/universal/social-connections':()=>({items:[]})
 });
 assert.equal(api.supportsAction(name),true);assert.equal(api.supportsAction('changePlan'),false);
 calls.length=0;const answer=await api[name](...args);
 const command=calls.find(c=>c.body?.function===name);
 assert.deepEqual(command,{url:'/api/universal/settings-action',body:{function:name,args,context:{session:'',surface:'home'}}});
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
 assert.equal(command.body.root,'app:workshop');assert.equal(command.body.scope,'app:workshop');
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

// Migrated behavior contracts from the retired StudioLM tests, against the current owner.
test('STUDIOTESTS stop-all posts once and preserves state after refusal',async()=>{
 let refused=true;const {api,requests}=await adapter({...signedInAccount},{'/stop-all':()=>refused?{ok:false,error:'Stop refused'}:{ok:true,stopped:true}});
 const stopped=api.getSnapshot().app.stopped;
 await assert.rejects(api.stopEverything(),/Stop refused/);
 assert.equal(api.getSnapshot().app.stopped,stopped,'refusal cannot fabricate a new stopped state');
 assert.equal(requests.filter(r=>r.url==='/stop-all').length,1);
 refused=false;await api.stopEverything();assert.equal(api.getSnapshot().app.stopped,true);
 assert.equal(requests.filter(r=>r.url==='/stop-all').length,2,'one mutation per explicit call');
});

test('STUDIOTESTS host availability returns only the server catalogue and retains empty and refused reads',async()=>{
 let response={hosts:[{id:'host-a',name:'Revit'}]};
 const {api,requests}=await adapter({...signedInAccount},{'/api/universal/hosts':()=>response});
 assert.deepEqual(JSON.parse(JSON.stringify(await api.readHostAvailability())),response);
 response={hosts:[]};assert.deepEqual(JSON.parse(JSON.stringify(await api.readHostAvailability())),response);
 response={ok:false,error:'Host catalogue unavailable'};await assert.rejects(api.readHostAvailability(),/Host catalogue unavailable/);
 assert.equal(requests.filter(r=>r.url==='/api/universal/hosts').length,3);
});

// Clean ApplicationServer projects declared group ports; member ports belong to the entered scope.
// clean_visual_projection.py::project_clean_visual_canvas, application_server.py::_clean_connect.
test('CARDPOLISH Properties opens the existing full-value Node dialog',async()=>{
 const {api}=await adapter({...signedInAccount});const state=api.getSnapshot();
 state.graph.nodes=[{id:'node-1',title:'Actual node',inputs:[],outputs:[],params:{payload:{full:'retained structured value'}}}];
 const screen=await restScreen('ContextMenu',api,state,{kind:'Node menu',nodeId:'node-1',close(){}});
 try{
  [...screen.win.document.querySelectorAll('button')].find(b=>b.textContent==='Properties').click();await screen.settle();
  // Properties is the command owner's menu.properties: it selects the node, whose full values open in the Inspector.
  assert.deepEqual(JSON.parse(JSON.stringify(screen.navigation)),[{select:'node-1'}]);
 }finally{screen.close();}
 const detail=await restScreen('NodeDetails',{...api,getNodeParameters:()=>[{key:'payload',label:'Payload',type:'object'}]},state,{id:'node-1'});
 try{assert.match(detail.win.document.body.textContent,/retained structured value/);assert.doesNotMatch(detail.win.document.body.textContent,/\[object Object\]/);}
 finally{detail.close();}
});

async function fileAdapter(open={}){
 const requests=[],items=[
  {id:'text-src',title:'Text source',engine:'data.constant',pure:true,params:{value:'a'},ports:{source:[{id:'out',type:'text'}],target:[]}},
  {id:'text-in',title:'Text input',engine:'data.constant',pure:true,params:{},ports:{source:[],target:[{id:'in',type:'text'}]}},
  {id:'number-in',title:'Number input',engine:'data.constant',pure:true,params:{},ports:{source:[],target:[{id:'in',type:'number'}]}}];
 const blank=title=>({format:'archhub',version:1,id:'doc-'+title,title,nodes:[],wires:[],groups:[],notes:[],properties:{}});
 const window={ARCHHUB_AUTHORITY:{},structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{home_load_ms:60000,token:'local-lease',csrf:'csrf'},
  Uint8Array:globalThis.Uint8Array,dispatchEvent(){},addEventListener(){},AH:{},crypto:require('node:crypto'),
  setInterval:()=>0,clearInterval(){},requestAnimationFrame:fn=>setTimeout(fn,0),cancelAnimationFrame:clearTimeout};
 window.ArchHubStudioAuthority={create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}};
 const answer=body=>{
  if(body.action==='catalogue')return {ok:true,items,sessions:[],recent:[],directory:'/fixture'};
  if(body.action==='initial')return {ok:true,document:blank('Untitled'),path:''};
  if(body.action==='open')return {ok:true,document:open.document||blank('Opened'),path:body.path||'/fixture/opened.archhub'};
  if(body.action==='solve')return {ok:true,results:{},solved:body.changed||[],stale:[],ms:1};
  if(body.action==='run')return open.run ? open.run(body) : {ok:true,results:{},revision:2};
  if(body.action==='wire-rule')return {ok:true,rule:body.rule};
  return {ok:true,document:body.document,path:body.path||'',revision:1};
 };
 const context={window,setTimeout,clearTimeout,document:{hidden:true,addEventListener(){}},CustomEvent:class{constructor(type,init){this.type=type;this.detail=init?.detail;}},
  sessionStorage:{getItem(){return null;},setItem(){}},URLSearchParams,TextEncoder:globalThis.TextEncoder,AbortSignal:globalThis.AbortSignal,console,
  fetch:async(url,options={})=>{
   const body=options.body?JSON.parse(options.body):{};requests.push({url,body});
   const data=url==='/api/universal/desktop-access'?desktopAccess():url==='/api/commands'?{commands:[]}:url==='/api/session-files'?answer(body):url==='/api/universal/canvas-op'?{ok:true,result:[]}:{ok:true,result:{}};
   return {ok:true,status:200,json:async()=>data};
  }};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/api.js'),'utf8'),context);
 await window.ArchHubAPI.ready;await window.ArchHubAPI.loadLibrary();
 return {api:window.ArchHubAPI,requests,files:requests.filter(r=>r.url==='/api/session-files')};
}

test('file-backed create, open and run use the session-files owner',async()=>{
 const {api,requests}=await fileAdapter();
 await api.newSession('Fixture flow');
 assert.equal(api.getSessionDocument().title,'Fixture flow');
 await api.openSession('/fixture/site.archhub');
 const opened=requests.find(r=>r.url==='/api/session-files'&&r.body.action==='open');
 assert.equal(opened.body.path,'/fixture/site.archhub');
 assert.equal(api.getSessionDocument().id,'doc-Opened');
 await api.runNode();
 const run=requests.find(r=>r.url==='/api/session-files'&&r.body.action==='run');
 assert.equal(run.body.document.id,'doc-Opened');
 assert.equal(run.body.path,'/fixture/site.archhub');
});

test('parameter writes land in the open file and rapid edits coalesce into one solve of that node',async()=>{
 const node={id:'n',type:'data.constant',item:'text-src',title:'Text source',pure:true,params:{value:'initial'},position:{x:0,y:0}};
 const {api,requests}=await fileAdapter({document:{format:'archhub',version:1,id:'doc-p',title:'Params',nodes:[node],wires:[],groups:[],notes:[],properties:{}}});
 await api.openSession('/fixture/params.archhub');
 const before=requests.filter(r=>r.body?.action==='solve').length;
 await api.setNodeParam('n','value','first');await api.setNodeParam('n','value','middle');await api.setNodeParam('n','value','final');
 await new Promise(resolve=>setTimeout(resolve,400));
 assert.equal(api.getSessionDocument().nodes[0].params.value,'final');
 const solves=requests.filter(r=>r.body?.action==='solve').slice(before);
 assert.equal(solves.length,1,'rapid edits coalesce into one solve');
 assert.deepEqual(solves[0].body.changed,['n']);
 assert.equal(solves[0].body.document.nodes[0].params.value,'final');
});

test('typed wiring on the open file refuses a mismatch with Insert Convert and connects matching types',async()=>{
 const {api}=await fileAdapter();
 const source=await api.addNode('text-src',{x:0,y:0}),number=await api.addNode('number-in',{x:300,y:0}),text=await api.addNode('text-in',{x:300,y:200});
 await assert.rejects(api.connectSockets({from:source.id,fromPort:'out',to:number.id,toPort:'in'}),/Wrong type.*Insert Convert/);
 assert.equal(api.getSessionDocument().wires.length,0);
 await api.connectSockets({from:source.id,fromPort:'out',to:text.id,toPort:'in'});
 assert.deepEqual(api.getSessionDocument().wires.map(w=>[w.from.node,w.from.socket,w.to.node,w.to.socket]),[[source.id,'out',text.id,'in']]);
});

test('scoped Run retains another completed node while running and after the scoped response',async()=>{
 const previous={status:'Done',output:{value:'previous'}};
 const doc={format:'archhub',version:1,id:'scoped',title:'Scoped',properties:{revision:1},
  nodes:['target','other'].map(id=>({id,type:'data.constant',position:{x:0,y:0},params:{value:id},result:previous})),
  wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom:1}};
 let signal,release;
 const started=new Promise(resolve=>{signal=resolve;});
 const pending=new Promise(resolve=>{release=resolve;});
 const {api}=await fileAdapter({document:doc,run:async body=>{
  assert.deepEqual(body.roots,['target']);signal();await pending;
  return {ok:true,succeeded:true,results:{target:{status:'Done',output:{value:'new'}}}};
 }});
 await api.openSession('/fixture/scoped.archhub');
 const other=()=>api.getSnapshot().graph.nodes.find(n=>n.id==='other');
 const running=api.runNode('target');
 try{
  await Promise.race([started,running]);assert.equal(other().status,'Done');assert.equal(other().output.value,'previous');
 }finally{release();await running;}
 assert.equal(other().status,'Done');assert.equal(other().output.value,'previous');
});
