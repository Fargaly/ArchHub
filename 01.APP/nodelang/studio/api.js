// The approved design's only domain boundary. Real owners; no demonstration data.
(() => {
'use strict';
  const NAVIGATION_ROUTES = {};
window.ArchHubRouteNames = NAVIGATION_ROUTES;
let state = {"keyboardPending": true, "revision": 0, "sessionApprovals": [], "activeWorkspace": "", "activeFile": "", "profile": {"id": "", "isFounder": false, "name": "", "firm": "", "email": "", "signedIn": false, "plan": ""}, "nodeSchemas": {}, "providers": [], "catalogue": [], "libraryPorts": [], "templates": [], "pages": ["Account", "Connections", "BABOOM", "Agents", "Brain", "System graph", "Workshop", "Library & Mods", "Automations", "Hooks", "Dependencies", "Privacy", "Appearance", "Updates & About", "Advanced"], "settings": [], "companion": {"mode": "idle", "x": null, "y": null, "pinned": false}, "workspaces": [], "tasks": [], "approvals": [], "graph": {"id": "", "name": "", "nodes": [], "wires": [], "workspaceIds": [], "documentation": "", "customProperties": [], "courtStatus": ""}, "brain": [], "dependencies": [], "connections": [], "files": [], "secrets": [], "people": [], "archives": [], "schedules": [], "mods": [], "receipts": [], "runs": [], "drafts": [], "feedback": [], "notifications": [], "meeting": {"title": "", "actions": [], "calendarId": "", "platform": "", "agent": "", "status": "", "consent": false, "transcript": [], "actionOwners": {}, "actionTasks": {}}, "watcher": {"geometry": {"outline": [], "walls": [], "doors": [], "tags": []}, "host": "", "view": "", "views": [], "rooms": [], "imageEdits": [], "wallY": 0, "pendingY": 0, "marks": [], "comments": [], "mask": null, "applied": false, "lengthMm": 0, "appliedLengthMm": 0, "thicknessMm": 0, "appliedThicknessMm": 0, "snap": false, "gridMm": 0, "orthogonal": false, "showDimensions": false, "dimensionAlignment": "", "dimensions": []}, "update": {"available": false, "installed": "", "next": ""}, "app": {"hidden": false, "quit": false, "stopped": false}, "backups": [], "sync": "", "lastResult": null, "docs": [], "bookGlossary": [], "social": {"office": {"name": "", "headline": "", "bio": "", "website": "", "audience": ""}, "inbox": [], "drafts": [], "groups": [], "digest": {"enabled": false, "time": "", "summary": ""}, "research": [], "tutorials": [], "triaged": false}, "learning": {"concept": "", "hosts": [], "baseline": "", "residual": "", "why": "", "sources": [], "findings": [], "status": "", "destination": "", "layer": "", "layers": {"Host": {"program": "", "operation": "", "preserveRelationships": false}, "Habit": {"pattern": "", "minimumRepeats": 0, "learn": false}, "Intent": {"baseline": "", "deviation": "", "why": ""}, "Self": {"metric": "", "threshold": null, "rebaseline": false}, "Agent": {"provider": "", "checkResults": false, "maxIterations": 0}, "Session": {"graph": "", "shareContext": false, "retainCheckpoints": false}}}, "modelSources": [], "devices": [], "activeDevice": "", "graphs": [], "capabilities": [], "mcpServers": [], "suggestions": [], "community": {"tab": "", "peers": [], "patterns": [], "shared": [], "points": [], "groups": [], "joinStatus": "", "marketQuery": "", "listing": {"title": "", "price": 0, "creatorShare": 0}, "charge": {"client": "", "project": "", "basis": "", "amount": 0}, "charges": [], "marketplace": []}, "modelReview": {"operation": "", "results": [], "issues": []}, "usage": {"tokens": 0, "cost": 0, "runs": 0, "quota": 0, "seats": 0, "grace": false}, "hostSkills": [], "provenance": [], "presentation": {"slides": [], "walkthrough": 0}, "healthHistory": [], "prototype": {"name": "", "threshold": null, "samples": 0, "baseline": 0, "status": "", "linkedModel": false, "pattern": null}, "composerAttachments": [], "settingsScope": "User", "officeItems": [], "timesheet": {"status": "", "rows": []}, "desktop": {"program": "", "stage": "", "taskId": null}, "meetingCalendar": [], "refine": {"breadth": 0, "depth": 0, "trials": 0, "tokens": 0, "results": [], "accepted": null}, "intakeRules": [], "uncertainLinks": [], "onboarding": {"role": "", "assessment": ""}, "firms": [], "activeFirm": "", "officeInvitations": [], "billing": {"status": "", "requestedPlan": "", "cycle": "", "checkout": null, "limitReached": null, "invoices": []}};
Object.assign(state,{agents:[],agentSummary:'Checking running agents…',agentHealth:'Checking running agents…'});
// The dock layout comes with the page (boot payload), so the first frame already shows his layout.
if(window.ARCHHUB_BOOT?.dock_layout)state.dockLayout=window.ARCHHUB_BOOT.dock_layout;
const emptyWatcher=window.structuredClone(state.watcher);
const exportedNames = ["moveNodes", "runValuation", "selectFirm", "acceptOfficeInvitation", "declineOfficeInvitation", "getUsageSummary", "setBilling", "prepareCheckout", "completeCheckout", "retryPayment", "downgradeBilling", "refreshBilling", "createCommunityGroup", "issueCommunityInvite", "revokeCommunityInvite", "verifyCommunityInvite", "joinCommunityGroup", "setMarketplace", "installMarketplaceItem", "proposeMarketplaceListing", "setProjectCharge", "proposeProjectCharge", "resolveTaskReview", "setApprovalRubric", "verifyOutputStamp", "setNodeRunPolicy", "contextLabel", "setGraphThumbnail", "setIntakeRule", "reviewBrainLink", "setOnboarding", "correctAnswerSource", "setResearchReview", "stampOutput", "runSpecialNode", "setTranscriptPass", "getDecisionState", "setDecisionState", "setRefine", "compareRefine", "setAnswerWidget", "startVoiceInput", "stopVoiceInput", "speak", "addCompatibleNode", "setPromotedParameter", "setPortVisibility", "compatibleNodes", "setDesktopProgram", "offerDesktopAction", "prepareDesktopAction", "setMeeting", "joinMeeting", "startMeetingTranscript", "stopMeetingTranscript", "readMeetingTranscript", "setMeetingActionOwner", "createMeetingTask", "proposeMeetingSummary", "setTaskPlanMode", "addTaskReview", "refreshOfficeAwareness", "settleTimesheet", "setSettingsScope", "openTemplateGraph", "addTemplateNode", "addComposerAttachment", "removeComposerAttachment", "manageDependency", "getCapabilityParameters", "setCapabilityParameter", "setCapabilityEnabled", "setLearningLayer", "postponeApproval", "resumeApproval", "contestDecision", "setScheduleResponsibility", "reviewScheduledWork", "getHealthHistory", "runResearchNode", "editSlide", "addSlide", "removeSlide", "reorderSlide", "setPrototype", "rebaselinePrototype", "checkVerdictPattern", "steerTask", "refreshModelRoster", "setMultipleNodeParameters", "runToHere", "setPinnedOutput", "setWireVisibility", "setSourceEvidence", "importHostSkill", "inspectConnectorBundle", "configureConnectorBundle", "installConnectorBundle", "setHostSkillEnabled", "auditHostSkill", "setAgentProfile", "setNodeFlags", "checkpointTask", "restoreTaskCheckpoint", "queueTaskMessage", "settleQueuedMessage", "setTaskDelegate", "getNodeOutput", "reviewModel", "updateReviewIssue", "subscribeCommunity", "reviewCommunityPattern", "proposeCommunityShare", "addInterfaceElement", "updateGraph", "removeGraph", "saveGraphVersion", "restoreGraphVersion", "setAccountSeats", "transferOwnership", "checkWatcherSource", "readYoutubeData", "refreshApproval", "setGraphWorkspaces", "discoverMcpTools", "reconnectMcp", "importMcpTool", "inspectMod", "retryMod", "installMod", "removeMod", "shareMod", "dismissSuggestion", "proposeMemory", "checkFeedback", "readResearchSource", "checkResearchLicense", "saveResearchDecision", "importRecipe", "exportRecipe", "getSocial", "saveSocialDraft", "proposeSocialDraft", "discardSocialDraft", "replySocialMessage", "readSocialMessage", "triageSocialInbox", "setSocialGroupRule", "updateOfficePage", "setSocialDigest", "generateSocialDigest", "readContentSource", "prepareTutorial", "setLearning", "runLearning", "distilLearning", "addGraph", "selectGraph", "openTaskGraph", "setAccountPlan", "setTeamAccess", "selectDevice", "setWorkspaceRules", "setModelSource", "checkModelRouting", "setWatcherDimension", "setWatcherOptions", "addDimension", "removeDimension", "getNodeParameters", "addNodeParameter", "setCompanionState", "getDocs", "getKnowledgeGraph", "getSnapshot", "subscribe", "ensureDependency", "checkDependencies", "reviewProofRow", "exposeSettingsPage", "selectWorkspace", "selectFile", "setWatcherView", "listWorkspaces", "addWorkspace", "removeWorkspace", "listProviders", "setProviderEnabled", "signInProvider", "setProviderModel", "listAgentsWorking", "getSettings", "setSetting", "resetSetting", "resetPage", "sendToBaboom", "listTasks", "listWorkshopMessages", "setTaskStatus", "approve", "decline", "stopEverything", "reassignTask", "startTemplate", "getGraph", "addNode", "moveNode", "setNodeParam", "resetNodeParam", "renameNode", "deleteNode", "forkNode", "arrangeGraph", "groupNodes", "ungroupNode", "connectSockets", "insertConvert", "setWireRule", "deleteWire", "runNode", "undo", "redo", "addSchedule", "setScheduleEnabled", "setScheduleTime", "removeSchedule", "editMemory", "forgetMemory", "remember", "setConnection", "checkConnection", "editWall", "addMark", "addComment", "proposeWatcherEdit", "discardWatcherChanges", "setWatcherHost", "updateProfile", "signIn", "syncAccount", "addFile", "removeFile", "disconnectSecret", "setModEnabled", "saveSkill", "sendFeedback", "changePlan", "invitePerson", "grantAccess", "installUpdate", "windowAction", "backUpNow", "rollBack", "archiveActivity", "readNotification", "exportData", "traceNode", "refreshMcpServers", "addMcpServer", "removeMcpServer", "setMcpServerEnabled", "signInMcpServer"];

const listeners=new Set();
let filePollTimer=null;  // the open-file poll; runs only while a screen is subscribed
let canvas=null, session=null, commands=null, renewing=null, scopeEpoch=0, accountEpoch=0;
let graphNavigation=Promise.resolve(), requestedGraph=null;
let refreshTimer=null, refreshInFlight=false, taskRefreshInFlight=null, ready=false, accountSignInPending=false;
const nativeReview=Boolean(window.ARCHHUB_NATIVE_APPROVAL);
let desktopAccess={admitted:false,state:'pending',subject:null,email:null,ready:false},desktopSubject=null,desktopCheck=null,desktopGeneration=0,lockedSnapshot=null;
const suspendedDesktop=new Map(),desktopWaiters=new Set();
const desktopRoutes=new Set(['/api/universal/desktop-access','/api/universal/cloud-signin','/api/universal/cloud-signout','/api/window-command','/api/universal/window-command']);
const desktopAdmitted=()=>nativeReview||desktopAccess.admitted===true;
function desktopError(){const error=Error('Sign in to archhub.io and reconnect before continuing.');error.response={code:'desktop_access_required',state:desktopAccess.state};return error;}
function requireDesktop(){if(!desktopAdmitted())throw desktopError();}
function desktopSnapshot(){return desktopAdmitted()?state:lockedSnapshot||(lockedSnapshot={...copy(initialState),desktopAccess});}
function showDesktopAccess(values){desktopAccess={...desktopAccess,...values};lockedSnapshot={...copy(initialState),desktopAccess};publish({desktopAccess});}
function lockDesktop(stateName='unavailable'){
 if(nativeReview)return;
 if(desktopAccess.admitted){accountEpoch++;scopeEpoch++;runEpoch++;composerGeneration++;clearTimeout(autosaveTimer);clearTimeout(solveTimer);window.cancelAnimationFrame(projectAfterPaint);keepDraftForRecovery(currentEditState().unsaved,sessionPath);}
 showDesktopAccess({admitted:false,state:stateName,subject:null,email:null,ready:false});
}
const waitForDesktop=()=>desktopAdmitted()?Promise.resolve():new Promise(resolve=>desktopWaiters.add(resolve));
async function changeDesktopSubject(subject){
 if(!desktopSubject||desktopSubject===subject){desktopSubject=subject;return;}
 keepDraftForRecovery(currentEditState().unsaved,sessionPath);
 suspendedDesktop.set(desktopSubject,{document:sessionDocument,path:sessionPath,revision:sessionRevision,history:fileHistory,future:fileFuture,dirty:localDirty,conflict:saveConflict,failed:saveFailed,breadcrumbs:sessionBreadcrumbs,view:state.desktopView});
 clearCanvas();fileNavigation++;runEpoch++;sessionDocument=null;sessionPath='';sessionRevision=0;fileHistory=[];fileFuture=[];localDirty=false;saveConflict=null;saveFailed=false;sessionBreadcrumbs=[];systemProjection=null;preferenceContext='';reportedEditState=null;reportedEditFile=null;
 desktopSubject=subject;localRecoveryRequested=false;
 const held=suspendedDesktop.get(subject);
 if(held){sessionDocument=held.document;sessionPath=held.path;sessionRevision=held.revision;fileHistory=held.history;fileFuture=held.future;localDirty=held.dirty;saveConflict=held.conflict;saveFailed=held.failed;sessionBreadcrumbs=held.breadcrumbs;publish({desktopView:held.view});suspendedDesktop.delete(subject);}
}
async function refreshDesktopAccess(force=false){
 if(nativeReview)return desktopAccess;
 if(desktopCheck&&!force)return desktopCheck;
 const generation=++desktopGeneration;
 const work=(async()=>{
  try{
   if(accountSignInPending){
    const phase=await request('/api/universal/cloud-signin');
    if(generation!==desktopGeneration)return desktopAccess;
    accountSignInPending=!['done','failed','idle'].includes(phase.phase);
    let notice='';
    if(phase.phase==='failed')notice=phase.error_code==='browser_open_failed'
     ?'Could not open the browser. Check your default browser and choose Retry.'
     :'Sign-in failed. Choose Retry to sign in again.';
    showDesktopAccess({signingIn:accountSignInPending,notice});
   }
   const answer=await request('/api/universal/desktop-access');if(generation!==desktopGeneration)return desktopAccess;
   if(answer.admitted!==true||answer.state!=='admitted'||typeof answer.subject!=='string'||!answer.subject){lockDesktop(['signed_out','session_invalid'].includes(answer.state)?answer.state:'unavailable');return desktopAccess;}
   const switching=Boolean(desktopSubject&&desktopSubject!==answer.subject);
   if(switching)lockDesktop('switching');
   await changeDesktopSubject(answer.subject);if(generation!==desktopGeneration)return desktopAccess;
   // The admitted subject is the account every in-flight owner read is guarded by; set it now, not when account discovery returns.
   if(state.profile.id!==answer.subject)publish({profile:{...state.profile,id:answer.subject}});
   showDesktopAccess({admitted:true,state:'admitted',notice:'',subject:answer.subject,email:answer.email||null,ready:ready&&!switching});
   if(switching&&ready){if(sessionDocument)projectFile();else await api.newSession();showDesktopAccess({ready:true});void refreshAccount().catch(()=>{});void api.listWorkspaces().catch(()=>{});}
   for(const resolve of desktopWaiters)resolve();desktopWaiters.clear();return desktopAccess;
  }catch(error){
   // Keep the last verified identity on transport failure. The server checks every protected request.
   if(generation===desktopGeneration&&desktopAccess.state==='pending')lockDesktop('unavailable');
   return desktopAccess;
  }
 })();desktopCheck=work;try{return await work;}finally{if(desktopCheck===work)desktopCheck=null;}
}
window.addEventListener('offline',()=>{void refreshDesktopAccess(true);});
window.addEventListener('online',()=>{void refreshDesktopAccess(true);});
let activeSurface='home', canvasRefresh=null;
let providerRoster=[], workingAgents=[], agentsChecked=false;
let controlsGeneration=0, preferenceGeneration=0, notificationGeneration=0;
let appearanceWrites=Promise.resolve();
// Settings rows with writes still queued: id -> {value, count}. The row shows the last value asked for until every write
// for it has answered, so a second quick click starts from the first click's value, not from the value before it.
const pendingSettings=new Map();
const withPending=rows=>pendingSettings.size?rows.map(row=>pendingSettings.has(row.id)?{...row,value:pendingSettings.get(row.id).value}:row):rows;
let composerGeneration=0;
let updateGeneration=0, updateActionPending=false;
let updateReadsPending=0, updateReadFailures=0, updateReadAfter=0;
// Same bounded five-second cadence as the existing studio Tool Hub, paused while hidden.
const ownerRefreshMs=5000;
const defaults=new Map(), parameterWrites=new Map();
let insertionPoint={scope:null,x:240};
const insertionReservations=new Set();
const copy=value=>window.structuredClone(value);
// A refresh whose answer equals what is shown neither replaces state nor re-renders. graph and the streamed answer change every time.
const sameValue=(key,a,b)=>Object.is(a,b)||key!=='graph'&&key!=='composerAnswer'&&a!==null&&b!==null&&typeof a==='object'&&typeof b==='object'&&JSON.stringify(a)===JSON.stringify(b);
function publish(values={}) {
 const keys=Object.keys(values), changed=keys.filter(key=>!sameValue(key,state[key],values[key]));
 if(keys.length&&!changed.length)return;
 // Unchanged keys keep their old reference, so screens that read only them stay as they are.
 state={...state,...Object.fromEntries(changed.map(key=>[key,values[key]])),revision:state.revision+1};listeners.forEach(fn=>fn());
}
// Poll reads answered 304 (unchanged) reuse the last parsed answer: no body, no parse.
const POLLED=new Set(['listTasks','listWorkshopMessages','listLiveAgents','listApprovals','listNotifications','readWatcher','readDesktop','readHostSkills','readControls']);
const conditional=new Map();
function notice(message) { window.dispatchEvent(new CustomEvent('archhub:notice',{detail:{message}})); }
function unavailable(operation,reason='') {
 const result={ok:false,status:'not_connected',operation,message:reason||'This action is not available in this release.'};
 notice(result.message);return result;
}
const normalise=data=>data && (data.canvas_root||data.root) && Array.isArray(data.nodes)
 ? {...data,root:data.scope?.current||data.root||data.canvas_root,graph_id:data.graph_id||data.application_root,
    nodes:data.nodes.map(n=>({...n,properties:Array.isArray(n.params)?n.params:n.properties||[]}))} : data;
async function signIn() {
 const descriptor=window.ARCHHUB_AUTHORITY;
 const response=await fetch('/api/universal/session',{method:'POST',headers:{'Content-Type':'application/json','X-ArchHub-Sign-In':'1',
 ...(descriptor?.canvas_key?{'X-ArchHub-Canvas-Key':descriptor.canvas_key}:{})},body:'{}'});
 const data=await response.json();if(!response.ok||!data.token||!data.csrf)throw Error(data.error||'Reopen ArchHub from its launcher.');
 session={...session,token:data.token,csrf:data.csrf};window.__archhubSession=session;
 try {sessionStorage.setItem('archhub.studio.session',JSON.stringify(session));} catch { notice('Browser session storage is unavailable. This window remains signed in.'); }
}
const projectTemplateWindow=window.crypto.randomUUID();
async function request(path,body=undefined,readRetry=true,signal=undefined) {
 if(!desktopRoutes.has(path))requireDesktop();
 const requestEpoch=scopeEpoch, requestAccountEpoch=accountEpoch, requestCanvas=commands?.getSnapshot()?.canvas||canvas;
 if(path==='/api/universal/focus'&&!window.ARCHHUB_AUTHORITY){path='/api/universal/gesture';body={expected_scope:body.expected_scope,roots:body.selected_roots,focus:body.primary_root};}
 let acknowledgementMode='';
 if(path==='/api/universal/interaction'&&body&&!window.ARCHHUB_AUTHORITY){
  const keys=['interaction','control','event','revision'];
  if(Array.isArray(body.event_facts)&&body.event_facts.length)keys.push('event_facts');
  // Scope entry must carry the acknowledgement mode named by its current lease.
  const held=(requestCanvas?.interaction_projection?.bindings||[]).filter(b=>b.control===body.control);
  if(held.length===1&&typeof body.projection_mode==='string'&&[held[0].projection_mode,held[0].acknowledgement_mode].includes(body.projection_mode)){
   keys.push('projection_mode');
   if(body.projection_mode===held[0].acknowledgement_mode)acknowledgementMode=held[0].acknowledgement_mode;
  }
  if(body.control==='app:control:canvas:remove-member')keys.push('membership','expected_scope','command_id');
  body=Object.fromEntries(keys.filter(k=>Object.hasOwn(body,k)).map(k=>[k,body[k]]));
 }
 const polled=body===undefined||POLLED.has(body.function)&&(path==='/api/universal/workshop'?body.action==='data-api':path==='/api/universal/settings-action');
 const readKey=polled?path+JSON.stringify({...body,request_id:undefined}):null, cached=readKey&&conditional.get(readKey);
 let response;try{response=await fetch(path,{method:body===undefined?'GET':'POST',cache:'no-store',signal,headers:{'Content-Type':'application/json',
 'X-ArchHub-Session':session?.token||'','X-ArchHub-CSRF':session?.csrf||'','X-ArchHub-Desktop-Subject':desktopSubject||'','X-ArchHub-Canvas-Key':window.ARCHHUB_AUTHORITY?.canvas_key||'','X-ArchHub-Renderer':'studio',...(cached?{'If-None-Match':cached.etag}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});}catch(cause){
  const reason=signal?.aborted&&signal.reason?.message;
  throw Error(reason ? reason+' — retry when ready.' : 'ArchHub did not respond. Check the result before retrying.',{cause});
 }
 if(response.status===304){
  if(!cached||requestAccountEpoch!==accountEpoch)throw Error('The account changed while this request was in flight.');
  return cached.result;
 }
 const data=await response.json();
 if(requestAccountEpoch!==accountEpoch)throw Error('The account changed while this request was in flight.');
 if(data?.code==='desktop_access_required'){lockDesktop(data.state||'unavailable');const failure=Error(data.error||'Sign in to continue.');failure.status=response.status;failure.response=data;throw failure;}
 if(response.status===403&&/browser session|session lease|credential digest|browser-session/i.test(data.error||'')) {
  if(readRetry){renewing=renewing||signIn().finally(()=>{renewing=null;});await renewing;
   // A refused write is never replayed. Only the next deliberate action uses the renewed session.
   if(body===undefined)return request(path,undefined,false,signal);}
 }
 if(!response.ok||data.ok===false){const error=Error(data.error||data.reason||'The backend refused this action.');error.status=response.status;error.response=data;throw error;}
 if(acknowledgementMode&&body.control!=='app:control:canvas:remove-member'&&!Array.isArray(data.nodes)){
  if(data.projection_mode!==acknowledgementMode||!Number.isInteger(data.committed_revision))throw Error('The canvas acknowledgement needs reconciliation. Refresh and retry.');
  const latest=await request('/api/universal/canvas');
  if(!Number.isInteger(latest.revision)||latest.revision<data.committed_revision)throw Error('The change is not visible in the refreshed canvas.');
  return latest;
 }
 const isDelta=['interaction-delta-v1','topology-delta-v1'].includes(data.projection_mode);
 if(requestEpoch!==scopeEpoch&&isDelta)throw Error('The graph changed while this request was in flight.');
 const result=normalise(isDelta?window.ArchHubStudioAuthority.mergeProjectionDelta(data,requestCanvas):data);
 if((result?.root&&Array.isArray(result.nodes))||result?.canvas){
  if(requestEpoch!==scopeEpoch)throw Error('The graph changed while this request was in flight.');
 }
 const etag=readKey&&response.headers&&response.headers.get('ETag');
 if(etag)conditional.set(readKey,{etag,result});
 return result;
}
function rows(node){return node?.properties||node?.params||[];}
// Every end of a turn that did not answer (refused, error, ended) clears its live status line under the composer.
async function routerChat(prompt,agent,replyTo,task,extra) {
 const generation=composerGeneration+1;
 try{return await streamChat(prompt,agent,replyTo,task,extra);}
 catch(error){if(generation===composerGeneration)publish({composerAnswer:null});throw error;}
}
// extra: {continue:true} for the thread's running chat, {fresh:true} for a session made for this start, or nothing
async function streamChat(prompt,agent,replyTo,task,extra) {
 requireDesktop();const streamAccount=accountEpoch;
 const generation=++composerGeneration;let answer='',who='Routing',steps=[];
 publish({composerAnswer:{answer:'',provider:'Routing',model:'Free model'}});
 let response;try{response=await fetch('/api/router/chat',{method:'POST',headers:{'Content-Type':'application/json',
  'X-ArchHub-Session':session?.token||'','X-ArchHub-CSRF':session?.csrf||'','X-ArchHub-Desktop-Subject':desktopSubject||'',
  'X-ArchHub-Canvas-Key':window.ARCHHUB_AUTHORITY?.canvas_key||''},body:JSON.stringify({prompt,agent,...(extra||{}),...(replyTo?{reply_to:replyTo}:{}),...(task?{task}:{})})});}catch(cause){throw Error('ArchHub did not respond. Check the result before retrying.',{cause});}
 if(streamAccount!==accountEpoch)throw Error('The account changed while this request was in flight.');
 if(!response.ok){const result=await response.json();if(result.code==='desktop_access_required')lockDesktop(result.state||'unavailable');throw Error(result.error||'The model request was refused.');}
 if(streamAccount!==accountEpoch||!desktopAdmitted()){await response.body.cancel();throw desktopError();}
 const reader=response.body.getReader(),decoder=new TextDecoder();let pending='',result;
 try{for(;;){const {done,value}=await reader.read();if(streamAccount!==accountEpoch||!desktopAdmitted()){await reader.cancel();throw desktopError();}pending+=decoder.decode(value||new window.Uint8Array(),{stream:!done});
  let split;while((split=pending.indexOf('\n\n'))>=0){const block=pending.slice(0,split);pending=pending.slice(split+2);
   for(const line of block.split('\n'))if(line.startsWith('data:')){const data=JSON.parse(line.slice(5));
    if(data.code==='desktop_access_required')lockDesktop(data.state||'unavailable');if(data.error)throw Error(data.error);
    if(data.step){if(data.step.who)who=data.step.who;else steps=[...steps.filter(s=>s.id!==data.step.id),data.step];if(generation===composerGeneration)publish({composerAnswer:{provider:who,model:who==='Routing'?'Free model':'ACP',answer,steps}});}
    if(data.delta){answer+=data.delta;if(generation===composerGeneration)publish({composerAnswer:{provider:who,model:who==='Routing'?'Free model':'ACP',answer,steps}});}
    if(data.result){result=data.result;if(generation===composerGeneration)publish({composerAnswer:result});}
   }}if(done)break;}
 }finally{reader.releaseLock();}
 if(!result)throw Error('The model reply did not complete.');
 return result;
}
function nodeDto(n) {
 const params=Object.fromEntries(rows(n).map(p=>[p.label,p.value]));
 const research=JSON.parse(params.research_run||'{}');
 const schema=rows(n).map(p=>({key:p.label,label:p.display_label||p.label,type:p.editor||'text',group:'Parameters',unit:p.unit||'',min:p.constraints?.minimum??p.constraints?.min,max:p.constraints?.maximum??p.constraints?.max,step:p.constraints?.step,options:p.constraints?.options||[],editable:p.editable===true,relation:p.relation,owner:p.owner||n.id}));
 const assembly=typeof n.assembly==='object' && n.assembly ? n.assembly : {name:n.assembly},
  definition=(canvas.catalog||[]).find(c=>c.id===(n.definition||assembly.definition)||c.name===assembly.name||c.name===n.kind),
  library=(state.libraryPorts||[]).filter(item=>item.engine===(params.engine||n.engine)),
  item=library.find(item=>item.title===(n.label||n.title))||(library.length===1 ? library[0] : null);
 const ports=(n.ports||[]).map(p=>{
  const name=p.name||p.label||p.id, parameter=rows(n).find(row=>row.label===name),
   declared=definition?.interface_contract?.[name]||{}, metadata=definition?.parameters?.[name]||{},
   logical=item?.ports?.[p.side]?.find(port=>port.id===name);
  return {...p,name,connect_choices:p.connect_choices?.map(c=>({id:c.owner||c.id,interface:c.interface||c.id})),type:p.value_type||p.logical_type||declared.type||(logical?.type==='unknown' ? undefined : logical?.type)||parameter?.type||metadata.type||'any',
   list:p.list??p.multiple??declared.multiple??((p.cardinality||logical?.cardinality)==='many'),unit:p.unit||parameter?.unit||metadata.unit||''};
 });
 return {id:n.id,title:n.label||n.title||n.id,kind:params.element?'UI element':n.kind||n.engine||assembly.name||'Node',x:n.x||0,y:n.y||0,status:n.status||'',
 params,defaults:Object.fromEntries(rows(n).filter(p=>p.default!==undefined).map(p=>[p.label,p.default])),parameterSchema:schema,inputs:ports.filter((_,i)=>['target','in'].includes(n.ports[i].side)),outputs:ports.filter((_,i)=>['source','out'].includes(n.ports[i].side)),
 definition:n.definition||assembly.definition,assembly:assembly.name,category:n.category||definition?.category||item?.cat||n.kind||'Node',icon:n.icon,colorToken:n.color_token,frame:n.group||'',
 members:n.members||[],children:(n.members||[]).map(r=>r.id||r),parent:(canvas.nodes||[]).some(row=>row.id===n.group)?n.group:null,pinned:n.pinned===true||params.pinned==='true',frozen:n.frozen===true||params.frozen==='true',output:research.output??n.output??n.result??[],application:n.application===true,
 review:JSON.parse(params.research_review||'{"items":{}}'),successfulPresets:research.preset?[research.preset]:[],
 portVisibility:JSON.parse(params.port_visibility||'{}'),parameterPresentation:JSON.parse(params.parameter_presentation||'{}')};
}
function settingDto(n,p) {
 const kind=p.setting?.kind||'property';
 const page=kind==='theme'?'Appearance':kind==='baboom'?'BABOOM':kind.includes('model')||kind==='generation'?'Agents':kind.startsWith('mod')?'Library & Mods':'System graph';
 const id=(p.relation||n.id)+':'+p.label;
 if(p.default!==undefined&&!defaults.has(id))defaults.set(id,copy(p.default));
 return {id,label:p.display_label||p.label,page,group:n.label||'Parameters',type:p.editor||'text',value:p.value,default:defaults.get(id),
 options:p.constraints?.options,advanced:false,owner:n.id,key:p.label,relation:p.relation,editable:p.editable===true,setting:p.setting};
}
function project() {
 const current=commands?.getSnapshot()?.canvas;
 if(!current?.root||!Array.isArray(current.nodes))return;
 canvas=current;
 const nodes=canvas.nodes.map(nodeDto),settings=canvas.nodes.flatMap(n=>rows(n).map(p=>settingDto(n,p)));
 if(Number.isFinite(canvas.viewport?.zoom)&&!settings.some(r=>r.page==='Appearance'&&r.label==='Zoom percentage'))settings.push({id:'Appearance.Zoom percentage',label:'Zoom percentage',page:'Appearance',group:'Canvas',type:'number',value:Math.round(canvas.viewport.zoom*100),owner:canvas.root,key:'zoom',editable:true});
 const catalogue=(canvas.catalog||[]).map(c=>({id:c.id,name:c.name,family:c.category||'Get',input:'any',output:'any',description:c.description||'',definition:c.id,revision:c.revision_root,descriptor:c.descriptor}));
 for(const mod of state.mods.filter(m=>m.enabled&&m.status!=='Ready for review'))for(const node of mod.nodes||[])catalogue.push({id:'mod:'+mod.id+':'+node.id,name:node.title,family:node.category||'Change',description:node.summary,modId:mod.id,itemId:node.id});
 const root=canvas.scope?.current||canvas.root;
 const graph={...state.graph,id:root,system:root===(canvas.canvas_root||(canvas.application_root?null:canvas.graph_id)),scopeKey:JSON.stringify([canvas.graph_id,canvas.authorization?.subject,canvas.authorization?.session,root]),name:canvas.scope?.current_label||'Graph',nodes,wires:(canvas.wires||[]).map(w=>({id:w.id,from:w.source||w.from,to:w.target||w.to,fromPort:w.source_interface||w.fromPort,toPort:w.target_interface||w.toPort,type:w.value_type||'any',rule:w.label||''}))};
 // WIRE-projects: the evaluator's condition parameter is the UI's wire rule.
 for(const wire of graph.wires)wire.type=nodes.find(n=>n.id===wire.from)?.outputs.find(p=>p.id===wire.fromPort)?.type||wire.type;
 const conditions=new Map((canvas.wires||[]).map(w=>[w.id,(w.params||[]).find(p=>p.label==='condition')?.value||'']));
 for(const wire of graph.wires)wire.rule=conditions.get(wire.id);
 // WIRE-projects end
 // A local browser-session lease is transport authority, never account sign-in.
 const profile={...state.profile};
 const graphs=state.graphs.some(g=>g.id===graph.id)?state.graphs.map(g=>g.id===graph.id?{...g,...graph}:g):[...state.graphs,graph];
 publish({profile,graph,graphs,settings,canvasPolicy:copy(canvas.interaction_policy||{}),runtimeParameters:copy(canvas.runtime_parameters||{}),catalogue,capabilities:catalogue.map(c=>({...c,nodeKind:c.name,page:'System graph',params:{},defaults:{},enabled:true})),
 docs:[...documentationTutorials(canvas.documentation?.tutorials||[]),...(canvas.documentation?.nodes||[]).map(d=>({id:d.id,category:d.category,title:d.title,summary:d.detail||'',steps:[],route:'canvas'}))],
 sync:'Local session'});
 if(state.social?.research?.length)publish({docs:[...state.docs,...state.social.research.map(researchDoc)]});
}
function workshopBinding() {
 const scope=canvas?.workshop_scope;
 const workshop=scope?.workshops?.find(w=>w.is_general)||scope?.workshops?.[0]||canvas?.workshops?.[0];
 if(workshop)return {root:workshop.root,scope:canvas.scope?.current||scope?.root||canvas.root};
 const boot=window.ARCHHUB_BOOT?.workshop;
 if(boot?.root)return {root:boot.root,scope:boot.scope||boot.root};
 // File-only Canvas never loads workshop_scope; keep the graph-free owner.
 return {root:'app:workshop',scope:'app:workshop'};
}
function rememberGraph(id) {
 if(id===state.graphs[0]?.id||id===session?.lastGraphId||!state.graphs.some(g=>g.id===id))return;
 session={...session,lastGraphId:id};
 try {sessionStorage.setItem('archhub.studio.session',JSON.stringify(session));}
 catch {notice('The last graph could not be saved for this browser session.');}
}
function openGraph(id) {
 requestedGraph=id;
 const opened=graphNavigation.then(()=>request('/api/universal/graph-open',{root:id}));
 graphNavigation=opened.catch(()=>{});
 return opened;
}
async function workshop(fn,args=[]) {
 const binding=workshopBinding();if(!binding)return unavailable(fn,'Workshop owner unavailable');
 const response=await request('/api/universal/workshop',{action:'data-api',function:fn,args,...binding,request_id:window.crypto.randomUUID()});
 return response.result;
}
const desktopActions=['setDesktopProgram','offerDesktopAction','prepareDesktopAction','setScheduleResponsibility','reviewScheduledWork'];
const watcherActions=['setWatcherHost','setWatcherView','addDimension','editWall','addMark','addComment','proposeWatcherEdit','discardWatcherChanges'];
const hostSkillActions=['importHostSkill','inspectConnectorBundle','configureConnectorBundle','installConnectorBundle','setHostSkillEnabled','auditHostSkill'];
const approvalActions=['postponeApproval','resumeApproval','contestDecision','refreshApproval','reviewProofRow','setApprovalRubric'];
const researchActions=['runValuation','runResearchNode','setResearchReview','correctAnswerSource'];
async function refreshApprovals() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const approvals=await workshop('listApprovals');
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return state.approvals;
 if(!Array.isArray(approvals))return approvals;  // same contract as refreshTasks: the owner's refusal is the answer, not a throw
 const tasks=state.tasks.map(task=>({...task,approvalId:approvals.findLast(card=>(card.work===task.id||card.taskIds?.includes(task.id))&&card.status!=='superseded')?.id}));
 publish({approvals,tasks,approvalActionsReady:true});return approvals;
}
async function refreshTasks(details=true) {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const tasks=await workshop('listTasks',[true]);if(!Array.isArray(tasks))return tasks==null ? state.tasks : tasks;
 const room=await workshop('listWorkshopMessages');
 const liveAgents=await workshop('listLiveAgents').catch(()=>[]);
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return state.tasks;
 const roomPage=Array.isArray(room?.messages)
  ? {workshopMessages:room.messages,workshopMessagesMore:room.more===true,workshopMessagesBefore:room.next_before,workshopMessagesScope:binding}
  : state.workshopMessagesScope===binding ? {}
  : {workshopMessages:[],workshopMessagesMore:false,workshopMessagesBefore:null,workshopMessagesScope:null};
 const opened=new Map(state.tasks.map(t=>[t.id,t]));
 const fileOwned=['fileMessages','path','sessionId','parameters'];
 publish({tasks:tasks.map(t=>{const old=opened.get(t.id)||{};const projected=key=>Object.hasOwn(t,key)?t[key]:(fileOwned.includes(key)?old[key]:undefined);return {...t,messages:t.messages||[],steps:t.steps||[],reviews:t.reviews||[],queuedMessages:t.queuedMessages||[],
  workflow:projected('workflow'),activity:projected('activity'),plan:projected('plan'),agents:projected('agents'),progress:projected('progress'),parameters:projected('parameters'),
  scope:projected('scope'),rules:projected('rules'),fileMessages:projected('fileMessages'),path:projected('path'),folders:projected('folders'),references:projected('references'),sessionId:projected('sessionId')};}),
   ...roomPage,liveAgents:Array.isArray(liveAgents)?liveAgents:[]});
 projectProviders();
 const current=tasks.find(row=>row.sessionOpen&&row.sessionPath);
 if(current&&!openingTask&&!Array.isArray(opened.get(current.id)?.workflow)){
  try{await api.openTaskGraph(current.id);}
  catch(error){publish({connectionNotice:error.message||'This task session did not open.'});}
 }
 if(details){await refreshApprovals();await refreshWatcher();await refreshHostSkills();await refreshDesktop();await refreshNotifications();}
 return state.tasks;
}
function projectProviders(agentGraph=state.agentGraph) {
 const providers=providerRoster.map(p=>({...p,model:state.providerPreferences?.[p.id]||p.model,models:state.providerModels?.[p.id]||[]}));
 const agents=workingAgents.filter(a=>a.kind!=='observation');
 const complete=workingAgents.every(a=>a.observation_complete!==false&&a.presence!=='unknown');
 const sessions=agentGraph?.sessions||[];
 const working=sessions.filter(a=>a.status==='working').length, idle=sessions.filter(a=>a.status==='idle').length;
 const assigned=new Set(state.tasks.flatMap(t=>(t.declarations||[]).map(d=>d.root)));
 const declaredTasks=[...new Map(agents.flatMap(p=>(p.sessions||[]).filter(d=>d.status==='working'&&!assigned.has(d.root))
  .map(d=>[d.request_id,{id:d.root,title:d.task,owner:p.runtime||p.id,status:'WIP',declaration:true}]))).values()];
 publish({providers,agents,declaredTasks,agentGraph,agentWorkingCount:working,
  agentSummary:!agentsChecked?'Checking running agents…':!complete?'Agent status is incomplete.':working?`${working} working · ${idle} idle`:sessions.length?'No agents are working.':'No agents are running.',
  agentHealth:!agentsChecked?'Checking running agents…':!complete?'Agent status is incomplete. Some sessions could not be checked.':'Agent status is current.'});
}
function providerDto(p) {
 const availability=({keyed:'Credential present · Sign-in not checked',running:'Reachable · Model not reported',
  'no key':'Not connected','key invalid':'Credential invalid','not running':'Not reachable',checking:'Checking local runtime…',
  installed:'Installed · Sign-in not checked','not installed':'Not installed',
  'keyed, not routed':'Credential present · No direct route','not supported':'Not supported yet'})[p.state]||'Availability not reported';
 return {...p,id:p.id||p.provider||p.app,name:p.name||p.label||p.id||p.provider||p.app,
  ini:p.ini||(p.name||p.id||p.provider||p.app||'').slice(0,1),col:p.col||window.AH?.inkSoft,
  availability,authentication:p.signedIn===true?'Connected':p.signedIn===false?'Not connected':'Sign-in not checked',
  presence:p.status||p.presence||availability,model:p.model||'Model not reported'};
}
function unknownAgent(a,previous=a) {
 const last=previous?.presence==='unknown'?previous.last_known_status:previous?.status_text;
 return {...a,observation_complete:false,presence:'unknown',status_text:'Status unknown',last_known_status:last,
  detail:'ArchHub could not check this agent.'+(last?` Last known status: ${last}.`:'')};
}
function agentsUnknown() {
 agentsChecked=true;
 workingAgents=workingAgents.length?workingAgents.map(a=>unknownAgent(a)): [{id:'agent-observation',kind:'observation',observation_complete:false}];
 projectProviders();
}
async function refreshAgents() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 try {
  const graph=await request('/api/universal/agents-canvas'), agents=graph.agents;
  if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return state.agents;
  if(!Array.isArray(agents)){agentsUnknown();return agents;}
  agentsChecked=true;
  const inventory=agents.some(a=>a.observation_complete===false)
   ? [...agents,...workingAgents.filter(a=>a.kind!=='observation'&&!agents.some(row=>row.id===a.id)).map(a=>unknownAgent(a))]:agents;
  workingAgents=inventory.map(a=>{
   if(a.presence==='unknown')a=unknownAgent(a,workingAgents.find(row=>row.id===a.id));
   return {...a,runtime:a.runtime||a.id,ini:(a.name||a.id||'A').slice(0,1),
    col:a.col||window.AH?.inkSoft,model:a.model||'Model not reported',task:a.task||a.sessions?.[0]?.task||'Idle'};
  });
  projectProviders(graph);return state.agents;
 } catch(error) {
  if(epoch===scopeEpoch&&binding===JSON.stringify(workshopBinding())){
   agentsUnknown();
  }
  throw error;
 }
}
async function refreshAccount() {
 const account=await request('/api/universal/cloud-session');
 if(!desktopAdmitted())return {};
 let attempt=null;
 if(accountSignInPending){
  attempt=await request('/api/universal/cloud-signin');
  if(['done','failed','idle'].includes(attempt.phase)||account.signed_in===true)accountSignInPending=false;
 }
 publish({profile:{...state.profile,id:desktopAccess.subject||'',
  name:String(account.user_id||'')===desktopSubject?(account.display_name||account.name||''):'',
  email:desktopAccess.email||'',signedIn:desktopAdmitted(),checking:false,
  isFounder:String(account.user_id||'')===desktopSubject&&account.founder===true},
  sync:account.signed_in===true?'Account connected':accountSignInPending?'Complete sign-in in your browser':account.state==='expired'?'Sign in again':'Signed out',
  ...(attempt?.phase==='failed'?{connectionNotice:attempt.error||'Sign-in failed. Try again.'}:{})});
 return copy(state.profile);
}
function projectUpdate(data) {
 const update={state:data.state||'unavailable',installed:data.current_build||'',next:data.available_build||'',
  available:data.state==='ready'&&!!data.available_build&&data.restart_supported===true,
  restartSupported:data.restart_supported===true,restartRefusal:data.restart_refusal||'',
  detail:data.detail||'Update status unavailable',updatedFrom:data.updated_from||'',updatedTo:data.updated_to||''};
 publish({update});return copy(update);
}
async function refreshApplicationUpdate(background=false) {
 if(updateActionPending||(background&&(document.hidden||updateReadsPending||Date.now()<updateReadAfter)))return copy(state.update);
 updateReadsPending++;
 const generation=++updateGeneration;
 try{
  const data=await request('/api/universal/application-update',undefined,true,AbortSignal.timeout(15000));
  if(generation!==updateGeneration)return copy(state.update);
  updateReadFailures=0;updateReadAfter=0;
  if(state.connectionNotice==='Checking for updates…')publish({connectionNotice:''});
  return projectUpdate(data);
 }catch(error){
  if(generation!==updateGeneration)return copy(state.update);
  const delay=[5000,15000,60000,300000][Math.min(updateReadFailures++,3)];
  updateReadAfter=Date.now()+delay;
  projectUpdate({state:'failed',current_build:state.update.installed,detail:error.message});
  if(!state.connectionNotice||state.connectionNotice==='Checking for updates…')publish({connectionNotice:'Checking for updates…'});
  if(!background)throw error;
  return copy(state.update);
 }finally{updateReadsPending--;}
}
async function updateAction(action) {
 if(updateActionPending)throw Error('An update action is already in progress. Read status before trying again.');
 const generation=++updateGeneration;
 updateActionPending=true;
 publish({update:{...state.update,available:false,state:action==='reload'?'restarting':action==='check'?'checking':state.update.state}});
 let refused=null;
 try{return projectUpdate(await request('/api/universal/application-update',{action}));}
 catch(error){
  // A refused restart (agents busy, unsaved work) is temporary: re-read the guard so the offer and its Update
  // control come back. Any other action's failure, or a status read that fails too, stays a failure.
  if(generation===updateGeneration){if(action==='reload')refused=error;else projectUpdate({state:'failed',current_build:state.update.installed,detail:error.message});}
  throw error;
 }finally{
  updateActionPending=false;
  if(refused)await refreshApplicationUpdate().catch(readError=>{
   console.warn('Update status read after a refused restart failed',readError);
   projectUpdate({state:'failed',current_build:state.update.installed,detail:refused.message});
  });
 }
}
window.addEventListener('archhub:update-ready',()=>{
 // Read failures belong to the retrying status owner, not a permanent toast.
 refreshApplicationUpdate().catch(error=>console.warn('Update status read will retry',error));
});
async function refreshLive() {
 if(!ready||!desktopAdmitted()||document.hidden||listeners.size===0)return state.tasks;
 if(activeSurface==='canvas'){
  if(!canvasRefresh)canvasRefresh=api.tickSchedules(true)
   .catch(error=>{if(error.status===403)clearCanvas();publish({connectionNotice:error.message});}).finally(()=>{canvasRefresh=null;});
  return canvasRefresh;
 }
 // The same timer refreshes rows even while account/provider discovery is slow.
 if(!taskRefreshInFlight)taskRefreshInFlight=refreshTasks(false).catch(error=>publish({connectionNotice:error.message})).finally(()=>{taskRefreshInFlight=null;});
 if(refreshInFlight){await taskRefreshInFlight;return state.tasks;}
 refreshInFlight=true;
 try {
  await taskRefreshInFlight;
  for(const refresh of [refreshAgents,...(Array.isArray(state.hosts)?[api.readHostAvailability]:[]),()=>refreshApplicationUpdate(true),refreshAccount,api.listProviders,refreshSettingsControls,refreshApprovals,refreshWatcher,refreshHostSkills,refreshDesktop,refreshNotifications]){
   if(activeSurface==='canvas')break;
   try{await refresh();}catch(error){publish({connectionNotice:error.message});}
  }
 }
 finally{refreshInFlight=false;}
 return state.tasks;
}
function stopRefresh(){if(refreshTimer!==null){window.clearInterval(refreshTimer);refreshTimer=null;}}
function clearCanvas(){
 scopeEpoch++;accountEpoch++;canvas=null;commands?.clear();defaults.clear();conditional.clear();state=copy(initialState);providerRoster=[];controlsGeneration++;preferenceGeneration++;notificationGeneration++;
 workingAgents=[];agentsChecked=false;
 publish({graphOpening:false,graph:{id:'',scopeKey:'',name:'',nodes:[],wires:[],workspaceIds:[],documentation:'',customProperties:[],courtStatus:''},graphs:[],settings:[],catalogue:[],libraryPorts:[],capabilities:[],docs:[],agents:[],agentSummary:'Checking running agents…',agentHealth:'Checking running agents…',tasks:[],declaredTasks:[],workshopMessages:[],workshopMessagesMore:false,workshopMessagesBefore:null,workshopMessagesScope:null,approvals:[],notifications:[],activeWorkspace:'',activeFile:'',files:[],workspaces:[],desktopReady:false,desktop:{program:'',stage:'',taskId:null,offers:[]},watcherReady:false,watcher:copy(emptyWatcher),hostSkillsReady:false,hostSkills:[],connectorBundle:null});
}
function watchRefresh(){stopRefresh();if(listeners.size&&!document.hidden)refreshTimer=window.setInterval(async()=>{await refreshDesktopAccess();if(desktopAdmitted())await refreshLive();},ownerRefreshMs);}
document.addEventListener('visibilitychange',()=>{watchRefresh();reportedSurface=null;reportSurface();if(!document.hidden)void refreshDesktopAccess(true).then(()=>{if(desktopAdmitted())return refreshLive();return null;});});
window.addEventListener('pagehide',stopRefresh);
window.addEventListener('pageshow',watchRefresh);
const canvasOperation=(op,args)=>[
 'project_schedules','list_skills','library_ports',
 'mcp_servers','add_mcp_server','remove_mcp_server','set_mcp_server_enabled',
 'discover_mcp_tools','reconnect_mcp','sign_in_mcp_server','prepare_mcp_tool'
].includes(op)
 ? request('/api/universal/canvas-op',{op,args}).then(data=>data.result)
 : mutate(async()=> (await request('/api/universal/canvas-op',{op,args})).result);
async function mutate(command,admitted=false) {
 const epoch=scopeEpoch;let result;
 if(admitted)result=await command();
 else await commands.transact(async()=>{
  result=await command();
  if(result?.ok===false)return commands.getSnapshot().canvas;
  const projection=normalise(result?.canvas||result);
  return projection?.root&&Array.isArray(projection.nodes)?projection:request('/api/universal/canvas');
 });
 if(epoch===scopeEpoch)project();
 return result;
}
function interaction(control,extra={}) {
 const current=commands?.getSnapshot()?.canvas||canvas;
 const bindings=(current?.interaction_projection?.bindings||[]).filter(b=>b.control===control);
 if(bindings.length!==1)return Promise.resolve(unavailable(control,'No current command binding'));
 const b=bindings[0];return request('/api/universal/interaction',{interaction:b.interaction,control:b.control,event:b.event,
 expected_scope:current.scope?.current||current.root,revision:current.revision,...(b.projection_mode?{projection_mode:b.projection_mode}:{}),command_id:window.crypto.randomUUID(),...extra});
}
function nodeProperty(id,key,value) {
 const epoch=scopeEpoch,address=JSON.stringify([epoch,id,key]),pending=parameterWrites.get(address);
 if(pending){pending.value=value;return pending.promise;}
 const write={value};parameterWrites.set(address,write);
 write.promise=(async()=>{
 let result;
 do {
 const submitted=write.value;delete write.value;value=submitted;
 try {
 result=await mutate(async()=>{
 if(epoch!==scopeEpoch)throw Error('The graph changed before this parameter was saved.');
 const current=commands.getSnapshot().canvas, n=current.nodes.find(n=>n.id===id),p=rows(n).find(p=>p.label===key);
 if(!p?.editable)return unavailable('setNodeParam','This parameter has no editable owner');
 if(p.setting?.kind==='baboom'){const preferences={value:rows(n).find(r=>r.setting?.key==='start_with_archhub')?.value,shows_as:rows(n).find(r=>r.setting?.key==='shows_as')?.value};preferences[p.setting.key==='shows_as'?'shows_as':'value']=value;value=JSON.stringify(preferences);}
 const binding=(current.interaction_projection?.bindings||[]).find(b=>b.control===p.relation);
 if(binding){const spec=binding.event_facts?.find(f=>f.source==='submitted');if(!spec)return unavailable('setNodeParam','No submitted-value binding');result=await interaction(binding.control,{...(!window.ARCHHUB_AUTHORITY?{projection_mode:binding.projection_mode||'interaction-delta-v1'}:{}),event_facts:[{input:spec.input,value:typeof value==='string'?value:JSON.stringify(value)}]});}
 else result=await request('/api/universal/set-property',{relation:p.relation,value:typeof value==='string'?value:JSON.stringify(value),...(!window.ARCHHUB_AUTHORITY&&Number.isInteger(current.revision)?{projection_mode:'interaction-delta-v1',projection_revision:current.revision}:{})});
 return result;
 });
 if(epoch!==scopeEpoch)throw Error('The graph changed while this parameter was saved.');
 if(result?.ok===false)return result;
 result=state.graph.nodes.find(n=>n.id===id)||result;
 if(Object.is(write.value,submitted))delete write.value;
 }catch(error){if(epoch!==scopeEpoch||!Object.hasOwn(write,'value'))throw error;}
 }while(Object.hasOwn(write,'value'));
 return result;
 })().finally(()=>parameterWrites.delete(address));
 return write.promise;
}
const api={};
// The desktop companion steps aside while Settings is the open, visible screen.
let reportedSurface='';
function reportSurface(){const surface=document.hidden?'':activeSurface;if(surface===reportedSurface)return;reportedSurface=surface;request('/api/universal/studio-surface',{surface}).catch(()=>{reportedSurface=null;});}
api.setActiveSurface=surface=>{const previous=activeSurface;activeSurface=surface;reportSurface();if(previous.startsWith('settings')&&!surface.startsWith('settings'))syncPreferenceContext(true);};
for(const name of exportedNames)api[name]=()=>unavailable(name);
const unfinishedActions={...api};
api.supportsAction=(name,mode)=>!(name==='approve'&&mode&&mode!=='once')&&typeof api[name]==='function'&&api[name]!==unfinishedActions[name];
const boundAction=api.supportsAction;
api.supportsAction=(name,mode)=>boundAction(name,mode)&&
 (!researchActions.includes(name)||!!workshopBinding()&&!state.nativeApproval)&&
 (!approvalActions.includes(name)||state.approvalActionsReady===true&&!state.nativeApproval)&&
 (!desktopActions.includes(name)||state.desktopReady===true&&!state.nativeApproval)&&
 (!watcherActions.includes(name)||state.watcherReady===true&&!state.nativeApproval)&&
 (!hostSkillActions.includes(name)||state.hostSkillsReady===true&&!state.nativeApproval)&&
 (name!=='decline'||state.nativeApproval||state.approvals.some(card=>['watcher','hostskills','desktop','schedule','ask','canvas','social'].includes(card.approvalKind)&&card.status==='pending'))&&
 (!['startVoiceInput','stopVoiceInput'].includes(name)||typeof window.ARCHHUB_VOICE_START==='function'&&typeof window.ARCHHUB_VOICE_STOP==='function')&&
 (name!=='speak'||typeof window.speechSynthesis?.speak==='function'&&typeof window.SpeechSynthesisUtterance==='function');
window.addEventListener('archhub:capabilities',()=>publish());
let voiceCapture=null;
// Settings › Agents › BABOOM: the saved value of one row (settings.json, read with the other Settings rows).
const agentValue=label=>state.settings.find(row=>row.id==='Agents.'+label)?.value;
const spokenAt=[];
api.startVoiceInput=async(options={})=>{
 if(!api.supportsAction('startVoiceInput'))throw Error('Open the desktop Studio to use Windows speech input.');
 if(agentValue('Voice')===false)throw Error('Voice is off in Settings › Agents › BABOOM.');
 if(voiceCapture)throw Error('Finish the current voice capture first.');
 const capture={};voiceCapture=capture;
 const listen=async()=>{
  options.onStatus?.(true);
  const result=await window.ARCHHUB_VOICE_START();
  if(result.ok!==true)throw Error(result.error||'Windows speech input did not complete.');
  if(!result.cancelled)options.onTranscript?.(result.text);
  return result;
 };
 try{return await listen().catch(failure=>{options.onError?.(failure.message);return {ok:false,error:failure.message};});}
 finally{if(voiceCapture===capture)voiceCapture=null;options.onStatus?.(false);}
};
api.stopVoiceInput=()=>{
 if(!api.supportsAction('stopVoiceInput'))throw Error('Open the desktop Studio to stop Windows speech input.');
 return window.ARCHHUB_VOICE_STOP();
};
api.speak=text=>{
 if(!api.supportsAction('speak'))throw Error('Speech output is unavailable in this window.');
 if(typeof text!=='string'||!text.trim()||text.length>32000)throw Error('Choose 1–32000 characters to read aloud.');
 // Voice off, Do not disturb Always, or Speaks at most N lines an hour reached: he answers in text only (the caller shows it).
 const hour=Date.now()-3600000;while(spokenAt.length&&spokenAt[0]<hour)spokenAt.shift();
 if(agentValue('Voice')===false||agentValue('Do not disturb')==='Always'||spokenAt.length>=(agentValue('Speaks at most')??Infinity))return Promise.resolve({ok:false});
 spokenAt.push(Date.now());
 return new Promise((resolve,reject)=>{
  const utterance=new window.SpeechSynthesisUtterance(text);
  utterance.onend=()=>resolve({ok:true});
  utterance.onerror=event=>reject(Error('Speech output failed: '+event.error));
  window.speechSynthesis.speak(utterance);
 });
};
Object.assign(api,{
 async signIn(enabled=true){
  if(!enabled){desktopGeneration++;lockDesktop('signed_out');}
  const result=await request(enabled?'/api/universal/cloud-signin':'/api/universal/cloud-signout',enabled?{method:'google'}:{});
  accountSignInPending=enabled;showDesktopAccess({signingIn:enabled,notice:''});
  await refreshDesktopAccess(true);if(desktopAdmitted())await refreshAccount();return result;
 },
 syncAccount:refreshAccount,
 async windowAction(action){
  if(action!=='quit')requireDesktop();
  if(typeof window.ARCHHUB_WINDOW_ACTION!=='function')throw Error('Open ArchHub from its desktop shortcut to use window controls.');
  const result=await window.ARCHHUB_WINDOW_ACTION(action);
  publish({app:{...state.app,hidden:result.visible===false,quit:action==='quit'}});return result;
 },
 
 async stopEverything(){const result=await request('/stop-all',{});publish({app:{...state.app,stopped:result.stopped===true}});return result;},
 async exportData(name,nodeId){
  if(name==='Graph')return {name:'Graph.json',type:'application/json',content:JSON.stringify(state.graph,null,2)};
  if(name==='Results'){
   const node=nodeId?state.graph.nodes.find(n=>n.id===nodeId):null;
   const rows=nodeId?node?.output:state.lastResult?.rows;
   if(!Array.isArray(rows)||!rows.length)throw Error('Run a node and choose its result before exporting.');
   const records=rows.map(row=>row&&typeof row==='object'&&!Array.isArray(row)?row:{value:row});
   const columns=[...new Set(records.flatMap(row=>Object.keys(row)))];
   const cell=value=>'"'+String(typeof value==='object'?JSON.stringify(value):value??'').replaceAll('"','""')+'"';
   return {name:'Results.csv',type:'text/csv',content:[columns,...records.map(row=>columns.map(key=>row[key]))].map(row=>row.map(cell).join(',')).join('\r\n')};
  }
  throw Error('Choose a saved graph or a completed node result to export.');
 },
 getSnapshot:desktopSnapshot,refreshDesktopAccess,readDesktopView:()=>desktopAdmitted()?copy(state.desktopView||{}):{},rememberDesktopView:view=>{if(desktopAdmitted()&&desktopAccess.ready)publish({desktopView:copy(view)});},subscribe(fn){listeners.add(fn);watchRefresh();watchFile();if(desktopAdmitted()&&!state.chatAgents)api.listChatAgents();return()=>{listeners.delete(fn);if(listeners.size===0){stopRefresh();stopFile();}};},
 listTasks:refreshTasks,listAgentsWorking:refreshAgents,
 async setTaskActivity(id,values){const result=await workshop('setTaskActivity',[id,values]);await refreshTasks();return result;},
 async listWorkshopMessages(before){const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());const page=await workshop('listWorkshopMessages',[before??null]);return epoch===scopeEpoch&&binding===JSON.stringify(workshopBinding())?page:null;},
 async listProviders(){const d=await request('/api/universal/providers');providerRoster=(d.providers||[]).map(providerDto);projectProviders();return state.providers;},
 getSettings:async()=>copy(state.settings),
 getNodeParameters:id=>copy(state.graph.nodes.find(n=>n.id===id)?.parameterSchema||[]),
 getCapabilityParameters:id=>copy(state.capabilities.find(c=>c.id===id)?.parameterSchema||[]),
 getNodeOutput:id=>copy(state.graph.nodes.find(n=>n.id===id)?.output||[]),
 getHealthHistory:async()=>copy(state.healthHistory),getDocs:()=>copy(state.docs),getSocial:()=>copy(state.social),
 getKnowledgeGraph:()=>({nodes:[],edges:[],status:'not_connected',message:'Knowledge graph is unavailable.'}),
 contextLabel:id=>state.files.find(x=>x.id===id)?.name||state.graph.nodes.find(x=>x.id===id)?.title||id,
 compatibleNodes:()=>[],getDecisionState:()=>null,
 async sendToBaboom(text,options={}){return routerChat(text,options.provider||'BABOOM',undefined,options.taskId,false);},
 async setSetting(id,value,destination=state.settingsDestination){
  if(window.ARCHHUB_BOOT?.nograph&&(id.startsWith('Appearance.')||id.startsWith('Projects.')||id.startsWith('Agents.')||id.startsWith('Connections.')||(id.startsWith('Account.') && state.settings.some(row=>row.id===id && row.storageKey)))&&state.settings.some(row=>row.id===id))return setAppearance(id,value,destination);
  const row=state.settings.find(r=>r.id===id);if(!row)return unavailable('setSetting');
  if(id==='Appearance.Zoom percentage'){
   if(!Number.isFinite(Number(value))||Number(value)<=0)throw Error('Enter a positive zoom percentage.');
   return mutate(()=>request('/api/universal/gesture',{viewport:{...canvas.viewport,zoom:Number(value)/100},expected_scope:canvas.scope?.current||canvas.root}));
  }
  return nodeProperty(row.owner,row.key,value);
 },
 async resetSetting(id,destination=state.settingsDestination){if(window.ARCHHUB_BOOT?.nograph&&(id.startsWith('Appearance.')||id.startsWith('Projects.')||id.startsWith('Agents.')||id.startsWith('Connections.')||(id.startsWith('Account.') && state.settings.some(row=>row.id===id && row.storageKey))))return settingsAction('resetAppearance',[id],destination).then(result=>preferenceChanged(id,result));const row=state.settings.find(r=>r.id===id);return row&&row.default!==undefined?api.setSetting(id,row.default,destination):unavailable('resetSetting','Backend default unavailable');},
 async resetPage(page){for(const row of state.settings.filter(r=>r.page===page&&(r.id!=='Appearance.Zoom percentage'||r.default!==undefined))) {const result=await api.resetSetting(row.id);if(result?.ok===false)return result;}return {ok:true};},
 setNodeParam:nodeProperty,
 resetNodeParam(id,key){const node=state.graph.nodes.find(n=>n.id===id);return node&&Object.hasOwn(node.defaults,key)?nodeProperty(id,key,node.defaults[key]):unavailable('resetNodeParam','Backend default unavailable');},
 async renameNode(id,title){return nodeProperty(id,'title',title);},
 async addNode(name,position={}){
  const scope=scopeEpoch+':'+state.graph.id;
  let {x,y=200}=position, reservation;
  if(x===undefined){
   const detail={reserved:[...insertionReservations].filter(point=>point.scope===scope),point:null,error:null};
   window.dispatchEvent(new CustomEvent('archhub:canvas-insertion',{detail}));
   if(detail.point){
    ({x,y}=detail.point);reservation={...detail.point,scope};insertionReservations.add(reservation);
   }else{
   x=insertionPoint.scope===scope?insertionPoint.x:240;
   for(const existing of state.graph.nodes)x=Math.max(x,existing.x+280);
   insertionPoint={scope,x:x+280};
   }
  }
  try{
  const create=async()=>{
  const modEntry=state.catalogue.find(c=>c.modId&&(c.id===name||c.name===name));
  if(modEntry){const made=await canvasOperation('import_mod_node',[modEntry.modId,modEntry.itemId]);await api.moveNode(made.id,{x,y});return state.graph.nodes.find(n=>n.id===made.id)||made;}
  const entry=(canvas.catalog||[]).find(c=>c.id===name||c.name===name);
  if(!entry)return unavailable('addNode','Definition unavailable');
  if(entry.revision_root){const result=await mutate(()=>commands.create({definition:entry.id,definition_revision:entry.revision_root,x,y}),true);return state.graph.nodes.find(n=>n.id===result.selected);}
  const engine=entry.descriptor?.engine,item=entry.descriptor?.item;
  if(!engine){const result=await interaction(entry.id,{event_facts:[{source:'canvas-point-x',value:x},{source:'canvas-point-y',value:y}]});if(result?.ok===false)return result;await commands.load();project();return state.graph.nodes.find(n=>n.id===result.selected)||result;}
  const result=await request('/api/universal/node-create',{title:entry.name,engine,item,x,y});await commands.load();project();return state.graph.nodes.find(n=>n.id===result.root)||result;
  };
  const made=await create();
  if(reservation && made?.id && !document.hidden && window.requestAnimationFrame){
   await new Promise(resolve=>{const timer=setTimeout(resolve,Number(state.canvasPolicy?.viewport_commit_debounce_ms??140));window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{clearTimeout(timer);resolve();}));});
   if(scope!==scopeEpoch+':'+state.graph.id || document.hidden)return made;
   const detail={reserved:[...insertionReservations].filter(point=>point!==reservation&&point.scope===scope),nodeId:made.id,point:null,error:null};
   window.dispatchEvent(new CustomEvent('archhub:canvas-insertion',{detail}));
   if(detail.point && (detail.point.x!==x || detail.point.y!==y))await api.moveNode(made.id,{x:detail.point.x,y:detail.point.y});
   if(detail.point)reservation=Object.assign(reservation,detail.point);
  }
  if(made?.id && reservation?.offscreen)notice('Added off-screen — '+reservation.offscreen);
  return state.graph.nodes.find(n=>n.id===made?.id)||made;
  }finally{if(reservation)insertionReservations.delete(reservation);}
 },
 moveNode:(id,position)=>mutate(()=>commands.move(id,position),true),
 moveNodes:positions=>mutate(()=>commands.moveMany(positions),true),
 groupNodes:ids=>mutate(()=>commands.composition('group',ids),true),
 ungroupNode:id=>mutate(()=>commands.composition('ungroup',[id]),true),
 deleteNode:id=>mutate(()=>commands.remove(id),true),
 async forkNode(id){const result=await canvasOperation('fork_node',[id]);return state.graph.nodes.find(n=>n.id===result.id)||result;},
 setNodeFlags:(id,values)=>canvasOperation('set_node_flags',[id,values.frozen??null,values.pinned??null]),
 traceNode:(id,direction)=>canvasOperation('trace_node',[id,direction]),
 async runToHere(id){const plan=await canvasOperation('run_to_here',[id]);if(!plan.roots.length)return plan;return mutate(()=>request('/api/universal/run-graph',{roots:plan.roots}));},
 async updateGraph(id,values){
  if(Object.keys(values).some(key=>!['name','pinned'].includes(key)))return unavailable('updateGraph','This graph property has no released owner');
  const result=await canvasOperation('update_graph',[id,values.name??null,values.pinned??null]);await refreshGraphs();return result;
 },
 async removeGraph(id){const result=await canvasOperation('remove_graph',[id]);await refreshGraphs();return result;},
 async arrangeGraph(){const positions=Object.fromEntries(state.graph.nodes.map((n,i)=>[n.id,{x:80+(i%4)*300,y:80+Math.floor(i/4)*220}]));return mutate(()=>commands.moveMany(positions,canvas.revision,null,'arrange'),true);},
 connectSockets:wire=>mutate(()=>commands.connect(wire.from,wire.fromPort,wire.to,wire.toPort),true),
 deleteWire:id=>mutate(()=>commands.remove(id),true),
 async runNode(id){if(id)await commands.select(id);return mutate(()=>commands.run(),true);},
 undo:()=>mutate(()=>commands.undo(),true),redo:()=>mutate(()=>commands.redo(),true),
 async addNodeParameter(id,input){
  if(!['text','All',undefined].includes(input.type))return unavailable('addNodeParameter','Typed parameter creation is not exposed by this owner');
  await commands.select(id);project();const b=(canvas.interaction_projection?.bindings||[]).find(b=>b.control==='app:control:inspector:add-property');
  if(!b)return unavailable('addNodeParameter','Property form unavailable');
  const specs=b.event_facts.filter(s=>s.source==='submitted');
  if(specs.length!==2)return unavailable('addNodeParameter','Property form changed');
  return mutate(()=>interaction(b.control,{event_facts:[{input:specs[0].input,value:input.label},{input:specs[1].input,value:String(input.value??'')}]}));
 },
 
  
async approve(id){const card=state.approvals.find(c=>c.id===id);if(card?.approvalKind==='social'){const result=await request('/api/universal/social-approve',{delegation:card.delegation,input_digest:card.input_digest,decision:'approve'});await refreshApprovals();return result;}if(!card?.delegation||!card?.input_digest||!card?.work)return unavailable('approve','No reviewed model delegation');const binding=workshopBinding();const body={...binding,work:card.work,delegation:card.delegation,input_digest:card.input_digest};const inspected=await request('/api/universal/workshop-model-approval?'+new URLSearchParams(body));if(inspected.expired||inspected.input_digest!==card.input_digest)return {ok:false,status:'stale',message:'Review changed; refresh before approving.'};const result=await request('/api/universal/workshop-model-approval',{...body,revision:inspected.revision});await refreshTasks();return result;},
 async selectWorkspace(id){preferenceGeneration++;try{const result=await request('/api/universal/workspace-roots',{action:'select',id});publish({activeWorkspace:result.root.root_id});return result;}finally{preferenceGeneration++;}},
 getUsageSummary:()=>({'Usage':'Usage is unavailable.'}),
 async setConnection(id,values){if(values.connected===false)return request('/api/universal/social-connection',{provider:id,action:'cancel'});if(values.connected===true)return request('/api/universal/social-connection',{provider:id,action:'start'});return unavailable('setConnection','No sign-in action requested');},
 async checkConnection(id){return request('/api/universal/social-connection?provider='+encodeURIComponent(id));},
 refreshApplicationUpdate,
 checkForUpdates:()=>updateAction('check'),
 acknowledgeUpdate:()=>updateAction('acknowledge'),
 async installUpdate(){
  // An explicit click asks the native guard again: a refusal from a moment ago (busy agents) may no longer hold.
  if(!state.update.available||state.update.restartRefusal)await refreshApplicationUpdate();
  if(!state.update.available)throw Error(state.update.detail||'No verified update is ready. Check for updates.');
  if(state.update.restartRefusal)throw Error(state.update.restartRefusal);
  return updateAction('reload');
 },
 async listWorkspaces(){let data;try{data=await request('/api/universal/workspace-roots',{action:'list'});}catch(error){publish({workspaceHealth:{state:'error',message:'ArchHub could not read your workspace list. Your files are unchanged.',detail:error.message}});throw error;}const roots=[...(data.built_in?[{...data.built_in,root_id:data.built_in.id,builtIn:true}]:[]),...(data.roots||[]).filter(w=>w.state!=='unregistered')];const workspaces=roots.map(w=>({id:w.root_id,name:w.label||(w.builtIn?'ArchHub':w.root_id),folder:w.path,canvas:w.canvas||'',builtIn:w.builtIn===true,removable:w.removable!==false,privacy:w.privacy,available:w.available,register:w.register,registerFiles:w.registerFiles||{},nativeClientEditor:data.native_client_editor===true,projectTemplate:w.project_template}));publish({workspaces,workspaceHealth:{...(data.health||{state:'unverified',message:'Reading workspaces…'}),projection:data.projection,revision:data.revision}});return workspaces;},
 editLocalProjectClient(id){return request('/api/universal/workspace-roots',{action:'edit-local-client',id});},
 async updateProjectRegister(workspace, number, override, references={}){
  // references: namingRegister / issuedRegister, a register file inside the project (relative or picked); omitted keeps, '' clears.
  const result=await request('/api/universal/workspace-roots',{...references,action:'update-register',id:workspace.id,expected:workspace.register,number,override});
  await api.listWorkspaces();
  syncPreferenceContext(true);
  return result;
 },
 // A register file picked on this PC; a cancelled pick answers {cancelled:true} and changes nothing.
 async pickProjectRegister(title, folder=false){const picked=folder?await request('/api/universal/workspace-roots',{action:'browse'}):await request('/api/universal/pick-file',{title,filter:'Register (*.xlsx *.xlsm *.csv *.md)'});return picked.path?{path:picked.path}:{cancelled:true,note:picked.note||''};},
 async chooseProjectTemplate(){return request('/api/universal/workspace-roots',{action:'browse',template:true,template_window:projectTemplateWindow});},
 async addWorkspace(input={}){if(input.create){const result=await request('/api/universal/workspace-roots',{action:'create',parent:input.parent,name:input.name,template:input.template||'',template_source:input.templateSource||'',template_window:projectTemplateWindow});await api.listWorkspaces();return {...result,message:'Project created and added to your workspaces.'};}let path=input.folder;if(!path){const picked=await request('/api/universal/workspace-roots',{action:'browse'});path=picked.path;if(!path)return {cancelled:true,message:'No workspace was added.'};}const result=await request('/api/universal/workspace-roots',{action:'register',path,privacy:'private',profile:'client'});await api.listWorkspaces();return {...result,message:'Workspace added. Your agents can work here.'};},
 async removeWorkspace(id){const result=await request('/api/universal/workspace-roots',{action:'unregister',id});await api.listWorkspaces();return {...result,message:'Workspace removed from ArchHub. Your files are unchanged.'};},
});
for(const fn of ['setTaskStatus','archiveTask','restoreArchivedTask','reassignTask','setTaskDelegate','setTaskAgentAccess','queueTaskMessage','settleQueuedMessage','steerTask','addTaskReview','resolveTaskReview']) {
 api[fn]=async(...args)=>{const result=await workshop(fn,args);if(result?.ok===false)return result;await refreshTasks();if(['reassignTask','setTaskDelegate','setTaskAgentAccess'].includes(fn)&&sessionDocument?.properties?.taskContext?.task===args[0])await pollFile(true).catch(()=>{});return result;};
}
api.continueTaskWithAgent=(id,agent)=>api.reassignTask(id,agent);
api.deleteTask=async(id,revision=null)=>{
 const isOpen=()=>sessionDocument?.properties?.taskContext?.task===id;
 if(isOpen()){
  if(currentEditState().unsaved)throw Error('Save or discard the unsaved canvas changes before deleting.');
  clearTimeout(autosaveTimer);
  await fileWrites;
 }
 const receipt=await workshop('deleteTask',[id,revision]);
 if(receipt?.ok!==true||receipt.deleted!==true||receipt.id!==id)return receipt;
 if(isOpen()){
  clearTimeout(autosaveTimer);autosaveTimer=null;
  clearTimeout(solveTimer);solveIds.clear();solveParams=[];
  fileNavigation++;runEpoch++;sessionDocument=null;sessionPath='';fileHistory=[];fileFuture=[];
  await api.newSession();
 }
 await refreshTasks(false);
 return receipt;
};
for(const name of approvalActions) {
 api[name]=async(...args)=>{
  const result=await workshop(name,args);
  if(!result?.id||result.ok===false)throw Error(result?.message||result?.error||'Approval action was not confirmed. Retry the Workshop read.');
  await refreshApprovals();return result;
 };
}
// Watcher state is projected only from its current admitted graph owner.
async function refreshWatcher() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const result=await workshop('readWatcher');
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return null;
 if(!result?.owner){publish({watcherReady:false,watcher:copy(emptyWatcher)});return null;}
 publish({watcher:{...state.watcher,...result},watcherReady:true});return result;
}
api.readWatcher=refreshWatcher;
for(const name of watcherActions) {
 api[name]=async(...args)=>{
  if(!api.supportsAction(name))throw Error('Watcher owner unavailable; open its Workshop and retry.');
  const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
  const result=await workshop(name,args);
  if(result?.ok===false||!(result?.owner||result?.approvalKind==='watcher'))throw Error(result?.error||result?.message||'Watcher action was not confirmed.');
  if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return result;
  await refreshWatcher();
  if(name==='proposeWatcherEdit'||name==='discardWatcherChanges')await refreshApprovals();
  return result;
 };
}
async function refreshDesktop() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 try {
  const result=await workshop('readDesktop');
  if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return null;
  if(!result?.owner||!Array.isArray(result.schedules)||!Array.isArray(result.offers))throw Error('Desktop owner unavailable');
  const {schedules,...desktop}=result;
  publish({desktop,schedules,desktopReady:true});return result;
 } catch(error) {
  if(epoch===scopeEpoch&&binding===JSON.stringify(workshopBinding()))publish({desktopReady:false,desktop:{program:'',stage:'',taskId:null,offers:[]}});
  return null;
 }
}
api.readDesktop=refreshDesktop;
for(const name of desktopActions)api[name]=async(...args)=>{
 if(!api.supportsAction(name))throw Error('Desktop and schedule owner unavailable; reopen the graph and retry.');
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const result=await workshop(name,args);
 if(result?.ok===false||!(result?.owner||result?.id))throw Error(result?.error||result?.message||'Desktop action was not confirmed.');
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return result;
 await refreshDesktop();await refreshApprovals();return result;
};
async function refreshHostSkills() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 try {
  const result=await workshop('readHostSkills');
  if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return null;
  if(!result?.owner||!Array.isArray(result.hostSkills)||!Array.isArray(result.connectorBundles))throw Error('Host package owner unavailable');
  const selected=result.connectorBundles.find(row=>row.id===state.connectorBundle?.id)||result.connectorBundle;
  publish({hostSkills:result.hostSkills,connectorBundle:selected,hostSkillsReady:true});return result;
 } catch(error) {
  if(epoch===scopeEpoch&&binding===JSON.stringify(workshopBinding()))publish({hostSkillsReady:false,hostSkills:[],connectorBundle:null});
  return null;
 }
}
api.readHostSkills=refreshHostSkills;
for(const name of hostSkillActions)api[name]=async(...args)=>{
 if(!api.supportsAction(name))throw Error('Host package owner unavailable; reopen its graph and retry.');
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 if(name==='inspectConnectorBundle'&&typeof args[0]?.arrayBuffer==='function'){
  const file=args[0],bytes=new window.Uint8Array(await file.arrayBuffer());
  if(bytes.length>262144)throw Error('Choose a package smaller than 256 KiB.');
  args=[{name:file.name,base64:window.btoa(Array.from(bytes,b=>String.fromCharCode(b)).join(''))}];
 }
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))throw Error('The graph changed while reading the package. Choose it again in the intended graph.');
 if(name==='configureConnectorBundle')args=[state.connectorBundle?.id,...args];
 if(name==='installConnectorBundle'&&!args.length)args=[state.connectorBundle?.id];
 const result=await workshop(name,args);
 if(!result?.id||result.ok===false)throw Error(result?.error||result?.message||'Host package action was not confirmed.');
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return result;
 if(name==='inspectConnectorBundle')publish({connectorBundle:result});
 await refreshHostSkills();await refreshApprovals();return result;
};
const approveDelegation=api.approve;
api.approve=async(id,...args)=>{
 const card=state.approvals.find(c=>c.id===id);
 if(['ask','canvas'].includes(card?.approvalKind)){
  if(card.approvalKind==='canvas')await flushAutosave();
  const result=await workshop('answerApproval',[card.approvalKind,id,card.input_digest,'approve']);
  if(result?.status!=='approved')throw Error(result?.error||result?.message||'The held action was not released.');
  if(card.approvalKind==='canvas' && card.path===sessionPath)await pollFile(true);
  await refreshApprovals();return result;
 }
 if(['desktop','schedule'].includes(card?.approvalKind)){
  const result=await workshop('answerApproval',[card.approvalKind,id,card.input_digest,'approve']);
  if(result?.status!=='approved')throw Error(result?.error||'Desktop result was not confirmed.');
  await refreshDesktop();await refreshWatcher();await refreshApprovals();return result;
 }

 if(card?.approvalKind==='hostskills'){
  const result=await workshop('answerApproval',['hostskills',id,card.input_digest,'approve']);
  if(result?.status!=='approved')throw Error(result?.error||'Package activation was not confirmed.');
  await refreshHostSkills();await refreshApprovals();return result;
 }
 if(card?.approvalKind!=='watcher')return approveDelegation(id,...args);
 const result=await workshop('answerApproval',['watcher',id,card.input_digest,'approve']);
 if(result?.status!=='approved')throw Error(result?.error||result?.message||'Host write was not confirmed.');
 await refreshWatcher();await refreshApprovals();return result;
};
api.decline=async id=>{
 const card=state.approvals.find(c=>c.id===id);
 if(['ask','canvas'].includes(card?.approvalKind)){
  if(card.approvalKind==='canvas')await flushAutosave();
  const result=await workshop('answerApproval',[card.approvalKind,id,card.input_digest,'deny']);
  if(result?.status!=='declined')throw Error(result?.error||result?.message||'The held action was not refused.');
  if(card.approvalKind==='canvas'&&card.path===sessionPath)await pollFile(true);
  await refreshApprovals();return result;
 }
 if(['desktop','schedule'].includes(card?.approvalKind)){
  const result=await workshop('answerApproval',[card.approvalKind,id,card.input_digest,'deny']);
  if(result?.status!=='declined')throw Error(result?.error||'Desktop decline was not confirmed.');
  await refreshDesktop();await refreshApprovals();return result;
 }

 if(card?.approvalKind==='hostskills'){
  const result=await workshop('answerApproval',['hostskills',id,card.input_digest,'deny']);
  if(result?.status!=='declined')throw Error(result?.error||'Package decline was not confirmed.');
  await refreshHostSkills();await refreshApprovals();return result;
 }
 if(card?.approvalKind==='social'){
  const result=await request('/api/universal/social-approve',{delegation:card.delegation,input_digest:card.input_digest,decision:'deny'});
  await refreshApprovals();return result;
 }
 if(card?.approvalKind!=='watcher')throw Error('Choose the exact Watcher proposal to decline.');
 const result=await workshop('answerApproval',['watcher',id,card.input_digest,'deny']);
 if(result?.status!=='declined')throw Error(result?.error||result?.message||'Discard was not confirmed.');
 await refreshWatcher();await refreshApprovals();return result;
};



// APP-AGENTS: the existing authenticated owner dispatches these physical adapters.
for(const fn of ['getAgentChannel','installAgentChannel','previewAgentChannel','repairAgentChannel','listAgentSessions','getDesktopCompanion']) {
 api[fn]=async(...args)=>{
  const response=await request('/api/universal/workshop',{action:'agent-channel',function:fn,args});
  return response.result;
 };
}
// WIRE-agents: extend this API registry; all writes use existing authenticated owners.
async function refreshAgentSurface() {
 await api.refreshRouter();
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const [surface, metadata] = await Promise.all([workshop('getAgentSurface'),workshop('getGraphMetadata')]);
 if(epoch!==scopeEpoch || binding!==JSON.stringify(workshopBinding()))return null;
 if(surface?.ok===false || metadata?.ok===false)throw Error(surface.message || metadata.message);
 const {learning,...values}=surface;
 delete values.agentProfiles;
 const {agents:agentProfiles}=await request('/api/router/settings',{});
 publish({...values,learning:{...state.learning,...learning,layers:{...state.learning.layers,...learning.layers}},
  providers:state.providers.map(p=>({...p,...agentProfiles[p.id]})),graph:{...state.graph,...metadata}});
 return surface;
}
for(const wireMethod of ['setTaskPlanMode','setIntakeRule',
 'setOnboarding','reviewBrainLink','setSourceEvidence','setLearningLayer','setPinnedOutput','setNodeRunPolicy','verifyOutputStamp']) {
 api[wireMethod]=async(...args)=>{const result=await workshop(wireMethod,args);if(result?.ok===false)throw Error(result.message||result.error);if(!sessionDocument){await commands.load();project();}else projectFile();await refreshTasks();await refreshAgentSurface();return result;};
}
function rememberTask(result, select=true){
 if(!result||!result.taskId)return result;
 const session={taskId:result.taskId,path:result.path||'',sessionId:result.id||'',scope:result.scope,rules:result.rules||[],agents:result.agents||[],plan:result.plan||[],
  progress:result.progress||{},workflow:result.workflow||[],activity:result.activity||[],parameters:result.parameters||[],fileMessages:result.messages||[],
  folders:result.folders||[],references:result.references||[],workspace:result.workspace||'',homePinned:result.homePinned===true,pinnedMessages:result.pinnedMessages||[]};
 const tasks=state.tasks.map(t=>t.id===result.taskId?{...t,...session,sessionPath:session.path,sessionOpen:select?true:Boolean(t.sessionOpen)}
  :(select?{...t,sessionOpen:Boolean(t.sessionPath&&session.path&&t.sessionPath===session.path)}:t));
 publish(select?{focusedTask:result.taskId,tasks}:{tasks});
 return session;
}
api.createTask=async(title,agent='',workspace=state.activeWorkspace||'',parent='',canvasTask='')=>{const result=await workshop('createTask',canvasTask?[title,agent,workspace,parent,canvasTask]:parent?[title,agent,workspace,parent]:[title,agent,workspace]);if(!result||result.ok===false)throw Error(result?.message||result?.error||'The task was not created.');await refreshTasks();return {...result,...rememberTask(result)};};
api.renameTask=async(id,title)=>{const result=await taskFileAction('renameTask',id,title);await refreshTasks(false);return result;};
async function taskFileAction(method,id,...args){
 const navigation=fileNavigation;
 if(sessionDocument)await flushAutosave();
 // The flush snapshot: a canvas edit made while the task write is in flight stays.
 const sent=sessionDocument?portableDocument():null, text=sent?JSON.stringify(sent):'';
 const path=state.tasks.find(task=>task.id===id)?.sessionPath;
 const result=await workshop(method,[id,...args]);if(!result||result.ok===false)throw Error(result?.message||result?.error||'This task session was not saved.');
 const target=result.taskId?result.path:path;
 const unchanged=()=>navigation===fileNavigation&&target&&sessionDocument&&sessionPath===target&&sent&&sessionDocument.id===sent.id&&JSON.stringify(portableDocument())===text;
 if(unchanged()){
  const read=await sessionRequest('read',{path:target,id:sent.id});
  if(unchanged()&&read?.document){sessionDocument=copy(read.document);sessionRevision=read.revision||read.document.properties?.revision||0;localDirty=false;projectFile();}
 }
 return {...result,...rememberTask(result,false)};
}
api.setTaskSession=async(id,values)=>{
 const result=await taskFileAction('setTaskSession',id,values);
 if(Object.hasOwn(values,'rules')&&sessionDocument?.properties?.taskContext?.task===id){
  const changed=sessionDocument.nodes.filter(node=>node.fixed&&node.type==='thing.workshop').map(node=>node.id);
  if(changed.length)scheduleSolve(changed,null);
 }
 return result;
};
api.pinTaskMessage=(id,message,pinned)=>taskFileAction('pinTaskMessage',id,message,pinned);
api.attachMeetingNotes=async(id,text)=>{const result=await workshop('attachMeetingNotes',[id,text]);if(!result||result.ok===false)throw Error(result?.error||'Meeting notes were not attached.');await refreshTasks(false);return result;};
for(const method of ['checkpointTask','restoreTaskCheckpoint','joinLegacyChild','restoreLegacyChild'])api[method]=async(id,...args)=>{const result=await taskFileAction(method,id,...args);await refreshTasks(false);return result;};
let openingTask=null;
api.openTaskGraph=id=>{
 if(openingTask?.id===id)return openingTask.promise;
 const held={id,promise:null};
 held.promise=(async()=>{
  try{
   const result=await workshop('openTaskGraph',[id]);
   if(openingTask!==held)return {cancelled:true};
   if(!result||result.ok===false)throw Error(result?.message||result?.error||'This task has no session file.');
   const opened=await api.selectGraph(result.path||result.id);
   return openingTask===held?{...opened,...rememberTask(result)}:{cancelled:true};
  }finally{if(openingTask===held)openingTask=null;}
 })();
 openingTask=held;
 return held.promise;
};
api.refreshOfficeAwareness=async()=>{const rows=await workshop('refreshOfficeAwareness');if(!Array.isArray(rows))throw Error(rows?.message||'Office task read failed; retry.');publish({officeItems:rows,officeUpdated:'Read from current Workshop'});return rows;};


api.setGraphThumbnail=async file=>{
 if(!file || !['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>40000)throw Error('Choose a PNG, JPEG or WebP thumbnail smaller than 40 KB.');
 const thumbnail=await new Promise((resolve,reject)=>{const reader=new window.FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Could not read thumbnail. Choose the file again.'));reader.readAsDataURL(file);});
 return api.updateGraph(state.graph.id,{thumbnail});
};
api.getNodeParameters=node=>copy(state.graph.nodes.find(n=>n.id===(typeof node==='string'?node:node?.id))?.parameterSchema||[]);
api.getNodeOutput=async id=>{
 const node=state.graph.nodes.find(n=>n.id===id);if(!node)throw Error('Node disappeared. Open it again from the canvas.');
 let output=node.output;
 if(node.pinned && node.params.pinned_output!==undefined)output=JSON.parse(node.params.pinned_output);
 const rows=Array.isArray(output)?output:output==null?[]:[output];
 const fields=[...new Set(rows.flatMap(row=>row&&typeof row==='object'?Object.keys(row):['value']))];
 return {rows:rows.map(row=>row&&typeof row==='object'?row:{value:row}),json:JSON.stringify(output??[],null,2),
  schema:fields.map(name=>({name,type:[...new Set(rows.map(row=>typeof (row&&typeof row==='object'?row[name]:row)))].join(' | ')}))};
};
api.setMultipleNodeParameters=async(ids,key,value)=>{
 if(!Array.isArray(ids)||!ids.length)throw Error('Select at least one node.');
 const nodes=ids.map(id=>state.graph.nodes.find(n=>n.id===id));
 if(nodes.some(n=>!n||!Object.hasOwn(n.params,key)))throw Error('Selection changed. Reselect nodes with this shared parameter.');
 const changed=[];
 const restore=async error=>{
  const failures=[];
  for(const node of changed.reverse())await api.setNodeParam(node.id,key,node.params[key]).catch(reason=>failures.push(reason.message));
  throw Error(error.message+(failures.length?' Rollback failed: '+failures.join('; '):' Earlier edits were rolled back.'));
 };
 for(const node of nodes){
  const result=await api.setNodeParam(node.id,key,value).catch(restore);
  if(result?.ok===false)return restore(Error(result.message));
  changed.push(node);
 }
 return changed;
};
async function refreshBrain() {
 let result=await request('/api/universal/brain-export',{});
 if(result.facts?.held>result.facts?.total)result=await request('/api/universal/brain-export',{limit:result.facts.held});
 if(result.facts?.held>result.facts?.total)throw Error('Brain export is incomplete. Narrow the selected memory scope before exporting.');
 const brain=(result.facts?.folders||[]).flatMap(folder=>folder.facts.map(f=>({id:f.id,text:f.body||f.desc||f.name,source:folder.label,scope:'User',kind:f.kind})));
 if(!Array.isArray(result.facts?.folders))throw Error('Brain export was malformed. Retry the Brain read.');
 publish({brain});return brain;
}
for(const [brainMethod,path] of [['forgetMemory','brain-forget'],['editMemory','brain-edit'],['remember','brain-remember']]) {
 api[brainMethod]=async(...args)=>{const body=brainMethod==='remember'?{text:args[0]}:{id:args[0],...(brainMethod==='editMemory'?{text:args[1]}:{})};const result=await request('/api/universal/'+path,body);await refreshBrain();return result;};
}
api.refreshBrain=refreshBrain;
api.getKnowledgeGraph=()=>({nodes:state.brain.map((r,i)=>({id:r.id,label:r.text,type:r.kind==='mandate'?'Preference':'Memory',x:90+(i%5)*160,y:85+Math.floor(i/5)*100})),edges:[]});
const exportOwned=api.exportData;
api.exportData=async(name,id)=>{
 if(name==='Brain')return {name:'Brain.json',type:'application/json',content:JSON.stringify(await refreshBrain(),null,2)};
 if(name==='Results' && id){
  const output=await api.getNodeOutput(id);if(!output.rows.length)throw Error('Run this node before exporting its result.');
  const columns=[...new Set(output.rows.flatMap(row=>Object.keys(row)))];
  const cell=value=>'"'+String(typeof value==='object'?JSON.stringify(value):value??'').replaceAll('"','""')+'"';
  return {name:'Results.csv',type:'text/csv',content:[columns,...output.rows.map(row=>columns.map(key=>row[key]))].map(row=>row.map(cell).join(',')).join('\r\n')};
 }
 return exportOwned(name,id);
};
api.refreshAgentSurface=refreshAgentSurface;
// WIRE-agents end.
// WIRE-agents: compiler declarations resolve the same executable API registry.
const WIRE_ACTIONS = {
 "setAgentProfile": "api.setAgentProfile",
 "setTaskDelegate": "api.setTaskDelegate",
 "checkpointTask": "api.checkpointTask",
 "restoreTaskCheckpoint": "api.restoreTaskCheckpoint",
 "queueTaskMessage": "api.queueTaskMessage",
 "settleQueuedMessage": "api.settleQueuedMessage",
 "setPinnedOutput": "api.setPinnedOutput",
 "runNode": "api.runNode",
 "setNodeFlags": {"handler":"api.setNodeFlags"},
 "ui.download": "u.download",
 "ui.show": "u.show",
 "setHostSkillEnabled": "api.setHostSkillEnabled",
 "auditHostSkill": "api.auditHostSkill",
 "addNode": "api.addNode",
 "ui.go": "u.go",
 "setNodeParam": "api.setNodeParam",
 "setSourceEvidence": "api.setSourceEvidence",
 "inspectConnectorBundle": "api.inspectConnectorBundle",
 "configureConnectorBundle": "api.configureConnectorBundle",
 "installConnectorBundle": "api.installConnectorBundle",
 "setMultipleNodeParameters": "api.setMultipleNodeParameters",
 "setLearningLayer": "api.setLearningLayer",
 "setScheduleResponsibility": "api.setScheduleResponsibility",
 "reviewScheduledWork": "api.reviewScheduledWork",
 "ui.setSelectedNodeId": "u.setSelectedNodeId",
 "setTaskPlanMode": "api.setTaskPlanMode",
 "addTaskReview": "api.addTaskReview",
 "resolveTaskReview": "api.resolveTaskReview",
 "steerTask": "api.steerTask",
 "refreshOfficeAwareness": "api.refreshOfficeAwareness",
 "updateGraph": "api.updateGraph",
 "setGraphThumbnail": "api.setGraphThumbnail",
 "setIntakeRule": "api.setIntakeRule",
 "reviewBrainLink": "api.reviewBrainLink",
 "setOnboarding": "api.setOnboarding",
 "correctAnswerSource": "api.correctAnswerSource",
 "setTranscriptPass": "api.setTranscriptPass",
 "setApprovalRubric": "api.setApprovalRubric",
 "verifyOutputStamp": "api.verifyOutputStamp",
 "setResearchReview": "api.setResearchReview",
 "ui.close": "u.close",
 "setNodeRunPolicy": "api.setNodeRunPolicy",
 "setTaskStatus": "api.setTaskStatus",
 "ui.setTask": "u.setTask",
 "openTaskGraph": "api.openTaskGraph",
 "listWorkshopMessages": "api.listWorkshopMessages",
 "reassignTask": "api.reassignTask",
 "ui.schedule": "u.schedule",
 "ui.confirm": "u.confirm",
 "getAgentChannel": "api.getAgentChannel",
 "installAgentChannel": "api.installAgentChannel",
 "previewAgentChannel": "api.previewAgentChannel",
 "repairAgentChannel": "api.repairAgentChannel",
 "listAgentSessions": "api.listAgentSessions",
 "ui.state": "u.state",
 "ui.retry": "u.retry",
 "ui.fit": "u.fit",
 "ui.select": "u.select",
 "ui.chooseBundle": "u.chooseBundle"
};
api.executeAction=(id, context, ...args)=>{
 const handler=typeof WIRE_ACTIONS[id]==='string'?WIRE_ACTIONS[id]:WIRE_ACTIONS[id]?.handler;if(!handler)throw Error('Unknown action '+id);
 if(id==='ui.state' || id==='ui.select')return context(...args);
 if(id==='ui.retry')return context?.();
 if(id==='ui.fit'){context.setZoom(1);context.setPan({x:0,y:0});context.setFocus(null);return;}
 if(id==='ui.chooseBundle')return context.current.click();
 if(handler.startsWith('u.'))return context[handler.slice(2)](...args);
 const run=()=>{const fn=api[handler.slice(4)];if(typeof fn!=='function')throw Error('Action owner missing: '+id);return fn(...args);};
 return context.act(run);
};
// WIRE-agents end.
// WIRE-social: data operations remain on the same authenticated transport and graph.
let socialTail=Promise.resolve();
function socialOperation(op,args=[]) {
 const epoch=scopeEpoch;
 const run=async()=>{
  if(epoch!==scopeEpoch)throw Error('The graph changed. Return to the intended graph and retry.');
  const response=await request('/api/universal/social-surface',{op,args});
  if(epoch===scopeEpoch){publish(response.state);const research=response.state.social?.research?.at(-1);if(research)projectResearch(research);}
  return response.result;
 };
 const result=socialTail.then(run);socialTail=result.catch(error=>{notice(error.message);});return result;
}
const socialOperations={refreshSocialState:'get_state',updateOfficePage:'update_office_page',
 saveSocialDraft:'save_social_draft',discardSocialDraft:'discard_social_draft',readSocialMessage:'read_social_message',
 replySocialMessage:'reply_social_message',triageSocialInbox:'triage_social_inbox',readWhatsappInbox:'read_whatsapp_inbox',setSocialGroupRule:'set_social_group_rule',
 setSocialDigest:'set_social_digest',generateSocialDigest:'generate_social_digest',addSlide:'add_slide',editSlide:'edit_slide',
 removeSlide:'remove_slide',reorderSlide:'reorder_slide',setPrototype:'set_prototype',rebaselinePrototype:'rebaseline_prototype',
 checkVerdictPattern:'check_verdict_pattern',setMeeting:'set_meeting',setMeetingActionOwner:'set_meeting_action_owner'};
for(const [socialFunction,operation] of Object.entries(socialOperations))api[socialFunction]=(...args)=>socialOperation(operation,args);
api.readContentSource=({kind,url})=>socialOperation('read_content_source',[kind,url]);
api.refreshModelRoster=async()=>{await refreshSettingsControls(true);const rows=await api.listProviders();publish({modelNotice:rows.length+' providers returned by the live provider owner.'});return rows;};
api.createMeetingTask=async index=>{
 const meeting=state.meeting,held=meeting.actionTasks?.[index];
 if(held){await refreshTasks();const existing=state.tasks.find(t=>t.id===held);if(existing)return existing;throw Error('The linked task needs reconciliation in the Workshop.');}
 if(!meeting.actions[index]||!meeting.actionOwners?.[index])throw Error('Choose an owned meeting action first.');
 const task=await socialWork('Meeting '+meeting.calendarId+' action '+index+': '+meeting.actions[index]+'\nOwner: '+meeting.actionOwners[index]);
 if(!task?.id||task.ok===false)throw Error(task?.message||'The Workshop did not confirm a task. Open the Workshop and retry.');
 await socialOperation('bind_meeting_task',[index,task.id]);return task;
};
async function socialWork(description,options={}) {
 const binding=workshopBinding();if(!binding)throw Error('Open the Workshop for this graph, then retry.');
 const digest=await window.crypto.subtle.digest('SHA-256',new TextEncoder().encode(description+JSON.stringify(options)));
 const request_id='social:'+Array.from(new window.Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
 const response=await request('/api/universal/workshop',{action:'data-api',function:'sendToBaboom',args:[description,options],...binding,request_id});
 const task=response.result;
 if(!task?.id||task.ok===false)throw Error(task?.message||'The Workshop did not accept this work. Open the Workshop and retry.');
 await refreshTasks();return task;
}
api.proposeSocialDraft=async id=>{
 const draft=state.social.drafts.find(row=>row.id===id);if(!draft)throw Error('Choose a saved draft.');
 return socialWork('Review this saved social draft and prepare its existing social.work_prepare approval. Do not publish without the existing approval. Draft '+id+'\n'+JSON.stringify(draft));
};
api.prepareTutorial=values=>socialWork('Prepare a tutorial recording, captions and private upload for review through the existing video and social tools. Report actual artifacts; do not claim completion before recording.\n'+JSON.stringify(values));
api.readYoutubeData=(source,operation)=>socialWork('Read YouTube '+operation+' from the actual connected YouTube source and return source-attributed data. Source: '+source);
// Settings › Agents › Meetings: which meetings he joins, his name, language, when he speaks and the pause he waits for.
const meetingRules=()=>'\nMeeting settings: '+JSON.stringify(Object.fromEntries(state.settings.filter(row=>row.id.startsWith('Agents.')&&row.group==='Meetings').map(row=>[row.label,row.value])));
api.joinMeeting=async()=>{
 const m=state.meeting;if(!m.calendarId||!m.platform||!m.agent)throw Error('Choose a calendar meeting, program and connected agent.');
 return socialWork('Join the selected meeting using the connected meeting program. Report the actual join result; no invented presence.\n'+JSON.stringify(m)+meetingRules(),{provider:m.agent});
};
api.startMeetingTranscript=()=>{
 if(!state.meeting.consent)throw Error('Record everyone’s transcript consent first.');
 return socialWork('Start the consented transcript for this selected meeting using its actual capture source. Return attributed transcript turns and capture status.\n'+JSON.stringify(state.meeting)+meetingRules(),{provider:state.meeting.agent});
};
api.stopMeetingTranscript=()=>socialWork('Stop actual transcript capture for this selected meeting and confirm capture stopped.\n'+JSON.stringify(state.meeting),{provider:state.meeting.agent});
api.readMeetingTranscript=()=>socialOperation('get_state').then(data=>data.meeting.transcript);
api.proposeMeetingSummary=()=>{
 if(!state.meeting.transcript.length)throw Error('Read a captured transcript before preparing a summary.');
 return socialWork('Prepare a source-backed meeting summary for the existing approval owner. Do not send it without approval.\n'+JSON.stringify(state.meeting)+meetingRules());
};
const exportBeforeSocial=api.exportData;
api.exportData=async(name,id)=>{
 if(name==='Presentation')return {name:'Presentation.json',type:'application/json',content:JSON.stringify(state.presentation,null,2)};
 if(name==='Captions'){
  const row=state.social.tutorials.find(t=>t.id===id);if(!row?.captions)throw Error('Choose a recorded tutorial with actual captions before exporting.');
  return {name:'Captions.vtt',type:'text/vtt',content:row.captions};
 }
 return exportBeforeSocial(name,id);
};
api.importMeetingCalendar=async()=>{
 const picked=await request('/api/universal/pick-file',{title:'Read calendar meeting',filter:'Calendar (*.ics)'});
 if(!picked.path)return null;return socialOperation('import_meeting_calendar',[picked.path]);
};
api.importMeetingTranscript=async()=>{
 const picked=await request('/api/universal/pick-file',{title:'Read captured transcript',filter:'Transcript (*.vtt *.srt *.txt)'});
 if(!picked.path)return null;return socialOperation('import_meeting_transcript',[picked.path]);
};
api.refreshSocialMemory=refreshBrain;
api.setSourceReadSeconds=seconds=>socialOperation('set_source_read_seconds',[seconds]);
async function refreshSettingsControls(refreshModels=false){
 const result=await settingsAction('readControls',[refreshModels]);projectProviders();return result;
}
let notificationsListed=false;
async function refreshNotifications(){
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding()),generation=notificationGeneration;
 const result=await workshop('listNotifications');
 if(generation===notificationGeneration&&epoch===scopeEpoch&&binding===JSON.stringify(workshopBinding())&&Array.isArray(result?.notifications)){
  // The first read after launch lists what is already there; only later arrivals are announced.
  const seen=new Set((state.notifications||[]).map(n=>n.id)),fresh=notificationsListed?result.notifications.filter(n=>!n.read&&!seen.has(n.id)):[];
  notificationsListed=true;
  publish({notifications:result.notifications});
  if(fresh.length)announceNotifications(fresh);
 }
 return result;
}
// Settings › Connections › Notifications: Windows notifications and Sound for notices that arrive while the app runs.
function announceNotifications(fresh){
 const on=label=>state.settings.find(row=>row.id==='Connections.'+label)?.value===true;
 if(on('Windows notifications')&&window.Notification){
  const send=()=>fresh.slice(0,3).forEach(n=>new window.Notification('ArchHub',{body:n.text,tag:n.id}));
  if(window.Notification.permission==='granted')send();else if(window.Notification.permission==='default')window.Notification.requestPermission().then(p=>{if(p==='granted')send();});
 }
 if(on('Sound')&&window.AudioContext){
  const audio=new window.AudioContext(),tone=audio.createOscillator(),gain=audio.createGain();
  tone.frequency.value=880;gain.gain.setValueAtTime(0.08,audio.currentTime);gain.gain.exponentialRampToValueAtTime(0.0001,audio.currentTime+0.25);
  tone.connect(gain).connect(audio.destination);tone.start();tone.stop(audio.currentTime+0.25);tone.onended=()=>audio.close();
 }
}
api.readNotification=async id=>{
 notificationGeneration++;
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const result=await workshop('readNotification',[id]);
 if(!result?.receipt||!Array.isArray(result.notifications))throw Error('Notification read was not confirmed. Refresh and retry.');
 if(epoch===scopeEpoch&&binding===JSON.stringify(workshopBinding()))publish({notifications:result.notifications});
 return result;
};
api.refreshSettingsControls=refreshSettingsControls;
api.setKeybinding=(id,chord,destination=state.settingsDestination)=>settingsAction('setKeybinding',[id,chord],destination);
api.resetKeybindings=(destination=state.settingsDestination)=>settingsAction('resetKeybindings',[],destination);
api.exposeSettingsPage=async page=>{
 const epoch=scopeEpoch;
 const result=await settingsAction('exposeSettingsPage',[page]);
 if(epoch!==scopeEpoch)throw Error('The graph changed. Open Settings again.');
 if(window.ARCHHUB_BOOT?.nograph){
  fileEdit(d=>{for(const node of result.nodes)if(!d.nodes.some(n=>n.type==='thing.setting'&&n.params.setting===node.params.setting))d.nodes.push(node);},result.nodes.map(n=>n.id));
 }else{await commands.load();project();}
 return state.graph.nodes.find(n=>n.id===result.id)||result;
};
// Which chat agents this PC can START, asked of the server each time a Recipient menu opens (it looks on PATH, starts nothing).
// One answer for the Home, Canvas and Workshop pickers: state.chatAgents = {status: waiting|loaded|error, rows, error}.
api.listChatAgents=async()=>{
 if(state.chatAgents?.status==='waiting')return state.chatAgents;
 publish({chatAgents:{status:'waiting',rows:state.chatAgents?.rows||[],error:''}});
 try{const result=await request('/api/router/chat-agents');publish({chatAgents:{status:'loaded',rows:Array.isArray(result.agents)?result.agents:[],error:''}});}
 catch(error){publish({chatAgents:{status:'error',rows:[],error:error.message||'The check did not answer.'}});}
 return state.chatAgents;
};
api.apiRouterChat=(prompt,agent,replyTo,task)=>routerChat(prompt,agent,replyTo,task,false);
// One composer turn from window.UI.chatTurn. A thread remembers the chat agent that answered in it (state.chatThreads,
// and after a restart its last answer's sender), so the next message continues that chat (continue=true). When
// the server says that chat has ended, the thread is marked ended (state.chatEnded) and nothing else is sent.
api.sendChatTurn=async(turn,replyTo,task)=>{
 const key=task||'';
 try{
  const result=await routerChat(turn.prompt,turn.agent,replyTo,task,turn.taskPeer?{task_peer:true}:turn.resume?{continue:true}:turn.fresh?{fresh:true}:{});
  if(turn.agent!=='BABOOM')publish({chatThreads:{...state.chatThreads,[key]:turn.agent},chatEnded:{...state.chatEnded,[key]:''}});
  return result;
 }catch(error){
  if(turn.resume&&/chat in this thread has ended/.test(error.message||''))publish({chatThreads:{...state.chatThreads,[key]:''},chatEnded:{...state.chatEnded,[key]:turn.agent}});
  throw error;
 }
};  // replyTo: the Workshop message this answers; task: the session thread it belongs to
function documentationTutorials(rows){return rows.map(d=>({id:d.id,category:d.id.startsWith('tutorial-')?'Tutorial':'Guide',title:d.title,summary:d.description||'',steps:String(d.text||'').split(/\n+/).map(line=>line.trim()).filter(Boolean),route:({'getting-started':'home','composer-canvas':'canvas','brain':'brain','connectors':'watcher','account-web':'settings/Account','workshop':'workshop','tasks':'workshop','approvals':'settings/Hooks','routines':'canvas'})[d.id]||'canvas',bookSource:'ArchHub documentation'}));}
api.refreshDocs=async()=>{
 const result=await request('/api/documentation');
 if(!Array.isArray(result.tutorials)||!Array.isArray(result.glossary))throw Error('Documentation could not be read. Retry the guide.');
 const docs=documentationTutorials(result.tutorials);
 publish({docs,bookGlossary:result.glossary.map(entry=>`| ${entry.term} | ${entry.definition} |`)});
 return docs;
};
api.refreshRouter=async(refreshCatalogue=false)=>{const result=await request('/api/router/settings'+(refreshCatalogue?'?refresh_catalogue=1':''),{});publish({router:result,providerPreferences:result.providerPreferences,providers:state.providers.map(p=>({...p,...result.agents[p.id]}))});return result;};
api.setRouterSettings=async values=>{await request('/api/router/settings',values);return api.refreshRouter();};
api.setProviderModel=async(id,model)=>{const current=await api.refreshRouter();return api.setRouterSettings({default_model:model,providerPreferences:{...current.providerPreferences,[id]:model}});};
api.setAgentProfile=async(id,values)=>{const current=await api.refreshRouter();return api.setRouterSettings({agents:{...current.agents,[id]:{...current.agents[id],...values}}});};
api.disconnectSecret=async id=>{const result=await settingsAction('disconnectSecret',[id]);await refreshSocialConnections();return result;};
api.setCompanionState=values=>settingsAction('setCompanionState',[values]);
api.readPermissions=()=>settingsAction('readPermissions');
api.readHookDrift=()=>settingsAction('readHookDrift');
api.readHostEffects=()=>settingsAction('readHostEffects');
api.setHostEffect=(key,on)=>settingsAction('setHostEffect',[key,on]);
api.acceptHookDrift=()=>settingsAction('acceptHookDrift');
api.hostPrograms=()=>settingsAction('hostPrograms');
api.hostProgramState=host=>settingsAction('hostProgramState',[host]);
api.connectorActions=connector=>settingsAction('connectorActions',[connector]);
api.connectorPreview=(connector,action,args)=>settingsAction('connectorPreview',[{connector,action,args}]);
api.setPermissions=values=>settingsAction('setPermissions',[values]);
api.openProgram=id=>settingsAction('openProgram',[id]);
async function refreshSocialConnections(){
 const identity=state.profile.id,epoch=scopeEpoch;
 const data=await request('/api/universal/social-connections');
 if(!Array.isArray(data.items))throw Error('The connection owner did not return accounts. Open Connections and retry.');
 if(identity!==state.profile.id||epoch!==scopeEpoch)return state.connections;
 const connections=data.items.map(row=>({...row,id:row.provider,connected:row.state==='connected'}));
 publish({connections});return connections;
}
api.refreshSocialConnections=refreshSocialConnections;
const setConnectionBeforeSocial=api.setConnection;
api.setConnection=async(id,values)=>{
 if(id==='youtube')return api.signIn(true);
 let result;
 const current=state.connections.find(row=>row.id===id);
 if(values.connected===false&&current?.connected){
  if(!current.vault_entry||!current.account_id||!current.custody_provider)throw Error('Refresh Connections before disconnecting this account.');
  result=await request('/api/universal/social-credential-remove',{provider:current.custody_provider,account_id:current.account_id,vault_entry:current.vault_entry});
 }else if(values.connected===true){
  const observed=await request('/api/universal/social-connection?provider='+encodeURIComponent(id));
  const row=observed.connection;
  if(row?.state==='ready')result=await request('/api/universal/social-connection',{provider:id,action:'finish'});
  else if(['connecting','choosing'].includes(row?.state))result=observed;
  else result=await setConnectionBeforeSocial(id,values);
 }else result=await setConnectionBeforeSocial(id,values);
 await refreshSocialConnections();
 return {...result,status:result.connection?.state,message:result.connection?.blocker||result.error||''};
};
api.finishSocialConnection=async(provider,account_id)=>{
 const result=await request('/api/universal/social-connection',{provider,action:'finish',account_id});
 await refreshSocialConnections();return {...result,status:result.connection?.state};
};
api.checkConnection=async id=>{const result=await request('/api/universal/social-connection?provider='+encodeURIComponent(id));await refreshSocialConnections();return {...result,status:result.connection?.state,message:result.connection?.blocker||''};};
const checkMeasuredPattern=api.checkVerdictPattern;
api.checkVerdictPattern=()=>state.prototype.linkedModel
 ? socialWork('Inspect the reference deviation using the configured linked model and these actual supplied measurements. Return evidence and uncertainty; never invent approved samples.\n'+JSON.stringify(state.prototype))
 : checkMeasuredPattern();
const refreshBeforeSocialConnections=api.refreshSocialState;
api.refreshSocialState=async()=>{const result=await refreshBeforeSocialConnections();await refreshSocialConnections();return result;};
// WIRE-social end
// WIRE-settings
const CONTROL_KEYS=['keybindings','keyboardCommands','keyboardError','firms','activeFirm','people','billing','dependencies','officeInvitations','settingsScope','settingsScopes','settingsDestination','settingsScopeNotice','activeWorkspace','devices','activeDevice','deviceNotice','backups','companion','secrets','providerPreferences','providerModels','libraryCollapsed','libraryCategories','libraryTree','sessionListFilters','homeLayout','dockLayout'];
async function settingsAction(functionName, args=[], destination=state.settingsDestination) {
 const identity=state.profile.id;
 const graph=state.graph.id;
 const sessionWrite=state.settingsScope==='Session'&&['setAppearance','resetAppearance','setKeybinding','resetKeybindings','importPreferences','resetPreferences'].includes(functionName);
 if(sessionWrite){await flushAutosave();if(graph!==state.graph.id)throw Error('The session changed. Retry this settings edit.');}
 const preferenceRead=['readPreferences','readEffectivePreferences'].includes(functionName);
 const preferenceEpoch=preferenceGeneration;
 const preferenceWrite=['setAppearance','resetAppearance','setKeybinding','resetKeybindings','setSettingsScope','importPreferences','resetPreferences'].includes(functionName);
 if(preferenceWrite)preferenceGeneration++;
 const generation=functionName==='readControls'?controlsGeneration:++controlsGeneration;
 const response=await request('/api/universal/settings-action',{function:functionName,args,context:{session:state.graph.id,surface:activeSurface,settingsDestination:destination}}).catch(error=>{if(error.response?.code==='settings_destination_changed')publish({settingsDestination:null,settingsScopeNotice:error.message});throw error;}).finally(()=>{if(preferenceWrite)preferenceGeneration++;});
 let result=response.result;
 if(identity!==state.profile.id)throw Error('Your account changed while this action ran. Refresh the page before retrying.');
 if(!result||typeof result!=='object'||Array.isArray(result)||result.ok===false)throw Error(result?.error||result?.message||'Settings owner did not confirm the action. Refresh and retry.');
 // A newer write answered for what it changed; what nothing has loaded yet (the dock layout at boot, say) still comes from this read,
 // or a write during the boot read would leave that owner unread and its screen on defaults until the next restart.
 if(preferenceRead&&preferenceEpoch!==preferenceGeneration)return result;
 if(!preferenceWrite&&preferenceEpoch!==preferenceGeneration){
  result={...result};
  for(const key of ['appearanceSettings','keybindings','keyboardCommands','keyboardError','settingsScope','settingsScopes','settingsDestination','settingsScopeNotice','activeWorkspace'])delete result[key];
 }
 if(['readControls','readKeybindings'].includes(functionName)&&generation!==controlsGeneration){
  const missing=Object.fromEntries(CONTROL_KEYS.filter(key=>Object.hasOwn(result,key)&&state[key]===undefined).map(key=>[key,result[key]]));
  const unread=Array.isArray(result.appearanceSettings)?result.appearanceSettings.filter(row=>!state.settings.some(held=>held.id===row.id)):[];
  if(unread.length)missing.settings=[...state.settings,...unread];  // a setting no write has answered for yet (the Inspector width, say)
  if(Object.keys(missing).length)publish(missing);
  return result;
 }
 if(['readOperations','setGraphWorkspaces','readPreferences','readEffectivePreferences','setAppearance','resetAppearance','setKeybinding','resetKeybindings','setSettingsScope','importPreferences','resetPreferences'].includes(functionName)&&graph!==state.graph.id)throw Error('The graph changed while Settings ran. Refresh Settings before retrying.');
 const values={};
 if(Array.isArray(result.appearanceSettings)){
  const ids=new Set(result.appearanceSettings.map(row=>row.id));
  values.settings=withPending([...state.settings.filter(row=>!ids.has(row.id)),...result.appearanceSettings]);
  values.libraryPorts=(state.libraryPorts||[]).map(item=>item.setting?{...item,setting:result.appearanceSettings.find(row=>row.id===item.setting.id)||item.setting}:item);
 }

 if(Object.hasOwn(result,'accountChecking'))values.profile={...state.profile,checking:result.accountChecking};
 for(const key of CONTROL_KEYS)if(Object.hasOwn(result,key)&&!(functionName==='readOperations'&&key==='dependencies'&&Array.isArray(result.dependencies)&&!result.dependencies.length&&state.dependencies?.length))values[key]=result[key];
 if(result.controlErrors){
  values.controlErrors={...state.controlErrors};
  for(const key of functionName==='read'?['officeInvitations']:['secrets','providerModels'])delete values.controlErrors[key];
  Object.assign(values.controlErrors,result.controlErrors);
 }
 if(result.workspacePolicies)values.workspaces=state.workspaces.map(row=>({...row,...result.workspacePolicies[row.id]}));
 if(result.workspaceIds)values.graph={...state.graph,workspaceIds:result.workspaceIds};
 if(result.profile){settingsProfile={...settingsProfile,...Object.fromEntries(Object.entries(result.profile).filter(([key])=>['name','firm','plan','role','photo','presence'].includes(key)))};values.profile={...(values.profile||state.profile),...settingsProfile};}
 const shownSettings=state.settings;
 publish(values);
 if(sessionWrite)await pollFile();
 // The canvas re-projects only when an appearance value really changed, not on every Settings read.
 if(result.appearanceSettings&&sessionDocument&&state.settings!==shownSettings)projectFile();
 if(result.controlErrors&&Object.keys(result.controlErrors).length)notice(Object.values(result.controlErrors).join(' '));
 if(result.message)notice(result.message);
 if(result.open_url){
  const url=new URL(result.open_url);
  if(url.protocol!=='https:'||url.username||url.password)throw Error('Billing returned an unsafe browser destination. Refresh billing.');
  window.open(url.href,'_blank','noopener,noreferrer');
  notice('Continue in your browser, then refresh billing to confirm the result.');
 }
 return result;
}
for(const functionName of ['updateProfile','invitePerson','selectFirm','setTeamAccess','setBilling','refreshBilling','prepareCheckout','completeCheckout','retryPayment','downgradeBilling','manageDependency','ensureDependency','checkDependencies','acceptOfficeInvitation','declineOfficeInvitation','archiveActivity','setWorkspaceRules','selectDevice','grantAccess','backUpNow','rollBack']) {
 api[functionName]=(...args)=>settingsAction(functionName,args);
}
api.refreshSettingsOperations=()=>settingsAction('readOperations',[state.graph.id]);
// Settings › This PC › The app: backup place and folder, Back up now, Export diagnostics (settings_owner.maintenance_settings).
for(const functionName of ['readMaintenance','setMaintenance','exportDiagnostics','readWorkspaceAccess','setWorkspaceReadOnly'])api[functionName]=(...args)=>settingsAction(functionName,args);
api.readDevices=()=>settingsAction('readDevices');
api.setGraphWorkspaces=ids=>settingsAction('setGraphWorkspaces',[state.graph.id,ids]);
function setAppearance(id,value,destination=state.settingsDestination){
 const identity=state.profile.id;
 const held=pendingSettings.get(id)||{count:0};pendingSettings.set(id,{value,count:held.count+1});
 publish({settings:withPending(state.settings)});
 const settle=()=>{const now=pendingSettings.get(id);if(now&&--now.count<=0)pendingSettings.delete(id);};
 const admittedEpoch=accountEpoch;const write=appearanceWrites.then(()=>{if(admittedEpoch!==accountEpoch)throw desktopError();if(identity!==state.profile.id)throw Error('Your account changed. Retry this preference edit.');return settingsAction('setAppearance',[id,value],destination);});
 appearanceWrites=write.catch(()=>{});
 // A refused write puts the owner's value back (re-read), never the optimistic one.
 return write.then(result=>{settle();if(!pendingSettings.has(id)&&Array.isArray(result?.appearanceSettings))publish({settings:withPending(state.settings.map(row=>result.appearanceSettings.find(next=>next.id===row.id)||row))});return preferenceChanged(id,result);},
  async error=>{settle();if(!pendingSettings.has(id))await refreshSettingsControls().catch(()=>{});throw error;});
}
function preferenceChanged(id,result){
 const changed=(sessionDocument?.nodes||[]).filter(n=>n.type==='thing.setting'&&n.params.setting===id||id==='Projects.Working subfolder'&&n.type==='thing.session'&&!n.params?.project_folder||id==='Projects.BCF version'&&n.type==='daily.ifc_check_bcf'&&(n.params?.bcf_version==='From Projects'||Object.hasOwn(n.params||{},'bcf_version')&&!n.params.bcf_version)).map(n=>n.id);
 if(changed.length)scheduleSolve(changed,null);
 return result;
}
api.setInspectorWidth=value=>setAppearance('Appearance.Inspector width',value);
api.readCanvasTabs=()=>settingsAction('readCanvasTabs');
api.setCanvasTabs=value=>settingsAction('setCanvasTabs',[value]);
api.readSessionListFilters=()=>settingsAction('readSessionListFilters');
api.setSessionListFilter=(list,value)=>settingsAction('setSessionListFilter',[list,value]);
api.readHomeLayout=()=>settingsAction('readHomeLayout');
api.setHomeLayout=value=>settingsAction('setHomeLayout',[value]);
api.setDockLayout=(layout,saved)=>settingsAction('setDockLayout',saved===undefined?[layout]:[layout,saved]);  // the user's one dock layout, the same on Home and in every session
// The Workshop settings the update policy reads (one owner: settings/settings.json); the node parameter edits the same value.
const UPDATE_POLICY_KEYS=['update_check_interval_minutes','update_idle_minutes','update_auto_apply_on_quit','update_preview_channel','update_install_when_idle'];
api.getApplicationSettings=()=>settingsAction('readApplicationSettings',[]);
api.setApplicationSetting=async(key,value)=>{const saved=await settingsAction('setApplicationSetting',[key,value]);await refreshLiveUpdatePolicy();return saved;};
let settingsScopeRequests=0;
api.setSettingsScope=async(scope,destination=state.settingsDestination,workspace=destination?.workspace)=>{
 settingsScopeRequests++;publish({settingsScopePending:true});
 try{return await settingsAction('setSettingsScope',[scope,workspace??sessionDocument?.properties?.project??state.activeWorkspace??'',destination?.session??state.graph.id],destination);}
 finally{settingsScopeRequests--;publish({settingsScopePending:settingsScopeRequests>0});}
};
api.refreshPreferences=()=>settingsAction('readPreferences');
api.importPreferences=(payload,destination=state.settingsDestination)=>settingsAction('importPreferences',[payload],destination);
api.resetPreferences=(destination=state.settingsDestination)=>settingsAction('resetPreferences',[],destination);
const settingsListWorkspaces=api.listWorkspaces;
api.listWorkspaces=async()=>{await settingsListWorkspaces();if(state.profile.signedIn)await api.refreshSettingsOperations();return copy(state.workspaces);};


api.refreshSettingsAccount=()=>settingsAction('read');
api.getUsageSummary=()=>({'Remaining messages':state.billing.remainingMessages??'Sign in and refresh billing','Plan':state.profile.plan});
api.setAccountPlan=plan=>api.setBilling({requestedPlan:plan});
function capabilityOwner(id){
 const capability=state.capabilities.find(c=>c.id===id);
 const owners=state.graph.nodes.filter(n=>n.id===id||n.kind===id||n.kind===capability?.nodeKind||capability?.descriptor?.engine&&n.kind===capability.descriptor.engine);
 return owners.length===1?owners[0]:null;
}
api.getCapabilityState=id=>{const owner=capabilityOwner(id),capability=state.capabilities.find(c=>c.id===id);return owner?{...capability,name:capability?.name||owner.title,params:owner.params}:null;};
api.getCapabilityParameters=id=>copy((capabilityOwner(id)?.parameterSchema||[]).map(p=>
 p.dataType==='folder'||p.dataType==='path'?{...p,type:'path'}:p));
api.setCapabilityParameter=(id,key,value)=>{
 requireDesktop();
 const owner=capabilityOwner(id);
 if(!owner)throw Error('Open the capability node on its canvas and select one exact instance before editing its parameters.');
 return sessionDocument&&state.graph.id===sessionDocument.id?api.setNodeParam(owner.id,key,value):nodeProperty(owner.id,key,value);
};
api.pickCapabilityFolder=async(id,key)=>{
 const navigation=fileNavigation,ownerId=capabilityOwner(id)?.id;
 const result=await request('/api/universal/workspace-roots',{action:'browse'});
 if(!result.path)return {cancelled:true,message:'Folder selection cancelled'};
 if(navigation!==fileNavigation||!ownerId||capabilityOwner(id)?.id!==ownerId)throw Error('The selected capability changed. Select one exact instance and retry.');
 return api.setCapabilityParameter(id,key,result.path);
};
const settingsExport=api.exportData;
api.exportData=async(name,nodeId)=>{
 if(name==='Dependency logs')return {name:'Dependency-logs.json',type:'application/json',content:JSON.stringify(state.dependencies.map(({id,logs})=>({id,logs})),null,2)};
 if(name.startsWith('Invoice ')){const invoice=state.billing.invoices.find(i=>i.id===name.slice(8));if(!invoice?.content)throw Error('Refresh billing and open the invoice from your billing provider.');return {name:invoice.number+'.txt',type:'text/plain',content:invoice.content};}
 return settingsExport(name,nodeId);
};
const settingsAccountRefresh=refreshAccount;
let settingsAccountIdentity='',settingsProfile={},watchingIdentity='';
refreshAccount=async()=>{
 const profile=await settingsAccountRefresh();
 if(profile.id!==settingsAccountIdentity){
  settingsAccountIdentity=profile.id;settingsProfile={};
  publish({watching:undefined,profile:{...state.profile,firm:'',plan:''},firms:[],activeFirm:'',people:[],officeInvitations:[],controlErrors:{},settingsScope:'User',activeWorkspace:'',activeDevice:'',devices:[],backups:[],workspaces:[],graph:{...state.graph,workspaceIds:[]},billing:{status:'',requestedPlan:'',cycle:'',checkout:null,invoices:[],plans:[]}});
 }else if(profile.signedIn){publish({profile:{...state.profile,...settingsProfile}});}
 if(profile.signedIn)await api.refreshSettingsAccount().catch(error=>publish({connectionNotice:error.message}));
 // Shared-with-you count for Home: once per admitted account, in the background; an account switch reads again.
 if(profile.signedIn&&profile.id&&watchingIdentity!==profile.id){watchingIdentity=profile.id;void api.readWatching().catch(()=>{watchingIdentity='';});}
 if(!profile.signedIn)watchingIdentity='';
 return copy(state.profile);
};
api.syncAccount=async()=>{await refreshAccount();if(state.profile.signedIn){await api.refreshSettingsAccount();await api.listWorkspaces();void api.readWatchGrants().catch(()=>{});}return copy(state.profile);};
// Invite to watch (watch_grants.py through the Settings owner): capability, the owner's grants, invite and stop.
api.readWatchGrants=async()=>{const watch=await settingsAction('readWatchGrants');publish({watch});return watch;};
api.inviteWatcher=async(path,email,ends)=>{const result=await settingsAction('inviteWatcher',[path,email,ends]);void api.readWatchGrants().catch(()=>{});return result;};
api.stopWatcher=async id=>{const result=await settingsAction('stopWatcher',[id]);void api.readWatchGrants().catch(()=>{});return result;};
// The recipient side: sessions shared with this account, and one read-only view (no document, no Run, no Save).
api.readWatching=async()=>{const asked=settingsAccountIdentity,watching=await settingsAction('readWatching');if(asked===settingsAccountIdentity)publish({watching});return watching;};
api.readWatchedSession=id=>settingsAction('readWatchedSession',[id]);
// WIRE-settings end
// WIRE-rest
// Resolve the current graph's admitted commands; never guess an HTTP operation.
async function restCommand(name, args=[]) {
 await commands.load();project();
 const matches=(canvas.interaction_projection?.bindings||[]).filter(b=>b.control===name);
 if(matches.length!==1)throw Error(name+': select its owner node in System graph, expose the command, then retry. The current canvas returned '+matches.length+' admitted bindings.');
 const binding=matches[0];
 if(!['interaction','control','event'].every(key=>typeof binding[key]==='string'&&binding[key]))throw Error(name+': refresh System graph; the owner returned an incomplete command binding.');
 const specs=(binding.event_facts||[]).filter(f=>f.source==='submitted');
 if(specs.length!==args.length||specs.some(spec=>typeof spec.input!=='string'||!spec.input))throw Error(name+': the owner input schema changed. Reopen the owner node parameters and retry.');
 const result=await request('/api/universal/interaction',{
  interaction:binding.interaction,control:binding.control,event:binding.event,
  expected_scope:canvas.scope?.current||canvas.root,revision:canvas.revision,command_id:window.crypto.randomUUID(),
  event_facts:specs.map((spec,index)=>({input:spec.input,value:typeof args[index]==='string'?args[index]:JSON.stringify(args[index])}))
 });
 await commands.load();project();
 return result.result??result;
}
for(const operationName of ['createCommunityGroup','issueCommunityInvite','revokeCommunityInvite','verifyCommunityInvite','joinCommunityGroup',
 'setMarketplace','installMarketplaceItem','proposeMarketplaceListing','setProjectCharge','proposeProjectCharge',
 'setDecisionState','setRefine','compareRefine','setAnswerWidget','setPromotedParameter','setPortVisibility',
 'setProviderEnabled','setModelSource','checkModelRouting','setCapabilityEnabled','setLearning','runLearning','distilLearning',
 'setWatcherDimension','setWatcherOptions','removeDimension']) {
 api[operationName]=(...args)=>restCommand(operationName,args);
}
// The Community owner answers its commands with its current records; show them at once.
for(const operationName of ['createCommunityGroup','issueCommunityInvite','revokeCommunityInvite','verifyCommunityInvite','joinCommunityGroup',
 'setMarketplace','installMarketplaceItem','proposeMarketplaceListing','setProjectCharge','proposeProjectCharge']) {
 api[operationName]=async(...args)=>{const result=await restCommand(operationName,args);if(result?.community)publish({community:{...state.community,...result.community}});return result;};
}


api.getDecisionState=id=>state.graph.nodes.find(node=>node.id===id)?.output?.decision??null;
api.readHostAvailability=async()=>{
 const data=await request('/api/universal/hosts');
 const hosts=data.connectors||data.hosts;
 publish({hosts:Array.isArray(hosts)?hosts:[],hostsProbing:data.probing===true,
  hostError:Array.isArray(hosts)?'':'Program status is unavailable. Refresh Connections and retry.'});return data;
};
// WIRE-rest end
for(const name of researchActions)api[name]=async(...args)=>{
 if(!api.supportsAction(name))throw Error('Open the graph Workshop before running this research action.');
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding()),identity=state.profile.id;
 const result=await workshop(name,args);
 if(!result||result.ok===false||!result.id)throw Error(result?.message||result?.error||'Research owner did not confirm this action.');
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding())||identity!==state.profile.id)return result;
 await commands.load();
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding())||identity!==state.profile.id)return result;
 project();
 if(name==='correctAnswerSource')await refreshTasks();
 return result;
};
// Other contract operations have no verified backend owner: the fallback is a visible plain state.
// WIRE-projects
async function changeSchedule(op,args,add=false){
 const navigation=fileNavigation;
 if(sessionDocument&&(localDirty||add&&!sessionPath))await flushAutosave();
 if(fileNavigation!==navigation)throw Error('The open workflow changed.');
 const {result}=await request('/api/universal/canvas-op',{op,args:add?[...args,sessionPath]:args});
 if(fileNavigation===navigation&&sessionPath&&(add||args[0].startsWith(sessionPath+'#')))await pollFile(true);
 await refreshProjectData();
 return result;
}
const starterCards=library=>(Array.isArray(library?.templates)?library.templates:[]).filter(t=>String(t.id||'').startsWith('starter:')&&Array.isArray(t.children))
 .map(t=>({...t,runs:t.run_count,chain:t.children.map(n=>n.title),library:true}));
const taskReplyText=t=>[...(t?.messages||[]).filter(m=>m.role!=='user'),...(t?.fileMessages||[]).filter(m=>m.who&&m.who!=='You'),...(t?.agentLog||[]).filter(m=>m.who&&m.who!=='You')].map(m=>m.text||m.content||'').filter(Boolean).join('\n');
async function refreshProjectData() {
 const [schedules,skills,library]=await Promise.all([
  canvasOperation('project_schedules',[]),canvasOperation('list_skills',[]),request('/api/universal/node-library?templates=1').catch(error=>({error:error.message}))]);
 if(!Array.isArray(schedules)||!Array.isArray(skills))throw Error('The project owner returned an invalid schedule or template list. Refresh the graph and retry.');
 const rows=Array.isArray(library.templates)?library.templates:[];
 const skillCards=rows.filter(t=>String(t.id||'').startsWith('skill:'));
 const valid=Array.isArray(library.templates);
 const templates=[...starterCards(library),...skillCards,...skills.filter(s=>!skillCards.some(c=>c.id===s.id))];
 await refreshTasks();
 const feedback=state.tasks.filter(t=>t.title.startsWith('Feedback: ')).map(t=>({id:t.id,text:t.title.slice('Feedback: '.length),status:t.status,
  response:taskReplyText(t)}));
 publish({schedules,templates,feedback,templateError:valid?'':library.error||'Templates could not be read. Retry All templates.'});
 return {schedules,templates};
}
const projectExport=api.exportData;
function projectRunResult(result){
 if(!result||result.ok===false||!Object.hasOwn(result,'ran')||!Object.hasOwn(result,'revision'))return result;
 const previews=Object.entries(result.lines||{});
 const watcher=previews.length?{...state.watcher,source:previews[0][0],
  host:state.graph.nodes.find(n=>n.id===previews[0][0])?.title||state.graph.name,
  geometry:{...state.watcher.geometry,walls:previews[0][1]},status:previews[0][1].length?'loaded':'empty'}:state.watcher;
 const run={id:'revision:'+result.revision,title:state.graph.name,
  status:Object.keys(result.pending||{}).length?'Needs review':result.ran+' nodes evaluated',
  rows:Object.entries(result.outputs||result.results||{}).map(([node,output])=>({node,output}))};
 publish({watcher,lastResult:run,runs:[...state.runs.filter(r=>r.id!==run.id),run]});
 return {...result,id:run.id};
}
Object.assign(api,{
 async refreshCompany(){
  const company=await canvasOperation('read_company',[]);
  publish({activeFirm:company.id,profile:{...state.profile,firm:company.name,plan:company.plan},usage:{...state.usage,seats:company.seat_limit},
   people:company.members.map(m=>({id:m.user_id,name:m.full_name||m.email,email:m.email,accessRole:m.role}))});
  return company;
 },
 async setAccountSeats(seats){await canvasOperation('set_account_seats',[seats,state.activeFirm]);return api.refreshCompany();},
 async transferOwnership(id){await canvasOperation('transfer_ownership',[id,state.activeFirm]);return api.refreshCompany();},
 async signOutEverywhere(){const result=await canvasOperation('sign_out_everywhere',[]);await refreshAccount();return result;},
 getNodeParameters:node=>copy(state.graph.nodes.find(n=>n.id===(typeof node==='string'?node:node?.id))?.parameterSchema||[]),
 
 async checkWatcherSource(){
  const node=state.graph.nodes.find(n=>n.params.engine==='lines.watch'||n.type==='watch.preview');
  if(!node)throw Error('Add a Watcher node from Library and wire its geometry input before running.');
  const result=await api.runToHere(node.id);
  const lines=result.lines?.[node.id];
  if(!Array.isArray(lines))throw Error('The source returned no line preview. Review the upstream node result and retry.');
  publish({watcher:{...state.watcher,source:node.id,host:node.title,status:lines.length?'loaded':'empty',geometry:{...state.watcher.geometry,walls:lines}}});
  return result;
 },
 async addSchedule(target,time){
  if(!sessionDocument)throw Error('Open a workflow before adding a schedule.');
  const navigation=fileNavigation;
  let roots;
  if(target===state.graph.id||target===state.graph.name)roots=state.graph.id;
  else{
   const node=state.graph.nodes.find(n=>n.id===target||n.title===target);
   const skill=state.templates.find(t=>t.id===target||t.title===target);
   if(skill){const opened=await api.openTemplateGraph(skill.id);if(skill.library){await api.ungroupNode(opened.root);const outgoing=new Set(state.graph.wires.filter(w=>opened.nodes.includes(w.to)).map(w=>w.from));roots=opened.nodes.filter(id=>!outgoing.has(id));}else{const outgoing=new Set(skill.recipe.wires.map(pair=>pair[0]));roots=opened.nodes.filter((id,index)=>!outgoing.has(index));}}
   else if(node)roots=node.id;
   else throw Error('Choose the node or saved skill to repeat on the canvas, then add its schedule.');
  }
  if(fileNavigation!==navigation)throw Error('The open workflow changed.');
  return changeSchedule('add_schedule',[roots,time],true);
 },
 automationPause:async(...args)=>{
   const {result}=await request('/api/universal/canvas-op',{op:'automation_pause',args});
   if(Array.isArray(result.schedules))publish({schedules:result.schedules,desktop:{...state.desktop,automationsPaused:result.paused,workflowActivity:result.workflowActivity}});
   return result;
 },
 setScheduleEnabled:(id,enabled)=>changeSchedule('set_schedule_enabled',[id,enabled]),
 setScheduleTime:(id,time)=>changeSchedule('set_schedule_time',[id,time]),
 removeSchedule:id=>changeSchedule('remove_schedule',[id]),
 importRecipe:yaml=>canvasOperation('import_recipe',[yaml]),
 async saveSkill(name){const result=await canvasOperation('save_skill',[name]);await refreshProjectData();return result;},
 async openTemplateGraph(id){
  if(!state.templates.some(t=>t.id===id&&t.library))return canvasOperation('open_skill',[id]);
  const opened=await mutate(()=>request('/api/universal/node-create',{template:id,expected_scope:state.graph.id}));
  return {...opened,nodes:opened.children};
 },
 async startTemplate(id){const parent=state.graph.id;const opened=await api.openTemplateGraph(id);if(opened.root){scopeEpoch++;publish({declaredTasks:[]});await mutate(()=>commands.open(opened.root),true);}const runEpoch=scopeEpoch;const raw=await mutate(()=>request('/api/universal/run-graph',{roots:opened.nodes}));const result=scopeEpoch===runEpoch?projectRunResult(raw):raw;if(opened.root&&scopeEpoch===runEpoch&&state.graph.id===opened.root){scopeEpoch++;publish({declaredTasks:[]});await mutate(()=>commands.open(parent),true);}await refreshProjectData();return result;},
 
 async exportData(name,id){
  if(name==='Settings'){const result=await settingsAction('exportPreferences',[id||state.settingsScope||'User']);return {name:'ArchHub settings.json',type:'application/json',content:JSON.stringify(result.settingsExport,null,2)};}
  if(name==='Recipe'||name==='Graph'){const doc=await api.exportRecipe();return {name:(doc.title||'Untitled').replace(/[<>:"/\\|?*\u0000-\u001f]/g,'-')+'.archhub',type:'application/json',content:JSON.stringify(doc,null,2)};}
  if(name.startsWith('Run ')){const run=state.runs.find(r=>'Run '+r.id===name);if(!run)throw Error('Open a current run before exporting.');return {name:'Run.json',type:'application/json',content:JSON.stringify(run.rows,null,2)};}
  if(name==='Issues'){
   const node=reviewNode('Clash & Issues',id);
   if(node?.result?.status!=='Done'||!Array.isArray(node.result.output?.issues))throw Error('Run the selected check before exporting issues.');
   return {name:'Issues.json',type:'application/json',content:JSON.stringify(node.result.output.issues,null,2)};
  }
  if(name==='Receipts')return {name:'App-health-activity.json',type:'application/json',content:JSON.stringify(Array.isArray(id)?id:[],null,2)};
  return projectExport(name,id);
 },
 
 
 async setModEnabled(id,enabled){const result=await request('/api/universal/mods',{action:'enable',id,enabled});publish({mods:result.mods.rows});project();return result.mod;},
 async inspectMod(){
  const picked=await request('/api/universal/mods',{action:'browse'});if(!picked.path)return null;
  const result=await request('/api/universal/mods',{action:'review',path:picked.path});
  const mod={...result.review,id:picked.path,path:picked.path,status:'Ready for review'};
  publish({mods:[...state.mods.filter(m=>m.id!==mod.id),mod]});return mod;
 },
 async retryMod(id){const result=await request('/api/universal/mods',{action:'retry',id});publish({mods:result.mods.rows});project();return result.mod;},
 async installMod(id){const mod=state.mods.find(row=>row.id===id);if(!mod?.path||!mod?.digest)throw Error('Review the mod package before installing it.');const result=await request('/api/universal/mods',{action:'install',path:mod.path,reviewed_digest:mod.digest});publish({mods:result.mods.rows});project();return result.mod;},
 async removeMod(id){const result=await request('/api/universal/mods',{action:'remove',id});publish({mods:result.mods.rows});project();return result;},
 async sendFeedback(text){
  if(!text.trim())throw Error('Describe the problem before sending feedback.');
  const clean=text.trim();
  const created=await api.createTask('Feedback: '+clean,'BABOOM');
  if(created?.ok===false)return created;
  const id=created.taskId||created.id;
  await workshop('attachMeetingNotes',[id,clean]).catch(()=>{});
  await refreshTasks();
  const row=state.tasks.find(t=>t.id===id)||{id,status:created.status||'PLANNED'};
  publish({feedback:[...state.feedback.filter(f=>f.id!==id),{id,text:clean,status:row.status||'PLANNED',response:taskReplyText(row)}]});
  return {...created,id,status:row.status||'PLANNED'};
 },
 async checkFeedback(id){
  await refreshTasks();const task=state.tasks.find(t=>t.id===id);
  if(!task)throw Error('Open this feedback task in Workshop and refresh its current status.');
  const response=taskReplyText(task);
  publish({feedback:state.feedback.map(f=>f.id===id?{...f,status:task.status,response}:f)});return task;
 },
 
 
});
// WIRE-projects end
// OPS-projects2: confirmed projections of the existing domain owners.
async function refreshProjectState(){
 const result=await canvasOperation('project_state',[]);
 publish({graph:{...state.graph,versions:result.versions},modelReview:result.modelReview,
  suggestions:state.suggestions.filter(row=>!result.dismissed.includes(row.id))});
 return result;
}
api.addInterfaceElement=async kind=>{
 if(!sessionDocument)throw Error('Open a workflow before adding an interface element.');
 const navigation=fileNavigation;
 if(localDirty||!sessionPath)await flushAutosave();
 if(fileNavigation!==navigation)throw Error('The open workflow changed.');
 const {result}=await request('/api/universal/canvas-op',{op:'add_interface_element',args:[kind,sessionPath]});
 if(fileNavigation===navigation)await pollFile(true);
 return result;
};


api.refreshMods=async()=>{const result=await request('/api/universal/mods',{action:'state'});publish({mods:result.mods.rows});project();return result.mods.rows;};
api.importModNode=(id,item)=>canvasOperation('import_mod_node',[id,item]);

api.socketCompatible=(out,input)=>['any','unknown'].includes(out.type)||['any','unknown'].includes(input.type)||out.type===input.type||(['file','path'].includes(out.type)&&(['file','path'].includes(input.type)||input.type==='string'&&input.id.replace(/^param:/,'')==='path'));
api.compatibleNodes=endpoint=>{
 const node=state.graph.nodes.find(n=>n.id===endpoint?.id);
 const port=(endpoint?.side==='out'?node?.outputs:node?.inputs)?.find(p=>p.id===endpoint.port);
 if(!port)return [];
 const side=endpoint.side==='out'?'target':'source';
 return (state.libraryPorts||[]).filter(entry=>entry.ports[side].some(p=>p.type!=='unknown'&&(endpoint.side==='out'?api.socketCompatible(port,p):api.socketCompatible(p,port)))).map(entry=>({id:entry.id,name:entry.title}));
};
api.addCompatibleNode=async(endpoint,item,position)=>{
 const before=copy(sessionDocument), node=await api.addNode(item,position), other=state.graph.nodes.find(n=>n.id===endpoint.id), side=endpoint.side==='out'?'inputs':'outputs', original=(endpoint.side==='out'?other.outputs:other.inputs).find(p=>p.id===endpoint.port), port=node[side].find(p=>endpoint.side==='out'?api.socketCompatible(original,p):api.socketCompatible(p,original));
 try{await api.connectSockets(endpoint.side==='out'?{from:endpoint.id,fromPort:endpoint.port,to:node.id,toPort:port.id}:{from:node.id,fromPort:port.id,to:endpoint.id,toPort:endpoint.port});return node;}catch(error){sessionDocument=before;projectFile();queueAutosave();throw error;}
};
api.insertConvert=async value=>{
 const id=typeof value==='string'?value:value.id,wire=copy(sessionDocument.wires.find(w=>w.id===id));if(!wire)throw Error('Choose an existing wire.');
 const before=copy(sessionDocument),source=state.graph.nodes.find(n=>n.id===wire.from.node),target=state.graph.nodes.find(n=>n.id===wire.to.node),node=await api.addNode('data.convert',{x:(source.x+target.x)/2,y:(source.y+target.y)/2});
 try{await api.deleteWire(id);await api.connectSockets({from:wire.from.node,fromPort:wire.from.socket,to:node.id,toPort:'in'});await api.connectSockets({from:node.id,fromPort:'out',to:wire.to.node,toPort:wire.to.socket});return node;}catch(error){sessionDocument=before;projectFile();queueAutosave();throw error;}
};
api.addTemplateNode=async id=>{const opened=await api.openTemplateGraph(id);return opened.root?state.graph.nodes.find(n=>n.id===opened.root)||opened:mutate(()=>commands.composition('group',opened.nodes),true);};
api.prepareMod=(name,description)=>socialWork('Prepare a reviewed ArchHub mod package using the existing supported stream engines. Do not install or claim completion before validation.\n'+JSON.stringify({name,description}));
api.refreshFiles=async()=>{const files=await canvasOperation('project_files',[]);publish({files});return files;};
api.addFile=async(_name,kind='Project file')=>{
 const picked=await request('/api/universal/pick-file',{title:'Choose a project file'});
 if(!picked.path){if(picked.note)throw Error(picked.note+'. Open the desktop app to choose a file.');return null;}
 const file=await canvasOperation('add_file',[picked.path,kind]);await api.refreshFiles();return file;
};
api.selectFile=async id=>{const file=state.files.find(f=>f.id===id);if(!file)throw Error('Refresh project files before opening this file.');await commands.select(id);publish({activeFile:id});return file;};
api.removeFile=async id=>{if(!state.files.some(f=>f.id===id))throw Error('Refresh project files before removing this reference.');await api.deleteNode(id);await api.refreshFiles();return {id};};
api.addComposerAttachment=id=>{const file=state.files.find(f=>f.id===id);if(!file)throw Error('Choose an existing project file.');publish({composerAttachments:[...state.composerAttachments.filter(f=>f.id!==id),file]});return file;};
api.removeComposerAttachment=id=>{publish({composerAttachments:state.composerAttachments.filter(f=>f.id!==id)});return {id};};
const sendBeforeFiles=api.sendToBaboom;
api.sendToBaboom=async(text,options={})=>{
 const files=state.composerAttachments;
 if(files.some(f=>!state.files.some(row=>row.id===f.id)))throw Error('An attached file was removed. Remove its attachment before sending.');
 const result=await sendBeforeFiles(text+(files.length?'\nAttached project file nodes: '+JSON.stringify(files.map(f=>({id:f.id,path:f.path}))):''),options);
 if(result?.ok!==false)publish({composerAttachments:[]});return result;
};
api.saveGraphVersion=async label=>{
 if(!sessionDocument)throw Error('Open a workflow before saving a version.');
 const navigation=fileNavigation;
 if(!sessionPath||localDirty)await api.saveSession();
 if(navigation!==fileNavigation)return {cancelled:true};
 const result=await canvasOperation('save_graph_version',[label||null,sessionPath]);
 if(navigation===fileNavigation&&result?.document){sessionDocument=copy(result.document);sessionRevision=result.document.properties?.revision||sessionRevision;localDirty=false;projectFile();}
 return result?.version||result;
};
api.restoreGraphVersion=async id=>{
 if(typeof id==='string'&&id.toLowerCase().endsWith('.archhub'))return api.openSession(id);
 if(!sessionDocument||!sessionPath)throw Error('Open a saved workflow before restoring a version.');
 const navigation=fileNavigation;
 if(localDirty)await flushAutosave();
 if(navigation!==fileNavigation)return {cancelled:true};
 const result=await canvasOperation('restore_graph_version',[id,sessionPath]);
 if(navigation===fileNavigation&&result?.document)return adoptFile(result.document,result.path||sessionPath,navigation);
 return result;
};
function reviewNode(operation, source) {
 if(operation!=='Clash & Issues')throw Error('This model check is unavailable in this release.');
 if(!source || !sessionDocument || source.document!==sessionDocument.id || source.path!==sessionPath ||
    source.scope!==state.graph.scopeKey || state.graphOpening)throw Error('The selected workflow changed. Reopen Model review.');
 const node=sessionDocument.nodes.find(n=>n.id===source.node && n.type==='daily.ifc_check_bcf');
 if(!node && (source.node || sessionDocument.nodes.some(n=>n.type==='daily.ifc_check_bcf')))throw Error('Choose the IFC/BCF check node in this workflow.');
 return node;
}
api.openModelReviewNode=async(operation,source)=>{
 let node=reviewNode(operation,source);
 if(!node && !(state.libraryPorts||[]).some(item=>item.id==='daily:ifc_check_bcf')){
  await api.refreshLibraryPorts();
  node=reviewNode(operation,source);
 }
 if(node)return {id:node.id};
 return api.addNode('daily:ifc_check_bcf');
};
api.reviewModel=async(operation,source)=>{
 const node=reviewNode(operation,source);
 if(!node)throw Error('Add the IFC/BCF check to this workflow first.');
 if(!node.params?.bcf && !node.params?.ifc && !sessionDocument.wires.some(w=>w.enabled!==false && w.to.node===node.id && ['ifc','bcf','param:ifc','param:bcf'].includes(w.to.socket)))
  throw Error('Open the check node and choose an IFC model or BCF issue file.');
 return api.runNode(node.id);
};
api.updateReviewIssue=async(id,values)=>{const result=await canvasOperation('update_review_issue',[id,values]);await refreshProjectState();return result;};
api.dismissSuggestion=async id=>{const result=await canvasOperation('dismiss_suggestion',[id]);await refreshProjectState();return result;};
api.refreshMcpServers=async()=>{const result=await canvasOperation('mcp_servers',[]);publish({mcpServers:result});return result;};
api.discoverMcpTools=async(id,kind='Tools')=>{const result=await canvasOperation('discover_mcp_tools',[id,kind]);await api.refreshMcpServers();return result;};
api.reconnectMcp=async id=>{const result=await canvasOperation('reconnect_mcp',[id]);await api.refreshMcpServers();return result;};
api.importMcpTool=async(id,tool)=>{
 if(!sessionDocument)throw Error('Open a workflow before importing a tool.');
 const navigation=fileNavigation,documentId=sessionDocument.id;
 const {node}=await canvasOperation('prepare_mcp_tool',[id,tool]);
 if(navigation!==fileNavigation||sessionDocument?.id!==documentId)return {cancelled:true};
 fileEdit(document=>document.nodes.push(node),[node.id]);
 return {id:node.id};
};
api.addMcpServer=async text=>{const result=await canvasOperation('add_mcp_server',[text]);publish({mcpServers:result.servers});return result;};
api.removeMcpServer=async id=>{const result=await canvasOperation('remove_mcp_server',[id]);publish({mcpServers:result});return result;};
api.signInMcpServer=async id=>{const result=await canvasOperation('sign_in_mcp_server',[id]);publish({mcpServers:result});return result;};
api.setMcpServerEnabled=async(id,on)=>{const result=await canvasOperation('set_mcp_server_enabled',[id,on]);publish({mcpServers:result});return result;};
// The provider's own sign-in opens in his browser; Subscriptions shows the new state on the app's next provider read.
api.signInProvider=async id=>{const result=await canvasOperation('provider_sign_in',[id]);return result;};
async function communityOperation(op,args=[]){const result=await canvasOperation(op,args);publish({community:{...state.community,...result}});return result;}
api.refreshCommunity=()=>communityOperation('community_state');
api.subscribeCommunity=id=>communityOperation('subscribe_community',[id]);
api.reviewCommunityPattern=(id,decision)=>{
 const pattern=state.community.patterns.find(row=>row.id===id);
 if(decision==='Recheck'){if(!pattern)throw Error('Refresh Community and choose an existing pattern.');return socialWork('Recheck the evidence and provenance of this quarantined pattern. Return findings through its existing Brain judgement owner.\n'+JSON.stringify(pattern));}
 return communityOperation('review_community_pattern',[id,decision]);
};
api.proposeCommunityShare=async values=>{
 if(!values?.title?.trim()||values.redact!==true)throw Error('Name the pattern and enable redaction before preparing a community share.');
 return socialWork('Prepare a community pattern for review, with redaction. Do not publish until the existing approval owner accepts the exact payload.\n'+JSON.stringify(values));
};
api.shareMod=async id=>{
 const mod=state.mods.find(m=>m.id===id);if(!mod)throw Error('Refresh Library and choose the installed mod.');
 return socialWork('Prepare this mod for sharing through the existing reviewed publication owner. Do not claim publication or upload without confirmation.\n'+JSON.stringify(mod));
};
api.proposeMemory=async id=>{
 const suggestion=state.suggestions.find(row=>row.id===id);if(!suggestion)throw Error('Refresh Brain and choose an existing suggestion.');
 return socialWork('Review this memory suggestion through the existing Brain approval owner. Do not remember it without confirmation.\n'+JSON.stringify(suggestion));
};
function researchDoc(row){return {id:row.id,category:'Research',title:row.title,summary:row.summary,steps:[row.decision,row.why,row.licenseStatus].filter(Boolean),route:state.pages.find(page=>page==='Brain').toLowerCase(),bookSource:row.source};}
function projectResearch(row){
 publish({learning:{...state.learning,research:{...row,origin:row.sha256,finding:row.summary}},
  docs:[...state.docs.filter(d=>d.id!==row.id),researchDoc(row)]});
 return row;
}
api.readResearchSource=async source=>projectResearch(await socialOperation('read_content_source',[/^https:\/\//i.test(source)?'Web':'File',source]));
api.checkResearchLicense=async()=>{
 const id=state.learning.research?.id;if(!id)throw Error('Read a research source before checking its license.');
 return projectResearch(await socialOperation('check_research_license',[id]));
};
api.saveResearchDecision=async values=>{
 const id=state.learning.research?.id;if(!id)throw Error('Read the source before saving its decision.');
 let row=await socialOperation('save_research_decision',[id,values]);
 if(values.decision==='Adopt'&&!row.work){
  const task=await socialWork('Apply this researched decision through the existing reviewed node and compiler owners. Do not claim installation until read-back.\n'+JSON.stringify({source:row.source,sha256:row.sha256,...values}));
  row=await socialOperation('bind_research_work',[id,task.id]);
 }
 return projectResearch(row);
};

// Canvas state is the portable file document; gestures never round-trip a graph.
let systemProjection=null;
let preferenceContext='',preferenceRequest=0;
let sessionDocument=null, sessionPath='', fileDirectory='', fileHistory=[], fileFuture=[], autosaveTimer=null, fileWrites=Promise.resolve(), runEpoch=0, fileNavigation=0;
let sessionBreadcrumbs=[];
api.enterSession=async id=>{
 const node=sessionDocument?.nodes.find(n=>n.id===id);
 if(!node?.params.session_file)throw Error('Choose a linked session group.');
 await flushAutosave();
 const parent={path:sessionPath,title:sessionDocument.title};
 const resolved=await sessionRequest('resolve-session',{params:node.params});
 const opened=await api.openSession(resolved.path,true);
 if(!opened?.cancelled){sessionBreadcrumbs.push(parent);publish({sessionBreadcrumbs:[...sessionBreadcrumbs]});}
 return opened;
};
// An embed card's linked session: read and update through the session-files owner with this window's session and
// CSRF headers (a bare fetch is refused 403, so every card read "Could not check linked session").
api.resolveLinkedSession=params=>sessionRequest('resolve-session',{params});
api.updateEmbeddedSession=async id=>{
 const result=await sessionRequest('update-session',{document:sessionDocument,node:id});
 if(result?.document&&sessionPath)await sessionRequest('save',{path:sessionPath,document:result.document});
 return result;
};
api.leaveSession=async()=>{
 const parent=sessionBreadcrumbs.at(-1);if(!parent)return;
 await api.openSession(parent.path,true);sessionBreadcrumbs.pop();publish({sessionBreadcrumbs:[...sessionBreadcrumbs]});
};
api.sessionPathKey = path => String(path || '').replaceAll('\\', '/').toLowerCase();
api.sameSessionPath = (a, b) => !!a && !!b && api.sessionPathKey(a) === api.sessionPathKey(b);
api.duplicateHomeTask=async(task,path)=>{
 const openSource=api.sameSessionPath(path,sessionPath) || (task && sessionDocument?.properties?.taskContext?.task===task);
 if(openSource && currentEditState().unsaved)throw Error('Save your edits before duplicating this task.');
 const created=await sessionRequest('duplicate-home-task',{task,path});
 await refreshTasks(false);
 return created;
};
api.insertSession=async(path,position={})=>{
 const navigation=fileNavigation, destination=sessionPath, original=portableDocument();
 const result=await sessionRequest('insert-session',{document:original,session:path,...position});
 if(navigation!==fileNavigation || destination!==sessionPath || original.id!==sessionDocument?.id)return {cancelled:true};
 // The server validates the child link against this document ID. Apply only its new node to the current draft.
 const linked=result.document.nodes.find(n=>n.id===result.node);
 if(!linked || sessionDocument.nodes.some(n=>n.id===linked.id))throw Error('The linked node could not be inserted.');
 fileEdit(d=>{d.nodes.push(linked);},[linked.id]);
 return state.graph.nodes.find(n=>n.id===result.node);
};
api.detachSession=async node=>{
 const result=await sessionRequest('detach-session',{document:portableDocument(),node});
 fileEdit(d=>{d.nodes=result.document.nodes;});return result;
};
api.addAutomation=async(options={})=>{
 const path=sessionPath,navigation=fileNavigation;
 await flushAutosave();
 if(navigation!==fileNavigation)return {cancelled:true};
 const schedule=options?.trigger==='schedule'&&options.armed===false;
 const result=await sessionRequest('add-automation',{path,...(schedule?{trigger:'schedule',armed:false}:{})});
 if(navigation!==fileNavigation)return {cancelled:true};
 await adoptFile(result.document,path);return result;
};
const sessionRequest=(action,extra={})=>request('/api/session-files',{action,...extra});
// node_params.py, mirrored for display only: every value change goes through the server's one implementation.
const PARAM_SOCKET={bool:'boolean',integer:'number',number:'number',text:'string',choice:'string',date:'string',file:'file',folder:'file',object:'any',list:'list',path:'file',color:'string',enum:'string',json:'any'};
const PARAM_EDITOR={number:'number',integer:'number',bool:'boolean',boolean:'boolean',color:'color',date:'date',list:'json',json:'json',object:'json'};
const NODE_ICONS=['canvas','docs','folder','check','send','brain','settings','code','clock'];
api.nodeIcons=NODE_ICONS;
const PARAM_TYPES=['bool','integer','number','text','choice','date','file','folder','object','list'];
// node_datasets.py, mirrored for display only: a field node is its dataset's column as a typed list.
const COLUMN_LABEL={number:'Number',integer:'Integer',text:'Text',bool:'Boolean',choice:'Choice',date:'Date',file:'File',folder:'Folder',object:'Object',list:'List'};
function datasetPorts(node){
 if(node.type==='data.field')return {source:[{id:'values',type:'list',label:(COLUMN_LABEL[node.params.type]||'Any')+'[]'}],target:[{id:'column',type:'list',label:'column'}]};
 if(node.type!=='data.dataset')return null;
 return {source:[{id:'records',type:'list',label:'Record[]'},...(node.paramDefs||[]).map(d=>({id:'field:'+d.id,type:'list',label:d.name+' \u00b7 '+(COLUMN_LABEL[d.type]||'Any')+'[]'}))],target:[]};
}
function fileNode(node, document=sessionDocument){
 const ports0=state.libraryPorts||[],item=ports0.find(row=>row.id===node.item)||ports0.find(row=>row.engine===node.type);let base=node.ports||item?.ports||{source:[],target:[]};
 // A session file from before its Parameters/Tools/Context values shows them with their defaults and output sockets;
 // the file gets them at the first edit (api.setNodeParam). Opening writes nothing.
 if(node.type==='thing.session'&&item?.paramDefs){const outs=(item.ports?.source||[]).filter(p=>!(base.source||[]).some(q=>q.id===p.id));
  node={...node,paramDefs:node.paramDefs?.length?node.paramDefs:item.paramDefs,params:{...Object.fromEntries(item.paramDefs.map(d=>[d.id,item.params[d.id]])),...node.params}};base={...base,source:[...(base.source||[]),...outs]};}
 const defs=(node.paramDefs||[]).filter(d=>!node.fixed||!['reference','thread','limit','workspace'].includes(d.id)).map(d=>node.type==='param.value'&&d.id==='value'?{...d,type:node.params.type}:d), bind=node.type==='param.value'?node.bind:null, owner=bind&&document.nodes.find(n=>n.id===bind.node);
 const ports=datasetPorts(node)||{source:node.type==='param.value'?[{id:'value',type:PARAM_SOCKET[node.params.type]||'any'}]:base.source||[],
  target:[...(base.target||[]).map(p=>node.type==='param.value'&&p.id==='value'?{...p,type:PARAM_SOCKET[node.params.type]||'any'}:p),...defs.map(d=>({id:'param:'+d.id,type:PARAM_SOCKET[d.type]||'any',label:d.name}))]};
 const params=bind?{type:node.params.type,value:owner?.params[bind.param]}:item?.setting?{value:item.setting.value}:{...node.params};
 const typeOf=key=>item?.setting&&key==='value'?({'boolean':'bool'}[item.setting.type]||item.setting.type):bind&&key==='value'?node.params.type:node.type==='param.value'&&key==='value'?node.params.type:defs.find(d=>d.id===key)?.type||ports.target.find(port=>port.id===key)?.type;
 const schema=Object.keys(params).map(key=>{const kind=typeOf(key),def=item?.setting||defs.find(d=>d.id===key)||(bind&&owner?.paramDefs?.find(d=>d.id===bind.param))||{};
   return {key,label:node.type==='param.value'&&key==='type'?'Type':def.name||key,type:(['min','max','step'].includes(key)||kind==='number'||kind==='integer')?'number':PARAM_EDITOR[kind]||(kind?'text':typeof params[key]==='number'?'number':typeof params[key]==='boolean'?'boolean':'text'),
   dataType:kind||'',min:def.min,max:def.max,step:def.step??(kind==='integer'?1:undefined),unit:node.type==='param.value'&&key==='type'?'':def.unit||'',options:['enum','choice'].includes(kind)?def.options||[]:undefined,
   editable:!(node.fixed&&['reference','thread','limit',...(node.type==='thing.session'?[]:['workspace'])].includes(key))&&!(['param.value','data.field'].includes(node.type)&&key==='type'),userParam:!!defs.find(d=>d.id===key),promoted:defs.find(d=>d.id===key)?.promoted||null,
   linkedTo:bind&&key==='value'?(owner?.title||'')+' \u00b7 '+(owner?.paramDefs?.find(d=>d.id===bind.param)?.name||bind.param):''};});
 const dataset=node.type==='data.dataset'?{fields:defs,records:node.records||[]}:null;
 const feed=node.type==='data.field'&&document.wires.find(w=>w.to.node===node.id&&w.to.socket==='column');
 const column=node.type==='data.field'?{dataset:feed?document.nodes.find(n=>n.id===feed.from.node)?.title||'':'',field:feed?feed.from.socket.replace(/^field:/,''):'',label:(COLUMN_LABEL[node.params.type]||'Any')+'[]'}:null;
 return {id:node.id,type:node.type,fixed:!!node.fixed,agentWork:node.agentWork,agentStep:node.params?.workshop_step===true,agentTask:document.properties?.taskContext?.task,workflowStart:node.id==='start'&&!!document.properties?.taskContext?.task,pure:node.type==='script.python'?node.params.kind!=='effect':node.type==='thing.agent'&&node.params.reference===true?true:item?.pure??node.pure,budget:node.budget||item?.budget||null,loop:node.loop||item?.loop||null,settingsKeys:item?.settingsKeys||[],dataset,column,title:node.frameMembers&&node.title==='Frame'?'Group':node.title||item?.title||node.type,kind:node.children?'Group':item?.title||node.type,category:node.agentWork?.role==='step'?node.agentWork.kind+' · '+node.agentWork.tool:item?.cat||'Node',x:node.position.x,y:node.position.y,
  params,defaults:item?.params||{},parameterSchema:schema,paramDefs:defs,bind,
  // A Library port declares a list as cardinality 'many' (library_engines port metadata); the canvas reads list.
  inputs:(ports.target||[]).map(p=>({...p,name:p.label||p.id,type:p.type==='unknown'?'any':p.type,list:p.list===true||p.cardinality==='many'})),outputs:(ports.source||[]).map(p=>({...p,name:p.label||p.id,type:p.type==='unknown'?'any':p.type,list:p.list===true||p.cardinality==='many'})),
  children:node.children||[],frameMembers:node.frameMembers,collapsed:node.collapsed!==false,members:(Array.isArray(node.members)?node.members:[]).filter(m=>m&&typeof m.id==='string'&&m.id).map(m=>({id:m.id,title:m.title||m.name||m.id,agent:m.agent||m.id})),parent:node.parent||null,icon:NODE_ICONS.includes(node.icon)?node.icon:'',color:typeof node.color==='string'&&/^#[0-9a-f]{6}$/i.test(node.color)?node.color:undefined,frozen:!!node.frozen,pinned:!!node.pinned,bypassed:!!node.bypassed,portVisibility:node.portVisibility||{},parameterPresentation:node.parameterPresentation||{},
  output:node.result?.output??[],status:node.result?.status==='Declined'?'Rejected':node.result?.status||'Idle',error:node.result?.error||'',display:node.result?.display||'',elapsedMs:node.result?.elapsed_ms};
}
// session_files.py _WIRE_MENUS, mirrored for the inspector. First choice is the omitted-field value.
const WIRE_MENUS=[['matching',['By index','Longest','Shortest','Cross']],['order',['Source order','Reverse']],['missing',['Preserve','Drop','Blank']],['units',['From source','From target']],['conversion',['None','Number','Text']],['route',['Bezier','Straight','Step']]];
function projectSessionWire(w,nodes){
 const row={id:w.id,inferred:!!w.inferred,from:w.from.node,fromPort:w.from.socket,to:w.to.node,toPort:w.to.socket,rule:w.rule||'',enabled:w.enabled!==false,type:nodes.find(n=>n.id===w.from.node)?.outputs.find(p=>p.id===w.from.socket)?.type||'any'};
 for(const [name,choices] of WIRE_MENUS)row[name]=choices.includes(w[name])?w[name]:choices[0];
 return row;
}
function projectGroups(nodes,wires){
 const groups=new Set(nodes.filter(n=>!n.fixed&&n.children.length));
 if(!groups.size)return {nodes,wires};
 const byId=new Map(nodes.map(n=>[n.id,n]));
 const collapsedOwner=new Map();
 for(const group of groups){
  group.inputs=[];group.outputs=[];group.output={};
  const members=group.children.map(id=>byId.get(id)).filter(Boolean);
  group.status=members.some(n=>/error|fail/i.test(n.status))?'Error':members.some(n=>/approval/i.test(n.status))?'Waiting for approval':members.some(n=>n.status==='Running')?'Running':members.every(n=>['Done','Solved','Skipped'].includes(n.status))?'Done':'Idle';
 }
 for(const member of nodes){
  if(!member.parent||groups.has(member))continue;
  const seen=new Set([member.id]);
  let owner=byId.get(member.parent);
  while(owner&&!seen.has(owner.id)){
   seen.add(owner.id);
   if(groups.has(owner)){
    if(owner.collapsed)collapsedOwner.set(member.id,owner);
    for(const [key,prefix] of [['inputs','in:'],['outputs','out:']]){
     for(const port of member[key]){
      const id=prefix+member.id+':'+port.id;
      owner[key].push({...port,id,member:{node:member.id,port:port.id}});
      if(key==='outputs')owner.output[id]=member.output?.[port.id];
     }
    }
   }
   owner=byId.get(owner.parent);
  }
 }
 for(const wire of wires){
  // A saved group boundary can itself be inside a collapsed group. Project from the real member first.
  for(const [side,ports] of [['from','outputs'],['to','inputs']]){
   const owner=byId.get(wire[side]);
   if(!groups.has(owner))continue;
   const alias=owner[ports].find(port=>port.id===wire[side+'Port']);
   if(!alias?.member)continue;
   wire[side]=alias.member.node;
   wire[side+'Port']=alias.member.port;
   if(side==='from')wire.type=alias.type;
  }
  const from=collapsedOwner.get(wire.from),to=collapsedOwner.get(wire.to);
  if(from?.id===to?.id)continue;
  if(from&&byId.get(wire.from)?.outputs.some(port=>port.id===wire.fromPort)){wire.memberFrom={node:wire.from,port:wire.fromPort};wire.fromPort='out:'+wire.from+':'+wire.fromPort;wire.from=from.id;}
  if(to&&byId.get(wire.to)?.inputs.some(port=>port.id===wire.toPort)){wire.memberTo={node:wire.to,port:wire.toPort};wire.toPort='in:'+wire.to+':'+wire.toPort;wire.to=to.id;}
 }
 return {nodes,wires};
}
// id -> {stamp, node}: a card whose file record, Library entry and document context did not change keeps its
// projected object, so the canvas redraws only what changed (a drop moves one card, not all of them).
let projectedNodes=new Map();
// The Workshop node's update parameters are the Settings owner's live values (spec 4.3): an older workflow's
// stored copy is shown as what the updater actually uses. Refreshed on open and after every Settings edit.
let liveUpdatePolicy=null;
function withLiveUpdatePolicy(node){
 if(!liveUpdatePolicy||node.params?.tool!=='workshop')return node;
 const live=Object.fromEntries(UPDATE_POLICY_KEYS.filter(key=>Object.hasOwn(node.params,key)&&Object.hasOwn(liveUpdatePolicy,key)).map(key=>[key,liveUpdatePolicy[key]]));
 return Object.keys(live).length?{...node,params:{...node.params,...live}}:node;
}
async function refreshLiveUpdatePolicy(){
 try{liveUpdatePolicy=await settingsAction('readUpdatePolicySettings',[]);projectFile();}
 catch(error){console.warn('Update settings not read for the canvas:',error.message);}
}
function syncPreferenceContext(force=false){
 if(!sessionDocument)return;
 const context=JSON.stringify([sessionDocument.id,sessionPath,sessionDocument.properties?.project,sessionDocument.properties?.settings]);
 if(!force&&context===preferenceContext)return;
 preferenceContext=context;
 const generation=++preferenceRequest;
 publish({keyboardPending:true});
 if(!sessionPath)return;
 void settingsAction(activeSurface.startsWith('settings')?'readPreferences':'readEffectivePreferences').catch(error=>{if(generation===preferenceRequest)publish({keyboardError:error.message||String(error)});}).finally(()=>{if(generation===preferenceRequest)publish({keyboardPending:false});});
}
function projectFile(){
 if(!sessionDocument)return;
 const properties=sessionDocument.properties||{};
 // Groups, bound values and dataset columns read other nodes (and groups are completed in place below): always fresh.
 // Members are only read by their group, so they keep their projection like any other card.
 const readsOthers=node=>node.children||node.frameMembers||node.bind||node.type==='data.field';
 const context=JSON.stringify([properties.taskContext?.task||'',state.libraryPorts.length]), kept=new Map();
 const nodes=sessionDocument.nodes.map(saved=>{
  const node=withLiveUpdatePolicy(saved);  // shown from the Settings owner; the file's copy is never written back
  if(readsOthers(node))return fileNode(node);
  const stamp=context+JSON.stringify(node), held=projectedNodes.get(node.id);
  const projected=held&&held.stamp===stamp&&held.ports===state.libraryPorts?held.node:fileNode(node);
  kept.set(node.id,{stamp,ports:state.libraryPorts,node:projected});return projected;
 });
 projectedNodes=kept;
 const versions=(properties.checkpoints||[]).filter(c=>c&&typeof c.id==='string').map(c=>({id:c.id,name:c.title||c.id,at:c.at||'',nodes:(c.document?.nodes||[]).map(n=>({id:n.id}))}));
 const graph={...properties,versions,id:sessionDocument.id,scopeKey:sessionDocument.id+':'+scopeEpoch,name:sessionDocument.title,system:false,
  ...projectGroups(nodes,sessionDocument.wires.map(w=>projectSessionWire(w,nodes))),viewport:sessionDocument.viewport};
 publish({graph,sessionFile:sessionPath,sessionDirty:localDirty || !sessionPath,graphOpening:false,sync:solveNote||'Local session file'});
 syncPreferenceContext();
}
api.readTaskPreview=async id=>{
 const task=state.tasks.find(row=>row.id===id);
 if(!task?.sessionPath)throw Error('This task has no session file.');
 const read=await sessionRequest('read',{path:task.sessionPath}),document=read.document,nodes=document.nodes.map(node=>fileNode(node,document));
 return {...document.properties,id:document.id,scopeKey:document.id+':preview',name:document.title,...projectGroups(nodes,document.wires.map(wire=>projectSessionWire(wire,nodes))),viewport:document.viewport};
};
// Parametric (Grasshopper): an edit re-solves the pure nodes downstream of it, then stops.
let sessionRevision=0, localDirty=false, solveIds=new Set(), solveParams=[], solveTimer=null, solveNote='', solveCount=0;
// A drop's redraw, waiting for the frame after the drop is painted (the edit itself is already in the document).
let projectAfterPaint=0;
function fileEdit(edit,solveFor=null,param=null,recordHistory=true,preserveSolve=false,afterPaint=false){
 requireDesktop();
 if(!sessionDocument)throw Error('Open a session first.');
 const before=copy(sessionDocument);
 if(recordHistory){fileHistory.push(before);if(fileHistory.length>100)fileHistory.shift();fileFuture=[];}
 try{
  edit(sessionDocument);
  if(before.properties?.taskContext?.anchor && sessionDocument.nodes.length>before.nodes.length){
   const task=state.focusedTask, active=state.tasks.find(row=>row.id===task);
   if(!active || !api.sameSessionPath(active.sessionPath,sessionPath) ||
      !before.nodes.some(node=>node.id===task && node.workshopTask===task))throw Error('Open the task to add nodes to its canvas.');
   const prior=new Set(before.nodes.map(node=>node.id));
   for(const node of sessionDocument.nodes)if(!prior.has(node.id))node.workshopTask=task;
  }
 }catch(error){sessionDocument=before;if(recordHistory)fileHistory.pop();throw error;}
 localDirty=true;if(!preserveSolve)runEpoch++;
 // afterPaint: the document, undo step and autosave are set now (a reload or close right after still saves it);
 // only the redraw of every view waits for the next painted frame.
 let shown=null;
 if(afterPaint){window.cancelAnimationFrame(projectAfterPaint);shown=new Promise(done=>{projectAfterPaint=window.requestAnimationFrame(()=>window.setTimeout(()=>{projectFile();done();}));});}else projectFile();
 queueAutosave();if(solveFor)scheduleSolve(solveFor,param);return shown?{ok:true,shown}:{ok:true};
}
function scheduleSolve(ids,param){
 for(const id of ids)solveIds.add(id);if(param)solveParams.push(param);
 // Debounce: rapid edits (dragging a slider, typing) coalesce into one solve.
 clearTimeout(solveTimer);solveTimer=setTimeout(()=>runSolve().catch(error=>notice('Solve failed: '+error.message)),Number(state.canvasPolicy?.solve_debounce_ms??120));
}
async function runSolve(){
 if(!desktopAdmitted())return;
 const changed=[...solveIds].filter(id=>sessionDocument?.nodes.some(n=>n.id===id)),params=solveParams;solveIds=new Set();solveParams=[];
 if(!sessionDocument||!changed.length)return;
 const id=sessionDocument.id,epoch=runEpoch;solveCount++;
 const solved=await sessionRequest('solve',{document:portableDocument(),path:sessionPath,changed,params});
 if(sessionDocument?.id!==id||epoch!==runEpoch)return;
 for(const n of sessionDocument.nodes)if(solved.results[n.id])n.result=solved.results[n.id];
 solveNote='Solved '+solved.solved.length+' node'+(solved.solved.length===1?'':'s')+' in '+solved.ms+' ms'+(solved.stale.length?' · '+solved.stale.length+' out of date (Run)':'');
 localDirty=true;projectFile();publish({solveMs:solved.ms,solveCount,solveStale:solved.stale});queueAutosave();
 if(solved.written?.length)api.refreshRouter?.().catch(()=>{});
 return solved;
}
function acknowledgeSave(sent,saved){
 // After every acknowledged save, adopt the owner's document for every field not changed locally since the sent snapshot.
 const current=portableDocument(),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b),viewUnchanged=same(current.viewport,sent.viewport)&&same(current.properties?.viewportSaved,sent.properties?.viewportSaved);
 if(same(current,sent)){
  // The owner's copy usually differs only in its own bookkeeping (revision, history): the canvas already shows it,
  // so only the saved state is published, not a whole new graph (a full re-render after every autosave).
  const shown=document=>({...document,properties:Object.fromEntries(Object.entries(document.properties||{}).filter(([key])=>!['revision','history','checkpoints'].includes(key)))});
  const unchanged=same(shown(saved.document),shown(sent));
  sessionDocument=copy(saved.document);sessionRevision=saved.revision??saved.document.properties?.revision??0;
  localDirty=false;
  if(unchanged){publish({sessionFile:sessionPath,sessionDirty:!sessionPath});syncPreferenceContext();}else projectFile();
  return;
 }
 for(const key of new Set([...Object.keys(sent),...Object.keys(saved.document)])){
  if(key==='properties'||key==='viewport'&&!viewUnchanged)continue;
  if(same(current[key],sent[key])){if(Object.hasOwn(saved.document,key))sessionDocument[key]=copy(saved.document[key]);else delete sessionDocument[key];}
 }
 for(const key of new Set([...Object.keys(sent.properties||{}),...Object.keys(saved.document.properties||{})])){
  if(key==='viewportSaved'?!viewUnchanged:!same(current.properties?.[key],sent.properties?.[key]))continue;
  if(Object.hasOwn(saved.document.properties||{},key))sessionDocument.properties[key]=copy(saved.document.properties[key]);else delete sessionDocument.properties[key];
 }
 // The owner now holds saved.revision: the next save builds on it, whatever changed here while this save was in flight.
 sessionRevision=saved.revision??saved.document.properties?.revision??sessionRevision;
 localDirty=!same(sessionDocument,saved.document);projectFile();
}
let saveConflict=null, resolvingSaveConflict=false, savedConflictDraft=null;
const saveConflictMessage='This workflow changed elsewhere. Keep your changes in a copy with automations paused, or discard them and reload.';
function rememberSaveConflict(error,path){
 if(error.response?.code!=='canvas_save_conflict'||!path||path!==sessionPath)return;
 saveConflict=path;savedConflictDraft=null;clearTimeout(autosaveTimer);
 reportEditState();
 publish({canvasSaveConflict:saveConflictMessage,canvasSaveRecoveryError:''});
}
function refuseUnresolvedSave(){
 if(!saveConflict)return;
 publish({canvasSaveConflict:saveConflictMessage});
 throw Error(saveConflictMessage);
}
function saveNow(){
 const id=sessionDocument?.id,writeAccount=accountEpoch;
 fileWrites=fileWrites.catch(()=>{}).then(async()=>{
  if(writeAccount!==accountEpoch||!desktopAdmitted()||sessionDocument?.id!==id)return {cancelled:true};
  refuseUnresolvedSave();
  const sent=portableDocument(),currentPath=sessionPath,base=sessionRevision;
  const saved=await sessionRequest('autosave',{document:sent,path:currentPath,base_revision:base}).catch(error=>{rememberSaveConflict(error,currentPath);throw error;});
  if(sessionDocument?.id===sent.id&&sessionPath===currentPath){sessionPath=saved.path;acknowledgeSave(sent,saved);}
  saveFailed=false;reportEditState();
  return saved;
 });
 return fileWrites;
}
// The server holds automatic update restarts while this is true: an unsaved edit, a failed save (it stays
// unsaved) or an unresolved Keep/Discard conflict. A restart then lost the local edit. Sent only on change.
// One entry per open Studio page and file: another page's clean report never clears this page's draft.
const editView=(window.crypto?.randomUUID?.()||String(Math.random()).slice(2))+'-'+Date.now();
// A reload of this tab replaces its page: the first report retires the previous page's entries (sessionStorage is per tab).
// Only an actual reload of this same tab retires the previous page. A tab opened from another one inherits its
// sessionStorage (window.open): that live opener is never retired by the new tab's reports.
let retiredEditView=null;
try{
 const navigation=window.performance?.getEntriesByType?.('navigation')?.[0]?.type;
 const previous=window.sessionStorage.getItem('archhub.editView');
 if(navigation==='reload'&&!window.opener&&previous&&previous!==editView)retiredEditView=previous;
 window.sessionStorage.setItem('archhub.editView',editView);
}catch(error){console.warn('Edit view not remembered for reloads:',error.message);}
let reportedEditState=null, reportedEditFile=null, editSeq=0, saveFailed=false;
function currentEditState(){return {unsaved:!!(localDirty||saveConflict||saveFailed),file:sessionPath||''};}
function reportEditState(force=false){
 if(resolvingSaveConflict)return;  // the Keep/Discard resolution reports for itself (resolveSaveConflict)
 const {unsaved,file}=currentEditState();  // localDirty stays true until a save is acknowledged
 if(!force&&unsaved===reportedEditState&&file===reportedEditFile)return;
 // Opening another file first saves this one (adoptFile flushes; an unresolved conflict refuses the switch).
 if(reportedEditFile!==null&&file!==reportedEditFile&&reportedEditState)
  sessionRequest('edit_state',{view:editView,file:reportedEditFile,seq:++editSeq,unsaved:false}).catch(error=>console.warn('Edit report failed:',error.message));
 reportedEditState=unsaved;reportedEditFile=file;
 keepDraftForRecovery(unsaved,file);
 const retire=retiredEditView;retiredEditView=null;
 sessionRequest('edit_state',{view:editView,file,seq:++editSeq,unsaved,...(retire?{retire}:{})}).catch(error=>{reportedEditState=null;if(retire)retiredEditView=retire;console.warn('Edit report failed:',error.message);});
}
// A closed window's unsaved draft survives in this browser profile so a later window can keep or discard
// exactly that draft; its server-side update hold is released only by that choice (resolves=<its view id>).
const DRAFT_PREFIX='archhub.draft.';
// A page's lease is a heartbeat: every live window rewrites its timestamp on each file poll and answers a ping
// on the 'archhub-pages' channel (message events are not throttled like a hidden tab's timers). A draft is
// offered for Keep/Discard only when its owner's heartbeat is older than LEASE_POLLS polls AND the owner does not
// answer a ping within one poll. A closed window drops its lease at pagehide; a crashed one simply stops beating.
// A live window is never offered, and is re-asked at click time.
const ALIVE_PREFIX='archhub.alive.', LEASE_POLLS=2;  // short: the live ping, not the timestamp, protects a live window
let draftRevision=0,localRecoveryRequested=false;
const pollMs=()=>Number(state.canvasPolicy?.file_poll_ms??1000);
function beat(){
 try{window.localStorage.setItem(ALIVE_PREFIX+editView,String(Date.now()));}
 catch(error){console.warn('Page lease not recorded:',error.message);}
}
beat();
window.addEventListener?.('pagehide',()=>{
 try{window.localStorage.removeItem(ALIVE_PREFIX+editView);}catch(error){console.warn('Page lease not released:',error.message);}
});
const pages=typeof window.BroadcastChannel==='function'?new window.BroadcastChannel('archhub-pages'):null;  // fallback channel
const pongs=new Map();
if(pages)pages.onmessage=event=>{
 const message=event.data||{};
 if(message.type==='ping'&&message.view===editView)pages.postMessage({type:'pong',view:editView});
 if(message.type==='pong')pongs.get(message.view)?.();
};
function askAlive(view){
 // True when the owning window answers within one poll; no channel means it cannot be proven gone.
 if(!pages)return Promise.resolve(true);
 return new Promise(resolve=>{
  const timer=setTimeout(()=>{pongs.delete(view);resolve(false);},pollMs());
  pongs.set(view,()=>{clearTimeout(timer);pongs.delete(view);resolve(true);});
  pages.postMessage({type:'ping',view});
 });
}
// Primary proof (where Web Locks exist): each live view holds 'archhub-view-<id>' for its whole life. The browser
// releases it when the page dies, a renderer crash included, so a draft written under a lock whose lock is no
// longer held belongs to a dead window. Drafts written without a lock (older pages, no Web Locks) use the
// heartbeat + ping fallback.
const LOCK_PREFIX='archhub-view-';
let viewLockHeld=false;
if(window.navigator?.locks?.request){
 window.navigator.locks.request(LOCK_PREFIX+editView,()=>{viewLockHeld=true;return new Promise(()=>{});})
  .catch(error=>console.warn('View lock not taken; heartbeat fallback only:',error.message));
}
async function ownerAlive(draft){
 if(draft.locked&&window.navigator?.locks?.query){
  try{
   const held=await window.navigator.locks.query();
   return (held.held||[]).some(lock=>lock.name===LOCK_PREFIX+draft.view);
  }catch(error){console.warn('Locks unreadable; treated as open:',error.message);return true;}
 }
 return !leaseStale(draft.view)||await askAlive(draft.view);
}
function leaseStale(view){
 // Missing, unreadable or older than LEASE_POLLS polls (a marker from before timestamps counts as stale too).
 try{
  const stamp=Number(window.localStorage.getItem(ALIVE_PREFIX+view));
  return !Number.isFinite(stamp)||Date.now()-stamp>LEASE_POLLS*pollMs();
 }catch(error){console.warn('Page lease unreadable; treated as open:',error.message);return false;}
}
const draftKey=()=>DRAFT_PREFIX+encodeURIComponent(desktopSubject||'unattributed')+'.'+editView;
function keepDraftForRecovery(unsaved,file){
 // Written on EVERY edit (not only when the dirty flag flips), in order: the stored draft is always the latest bytes.
 try{
  if(unsaved&&sessionDocument)window.localStorage.setItem(draftKey(),JSON.stringify({subject:desktopSubject,view:editView,file,revision:++draftRevision,locked:viewLockHeld,document:portableDocument()}));
  else window.localStorage.removeItem(draftKey());
 }catch(error){console.warn('Draft not kept for recovery:',error.message);}
}
function storedDrafts(includeLocal=localRecoveryRequested){
 const found=[];if(!desktopAdmitted()||!desktopSubject)return found;
 try{
  for(let index=0;index<window.localStorage.length;index++){
   const key=window.localStorage.key(index);
   if(!key?.startsWith(DRAFT_PREFIX)||key===draftKey())continue;
   const draft=JSON.parse(window.localStorage.getItem(key)||'null');
   if((draft?.subject===desktopSubject||includeLocal&&!draft?.subject)&&draft?.view&&draft.document)found.push({view:draft.view,file:draft.file||'',key,locked:draft.locked===true});
  }
 }catch(error){console.warn('Drafts from closed windows unreadable:',error.message);}
 return found;
}
let orphanCheck=null;
function refreshOrphanDrafts(includeLocal=localRecoveryRequested){
 // One check at a time; only drafts whose owner is stale AND silent are offered.
 if(orphanCheck)return orphanCheck;
 orphanCheck=(async()=>{
  const candidates=storedDrafts(includeLocal);
  const answers=await Promise.all(candidates.map(ownerAlive));
  publish({orphanDrafts:candidates.filter((_draft,index)=>!answers[index])});
 })().catch(error=>console.warn('Closed-window drafts not checked:',error.message)).finally(()=>{orphanCheck=null;});
 return orphanCheck;
}
function orphanDrafts(){return state.orphanDrafts||[];}
api.recoverLocalWork=async()=>{requireDesktop();if(orphanCheck)await orphanCheck;localRecoveryRequested=true;return refreshOrphanDrafts(true);};
// Another window closing (lease removed) or changing its draft changes what can be recovered here.
window.addEventListener?.('storage',event=>{
 if(event.key===null||event.key.startsWith(ALIVE_PREFIX)||event.key.startsWith(DRAFT_PREFIX))refreshOrphanDrafts();
});
api.resolveOrphanDraft=async(view,keep)=>{
 requireDesktop();
 const key=orphanDrafts().find(draft=>draft.view===view)?.key;if(!key)throw Error('That draft is not available for this account.');const draft=JSON.parse(window.localStorage.getItem(key)||'null');
 if(draft?.subject&&draft.subject!==desktopSubject)throw Error('That draft belongs to another account.');
 if(!draft?.document)throw Error('That draft is no longer here.');
 if(await ownerAlive({view,locked:draft.locked===true}))throw Error('That window is still open; choose there.');
 try{
  if(keep)await sessionRequest('save',{document:draft.document,save_as:true,conflict_copy_of:draft.file||undefined});
  // This page's own state for that file rides along, so the report never clears this page's own draft.
  const mine=currentEditState();
  await sessionRequest('edit_state',{view:editView,file:draft.file||'',seq:++editSeq,
   unsaved:mine.unsaved&&mine.file===(draft.file||''),resolves:view,resolved:keep?'keep':'discard'});
  window.localStorage.removeItem(key);
  publish({orphanDrafts:orphanDrafts().filter(draft=>draft.view!==view),orphanDraftError:''});
  return {ok:true};
 }catch(error){publish({orphanDraftError:error.message});throw error;}
};
// A reloaded tab whose old page left an unsaved draft does not retire it: that draft holds until kept or discarded.
try{if(retiredEditView){for(let index=0;index<window.localStorage.length;index++){const key=window.localStorage.key(index);if(key===DRAFT_PREFIX+retiredEditView||key?.startsWith(DRAFT_PREFIX)&&key.endsWith('.'+retiredEditView)){retiredEditView=null;break;}}}}
catch(error){console.warn('Previous page draft unreadable:',error.message);}
Promise.resolve().then(refreshOrphanDrafts);
// The desktop asks the live page right before an automatic close; no answer means it does not close.
window.__archhubEditState=()=>{reportEditState(true);return currentEditState();};
function queueAutosave(){
 reportEditState();  // the first edit is protected at once, not at the next file poll
 const now=currentEditState();keepDraftForRecovery(now.unsaved,now.file);  // every edit refreshes the stored draft
 if(saveConflict||!desktopAdmitted())return;
 clearTimeout(autosaveTimer);autosaveTimer=setTimeout(()=>{
  saveNow().catch(error=>{saveFailed=true;reportEditState();if(!saveConflict)notice('Autosave failed: '+error.message);});
 },Number(state.canvasPolicy?.viewport_commit_debounce_ms??140));
}
// The open file is shared with agents: pick up their edits (file revision), no background solve.
async function pollFile(force=false){
 if(!desktopAdmitted()){beat();return;}
 reportEditState();  // on the file poll's own cadence (canvasPolicy.file_poll_ms)
 beat();refreshOrphanDrafts();  // this window's heartbeat; a crashed window's draft becomes recoverable
 const navigation=fileNavigation;
 if(force&&localDirty)await flushAutosave();
 if(!sessionDocument||localDirty||!force&&document.hidden||navigation!==fileNavigation)return;
 const id=sessionDocument.id,path=sessionPath;
 const current=()=>navigation===fileNavigation&&path===sessionPath&&sessionDocument?.id===id&&!localDirty;
 const head=await sessionRequest('head',{path,id});
 if(!current()||head.revision<=sessionRevision)return;
 const read=await sessionRequest('read',{path,id});
 if(!current()||read.document?.id!==id||read.revision<=sessionRevision)return;
 fileHistory.push(copy(sessionDocument));sessionDocument=copy(read.document);sessionRevision=read.revision;runEpoch++;
 solveNote=read.by&&read.by!=='You'?'Updated by '+read.by:solveNote;projectFile();publish({liveEditBy:read.by,liveRevision:read.revision});
}
// Nothing polls in the background by itself: the file poll runs only while a screen is subscribed.
function watchFile(){if(listeners.size&&filePollTimer===null&&typeof window.setInterval==='function')filePollTimer=window.setInterval(()=>pollFile().catch(()=>{}),Number(state.canvasPolicy?.file_poll_ms??1000));}
function stopFile(){if(filePollTimer!==null){window.clearInterval(filePollTimer);filePollTimer=null;}}
function portableDocument(){return copy(sessionDocument);}
async function adoptFile(document,path='',navigation=++fileNavigation,recoveredDraft=null){
 requireDesktop();
 if(recoveredDraft===null)refuseUnresolvedSave();
 const checked=await sessionRequest('validate',{document});
 if(navigation!==fileNavigation)return {cancelled:true};
 // The untouched startup draft has no file to flush when another workflow opens.
 if(recoveredDraft===null&&sessionDocument&&(sessionPath||localDirty||autosaveTimer!==null))await flushAutosave();
 if(navigation!==fileNavigation)return {cancelled:true};
 if(recoveredDraft!==null){
  if(recoveredDraft!==JSON.stringify(sessionDocument))throw Error('Your draft changed during recovery. Choose again to keep the latest edits.');
  saveConflict=null;savedConflictDraft=null;publish({canvasSaveConflict:''});notice('');
 }
 sessionDocument=copy(checked.document);sessionPath=path;sessionRevision=checked.document.properties?.revision||0;localDirty=false;solveNote='';fileHistory=[];fileFuture=[];runEpoch++;scopeEpoch++;projectFile();if(recoveredDraft===null)queueAutosave();
 refreshLiveUpdatePolicy();  // an older workflow shows the updater's real settings, not its stored copy
 return state.graph;
}
async function flushAutosave(){
 refuseUnresolvedSave();
 const navigation=fileNavigation;
 // A solve or edit during the save leaves the revision unacknowledged; drain it before restoring history.
 do{clearTimeout(autosaveTimer);if(!sessionDocument)return;await saveNow();}while(navigation===fileNavigation&&localDirty);
}
api.dismissSaveConflict=()=>publish({canvasSaveConflict:''});
api.resolveSaveConflict=async keep=>{
 if(!saveConflict||resolvingSaveConflict)return {cancelled:true};
 const path=saveConflict,navigation=++fileNavigation,draft=portableDocument(),snapshot=JSON.stringify(draft);
 clearTimeout(solveTimer);solveIds.clear();solveParams=[];runEpoch++;
 resolvingSaveConflict=true;publish({canvasSaveResolving:true,canvasSaveRecoveryError:''});
 try{
  if(keep&&savedConflictDraft!==snapshot){
   await sessionRequest('save',{document:draft,save_as:true,conflict_copy_of:path});
   savedConflictDraft=snapshot;
  }
  // Durable, server-side and before any reload: this page's entry for the file is resolved (copy kept or
  // changes discarded), including a failed-save state. A later genuine edit reports dirty again with a newer number.
  saveFailed=false;
  await sessionRequest('edit_state',{view:editView,file:path,seq:++editSeq,unsaved:false,resolved:keep?'keep':'discard'});
  reportedEditState=false;reportedEditFile=path;
  const opened=await sessionRequest('open',{path});
  return await adoptFile(opened.document,opened.path,navigation,snapshot);
 }catch(error){
  publish({canvasSaveRecoveryError:error.message});
  return {ok:false};
 }finally{
  resolvingSaveConflict=false;publish({canvasSaveResolving:false});
  reportEditState();  // Keep or Discard releases this page's own entry only
 }
};
api.newSession=async title=>{
 requireDesktop();
 sessionBreadcrumbs=[];publish({sessionBreadcrumbs:[]});
 const zoom=(state.settings.find(row=>row.id==='Appearance.Default zoom')?.value??100)/100;
 return adoptFile({format:'archhub',version:1,id:window.crypto.randomUUID(),title:title||'Untitled',nodes:[],wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom},properties:{viewportSaved:false}});
};
api.openSession=async(path,linked=false,linkedParams=null)=>{
 refuseUnresolvedSave();
 if(linkedParams){
  const resolved=await sessionRequest('resolve-session',{params:linkedParams});
  path=resolved.path;
 }
 if(!path&&typeof window.ARCHHUB_WINDOW_ACTION!=='function')return new Promise((resolve,reject)=>{
  const picker=document.createElement('input');picker.type='file';picker.accept='.archhub';picker.hidden=true;
  picker.onchange=()=>{const file=picker.files[0];picker.remove();if(file)api.importSession(file).then(resolve,reject);else resolve({cancelled:true});};
  picker.oncancel=()=>{picker.remove();resolve({cancelled:true});};document.body.append(picker);picker.click();
 });
 const navigation=++fileNavigation;
 // The shown document is inert while another file opens; the opened file (or a refusal or cancel) ends it.
 publish({graphOpening:true});
 try{
  const opened=await sessionRequest('open',{...(path?{path}:{})});if(opened.cancelled||navigation!==fileNavigation)return {cancelled:true};const result=await adoptFile(opened.document,opened.path,navigation);if(opened.migrationDocument)fileHistory.push(copy(opened.migrationDocument));if(!linked){sessionBreadcrumbs=[];publish({sessionBreadcrumbs:[]});}return result;
 }finally{if(navigation===fileNavigation&&state.graphOpening)publish({graphOpening:false});}
};
// Built-in starters (Book ch.12): open one as a new session file; Start also runs it to its Approve gate.
api.openStarter=async id=>{const navigation=++fileNavigation,opened=await sessionRequest('starter',{id});return adoptFile(opened.document,opened.path,navigation);};
api.startTemplate=async id=>{const opened=await api.openTemplateGraph(id);if(opened?.cancelled)return opened;await api.runNode();return {ok:true};};
api.importSession=async file=>{const navigation=++fileNavigation;if(!file.name.toLowerCase().endsWith('.archhub')||file.size>8388608)throw Error('Choose an .archhub file up to 8 MiB.');return adoptFile(JSON.parse(await file.text()),'',navigation);};
api.saveSession=async(path=sessionPath,saveAs=false)=>{
 if(sessionDocument && sessionDocument.properties?.viewportSaved!==true)api.setSessionViewport(window.UI?.requestCanvasViewport?.() || sessionDocument.viewport);
 const navigation=fileNavigation,previousPath=sessionPath,writeAccount=accountEpoch;
 if(saveAs){refuseUnresolvedSave();clearTimeout(autosaveTimer);}else await flushAutosave();
 if(navigation!==fileNavigation)return {cancelled:true};if(!saveAs&&path===previousPath)path=sessionPath;
 fileWrites=fileWrites.catch(()=>{}).then(async()=>{
 if(navigation!==fileNavigation||writeAccount!==accountEpoch||!desktopAdmitted())return {cancelled:true};
 refuseUnresolvedSave();
 const document=portableDocument(),saved=await sessionRequest('save',{path,document,save_as:saveAs,copy_source:saveAs?sessionPath:undefined,base_revision:sessionRevision,expect_existing:!!path&&path===sessionPath}).catch(error=>{rememberSaveConflict(error,path);throw error;});
 if(saved.cancelled){if(saveAs&&localDirty&&navigation===fileNavigation)queueAutosave();return saved;}if(navigation===fileNavigation&&sessionDocument.id===document.id){sessionPath=saved.path;acknowledgeSave(document,saved);queueAutosave();if(saved.issueRevision)notice('Saved '+saved.issueRevision);}return saved;
 });const saved=await fileWrites;await refreshGraphs();return saved;
};
api.saveSessionAs=()=>api.saveSession('',true);
api.getSessionDocument=()=>desktopAdmitted()?copy(portableDocument()):null;
api.pickNodeParameter=async(id,key,type)=>{
 const navigation=fileNavigation,fromDocument=sessionDocument?.nodes.some(node=>node.id===id);
 const picked=await request(type==='folder'?'/api/universal/workspace-roots':'/api/universal/pick-file',type==='folder'?{action:'browse'}:{title:'Choose '+key});if(!picked.path){if(picked.note)throw Error(picked.note);return {cancelled:true};}
 if(navigation!==fileNavigation||(fromDocument&&!sessionDocument?.nodes.some(node=>node.id===id)))throw Error('The selected node changed. Reopen its picker and retry.');
 return api.setNodeParam(id,key,picked.path);
};
api.hasSessionEdits=()=>fileHistory.length>0;
api.readSystemGraph=async()=>{
 const data=await request('/api/universal/canvas'),previous=canvas;
 try{canvas=normalise(data);systemProjection=canvas;await commands.adopt(canvas);return {nodes:canvas.nodes.map(nodeDto),wires:(canvas.wires||[]).map(w=>({id:w.id,from:w.source||w.from,to:w.target||w.to,fromPort:w.source_interface||w.fromPort,toPort:w.target_interface||w.toPort,type:w.value_type||'any'}))};}
 finally{canvas=previous;}
};
api.readAgentsGraph=async()=>{await refreshAgents();return state.agentGraph;};
api.readAgentTranscript=session=>request('/api/universal/agents-transcript',{session});
api.readStepHistory=node=>sessionRequest('agent-history',{document:portableDocument(),node});
api.setSessionViewport=viewport=>{
 if(!sessionDocument||sessionDocument.properties?.viewportSaved&&['x','y','zoom'].every(key=>sessionDocument.viewport?.[key]===viewport[key]))return;
 sessionDocument.viewport=copy(viewport);
 sessionDocument.properties={...sessionDocument.properties,viewportSaved:true};
 localDirty=true;
 publish({graph:{...state.graph,viewport:sessionDocument.viewport,viewportSaved:true},sessionDirty:true});
 queueAutosave();
};
api.addGraph=api.newSession;
api.selectGraph=path=>{
 if(path&&(path===sessionPath||path===sessionDocument?.id))return Promise.resolve(state.graph);
 return api.openSession(path);
};
api.getGraph=()=>copy(state.graph);
api.setLibraryCollapsed=async groups=>{
 if(!state.libraryCategories)await settingsAction('readLibraryCollapsed');
 if(!Array.isArray(groups)||groups.some(name=>!state.libraryCategories.includes(name)))throw Error('Unknown Library category.');
 return settingsAction('setLibraryCollapsed',[groups]);
};
api.refreshProjects=async()=>{if(!ready)await api.ready;projectFile();return copy(state.graph);};
api.tickSchedules=async()=>[];
api.refreshLibraryPorts=async()=>{
 const data=await sessionRequest('catalogue');fileDirectory=data.directory;
 publish({sessionsFolder:data.directory,libraryPorts:data.items,catalogue:data.items.map(i=>({id:i.id,name:i.title,family:i.cat,description:i.sub,unavailable:!!i.noEngine,soon:i.available===false,reason:i.reason,descriptor:{engine:i.engine}})),graphs:data.sessions.map(row=>({...row,id:row.path,name:row.title})),templates:[...state.templates.filter(row=>String(row.id).startsWith('starter:')),...data.sessions.map(row=>({...row,id:'skill:'+row.id}))]});
 projectFile();return data.items;
};
// Load built-in starters separately so opening the Library reads each saved file only once.
async function loadStarters(){
 try{const starters=starterCards(await request('/api/universal/node-library?starters=1'));
  publish({templates:[...starters,...state.templates.filter(row=>!String(row.id).startsWith('starter:'))],templateError:''});}
 catch(error){publish({templateError:error.message||'Templates could not be read. Retry All templates.'});}
}
// The Library's own loading state: waiting while the catalogue is read, then its rows, or the refusal with Retry.
api.loadLibrary=async()=>{
 publish({libraryStatus:'waiting',libraryError:''});
 try{const items=await api.refreshLibraryPorts();publish({libraryStatus:'loaded'});void loadStarters();return items;}
 catch(error){notice(error.message);publish({libraryStatus:'error',libraryError:error.message||'The Library could not be read.'});return null;}
};
async function refreshGraphs(){return refreshSessionFiles();}
const refreshSessionFiles=async()=>{const data=await sessionRequest('catalogue');publish({graphs:data.sessions.map(row=>({...row,id:row.path,name:row.title}))});return data.sessions;};
function libraryNode(item,position){return {id:window.crypto.randomUUID(),type:item.engine,item:item.id,title:item.title,pure:item.pure===true,budget:copy(item.budget||{}),...(item.engine==='script.python'?{ports:{source:[{id:'result',type:'text'}],target:[{id:'a',type:'text'}]}}:{}),...(item.loop?{loop:copy(item.loop)}:{}),params:copy(item.params),...(item.paramDefs?{paramDefs:copy(item.paramDefs)}:{}),position:{x:position.x,y:position.y??100}};}
const TRIGGER_BY_EVENT={'Manual':'tr_manual','Schedule':'tr_schedule','File changed':'tr_file','Host event':'tr_host','Approval granted':'tr_approval','Webhook':'tr_webhook'};
api.addNode=async(name,position={})=>{
 if(!sessionDocument&&desktopAdmitted())await api.newSession();
 if(!(state.libraryPorts||[]).length&&desktopAdmitted())await api.refreshLibraryPorts();
 const lookup=name==='Trigger'?'tr_manual':(TRIGGER_BY_EVENT[name]||name);
 const item=(state.libraryPorts||[]).find(i=>i.id===lookup||i.title===lookup||i.id===name||i.title===name);
 if(!item||item.noEngine||item.available===false)throw Error(item?.reason||'Choose an executable Library node.');
 // NODEPLACE: a placed card holds its spot until it is painted, so concurrent adds never take the same one.
 const scope=scopeEpoch+':'+state.graph.id;let reservation=null;
 if(position.x===undefined){const detail={reserved:[...insertionReservations].filter(point=>point.scope===scope),point:null,error:null};window.dispatchEvent(new CustomEvent('archhub:canvas-insertion',{detail}));if(detail.error)throw Error(detail.error);position=detail.point||{x:80,y:100};if(detail.point){reservation={...detail.point,scope};insertionReservations.add(reservation);}}
 try{
  if(item.engine==='skill'&&item.params.session_file)return await api.insertSession(item.params.session_file,position);
  const node=libraryNode(item,position),shown=()=>state.graph.nodes.find(n=>n.id===node.id);
  fileEdit(d=>d.nodes.push(node),[node.id]);
  // Once painted, the Canvas places the card again by its real height; a navigation in between leaves it where it is.
  if(reservation&&!document.hidden&&window.requestAnimationFrame){
   await new Promise(resolve=>{const timer=setTimeout(resolve,Number(state.canvasPolicy?.viewport_commit_debounce_ms??140));window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{clearTimeout(timer);resolve();}));});
   if(scope!==scopeEpoch+':'+state.graph.id||document.hidden||!sessionDocument?.nodes.some(n=>n.id===node.id))return shown();
   const detail={reserved:[...insertionReservations].filter(point=>point!==reservation&&point.scope===scope),nodeId:node.id,point:null,error:null};
   window.dispatchEvent(new CustomEvent('archhub:canvas-insertion',{detail}));
   if(detail.point&&(detail.point.x!==position.x||detail.point.y!==position.y))await api.moveNodes({[node.id]:{x:detail.point.x,y:detail.point.y}});
   if(detail.point)Object.assign(reservation,detail.point);
  }
  if(reservation?.offscreen)notice('Added off-screen — '+reservation.offscreen);
  return shown();
 }finally{if(reservation)insertionReservations.delete(reservation);}
};
api.moveNode=(id,position)=>api.moveNodes({[id]:position});
// afterPaint (a canvas drop): the file edit now, the redraw after the drop's frame is painted.
api.moveNodes=async(positions,afterPaint=false)=>fileEdit(d=>{
 const changes={...positions};
 const move=(id,dx,dy)=>{const node=d.nodes.find(n=>n.id===id);if(!node||changes[id])return;changes[id]={x:node.position.x+dx,y:node.position.y+dy};for(const child of node.children||node.frameMembers||[])move(child,dx,dy);};
 for(const [id,point] of Object.entries(positions)){const node=d.nodes.find(n=>n.id===id);if(node)for(const child of node.children||node.frameMembers||[])move(child,point.x-node.position.x,point.y-node.position.y);}
 for(const [id,point] of Object.entries(changes)){const node=d.nodes.find(n=>n.id===id);if(node)node.position={x:point.x,y:point.y};}
},null,null,true,false,afterPaint);
api.setNodeParam=async(id,key,value)=>{
 if(!sessionDocument.nodes.some(n=>n.id===id)&&systemProjection?.nodes.some(n=>n.id===id)){try{await commands.adopt(systemProjection);const result=await nodeProperty(id,key,value);systemProjection=commands.getSnapshot().canvas;publish({systemRevision:(state.systemRevision||0)+1});return result;}finally{projectFile();}}
 const held=sessionDocument.nodes.find(n=>n.id===id);
 // The inspector shows this parameter read-only (fileNode editable:false): every caller gets the same refusal.
 if(held&&state.graph.nodes.find(n=>n.id===id)?.parameterSchema?.some(p=>p.key===key&&p.editable===false))throw Error('This parameter is read-only.');
 if(held?.type==='thing.setting'&&held.params.setting&&key==='value'){await api.setSetting(held.params.setting,value);return state.graph.nodes.find(n=>n.id===id);}
 // The Workshop node's update parameters are the Settings owner's values: an explicit edit writes that owner first.
 if(held&&held.params?.tool==='workshop'&&UPDATE_POLICY_KEYS.includes(key))await api.setApplicationSetting(key,value);
 const sessionItem=held?.type==='thing.session'&&!(held.paramDefs||[]).length&&(state.libraryPorts||[]).find(row=>row.engine==='thing.session');
 if(sessionItem?.paramDefs?.some(d=>d.id===key)){  // the first edit of a session from before its panel values: they join the file with it
  fileEdit(d=>{const n=d.nodes.find(n=>n.id===id);n.paramDefs=copy(sessionItem.paramDefs);for(const def of sessionItem.paramDefs)if(!Object.hasOwn(n.params,def.id))n.params[def.id]=copy(sessionItem.params[def.id]);n.params[key]=value;},[id],{node:id,key,value});
  return state.graph.nodes.find(n=>n.id===id);}
 if(held&&held.type?.startsWith('trigger.')&&key==='event'&&Object.hasOwn(TRIGGER_BY_EVENT,value)){
  if(!(state.libraryPorts||[]).length&&desktopAdmitted())await api.refreshLibraryPorts();
  const targetItem=(state.libraryPorts||[]).find(i=>i.id===TRIGGER_BY_EVENT[value]);
  if(targetItem){
   fileEdit(d=>{const n=d.nodes.find(row=>row.id===id);if(!n)throw Error('Choose a node in this workflow.');n.type=targetItem.engine;n.item=targetItem.id;n.title=targetItem.title;n.params={...copy(targetItem.params),event:Object.hasOwn(targetItem.params,'event')?(n.params.event&&!Object.hasOwn(TRIGGER_BY_EVENT,n.params.event)?n.params.event:targetItem.params.event):value};},[id],{node:id,key,value});
   return state.graph.nodes.find(n=>n.id===id);
  }
 }
 if(held&&(held.type==='param.value'||(held.paramDefs||[]).some(d=>d.id===key))){await paramOp('set',[id,key,value]);return state.graph.nodes.find(n=>n.id===id);}
 fileEdit(d=>{const n=d.nodes.find(n=>n.id===id);if(!n||!Object.hasOwn(n.params,key))throw Error('Parameter is absent');n.params[key]=value;},[id],{node:id,key,value});return state.graph.nodes.find(n=>n.id===id);};
async function paramOp(op,args){
 const navigation=fileNavigation;
 const document=portableDocument();
 const result=await sessionRequest('param-op',{document,op,args});
 if(navigation!==fileNavigation)throw Error('The open document changed before the parameter edit finished.');
 // A move during the round trip is layout only: the parameter edit still lands and the move is kept.
 const shape=nodes=>JSON.stringify(nodes.map(({position,...node})=>node));
 if(shape(document.nodes)!==shape(sessionDocument.nodes)||JSON.stringify(document.wires)!==JSON.stringify(sessionDocument.wires))throw Error('The canvas changed during the parameter edit. Retry the edit.');
 const moved=new Map(sessionDocument.nodes.map(node=>[node.id,node.position]));
 fileEdit(d=>{d.nodes=result.document.nodes.map(node=>moved.has(node.id)?{...node,position:moved.get(node.id)}:node);d.wires=result.document.wires;},result.changed);
 return result;
}
api.addNodeParameter=async(id,input={})=>{
 const name=String(input.name||input.label||'').trim(),type=input.type&&input.type!=='All'?input.type:'text';
 if(!name)throw Error('Name the parameter.');
 const limits=Object.fromEntries(Object.entries({min:input.min,max:input.max,step:input.step,unit:input.unit,options:input.options,show_as_node:input.showAsNode===true}).filter(([,v])=>v!==undefined&&v!==''));
 await paramOp('add',[id,name,type,input.value??'',limits]);
 return state.graph.nodes.find(n=>n.id===id);
};
// +Field / +Record / cells: one implementation on the server (node_datasets.py); a cell edit re-solves downstream.
async function datasetOp(op,args,options={}){
 const result=await sessionRequest('dataset-op',{document:portableDocument(),op,args,options});
 fileEdit(d=>{d.nodes=result.document.nodes;d.wires=result.document.wires;},result.changed);
 return result;
}
api.addDatasetField=async(id,input={})=>{
 const name=String(input.name||'').trim(),type=input.type||'number';
 if(!name)throw Error('Name the field.');
 const options=Object.fromEntries(Object.entries({unit:input.unit,options:input.options,min:input.min,max:input.max,step:input.step}).filter(([,v])=>v!==undefined&&v!==''));
 await datasetOp('add-field',[id,name,type,input.value??''],options);
 if(input.showAsNode){const held=sessionDocument.nodes.find(n=>n.id===id);await datasetOp('expose-field',[id,held.paramDefs[held.paramDefs.length-1].id]);}
 return state.graph.nodes.find(n=>n.id===id);
};
api.addDatasetRecord=async(id,cells={})=>{await datasetOp('add-record',[id,cells]);return state.graph.nodes.find(n=>n.id===id);};
api.setDatasetCell=async(id,record,field,value)=>{await datasetOp('set-cell',[id,record,field,value]);return state.graph.nodes.find(n=>n.id===id);};
api.exposeDatasetField=async(id,field)=>{const result=await datasetOp('expose-field',[id,field]);return state.graph.nodes.find(n=>n.id===result.changed[0]);};
async function memberOp(op,args){
 const result=await sessionRequest('member-op',{document:portableDocument(),op,args});
 fileEdit(d=>{d.nodes=result.document.nodes;d.wires=result.document.wires;});
 return result;
}
api.detachMember=async(groupId,member,point)=>memberOp('detach',[groupId,member,point&&point.x||0,point&&point.y||0]);
api.attachMember=async(groupId,nodeId)=>memberOp('attach',[groupId,nodeId]);
api.promoteParam=async(id,key)=>{await paramOp('promote',[id,key]);return state.graph.nodes.find(n=>n.id===id);};
api.demoteParam=async(id,key)=>{await paramOp('demote',[id,key]);return state.graph.nodes.find(n=>n.id===id);};
api.parameterTypes=()=>[...PARAM_TYPES];
api.resetNodeParam=(id,key)=>api.setNodeParam(id,key,state.graph.nodes.find(n=>n.id===id)?.defaults[key]);
api.setNodePresentation=async(id,values)=>{
 if(!values||typeof values!=='object'||Array.isArray(values)||Object.keys(values).some(key=>!['icon','color'].includes(key))||('icon'in values&&values.icon!==''&&!NODE_ICONS.includes(values.icon))||('color'in values&&!/^#[0-9a-f]{6}$/i.test(values.color)))throw Error('Choose an approved icon and a six-digit colour.');
 return fileEdit(d=>{const node=d.nodes.find(n=>n.id===id);if(!node)throw Error('Choose a node in this workflow.');Object.assign(node,values);});
};
api.renameNode=async(id,title)=>fileEdit(d=>{const n=d.nodes.find(n=>n.id===id);if(n)n.title=title;});
api.deleteSelection=async(nodes=[],wires=[])=>{
 const navigation=fileNavigation;await flushAutosave();if(navigation!==fileNavigation)return {cancelled:true};
 if(sessionDocument.nodes.some(node=>node.fixed&&nodes.includes(node.id)))throw Error('The four fixed nodes stay on every task canvas.');
 const removedNodes=new Set(nodes),removedWires=new Set(wires),removed=w=>removedWires.has(w.id)||removedNodes.has(w.from.node)||removedNodes.has(w.to.node);
 return fileEdit(d=>{
  d.nodes=d.nodes.filter(n=>!removedNodes.has(n.id));d.wires=d.wires.filter(w=>!removed(w));
  for(const n of d.nodes){if(n.children)n.children=n.children.filter(id=>!removedNodes.has(id));if(n.frameMembers)n.frameMembers=n.frameMembers.filter(id=>!removedNodes.has(id));if(removedNodes.has(n.parent))delete n.parent;}
  d.groups=d.groups.filter(g=>!removedNodes.has(g.id)).map(g=>({...g,nodes:g.nodes.filter(id=>!removedNodes.has(id))}));
 },sessionDocument.wires.filter(removed).map(w=>w.to.node));
};
api.deleteNode=async id=>api.deleteSelection([id]);
api.deleteWire=async id=>api.deleteSelection([],[id]);
api.connectSockets=async wire=>{
 for(const [side,ports] of [['from','outputs'],['to','inputs']]){const node=state.graph.nodes.find(n=>n.id===wire[side]),port=node?.[ports].find(p=>p.id===wire[side+'Port']);if(port?.member)wire={...wire,[side]:port.member.node,[side+'Port']:port.member.port};}
 const from=state.graph.nodes.find(n=>n.id===wire.from),to=state.graph.nodes.find(n=>n.id===wire.to),out=from?.outputs.find(p=>p.id===wire.fromPort),input=to?.inputs.find(p=>p.id===wire.toPort);
 if(!out||!input||from.id===to.id)throw Error('Choose an output and another node input.');
 if(!api.socketCompatible(out,input)){throw Error('Wrong type: a '+out.type+' output cannot feed a '+input.type+' input. Insert Convert.');}
 if(sessionDocument.wires.some(w=>w.to.node===to.id&&w.to.socket===input.id))throw Error('Disconnect the existing input wire first.');
 const reaches=new Set([to.id]);let changed=true;while(changed){changed=false;for(const w of sessionDocument.wires)if(reaches.has(w.from.node)&&!reaches.has(w.to.node)){reaches.add(w.to.node);changed=true;}}
 if(reaches.has(from.id))throw Error('Cycle detected: disconnect a feedback wire first.');
 return fileEdit(d=>d.wires.push({id:window.crypto.randomUUID(),from:{node:from.id,socket:out.id},to:{node:to.id,socket:input.id}}),[to.id]);
};
api.runNode=async(id,again=false)=>{
 const navigation=fileNavigation;clearTimeout(solveTimer);await runSolve();await flushAutosave();if(navigation!==fileNavigation)return {cancelled:true};
 const epoch=++runEpoch,document=portableDocument();
 const seen=new Set(),expand=key=>{if(seen.has(key))return [];seen.add(key);const node=document.nodes.find(n=>n.id===key),members=node?.children?.length?node.children:node?.frameMembers;return members?.length?members.flatMap(expand):[key];};
 const roots=id?(Array.isArray(id)?id:[id]).flatMap(expand):null;
 if(roots && (!roots.length || roots.some(key=>!document.nodes.some(n=>n.id===key))))throw Error('Choose an existing node to run.');
 const targets=roots && new Set(roots);
 const inRun=node=>!targets || targets.has(node.id);
 publish({graph:{...state.graph,nodes:state.graph.nodes.map(node=>inRun(node)?{...node,status:'Running'}:node)}});

 try{const result=await sessionRequest('run',{document,path:sessionPath,again,...(roots?{roots}:{})});if(epoch!==runEpoch)throw Error('Session changed during Run; run the new values again.');
  if(result.document){sessionDocument=copy(result.document);sessionRevision=result.revision;}else if(result.run)sessionDocument.properties.canvasRun=copy(result.run);
  for(const node of sessionDocument.nodes)if(result.results[node.id])node.result=result.results[node.id];projectFile();queueAutosave();if(result.approvalId){await refreshApprovals();await refreshNotifications();}const lines=Object.fromEntries(Object.entries(result.results||{}).filter(([nid,val])=>{const n=sessionDocument.nodes.find(x=>x.id===nid);return (n?.type==='watch.preview'||n?.params?.engine==='lines.watch')&&Array.isArray(val?.output);}).map(([nid,val])=>[nid,val.output]));const run={id:window.crypto.randomUUID(),title:sessionDocument.title,status:result.succeeded?'Done':'Needs review',rows:Object.entries(result.results).map(([node,value])=>({node:state.graph.nodes.find(n=>n.id===node)?.title||node,status:value.status,output:JSON.stringify(value.output),error:value.error||''}))};publish({lastResult:run,runs:[...state.runs,run]});return {...result,lines,id:run.id};
 }catch(error){if(epoch===runEpoch){for(const node of sessionDocument.nodes)if(inRun(node))node.result={status:'Error',error:error.message};projectFile();queueAutosave();}throw error;}
};
api.runToHere=api.runNode;
api.recoverRun=async(node,decision)=>{
 const result=await sessionRequest('recover-run',{path:sessionPath,node,decision});
 sessionDocument=copy(result.document);sessionRevision=result.revision;projectFile();
 if(decision==='retry')return api.runNode(node);
 return result;
};
api.runSelection=ids=>api.runNode(ids);
api.setNodeFlags=async(id,values)=>fileEdit(d=>{const n=d.nodes.find(row=>row.id===id);if(!n)throw Error('Choose a node in this workflow.');for(const [k,v] of Object.entries(values||{})){if(v===null||v===undefined||k==='color'&&v==='')delete n[k];else n[k]=v;}},[id]);
api.setPinnedOutput=async(id,raw)=>{
 let parsed;try{parsed=typeof raw==='string'?JSON.parse(raw):raw;}catch{throw Error('Enter valid JSON before pinning node output.');}
 await fileEdit(d=>{const n=d.nodes.find(row=>row.id===id);if(!n)throw Error('Choose a node in this workflow.');n.pinned=true;n.result={...(n.result||{}),status:n.result?.status&&n.result.status!=='Idle'?n.result.status:'Done',error:'',output:parsed};},[id]);
 return state.graph.nodes.find(n=>n.id===id);
};
api.traceNode=(id,direction)=>canvasOperation('trace_node',sessionDocument?[id,direction,portableDocument()]:[id,direction]);
api.forkNode=async id=>{const result=await sessionRequest('fork-node',{document:portableDocument(),node:id});fileEdit(d=>{d.nodes=result.document.nodes;d.wires=result.document.wires;});return state.graph.nodes.find(n=>n.id===result.ids[0]);};
// Arrangement changes presentation only; keep in-flight pure-node results.
// Tidy up arranges the document; the first view of a never-arranged file is arranged on screen only (opening never writes).
const arrangeDocument=d=>{
 const session=d.nodes.find(n=>n.fixed&&n.type==='thing.session'),nodes=d.nodes.filter(n=>(!n.fixed&&(!session||(n.agentWork?.role!=='session'||n.params?.workshop_step&&!d.nodes.some(row=>row.agentWork?.owner===n.id)))||n===session)&&!n.parent),ids=new Set(nodes.map(n=>n.id));
 const incoming=new Map(nodes.map(n=>[n.id,[]])),rank=new Map(),order=new Map(nodes.map((n,i)=>[n.id,i])),was=new Map(nodes.map(n=>[n.id,n.position]));
 for(const w of d.wires)if(ids.has(w.from.node)&&ids.has(w.to.node))incoming.get(w.to.node).push(w.from.node);
 const left=nodes.filter(n=>n!==session&&session&&incoming.get(session.id).includes(n.id));
 const pending=new Set(nodes.filter(n=>!left.includes(n)).map(n=>n.id));
 if(session){rank.set(session.id,0);pending.delete(session.id);}
 for(const n of left)rank.set(n.id,-1);
 while(pending.size){let changed=false;for(const id of pending){const sources=incoming.get(id);if(sources.every(key=>rank.has(key))){rank.set(id,Math.max(session&&id!==session.id?1:0,...sources.map(key=>rank.get(key)+1)));pending.delete(id);changed=true;}}if(!changed){for(const id of pending)rank.set(id,session&&id!==session.id?1:0);break;}}
 const columns=[];
 for(const n of nodes.filter(n=>!left.includes(n))){const r=rank.get(n.id);(columns[r]||=[]).push(n);}
 const rendered=new Map([...(document.querySelectorAll?.('[data-graph-node]') || [])].map(el=>[el.dataset.graphNode,{w:el.offsetWidth||300,h:el.offsetHeight||160}]));
 const size=n=>rendered.get(n.id)||{w:300,h:160};
 const grid=v=>Math.round(v/8)*8,y0=grid(session?.position.y||0);let x=grid(session?.position.x||0);
 if(left.length){let y=y0;const width=Math.max(...left.map(n=>size(n).w));for(const n of left){n.position={x:grid(x-width-96),y:grid(y)};y+=size(n).h+32;}}
 for(const column of columns){if(!column)continue;column.sort((a,b)=>{const source=n=>incoming.get(n.id).reduce((sum,id)=>sum+nodes.find(n=>n.id===id).position.y,0)/Math.max(1,incoming.get(n.id).length);return source(a)-source(b)||order.get(a.id)-order.get(b.id);});let y=y0;for(const n of column){n.position={x:grid(x),y:grid(y)};y+=size(n).h+32;}x+=Math.max(...column.map(n=>size(n).w))+96;}
 // A group's members keep their place inside it: they move with their group, so its frame stays around them.
 const follow=(id,dx,dy)=>{for(const child of d.nodes)if(child.parent===id){child.position={x:child.position.x+dx,y:child.position.y+dy};follow(child.id,dx,dy);}};
 for(const n of nodes){const p=was.get(n.id);if(!n.fixed&&n.children?.length&&(n.position.x!==p.x||n.position.y!==p.y))follow(n.id,n.position.x-p.x,n.position.y-p.y);}
 d.properties={...d.properties,canvasLayout:'v48'};
};
// Only his Tidy up arranges: an open shows the saved places, and no edit writes an arrangement he did not ask for.
api.arrangeGraph=async()=>fileEdit(arrangeDocument,null,null,true,true);
api.groupNodes=async ids=>{
 if(!Array.isArray(ids))throw Error('Choose nodes to group.');
 const members=sessionDocument.nodes.filter(n=>ids.includes(n.id));
 if(new Set(ids).size!==ids.length||members.length!==ids.length||ids.length<1||members.some(n=>n.fixed)||new Set(members.map(n=>n.parent||'')).size!==1)throw Error('Choose editable nodes in the same group.');
 // One node from several: the group starts collapsed and carries every member socket (projectGroups).
 const node={id:window.crypto.randomUUID(),type:'note',title:'Group',params:{},...(members[0].parent?{parent:members[0].parent}:{}),children:[...ids],collapsed:true};
 // Its origin is measured inside the edit: the first edit turns the on-screen arrangement into the document, and the frame sits around the members where they are then.
 fileEdit(d=>{node.position={x:Math.min(...members.map(n=>n.position.x))-24,y:Math.min(...members.map(n=>n.position.y))-44};d.nodes.push(node);const parent=d.nodes.find(n=>n.id===node.parent);if(parent?.children)parent.children=[...parent.children.filter(id=>!ids.includes(id)),node.id];const listing=d.groups.find(g=>g.id===node.parent);if(listing)listing.nodes=[...listing.nodes.filter(id=>!ids.includes(id)),node.id];for(const n of members)n.parent=node.id;d.groups.push({id:node.id,nodes:[...ids]});});
 return state.graph.nodes.find(n=>n.id===node.id);
};
api.ungroupNode=async id=>{
 const navigation=fileNavigation;await flushAutosave();if(navigation!==fileNavigation)return {cancelled:true};
 const group=sessionDocument.nodes.find(n=>n.id===id);
 if(!group||group.fixed||!group.children?.length&&!group.frameMembers)throw Error('Choose an editable group.');
 const projected=state.graph.nodes.find(n=>n.id===id);
 const incoming=new Set();
 const wires=sessionDocument.wires.map(wire=>{
  const updated={...wire};
  for(const [end,ports] of [['from','outputs'],['to','inputs']]){
   if(wire[end].node!==id)continue;
   const member=projected?.[ports].find(port=>port.id===wire[end].socket)?.member;
   if(!member)throw Error('A group wire has no matching member socket: '+wire[end].socket);
   updated[end]={node:member.node,socket:member.port};
  }
  const target=JSON.stringify([updated.to.node,updated.to.socket]);
  if(incoming.has(target))throw Error('Two wires point to the same member input.');
  incoming.add(target);
  return updated;
 });
 return fileEdit(d=>{d.wires=wires;for(const n of d.nodes)if(n.parent===id){if(group.parent)n.parent=group.parent;else delete n.parent;}d.nodes=d.nodes.filter(n=>n.id!==id);d.groups=d.groups.filter(g=>g.id!==id);for(const n of d.nodes)if(n.children?.includes(id))n.children=n.children.flatMap(child=>child===id?group.children||[]:[child]);for(const g of d.groups)g.nodes=g.nodes.flatMap(child=>child===id?group.children||[]:[child]);});
};
api.setGroupCollapsed=async(id,collapsed)=>fileEdit(d=>{const node=d.nodes.find(n=>n.id===id);if(!node?.children?.length||node.fixed)throw Error('Choose an editable group.');node.collapsed=!!collapsed;});
api.setScriptPorts=async(id,ports,rename)=>{
 const node=sessionDocument.nodes.find(n=>n.id===id);
 if(node?.type!=='script.python')throw Error('Choose a Script node.');
 for(const side of ['source','target'])if(!Array.isArray(ports[side])||new Set(ports[side].map(p=>p.id)).size!==ports[side].length||ports[side].some(p=>!/^[_a-zA-Z][_a-zA-Z0-9]*$/.test(p.id)||p.id.startsWith('_')||!['text','number','file','elements','color','event','any'].includes(p.type)))throw Error('Use unique socket names and a supported type.');
 if(!ports.source.length)throw Error('Keep at least one output.');
 return fileEdit(d=>{const n=d.nodes.find(n=>n.id===id),old=n.ports;if(rename){if(!["source","target"].includes(rename.side)||!old[rename.side].some(p=>p.id===rename.from)||!ports[rename.side].some(p=>p.id===rename.to))throw Error("Choose the socket to rename.");for(const w of d.wires){const end=rename.side==="source"?w.from:w.to;if(end.node===id&&end.socket===rename.from)end.socket=rename.to;if(end.node===id&&end.socket==="param:"+rename.from)end.socket="param:"+rename.to;}if(rename.side==="target"){n.params[rename.to]=n.params[rename.from];delete n.params[rename.from];for(const d of n.paramDefs||[])if(d.id===rename.from){d.id=rename.to;d.name=rename.to;}}}n.ports=copy(ports);for(const p of ports.target){const kind=['number','file'].includes(p.type)?p.type:'text';const def=(n.paramDefs||[]).find(d=>d.id===p.id);if(def)def.type=kind;else(n.paramDefs||=[]).push({id:p.id,name:p.id,type:kind});if(!Object.hasOwn(n.params,p.id)||n.params[p.id]==='')n.params[p.id]=kind==='number'?0:'';}for(const p of old?.target||[])if(!ports.target.some(row=>row.id===p.id)){delete n.params[p.id];n.paramDefs=(n.paramDefs||[]).filter(d=>d.id!==p.id);}d.wires=d.wires.filter(w=>(w.from.node!==id||ports.source.some(p=>p.id===w.from.socket))&&(w.to.node!==id||ports.target.some(p=>p.id===w.to.socket)||w.to.socket.startsWith('param:')));},[id]);
};
api.scanNodeType=(ids,name,category,publicParameters)=>sessionRequest('scan-node-type',{document:portableDocument(),ids,name,category,public:publicParameters});
api.saveNodeType=async(ids,name,category,publicParameters,kind)=>{const result=await sessionRequest('save-node-type',{document:portableDocument(),ids,name,category,public:publicParameters,kind});await api.refreshLibraryPorts();return result;};
let copiedNodes=null;
api.hasCopiedNodes=()=>!!copiedNodes;
api.copyNodes=async ids=>{
 const selected=new Set(ids),include=id=>{const node=sessionDocument.nodes.find(n=>n.id===id);for(const child of [...(node?.children||[]),...(node?.frameMembers||[])]){if(selected.has(child))continue;selected.add(child);include(child);}};
 for(const id of ids)include(id);
 const nodes=sessionDocument.nodes.filter(n=>selected.has(n.id));
 if(!nodes.length||nodes.some(n=>n.fixed))throw Error('Choose editable nodes to copy.');
 copiedNodes={path:sessionPath,nodes:copy(nodes),wires:copy(sessionDocument.wires.filter(w=>selected.has(w.from.node)&&selected.has(w.to.node))),groups:copy(sessionDocument.groups.filter(g=>selected.has(g.id)))};
 return {ok:true};
};
api.pasteNodes=async point=>{
 if(!copiedNodes)throw Error('Copy nodes from a canvas first.');
 const source=copy(copiedNodes),navigation=fileNavigation;
 const watchers=source.nodes.filter(node=>node.type==='trigger.file'&&typeof node.params.folder==='string'&&node.params.folder);
 if(source.path&&source.path!==sessionPath&&watchers.length){
  const {folders}=await sessionRequest('copy-watch-folders',{source_path:source.path,folders:watchers.map(node=>node.params.folder)});
  if(navigation!==fileNavigation)return {cancelled:true};
  watchers.forEach((node,index)=>{node.params.folder=folders[index];});
 }
 const ids=new Map(source.nodes.map(n=>[n.id,window.crypto.randomUUID()])),dx=(point?.x??Math.min(...source.nodes.map(n=>n.position.x))+32)-Math.min(...source.nodes.map(n=>n.position.x)),dy=(point?.y??Math.min(...source.nodes.map(n=>n.position.y))+32)-Math.min(...source.nodes.map(n=>n.position.y));
 for(const node of source.nodes)if(node.type==='trigger.schedule'||node.type==='trigger.file')node.params.armed=false;
 for(const n of source.nodes){n.id=ids.get(n.id);n.position={x:n.position.x+dx,y:n.position.y+dy};delete n.result;delete n.taskContext;delete n.workshopTask;if(n.parent&&ids.has(n.parent))n.parent=ids.get(n.parent);else delete n.parent;if(n.children)n.children=n.children.map(id=>ids.get(id));if(n.frameMembers)n.frameMembers=n.frameMembers.filter(id=>ids.has(id)).map(id=>ids.get(id));if(n.bind&&ids.has(n.bind.node))n.bind.node=ids.get(n.bind.node);for(const p of n.paramDefs||[])if(p.promoted)p.promoted=ids.get(p.promoted)||null;}
 for(const w of source.wires){w.id=window.crypto.randomUUID();w.from.node=ids.get(w.from.node);w.to.node=ids.get(w.to.node);}
 fileEdit(d=>{d.nodes.push(...source.nodes);d.wires.push(...source.wires);d.groups.push(...source.groups.map(g=>({...g,id:ids.get(g.id),nodes:g.nodes.map(id=>ids.get(id))})));},source.nodes.map(n=>n.id));
 return {ids:source.nodes.filter(n=>!n.parent).map(n=>n.id)};
};
api.duplicateNodes=async ids=>{await api.copyNodes(ids);return api.pasteNodes();};
api.cutNodes=async ids=>{await api.copyNodes(ids);return api.deleteSelection(copiedNodes.nodes.map(n=>n.id));};
api.deleteGroup=async id=>{await api.copyNodes([id]);return api.deleteSelection(copiedNodes.nodes.map(n=>n.id));};
api.addNote=async(text,position={x:80,y:100})=>{
 if(typeof text!=='string'||!text.trim())throw Error('Write a note first.');
 const node={id:window.crypto.randomUUID(),type:'note',title:'Note',params:{text:text.trim()},position};fileEdit(d=>d.nodes.push(node));return node;
};
api.alignNodes=async(ids,axis)=>{
 if(!['x','y'].includes(axis))throw Error('Choose left or top alignment.');
 const nodes=sessionDocument.nodes.filter(n=>ids.includes(n.id));if(nodes.length<2||nodes.some(n=>n.fixed))throw Error('Choose two editable nodes.');
 const at=Math.min(...nodes.map(n=>n.position[axis]));return api.moveNodes(Object.fromEntries(nodes.map(n=>[n.id,{...n.position,[axis]:at}])));
};
api.undo=async()=>{const navigation=fileNavigation;await flushAutosave();if(navigation!==fileNavigation)return {cancelled:true};if(fileHistory.length){fileFuture.push(copy(sessionDocument));sessionDocument=fileHistory.pop();localDirty=true;runEpoch++;projectFile();queueAutosave();scheduleSolve(sessionDocument.nodes.map(n=>n.id),null);}return {ok:true};};
api.redo=async()=>{const navigation=fileNavigation;await flushAutosave();if(navigation!==fileNavigation)return {cancelled:true};if(fileFuture.length){fileHistory.push(copy(sessionDocument));sessionDocument=fileFuture.pop();localDirty=true;runEpoch++;projectFile();queueAutosave();scheduleSolve(sessionDocument.nodes.map(n=>n.id),null);}return {ok:true};};
api.wireMenus=WIRE_MENUS;
api.setWireRule=async(id,rule)=>{const wire=sessionDocument.wires.find(w=>w.id===id);if(!wire)throw Error('Choose a wire.');const checked=await sessionRequest('wire-rule',{document:portableDocument(),id,rule});return fileEdit(d=>{const current=d.wires.find(w=>w.id===id);if(!current)throw Error('This wire was removed.');current.rule=checked.rule;},[wire.to.node]);};
api.setWireEnabled=async(id,enabled)=>{const wire=sessionDocument.wires.find(w=>w.id===id);if(!wire||typeof enabled!=='boolean')throw Error('Choose a wire and its enabled state.');return fileEdit(d=>{const w=d.wires.find(w=>w.id===id);if(enabled)delete w.enabled;else w.enabled=false;},[wire.to.node]);};
api.insertNodeOnWire=async(id,name,point)=>{
 const wire=sessionDocument.wires.find(w=>w.id===id),item=(state.libraryPorts||[]).find(i=>i.id===name||i.title===name),from=state.graph.nodes.find(n=>n.id===wire?.from.node),to=state.graph.nodes.find(n=>n.id===wire?.to.node);
 if(!wire||!item||item.noEngine||!from||!to)throw Error('Choose a wire and an executable node.');
 const node=libraryNode(item,point||{x:(from.x+to.x)/2,y:(from.y+to.y)/2+120});
 if(item.engine==='data.convert')node.params.target_type=to.inputs.find(p=>p.id===wire.to.socket)?.type==='number'?'number':'text';
 const projected=fileNode(node),out=from.outputs.find(p=>p.id===wire.from.socket),input=to.inputs.find(p=>p.id===wire.to.socket),into=projected.inputs.find(p=>api.socketCompatible(out,p)),away=projected.outputs.find(p=>api.socketCompatible(p,input));
 if(!into||!away)throw Error('This node has no compatible input and output for this wire.');
 fileEdit(d=>{d.nodes.push(node);d.wires=d.wires.filter(w=>w.id!==id);d.wires.push({...copy(wire),id:window.crypto.randomUUID(),to:{node:node.id,socket:into.id}},{id:window.crypto.randomUUID(),from:{node:node.id,socket:away.id},to:copy(wire.to)});},[node.id,to.id]);
 return state.graph.nodes.find(n=>n.id===node.id);
};
api.insertConvertOnWire=id=>api.insertNodeOnWire(id,'data.convert');
api.setWireParam=async(id,key,value)=>{
 if(!sessionDocument)throw Error('Open a session first.');
 const current=sessionDocument.wires.find(w=>w.id===id);
 if(!current)throw Error('Wire is absent');
 const menu=WIRE_MENUS.find(row=>row[0]===key);
 if(!menu||!menu[1].includes(value))throw Error('That is not a choice for this wire parameter');
 return fileEdit(d=>{const w=d.wires.find(item=>item.id===id);if(value===menu[1][0])delete w[key];else w[key]=value;},[current.to.node]);
};
api.setWireVisibility=async value=>fileEdit(d=>{d.properties={...d.properties,wireVisibility:value};});
api.setPortVisibility=async(id,port,value)=>fileEdit(d=>{const n=d.nodes.find(n=>n.id===id);n.portVisibility={...n.portVisibility,[port]:value};});
api.setPromotedParameter=async(id,key,value)=>fileEdit(d=>{const n=d.nodes.find(n=>n.id===id);n.parameterPresentation={...n.parameterPresentation,[key]:value};});
api.updateGraph=async(id,values)=>{
 if(!values||typeof values!=='object'||Array.isArray(values))throw Error('Choose workflow properties to update.');
 if(id&&sessionDocument&&id!==sessionDocument.id&&!api.sameSessionPath(id,sessionPath)){
  const result=await canvasOperation('update_graph',[id,values.name??null,values.pinned??null]);
  await refreshGraphs();
  return result;
 }
 const out=await fileEdit(d=>{if(values.name)d.title=values.name;d.properties={...d.properties,...values};});
 if(sessionPath)void flushAutosave().then(()=>refreshGraphs()).catch(()=>{});
 return out;
};
api.removeGraph=async id=>{
 const removingOpen=sessionDocument&&(id===sessionDocument.id||api.sameSessionPath(id,sessionPath));
 if(removingOpen){clearTimeout(autosaveTimer);autosaveTimer=null;await fileWrites.catch(()=>{});}
 const result=await canvasOperation('remove_graph',[id]);
 if(removingOpen){sessionDocument=null;sessionPath='';localDirty=false;fileHistory=[];fileFuture=[];await api.newSession();}
 await refreshGraphs();
 return result;
};
api.exportRecipe=async()=>portableDocument();
api.solveNow=()=>runSolve();api.getSessionPath=()=>desktopAdmitted()?sessionPath:'';
api.saveSkill=async name=>{if(name)fileEdit(d=>{d.title=String(name).trim()||d.title;});const saved=await api.saveSession();await api.refreshLibraryPorts();return saved;};
api.openTemplateGraph=async id=>{const row=state.templates.find(t=>t.id===id);if(row?.path)return api.openSession(row.path);return api.openStarter(id);};
api.readSessionsFolder=()=>settingsAction('readSessionsFolder').then(result=>{publish({sessionsFolder:result.sessionsFolder});return result;});
api.chooseSessionsFolder=async()=>{await flushAutosave();const result=await settingsAction('setSessionsFolder',[]);sessionPath=result.moved?.find(([old])=>old===sessionPath)?.[1]||sessionPath;publish({sessionsFolder:result.sessionsFolder,sessionFile:sessionPath});await api.refreshLibraryPorts();return result;};
window.addEventListener('pagehide',()=>{if(desktopAdmitted()&&sessionDocument&&localDirty&&!saveConflict){const body=JSON.stringify({action:'autosave',document:portableDocument(),path:sessionPath,base_revision:sessionRevision});fetch('/api/session-files',{method:'POST',headers:{'Content-Type':'application/json','X-ArchHub-Session':session?.token||'','X-ArchHub-CSRF':session?.csrf||'','X-ArchHub-Desktop-Subject':desktopSubject||'',...(window.ARCHHUB_AUTHORITY?.canvas_key?{'X-ArchHub-Canvas-Key':window.ARCHHUB_AUTHORITY.canvas_key}:{})},body,keepalive:true}).catch(()=>{});}});

const initialState=copy(state);
async function loadDesktop(){
 const initialNavigation=fileNavigation;
 // The native Qt owner supplies one reviewed payload and the existing bound decision bridge.
 if(window.ARCHHUB_NATIVE_APPROVAL){
  const supplied=window.ARCHHUB_NATIVE_APPROVAL;
  const card={...supplied.approval,id:supplied.approval.id||supplied.binding,status:'pending',
   rows:(supplied.approval.rows||supplied.approval.changes||[]).map(row=>({...row,element:row.element||row.label,before:row.before??row.now,after:row.after}))};
  let decision=null;
  async function decideNative(id,choice){
   if(id!==card.id||state.approvals[0]?.status!=='pending')return unavailable(choice,'This native review is no longer pending');
   if(decision)return decision;
   decision=(async()=>{try{await window.ARCHHUB_NATIVE_DECIDE(choice);publish({approvals:[{...card,status:choice==='decline'?'declined':'approved'}]});return {ok:true};}catch(error){publish({approvals:[{...card,status:'refused'}]});throw error;}finally{decision=null;}})();
   return decision;
  }
  api.approve=(id,mode='once')=>mode==='once'?decideNative(id,'approve'):unavailable('approve','Native review permits this action once');
  api.decline=id=>decideNative(id,'decline');
  publish({nativeApproval:true,approvals:[card]});return state;
 }
 // COMMANDREGISTRY: served by the owner; this is a disposable projection, never a settings store.
 window.ArchHubCommandRegistry = await request('/api/commands');
 Object.assign(NAVIGATION_ROUTES,Object.fromEntries(window.ArchHubCommandRegistry.commands.filter(c=>c.action.route).map(c=>[c.action.route,c.label])));
 Object.freeze(NAVIGATION_ROUTES);
 // First-file startup stays independent; editable shortcuts wait for the local override read.
 void settingsAction('readKeybindings').catch(error=>publish({...(state.keybindings===undefined?{keybindings:{},keyboardCommands:[]}:{}),keyboardError:error.message||'Keyboard shortcuts could not be read. Defaults are active.'})).finally(()=>{if(preferenceRequest===0)publish({keyboardPending:false});});
 commands=window.ArchHubStudioAuthority.create({get:path=>request(path),post:(path,body)=>request(path,body)});
 // Library collapse is advisory. A refused or slow settings read stays expanded and does not gate the first session file.
 // The refusal still belongs on the status footer; a later update read must not erase it.
 void settingsAction('readLibraryCollapsed').catch(error=>{const message=error.message||String(error);notice(message);publish({libraryCollapsed:[],connectionNotice:state.connectionNotice&&state.connectionNotice!=='Checking for updates…'?state.connectionNotice:message});});
 // The Library catalogue reads every saved session file (a cold first start on a full profile takes seconds): it loads after
 // the splash, and the Library shows that it is loading. The first file's nodes take their ports when it arrives.
 publish({libraryStatus:'waiting',libraryError:''});
 try{
  const initialFile=await sessionRequest('initial');
  // A late startup response must not replace the workflow the user has already chosen.
  if(initialNavigation===fileNavigation){
   if(initialFile?.document){sessionDocument=copy(initialFile.document);sessionPath=initialFile.path||'';sessionRevision=sessionDocument.properties?.revision||0;if(initialFile.migrationDocument)fileHistory.push(copy(initialFile.migrationDocument));projectFile();}
   else await api.newSession();
  }
 }catch(error){
  if(!desktopAdmitted())throw error;
  if(initialNavigation===fileNavigation){
   notice(error.message||String(error));
   // A file that failed to open is not the open file: the new session must not save over it or project it again.
   sessionDocument=null;sessionPath='';sessionRevision=0;
   try{await api.newSession();}catch(inner){notice(inner.message||String(inner));}
  }
 }
 publish({learning:{...state.learning,layer:'Host'},connectionNotice:state.connectionNotice||''});
 ready=true;showDesktopAccess({ready:true});watchRefresh();
 void api.loadLibrary();
 void api.refreshRouter?.().catch(error=>notice(error.message));
 // Account/network discovery must not hold the usable graph behind its timeout.
 void (async()=>{
  // The saved sessions arrive with the Library catalogue above (one read of every file), so the tasks never wait behind a second one.
  for(const refresh of [api.listWorkspaces,refreshSettingsControls,refreshApplicationUpdate,refreshAccount,api.listProviders,refreshTasks,refreshAgents]){
   if(activeSurface==='canvas')break;
   try{await refresh();}catch(error){if(refresh!==refreshApplicationUpdate)publish({connectionNotice:error.message});}
  }
 })();
 return state;
}
api.ready=(async()=>{
 if(nativeReview)return loadDesktop();
 session=window.ARCHHUB_BOOT;
 try {const saved=typeof sessionStorage==='undefined'?null:JSON.parse(sessionStorage.getItem('archhub.studio.session')||'null');session=session?{...session,lastGraphId:saved?.lastGraphId}:saved;}
 catch {notice('The saved browser session could not be read. Reconnecting this window.');}
 if((!session?.token||!session?.csrf)&&!window.ARCHHUB_AUTHORITY?.canvas_key)await signIn();else window.__archhubSession=session;
 await refreshDesktopAccess();
 let opened=null;while(opened===null){await waitForDesktop();try{opened=await loadDesktop();}catch(error){if(desktopAdmitted())throw error;}}return opened;
})();
// WIRE-projects: tick existing schedule nodes while the desktop is open, including hidden pages.
api.ready.then(()=>{
 if(state.nativeApproval || typeof window.setInterval!=='function')return;
 let ticking=false;
 const tick=()=>{
  if(ticking||!desktopAdmitted()||document.hidden||activeSurface==='canvas')return;ticking=true;
  return api.tickSchedules()
   .catch(failure=>notice(failure.message+' Review Schedules, then retry.'))
   .finally(()=>{ticking=false;});
 };
 const timer=window.setInterval(tick,ownerRefreshMs);
 window.addEventListener('pagehide',()=>window.clearInterval(timer),{once:true});
}).catch(error=>notice(error.message));
// WIRE-projects end
// SESSION MODEL (ONE BUILD 1): every session field is read and set through /api/session-model; screens bind these.
// Read on open, after a save and on a file change: never polled.
const sessionModel=(action,extra={})=>request('/api/session-model',{action,...extra});
api.listSessionModel=()=>sessionModel('list');
api.readSessionModel=path=>sessionModel('get',{path}).then(data=>data.session);
api.setSessionModel=async(path,values)=>{
 const current=path===sessionPath,navigation=fileNavigation;
 if(current){await flushAutosave();if(navigation!==fileNavigation)throw Error('The session changed. Retry the session edit.');}
 const result=await sessionModel('set',{path,values});
 if(current&&navigation===fileNavigation)await pollFile();
 return result.session;
};
api.sessionInputLinks=path=>sessionModel('links',{path}).then(data=>data.links);
api.sessionRuns=(path,limit=200)=>sessionModel('runs',{path,limit}).then(data=>data.runs);
// App health › Activity: every session's newest run receipts (the run history beside each file).
api.recentRuns=(limit=60)=>sessionModel('activity',{limit}).then(data=>data.runs);
api.sessionSetting=(path,id)=>sessionModel('setting',{path,id});
api.approveSessionRun=(path,run)=>sessionModel('approve-run',{path,run}).then(data=>data.outcome);
// SESSION MODEL end
// Settings load on their existing screen; Canvas boot reads only its file.
window.ArchHubAPI=Object.freeze(api);
})();
