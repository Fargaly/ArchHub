import fs from 'node:fs';
import net from 'node:net';
import crypto from 'node:crypto';
import path from 'node:path';
import {PeerEndpoint} from './vendor/src/peer-protocol.mjs';
import {validateModel,promptSelectedModel,modelReceipt} from './opencode-model.mjs';
const MESSAGE_READ_BOUND=64;
async function readOpenCodeMessages(client, sessionId, directory, timeout=10000) {
 const response=await client.session.messages({path:{id:sessionId},query:{directory,limit:MESSAGE_READ_BOUND},signal:AbortSignal.timeout(timeout)});
 if(response?.error)throw new Error('OpenCode turn read rejected');
 const rows=response?.data??response;
 if(!Array.isArray(rows)||rows.length>MESSAGE_READ_BOUND)throw new Error('OpenCode message count bound');
 if(Buffer.byteLength(JSON.stringify(rows),'utf8')>2*1024*1024)throw new Error('OpenCode message byte bound');
 return rows;
}
// Same bounded Workshop reader, projecting tool metadata only, never text parts.
export async function collectOpenCodeActivity(client,{sessionId,directory,root}) {
 const relative=path.relative(path.resolve(root),path.resolve(directory));
 if(relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative)||
    [...path.resolve(directory).split(path.sep),...path.resolve(root).split(path.sep)].some(p=>/^(20\.CLIENTS|60\.PERSONAL)$/i.test(p)))throw new Error('OpenCode workspace outside activity scope');
 const rows=await readOpenCodeMessages(client,sessionId,directory,2000), events=[];
 for(const row of rows){
  if(row?.info?.sessionID!==sessionId||row.info.role!=='assistant'||!Array.isArray(row.parts))continue;
  for(const part of row.parts.slice(0,256)){
   if(part?.type!=='tool'||part.sessionID!==sessionId||part.messageID!==row.info.id||
      !/^[A-Za-z_][A-Za-z0-9_.:-]{0,79}$/.test(part.tool||''))continue;
   const input=part.state?.input, raw=input?.filePath||input?.file_path||input?.path;
   if(typeof raw!=='string'||raw.length>4096||/[\x00-\x1f]/.test(raw))continue;
   const absolute=path.resolve(directory,raw), file=path.relative(path.resolve(root),absolute).split(path.sep).join('/');
   if(!file||file==='..'||file.startsWith('../')||path.isAbsolute(file)||
      absolute.split(path.sep).some(p=>/^(20\.CLIENTS|60\.PERSONAL)$/i.test(p)))continue;
   const stamp=part.state?.time?.end||part.state?.time?.start||row.info.time?.created;
   if(!Number.isFinite(stamp))continue;
   const state=row.info.time?.completed&&row.info.finish==='stop'?'turn_ended':part.state.status==='running'?'working':'tool_ended';
   events.push({provider:'opencode',session:sessionId,tool:part.tool,file,state,at:stamp/1000});
  }
 }
 return events.slice(-128);
}
// A prompt may produce several assistant messages before its final response.
// Only public text from that exact completed turn may cross the transport.
export async function collectOpenCodeTurn(client, {sessionId, directory, reply, model}) {
 const fail = detail => {throw new Error('OpenCode response incomplete: '+detail+'; prompt was already sent, do not resend automatically');};
 const final = reply?.info;
 if (!final || final.role !== 'assistant' || final.sessionID !== sessionId ||
     typeof final.id !== 'string' || typeof final.parentID !== 'string') fail('final identity unavailable');
 let response;
 try {response = await readOpenCodeMessages(client,sessionId,directory);}
 catch (error) {fail(error.message==='OpenCode turn read rejected'?'turn read rejected':
  error.message==='OpenCode message count bound'?'message count bound':
  error.message==='OpenCode message byte bound'?'message byte bound':'turn read failed');}
 if (response?.error) fail('turn read rejected');
 const rows = response;
 if (!Array.isArray(rows) || rows.length > 64) fail('message count bound');
 if (Buffer.byteLength(JSON.stringify(rows), 'utf8') > 2*1024*1024) fail('message byte bound');
 const unique = new Map();
 for (const row of rows) {
  const info = row?.info;
  if (!info || typeof info.id !== 'string' || !Number.isFinite(info.time?.created) || !Array.isArray(row.parts)) fail('malformed message');
  if (unique.has(info.id)) {
   if (JSON.stringify(unique.get(info.id)) !== JSON.stringify(row)) fail('conflicting message identity');
  } else unique.set(info.id,row);
 }
 const ordered = [...unique.values()].sort((a,b)=>a.info.time.created-b.info.time.created || (a.info.id<b.info.id?-1:a.info.id>b.info.id?1:0));
 const start = ordered.findIndex(row=>row.info.id===final.parentID && row.info.role==='user' && row.info.sessionID===sessionId);
 const end = ordered.findIndex(row=>row.info.id===final.id && row.info.role==='assistant' && row.info.sessionID===sessionId && row.info.parentID===final.parentID);
 if (start<0 || end<=start) fail('turn boundary missing from bounded read');
 const selected=ordered.slice(start+1,end+1).filter(row=>row.info.role==='assistant' && row.info.sessionID===sessionId && row.info.parentID===final.parentID);
 const textParts = row => {
  if (!Array.isArray(row.parts) || row.parts.some(part=>!part || typeof part!=='object' || Array.isArray(part))) fail('malformed part');
  return row.parts.filter(part=>part.type==='text');
 };
 if (!Array.isArray(reply.parts) || JSON.stringify(textParts(ordered[end]))!==JSON.stringify(textParts(reply))) fail('final text changed');
 const texts=[], partIds=new Map(), messageIds=[];
 let bytes=0, parts=0;
 for (const row of selected) {
  messageIds.push(row.info.id);
  parts+=row.parts.length;
  if (parts>4096) fail('part count bound');
  for (const part of textParts(row)) {
   if (typeof part.id!=='string' || part.messageID!==row.info.id || part.sessionID!==sessionId || typeof part.text!=='string') fail('text identity invalid');
   if (partIds.has(part.id)) {
    if (partIds.get(part.id)!==JSON.stringify(part)) fail('conflicting text identity');
    continue;
   }
   partIds.set(part.id,JSON.stringify(part));
   bytes+=Buffer.byteLength(part.text,'utf8')+(texts.length?1:0);
   if (bytes>512*1024) fail('text byte bound');
   texts.push(part.text);
  }
 }
 const result=modelReceipt({id:final.id, parent_id:final.parentID, message_ids:messageIds, text:texts.join('\n')},model,selected.map(row=>row.info));
 // JSON escaping can expand control characters sixfold. Leave room for every
 // enclosing bridge below its 1,000,000-character response limit.
 if (Buffer.byteLength(JSON.stringify({ok:true,result})+'\n','utf8')>768*1024) fail('serialized response byte bound');
 return result;
}

export function createWorkshopPlugin({stateDirectory}){
 if(typeof stateDirectory!=='string'||!path.isAbsolute(stateDirectory))throw new Error('Explicit application transport state directory required');
 const runtimeDir=path.join(stateDirectory,'opencode-runtimes');
 const runtime=path.join(runtimeDir,process.pid+'.json');
 return async ({client,directory})=>{
 const symbol=Symbol.for('archhub.workshop.opencodeserver');
 if(globalThis[symbol]&&globalThis[symbol].stateDirectory!==stateDirectory)throw new Error('This OpenCode process is attached to another transport state directory');
 if(globalThis[symbol]){globalThis[symbol].clients.set(directory,client);return {};}
 const clients=new Map([[directory,client]]),busy=new Set(),queues=new Map(),seen=new Set();
 const peer=new PeerEndpoint({name:'opencode-workshop-'+process.pid,cwd:directory});await peer.start();
 const control='\\\\.\\pipe\\LOCAL\\opencode-workshop-'+crypto.randomUUID();
 const unwrap=r=>{if(r.error)throw new Error('OpenCode SDK rejected request');return r.data??r;};
 const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 const idle=async(c,id,directory)=>{
  const deadline=Date.now()+180000;
  for(;;){
   const statuses=unwrap(await c.session.status({query:{directory}}));
   if(!busy.has(id)&&!(statuses[id]&&statuses[id].type!=='idle'))return;
   if(Date.now()>=deadline)throw new Error('Session stayed busy; message not sent');
   await sleep(250);
  }
 };
 const sendTurn=async({id,directory,text,model})=>{
  if(typeof text!=='string'||!text.trim()||text.length>32000)throw new Error('Invalid text');
  const c=clients.get(directory);if(!c)throw new Error('Workspace is not attached to this OpenCode process');
  const session=unwrap(await c.session.get({path:{id},query:{directory}}));if(session.id!==id||session.directory!==directory)throw new Error('Session/workspace mismatch');
  await idle(c,id,directory);
  busy.add(id);
  try{const reply=unwrap(await promptSelectedModel(c,{id,directory,text,model}));
  return await collectOpenCodeTurn(c,{sessionId:id,directory,reply,model});}finally{busy.delete(id);}
 };
 const enqueue=({id,directory,text,model})=>{
  const key=directory+'\0'+id;
  const prior=queues.get(key)||Promise.resolve();
  const run=prior.then(()=>sendTurn({id,directory,text,model}));
  queues.set(key,run.catch(()=>{}).finally(()=>{if(queues.get(key)===run)queues.delete(key);}));
  return run;
 };
 const onlySession=async()=>{
  const rows=[];
  for(const [cwd,c] of clients){const list=unwrap(await c.session.list({query:{directory:cwd}}));for(const s of list)rows.push({id:s.id,directory:s.directory||cwd});}
  if(rows.length!==1)throw new Error('OpenCode peer inbox requires exactly one attached session');
  return rows[0];
 };
 let peerChain=Promise.resolve();
 peer.onMessage(record=>{peerChain=peerChain.then(async()=>{try{
  if(!record.msgId||seen.has(record.msgId))return;if(typeof record.text!=='string'||record.text.length>32000)throw new Error('Message exceeds 32000 characters');
  seen.add(record.msgId);if(seen.size>2000)seen.delete(seen.values().next().value);
  const target=await onlySession();
  await enqueue({id:target.id,directory:target.directory,text:record.text,model:undefined});
 }catch(e){peer.log('opencode peer delivery failed: '+e.message);}});});
 const server=net.createServer(socket=>{let buffer='',handled=false;socket.setEncoding('utf8');socket.setTimeout(190000,()=>socket.destroy());socket.on('error',()=>{});socket.on('data',async chunk=>{
  if(handled)return;buffer+=chunk;if(buffer.length>70000){socket.destroy();return;}if(!buffer.includes('\n'))return;handled=true;
  try{const r=JSON.parse(buffer.slice(0,buffer.indexOf('\n')));if(r.token!==peer.peerToken)throw new Error('Unauthenticated request');let result;
   if(r.operation==='list'){const rows=[];for(const [cwd,c] of clients){const list=unwrap(await c.session.list({query:{directory:cwd}}));for(const s of list)rows.push({app:'opencode',id:s.id,title:s.title,cwd:s.directory||cwd,runtimeId:process.pid});}result=[...new Map(rows.map(x=>[x.id,x])).values()];}
   else if(r.operation==='capabilities')result={per_request_free_model:1};
   else if(r.operation==='activity'){
    const c=clients.get(r.directory);if(!c)throw new Error('Workspace is not attached to this OpenCode process');
    const target=unwrap(await c.session.get({path:{id:r.id},query:{directory:r.directory}}));
    if(target.id!==r.id||target.directory!==r.directory)throw new Error('Session/workspace mismatch');
    result=await collectOpenCodeActivity(c,{sessionId:r.id,directory:r.directory,root:r.root});
   }
   else if(r.operation==='inject'){
    const model=validateModel(r.model);
    if(typeof r.messageId!=='string'||!r.messageId||r.messageId.length>512||typeof r.text!=='string'||!r.text.trim()||r.text.length>32000)throw new Error('Invalid Workshop injection');
    const c=clients.get(r.directory);if(!c)throw new Error('Workspace is not attached to this OpenCode process');
    const target=unwrap(await c.session.get({path:{id:r.id},query:{directory:r.directory}}));
    if(target.id!==r.id||target.directory!==r.directory)throw new Error('Session/workspace mismatch');
    const key='workshop:'+r.id+':'+r.messageId;
    if(!seen.has(key)){
     seen.add(key);if(seen.size>2000)seen.delete(seen.values().next().value);
     void enqueue({id:r.id,directory:r.directory,text:r.text,model}).catch(()=>{
      process.stderr.write('Workshop injection did not complete; its public message remains pending.\n');
     });
    }
    result={status:'queued'};
   }
   else if(r.operation==='send'){
   const model=validateModel(r.model);
    result=await enqueue({id:r.id,directory:r.directory,text:r.text,model});
   }else throw new Error('Unsupported operation');socket.end(JSON.stringify({ok:true,result})+'\n');
  }catch(e){socket.end(JSON.stringify({ok:false,error:e.message})+'\n');}
 });});
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(control,resolve);});
 fs.mkdirSync(runtimeDir,{recursive:true});fs.writeFileSync(runtime,JSON.stringify({pid:process.pid,control,keyPath:peer.keyPath}));
 globalThis[symbol]={clients,server,peer,stateDirectory};return {};
};

}
