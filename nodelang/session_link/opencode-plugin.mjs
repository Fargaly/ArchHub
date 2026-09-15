import fs from 'node:fs';
import net from 'node:net';
import crypto from 'node:crypto';
import path from 'node:path';
import {PeerEndpoint} from './vendor/src/peer-protocol.mjs';
// A prompt may produce several assistant messages before its final response.
// Only public text from that exact completed turn may cross the transport.
export async function collectOpenCodeTurn(client, {sessionId, directory, reply}) {
 const fail = detail => {throw new Error('OpenCode response incomplete: '+detail+'; prompt was already sent, do not resend automatically');};
 const final = reply?.info;
 if (!final || final.role !== 'assistant' || final.sessionID !== sessionId ||
     typeof final.id !== 'string' || typeof final.parentID !== 'string') fail('final identity unavailable');
 let response;
 try {response = await client.session.messages({path:{id:sessionId}, query:{directory, limit:64}, signal:AbortSignal.timeout(10000)});}
 catch (_) {fail('turn read failed');}
 if (response?.error) fail('turn read rejected');
 const rows = response?.data ?? response;
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
 const result={id:final.id, parent_id:final.parentID, message_ids:messageIds, text:texts.join('\n')};
 // JSON escaping can expand control characters sixfold. Leave room for every
 // enclosing bridge below its 1,000,000-character response limit.
 if (Buffer.byteLength(JSON.stringify({ok:true,result})+'\n','utf8')>768*1024) fail('serialized response byte bound');
 return result;
}

export function createSessionLinkPlugin({stateDirectory}){
 if(typeof stateDirectory!=='string'||!path.isAbsolute(stateDirectory))throw new Error('Explicit application transport state directory required');
 const runtimeDir=path.join(stateDirectory,'opencode-runtimes');
 const runtime=path.join(runtimeDir,process.pid+'.json');
 return async ({client,directory})=>{
 const symbol=Symbol.for('archhub.session-link.opencodeserver');
 if(globalThis[symbol]&&globalThis[symbol].stateDirectory!==stateDirectory)throw new Error('This OpenCode process is attached to another transport state directory');
 if(globalThis[symbol]){globalThis[symbol].clients.set(directory,client);return {};}
 const clients=new Map([[directory,client]]),busy=new Set();
 const peer=new PeerEndpoint({name:'opencode-session-link-'+process.pid,cwd:directory});await peer.start();
 const control='\\\\.\\pipe\\LOCAL\\opencode-session-link-'+crypto.randomUUID();
 const unwrap=r=>{if(r.error)throw new Error('OpenCode SDK rejected request');return r.data??r;};
 const server=net.createServer(socket=>{let buffer='',handled=false;socket.setEncoding('utf8');socket.setTimeout(190000,()=>socket.destroy());socket.on('error',()=>{});socket.on('data',async chunk=>{
  if(handled)return;buffer+=chunk;if(buffer.length>70000){socket.destroy();return;}if(!buffer.includes('\n'))return;handled=true;
  try{const r=JSON.parse(buffer.slice(0,buffer.indexOf('\n')));if(r.token!==peer.peerToken)throw new Error('Unauthenticated request');let result;
   if(r.operation==='list'){const rows=[];for(const [cwd,c] of clients){const list=unwrap(await c.session.list({query:{directory:cwd}}));for(const s of list)rows.push({app:'opencode',id:s.id,title:s.title,cwd:s.directory||cwd,runtimeId:process.pid});}result=[...new Map(rows.map(x=>[x.id,x])).values()];}
   else if(r.operation==='send'){
    if(typeof r.text!=='string'||!r.text.trim()||r.text.length>32000)throw new Error('Invalid text');
    const c=clients.get(r.directory);if(!c)throw new Error('Workspace is not attached to this OpenCode process');
    const session=unwrap(await c.session.get({path:{id:r.id},query:{directory:r.directory}}));if(session.id!==r.id||session.directory!==r.directory)throw new Error('Session/workspace mismatch');
    const statuses=unwrap(await c.session.status({query:{directory:r.directory}}));
    if(busy.has(r.id)||(statuses[r.id]&&statuses[r.id].type!=='idle'))throw new Error('Session is busy; message not sent');
    busy.add(r.id);
    try{const reply=unwrap(await c.session.prompt({path:{id:r.id},query:{directory:r.directory},body:{parts:[{type:'text',text:r.text}]}}));
    result=await collectOpenCodeTurn(c,{sessionId:r.id,directory:r.directory,reply});}finally{busy.delete(r.id);}
   }else throw new Error('Unsupported operation');socket.end(JSON.stringify({ok:true,result})+'\n');
  }catch(e){socket.end(JSON.stringify({ok:false,error:e.message})+'\n');}
 });});
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(control,resolve);});
 fs.mkdirSync(runtimeDir,{recursive:true});fs.writeFileSync(runtime,JSON.stringify({pid:process.pid,control,keyPath:peer.keyPath}));
 globalThis[symbol]={clients,server,peer,stateDirectory};return {};
};

}
