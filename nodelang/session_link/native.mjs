import net from 'node:net';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {stateDir} from './paths.mjs';
let admittedAttachment=null;
export function setAttachment(value){admittedAttachment=value;}
export async function attachmentCall(operation,extra={}){
 const grant=admittedAttachment;
 if(!grant||grant.expires_at<=Date.now())throw new Error('Attachment unavailable or expired');
 return await new Promise((resolve,reject)=>{
  const s=net.connect(grant.control);let data='',settled=false;
  const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);s.destroy();error?reject(error):resolve(value);};
  const timer=setTimeout(()=>finish(new Error('Attachment timeout; do not resend')),25000);
  s.setEncoding('utf8');s.on('error',()=>finish(new Error('Attachment unavailable')));
  s.on('end',()=>{if(!settled)finish(new Error('Attachment response incomplete'));});
  s.on('connect',()=>s.write(JSON.stringify({...extra,...grant,operation})+'\n'));
  s.on('data',chunk=>{data+=chunk;if(data.length>1000000)return finish(new Error('Attachment response oversized'));if(data.includes('\n')){try{const r=JSON.parse(data.slice(0,data.indexOf('\n')));if(!r.ok)throw new Error('Attachment refused or unavailable');finish(null,r.result);}catch(e){finish(e);}}});
 });
}
export function hasAttachment(){return admittedAttachment!==null;}
// The target's live list_threads row: its host goes into the send arguments.
async function liveCodexRow(threadId){
 const listed=await nativeCall('list_threads',{limit:50});
 const text=(listed.contentItems||[]).filter(x=>x.type==='inputText').map(x=>x.text).join('\n');
 const all=JSON.parse(text),rows=[...(all.pinnedThreads||[]),...(all.threads||[])].filter(t=>t.kind==='codex'&&t.id===threadId);
 if(rows.length!==1)throw new Error('Target is not exactly one live Codex task; not sent');
 return rows[0];
}
// requestId is the logical request's identity at its origin (an ask id, a
// Session Link message id); every route below carries it to the wire.
export async function postCodex(threadId,prompt,{requestId}={}){
 const identity=typeof requestId==='string'&&requestId?{messageId:requestId}:{};
 if(admittedAttachment){if(threadId!==admittedAttachment.destination)throw new Error('Attachment destination mismatch');return await attachmentCall('attachment-post',{text:prompt,...identity});}
 if(process.env.CODEX_APP_TOOLS_PIPE_PATH&&process.env.CODEX_THREAD_ID){
  // Direct from a Codex task: the caller is this task (its own thread and host);
  // the target's host is read from its live row, never assumed.
  const row=await liveCodexRow(threadId);
  return await nativeCall('send_message_to_thread',{threadId,prompt,...(typeof row.hostId==='string'&&row.hostId?{hostId:row.hostId}:{})},
   process.env.CODEX_THREAD_ID,identity.messageId?{requestId:identity.messageId}:{});
 }
 if(process.env.SESSION_LINK_PRODUCT_WORKER==='1')throw new Error('Admitted native Codex app context unavailable; another caller context will not be borrowed');
 const dir=path.join(stateDir(),'connections');
 for(const name of fs.readdirSync(dir).filter(n=>n.endsWith('.runtime.json'))){
  let config,token;
  try{config=JSON.parse(fs.readFileSync(path.join(dir,name),'utf8'));token=JSON.parse(fs.readFileSync(config.keyPath,'utf8')).peerToken;}catch{continue;}
  // Probe capabilities before attempting a mutation. Never retry a submitted post.
  const call=request=>new Promise((resolve,reject)=>{const s=net.connect(config.control);let data='';s.setEncoding('utf8');s.setTimeout(25000,()=>{s.destroy();reject(new Error('Bridge request timeout; delivery uncertain'));});s.on('error',reject);s.on('connect',()=>s.write(JSON.stringify({...request,token})+'\n'));s.on('data',c=>{data+=c;if(data.length>2000000){s.destroy();reject(new Error('Oversized response'));return;}if(data.includes('\n')){s.destroy();try{const r=JSON.parse(data);r.ok?resolve(r.result):reject(new Error(r.error));}catch(e){reject(e);}}});});
  let capabilities;try{capabilities=await call({operation:'capabilities'});}catch{continue;}
  if(capabilities.postCodex)return await call({operation:'post-codex',threadId,text:prompt,...identity});
 }
 throw new Error('No active bridge supports terminal-to-Codex delivery; connect from a current Codex Desktop task');
}
// The caller's host is where the calling Codex task runs. The app hands it to
// its own tools server as CODEX_APP_TOOLS_CALLER_HOST_ID; a saved link carries
// the value captured when it was made. Absent means omitted -- never invented,
// the app then applies its own default. The TARGET's host belongs in the tool's
// arguments (send_message_to_thread takes hostId from list_threads), not here.
export function callerHostFor(threadId,context={}){
  if(Object.prototype.hasOwnProperty.call(context,'hostId'))
    return typeof context.hostId==='string'&&context.hostId?context.hostId:undefined;
  const own=process.env.CODEX_APP_TOOLS_CALLER_HOST_ID;
  return threadId===process.env.CODEX_THREAD_ID&&typeof own==='string'&&own?own:undefined;
}
// One logical request keeps one identity from where it starts (a Session Link
// message, an ask, a shell reply) to the wire: callId/turnId derive from it.
// A stable identity is NOT permission to replay: a send whose outcome is
// uncertain stays uncertain and is never resent automatically because it
// would carry the same id -- the app's handling of a repeated callId is not a
// documented deduplication guarantee.
export function nativeCallParams(tool,args,threadId,context={}){
  const request=typeof context.requestId==='string'&&context.requestId?context.requestId:crypto.randomUUID();
  const hostId=callerHostFor(threadId,context);
  return {arguments:args,callerSource:'codex',callId:'session-link-'+request,...(hostId?{hostId}:{}),
    namespace:'codex_app',threadId,tool,turnId:'session-link-turn-'+request};
}
export function nativeCall(tool,args,threadId=process.env.CODEX_THREAD_ID,context={}){
  return new Promise((resolve,reject)=>{
    const socket=net.connect(process.env.CODEX_APP_TOOLS_PIPE_PATH);
    let buffer=Buffer.alloc(0),settled=false;
    const finish=(err,result)=>{if(settled)return;settled=true;clearTimeout(timer);socket.destroy();err?reject(err):resolve(result);};
    const timer=setTimeout(()=>finish(new Error('Native request timed out; delivery uncertain; do not resend automatically')),20000);
    socket.on('error',e=>finish(e));
    socket.on('connect',()=>{
      // Codex 26.924 validates tools/call params strictly and requires callerSource
      // ('codex'|'chatgpt'); the bundled codex-app-tools server sends 'codex' for a
      // Codex task. Without it the app answers -32602 "Invalid app tool request".
      const body=Buffer.from(JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:nativeCallParams(tool,args,threadId,context)}));
      const header=Buffer.alloc(4);header.writeUInt32LE(body.length);socket.write(Buffer.concat([header,body]));
    });
    socket.on('data',chunk=>{
      buffer=Buffer.concat([buffer,chunk]);
      if(buffer.length<4)return;
      const n=buffer.readUInt32LE(0);
      if(n>8*1024*1024)return finish(new Error('Oversized native response'));
      if(buffer.length<n+4)return;
      try{const response=JSON.parse(buffer.subarray(4,n+4));if(response.error)finish(new Error(response.error.message));else if(response.result?.success!==true)finish(new Error(JSON.stringify(response.result)));else finish(null,response.result);}catch(e){finish(e);}
    });
  });
}
