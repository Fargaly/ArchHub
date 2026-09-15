// Bounded stdio adapter. The application owns policy, messages and work state.
import readline from 'node:readline';
import {catalog} from './bridge.mjs';
import {ask} from './ask.mjs';
import {setAttachment,attachmentCall} from './native.mjs';
process.env.SESSION_LINK_PRODUCT_WORKER='1';
let active=false,dispatched=false,finished=false;
function emit(value){const encoded=JSON.stringify(value);if(Buffer.byteLength(encoded)>1048576)throw new Error('Oversized worker result');process.stdout.write(encoded+'\n');}
const input=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',async line=>{
 if(line.length>131072){emit({event:'result',status:dispatched?'uncertain':'not_sent',reason:'input_limit'});process.exit(1);}
 let r;try{r=JSON.parse(line);}catch{emit({event:'result',status:'not_sent',reason:'invalid_json'});process.exit(1);}
 if(r.operation==='cancel'&&active&&!finished){emit({event:'result',status:'cancelled_wait',dispatch_attempted:dispatched,external_cancelled:false});process.exit(0);}
 if(active)return;active=true;
 try{
  if(r.attachment)setAttachment(r.attachment);
  if(r.operation==='detach'){
   const result=await attachmentCall('attachment-revoke');
   emit({event:'result',status:'ok',...result});
  }else
  if(r.operation==='discover'){
   const all=await catalog();
   const recipients=['claude','codex','opencode','antigravity','antigravity-ide'].flatMap(app=>(all[app]||[]).map(s=>({...s,app})));
   emit({event:'result',status:'ok',recipients,providers:all.adapterStatus||{}});
  }else if(r.operation==='request'){
   const e=r.recipient;
   if(!e||typeof e.id!=='string'||typeof e.app!=='string')throw new Error('Invalid recipient');
   const reply=await ask(e.app,e.selector||e.id,r.text,r.permission_mode||'prompting',{expected:e,onDispatch:()=>{dispatched=true;emit({event:'dispatch_attempted'});}});
   if(typeof reply.text!=='string'||reply.text.length>32000)throw new Error('Reply text limit');
   emit({event:'result',status:'replied',dispatch_attempted:dispatched,recipient:e,reply,work_authority:false,execution_verified:false});
  }else throw new Error('Invalid operation');
 }catch(e){
  const reason=/binding changed/i.test(e.message)?'binding_changed':/busy|dispatch lock/i.test(e.message)?'busy':/timeout|timed out|180 seconds/i.test(e.message)?'timeout':/exactly one|resolve|offline|unavailable/i.test(e.message)?'recipient_unavailable':'transport_failure';
  emit({event:'result',status:dispatched?'uncertain':'not_sent',dispatch_attempted:dispatched,reason,external_cancelled:false});
 }finally{finished=true;input.close();process.stdin.pause();}
});
