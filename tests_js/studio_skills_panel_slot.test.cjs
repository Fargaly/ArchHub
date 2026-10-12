const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function mountStudio(loadSkills) {
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
  win.AH_LIBRARY = [];
  win.ARCHHUB_LOAD_SKILLS = loadSkills;
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:[], connectors:[], graph:{nodes:[], wires:[]}, memory:[], skills:[]};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({canvas:null, workshops:[], applicationUpdate:{state:'idle', current_build:'20261012-k1'},
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

// R11 / gate row RL: a rail page opens in the panel slot, never inside the 44px rail column.
for (const [name, loader] of [
  ['while the catalogue is still loading', () => new Promise(() => {})],
  ['after the catalogue failed', async () => { throw new Error('skills endpoint down'); }],
  ['after the catalogue loaded', async () => [{id:'qa', name:'Door schedule QA', runs:3, args:'level', when:'today'}]],
]) {
  test('Skills opens as one panel beside the rail ' + name, async () => {
    const studio = await mountStudio(loader);
    try {
      const button = studio.doc.querySelector('[title="Skills"]');
      assert.ok(button, 'Skills rail button exists');
      studio.flush(() => button.click());
      await studio.settle();
      const aside = button.closest('aside');
      assert.ok(aside, 'the rail sits in the Sidebar grid');
      assert.equal(aside.children.length, 2, 'the Sidebar grid ("44px 1fr") holds exactly the rail and one panel, so the panel takes the 1fr column');
      const panel = aside.children[1];
      assert.ok(panel.textContent.includes('Skills'), 'the Skills heading is inside the panel slot');
      for (const line of aside.querySelectorAll('[role=status],[role=alert]')) {
        assert.ok(panel.contains(line), 'catalogue status lines live inside the panel, not beside it');
      }
    } finally { studio.close(); }
  });
}
