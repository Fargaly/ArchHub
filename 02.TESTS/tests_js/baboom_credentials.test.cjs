const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const cp = require('node:child_process');
const {syncBuiltinESMExports} = require('node:module');
const {pathToFileURL} = require('node:url');
const http = require('node:http');

test('BABOOM uses its referenced OS credential without a plaintext fallback', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'baboom-credential-court-'));
  const keys = ['WORKSHOP_STATE_DIR', 'WORKSHOP_PYTHON', 'SystemRoot'];
  const previous = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  const originalRead = cp.execFileSync, originalFetch = globalThis.fetch;
  const token = 'test_'.repeat(9), wrong = 'wrong_'.repeat(8);
  let credential = token, reads = 0, dispatched = 0, requests = [];
  try {
    process.env.WORKSHOP_STATE_DIR = path.join(root, 'workshop');
    process.env.WORKSHOP_PYTHON = process.execPath;
    process.env.SystemRoot ||= 'C:/Windows';
    fs.mkdirSync(path.join(root, 'settings'));
    const file = path.join(root, 'settings/baboom-session.json');
    const held = {pid: process.pid, session: 'app-baboom', url: 'http://127.0.0.1:12345', credential: 'wcm://ArchHub/baboom-turn:' + 'a'.repeat(64)};
    cp.execFileSync = (_python, args) => {
      reads++;
      assert(!args.some(value => String(value).includes(token)));
      assert.equal(args.at(-2), root);
      if(args.at(-1)!==held.credential)throw new Error('profile mismatch');
      return credential;
    };
    syncBuiltinESMExports();
    globalThis.fetch = async (url, request) => {
      requests.push({url, request});
      const ok = request.headers['X-ArchHub-BABOOM'] === token;
      return {status: ok ? 200 : 401, json: async () => ({ok, error: ok ? '' : 'wrong token'})};
    };
    const {injectApp} = await import(pathToFileURL(path.resolve(__dirname, '../../01.APP/nodelang/workshop/workshop-apps.mjs')));
    const send = () => injectApp({app: 'archhub', id: 'baboom'}, 'hello', 'request-1', () => {dispatched++;});
    await t.test('referenced credential authenticates the existing turn door', async () => {
      fs.writeFileSync(file, JSON.stringify(held));
      assert.equal((await send()).status, 'injected');
      assert.equal(reads, 1); assert.equal(dispatched, 1);
      assert.equal(requests[0].url, 'http://127.0.0.1:12345/baboom/turn');
    });
    await t.test('missing credential refuses before dispatch', async () => {
      credential = ''; dispatched = 0; requests = [];
      assert.equal((await send()).status, 'not_sent');
      assert.equal(dispatched, 0); assert.equal(requests.length, 0);
    });
    await t.test('wrong credential is refused without retry', async () => {
      credential = wrong; dispatched = 0; requests = [];
      assert.equal((await send()).status, 'not_sent');
      assert.equal(dispatched, 1); assert.equal(requests.length, 1);
    });
    await t.test('legacy token and unrelated reference never reach the helper', async () => {
      reads = 0; dispatched = 0; requests = [];
      fs.writeFileSync(file, JSON.stringify({...held, credential: 'wcm://ArchHub/openrouter', token}));
      assert.equal((await send()).status, 'not_sent');
      assert.equal(reads, 0); assert.equal(dispatched, 0); assert.equal(requests.length, 0);
    });
    await t.test('an untrusted URL never receives a credential', async () => {
      reads = 0; dispatched = 0; requests = [];
      fs.writeFileSync(file, JSON.stringify({...held, url: 'https://example.invalid/collect'}));
      assert.equal((await send()).status, 'not_sent');
      assert.equal(reads, 0); assert.equal(dispatched, 0); assert.equal(requests.length, 0);
    });
    await t.test('another profiles reference is refused by the owner helper', async () => {
      reads = 0; dispatched = 0; requests = [];
      fs.writeFileSync(file, JSON.stringify({...held, credential: 'wcm://ArchHub/baboom-turn:' + 'b'.repeat(64)}));
      assert.equal((await send()).status, 'not_sent');
      assert.equal(reads, 1); assert.equal(dispatched, 0); assert.equal(requests.length, 0);
    });
    await t.test('a redirect cannot forward the credential to another origin', async () => {
      let forwarded = 0;
      const target = http.createServer((_req, res) => {forwarded++; res.end('{"ok":true}');});
      const redirect = http.createServer((_req, res) => {
        res.writeHead(307, {Location: `http://127.0.0.1:${target.address().port}/collect`});
        res.end();
      });
      try {
        await new Promise(resolve => target.listen(0, '127.0.0.1', resolve));
        await new Promise(resolve => redirect.listen(0, '127.0.0.1', resolve));
        credential = token; dispatched = 0; globalThis.fetch = originalFetch;
        fs.writeFileSync(file, JSON.stringify({...held, url: `http://127.0.0.1:${redirect.address().port}`}));
        await assert.rejects(send(), /fetch failed/);
        assert.equal(dispatched, 1); assert.equal(forwarded, 0);
      } finally {
        await Promise.all([redirect, target].map(server => new Promise(resolve => {
          server.close(resolve); server.closeAllConnections();
        })));
      }
    });
  } finally {
    cp.execFileSync = originalRead; syncBuiltinESMExports(); globalThis.fetch = originalFetch;
    for (const key of keys) if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key];
    assert(root.startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(root, {recursive: true});
  }
});
