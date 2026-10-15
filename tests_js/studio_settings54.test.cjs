const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(match => [match[1], match[2]]));

function systemProjection() {
  const nodes = [
    {id:'sys_account', application:true, title:'Account', group:'Account', cat:'logic', x:20, y:44, w:240,
      params:[{k:'identity', label:'Identity', v:'local', editable:false}]},
    {id:'sys_connections', application:true, title:'Connections', group:'Connections', cat:'tools', x:320, y:44, w:240,
      outs:[{id:'relay', label:'relay', t:'event'}], params:[{k:'relay_state', label:'Relay state', v:'open', editable:false}]},
    {id:'sys_ai', application:true, title:'BABOOM', group:'AI', cat:'ai', x:620, y:44, w:240,
      ins:[{id:'relay', label:'relay', t:'event'}], outs:[{id:'speech', label:'speech', t:'number'}],
      params:[{k:'speech_budget_per_hour', label:'Speech budget', v:2, type:'number', unit:'per hour'}]},
    {id:'sys_permissions', application:true, title:'Permissions', group:'Permissions', cat:'logic', x:320, y:252, w:240,
      ins:[{id:'speech', label:'speech', t:'number'}], params:[{k:'permission_store', label:'Permission store', v:'backend', editable:false}]},
    {id:'sys_appearance', application:true, title:'UI & Design System', group:'Appearance', cat:'display', x:20, y:252, w:260,
      outs:[{id:'theme', label:'theme', t:'view'}], params:[
        {k:'theme', label:'Theme', v:'dark', options:['dark', 'light', 'system']},
        {k:'density', label:'Density', v:'comfortable', options:['comfortable', 'compact', 'spacious']},
        {k:'text_size', label:'Text size', v:14, type:'number', unit:'px'},
      ]},
    {id:'sys_storage', application:true, title:'Storage & About', group:'Storage & About', cat:'data', x:620, y:252, w:240,
      ins:[{id:'theme', label:'theme', t:'view'}], params:[{k:'release_channel', label:'Version', v:'b1', editable:false}]},
  ];
  return {
    canvas:{graph_id:'app', application_root:'app', root:'app', revision:7, authorization:{system_view:true}},
    graph:{nodes, wires:[
      {id:'w-theme-storage', from:['sys_appearance', 'theme'], to:['sys_storage', 'theme']},
      {id:'w-relay-ai', from:['sys_connections', 'relay'], to:['sys_ai', 'relay']},
      {id:'w-ai-perms', from:['sys_ai', 'speech'], to:['sys_permissions', 'speech']},
    ]},
  };
}

async function openSettings({permissionRows, permissionReadFails = false, exposePermissionWriter = true,
  exposeParamWriter = true, socialAccounts = [], socialApprovals = [], signedIn = false, cloudAllowed = false,
  projectionOverride = null} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-account.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, `Studio build is stale for ${source}: run npm run build:studio`);
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53954/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  if (signedIn) win.localStorage.setItem('archhub.account.v1', JSON.stringify({signedIn:true, email:'af@example.com', firm:'ArchHub'}));
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const projection = projectionOverride || systemProjection();
  const listeners = new Set();
  const backendRows = permissionRows ?? [
    {actor:'Cloud relay consent', kind:'consent', read:'Allow', write:'Ask', send:'Ask'},
    {actor:'Social approval queue', kind:'approval', read:'Allow', write:'Ask', send:'Ask'},
  ];
  const calls = {setNodeProp:[], moveMany:[], readPermissionRows:0, setPermission:[], cloudConsent:[], socialDecision:[], socialRemove:[]};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({applicationUpdate:{state:'idle', current_build:'b1'}, theme:{configuration:{theme:{...seed}, binding_mode:'personal-wip', state:'WIP', history:[], personal_wip_heads:['head-a']}}, pending:false, error:''}),
    subscribe:fn => { listeners.add(fn); return () => listeners.delete(fn); },
    readProviders:async () => [{id:'openrouter', name:'OpenRouter', state:'keyed'}],
    watchApplicationUpdate:() => () => {},
    readCloudPublishConsent:async () => ({allowed:cloudAllowed, account:'af@example.com'}),
    setCloudPublishConsent:async allowed => { calls.cloudConsent.push(allowed); return {allowed, account:'af@example.com'}; },
    listSocialApprovals:async () => socialApprovals.map(row => ({...row})),
    decideSocialApproval:async body => { calls.socialDecision.push({...body}); return {ok:true}; },
    listLocalSocialAccounts:async () => socialAccounts.map(row => ({...row})),
    removeLocalSocialAccount:async body => { calls.socialRemove.push({...body}); return {ok:true}; },
  };
  if (permissionRows !== null) {
    win.ARCHHUB_EXISTING_WORKSHOP.readSettingsPermissionRows = async () => {
      calls.readPermissionRows += 1;
      if (permissionReadFails) throw new Error('permission store unavailable');
      return backendRows.map(row => ({...row}));
    };
    if (exposePermissionWriter) win.ARCHHUB_EXISTING_WORKSHOP.setSettingsPermission = async row => {
      calls.setPermission.push({...row});
      return {ok:true, ...row};
    };
  }
  win.ARCHHUB_STUDIO_AUTHORITY = {
    getSnapshot:() => ({...projection, applicationUpdate:{state:'idle', current_build:'b1'}, pending:false, error:''}),
    subscribe:fn => { listeners.add(fn); return () => listeners.delete(fn); },
    moveMany:async (positions, revision, expected, placement) => {
      calls.moveMany.push({positions, revision, expected, placement});
      for (const node of projection.graph.nodes) if (positions[node.id]) Object.assign(node, positions[node.id]);
      listeners.forEach(fn => fn());
      return {ok:true};
    },
  };
  if (exposeParamWriter) {
    win.ARCHHUB_SET_NODE_PROP = async (id, key, value) => {
      calls.setNodeProp.push({id, key, value});
      const node = projection.graph.nodes.find(item => item.id === id);
      const row = node?.params?.find(item => item.k === key);
      if (row) row.v = value;
      listeners.forEach(fn => fn());
      return {ok:true};
    };
  }
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:[], connectors:[], graph:projection.graph, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async () => { for (let i = 0; i < 8; i += 1) await new Promise(resolve => win.setTimeout(resolve, 0)); };
  const opener = doc.querySelector('[title="Settings"]');
  assert.ok(opener, 'actual Settings control exists');
  flush(() => opener.click());
  await settle();
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, settle, calls, close};
}

async function openSettingsCapability(s, groupLabel, capabilityLabel) {
  const shell = s.doc.querySelector('[data-settings54-shell]');
  const group = [...shell.querySelectorAll('button')].find(button =>
    button.querySelector('[data-settings54-group-title]')?.textContent.trim() === groupLabel);
  assert.ok(group, groupLabel + ' group is visible');
  s.flush(() => group.click());
  await s.settle();
  const button = [...shell.querySelectorAll(`[data-settings54-capability-nav] button`)]
    .find(item => item.textContent.trim() === capabilityLabel);
  assert.ok(button, capabilityLabel + ' capability is visible under ' + groupLabel);
  s.flush(() => button.click());
  await s.settle();
  assert.equal(shell.querySelector('[data-settings54-capability]')?.getAttribute('data-settings54-capability'), capabilityLabel);
  return shell;
}

test('SETTINGS-54 p3: Settings shell renders admitted System nodes and real endpoint wires', async () => {
  const s = await openSettings();
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    assert.ok(shell, 'Settings renders the SETTINGS-54 shell');
    assert.deepEqual([...shell.querySelectorAll('[data-settings54-group-title]')].map(node => node.textContent.trim()),
      ['Account', 'Connections', 'AI', 'Permissions', 'Appearance', 'Storage & About']);
    const cards = [...shell.querySelectorAll('[data-settings54-node-card]')];
    assert.ok(cards.length >= 6, 'real projected System nodes render');
    assert.ok(cards.every(card => card.getAttribute('data-settings54-node-id')?.startsWith('sys_')), 'cards carry projected ids');
    const ports = new Set([...shell.querySelectorAll('[data-settings54-port]')].map(port => port.getAttribute('data-settings54-port')));
    const wires = [...shell.querySelectorAll('[data-settings54-wire]')].map(wire => wire.getAttribute('data-settings54-wire'));
    assert.deepEqual(wires, ['sys_appearance:theme->sys_storage:theme', 'sys_connections:relay->sys_ai:relay', 'sys_ai:speech->sys_permissions:speech']);
    for (const wire of wires) {
      const [from, to] = wire.split('->');
      assert.ok(ports.has(from), 'wire source port exists: ' + from);
      assert.ok(ports.has(to), 'wire target port exists: ' + to);
    }
    assert.equal(shell.textContent.includes('Add node'), false, 'Settings has no Add node chrome');
    assert.match(shell.textContent, /Connected/);
  } finally { s.close(); }
});

test('SETTINGS-54 p3: find focuses matches and inspector controls post real System parameter writes', async () => {
  const s = await openSettings();
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    const find = shell.querySelector('input[aria-label="Find a setting"]');
    s.flush(() => { find.value = 'Density'; find.dispatchEvent(new s.win.Event('input', {bubbles:true})); });
    await s.settle();
    assert.equal(shell.querySelector('[data-settings54-graph]').getAttribute('data-settings54-focus'), 'sys_appearance');
    const properties = [...shell.querySelectorAll('button')].find(button => button.textContent.trim() === 'Properties');
    s.flush(() => properties.click());
    await s.settle();
    const density = [...shell.querySelectorAll('[data-settings54-param-row]')].find(row => row.textContent.includes('Density')).querySelector('select');
    s.flush(() => { density.value = 'compact'; density.dispatchEvent(new s.win.Event('change', {bubbles:true})); });
    await s.settle();
    assert.deepEqual(s.calls.setNodeProp.at(-1), {id:'sys_appearance', key:'density', value:'compact'});
    const reread = [...shell.querySelectorAll('[data-settings54-param-row]')].find(row => row.textContent.includes('Density')).querySelector('select');
    assert.equal(reread.value, 'compact', 're-read projection shows the written value');
    const arrange = [...shell.querySelectorAll('button')].find(button => button.textContent.trim() === 'Arrange');
    s.flush(() => arrange.click());
    await s.settle();
    assert.equal(s.calls.moveMany.at(-1).placement, 'arrange');
  } finally { s.close(); }
});

test('SETTINGS-54 p3: permissions render backend rows only and use backend writer only', async () => {
  const s = await openSettings({permissionRows:[
    {actor:'Cloud relay consent', kind:'consent', read:'Allow', write:'Ask', send:'Ask'},
    {actor:'Social approval queue', kind:'approval', read:'Allow', write:'Ask', send:'Ask'},
  ]});
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    const permButton = [...shell.querySelectorAll('button')].find(button => button.textContent.includes('Permissions'));
    s.flush(() => permButton.click());
    await s.settle();
    const rows = [...shell.querySelectorAll('[data-permission-row]')];
    assert.deepEqual(rows.map(row => row.querySelector('span span')?.textContent || row.textContent.trim().split(/\s+/)[0]),
      ['Cloud relay consent', 'Social approval queue']);
    for (const actor of ['Claude Code', 'Codex', 'OpenCode', 'BABOOM']) {
      assert.equal(rows.some(row => row.textContent.includes(actor)), false, actor + ' is not synthesized');
    }
    const allow = rows[1].querySelector('[data-permission-col="Write"] [data-seg-control] button:nth-child(2)');
    s.flush(() => allow.click());
    await s.settle();
    assert.deepEqual(s.calls.setPermission.at(-1), {actor:'Social approval queue', column:'write', value:'Allow'});
  } finally { s.close(); }
});

test('SETTINGS-54 p3: missing permission authority is explicit OPEN, with no synthetic rows', async () => {
  const s = await openSettings({permissionRows:null});
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    const permButton = [...shell.querySelectorAll('button')].find(button => button.textContent.includes('Permissions'));
    s.flush(() => permButton.click());
    await s.settle();
    assert.equal(shell.querySelectorAll('[data-permission-row]').length, 0);
    assert.match(shell.textContent, /Per-agent permissions: not available yet/);
  } finally { s.close(); }
});

test('SETTINGS-54 p4: every former Settings capability has a visible click path and no hidden compat DOM', async () => {
  const s = await openSettings();
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    const paths = [
      ['Account', 'Account'], ['Account', 'Profile'], ['Account', 'Team'],
      ['Connections', 'Hub'], ['Connections', 'Hosts'], ['Connections', 'Providers'],
      ['AI', 'BABOOM'], ['AI', 'Models'], ['AI', 'Brain'],
      ['Permissions', 'Permissions'], ['Permissions', 'Workspaces'],
      ['Appearance', 'Theme'], ['Appearance', 'Shortcuts'], ['Appearance', 'System'],
      ['Storage & About', 'Storage'], ['Storage & About', 'About'],
    ];
    for (const [group, label] of paths) await openSettingsCapability(s, group, label);
    await openSettingsCapability(s, 'Appearance', 'Theme');
    assert.equal(shell.querySelector('[data-settings54-graph]').getAttribute('data-settings54-focus'), 'sys_appearance',
      'full projection still selects the real Appearance node');
    assert.equal(shell.querySelectorAll('[style*="display: none"]').length, 0, 'Settings shell has no hidden compatibility DOM');
    const source = read('nodelang/studio/studio-lm.jsx');
    assert.doesNotMatch(source, /compatTabs|compatPanel/);
  } finally { s.close(); }
});

test('SETTINGS-54 p5: sparse projection keeps group capabilities reachable without fallback node selection', async () => {
  const sparse = systemProjection();
  sparse.graph.nodes = sparse.graph.nodes.filter(node => node.id === 'sys_account');
  sparse.graph.wires = [];
  const s = await openSettings({projectionOverride:sparse});
  try {
    const shell = await openSettingsCapability(s, 'Appearance', 'Theme');
    assert.equal(shell.querySelector('[data-settings54-graph]').getAttribute('data-settings54-focus'), '',
      'Appearance does not select the fallback Account node');
    assert.match(shell.textContent, /No live node for Appearance yet/);
    await openSettingsCapability(s, 'Appearance', 'Shortcuts');
    assert.equal(shell.querySelector('[data-settings54-graph]').getAttribute('data-settings54-focus'), '',
      'Shortcuts stays on empty node selection when Appearance has no live node');
  } finally { s.close(); }
});

test('SETTINGS-54 p5: empty projection still exposes every group capability', async () => {
  const empty = systemProjection();
  empty.graph.nodes = [];
  empty.graph.wires = [];
  const s = await openSettings({projectionOverride:empty});
  try {
    const paths = [
      ['Account', 'Account'], ['Account', 'Profile'], ['Account', 'Team'],
      ['Connections', 'Hub'], ['Connections', 'Hosts'], ['Connections', 'Providers'],
      ['AI', 'BABOOM'], ['AI', 'Models'], ['AI', 'Brain'],
      ['Permissions', 'Permissions'], ['Permissions', 'Workspaces'],
      ['Appearance', 'Theme'], ['Appearance', 'Shortcuts'], ['Appearance', 'System'],
      ['Storage & About', 'Storage'], ['Storage & About', 'About'],
    ];
    for (const [group, label] of paths) {
      const shell = await openSettingsCapability(s, group, label);
      assert.equal(shell.querySelector('[data-settings54-graph]').getAttribute('data-settings54-focus'), '',
        label + ' does not fabricate a selected node');
    }
  } finally { s.close(); }
});

test('SETTINGS-54 p4: Permissions keeps existing consent, social disconnect and approval routes visible without new permission backend', async () => {
  const s = await openSettings({
    permissionRows:null,
    signedIn:true,
    cloudAllowed:true,
    socialAccounts:[{provider:'linkedin', account_id:'urn:li:person:af', vault_entry:'social-linkedin-af', display_name:'AF'}],
    socialApprovals:[{delegation:'delegation-a', input_digest:'d'.repeat(64), operation:'linkedin.post', account_id:'urn:li:person:af', account_binding:'provider-verified', review_text:'Post copy'}],
  });
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    const permButton = [...shell.querySelectorAll('button')].find(button => button.textContent.includes('Permissions'));
    s.flush(() => permButton.click());
    await s.settle();
    assert.match(shell.textContent, /Publish this machine map to the cloud/);
    assert.match(shell.textContent, /Connected accounts/);
    assert.match(shell.textContent, /Posts waiting for your approval/);
    assert.match(shell.textContent, /Per-agent permissions: not available yet/);
    assert.equal(shell.querySelectorAll('[data-permission-row]').length, 0, 'new per-agent table is absent without backend');
    const publish = shell.querySelector('button[aria-label="Publish this machine map to the cloud"]');
    s.flush(() => publish.click());
    await s.settle();
    assert.deepEqual(s.calls.cloudConsent, [false]);
    const approve = shell.querySelector('[data-approval-surface="social"] [data-workshop-primary="approve"]');
    assert.equal(approve.textContent.trim(),'Approve');
    s.flush(() => approve.click());
    await s.settle();
    assert.deepEqual(s.calls.socialDecision.at(-1), {delegation:'delegation-a', input_digest:'d'.repeat(64), decision:'approve'});
    const disconnect = [...shell.querySelectorAll('button')].find(button => button.textContent.trim() === 'Disconnect');
    s.flush(() => disconnect.click());
    await s.settle();
    assert.deepEqual(s.calls.socialRemove.at(-1), {provider:'linkedin', account_id:'urn:li:person:af', vault_entry:'social-linkedin-af'});
  } finally { s.close(); }
});

test('SETTINGS-54 p4: parameter controls are disabled with a reason when no writer route exists', async () => {
  const s = await openSettings({exposeParamWriter:false});
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    const find = shell.querySelector('input[aria-label="Find a setting"]');
    s.flush(() => { find.value = 'Density'; find.dispatchEvent(new s.win.Event('input', {bubbles:true})); });
    await s.settle();
    const properties = [...shell.querySelectorAll('button')].find(button => button.textContent.trim() === 'Properties');
    s.flush(() => properties.click());
    await s.settle();
    const density = [...shell.querySelectorAll('[data-settings54-param-row]')].find(row => row.textContent.includes('Density'));
    assert.ok(density, 'Density parameter row is visible');
    assert.ok(density.querySelector('select:disabled'), 'unsupported parameter writer disables the control');
    assert.match(density.textContent, /Parameter writer is not available in this runtime/);
    s.flush(() => density.querySelector('select').dispatchEvent(new s.win.Event('change', {bubbles:true})));
    await s.settle();
    assert.equal(s.calls.setNodeProp.length, 0);
  } finally { s.close(); }
});

test('SETTINGS-54 p3: source contains no decorative graph constants or permission localStorage fallback', () => {
  const source = read('nodelang/studio/studio-lm.jsx');
  for (const banned of ['SETTINGS54_' + 'NODE', 'SETTINGS54_' + 'SYSTEM_GRAPH', 'SETTINGS54_' + 'SYSTEM_WIRES']) {
    assert.equal(source.includes(banned), false);
  }
  assert.doesNotMatch(source, /archhub\.settings\.permissions\.v1/);
  const block = source.slice(source.indexOf('const Settings ='), source.indexOf('const SystemMiniGraph'));
  assert.doesNotMatch(block, /const \[textSize|const \[density|const \[speechBudget/);
  assert.doesNotMatch(block, /LM\.serif|LM\.mono|fontFamily:\s*['"](?:serif|monospace)/);
});
