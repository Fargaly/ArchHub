const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(match => [match[1], match[2]]));

const defaultToolRows = () => [
  {id:'studio', label:'Studio', state:'running', state_word:'RUNNING', description:'Canvas, chats and graph sessions.', stat_line:'1 session.', off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio -> Brain'},
  {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING', description:'Projects, tasks and governed work.', stat_line:'0 projects.', off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop -> Studio'},
  {id:'brain', label:'Brain', state:'running', state_word:'RUNNING', description:'Memory, facts and local classification.', stat_line:'0 facts.', off_sentence:'Switched off. Nothing is remembered.', wire_summary:'Brain -> Cloud'},
  {id:'baboom', label:'BABOOM', state:'running', state_word:'RUNNING', description:'Desktop companion and approved execution.', stat_line:'Attached runtime.', off_sentence:'Switched off. No companion.', wire_summary:'BABOOM <- Studio'},
  {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING', description:'Host bridges and Speckle access.', stat_line:'0/0 hosts connected.', off_sentence:'Switched off. No host reads.', wire_summary:'Connectors -> Studio'},
  {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING', description:'Devices, grants and cloud agents.', stat_line:'Not signed in.', off_sentence:'Switched off. Works on this machine only.', wire_summary:'Cloud <- Brain'},
];

async function mountStudio({toolRows = defaultToolRows(), account = null, cloudSession = {ok:true, state:'signed_out', signed_in:false}} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-account.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, `Studio build is stale for ${source}: run npm run build:studio`);
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  if (account) win.localStorage.setItem('archhub.account.v1', JSON.stringify(account));
  win.fetch = url => String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:toolRows})})
    : String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'', readiness:{state:'no_model'}})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_TOOL_HUB = {ok:true, tools:toolRows, waiting:[]};
  win.ARCHHUB_CLOUD_SESSION = async () => cloudSession;
  win.ARCHHUB_CLOUD_SIGNIN_STATUS = async () => ({phase:'idle'});
  win.ARCHHUB_CLOUD_SIGNIN = async () => ({phase:'waiting'});
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({canvas:null, workshops:[], applicationUpdate:{state:'idle', current_build:'20261011-cloud'},
      theme:{configuration:{baboom_startup:{value:'off', source:'default', available:true}}, pending:false, error:''}}),
    subscribe:() => () => {},
    watchApplicationUpdate:() => () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[], hosts:[], connectors:[], graph:{nodes:[], wires:[]}, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 80));
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc:win.document, settle, close};
}

async function openSettingsHub(studio) {
  const settings = studio.doc.querySelector('[title="Settings"]');
  assert.ok(settings, 'Studio Settings control exists');
  studio.win.ReactDOM.flushSync(() => settings.click());
  await studio.settle();
  const theme = [...studio.doc.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Theme');
  assert.ok(theme, 'Settings sidebar exists');
  return theme.parentElement.nextElementSibling;
}

// Founder 2026-10-12: Cloud's page only restated sign-in, so an on Cloud opens Settings > Account
// (the one place that states sign-in); an off Cloud keeps its off panel in the main area.
async function openCloudTool(studio) {
  await studio.settle(); await studio.settle();
  const hub = await openSettingsHub(studio);
  const card = hub.querySelector('[data-tool-card="cloud"]');
  assert.ok(card, 'Cloud tool card exists');
  studio.win.ReactDOM.flushSync(() => card.click());
  await studio.settle(); await studio.settle();
  const page = studio.doc.querySelector('[data-tool-view="cloud"]');
  if (page) return {page};
  const account = [...studio.doc.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Account');
  assert.ok(account, 'Settings is open');
  return {settings:account.parentElement.nextElementSibling, dialog:account.parentElement.parentElement};
}

test('an on Cloud opens Settings > Account, never a full-window Cloud page', async () => {
  const studio = await mountStudio();
  try {
    const {page, settings} = await openCloudTool(studio);
    assert.equal(page, undefined, 'no full-window Cloud page');
    assert.ok(settings.textContent.includes('Continue with Google'), 'Settings > Account renders the account block');
    assert.equal(settings.textContent.includes('Cloud status'), false, 'sign-in is stated once, by the Account block');
  } finally {
    studio.close();
  }
});

test('Cloud is not on the rail; Hub still opens the same Settings > Account', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const rail = studio.doc.querySelector('[data-tool-rail="cloud"]');
    assert.equal(rail, null, 'tool icons are not rail entries');
    const settings = studio.doc.querySelector('[title="Settings"]');
    studio.win.ReactDOM.flushSync(() => settings.click());
    await studio.settle(); await studio.settle();
    const hubCloud = studio.doc.querySelector('[data-tool-card="cloud"]');
    assert.ok(hubCloud, 'Hub keeps the Cloud card');
    studio.win.ReactDOM.flushSync(() => hubCloud.click());
    await studio.settle(); await studio.settle();
    const account = [...studio.doc.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Account');
    assert.ok(account, 'Settings opened');
    assert.ok(account.parentElement.nextElementSibling.textContent.includes('Continue with Google'), 'on its Account tab');
  } finally {
    studio.close();
  }
});

test('an off Cloud opens its Settings > Hub card, never a page', async () => {
  const toolRows = defaultToolRows().map(row => row.id === 'cloud'
    ? {...row, state:'off', state_word:'OFF', empty_title:'Cloud is off', off_sentence:'Switched off. Works on this machine only.'}
    : row);
  const studio = await mountStudio({toolRows});
  try {
    const {page, dialog} = await openCloudTool(studio);
    assert.equal(page, undefined, 'no full-window off panel (CP1)');
    assert.ok(dialog.querySelector('[data-tool-card="cloud"]'), 'the Hub shows the Cloud card');
    assert.doesNotMatch(dialog.textContent, /Cloud status/);
  } finally {
    studio.close();
  }
});

test('Cloud never renders internal cloud fields or raw JSON in Settings', async () => {
  const toolRows = defaultToolRows().map(row => row.id === 'cloud'
    ? {...row, state:'running', state_word:'SIGNED IN', stat_line:'Signed in as owner@example.com.',
      wire_summary:'Cloud <- Brain', node_id:'cloud-id-7', access_token:'tok-abc', token_path:'C:/sec/tok.txt',
      raw_json:'{"ok":true}'}
    : row);
  const studio = await mountStudio({toolRows, account:{signedIn:true, email:'owner@example.com'}});
  try {
    const {dialog} = await openCloudTool(studio);
    const text = dialog.textContent;
    for (const leak of [/node_id/, /cloud-id-7/, /access_token/, /tok-abc/, /token_path/, /C:\/sec\/tok\.txt/, /raw_json/, /\{"ok":true\}/]) {
      assert.doesNotMatch(text, leak);
    }
  } finally {
    studio.close();
  }
});
