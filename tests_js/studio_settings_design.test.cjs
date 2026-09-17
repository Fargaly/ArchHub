/* Settings is the design's dialog: the shell, the twelve tabs and each tab's drawn layout come from
   archhub/project studio-lm.jsx:2403-3142 and studio-account.jsx:362-465. Only seeded values are
   replaced (provider registry, Personal Settings, release status, account tier, the brain's facts),
   and shipped-only controls sit inside the design's own affordances: a provider row's manage/connect,
   the accent row's change, the About "updates" link, a fact's own text, a row in the Hosts list.
   Real browser DOM in memory; no application, provider or network. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(match => [match[1], match[2]]));
const DESIGN_TABS = ['Account', 'Brain', 'Team', 'Profile', 'Permissions', 'Hosts', 'Providers', 'Models', 'Theme',
  'Shortcuts', 'Storage', 'About'];
// Shaped as model_router.provider_rows() emits them. No row carries a key.
const PROVIDERS = [
  {id:'openrouter', name:'OpenRouter', state:'keyed', source:'secrets store', sets:'OPENROUTER_API_KEY'},
  {id:'cloud', name:'ArchHub cloud', state:'no key', source:'', sets:'ARCHHUB_CLOUD_TOKEN'},
  {id:'lmstudio', name:'LM Studio', state:'running', source:'127.0.0.1:1234', sets:''},
  {id:'ollama', name:'Ollama', state:'not running', source:'127.0.0.1:11434', sets:''},
];

async function openSettings({account = null} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-account.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, `Studio build is stale for ${source}: run npm run build:studio`);
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {}); // court sandbox: the server never answers
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  if (account) win.localStorage.setItem('archhub.account.v1', JSON.stringify(account));
  const calls = {edit:[], providers:0, watch:0};
  win.prompt = () => 'Rewritten fact.';
  win.ARCHHUB_BRAIN_EDIT = async (id, text) => { calls.edit.push([id, text]); return {ok:true}; };
  win.ARCHHUB_BRAIN_FORGET = async () => ({ok:true});
  const listeners = new Set();
  const snapshot = {canvas:null, workshops:[], applicationUpdate:{state:'idle', current_build:'20260916-2130-e733a13'},
    theme:{configuration:{theme:{...seed}, binding_mode:'personal-wip', state:'WIP', history:[], personal_wip_heads:['head-a'],
      baboom_startup:{value:'on', source:'default', revision:null, available:true, control:'c', event_fact_input:'i'}}, pending:false, error:''}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    readProviders:async () => { calls.providers += 1; return PROVIDERS.map(row => ({...row})); },
    saveProviderKey:async () => ({ok:true}),
    watchApplicationUpdate:() => { calls.watch += 1; return () => {}; },
    refreshApplicationUpdate:async () => {}, applicationUpdateAction:async () => {},
    refreshTheme:async () => {}, previewThemeToken:async () => {}, restoreThemeRevision:async () => {}, setBaboomStartup:async () => {},
    refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {}, selectTopology:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:[], connectors:[], graph:{nodes:[], wires:[]},
    memory:[{id:'m1', text:'Real fact read from the brain.', src:'folder'}], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async () => { for (let i = 0; i < 5; i += 1) await new Promise(resolve => win.setTimeout(resolve, 0)); };
  const opener = doc.querySelector('[title="Settings"]');
  assert.ok(opener, 'actual Studio Settings control exists');
  flush(() => opener.click());
  await settle();
  const anchor = [...doc.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Theme');
  assert.ok(anchor, 'actual Settings sidebar exists');
  const sidebar = anchor.parentElement;
  const tab = async label => {
    const button = [...sidebar.children].find(child => child.firstElementChild?.textContent === label);
    assert.ok(button, 'the sidebar has the ' + label + ' tab');
    flush(() => button.click());
    await settle();
    return sidebar.nextElementSibling;
  };
  const buttons = (scope, text) => [...scope.querySelectorAll('button, [role="button"]')].filter(node => node.textContent.trim() === text);
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, settle, sidebar, tab, buttons, calls, close};
}

test('the Settings sidebar is the design tab table, in the design order, and states the live badges', async () => {
  const s = await openSettings();
  try {
    assert.deepEqual([...s.sidebar.children].map(child => child.firstElementChild.textContent), DESIGN_TABS);
    const badge = label => [...s.sidebar.children].find(child => child.firstElementChild.textContent === label).children[1]?.textContent || null;
    assert.equal(badge('Providers'), '1 key', 'the Providers badge counts the keyed registry rows');
    assert.equal(badge('Theme'), 'Dark', 'the Theme badge states the mode the Studio draws');
    assert.equal(badge('Brain'), '4 strata \u00b7 1 facts');
    assert.ok(s.doc.body.textContent.includes('STUDIO \u00b7 20260916-2130-e733a13'), 'the dialog header states the running build');
  } finally { s.close(); }
});

test('Providers draws the registry in the design rows: masked key, state pill, manage or connect; the key form opens from manage', async () => {
  const s = await openSettings();
  try {
    const panel = await s.tab('Providers');
    assert.ok(s.calls.providers >= 1, 'the provider registry was read');
    assert.equal(!!panel.querySelector('input[aria-label="OpenRouter API key"]'), false, 'no key form sits beside the drawn list');
    assert.equal(!!panel.querySelector('details'), false, 'no disclosure widget outside the design affordances');
    const text = panel.textContent;
    assert.ok(text.includes('\u2022'.repeat(12) + ' \u00b7 key from the secrets store'), 'a keyed row draws a masked key slot');
    assert.ok(text.includes('no key \u00b7 set ARCHHUB_CLOUD_TOKEN') && text.includes('127.0.0.1:1234 \u00b7 local runtime'));
    assert.deepEqual([...panel.querySelectorAll('button[aria-expanded]')].slice(0, 4).map(button => button.textContent), ['manage', 'connect', 'manage', 'connect']);
    s.flush(() => s.buttons(panel, 'manage')[0].click());
    assert.ok(panel.querySelector('input[aria-label="OpenRouter API key"]'), 'OpenRouter manage opens the key form');
    assert.equal(s.buttons(panel, 'Save OpenRouter key')[0].disabled, true, 'nothing to save before a key is typed');
    const social = [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Social account credentials'));
    assert.ok(social, 'social credentials sit behind the design dashed affordance');
    s.flush(() => social.click());
    assert.ok(panel.querySelector('input[name="vault_entry"]'), 'the social credential form opens from it');
  } finally { s.close(); }
});

test('Theme: the Dark card is selected, and the saved-theme editor lives inside the accent row change', async () => {
  const s = await openSettings();
  try {
    const panel = await s.tab('Theme');
    const card = name => [...panel.querySelectorAll('button')].find(button => button.textContent.startsWith(name + ' ') || button.textContent.startsWith(name));
    const [system, dark, light] = ['System', 'Dark', 'Light'].map(card);
    assert.ok(system && dark && light, 'the three design theme cards are drawn');
    assert.notEqual(dark.style.borderColor, light.style.borderColor, 'the Dark card carries the selected border');
    assert.equal(system.style.borderColor, light.style.borderColor, 'only one card is selected');
    assert.equal(!!panel.querySelector('[aria-label="Refresh Personal Settings"]'), false, 'no status strip above the design cards');
    assert.equal(panel.textContent.includes('VERSIONS'), false);
    assert.ok(panel.textContent.includes(seed.accent + ' \u00b7 saved in Personal Settings'), 'the accent row states the saved accent');
    s.flush(() => s.buttons(panel, 'change')[0].click());
    assert.ok(panel.querySelector('[aria-label="Refresh Personal Settings"]'), 'change opens the saved-theme editor');
    assert.ok(s.buttons(panel, 'Save accent').length === 1 && panel.querySelector('input[aria-label="Accent hex colour"]'));
  } finally { s.close(); }
});

test('Brain: a fact is rewritten from its own text; the rows and the export row carry only the design buttons', async () => {
  const s = await openSettings();
  try {
    const panel = await s.tab('Brain');
    const names = [...panel.querySelectorAll('button')].map(button => button.textContent);
    assert.equal(names.includes('edit'), false, 'no per-fact edit button beside the design forget');
    assert.equal(names.includes('add fact'), false, 'no add fact button in the design export row');
    const fact = [...panel.querySelectorAll('[title="Rewrite this memory"]')].find(node => node.textContent === 'Real fact read from the brain.');
    assert.ok(fact, 'the fact text is the rewrite affordance');
    s.flush(() => fact.click());
    await s.settle();
    assert.deepEqual(s.calls.edit, [['m1', 'Rewritten fact.']], 'the brain edit bridge receives the rewrite');
  } finally { s.close(); }
});

test('Storage, Models and About state no seeded measurement; About opens the release controls from its updated line', async () => {
  const s = await openSettings();
  try {
    const storage = (await s.tab('Storage')).textContent;
    for (const seeded of ['2.1 GB', '186 MB', '5.4 GB']) assert.equal(storage.includes(seeded), false, 'Storage carries no seeded ' + seeded);
    const models = (await s.tab('Models')).textContent;
    for (const seeded of ['$3 / $15', 'Claude Sonnet 4.5', 'Gemini 2.5 Pro', 'qwen2.5-coder']) assert.equal(models.includes(seeded), false, 'Models carries no seeded ' + seeded);
    const about = await s.tab('About');
    for (const seeded of ['1.4.0-prototype', 'localhost:7300', 'Anthropic, OpenAI']) assert.equal(about.textContent.includes(seeded), false, 'About carries no seeded ' + seeded);
    assert.ok(about.textContent.includes('version     20260916-2130-e733a13') || about.textContent.includes('20260916-2130-e733a13'), 'About states the running build');
    assert.equal(!!about.querySelector('section[aria-label="Application release updates"]'), false, 'the release controls wait behind the updated line');
    s.flush(() => s.buttons(about, 'updates \u2192')[0].click());
    assert.ok(about.querySelector('section[aria-label="Application release updates"]'), 'updates opens the release controls');
  } finally { s.close(); }
});

test('Account: the tier the graph holds is the design current plan card, with no price or plan table', async () => {
  const s = await openSettings({account:{signedIn:true, email:'ana@studio.example', name:'Ana Example', graphTier:'founder'}});
  try {
    const panel = await s.tab('Account');
    const label = [...panel.querySelectorAll('div')].find(node => node.textContent === 'SUBSCRIPTION');
    assert.ok(label, 'the SUBSCRIPTION block is drawn for a held tier');
    const grid = label.nextElementSibling;
    assert.equal(grid.style.gridTemplateColumns, 'repeat(3,1fr)', 'the design plan grid');
    assert.equal(grid.children.length, 1, 'one card: the plan the account holds, never a plan table');
    assert.ok(grid.textContent.startsWith('founder \u00b7 current'), grid.textContent);
    assert.equal(/\$\d/.test(grid.textContent), false, 'no price');
  } finally { s.close(); }
});
