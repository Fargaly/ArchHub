// Existing authenticated client facade only. No enrollment, file, CLI credential,
// subprocess capability output, persistent grant, or additional transport owner.
import {createHash} from 'node:crypto';

export async function attachSessionLink(connection, client, {ttlSeconds=300, delegate}={}) {
 let phase='scope';
 try {
  if(!Number.isInteger(ttlSeconds)||ttlSeconds<1||ttlSeconds>900)return {status:'not_attached',attached:false,reason:'invalid_lifetime'};
  const destination=typeof connection?.codex==='string'?connection.codex:connection?.codex?.id;
  if(typeof destination!=='string'||!destination)return {status:'not_attached',attached:false,reason:'invalid_connection'};
  const scope=await client.session_link_scope();
  if(typeof scope?.instance_id!=='string'||!scope.instance_id||scope.instance_id.length>200||
     scope.destination_fingerprint!==createHash('sha256').update(destination,'utf8').digest('hex'))
   return {status:'not_attached',attached:false,stage:'scope',reason:'scope_mismatch'};
  const issue=delegate||(await import('./bridge.mjs')).delegateInstance;
  phase='delegate';
  let capability=await issue({...connection,codex:destination},scope.instance_id,ttlSeconds);
  try {
   if(capability?.destination!==destination||capability.instance_id!==scope.instance_id||
      capability.connection_id!==connection.id||typeof capability.connection_generation!=='string'||
      !Number.isFinite(capability.expires_at)||capability.expires_at<=Date.now())
    return {status:'uncertain',attached:false,stage:'delegate',reason:'delegation_result_invalid'};
   phase='attach';
   const result=await client.attach_session_link(capability);
   if(result?.attached===false)return {status:'not_attached',attached:false,stage:'attach',reason:'application_refused'};
   if(result?.attached!==true||result.instance_id!==scope.instance_id||
      result.expires_at!==capability.expires_at)
    return {status:'uncertain',attached:false,stage:'attach',reason:'attachment_result_invalid'};
   return {status:'attached',attached:true,instance_id:scope.instance_id,expires_at:result.expires_at};
  } finally {capability=null;}
 } catch {
  return {status:phase==='scope'?'not_attached':'uncertain',attached:false,stage:phase,
   reason:phase==='scope'?'scope_unavailable':'handoff_unconfirmed'};
 }
}

export async function detachSessionLink(client) {
 // The bound client selects its own session. No iteration/global channel close.
 try {
  const result=await client.detach_session_link();
  const output={};
  for(const key of ['detached','revoked','worker_stopped','local_call_joined','external_cancelled'])
   if(typeof result?.[key]==='boolean')output[key]=result[key];
  if(['ok','detached','not_attached','uncertain','not_sent','cancelled_wait'].includes(result?.status))output.status=result.status;
  else output.status='uncertain';
  return output;
 } catch {return {status:'uncertain',stage:'detach',reason:'detach_unconfirmed'};}
}
