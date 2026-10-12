const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');

test('gov eq unmapped OpenCode tools pass through the shared governance gate', async () => {
  const moduleUrl = pathToFileURL(path.join(root, 'nodelang', 'session_link', 'opencode-governance.mjs')).href;
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
  const moduleUrl = pathToFileURL(path.join(root, 'nodelang', 'session_link', 'opencode-governance.mjs')).href;
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
