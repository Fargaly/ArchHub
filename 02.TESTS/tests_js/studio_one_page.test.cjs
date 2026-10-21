const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
/* UI audit 2026-09-28 (work/ui-audit 08-back-navigation, 13-ctrl-k): the Studio is the whole window.
     P1  Alt+Left, Alt+Right and the Back / Forward keys are refused by the page (the launcher also
         empties the history behind /studio; 02.TESTS/tests_replica/test_studio_window_is_one_page.py);
     P2  the mouse's Back / Forward buttons (3, 4) are refused;
     P3  Ctrl+K opens the command bar, and Esc closes it;
     P4  the Studio opens on Canvas; Chat moved into the selection inspector composer and
         Workshop opens from the Settings Hub tool card, not a Studio header tab. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function mountStudio({workshops = [], unavailable, models} = {}) {
  const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  // Only the model listing may answer; every other request stays pending, as an unanswered server would.
  win.fetch = url => String(url).includes('/api/universal/models') && models
    ? Promise.resolve({ok:true, json:() => Promise.resolve(models)}) : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[], wires:[]};
  const listeners = new Set();
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization,
      ...(unavailable === undefined ? {} : {unavailable})}, workshops,
    applicationUpdate:{state:'idle', current_build:'20260923-r8'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const owner = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    watchApplicationUpdate:() => () => {},
  };
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner, {get:(target, key) => key in target || typeof key !== 'string' ||
    key === 'then' ? target[key] : () => new Promise(() => {})});
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('01.APP/nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const segment = label => label === 'Workshop' ? doc.querySelector('button[aria-label="Open the Workshop"]') :
    [...doc.querySelectorAll('button[aria-pressed]')].find(button => button.textContent.trim() === label);
  const inWorkshop = () => !doc.querySelector('button[aria-label="Open the Workshop"]');
  const spoken = () => [...doc.querySelectorAll('[role="alert"], [role="status"]')].map(node => node.textContent.trim()).join(' | ');
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {doc, win, flush, segment, spoken, close, inWorkshop};
}

test('P1/P2: Back keys and mouse Back / Forward buttons never navigate the Studio away', async () => {
  const studio = await mountStudio();
  try {
    for (const init of [{key:'ArrowLeft', altKey:true}, {key:'ArrowRight', altKey:true}, {key:'BrowserBack'}, {key:'BrowserForward'}]) {
      const event = new studio.win.KeyboardEvent('keydown', {...init, bubbles:true, cancelable:true});
      studio.flush(() => studio.doc.body.dispatchEvent(event));
      assert.equal(event.defaultPrevented, true, JSON.stringify(init) + ' is refused');
    }
    const plain = new studio.win.KeyboardEvent('keydown', {key:'ArrowLeft', bubbles:true, cancelable:true});
    studio.flush(() => studio.doc.body.dispatchEvent(plain));
    assert.equal(plain.defaultPrevented, false, 'a plain arrow key is left alone');
    for (const button of [3, 4]) {
      for (const type of ['mousedown', 'mouseup', 'auxclick']) {
        const event = new studio.win.MouseEvent(type, {button, bubbles:true, cancelable:true});
        studio.doc.body.dispatchEvent(event);
        assert.equal(event.defaultPrevented, true, type + ' of mouse button ' + button + ' is refused');
      }
    }
  } finally { studio.close(); }
});

test('P3: Ctrl+K opens the command bar; Esc closes it', async () => {
  const studio = await mountStudio();
  try {
    const library = () => studio.doc.querySelector('[data-command-bar]');
    assert.equal(library(), null, 'closed at start');
    const event = new studio.win.KeyboardEvent('keydown', {key:'k', ctrlKey:true, bubbles:true, cancelable:true});
    studio.flush(() => studio.win.dispatchEvent(event));
    assert.equal(event.defaultPrevented, true, 'Ctrl+K is answered');
    assert.ok(library(), 'Ctrl+K draws the command bar');
    assert.ok(library().textContent.includes('Add node'), 'command bar includes Add node group');
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    assert.equal(library(), null, 'Esc closes it again');
  } finally { studio.close(); }
});

test('P4: the Studio opens on Canvas; Chat input moved to the selection panel and Workshop to the Settings Hub card', async () => {
  const studio = await mountStudio({workshops:[{root:'general-a', label:'Workshop', is_general:true}]});
  try {
    assert.ok(studio.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), 'Canvas is the default session view');
    const headerButtons = [...studio.doc.querySelectorAll('main > div button')].map(button => button.textContent.trim());
    for (const moved of ['Chat', 'Workshop', 'System']) assert.equal(headerButtons.includes(moved), false,
      moved + ' moved out of the Studio session header');
    assert.equal(studio.doc.querySelectorAll('input[aria-label="Ask selection"]').length, 1,
      'Chat moved to the single selection-panel composer');
    studio.flush(() => studio.doc.querySelector('[title="All sessions"]').click());
    studio.flush(() => studio.doc.querySelector('[data-rail-panel="Settings"]').click());
    const settle = async () => { await new Promise(resolve => studio.win.setTimeout(resolve, 20)); };
    await settle();
    const hub = await settingsNavigator({doc:studio.doc, flush:studio.flush, settle}).tab('Hub');
    assert.ok(hub.querySelector('[data-tool-card="workshop"]'), 'Workshop is reached from Settings Connections Hub');
  } finally { studio.close(); }
});
