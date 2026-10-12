const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');

function tmpRoot() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'archhub-gov-eq-opencode-'));
  fs.mkdirSync(path.join(dir, 'home'), { recursive: true });
  process.env.HOME = path.join(dir, 'home');
  process.env.USERPROFILE = path.join(dir, 'home');
  return dir;
}

function fakeClient(directory, calls, statuses = []) {
  let promptCount = 0;
  const replyFor = (sessionId, parentID) => ({
    info: {
      id: `assistant-${++promptCount}`,
      parentID,
      role: 'assistant',
      sessionID: sessionId,
      time: { created: 2 + promptCount },
    },
    parts: [{ id: `part-${promptCount}`, messageID: `assistant-${promptCount}`, sessionID: sessionId, type: 'text', text: 'ok' }],
  });
  let lastUser = null;
  let lastReply = null;
  return {
    session: {
      list: async () => ({ data: [{ id: 'ses_goveq', title: 'Gov Eq', directory }] }),
      get: async ({ path: given, query }) => ({ data: { id: given.id, directory: query.directory } }),
      status: async () => ({ data: { ses_goveq: statuses.shift() || { type: 'idle' } } }),
      prompt: async ({ path: given, query, body }) => {
        const text = body.parts[0].text;
        calls.push(text);
        lastUser = {
          info: { id: `user-${promptCount + 1}`, parentID: null, role: 'user', sessionID: given.id, time: { created: 1 + promptCount } },
          parts: [{ id: `user-part-${promptCount + 1}`, messageID: `user-${promptCount + 1}`, sessionID: given.id, type: 'text', text }],
        };
        lastReply = replyFor(given.id, lastUser.info.id);
        return { data: lastReply };
      },
      messages: async () => ({ data: [lastUser, lastReply] }),
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
    socket.on('end', () => {
      try { resolve(JSON.parse(data)); } catch (error) { reject(error); }
    });
    socket.on('connect', () => socket.write(JSON.stringify(payload) + '\n'));
  });
}

async function closePlugin() {
  const symbol = Symbol.for('archhub.session-link.opencodeserver');
  const held = globalThis[symbol];
  delete globalThis[symbol];
  if (!held) return;
  await new Promise(resolve => held.server.close(resolve));
  held.peer.stop();
}

test('gov eq OpenCode plugin queues a busy session and delivers when idle', async () => {
  const dir = tmpRoot();
  const moduleUrl = pathToFileURL(path.join(root, 'nodelang', 'session_link', 'opencode-plugin.mjs')).href;
  const { createSessionLinkPlugin } = await import(moduleUrl);
  const calls = [];
  const directory = path.join(dir, 'workspace');
  fs.mkdirSync(directory);
  const client = fakeClient(directory, calls, [{ type: 'busy' }, { type: 'idle' }]);

  try {
    await createSessionLinkPlugin({ stateDirectory: dir })({ client, directory });
    const runtime = JSON.parse(fs.readFileSync(path.join(dir, 'opencode-runtimes', `${process.pid}.json`), 'utf8'));
    const answer = await rpc(runtime.control, {
      token: runtime.keyPath ? JSON.parse(fs.readFileSync(runtime.keyPath, 'utf8')).peerToken : undefined,
      operation: 'send',
      id: 'ses_goveq',
      directory,
      text: 'queued hello',
    });

    assert.equal(answer.ok, true, answer);
    assert.deepEqual(calls, ['queued hello']);
  } finally {
    await closePlugin();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('gov eq OpenCode plugin reads its PeerEndpoint inbox and prompts the session', async () => {
  const dir = tmpRoot();
  const moduleUrl = pathToFileURL(path.join(root, 'nodelang', 'session_link', 'opencode-plugin.mjs')).href;
  const protocolUrl = pathToFileURL(path.join(root, 'nodelang', 'session_link', 'vendor', 'src', 'peer-protocol.mjs')).href;
  const { createSessionLinkPlugin } = await import(moduleUrl);
  const { buildFrame, peerKeyPath } = await import(protocolUrl);
  const calls = [];
  const directory = path.join(dir, 'workspace');
  fs.mkdirSync(directory);
  const client = fakeClient(directory, calls);

  try {
    await createSessionLinkPlugin({ stateDirectory: dir })({ client, directory });
    const sessionDir = path.join(process.env.HOME, '.claude', 'sessions');
    const entries = fs.readdirSync(sessionDir)
      .filter(name => name.endsWith('.json'))
      .map(name => JSON.parse(fs.readFileSync(path.join(sessionDir, name), 'utf8')));
    const opencode = entries.find(entry => entry.name && entry.name.startsWith('opencode-session-link-'));
    assert.ok(opencode, 'OpenCode peer was not registered');

    const key = JSON.parse(fs.readFileSync(peerKeyPath(opencode.pid, opencode.messagingSocketPath), 'utf8'));
    await new Promise((resolve, reject) => {
      const socket = net.connect({ path: opencode.messagingSocketPath });
      socket.on('error', reject);
      socket.on('close', resolve);
      socket.on('connect', () => {
        const frame = buildFrame({ text: 'peer hello', fromSocket: '\\\\.\\pipe\\LOCAL\\goveq-sender' });
        socket.end(JSON.stringify({ type: 'auth', token: key.peerToken }) + '\n' + JSON.stringify(frame) + '\n');
      });
    });

    for (let i = 0; i < 40 && calls.length === 0; i += 1) {
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.deepEqual(calls, ['peer hello']);
  } finally {
    await closePlugin();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
