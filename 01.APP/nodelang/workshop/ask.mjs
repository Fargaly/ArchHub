/* Native task control stays application-owned; all task text/replies live in Workshop. */
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {sendExtra} from './extra-apps.mjs';
import {postCodex,mailbox,mailboxSend} from './native.mjs';
export {mailboxSend} from './native.mjs';
import {catalog} from './bridge.mjs';
import {readMessage} from './paths.mjs';
import {validateModel} from './opencode-model.mjs';
import {interrupt} from './interrupt.mjs';
import {askDormant,runDormantCommand} from './dormant.mjs';
export {askDormant,runDormantCommand};
const args=process.argv.slice(2),opt=n=>{const i=args.indexOf('--'+n);return i<0?undefined:args[i+1];};
const validate=text=>{if(typeof text!=='string'||!text.trim()||text.length>32000)throw new Error('Text must contain 1–32000 characters');return text;};
const span=(units,scale=1000)=>units*scale;
export async function ask(app,session,text,permissionMode='prompting',{expected,onDispatch=()=>{},model,discover,dispatchControl,mailboxMessage,mailboxCall}={}){
 const callMailbox=mailboxCall||mailbox;
 validate(text);validateModel(model);
 if(model!==undefined&&app!=='opencode')throw new Error('Explicit model selection is OpenCode-only; not sent');
 if(!['claude','codex','opencode','antigravity','antigravity-ide'].includes(app))throw new Error('Unsupported target app');
 if(!['prompting','bypass'].includes(permissionMode))throw new Error('Invalid sender permission mode');
 const list=discover||catalog;
 const all=await list({apps:[app]});
 const matches=(all[app]||[]).filter(s=>s.id===session||s.selector===session||s.title===session);
 if(!matches.length&&all.adapterStatus?.[app]?.status==='unavailable')throw new Error((app==='codex'?'Codex tasks':app)+' unavailable: '+all.adapterStatus[app].reason);
 if(matches.length!==1)throw new Error('Target must resolve to exactly one live session; use its exact ID');
 const target=matches[0];
 // OpenCode's native plugin returns its OS process.pid as runtimeId.
 // Codex list_threads has no per-target PID: keep its completion unverified.
 const targetPid=target.pid ?? (app==='opencode'&&Number.isInteger(target.runtimeId)&&target.runtimeId>0?target.runtimeId:undefined);
 if(expected)for(const field of ['app','id','pid','port','socket','cwd','runtimeId'])if(expected[field]!==target[field])throw new Error('Recipient binding changed before dispatch: '+field);
 if(app==='codex'&&target.id===process.env.CODEX_THREAD_ID)throw new Error('Synchronous self-request would deadlock; use another existing task');
 let identityPage=callMailbox('read',{since:0,include_archived:true}),identities=[...identityPage.declarations];
 while(identityPage.declarations_more){identityPage=callMailbox('read',{since:identityPage.next_since,include_archived:true,declarations_after:identityPage.declarations_after});identities.push(...identityPage.declarations);}
 const targetGenerations=new Set(identities.filter(row=>row.process_alive&&row.app===app&&row.native_session_id===target.id)
  .flatMap(row=>(row.process_lineage||[]).filter(process=>process.pid===targetPid).map(process=>process.created_at)));
 let targetGeneration=targetGenerations.size===1?[...targetGenerations][0]:null;
 let note;
 if(mailboxMessage){
  if(typeof mailboxMessage.message_id!=='string'||!Number.isSafeInteger(mailboxMessage.sequence)||mailboxMessage.sequence<1)throw new Error('Invalid Workshop source reference');
  const page=callMailbox('read',{since:mailboxMessage.sequence-1});
  if(!page.messages.some(row=>row.id===mailboxMessage.message_id&&row.sequence===mailboxMessage.sequence&&
     (!mailboxMessage.work_root||row.refs?.includes(mailboxMessage.work_root))))throw new Error('Workshop source is not public and readable; private content is never copied');
  note={...mailboxMessage,sender_label:'founder'};
 }else note=callMailbox('send',{to:target.id,text,...(app!=='claude'?{native_control:{app,id:target.id,...(model?{model}:{})}}:{})});
 const pointer=`Application task in Workshop, message ${note.message_id}. Use MCP read(since=${note.sequence-1}) to read it. Declare task/paths/status with request_id=${note.work_root||note.message_id}. Reply ONLY with MCP send(to=${JSON.stringify(note.sender_label)}, reply_to=${JSON.stringify(note.message_id)}, text=your_result). Keep the declaration current. No Workshop answer or peer reply.`;
 let controlError=null;
 // Claude follows the Workshop record in its plugin; other apps retain native wakeup.
 const dispatch=async()=>{
 if(app==='claude'){onDispatch();return;}
 if(dispatchControl){await dispatchControl(target,pointer,{onDispatch,model});return;}
 if(app==='codex'){onDispatch();await postCodex(target.id,pointer,{requestId:note.message_id});} else await sendExtra(target,pointer,{onDispatch,model});
 };
 void dispatch().catch(error=>{controlError=error;});
 let since=note.sequence;
 const deadline=Date.now()+span(180);
 const pollWait=span(1);
 while(Date.now()<deadline){
  let page=callMailbox('read',{since,include_archived:true}),declarations=[...(page.declarations||[])];
  const messages=page.messages;since=page.next_since;
  while(page.declarations_more){
   page=callMailbox('read',{since,declarations_after:page.declarations_after,include_archived:true});
   declarations.push(...page.declarations);messages.push(...page.messages);since=page.next_since;
  }
  if(targetGeneration===null&&targetPid!==undefined){
   const generations=new Set(declarations.filter(row=>row.process_alive&&row.app===app&&row.native_session_id===target.id)
    .flatMap(row=>(row.process_lineage||[]).filter(process=>process.pid===targetPid).map(process=>process.created_at)));
   if(generations.size===1)targetGeneration=[...generations][0];
  }
  const senders=new Set(declarations.filter(row=>row.app===app&&row.native_session_id===target.id&&targetGeneration!==null&&
   row.process_lineage?.some(process=>process.pid===targetPid&&process.created_at===targetGeneration)).map(row=>row.agent+' ['+row.session+']'));
  const peerReply=row=>row.reply_to===note.message_id&&row.category==='app:workshop:category:note';
  const reply=messages.find(row=>peerReply(row)&&senders.has(row.author));
  if(reply)return {status:'replied',id:reply.id,text:reply.content.replace(/^To [^\n]+:\n/,''),mailbox_message:note.message_id};
  if(controlError)return {status:'uncertain',reason:'native_control_failed',mailbox_message:note.message_id};
  if(targetGeneration===null&&messages.some(row=>peerReply(row)&&row.author!==note.sender_label))return {status:'uncertain',reason:'recipient_identity_unverified',mailbox_message:note.message_id};
  await new Promise(resolve=>setTimeout(resolve,pollWait));
 }
 throw new Error('No Workshop reply confirmed in 180 seconds; task may have run; do not resend automatically.');
}
async function runCli(){
 if(args[0]==='ask-dormant'){
  const result=await askDormant(opt('app'),opt('session'),await readMessage(args),{level:args.includes('--wake')?'wake':opt('session')?'read':'search',model:opt('model')});
  process.stdout.write(JSON.stringify(result)+'\n',()=>process.exit(result.status==='failed'?1:0));
 }
 else if(args[0]==='interrupt')console.log(JSON.stringify(await interrupt(opt('app'),opt('session'),opt('reason'),{permissionMode:opt('permission-mode')??'prompting'})));
 else if(args[0]==='ask')console.log(JSON.stringify(await ask(opt('app'),opt('session'),await readMessage(args),opt('permission-mode')??'prompting')));
 else if(args[0]==='send')console.log(JSON.stringify(mailboxSend(opt('session')||'*',await readMessage(args))));
 else if(args[0]==='answer'){await readMessage(args);throw new Error('Replies use MCP send(reply_to=the Workshop message id); no peer reply endpoint.');}
 else throw new Error('Use ask or send; replies use MCP send(reply_to=the Workshop message id).');
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 runCli().catch(err=>{console.error(err.message);process.exitCode=1;});
}
