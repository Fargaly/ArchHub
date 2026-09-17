/* Settings > Brain is the design's governance layer read from brain-model.jsx, filled with the real
   facts the brain holds; Settings > Team is the design layout with every value empty.
   The design bundle (archhub/project/studio-lm.jsx Settings 2411-2506, SettingsMemory 2519-2730,
   SettingsTeam 2731-2793, brain-model.jsx) seeds a firm, a roster, an invite token, a recovery kit and
   thirteen sample facts. No window.ARCHHUB_* binding projects a firm, seats, invites or a key wrap
   (studio.html holds only REMEMBER/EXPORT/FORGET/EDIT/LOAD_MEMORY), so none of that sample may ship.
   Real browser DOM in memory; no application, provider or network. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const jsx = read('nodelang/studio/studio-lm.jsx');
const model = read('nodelang/studio/brain-model.jsx');

// Authored sample the design drew as if it were real. None of it may reach the shipped Studio.
const SEEDED = ['Habib Studio', 'ah-inv-', '@practice.com', 'AHUB-4K7M', '5 seats', 'Fargaly Habib',
  'Amina Habib', 'Karim Saleh', 'Dina Wasfy', 'L02 cladding', '\u00a3', 'Studio \u00b7 5'];
const STRATA = ['Ontology', 'Relationships', 'Categorisation', 'Instances'];
const TEAM_STATUS = 'No firm in this connection. Members appear here when the workspace has one.';
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)]
  .map(match => [match[1], match[2]]));

test('brain-model.jsx is the one brain definition, registered once and carrying no sample facts', () => {
  const names = read('packaging/compile_studio.cjs').match(/const names = \[([\s\S]*?)\];/)[1];
  // Design ArchHub App.html load order: brain-model.jsx, then studio-workshop.jsx, then studio-lm.jsx.
  assert.match(names, /'studio-account\.jsx',[\s\S]*'brain-model\.jsx',\s*'studio-workshop\.jsx',\s*'studio-lm\.jsx'/, 'brain-model.jsx loads before studio-lm.jsx');
  assert.match(read('nodelang/studio/studio.html'), /'studio-account\.jsx',(?:'[a-z-]+\.jsx',)*'brain-model\.jsx','studio-workshop\.jsx','studio-lm\.jsx'/);
  assert.match(model, /const BRAIN_FACTS = \[\];/, 'the seeded facts stay in the design bundle');
  for (const name of ['BRAIN_STRATA', 'BRAIN_LAKES', 'BRAIN_GATES', 'BRAIN_KEYS', 'BRAIN_PATHS']) {
    assert.ok(model.includes(name), `brain-model.jsx exports ${name}`);
    assert.equal(new RegExp(`const ${name} = `).test(jsx), false, `studio-lm.jsx never restates ${name}`);
  }
  for (const seeded of SEEDED) {
    assert.equal(jsx.includes(seeded), false, `studio-lm.jsx carries no ${JSON.stringify(seeded)}`);
    assert.equal(model.includes(seeded), false, `brain-model.jsx carries no ${JSON.stringify(seeded)}`);
  }
});

test('the Settings tab table matches the design: Brain on the memory tab, Team beside it', () => {
  const settings = jsx.indexOf('const Settings = (');
  const tabsStart = jsx.indexOf('  const tabs = [', settings);
  const tabsEnd = jsx.indexOf('\n  ];', tabsStart);
  const componentEnd = jsx.indexOf('// \u2500\u2500 Settings section header', tabsEnd);
  assert.ok(settings > 0 && tabsStart > settings && tabsEnd > tabsStart && componentEnd > tabsEnd);
  const tabs = jsx.slice(tabsStart, tabsEnd);
  const rendered = jsx.slice(tabsEnd, componentEnd);
  assert.match(tabs, /\['memory',\s*'Brain',\s*`\$\{\(window\.BRAIN_STRATA \|\| \[\]\)\.length\} strata \\u00b7 \$\{LM_MEMORY\.length/);
  assert.match(tabs, /\['team',\s*'Team',\s*null\]/, 'the Team badge states nothing it cannot read');
  assert.equal(/\['brain',/.test(tabs), false, 'there is one Brain tab, not a Memory tab beside an empty Brain tab');
  assert.match(rendered, /\{tab === 'memory'\s+&& <SettingsMemory /);
  assert.match(rendered, /\{tab === 'team'\s+&& <SettingsTeam\/>\}/);
});

test('the shipped Settings dialog draws the brain strata with real facts and an empty Team', async () => {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'brain-model.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, `Studio build is stale for ${source}: run npm run build:studio`);
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {}); // court sandbox: the mounted Studio talks to a server that never answers
  win.ARCHHUB_THEME = {...seed};
  win.ARCHHUB_LIVE = {memory:[{id:'m1', text:'Real fact read from the brain.', src:'folder'}]};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  try {
    for (const file of manifest.files) {
      if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
    }
    win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
    const settings = win.document.querySelector('[title="Settings"]');
    assert.ok(settings, 'actual Studio Settings control exists');
    win.ReactDOM.flushSync(() => settings.click());
    const anchor = [...win.document.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Theme');
    assert.ok(anchor, 'actual Settings sidebar exists');
    const sidebar = anchor.parentElement;
    const tab = label => [...sidebar.children].filter(button => button.firstElementChild?.textContent === label);
    assert.equal(tab('Memory').length, 0, 'no separate Memory tab');
    assert.equal(tab('Brain').length, 1, 'one Brain tab');
    assert.equal(tab('Brain')[0].lastElementChild.textContent, '4 strata \u00b7 1 facts');
    win.ReactDOM.flushSync(() => tab('Brain')[0].click());
    const panel = sidebar.nextElementSibling;
    for (const name of STRATA) assert.ok(panel.textContent.includes(name), `the Brain panel draws the ${name} stratum`);
    assert.ok(panel.textContent.includes('Real fact read from the brain.'), 'the real fact is filed under Instances');
    assert.ok(panel.textContent.includes('UNCLASSIFIED \u00b7 SEALED'), 'an unclassified real fact is sealed by default');
    assert.ok(panel.textContent.includes('GATES') && panel.textContent.includes('CONSENT RECORD') && panel.textContent.includes('KEY'));
    const kit = [...panel.querySelectorAll('button')].find(button => button.textContent === 'show recovery kit');
    win.ReactDOM.flushSync(() => kit.click());
    assert.ok([...panel.querySelectorAll('[role="status"]')].some(node => node.textContent.startsWith('No recovery kit exists in this connection.')),
      'the recovery kit is an absent state, never a sample key');
    const team = tab('Team')[0];
    assert.ok(team && !team.lastElementChild.textContent.includes('seat'), 'the Team badge names no firm or seats');
    win.ReactDOM.flushSync(() => team.click());
    const teamPanel = sidebar.nextElementSibling;
    assert.ok([...teamPanel.querySelectorAll('[role="status"]')].some(node => node.textContent.trim() === TEAM_STATUS));
    const controls = [...teamPanel.querySelectorAll('button')];
    assert.deepEqual(controls.map(button => button.textContent), ['invite a teammate', 'set seat count', 'transfer ownership', 'leave firm']);
    assert.ok(controls.every(button => button.disabled), 'no Team control acts without a firm');
    for (const seeded of SEEDED) assert.equal(win.document.body.textContent.includes(seeded), false, `no ${JSON.stringify(seeded)} on screen`);
  } finally {
    if (win.__studioRoot) win.ReactDOM.flushSync(() => win.__studioRoot.unmount());
    dom.window.close();
  }
});