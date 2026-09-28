import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';

// Courts for removing offline Session Link connections. The CLI runs as a real
// child against a temp state folder; no live connection or bridge is touched.
const BS=String.fromCharCode(92),NL=String.fromCharCode(10);
const pipe=name=>BS+BS+'.'+BS+'pipe'+BS+'LOCAL'+BS+name+'-'+crypto.randomUUID();
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-forget-'));
const state=path.join(home,'state'),dir=path.join(state,'connections');
fs.mkdirSync(dir,{recursive:true});
const lib=path.join(import.meta.dirname,'..','nodelang','session_link');
test.after(()=>fs.rmSync(home,{recursive:true,force:true}));
const env={...process.env,HOME:home,SESSION_LINK_STATE_DIR:state};
delete env.CODEX_APP_TOOLS_PIPE_PATH;delete env.CODEX_THREAD_ID;
const cli=(...args)=>new Promise(resolve=>{const child=spawn(process.execPath,[path.join(lib,'bridge.mjs'),...args],{env,windowsHide:true,stdio:['ignore','pipe','pipe']});
 let out='',err='';child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');child.stdout.on('data',c=>out+=c);child.stderr.on('data',c=>err+=c);
 child.on('close',code=>resolve({code,out,err}));});
// A pid that belonged to a process that has already exited.
const deadPid=await new Promise(resolve=>{const c=spawn(process.execPath,['-e',''],{windowsHide:true});c.on('exit',()=>resolve(c.pid));});
const newId=()=>crypto.randomBytes(8).toString('hex');
const files=id=>fs.readdirSync(dir).filter(f=>f.startsWith(id+'.')).sort();
function offlineConnection(id=newId()){
 fs.writeFileSync(path.join(dir,id+'.binding.json'),JSON.stringify({id,claude:{id:'c',app:'claude'},codex:{id:'x'},permissionMode:'prompting'}));
 fs.writeFileSync(path.join(dir,id+'.runtime.json'),JSON.stringify({id,pid:deadPid,control:pipe('sl-forget-dead'),keyPath:path.join(home,'none.key')}));
 fs.writeFileSync(path.join(dir,id+'.events.jsonl'),'{}'+NL);
 fs.writeFileSync(path.join(dir,id+'.stderr.log'),'');
 return id;
}
const token=crypto.randomBytes(16).toString('hex'),keyPath=path.join(home,'live.key');fs.writeFileSync(keyPath,JSON.stringify({peerToken:token}));
async function liveConnection(){
 const id=newId(),control=pipe('sl-forget-live');
 const server=net.createServer(sock=>{let d='';sock.setEncoding('utf8');sock.on('error',()=>{});sock.on('data',c=>{d+=c;if(!d.includes(NL))return;
  const r=JSON.parse(d.slice(0,d.indexOf(NL)));sock.end(JSON.stringify(r.token===token&&r.operation==='status'?{ok:true,result:{id,pid:process.pid,peer:'codex-live',permissionMode:'prompting'}}:{ok:false,error:'refused'})+NL);});});
 await new Promise(resolve=>server.listen(control,resolve));
 fs.writeFileSync(path.join(dir,id+'.binding.json'),JSON.stringify({id,permissionMode:'prompting'}));
 fs.writeFileSync(path.join(dir,id+'.runtime.json'),JSON.stringify({id,pid:process.pid,control,keyPath}));
 return {id,close:()=>new Promise(done=>server.close(done))};
}

test('F1 forget removes an offline connection records and nothing else',async()=>{
 const gone=offlineConnection(),kept=offlineConnection();
 const r=await cli('forget',gone);
 assert.equal(r.code,0,r.err);
 assert.deepEqual(files(gone),[]);
 assert.equal(files(kept).length,4);
 assert.deepEqual(JSON.parse(r.out).removed.sort(),[gone+'.binding.json',gone+'.events.jsonl',gone+'.runtime.json',gone+'.stderr.log']);
});

test('F2 disconnect of an offline connection removes it locally without a bridge',async()=>{
 const id=offlineConnection();
 const r=await cli('disconnect',id);
 assert.equal(r.code,0,r.err);
 assert.deepEqual(files(id),[]);
 assert.equal(JSON.parse(r.out).offline,true);
});

test('F3 forget refuses a live connection and points to disconnect; nothing removed',async()=>{
 const live=await liveConnection();
 try{
  const before=files(live.id);
  const r=await cli('forget',live.id);
  assert.equal(r.code,1);
  assert.match(r.err,new RegExp('is live .*disconnect '+live.id));
  assert.deepEqual(files(live.id),before);
 }finally{await live.close();}
});

test('F4 forget refuses while a resume of the connection is running',async()=>{
 const id=offlineConnection();
 fs.writeFileSync(path.join(dir,id+'.resume.lock'),JSON.stringify({pid:process.pid,id,spawned:false}));
 const r=await cli('forget',id);
 assert.equal(r.code,1);assert.match(r.err,/is live/);
 assert.equal(files(id).length,5);
});

test('F5 forget refuses a malformed or unknown id',async()=>{
 for(const bad of ['../../etc','0123456789abcdef']){const r=await cli('forget',bad);assert.equal(r.code,1);assert.match(r.err,/nothing removed/);}
});

test('F6 status summarises offline connections in plain words and still reports live ones',async()=>{
 for(const f of fs.readdirSync(dir))fs.rmSync(path.join(dir,f),{force:true});
 const a=offlineConnection(),b=offlineConnection(),live=await liveConnection();
 try{
  const r=await cli('status');
  assert.equal(r.code,0,r.err);
  const rows=JSON.parse(r.out);
  assert.ok(rows.some(x=>x.id===live.id&&x.peer==='codex-live'));
  const summary=rows.find(x=>x.offline!==undefined);
  assert.equal(summary?.note,'2 old connections are offline. Remove them with forget.');
  assert.deepEqual(summary.ids.sort(),[a,b].sort());
  assert.ok(!r.out.includes('Session Link offline'));
 }finally{await live.close();}
});