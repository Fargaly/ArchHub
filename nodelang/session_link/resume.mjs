// Restore transport only. Never replay messages, enroll actors, or replace chats.
export function confirmsSavedChild(binding, lock, runtime, observed) {
 return lock?.id===binding.id && lock.spawned===true && Number.isInteger(lock.childPid)
  && runtime?.id===binding.id && runtime.pid===lock.childPid
  && observed?.id===binding.id && observed.pid===lock.childPid
  && observed.codex===binding.codex.id && observed.claude===binding.claude.id
  && observed.remoteApp===(binding.claude.app||'claude');
}
export async function resumeSaved(binding, {probe, discover, connect, currentExecutor}) {
 if(!binding || !/^[a-f0-9]{16}$/.test(binding.id||'') ||
    typeof binding.claude?.id!=='string' || !binding.claude.id ||
    typeof binding.codex?.id!=='string' || !binding.codex.id)
   return {status:'recovery_required',reason:'invalid_saved_binding',dispatch_attempted:false};
 const held=await probe(binding.id);
 if(held.status==='live')return {...held,status:'already_connected',dispatch_attempted:false};
 if(held.status!=='offline')return {...held,dispatch_attempted:false};
 if(binding.permissionMode==='bypass' && (!currentExecutor || binding.executor!==currentExecutor))
   return {status:'recovery_required',reason:'saved_sender_permission_origin_changed',dispatch_attempted:false};
 const all=await discover(),app=binding.claude.app||'claude';
 const remote=(all[app]||[]).filter(r=>r.id===binding.claude.id&&r.cwd===binding.claude.cwd);
 const codex=(all.codex||[]).filter(r=>r.id===binding.codex.id&&r.cwd===binding.codex.cwd);
 if(remote.length!==1||codex.length!==1)
   return {status:'recovery_required',reason:'saved_endpoint_not_exactly_one_live_session',dispatch_attempted:false};
 const restored=await connect({app,claude:remote[0].selector||remote[0].id,
   codex:codex[0].id,permissionMode:binding.permissionMode||'prompting'});
 return {status:'restored',connection:restored,dispatch_attempted:false,work_recovery_required:true};
}
