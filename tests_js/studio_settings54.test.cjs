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
        {k:'theme', label:'Theme', v:'dark', type:'menu', editable:true, options:['dark', 'light', 'system']},
        {k:'density', label:'Density', v:'comfortable', type:'menu', editable:true, options:['comfortable', 'compact', 'spacious']},
        {k:'text_size', label:'Text size', v:14, type:'number', editable:true, unit:'px'},
      ]},
    {id:'sys_storage', application:true, title:'Storage & About', group:'Storage & About', cat:'data', x:620, y:252, w:240,
      ins:[{id:'theme', label:'theme', t:'view'}], params:[{k:'release_channel', label:'Version', v:'b1', editable:false}]},
  ];
  return {
    canvas:{graph_id:'app', application_root:'app', canvas_root:'canvas-root', root:'app', scope:{current:'app',trail:[{root:'canvas-root',label:'Root canvas'},{root:'app',label:'Application'}]},
      revision:7, authorization:{subject:'owner-a',session:'view-a',system_view:true}},
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
  const calls = {setNodeProp:[], moveMany:[], graphOpen:[], readPermissionRows:0, setPermission:[], cloudConsent:[], socialDecision:[], socialRemove:[]};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({canvas:projection.canvas,topology:projection,workshops:[],
      applicationUpdate:{state:'idle', current_build:'b1'}, theme:{configuration:{theme:{...seed}, binding_mode:'personal-wip', state:'WIP', history:[], personal_wip_heads:['head-a']}}, pending:false, error:''}),
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
    getSnapshot:() => ({...projection, workshops:[], applicationUpdate:{state:'idle', current_build:'b1'}, pending:false, error:''}),
    subscribe:fn => { listeners.add(fn); return () => listeners.delete(fn); },
    load:async()=>projection,
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
  const sessions=[{id:'canvas-root',title:'Root canvas',state:'idle',host:'archhub',file:'Graph composition'}];
  win.ARCHHUB_GRAPH_OPEN=async id=>{
    calls.graphOpen.push(id);
    assert.equal(id,'canvas-root','System opens the admitted canvas graph, not the application-root id');
    return {ok:true,current_graph:id,graphs:sessions,canvas:projection.canvas};
  };
  win.ARCHHUB_LIVE = {sessions, currentGraph:null, hosts:[], connectors:[], graph:projection.graph, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') {
      let code=read('nodelang/studio/compiled/' + file.output);
      if(file.source==='studio-lm.jsx') code=code.replace(/window\.StudioLM\s*=\s*StudioLM\s*;/,
        'window.StudioLM = StudioLM; window.__settings54Court = {Select:Settings54Select,writer:settings54ParamWriter};');
      win.eval(code);
    }
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async () => { for (let i = 0; i < 8; i += 1) await new Promise(resolve => win.setTimeout(resolve, 0)); };
  const opener = doc.querySelector('[title="Settings"]');
  assert.ok(opener, 'actual Settings control exists');
  flush(() => opener.click());
  await settle();
  // Settings owns capability controls; the header System graph action opens a separate workspace.
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, settle, calls, projection, close};
}

async function findSetting(s, text) {
  const find=s.doc.querySelector('input[aria-label="Find a setting"]');
  assert.ok(find,'Settings search is visible');
  s.flush(()=>{
    Object.getOwnPropertyDescriptor(s.win.HTMLInputElement.prototype,'value').set.call(find,text);
    find.dispatchEvent(new s.win.Event('input',{bubbles:true}));
  });
  await s.settle();
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
    await openSettingsCapability(s,'Appearance','System');
    const cards = [...shell.querySelectorAll('[data-system-mini-node]')];
    assert.equal(cards.length,6,'the real System preview renders every projected node');
    assert.deepEqual(cards.map(card=>card.getAttribute('data-system-mini-node')),s.projection.graph.nodes.map(node=>node.id));
    const wires=[...shell.querySelectorAll('[data-system-mini-wire]')];
    assert.equal(wires.length,3,'every projected relation renders');
    for(const [index,wire]of s.projection.graph.wires.entries()) {
      const from=cards.find(card=>card.getAttribute('data-system-mini-node')===wire.from[0]).querySelector('rect');
      const to=cards.find(card=>card.getAttribute('data-system-mini-node')===wire.to[0]).querySelector('rect');
      const start=[+from.getAttribute('x')+ +from.getAttribute('width'),+from.getAttribute('y')+ +from.getAttribute('height')/2];
      const end=[+to.getAttribute('x'),+to.getAttribute('y')+ +to.getAttribute('height')/2];
      assert.ok(wires[index].getAttribute('d').startsWith('M'+start.join(',')),'wire source is its projected node');
      assert.ok(wires[index].getAttribute('d').endsWith(end.join(',')),'wire target is its projected node');
      assert.ok(s.projection.graph.nodes.find(node=>node.id===wire.from[0]).outs.some(port=>port.id===wire.from[1]));
      assert.ok(s.projection.graph.nodes.find(node=>node.id===wire.to[0]).ins.some(port=>port.id===wire.to[1]));
    }
    assert.equal(shell.textContent.includes('Add node'), false, 'Settings has no Add node chrome');
    assert.match(shell.textContent, /Connected/);
  } finally { s.close(); }
});

test('SETTINGS-54 p3: find focuses matches and inspector controls post real System parameter writes', async () => {
  const s = await openSettings();
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    await findSetting(s,'Density');
    const inspector=shell.querySelector('[data-application-parameters="sys_appearance"]');
    assert.ok(inspector,'search selects the actual application node inspector');
    const density=inspector.querySelector('[data-param-key="density"]');
    assert.ok(density,'Density parameter is visible');
    const picker=density.querySelector('[data-param-control] select');
    assert.ok(picker,'the actual application inspector uses its fixed menu control');
    s.flush(()=>{picker.value='compact';picker.dispatchEvent(new s.win.Event('change',{bubbles:true}));});
    await s.settle();
    assert.deepEqual(s.calls.setNodeProp.at(-1), {id:'sys_appearance', key:'density', value:'compact'});
    assert.equal(inspector.querySelector('[data-param-key="density"] [data-param-control] select').value,'compact','re-read projection shows the written value');
    const open=[...shell.querySelectorAll('button')].find(button=>button.textContent.trim()==='System graph');
    s.flush(()=>open.click());
    await s.settle();
    assert.equal(s.doc.querySelector('[data-settings54-shell]'),null,'System graph opens in its own workspace');
    assert.ok(s.doc.querySelector('[data-system-graph]'),'the actual System workspace renders: '+JSON.stringify({
      workspacePending:!!s.doc.querySelector('[data-workspace-canvas-loading]'),
      nodes:s.doc.querySelectorAll('[data-node-id]').length,
      text:s.doc.getElementById('root').textContent.replace(/\s+/g,' ').slice(0,350),
      ownerCanvas:s.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().canvas,
    }));
    assert.deepEqual(s.calls.graphOpen,['canvas-root'],'navigation uses the real root-graph open protocol');
    const arrange=s.doc.querySelector('button[aria-label="Arrange"]');
    assert.ok(arrange,'the workspace exposes Arrange');
    assert.equal(arrange.disabled,false,'the admitted owner supports arranging this canvas');
    // jsdom does not perform layout. The real Arrange guard requires measured
    // mounted card sizes, as in studio_canvas_user_layout's Arrange harness.
    const cards=[...s.doc.querySelectorAll('.lm-node[data-node-id]')];
    assert.equal(cards.length,s.projection.graph.nodes.length,'all admitted System cards are mounted');
    for(const card of cards) {
      const node=s.projection.graph.nodes.find(row=>row.id===card.dataset.nodeId);
      assert.ok(node,'each measured card belongs to the owner projection');
      Object.defineProperty(card,'offsetWidth',{configurable:true,value:node.w});
      Object.defineProperty(card,'offsetHeight',{configurable:true,value:180});
    }
    const previousWrites=s.calls.moveMany.length;
    s.flush(()=>arrange.click());await s.settle();
    assert.equal(s.calls.moveMany.length,previousWrites+1,'one explicit Arrange click writes one owner layout');
    assert.equal(s.calls.moveMany.at(-1)?.placement, 'arrange');
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
    assert.doesNotMatch(shell.textContent, /Per-agent permissions: not available yet/, 'unsupported empty permission section is removed');
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
    await findSetting(s,'Density');
    assert.ok(shell.querySelector('[data-application-parameters="sys_appearance"]'),'full projection selects the real Appearance node');
    const hidden=[...shell.querySelectorAll('[style*="display: none"]')];
    const fixedActionSlot=node=>node.parentElement?.matches('[data-param-row]') &&
      node===node.parentElement.lastElementChild && node.childElementCount===0;
    assert.equal(hidden.filter(node=>!fixedActionSlot(node)).length,0,'Settings shell has no hidden compatibility DOM');
    assert.ok(hidden.every(fixedActionSlot),'only empty fixed application parameter action slots are hidden');
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
    assert.equal(shell.querySelector('[data-application-parameters="sys_account"]'),null,'Appearance does not select the fallback Account node');
    assert.ok(shell.querySelector('[data-settings54-capability="Theme"]'),'Appearance shows its real capability owner');
    await openSettingsCapability(s, 'Appearance', 'Shortcuts');
    assert.equal(shell.querySelector('[data-application-parameters="sys_account"]'),null,'Shortcuts does not fabricate a selected node');
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
      assert.equal(shell.querySelector('[data-application-parameters]'),null,label+' does not fabricate a selected node');
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
    assert.doesNotMatch(shell.textContent, /Per-agent permissions: not available yet/, 'unsupported empty permission section is removed');
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
  let consumerRoot;
  try {
    const shell = s.doc.querySelector('[data-settings54-shell]');
    const row=s.projection.graph.nodes.find(node=>node.id==='sys_appearance').params.find(row=>row.k==='density');
    const writer=s.win.__settings54Court.writer(row);
    assert.equal(writer.ok,false,'the real writer resolver refuses absent authority');
    assert.match(writer.reason,/Parameter writer is not available in this runtime/);
    const host=s.doc.createElement('div');s.doc.body.appendChild(host);
    consumerRoot=s.win.ReactDOM.createRoot(host);
    let writes=0;
    s.flush(()=>consumerRoot.render(s.win.React.createElement('span',{title:writer.reason},
      s.win.React.createElement(s.win.__settings54Court.Select,{label:'Density',value:row.v,options:row.options,
        disabled:!writer.ok,onChange:()=>writes++}))));
    assert.ok(host.querySelector('select:disabled'),'the shared Settings selector disables unsupported writes');
    assert.match(host.firstElementChild.title,/Parameter writer is not available in this runtime/);
    s.flush(()=>host.querySelector('select').click());
    assert.equal(writes,0,'disabled selector cannot activate a writer');
    // The routed inspector replaced the embedded Settings selector; it reports a failed write visibly.
    await findSetting(s,'Density');
    const density=shell.querySelector('[data-application-parameters="sys_appearance"] [data-param-key="density"]');
    assert.ok(density,'the routed inspector still shows the projected parameter');
    const select=density.querySelector('[data-param-control] select');assert.ok(select);
    s.flush(()=>{select.value='compact';select.dispatchEvent(new s.win.Event('change',{bubbles:true}));});await s.settle();
    assert.ok(shell.querySelector('[data-sysnode-param="density"] [role="alert"]'),'unsupported routed write has a visible refusal');
    assert.equal(s.calls.setNodeProp.length, 0);
  } finally {if(consumerRoot)s.flush(()=>consumerRoot.unmount());s.close(); }
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
