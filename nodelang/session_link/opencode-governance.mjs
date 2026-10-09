import {spawn} from 'node:child_process';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

const fail = reason => {throw new Error('ArchHub OpenCode governance: '+reason);};
class NativeNotDelivered extends Error {}
const notDelivered = reason => {throw new NativeNotDelivered('ArchHub OpenCode governance: '+reason+'; tool not delivered');};
const object = value => value && typeof value==='object' && !Array.isArray(value);
const readTools = new Set(['read','glob','grep','list','skill']);
const shellTools = new Set(['bash','powershell']);
// Tools the native owner itself executes for this exact session: selected Work,
// and messages to other agents under the owner's own coordination identity.
const nativeTools = new Set(['archhub_work','archhub_message']);
// Only these tools' effects are fully accounted by the owner's permit/receipt
// ledger (reads have none; write/edit hold a permit until receipted).
const stringify = value => JSON.stringify(value, (_key,item)=>object(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const toolClassification = new Map([
 ...[...readTools].map(tool=>[tool,'read']),
 ['write','write'],['edit','write'],
 ['bash','execute'],['powershell','execute'],
 ['archhub_work','execute'],['archhub_message','execute'],
 ['archhub-hosts_hosts_state','read'],
 ['archhub-hosts_office_read','read'],
 ['archhub-hosts_outlook_inbox','read'],
 ['archhub-hosts_notion_search','read'],
 ['archhub-hosts_dropbox_list','read'],
 ['archhub-hosts_revit_ping','read'],['archhub-hosts_revit_info','read'],
 ['archhub-hosts_revit_execute_csharp','execute'],
 ['archhub-hosts_revit_screenshot','execute'],
 ['archhub-hosts_acad_ping','read'],['archhub-hosts_acad_info','read'],
 ['archhub-hosts_acad_execute_csharp','execute'],
 ['archhub-hosts_max_ping','read'],['archhub-hosts_max_info','read'],
 ['archhub-hosts_max_execute_python','execute'],['archhub-hosts_max_execute_maxscript','execute'],
 ['archhub-hosts_blender_ping','read'],['archhub-hosts_blender_execute_python','execute'],
 ['archhub-hosts_rhino_ping','read'],['archhub-hosts_rhino_execute_python','execute'],
 ['archhub_agent_coordination_coordination_ping','read'],
 ['archhub_agent_coordination_coordination_info','read'],
 ['archhub_agent_coordination_coordination_list_agents','read'],
 ['archhub_agent_coordination_coordination_read_messages','read'],
 ['archhub_agent_coordination_coordination_read_message','read'],
 ['archhub_agent_coordination_native_owner_status','read'],
 ['archhub_agent_coordination_native_owner_inspect_effects','read'],
 ['archhub_agent_coordination_coordination_send_message','execute'],
 ['archhub_agent_coordination_coordination_acknowledge_message','execute'],
 ['archhub_agent_coordination_native_work_artifact_material','read'],
 ['archhub_agent_coordination_native_work_read_artifact','read'],
 ['archhub_agent_coordination_native_work_assignment','read'],
 ['archhub_agent_coordination_native_work_current','read'],
 ['archhub_agent_coordination_native_work_material','read'],
 ['archhub_agent_coordination_native_work_configuration','read'],
 ['archhub_agent_coordination_native_work_plan_read','read'],
 ['archhub_agent_coordination_native_work_reconcile','read'],
 ['archhub_agent_coordination_native_work_claim','execute'],
 ['archhub_agent_coordination_native_work_release','execute'],
 ['archhub_agent_coordination_native_work_configure','execute'],
 ['archhub_agent_coordination_native_work_plan_draft','execute'],
 ['archhub_agent_coordination_native_work_submit','execute'],
 ['archhub_agent_coordination_native_work_request_court','execute'],
 ['archhub_agent_coordination_native_work_publish_artifact','execute'],
 ['archhub_agent_coordination_native_work_review_artifact','execute'],
 ['archhub_agent_coordination_native_work_task_attach','execute'],
 ['archhub_agent_coordination_native_work_task_detach','execute'],
 ['archhub_agent_coordination_native_owner_resume','execute'],
 ['archhub_agent_coordination_native_owner_recover','execute'],
 ['archhub_agent_coordination_native_connection_recover','execute'],
 ['archhub_agent_coordination_native_resume_recover','execute'],
 ['archhub_agent_coordination_native_owner_settle_effect','execute'],
]);

function toolClass(tool) {
 return typeof tool==='string'?toolClassification.get(tool):undefined;
}

function isLedgerTool(tool) {
 const kind=toolClass(tool);
 return kind==='read'||tool==='write'||tool==='edit';
}

function mappedMcpTool(tool) {
 if(typeof tool!=='string')return null;
 let server='',name='';
 if(tool.startsWith('archhub-hosts_')){server='archhub-hosts';name=tool.slice('archhub-hosts_'.length);}
 else if(tool.startsWith('archhub_agent_coordination_')){server='archhub_agent_coordination';name=tool.slice('archhub_agent_coordination_'.length);}
 else return null;
 if(!name||name.length>128||!/^[A-Za-z0-9_.-]+$/.test(name))fail('tool has no verified governance mapping: '+tool);
 const kind=toolClass(tool);
 if(!kind)fail('tool has no verified governance mapping: '+tool);
 return {toolName:'mcp__'+server+'__'+name,read:kind==='read'};
}

function isReadTool(tool) {
 return toolClass(tool)==='read';
}

// The private installed loader supplies the existing admitted gate command.
// No shell, Bun global, source-checkout lookup, enrollment or fallback service.
export function createNativeGateRunner(command,args,{expectedSessions={},selectedWorks={},sessionLink=null,laneFolders={}}={}) {
 if(!path.isAbsolute(command)||!Array.isArray(args)||args.some(a=>typeof a!=='string'))fail('trusted native gate command required');
 if(!object(expectedSessions)||Object.keys(expectedSessions).length>128||Object.entries(expectedSessions).some(([session,actor])=>
    !/^ses_[A-Za-z0-9]+$/.test(session)||typeof actor!=='string'||!/^app:agent-session:runtime:[a-f0-9]{32}$/.test(actor)))fail('exact recovery session identities required');
 // Quarantine keeps the exact actor, delivery state and any release ack. A
 // fresh owner is allowed only after positive no-enrollment evidence, once.
 const workers=new Map(),lineages=new Map(),queues=new Map(),quarantined=new Map(),probes=new Map(),reenrolls=new Map();
 if(!object(laneFolders)||Object.keys(laneFolders).length>128||Object.entries(laneFolders).some(([session,lane])=>
    !/^ses_[A-Za-z0-9]+$/.test(session)||typeof lane!=='string'||!path.isAbsolute(lane)||lane.length>1024||lane.includes('\0')))fail('trusted lane folders required');
 if(!object(selectedWorks)||Object.keys(selectedWorks).length>128||Object.entries(selectedWorks).some(([session,work])=>
    !/^ses_[A-Za-z0-9]+$/.test(session)||typeof work!=='string'||!work.startsWith('assembly-instance:')||work.length>512||work.trim()!==work))fail('trusted selected Work identities required');
 if(sessionLink!==null&&(!object(sessionLink)||typeof sessionLink.node!=='string'||!path.isAbsolute(sessionLink.node)||
    typeof sessionLink.stateDirectory!=='string'||!path.isAbsolute(sessionLink.stateDirectory)||!object(sessionLink.connections)||
    Object.keys(sessionLink.connections).length>128||Object.entries(sessionLink.connections).some(([session,ids])=>
     !/^ses_[A-Za-z0-9]+$/.test(session)||!Array.isArray(ids)||!ids.length||ids.length>16||new Set(ids).size!==ids.length||
     ids.some(id=>typeof id!=='string'||!/^[a-f0-9]{16}$/.test(id)))))fail('exact Session Link recovery configuration required');
 if(Object.keys(selectedWorks).some(session=>!sessionLink?.connections[session]))fail('selected Work requires its native Session Link configuration');
 for(const [session,actor] of Object.entries(expectedSessions))lineages.set(session,actor);
 let next=0;
 const dispatch=event=>{
  // Reject local input before acquiring a child, actor slot or lineage.
  const id=String(++next);
  let payload;
  try{payload=Buffer.from(JSON.stringify({request_id:id,event})+'\n','utf8');}
  catch(_){notDelivered('native input serialization failed');}
  if(payload.length>1024*1024)notDelivered('native input byte limit');
  if(!object(event)||typeof event.session_id!=='string'||!/^ses_[A-Za-z0-9]+$/.test(event.session_id)||
     typeof event.cwd!=='string'||!path.isAbsolute(event.cwd)||typeof event.tool_use_id!=='string'||
     !event.tool_use_id||event.tool_use_id.length>256)notDelivered('native input identity is invalid');
  const held=quarantined.get(event.session_id);
  if(held&&!held.actor&&!held.ack&&!held.delivered){
   quarantined.delete(event.session_id);
   probes.delete(event.session_id);
  }else if(held&&!held.actor&&!held.ack)notDelivered('native session quarantined; no duplicate enrollment; reconcile no recorded graph actor; coordinator: '+coordinator(event.session_id,null));
  else if(held)return reconcile(event.session_id).then(verdict=>{
   if(verdict.outcome==='unknown')notDelivered('native session quarantined; no duplicate enrollment; reconcile '+verdict.reason+'; coordinator: '+verdict.command);
   return dispatch(event);
  });
  let state=workers.get(event.session_id);
  // An idle check asks a live owner only; it never spawns, enrolls or renews one.
  if(!state&&event.hook_event_name==='Stop')notDelivered('no live native owner for the idle check');
  if(!state){
   if(workers.size>=4)notDelivered('native owner capacity reached');
   if(!lineages.has(event.session_id)&&lineages.size>=128)notDelivered('native identity retention capacity reached');
   if(!lineages.has(event.session_id))lineages.set(event.session_id,null);
   const child=spawn(command,args,{shell:false,windowsHide:true,cwd:event.cwd,stdio:['pipe','pipe','pipe'],env:{...process.env,
    ARCHHUB_COORDINATION_VENDOR:'opencode',ARCHHUB_AGENT_RUNTIME:'opencode',ARCHHUB_EXTERNAL_SESSION_ID:event.session_id,
    OPENCODE_SESSION_ID:event.session_id,
    ARCHHUB_EXPECTED_AGENT_SESSION:lineages.get(event.session_id)||'',
    ARCHHUB_SELECTED_WORK:selectedWorks[event.session_id]||'',
    ARCHHUB_ADMITTED_LANE:laneFolders[event.session_id]||'',
    ...(sessionLink?{SESSION_LINK_NODE:sessionLink.node,SESSION_LINK_STATE_DIR:sessionLink.stateDirectory,
      SESSION_LINK_REQUIRED_CONNECTIONS:(sessionLink.connections[event.session_id]||[]).join(',')}:{}),
    PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'}});
   state={child,cwd:event.cwd,failed:false,pending:null,buffer:Buffer.alloc(0),stderrBytes:0};workers.set(event.session_id,state);
   const abort=reason=>{
    state.failed=true;state.buffer=Buffer.alloc(0);
    // Preserve an in-flight native owner after caller uncertainty; no respawn.
    for(const key of ['pending','notDelivered'])if(state[key]){
     clearTimeout(state[key].timer);state[key].reject(new Error('ArchHub OpenCode governance: '+reason+'; retained outcome requires reconciliation'));state[key]=null;
    }
   };
   state.abort=abort;
   child.on('error',()=>abort('native gate launch failed'));
   child.stdin.on('error',()=>abort('native gate input failed'));
   child.on('close',code=>{
    if(code===0&&state.released&&!state.pending&&!state.failed&&!state.buffer.length){
     workers.delete(event.session_id);
     if(state.notDelivered){clearTimeout(state.notDelivered.timer);state.notDelivered.resolve({allow:false,notDelivered:true});state.notDelivered=null;}
     state.closed?.resolve();
    }else{
     abort('native owner closed without confirmed release');
     const provenNeverEnrolled = state.neverBound===true&&!state.actor&&!lineages.get(event.session_id)&&
      (state.preAdmissionRefused||state.inputUndelivered)&&!state.pending&&!state.notDelivered&&!state.deliveryUncertain;
     const usedReenrolls = reenrolls.get(event.session_id)||0;
     if(provenNeverEnrolled&&usedReenrolls<1){
      reenrolls.set(event.session_id,usedReenrolls+1);
      probes.delete(event.session_id);
     }else quarantined.set(event.session_id,{actor:state.actor||lineages.get(event.session_id)||null,cwd:state.cwd,
      delivered:!!(state.actor||state.lastCompleted||state.released||state.deliveryUncertain||provenNeverEnrolled),
      ack:state.released?.released===true&&!state.notDelivered?state.released:null});
     workers.delete(event.session_id);
     state.closed?.reject(new Error('native release uncertain'));
    }
   });
   child.stderr.on('data',data=>{if(state.failed)return;state.stderrBytes+=data.length;if(state.stderrBytes>65536)abort('native diagnostics byte limit');});
   const receive=line=>{
    if(state.released){abort('native frame after release');return;}
    const held=state.pending;
    let reply;
    try{reply=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(line));}catch(_){abort('invalid native UTF-8 JSON');return;}
    if(reply.kind==='released'||reply.kind==='release-refused'){
     if(reply.session_id!==event.session_id||reply.agent_session!==state.actor||
        reply.last_request_id!==(state.lastCompleted??null)||
        !/^[a-f0-9]{32}$/.test(reply.release_id)||!state.actor){abort('native release handshake mismatch');return;}
     if(reply.kind==='release-refused'&&reply.released===false&&reply.retained===true){
      const closed=state.closed;state.closed=null;closed?.reject(new Error('native release refused; exact owner retained'));return;
     }
     if(reply.released!==true){abort('native release outcome unavailable');return;}
     // The worker seals its last evaluated request before exiting. A request
     // written after that watermark was not evaluated. Wait for clean exit
     // before reporting non-delivery; never automatically replay the tool.
     if(held){state.pending=null;state.notDelivered=held;}
     state.released=reply;return;
    }
    if(!held){abort('unexpected native reply');return;}
    if(held.stop&&reply.request_id===held.id&&(reply.error||reply.decision!=='allow')){
     // A refused or failed idle check reads as "no open Work"; the owner stays usable.
     clearTimeout(held.timer);state.pending=null;state.lastCompleted=held.id;held.resolve({allow:true,toolOutput:'{}'});return;
    }
    // A reply naming another actor is an identity failure before anything else.
    if(reply.agent_session!==undefined&&(!state.actor?lineages.get(event.session_id)&&reply.agent_session!==lineages.get(event.session_id)
       :reply.agent_session!==state.actor)){abort('native graph identity changed');return;}
     if(reply.request_id===held.id&&reply.session_id===event.session_id&&reply.tool_use_id===held.call&&
       reply.admitted===false&&reply.decision==='deny'&&(reply.never_bound===true||lineages.get(event.session_id))&&
       typeof reply.error==='string'&&!state.actor&&reply.agent_session===undefined){
     // Only a never-bound owner proves this frame was not admitted: no permit can
     // exist, so this is a clean denial with its reason. Every other error keeps
     // custody (abort) below; an invalid or missing decision is a protocol failure.
     const why=[reply.error,reply.reason].filter(v=>typeof v==='string'&&v).join(': ');
      clearTimeout(held.timer);state.pending=null;state.lastCompleted=held.id;state.deliveryUncertain=false;state.preAdmissionRefused=true;
      state.neverBound=reply.never_bound===true;
     if(lineages.get(event.session_id)){
      // A continuation that never bound is not retried by this worker. Retire it:
      // its exit is reconciled against the owner's custody before a fresh worker.
      state.retiring=true;try{state.child.stdin.end();}catch(_){}
     }
     held.resolve({allow:false,reason:('native owner could not decide: '+why).slice(0,1024)});return;
    }
    if(reply.request_id!==held.id||reply.session_id!==event.session_id||reply.tool_use_id!==held.call||
       reply.error||!['allow','deny'].includes(reply.decision)){abort('native reply identity or outcome unavailable');return;}
    if(!/^app:agent-session:runtime:[a-f0-9]{32}$/.test(reply.agent_session)||
       (state.actor&&state.actor!==reply.agent_session)||
       (!state.actor&&lineages.get(event.session_id)&&
        (lineages.get(event.session_id)!==reply.agent_session||reply.continued!==true))){abort('native graph identity changed');return;}
    state.actor=reply.agent_session;lineages.set(event.session_id,state.actor);
    state.lastCompleted=held.id;
    clearTimeout(held.timer);state.pending=null;
    held.resolve({allow:reply.decision==='allow',toolOutput:reply.tool_output,
     ...(reply.decision==='deny'&&typeof reply.reason==='string'?{reason:reply.reason.slice(0,1024)}:{})});
   };
   child.stdout.on('data',data=>{
    if(state.failed)return;
    state.buffer=Buffer.concat([state.buffer,data]);
    if(state.buffer.length>1024*1024){abort('native reply byte limit');return;}
    while(!state.failed){
     const end=state.buffer.indexOf(10);if(end<0)break;
     const line=state.buffer.subarray(0,end);state.buffer=state.buffer.subarray(end+1);receive(line);
    }
   });
  }
  if(state.cwd!==event.cwd)notDelivered('native session workspace changed');
  if(state.retiring)notDelivered('native owner is retiring after an unreachable application; retry after reconciliation');
  if(state.failed||state.pending||state.released||state.closed)notDelivered('native owner unavailable or already active; no duplicate enrollment');
  return new Promise((resolve,reject)=>{
   const stop=event.hook_event_name==='Stop';
   // An idle check never fails its owner: past 10 s it reads as "no open Work" and its
   // late reply is absorbed below; every tool call keeps the 30 s abort.
   state.pending={id,call:event.tool_use_id,resolve,reject,stop,timer:setTimeout(()=>{
    if(stop)resolve({allow:true,toolOutput:'{}'});else state.abort('native gate timeout');},stop?10000:30000)};
   setTimeout(()=>{
    if(state.failed||state.pending?.id!==id)return;
    try{
     if(!state.child.stdin.writable)throw new Error('native gate input unavailable');
     state.child.stdin.write(payload);
     state.deliveryUncertain=true;
    }catch(_){state.inputUndelivered=true;state.abort('native gate input failed');}
   },0);
  });
 };
 const coordinator=(session,actor)=>[command,...args,'--reconcile-status',session,actor||'<actor>'].join(' ');
 // One read-only owner inspection per session at a time; an unknown verdict is
 // reused for 15 seconds so a blocked session cannot spawn a probe per call.
 const reconcile=session=>{
  const held=quarantined.get(session);
  if(!held)return Promise.resolve(workers.has(session)?
   {outcome:'unknown',reason:'native owner still live',command:coordinator(session,lineages.get(session))}:null)
   .then(live=>live||probe(session,lineages.get(session),process.cwd(),null));
  return probe(session,held.actor,held.cwd,held.ack).then(verdict=>{
   if(verdict.outcome!=='unknown'&&quarantined.get(session)===held)quarantined.delete(session);
   return verdict;
  });
 };
 const probe=(session,actor,cwd,ack)=>{
  const command_=coordinator(session,actor);
  if(ack&&ack.agent_session===actor&&/^[a-f0-9]{32}$/.test(ack.release_id))
   return Promise.resolve({outcome:'released',reason:'release acknowledged '+ack.release_id,command:command_});
  if(!actor)return Promise.resolve({outcome:'unknown',reason:'no recorded graph actor',command:command_});
  const cached=probes.get(session);
  if(cached&&(cached.promise||Date.now()-cached.at<15000))return cached.promise||Promise.resolve(cached.verdict);
  const entry={at:Date.now(),verdict:null,promise:null};
  entry.promise=new Promise(resolve=>{
   const unknown=reason=>resolve({outcome:'unknown',reason,command:command_});
   let child;
   try{child=spawn(command,[...args,'--reconcile'],{shell:false,windowsHide:true,cwd,stdio:['ignore','pipe','ignore'],env:{...process.env,
    ARCHHUB_COORDINATION_VENDOR:'opencode',ARCHHUB_AGENT_RUNTIME:'opencode',ARCHHUB_EXTERNAL_SESSION_ID:session,
    OPENCODE_SESSION_ID:session,ARCHHUB_EXPECTED_AGENT_SESSION:actor,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'}});}
   catch(_){unknown('owner inspection launch failed');return;}
   let out=Buffer.alloc(0);
   const timer=setTimeout(()=>{child.kill();},30000);
   child.on('error',()=>{clearTimeout(timer);unknown('owner inspection launch failed');});
   child.stdout.on('data',data=>{out=Buffer.concat([out,data]);if(out.length>65536)child.kill();});
   child.on('close',()=>{
    clearTimeout(timer);
    let reply=null;
    try{reply=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(out).trim().split('\n').pop());}catch(_){}
    if(!object(reply)||reply.kind!=='reconciled'||reply.session_id!==session||reply.agent_session!==actor||
       !['released','owner-gone','unknown'].includes(reply.outcome)||typeof reply.reason!=='string'){unknown('owner inspection unavailable');return;}
    resolve({outcome:reply.outcome,reason:reply.reason.slice(0,256),command:command_});
   });
  }).then(verdict=>{entry.promise=null;entry.verdict=verdict;entry.at=Date.now();
   if(verdict.outcome!=='unknown')probes.delete(session);return verdict;});
  probes.set(session,entry);
  return entry.promise;
 };
 const run=event=>{
  const key=event.session_id,prior=queues.get(key);
  if(prior?.count>=64)notDelivered('native request queue capacity reached');
  const promise=prior?prior.promise.then(()=>dispatch(event),()=>notDelivered('prior native request unresolved')):dispatch(event);
  const entry={promise,count:(prior?.count||0)+1};queues.set(key,entry);
  const clear=()=>{if(queues.get(key)===entry)queues.delete(key);};
  promise.then(clear,clear);return promise;
 };
 run.reconcile=reconcile;
 // session.idle: the Work verdict of this session's LIVE owner, or null. Only a
 // session configured with selected Work is asked; a failure is null, never a block.
 run.idle=(session,cwd)=>{
  const state=workers.get(session);
  if(!selectedWorks[session]||!state||state.failed||state.pending||state.released||state.closed||state.cwd!==cwd)
   return Promise.resolve(null);
  return Promise.resolve().then(()=>run({session_id:session,cwd,tool_use_id:'idle-'+randomUUID(),vendor:'opencode',hook_event_name:'Stop'}))
   .then(result=>{
    let verdict=null;try{verdict=JSON.parse(result.toolOutput);}catch(_){}
    return object(verdict)&&verdict.decision==='block'&&typeof verdict.reason==='string'?verdict:null;
   },()=>null);
 };
 run.close=async()=>{
  if(queues.size)fail('native requests remain unresolved');
  for(const state of workers.values())if(state.pending||state.failed)fail('native outcome unresolved');
  const done=[];
  for(const [session_id,state] of workers){
   if(state.pending||state.failed)fail('native outcome unresolved');
   if(!state.closed){
    const promise=new Promise((resolve,reject)=>{state.closed={resolve,reject};});
    const timer=setTimeout(()=>{state.abort('native release timeout');state.closed.reject(new Error('native release uncertain'));},30000);
    state.closed.promise=promise.finally(()=>clearTimeout(timer));
    if(!state.released)state.child.stdin.write(JSON.stringify({command:'release',session_id})+'\n');
   }
   done.push(state.closed.promise);
  }
  await Promise.all(done);
 };
 return run;
}

function normalized(tool,args) {
 if(!object(args))fail('native tool arguments unavailable');
 if(tool==='skill'&&(Object.keys(args).length!==1||typeof args.name!=='string'||!args.name.trim()||args.name.length>256))fail('native skill arguments unavailable');
 if(tool==='write')return {tool_name:'Write',tool_input:{file_path:args.filePath,content:args.content}};
 if(tool==='edit')return {tool_name:'Edit',tool_input:{file_path:args.filePath,old_string:args.oldString,new_string:args.newString,replace_all:args.replaceAll===true}};
 if(nativeTools.has(tool)){
  if(Object.keys(args).sort().join(',')!=='arguments,operation'||typeof args.operation!=='string'||!object(args.arguments))fail((tool==='archhub_work'?'selected Work':'agent message')+' arguments unavailable');
  return {tool_name:tool,tool_input:args};
 }
 const mcp=mappedMcpTool(tool);
 if(mcp)return {tool_name:mcp.toolName,tool_input:args};
 if(readTools.has(tool))return {tool_name:tool,tool_input:args};
 if(shellTools.has(tool)){
  // Admission is the shared shell allowlist in the native gate; nothing else runs.
  if(typeof args.command!=='string'||!args.command.trim()||args.command.length>8192||
     (args.workdir!==undefined&&(typeof args.workdir!=='string'||!args.workdir)))fail('native shell arguments unavailable');
  return {tool_name:'Bash',tool_input:{command:args.command,...(args.workdir?{workdir:args.workdir}:{})}};
 }
 fail('tool has no verified governance mapping: '+String(tool));
}

export function createOpenCodeGovernance({gateCommand,gateArgs,gateRunner,expectedSessions,selectedWorks={},workToolFactory,sessionLink,laneFolders={},readStaleMs=60000}) {
 const invoke=gateRunner||createNativeGateRunner(gateCommand,gateArgs,{expectedSessions,selectedWorks,sessionLink,laneFolders});
 // Retained for all workspaces in this loaded plugin; never clear on idle/error.
 const pending=new Map();
 // Sessions re-prompted once for open Work; their next idle passes (OpenCode's
 // stop_hook_active). Shared across workspaces of this loaded plugin.
 const nudged=new Set(),checking=new Set();
 return async ({directory,client})=>{
  if(!path.isAbsolute(directory))fail('native workspace unavailable');
  const identity=input=>{
   if(!input || typeof input.sessionID!=='string'||!/^ses_[A-Za-z0-9]+$/.test(input.sessionID)||
      typeof input.callID!=='string'||!input.callID||input.callID.length>256)fail('native session/call identity unavailable');
   return input.sessionID+'\0'+input.callID;
  };
  // One execution path for every owner-executed tool: the call must match an
  // admission this session's before-hook recorded; lost output is never replayed.
  const nativeExecute=(tool,label)=>async(args,context)=>{
   const record=[...pending.values()].find(p=>p.session===context.sessionID&&p.stamp===args._archhub_call);
   const {_archhub_call,...original}=args;
   if(!record||record.tool!==tool||record.state!=='admitted'||record.args!==stringify(original)||context.directory!==directory)fail(label+' execution has no matching native admission');
   record.state='executing';
   try{
    const result=await invoke({...record.event,hook_event_name:'NativeToolExecute'});
    if(!result.allow||typeof result.toolOutput!=='string')fail(label+' output unavailable; reconcile before retry');
    record.state='executed';return result.toolOutput;
   }catch(error){record.state='uncertain';throw error;}
  };
  const nativeArgs=()=>({operation:workToolFactory.schema.string(),arguments:workToolFactory.schema.object({}).passthrough(),_archhub_call:workToolFactory.schema.string().optional()});
  return {
   ...(workToolFactory?{tool:{
    archhub_work:workToolFactory({
     description:'Use this native session’s configured Workshop task. Attachment does not grant execution or file permission.',
     args:nativeArgs(),execute:nativeExecute('archhub_work','selected Work'),
    }),
    // OpenCode starts MCP servers once per app, so a coordination MCP there has no
    // session identity. Messages go through this session's own native owner instead.
    archhub_message:workToolFactory({
     description:'Message other ArchHub agents as this OpenCode session. operation is one of coordination.list_agents, coordination.send_message (target, message, idempotency_key, reply_to?), coordination.read_messages (limit?, before?), coordination.read_message (message_id, sequence), coordination.acknowledge_message (message_id, sequence, idempotency_key); arguments holds its fields. A lost reply is never resent.',
     args:nativeArgs(),execute:nativeExecute('archhub_message','agent message'),
    }),
   }}:{}),
   dispose:async()=>{if(pending.size)fail('native receipts remain unresolved');await invoke.close?.();},
   // No idle turn end with open Work: OpenCode cannot block a stop, so a session that
   // goes idle with open Work is prompted once to continue; its next idle passes.
   event:async({event})=>{
    if(event?.type!=='session.idle'||typeof invoke.idle!=='function')return;
    const session=event.properties?.sessionID;
    if(typeof session!=='string'||!/^ses_[A-Za-z0-9]+$/.test(session))return;
    if(nudged.delete(session)||checking.has(session))return;
    // Concurrent idles of one session send a single prompt.
    checking.add(session);
    try{
     const verdict=await invoke.idle(session,directory);
     if(!verdict||!client?.session?.prompt)return;
     nudged.add(session);
     await client.session.prompt({path:{id:session},query:{directory},body:{parts:[{type:'text',
      text:verdict.reason.slice(0,4000)+' (ArchHub: this session still has open Work; continue it. This reminder is sent once per turn.)'}]}});
    }finally{checking.delete(session);}
   },
   'tool.execute.before':async(input,output)=>{
    const key=identity(input);
    const read=isReadTool(input.tool);
    // OpenCode never runs tool.execute.after for an aborted or failed call. A read
    // admitted long ago with no receipt has ended; reads carry no write effect,
    // so drop it instead of refusing every later tool in the session forever.
    for(const [held,p] of pending)if(p.session===input.sessionID&&p.read&&p.state==='admitted'&&
       Date.now()-p.admittedAt>=readStaleMs)pending.delete(held);
    const blocker=()=>pending.get(key)||[...pending.values()].find(p=>p.session===input.sessionID&&
       (!read||!p.read||!['preparing','admitted','settling'].includes(p.state)));
    let blocking=blocker();
    // Uncertain read/write/edit records settle only on the owner's verdict:
    // released or gone with zero unreceipted permits proves no open write effect.
    // Shell calls and Work executions carry no permit, so the ledger cannot
    // prove their outcome; they stay retained and keep refusing.
    if(blocking&&blocking.state==='uncertain'&&invoke.reconcile&&!pending.get(key)&&
       ![...pending.values()].some(p=>p.session===input.sessionID&&(p.state!=='uncertain'||!isLedgerTool(p.tool)))){
     const verdict=await invoke.reconcile(input.sessionID);
     if(verdict.outcome==='unknown')fail('earlier tool outcome unresolved; reconcile '+verdict.reason+'; coordinator: '+verdict.command);
     for(const [held,record] of pending)if(record.session===input.sessionID&&record.state==='uncertain')pending.delete(held);
     blocking=blocker();
    }
    // Identify the exact retained call without exposing arguments, file content,
    // credentials or another session's state. Diagnostics never clear custody.
    if(blocking)fail('earlier tool admission or receipt unresolved '+JSON.stringify({
     session: blocking.session, call: blocking.call, tool: blocking.tool,
     state: blocking.state, phase: blocking.event.hook_event_name,
    }));
    if(pending.size>=64)fail('pending capacity reached');
    const args=JSON.parse(JSON.stringify(output?.args));
    if(input.tool==='archhub_work'&&(!workToolFactory||!selectedWorks[input.sessionID]))fail('this native session has no configured Work; no claim or permission granted');
    const event={...normalized(input.tool,args),session_id:input.sessionID,tool_use_id:input.callID,
     cwd:directory,vendor:'opencode',hook_event_name:'PreToolUse'};
    const record={session:input.sessionID,call:input.callID,tool:input.tool,read,args:stringify(args),event,state:'preparing'};
    pending.set(key,record);
    let result;
    try{result=await invoke(event);}catch(error){
     if(error instanceof NativeNotDelivered)pending.delete(key);
     else record.state='uncertain';
     throw error;
    }
    if(!result.allow){pending.delete(key);fail(result.notDelivered?'native owner released before admission; tool not delivered':
     'prewrite admission denied'+(typeof result.reason==='string'?': '+result.reason:''));}
    record.state='admitted';record.admittedAt=Date.now();
    if(nativeTools.has(input.tool)){
     record.stamp=randomUUID();output.args._archhub_call=record.stamp;
    }
   },
   'tool.execute.after':async(input,_output)=>{
    const key=identity(input),record=pending.get(key);
    const supplied={...input.args};
    if(nativeTools.has(record?.tool)){
     if(supplied._archhub_call!==record.stamp)fail((record.tool==='archhub_work'?'selected Work':'agent message')+' receipt stamp differs');
     delete supplied._archhub_call;
    }
    const skipped=nativeTools.has(input.tool)&&record?.state==='admitted';
    if(!record||(!skipped&&record.state!==(nativeTools.has(input.tool)?'executed':'admitted'))||record.tool!==input.tool||record.args!==stringify(supplied)||record.event.cwd!==directory)fail('postwrite identity or arguments differ');
    record.state='settling';
    record.event={...record.event,hook_event_name:'PostToolUse'};
    let result;
    try{result=await invoke({...record.event,hook_event_name:'PostToolUse',tool_response:{status:skipped?'skipped':'completed'}});}
    catch(error){record.state='uncertain';throw error;}
    if(!result.allow){record.state='uncertain';fail('postwrite receipt denied; continuation blocked');}
    pending.delete(key);
   },
  };
 };
}
