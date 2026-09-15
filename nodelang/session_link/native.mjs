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
export async function postCodex(threadId,prompt){
 if(admittedAttachment){if(threadId!==admittedAttachment.destination)throw new Error('Attachment destination mismatch');return await attachmentCall('attachment-post',{text:prompt});}
 if(process.env.CODEX_APP_TOOLS_PIPE_PATH&&process.env.CODEX_THREAD_ID)return await nativeCall('send_message_to_thread',{threadId,prompt});
 if(process.env.SESSION_LINK_PRODUCT_WORKER==='1')throw new Error('Admitted native Codex app context unavailable; another caller context will not be borrowed');
 const dir=path.join(stateDir(),'connections');
 for(const name of fs.readdirSync(dir).filter(n=>n.endsWith('.runtime.json'))){
  let config,token;
  try{config=JSON.parse(fs.readFileSync(path.join(dir,name),'utf8'));token=JSON.parse(fs.readFileSync(config.keyPath,'utf8')).peerToken;}catch{continue;}
  // Probe capabilities before attempting a mutation. Never retry a submitted post.
  const call=request=>new Promise((resolve,reject)=>{const s=net.connect(config.control);let data='';s.setEncoding('utf8');s.setTimeout(25000,()=>{s.destroy();reject(new Error('Bridge request timeout; delivery uncertain'));});s.on('error',reject);s.on('connect',()=>s.write(JSON.stringify({...request,token})+'\n'));s.on('data',c=>{data+=c;if(data.length>2000000){s.destroy();reject(new Error('Oversized response'));return;}if(data.includes('\n')){s.destroy();try{const r=JSON.parse(data);r.ok?resolve(r.result):reject(new Error(r.error));}catch(e){reject(e);}}});});
  let capabilities;try{capabilities=await call({operation:'capabilities'});}catch{continue;}
  if(capabilities.postCodex)return await call({operation:'post-codex',threadId,text:prompt});
 }
 throw new Error('No active bridge supports terminal-to-Codex delivery; connect from a current Codex Desktop task');
}
export function nativeCall(tool,args,threadId=process.env.CODEX_THREAD_ID){
  return new Promise((resolve,reject)=>{
    const socket=net.connect(process.env.CODEX_APP_TOOLS_PIPE_PATH);
    let buffer=Buffer.alloc(0),settled=false;
    const finish=(err,result)=>{if(settled)return;settled=true;clearTimeout(timer);socket.destroy();err?reject(err):resolve(result);};
    const timer=setTimeout(()=>finish(new Error('Native request timed out; delivery uncertain; do not resend automatically')),20000);
    socket.on('error',e=>finish(e));
    socket.on('connect',()=>{
      const body=Buffer.from(JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{arguments:args,callId:'claude-link-'+crypto.randomUUID(),namespace:'codex_app',threadId,tool,turnId:'claude-link-'+crypto.randomUUID()}}));
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
