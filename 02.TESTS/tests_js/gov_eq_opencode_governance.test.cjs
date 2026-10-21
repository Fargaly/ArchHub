const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..', '..');

test('gov eq unmapped OpenCode tools pass through the shared governance gate', async () => {
  const moduleUrl = pathToFileURL(path.join(root, '01.APP/nodelang', 'session_link', 'opencode-governance.mjs')).href;
  const { createOpenCodeGovernance } = await import(moduleUrl);
  const events = [];
  const hooks = await createOpenCodeGovernance({
    gateRunner: async (event) => {
      events.push(event);
      return { allow: true };
    },
  })({ directory: root, client: {} });

  const input = { sessionID: 'ses_goveq', callID: 'call-1', tool: 'vendor_unmapped_tool' };
  const output = { args: { alpha: 1, nested: { ok: true } } };

  await hooks['tool.execute.before'](input, output);
  await hooks['tool.execute.after']({ ...input, args: output.args }, {});
  await hooks.dispose();

  assert.equal(events[0].hook_event_name, 'PreToolUse');
  assert.equal(events[0].tool_name, 'vendor_unmapped_tool');
  assert.deepEqual(events[0].tool_input, { alpha: 1, nested: { ok: true } });
  assert.equal(events[1].hook_event_name, 'PostToolUse');
});

test('gov eq one unclear shell outcome never refuses every later OpenCode tool', async () => {
  const moduleUrl = pathToFileURL(path.join(root, '01.APP/nodelang', 'session_link', 'opencode-governance.mjs')).href;
  const { createOpenCodeGovernance } = await import(moduleUrl);
  let calls = 0;
  const hooks = await createOpenCodeGovernance({
    gateRunner: async () => {
      calls += 1;
      if (calls === 1) throw new Error('owner frame lost');
      return { allow: true };
    },
  })({ directory: root, client: {} });

  const first = { sessionID: 'ses_goveqshell', callID: 'call-1', tool: 'bash' };
  await assert.rejects(hooks['tool.execute.before'](first, { args: { command: 'git status' } }));
  const second = { sessionID: 'ses_goveqshell', callID: 'call-2', tool: 'bash' };
  await hooks['tool.execute.before'](second, { args: { command: 'git status' } });
  await hooks['tool.execute.after']({ ...second, args: { command: 'git status' } }, {});
  await hooks.dispose();
  assert.equal(calls >= 2, true);
});

test('next OpenCode tool joins the exact in-flight receipt without replay', async () => {
  const { createOpenCodeGovernance } = await import(pathToFileURL(path.join(root, '01.APP/nodelang/session_link/opencode-governance.mjs')).href);
  let settle; const events = [];
  const receipt = new Promise(resolve => { settle = resolve; });
  const hooks = await createOpenCodeGovernance({
    gateRunner: async event => {
      events.push(event);
      if (event.hook_event_name === 'PostToolUse' && event.tool_use_id === 'write-1') return receipt;
      return { allow: true };
    },
  })({ directory: root, client: {} });
  const first = { sessionID: 'ses_receipt', callID: 'write-1', tool: 'write' };
  const firstArgs = { filePath: path.join(root, 'unused.txt'), content: 'fixture' };
  await hooks['tool.execute.before'](first, { args: firstArgs });
  const after = hooks['tool.execute.after']({ ...first, args: firstArgs }, {});
  const second = { sessionID: 'ses_receipt', callID: 'write-2', tool: 'write' };
  const secondArgs = { ...firstArgs, content: 'second' };
  let admitted = false;
  const before = hooks['tool.execute.before'](second, { args: secondArgs }).then(() => { admitted = true; });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(admitted, false);
  assert.equal(events.filter(e => e.hook_event_name === 'PostToolUse').length, 1);
  settle({ allow: true }); await after; await before;
  assert.equal(admitted, true);
  await hooks['tool.execute.after']({ ...second, args: secondArgs }, {});
  await hooks.dispose();
  assert.equal(events.length, 4);
});

test('a denied in-flight receipt retains custody and refuses continuation', async () => {
  const { createOpenCodeGovernance } = await import(pathToFileURL(path.join(root, '01.APP/nodelang/session_link/opencode-governance.mjs')).href);
  let settle; let admissions = 0;
  const receipt = new Promise(resolve => { settle = resolve; });
  const hooks = await createOpenCodeGovernance({
    gateRunner: async event => {
      if (event.hook_event_name === 'PostToolUse') return receipt;
      admissions++; return { allow: true };
    },
  })({ directory: root, client: {} });
  const first = { sessionID: 'ses_deniedreceipt', callID: 'write-1', tool: 'write' }, args = { filePath: path.join(root, 'unused.txt'), content: 'fixture' };
  await hooks['tool.execute.before'](first, { args });
  const after = assert.rejects(hooks['tool.execute.after']({ ...first, args }, {}), /receipt denied/);
  const next = assert.rejects(hooks['tool.execute.before']({ ...first, callID: 'write-2' }, { args }), /receipt denied/);
  settle({ allow: false }); await after; await next;
  assert.equal(admissions, 1);
  await assert.rejects(hooks.dispose(), /receipts remain unresolved/);
});

test('write joins both in-flight receipts after concurrent reads', async () => {
  const { createOpenCodeGovernance } = await import(pathToFileURL(path.join(root, '01.APP/nodelang/session_link/opencode-governance.mjs')).href);
  const resolvers = new Map(), receipts = new Map();
  for (const id of ['read-a', 'read-b']) receipts.set(id, new Promise(resolve => resolvers.set(id, resolve)));
  const hooks = await createOpenCodeGovernance({ gateRunner: async event => event.hook_event_name === 'PostToolUse' && receipts.has(event.tool_use_id) ? receipts.get(event.tool_use_id) : { allow: true } })({ directory: root, client: {} });
  const args = { filePath: path.join(root, 'unused.txt') };
  const a = { sessionID: 'ses_reads', callID: 'read-a', tool: 'read' }, b = { ...a, callID: 'read-b' };
  await hooks['tool.execute.before'](a, { args }); await hooks['tool.execute.before'](b, { args });
  const posts = [hooks['tool.execute.after']({ ...a, args }, {}), hooks['tool.execute.after']({ ...b, args }, {})];
  const write = { ...a, callID: 'write', tool: 'write' }, writeArgs = { ...args, content: 'test' };
  let admitted = false; const before = hooks['tool.execute.before'](write, { args: writeArgs }).then(() => { admitted = true; });
  resolvers.get('read-a')({ allow: true }); await new Promise(resolve => setTimeout(resolve, 0)); assert.equal(admitted, false);
  resolvers.get('read-b')({ allow: true }); await Promise.all(posts); await before; assert.equal(admitted, true);
  await hooks['tool.execute.after']({ ...write, args: writeArgs }, {}); await hooks.dispose();
});

test('declare mailbox tool bypasses Work/file admission like send and read', async () => {
  const { createOpenCodeGovernance } = await import(pathToFileURL(path.join(root, '01.APP/nodelang/session_link/opencode-governance.mjs')).href);
  const hooks = await createOpenCodeGovernance({
    gateRunner: async () => { throw new Error('Work owner must not be acquired for declare'); },
  })({ directory: root, client: {} });
  const input = { sessionID: 'ses_declare', callID: 'declare-1', tool: 'archhub_agent_coordination_declare' };
  const args = { task: 'test declaration', paths: ['01.APP/nodelang/agent_declarations.py'], status: 'working' };
  const output = { args: JSON.parse(JSON.stringify(args)) };
  await hooks['tool.execute.before'](input, output);
  assert.deepEqual(output.args, args);
  await hooks['tool.execute.after']({ ...input, args: output.args }, {});
  await hooks.dispose();
});

test('failed MCP terminal event settles its exact call then permits file work', async () => {
 const {createOpenCodeGovernance}=await import(pathToFileURL(path.join(root,'01.APP/nodelang/session_link/opencode-governance.mjs')).href);
 const events=[];
 const hooks=await createOpenCodeGovernance({gateRunner:async event=>{events.push(event);return {allow:true};}})({directory:root,client:{}});
 const first={sessionID:'ses_failedmcp',callID:'failed-call',tool:'archhub-hosts_hosts_state'},args={};
 await hooks['tool.execute.before'](first,{args});
 await hooks.event({event:{type:'message.part.updated',properties:{part:{type:'tool',sessionID:first.sessionID,callID:first.callID,tool:first.tool,state:{status:'error',input:args,error:'fixture server failure'}}}}});
 assert.equal(events[1].hook_event_name,'PostToolUse');assert.equal(events[1].tool_response.status,'failed');
 const write={...first,callID:'write-after-error',tool:'write'},writeArgs={filePath:path.join(root,'unused.txt'),content:'fixture'};
 await hooks['tool.execute.before'](write,{args:writeArgs});
 await hooks['tool.execute.after']({...write,args:writeArgs},{});await hooks.dispose();
});

test('trusted outside directories keep other permission rules and the native gate', async () => {
 const {createOpenCodeGovernance}=await import(pathToFileURL(path.join(root,'01.APP/nodelang/session_link/opencode-governance.mjs')).href);
 const trusted=path.join(root,'registered-rules');let admissions=0;
 const hooks=await createOpenCodeGovernance({trustedDirectories:[trusted],gateRunner:async()=>{admissions++;return {allow:false};}})({directory:root,client:{}});
 const config={permission:{edit:'deny',external_directory:{'*':'ask','/outside/*':'deny'}}};await hooks.config(config);
 assert.equal(config.permission.external_directory[trusted.replaceAll('\\','/')+'/*'],'allow');
 assert.equal(config.permission.external_directory['/outside/*'],'deny');assert.equal(config.permission.edit,'deny');
 await assert.rejects(hooks['tool.execute.before']({sessionID:'ses_scope',callID:'write',tool:'write'},{args:{filePath:path.join(trusted,'x'),content:'x'}}),/admission denied/);
 assert.equal(admissions,1);await hooks.dispose();
});
