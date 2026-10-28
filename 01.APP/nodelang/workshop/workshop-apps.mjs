// Workshop injection for the apps outside Workshop's original three (Claude, Codex, OpenCode).
// One channel: the Workshop reaches every agent through Workshop; each app keeps its own native door.
//   antigravity, antigravity-ide  the IDE's own cascade API (the same one ask/send use), dispatch only
//   cursor                        Cursor's Desktop Bridge (~/.cursor/desktop-bridge/<hash>.json)
//   archhub                       the app's BABOOM (its local turn door, settings/baboom-session.json)
//   seat                          any terminal-hosted CLI (gemini, cursor-agent, copilot, codex CLI) through
//                                 its console seat (console_seat.py here, draft-aware; adopted from OpenRig seat delivery)
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {agCall} from './extra-apps.mjs';
import {stateDir} from './paths.mjs';

// The adapters' timings, one place (milliseconds).
const WORKSHOP_APPS_NODE={id:'workshop.apps',params:{list_ms:5000,send_ms:10000,seat_ms:30000,baboom_ms:10000}};
const CURSOR_OFF='Cursor Desktop Bridge is off: turn on Settings > Beta > "Allow CLI to access desktop agents" and restart Cursor';
const alive=pid=>{try{process.kill(pid,0);return true;}catch(e){return e.code==='EPERM';}};
function records(folder){
 let names=[];
 try{names=fs.readdirSync(folder).filter(n=>n.endsWith('.json'));}
 catch(e){if(e.code!=='ENOENT')process.stderr.write('workshop: '+folder+' unreadable: '+e.message+'\n');return [];}  // absent = app not installed
 return names.map(n=>{try{return JSON.parse(fs.readFileSync(path.join(folder,n),'utf8'));}
  catch(e){process.stderr.write('workshop: skipped unreadable record '+n+': '+e.message+'\n');return null;}})
  .filter(r=>r&&r.pid&&alive(r.pid)).sort((a,b)=>(b.createdAt||0)-(a.createdAt||0));
}
function cursorPost(record,body,timeoutMs){
 return new Promise((resolve,reject)=>{
  const data=JSON.stringify(body);
  const req=http.request({socketPath:record.socketPath,method:'POST',path:'/',timeout:timeoutMs,
   headers:{Authorization:'Bearer '+record.token,'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}},res=>{
   let text='';res.setEncoding('utf8');res.on('data',c=>{text+=c;if(text.length>1000000)req.destroy(new Error('Oversized reply'));});
   res.on('end',()=>{try{resolve({code:res.statusCode,body:JSON.parse(text||'{}')});}catch(e){reject(e);}});
  });
  req.on('timeout',()=>req.destroy(new Error('Cursor Desktop Bridge did not answer in time')));
  req.on('error',reject);req.end(data);
 });
}
export async function cursorThreads(){
 const out=[];
 for(const record of records(process.env.CURSOR_DESKTOP_BRIDGE_DIR||path.join(os.homedir(),'.cursor','desktop-bridge'))){
  try{const r=await cursorPost(record,{type:'listThreads'},WORKSHOP_APPS_NODE.params.list_ms);if(r.code===200)out.push(...(r.body.threads||[]));}
  catch(e){process.stderr.write('workshop: Cursor Desktop Bridge did not list threads: '+e.message+'\n');}
 }
 return out;
}
async function injectCursor(recipient,text,onDispatch){
 const found=records(process.env.CURSOR_DESKTOP_BRIDGE_DIR||path.join(os.homedir(),'.cursor','desktop-bridge'));
 if(!found.length)return {status:'not_sent',reason:CURSOR_OFF};
 let last='unknown-thread';
 for(const record of found){
  onDispatch();
  let r;try{r=await cursorPost(record,{type:'sendMessage',threadId:recipient.id,text},WORKSHOP_APPS_NODE.params.send_ms);}catch(e){last='Cursor Desktop Bridge did not answer: '+e.message;continue;}
  if(r.code===200&&r.body.status==='submitted')return {status:'injected'};
  if(r.code===200&&r.body.status==='queued')return {status:'injected',note:'joined the running turn (Cursor queued it)'};
  if(r.body.status==='unknown-thread')continue;
  last=r.body.reason||r.body.message||r.body.error||r.body.status||('HTTP '+r.code);
 }
 return {status:'not_sent',reason:'Cursor: '+last};
}
async function injectAntigravity(recipient,text,onDispatch){
 const {discoverExtra}=await import('./extra-apps.mjs');
 const all=await discoverExtra({apps:[recipient.app]});
 const matches=(all[recipient.app]||[]).filter(r=>r.id===recipient.id||r.selector===recipient.id);
 if(matches.length!==1)return {status:'not_sent',reason:'Target must resolve to exactly one live '+recipient.app+' conversation; not injected'};
 const endpoint=matches[0];
 if(endpoint.status!=='CASCADE_RUN_STATUS_IDLE')return {status:'not_sent',reason:recipient.app+' session is busy; message not sent'};
 const trajectory=await agCall(endpoint,'GetCascadeTrajectory',{cascadeId:endpoint.id});
 const inputs=(trajectory.trajectory?.steps||[]).filter(s=>s.userInput).reverse();
 const config=inputs.map(s=>s.userInput.userConfig||s.userInput.lastUserConfig).find(c=>c?.plannerConfig?.requestedModel||c?.plannerConfig?.planModel);
 if(!config)return {status:'not_sent',reason:'No established native model/configuration; message not sent'};
 onDispatch();await agCall(endpoint,'SendUserCascadeMessage',{cascadeId:endpoint.id,items:[{text}],cascadeConfig:config});
 return {status:'injected'};
}
async function injectArchHub(recipient,text,messageId,onDispatch){
 // BABOOM's door is the running app's own loopback endpoint; its token is written by that app.
 let held;try{held=JSON.parse(fs.readFileSync(path.join(path.dirname(stateDir()),'settings','baboom-session.json'),'utf8'));}
 catch{return {status:'not_sent',reason:'BABOOM is not running (start ArchHub; BABOOM starts with it unless turned off)'};}
 if(!alive(held.pid)||!held.url)return {status:'not_sent',reason:'BABOOM is not running (start ArchHub; BABOOM starts with it unless turned off)'};
 onDispatch();
 const r=await fetch(held.url+'/baboom/turn',{method:'POST',headers:{'Content-Type':'application/json','X-ArchHub-BABOOM':held.token},
  body:JSON.stringify({text,message_id:messageId}),signal:AbortSignal.timeout(WORKSHOP_APPS_NODE.params.baboom_ms)});
 const answer=await r.json().catch(()=>({}));
 return answer.ok?{status:'injected'}:{status:'not_sent',reason:String(answer.error||('HTTP '+r.status))};
}
function injectSeat(recipient,text,onDispatch){
 const python=process.env.WORKSHOP_PYTHON;
 const pids=(recipient.pids||[]).filter(Number.isInteger);
 if(!python)return Promise.resolve({status:'not_sent',reason:'No console seat helper in this runtime'});
 if(!pids.length)return Promise.resolve({status:'not_sent',reason:'no process of this session has a console'});
 return new Promise(resolve=>{
  onDispatch();
  const child=spawn(python,['-m','nodelang.workshop.console_seat','deliver',...pids.map(String)],{windowsHide:true,stdio:['pipe','pipe','pipe'],
   env:{...process.env,PYTHONPATH:process.env.WORKSHOP_PYTHONPATH||process.env.PYTHONPATH||''}});
  let out='';child.stdout.on('data',c=>{out+=c;});
  const timer=setTimeout(()=>child.kill(),WORKSHOP_APPS_NODE.params.seat_ms);
  child.on('close',()=>{clearTimeout(timer);try{const r=JSON.parse(out.trim().split('\n').pop()||'{}');resolve(r.state==='delivered'?{status:'injected'}:{status:'not_sent',reason:(r.state||'seat_failed')+': '+(r.reason||'no answer')});}
   catch{resolve({status:'not_sent',reason:'console seat did not answer'});}});
  child.stdin.end(text);
 });
}
export async function injectApp(recipient,text,messageId,onDispatch){
 if(recipient.app==='cursor'&&!(recipient.pids||[]).length)return injectCursor(recipient,text,onDispatch);
 if(['antigravity','antigravity-ide'].includes(recipient.app))return injectAntigravity(recipient,text,onDispatch);
 if(recipient.app==='archhub')return injectArchHub(recipient,text,messageId,onDispatch);
 return injectSeat(recipient,text,onDispatch);
}
