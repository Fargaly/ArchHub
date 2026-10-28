/* Real local socket fixture: no vendor process or account data is consulted. */
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {PeerEndpoint} from '../../01.APP/nodelang/workshop/vendor/src/peer-protocol.mjs';

const [directory,mode='codex',session='codex-fixture']=process.argv.slice(2);
const transcript=path.join(directory,'TURNS.jsonl');
const capture=record=>fs.appendFileSync(transcript,JSON.stringify(record)+'\n');
let stop;
if(mode==='opencode'){
 const {createWorkshopPlugin}=await import('../../01.APP/nodelang/workshop/opencode-plugin.mjs');
 const reply={info:{id:'answer',parentID:'question',role:'assistant',sessionID:session,time:{created:2}},
  parts:[{id:'text',messageID:'answer',sessionID:session,type:'text',text:'Fixture answer'}]};
 const client={session:{list:async()=>({data:[{id:session,directory,title:'OpenCode fixture'}]}),
  get:async()=>({data:{id:session,directory}}),status:async()=>({data:{[session]:{type:'idle'}}}),
  messages:async()=>({data:[{info:{id:'question',role:'user',sessionID:session,time:{created:1}},parts:[]},reply]}),
  prompt:async request=>{capture({text:request.body.parts[0].text});return {data:reply};}}};
 await createWorkshopPlugin({stateDirectory:directory})({client,directory});
 const state=globalThis[Symbol.for('archhub.workshop.opencodeserver')];
 stop=()=>{state.peer.stop();state.server.close();};
}else if(mode==='claude'){
 const peer=new PeerEndpoint({name:'Claude fixture',cwd:directory});
 await peer.start();
 peer.registry.entrypoint='claude-cli';peer.registry.sessionId=session;
 fs.writeFileSync(peer.registryPath,JSON.stringify(peer.registry));
 peer.onMessage(record=>capture(record));
 stop=()=>peer.stop();
}else{
 const connections=path.join(directory,'connections');fs.mkdirSync(connections,{recursive:true});
 const control=process.platform==='win32'?'\\\\.\\pipe\\LOCAL\\wsinject-'+crypto.randomUUID():path.join(directory,'BRIDGE.sock');
 const token=crypto.randomBytes(16).toString('hex');
 const keyPath=path.join(directory,'FIXTURE.key');fs.writeFileSync(keyPath,JSON.stringify({peerToken:token}));
 const server=net.createServer(socket=>{
  let buffer='';socket.setEncoding('utf8');
  socket.on('data',chunk=>{buffer+=chunk;if(!buffer.includes('\n'))return;
   const r=JSON.parse(buffer.slice(0,buffer.indexOf('\n')));
   if(r.token!==token){socket.end(JSON.stringify({ok:false,error:'fixture auth'})+'\n');return;}
   let result;
   if(r.operation==='list')result={codex:[{app:'codex',id:session,title:'Fixture Codex',cwd:directory}]};
   else if(r.operation==='capabilities')result={postCodex:true};
   else if(r.operation==='post-codex'){capture({operation:r.operation,threadId:r.threadId,text:r.text});result={submitted:true};}
   else {socket.end(JSON.stringify({ok:false,error:'unexpected fixture operation'})+'\n');return;}
   socket.end(JSON.stringify({ok:true,result})+'\n');
  });
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(control,resolve);});
 fs.writeFileSync(path.join(connections,'0123456789abcdef.runtime.json'),JSON.stringify({pid:process.pid,control,keyPath}));
 stop=()=>server.close();
}
process.stdout.write('READY\n');
process.stdin.resume();process.stdin.on('end',()=>{stop();process.exit(0);});
