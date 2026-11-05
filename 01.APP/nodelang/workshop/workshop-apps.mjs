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
import {execFileSync,spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {agCall} from './extra-apps.mjs';
import {stateDir} from './paths.mjs';

// The adapters' timings, one place (milliseconds).
const WORKSHOP_APPS_NODE={id:'workshop.apps',params:{list_ms:5000,send_ms:10000,seat_ms:30000,baboom_ms:10000,bridge_gate_ms:2000}};
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
function cursorBridgeGateOff(){
 // Cursor keeps a server-side gate separate from Settings > Beta. When it is false, listThreads/sendMessage
 // stay empty even with a live desktop-bridge record and desktopBridgeUserEnabled=true.
 try{
  const dbPath=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'Cursor','User','globalStorage','state.vscdb');
  const py=process.env.WORKSHOP_PYTHON;
  if(!py||!fs.existsSync(dbPath))return false;
  const script="import sqlite3,sys;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);r=c.execute(\"select value from ItemTable where key='cursor.desktopBridge.enabled'\").fetchone();print((r[0].decode() if isinstance(r[0],(bytes,bytearray)) else r[0]) if r else '')";
  const out=execFileSync(py,['-I','-B','-c',script,dbPath],{timeout:WORKSHOP_APPS_NODE.params.bridge_gate_ms,windowsHide:true,encoding:'utf8'});
  return String(out).trim().toLowerCase()==='false';
 }catch(error){
  process.stderr.write('workshop: Cursor Desktop Bridge gate check failed: '+error.message+'\n');
  return false;
 }
}
async function injectCursor(recipient,text,onDispatch){
 const found=records(process.env.CURSOR_DESKTOP_BRIDGE_DIR||path.join(os.homedir(),'.cursor','desktop-bridge'));
 if(!found.length)return {status:'not_sent',reason:CURSOR_OFF};
 if(cursorBridgeGateOff())return {status:'not_sent',reason:'Cursor Desktop Bridge account gate is off (cursor.desktopBridge.enabled=false); user Beta toggle alone cannot open the door'};
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
 // The app publishes metadata only; the existing OS credential owner keeps the bearer.
 let held;try{held=JSON.parse(fs.readFileSync(path.join(path.dirname(stateDir()),'settings','baboom-session.json'),'utf8'));}
 catch{return {status:'not_sent',reason:'BABOOM is not running (start ArchHub; BABOOM starts with it unless turned off)'};}
 if(!Number.isSafeInteger(held.pid)||held.pid<=0||!alive(held.pid)||typeof held.url!=='string')return {status:'not_sent',reason:'BABOOM is not running (start ArchHub; BABOOM starts with it unless turned off)'};
 let endpoint;
 try{endpoint=new URL(held.url);}catch{return {status:'not_sent',reason:'BABOOM local turn address is invalid'};}
 if(endpoint.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(endpoint.hostname)||endpoint.username||endpoint.password||endpoint.search||endpoint.hash||endpoint.pathname!=='/')
  return {status:'not_sent',reason:'BABOOM turn address must be the existing local app'};
 if(typeof held.credential!=='string'||!/^wcm:\/\/ArchHub\/baboom-turn:[0-9a-f]{64}$/.test(held.credential))return {status:'not_sent',reason:'BABOOM secure credential reference is unavailable; update and reopen ArchHub'};
 const python=process.env.WORKSHOP_PYTHON;
 if(!python)return {status:'not_sent',reason:'BABOOM credential helper is unavailable in this runtime'};
 let token;
 try{
  const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
  const read="import sys;sys.path.insert(0,sys.argv[1]);from nodelang.baboom_nograph import load_turn_credential;sys.stdout.write(load_turn_credential(sys.argv[2],sys.argv[3]) or '')";
  token=String(execFileSync(python,['-I','-B','-c',read,root,path.dirname(stateDir()),held.credential],{timeout:WORKSHOP_APPS_NODE.params.baboom_ms,windowsHide:true,encoding:'utf8',maxBuffer:4096,stdio:['ignore','pipe','pipe']}));
 }catch{return {status:'not_sent',reason:'BABOOM secure credential could not be read; reopen ArchHub'};}
 if(!/^[A-Za-z0-9_-]{32,256}$/.test(token))return {status:'not_sent',reason:'BABOOM secure credential is unavailable; reopen ArchHub'};
 onDispatch();
 const r=await fetch(endpoint.origin+'/baboom/turn',{method:'POST',redirect:'error',headers:{'Content-Type':'application/json','X-ArchHub-BABOOM':token},
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
// Grok Bot's agent runs in the cloud; its documented inbound door is a routine's webhook trigger
// (docs.x.ai/grok-bot/skills-routines-and-automations: POST to the routine URL with Authorization: Bearer <key>;
// the run lands in the Bot's chat). Grok writes its routine's URL and key here itself, through its local runner.
const GROK_ROUTINE_FILE='grok-routine.json';
async function injectGrok(text,messageId,onDispatch){
 let routine;
 try{routine=JSON.parse(fs.readFileSync(path.join(stateDir(),GROK_ROUTINE_FILE),'utf8'));}
 catch(e){return {status:'not_sent',reason:'Grok has no Workshop routine yet ('+GROK_ROUTINE_FILE+': '+(e.code||e.message)+'); it reads the room when it next pulls'};}
 if(typeof routine?.url!=='string'||!/^https:\/\//.test(routine.url)||typeof routine.key!=='string'||!routine.key)
  return {status:'not_sent',reason:'Grok routine webhook record is incomplete; not sent'};
 onDispatch();
 let r;try{r=await fetch(routine.url,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+routine.key},
  body:JSON.stringify({source:'ArchHub Workshop',message_id:messageId,text}),signal:AbortSignal.timeout(WORKSHOP_APPS_NODE.params.send_ms)});}
 catch(e){return {status:'not_sent',reason:'Grok routine webhook unreachable: '+String(e.cause?.code||e.message).slice(0,120)};}
 return r.ok?{status:'injected',note:'started its Workshop routine'}:{status:'not_sent',reason:'Grok routine webhook answered HTTP '+r.status};
}
export async function injectApp(recipient,text,messageId,onDispatch){
 // Cursor Desktop Bridge is the only inbound door for GUI Cursor. Pids on the declaration are the
 // Cursor.exe host process, not a console seat; routing those pids into injectSeat caused
 // console_unavailable and blocked Workshop delivery into Cursor chats.
 if(recipient.app==='cursor')return injectCursor(recipient,text,onDispatch);
 if(['antigravity','antigravity-ide'].includes(recipient.app))return injectAntigravity(recipient,text,onDispatch);
 if(recipient.app==='archhub')return injectArchHub(recipient,text,messageId,onDispatch);
 if(recipient.app==='grok')return injectGrok(text,messageId,onDispatch);
 return injectSeat(recipient,text,onDispatch);
}
