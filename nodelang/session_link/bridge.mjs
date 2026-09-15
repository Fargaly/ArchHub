import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {stateDir} from './paths.mjs';
import {PeerEndpoint,listClaudeSessions} from './vendor/src/peer-protocol.mjs';
import {nativeCall,hasAttachment,attachmentCall} from './native.mjs';
import {discoverExtra,sendExtra} from './extra-apps.mjs';
import {ScopedAttachments} from './scoped-attachment.mjs';
import {resumeSaved,confirmsSavedChild} from './resume.mjs';
const root=stateDir(),dir=path.join(root,'connections');
fs.mkdirSync(dir,{recursive:true});
const argv=process.argv.slice(2),cmd=argv[0]||'help';
const option=n=>{const i=argv.indexOf('--'+n);return i<0?undefined:argv[i+1];};
const idFor=(a,b)=>crypto.createHash('sha256').update(a+'|'+b).digest('hex').slice(0,16);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const alive=pid=>{try{process.kill(pid,0);return true;}catch{return false;}};
const configs=()=>fs.readdirSync(dir).filter(f=>f.endsWith('.runtime.json')).sort((a,b)=>fs.statSync(path.join(dir,b)).mtimeMs-fs.statSync(path.join(dir,a)).mtimeMs).map(f=>{try{return read(path.join(dir,f));}catch{return null;}}).filter(Boolean);
const decode=r=>{const s=(r.contentItems||[]).filter(x=>x.type==='inputText').map(x=>x.text).join('\n');return JSON.parse(s);};
function tailTitle(s){
  const folder=s.cwd.replace(/[^a-zA-Z0-9]/g,'-');
  const file=path.join(process.env.USERPROFILE,'.claude','projects',folder,s.sessionId+'.jsonl');
  let fd;try{fd=fs.openSync(file,'r');const size=fs.fstatSync(fd).size,b=Buffer.alloc(Math.min(size,131072));fs.readSync(fd,b,0,b.length,size-b.length);const rows=b.toString('utf8').split('\n').filter(x=>x.startsWith('{"type":"custom-title"'));return rows.length?JSON.parse(rows.at(-1)).customTitle:s.name;}catch{return s.name;}finally{if(fd!==undefined)fs.closeSync(fd);}
}
const claudes=()=>listClaudeSessions().map(s=>({id:s.sessionId,title:tailTitle(s),cwd:s.cwd,pid:s.pid,socket:s.socket,app:'claude'}));
function exact(rows,needle,app){const hits=rows.filter(s=>s.id===needle||s.selector===needle||s.title===needle);if(hits.length!==1)throw new Error(`${app}: expected exactly one session for ${JSON.stringify(needle)}, found ${hits.length}; use list and exact ID or process-qualified selector`);return hits[0];}
async function rpc(config,request,{onDispatch=()=>{},timeoutMs=25000}={}){
  if(!alive(config.pid))throw new Error('Session Link offline; request not dispatched. Resume the exact saved connection.');
  let token;
  try{token=read(config.keyPath).peerToken;}catch{throw new Error('Session Link credential unavailable; request not dispatched. Existing live owner requires reconciliation.');}
  return await new Promise((resolve,reject)=>{
    const socket=net.connect(config.control);let buffer='';socket.setEncoding('utf8');
    const timer=setTimeout(()=>{socket.destroy();reject(new Error('Control timeout; delivery may be uncertain; do not repeat send'));},timeoutMs);
    socket.on('error',e=>{clearTimeout(timer);reject(e);});
    socket.on('connect',()=>{onDispatch();socket.write(JSON.stringify({...request,token})+'\n');});
    socket.on('data',c=>{buffer+=c;if(buffer.length>1000000){socket.destroy();clearTimeout(timer);reject(new Error('Oversized response'));return;}if(buffer.includes('\n')){clearTimeout(timer);socket.destroy();try{const r=JSON.parse(buffer);r.ok?resolve(r.result):reject(new Error(r.error));}catch(e){reject(e);}}});
  });
}
// Caller supplies one exact owner-controlled connection descriptor. The returned
// capability must go directly to the authenticated instance in memory, never UI.
export async function delegateInstance(config,instanceId,ttlSeconds=300){
 if(!config||!alive(config.pid))throw new Error('Selected connection unavailable');
 const status=await rpc(config,{operation:'status'});
 if(status.id!==config.id||status.pid!==config.pid||status.codex!==config.codex)throw new Error('Selected connection changed');
 return await rpc(config,{operation:'delegate-instance',instance_id:instanceId,ttl_seconds:ttlSeconds});
}
export async function catalog(){
  if(hasAttachment()){
    let codex=[];let status='unavailable';
    try{const r=await attachmentCall('attachment-status');codex=[r.recipient];status='attached';}catch{}
    const extra=await discoverExtra();return {...extra,claude:claudes(),codex,adapterStatus:{...extra.adapterStatus,codex:{status}}};
  }
  if(process.env.CODEX_APP_TOOLS_PIPE_PATH&&process.env.CODEX_THREAD_ID){const r=decode(await nativeCall('list_threads',{limit:50}));return {...await discoverExtra(),claude:claudes(),codex:[...(r.pinnedThreads||[]),...(r.threads||[])].filter(t=>t.kind==='codex').map(t=>({id:t.id,title:t.title,cwd:t.cwd,app:'codex'}))};}
  if(process.env.SESSION_LINK_PRODUCT_WORKER==='1')return {...await discoverExtra(),claude:claudes(),codex:[]};
  for(const config of configs().filter(c=>alive(c.pid))){try{return await rpc(config,{operation:'list'});}catch{}}
  return {...await discoverExtra(),claude:claudes(),codex:[]};
}
async function connect(request,{onSpawn=()=>{}}={}){
  if(request.permissionMode&&!['prompting','bypass'].includes(request.permissionMode))throw new Error('Permission mode must be prompting or bypass');
  const all=await catalog(),app=request.app||'claude',c=exact(all[app]||[],request.claude,app),x=exact(all.codex,request.codex,'Codex');
  const id=idFor(c.id,x.id),runtime=path.join(dir,id+'.runtime.json'),binding=path.join(dir,id+'.binding.json');
  if(fs.existsSync(runtime)){const old=read(runtime);if(request.permissionMode&&fs.existsSync(binding)&&read(binding).permissionMode!==request.permissionMode)throw new Error('Existing connection has a different sender permission mode; connect does not change it. Reconcile pending delivery before explicit reconnect.');try{return await rpc(old,{operation:'status'});}catch{if(alive(old.pid))throw new Error('Existing bridge process is unreachable; stop it before reconnecting');}}
  if(!process.env.CODEX_APP_TOOLS_PIPE_PATH||!process.env.CODEX_THREAD_ID){
    for(const config of configs().filter(c=>alive(c.pid))){return await rpc(config,{operation:'connect',claude:c.selector||c.id,codex:x.id,app},{onDispatch:()=>onSpawn(null)});}
    throw new Error('Connect from a Codex task once to establish the local app transport');
  }
  fs.writeFileSync(binding,JSON.stringify({id,claude:c,codex:x,executor:process.env.CODEX_THREAD_ID,permissionMode:request.permissionMode||'prompting'}));
  const stderr=fs.openSync(path.join(dir,id+'.stderr.log'),'a');
  const child=spawn(process.execPath,[fileURLToPath(import.meta.url),'serve',binding],{detached:true,windowsHide:true,stdio:['ignore','ignore',stderr],env:process.env});
  if(child.pid)onSpawn(child.pid);
  child.on('error',()=>{});child.unref();fs.closeSync(stderr);
  for(let i=0;i<60;i++){await new Promise(r=>setTimeout(r,100));if(fs.existsSync(runtime)){try{return await rpc(read(runtime),{operation:'status'});}catch{}}}
  throw new Error('Bridge startup unconfirmed; inspect connection stderr before retrying');
}
async function resume(id){
 if(!/^[a-f0-9]{16}$/.test(id||''))throw new Error('Exact saved connection ID required');
 const saved=read(path.join(dir,id+'.binding.json'));
 if(saved.id!==id||idFor(saved.claude?.id,saved.codex?.id)!==id)throw new Error('Saved connection identity mismatch');
 const lock=path.join(dir,id+'.resume.lock');let fd;
 if(fs.existsSync(lock)){
  const reclaim=lock+'.reclaim';let guard,guardRecord;
  try{
   if(fs.existsSync(reclaim)){
    const raw=fs.readFileSync(reclaim,'utf8'),held=JSON.parse(raw);
    if(held.id!==id||!Number.isInteger(held.pid)||held.pid<=0||typeof held.nonce!=='string'||
       !/^[a-f0-9]{32}$/.test(held.nonce)||alive(held.pid))throw new Error('Resume guard remains owned or uncertain');
    // Recheck exact generation immediately before removing a dead owner's guard.
    if(fs.readFileSync(reclaim,'utf8')!==raw||alive(held.pid))throw new Error('Resume guard changed');
    fs.unlinkSync(reclaim);
   }
   guard=fs.openSync(reclaim,'wx');guardRecord=JSON.stringify({id,pid:process.pid,nonce:crypto.randomBytes(16).toString('hex')});
   fs.writeFileSync(guard,guardRecord);const previous=read(lock);
   const runtime=path.join(dir,id+'.runtime.json');const current=fs.existsSync(runtime)?read(runtime):null;
   if(previous.id===id && Number.isInteger(previous.childPid) && current?.pid===previous.childPid && alive(current.pid)){
    const observed=await rpc(current,{operation:'status'},{timeoutMs:1500});
    if(confirmsSavedChild(saved,previous,current,observed)){
     if(!alive(previous.pid))fs.rmSync(lock,{force:true});
     return {id,status:'already_connected',connection:observed,dispatch_attempted:false,work_recovery_required:true};
    }
   }
   if(previous.id===id && Number.isInteger(previous.pid) && previous.pid>0 && !alive(previous.pid) &&
      (previous.spawned===false || previous.spawned===true && Number.isInteger(previous.childPid)&&
       previous.childPid>0&&!alive(previous.childPid)&&(!current||current.id===id&&!alive(current.pid))))
     fs.rmSync(lock,{force:true});
  }catch{}finally{if(guard!==undefined){fs.closeSync(guard);try{if(fs.readFileSync(reclaim,'utf8')===guardRecord)fs.unlinkSync(reclaim);}catch{}}}
 }
 try{fd=fs.openSync(lock,'wx');}catch(e){if(e.code==='EEXIST')return {id,status:'recovery_required',reason:'resume_already_running_or_unconfirmed',dispatch_attempted:false};throw e;}
 let confirmed=false,spawned=false;
 try{
  fs.writeFileSync(fd,JSON.stringify({pid:process.pid,id,spawned:false}));
  const result=await resumeSaved(saved,{discover:catalog,currentExecutor:process.env.CODEX_THREAD_ID,
   connect:request=>connect(request,{onSpawn:childPid=>{
    spawned=true;fs.writeFileSync(lock,JSON.stringify({pid:process.pid,id,spawned:true,childPid}));
   }}),probe:async()=>{
   const file=path.join(dir,id+'.runtime.json');if(!fs.existsSync(file))return {status:'offline'};
   const state=read(file);if(!alive(state.pid))return {status:'offline'};
   try{return {status:'live',connection:await rpc(state,{operation:'status'})};}
   catch{return {status:'recovery_required',reason:'live_owner_unreachable'};}
  }});
  confirmed=true;return {id,...result};
 }finally{fs.closeSync(fd);if(confirmed||!spawned)fs.rmSync(lock,{force:true});}
}
async function serve(binding){
  const b=read(binding),runtime=path.join(dir,b.id+'.runtime.json'),events=path.join(dir,b.id+'.events.jsonl');
  const log=(event,data={})=>fs.appendFileSync(events,JSON.stringify({time:new Date().toISOString(),event,...data})+'\n');
  const peer=new PeerEndpoint({name:'codex-'+b.codex.id.slice(0,8)+'-'+b.id.slice(0,4),cwd:b.codex.cwd,log:message=>log('peer',{message})});
  peer.permissionMode=b.permissionMode;await peer.start();
  const control='\\\\.\\pipe\\LOCAL\\session-link-'+crypto.randomUUID();
  const attachments=new ScopedAttachments({connectionId:b.id,destination:b.codex.id});
  let sent=0,forwarded=0,lastError=null,chain=Promise.resolve(),attempts=[];const seen=new Set();
  const target=()=>{const found=claudes().find(s=>s.id===b.claude.id);if(!found||found.cwd!==b.claude.cwd)throw new Error('Bound Claude session is offline or changed workspace');return found;};
  const rate=()=>{attempts=attempts.filter(t=>Date.now()-t<60000);if(attempts.length>=20)throw new Error('20 messages/minute limit reached; possible echo loop');attempts.push(Date.now());};
  peer.onMessage(record=>{chain=chain.then(async()=>{try{
    if(record.fromSocket!==target().socket)throw new Error('Rejected unbound sender');
    if(!record.msgId||seen.has(record.msgId))return;if(record.text.length>32000)throw new Error('Message exceeds 32000 characters');rate();seen.add(record.msgId);if(seen.size>2000)seen.delete(seen.values().next().value);
    await nativeCall('send_message_to_thread',{threadId:b.codex.id,prompt:`[From Claude Code: ${b.claude.title}; session ${b.claude.id}; link ${b.id}; message ${record.msgId}]\n${record.text}`},b.executor);
    forwarded++;lastError=null;log('delivered',{messageId:record.msgId,direction:'claude-to-codex'});
  }catch(e){lastError=e.message;log('error',{error:lastError});}});});
  const state=()=>({id:b.id,pid:process.pid,remoteApp:b.claude.app||'claude',remoteId:b.claude.id,remoteTitle:b.claude.title,claude:b.claude.id,claudeTitle:b.claude.title,codex:b.codex.id,codexTitle:b.codex.title,peer:peer.name,sent,forwarded,lastError,claudeOnline:b.claude.app==='claude'?claudes().some(s=>s.id===b.claude.id):undefined});
  const server=net.createServer(socket=>{
    let buffer='',handled=false;socket.setEncoding('utf8');socket.setTimeout(30000,()=>socket.destroy());socket.on('error',()=>{});
    socket.on('data',async chunk=>{if(handled)return;buffer+=chunk;if(buffer.length>70000){socket.destroy();return;}if(!buffer.includes('\n'))return;handled=true;
      try{const r=JSON.parse(buffer.slice(0,buffer.indexOf('\n')));
        if(['attachment-status','attachment-post','attachment-revoke'].includes(r.operation)){
          attachments.require(r);
          if(r.operation==='attachment-revoke'){socket.end(JSON.stringify({ok:true,result:attachments.revoke(r)})+'\n');return;}
          const current=exact((await catalog()).codex,b.codex.id,'Codex');
          if(current.cwd!==b.codex.cwd)throw new Error('Bound Codex workspace changed');
          attachments.require(r); // Recheck expiry/revocation after native lookup.
          let result={recipient:current,connection_id:b.id,instance_id:r.instance_id,permission_mode:'prompting'};
          if(r.operation==='attachment-post'){
            if(typeof r.text!=='string'||!r.text.trim()||r.text.length>34000)throw new Error('Invalid text');
            rate();await nativeCall('send_message_to_thread',{threadId:b.codex.id,prompt:r.text},b.executor);
            result={submitted:true};
          }
          socket.end(JSON.stringify({ok:true,result})+'\n');return;
        }
        if(r.token!==peer.peerToken)throw new Error('Unauthenticated request');let result;
        if(r.operation==='status')result=state();
        else if(r.operation==='delivery'){
          if(typeof r.messageId!=='string')throw new Error('Exact message ID required');
          result=peer.readDelivery(r.messageId);
          if(!result)throw new Error('No retained delivery record for this message; historical submission is unconfirmed');
        }
        else if(r.operation==='capabilities')result={postCodex:true,ask:true,scopedAttachment:true};
        else if(r.operation==='delegate-instance'){
          const current=exact((await catalog()).codex,b.codex.id,'Codex');
          if(current.cwd!==b.codex.cwd)throw new Error('Bound Codex workspace changed');
          result={...attachments.issue(r.instance_id,r.ttl_seconds),control,pid:process.pid};
        }
        else if(r.operation==='post-codex'){if(typeof r.text!=='string'||!r.text.trim()||r.text.length>34000)throw new Error('Invalid text');const all=await catalog();exact(all.codex,r.threadId,'Codex');rate();await nativeCall('send_message_to_thread',{threadId:r.threadId,prompt:r.text},b.executor);result={submitted:true};}
        else if(r.operation==='list')result=await catalog();
        else if(r.operation==='connect')result=await connect(r);
        else if(r.operation==='reply'){if(typeof r.text!=='string'||!r.text.trim()||r.text.length>32000)throw new Error('Invalid text');rate();await nativeCall('send_message_to_thread',{threadId:b.codex.id,prompt:`[Local shell relay for ${b.claude.app}: ${b.claude.title}; link ${b.id}; caller agent identity not independently verified]\n${r.text}`},b.executor);forwarded++;result={delivered:true};}
        else if(r.operation==='send'){if(typeof r.text!=='string'||!r.text.trim()||r.text.length>32000)throw new Error('Invalid text');rate();
          const senderMode=r.permissionMode??peer.permissionMode;
          if(!['prompting','bypass'].includes(senderMode))throw new Error('Invalid explicit sender permission mode');
          if(b.claude.app!=='claude'){
            const messageId=crypto.randomUUID();log('queued',{messageId});
            chain=chain.then(async()=>{try{sent++;const answer=await sendExtra(b.claude,r.text);if(!answer.text)throw new Error('No response text returned');await nativeCall('send_message_to_thread',{threadId:b.codex.id,prompt:`[From ${b.claude.app}: ${b.claude.title}; link ${b.id}; reply ${answer.id}]\n${answer.text}`},b.executor);forwarded++;lastError=null;log('delivered',{messageId,direction:'app-to-codex'});}catch(e){lastError=e.message;log('error',{error:lastError});}});
            result={messageId,status:'queued locally; check status and native chat for delivery'};
          }else{
            const recipient=target();
            // Applies only to this NEW message. Existing pending/held guards
            // remain in sendAndWait; no receipt or recipient mode is changed.
            const delivery=await peer.sendAndWait(recipient.socket,r.text,{timeoutMs:0,permissionMode:senderMode});
            const messageId=delivery.msgId;
            sent++;log('submitted',{messageId,direction:'codex-to-claude'});
            result={messageId,status:peer.readDelivery(messageId)?.status||'sent_unconfirmed',note:'Native delivery status is not an agent reply; query delivery with this exact ID'};
          }}
        else if(r.operation==='disconnect'){attachments.clear();result={disconnected:b.id};setTimeout(()=>{peer.stop();server.close();fs.rmSync(runtime,{force:true});process.exit(0);},100);}
        else throw new Error('Unknown operation');socket.end(JSON.stringify({ok:true,result})+'\n');
      }catch(e){socket.end(JSON.stringify({ok:false,error:e.message})+'\n');}
    });
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(control,resolve);});
  fs.writeFileSync(runtime,JSON.stringify({...state(),control,keyPath:peer.keyPath}));log('started',state());
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))try{
 let result;
 if(cmd==='serve'){await serve(argv[1]);}
 else if(cmd==='resume'){
  if(argv[1]==='--current'){
   const current=process.env.CODEX_THREAD_ID||process.env.CLAUDE_CODE_SESSION_ID||process.env.CLAUDE_SESSION_ID;
   if(!current)throw new Error('Current native session identity unavailable; no guessed resume');
   const ids=fs.readdirSync(dir).filter(f=>f.endsWith('.binding.json')).filter(f=>{const b=read(path.join(dir,f));return b.codex?.id===current||b.claude?.id===current;}).map(f=>f.slice(0,-13));
   result=[];for(const id of ids)result.push(await resume(id));
  }else result=await resume(argv[1]);
 }
 else if(cmd==='list')result=await catalog();
 else if(cmd==='connect'||cmd==='reconnect'){
   const allowed=new Set(['--claude','--codex','--opencode','--antigravity','--antigravity-ide','--permission-mode']);
   if(argv.slice(1).some(v=>v.startsWith('--')&&!allowed.has(v)))throw new Error('Unknown connection option; run help');
   if(['claude','opencode','antigravity','antigravity-ide'].filter(a=>option(a)).length>1)throw new Error('Choose exactly one remote app');
   const app=['opencode','antigravity','antigravity-ide'].find(a=>option(a))||'claude';
   const request={app,claude:option(app)||claudes().find(c=>c.socket===process.env.CLAUDE_CODE_MESSAGING_SOCKET)?.id,codex:option('codex')||process.env.CODEX_THREAD_ID,permissionMode:option('permission-mode')};
   if(cmd==='reconnect'){
     if(!process.env.CODEX_APP_TOOLS_PIPE_PATH||!process.env.CODEX_THREAD_ID)throw new Error('Reconnect from a current Codex Desktop task to refresh the native app connection');
     const all=await catalog(),c=exact(all[app]||[],request.claude,app),x=exact(all.codex,request.codex,'Codex');
     const previous=configs().find(v=>v.id===idFor(c.id,x.id));
     if(previous&&alive(previous.pid)){await rpc(previous,{operation:'disconnect'});for(let n=0;n<30&&alive(previous.pid);n++)await new Promise(r=>setTimeout(r,100));if(alive(previous.pid))throw new Error('Previous process has not stopped');}
   }
   result=await connect(request);
 }
 else if(cmd==='status'){result=[];for(const c of configs()){try{result.push(await rpc(c,{operation:'status'}));}catch(e){result.push({id:c.id,status:'offline',error:e.message});}}}
 else if(cmd==='delivery'){
   const matches=configs().filter(c=>c.id===argv[1]);if(matches.length!==1)throw new Error('Exact connection ID required');
   result=await rpc(matches[0],{operation:'delivery',messageId:argv[2]});
 }
 else if(cmd==='send'||cmd==='reply'||cmd==='disconnect'){const matches=configs().filter(c=>c.id===argv[1]);if(matches.length!==1)throw new Error('Use exact connection ID from status');result=await rpc(matches[0],{operation:cmd,text:cmd==='send'||cmd==='reply'?fs.readFileSync(option('file'),'utf8'):undefined,...(cmd==='send'&&option('permission-mode')?{permissionMode:option('permission-mode')}:{} )});}
 else result={commands:['list','connect --claude|--opencode|--antigravity|--antigravity-ide "title or ID" --codex "title or ID"','ask --app APP --session "title or ID" --file UTF8_FILE','answer REQUEST_ID --file UTF8_FILE','status','send CONNECTION_ID --file UTF8_FILE','reply CONNECTION_ID --file UTF8_FILE','disconnect CONNECTION_ID','reconnect --claude ID --codex ID'],apps:['claude','codex','opencode','antigravity','antigravity-ide'],note:'Use session-link.ps1 for ask/answer. Any shell-capable agent can initiate ask and receive its reply. This does not wake arbitrary idle terminals. Check adapterStatus and verify a real reply. Recipient permissions remain active.'};
 if(result!==undefined)console.log(JSON.stringify(result,null,2));
}catch(e){console.error(e.message);process.exitCode=1;}

