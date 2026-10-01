import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PeerEndpoint,listClaudeSessions,publicDeliveryReceipt} from './vendor/src/peer-protocol.mjs';
import {sendExtra} from './extra-apps.mjs';
import {postCodex} from './native.mjs';
import {catalog,connect,idFor} from './bridge.mjs';
import {stateDir,readMessage} from './paths.mjs';
import {modelFromArgs,validateModel} from './opencode-model.mjs';
import {interrupt} from './interrupt.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const psQuote=value=>"'"+String(value).replaceAll("'","''")+"'";
const args=process.argv.slice(2),opt=n=>{const i=args.indexOf('--'+n);return i<0?undefined:args[i+1];};
const validate=text=>{if(typeof text!=='string'||!text.trim()||text.length>32000)throw new Error('Text must contain 1–32000 characters');return text;};
// Any shell-capable agent can use this request/reply interface. It neither
// starts a second model session nor writes into another terminal's stdin.
// A Codex task asking Claude gets a durable reply address: the persistent
// bridge peer, which forwards any later SendMessage into this Codex task. The
// one-shot request pipe below still carries the synchronous reply. The durable
// link is always 'prompting': a per-request sender mode never outlives its request.
export async function durableReply(target,{connectLink=connect}={}){
 if(!process.env.CODEX_APP_TOOLS_PIPE_PATH||!process.env.CODEX_THREAD_ID)return null;
 const codex=process.env.CODEX_THREAD_ID;let link;
 try{
  const observedCatalog=await catalog({apps:['claude','codex']});
  link=await connectLink({app:'claude',claude:target.id,codex,permissionMode:'prompting'},{observedCatalog});
 }catch(e){if(e?.code==='SESSION_LINK_MISMATCH')throw e;return {error:e.message};}
 // Advertise only the exact prompting link for this pair, as the bridge attests it.
 if(link?.id!==idFor(target.id,codex)||(link.remoteApp||'claude')!=='claude'||link.remoteId!==target.id||link.codex!==codex||
    link.permissionMode!=='prompting'||typeof link.peer!=='string'||!link.peer){
  const e=new Error('Durable Session Link is not the exact prompting link for this request; nothing sent');e.code='SESSION_LINK_MISMATCH';throw e;
 }
 return {connection:link.id,peer:link.peer};
}
export async function ask(app,session,text,permissionMode='prompting',{expected,onDispatch=()=>{},model,connectLink}={}){
 validate(text);
 validateModel(model);
 if(model!==undefined && app!=='opencode')throw new Error('Explicit model selection is OpenCode-only; not sent');
 if(!['claude','codex','opencode','antigravity','antigravity-ide'].includes(app))throw new Error('Unsupported target app');
 if(!['prompting','bypass'].includes(permissionMode))throw new Error('Invalid sender permission mode');
 const all=await catalog({apps:[app]});
 const matches=(all[app]||[]).filter(s=>s.id===session||s.selector===session||s.title===session);
 if(matches.length!==1){
  const down=all.adapterStatus?.[app];
  if(app==='codex'&&!matches.length&&down?.status==='unavailable')throw new Error('Codex tasks unavailable: '+(down.reason||'no reason reported'));
  throw new Error('Target must resolve to exactly one live session; use its exact ID');
 }
 const target=matches[0];
 if(expected){for(const field of ['app','id','pid','port','socket','cwd','runtimeId'])if(expected[field]!==target[field])throw new Error('Recipient binding changed before dispatch: '+field);}
 if(app!=='claude'&&app!=='codex')return await sendExtra(target,text,{onDispatch,model});
 if(app==='codex'&&target.id===process.env.CODEX_THREAD_ID)throw new Error('Synchronous self-request would deadlock; use another existing task');
 const id=crypto.randomUUID(),peer=new PeerEndpoint({name:'session-link-request-'+id.slice(0,8),cwd:process.cwd()});
 peer.permissionMode=permissionMode;
 await peer.start();
 const control='\\\\.\\pipe\\LOCAL\\session-link-request-'+id;
 const requestDir=path.join(stateDir(),'requests'),file=path.join(requestDir,id+'.json');
 fs.mkdirSync(requestDir,{recursive:true});
 let server,timer;
 let resolveReply,rejectReply;
 const reply=new Promise((resolve,reject)=>{resolveReply=resolve;rejectReply=reject;});
 // Attach rejection handling before sending so timeouts never become unhandled.
 reply.catch(()=>{});
 try{
  if(app==='codex'){
   server=net.createServer(socket=>{let data='',handled=false;socket.setEncoding('utf8');socket.setTimeout(10000,()=>socket.destroy());socket.on('error',()=>{});socket.on('data',chunk=>{
    if(handled)return;data+=chunk;if(data.length>70000){socket.destroy();return;}if(!data.includes('\n'))return;handled=true;
    try{const r=JSON.parse(data.slice(0,data.indexOf('\n')));if(r.token!==peer.peerToken||r.session!==target.id)throw new Error('Wrong request/session authentication');validate(r.text);socket.end(JSON.stringify({ok:true})+'\n');resolveReply({id,text:r.text});}catch(e){socket.end(JSON.stringify({ok:false,error:e.message})+'\n');}
   });});
   await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(control,resolve);});
   fs.writeFileSync(file,JSON.stringify({control,keyPath:peer.keyPath,target:target.id,pid:process.pid}));
  }
  if(app==='codex')timer=setTimeout(()=>rejectReply(new Error('No reply confirmed in 180 seconds. The prompt may have arrived; do not resend automatically.')),180000);
  if(app==='claude'){
   const live=listClaudeSessions().find(s=>s.sessionId===target.id);if(!live)throw new Error('Claude went offline before send');
   const durable=await durableReply(target,{connectLink});
   const later=durable?.peer?` If you reply after this request closes, or to follow up later, use native SendMessage to peer ${durable.peer} (Session Link connection ${durable.connection}); it delivers into the requesting Codex task.`:'';
   const outcome=await peer.sendAndWait(live.socket,`[Session Link request ${id}. Reply using native SendMessage to peer ${peer.name}. The requesting agent is waiting for the reply.${later} Respect your existing execution permissions.]\n${text}`,{timeoutMs:180000,permissionMode,beforeSend:onDispatch});
   const delivery=outcome.delivery,route=durable?{durable_reply:durable}:{};
   if(delivery && ['held','refused','rejected','denied','expired','dropped'].includes(delivery.status))
    return {status:'held',id:outcome.msgId,...publicDeliveryReceipt(delivery),...route};
   if(!outcome.reply)throw new Error('No reply confirmed in 180 seconds; delivery remains uncertain; do not resend'+(durable?.peer?`; a late reply still reaches this task through peer ${durable.peer}`:''));
   return {id:outcome.reply.msgId,text:outcome.reply.text,...route};
  }else{
   onDispatch();await postCodex(target.id,`[Session Link request ${id}. An existing terminal agent is waiting. After preparing your response, write it to a UTF-8 file inside your permitted workspace, then run PowerShell: & ${psQuote(path.join(root,'session-link.ps1'))} answer ${id} --state-dir ${psQuote(stateDir())} --file 'ABSOLUTE_RESPONSE_FILE'. This returns your response to the caller. Respect your current permissions.]\n${text}`,{requestId:id});
  }
  return await reply;
 }finally{clearTimeout(timer);server?.close();peer.stop();if(fs.existsSync(file))fs.rmSync(file);}
}
async function answer(id,text){
 if(!/^[0-9a-f-]{36}$/.test(id||''))throw new Error('Invalid request ID');validate(text);
 const r=JSON.parse(fs.readFileSync(path.join(stateDir(),'requests',id+'.json'),'utf8'));
 if(process.env.CODEX_THREAD_ID!==r.target)throw new Error('Answer must run inside the exact receiving Codex task');
 const token=JSON.parse(fs.readFileSync(r.keyPath,'utf8')).peerToken;
 return await new Promise((resolve,reject)=>{const s=net.connect(r.control);let data='';s.setEncoding('utf8');s.setTimeout(10000,()=>{s.destroy();reject(new Error('Answer timeout; delivery uncertain'));});s.on('error',reject);s.on('connect',()=>s.write(JSON.stringify({token,session:process.env.CODEX_THREAD_ID,text})+'\n'));s.on('data',c=>{data+=c;if(data.includes('\n')){s.destroy();try{const v=JSON.parse(data);v.ok?resolve({delivered:true}):reject(new Error(v.error));}catch(e){reject(e);}}});});
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{if(args[0]==='interrupt'){console.log(JSON.stringify(await interrupt(opt('app'),opt('session'),opt('reason'),{permissionMode:opt('permission-mode')??'prompting'}),null,2));}
 else{const model=modelFromArgs(args);const text=validate(await readMessage(args));if(args[0]==='answer'&&model)throw new Error('Answer cannot select a model');const result=args[0]==='answer'?await answer(args[1],text):await ask(opt('app'),opt('session'),text,opt('permission-mode'),{model});console.log(JSON.stringify(result,null,2));if(result.status==='model_selection_failed')process.exitCode=1;}}catch(e){console.error(e.message);process.exitCode=1;}
}
