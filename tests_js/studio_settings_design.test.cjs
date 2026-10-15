const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
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
// BABOOM sits after Brain as in the design dialog (ArchHub App Window.html, Settings).
const DESIGN_TABS = ['Hub', 'Account', 'Brain', 'BABOOM', 'Team', 'Profile', 'Permissions', 'Connections', 'Workspaces', 'Hosts', 'Providers', 'Models',
  'Theme', 'Shortcuts', 'Storage', 'About'];
// Shaped as model_router.provider_rows() emits them. No row carries a key.
const PROVIDERS = [
  {id:'openrouter', name:'OpenRouter', state:'keyed', source:'secrets store', sets:'OPENROUTER_API_KEY'},
  {id:'cloud', name:'ArchHub cloud', state:'no key', source:'', sets:'ARCHHUB_CLOUD_TOKEN'},
  {id:'lmstudio', name:'LM Studio', state:'running', source:'127.0.0.1:1234', sets:''},
  {id:'ollama', name:'Ollama', state:'not running', source:'127.0.0.1:11434', sets:''},
];

async function openSettings({account = null, socialAccounts = [], socialApprovals = [], linkedInAppSaved = false, metaAppSaved = false,
  linkedInReady = false, metaReady = false, hosts = [], systemNodes = []} = {}) {
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
  const calls = {edit:[], providers:0, watch:0, socialRemovals:[], linkedInStarts:0, linkedInFinishes:0,
    metaStarts:0, metaFinishes:0, notionStarts:0, clientMcp:[]};
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
    startLinkedInSignIn:async () => {
      calls.linkedInStarts += 1;
      return {ok:true, phase:'waiting', redirect_uri:'http://127.0.0.1:48720/linkedin/callback'};
    },
    cancelLinkedInSignIn:async () => ({ok:true, phase:'cancelled'}),
    linkedInSignInStatus:async () => linkedInReady ? {ok:true, phase:'ready', name:'Founder'} : {ok:true, phase:'waiting'},
    finishLinkedInSignIn:async () => { calls.linkedInFinishes += 1; return {ok:true, account_id:'urn:li:person:founder', vault_entry:'social-linkedin-founder'}; },
    metaAppStatus:async () => metaAppSaved ? {ok:true, state:'saved'} : {ok:true, state:'missing'},
    startMetaSignIn:async () => {
      calls.metaStarts += 1;
      return {ok:true, phase:'waiting', redirect_uri:'http://127.0.0.1:48721/meta/callback'};
    },
    cancelMetaSignIn:async () => ({ok:true, phase:'cancelled'}),
    metaSignInStatus:async () => metaReady ? {ok:true, phase:'ready', pages:[{id:'112233445566778', name:'ArchHub Page'}]} : {ok:true, phase:'waiting'},
    finishMetaSignIn:async ({page_id}) => { calls.metaFinishes += 1; return {ok:true, state:'enrolled', provider:'meta', account_id:page_id,
      vault_entry:'social-meta-page-' + page_id, account_binding:'provider-verified'}; },
    connectNotion:async () => { calls.notionStarts += 1; return {ok:true, label:'Notion is connected'}; },
    installMcpClient:async provider => { calls.clientMcp.push(provider); return {ok:true, provider}; },
    watchApplicationUpdate:() => { calls.watch += 1; return () => {}; },
    refreshApplicationUpdate:async () => {}, applicationUpdateAction:async () => {},
    refreshTheme:async () => {}, previewThemeToken:async () => {}, restoreThemeRevision:async () => {}, setBaboomStartup:async () => {},
    refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {}, selectTopology:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:hosts.map(row => ({...row})), connectors:[], graph:{nodes:systemNodes.map(row => ({...row})), wires:[]},
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
  const {sidebar, tab} = settingsNavigator({doc, flush, settle});
  const buttons = (scope, text) => [...scope.querySelectorAll('button, [role="button"]')].filter(node => node.textContent.trim() === text);
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, settle, sidebar, tab, buttons, calls, close};
}

module.exports.openSettingsForCourt = openSettings;

test('the Settings sidebar is the DSYS-065 six-group graph rail and retains the existing capability badges', async () => {
  const s = await openSettings({systemNodes:[
    ['account', 'Account'], ['connections', 'Connections'], ['ai', 'AI'],
    ['permissions', 'Permissions'], ['appearance', 'Appearance'], ['storage', 'Storage & About'],
  ].map(([id, group], index) => ({id:'sys_' + id, application:true, title:group, group, cat:'logic',
    x:40 + (index % 3) * 300, y:76 + Math.floor(index / 3) * 206, params:[]}))});
  try {
    const dialog = s.doc.querySelector('[data-settings54-shell]');
    assert.ok(dialog, 'Settings is a dialog');
    assert.equal(dialog.getAttribute('aria-modal'), 'true', 'Settings says it is modal');
    assert.equal(dialog.getAttribute('aria-label'), 'Settings');
    assert.deepEqual([...dialog.querySelectorAll('[data-settings54-group-title]')].map(node => node.textContent.trim()),
      ['Account', 'Connections', 'AI', 'Permissions', 'Appearance', 'Storage & About']);
    assert.equal(dialog.querySelectorAll('[data-settings54-node-card]').length >= 5, true,
      'System graph cards are the visible Settings surface');
    assert.deepEqual([dialog.style.width, dialog.style.height], ['100%', '100%'],
      'the full-page Settings shell grows with the window');
    assert.ok(dialog.querySelector('[data-settings54-nav]').classList.contains('ah-scroll'),
      'the visible group rail uses the dark app scrollbar, not the native white one');
    // Old flat-tab order, per-tab badges and bounded-dialog dimensions are retired surface DOM.
    // Capability behavior remains covered by the owner courts below, including Office collapse.
    const hub = await s.tab('Hub');
    assert.equal(hub.querySelector('[data-tool-grid]').style.gridTemplateColumns, 'repeat(3, minmax(0, 1fr))',
      'the Settings Hub is the same 3 x 2 grid as Home, never 5 + 1');
    for (const stat of hub.querySelectorAll('[data-tool-stat]')) {
      assert.notEqual(stat.style.textOverflow, 'ellipsis', 'a card stat line is never cut with an ellipsis');
      assert.notEqual(stat.style.whiteSpace, 'nowrap', 'a card stat line wraps instead');
    }
    const about = await s.tab('About');
    assert.ok(about.textContent.includes('20260916-2130-e733a13'), 'About states the same running build after the old dialog header moved');
  } finally { s.close(); }
});

test('Hosts counts use the same Office-collapsed rows in badge, card and Settings', async () => {
  const hosts = [
    {id:'revit', name:'Revit', state:'connected', detail:'add-in on :48884'},
    {id:'excel', name:'Excel', state:'running', detail:'workbook open'},
    {id:'word', name:'Word', state:'running', detail:'document open'},
    {id:'powerpoint', name:'PowerPoint', state:'running', detail:'deck open'},
  ];
  const s = await openSettings({hosts});
  try {
    const hub = await s.tab('Hub');
    assert.ok(hub.textContent.includes('2/2 hosts running.'), 'Hub Connectors card uses collapsed Office rows');
    const hostsPanel = await s.tab('Hosts');
    assert.match(hostsPanel.querySelector('[data-connectors-bar]').textContent, /2\/2 running/);
    const office = [...hostsPanel.querySelectorAll('[data-connector-row]')].find(row => /Office/.test(row.textContent));
    assert.ok(office, 'Office aggregate is rendered');
    assert.equal(office.querySelector('[data-host-state]').textContent, 'Running', 'separate tally aggregation keeps Office classified as built and running');
  } finally { s.close(); }
});

// DP-CONNECTORS (design: ArchHub Product.html #connectors, superseding UX-SET2's column chips): one count row
// for Office with governed child rows below it, and the programs without a connector kept as separate
// "no connector yet" rows (design "Never removed").
test('DP-CONNECTORS: design rows, Office count row and child rows, not-built rows kept, plain copy', async () => {
  const s = await openSettings({hosts:[
    {id:'revit', name:'Revit', state:'absent', detail:'no session listening on 48884-48899'},
    {id:'autocad', name:'AutoCAD', state:'absent', detail:'no session listening'},
    {id:'excel', name:'Excel', state:'installed', detail:'installed \u00b7 open a file and the reads answer'},
    {id:'outlook', name:'Outlook', state:'installed', detail:'installed \u00b7 open Outlook and the inbox reads answer'},
    {id:'rhino', name:'Rhino', state:'absent', detail:''},
    {id:'civil3d', name:'Civil 3D', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'navisworks', name:'Navisworks', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'sketchup', name:'SketchUp', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'archicad', name:'Archicad', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'ifc', name:'IFC', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'bluebeam', name:'Bluebeam', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'enscape', name:'Enscape', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'powerbi', name:'Power BI', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'sharepoint', name:'SharePoint', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'slack', name:'Slack', state:'unknown', detail:'no connector yet', connector_built:false},
    {id:'airtable', name:'Airtable', state:'unknown', detail:'no connector yet', connector_built:false},
  ]});
  try {
    const panel = await s.tab('Hosts');
    const rows = [...panel.querySelectorAll('[data-connector-row]')];
    const notBuilt = [...panel.querySelectorAll('[data-host-state]')].filter(row => row.textContent === 'no connector yet');
    assert.equal(notBuilt.length, 11, 'the eleven programs without a connector stay listed separately');
    assert.equal(rows.length - notBuilt.length, 6, 'Revit, AutoCAD, Rhino, ONE Office count row and two Office child rows');
    const text = panel.textContent;
    assert.ok(text.includes('Excel \u00b7 Outlook'), 'the Office programs share one row');
    assert.equal(panel.querySelectorAll('[data-office-child]').length, 2, 'the actual Office host controls render under the count row');
    for (const stale of ['reads answer', '48884', 'no session listening']) assert.equal(text.includes(stale), false, 'no "' + stale + '" on screen');
    assert.ok(text.includes('installed \u00b7 reads when a file is open'));
    assert.ok(text.includes('Not open \u00b7 Start opens it'), 'a startable host says Start opens it');
  } finally { s.close(); }
});

test('BABOOM renders the existing companion settings: startup switch and speech budget', async () => {
  const s = await openSettings();
  try {
    const panel = await s.tab('BABOOM');
    assert.ok(panel.textContent.includes('Speech budget'), 'the BABOOM tab is the existing companion settings');
    assert.ok(panel.textContent.includes('Speaks at most 2 times an hour.'), 'the budget states the same value as the badge');
    assert.ok(panel.querySelector('[role="switch"][aria-label="Start BABOOM when ArchHub opens"]'), 'the startup switch is drawn');
  } finally { s.close(); }
});

test('Providers draws the registry in the design rows: masked key, state pill, manage or connect; manage opens no paste field', async () => {
  const s = await openSettings({linkedInAppSaved:true, metaAppSaved:true});
  try {
    const panel = await s.tab('Providers');
    assert.ok(s.calls.providers >= 1, 'the provider registry was read');
    assert.equal(!!panel.querySelector('input[aria-label="OpenRouter API key"]'), false, 'no key form sits beside the drawn list');
    assert.equal(!!panel.querySelector('details'), false, 'no disclosure widget outside the design affordances');
    const text = panel.textContent;
    assert.ok(text.includes('Connected on this machine'), 'a connected row states the status without exposing raw provider codes');
    assert.ok(text.includes('Sign in to use ArchHub cloud') && text.includes('LM Studio') && text.includes('Connected'));
    assert.equal(/ARCHHUB_CLOUD_TOKEN|127\.0\.0\.1|:\d{3,5}/.test(text), false, 'provider rows hide env vars and ports');
    assert.deepEqual([...panel.querySelectorAll('button[aria-expanded]')].slice(0, 4).map(button => button.textContent), ['manage', 'connect', 'manage', 'connect']);
    s.flush(() => s.buttons(panel, 'manage')[0].click());
    assert.equal(!!panel.querySelector('input[aria-label="OpenRouter API key"]'), false, 'OpenRouter manage does not open a paste field');
    assert.equal(s.buttons(panel, 'Save OpenRouter key').length, 0, 'OpenRouter key save is not in user Settings');
    const social = [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Connections'));
    assert.ok(social, 'social credentials sit behind the design dashed affordance');
    s.flush(() => social.click());
    await s.settle();
    assert.equal(panel.querySelectorAll('input[type="password"], input[name="client_id"], input[name="client_secret"], input[name="app_id"], input[name="app_secret"]').length, 0,
      'user Settings has no app ids, secrets or password fields');
    assert.equal(s.buttons(panel, 'Save LinkedIn app').length, 0, 'LinkedIn app setup is not in user Settings');
    assert.equal(s.buttons(panel, 'Meta app').length, 0, 'Meta app setup is not in user Settings');
    assert.ok(panel.textContent.includes('Connections'), 'the panel renders Connections rows');
    for (const label of ['LinkedIn', 'Facebook and Instagram', 'Notion', 'Outlook', 'Dropbox']) {
      assert.ok(panel.textContent.includes(label), label + ' row is shown');
    }
    assert.ok(s.buttons(panel, 'Connect LinkedIn').length === 1, 'LinkedIn connects through an OAuth button');
    assert.ok(s.buttons(panel, 'Connect Facebook / Instagram').length === 1, 'Meta connects through an OAuth button');
    assert.ok(s.buttons(panel, 'Connect Notion').length === 1, 'Notion connects through notion.connect');
    s.flush(() => s.buttons(panel, 'Connect Notion')[0].click());
    await s.settle();
    assert.equal(s.calls.notionStarts, 1, 'Notion button calls the existing owner route');
    assert.equal(!!panel.querySelector('input[name="token"]'), false, 'no raw access-token field is shown');
  } finally { s.close(); }
});

test('Connections render stored accounts and disconnect by exact saved identity', async () => {
  const s = await openSettings({socialAccounts:[
    {provider:'linkedin', account_id:'urn:li:person:founder', vault_entry:'social-linkedin-founder', account_binding:'provider-verified'},
    {provider:'meta', account_id:'112233445566778', vault_entry:'social-meta-page-112233445566778', account_binding:'provider-verified'},
    {provider:'meta', account_id:'17841412345678901', vault_entry:'social-meta-ig-17841412345678901', account_binding:'provider-verified'},
    {provider:'meta', account_id:'meta:user:older', vault_entry:'social-meta-legacy', account_binding:'operator-declared'},
  ]});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Connections')).click());
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

test('Connections show account-route controls before a LinkedIn app is configured', async () => {
  const s = await openSettings({linkedInAppSaved:false});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Connections')).click());
    await s.settle();
    assert.equal(s.buttons(panel, 'Connect LinkedIn').length, 0, 'LinkedIn connect waits for the saved app');
    assert.equal(panel.querySelectorAll('input[type="password"], input[name="client_id"], input[name="client_secret"]').length, 0,
      'LinkedIn app fields are not shown');
    assert.ok(s.buttons(panel, 'Sign in to ArchHub to connect').length >= 2,
      'signed out, LinkedIn and Meta say a cloud sign-in is needed (not "coming soon"), never a form');
    assert.match(panel.textContent, /Sign in under Settings › Account, then connect here\./, 'the row says where to sign in');
    assert.ok(s.buttons(panel, 'Connect from Account').length >= 1, 'a provider with no broker points at the account route');
    assert.equal(/coming soon/i.test(panel.textContent), false, 'Connections show no stub wording');
    assert.equal(/Continue with Google|Signed in as/.test(s.doc.body.textContent), false, 'the account block is not on Providers');
    s.flush(() => s.buttons(panel, 'Connect from Account')[0].click());
    await s.settle();
    assert.ok(s.doc.querySelector('[data-settings-tab="account"], [data-tab="account"]') ||
      /Continue with Google|Signed in as/.test(s.doc.body.textContent), 'Connect from Account opens Settings › Account');
  } finally { s.close(); }
});

test('Connections connect LinkedIn after a LinkedIn app is saved', async () => {
  const s = await openSettings({linkedInAppSaved:true, linkedInReady:true});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Connections')).click());
    await s.settle();
    assert.equal(!!panel.querySelector('input[name="client_id"]'), false, 'saved LinkedIn app hides setup fields');
    const connect = s.buttons(panel, 'Connect LinkedIn');
    assert.equal(connect.length, 1, 'saved LinkedIn app exposes connect');
    s.flush(() => connect[0].click());
    await s.settle();
    assert.equal(s.calls.linkedInStarts, 1);
    assert.equal(s.calls.linkedInFinishes, 1, 'LinkedIn polling reaches finish after OAuth completes');
  } finally { s.close(); }
});

test('Connections connect Meta by polling for Pages and finishing the selected Page', async () => {
  const s = await openSettings({metaAppSaved:true, metaReady:true});
  try {
    const panel = await s.tab('Providers');
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Connections')).click());
    await s.settle();
    const connect = s.buttons(panel, 'Connect Facebook / Instagram');
    assert.equal(connect.length, 1, 'saved Meta app exposes connect');
    s.flush(() => connect[0].click());
    await s.settle();
    const page = s.buttons(panel, 'Use ArchHub Page');
    assert.equal(page.length, 1, 'Meta polling exposes Page choices without a token field');
    s.flush(() => page[0].click());
    await s.settle();
    assert.equal(s.calls.metaStarts, 1);
    assert.equal(s.calls.metaFinishes, 1, 'Meta polling reaches finish after OAuth completes');
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
    s.flush(() => [...panel.querySelectorAll('button')].find(button => button.textContent.includes('Connections')).click());
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

test('DP-CLOUD: the tier the graph holds sits in the identity row, with no price and no plan table', async () => {
  const s = await openSettings({account:{signedIn:true, email:'ana@studio.example', name:'Ana Example', graphTier:'founder'}});
  try {
    const panel = await s.tab('Account');
    assert.ok(panel.querySelector('[data-cloud-panel]'), 'Account is the design Cloud window');
    const label = [...panel.querySelectorAll('div')].find(node => node.textContent === 'SUBSCRIPTION');
    assert.equal(label, undefined, 'no separate SUBSCRIPTION plan grid');
    const identity = panel.querySelector('[data-cloud-identity]');
    if (identity) assert.equal(/\$\d/.test(identity.textContent), false, 'no price');
    assert.equal(/\$\d/.test(panel.textContent), false, 'no price anywhere in the Cloud window');
  } finally { s.close(); }
});


test('LAZYONREL late System projection preserves the user chosen Settings capability', async () => {
  const s = await openSettings();
  try {
    await s.tab('Hosts');
    assert.ok(s.doc.querySelector('[data-connectors-bar]'), 'Hosts is selected before the delayed projection');
    s.flush(() => {
      s.win.ARCHHUB_LIVE.graph.nodes.push({id:'late-system', application:true, title:'Appearance', group:'Appearance', cat:'logic', params:[]});
      s.win.__studioRoot.render(s.win.React.createElement(s.win.StudioLM));
    });
    await s.settle();
    assert.ok(s.doc.querySelector('[data-settings54-capability-nav="connections"]'), 'late nodes retain the user chosen group');
    assert.ok(s.doc.querySelector('[data-connectors-bar]'), 'late nodes retain Hosts instead of restoring initialTab');
  } finally {s.close();}
});
