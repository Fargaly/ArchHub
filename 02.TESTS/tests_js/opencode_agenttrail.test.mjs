import {test} from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {collectOpenCodeActivity} from '../../01.APP/nodelang/workshop/opencode-plugin.mjs';

test('Workshop projects only exact-session runtime tool parts and never prompts',async()=>{
 const directory=path.resolve('WORKSPACE'),sessionId='ses_fixture', at=Date.now();
 const part=(filePath,sessionID=sessionId)=>({type:'tool',sessionID,messageID:'msg_fixture',tool:'edit',
  state:{status:'running',input:{filePath,content:'PRIVATE_PROMPT_CANARY'},time:{start:at}}});
 let reads=0;
 const client={session:{messages:async request=>{
  reads++;assert.equal(request.query.limit,64);assert.equal(request.path.id,sessionId);
  return {data:[{info:{id:'msg_fixture',role:'assistant',sessionID:sessionId,time:{created:at}},parts:[
   {type:'text',text:'PRIVATE_PROMPT_CANARY'},{type:'reasoning',text:'PRIVATE_REASONING_CANARY'},
   part('01.APP/OWNED.py'),part('20.CLIENTS/SECRET.dwg'),part('60.PERSONAL/SECRET.txt'),
   part('../OUTSIDE.txt'),part('01.APP/WRONG.py','ses_other')]}]};
 }}};
 const events=await collectOpenCodeActivity(client,{sessionId,directory,root:directory});
 assert.equal(reads,1);assert.equal(events.length,1);
 assert.deepEqual(events[0],{provider:'opencode',session:sessionId,tool:'edit',file:'01.APP/OWNED.py',state:'working',at:at/1000});
 assert.doesNotMatch(JSON.stringify(events),/PRIVATE_|20\.CLIENTS|60\.PERSONAL|OUTSIDE/);
});

test('OpenCode observation refuses foreign workspace and oversized reads',async()=>{
 const root=path.resolve('WORKSPACE');
 const client={session:{messages:async()=>({data:Array.from({length:65},()=>({}))})}};
 await assert.rejects(collectOpenCodeActivity(client,{sessionId:'ses_fixture',directory:path.dirname(root),root}),/outside activity scope/);
 await assert.rejects(collectOpenCodeActivity(client,{sessionId:'ses_fixture',directory:root,root}),/message count bound/);
});

test('an intermediate completed tool-calls message never means the turn ended',async()=>{
 const root=path.resolve('WORKSPACE'),stamp=Date.now();
 const rows=[{info:{id:'m',role:'assistant',sessionID:'ses_fixture',finish:'tool-calls',time:{created:stamp,completed:stamp}},
  parts:[{type:'tool',sessionID:'ses_fixture',messageID:'m',tool:'edit',
   state:{status:'completed',input:{filePath:'01.APP/OWNED.py'},time:{start:stamp,end:stamp}}}]}];
 const events=await collectOpenCodeActivity({session:{messages:async()=>({data:rows})}},
  {sessionId:'ses_fixture',directory:root,root});
 assert.equal(events[0].state,'tool_ended');
});
