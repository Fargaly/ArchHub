// Bounded stdio adapter. The application owns policy, messages and work state.
import readline from 'node:readline';
import {catalog} from './bridge.mjs';
import {ask} from './ask.mjs';
import {setAttachment,attachmentCall,injectWorkshop} from './native.mjs';
process.env.WORKSHOP_PRODUCT_WORKER='1';
let active=false,dispatched=false,finished=false;
function emit(value){const encoded=JSON.stringify(value);if(Buffer.byteLength(encoded)>1048576)throw new Error('Oversized worker result');process.stdout.write(encoded+'\n');}
function terminal(value,code=0){
 if(finished)return;
 finished=true;
 input.close();process.stdin.pause();
 const encoded=JSON.stringify(value);
 if(Buffer.byteLength(encoded)>1048576){process.stderr.write('Oversized worker result\n',()=>process.exit(1));return;}
 process.stdout.write(encoded+'\n',()=>process.exit(code));
}
const input=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',async line=>{
 if(line.length>131072){terminal({event:'result',status:dispatched?'uncertain':'not_sent',reason:'input_limit'},1);return;}
 let r;try{r=JSON.parse(line);}catch{terminal({event:'result',status:'not_sent',reason:'invalid_json'},1);return;}
 if(r.operation==='cancel'&&active&&!finished){terminal({event:'result',status:'cancelled_wait',dispatch_attempted:dispatched,external_cancelled:false});return;}
 if(active)return;active=true;
 try{
  if(r.attachment)setAttachment(r.attachment);
  if(r.operation==='detach'){
   const result=await attachmentCall('attachment-revoke');
   terminal({event:'result',status:'ok',...result});
  }else
  if(r.operation==='discover'){
   let snapshots=0;
   const projection=all=>{const rows=['claude','codex','opencode','antigravity','antigravity-ide','cursor'].flatMap(app=>(all[app]||[]).map(s=>({...s,app})));return {status:'ok',recipients:rows.slice(0,128),providers:all.adapterStatus||{},complete_apps:rows.length>128?[]:all.complete_apps||[],truncated:rows.length>128};};
   const all=await catalog({apps:r.apps,onProgress:all=>{if(snapshots++<16)emit({event:'discovery_snapshot',...projection(all)});}});
   if(!r.apps||r.apps.includes('cursor')){const {cursorThreads}=await import('./workshop-apps.mjs');all.cursor=(await cursorThreads()).map(t=>({...t,selector:'cursor:'+t.id}));}
   terminal({event:'result',...projection(all)});
  }else if(r.operation==='activity'){
   const {pluginRpc}=await import('./extra-apps.mjs');
   if(r.attachment||typeof r.session!=='string'||typeof r.root!=='string')throw new Error('Invalid activity scope');
   const all=await catalog({apps:['opencode']});
   const targets=(all.opencode||[]).filter(row=>row.id===r.session);
   if(targets.length!==1)throw new Error('Exact OpenCode session unavailable');
   const target=targets[0];
   const events=await pluginRpc({operation:'activity',id:target.id,directory:target.cwd,root:r.root},target.runtimeId);
   terminal({event:'result',status:'ok',events,work_authority:false,execution_verified:false});
  }else if(r.operation==='inject'){
   if(r.attachment)throw new Error('Public Workshop injection cannot borrow a Work attachment');
   const result=await injectWorkshop(r.recipient,r.text,r.message_id,{model:r.model,permissionMode:r.permission_mode||'prompting',onDispatch:()=>{dispatched=true;emit({event:'dispatch_attempted'});}});
   terminal({event:'result',...result,dispatch_attempted:dispatched,work_authority:false,execution_verified:false});
  }else if(r.operation==='request'){
   const e=r.recipient;
   if(!e||typeof e.id!=='string'||typeof e.app!=='string')throw new Error('Invalid recipient');
   const reply=await ask(e.app,e.selector||e.id,r.text,r.permission_mode||'prompting',{expected:e,mailboxMessage:r.mailbox_message,onDispatch:()=>{dispatched=true;emit({event:'dispatch_attempted'});}});
   if(reply.status==='uncertain'){terminal({event:'result',status:'uncertain',dispatch_attempted:dispatched,reason:reply.reason,external_cancelled:false});return;}
   if(reply.status==='held'){terminal({event:'result',status:'held',dispatch_attempted:dispatched,delivery_status:reply.delivery_status,delivery_reason:reply.delivery_reason,mailbox_message:reply.mailbox_message});return;}
   if(typeof reply.text!=='string'||reply.text.length>32000)throw new Error('Reply text limit');
   terminal({event:'result',status:'replied',dispatch_attempted:dispatched,recipient:e,reply,work_authority:false,execution_verified:false});
  }else throw new Error('Invalid operation');
 }catch(e){
  const reason=/binding changed/i.test(e.message)?'binding_changed':/busy|dispatch lock/i.test(e.message)?'busy':/timeout|timed out|180 seconds/i.test(e.message)?'timeout':/exactly one|resolve|offline|unavailable/i.test(e.message)?'recipient_unavailable':'transport_failure';
  terminal({event:'result',status:dispatched?'uncertain':'not_sent',dispatch_attempted:dispatched,reason,external_cancelled:false});
 }finally{if(!finished){finished=true;input.close();process.stdin.pause();}}
});
