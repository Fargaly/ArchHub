import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';

// Courts for the Session Link --stdin message input. Isolated: temp HOME and
// state, private LOCAL pipes, a mock bridge/request endpoint in this process.
// The CLI runs as a real child with stdin; nothing live is touched. Payloads
// carry shell syntax and a sentinel path: nothing may execute them.
const BS=String.fromCharCode(92),NL=String.fromCharCode(10),CR=String.fromCharCode(13);
const pipe=name=>BS+BS+'.'+BS+'pipe'+BS+'LOCAL'+BS+name+'-'+crypto.randomUUID();
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-stdin-'));
const state=path.join(home,'state'),connections=path.join(state,'connections'),requests=path.join(state,'requests');
fs.mkdirSync(connections,{recursive:true});fs.mkdirSync(requests,{recursive:true});
const lib=path.join(import.meta.dirname,'..','nodelang','session_link');
test.after(()=>fs.rmSync(home,{recursive:true,force:true}));
const sentinel=name=>path.join(home,'EXECUTED-'+name);
const payload=tag=>'taskkill /IM python.exe'+CR+NL+'$(New-Item -ItemType File -Path '+JSON.stringify(sentinel(tag+'-ps'))+')'+NL+
 '$(node -e "require(\'fs\').writeFileSync('+JSON.stringify(sentinel(tag+'-node'))+',\'x\')")'+NL+
 '`touch '+sentinel(tag+'-bt')+'` ; & calc ; | whoami '+String.fromCharCode(233,252,0x4e2d)+NL;
const noSentinels=tag=>{for(const s of ['-ps','-node','-bt'])assert.equal(fs.existsSync(sentinel(tag+s)),false,'executed: '+tag+s);};

// Mock of the live bridge control endpoint (same runtime/key/newline-JSON
// contract that bridge.mjs rpc() uses) and of an ask request endpoint.
const token=crypto.randomBytes(16).toString('hex'),keyPath=path.join(home,'peer.key');
fs.writeFileSync(keyPath,JSON.stringify({peerToken:token}));
const received=[];
function endpoint(control,check){
 const server=net.createServer(sock=>{let d='';sock.setEncoding('utf8');sock.on('error',()=>{});sock.on('data',c=>{d+=c;if(!d.includes(NL))return;
  const r=JSON.parse(d.slice(0,d.indexOf(NL)));
  if(!check(r)){sock.end(JSON.stringify({ok:false,error:'Unauthenticated request'})+NL);return;}
  received.push(r);sock.end(JSON.stringify({ok:true,result:{delivered:true}})+NL);});});
 return new Promise(resolve=>server.listen(control,()=>resolve(server)));
}
const CONNECTION='5715715715715715',CODEX='01a0beef-0000-7000-8000-000000000005',REQUEST=crypto.randomUUID();
const bridgeControl=pipe('sl-stdin-bridge'),requestControl=pipe('sl-stdin-request');
const servers=[await endpoint(bridgeControl,r=>r.token===token),await endpoint(requestControl,r=>r.token===token&&r.session===CODEX)];
fs.writeFileSync(path.join(connections,CONNECTION+'.runtime.json'),JSON.stringify({id:CONNECTION,pid:process.pid,control:bridgeControl,keyPath}));
fs.writeFileSync(path.join(requests,REQUEST+'.json'),JSON.stringify({control:requestControl,keyPath,target:CODEX,pid:process.pid}));
test.after(()=>{for(const s of servers)s.close();});

const env={...process.env,HOME:home,SESSION_LINK_STATE_DIR:state,CODEX_THREAD_ID:CODEX};
delete env.CODEX_APP_TOOLS_PIPE_PATH;
function run(file,args,input,{command=process.execPath,extraEnv={}}={}){
 return new Promise(resolve=>{
  const child=spawn(command,file?[path.join(lib,file),...args]:args,{env:{...env,...extraEnv},windowsHide:true,stdio:['pipe','pipe','pipe']});
  let out='',err='';child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
  child.stdout.on('data',c=>out+=c);child.stderr.on('data',c=>err+=c);
  child.on('close',code=>resolve({code,out,err}));
  if(input!==undefined)child.stdin.end(Buffer.from(input,'utf8'));else child.stdin.end();
 });
}
const verbs=[['bridge.mjs',['send',CONNECTION]],['bridge.mjs',['reply',CONNECTION]],['ask.mjs',['answer',REQUEST]]];

for(const [file,args] of verbs)test('S1 '+args[0]+' --stdin delivers the exact text and executes nothing',async()=>{
 received.length=0;const text=payload(args[0]);
 const r=await run(file,[...args,'--stdin'],text);
 assert.equal(r.code,0,r.err);
 assert.equal(received.length,1);
 assert.equal(Buffer.compare(Buffer.from(received[0].text,'utf8'),Buffer.from(text,'utf8')),0);
 noSentinels(args[0]);
});

for(const [file,args] of verbs)test('S2 '+args[0]+' refuses --file together with --stdin',async()=>{
 received.length=0;const f=path.join(home,'m.txt');fs.writeFileSync(f,'from file');
 const r=await run(file,[...args,'--file',f,'--stdin'],'from stdin');
 assert.equal(r.code,1);assert.match(r.err,/--file or --stdin, not both/);assert.equal(received.length,0);
});

for(const [file,args] of verbs)test('S3 '+args[0]+' refuses an empty stdin and an oversize stdin',async()=>{
 received.length=0;
 for(const empty of ['','   '+NL+CR+NL]){const r=await run(file,[...args,'--stdin'],empty);assert.equal(r.code,1);assert.match(r.err,/Empty stdin message/);}
 const big=await run(file,[...args,'--stdin'],'x'.repeat(32001));
 assert.equal(big.code,1);assert.match(big.err,/1-32000 characters/);
 assert.equal(received.length,0);
});

// End to end through the wrapper, in the caller's real form:
//   @'...'@ | & session-link.ps1 send CONNECTION --stdin
// for Windows PowerShell 5.1 and PowerShell 7. A single-quoted here-string is
// one pipeline item; its text must reach the bridge byte-identical.
for(const shell of ['powershell.exe','pwsh.exe'])test('S4 '+shell+' here-string piped into session-link.ps1 send --stdin arrives byte-identical',async()=>{
 received.length=0;const tag='ps-'+shell.split('.')[0];
 const body=payload(tag).split(CR+NL).join(NL).replace(/\n$/,'');
 const driver=path.join(home,tag+'.ps1');
 // Windows PowerShell 5.1 reads a BOM-less script as ANSI; a real script file carries the UTF-8 BOM.
 fs.writeFileSync(driver,String.fromCharCode(0xfeff)+"@'"+NL+body+NL+"'@ | & "+"'"+path.join(lib,'session-link.ps1').replaceAll("'","''")+"' --state-dir '"+state.replaceAll("'","''")+"' send "+CONNECTION+" --stdin"+NL+'exit $LASTEXITCODE'+NL,'utf8');
 const r=await run(null,['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',driver],undefined,{command:shell,extraEnv:{SESSION_LINK_NODE:process.execPath}});
 assert.equal(r.code,0,r.err+r.out);
 assert.equal(received.length,1);
 assert.equal(Buffer.compare(Buffer.from(received[0].text,'utf8'),Buffer.from(body,'utf8')),0);
 noSentinels(tag);
});
// Without --stdin the wrapper must never read pipeline input or stdin: stray
// input is ignored and an open stdin that never closes cannot block a command.
function runShell(shell,args,{input,keepOpen=false,timeoutMs=5000}={}){
 return new Promise(resolve=>{
  const started=Date.now();
  const child=spawn(shell,['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',path.join(lib,'session-link.ps1'),'--state-dir',state,...args],
   {env:{...env,SESSION_LINK_NODE:process.execPath},windowsHide:true,stdio:['pipe','pipe','pipe']});
  let out='',err='',done=false;child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
  child.stdout.on('data',c=>out+=c);child.stderr.on('data',c=>err+=c);
  const timer=setTimeout(()=>{if(!done){done=true;child.kill();resolve({code:'timeout',out,err,ms:Date.now()-started});}},timeoutMs);
  child.on('close',code=>{if(done)return;done=true;clearTimeout(timer);child.stdin.destroy();resolve({code,out,err,ms:Date.now()-started});});
  if(input!==undefined)child.stdin.write(input);
  if(!keepOpen)child.stdin.end();
 });
}
for(const shell of ['powershell.exe','pwsh.exe']){
 test('S5 '+shell+' stray stdin with status (no --stdin) returns 0',async()=>{
  const r=await runShell(shell,['status'],{input:'stray'+NL});
  assert.equal(r.code,0,r.err+r.out);
 });
 test('S6 '+shell+' open never-closed stdin without --stdin finishes within 5s',async()=>{
  const r=await runShell(shell,['status'],{keepOpen:true});
  assert.notEqual(r.code,'timeout','hung for '+r.ms+'ms');
  assert.equal(r.code,0,r.err+r.out);
 });
}

for(const [file,args] of verbs)test('S7 '+args[0]+' with neither --file nor --stdin is refused and reads no file',async()=>{
 received.length=0;
 const cwd=fs.mkdtempSync(path.join(home,'cwd-'));
 for(const name of [args[0],args[1]])fs.writeFileSync(path.join(cwd,name),'LEAKED FILE CONTENT');
 const r=await new Promise(resolve=>{const child=spawn(process.execPath,[path.join(lib,file),...args],{cwd,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
  let err='';child.stderr.setEncoding('utf8');child.stderr.on('data',c=>err+=c);child.on('close',code=>resolve({code,err}));child.stdin.end();});
 assert.equal(r.code,1);
 assert.match(r.err,/Message input required: --file UTF8_FILE or --stdin/);
 assert.equal(received.length,0);
});
for(const shell of ['powershell.exe','pwsh.exe'])test('S8 '+shell+' -File with raw redirected stdin and --stdin delivers the bytes unchanged',async()=>{
 received.length=0;const tag='raw-'+shell.split('.')[0];const text=payload(tag);
 const r=await runShell(shell,['send',CONNECTION,'--stdin'],{input:Buffer.from(text,'utf8')});
 assert.equal(r.code,0,r.err+r.out);
 assert.equal(received.length,1);
 assert.equal(Buffer.compare(Buffer.from(received[0].text,'utf8'),Buffer.from(text,'utf8')),0);
 noSentinels(tag);
});
test('S9 oversize stdin is refused before the writer closes it',async()=>{
 received.length=0;
 const r=await new Promise(resolve=>{
  const child=spawn(process.execPath,[path.join(lib,'bridge.mjs'),'send',CONNECTION,'--stdin'],{env,windowsHide:true,stdio:['pipe','pipe','pipe']});
  let err='',done=false;child.stderr.setEncoding('utf8');child.stderr.on('data',c=>err+=c);
  const timer=setTimeout(()=>{if(!done){done=true;child.kill();resolve({code:'timeout',err});}},5000);
  child.on('close',code=>{if(done)return;done=true;clearTimeout(timer);child.stdin.destroy();resolve({code,err});});
  child.stdin.on('error',()=>{});
  child.stdin.write('x'.repeat(40000));
 });
 assert.notEqual(r.code,'timeout','waited for stdin to close');
 assert.equal(r.code,1);assert.match(r.err,/1-32000 characters/);assert.equal(received.length,0);
});
test('S10 a stdin that stays open under the limit is refused after the idle period',async()=>{
 received.length=0;
 const r=await new Promise(resolve=>{
  const child=spawn(process.execPath,[path.join(lib,'bridge.mjs'),'send',CONNECTION,'--stdin'],{env:{...env,SESSION_LINK_STDIN_IDLE_MS:'1500'},windowsHide:true,stdio:['pipe','pipe','pipe']});
  let err='',done=false;child.stderr.setEncoding('utf8');child.stderr.on('data',c=>err+=c);
  const timer=setTimeout(()=>{if(!done){done=true;child.kill();resolve({code:'timeout',err});}},6000);
  child.on('close',code=>{if(done)return;done=true;clearTimeout(timer);child.stdin.destroy();resolve({code,err});});
  child.stdin.on('error',()=>{});
  child.stdin.write('partial message, writer never closes');
 });
 assert.notEqual(r.code,'timeout','waited for stdin to close');
 assert.equal(r.code,1);assert.match(r.err,/No stdin data for 2 seconds and stdin was not closed; not sent/);assert.equal(received.length,0);
});
