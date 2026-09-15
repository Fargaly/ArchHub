import {spawn} from 'node:child_process';
import path from 'node:path';

const fail = reason => {throw new Error('ArchHub OpenCode governance: '+reason);};
class NativeNotDelivered extends Error {}
const notDelivered = reason => {throw new NativeNotDelivered('ArchHub OpenCode governance: '+reason+'; tool not delivered');};
const object = value => value && typeof value==='object' && !Array.isArray(value);
const stringify = value => JSON.stringify(value, (_key,item)=>object(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);

// The private installed loader supplies the existing admitted gate command.
// No shell, Bun global, source-checkout lookup, enrollment or fallback service.
export function createNativeGateRunner(command,args) {
 if(!path.isAbsolute(command)||!Array.isArray(args)||args.some(a=>typeof a!=='string'))fail('trusted native gate command required');
 const workers=new Map(),lineages=new Map(),queues=new Map(),quarantined=new Set();
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
  if(quarantined.has(event.session_id))notDelivered('native session quarantined; no duplicate enrollment');
  let state=workers.get(event.session_id);
  if(!state){
   if(workers.size>=4)notDelivered('native owner capacity reached');
   if(!lineages.has(event.session_id)&&lineages.size>=128)notDelivered('native identity retention capacity reached');
   if(!lineages.has(event.session_id))lineages.set(event.session_id,null);
   const child=spawn(command,args,{shell:false,windowsHide:true,cwd:event.cwd,stdio:['pipe','pipe','pipe'],env:{...process.env,
    ARCHHUB_COORDINATION_VENDOR:'opencode',ARCHHUB_AGENT_RUNTIME:'opencode',ARCHHUB_EXTERNAL_SESSION_ID:event.session_id,
    OPENCODE_SESSION_ID:event.session_id,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'}});
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
     quarantined.add(event.session_id);workers.delete(event.session_id);
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
    if(reply.request_id!==held.id||reply.session_id!==event.session_id||reply.tool_use_id!==held.call||
       reply.error||!['allow','deny'].includes(reply.decision)){abort('native reply identity or outcome unavailable');return;}
    if(!/^app:agent-session:runtime:[a-f0-9]{32}$/.test(reply.agent_session)||
       (state.actor&&state.actor!==reply.agent_session)||
       (!state.actor&&lineages.get(event.session_id)&&
        (lineages.get(event.session_id)!==reply.agent_session||reply.continued!==true))){abort('native graph identity changed');return;}
    state.actor=reply.agent_session;lineages.set(event.session_id,state.actor);
    state.lastCompleted=held.id;
    clearTimeout(held.timer);state.pending=null;held.resolve({allow:reply.decision==='allow'});
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
  if(state.failed||state.pending||state.released||state.closed)notDelivered('native owner unavailable or already active; no duplicate enrollment');
  return new Promise((resolve,reject)=>{
   state.pending={id,call:event.tool_use_id,resolve,reject,timer:setTimeout(()=>state.abort('native gate timeout'),30000)};
   state.child.stdin.write(payload);
  });
 };
 const run=event=>{
  const key=event.session_id,prior=queues.get(key);
  if(prior?.count>=64)notDelivered('native request queue capacity reached');
  const promise=prior?prior.promise.then(()=>dispatch(event),()=>notDelivered('prior native request unresolved')):dispatch(event);
  const entry={promise,count:(prior?.count||0)+1};queues.set(key,entry);
  const clear=()=>{if(queues.get(key)===entry)queues.delete(key);};
  promise.then(clear,clear);return promise;
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
 if(tool==='write')return {tool_name:'Write',tool_input:{file_path:args.filePath,content:args.content}};
 if(tool==='edit')return {tool_name:'Edit',tool_input:{file_path:args.filePath,old_string:args.oldString,new_string:args.newString,replace_all:args.replaceAll===true}};
 if(['read','glob','grep','list'].includes(tool))return {tool_name:tool,tool_input:args};
 fail('tool has no verified governance mapping: '+String(tool));
}

export function createOpenCodeGovernance({gateCommand,gateArgs,gateRunner}) {
 const invoke=gateRunner||createNativeGateRunner(gateCommand,gateArgs);
 // Retained for all workspaces in this loaded plugin; never clear on idle/error.
 const pending=new Map();
 return async ({directory})=>{
  if(!path.isAbsolute(directory))fail('native workspace unavailable');
  const identity=input=>{
   if(!input || typeof input.sessionID!=='string'||!/^ses_[A-Za-z0-9]+$/.test(input.sessionID)||
      typeof input.callID!=='string'||!input.callID||input.callID.length>256)fail('native session/call identity unavailable');
   return input.sessionID+'\0'+input.callID;
  };
  return {
   dispose:async()=>{if(pending.size)fail('native receipts remain unresolved');await invoke.close?.();},
   'tool.execute.before':async(input,output)=>{
    const key=identity(input);
    const read=['read','glob','grep','list'].includes(input.tool);
    if(pending.has(key)||[...pending.values()].some(p=>p.session===input.sessionID&&
       (!read||!p.read||!['preparing','admitted','settling'].includes(p.state))))fail('earlier tool admission or receipt unresolved');
    if(pending.size>=64)fail('pending capacity reached');
    const args=JSON.parse(JSON.stringify(output?.args));
    const event={...normalized(input.tool,args),session_id:input.sessionID,tool_use_id:input.callID,
     cwd:directory,vendor:'opencode',hook_event_name:'PreToolUse'};
    const record={session:input.sessionID,tool:input.tool,read,args:stringify(args),event,state:'preparing'};
    pending.set(key,record);
    let result;
    try{result=await invoke(event);}catch(error){
     if(error instanceof NativeNotDelivered)pending.delete(key);
     else record.state='uncertain';
     throw error;
    }
    if(!result.allow){pending.delete(key);fail(result.notDelivered?'native owner released before admission; tool not delivered':'prewrite admission denied');}
    record.state='admitted';
   },
   'tool.execute.after':async(input,_output)=>{
    const key=identity(input),record=pending.get(key);
    if(!record||record.state!=='admitted'||record.tool!==input.tool||record.args!==stringify(input.args)||record.event.cwd!==directory)fail('postwrite identity or arguments differ');
    record.state='settling';
    let result;
    try{result=await invoke({...record.event,hook_event_name:'PostToolUse',tool_response:{status:'completed'}});}
    catch(error){record.state='uncertain';throw error;}
    if(!result.allow){record.state='uncertain';fail('postwrite receipt denied; continuation blocked');}
    pending.delete(key);
   },
  };
 };
}
