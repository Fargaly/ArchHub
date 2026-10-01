import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';

const root=path.join(import.meta.dirname,'..');
const sourceDir=path.join(root,'nodelang','session_link');

function writeFixtureWorker(dir,mode='normal'){
 fs.mkdirSync(dir,{recursive:true});
 fs.copyFileSync(path.join(sourceDir,'worker.mjs'),path.join(dir,'worker.mjs'));
 fs.writeFileSync(path.join(dir,'bridge.mjs'),`
export async function catalog({onProgress}={}){
 if(onProgress)onProgress({claude:[],codex:[],opencode:[],antigravity:[],'antigravity-ide':[],adapterStatus:{},complete_apps:['claude']});
 setInterval(()=>{},1000);
 return {claude:[{id:'fixture',title:'Fixture',pid:123}],codex:[],opencode:[],antigravity:[],'antigravity-ide':[],adapterStatus:{},complete_apps:['claude']};
}
`);
 fs.writeFileSync(path.join(dir,'ask.mjs'),`
export async function ask(_app,_id,_text,_mode,{onDispatch}={}){
 setInterval(()=>{},1000);
 if(onDispatch)onDispatch();
 if(${JSON.stringify(mode)}==='held')return {status:'held',delivery_status:'held',delivery_reason:'waiting'};
 if(${JSON.stringify(mode)}==='throw')throw new Error('timed out');
 return {id:'reply',text:'done'};
}
`);
 fs.writeFileSync(path.join(dir,'native.mjs'),`
export function setAttachment(){}
export async function attachmentCall(){
 setInterval(()=>{},1000);
 return {revoked:true};
}
`);
}

function runWorker(workerDir,payload,timeoutMs=3000){
 return new Promise(resolve=>{
  const started=Date.now();
  const child=spawn(process.execPath,[path.join(workerDir,'worker.mjs')],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  let out='',err='',done=false;
  child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
  child.stdout.on('data',c=>out+=c);child.stderr.on('data',c=>err+=c);
  const timer=setTimeout(()=>{if(done)return;done=true;child.kill();resolve({code:'timeout',out,err,ms:Date.now()-started});},timeoutMs);
  child.on('close',code=>{if(done)return;done=true;clearTimeout(timer);resolve({code,out,err,ms:Date.now()-started});});
  child.stdin.end(JSON.stringify(payload)+'\n');
 });
}

test('Session Link worker exits after a terminal discovery result despite lingering handles',async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-worker-exit-'));
 try{
  const workerDir=path.join(home,'session_link');
  writeFixtureWorker(workerDir);
  const r=await runWorker(workerDir,{operation:'discover'});
  assert.notEqual(r.code,'timeout','worker stayed alive after terminal result: '+r.out+r.err);
  assert.equal(r.code,0,r.err);
  const result=r.out.trim().split('\n').map(line=>JSON.parse(line)).find(row=>row.event==='result');
  assert.equal(result.status,'ok');
  assert.equal(result.recipients[0].id,'fixture');
 }finally{
  fs.rmSync(home,{recursive:true,force:true});
 }
});

test('Session Link worker exits after request replied and preserves dispatch event order',async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-worker-replied-'));
 try{
  const workerDir=path.join(home,'session_link');
  writeFixtureWorker(workerDir);
  const recipient={app:'claude',id:'fixture'};
  const r=await runWorker(workerDir,{operation:'request',recipient,text:'hello'});
  assert.notEqual(r.code,'timeout','worker stayed alive after replied: '+r.out+r.err);
  assert.equal(r.code,0,r.err);
  const frames=r.out.trim().split('\n').map(line=>JSON.parse(line));
  assert.equal(frames[0].event,'dispatch_attempted');
  assert.equal(frames[1].status,'replied');
  assert.equal(frames[1].dispatch_attempted,true);
 }finally{fs.rmSync(home,{recursive:true,force:true});}
});

test('Session Link worker exits after request held',async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-worker-held-'));
 try{
  const workerDir=path.join(home,'session_link');
  writeFixtureWorker(workerDir,'held');
  const r=await runWorker(workerDir,{operation:'request',recipient:{app:'claude',id:'fixture'},text:'hello'});
  assert.notEqual(r.code,'timeout','worker stayed alive after held: '+r.out+r.err);
  const result=r.out.trim().split('\n').map(line=>JSON.parse(line)).find(row=>row.event==='result');
  assert.equal(result.status,'held');
  assert.equal(result.dispatch_attempted,true);
 }finally{fs.rmSync(home,{recursive:true,force:true});}
});

test('Session Link worker exits after detach despite lingering handles',async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-worker-detach-'));
 try{
  const workerDir=path.join(home,'session_link');
  writeFixtureWorker(workerDir);
  const r=await runWorker(workerDir,{operation:'detach'});
  assert.notEqual(r.code,'timeout','worker stayed alive after detach: '+r.out+r.err);
  const result=r.out.trim().split('\n').map(line=>JSON.parse(line)).find(row=>row.event==='result');
  assert.equal(result.status,'ok');
  assert.equal(result.revoked,true);
 }finally{fs.rmSync(home,{recursive:true,force:true});}
});

test('Session Link worker exits after invalid json, input limit, and catch path',async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-worker-errors-'));
 try{
  const workerDir=path.join(home,'session_link');
  writeFixtureWorker(workerDir,'throw');
  const invalid=await new Promise(resolve=>{
   const child=spawn(process.execPath,[path.join(workerDir,'worker.mjs')],{windowsHide:true,stdio:['pipe','pipe','pipe']});
   let out='';child.stdout.setEncoding('utf8');child.stdout.on('data',c=>out+=c);
   child.on('close',code=>resolve({code,out}));
   child.stdin.end('{\n');
  });
  assert.equal(JSON.parse(invalid.out).reason,'invalid_json');
  const limited=await runWorker(workerDir,{text:'x'.repeat(140000)});
  assert.equal(JSON.parse(limited.out).reason,'input_limit');
  const caught=await runWorker(workerDir,{operation:'request',recipient:{app:'claude',id:'fixture'},text:'hello'});
  const result=caught.out.trim().split('\n').map(line=>JSON.parse(line)).find(row=>row.event==='result');
  assert.equal(result.status,'uncertain');
  assert.equal(result.dispatch_attempted,true);
 }finally{fs.rmSync(home,{recursive:true,force:true});}
});
