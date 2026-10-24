// OpenRig ask/ask-wake (Apache-2.0): read evidence first; wake is explicit only.
import fs from 'node:fs';
import {opendir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {homeDir,resolveCodexBin} from './vendor/src/platform.mjs';
import {MESSAGE_LIMIT as limit} from './paths.mjs';

const directory=path.dirname(fileURLToPath(import.meta.url));
const uuid=/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const failure=reason=>Object.assign(new Error(reason),{code:reason});
const failed=(reason,level)=>({status:'failed',reason,level,execution_verified:false});
function transcriptRoots(){
 const claude=process.env.CLAUDE_CONFIG_DIR||path.join(homeDir(),'.claude');
 const codex=process.env.CODEX_HOME||path.join(homeDir(),'.codex');
 return {claude:[path.join(claude,'projects')],codex:[path.join(codex,'sessions'),path.join(codex,'archived_sessions')]};
}
async function* files(root,signal){
 signal.throwIfAborted();
 let entries;
 try{entries=await opendir(root);}catch(error){if(error.code==='ENOENT')return;throw failure('transcript_read_failed');}
 for await(const entry of entries){
  signal.throwIfAborted();
  const file=path.join(root,entry.name);
  if(entry.isDirectory())yield* files(file,signal);
  else if(entry.isFile()&&entry.name.endsWith('.jsonl'))yield file;
 }
}
function message(row){
 if(row.isMeta||row.isSidechain)return null;
 const value=row.type==='response_item'?row.payload:row.message;
 if(!value||!['user','assistant'].includes(value.role))return null;
 const content=value.content;
 const text=typeof content==='string'?content:Array.isArray(content)?content
  .filter(part=>['text','input_text','output_text'].includes(part.type)&&typeof part.text==='string').map(part=>part.text).join('\n'):'';
 return text.trim()?{role:value.role,text}:null;
}
async function scan(file,signal,accept){
 const stream=fs.createReadStream(file,{encoding:'utf8',highWaterMark:65536,signal});
 let pending='',line=0;
 const consume=text=>{
  line++;
  if(!text.trim())return;
  let row;try{row=JSON.parse(text);}catch{throw failure('transcript_invalid');}
  if(!row||typeof row!=='object'||Array.isArray(row))throw failure('transcript_invalid');
  accept(row,line);
 };
 try{
  for await(const chunk of stream){
   pending+=chunk;
   let end;
   while((end=pending.indexOf('\n'))>=0){
    if(end>1048576)throw failure('transcript_line_limit');
    consume(pending.slice(0,end));pending=pending.slice(end+1);signal.throwIfAborted();
   }
   if(pending.length>1048576)throw failure('transcript_line_limit');
  }
  consume(pending);
 }catch(error){if(error.code==='ABORT_ERR'||signal.aborted)throw error;throw failure(error.code?.startsWith('transcript_')?error.code:'transcript_read_failed');}
 finally{stream.destroy();}
}
async function locate(roots,app,session,signal){
 const found=[];
 for(const [provider,paths] of Object.entries(roots)){
  if(app&&provider!==app)continue;
  for(const root of paths)for await(const file of files(root,signal)){
   const token=path.basename(file).match(/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$/i)?.[1];
   if(token&&(!session||token.toLowerCase()===session.toLowerCase()))found.push({file,app:provider,session:token});
  }
 }
 return found;
}
async function freeLocalModel(model,fetcher,signal){
 if(typeof model!=='string'||!/^[a-z0-9][a-z0-9._:/-]{0,120}$/i.test(model)||/cloud/i.test(model))throw failure('wake_free_model_unavailable');
 const response=await fetcher('http://127.0.0.1:11434/api/tags',{signal});
 if(!response.ok)throw failure('wake_free_model_unavailable');
 const reader=response.body.getReader(),chunks=[];let size=0;
 try{for(;;){
  signal.throwIfAborted();const {value,done}=await reader.read();if(done)break;
  size+=value.byteLength;if(size>1048576)throw failure('wake_free_model_unavailable');chunks.push(value);
 }}finally{await reader.cancel();}
 const rows=JSON.parse(Buffer.concat(chunks).toString('utf8')).models;
 const selected=Array.isArray(rows)?rows.filter(row=>row.name===model):[];
 if(selected.length!==1||selected[0].remote_host||selected[0].remote_model||selected[0].details?.format!=='gguf'||!(selected[0].size>0))
  throw failure('wake_free_model_unavailable');
}
function wakeCommand(app,session,model){
 const env={OLLAMA_HOST:'http://127.0.0.1:11434'};
 if(app==='codex')return {command:resolveCodexBin(),env,args:['exec','--oss','--local-provider','ollama',
  '-c','model_provider="ollama"','-c','model_providers.ollama.base_url="http://127.0.0.1:11434/v1"',
  '-c','model_providers.ollama.requires_openai_auth=false','--model',model,'--sandbox','read-only',
  'resume',session,'-','--json','--ignore-user-config']};
 Object.assign(env,{ANTHROPIC_BASE_URL:'http://127.0.0.1:11434',ANTHROPIC_AUTH_TOKEN:'ollama',ANTHROPIC_API_KEY:'',
  ANTHROPIC_DEFAULT_HAIKU_MODEL:model,ANTHROPIC_DEFAULT_SONNET_MODEL:model,ANTHROPIC_DEFAULT_OPUS_MODEL:model});
 return {command:process.platform==='win32'?path.join(homeDir(),'.local','bin','claude.exe'):'claude',env,
  args:['-p','--resume',session,'--model',model,'--output-format','json','--max-turns','1','--tools','',
   '--settings',JSON.stringify({env})]};
}
export function runDormantCommand(request){
 const python=process.env.ARCHHUB_PYTHON||[
  path.resolve(directory,'../../../.venv/Scripts/python.exe'),path.resolve(directory,'../../runtime/python/python.exe')
 ].find(file=>fs.existsSync(file))||'python';
 return new Promise(resolve=>{
  const child=execFile(python,[path.resolve(directory,'../session_link_transport.py'),'--dormant-wake'],
   {encoding:'utf8',windowsHide:true,timeout:request.timeoutMs,maxBuffer:1048576,signal:request.signal},(error,stdout)=>{
    if(error)resolve({code:null,stdout:'',timedOut:!!error.killed||error.name==='AbortError',reason:'wake_runner_failed'});
    else try{resolve(JSON.parse(stdout));}catch{resolve({code:null,stdout:'',reason:'wake_runner_failed'});}
   });
  child.stdin.on('error',()=>{}); // The bounded runner reports early exit; never replay input.
  child.stdin.end(JSON.stringify({command:request.command,args:request.args,text:request.text,env:request.env,timeoutMs:request.timeoutMs}));
 });
}
function answer(app,result){
 if(result.timedOut)throw failure('wake_timeout');
 if(result.reason)throw failure(result.reason);
 if(result.code!==0)throw Object.assign(failure('wake_exit_nonzero'),{exitCode:result.code});
 if(!result.stdout?.trim())throw failure('wake_empty_answer');
 let rows;
 try{rows=result.stdout.trim().split('\n').map(line=>JSON.parse(line));}catch{throw failure('wake_invalid_answer');}
 if(rows.some(row=>row.is_error||row.type==='turn.failed'||row.type==='error'))throw failure('wake_provider_failed');
 const text=app==='claude'?rows.at(-1)?.result:rows.filter(row=>row.type==='item.completed'&&row.item?.type==='agent_message').at(-1)?.item.text;
 if(typeof text!=='string'||!text.trim())throw failure('wake_empty_answer');
 if(text.length>limit)throw failure('wake_output_limit');
 return text.trim();
}
export async function askDormant(app,session,text,{level=session?'read':'search',model,timeoutMs=180000,
 roots=transcriptRoots(),discover,fetcher=fetch,run=runDormantCommand}={}){
 const label={search:'L1',read:'L2',wake:'L3'}[level];
 if(!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>180000)return failed('timeout_invalid',label);
 const controller=new AbortController(),deadline=Date.now()+timeoutMs;
 let timer;
 const work=async()=>{
  if(!label||app!==undefined&&!['claude','codex'].includes(app))throw failure('dormant_target_invalid');
  if(typeof text!=='string'||!text.trim()||text.length>limit)throw failure('question_invalid');
  if(session!==undefined&&!uuid.test(session))throw failure('session_id_invalid');
  if(level!=='search'&&(!session||!app))throw failure('session_id_invalid');
  const candidates=await locate(roots,app,session,controller.signal);
  if(level!=='search'&&candidates.length!==1)throw failure(candidates.length?'session_ambiguous':'session_not_found');
  if(level!=='wake'){
   const terms=text.toLowerCase().match(/[\p{L}\p{N}_-]+/gu)||[];
   const hits=[];let omitted=0;
   for(const candidate of candidates)await scan(candidate.file,controller.signal,(row,line)=>{
    if(row.type==='session_meta'&&row.payload?.id?.toLowerCase()!==candidate.session.toLowerCase())throw failure('transcript_identity_mismatch');
    const value=message(row);
    if(value&&terms.some(term=>value.text.toLowerCase().includes(term))){
     const match=Math.min(...terms.map(term=>value.text.toLowerCase().indexOf(term)).filter(index=>index>=0));
     const offset=Math.max(0,match-256);
     if(hits.length<64)hits.push({...candidate,...value,text:value.text.slice(offset,offset+4000),line,
      truncated:offset>0||value.text.length>4000,char_offset:offset});else omitted++;
    }
   });
   return {status:hits.length?'evidence':'failed',...(hits.length?{}:{reason:'transcript_no_match'}),level:label,
    hits,complete:omitted===0,omitted,execution_verified:false};
  }
  await freeLocalModel(model,fetcher,controller.signal);
  const list=discover||((await import('./bridge.mjs')).catalog);
  const all=await list({apps:[app]});
  if(all.adapterStatus?.[app]?.status==='unavailable')throw failure('live_state_unavailable');
  if((all[app]||[]).some(row=>typeof row.id==='string'&&row.id.toLowerCase()===session.toLowerCase()))throw failure('session_live');
  const command=wakeCommand(app,session,model);
  const remaining=deadline-Date.now();if(remaining<=0)throw failure('wake_timeout');
  const result=await run({...command,text,timeoutMs:remaining,signal:controller.signal});
  return {status:'replied',level:label,app,session,text:answer(app,result),execution_verified:false};
 };
 try{return await Promise.race([work(),new Promise((_,reject)=>{timer=setTimeout(()=>{
  controller.abort();reject(failure(level==='wake'?'wake_timeout':'transcript_timeout'));
 },timeoutMs);})]);}
 catch(error){return {...failed(controller.signal.aborted?(level==='wake'?'wake_timeout':'transcript_timeout'):
  typeof error.code==='string'&&/^(?:wake_|session_|transcript_|question_|dormant_|live_)/.test(error.code)?error.code:
  level==='wake'?'wake_preflight_failed':'transcript_read_failed',label),
  ...(Number.isInteger(error.exitCode)?{exit_code:error.exitCode}:{})};}
 finally{clearTimeout(timer);controller.abort();}
}
