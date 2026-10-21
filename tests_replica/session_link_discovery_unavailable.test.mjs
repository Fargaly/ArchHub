import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

// Courts for connect() when discovery for an app FAILED versus when it was a
// complete empty listing. Isolated: temp HOME and SESSION_LINK_STATE_DIR, no
// Codex app environment, observed catalogs only. No live app, session, bridge,
// binding or spawn is touched.
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-discovery-'));
process.env.HOME=home;
process.env.SESSION_LINK_STATE_DIR=path.join(home,'state');
const connections=path.join(process.env.SESSION_LINK_STATE_DIR,'connections');
fs.mkdirSync(connections,{recursive:true});
for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','SESSION_LINK_PRODUCT_WORKER'])delete process.env[k];
const lib=path.join(import.meta.dirname,'..','nodelang','session_link');
const {connect}=await import(pathToFileURL(path.join(lib,'bridge.mjs')).href);
test.after(()=>fs.rmSync(home,{recursive:true,force:true}));

const CLAUDE='11111111-2222-4333-8444-555555555555';
const CODEX='01a0f223-0000-7000-8000-000000000001';
const claudeRow={id:CLAUDE,title:'Builder',app:'claude'};
const codexRow={id:CODEX,title:'Mishmish',app:'codex',hostId:'host-a'};
const base=over=>({claude:[claudeRow],codex:[],opencode:[],antigravity:[],'antigravity-ide':[],adapterStatus:{},complete_apps:[],...over});
const files=()=>fs.readdirSync(connections);
const run=async catalog=>{const spawns=[];let err;try{await connect({app:'claude',claude:CLAUDE,codex:CODEX},{observedCatalog:catalog,onSpawn:p=>spawns.push(p)});}catch(e){err=e;}return {err,spawns};};

test('failed Codex listing is refused as unavailable, never "found 0"',async()=>{
  const {err,spawns}=await run(base({adapterStatus:{codex:{status:'unavailable',reason:'Codex app tools could not list tasks: timeout'}}}));
  assert.equal(err?.code,'SESSION_LINK_DISCOVERY_UNAVAILABLE');
  assert.match(err.message,/Codex discovery unavailable for this host: Codex app tools could not list tasks: timeout/);
  assert.doesNotMatch(err.message,/found 0/);
  assert.deepEqual(spawns,[]);
  assert.deepEqual(files(),[]);
});

test('failed remote-app listing is refused before any Codex selection',async()=>{
  const {err,spawns}=await run(base({claude:[],codex:[codexRow],adapterStatus:{claude:{status:'unavailable',reason:'registry unreadable'}}}));
  assert.equal(err?.code,'SESSION_LINK_DISCOVERY_UNAVAILABLE');
  assert.match(err.message,/^claude discovery unavailable for this host: registry unreadable/);
  assert.deepEqual(spawns,[]);
  assert.deepEqual(files(),[]);
});

test('a genuinely complete empty listing still reports found 0',async()=>{
  const {err,spawns}=await run(base({adapterStatus:{codex:{status:'ok'}}}));
  assert.equal(err?.code,undefined);
  assert.match(err.message,/^Codex: expected exactly one session for .*found 0;/);
  assert.deepEqual(spawns,[]);
  assert.deepEqual(files(),[]);
});

test('a healthy exact session is selected and connect proceeds past selection',async()=>{
  // With no Codex app environment and no live bridge, connect stops at the
  // transport requirement: proof that both selections succeeded, with nothing
  // registered or spawned.
  const {err,spawns}=await run(base({codex:[codexRow],adapterStatus:{codex:{status:'ok'}}}));
  assert.match(err.message,/^Connect from a Codex task once to establish the local app transport/);
  assert.deepEqual(spawns,[]);
  assert.deepEqual(files(),[]);
});

test('reason text is sanitized of app pipe paths',async()=>{
  const {err}=await run(base({adapterStatus:{codex:{status:'unavailable',reason:'failed at \\\\.\\pipe\\codex-secret-123 now'}}}));
  assert.equal(err?.code,'SESSION_LINK_DISCOVERY_UNAVAILABLE');
  assert.doesNotMatch(err.message,/codex-secret-123/);
  assert.match(err.message,/\[app pipe\]/);
});
