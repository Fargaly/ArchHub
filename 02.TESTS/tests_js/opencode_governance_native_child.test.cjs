const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..', '..');
const moduleUrl = pathToFileURL(path.join(root, '01.APP/nodelang', 'workshop', 'opencode-governance.mjs')).href;

const gateSource = `
const fs=require('node:fs');
const readline=require('node:readline');
const mode=process.argv[2];
const counter=process.argv[3];
const actor='app:agent-session:runtime:'+'a'.repeat(32);
if(process.argv.includes('--reconcile')){
 process.stdout.write(JSON.stringify({kind:'reconciled',session_id:process.env.OPENCODE_SESSION_ID,
  agent_session:process.env.ARCHHUB_EXPECTED_AGENT_SESSION,outcome:'unknown',reason:'owner binding still retained'})+'\\n');
 process.exit(0);
}
if(counter)fs.writeFileSync(counter,String((fs.existsSync(counter)?Number(fs.readFileSync(counter,'utf8')):0)+1));
let calls=0;
readline.createInterface({input:process.stdin}).on('line',line=>{
 const frame=JSON.parse(line);
 if(frame.command==='release')process.exit(2);
 const event=frame.event;
 const base={request_id:frame.request_id,session_id:event.session_id,tool_use_id:event.tool_use_id};
 if(mode==='close-read'||mode==='uncertain-write')process.exit(2);
 if(mode==='owner-bound-read-close'){
  calls++;
  if(calls===1){
   process.stdout.write(JSON.stringify({...base,decision:'allow',agent_session:actor,continued:false})+'\\n');
   return;
  }
  process.exit(2);
 }
 const command=event.tool_input&&event.tool_input.command||'';
 const filePath=event.tool_input&&(event.tool_input.file_path||event.tool_input.filePath)||'';
 const historyRewrite=command.includes('push '+'--force');
 const hard=historyRewrite||filePath.includes('60.PERSONAL');
 const reply={...base,admitted:false,never_bound:true,decision:hard?'deny':'allow'};
 if(hard){reply.error='hard harm';reply.reason=historyRewrite?'git_history_rewrite':'public_session_private_area';}
 else reply.note='owner path unavailable; allowed by shared hard-harm scan';
 process.stdout.write(JSON.stringify(reply)+'\\n');
 setTimeout(()=>process.exit(2),60);
});
`;

const settle = () => new Promise(resolve => setTimeout(resolve, 120));

async function makeGate(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'archhub-oc-gate-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const gate = path.join(dir, 'gate.cjs');
  fs.writeFileSync(gate, gateSource, 'utf8');
  return { dir, gate };
}

test('no owner binding allows the first read and a normal write without quarantine', async (t) => {
  const { gate } = await makeGate(t);
  const { createOpenCodeGovernance } = await import(moduleUrl);
  const hooks = await createOpenCodeGovernance({ gateCommand: process.execPath, gateArgs: [gate, 'owner-absent'] })({
    directory: root,
    client: {},
  });

  const read = { sessionID: 'ses_noowner', callID: 'read-1', tool: 'read' };
  await hooks['tool.execute.before'](read, { args: { filePath: path.join(root, 'BRIEF-GOV-OPENCODE.md') } });
  await hooks['tool.execute.after']({ ...read, args: { filePath: path.join(root, 'BRIEF-GOV-OPENCODE.md') } }, {});
  await settle();

  const writeArgs = { filePath: path.join(os.tmpdir(), 'archhub-normal-write.txt'), content: 'ok' };
  const write = { sessionID: 'ses_noowner', callID: 'write-1', tool: 'write' };
  await hooks['tool.execute.before'](write, { args: writeArgs });
  await hooks['tool.execute.after']({ ...write, args: writeArgs }, {});
  await settle();

  const next = { sessionID: 'ses_noowner', callID: 'read-2', tool: 'read' };
  await hooks['tool.execute.before'](next, { args: { filePath: path.join(root, 'SPEC.md') } });
  await hooks['tool.execute.after']({ ...next, args: { filePath: path.join(root, 'SPEC.md') } }, {});
  await settle();
  await hooks.dispose();
});

test('a gate that crashes before a read decision fails that call, never quarantines the session', async (t) => {
  const { dir, gate } = await makeGate(t);
  const counter = path.join(dir, 'spawns.txt');
  const { createNativeGateRunner } = await import(moduleUrl);
  const run = createNativeGateRunner(process.execPath, [gate, 'close-read', counter]);
  const call = id => run({ session_id: 'ses_readclose', cwd: root, tool_use_id: id, vendor: 'opencode',
    hook_event_name: 'PreToolUse', tool_name: 'read', tool_input: { file_path: 'brief' } });

  await assert.rejects(call('read-1'), /native gate exited \(code 2\) before admitting this call.*tool not delivered/);
  await settle();
  await assert.rejects(async () => call('read-2'), /native gate exited \(code 2\) before admitting this call.*tool not delivered/);   // a fresh gate, not a quarantine
  assert.equal(fs.readFileSync(counter, 'utf8'), '2', 'each call had its own gate; read-1 was not replayed');
});

test('an owner-bound gate that crashes fails only the call in flight', async (t) => {
  const { gate } = await makeGate(t);
  const { createNativeGateRunner } = await import(moduleUrl);
  const run = createNativeGateRunner(process.execPath, [gate, 'owner-bound-read-close']);
  const event = id => ({ session_id: 'ses_boundread', cwd: root, tool_use_id: id, vendor: 'opencode',
    hook_event_name: 'PreToolUse', tool_name: 'read', tool_input: { file_path: 'brief' } });

  assert.equal((await run(event('read-1'))).allow, true);
  await assert.rejects(run(event('read-2')), /native gate exited \(code 2\) before admitting this call.*tool not delivered/);
  await settle();
  // The next call reaches a fresh gate (never "quarantined"); that gate must still prove it
  // continues the same owner binding, which this fixture's fresh child does not.
  await assert.rejects(run(event('read-3')), error => !/quarantined/.test(error.message) && /identity changed/.test(error.message));
});

test('a gate that crashes mid write admission fails that write and never replays it', async (t) => {
  const { dir, gate } = await makeGate(t);
  const counter = path.join(dir, 'spawns.txt');
  const { createNativeGateRunner } = await import(moduleUrl);
  const run = createNativeGateRunner(process.execPath, [gate, 'uncertain-write', counter]);
  const event = id => ({ session_id: 'ses_uncertainwrite', cwd: root, tool_use_id: id, vendor: 'opencode',
    hook_event_name: 'PreToolUse', tool_name: 'Write', tool_input: { file_path: 'x', content: 'y' } });

  await assert.rejects(run(event('write-1')), /native gate exited \(code 2\) before admitting this call.*tool not delivered/);
  await settle();
  await assert.rejects(async () => run(event('write-2')), /native gate exited \(code 2\) before admitting this call.*tool not delivered/);
  assert.equal(fs.readFileSync(counter, 'utf8'), '2', 'write-1 was never replayed; write-2 had its own gate');
});

test('hard harm is refused even when no owner binding exists', async (t) => {
  const { gate } = await makeGate(t);
  const { createOpenCodeGovernance } = await import(moduleUrl);
  const hooks = await createOpenCodeGovernance({ gateCommand: process.execPath, gateArgs: [gate, 'owner-absent'] })({
    directory: root,
    client: {},
  });

  const input = { sessionID: 'ses_hardharm', callID: 'hard-1', tool: 'bash' };
  const dangerous = ['git', 'push', '--force', 'origin', 'main'].join(' ');
  await assert.rejects(
    hooks['tool.execute.before'](input, { args: { command: dangerous } }),
    /prewrite admission denied: native owner could not decide: hard harm: git_history_rewrite/,
  );
  await settle();
  const next = { sessionID: 'ses_hardharm', callID: 'safe-1', tool: 'bash' };
  await hooks['tool.execute.before'](next, { args: { command: 'git status' } });
  await hooks['tool.execute.after']({ ...next, args: { command: 'git status' } }, {});
  await settle();
  await hooks.dispose();
});

test('a private-area read is refused by the confirmed owner-absent decision', async (t) => {
  const { gate } = await makeGate(t);
  const { createOpenCodeGovernance } = await import(moduleUrl);
  const hooks = await createOpenCodeGovernance({ gateCommand: process.execPath, gateArgs: [gate, 'owner-absent'] })({
    directory: root,
    client: {},
  });

  const input = { sessionID: 'ses_privateread', callID: 'private-1', tool: 'read' };
  await assert.rejects(
    hooks['tool.execute.before'](input, { args: { filePath: path.join(root, '60.PERSONAL', 'secret.txt') } }),
    /prewrite admission denied: native owner could not decide: hard harm: public_session_private_area/,
  );
  await hooks.dispose();
});

test('confirmed owner-absent allow and deny are decided by the matching hard-harm frame', async (t) => {
  const { gate } = await makeGate(t);
  const { createNativeGateRunner } = await import(moduleUrl);
  const run = createNativeGateRunner(process.execPath, [gate, 'owner-absent']);
  const read = { session_id: 'ses_confirmed', cwd: root, tool_use_id: 'read-ok', vendor: 'opencode',
    hook_event_name: 'PreToolUse', tool_name: 'read', tool_input: { file_path: 'README.md' } };
  const deny = { ...read, tool_use_id: 'read-deny', tool_input: { file_path: path.join(root, '60.PERSONAL', 'x.txt') } };

  assert.equal((await run(read)).allow, true);
  await settle();
  const refused = await run(deny);
  assert.equal(refused.allow, false);
  assert.match(refused.reason, /public_session_private_area/);
});

test('a crashed gate call is not delivered and the session continues', async (t) => {
  const { gate } = await makeGate(t);
  const { createNativeGateRunner } = await import(moduleUrl);
  const run = createNativeGateRunner(process.execPath, [gate, 'owner-bound-read-close']);
  const event = id => ({ session_id: 'ses_unknown', cwd: root, tool_use_id: id, vendor: 'opencode',
    hook_event_name: 'PreToolUse', tool_name: 'read', tool_input: { file_path: 'brief' } });

  assert.equal((await run(event('read-1'))).allow, true);
  await assert.rejects(run(event('read-2')), /tool not delivered/);
  await settle();
  await assert.rejects(run(event('read-3')), error => !/quarantined/.test(error.message));
});
