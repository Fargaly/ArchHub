/* Canvas live-node conversation rail: a node with has_conversation shows its Workshop
   transcript READ-ONLY (GET /api/universal/workshop-transcript, rows {id,who,is_me,time,text,kind}),
   for ANY live bound node (a workflow Workshop room has a `conversation` and no `model`),
   re-reads on open, serializes polls, rejects stale responses, and offers "Continue in the Workshop".
   Real browser-owner callbacks in memory; no provider, app or database. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const lmPath = process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-lm.jsx');
const dir = path.dirname(lmPath);
const source = fs.readFileSync(lmPath, 'utf8');
const html = fs.readFileSync(path.join(dir, 'studio.html'), 'utf8');
const authority = fs.readFileSync(path.join(dir, 'studio-authority.js'), 'utf8');

const slice = (from, to) => {
  const start = source.indexOf(from), end = source.indexOf(to, start);
  assert.ok(start > 0 && end > start, from + ' is a slice of the shipped studio-lm.jsx');
  return source.slice(start, end);
};
// Everything from the conversation component through NodeRail (so a real NodeRail mount has its deps).
const railSlice = () => slice('const NodeModelConversation =', '\nconst ConversationRail =');

// The real helpers, so the model gate is exercised, not faked.
const REAL_HELPERS = `
const nodeModelRow = n => (n && n.params || []).find(row => row.k === 'model') || null;
const nodeModelRoute = n => { const r = String((nodeModelRow(n)||{}).v || '').trim(); return r === 'provider-selected' ? '' : r; };
`;

async function mountEnv(fn) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window;
  global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const LM = new Proxy({}, {get:(_, k) => 'token-' + String(k)});
  const studioCategory = () => ({col:'#E0794A', icon:'A', label:'AI', role:''});
  const InlineAsk = () => React.createElement('textarea', {'data-stub':'inlineask'});
  const HoverBtn = ({onClick, disabled, children}) => React.createElement('button', {onClick, disabled}, children);
  win.NodeInspector = () => React.createElement('div', {'data-stub':'inspector'});
  const ConversationRail = () => React.createElement('div', {'data-stub':'convrail'});
  const context = vm.createContext({React, LM, studioCategory, InlineAsk, HoverBtn, ConversationRail,
    window:win, document:win.document, setInterval, clearInterval, setTimeout, clearTimeout});
  vm.runInContext(transformSync(REAL_HELPERS + railSlice() +
    '\nglobalThis.Conv = NodeModelConversation; globalThis.Rail = NodeRail;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  try { await fn({React, win, root, context}); }
  finally {
    await React.act(async () => root.unmount());
    win.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
}
const tick = async React => { await React.act(async () => { await new Promise(r => setTimeout(r, 0)); }); };

// ── projection fields reach the client node (studio-authority.js map) ──
test('the clean canvas node carries conversation_root and has_conversation', () => {
  const anchor = authority.indexOf('node.category');
  const map = authority.slice(authority.lastIndexOf('return {', anchor), authority.indexOf('};', anchor));
  assert.match(map, /conversation_root:\s*node\.conversation_root/);
  assert.match(map, /has_conversation:\s*node\.has_conversation\s*===\s*true/);
});

// ── the read-only transcript reader exists and hits the agreed route ──
test('studio.html exposes a read-only node-transcript reader on the agreed route', () => {
  assert.match(html, /ARCHHUB_WORKSHOP_TRANSCRIPT\s*=/);
  const reader = html.slice(html.indexOf('ARCHHUB_WORKSHOP_TRANSCRIPT'),
    html.indexOf(';', html.indexOf('ARCHHUB_WORKSHOP_TRANSCRIPT')) + 1);
  assert.match(reader, /\/api\/universal\/workshop-transcript\?node=/);
  assert.match(reader, /scope=/);
  assert.match(reader, /jget\(/);
});

// ── the rail is wired with the scope and a continue-in-Workshop opener, gated for ANY bound node ──
test('the Workspace threads scope + opener, and NodeRail gates on has_conversation too', () => {
  const workspace = slice('const Workspace =', '// The string the server');
  assert.match(workspace, /<NodeRail[\s\S]*?scope=\{/);
  assert.match(workspace, /<NodeRail[\s\S]*?openConversation=\{/);
  // The gate must not require a model row — a model-less room node still gets the transcript.
  const rail = slice('const NodeRail =', '\nconst ConversationRail =');
  assert.match(rail, /node\.live && \(node\.has_conversation \|\| nodeModelRow\(node\)\)/,
    'NodeRail must render the conversation component for any live has_conversation node, not only model nodes');
});

// ── FINDING 1: a real NodeRail mount with a model-less Workshop room node ──
test('NodeRail shows the transcript + Continue for a model-less room node', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    const calls = [];
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node, scope) => {
      calls.push({node, scope});
      return {ok:true, node, conversation_root:'app:workshop', revision:4, has_older:true, next_before:'b1',
        rows:[{id:'m1', who:'You', is_me:true, time:'2026-10-01T18:51:32.468877+00:00', text:'PROPOSE a workflow.', kind:'message'},
              {id:'m2', who:'acceptance-claude', is_me:false, time:'2026-10-01T18:51:34.031545+00:00', text:'Here is my proposal.', kind:'reply'}]};
    };
    // The real bound node: a Workshop room — conversation param, NO model.
    const room = {id:'assembly-instance:room', title:'This Workshop', live:true, cat:'ai',
      has_conversation:true, conversation_root:'app:workshop', params:[{k:'conversation', v:'app:workshop'}]};
    const opened = [];
    await React.act(async () => root.render(React.createElement(context.Rail,
      {node:room, scope:'app:workshop', openConversation:r => opened.push(r)})));
    await tick(React);
    const text = win.document.getElementById('root').textContent;
    assert.ok(calls.length >= 1 && calls[0].node === 'assembly-instance:room', 'the room node transcript is read');
    assert.match(text, /PROPOSE a workflow\./, 'the transcript renders for a model-less node');
    assert.match(text, /Here is my proposal\./);
    assert.match(text, /Latest messages only/, 'has_older shows the honest history hint');
    assert.equal(win.document.querySelector('#root textarea'), null, 'a model-less node shows no model composer');
    const cont = [...win.document.querySelectorAll('button')].find(b => /continue in the workshop/i.test(b.textContent));
    assert.ok(cont, 'Continue in the Workshop is present');
    await React.act(async () => cont.click());
    assert.deepEqual(opened, ['app:workshop']);
  });
});

// ── a model-bearing node keeps the model composer AND can show a transcript ──
test('a model node keeps its composer; honest-empty when no rows', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node) => ({ok:true, node, conversation_root:'conv-a',
      revision:4, has_older:false, next_before:null, rows:[]});
    const modelNode = {id:'node-m', title:'Agent', live:true, cat:'ai', has_conversation:true,
      conversation_root:'conv-a', params:[{k:'model', v:'openrouter/model-a'}]};
    await React.act(async () => root.render(React.createElement(context.Conv,
      {node:modelNode, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    assert.ok(win.document.querySelector('#root textarea[data-stub="inlineask"]'), 'model node keeps the composer');
    assert.match(win.document.getElementById('root').textContent, /No conversation yet/, 'empty bound transcript is honest');
  });
});

// ── FINDING 2a: populated rows do NOT survive a scope switch; the stale response is dropped ──
test('rows clear on a scope switch and the stale response never lands', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    const held = {};
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = (node, scope) => new Promise(res => {
      held[scope] = () => res({ok:true, node, conversation_root:'conv-a', revision:4, has_older:false, next_before:null,
        rows:[{id:scope, who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'rows-of-' + scope, kind:'message'}]});
    });
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a',
      params:[{k:'model', v:'openrouter/model-a'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await React.act(async () => { held['scope-a'](); await new Promise(r => setTimeout(r, 0)); });
    assert.match(win.document.getElementById('root').textContent, /rows-of-scope-a/, 'scope-a rows are shown first');
    // switch scope; old rows must clear immediately (not linger under the new binding)
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-b', openConversation:()=>{}})));
    await tick(React);
    const mid = win.document.getElementById('root').textContent;
    assert.ok(!/rows-of-scope-a/.test(mid), 'stale scope-a rows must not linger under scope-b');
    assert.match(mid, /Reading the conversation/, 'the new binding shows loading, not stale rows');
    await React.act(async () => { held['scope-b'](); await new Promise(r => setTimeout(r, 0)); });
    assert.match(win.document.getElementById('root').textContent, /rows-of-scope-b/, 'scope-b rows land');
  });
});

// ── FINDING 2c: a response whose node/conversation does not match the current binding is rejected ──
test('a response for the wrong node is not shown', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async () => ({ok:true, node:'some-other-node', conversation_root:'conv-a',
      revision:4, has_older:false, next_before:null,
      rows:[{id:'x', who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'WRONG-NODE-ROWS', kind:'message'}]});
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a',
      params:[{k:'model', v:'openrouter/model-a'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    assert.ok(!/WRONG-NODE-ROWS/.test(win.document.getElementById('root').textContent),
      'a mismatched-node response must be rejected, never rendered');
  });
});

// ── FINDING 2b: polls are serialized — a new read never starts while one is in flight ──
test('an 8s poll does not overlap an in-flight read', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window; global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  let poll = null; const fakeSetInterval = fn => { poll = fn; return 1; }; const fakeClearInterval = () => { poll = null; };
  let calls = 0, release = null;
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = (node) => { calls += 1; return new Promise(res => { release = () => res({ok:true, node,
    conversation_root:'conv-a', revision:4, has_older:false, next_before:null, rows:[]}); }); };
  const LM = new Proxy({}, {get:(_, k) => 'token-' + String(k)});
  const studioCategory = () => ({col:'#E0794A', icon:'A', label:'AI'});
  const InlineAsk = () => React.createElement('textarea', {}); const HoverBtn = ({children}) => React.createElement('button', {}, children);
  win.NodeInspector = () => null; const ConversationRail = () => null;
  const context = vm.createContext({React, LM, studioCategory, InlineAsk, HoverBtn, ConversationRail,
    window:win, document:win.document, setInterval:fakeSetInterval, clearInterval:fakeClearInterval, setTimeout, clearTimeout});
  vm.runInContext(transformSync(REAL_HELPERS + railSlice() + '\nglobalThis.Conv = NodeModelConversation;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  try {
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a', params:[{k:'model', v:'m'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await React.act(async () => { await new Promise(r => setTimeout(r, 0)); });
    assert.equal(calls, 1, 'the open read fired once');
    // fire the poll twice WHILE the first read is still in flight
    await React.act(async () => { if (poll) { poll(); poll(); } await new Promise(r => setTimeout(r, 0)); });
    assert.equal(calls, 1, 'a poll must not start a new read while one is in flight');
    await React.act(async () => { release(); await new Promise(r => setTimeout(r, 0)); });
    await React.act(async () => { if (poll) poll(); await new Promise(r => setTimeout(r, 0)); });
    assert.equal(calls, 2, 'once the in-flight read settles, the next poll may read');
  } finally {
    await React.act(async () => root.unmount());
    win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});

// ── FINDING 2: unmount mid-flight does not set state after teardown ──
test('a read that resolves after unmount throws nothing and sets no state', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window; global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const errors = []; const origErr = console.error; console.error = (...a) => errors.push(a.join(' '));
  let release;
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = (node) => new Promise(res => { release = () => res({ok:true, node,
    conversation_root:'conv-a', revision:4, has_older:false, next_before:null, rows:[{id:'m', who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'late', kind:'message'}]}); });
  const LM = new Proxy({}, {get:(_, k) => 'token-' + String(k)});
  const studioCategory = () => ({col:'#E0794A', icon:'A', label:'AI'});
  const InlineAsk = () => React.createElement('textarea', {});
  const HoverBtn = ({onClick, disabled, children}) => React.createElement('button', {onClick, disabled}, children);
  win.NodeInspector = () => null; const ConversationRail = () => null;
  const context = vm.createContext({React, LM, studioCategory, InlineAsk, HoverBtn, ConversationRail,
    window:win, document:win.document, setInterval, clearInterval, setTimeout, clearTimeout});
  vm.runInContext(transformSync(REAL_HELPERS + railSlice() + '\nglobalThis.Conv = NodeModelConversation;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  try {
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a', params:[{k:'model', v:'m'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await React.act(async () => root.unmount());
    await React.act(async () => { release(); await new Promise(r => setTimeout(r, 0)); });
    assert.ok(!errors.some(e => /unmounted|not wrapped in act|memory leak/i.test(e)),
      'no set-state-after-unmount warning: ' + errors.join(' | '));
  } finally {
    console.error = origErr; win.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});
