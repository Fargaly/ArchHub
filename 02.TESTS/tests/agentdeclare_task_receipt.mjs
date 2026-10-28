// Only native task control is synthetic; text, identity and receipt use the real mailbox.
import fs from 'node:fs';
import {ask} from '../01.APP/nodelang/workshop/ask.mjs';
const {id,runtimeId,app='opencode'}=JSON.parse(fs.readFileSync(0,'utf8'));
const result=await ask(app,id,'Native task receipt court','prompting',{
 discover:async()=>({[app]:[{app,id,...(app==='opencode'?{runtimeId}:{})}]}),
 dispatchControl:async()=>{console.log('ready');}
});
if(app==='opencode'&&result.text!=='Native task completed through Workshop')throw new Error('Wrong task completion');
if(app==='codex'&&(result.status!=='uncertain'||result.reason!=='recipient_identity_unverified'))throw new Error('Unverified Codex completion accepted');
console.log(JSON.stringify(result));
