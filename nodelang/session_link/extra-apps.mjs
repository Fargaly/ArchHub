import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {stateDir} from './paths.mjs';
const root=stateDir();
const ps=path.join(process.env.SystemRoot,'System32/WindowsPowerShell/v1.0/powershell.exe');
let cachedAt=0,cached=[];
function agProcesses(){
 if(Date.now()-cachedAt<5000)return cached;
 const script=`$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'language_server.exe' -or $_.Name -eq 'language_server_windows_x64.exe' }; $rows=@(); foreach($x in $p){ if($x.ExecutablePath -notmatch '\\\\Programs\\\\Antigravity(?: IDE)?\\\\'){continue};$m=[regex]::Match($x.CommandLine,'--csrf_token[= ]+([^ ]+)');if(-not $m.Success){continue};$ports=@(Get-NetTCPConnection -State Listen -OwningProcess $x.ProcessId -ErrorAction SilentlyContinue | Where-Object LocalAddress -eq '127.0.0.1' | Select-Object -ExpandProperty LocalPort);$rows+=@{pid=$x.ProcessId;app=$(if($x.ExecutablePath -match 'Antigravity IDE'){'antigravity-ide'}else{'antigravity'});token=$m.Groups[1].Value;ports=$ports} }; ConvertTo-Json -InputObject @($rows) -Depth 4 -Compress`;
 // Authentication travels only through this child-process capture into memory.
 cached=JSON.parse(execFileSync(ps,['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,timeout:15000,encoding:'utf8'}));cachedAt=Date.now();return cached;
}
export async function agCall(endpoint,method,body={}){
 const processInfo=agProcesses().find(p=>p.pid===endpoint.pid&&p.app===endpoint.app&&p.ports.includes(endpoint.port));
 if(!processInfo)throw new Error('Antigravity process or endpoint changed; reconnect');
 const res=await fetch(`http://127.0.0.1:${endpoint.port}/exa.language_server_pb.LanguageServerService/${method}`,{method:'POST',headers:{'Content-Type':'application/json','Connect-Protocol-Version':'1','x-codeium-csrf-token':processInfo.token},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
 if(!res.ok)throw new Error(`${endpoint.app} ${method}: HTTP ${res.status}; no automatic retry`);
 return await res.json();
}
export async function pluginRpc(request,runtimeId){
 if(!Number.isInteger(runtimeId))throw new Error('Exact OpenCode runtime required');
 const cfg=JSON.parse(fs.readFileSync(path.join(root,'opencode-runtimes',runtimeId+'.json'),'utf8'));
 const token=JSON.parse(fs.readFileSync(cfg.keyPath,'utf8')).peerToken;
 return new Promise((resolve,reject)=>{const s=net.connect(cfg.control);let data='';s.setEncoding('utf8');const timer=setTimeout(()=>{s.destroy();reject(new Error('OpenCode timeout; delivery may be uncertain'));},180000);s.on('error',e=>{clearTimeout(timer);reject(e);});s.on('connect',()=>s.write(JSON.stringify({...request,token})+'\n'));s.on('data',c=>{data+=c;if(data.length>2000000){s.destroy();clearTimeout(timer);reject(new Error('Oversized OpenCode response'));return;}if(data.includes('\n')){clearTimeout(timer);s.destroy();try{const r=JSON.parse(data);r.ok?resolve(r.result):reject(new Error(r.error));}catch(e){reject(e);}}});});
}
export async function discoverExtra(){
 const result={opencode:[],antigravity:[],'antigravity-ide':[],adapterStatus:{}};
 result.adapterStatus.opencode='plugin not active; reload OpenCode and open a workspace';
 try{for(const name of fs.readdirSync(path.join(root,'opencode-runtimes')).filter(n=>/^\d+\.json$/.test(n))){try{result.opencode.push(...await pluginRpc({operation:'list'},Number(name.slice(0,-5))));result.adapterStatus.opencode='live';}catch{}}}catch{}
 try{for(const p of agProcesses()){
   let found=false;
   for(const port of p.ports){try{const e={app:p.app,pid:p.pid,port};let r=await agCall(e,'GetAllCascadeTrajectories');
     if(p.app==='antigravity-ide'&&!Object.keys(r.trajectorySummaries||{}).length){
       // GetAll lists loaded trajectories only. Hydrate the most recent saved
       // conversation through a native read; never create or rewrite a chat.
       const savedDir=path.join(process.env.USERPROFILE,'.gemini','antigravity-ide','conversations');
       const saved=fs.readdirSync(savedDir).filter(n=>/^[0-9a-f-]{36}\.db$/.test(n)).sort((a,b)=>fs.statSync(path.join(savedDir,b)).mtimeMs-fs.statSync(path.join(savedDir,a)).mtimeMs)[0];
       if(saved){await agCall(e,'GetCascadeTrajectory',{cascadeId:saved.slice(0,-3)});r=await agCall(e,'GetAllCascadeTrajectories');}
     }
     if(!r.trajectorySummaries)continue;
     for(const [id,v] of Object.entries(r.trajectorySummaries))result[p.app].push({...e,id,selector:id+'@'+p.pid,title:v.summary||id,status:v.status});found=true;break;
   }catch{}}
   result.adapterStatus[p.app]=found?'live discovery':'no sessions returned';
 }}catch{result.adapterStatus.antigravity='discovery unavailable';}
 return result;
}
export async function sendExtra(endpoint,text,{onDispatch=()=>{}}={}){
 const lockDir=path.join(root,'dispatch-locks');fs.mkdirSync(lockDir,{recursive:true});
 const lock=path.join(lockDir,crypto.createHash('sha256').update(endpoint.app+'|'+endpoint.id).digest('hex')+'.json');
 let fd;try{fd=fs.openSync(lock,'wx');}catch(e){if(e.code==='EEXIST')throw new Error('Another request owns this session dispatch lock; message not sent. If its process exited, inspect the stale lock before recovery.');throw e;}
 fs.writeFileSync(fd,JSON.stringify({pid:process.pid,app:endpoint.app,session:endpoint.id,started:new Date().toISOString()}));fs.closeSync(fd);
 const cleanup=()=>{try{fs.rmSync(lock,{force:true});}catch{}};process.once('exit',cleanup);
 try{return await sendExtraLocked(endpoint,text,onDispatch);}finally{cleanup();process.removeListener('exit',cleanup);}
}
async function sendExtraLocked(endpoint,text,onDispatch){
 if(endpoint.app==='opencode'){onDispatch();return await pluginRpc({operation:'send',id:endpoint.id,directory:endpoint.cwd,text},endpoint.runtimeId);}
 const all=await agCall(endpoint,'GetAllCascadeTrajectories');
 if(!all.trajectorySummaries?.[endpoint.id])throw new Error('Exact Antigravity conversation unavailable');
 const baseline=all.trajectorySummaries[endpoint.id].stepCount||0;
 if(all.trajectorySummaries[endpoint.id].status!=='CASCADE_RUN_STATUS_IDLE')throw new Error('Antigravity session is busy; message not sent');
 // The native API does not inherit configuration when omitted. Reuse the
 // latest native user configuration verbatim, in memory only, including gates.
 const trajectory=await agCall(endpoint,'GetCascadeTrajectory',{cascadeId:endpoint.id});
 const inputs=(trajectory.trajectory?.steps||[]).filter(s=>s.userInput).reverse();
 const config=inputs.map(s=>s.userInput.userConfig||s.userInput.lastUserConfig).find(c=>c?.plannerConfig?.requestedModel||c?.plannerConfig?.planModel);
 if(!config)throw new Error('No established native model/configuration; message not sent');
 onDispatch();await agCall(endpoint,'SendUserCascadeMessage',{cascadeId:endpoint.id,items:[{text}],cascadeConfig:config});
 for(let n=0;n<90;n++){
  await new Promise(r=>setTimeout(r,2000));
  const current=await agCall(endpoint,'GetAllCascadeTrajectories');
  const summary=current.trajectorySummaries?.[endpoint.id];
  if(!summary)throw new Error('Conversation disappeared after submission; delivery uncertain');
  if(summary.status!=='CASCADE_RUN_STATUS_IDLE'||summary.stepCount<=baseline)continue;
  const r=await agCall(endpoint,'GetCascadeTrajectorySteps',{cascadeId:endpoint.id,stepOffset:baseline});
  const replies=(r.steps||[]).filter(s=>s.type==='CORTEX_STEP_TYPE_PLANNER_RESPONSE').map(s=>s.plannerResponse?.modifiedResponse||s.plannerResponse?.response||s.plannerResponse?.content||'').filter(Boolean);
  if(replies.length)return {id:endpoint.id+':'+summary.stepCount,text:replies.join('\n')};
  const error=(r.steps||[]).find(s=>s.type==='CORTEX_STEP_TYPE_ERROR_MESSAGE');
  if(error)throw new Error('Antigravity: '+(error.errorMessage?.error?.shortError||'native agent error'));
 }
 throw new Error('Reply not confirmed in 180 seconds; do not repeat the submitted prompt');
}
