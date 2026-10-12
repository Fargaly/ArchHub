const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function mountStudio(loadSkills, {timeoutMs = 0} = {}) {
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
  if (timeoutMs) win.ARCHHUB_CATALOGUE_TIMEOUT_MS = timeoutMs;
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


// SKILLS-ONE (PM, installed 2111): Search counted 8 skills while the Skills panel said 0 and kept
// "Loading catalogue…". One list (ARCHHUB_LIVE.skills), a settled state, and an empty state.
const SKILL_ROWS = Array.from({length:8}, (_, i) => ({id:'s' + i, name:'Skill ' + i, runs:i, args:'a', when:'today'}));
const openRail = async (studio, title) => {
  const button = studio.doc.querySelector(`[title="${title}"]`);
  assert.ok(button, title + ' rail button exists');
  studio.flush(() => button.click());
  await studio.settle();
};
test('SKILLS-ONE: the Skills panel lists the same skills Search counts, and the loading line clears', async () => {
  const studio = await mountStudio(async () => SKILL_ROWS.map(row => ({...row})));
  try {
    await openRail(studio, 'Skills');
    for (let i = 0; i < 5; i += 1) await studio.settle();
    const aside = studio.doc.querySelector('[title="Skills"]').closest('aside');
    const panel = aside.children[1];
    assert.equal(panel.textContent.includes('Loading catalogue'), false, 'loading clears once the list answers');
    assert.match(panel.textContent, /8 SAVED/, 'the Skills header counts the 8 skills');
    await openRail(studio, 'Search');
    const skillsRow = [...studio.doc.querySelectorAll('button')].find(b => b.firstElementChild?.textContent === 'skills');
    assert.ok(skillsRow, 'Search lists the skills scope');
    assert.equal(skillsRow.lastElementChild.textContent, '8', 'Search counts the same 8');
  } finally { studio.close(); }
});

// SKILLS-ONE v2 (installed 2248, 05_rail_Skills / 06_rail_Search): the panel opened mid-read and said
// "0 SAVED" under "Loading catalogue…" while Search counted 83 a moment later. Rows here use the
// catalogue's real shape (name, source, description, path; no id/args/runs/when).
const REAL_ROWS = Array.from({length:83}, (_, i) => ({name:'skill-' + i, source:i % 2 ? 'claude' : 'codex',
  description:'What skill ' + i + ' does.', path:'C:/skills/skill-' + i + '/SKILL.md'}));
test('SKILLS-ONE v2: saved skills are read at start, so the panel opens on the list Search counts', async () => {
  let calls = 0;
  const studio = await mountStudio(async () => { calls += 1; return REAL_ROWS.map(row => ({...row})); });
  try {
    for (let i = 0; i < 4; i += 1) await studio.settle();
    assert.equal(calls, 1, 'Studio reads the saved skills once at start, before the panel opens');
    await openRail(studio, 'Skills');
    const panel = studio.doc.querySelector('[title="Skills"]').closest('aside').children[1];
    assert.equal(calls, 1, 'opening the panel does not read the list again');
    assert.equal(panel.textContent.includes('Loading catalogue'), false, 'no loading line over a list already read');
    assert.equal(panel.querySelector('[data-skills-count]').textContent.trim(), '83 SAVED');
    const rows = panel.querySelectorAll('[data-skill-row]');
    assert.equal(rows.length, 83, 'every saved skill is listed');
    assert.ok(rows[0].textContent.includes('skill-0') && rows[0].textContent.includes('What skill 0 does.'), 'a row shows the name and description');
    assert.equal(panel.textContent.includes('args:'), false, 'no blank seed fields (args/runs/when) on real rows');
    await openRail(studio, 'Search');
    const skillsRow = [...studio.doc.querySelectorAll('button')].find(b => b.firstElementChild?.textContent === 'skills');
    assert.equal(skillsRow.lastElementChild.textContent, '83', 'Search counts the same 83');
  } finally { studio.close(); }
});

test('SKILLS-ONE v2: while the list is still being read the header never says 0 SAVED', async () => {
  let answer;
  const studio = await mountStudio(() => new Promise(resolve => { answer = resolve; }));
  try {
    await openRail(studio, 'Skills');
    const panel = () => studio.doc.querySelector('[title="Skills"]').closest('aside').children[1];
    assert.equal(panel().querySelector('[data-skills-count]').textContent.trim(), 'READING\u2026', 'unread is not zero');
    assert.equal(studio.doc.querySelector('[data-skills-empty]'), null, 'no empty state before the list answers');
    studio.flush(() => answer(REAL_ROWS.slice(0, 3).map(row => ({...row}))));
    for (let i = 0; i < 5; i += 1) await studio.settle();
    assert.equal(panel().querySelector('[data-skills-count]').textContent.trim(), '3 SAVED');
    assert.equal(panel().querySelectorAll('[data-skill-row]').length, 3);
    assert.equal(panel().textContent.includes('Loading catalogue'), false, 'the loading line clears');
  } finally { studio.close(); }
});

test('SKILLS-ONE: zero saved skills shows a real empty state, not a blank panel', async () => {
  const studio = await mountStudio(async () => []);
  try {
    await openRail(studio, 'Skills');
    for (let i = 0; i < 5; i += 1) await studio.settle();
    const empty = studio.doc.querySelector('[data-skills-empty]');
    assert.ok(empty, 'the empty state is drawn');
    assert.match(empty.textContent, /No saved skills yet\./);
    assert.equal(studio.doc.body.textContent.includes('Loading catalogue'), false);
  } finally { studio.close(); }
});

test('SKILLS-ONE: a list that never answers stops loading and offers Retry', async () => {
  const studio = await mountStudio(() => new Promise(() => {}), {timeoutMs:40});
  try {
    await openRail(studio, 'Skills');
    await new Promise(resolve => studio.win.setTimeout(resolve, 120));
    for (let i = 0; i < 5; i += 1) await studio.settle();
    assert.equal(studio.doc.body.textContent.includes('Loading catalogue'), false, 'no endless loading line');
    const alert = studio.doc.querySelector('[role="alert"]');
    assert.ok(alert && /did not answer/.test(alert.textContent), 'says the list did not answer');
    assert.ok([...alert.querySelectorAll('button')].some(b => b.textContent === 'Retry'), 'offers Retry');
    assert.equal(studio.doc.querySelector('[data-skills-empty]'), null, 'an unanswered list is not shown as empty');
  } finally { studio.close(); }
});
