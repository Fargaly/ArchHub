/* Workshop "Assign to agent" (design workshop-assign-design.html, founder decisions 1-5): the ASSIGN
   section of the Work's context panel, rendered from the COMPILED Studio in a real browser DOM.
   Only the rail's verified agents can be picked; nothing lets anyone type or start a session; the
   review card says what assigning does and does not do; a refusal leaves nothing assigned; a lost
   reply is retried with the SAME assignment id. The assign call is a stand-in for the transport. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

const agent = (id, name, status, verified, extra = {}) => ({id, name, status, verified, self:false, col:'#445566', ink:'#ffffff',
  ini:name.charAt(0), round:false, seen:verified ? '09:14' : '', ...extra});
const AGENTS = [
  {...agent('app:agent-session:runtime:founder', 'You', 'available', true), self:true},
  agent('app:agent-session:runtime:ping', 'Codex · Ping', 'available', true),
  agent('app:agent-session:runtime:717', 'Claude · 717 reviews', 'working', true),
  agent('app:agent-session:runtime:stale', 'OpenCode · 74588', 'stale', false),
  agent('app:agent-session:runtime:gone', 'Codex · 25f3', 'off', false),
];
const TASK = {work:'app:governed-work:7f3c21a0', title:'BBC4 installed evidence (3)', state:'open'};

async function mount(assign) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-workshop.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-workshop.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-workshop.jsx: run npm run build:studio');
  let JSDOM;
  try { ({JSDOM} = require('jsdom')); } catch (error) { ({JSDOM} = await import('jsdom')); }
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  if (!win.crypto || !win.crypto.randomUUID) {
    Object.defineProperty(win, 'crypto', {value:{randomUUID:() => require('node:crypto').randomUUID()}});
  }
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  assert.equal(typeof win.WorkshopAssignSection, 'function', 'the compiled Workshop module exports the ASSIGN section');
  win.__assign = assign;
  win.__props = {task:TASK, room:'app:workshop', agents:AGENTS, assignments:[]};
  win.eval('window.__root=ReactDOM.createRoot(document.getElementById("root"));' +
    'window.__render=()=>ReactDOM.flushSync(()=>window.__root.render(React.createElement(WorkshopAssignSection,' +
    '{...window.__props, assign:(request)=>window.__assign(request)})));window.__render();');
  const render = patch => { win.__props = {...win.__props, ...patch}; win.eval('window.__render()'); };
  // Unmount the section and mount a fresh one in the same window (the module's
  // pending-request map lives on, as it does when the panel closes and reopens).
  const remount = () => win.eval('window.__root.unmount();' +
    'window.__root=ReactDOM.createRoot(document.getElementById("root"));window.__render();');
  const doc = win.document;
  const click = element => win.eval('(el => ReactDOM.flushSync(() => el.click()))')(element);
  const settle = async (ms = 30) => { await new Promise(resolve => setTimeout(resolve, ms)); };
  const button = label => [...doc.querySelectorAll('button')].find(item => item.textContent.trim() === label);
  const radio = name => [...doc.querySelectorAll('[role="radio"]')].find(item => item.textContent.includes(name));
  return {win, doc, click, settle, button, radio, render, remount, close:() => { win.eval('window.__root.unmount()'); win.close(); }};
}

test('only verified agents can be picked, and nothing lets anyone type or start a session', async () => {
  const ui = await mount(async () => { throw new Error('not called'); });
  try {
    const radios = [...ui.doc.querySelectorAll('[role="radio"]')];
    assert.equal(radios.some(item => item.textContent.includes('You')), false, 'the founder himself is not a candidate');
    assert.equal(ui.radio('Codex · Ping').disabled, false);
    assert.equal(ui.radio('Claude · 717 reviews').disabled, false);
    assert.equal(ui.radio('OpenCode · 74588').disabled, true, 'a stale connection cannot be picked');
    assert.equal(ui.radio('Codex · 25f3').disabled, true, 'a disconnected agent cannot be picked');
    assert.match(ui.radio('OpenCode · 74588').textContent, /connection not renewed/);
    assert.match(ui.radio('Codex · 25f3').textContent, /disconnected from this app/);
    assert.equal(ui.doc.querySelectorAll('input, textarea').length, 0, 'no free-text field for a session');
    assert.equal(ui.button('Assign…').disabled, true, 'nothing is picked yet');
    assert.match(ui.doc.body.textContent, /ASSIGNED TO · nobody/);
  } finally { ui.close(); }
});

test('the review says what assigning does and does not, then the founder assigns once', async () => {
  const calls = [];
  const ui = await mount(async request => { calls.push(request);
    return {ok:true, assignment:request.assignment_id, work:request.work, agent_session:request.agent_session}; });
  try {
    ui.click(ui.radio('Codex · Ping'));
    ui.click(ui.button('Assign to Codex · Ping…'));
    const text = ui.doc.body.textContent;
    assert.match(text, /Assign this Work/);
    assert.match(text, /records the assignment · adds it to the agent's Work list · raises an attention item/);
    assert.match(text, /claim the Work · grant any file writes · start or enrol a session/);
    assert.match(text, /connection re-checked at commit · assignment id reused on retry/);
    assert.equal(calls.length, 0, 'reviewing sends nothing');
    ui.click(ui.button('Assign · founder'));
    await ui.settle();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].work, TASK.work);
    assert.equal(calls[0].agent_session, 'app:agent-session:runtime:ping');
    assert.match(calls[0].assignment_id, /^app:workshop-assignment:[a-f0-9]{32}$/);
    // "Assigned" is the projection's answer, not the reply's: the next read carries it.
    ui.render({assignments:[{assignment:calls[0].assignment_id, work:TASK.work, agent_session:calls[0].agent_session}]});
    assert.match(ui.doc.body.textContent, /ASSIGNED TO[\s\S]*Codex · Ping[\s\S]*it claims the Work itself/);
    assert.doesNotMatch(ui.doc.body.textContent, /cancel/i, 'no copy offers a cancellation that does not ship');
  } finally { ui.close(); }
});

test('a refusal leaves nothing assigned and says why; a lost reply retries the SAME assignment id', async () => {
  const calls = [];
  let mode = 'refuse';
  const ui = await mount(async request => {
    calls.push(request);
    if (mode === 'refuse') { const e = new Error('This agent has no live verified connection now; nothing was assigned'); e.assignmentRefused = true; throw e; }
    if (mode === 'lost') { const e = new Error('The assignment reply was lost. Retry sends the same assignment id, so it cannot assign twice.'); e.assignmentUncertain = true; throw e; }
    return {ok:true, assignment:request.assignment_id, work:request.work, agent_session:request.agent_session};
  });
  try {
    ui.click(ui.radio('Claude · 717 reviews'));
    ui.click(ui.button('Assign to Claude · 717 reviews…'));
    ui.click(ui.button('Assign · founder'));
    await ui.settle();
    assert.match(ui.doc.body.textContent, /NOT ASSIGNED[\s\S]*no live verified connection now; nothing was assigned/);
    assert.match(ui.doc.body.textContent, /ASSIGNED TO · nobody/, 'back to the pick list, nothing assigned');
    mode = 'lost';
    ui.click(ui.radio('Claude · 717 reviews'));
    ui.click(ui.button('Assign to Claude · 717 reviews…'));
    ui.click(ui.button('Assign · founder'));
    await ui.settle();
    assert.match(ui.doc.body.textContent, /NOT CONFIRMED/);
    assert.equal(ui.button('Back').disabled, true, 'an unconfirmed request is not dropped by Back');
    // Another task, then back: the unconfirmed request and its id are still there.
    ui.render({task:{work:'app:governed-work:other0001', title:'Other Work', state:'open'}});
    assert.match(ui.doc.body.textContent, /ASSIGNED TO · nobody/);
    assert.doesNotMatch(ui.doc.body.textContent, /NOT CONFIRMED/, 'the other Work shows nothing of it');
    ui.render({task:TASK});
    assert.match(ui.doc.body.textContent, /NOT CONFIRMED/);
    mode = 'ok';
    ui.click(ui.button('Retry the same assignment'));
    await ui.settle();
    assert.equal(calls.length, 3);
    assert.notEqual(calls[1].assignment_id, calls[0].assignment_id, 'a refused attempt is never reused');
    assert.equal(calls[2].assignment_id, calls[1].assignment_id, 'the retry after a lost reply reuses its id');
    assert.equal(calls[2].agent_session, calls[1].agent_session);
  } finally { ui.close(); }
});


test('reopening an assigned Work shows its assignee from the projection, not the pick list', async () => {
  const ui = await mount(async () => { throw new Error('not called'); });
  try {
    ui.render({assignments:[{assignment:'app:workshop-assignment:held', work:TASK.work, agent_session:'app:agent-session:runtime:717'}]});
    assert.match(ui.doc.body.textContent, /ASSIGNED TO[\s\S]*Claude · 717 reviews/);
    assert.equal(ui.doc.querySelectorAll('[role="radio"]').length, 0, 'an assigned Work offers no second assignee');
  } finally { ui.close(); }
});

test('a late reply for the previous Work never changes the panel now showing another Work', async () => {
  let release;
  const ui = await mount(request => new Promise(resolve => { release = () => resolve({ok:true,
    assignment:request.assignment_id, work:request.work, agent_session:request.agent_session}); }));
  try {
    ui.click(ui.radio('Codex · Ping'));
    ui.click(ui.button('Assign to Codex · Ping…'));
    ui.click(ui.button('Assign · founder'));
    ui.render({task:{work:'app:governed-work:other0002', title:'Other Work', state:'open'}});
    release();
    await ui.settle();
    assert.match(ui.doc.body.textContent, /ASSIGNED TO · nobody/, 'the new Work is untouched');
    assert.doesNotMatch(ui.doc.body.textContent, /NOT CONFIRMED|NOT ASSIGNED|Assigning…/);
  } finally { ui.close(); }
});


test('a lost reply, then unmount and remount: the review stays on the pending agent and its id, no other pick', async () => {
  const calls = [];
  let mode = 'lost';
  const ui = await mount(async request => {
    calls.push(request);
    if (mode === 'lost') { const e = new Error('The assignment reply was lost.'); e.assignmentUncertain = true; throw e; }
    return {ok:true, assignment:request.assignment_id, work:request.work, agent_session:request.agent_session};
  });
  try {
    ui.click(ui.radio('Codex · Ping'));
    ui.click(ui.button('Assign to Codex · Ping…'));
    ui.click(ui.button('Assign · founder'));
    await ui.settle();
    assert.equal(calls.length, 1);
    ui.remount();
    const text = ui.doc.body.textContent;
    assert.match(text, /NOT CONFIRMED/, 'the fresh mount starts from the unconfirmed request');
    const agent = ui.doc.querySelector('[data-assign-agent]');
    assert.equal(agent.dataset.assignAgent, 'app:agent-session:runtime:ping', 'the pending agent is the one shown');
    assert.equal(ui.doc.querySelectorAll('[role="radio"]').length, 0, 'no other agent can be picked while it is pending');
    assert.equal(ui.button('Back').disabled, true);
    mode = 'ok';
    ui.click(ui.button('Retry the same assignment'));
    await ui.settle();
    assert.equal(calls.length, 2);
    assert.equal(calls[1].agent_session, calls[0].agent_session, 'what was shown is what was sent');
    assert.equal(calls[1].assignment_id, calls[0].assignment_id, 'the same assignment id');
  } finally { ui.close(); }
});


test('a retry whose Workshop read fails BEFORE the POST keeps the earlier unconfirmed id and agent', async () => {
  const calls = [];
  let mode = 'lost';
  const ui = await mount(async request => {
    calls.push({...request, mode});
    if (mode === 'lost') { const e = new Error('The assignment reply was lost.'); e.assignmentUncertain = true; throw e; }
    if (mode === 'preflight') { const e = new Error('Refresh the Workshop before assigning.'); e.assignmentPreflight = true; throw e; }
    return {ok:true, assignment:request.assignment_id, work:request.work, agent_session:request.agent_session};
  });
  try {
    ui.click(ui.radio('Claude · 717 reviews'));
    ui.click(ui.button('Assign to Claude · 717 reviews…'));
    ui.click(ui.button('Assign · founder'));
    await ui.settle();
    mode = 'preflight';
    ui.click(ui.button('Retry the same assignment'));
    await ui.settle();
    assert.match(ui.doc.body.textContent, /NOT CONFIRMED[\s\S]*Nothing was sent/, 'a failed read is not a refusal');
    assert.equal(ui.doc.querySelectorAll('[role="radio"]').length, 0, 'the earlier write is still unsettled');
    ui.remount();
    assert.equal(ui.doc.querySelector('[data-assign-agent]').dataset.assignAgent, 'app:agent-session:runtime:717');
    mode = 'ok';
    ui.click(ui.button('Retry the same assignment'));
    await ui.settle();
    assert.equal(calls.length, 3);
    assert.equal(new Set(calls.map(call => call.assignment_id)).size, 1, 'one assignment id from first try to confirmation');
    assert.equal(new Set(calls.map(call => call.agent_session)).size, 1, 'one agent throughout');
  } finally { ui.close(); }
});

test('the Workshop API marks a failure before dispatch as preflight and sends nothing', async () => {
  const vm = require('node:vm');
  const context = vm.createContext({crypto: require('node:crypto').webcrypto, console});
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), context);
  const posts = [];
  const api = context.ArchHubExistingWorkshop.create({
    get: async () => ({ok:false}), post: async (...args) => { posts.push(args); return {ok:true}; },
    pendingStorage: {getItem: () => null, setItem: () => {}, removeItem: () => {}}, projectCanvas: () => null,
  });
  await assert.rejects(api.assignWork('app:workshop', {work:'app:governed-work:x', agent_session:'app:agent-session:runtime:717',
    assignment_id:'app:workshop-assignment:abcdef0123456789'}), error => error.assignmentPreflight === true);
  assert.equal(posts.length, 0, 'nothing was sent');
});


test('only a refusal naming the exact assignment id is a refusal; a null or malformed reply stays uncertain', () => {
  const vm = require('node:vm');
  const context = vm.createContext({crypto: require('node:crypto').webcrypto, console});
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), context);
  const classify = context.ArchHubExistingWorkshop.classifyAssignmentReply;
  const ask = {assignment_id:'app:workshop-assignment:abcdef0123456789', work:'app:governed-work:x',
    agent_session:'app:agent-session:runtime:717'};
  const refusal = (body) => Object.assign(new Error('refused'), {response: body});
  assert.equal(classify(null, null, ask).kind, 'uncertain', 'a null reply after the commit is not a refusal');
  assert.equal(classify(undefined, null, ask).kind, 'uncertain');
  assert.equal(classify({ok:false}, null, ask).kind, 'uncertain', 'a bare ok:false names no id');
  assert.equal(classify('nonsense', null, ask).kind, 'uncertain');
  assert.equal(classify(null, new Error('network'), ask).kind, 'uncertain');
  assert.equal(classify(null, refusal({refused:true, assignment:'app:workshop-assignment:someone-else'}), ask).kind,
    'uncertain', 'a refusal of another id settles nothing here');
  assert.equal(classify(null, refusal({refused:true}), ask).kind, 'uncertain');
  assert.equal(classify(null, refusal({refused:true, assignment:ask.assignment_id, error:'lapsed'}), ask).kind,
    'uncertain', 'a refusal that does not reconcile the id as absent settles nothing');
  assert.equal(classify(null, refusal({refused:true, assignment:ask.assignment_id, reconciled_absent:true, error:'lapsed'}), ask).kind, 'refused');
  assert.equal(classify({ok:true, assignment:ask.assignment_id, work:ask.work, agent_session:ask.agent_session}, null, ask).kind, 'assigned');
  assert.equal(classify({ok:true, assignment:'app:workshop-assignment:other', work:ask.work, agent_session:ask.agent_session}, null, ask).kind, 'uncertain');
});

test('a committed assignment whose reply comes back null keeps its pending id and agent', async () => {
  const vm = require('node:vm');
  const context = vm.createContext({crypto: require('node:crypto').webcrypto, console});
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), context);
  const classify = context.ArchHubExistingWorkshop.classifyAssignmentReply;
  const calls = [];
  let reply = null;   // the server committed; the reply came back null
  const ui = await mount(async request => {
    calls.push(request);
    const verdict = classify(reply, null, request);
    if (verdict.kind === 'uncertain') { const e = new Error(verdict.message); e.assignmentUncertain = true; throw e; }
    if (verdict.kind === 'refused') { const e = new Error(verdict.message); e.assignmentRefused = true; throw e; }
    return reply;
  });
  try {
    ui.click(ui.radio('Codex · Ping'));
    ui.click(ui.button('Assign to Codex · Ping…'));
    ui.click(ui.button('Assign · founder'));
    await ui.settle();
    assert.match(ui.doc.body.textContent, /NOT CONFIRMED/, 'a null reply is not a refusal');
    ui.remount();
    assert.equal(ui.doc.querySelector('[data-assign-agent]').dataset.assignAgent, 'app:agent-session:runtime:ping');
    reply = {ok:true, assignment:calls[0].assignment_id, work:calls[0].work, agent_session:calls[0].agent_session};
    ui.click(ui.button('Retry the same assignment'));
    await ui.settle();
    assert.equal(calls.length, 2);
    assert.equal(calls[1].assignment_id, calls[0].assignment_id);
  } finally { ui.close(); }
});
