// OpenCode 2 (setup(ctx)) joins the Workshop through the same transport as OpenCode 1. Fake ctx only.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..', '..');
const moduleUrl = pathToFileURL(path.join(root, '01.APP/nodelang', 'workshop', 'opencode-plugin.mjs')).href;

function tmpRoot() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'archhub-opencode-v2-'));
  fs.mkdirSync(path.join(dir, 'home'), { recursive: true });
  process.env.HOME = path.join(dir, 'home');
  process.env.USERPROFILE = path.join(dir, 'home');
  return dir;
}

// The V2 plugin ctx shape of @opencode/plugin 2.3.2: session.{list,get,context,prompt,wait,switchModel}.
function fakeCtx(directory, calls) {
  const messages = [];
  let n = 0;
  return {
    location: { directory },
    session: {
      list: async input => { calls.push(['list', input]); return { data: [{ id: 'ses_v2', title: 'V2', location: { directory } }], cursor: {} }; },
      get: async ({ sessionID }) => ({ id: sessionID, title: 'V2', location: { directory } }),
      context: async () => messages,
      switchModel: async input => calls.push(['model', input]),
      prompt: async ({ sessionID, text, delivery }) => {
        calls.push(['prompt', text, delivery]);
        const user = { id: `msg_u${++n}`, type: 'user', text, time: { created: 10 * n } };
        messages.push(user);
        messages.push({ id: `msg_a${n}`, type: 'assistant', agent: 'build', model: { id: 'm', providerID: 'p' },
          time: { created: 10 * n + 1, completed: 10 * n + 2 }, finish: 'stop',
          content: [{ type: 'tool', id: 't', name: 'edit', state: { status: 'completed', input: { filePath: 'a.txt' }, content: [{}] },
                      time: { created: 10 * n + 1, completed: 10 * n + 2 } },
                    { type: 'text', text: 'reply to ' + text }] });
        return { id: user.id, sessionID, type: 'user', time: { created: user.time.created }, delivery: delivery || 'queue' };
      },
      wait: async ({ sessionID }) => calls.push(['wait', sessionID]),
    },
  };
}

function rpc(control, payload) {
  return new Promise((resolve, reject) => {
    const socket = net.connect({ path: control });
    let data = '';
    socket.setEncoding('utf8');
    socket.on('error', reject);
    socket.on('data', chunk => { data += chunk; });
    socket.on('end', () => { try { resolve(JSON.parse(data)); } catch (error) { reject(error); } });
    socket.on('connect', () => socket.write(JSON.stringify(payload) + '\n'));
  });
}

async function closePlugin() {
  const symbol = Symbol.for('archhub.workshop.opencodeserver');
  const held = globalThis[symbol];
  delete globalThis[symbol];
  if (!held) return;
  await new Promise(resolve => held.server.close(resolve));
  held.peer.stop();
}

test('OpenCode 2 setup joins the Workshop: list, send waits for the reply, inject steers, activity reads tools', async () => {
  const dir = tmpRoot();
  const { createWorkshopPluginV2 } = await import(moduleUrl);
  const calls = [];
  const directory = path.join(dir, 'workspace');
  fs.mkdirSync(directory);
  try {
    await createWorkshopPluginV2({ stateDirectory: dir })(fakeCtx(directory, calls));
    const runtime = JSON.parse(fs.readFileSync(path.join(dir, 'opencode-runtimes', `${process.pid}.json`), 'utf8'));
    const token = JSON.parse(fs.readFileSync(runtime.keyPath, 'utf8')).peerToken;
    const ask = payload => rpc(runtime.control, { token, ...payload });

    const listed = await ask({ operation: 'list' });
    assert.equal(listed.ok, true, JSON.stringify(listed));
    assert.deepEqual(listed.result.map(row => [row.app, row.id, row.cwd]), [['opencode', 'ses_v2', directory]]);

    const sent = await ask({ operation: 'send', id: 'ses_v2', directory, text: 'hello' });
    assert.equal(sent.ok, true, JSON.stringify(sent));
    assert.equal(sent.result.text, 'reply to hello');
    assert.deepEqual(calls.filter(c => c[0] !== 'list'), [['prompt', 'hello', 'queue'], ['wait', 'ses_v2']]);

    const injected = await ask({ operation: 'inject', id: 'ses_v2', directory, text: 'mid-turn', messageId: 'w1' });
    assert.equal(injected.ok, true, JSON.stringify(injected));
    assert.deepEqual(calls.at(-1), ['prompt', 'mid-turn', 'steer']);

    const activity = await ask({ operation: 'activity', id: 'ses_v2', directory, root: directory });
    assert.equal(activity.ok, true, JSON.stringify(activity));
    assert.equal(activity.result[0].tool, 'edit');
    assert.equal(activity.result[0].file, 'a.txt');
  } finally {
    await closePlugin();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('a message steered mid-turn does not steal the turn reply; a missing workspace folder attaches nothing', async () => {
  const dir = tmpRoot();
  const { v1ClientFromV2, createWorkshopPluginV2 } = await import(moduleUrl);
  const directory = path.join(dir, 'workspace');
  fs.mkdirSync(directory);
  try {
    const messages = [];
    let n = 0;
    const ctx = {
      location: { directory },
      session: {
        context: async () => messages,
        wait: async () => {
          // While the queued turn runs, a steer lands, then the turn's reply: in V2 order, no parent links.
          messages.push({ id: 'msg_steer', type: 'user', text: 'also this', time: { created: 2 } });
          messages.push({ id: 'msg_a', type: 'assistant', model: { id: 'm', providerID: 'p' }, finish: 'stop',
            time: { created: 3, completed: 4 }, content: [{ type: 'text', text: 'the reply' }] });
        },
        prompt: async ({ text, delivery }) => {
          const id = delivery === 'steer' ? 'msg_steer' : 'msg_turn';
          if (delivery !== 'steer') messages.push({ id, type: 'user', text, time: { created: 1 } });
          n += 1;
          return { id, type: 'user', time: { created: n }, delivery };
        },
      },
    };
    const client = v1ClientFromV2(ctx);
    await client.session.promptAsync({ path: { id: 'ses' }, body: { parts: [{ type: 'text', text: 'also this' }] } });
    const reply = await client.session.prompt({ path: { id: 'ses' }, body: { parts: [{ type: 'text', text: 'do it' }] } });
    assert.equal(reply.data.info.id, 'msg_a');
    assert.equal(reply.data.info.parentID, 'msg_turn');

    await createWorkshopPluginV2({ stateDirectory: dir })({ session: ctx.session });
    assert.equal(fs.existsSync(path.join(dir, 'opencode-runtimes')), false);
  } finally {
    await closePlugin();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('his own MCP servers reach OpenCode as one local server: V2 through ctx.mcp, V1 through the config hook', async () => {
  const dir = tmpRoot();
  const { createWorkshopPlugin, createWorkshopPluginV2 } = await import(moduleUrl);
  const directory = path.join(dir, 'workspace');
  fs.mkdirSync(directory);
  const tools = { command: ['C:/ArchHub/.venv/Scripts/python.exe', '-I', '-B', '-c', 'loader', 'C:/ArchHub'], cwd: 'C:/ArchHub' };
  const set = [];
  try {
    const ctx = fakeCtx(directory, []);
    ctx.mcp = { transform: async edit => { edit({ set: (name, config) => set.push([name, config]) }); return { dispose: async () => {} }; } };
    await createWorkshopPluginV2({ stateDirectory: dir, tools })(ctx);
    assert.deepEqual(set, [['archhub-tools', { type: 'local', command: tools.command, cwd: tools.cwd }]]);

    const hooks = await createWorkshopPlugin({ stateDirectory: dir, tools })({ client: {}, directory });
    const config = { mcp: { other: { type: 'remote', url: 'https://x' } } };
    await hooks.config(config);
    assert.deepEqual(Object.keys(config.mcp), ['other', 'archhub-tools']);
    assert.equal(config.mcp['archhub-tools'].enabled, true);

    const plain = await createWorkshopPlugin({ stateDirectory: dir })({ client: {}, directory });
    assert.deepEqual(plain, {});
  } finally {
    await closePlugin();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
