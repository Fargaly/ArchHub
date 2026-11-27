const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const studioDir = path.resolve(__dirname, '../../01.APP/nodelang/studio');

async function mountStudio(initialState = {}, apiOverrides = {}, initialRoute = 'docs') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
    url: 'http://127.0.0.1:8765/',
    runScripts: 'outside-only',
    pretendToBeVisual: true
  });
  const win = dom.window;
  win.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {};

  for (const vendor of ['react.js', 'react-dom.js', 'babel.js']) {
    win.eval(fs.readFileSync(path.join(studioDir, 'vendor', vendor), 'utf8'));
  }

  const subscribers = new Set();
  const calls = [];
  const toasts = [];
  let state = {
    docs: [
      { id: 'getting-started', category: 'START', title: 'Getting started', summary: 'Install and launch.', steps: ['Open Home.', 'Start a session.'], route: 'home' }
    ],
    bookGlossary: [
      '| **Document** | One .archhub file holding nodes, wires, groups, notes and the viewport. |',
      '| **Broker** | The narrow admitted bridge to one host program or service. |'
    ],
    baboomStandard: {
      version: '2026 · current',
      site: 'baboom.archhub.io',
      rules: [
        { code: 'WALLS-07', title: 'Wall types and fire ratings', summary: 'Standard wall assemblies and fire rating codes', tools: ['Check fire rating'] }
      ]
    },
    libraryPorts: [
      {
        id: 'revit.collect_sheets',
        title: 'Collect sheets',
        cat: 'Revit',
        sub: 'Revit · Sheets',
        engine: 'revit.collect_sheets',
        pure: true,
        ports: {
          target: [{ id: 'model', label: 'Model', type: 'file', cardinality: 'one' }],
          source: [{ id: 'sheets', label: 'Sheets', type: 'elements', cardinality: 'many' }]
        },
        params: { filter: 'Issued', source_file: '/projects/demo/tower-a.rvt' },
        paramDefs: [
          { id: 'filter', name: 'Filter', type: 'sel', options: ['All', 'Issued'] },
          { id: 'source_file', name: 'Source file', type: 'file' }
        ]
      },
      {
        id: 'excel.write_register',
        title: 'Write sheet register',
        cat: 'Files',
        sub: 'Excel · Output',
        engine: 'excel.write_register',
        pure: false,
        ports: {
          target: [{ id: 'sheets', label: 'Sheets', type: 'elements', cardinality: 'many' }],
          source: [{ id: 'workbook', label: 'Workbook', type: 'file', cardinality: 'one' }]
        },
        params: { count: 10 },
        paramDefs: [{ id: 'count', name: 'Max rows', type: 'int', min: 1, max: 500, unit: 'rows' }]
      },
      {
        id: 'model.open_rvt',
        title: 'Open model',
        cat: 'Revit',
        sub: 'Revit · Input',
        engine: 'model.open_rvt',
        pure: true,
        ports: {
          target: [],
          source: [{ id: 'model', label: 'Model', type: 'file', cardinality: 'one' }]
        },
        params: {},
        paramDefs: []
      }
    ],
    catalogue: [],
    settings: [],
    profile: { signedIn: true, id: 'u-1', name: 'Studio Architect', email: 'architect@example.org', plan: 'Studio' },
    community: {
      peers: [],
      patterns: [],
      shared: [],
      groups: [],
      joinStatus: 'Pending code',
      marketQuery: '',
      listing: { title: '', price: 0, creatorShare: 0 },
      charge: { client: '', project: '', basis: 'Per project', amount: 0 },
      charges: [],
      marketplace: []
    },
    graph: { id: 'g-1', name: 'Facade QA', nodes: [], wires: [], versions: [] },
    graphs: [{ id: 'g-1', name: 'Facade QA', nodes: [] }],
    tasks: [],
    approvals: [],
    runs: [],
    people: [],
    usage: { seats: 2 },
    ...initialState
  };

  function setState(patch) {
    state = typeof patch === 'function' ? patch(state) : { ...state, ...patch };
    subscribers.forEach(fn => fn());
  }

  let nodeCounter = 0;
  const api = {
    getSnapshot: () => state,
    subscribe: fn => {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
    refreshDocs: async () => state.docs,
    refreshCommunity: async () => state.community,
    newSession: async title => {
      calls.push(['newSession', title]);
      setState(prev => ({
        ...prev,
        graph: { id: 'session-' + calls.length, name: title, nodes: [], wires: [], versions: [] }
      }));
      return state.graph;
    },
    addNode: async (libId, pos = { x: 100, y: 100 }) => {
      const id = 'node-' + (++nodeCounter);
      const lib = state.libraryPorts.find(x => x.id === libId) || { id: libId, title: libId, ports: { target: [], source: [] } };
      const node = {
        id,
        title: lib.title,
        x: pos.x,
        y: pos.y,
        status: 'Planned',
        inputs: (lib.ports?.target || []).map(p => ({ id: p.id, type: p.type })),
        outputs: (lib.ports?.source || []).map(p => ({ id: p.id, type: p.type })),
        params: { ...(lib.params || {}) }
      };
      calls.push(['addNode', libId]);
      setState(prev => ({ ...prev, graph: { ...prev.graph, nodes: [...prev.graph.nodes, node] } }));
      return node;
    },
    renameNode: async (id, title) => {
      calls.push(['renameNode', id, title]);
      setState(prev => ({
        ...prev,
        graph: {
          ...prev.graph,
          nodes: prev.graph.nodes.map(n => (n.id === id ? { ...n, title } : n))
        }
      }));
      return { ok: true };
    },
    connectSockets: async wire => {
      calls.push(['connectSockets', wire]);
      setState(prev => ({
        ...prev,
        graph: { ...prev.graph, wires: [...prev.graph.wires, wire] }
      }));
      return { ok: true };
    },
    runNode: async id => {
      calls.push(['runNode', id]);
      return { ok: true };
    },
    sendToBaboom: async text => {
      calls.push(['sendToBaboom', text]);
      return { ok: true };
    },
    createCommunityGroup: async name => {
      calls.push(['createCommunityGroup', name]);
      return { id: 'grp-1', name };
    },
    ...apiOverrides
  };

  win.ArchHubAPI = api;
  for (const file of ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx', 'community-tools.jsx', 'project-tools.jsx', 'docs.jsx']) {
    const src = fs.readFileSync(path.join(studioDir, file), 'utf8');
    const code = file.endsWith('.jsx') ? win.Babel.transform(src, { presets: ['react'] }).code : src;
    win.eval(code + '\n;void 0;');
  }

  let appState = { route: initialRoute, selectedNodeId: null, companion: false };
  const appListeners = new Set();
  function setAppState(patch) {
    appState = { ...appState, ...(typeof patch === 'function' ? patch(appState) : patch) };
    appListeners.forEach(fn => fn());
  }

  function TestHarness() {
    const [, bump] = win.React.useReducer(x => x + 1, 0);
    win.React.useEffect(() => {
      const fn = () => bump();
      appListeners.add(fn);
      return () => appListeners.delete(fn);
    }, []);
    const u = {
      route: appState.route,
      selectedNodeId: appState.selectedNodeId,
      companion: appState.companion,
      setCompanion: open => { calls.push(['companion', open]); setAppState({ companion: open }); },
      setSelectedNodeId: id => { calls.push(['selectNode', id]); setAppState({ selectedNodeId: id }); },
      go: route => { calls.push(['go', route]); setAppState({ route }); },
      show: (kind, data) => calls.push(['show', kind, data]),
      setToast: msg => toasts.push(msg),
      act: fn => Promise.resolve().then(fn)
    };
    // Community has no page: its catalogue rows sit in the Library and open these two dialogs.
    const Screen = appState.route === 'community-preview'
      ? () => win.React.createElement(win.UI.CommunityPreview, { item: win.UI.communityWorkflows(state)[0], onClose: () => setAppState({ route: 'canvas' }) })
      : appState.route === 'community-publish'
        ? () => win.React.createElement(win.UI.PublishCommunityDialog, { onClose: () => setAppState({ route: 'canvas' }) })
      : appState.route === 'docs'
        ? win.UI.Docs
        : () => win.React.createElement('div', { 'data-screen': appState.route }, 'Canvas view');
    return win.React.createElement(
      win.UI.Ctx.Provider,
      { value: u },
      win.React.createElement(Screen),
      win.UI.TutorialOverlay ? win.React.createElement(win.UI.TutorialOverlay) : null
    );
  }

  const root = win.ReactDOM.createRoot(win.document.getElementById('root'));
  win.ReactDOM.flushSync(() => {
    root.render(win.React.createElement(TestHarness));
  });

  const settle = (ms = 25) => new Promise(resolve => setTimeout(resolve, ms));
  await settle();

  async function click(el) {
    assert.ok(el, 'Expected target element to exist before click');
    win.ReactDOM.flushSync(() => {
      el.click();
    });
    await settle(15);
  }

  async function typeInput(el, value) {
    assert.ok(el, 'Expected input element to exist');
    const proto = el.tagName === 'SELECT' ? win.HTMLSelectElement.prototype : win.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    win.ReactDOM.flushSync(() => {
      setter.call(el, value);
      el.dispatchEvent(new win.Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    });
    await settle(15);
  }

  async function pressEnter(el) {
    win.ReactDOM.flushSync(() => {
      el.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    await settle(15);
  }

  return {
    win,
    doc: win.document,
    calls,
    toasts,
    getState: () => state,
    setState,
    getAppState: () => appState,
    setAppState,
    click,
    typeInput,
    pressEnter,
    settle,
    close() {
      root.unmount();
      dom.window.close();
    }
  };
}

test('AG-24, AG-25, AG-26, AG-27: Docs 6-group TOC, search + Enter docsFind, Connect modal, article anatomy and 3-column dside', async () => {
  const h = await mountStudio({}, {}, 'docs');
  try {
    // AG-25: exact 6-group TOC order
    const eyebrows = [...h.doc.querySelectorAll('.toc .eyebrow')].map(el => el.textContent.trim());
    assert.deepEqual(eyebrows, [
      'START',
      'TUTORIALS',
      'WORK',
      'CONFIGURE',
      'OFFICE STANDARD (BABOOM)',
      'REFERENCE'
    ]);

    // Populated TUTORIALS and OFFICE STANDARD (BABOOM) including live BA standard rule
    const tocButtons = [...h.doc.querySelectorAll('.toc .tocb')].map(b => b.textContent.trim());
    assert.ok(tocButtons.includes('Your first workflow'));
    assert.ok(tocButtons.includes('Start here'));
    assert.ok(tocButtons.some(t => t.includes('WALLS-07')));

    // AG-26 & AG-27: 3-column .docgrid.d3, .dlead, .dsteps, figure.dfig + figcaption, aside.dside
    assert.ok(h.doc.querySelector('.docgrid.d3'));
    assert.ok(h.doc.querySelector('article.card .dlead'));
    assert.ok(h.doc.querySelectorAll('article.card .dsteps li').length >= 3);
    assert.ok(h.doc.querySelector('article.card figure.dfig figcaption'));

    const dsideText = h.doc.querySelector('aside.dside').textContent;
    assert.match(dsideText, /On this page/);
    assert.match(dsideText, /Try it/);
    assert.match(dsideText, /Related/);
    assert.match(dsideText, /Ask BABOOM about First task/);

    // Ask BABOOM button works
    await h.click(h.doc.querySelector('[data-dask]'));
    assert.ok(h.calls.some(c => c[0] === 'companion' && c[1] === true));

    // AG-24: Search placeholder, Enter best match + miss toast, header buttons
    const dq = h.doc.querySelector('#dq');
    assert.equal(dq.getAttribute('placeholder'), 'Find in the guide: “approve a step”');
    const webLink = [...h.doc.querySelectorAll('a.btn')].find(a => a.textContent.trim() === 'Open on the web');
    assert.ok(webLink && webLink.href.startsWith('https://archhub.io/docs/'));

    await h.typeInput(dq, 'approve a step');
    await h.pressEnter(dq);
    assert.equal(h.doc.querySelector('article.card h2').textContent, 'Approvals');
    assert.ok(h.toasts.includes('Opened “Approvals”.'));

    await h.typeInput(dq, 'zzzzzznonexistent');
    await h.pressEnter(dq);
    assert.ok(h.toasts.includes('No article matches. Ask an agent instead?'));
    await h.typeInput(dq, '');

    // How everything connects modal
    await h.click(h.doc.querySelector('#cmapb'));
    const connectDialog = h.doc.querySelector('[role="dialog"][aria-label="How everything connects"]');
    assert.ok(connectDialog);
    await h.click(connectDialog.querySelector('[data-cbox="BABOOM"]'));
    assert.match(connectDialog.textContent, /baboom\.archhub\.io/);
    await h.click([...connectDialog.querySelectorAll('button')].find(b => b.textContent.trim() === 'Close'));
    assert.equal(h.doc.querySelector('[role="dialog"][aria-label="How everything connects"]'), null);
  } finally {
    h.close();
  }
});

test('AG-21, AG-22, AG-23: Glossary merges 6 core + 9 status + bookGlossary; Node reference 3-col table and per-node page', async () => {
  const h = await mountStudio({}, {}, 'docs');
  try {
    // AG-21: Glossary
    const glossBtn = [...h.doc.querySelectorAll('.toc .tocb')].find(b => b.textContent.trim() === 'Glossary');
    await h.click(glossBtn);
    const terms = [...h.doc.querySelectorAll('dl.gloss dt')].map(dt => dt.textContent.trim());
    for (const core of ['Node', 'Socket', 'Wire', 'Session', 'Workflow', 'Skill']) {
      assert.ok(terms.includes(core), 'Missing core glossary term: ' + core);
    }
    for (const statusWord of ['Done', 'Running', 'Pending', 'Needs approval', 'Working', 'Waiting', 'Idle', 'Planned', 'Out of date']) {
      assert.ok(terms.includes(statusWord), 'Missing status glossary word: ' + statusWord);
    }
    assert.ok(terms.includes('Document') && terms.includes('Broker'), 'bookGlossary terms merged');

    // AG-22: Node reference is a drawn catalogue: one row of node cards per family, families only in the aside
    const nodeRefBtn = [...h.doc.querySelectorAll('.toc .tocb')].find(b => b.textContent.trim() === 'Node reference');
    await h.click(nodeRefBtn);
    const revitRow = h.doc.querySelector('article.card [data-fam="Revit"]');
    assert.ok(revitRow);
    assert.equal(revitRow.querySelectorAll('.nc').length, 2);
    assert.ok(revitRow.querySelector('.nc .nct') && revitRow.querySelector('.nc .ncb'), 'cards carry an icon tile and sockets');
    assert.ok(!/`/.test(h.doc.querySelector('article.card').textContent), 'no raw markdown');
    assert.ok([...h.doc.querySelectorAll('.dside [data-dfam]')].some(b => b.textContent.trim() === 'Revit'));

    // AG-23: Per-node doc page for Pure node + redacted file basename + upstream/downstream .pgraph
    const collectBtn = h.doc.querySelector('[data-docnode="revit.collect_sheets"]');
    await h.click(collectBtn);
    assert.equal(h.doc.querySelector('article.card .eyebrow').textContent.trim(), 'Node reference · Revit');
    assert.equal(h.doc.querySelector('article.card h2').textContent.trim(), 'Collect sheets');
    assert.match(h.doc.querySelector('article.card .f-ok').textContent, /Pure: it re-solves on every edit/);
    // File default parameter reduced to basename (never full directory path)
    const articleText = h.doc.querySelector('article.card').textContent;
    assert.match(articleText, /tower-a\.rvt/);
    assert.doesNotMatch(articleText, /\/projects\/demo\//);
    // Upstream -> active (.pn2.on) -> downstream in .pgraph
    const chain = [...h.doc.querySelectorAll('article.card .pgraph .pn2')].map(el => el.textContent.trim());
    assert.deepEqual(chain, ['Open model', 'Collect sheets', 'Write sheet register']);
    assert.equal(h.doc.querySelector('article.card .pgraph .pn2.on').textContent.trim(), 'Collect sheets');

    // All nodes back button -> then inspect Effect node banner -> Place on the Canvas
    await h.click(h.doc.querySelector('[data-docback]'));
    await h.click(h.doc.querySelector('[data-docnode="excel.write_register"]'));
    assert.match(h.doc.querySelector('article.card .f-warn').textContent, /Effect: it changes something outside the file/);
    await h.click(h.doc.querySelector('[data-docplace="excel.write_register"]'));
    assert.ok(h.calls.some(c => c[0] === 'addNode' && c[1] === 'excel.write_register'));
    assert.equal(h.getAppState().route, 'canvas');
  } finally {
    h.close();
  }
});

test('AG-32: Start the tutorial with BABOOM creates copy workflow, navigates to Canvas, advances steps 1 -> 2 -> 3, and supports Skip', async () => {
  const h = await mountStudio({}, {}, 'docs');
  try {
    const tutTopic = [...h.doc.querySelectorAll('.toc .tocb')].find(b => b.textContent.trim() === 'Your first workflow');
    await h.click(tutTopic);
    const startBtn = h.doc.querySelector('#starttut');
    assert.equal(startBtn.textContent.trim(), 'Start the tutorial with BABOOM');

    await h.click(startBtn);
    assert.equal(h.getAppState().route, 'canvas');
    assert.ok(h.calls.some(c => c[0] === 'newSession' && c[1] === 'Tutorial · your first workflow'));
    const nodeTitles = h.getState().graph.nodes.map(n => n.title);
    assert.deepEqual(nodeTitles, ['Goal: open a model', 'Action: collect sheets', 'Check: count is right']);
    assert.equal(h.calls.some(c => c[0] === 'runNode'), false, 'Tutorial copy must not auto-run');

    // Step 1 of 3 visible
    let guide = h.doc.querySelector('.guide');
    assert.ok(guide);
    assert.equal(guide.querySelector('.eyebrow').textContent.trim(), 'BABOOM · step 1 of 3');
    assert.match(guide.textContent, /Goal: open a model/);

    // Select node 0 -> advances to step 2 of 3
    const firstId = h.getState().graph.nodes[0].id;
    h.win.ReactDOM.flushSync(() => {
      h.setAppState({ selectedNodeId: firstId });
    });
    await h.settle(20);
    guide = h.doc.querySelector('.guide');
    assert.equal(guide.querySelector('.eyebrow').textContent.trim(), 'BABOOM · step 2 of 3');
    assert.match(guide.textContent, /Press Run on that node/);

    // Node 0 becomes Done -> advances to step 3 of 3 and schedules 6s completion dismissal
    let scheduled6sCallback = null;
    const origSetTimeout = h.win.setTimeout;
    h.win.setTimeout = (fn, ms, ...rest) => {
      if (ms === 6000) {
        scheduled6sCallback = fn;
        return 9999;
      }
      return origSetTimeout(fn, ms, ...rest);
    };
    h.win.ReactDOM.flushSync(() => {
      h.setState(prev => ({
        ...prev,
        graph: {
          ...prev.graph,
          nodes: prev.graph.nodes.map((n, i) => (i === 0 ? { ...n, status: 'Done' } : n))
        }
      }));
    });
    await h.settle(20);
    h.win.setTimeout = origSetTimeout;

    guide = h.doc.querySelector('.guide');
    assert.equal(guide.querySelector('.eyebrow').textContent.trim(), 'BABOOM · step 3 of 3');
    assert.match(guide.textContent, /That is a workflow: nodes, wires and Run/);
    assert.equal(typeof scheduled6sCallback, 'function', 'Step 3 schedules 6s auto-completion');

    // Trigger 6s completion timer -> TutorialOverlay dismisses
    h.win.ReactDOM.flushSync(() => {
      scheduled6sCallback();
    });
    await h.settle(15);
    assert.equal(h.doc.querySelector('.guide'), null);

    // Re-open tutorial and verify Skip button also dismisses immediately
    h.win.ReactDOM.flushSync(() => h.setAppState({ route: 'docs', selectedNodeId: null }));
    await h.settle(15);
    await h.click([...h.doc.querySelectorAll('.toc .tocb')].find(b => b.textContent.trim() === 'Your first workflow'));
    await h.click(h.doc.querySelector('#starttut'));
    assert.ok(h.doc.querySelector('.guide'));
    await h.click(h.doc.querySelector('.guide [data-tutx]'));
    assert.equal(h.doc.querySelector('.guide'), null);
  } finally {
    h.close();
  }
});

test('AG-29, AG-30: Library › Community preview installs a copy without running; Publish dialog blocks keys (no Community page)', async () => {
  const h = await mountStudio({
    community: {
      peers: [{ id: 'community:office', name: 'office', subscribed: true }],
      patterns: [{ id: 'p1', title: 'Sheet register to Excel', description: 'Collect sheets', source: 'community:office', status: 'Accepted' }],
      shared: [], groups: [], joinStatus: '', marketQuery: '', listing: {}, charge: {}, charges: [], marketplace: []
    },
    graphs: [{ id: 'g-pub', name: 'Issue Exporter', nodes: [{ id: 'n-sec', title: 'Upload bundle', effect: true,
      params: { api_key: 'sk-abc123secretkey', out_file: '/workspace/deliverables/bundle.ifc', endpoint: 'https://bim.example.org/upload' } }] }]
  }, {}, 'community-preview');

  try {
    assert.equal(h.win.UI.Community, undefined, 'the Community page is gone');
    // Only real owner records: the fixed sample catalogue is gone.
    assert.deepEqual(Array.from(h.win.UI.communityWorkflows(h.getState()), c => c.name), ['Sheet register to Excel']);

    // AG-30: Preview dialog (.pgraph + copy explanation) and Install without running
    const prevDialog = h.doc.querySelector('[role="dialog"][aria-label="Sheet register to Excel"]');
    assert.ok(prevDialog);
    assert.match(prevDialog.textContent, /Install makes a copy in its own \.archhub file\. Nothing runs until you press Run/);
    // AG-29: no price or charges UI (F22)
    assert.doesNotMatch(h.doc.body.textContent, /Creator share|Price · USD|Client project charges|Amount · USD|\$\d/);
    const runCallsBefore = h.calls.filter(c => c[0] === 'runNode').length;
    await h.click([...prevDialog.querySelectorAll('button')].find(b => b.textContent.trim() === 'Install'));
    assert.equal(h.calls.filter(c => c[0] === 'runNode').length, runCallsBefore, 'Install must never auto-run');
    assert.ok(h.calls.some(c => c[0] === 'newSession' && c[1] === 'Sheet register to Excel (copy)'));
    assert.ok(h.toasts.includes('Sheet register to Excel imported as a copy. Nothing ran; assign an agent or press Run.'));
    assert.equal(h.getAppState().route, 'canvas');

    // Publish dialog: live privacy check blocks secrets, then sends for review once the key is removed
    h.win.ReactDOM.flushSync(() => h.setAppState({ route: 'community-publish' }));
    await h.settle(15);
    let pubDialog = h.doc.querySelector('[role="dialog"][aria-label="Publish a workflow"]');
    assert.ok(pubDialog);
    await h.typeInput(pubDialog.querySelector('#pubt'), 'g-pub');
    assert.ok(pubDialog.querySelector('#pubcheck .f-err'), 'Secret key triggers error state in Privacy check');
    assert.match(pubDialog.querySelector('#pubcheck').textContent, /local path.*will be published as file names only/);
    await h.click([...pubDialog.querySelectorAll('button')].find(b => b.textContent.trim() === 'Publish'));
    assert.ok(h.toasts.includes('Remove the key first. Nothing was published.'));
    assert.ok(h.doc.querySelector('[role="dialog"][aria-label="Publish a workflow"]'), 'Dialog stays open when blocked');

    h.win.ReactDOM.flushSync(() => {
      h.setState(prev => ({ ...prev, graphs: [{ id: 'g-pub', name: 'Issue Exporter', nodes: [{ id: 'n-sec', title: 'Upload bundle', effect: true, params: { out_file: '/workspace/deliverables/bundle.ifc' } }] }] }));
    });
    await h.settle(15);
    pubDialog = h.doc.querySelector('[role="dialog"][aria-label="Publish a workflow"]');
    assert.equal(pubDialog.querySelector('#pubcheck .f-err'), null);
    await h.click([...pubDialog.querySelectorAll('button')].find(b => b.textContent.trim() === 'Publish'));
    assert.ok(h.toasts.includes('Issue Exporter sent for review before it is shared with Office. Paths are reduced to file names.'));
    assert.equal(h.doc.querySelector('[role="dialog"][aria-label="Publish a workflow"]'), null);
  } finally {
    h.close();
  }
});
