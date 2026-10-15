const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(match => [match[1], match[2]]));

const SKILLS = [
  {id:'dim', name:'Dimension walls', source:'claude', description:'Dimension walls in the active view.', path:'C:/skills/dim/SKILL.md'},
  {id:'door', name:'Door QA', source:'codex', description:'Check door schedules.', path:'C:/skills/door/SKILL.md'},
  {id:'sheet', name:'Sheet issue', source:'claude', description:'Prepare a sheet issue set.', path:'C:/skills/sheet/SKILL.md'},
  {id:'model', name:'Model audit', source:'codex', description:'Audit model warnings.', path:'C:/skills/model/SKILL.md'},
  {id:'room', name:'Room names', source:'claude', description:'Normalize room names.', path:'C:/skills/room/SKILL.md'},
];
const SKILL_TEXT = '---\nname: Dimension walls\nversion: 1\n---\n\n# Dimension walls\n\n## Run\nCreate dimensions.\n';

async function mountStudio(options = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-suite.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, 'Studio build is stale for ' + source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const graph = {nodes:[], wires:[]};
  const createCalls = [];
  const readCalls = [];
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/free'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:[], stopped:false})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.AH_LIBRARY = [{cat:'logic', items:[{id:'number', title:'Number', sub:'constant value', engine:'data.constant'}]}];
  win.ARCHHUB_LOAD_SKILLS = options.loadSkills || (async () => SKILLS.map(skill => ({...skill})));
  win.ARCHHUB_READ_SKILL = async subject => { readCalls.push(subject); return SKILL_TEXT; };
  win.ARCHHUB_NODE_CREATE = async payload => { createCalls.push(payload); return {ok:true, id:'node-created'}; };
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:[], connectors:[], graph, memory:[], skills:[]};
  if (options.timeoutMs) win.ARCHHUB_CATALOGUE_TIMEOUT_MS = options.timeoutMs;
  if (typeof options.prepare === 'function') options.prepare(win);
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({canvas:null, workshops:[], applicationUpdate:{state:'idle', current_build:'20261012-rail-z'},
      topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:{subject:'owner-a'}}, graph, selected:null}}),
    subscribe:() => () => {},
    watchApplicationUpdate:() => () => {},
    refreshTopologyCanvas:async () => ({ok:true}),
  };
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async (done, label = 'settled') => {
    if (!done) {
      for (let i = 0; i < 8; i += 1) await new Promise(resolve => win.setTimeout(resolve, 0));
      return;
    }
    for (let i = 0; i < 120 && !done(); i += 1) await new Promise(resolve => win.setTimeout(resolve, 5));
    assert.ok(done(), label);
  };
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc:win.document, flush, settle, close, createCalls, readCalls};
}

const text = node => (node && node.textContent || '').replace(/\s+/g, ' ').trim();
const buttons = doc => [...doc.querySelectorAll('button')];
const clickLibrarySkills = async studio => {
  const library = studio.doc.querySelector('[data-rail-panel="Library"]');
  assert.ok(library, 'Library rail button exists');
  studio.flush(() => library.click());
  await studio.settle(() => studio.doc.querySelector('[data-library-tab="skills"]'), 'Library panel opened');
  const skills = studio.doc.querySelector('[data-library-tab="skills"]');
  studio.flush(() => skills.click());
  await studio.settle(() => studio.doc.body.textContent.includes('Search saved skills'), 'Skills tab opened');
};

test('Library Skills tab loads saved skills and the empty state is mounted', async () => {
  const loaded = await mountStudio();
  try {
    await clickLibrarySkills(loaded);
    await loaded.settle(() => loaded.doc.querySelectorAll('[data-skill-row]').length === SKILLS.length, 'all saved skills loaded');
    assert.ok(loaded.doc.body.textContent.includes(SKILLS.length + ' SAVED'), 'loaded count is visible');
    for (const skill of SKILLS) assert.ok(loaded.doc.body.textContent.includes(skill.name), 'skill row is visible: ' + skill.name);
  } finally { loaded.close(); }

  const empty = await mountStudio({loadSkills:async () => []});
  try {
    await clickLibrarySkills(empty);
    await empty.settle(() => empty.doc.querySelector('[data-skills-empty]'), 'empty state rendered');
    assert.ok(empty.doc.body.textContent.includes('No saved skills yet.'), 'empty copy is visible');
  } finally { empty.close(); }
});

test('Library Skills tab preserves pending and failed Retry states', async () => {
  const pending = await mountStudio({loadSkills:() => new Promise(() => {})});
  try {
    await clickLibrarySkills(pending);
    assert.ok(pending.doc.body.textContent.includes('Loading catalogue'), 'pending read shows loading state');
    assert.ok(pending.doc.body.textContent.includes('READING'), 'pending count does not claim zero saved skills');
  } finally { pending.close(); }

  let attempts = 0;
  const failed = await mountStudio({loadSkills:async () => {
    attempts += 1;
    if (attempts === 1) throw new Error('skills unavailable');
    return [SKILLS[0]];
  }});
  try {
    await clickLibrarySkills(failed);
    await failed.settle(() => failed.doc.body.textContent.includes('skills unavailable'), 'failure is visible');
    const retry = buttons(failed.doc).find(button => button.textContent.trim() === 'Retry');
    assert.ok(retry, 'Retry button is visible after failed skills read');
    failed.flush(() => retry.click());
    await failed.settle(() => failed.doc.querySelectorAll('[data-skill-row]').length === 1, 'Retry loaded skills');
  } finally { failed.close(); }
});

test('Library Skills opens a real skill file and Add to canvas uses the graph node route', async () => {
  const studio = await mountStudio();
  try {
    await clickLibrarySkills(studio);
    await studio.settle(() => studio.doc.querySelectorAll('[data-skill-row]').length === SKILLS.length, 'skills loaded');
    const row = [...studio.doc.querySelectorAll('[data-skill-row]')].find(button => button.textContent.includes('Dimension walls'));
    studio.flush(() => row.click());
    await studio.settle(() => studio.doc.querySelector('[data-studio-screen="skill"]'), 'skill screen opened');
    await studio.settle(() => studio.readCalls.length === 1, 'skill file read requested');
    assert.equal(studio.readCalls[0], SKILLS[0].path, 'the skill view reads the selected row path');
    assert.ok(studio.doc.body.textContent.includes('Create dimensions.'), 'skill file text is visible');

    const add = buttons(studio.doc).find(button => button.textContent.trim() === 'Add to canvas');
    assert.ok(add && !add.disabled, 'Add to canvas is available from the skill split view');
    studio.flush(() => add.click());
    await studio.settle(() => studio.createCalls.length === 1, 'Add to canvas called node creation');
    assert.equal(studio.createCalls[0].engine, 'skill');
    assert.equal(studio.createCalls[0].params.skill.path, SKILLS[0].path);
  } finally { studio.close(); }
});

test('Command bar searches all saved skills and keeps open on an unavailable skill route', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(() => studio.win.ARCHHUB_LIVE.skills.length === SKILLS.length, 'skills loaded for command bar');
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'k', ctrlKey:true, bubbles:true})));
    await studio.settle(() => studio.doc.querySelector('[data-command-bar]'), 'command bar opened');
    const command = studio.doc.querySelector('[data-command-bar]');
    for (const skill of SKILLS) assert.ok(command.textContent.includes(skill.name), 'command bar includes saved skill: ' + skill.name);

    studio.win.ArchHubStudioScreens = null;
    const skillButton = buttons(command).find(button => text(button).includes(SKILLS[0].name));
    studio.flush(() => skillButton.click());
    assert.ok(studio.doc.querySelector('[data-command-bar]'), 'command bar stays open when the route is unavailable');
    assert.ok(command.textContent.includes('Skill viewer is unavailable'), 'visible route failure is shown');
  } finally { studio.close(); }
});

// INTEG1: preserve pre-frame behavior courts; only retired rail DOM selectors change.
const mountPreservedSkills = (loadSkills, options = {}) => mountStudio({...options, loadSkills});

// R11 / gate row RL: a rail page opens in the panel slot, never inside the 44px rail column.
for (const [name, loader] of [
  ['while the catalogue is still loading', () => new Promise(() => {})],
  ['after the catalogue failed', async () => { throw new Error('skills endpoint down'); }],
  ['after the catalogue loaded', async () => [{id:'qa', name:'Door schedule QA', runs:3, args:'level', when:'today'}]],
]) {
  test('Skills opens as one panel beside the rail ' + name, async () => {
    const studio = await mountPreservedSkills(loader);
    try {
      await clickLibrarySkills(studio);
      const aside = studio.doc.querySelector('[data-app-frame]');
      assert.ok(aside.querySelector('nav'), 'the rail remains inside the application frame');
      assert.equal(aside.querySelectorAll('[data-left-panel]').length, 1, 'the frame holds exactly one left panel beside the rail');
      const panel = aside.querySelector('[data-left-panel]');
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
  if (title === 'Skills') return clickLibrarySkills(studio);
  const library = studio.doc.querySelector('[data-rail-panel="Library"]');
  assert.ok(library, 'Library rail button exists');
  studio.flush(() => library.click());
  await studio.settle(() => studio.doc.querySelector('[data-library-tab="search"]'), 'Search Library tab is available');
  const button = studio.doc.querySelector('[data-library-tab="search"]');
  assert.ok(button, title + ' Library tab exists');
  studio.flush(() => button.click());
  await studio.settle();
};

const key = (studio, target, init) => studio.flush(() => target.dispatchEvent(new studio.win.KeyboardEvent('keydown', {bubbles:true, ...init})));
const reactProps = element => element[Object.keys(element).find(key => key.startsWith('__reactProps'))] || {};
const waitFor = async (studio, predicate, note) => {
  for (let i = 0; i < 12; i += 1) {
    await studio.settle();
    if (predicate()) return;
  }
  assert.ok(predicate(), note);
};
test('SKILLS-ONE: the Skills panel lists the same skills Search counts, and the loading line clears', async () => {
  const studio = await mountPreservedSkills(async () => SKILL_ROWS.map(row => ({...row})));
  try {
    await openRail(studio, 'Skills');
    for (let i = 0; i < 5; i += 1) await studio.settle();
    const panel = studio.doc.querySelector('[data-left-panel]');
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
  const studio = await mountPreservedSkills(async () => { calls += 1; return REAL_ROWS.map(row => ({...row})); });
  try {
    for (let i = 0; i < 4; i += 1) await studio.settle();
    assert.equal(calls, 1, 'Studio reads the saved skills once at start, before the panel opens');
    await openRail(studio, 'Skills');
    const panel = studio.doc.querySelector('[data-left-panel]');
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
  const studio = await mountPreservedSkills(() => new Promise(resolve => { answer = resolve; }));
  try {
    await openRail(studio, 'Skills');
    const panel = () => studio.doc.querySelector('[data-left-panel]');
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
  const studio = await mountPreservedSkills(async () => []);
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
  const studio = await mountPreservedSkills(() => new Promise(() => {}), {timeoutMs:40});
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

test('SKILL-ROW: rows are controls, open real skill files, return, and add to canvas', async () => {
  const row = {id:'door-qa', name:'Door schedule QA', source:'codex',
    description:'Checks door schedules against room data.', path:'C:\\skills\\door-qa\\SKILL.md'};
  const skillText = '---\nname: Door schedule QA\ndescription: Checks door schedules.\n---\n\n# Door schedule QA\n\n## Verify\nRead the real file.\n';
  const reads = [], created = [];
  const studio = await mountPreservedSkills(async () => [{...row}], {prepare:win => {
    win.ARCHHUB_READ_SKILL = async target => { reads.push(target); return skillText; };
    win.ARCHHUB_NODE_CREATE = async payload => { created.push(payload); return {ok:true, id:'node-door-qa'}; };
  }});
  try {
    await openRail(studio, 'Skills');
    await waitFor(studio, () => studio.doc.querySelectorAll('[data-skill-row]').length === 1, 'skill row appears');
    const skillRow = studio.doc.querySelector('[data-skill-row]');
    assert.equal(skillRow.tagName, 'BUTTON', 'skill row is a button control');
    assert.equal(skillRow.getAttribute('aria-label'), 'Open skill Door schedule QA');
    assert.equal(skillRow.textContent.includes(row.source), true, 'row shows the source');
    assert.equal(skillRow.textContent.includes(row.description), true, 'row shows the description');
    studio.flush(() => skillRow.click());
    await waitFor(studio, () => studio.doc.querySelector('[data-studio-screen="skill"]')?.textContent.includes('Read the real file.'), 'click opens skill content');
    assert.deepEqual(reads, [row.path], 'the split view reads the row path');
    const view = studio.doc.querySelector('[data-studio-screen="skill"]');
    assert.equal(view.querySelector('h1').textContent, row.name);
    assert.equal(view.textContent.includes(row.path), true, 'the split view shows the skill path');
    const add = [...view.querySelectorAll('button')].find(button => button.textContent.includes('Add to canvas'));
    assert.ok(add, 'Add to canvas is drawn');
    assert.equal(add.disabled, false, 'Add to canvas is live when the add-node path exists');
    assert.equal(typeof reactProps(add).onClick, 'function', 'Add to canvas has a React action');
    studio.flush(() => add.click());
    await waitFor(studio, () => created.length === 1, 'Add to canvas calls node create');
    assert.equal(created[0].item, 'skill:door-qa');
    assert.equal(created[0].engine, 'skill');
    assert.equal(created[0].params.skill.id, row.id);
    assert.equal(created[0].params.skill.name, row.name);
    assert.equal(created[0].params.skill.source, row.source);
    assert.equal(created[0].params.skill.path, row.path);
    assert.equal(created[0].params.skill.description, row.description);
    key(studio, studio.win, {key:'Escape'});
    await waitFor(studio, () => !studio.doc.querySelector('[data-studio-screen="skill"]'), 'Escape returns to list');
    key(studio, skillRow, {key:'Enter'});
    await waitFor(studio, () => studio.doc.querySelector('[data-studio-screen="skill"]'), 'Enter opens the skill');
  } finally { studio.close(); }
});
