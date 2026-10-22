import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {ask}=await import(process.argv[2] ? pathToFileURL(process.argv[2]).href : new URL('../../01.APP/nodelang/session_link/ask.mjs',import.meta.url).href);
for(const app of ['claude','codex','opencode','antigravity','antigravity-ide'])for(const model of app==='opencode'?[undefined,{providerID:'openrouter',modelID:'qwen/qwen3.8-27b:free'}]:[undefined]){
 let nativeCalls=0,sends=0,dispatched=0;
 const target={app,id:'native-target',pid:123};
 const declarations=[{app,native_session_id:target.id,process_alive:true,
  process_lineage:[{pid:123,created_at:1}],agent:'Target',session:'session'}];
 const mailboxCall=(method,body)=>{
  if(method==='send'){sends++;assert.deepEqual(body.native_control,app==='claude'?undefined:{app,id:target.id,...(model?{model}:{})});return {message_id:'task',sequence:7,sender_label:'caller'};}
  return {declarations,declarations_more:false,next_since:8,
   messages:body.since===0?[]:[{id:'reply',reply_to:'task',author:'Target [session]',category:'app:workshop:category:note',content:'To caller:\nOK'}]};
 };
 const result=await ask(app,target.id,'Existing approved task','prompting',{
  discover:async()=>({[app]:[target]}),mailboxCall,model,
  dispatchControl:async(_target,_text,options)=>{nativeCalls++;assert.deepEqual(options.model,model);options.onDispatch();},onDispatch:()=>{dispatched++;}
 });
 assert.equal(result.status,'replied');assert.equal(result.text,'OK');assert.equal(sends,1);
 assert.equal(nativeCalls,app==='claude'?0:1,'An explicit native controller owns exactly one original dispatch');
 if(app==='claude')assert.equal(dispatched,1);
 console.log(JSON.stringify({app,status:result.status,workshop_sends:sends,native_calls:nativeCalls}));
}

{
 let sends=0,polls=0,clockReads=0;
 const originalNow=Date.now;
 const target={app:'codex',id:'native-target',pid:123};
 const declarations=[{app:'codex',native_session_id:target.id,process_alive:true,
  process_lineage:[{pid:123,created_at:1}],agent:'Target',session:'session'}];
 Date.now=()=>clockReads++<2?0:46000;
 try{
  const result=await ask('codex',target.id,'One watchdog only','prompting',{
   discover:async()=>({codex:[target]}),dispatchControl:async()=>{},
   mailboxCall:(method,body)=>{
    if(method==='send'){sends++;return {message_id:'task',sequence:7,sender_label:'caller'};}
    return {declarations,declarations_more:false,next_since:8,
     messages:body.since===0||++polls<2?[]:[{id:'reply',reply_to:'task',author:'Target [session]',category:'app:workshop:category:note',content:'To caller:\nOK'}]};
   }});
  assert.equal(result.status,'replied');assert.equal(sends,1,'ask must not create a second follow-up watchdog');
 }finally{Date.now=originalNow;}
 console.log('single application follow-up owner: pass');
}

{
 let polls=0;
 const target={app:'codex',id:'native-without-pid'};
 const result=await ask('codex',target.id,'Wait for the peer, not a delivery receipt','prompting',{
  discover:async()=>({codex:[target]}),dispatchControl:async()=>{},
  mailboxCall:(method,body)=>{
   if(method==='send')return {message_id:'task',sequence:7,sender_label:'caller'};
   return {declarations:[],declarations_more:false,next_since:8,messages:body.since===0?[]:
    ++polls===1?[{id:'receipt',reply_to:'task',author:'Workshop delivery',category:'app:workshop:category:tool',content:'{}'}]:
     [{id:'reply',reply_to:'task',author:'Target [session]',category:'app:workshop:category:note',content:'To caller:\nOK'}]};
  }});
 assert.equal(polls,2,'delivery receipts cannot masquerade as an unverified peer reply');
 assert.equal(result.reason,'recipient_identity_unverified','an absent Codex PID must remain explicit uncertainty');
 console.log('receipt is not a peer reply: pass');
}
