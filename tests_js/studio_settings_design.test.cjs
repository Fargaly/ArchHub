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
// Workspaces (274e4f2a) registers the folders the graph governs; it sits after Permissions.
const DESIGN_TABS = ['Account', 'Brain', 'Team', 'Profile', 'Permissions', 'Workspaces', 'Hosts', 'Providers', 'Models',
  'Theme', 'Shortcuts', 'Storage', 'About'];
// Shaped as model_router.provider_rows() emits them. No row carries a key.
const PROVIDERS = [
  {id:'openrouter', name:'OpenRouter', state:'keyed', source:'secrets store', sets:'OPENROUTER_API_KEY'},
  {id:'cloud', name:'ArchHub cloud', state:'no key', source:'', sets:'ARCHHUB_CLOUD_TOKEN'},
  {id:'lmstudio', name:'LM Studio', state:'running', source:'127.0.0.1:1234', sets:''},
  {id:'ollama', name:'Ollama', state:'not running', source:'127.0.0.1:11434', sets:''},
];

async function openSettings({account = null, socialAccounts = [], socialApprovals = [], linkedInAppSaved = false} = {}) {
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
  const calls = {edit:[], providers:0, watch:0, socialRemovals:[], linkedInAppSaves:[], linkedInStarts:0};
  let heldSocialAccounts = socialAccounts.map(row => ({...row}));
  win.prompt = () => 'Rewritten fact.';
  win.ARCHHUB_BRAIN_EDIT = async (id, text) => { calls.edit.push([id, text]); return {ok:true}; };
  win.ARCHHUB_BRAIN_FORGET = async () => ({ok:true});
  const listeners = new Set();
  const snapshot = {canvas:null, workshops:[], applicationUpdate:{state:'idle', current_build:'20260916-2130-e733a13'},
    theme:{configuration:{theme:{...seed},
      // As the canvas projection sends it (universal_application._project_offered_themes).
      design_system:{themes:{offered:[{name:'forge', label:'Default dark warm surface'}], active:'forge'}},
      binding_mode:'personal-wip', state:'WIP', history:[], personal_wip_heads:['head-a'],
      baboom_startup:{value:'on', source:'default', revision:null, available:true, control:'c', event_fact_input:'i'}}, pending:false, error:''}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    readProviders:async () => { calls.providers += 1; return PROVIDERS.map(row => ({...row})); },
    saveProviderKey:async () => ({ok:true}),
    listLocalSocialAccounts:async () => heldSocialAccounts.map(row => ({...row})),
    removeLocalSocialAccount:async body => {
      calls.socialRemovals.push({...body});
      heldSocialAccounts = heldSocialAccounts.filter(row =>
        row.provider !== body.provider || row.account_id !== body.account_id || row.vault_entry !== body.vault_entry);
      return {ok:true, ...body, state:'removed', provider_token_revoked:false, graph_reference_retained:true};
    },
    listSocialApprovals:async () => socialApprovals.map(row => ({...row})),
    decideSocialApproval:async ({delegation, input_digest, decision}) => ({
      ok:true, delegation, input_digest, decision:decision === 'approve' ? 'approved' : 'denied'}),
    linkedInAppStatus:async () => linkedInAppSaved ? {ok:true, state:'saved', client_id:'86abc123xyz'} : {ok:true, state:'missing'},
    saveLinkedInApp:async body => {
      calls.linkedInAppSaves.push({...body});
      linkedInAppSaved = true;
      return {ok:true, client_id:body.client_id};
    },
    startLinkedInSignIn:async () => {
      calls.linkedInStarts += 1;
      return {ok:true, phase:'waiting', redirect_uri:'http://127.0.0.1:48720/linkedin/callback'};
    },
    cancelLinkedInSignIn:async () => ({ok:true, phase:'cancelled'}),
    linkedInSignInStatus:async () => ({ok:true, phase:'waiting'}),
    finishLinkedInSignIn:async () => ({ok:true, account_id:'urn:li:person:founder', vault_entry:'social-linkedin-founder'}),
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
    assert.ok(text.includes('Key saved on this machine'), 'a keyed row states the saved key without exposing it');
    assert.ok(text.includes('Sign in to use ArchHub cloud') && text.includes('Local runtime is running'));
    assert.equal(/ARCHHUB_CLOUD_TOKEN|127\.0\.0\.1|:\d{3,5}/.test(text), false, 'provider rows hide env vars and ports');
    assert.deepEqual([...panel.querySelectorAll('button[aria-expanded]')].slice(0, 4).map(button => button.textContent), ['manage', 'connect', 'manage', 'connect']);
    s.flush(() => s.buttons(panel, 'manage')[0].click());
    assert.ok(panel.querySelector('input[aria-label="OpenRouter API key"]'), 'OpenRouter manage opens the key form');
    assert.equal(s.buttons(panel, 'Save OpenRouter key')[0].disabled, true, 'nothing to save before a key is typed');
    const social = [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Social account credentials'));
    assert.ok(social, 'social credentials sit behind the design dashed affordance');
    s.flush(() => social.click());
    assert.ok(panel.querySelector('input[name="client_id"]'), 'LinkedIn shows app setup before OAuth connect');
    assert.ok(s.buttons(panel, 'Save LinkedIn app').length === 1, 'LinkedIn app setup saves through Settings');
    assert.ok(s.buttons(panel, 'Connect Facebook / Instagram').length === 1, 'Meta connects through an OAuth button');
    assert.equal(!!panel.querySelector('input[name="token"]'), false, 'no raw access-token field is shown');
  } finally { s.close(); }
});

test('Social account credentials render stored accounts and disconnect by exact saved identity', async () => {
  const s = await openSettings({socialAccounts:[
    {provider:'linkedin', account_id:'urn:li:person:founder', vault_entry:'social-linkedin-founder', account_binding:'provider-verified'},
    {provider:'meta', account_id:'112233445566778', vault_entry:'social-meta-page-112233445566778', account_binding:'provider-verified'},
    {provider:'meta', account_id:'17841412345678901', vault_entry:'social-meta-ig-17841412345678901', account_binding:'provider-verified'},
    {provider:'meta', account_id:'meta:user:older', vault_entry:'social-meta-legacy', account_binding:'operator-declared'},
  ]});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Social account credentials')).click());
    await s.settle();
    assert.ok(panel.textContent.includes('Connected accounts'), 'stored credentials have a visible list');
    for (const label of ['LinkedIn', 'Facebook Page', 'Instagram', 'Meta']) {
      assert.ok(panel.textContent.includes(label), label + ' account row is shown');
    }
    const buttons = [...panel.querySelectorAll('button')].filter(button => button.textContent.trim() === 'Disconnect');
    assert.equal(buttons.length, 4, 'one Disconnect per stored account');
    s.flush(() => buttons[2].click());
    await s.settle();
    assert.deepEqual(s.calls.socialRemovals, [{
      provider:'meta',
      account_id:'17841412345678901',
      vault_entry:'social-meta-ig-17841412345678901',
    }]);
  } finally { s.close(); }
});

test('Social account credentials show LinkedIn app setup before a LinkedIn app is saved', async () => {
  const s = await openSettings({linkedInAppSaved:false});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Social account credentials')).click());
    await s.settle();
    assert.equal(s.buttons(panel, 'Connect LinkedIn').length, 0, 'LinkedIn connect waits for the saved app');
    assert.ok(panel.querySelector('input[name="client_id"]'), 'LinkedIn Client ID field is shown');
    assert.ok(panel.querySelector('input[name="client_secret"]'), 'LinkedIn Client Secret field is shown');
    const id = panel.querySelector('input[name="client_id"]');
    const secret = panel.querySelector('input[name="client_secret"]');
    s.flush(() => { id.value = '86abc123xyz'; secret.value = 'secret-value-1'; });
    s.flush(() => s.buttons(panel, 'Save LinkedIn app')[0].click());
    await s.settle();
    assert.deepEqual(s.calls.linkedInAppSaves, [{client_id:'86abc123xyz', client_secret:'secret-value-1'}]);
  } finally { s.close(); }
});

test('Social account credentials connect LinkedIn after a LinkedIn app is saved', async () => {
  const s = await openSettings({linkedInAppSaved:true});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Social account credentials')).click());
    await s.settle();
    assert.equal(!!panel.querySelector('input[name="client_id"]'), false, 'saved LinkedIn app hides setup fields');
    const connect = s.buttons(panel, 'Connect LinkedIn');
    assert.equal(connect.length, 1, 'saved LinkedIn app exposes connect');
    s.flush(() => connect[0].click());
    await s.settle();
    assert.equal(s.calls.linkedInStarts, 1);
  } finally { s.close(); }
});

test('Social approval account confirmation names the provider being approved', async () => {
  const approvals = [
    {delegation:'app:baboom-connector-delegation:li', work:'w1', operation:'linkedin.post', account_id:'urn:li:person:founder',
      input_digest:'d1', review_text:'LinkedIn post', expires_at:9999999999, account_binding:'provider-verified'},
    {delegation:'app:baboom-connector-delegation:fb', work:'w2', operation:'facebook.page_post', account_id:'112233445566778',
      input_digest:'d2', review_text:'Facebook post', expires_at:9999999999, account_binding:'provider-verified'},
    {delegation:'app:baboom-connector-delegation:ig', work:'w3', operation:'instagram.media_publish', account_id:'17841412345678901',
      input_digest:'d3', review_text:'Instagram post', expires_at:9999999999, account_binding:'provider-verified'},
  ];
  const s = await openSettings({socialApprovals:approvals});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Social account credentials')).click());
    await s.settle();
    for (const label of ['account confirmed by LinkedIn', 'account confirmed by Facebook', 'account confirmed by Instagram']) {
      assert.ok(panel.textContent.includes(label), label);
    }
  } finally { s.close(); }
});

test('Theme: only the offered themes are cards, the active one is marked, and the saved-theme editor lives inside the accent row change', async () => {
  // 8623a579: Settings > Theme draws one card per theme the graph offers
  // (configuration.design_system.themes), not three fixed System/Dark/Light cards.
  const s = await openSettings();
  try {
    const panel = await s.tab('Theme');
    const cards = [...panel.querySelectorAll('[data-theme-cards] [data-theme]')];
    assert.deepEqual(cards.map(card => card.dataset.theme), ['forge'], 'one card per offered theme');
    assert.equal(cards[0].getAttribute('aria-current'), 'true', 'the active theme is marked');
    assert.equal(cards[0].tagName, 'DIV', 'no switch route exists yet, so a card is display-only, never a dead button (founder 2026-10-08)');
    assert.ok(cards[0].textContent.includes('Default dark warm surface · active'));
    for (const name of ['System', 'Light']) {
      assert.equal([...panel.querySelectorAll('button')].some(button => button.textContent.startsWith(name)), false,
        name + ' is not drawn: the graph cannot paint it');
    }
    assert.equal(!!panel.querySelector('[aria-label="Refresh Personal Settings"]'), false, 'no status strip above the theme cards');
    assert.equal(panel.textContent.includes('VERSIONS'), false);
    assert.ok(panel.textContent.includes(seed.accent + ' · saved in Personal Settings'), 'the accent row states the saved accent');
    s.flush(() => s.buttons(panel, 'change')[0].click());
    assert.ok(panel.querySelector('[aria-label="Refresh Personal Settings"]'), 'change opens the saved-theme editor');
    assert.ok(s.buttons(panel, 'Apply accent').length === 1 && panel.querySelector('input[aria-label="Accent hex colour"]'));
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
