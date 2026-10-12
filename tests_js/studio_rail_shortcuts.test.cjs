const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

const LIBRARY = [
  {cat:'logic', items:[{id:'number', title:'Number', sub:'constant value', engine:'data.constant'}]},
  {cat:'ai', items:[{id:'ask', title:'Ask model', sub:'model request', engine:'ai.ask'}]},
];
const SKILLS = [
  {id:'dim', name:'Dimension walls in active view', runs:14, args:'scale, min_length', when:'today'},
  {id:'qa', name:'Door schedule QA', runs:38, args:'level', when:'yesterday'},
];
const EXPECTED_SHORTCUTS = [
  ['open-node-library', 'Open the node catalogue', 'Global', 'Ctrl/Cmd+K'],
  ['toggle-settings', 'Toggle settings', 'Global', 'Ctrl/Cmd+,'],
  ['open-documentation', 'Open documentation', 'Global', 'Ctrl/Cmd+/'],
  ['close-overlays', 'Close settings, docs, or catalogue', 'Global', 'Esc'],
  ['canvas-open-menu', 'Open canvas menu', 'Canvas', 'Menu / Shift+F10'],
  ['canvas-select-all', 'Select all nodes', 'Canvas', 'Ctrl/Cmd+A'],
  ['canvas-add-node', 'Add node from library', 'Canvas', 'Ctrl/Cmd+L'],
  ['canvas-fit-graph', 'Fit graph to view', 'Canvas', 'Ctrl/Cmd+0'],
  ['canvas-zoom-100', 'Zoom to 100%', 'Canvas', 'Ctrl/Cmd+1'],
  ['canvas-auto-layout', 'Auto-layout', 'Canvas', 'Ctrl/Cmd+Shift+L'],
  ['canvas-undo', 'Undo', 'Canvas', 'Ctrl/Cmd+Z'],
  ['canvas-redo', 'Redo', 'Canvas', 'Ctrl/Cmd+Shift+Z / Ctrl/Cmd+Y'],
  ['canvas-fit-selection', 'Fit selection or all', 'Canvas', 'F'],
  ['canvas-move-selection', 'Move selected nodes', 'Canvas', 'Arrows / Shift+Arrows'],
  ['canvas-cut-wire', 'Cut selected wire', 'Canvas', 'Delete / Backspace'],
];

async function mountStudio() {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/free'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:[]})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.AH_LIBRARY = LIBRARY.map(group => ({...group, items:group.items.map(item => ({...item}))}));
  win.ARCHHUB_LOAD_SKILLS = async () => SKILLS.map(skill => ({...skill}));
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:[], connectors:[], graph:{nodes:[], wires:[]}, memory:[], skills:[]};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({canvas:null, workshops:[], applicationUpdate:{state:'idle', current_build:'20261012-rail-z'},
      theme:{configuration:{theme:{...seed}}, pending:false, error:''}}),
    subscribe:() => () => {},
    watchApplicationUpdate:() => () => {},
  };
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async () => { for (let i = 0; i < 8; i += 1) await new Promise(resolve => win.setTimeout(resolve, 0)); };
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc:win.document, flush, settle, close};
}

test('Settings Shortcuts renders the explicit handled shortcut list and filters it', async () => {
  const studio = await mountStudio();
  try {
    assert.ok(Array.isArray(studio.win.STUDIO_SHORTCUT_BINDINGS), 'shortcut binding table is exported');
    const settings = studio.doc.querySelector('[title="Settings"]');
    assert.ok(settings, 'Settings rail button exists');
    studio.flush(() => settings.click());
    await studio.settle();
    const shortcutTab = [...studio.doc.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Shortcuts');
    assert.ok(shortcutTab, 'Settings has the Shortcuts tab');
    studio.flush(() => shortcutTab.click());
    await studio.settle();
    const panel = shortcutTab.parentElement.nextElementSibling;
    const rows = () => [...panel.querySelectorAll('[data-shortcut-id]')];
    const rowValues = () => rows().map(row => {
      const spans = row.querySelectorAll('span');
      return [row.getAttribute('data-shortcut-id'), spans[0].textContent, spans[1].textContent, row.querySelector('kbd').textContent];
    });
    assert.deepEqual(rowValues(), EXPECTED_SHORTCUTS);
    assert.equal(/coming soon|placeholder|stub/i.test(panel.textContent), false, 'Shortcuts has no stub language');

    const filter = panel.querySelector('input[aria-label="Filter shortcuts"]');
    assert.ok(filter, 'Shortcuts has a filter box');
    const setValue = Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set;
    studio.flush(() => {
      setValue.call(filter, 'documentation');
      filter.dispatchEvent(new studio.win.Event('input', {bubbles:true}));
    });
    await studio.settle();
    assert.deepEqual(rowValues(), [['open-documentation', 'Open documentation', 'Global', 'Ctrl/Cmd+/']], 'filter narrows to the matching shortcut');
  } finally { studio.close(); }
});

test('global keydown actions are driven by the exported shortcut table', async () => {
  const studio = await mountStudio();
  try {
    const send = (id, init) => {
      assert.ok(studio.win.STUDIO_SHORTCUT_BINDINGS.some(binding => binding.id === id), id + ' binding exists');
      studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {
        bubbles:true, cancelable:true, ...init,
      })));
    };
    send('open-node-library', {key:'k', ctrlKey:true});
    await studio.settle();
    assert.ok([...studio.doc.querySelectorAll('span')].some(node => node.textContent === 'Node library'), 'Ctrl+K opens the node library overlay');
    send('open-documentation', {key:'/', ctrlKey:true});
    await studio.settle();
    assert.ok(studio.doc.body.textContent.includes('Getting started'), 'Ctrl+/ opens documentation');
    // UX-DOC1 (installed 2248, 07): Getting started matches the shipped app.
    const docs = studio.doc.body.textContent;
    for (const stale of ['get.archhub.app', 'archhub doctor', 'archhub up', ':7300', 'session spend', 'macOS', '~/.archhub', 'OS keychain']) {
      assert.equal(docs.includes(stale), false, 'Getting started no longer says ' + stale);
    }
    assert.match(studio.doc.querySelector('[data-docs-install]').textContent, /Windows installer from archhub\.io/);
    assert.match(studio.doc.querySelector('[data-docs-strip]').textContent, /local server, how many hosts are running/);
    send('toggle-settings', {key:',', ctrlKey:true});
    await studio.settle();
    assert.ok([...studio.doc.querySelectorAll('button')].some(button => button.firstElementChild?.textContent === 'Hub'), 'Ctrl+, opens Settings');
  } finally { studio.close(); }
});
