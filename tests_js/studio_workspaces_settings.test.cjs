/* Settings > Workspaces behaves by the registry's real state: changes are offered only when
   the start-up check and the current read agree, a pending check is read again until it
   answers, a failed read can be retried, and a mismatch pauses changes and offers Republish.
   The shipped compiled Studio in a real browser DOM; the one route is a court stand-in. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)]
  .map(match => [match[1], match[2]]));
const PROMISE = 'Removing a workspace only stops ArchHub from governing it. Your files are never deleted.';

const view = (boot, projection, roots = [], pinned = roots.length > 0) => ({
  ok:true, revision:1, boot, projection, key_pinned:pinned, promise:PROMISE,
  built_in:{id:'archhub', path:'C:\\Users\\fargaly\\00.ARCHUB', removable:false},
  roots:roots.map(id => ({root_id:id, path:'D:\\Clients\\' + id, privacy:'private', profile:'client',
    writers:['claude'], state:'registered', registered_at:'2026-09-29T00:00:00Z'})),
});

async function mount(answers) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  let JSDOM;
  try { ({JSDOM} = require('jsdom')); } catch (error) { ({JSDOM} = await import('jsdom')); }
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const requests = [];
  win.fetch = (url, options = {}) => {
    if (String(url) !== '/api/universal/workspace-roots') return new Promise(() => {});
    const body = JSON.parse(options.body || '{}');
    requests.push(body);
    const answer = answers.shift();
    if (!answer) return new Promise(() => {});
    if (answer === 'fail') return Promise.resolve({ok:false, json:async () => ({ok:false, error:'registry unreachable'})});
    return Promise.resolve({ok:true, json:async () => answer});
  };
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const click = element => win.eval('(el => ReactDOM.flushSync(() => el.click()))')(element);
  click(doc.querySelector('[title="Settings"]'));
  const tab = [...doc.querySelectorAll('button')].find(button => button.textContent.trim().startsWith('Workspaces'));
  assert.ok(tab, 'Settings offers the Workspaces tab');
  click(tab);
  const settle = async (ms = 30) => { await new Promise(resolve => setTimeout(resolve, ms)); };
  const button = label => [...doc.querySelectorAll('button')].find(item => item.textContent.trim() === label);
  const typePath = value => {
    const input = doc.querySelector('[aria-label="Workspace folder"]');
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    win.eval('(el => ReactDOM.flushSync(() => el.dispatchEvent(new Event("input", {bubbles:true}))))')(input);
  };
  return {win, doc, requests, click, settle, button, typePath,
    close: () => { win.eval('window.__studioRoot.unmount()'); win.close(); }};
}

test('a pending start-up check offers no change, is read again, and opens changes when it matches', async () => {
  const ui = await mount([view('checking', 'missing'), view('checking', 'missing'), view('missing', 'missing')]);
  try {
    await ui.settle();
    ui.typePath('D:\\Clients\\alpha');
    await ui.settle();
    assert.equal(ui.button('Add').disabled, true, 'Add stays off while the check is pending');
    assert.equal(ui.button('Republish'), undefined, 'no Republish while the first check is pending');
    ui.click(ui.button('Add'));
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
    assert.equal(ui.button('Add').disabled, true, 'no change after a failed read');
    ui.click(ui.button('Add'));
    await ui.settle();
    assert.deepEqual(ui.requests.map(item => item.action), ['list']);
    ui.click(ui.button('Read again'));
    await ui.settle();
    assert.equal(ui.button('Add').disabled, false);
    assert.ok(ui.button('Remove'), 'the registered root is listed after the retry');
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
    assert.equal(ui.button('Add').disabled, true);
    assert.equal(ui.button('Remove').disabled, true);
    ui.click(ui.button('Remove'));
    await ui.settle();
    assert.equal(ui.doc.querySelector('[role="dialog"]'), null, 'no confirmation while paused');
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
    assert.equal(ui.button('Add').disabled, true);
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
    const dialog = ui.doc.querySelector('[role="dialog"]');
    assert.ok(dialog && dialog.textContent.includes(PROMISE));
    ui.click(ui.button('Stop governing'));
    await ui.settle();
    assert.deepEqual(ui.requests[1], {action:'unregister', id:'alpha'});
  } finally { ui.close(); }
});
