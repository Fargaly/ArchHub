// The approved design's only domain boundary. Real owners; no demonstration data.
(() => {
'use strict';
  const NAVIGATION_ROUTES = {
    'home': 'Home',
    'workshop': 'Workshop',
    'canvas': 'Canvas',
    'library': 'Library',
    'baboom': 'BABOOM',
    'colleagues': 'Team',
    'watcher': 'Watcher',
    'brain': 'Brain',
    'system': 'System graph',
    'first-run': 'First run',
    'runs': 'Runs',
    'receipts': 'Logs & receipts',
    'automations': 'Automations',
    'docs': 'Docs',
    'meetings': 'Meetings',
    'dependencies': 'Dependencies',
    'present': 'Present',
    'community': 'Community',
    'model-review': 'Model review',
    'interface': 'Interface studio',
    'feedback': 'Feedback',
    'social': 'Social media',
    'xray': 'X-RAY',
    'access': 'Plan & access',
    'routing': 'Model routing'
  };
window.ArchHubRouteNames = Object.freeze(NAVIGATION_ROUTES);
let state = {"revision": 0, "sessionApprovals": [], "activeWorkspace": "", "activeFile": "", "profile": {"id": "", "isFounder": false, "name": "", "firm": "", "email": "", "signedIn": false, "plan": ""}, "nodeSchemas": {}, "providers": [], "catalogue": [], "templates": [], "pages": ["Account", "Connections", "BABOOM", "Agents", "Brain", "System graph", "Workshop", "Library & Mods", "Automations", "Hooks", "Dependencies", "Privacy", "Appearance", "Updates & About", "Advanced"], "settings": [], "companion": {"mode": "idle", "x": null, "y": null, "pinned": false}, "workspaces": [], "tasks": [], "approvals": [], "graph": {"id": "", "name": "", "nodes": [], "wires": [], "workspaceIds": [], "documentation": "", "customProperties": [], "courtStatus": ""}, "brain": [], "dependencies": [], "connections": [], "files": [], "secrets": [], "people": [], "archives": [], "schedules": [], "mods": [], "receipts": [], "runs": [], "drafts": [], "feedback": [], "notifications": [], "meeting": {"title": "", "actions": [], "calendarId": "", "platform": "", "agent": "", "status": "", "consent": false, "transcript": [], "actionOwners": {}, "actionTasks": {}}, "watcher": {"geometry": {"outline": [], "walls": [], "doors": [], "tags": []}, "host": "", "view": "", "views": [], "rooms": [], "imageEdits": [], "wallY": 0, "pendingY": 0, "marks": [], "comments": [], "mask": null, "applied": false, "lengthMm": 0, "appliedLengthMm": 0, "thicknessMm": 0, "appliedThicknessMm": 0, "snap": false, "gridMm": 0, "orthogonal": false, "showDimensions": false, "dimensionAlignment": "", "dimensions": []}, "update": {"available": false, "installed": "", "next": ""}, "app": {"hidden": false, "quit": false, "stopped": false}, "backups": [], "sync": "", "lastResult": null, "docs": [], "bookGlossary": [], "social": {"office": {"name": "", "headline": "", "bio": "", "website": "", "audience": ""}, "inbox": [], "drafts": [], "groups": [], "digest": {"enabled": false, "time": "", "summary": ""}, "research": [], "tutorials": [], "triaged": false}, "learning": {"concept": "", "hosts": [], "baseline": "", "residual": "", "why": "", "sources": [], "findings": [], "status": "", "destination": "", "layer": "", "layers": {"Host": {"program": "", "operation": "", "preserveRelationships": false}, "Habit": {"pattern": "", "minimumRepeats": 0, "learn": false}, "Intent": {"baseline": "", "deviation": "", "why": ""}, "Self": {"metric": "", "threshold": null, "rebaseline": false}, "Agent": {"provider": "", "checkResults": false, "maxIterations": 0}, "Session": {"graph": "", "shareContext": false, "retainCheckpoints": false}}}, "modelSources": [], "devices": [], "activeDevice": "", "graphs": [], "capabilities": [], "mcpServers": [], "suggestions": [], "community": {"tab": "", "peers": [], "patterns": [], "shared": [], "points": [], "groups": [], "joinStatus": "", "marketQuery": "", "listing": {"title": "", "price": 0, "creatorShare": 0}, "charge": {"client": "", "project": "", "basis": "", "amount": 0}, "charges": [], "marketplace": []}, "modelReview": {"operation": "", "results": [], "issues": []}, "usage": {"tokens": 0, "cost": 0, "runs": 0, "quota": 0, "seats": 0, "grace": false}, "hostSkills": [], "provenance": [], "presentation": {"slides": [], "walkthrough": 0}, "healthHistory": [], "prototype": {"name": "", "threshold": null, "samples": 0, "baseline": 0, "status": "", "linkedModel": false, "pattern": null}, "composerAttachments": [], "settingsScope": "User", "officeItems": [], "timesheet": {"status": "", "rows": []}, "desktop": {"program": "", "stage": "", "taskId": null}, "meetingCalendar": [], "refine": {"breadth": 0, "depth": 0, "trials": 0, "tokens": 0, "results": [], "accepted": null}, "intakeRules": [], "uncertainLinks": [], "onboarding": {"role": "", "assessment": ""}, "firms": [], "activeFirm": "", "officeInvitations": [], "billing": {"status": "", "requestedPlan": "", "cycle": "", "checkout": null, "limitReached": null, "invoices": []}};
const exportedNames = ["moveNodes", "runValuation", "selectFirm", "acceptOfficeInvitation", "declineOfficeInvitation", "getUsageSummary", "setBilling", "prepareCheckout", "completeCheckout", "retryPayment", "downgradeBilling", "refreshBilling", "createCommunityGroup", "issueCommunityInvite", "revokeCommunityInvite", "verifyCommunityInvite", "joinCommunityGroup", "setMarketplace", "installMarketplaceItem", "proposeMarketplaceListing", "setProjectCharge", "proposeProjectCharge", "resolveTaskReview", "setApprovalRubric", "verifyOutputStamp", "setNodeRunPolicy", "contextLabel", "setGraphThumbnail", "setIntakeRule", "reviewBrainLink", "setOnboarding", "correctAnswerSource", "setResearchReview", "stampOutput", "runSpecialNode", "setTranscriptPass", "getDecisionState", "setDecisionState", "setRefine", "compareRefine", "setAnswerWidget", "startVoiceInput", "stopVoiceInput", "speak", "addCompatibleNode", "setPromotedParameter", "setPortVisibility", "compatibleNodes", "setDesktopProgram", "offerDesktopAction", "prepareDesktopAction", "setMeeting", "joinMeeting", "startMeetingTranscript", "stopMeetingTranscript", "readMeetingTranscript", "setMeetingActionOwner", "createMeetingTask", "proposeMeetingSummary", "setTaskPlanMode", "addTaskReview", "refreshOfficeAwareness", "settleTimesheet", "setSettingsScope", "openTemplateGraph", "addTemplateNode", "addComposerAttachment", "removeComposerAttachment", "manageDependency", "getCapabilityParameters", "setCapabilityParameter", "setCapabilityEnabled", "setLearningLayer", "postponeApproval", "resumeApproval", "contestDecision", "setScheduleResponsibility", "reviewScheduledWork", "getHealthHistory", "runResearchNode", "editSlide", "addSlide", "removeSlide", "reorderSlide", "setPrototype", "rebaselinePrototype", "checkVerdictPattern", "steerTask", "refreshModelRoster", "setMultipleNodeParameters", "runToHere", "setPinnedOutput", "setWireVisibility", "setSourceEvidence", "importHostSkill", "inspectConnectorBundle", "configureConnectorBundle", "installConnectorBundle", "setHostSkillEnabled", "auditHostSkill", "setAgentProfile", "setNodeFlags", "checkpointTask", "restoreTaskCheckpoint", "queueTaskMessage", "settleQueuedMessage", "setTaskDelegate", "getNodeOutput", "reviewModel", "updateReviewIssue", "subscribeCommunity", "reviewCommunityPattern", "proposeCommunityShare", "addInterfaceElement", "updateGraph", "removeGraph", "saveGraphVersion", "restoreGraphVersion", "setAccountSeats", "transferOwnership", "checkWatcherSource", "readYoutubeData", "refreshApproval", "setGraphWorkspaces", "discoverMcpTools", "reconnectMcp", "importMcpTool", "inspectMod", "retryMod", "installMod", "removeMod", "shareMod", "dismissSuggestion", "proposeMemory", "checkFeedback", "readResearchSource", "checkResearchLicense", "saveResearchDecision", "importRecipe", "exportRecipe", "getSocial", "saveSocialDraft", "proposeSocialDraft", "discardSocialDraft", "replySocialMessage", "readSocialMessage", "triageSocialInbox", "setSocialGroupRule", "updateOfficePage", "setSocialDigest", "generateSocialDigest", "readContentSource", "prepareTutorial", "setLearning", "runLearning", "distilLearning", "addGraph", "selectGraph", "openTaskGraph", "setAccountPlan", "setTeamAccess", "selectDevice", "setWorkspaceRules", "setModelSource", "checkModelRouting", "setWatcherDimension", "setWatcherOptions", "addDimension", "removeDimension", "getNodeParameters", "addNodeParameter", "setCompanionState", "getDocs", "getKnowledgeGraph", "getSnapshot", "subscribe", "ensureDependency", "checkDependencies", "reviewProofRow", "exposeSettingsPage", "selectWorkspace", "selectFile", "setWatcherView", "listWorkspaces", "addWorkspace", "removeWorkspace", "listProviders", "setProviderEnabled", "signInProvider", "setProviderModel", "listAgentsWorking", "getSettings", "setSetting", "resetSetting", "resetPage", "sendToBaboom", "listTasks", "setTaskStatus", "approve", "decline", "stopEverything", "reassignTask", "startTemplate", "getGraph", "addNode", "moveNode", "setNodeParam", "resetNodeParam", "renameNode", "deleteNode", "forkNode", "arrangeGraph", "groupNodes", "ungroupNode", "connectSockets", "insertConvert", "setWireRule", "deleteWire", "runNode", "undo", "redo", "addSchedule", "setScheduleEnabled", "setScheduleTime", "removeSchedule", "editMemory", "forgetMemory", "remember", "setConnection", "checkConnection", "editWall", "addMark", "addComment", "proposeWatcherEdit", "discardWatcherChanges", "setWatcherHost", "updateProfile", "signIn", "syncAccount", "addFile", "removeFile", "disconnectSecret", "setModEnabled", "importFlow", "saveSkill", "sendFeedback", "changePlan", "invitePerson", "grantAccess", "installUpdate", "windowAction", "backUpNow", "rollBack", "archiveActivity", "readNotification", "exportData", "traceNode"];

const listeners=new Set();
let canvas=null, session=null, commands=null, renewing=null, scopeEpoch=0;
let refreshTimer=null, refreshInFlight=false, ready=false, accountSignInPending=false;
let providerRoster=[], workingAgents=[];
let updateGeneration=0, updateActionPending=false;
// Same bounded five-second cadence as the existing studio Tool Hub, paused while hidden.
const ownerRefreshMs=5000;
const defaults=new Map();
const copy=value=>window.structuredClone(value);
function publish(values={}) { state={...state,...values,revision:state.revision+1};listeners.forEach(fn=>fn()); }
function notice(message) { window.dispatchEvent(new CustomEvent('archhub:notice',{detail:{message}})); }
function unavailable(operation,reason='') {
 const result={ok:false,status:'not_connected',operation,message:reason||'This action is not available in this release.'};
 notice(result.message);return result;
}
const normalise=data=>data && (data.canvas_root||data.root) && Array.isArray(data.nodes)
 ? {...data,root:data.root||data.canvas_root,graph_id:data.graph_id||data.application_root,
    nodes:data.nodes.map(n=>({...n,properties:n.properties||n.params||[]}))} : data;
async function signIn() {
 const descriptor=window.ARCHHUB_AUTHORITY;
 const response=await fetch('/api/universal/session',{method:'POST',headers:{'Content-Type':'application/json','X-ArchHub-Sign-In':'1',
 ...(descriptor?.canvas_key?{'X-ArchHub-Canvas-Key':descriptor.canvas_key}:{})},body:'{}'});
 const data=await response.json();if(!response.ok||!data.token||!data.csrf)throw Error(data.error||'Reopen ArchHub from its launcher.');
 session={token:data.token,csrf:data.csrf};window.__archhubSession=session;
 try {sessionStorage.setItem('archhub.studio.session',JSON.stringify(session));} catch { notice('Browser session storage is unavailable. This window remains signed in.'); }
}
async function request(path,body=undefined,readRetry=true,signal=undefined) {
 if(path==='/api/universal/interaction'&&body&&!window.ARCHHUB_AUTHORITY){const keys=['interaction','control','event','revision','event_facts'];if(body.control==='app:control:canvas:remove-member')keys.push('membership','expected_scope','command_id');body=Object.fromEntries(keys.filter(k=>Object.hasOwn(body,k)).map(k=>[k,body[k]]));}
 const response=await fetch(path,{method:body===undefined?'GET':'POST',cache:'no-store',signal,headers:{'Content-Type':'application/json',
 'X-ArchHub-Session':session?.token||'','X-ArchHub-CSRF':session?.csrf||''},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const data=await response.json();
 if(response.status===403&&/browser session|session lease|credential digest|browser-session/i.test(data.error||'')) {
  if(readRetry){renewing=renewing||signIn().finally(()=>{renewing=null;});await renewing;
   // A refused write is never replayed. Only the next deliberate action uses the renewed session.
   if(body===undefined)return request(path,undefined,false,signal);}
 }
 if(!response.ok||data.ok===false){const error=Error(data.error||data.reason||'The backend refused this action.');error.status=response.status;error.response=data;throw error;}
 const result=normalise(data);if(result?.root&&Array.isArray(result.nodes))canvas=result;
 return result;
}
function rows(node){return node?.properties||node?.params||[];}
function nodeDto(n) {
 const params=Object.fromEntries(rows(n).map(p=>[p.label,p.value]));
 const schema=rows(n).map(p=>({key:p.label,label:p.display_label||p.label,type:p.editor||'text',group:'Parameters',unit:p.unit||'',options:p.constraints?.options||[],editable:p.editable===true,relation:p.relation,owner:p.owner||n.id}));
 const ports=(n.ports||[]).map(p=>({id:p.id,name:p.name||p.label||p.id,type:p.value_type||'any'}));
 return {id:n.id,title:n.label||n.title||n.id,kind:params.element?'UI element':n.kind||n.engine||n.assembly||'Node',x:n.x||0,y:n.y||0,status:n.status||'',
 params,defaults:Object.fromEntries(rows(n).filter(p=>p.default!==undefined).map(p=>[p.label,p.default])),parameterSchema:schema,inputs:ports.filter((_,i)=>['target','in'].includes(n.ports[i].side)),outputs:ports.filter((_,i)=>['source','out'].includes(n.ports[i].side)),
 children:(n.members||[]).map(r=>r.id||r),parent:n.group||null,pinned:n.pinned===true||params.pinned==='true',frozen:n.frozen===true||params.frozen==='true',output:n.output||n.result||[],application:n.application===true,
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
 if(!canvas)return;
 const nodes=canvas.nodes.map(nodeDto),settings=canvas.nodes.flatMap(n=>rows(n).map(p=>settingDto(n,p)));
 const catalogue=(canvas.catalog||[]).map(c=>({id:c.id,name:c.name,family:c.category||'Get',input:'any',output:'any',description:c.description||'',definition:c.id,revision:c.revision_root,descriptor:c.descriptor}));
 for(const mod of state.mods.filter(m=>m.enabled&&m.status!=='Ready for review'))for(const node of mod.nodes||[])catalogue.push({id:'mod:'+mod.id+':'+node.id,name:node.title,family:node.category||'Change',description:node.summary,modId:mod.id,itemId:node.id});
 const root=canvas.scope?.current||canvas.root;
 const graph={...state.graph,id:root,name:canvas.scope?.current_label||'Graph',nodes,wires:(canvas.wires||[]).map(w=>({id:w.id,from:w.source||w.from,to:w.target||w.to,fromPort:w.source_interface||w.fromPort,toPort:w.target_interface||w.toPort,type:w.value_type||'any',rule:w.label||''}))};
 // WIRE-projects: the evaluator's condition parameter is the UI's wire rule.
 const conditions=new Map((canvas.wires||[]).map(w=>[w.id,(w.params||[]).find(p=>p.label==='condition')?.value||'']));
 for(const wire of graph.wires)wire.rule=conditions.get(wire.id);
 // WIRE-projects end
 // A local browser-session lease is transport authority, never account sign-in.
 const profile={...state.profile};
 const graphs=state.graphs.some(g=>g.id===graph.id)?state.graphs.map(g=>g.id===graph.id?{...g,...graph}:g):[...state.graphs,graph];
 publish({profile,graph,graphs,settings,runtimeParameters:copy(canvas.runtime_parameters||{}),catalogue,capabilities:catalogue.map(c=>({...c,nodeKind:c.name,page:'System graph',params:{},defaults:{},enabled:true})),
 docs:[...(canvas.documentation?.tutorials||[]).map(d=>({id:d.id,category:d.id.startsWith('tutorial-')?'Tutorial':'Guide',title:d.title,summary:d.description||'',steps:String(d.text||'').split(/\n+/).map(line=>line.trim()).filter(Boolean),route:({'getting-started':'home','composer-canvas':'canvas','brain':'brain','connectors':'watcher','account-web':'settings/Account'})[d.id]||'canvas',bookSource:'ArchHub documentation'})),...(canvas.documentation?.nodes||[]).map(d=>({id:d.id,category:d.category,title:d.title,summary:d.detail||'',steps:[],route:'canvas'}))],
 sync:'Local session'});
 if(state.social?.research?.length)publish({docs:[...state.docs,...state.social.research.map(researchDoc)]});
}
function workshopBinding() {
 const scope=canvas?.workshop_scope;
 const workshop=scope?.workshops?.find(w=>w.is_general)||scope?.workshops?.[0]||canvas?.workshops?.[0];
 return workshop?{root:workshop.root,scope:canvas.scope?.current||scope?.root||canvas.root}:null;
}
async function workshop(fn,args=[]) {
 const binding=workshopBinding();if(!binding)return unavailable(fn,'Workshop owner unavailable');
 const response=await request('/api/universal/workshop',{action:'data-api',function:fn,args,...binding,request_id:window.crypto.randomUUID()});
 return response.result;
}
async function refreshTasks() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const tasks=await workshop('listTasks');if(!Array.isArray(tasks))return tasks;
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return state.tasks;
 publish({tasks:tasks.map(t=>({...t,messages:t.messages||[],steps:t.steps||[],reviews:t.reviews||[],queuedMessages:t.queuedMessages||[]}))});return state.tasks;
}
function projectProviders() {
 const roster=new Map(providerRoster.map(p=>[p.id,p]));
 for(const a of workingAgents)roster.set(a.id,{...roster.get(a.id),...a});
 publish({providers:[...roster.values()]});
}
async function refreshAgents() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const agents=await workshop('listAgentsWorking');if(!Array.isArray(agents))return agents;
 if(epoch!==scopeEpoch||binding!==JSON.stringify(workshopBinding()))return state.providers;
 workingAgents=agents.map(a=>({...a,id:a.id||a.provider||a.app,name:a.name||a.provider||a.app,ini:(a.name||a.provider||'?').slice(0,1),
 col:a.col||window.AH?.inkSoft,presence:a.status||a.presence||'Unavailable',model:a.model||'Unavailable',enabled:a.enabled===true,signedIn:a.signedIn??null}));
 projectProviders();return state.providers;
}
async function refreshAccount() {
 const account=await request('/api/universal/cloud-session');
 let attempt=null;
 if(accountSignInPending){
  attempt=await request('/api/universal/cloud-signin');
  if(['done','failed','idle'].includes(attempt.phase)||account.signed_in===true)accountSignInPending=false;
 }
 publish({profile:{...state.profile,id:account.signed_in===true?(account.user_id||account.email||''):'',
  name:account.signed_in===true?(account.display_name||account.name||account.email||'Account'):'Account',
  email:account.email||'',signedIn:account.signed_in===true,
  isFounder:account.signed_in===true&&account.founder===true},
  sync:account.signed_in===true?'Account connected':accountSignInPending?'Complete sign-in in your browser':account.state==='expired'?'Sign in again':'Signed out',
  ...(attempt?.phase==='failed'?{connectionNotice:attempt.error||'Sign-in failed. Try again.'}:{})});
 return copy(state.profile);
}
async function refreshGraphs(){
 const data=await request('/api/universal/graphs?screen=home');
 publish({graphs:(data.graphs||[]).map(g=>({...g,name:g.title||g.name||'Graph'}))});
 return copy(state.graphs);
}
function projectUpdate(data) {
 const update={state:data.state||'unavailable',installed:data.current_build||'',next:data.available_build||'',
  available:data.state==='ready'&&!!data.available_build&&data.restart_supported===true,
  restartSupported:data.restart_supported===true,restartRefusal:data.restart_refusal||'',
  detail:data.detail||'Update status unavailable',updatedFrom:data.updated_from||'',updatedTo:data.updated_to||''};
 publish({update});return copy(update);
}
async function refreshApplicationUpdate() {
 if(updateActionPending)return copy(state.update);
 const generation=++updateGeneration;
 try{
  const data=await request('/api/universal/application-update',undefined,true,AbortSignal.timeout(15000));
  return generation===updateGeneration?projectUpdate(data):copy(state.update);
 }catch(error){
  if(generation!==updateGeneration)return copy(state.update);
  projectUpdate({state:'failed',current_build:state.update.installed,detail:error.message});throw error;
 }
}
async function updateAction(action) {
 if(updateActionPending)throw Error('An update action is already in progress. Read status before trying again.');
 const generation=++updateGeneration;
 updateActionPending=true;
 publish({update:{...state.update,available:false,state:action==='reload'?'restarting':action==='check'?'checking':state.update.state}});
 try{return projectUpdate(await request('/api/universal/application-update',{action}));}
 catch(error){
  if(generation===updateGeneration)projectUpdate({state:'failed',current_build:state.update.installed,detail:error.message});
  throw error;
 }finally{updateActionPending=false;}
}
window.addEventListener('archhub:update-ready',()=>{
 refreshApplicationUpdate().catch(error=>notice(error.message));
});
async function refreshLive() {
 if(!ready||document.hidden||refreshInFlight||listeners.size===0)return;
 refreshInFlight=true;
 try {
  for(const refresh of [refreshApplicationUpdate,refreshAccount,refreshTasks,refreshAgents]){
   try{await refresh();}catch(error){publish({connectionNotice:error.message});}
  }
 }
 finally{refreshInFlight=false;}
}
function stopRefresh(){if(refreshTimer!==null){window.clearInterval(refreshTimer);refreshTimer=null;}}
function watchRefresh(){stopRefresh();if(ready&&listeners.size&&!document.hidden)refreshTimer=window.setInterval(refreshLive,ownerRefreshMs);}
document.addEventListener('visibilitychange',()=>{watchRefresh();if(!document.hidden)refreshLive();});
window.addEventListener('pagehide',stopRefresh);
window.addEventListener('pageshow',watchRefresh);
const canvasOperation=(op,args)=>mutate(async()=> (await request('/api/universal/canvas-op',{op,args})).result);
async function mutate(command) { const result=await command();await commands.load();project();return result; }
function interaction(control,extra={}) {
 const bindings=(canvas?.interaction_projection?.bindings||[]).filter(b=>b.control===control);
 if(bindings.length!==1)return Promise.resolve(unavailable(control,'No current command binding'));
 const b=bindings[0];return request('/api/universal/interaction',{interaction:b.interaction,control:b.control,event:b.event,
 expected_scope:canvas.scope?.current||canvas.root,revision:canvas.revision,command_id:window.crypto.randomUUID(),...extra});
}
async function nodeProperty(id,key,value) {
 const n=canvas.nodes.find(n=>n.id===id),p=rows(n).find(p=>p.label===key);
 if(!p?.editable)return unavailable('setNodeParam','This parameter has no editable owner');
 if(p.setting?.kind==='baboom'){const preferences={value:rows(n).find(r=>r.setting?.key==='start_with_archhub')?.value,shows_as:rows(n).find(r=>r.setting?.key==='shows_as')?.value};preferences[p.setting.key==='shows_as'?'shows_as':'value']=value;value=JSON.stringify(preferences);}
 const binding=(canvas.interaction_projection?.bindings||[]).find(b=>b.control===p.relation);
 let result;
 if(binding){const spec=binding.event_facts?.find(f=>f.source==='submitted');if(!spec)return unavailable('setNodeParam','No submitted-value binding');result=await interaction(binding.control,{event_facts:[{input:spec.input,value:typeof value==='string'?value:JSON.stringify(value)}]});}
 else result=await request('/api/universal/set-property',{relation:p.relation,value:typeof value==='string'?value:JSON.stringify(value)});
 await commands.load();project();return state.graph.nodes.find(n=>n.id===id)||result;
}
const api={};
for(const name of exportedNames)api[name]=()=>unavailable(name);
const unfinishedActions={...api};
api.supportsAction=(name,mode)=>!(name==='approve'&&mode&&mode!=='once')&&typeof api[name]==='function'&&api[name]!==unfinishedActions[name];
Object.assign(api,{
 async signIn(enabled=true){
  const result=await request(enabled?'/api/universal/cloud-signin':'/api/universal/cloud-signout',enabled?{method:'google'}:{});
  accountSignInPending=enabled;
  await refreshAccount();return result;
 },
 syncAccount:refreshAccount,
 async windowAction(action){
  if(typeof window.ARCHHUB_WINDOW_ACTION!=='function')throw Error('Open ArchHub from its desktop shortcut to use window controls.');
  const result=await window.ARCHHUB_WINDOW_ACTION(action);
  publish({app:{...state.app,hidden:result.visible===false,quit:action==='quit'}});return result;
 },
 async addGraph(name){
  const result=await request('/api/universal/graph-create',{title:name});
  await commands.load();project();await refreshGraphs();
  return state.graphs.find(g=>g.id===result.graph?.id)||state.graph;
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
 getSnapshot:()=>state,subscribe(fn){listeners.add(fn);watchRefresh();return()=>{listeners.delete(fn);if(listeners.size===0)stopRefresh();};},
 listTasks:refreshTasks,listAgentsWorking:refreshAgents,
 async listProviders(){const d=await request('/api/universal/providers');const providers=(d.providers||[]).map(p=>({...p,id:p.id||p.provider,name:p.name||p.label||p.id,ini:(p.name||p.id||'?').slice(0,1),col:window.AH?.inkSoft,presence:p.status||'Unavailable',model:p.model||'Unavailable'}));providerRoster=providers;projectProviders();return state.providers;},
 getSettings:async()=>copy(state.settings),getGraph:async()=>copy(state.graph),
 getNodeParameters:id=>copy(state.graph.nodes.find(n=>n.id===id)?.parameterSchema||[]),
 getCapabilityParameters:id=>copy(state.capabilities.find(c=>c.id===id)?.parameterSchema||[]),
 getNodeOutput:id=>copy(state.graph.nodes.find(n=>n.id===id)?.output||[]),
 getHealthHistory:async()=>copy(state.healthHistory),getDocs:()=>copy(state.docs),getSocial:()=>copy(state.social),
 getKnowledgeGraph:()=>({nodes:[],edges:[],status:'not_connected',message:'Knowledge graph is unavailable.'}),
 contextLabel:id=>state.files.find(x=>x.id===id)?.name||state.graph.nodes.find(x=>x.id===id)?.title||id,
 compatibleNodes:()=>[],getDecisionState:()=>null,
 async sendToBaboom(text,options={}){if(options.scope&&options.scope!==state.graph.id)return unavailable('sendToBaboom','Node-scoped requests are not exposed by the Workshop owner');const admitted=Object.fromEntries(['provider','taskId'].filter(k=>typeof options[k]==='string'&&options[k]).map(k=>[k,options[k]]));const task=await workshop('sendToBaboom',[text,admitted]);if(task?.ok===false)return task;await refreshTasks();return task;},
 async setSetting(id,value){const row=state.settings.find(r=>r.id===id);if(!row)return unavailable('setSetting');return nodeProperty(row.owner,row.key,value);},
 async resetSetting(id){const row=state.settings.find(r=>r.id===id);return row&&row.default!==undefined?api.setSetting(id,row.default):unavailable('resetSetting','Backend default unavailable');},
 async resetPage(page){for(const row of state.settings.filter(r=>r.page===page)) {const result=await api.resetSetting(row.id);if(result?.ok===false)return result;}return {ok:true};},
 setNodeParam:nodeProperty,
 resetNodeParam(id,key){const node=state.graph.nodes.find(n=>n.id===id);return node&&Object.hasOwn(node.defaults,key)?nodeProperty(id,key,node.defaults[key]):unavailable('resetNodeParam','Backend default unavailable');},
 async renameNode(id,title){return nodeProperty(id,'title',title);},
 async addNode(name,position={}){
  const {x=240,y=200}=position;
  const modEntry=state.catalogue.find(c=>c.modId&&(c.id===name||c.name===name));
  if(modEntry){const made=await canvasOperation('import_mod_node',[modEntry.modId,modEntry.itemId]);if(position.x!==undefined||position.y!==undefined)await api.moveNode(made.id,{x,y});return state.graph.nodes.find(n=>n.id===made.id)||made;}
  const entry=(canvas.catalog||[]).find(c=>c.id===name||c.name===name);
  if(!entry)return unavailable('addNode','Definition unavailable');
  if(entry.revision_root){await mutate(()=>commands.create({definition:entry.id,definition_revision:entry.revision_root,x,y}));return state.graph.nodes.find(n=>n.id===canvas.selected);}
  // Legacy catalogue entries use their actual engine/item descriptor, never a guessed operation.
  const engine=entry.descriptor?.engine,item=entry.descriptor?.item;
  if(!engine){const result=await interaction(entry.id,{event_facts:[{source:'canvas-point-x',value:x},{source:'canvas-point-y',value:y}]});if(result?.ok===false)return result;await commands.load();project();return state.graph.nodes.find(n=>n.id===canvas.selected)||result;}
  const result=await request('/api/universal/node-create',{title:entry.name,engine,item,x,y});await commands.load();project();return state.graph.nodes.find(n=>n.id===result.root)||result;
 },
 moveNode:(id,position)=>mutate(()=>commands.move(id,position)),
 moveNodes:positions=>mutate(()=>commands.moveMany(positions)),
 groupNodes:ids=>mutate(()=>commands.composition('group',ids)),
 ungroupNode:id=>mutate(()=>commands.composition('ungroup',[id])),
 deleteNode:id=>mutate(()=>commands.remove(id)),
 async forkNode(id){const result=await canvasOperation('fork_node',[id]);return state.graph.nodes.find(n=>n.id===result.id)||result;},
 setNodeFlags:(id,values)=>canvasOperation('set_node_flags',[id,values.frozen??null,values.pinned??null]),
 traceNode:(id,direction)=>canvasOperation('trace_node',[id,direction]),
 async runToHere(id){const plan=await canvasOperation('run_to_here',[id]);if(!plan.roots.length)return plan;return mutate(()=>request('/api/universal/run-graph',{roots:plan.roots}));},
 async updateGraph(id,values){
  if(Object.keys(values).some(key=>!['name','pinned'].includes(key)))return unavailable('updateGraph','This graph property has no released owner');
  const result=await canvasOperation('update_graph',[id,values.name??null,values.pinned??null]);await refreshGraphs();return result;
 },
 async removeGraph(id){const result=await canvasOperation('remove_graph',[id]);await refreshGraphs();return result;},
 async arrangeGraph(){const positions=Object.fromEntries(state.graph.nodes.map((n,i)=>[n.id,{x:80+(i%4)*300,y:80+Math.floor(i/4)*220}]));return mutate(()=>commands.moveMany(positions,canvas.revision,null,'arrange'));},
 connectSockets:wire=>mutate(()=>commands.connect(wire.from,wire.fromPort,wire.to,wire.toPort)),
 deleteWire:id=>mutate(()=>commands.remove(id)),
 async runNode(id){if(id)await commands.select(id);return mutate(()=>commands.run());},
 undo:()=>mutate(()=>commands.undo()),redo:()=>mutate(()=>commands.redo()),
 async addNodeParameter(id,input){
  if(!['text','All',undefined].includes(input.type))return unavailable('addNodeParameter','Typed parameter creation is not exposed by this owner');
  await commands.select(id);project();const b=(canvas.interaction_projection?.bindings||[]).find(b=>b.control==='app:control:inspector:add-property');
  if(!b)return unavailable('addNodeParameter','Property form unavailable');
  const specs=b.event_facts.filter(s=>s.source==='submitted');
  if(specs.length!==2)return unavailable('addNodeParameter','Property form changed');
  return mutate(()=>interaction(b.control,{event_facts:[{input:specs[0].input,value:input.label},{input:specs[1].input,value:String(input.value??'')}]}));
 },
 async approve(id){const card=state.approvals.find(c=>c.id===id);if(!card?.delegation||!card?.input_digest||!card?.work)return unavailable('approve','No reviewed model delegation');const binding=workshopBinding();const body={...binding,work:card.work,delegation:card.delegation,input_digest:card.input_digest};const inspected=await request('/api/universal/workshop-model-approval?'+new URLSearchParams(body));if(inspected.expired||inspected.input_digest!==card.input_digest)return {ok:false,status:'stale',message:'Review changed; refresh before approving.'};const result=await request('/api/universal/workshop-model-approval',{...body,revision:inspected.revision});await refreshTasks();return result;},
 async selectGraph(id){scopeEpoch++;workingAgents=[];publish({tasks:[]});await request('/api/universal/graph-open',{root:id});await commands.load();project();await refreshGraphs();await refreshTasks();await refreshAgents();return state.graph;},
 async selectWorkspace(id){return api.selectGraph(id);},
 getUsageSummary:()=>({'Usage':'Usage is unavailable.'}),
 async setConnection(id,values){if(values.connected===false)return request('/api/universal/social-connection',{provider:id,action:'cancel'});if(values.connected===true)return request('/api/universal/social-connection',{provider:id,action:'start'});return unavailable('setConnection','No sign-in action requested');},
 async checkConnection(id){return request('/api/universal/social-connection?provider='+encodeURIComponent(id));},
 refreshApplicationUpdate,
 checkForUpdates:()=>updateAction('check'),
 acknowledgeUpdate:()=>updateAction('acknowledge'),
 async installUpdate(){
  if(!state.update.available)throw Error(state.update.detail||'No verified update is ready. Check for updates.');
  if(state.update.restartRefusal)throw Error(state.update.restartRefusal);
  return updateAction('reload');
 },
 async listWorkspaces(){const data=await request('/api/universal/workspace-roots',{action:'list'});const roots=[...(data.built_in?[{...data.built_in,root_id:data.built_in.id,builtIn:true}]:[]),...(data.roots||[])];const workspaces=roots.map(w=>({id:w.root_id,name:w.label||w.root_id,folder:w.path,canvas:w.canvas||'',builtIn:w.builtIn===true,removable:w.removable!==false,privacy:w.privacy}));publish({workspaces});return workspaces;},
 async addWorkspace(input={}){let path=input.folder;if(!path){const picked=await request('/api/universal/workspace-roots',{action:'browse'});path=picked.path;if(!path)return null;}const result=await request('/api/universal/workspace-roots',{action:'register',path,privacy:'private',profile:'client'});await api.listWorkspaces();return result;},
 async removeWorkspace(id){const result=await request('/api/universal/workspace-roots',{action:'unregister',id});await api.listWorkspaces();return result;},
});
for(const fn of ['setTaskStatus','reassignTask','setTaskDelegate','queueTaskMessage','settleQueuedMessage','steerTask','addTaskReview','resolveTaskReview']) {
 api[fn]=async(...args)=>{const result=await workshop(fn,args);if(result?.ok===false)return result;await refreshTasks();return result;};
}
// APP-AGENTS: the existing authenticated owner dispatches these physical adapters.
for(const fn of ['getAgentChannel','installAgentChannel','previewAgentChannel','repairAgentChannel','listAgentSessions','getDesktopCompanion']) {
 api[fn]=async(...args)=>{
  const response=await request('/api/universal/workshop',{action:'agent-channel',function:fn,args});
  return response.result;
 };
}
// WIRE-agents: extend this API registry; all writes use existing authenticated owners.
async function refreshAgentSurface() {
 const epoch=scopeEpoch,binding=JSON.stringify(workshopBinding());
 const [surface, metadata] = await Promise.all([workshop('getAgentSurface'),workshop('getGraphMetadata')]);
 if(epoch!==scopeEpoch || binding!==JSON.stringify(workshopBinding()))return null;
 if(surface?.ok===false || metadata?.ok===false)throw Error(surface.message || metadata.message);
 const {agentProfiles,learning,...values}=surface;
 publish({...values,learning:{...state.learning,...learning,layers:{...state.learning.layers,...learning.layers}},
  providers:state.providers.map(p=>({...p,...agentProfiles[p.id]})),graph:{...state.graph,...metadata}});
 return surface;
}
for(const wireMethod of ['setAgentProfile','setTaskPlanMode','checkpointTask','restoreTaskCheckpoint','setIntakeRule',
 'setOnboarding','reviewBrainLink','setSourceEvidence','setLearningLayer','setPinnedOutput','setNodeRunPolicy','verifyOutputStamp']) {
 api[wireMethod]=async(...args)=>{const result=await workshop(wireMethod,args);if(result?.ok===false)throw Error(result.message||result.error);await commands.load();project();await refreshTasks();await refreshAgentSurface();return result;};
}
api.openTaskGraph=async id=>{const result=await workshop('openTaskGraph',[id]);if(result?.ok===false)throw Error(result.message||result.error);return api.selectGraph(result.id);};
api.refreshOfficeAwareness=async()=>{const rows=await workshop('refreshOfficeAwareness');if(!Array.isArray(rows))throw Error(rows?.message||'Office task read failed; retry.');publish({officeItems:rows,officeUpdated:'Read from current Workshop'});return rows;};
const graphUpdate=api.updateGraph;
api.updateGraph=async(id,values)=>{
 if(Object.keys(values).every(key=>['name','pinned'].includes(key)))return graphUpdate(id,values);
 const result=await workshop('setGraphMetadata',[id,values]);if(result?.ok===false)throw Error(result.message||result.error);
 await refreshAgentSurface();return result;
};
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
  for(const node of changed.reverse())await nodeProperty(node.id,key,node.params[key]).catch(reason=>failures.push(reason.message));
  throw Error(error.message+(failures.length?' Rollback failed: '+failures.join('; '):' Earlier edits were rolled back.'));
 };
 for(const node of nodes){
  const result=await nodeProperty(node.id,key,value).catch(restore);
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
 replySocialMessage:'reply_social_message',triageSocialInbox:'triage_social_inbox',setSocialGroupRule:'set_social_group_rule',
 setSocialDigest:'set_social_digest',generateSocialDigest:'generate_social_digest',addSlide:'add_slide',editSlide:'edit_slide',
 removeSlide:'remove_slide',reorderSlide:'reorder_slide',setPrototype:'set_prototype',rebaselinePrototype:'rebaseline_prototype',
 checkVerdictPattern:'check_verdict_pattern',setMeeting:'set_meeting',setMeetingActionOwner:'set_meeting_action_owner'};
for(const [socialFunction,operation] of Object.entries(socialOperations))api[socialFunction]=(...args)=>socialOperation(operation,args);
api.readContentSource=({kind,url})=>socialOperation('read_content_source',[kind,url]);
api.refreshModelRoster=async()=>{const rows=await api.listProviders();publish({modelNotice:rows.length+' providers returned by the live provider owner.'});return rows;};
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
api.joinMeeting=async()=>{
 const m=state.meeting;if(!m.calendarId||!m.platform||!m.agent)throw Error('Choose a calendar meeting, program and connected agent.');
 return socialWork('Join the selected meeting using the connected meeting program. Report the actual join result; no invented presence.\n'+JSON.stringify(m),{provider:m.agent});
};
api.startMeetingTranscript=()=>{
 if(!state.meeting.consent)throw Error('Record everyone’s transcript consent first.');
 return socialWork('Start the consented transcript for this selected meeting using its actual capture source. Return attributed transcript turns and capture status.\n'+JSON.stringify(state.meeting),{provider:state.meeting.agent});
};
api.stopMeetingTranscript=()=>socialWork('Stop actual transcript capture for this selected meeting and confirm capture stopped.\n'+JSON.stringify(state.meeting),{provider:state.meeting.agent});
api.readMeetingTranscript=()=>socialOperation('get_state').then(data=>data.meeting.transcript);
api.proposeMeetingSummary=()=>{
 if(!state.meeting.transcript.length)throw Error('Read a captured transcript before preparing a summary.');
 return socialWork('Prepare a source-backed meeting summary for the existing approval owner. Do not send it without approval.\n'+JSON.stringify(state.meeting));
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
async function refreshSocialConnections(){
 const data=await request('/api/universal/social-connections');
 if(!Array.isArray(data.items))throw Error('The connection owner did not return accounts. Open Connections and retry.');
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
async function settingsAction(functionName, args=[]) {
 const identity=state.profile.id;
 const graph=state.graph.id;
 const response=await request('/api/universal/settings-action',{function:functionName,args});
 const result=response.result;
 if(identity!==state.profile.id)throw Error('Your account changed while this action ran. Refresh the page before retrying.');
 if(!result||typeof result!=='object'||Array.isArray(result)||result.ok===false)throw Error(result?.error||result?.message||'Settings owner did not confirm the action. Refresh and retry.');
 if(['readOperations','setGraphWorkspaces'].includes(functionName)&&graph!==state.graph.id)throw Error('The graph changed while Settings ran. Refresh Settings before retrying.');
 const values={};
 for(const key of ['firms','activeFirm','people','billing','dependencies','officeInvitations','settingsScope','activeWorkspace','devices','activeDevice','backups'])if(Object.hasOwn(result,key))values[key]=result[key];
 if(result.workspacePolicies)values.workspaces=state.workspaces.map(row=>({...row,...result.workspacePolicies[row.id]}));
 if(result.workspaceIds)values.graph={...state.graph,workspaceIds:result.workspaceIds};
 if(result.profile){settingsProfile={...settingsProfile,...Object.fromEntries(Object.entries(result.profile).filter(([key])=>['name','firm','plan'].includes(key)))};values.profile={...state.profile,...settingsProfile};}
 publish(values);
 if(result.message)notice(result.message);
 if(result.open_url){
  const url=new URL(result.open_url);
  if(url.protocol!=='https:'||url.username||url.password)throw Error('Billing returned an unsafe browser destination. Refresh billing.');
  window.open(url.href,'_blank','noopener,noreferrer');
  notice('Continue in your browser, then refresh billing to confirm the result.');
 }
 return result;
}
for(const functionName of ['updateProfile','invitePerson','selectFirm','setTeamAccess','setBilling','refreshBilling','prepareCheckout','completeCheckout','retryPayment','downgradeBilling','manageDependency','checkDependencies','acceptOfficeInvitation','declineOfficeInvitation','archiveActivity','setWorkspaceRules','selectDevice','grantAccess','backUpNow','rollBack']) {
 api[functionName]=(...args)=>settingsAction(functionName,args);
}
api.refreshSettingsOperations=()=>settingsAction('readOperations',[state.graph.id]);
api.setGraphWorkspaces=ids=>settingsAction('setGraphWorkspaces',[state.graph.id,ids]);
api.setSettingsScope=async scope=>{const result=await settingsAction('setSettingsScope',[scope,state.activeWorkspace||state.graph.workspaceIds?.[0]||'',state.graph.id]);scopeEpoch++;await commands.load();project();await api.refreshSettingsOperations();return result;};
const settingsListWorkspaces=api.listWorkspaces;
api.listWorkspaces=async()=>{await settingsListWorkspaces();if(state.profile.signedIn)await api.refreshSettingsOperations();return copy(state.workspaces);};
const settingsSelectGraph=api.selectGraph;
api.selectGraph=async id=>{const result=await settingsSelectGraph(id);if(state.profile.signedIn)await api.refreshSettingsOperations();return result;};
api.refreshSettingsAccount=()=>settingsAction('read');
api.getUsageSummary=()=>({'Remaining messages':state.billing.remainingMessages??'Sign in and refresh billing','Plan':state.profile.plan});
api.setAccountPlan=plan=>api.setBilling({requestedPlan:plan});
function capabilityOwner(id){
 const capability=state.capabilities.find(c=>c.id===id);
 const owners=state.graph.nodes.filter(n=>n.id===id||n.kind===id||n.kind===capability?.nodeKind||capability?.descriptor?.engine&&n.kind===capability.descriptor.engine);
 return owners.length===1?owners[0]:null;
}
api.getCapabilityState=id=>{const owner=capabilityOwner(id),capability=state.capabilities.find(c=>c.id===id);return owner?{...capability,name:capability?.name||owner.title,params:owner.params}:null;};
api.getCapabilityParameters=id=>copy(capabilityOwner(id)?.parameterSchema||[]);
api.setCapabilityParameter=(id,key,value)=>{const owner=capabilityOwner(id);if(!owner)throw Error('Open the capability node on its canvas and select one exact instance before editing its parameters.');return nodeProperty(owner.id,key,value);};
api.pickCapabilityFolder=async(id,key)=>{const result=await request('/api/universal/workspace-roots',{action:'browse'});if(!result.path)return {cancelled:true,message:'Folder selection cancelled'};return api.setCapabilityParameter(id,key,result.path);};
const settingsExport=api.exportData;
api.exportData=async(name,nodeId)=>{
 if(name==='Dependency logs')return {name:'Dependency-logs.json',type:'application/json',content:JSON.stringify(state.dependencies.map(({id,logs})=>({id,logs})),null,2)};
 if(name.startsWith('Invoice ')){const invoice=state.billing.invoices.find(i=>i.id===name.slice(8));if(!invoice?.content)throw Error('Refresh billing and open the invoice from your billing provider.');return {name:invoice.number+'.txt',type:'text/plain',content:invoice.content};}
 return settingsExport(name,nodeId);
};
const settingsAccountRefresh=refreshAccount;
let settingsAccountIdentity='',settingsProfile={};
refreshAccount=async()=>{
 const profile=await settingsAccountRefresh();
 if(profile.id!==settingsAccountIdentity){
  settingsAccountIdentity=profile.id;settingsProfile={};
  publish({profile:{...state.profile,firm:'',plan:''},firms:[],activeFirm:'',people:[],officeInvitations:[],settingsScope:'User',activeWorkspace:'',activeDevice:'',devices:[],backups:[],workspaces:[],graph:{...state.graph,workspaceIds:[]},billing:{status:'',requestedPlan:'',cycle:'',checkout:null,invoices:[],plans:[]}});
  if(profile.signedIn)await api.refreshSettingsAccount();
 }else if(profile.signedIn){publish({profile:{...state.profile,...settingsProfile}});}
 return copy(state.profile);
};
api.syncAccount=async()=>{await refreshAccount();if(state.profile.signedIn){await api.refreshSettingsAccount();await api.listWorkspaces();}return copy(state.profile);};
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
const restUpdateGraph=api.updateGraph;
api.updateGraph=(id,values)=>Object.keys(values).every(key=>['name','pinned','documentation','customProperties','courtStatus','thumbnail'].includes(key))?restUpdateGraph(id,values):restCommand('updateGraph',[id,values]);
api.getDecisionState=id=>state.graph.nodes.find(node=>node.id===id)?.output?.decision??null;
api.readHostAvailability=async()=>request('/api/universal/hosts');
// WIRE-rest end
// Other contract operations have no verified backend owner: the fallback is a visible plain state.
// WIRE-projects
async function refreshProjectData() {
 const [schedules,templates]=await Promise.all([
  canvasOperation('project_schedules',[]),canvasOperation('list_skills',[])]);
 if(!Array.isArray(schedules)||!Array.isArray(templates))throw Error('The project owner returned an invalid schedule or template list. Refresh the graph and retry.');
 await refreshTasks();
 const feedback=state.tasks.filter(t=>t.title.startsWith('Feedback: ')).map(t=>({id:t.id,text:t.title.slice('Feedback: '.length),status:t.status,
  response:t.messages.filter(m=>m.role!=='user').map(m=>m.text||m.content||'').join('\n')}));
 publish({schedules,templates,feedback});
 return {schedules,templates};
}
const projectExport=api.exportData;
const projectRun=api.runNode;
const projectRunToHere=api.runToHere;
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
 async runNode(id){return projectRunResult(await projectRun(id));},
 async runToHere(id){return projectRunResult(await projectRunToHere(id));},
 async checkWatcherSource(){
  const node=state.graph.nodes.find(n=>n.params.engine==='lines.watch');
  if(!node)throw Error('Add a Watcher node from Library and wire its geometry input before running.');
  const result=await api.runToHere(node.id);
  const lines=result.lines?.[node.id];
  if(!Array.isArray(lines))throw Error('The source returned no line preview. Review the upstream node result and retry.');
  publish({watcher:{...state.watcher,source:node.id,host:node.title,status:lines.length?'loaded':'empty',geometry:{...state.watcher.geometry,walls:lines}}});
  return result;
 },
 async addSchedule(target,time){
  let roots;
  if(target===state.graph.id||target===state.graph.name)roots=state.graph.id;
  else{
   const node=state.graph.nodes.find(n=>n.id===target||n.title===target);
   const skill=state.templates.find(t=>t.id===target||t.title===target);
   if(node)roots=node.id;
   else if(skill){const opened=await api.openTemplateGraph(skill.id);const outgoing=new Set(skill.recipe.wires.map(pair=>pair[0]));roots=opened.nodes.filter((id,index)=>!outgoing.has(index));}
   else throw Error('Choose the node or saved skill to repeat on the canvas, then add its schedule.');
  }
  const result=await canvasOperation('add_schedule',[roots,time]);await refreshProjectData();return result;
 },
 async setScheduleEnabled(id,enabled){const result=await canvasOperation('set_schedule_enabled',[id,enabled]);await refreshProjectData();return result;},
 async setScheduleTime(id,time){const result=await canvasOperation('set_schedule_time',[id,time]);await refreshProjectData();return result;},
 async removeSchedule(id){const result=await canvasOperation('remove_schedule',[id]);await refreshProjectData();return result;},
 importRecipe:yaml=>canvasOperation('import_recipe',[yaml]),
 importFlow:flow=>canvasOperation('import_recipe',[flow]),
 async saveSkill(name){const result=await canvasOperation('save_skill',[name]);await refreshProjectData();return result;},
 openTemplateGraph:id=>canvasOperation('open_skill',[id]),
 async startTemplate(id){const opened=await api.openTemplateGraph(id);return projectRunResult(await mutate(()=>request('/api/universal/run-graph',{roots:opened.nodes})));},
 async exportRecipe(){return {name:'Recipe.yaml',type:'application/yaml',content:JSON.stringify(await canvasOperation('export_recipe',[]),null,2)};},
 async exportData(name,id){
  if(name==='Recipe')return api.exportRecipe();
  if(name.startsWith('Run ')){const run=state.runs.find(r=>'Run '+r.id===name);if(!run)throw Error('Open a current run before exporting.');return {name:'Run.json',type:'application/json',content:JSON.stringify(run.rows,null,2)};}
  if(name==='Receipts'||name==='Issues')return {name:name+'.json',type:'application/json',content:JSON.stringify(name==='Receipts'?state.receipts:state.modelReview.issues,null,2)};
  return projectExport(name,id);
 },
 async setWireRule(id,rule){
  const wire=canvas.wires.find(w=>w.id===id);if(!wire)throw Error('The wire changed. Select it again and retry.');
  const condition=(wire.params||[]).find(p=>p.label==='condition');
  return mutate(()=>condition?request('/api/universal/set-property',{relation:condition.relation,value:rule}):
   request('/api/universal/wire-property',{wire:id,label:'condition',value:rule}));
 },
 async setWireVisibility(value){
  if(!['Visible','Faint','Hidden'].includes(value))throw Error('Choose a wire visibility from the list.');
  publish({graph:{...state.graph,wireVisibility:value}});return {value};
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
  const task=await api.sendToBaboom('Feedback: '+text);
  if(task?.ok===false)return task;
  publish({feedback:[...state.feedback,{id:task.id,text,status:task.status,response:''}]});return task;
 },
 async checkFeedback(id){
  await refreshTasks();const task=state.tasks.find(t=>t.id===id);
  if(!task)throw Error('Open this feedback task in Workshop and refresh its current status.');
  const response=task.messages.filter(m=>m.role!=='user').map(m=>m.text||m.content||'').join('\n');
  publish({feedback:state.feedback.map(f=>f.id===id?{...f,status:task.status,response}:f)});return task;
 },
 async refreshProjects(){await commands.load();project();return refreshProjectData();},
 async tickSchedules(){const result=await request('/api/universal/canvas-op',{op:'scheduler_tick',args:[]});await commands.load();project();return result.result;},
});
// WIRE-projects end
// OPS-projects2: confirmed projections of the existing domain owners.
async function refreshProjectState(){
 const result=await canvasOperation('project_state',[]);
 publish({graph:{...state.graph,versions:result.versions},modelReview:result.modelReview,
  suggestions:state.suggestions.filter(row=>!result.dismissed.includes(row.id))});
 return result;
}
api.addInterfaceElement=async kind=>{const result=await canvasOperation('add_interface_element',[kind]);return state.graph.nodes.find(n=>n.id===result.id)||result;};
api.setPortVisibility=(id,port,value)=>canvasOperation('set_port_visibility',[id,port,value]);
api.setPromotedParameter=(id,key,values)=>canvasOperation('set_promoted_parameter',[id,key,values]);
api.refreshMods=async()=>{const result=await request('/api/universal/mods',{action:'state'});publish({mods:result.mods.rows});project();return result.mods.rows;};
api.importModNode=(id,item)=>canvasOperation('import_mod_node',[id,item]);
api.refreshLibraryPorts=async()=>{const libraryPorts=await canvasOperation('library_ports',[]);publish({libraryPorts});return libraryPorts;};
api.compatibleNodes=endpoint=>{
 const node=state.graph.nodes.find(n=>n.id===endpoint?.id);
 const port=(endpoint?.side==='out'?node?.outputs:node?.inputs)?.find(p=>p.id===endpoint.port);
 if(!port)return [];
 const side=endpoint.side==='out'?'target':'source';
 return (state.libraryPorts||[]).filter(entry=>entry.ports[side].some(p=>p.type!=='unknown'&&(p.type===port.type||[p.type,port.type].includes('any')))).map(entry=>({id:entry.id,name:entry.title}));
};
api.addCompatibleNode=(endpoint,item,position)=>canvasOperation('add_compatible_node',[endpoint,item,position]);
api.insertConvert=wire=>canvasOperation('insert_convert',[typeof wire==='string'?wire:wire?.id||wire]);
api.addTemplateNode=async id=>{const opened=await api.openTemplateGraph(id);return mutate(()=>commands.composition('group',opened.nodes));};
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
api.saveGraphVersion=async()=>{const result=await canvasOperation('save_graph_version',[]);await refreshProjectState();return result;};
api.restoreGraphVersion=async id=>{const result=await canvasOperation('restore_graph_version',[id]);await refreshProjectState();return result;};
api.reviewModel=async operation=>{
 const result=await canvasOperation('review_model',[operation]);
 projectRunResult(result.run);publish({modelReview:result.modelReview});return result;
};
api.updateReviewIssue=async(id,values)=>{const result=await canvasOperation('update_review_issue',[id,values]);await refreshProjectState();return result;};
api.dismissSuggestion=async id=>{const result=await canvasOperation('dismiss_suggestion',[id]);await refreshProjectState();return result;};
api.refreshMcpServers=async()=>{const result=await canvasOperation('mcp_servers',[]);publish({mcpServers:result});return result;};
api.discoverMcpTools=async(id,kind='Tools')=>{const result=await canvasOperation('discover_mcp_tools',[id,kind]);await api.refreshMcpServers();return result;};
api.reconnectMcp=async id=>{const result=await canvasOperation('reconnect_mcp',[id]);await api.refreshMcpServers();return result;};
api.importMcpTool=(id,tool)=>canvasOperation('import_mcp_tool',[id,tool]);
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
const refreshBeforeOps=api.refreshProjects;
api.refreshProjects=async()=>{await refreshBeforeOps();await refreshProjectState();await api.refreshFiles();await api.refreshMods();await api.refreshLibraryPorts();await api.refreshMcpServers();return api.refreshCommunity();};
api.ready=(async()=>{
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
 session=window.ARCHHUB_BOOT;
 if(!session){try{session=JSON.parse(sessionStorage.getItem('archhub.studio.session')||'null');}catch { notice('The saved browser session could not be read. Reconnecting this window.'); }}
 if(!session?.token||!session?.csrf)await signIn();else window.__archhubSession=session;
 commands=window.ArchHubStudioAuthority.create({get:path=>request(path),post:(path,body)=>request(path,body)});
 await commands.load();project();
 publish({learning:{...state.learning,layer:'Host'}});
 ready=true;watchRefresh();
 // Account/network discovery must not hold the usable graph behind its timeout.
 void (async()=>{
  for(const refresh of [refreshApplicationUpdate,refreshAccount,refreshGraphs,api.listWorkspaces,api.listProviders,refreshTasks,refreshAgents]){
   try{await refresh();}catch(error){publish({connectionNotice:error.message});}
  }
 })();
 return state;
})();
// WIRE-projects: tick existing schedule nodes while the desktop is open, including hidden pages.
api.ready.then(()=>{
 if(state.nativeApproval || typeof window.setInterval!=='function')return;
 let ticking=false;
 const tick=()=>{
  if(ticking)return;ticking=true;
  return api.tickSchedules()
   .catch(failure=>notice(failure.message+' Review Schedules, then retry.'))
   .finally(()=>{ticking=false;});
 };
 const timer=window.setInterval(tick,ownerRefreshMs);
 void api.refreshProjects().catch(failure=>notice(failure.message+' Retry loading the graph.'));
 window.addEventListener('pagehide',()=>window.clearInterval(timer),{once:true});
}).catch(error=>notice(error.message));
// WIRE-projects end
window.ArchHubAPI=Object.freeze(api);
})();
