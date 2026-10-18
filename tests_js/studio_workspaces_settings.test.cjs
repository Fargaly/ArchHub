/* Settings > Workspaces behaves by the registry's real state: changes are offered only when
   the start-up check and the current read agree, a pending check is read again until it
   answers, a failed read can be retried, and a mismatch pauses changes and offers Republish.
   The shipped compiled Studio in a real browser DOM; the one route is a court stand-in. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)]
  .map(match => [match[1], match[2]]));
const PROMISE = 'Removing a workspace only stops ArchHub from governing it. Your files are never deleted.';
const AGENTS = ['claude','codex','gemini','opencode','antigravity','cursor','windsurf','zed','aider'];

const view = (boot, projection, roots = [], pinned = roots.length > 0) => ({
  ok:true, revision:1, boot, projection, key_pinned:pinned, promise:PROMISE,
  built_in:{id:'archhub', path:'C:\\Users\\fargaly\\00.ARCHUB', removable:false},
  roots:roots.map(id => ({root_id:id, path:'D:\\Clients\\' + id, privacy:'private', profile:'client',
    writers:[...AGENTS], state:'registered', registered_at:'2026-09-29T00:00:00Z'})),
});

async function mount(answers, options = {}) {
  const sourceMode = process.env.PRIVGRANT_SOURCE === '1';
  const names = ['tokens.jsx','ds/index.jsx','design-canvas.jsx','shared-data.jsx','studio-suite.jsx','param-types.jsx','studio-params.jsx','studio-mobile.jsx','studio-account.jsx','node-registry.jsx','brain-model.jsx','workshop-board.jsx','studio-workshop.jsx','studio-lm.jsx'];
  const manifest = sourceMode ? {files:names.map(source => ({source}))} : JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  if (!sourceMode) assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  let JSDOM;
  try { ({JSDOM} = require('jsdom')); } catch (error) { ({JSDOM} = await import('jsdom')); }
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const requests = [];
  const hostAnswers = [...(options.hosts || [{ok:true, connectors:[], operations:[]}])];
  let lastHostAnswer = {ok:true, connectors:[], operations:[]};
  win.fetch = (url, fetchOptions = {}) => {
    if (String(url) === '/api/universal/hosts') {
      const answer = hostAnswers.length ? (lastHostAnswer = hostAnswers.shift()) : lastHostAnswer;
      return Promise.resolve({ok:answer.ok !== false, status:answer.ok === false ? 500 : 200, json:async () => answer});
    }
    if (String(url) === '/tools') return Promise.resolve({ok:true, json:async () => ({tools:[]})});
    if (String(url) === '/waiting') return Promise.resolve({ok:true, json:async () => ({items:[]})});
    if (String(url) !== '/api/universal/workspace-roots') return new Promise(() => {});
    const body = JSON.parse(fetchOptions.body || '{}');
    requests.push(body);
    const answer = answers.shift();
    if (!answer) return new Promise(() => {});
    if (answer === 'fail') return Promise.resolve({ok:false, json:async () => ({ok:false, error:'registry unreachable'})});
    if (answer === 'owner-down') return Promise.resolve({ok:false, json:async () => ({ok:false, error:"the ArchHub graph owner is not answering (connection refused); start ArchHub's graph service"})});
    if (answer.refused) return Promise.resolve({ok:false, status:403, json:async () => ({ok:false, error:answer.refused})});
    return Promise.resolve({ok:true, status:200, json:async () => ({...answer,private_grant_sessions:options.native || {status:'ok',sessions:[]}})});
  };
  win.ARCHHUB_THEME = {...seed};
  win.ARCHHUB_LIVE = {hosts:[], connectors:[], skills:[], memory:[], graph:{nodes:[], wires:[]}};
  win.ARCHHUB_LOAD_HOSTS = async () => {
    const scan = await win.fetch('/api/universal/hosts').then(response => response.json());
    const rows = (Array.isArray(scan.connectors) ? scan.connectors : []).filter(row => row && row.id).map(row => ({
      ...row,
      id:String(row.id),
      state:row.state || 'unknown',
      detail:row.detail || (row.connector_built === false ? 'no connector yet' : 'status unknown'),
    }));
    return {hosts:rows, connectors:rows};
  };
  const renewals = [];
  win.__archhubSession = {token:'held-token', csrf:'held-csrf'};
  win.__archhubRenewSession = async () => {
    renewals.push(1);
    win.__archhubSession = {token:'fresh-token', csrf:'fresh-csrf'};
    return win.__archhubSession;
  };
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  if (sourceMode) win.eval(read('nodelang/studio/vendor/babel.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(sourceMode ? win.Babel.transform(read('nodelang/studio/' + file.source), {presets:['react','env']}).code : read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const click = element => win.eval('(el => ReactDOM.flushSync(() => el.click()))')(element);
  click(doc.querySelector('[title="Settings"]'));
  const settle = async (ms = 30) => { await new Promise(resolve => setTimeout(resolve, ms)); };
  const tabName = options.tab || 'Workspaces';
  const navigation = settingsNavigator({doc, flush:fn => win.ReactDOM.flushSync(fn), settle});
  await navigation.tab(tabName);
  const button = label => [...doc.querySelectorAll('button')].find(item => item.textContent.trim() === label);
  const typePath = value => {
    const input = doc.querySelector('[aria-label="Workspace folder"]');
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    win.eval('(el => ReactDOM.flushSync(() => el.dispatchEvent(new Event("input", {bubbles:true}))))')(input);
  };
  const typeName = value => {
    const input = doc.querySelector('[aria-label="Workspace name"]');
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    win.eval('(el => ReactDOM.flushSync(() => el.dispatchEvent(new Event("input", {bubbles:true}))))')(input);
  };
  return {win, doc, requests, renewals, click, settle, button, typePath, typeName,
    close: () => { win.eval('window.__studioRoot.unmount()'); win.close(); }};
}

test('Hosts renders not-built server rows separately and counts only built running rows', async () => {
  const hosts = {ok:true, operations:[], connectors:[
    {id:'revit', name:'Revit', state:'connected', detail:'1 session', connector_built:true},
    {id:'civil3d', name:'Civil 3D', state:'off', detail:'no connector yet', connector_built:false},
    {id:'navisworks', name:'Navisworks', state:'off', detail:'no connector yet', connector_built:false},
  ]};
  const ui = await mount([], {tab:'Hosts', hosts:[hosts]});
  try {
    await ui.settle(80);
    const rows = [...ui.doc.querySelectorAll('[data-connector-row]')];
    assert.equal(rows.length, 3);
    assert.ok(rows.some(row => row.textContent.includes('Civil 3D') && row.textContent.includes('no connector yet')));
    assert.ok(rows.some(row => row.textContent.includes('Navisworks') && row.textContent.includes('no connector yet')));
    assert.match(ui.doc.querySelector('[data-connectors-bar]').textContent, /1\/1 running .* 2 coming/);
  } finally { ui.close(); }
});

test('Hosts renders stopped built programs as Not running without warn pulse', async () => {
  const hosts = {ok:true, operations:[], connectors:[
    {id:'revit', name:'Revit', state:'stopped', detail:'installed', connector_built:true},
  ]};
  const ui = await mount([], {tab:'Hosts', hosts:[hosts]});
  try {
    await ui.settle(80);
    const row = ui.doc.querySelector('[data-connector-row]');
    assert.ok(row.textContent.includes('Not running'));
    assert.equal(row.querySelector('span').style.animation, 'none');
  } finally { ui.close(); }
});

test('a pending start-up check offers no change, is read again, and opens changes when it matches', async () => {
  const ui = await mount([view('checking', 'missing'), view('checking', 'missing'), view('missing', 'missing')]);
  try {
    await ui.settle();
    ui.typePath('D:\\Clients\\alpha');
    await ui.settle();
    assert.equal(ui.button('Add'), undefined, 'Add is not shown while the check is pending');
    assert.equal(ui.button('Republish'), undefined, 'no Republish while the first check is pending');
    assert.equal(ui.button('Add'), undefined, 'no hidden Add route while the check is pending');
    await ui.settle();
    assert.deepEqual(ui.requests.map(item => item.action), ['list'], 'a pending check sends no change');
    await ui.settle(3400);
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'list', 'list'], 'read again while checking');
    assert.equal(ui.button('Add').disabled, false, 'Add opens once the check and the read agree');
    await ui.settle(1700);
    assert.equal(ui.requests.length, 3, 'reading stops once the check answered');
  } finally { ui.close(); }
});

test('a failed first read offers Read again and no change until it succeeds', async () => {
  const ui = await mount(['fail', view('match', 'match', ['alpha'])]);
  try {
    await ui.settle();
    assert.match(ui.doc.body.textContent, /The workspace registry was not read: registry unreachable/);
    ui.typePath('D:\\Clients\\beta');
    await ui.settle();
    assert.equal(ui.button('Add'), undefined, 'no change after a failed read');
    assert.equal(ui.button('Add'), undefined, 'no hidden Add route after a failed read');
    await ui.settle();
    assert.deepEqual(ui.requests.map(item => item.action), ['list']);
    ui.click(ui.button('Read again'));
    await ui.settle();
    assert.equal(ui.button('Add').disabled, false);
    assert.ok(ui.button('Remove'), 'the registered root is listed after the retry');
  } finally { ui.close(); }
});

test('an owner-down registry read shows starting status and auto-retries until rows load', async () => {
  const ui = await mount(['owner-down', view('missing', 'missing', ['client-a'])]);
  try {
    await ui.settle();
    assert.match(ui.doc.body.textContent, /Starting ArchHub's graph service/);
    assert.ok(ui.button('Retry'), 'manual Retry remains available during service startup');
    assert.equal(ui.doc.querySelector('[role="alert"]'), null, 'owner-down read is not rendered as a red refusal');
    assert.equal(ui.doc.body.textContent.includes('The workspace registry was not read'), false);
    await ui.settle(2100);
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'list']);
    assert.ok(ui.button('Remove'), 'the registered root is listed after automatic retry');
    assert.equal(ui.doc.body.textContent.includes('Starting ArchHub'), false);
  } finally { ui.close(); }
});

test('a start-up match with a current mismatch pauses changes and offers Republish', async () => {
  const ui = await mount([view('match', 'mismatch', ['alpha']), view('match', 'match', ['alpha'])]);
  try {
    await ui.settle();
    const alert = [...ui.doc.querySelectorAll('[role="alert"]')].map(item => item.textContent).join(' ');
    assert.match(alert, /does not match the graph \(start-up check: match; now: mismatch\)/);
    ui.typePath('D:\\Clients\\beta');
    await ui.settle();
    assert.equal(ui.button('Add'), undefined);
    assert.equal(ui.button('Remove').disabled, true);
    ui.click(ui.button('Remove'));
    await ui.settle();
    assert.equal(ui.doc.querySelector('[role="dialog"]:not([aria-label="Settings"])'), null, 'no confirmation while paused');
    ui.click(ui.button('Republish'));
    await ui.settle();
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'republish']);
    assert.equal(ui.button('Add').disabled, false, 'changes reopen once the projection matches');
  } finally { ui.close(); }
});

test('nothing registered and a mismatch offers no Republish (there is nothing to republish)', async () => {
  const ui = await mount([view('unsigned', 'unsigned', [], false)]);
  try {
    await ui.settle();
    assert.match(ui.doc.body.textContent, /does not match the graph/);
    assert.equal(ui.button('Republish'), undefined);
    assert.equal(ui.button('Add'), undefined);
  } finally { ui.close(); }
});

test('removing asks first, states the promise, and sends only the unregister of that root', async () => {
  const ui = await mount([view('match', 'match', ['alpha']), view('match', 'match', [])]);
  try {
    await ui.settle();
    assert.equal([...ui.doc.querySelectorAll('button')].filter(item => item.textContent.trim() === 'Remove').length, 1,
      'the built-in root has no Remove');
    ui.click(ui.button('Remove'));
    await ui.settle();
    const dialog = ui.doc.querySelector('[role="dialog"]:not([aria-label="Settings"])');
    assert.ok(dialog && dialog.textContent.includes(PROMISE));
    ui.click(ui.button('Stop governing'));
    await ui.settle();
    assert.deepEqual(ui.requests[1], {action:'unregister', id:'alpha'});
  } finally { ui.close(); }
});


test('a refused session (CSRF drift) signs in again once and the read succeeds', async () => {
  const ui = await mount([{refused:'browser CSRF digest drifted'}, view('missing', 'missing')]);
  try {
    await ui.settle(80);
    assert.equal(ui.renewals.length, 1, 'one fresh sign-in');
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'list']);
    assert.ok(!ui.doc.body.textContent.includes('CSRF digest drifted'), 'the drift is not shown after renewal');
    ui.typePath('E:\\01.PERSONAL');
    await ui.settle();
    assert.equal(ui.button('Add').disabled, false, 'Add is offered once the read succeeds');
  } finally { ui.close(); }
});

test('a refused session renews once but does not replay a workspace write', async () => {
  const ui = await mount([view('missing', 'missing'), {refused:'browser CSRF digest drifted'}, view('missing', 'missing', ['beta'])]);
  try {
    await ui.settle();
    ui.typePath('D:\\Clients\\beta');
    await ui.settle();
    ui.click(ui.button('Add'));
    await ui.settle(80);
    assert.equal(ui.renewals.length, 1, 'one fresh sign-in prepares the next user attempt');
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'register']);
    assert.ok(ui.doc.body.textContent.includes('browser CSRF digest drifted'), 'the refused write is shown once');
    await ui.settle(2200);
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'register'], 'failed writes are not auto-retried');
    ui.click(ui.button('Add'));
    await ui.settle(80);
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'register', 'register']);
    assert.ok(ui.button('Remove'), 'the user retry succeeds with the renewed session');
  } finally { ui.close(); }
});

test('a second refusal after renewal is shown, never retried forever', async () => {
  const ui = await mount([{refused:'browser CSRF digest drifted'}, {refused:'browser CSRF digest drifted'}]);
  try {
    await ui.settle(80);
    assert.equal(ui.renewals.length, 1);
    assert.equal(ui.requests.length, 2);
    assert.ok(ui.doc.body.textContent.includes('browser CSRF digest drifted'));
  } finally { ui.close(); }
});

test('Browse fills the folder from the Windows dialog and registers nothing', async () => {
  const ui = await mount([view('missing', 'missing'), {ok:true, path:'E:\\01.PERSONAL'}]);
  try {
    await ui.settle();
    const browse = ui.doc.querySelector('[aria-label="Browse for a folder"]');
    assert.ok(browse, 'a Browse button sits beside the folder field');
    ui.click(browse);
    await ui.settle();
    assert.equal(ui.doc.querySelector('[aria-label="Workspace folder"]').value, 'E:\\01.PERSONAL');
    assert.deepEqual(ui.requests.map(item => item.action), ['list', 'browse'], 'Browse sends no register');
  } finally { ui.close(); }
});

test('Workspaces page removes permit profile writer and key wording from the visible UI', async () => {
  const ui = await mount([view('match', 'match', ['alpha'])]);
  try {
    await ui.settle();
    const title = [...ui.doc.querySelectorAll('div')].find(item => item.textContent.trim() === 'Workspaces');
    assert.ok(title, 'Workspaces title is visible');
    const panel = title.parentElement.parentElement;
    const text = panel.textContent;
    assert.ok(text.includes('Private workspaces are never shared publicly.'));
    assert.ok(!/permits/i.test(text), 'visible UI must not mention permits');
    assert.ok(!/Profile:/i.test(text), 'visible UI must not mention profiles');
    assert.ok(!/writers/i.test(text), 'visible UI must not mention writers');
    assert.ok(!/key/i.test(text), 'visible UI must not mention keys');
    assert.equal(ui.button('Grant claude write access'), undefined);
    assert.equal(ui.button('Revoke'), undefined);
  } finally { ui.close(); }
});

test('Add sends a slugged name, private privacy, and all agents without profile or approval wording', async () => {
  const ui = await mount([view('missing', 'missing'), view('match', 'match', ['bbc4'])]);
  try {
    await ui.settle();
    ui.typePath('E:\\01.PERSONAL\\BBC4');
    ui.typeName('BBC4');
    await ui.settle();
    ui.click(ui.button('Add'));
    await ui.settle(80);
    assert.deepEqual(ui.requests[1], {
      action:'register',
      id:'BBC4',
      path:'E:\\01.PERSONAL\\BBC4',
      privacy:'private',
      writers:AGENTS,
    });
    assert.ok(!ui.doc.body.textContent.includes('Approve the Windows prompt'));
  } finally { ui.close(); }
});

test('each workspace row has one immediate writer toggle per agent', async () => {
  const after = view('match', 'match', ['alpha']);
  after.roots[0].writers = AGENTS.filter(agent => agent !== 'codex');
  const ui = await mount([view('match', 'match', ['alpha']), after]);
  try {
    await ui.settle();
    for (const agent of AGENTS) {
      assert.ok(ui.doc.querySelector(`[aria-label="Allow ${agent} to write alpha"]`),
        `missing ${agent} writer toggle`);
    }
    const codex = ui.doc.querySelector('[aria-label="Allow codex to write alpha"]');
    assert.equal(codex.checked, true);
    ui.click(codex);
    await ui.settle(80);
    assert.deepEqual(ui.requests[1], {
      action:'update-writers',
      id:'alpha',
      writers:AGENTS.filter(agent => agent !== 'codex'),
    });
    assert.equal(ui.doc.querySelector('[aria-label="Allow codex to write alpha"]').checked, false);
  } finally { ui.close(); }
});

const pickedSession = {kind:'native-session',app:'codex',session_id:'session-exact-codex-82e79',title:'August 7 sheet work',connected:true,selectable:true,issued_at:200};
const privateView = () => ({...view('match','match',['alpha']),private_grants:[],private_grant_defaults:{operations:['edit_file','apply_patch','write_file','create'],expires_after_seconds:2592000}});
test('PRIVGRANT private row chooses one live registry session, confirms exact scope, grants and revokes server state', async () => {
  const first=privateView();
  const grant={root_id:'alpha',runtime:'codex',session_id:pickedSession.session_id,operations:first.private_grant_defaults.operations,expires_at:1800000000};
  const granted={...first,private_grants:[grant],last_private_grant_event:{action:'grant-private-root',root_id:'alpha',runtime:'codex',session_id:pickedSession.session_id,message:'unverifiable document set aside as private-root-grants.unverifiable-court.json'}};
  const ui=await mount([first,first,granted,first],{native:{ok:true,status:'ok',sessions:[{...pickedSession,session_id:'older',title:'Older',issued_at:100},pickedSession,{...pickedSession,session_id:'dead',connected:false}]}});
  try {
    await ui.settle(80);
    assert.ok(ui.button('Grant agent access'),'private root must offer grant consent');
    ui.click(ui.button('Grant agent access')); await ui.settle(80);
    const choices=[...ui.doc.querySelectorAll('[data-private-session]')];
    assert.equal(choices.length,2); assert.match(choices[0].textContent,/session-exact-codex-82e79/);
    assert.match(choices[0].textContent,/Codex|codex/); assert.match(choices[0].textContent,/August 7 sheet work/);
    ui.click(choices[0]);
    const confirm=ui.doc.querySelector('[aria-label="Confirm agent access"]');
    for(const text of ['alpha','D:\\Clients\\alpha','codex',pickedSession.session_id,'edit_file','apply_patch','write_file','create','30 days']) assert.ok(confirm.textContent.includes(text),text);
    assert.equal(ui.requests.length,2,'selection must only read');
    ui.click(ui.button('Confirm grant')); await ui.settle(80);
    assert.deepEqual(ui.requests[2],{action:'grant-private-root',id:'alpha',runtime:'codex',session_id:pickedSession.session_id});
    assert.match(ui.doc.body.textContent,/unverifiable document set aside as/);
    assert.match(ui.doc.querySelector('[data-private-grant]').textContent,/session-exact-codex-82e79/);
    assert.match(ui.doc.querySelector('[data-private-grant]').textContent,/2027/);
    ui.click(ui.button('Revoke')); await ui.settle(80);
    assert.deepEqual(ui.requests[3],{action:'revoke-private-root',id:'alpha',runtime:'codex',session_id:pickedSession.session_id});
    assert.equal(ui.doc.querySelectorAll('[data-private-grant]').length,0);
  } finally {ui.close();}
});
test('PRIVGRANT public roots have no grant; empty discovery explains absence and Cancel sends no grant', async () => {
  const publicState=privateView();publicState.roots[0].privacy='public';
  let ui=await mount([publicState]);
  try {await ui.settle(80);assert.equal(ui.button('Grant agent access'),undefined);} finally {ui.close();}
  ui=await mount([privateView(),privateView()]);
  try {await ui.settle(80);ui.click(ui.button('Grant agent access'));await ui.settle(80);assert.match(ui.doc.body.textContent,/No live agent sessions/);ui.click(ui.button('Cancel'));assert.equal(ui.requests.length,2);} finally {ui.close();}
});
