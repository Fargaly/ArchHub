/* Settings > Team and Settings > Brain are explicit absent states, never a roster or a strata list.
   The design bundle (70.HANDOFFS/ARCHHUB-handoff.zip archhub/project/studio-lm.jsx:2443-2444 and
   2731-2791) fills both tabs from authored data: a firm name with a seat count, four roster rows, a
   single-use invite token and brain-model.jsx strata. No window.ARCHHUB_* binding projects any of
   it (studio.html:209-216 holds only REMEMBER/EXPORT/FORGET/EDIT), so the shipped tabs must say so.
   Real browser DOM in memory; no application, provider or network. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const jsx = read('nodelang/studio/studio-lm.jsx');

// Authored data the design drew as if it were real. None of it may reach the shipped Studio.
const SEEDED = ['Habib Studio', 'ah-inv-', '@practice.com', 'BRAIN_STRATA', 'BRAIN_FACTS', 'BRAIN_GATES',
  'SettingsTeam', 'invite a teammate', 'transfer ownership', 'leave firm', 'strata ·', '5 seats'];
const ABSENT = 'Not available in this connection.';
const STATUS = {
  Team: 'No data path projects a firm roster, seats, roles or invite tokens for this view. Nothing is shown rather than a sample.',
  Brain: 'No data path projects strata, lakes, gates and per-fact classes for this view. Nothing is shown rather than a sample. Memory holds the facts this app has loaded.',
};
const escape = text => text.replace(/[.]/g, '\\.');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)]
  .map(match => [match[1], match[2]]));

test('the Settings tab table lists Brain and Team as absent states beside the real Memory tab', () => {
  const settings = jsx.indexOf('const Settings = (');
  const tabsStart = jsx.indexOf('  const tabs = [', settings);
  const tabsEnd = jsx.indexOf('\n  ];', tabsStart);
  const componentEnd = jsx.indexOf('// ── Settings section header', tabsEnd);
  assert.ok(settings > 0 && tabsStart > settings && tabsEnd > tabsStart && componentEnd > tabsEnd);
  const tabs = jsx.slice(tabsStart, tabsEnd);
  const rendered = jsx.slice(tabsEnd, componentEnd);
  for (const [id, label] of [['brain', 'Brain'], ['team', 'Team']]) {
    const row = tabs.match(new RegExp(`\\['${id}',\\s*'([^']*)',\\s*('[^']*'|null)\\]`));
    assert.ok(row, `Settings lists a ${label} tab`);
    assert.equal(row[1], label);
    assert.equal(row[2], "'not available'", `the ${label} badge states the absence, never a count, a firm or a plan`);
    assert.match(rendered, new RegExp(`\\{tab === '${id}'\\s+&& <SettingsNotAvailable title="${label}"`),
      `the ${label} tab mounts the shared absent state`);
  }
  assert.match(tabs, /\['memory',\s*'Memory',\s*`\$\{LM_MEMORY\.length/, 'Memory still counts the facts the app loaded');
  assert.match(rendered, /\{tab === 'memory'\s+&& <SettingsMemory /, 'Memory still opens the real brain panel');
  for (const seeded of SEEDED) assert.equal(jsx.includes(seeded), false, `studio-lm.jsx carries no ${JSON.stringify(seeded)}`);
});

test('SettingsNotAvailable renders the absence as one status line with nothing sampled', () => {
  const start = jsx.indexOf('// ── Settings section header');
  const end = jsx.indexOf('// ── Memory: things the AI remembers', start);
  assert.ok(start > 0 && end > start);
  const {code} = require('esbuild').transformSync(jsx.slice(start, end) +
    '\nthis.SettingsNotAvailable = SettingsNotAvailable;', {loader:'jsx', target:'es2020'});
  const React = require('react');
  const context = vm.createContext({React, LM:{}});
  vm.runInContext(code, context);
  const {renderToStaticMarkup} = require('react-dom/server');
  const markup = props => renderToStaticMarkup(React.createElement(context.SettingsNotAvailable, props));
  const team = markup({title:'Team', what:'a firm roster, seats, roles or invite tokens'});
  assert.ok(team.includes('>Team<') && team.includes('>' + ABSENT + '<'), 'the head names the tab and the absence');
  assert.match(team, new RegExp('<p role="status"[^>]*>' + escape(STATUS.Team) + '</p>'));
  const brain = markup({title:'Brain', what:'strata, lakes, gates and per-fact classes',
    hint:'Memory holds the facts this app has loaded.'});
  assert.match(brain, new RegExp('<p role="status"[^>]*>' + escape(STATUS.Brain) + '</p>'));
  for (const html of [team, brain]) {
    assert.equal(/<(button|input|table|ul|ol)\b/.test(html), false, 'no control, list or roster is drawn');
    for (const seeded of SEEDED) assert.equal(html.includes(seeded), false);
  }
});

test('the shipped Settings dialog opens Team and Brain as absent states and draws no roster or strata', async () => {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {}); // court sandbox: the mounted Studio talks to a server that never answers
  win.ARCHHUB_THEME = {...seed};
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
    const tab = label => [...sidebar.children].find(button => button.firstElementChild?.textContent === label);
    const memory = tab('Memory');
    assert.ok(memory && /\d+ facts$/.test(memory.lastElementChild.textContent), 'the real Memory tab survives beside Brain');
    for (const label of ['Team', 'Brain']) {
      const button = tab(label);
      assert.ok(button, `actual Settings ${label} tab exists`);
      assert.equal(button.lastElementChild.textContent, 'not available', `the ${label} badge states the absence`);
      win.ReactDOM.flushSync(() => button.click());
      const line = [...win.document.querySelectorAll('[role="status"]')].find(node => node.textContent === STATUS[label]);
      assert.ok(line, `the ${label} panel is one status line`);
      const panel = line.closest('.ah-scroll');
      assert.ok(panel && panel.textContent.includes(label) && panel.textContent.includes(ABSENT), `the ${label} head names the absence`);
      assert.equal(panel.querySelectorAll('button, input, table, ul, ol, [role="switch"]').length, 0,
        `the ${label} panel draws no seat, invite, share or roster control`);
      for (const seeded of SEEDED) assert.equal(win.document.body.textContent.includes(seeded), false, `no ${JSON.stringify(seeded)} on screen`);
    }
  } finally {
    if (win.__studioRoot) win.ReactDOM.flushSync(() => win.__studioRoot.unmount());
    dom.window.close();
  }
});
