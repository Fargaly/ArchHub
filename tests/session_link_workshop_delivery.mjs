import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {ask}=await import(process.argv[2] ? pathToFileURL(process.argv[2]).href : new URL('../nodelang/session_link/ask.mjs',import.meta.url).href);
for(const app of ['claude','codex']){
 let nativeCalls=0,sends=0,dispatched=0;
 const target={app,id:'native-target',pid:123};
 const declarations=[{app,native_session_id:target.id,process_alive:true,
  process_lineage:[{pid:123,created_at:1}],agent:'Target',session:'session'}];
 const mailboxCall=(method,body)=>{
  if(method==='send'){sends++;return {message_id:'task',sequence:7,sender_label:'caller'};}
  return {declarations,declarations_more:false,next_since:8,
   messages:body.since===0?[]:[{id:'reply',reply_to:'task',author:'Target [session]',content:'To caller:\nOK'}]};
 };
 const result=await ask(app,target.id,'Existing approved task','prompting',{
  discover:async()=>({[app]:[target]}),mailboxCall,
  dispatchControl:async()=>{nativeCalls++;},onDispatch:()=>{dispatched++;}
 });
 assert.equal(result.status,'replied');assert.equal(result.text,'OK');assert.equal(sends,1);
 assert.equal(nativeCalls,app==='claude'?0:1,'Claude must use the Workshop delivery only');
 if(app==='claude')assert.equal(dispatched,1);
 console.log(JSON.stringify({app,status:result.status,workshop_sends:sends,native_calls:nativeCalls}));
}
