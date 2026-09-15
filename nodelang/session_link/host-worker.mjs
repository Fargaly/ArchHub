// PRIVATE IPC entry, never a public CLI. Parent owns an already bound client and
// consumes every frame; it may expose only the final allowlisted result.
import {attachSessionLink,detachSessionLink} from './host-attachment.mjs';

if(process.env.SESSION_LINK_PRIVATE_HOST_IPC!=='1'||process.stdout.isTTY){
 process.stderr.write('Private authenticated host IPC required\n');process.exit(2);
}
let buffer='',started=false,finished=false,calls=0,pending=null;
function emit(value){const text=JSON.stringify(value);if(Buffer.byteLength(text)>65536)throw new Error('frame_limit');process.stdout.write(text+'\n');}
function finish(result){if(finished)return;finished=true;clearTimeout(lifetime);if(pending){clearTimeout(pending.timer);pending=null;}emit({event:'result',result});process.exit(0);}
const lifetime=setTimeout(()=>finish({status:'uncertain',reason:'host_deadline'}),115000);
function call(method,args){
 if(finished||pending||++calls>3)return Promise.reject(new Error('client_call_limit'));
 return new Promise((resolve,reject)=>{
  const id=calls;
  const timeout={session_link_scope:12000,attach_session_link:40000,detach_session_link:25000}[method];
  const timer=setTimeout(()=>{pending=null;reject(new Error('client_timeout'));},timeout);
  pending={id,resolve,reject,timer};
  emit({event:'client_call',id,method,args});
 });
}
const client={session_link_scope:()=>call('session_link_scope',[]),
 attach_session_link:cap=>call('attach_session_link',[cap]),
 detach_session_link:()=>call('detach_session_link',[])};
async function receive(frame){
 if(frame.operation==='cancel')return finish({status:'cancelled_wait',external_cancelled:false});
 if(frame.event==='client_result'){
  if(!pending||frame.id!==pending.id)return finish({status:'uncertain',reason:'client_protocol_error'});
  const waiting=pending;pending=null;clearTimeout(waiting.timer);
  if(frame.ok===true)waiting.resolve(frame.result);else waiting.reject(new Error('client_refused'));
  return;
 }
 if(started)return finish({status:'uncertain',reason:'duplicate_host_request'});
 started=true;
 try {
  if(frame.operation==='attach')finish(await attachSessionLink(frame.connection,client,{ttlSeconds:frame.ttl_seconds??300}));
  else if(frame.operation==='detach')finish(await detachSessionLink(client));
  else finish({status:'not_attached',reason:'invalid_operation'});
 }catch{finish({status:'uncertain',reason:'host_failure'});}
}
process.stdin.setEncoding('utf8');
process.stdin.on('data',chunk=>{
 buffer+=chunk;
 if(Buffer.byteLength(buffer)>65536)return finish({status:'uncertain',reason:'input_limit'});
 while(buffer.includes('\n')){
  const index=buffer.indexOf('\n'),line=buffer.slice(0,index);buffer=buffer.slice(index+1);
  try{const frame=JSON.parse(line);if(!frame||typeof frame!=='object')throw new Error();void receive(frame);}
  catch{finish({status:'uncertain',reason:'invalid_frame'});}
 }
});
process.stdin.on('end',()=>finish({status:'uncertain',reason:'parent_disconnected'}));
process.stdin.on('error',()=>finish({status:'uncertain',reason:'parent_disconnected'}));
process.stdout.on('error',()=>process.exit(1));
