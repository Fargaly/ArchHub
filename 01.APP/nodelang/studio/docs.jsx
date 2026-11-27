// Documentation guide, per-node reference, glossary, and BABOOM Canvas tutorial overlay.
(() => {
  function executeAction(id, context, event) {
    if (typeof window.executeAction === 'function') return window.executeAction(id, context, event);
    return context?.handler?.(event);
  }
  const {
    api,
    useData,
    useApp
  } = window.UI;
  const Icon = window.AHIcon || (() => null);

  const TYPE_LABELS = {
    elements: 'Elements',
    number: 'Number',
    int: 'Whole number',
    text: 'Text',
    boolean: 'True or false',
    bool: 'Yes or no',
    file: 'File',
    folder: 'Folder',
    event: 'Trigger',
    view: 'View',
    color: 'Colour',
    any: 'Anything'
  };

  const PARAM_TYPE_LABELS = {
    sel: 'Choice',
    select: 'Choice',
    num: 'Number',
    number: 'Number',
    int: 'Whole number',
    integer: 'Whole number',
    bool: 'Yes or no',
    boolean: 'Yes or no',
    text: 'Text',
    string: 'Text',
    file: 'File',
    folder: 'Folder',
    list: 'List',
    color: 'Colour',
    date: 'Date'
  };

  const CORE_GLOSSARY = [
    ['Node', 'One block with typed sockets and parameters.'],
    ['Socket', 'A typed connection point. Colour is the type: Elements, Number, Text, True or false, File, Trigger, View, Anything.'],
    ['Wire', 'One connection from an output to an input, with its own rule.'],
    ['Session', 'An agent at work; it is a node on the Canvas and a thread in the Workshop.'],
    ['Workflow', 'A task saved as an .archhub file to run again.'],
    ['Skill', 'A workflow saved as one node in the Library.'],
    ['Done', 'The step ran and its result is on the node.'],
    ['Running', 'An agent is on this step now.'],
    ['Pending', 'Waiting for the steps before it.'],
    ['Needs approval', 'It changes something outside the workflow and waits for your Approve.'],
    ['Working', 'The agent is running steps.'],
    ['Waiting', 'Something needs you.'],
    ['Idle', 'Nothing is running.'],
    ['Planned', 'Set up; not started.'],
    ['Out of date', 'An input changed; press Run to update it.']
  ];

  const CORE_DOCS = {
    START: [
      ['First task', 'Say what you need in the New session box at the bottom of Home. ArchHub saves the work as its own .archhub file and opens its canvas.', [
        'The canvas opens with one Session node on the left. The agent, You, Parameters, Tools, Context and the thread are its panels: open one to change it; the Thread panel opens the thread beside the canvas. Any agent can join the same work.',
        'Tell the agent what you need in the thread, or press Tab and bring a node in from the Library.',
        'Steps that only read or compute run on their own. Steps that change files, send or publish wait for your Approve.',
        'Close the tab whenever you like: the file keeps everything, and Home shows where it stands.'
      ]]
    ],
    TUTORIALS: [
      ['Your first workflow', 'A short guided workflow: open a model, collect its sheets, check the count. BABOOM points at each control as you go.', [
        'It runs on the real controls, not a video, so what you learn is what you will use.',
        'You can stop at any step; the tutorial task stays on Home until you delete it.'
      ]]
    ],
    WORK: [
      ['Canvas and nodes', 'Each step is a node with typed sockets. Drag from an output to an input; a wrong type is refused with the reason and an Insert Convert fix.', [
        'Right-click anything (a node, a wire, a socket, the empty canvas) for its actions. The same actions are in Ctrl K with the same names and keys.',
        'Select nodes and press Ctrl G to group them. The group gets sockets from the wires that cross its edge; Ctrl E collapses it, Enter goes inside, Esc comes back out.',
        'Frames (Ctrl Alt G) only label and colour an area. Notes (N) are sticky text.',
        'Press F to fit everything, or zoom with the wheel. Below 60% nodes show their title and status only.'
      ]],
      ['Threads', 'Every task is a thread. Write to any agent from the composer; the message lands inside its session.', [
        'Agents answer in the same thread, and each reply that changes the canvas shows as a node change you can undo.',
        'Direct threads (an agent without a task) are listed under Agents.',
        'Everything that needs you is counted once: the same number on Home, the status bar, the Workshop badge and the bell.'
      ]],
      ['Approvals', 'Steps that change files outside the workflow wait for your Approve.', [
        'The waiting step shows an Approve card in the Inspector, on Home and in the thread, with what it will change and whether it can be undone.',
        'Approve runs it. Ask why sends the question to the agent. Reject resets the step and nothing is sent.',
        'Pressing R on such a step asks for approval; it never runs it straight away.'
      ]]
    ],
    CONFIGURE: [
      ['Look', 'Settings › Look holds every look value: theme, text size, density, accent and the canvas grid.', [
        'The Appearance node on the canvas shows the same values; changing one changes the other.',
        'Keyboard shortcuts are under Look › Keyboard. Each action has one shortcut, the same in menus and Ctrl K.'
      ]],
      ['Models', 'Settings › Agents › Models: free models first; a change applies on the next message.', [
        'Each agent can use a different model. Budgets per run are shown in your currency; ArchHub never bills you.',
        'If a model is down, the next one in the fallback list answers and the thread says which.'
      ]]
    ],
    'OFFICE STANDARD (BABOOM)': [
      ['Start here', 'The office standard from baboom.archhub.io: 77 standards, 6 templates and CAD sets, 888 families, 379 details, 116 tools, 17 training pages, 9 QA/QC checks. The same pages as on the site.', [
        'Search it here, or open it on baboom.archhub.io.',
        'A standard that has a matching node or ribbon tool says "Use it in ArchHub".',
        'Ask BABOOM about any of it from the companion in the rail.'
      ]],
      ['SHEETS-03 Sheet numbers and title block', 'How sheets are numbered and which title block they use.', [
        'Use it in ArchHub: Create sheets from list, Name check and fix.',
        'The Revit ribbon has the same tool: Sheet tools.'
      ]]
    ],
    REFERENCE: [
      ['Node reference', 'Revit, List, Check, Agent and Effect nodes, their sockets and parameters.', []],
      ['Glossary', 'Node, socket, wire, task, session, thread, workflow, skill.', []]
    ]
  };

  const DOC_GROUPS = [
    'START',
    'TUTORIALS',
    'WORK',
    'CONFIGURE',
    'OFFICE STANDARD (BABOOM)',
    'REFERENCE'
  ];

  const DOC_CAP = {
    'First task': 'Details library, a real task: the Session node on the left, the steps to the right in the order they run.',
    'Canvas and nodes': 'Drawing set review: each box is a node, each line a wire from an output to an input.',
    'Threads': 'Export issue package: the thread and the workflow are the same task.',
    'Approvals': 'The Approve card says what will change, and what Undo can and cannot bring back.'
  };

  const DOC_TRY = {
    'First task': ['Start a task now', u => u?.go?.('home')],
    'Canvas and nodes': ['Open a Canvas', u => u?.go?.('canvas')],
    'Threads': ['Open a thread', u => u?.go?.('workshop')],
    'Approvals': ['See what waits for you', u => u?.go?.('home')],
    'Look': ['Open Settings › Look', u => u?.go?.('settings/Appearance')],
    'Models': ['Open Settings › Agents', u => u?.go?.('settings/Agents')]
  };

  const LINKS = {
    App: {
      t: 'ArchHub app',
      d: 'This program on your PC. Every task is a Canvas file; agents, programs and you work on it. Every program tool comes three ways: a button in the program, a node on the Canvas, a tool agents call.',
      w: 'Home, Canvas, Docs, Settings',
      u: ''
    },
    Website: {
      t: 'archhub.io',
      d: 'The website. Same account as the app, same catalogue. Each Docs article and each Community item has a page there with "Open in ArchHub".',
      w: 'Your profile card › Your account on archhub.io; Docs › Open on the web',
      u: 'https://archhub.io'
    },
    Community: {
      t: 'Community',
      d: 'Workflows and nodes people share. Publish from a Canvas, install into your Library.',
      w: 'Canvas › Save › Publish to Community; Library › Community',
      u: 'https://archhub.io/community'
    },
    Docs: {
      t: 'Docs',
      d: 'The guide and the node reference. The same articles live on the website.',
      w: 'Docs in the rail; Settings search',
      u: 'https://archhub.io/docs'
    },
    BABOOM: {
      t: 'BABOOM',
      d: 'Your guide. The companion in the app teaches how ArchHub works; baboom.archhub.io holds the standard, families, details and tools. One persona in both.',
      w: 'The wizard at the bottom of the rail › BABOOM site',
      u: 'https://baboom.archhub.io'
    }
  };

  const CONCEPT = 'ArchHub is the connectors, the harness, the guardrails, the hooks, the orchestration layer, your companion and the integration base: one universal layer where AI, people and programs work together across all engineering work.';

  const CONNECT_POS = {
    App: [270, 150],
    Website: [470, 60],
    Community: [520, 210],
    Docs: [70, 60],
    BABOOM: [60, 230]
  };

  const CONNECT_EDGES = [
    ['App', 'Website', 'same account'],
    ['App', 'Community', 'publish · install'],
    ['App', 'Docs', 'same articles'],
    ['Website', 'Docs', 'docs pages'],
    ['Website', 'Community', 'lives on the site'],
    ['App', 'BABOOM', 'the guide'],
    ['BABOOM', 'Website', 'baboom.archhub.io']
  ];

  const TUT_STEPS = [
    'Click the first node, "Goal: open a model", to select it.',
    'Press Run on that node.',
    'That is a workflow: nodes, wires and Run. Change a parameter and press Run again any time.'
  ];

  const TUTORIAL_NODES = [
    'Goal: open a model',
    'Action: collect sheets',
    'Check: count is right'
  ];

  // Shared tutorial state for TutorialOverlay (AG-32) and cross-screen Docs deep-link.
  const tutorialListeners = new Set();
  let tutorialState = {
    active: false,
    step: 0,
    taskTitle: '',
    firstNodeId: null,
    completedAt: null
  };
  function setTutorialState(next) {
    tutorialState = typeof next === 'function' ? next(tutorialState) : next;
    tutorialListeners.forEach(fn => fn());
  }

  let pendingDocTarget = null;
  const docTargetListeners = new Set();
  window.UI.openDocTopic = (topic, nodeId = null) => {
    pendingDocTarget = { topic, nodeId };
    docTargetListeners.forEach(fn => fn(pendingDocTarget));
  };

  const DOCS_CSS = `
    .page.docs { padding: 24px 28px 40px; max-width: 1380px; margin: 0 auto; color: var(--color-ink, #ece8e1); }
    .page.docs .spread { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
    .page.docs h1 { font-size: 22px; font-weight: 650; margin: 0; letter-spacing: -0.01em; }
    .page.docs .sfind.dfind { display: inline-flex; align-items: center; gap: 8px; flex: 1 1 280px; max-width: 440px; background: var(--color-bg-panel, #15151a); border: 1px solid var(--color-line, #2a2a33); border-radius: 8px; padding: 0 10px; height: 34px; }
    .page.docs .sfind.dfind .field { border: 0; background: transparent; color: inherit; width: 100%; outline: none; font: inherit; font-size: 13px; }
    .page.docs .docgrid.d3 { display: grid; grid-template-columns: 220px minmax(0, 1fr) 230px; gap: 20px; align-items: start; }
    @media (max-width: 980px) { .page.docs .docgrid.d3 { grid-template-columns: 1fr; } }
    .page.docs .toc, .page.docs .dside { display: flex; flex-direction: column; gap: 3px; }
    .page.docs .eyebrow, .guide .eyebrow { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-ink-soft, #9b958d); margin: 12px 0 4px; display: block; }
    .page.docs .toc .eyebrow:first-child, .page.docs .dside section:first-child .eyebrow, .guide .eyebrow { margin-top: 0; }
    .page.docs .tocb { text-align: left; background: transparent; border: 0; color: var(--color-ink-soft, #9b958d); padding: 6px 10px; border-radius: 6px; cursor: pointer; font: inherit; font-size: 13px; line-height: 1.35; }
    .page.docs .tocb:hover { background: rgba(255,255,255,0.04); color: var(--color-ink, #ece8e1); }
    .page.docs .tocb.on { background: rgba(217,119,87,0.14); color: var(--color-ink, #ece8e1); font-weight: 600; }
    .page.docs article.card { background: var(--color-bg-panel, #15151a); border: 1px solid var(--color-line, #2a2a33); border-radius: 12px; padding: 24px 28px; min-width: 0; }
    .page.docs article.card h2 { margin: 0 0 8px; font-size: 20px; font-weight: 650; }
    .page.docs article.card h3 { margin: 20px 0 8px; font-size: 14px; font-weight: 600; }
    .page.docs .dlead { font-size: 14.5px; line-height: 1.55; color: var(--color-ink, #ece8e1); margin: 0 0 16px; }
    .page.docs .dsteps { margin: 0 0 18px; padding-left: 20px; display: grid; gap: 10px; line-height: 1.5; font-size: 13.5px; }
    .page.docs .dsteps li.cue { background: rgba(217,119,87,0.16); border-radius: 6px; padding: 4px 8px; transition: background 0.25s ease; }
    .page.docs .dfig { margin: 20px 0 4px; padding: 16px; border-radius: 10px; background: rgba(0,0,0,0.22); border: 1px solid var(--color-line, #2a2a33); }
    .page.docs .dfig figcaption { margin-top: 10px; font-size: 12px; color: var(--color-ink-soft, #9b958d); }
    .page.docs .dside section { margin-bottom: 14px; display: flex; flex-direction: column; gap: 4px; }
    .page.docs .gloss { display: grid; grid-template-columns: minmax(120px, 160px) 1fr; gap: 8px 16px; margin: 14px 0 0; font-size: 13px; }
    .page.docs .gloss dt { font-weight: 600; color: var(--color-ink, #ece8e1); }
    .page.docs .gloss dd { margin: 0; color: var(--color-ink-soft, #9b958d); line-height: 1.45; }
    .page.docs .tablewrap { overflow-x: auto; margin: 8px 0 14px; }
    .page.docs table.mini { width: 100%; border-collapse: collapse; font-size: 13px; }
    .page.docs table.mini th, .page.docs table.mini td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--color-line, #2a2a33); vertical-align: top; }
    .page.docs .link, .guide .link { background: none; border: 0; padding: 0; color: var(--color-accent, #d97757); cursor: pointer; font: inherit; text-decoration: underline; text-underline-offset: 2px; }
    .page.docs .btn { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 12px; border-radius: 7px; border: 1px solid var(--color-line, #2a2a33); background: #222229; color: var(--color-ink, #ece8e1); font: 500 13px var(--font-sans, Inter, sans-serif); cursor: pointer; text-decoration: none; }
    .page.docs .btn.sm { height: 28px; padding: 0 10px; font-size: 12px; }
    .page.docs .btn.btn-primary { background: var(--color-accent, #d97757); border-color: var(--color-accent, #d97757); color: #fff; font-weight: 600; }
    .page.docs .btn:disabled { opacity: 0.5; cursor: default; }
    .page.docs .f-ok { color: var(--color-ok, #58b368); }
    .page.docs .f-warn { color: var(--color-warn, #e5b25a); }
    .page.docs .sub { color: var(--color-ink-soft, #9b958d); font-size: 12.5px; margin: 6px 0; }
    .page.docs .pgraph { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 10px 0 16px; }
    .page.docs .pn2 { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 7px; background: #1e1e25; border: 1px solid var(--color-line, #2a2a33); font-size: 12.5px; }
    .page.docs .pn2.on { border-color: var(--color-accent, #d97757); background: rgba(217,119,87,0.14); font-weight: 600; }
    .page.docs .pw { width: 18px; height: 2px; background: var(--color-line, #2a2a33); display: inline-block; }
    .page.docs .sact { display: flex; align-items: center; gap: 8px; margin: 16px 0 10px; }
    .page.docs .sk { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--color-ink-soft, #9b958d); margin-right: 5px; vertical-align: middle; }
    .page.docs .sk.l { border-radius: 2px; }
    .page.docs .sk.t-elements { background: #d97757; }
    .page.docs .sk.t-number, .page.docs .sk.t-int { background: #e5b25a; }
    .page.docs .sk.t-file, .page.docs .sk.t-folder { background: #58b368; }
    .page.docs .sk.t-boolean, .page.docs .sk.t-bool { background: #a87ffb; }
    .page.docs .sk.t-event, .page.docs .sk.t-view { background: #56b6c2; }
    .page.docs .cmap { display: grid; grid-template-columns: minmax(0, 1fr) 240px; gap: 16px; align-items: start; margin-top: 12px; }
    .page.docs .cmapc { position: relative; height: 320px; background: rgba(0,0,0,0.24); border: 1px solid var(--color-line, #2a2a33); border-radius: 10px; overflow: hidden; }
    .page.docs .cmapl { width: 100%; height: 100%; }
    .page.docs .cmapl line { stroke: #3a3a46; stroke-width: 1.5; }
    .page.docs .cmapl text { fill: #9b958d; font-size: 10px; text-anchor: middle; }
    .page.docs .cbox { position: absolute; min-width: 132px; height: 40px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--color-line, #2a2a33); background: #1e1e26; color: var(--color-ink, #ece8e1); font: 600 12.5px var(--font-sans, Inter, sans-serif); cursor: pointer; }
    .page.docs .cbox.on { border-color: var(--color-accent, #d97757); background: rgba(217,119,87,0.18); }
    .guide { position: fixed; bottom: 24px; right: 24px; z-index: 950; max-width: 360px; padding: 14px 18px; border-radius: 12px; background: var(--color-bg-panel, #18181f); border: 1px solid var(--color-accent, #d97757); box-shadow: 0 10px 32px rgba(0,0,0,0.45); color: var(--color-ink, #ece8e1); display: grid; gap: 6px; }
    .guide p { margin: 0; font-size: 13.5px; line-height: 1.45; }
  `;

  function slugify(value) {
    return String(value || 'guide').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'guide';
  }

  function baseName(value) {
    return String(value ?? '').split(/[\\/]/).filter(Boolean).pop() || String(value ?? '');
  }

  function normalizeSocketType(raw) {
    const t = String(raw || 'any').toLowerCase();
    if (t === 'boolean') return 'bool';
    if (t === 'integer') return 'int';
    if (t === 'string') return 'text';
    return t;
  }

  function cleanStepLine(line) {
    return String(line || '').replace(/^#+\s*/, '').replace(/^\d+\.\s*/, '').trim();
  }

  function parseGlossaryRows(bookGlossary) {
    const map = new Map();
    for (const [term, def] of CORE_GLOSSARY) {
      map.set(term.toLowerCase(), [term, def]);
    }
    for (const entry of Array.isArray(bookGlossary) ? bookGlossary : []) {
      let term = '', def = '';
      if (Array.isArray(entry) && entry.length >= 2) {
        [term, def] = [String(entry[0] || '').trim(), String(entry[1] || '').trim()];
      } else if (entry && typeof entry === 'object') {
        term = String(entry.term || entry.name || entry.title || '').trim();
        def = String(entry.definition || entry.summary || entry.description || '').trim();
      } else if (typeof entry === 'string') {
        const parts = entry.split('|').map(p => p.replaceAll('**', '').trim()).filter(Boolean);
        if (parts.length >= 2 && !/^[-:]+$/.test(parts[0]) && parts[0].toLowerCase() !== 'term') {
          [term, def] = [parts[0], parts[1]];
        } else {
          const m = entry.match(/^[-*]?\s*\*\*([^*]+)\*\*[:\s—-]+(.+)$/);
          if (m) [term, def] = [m[1].trim(), m[2].trim()];
        }
      }
      if (term && def) {
        const key = term.toLowerCase();
        if (!map.has(key)) map.set(key, [term, def]);
      }
    }
    return [...map.values()];
  }

  function normalizeLibraryNodes(s) {
    const byId = new Map();
    const portsList = Array.isArray(s?.libraryPorts) ? s.libraryPorts : [];
    const catList = Array.isArray(s?.catalogue) ? s.catalogue : [];
    for (const p of portsList) {
      if (!p || !p.id) continue;
      const g = p.cat || p.family || 'Nodes';
      const effect = p.pure === undefined
        ? /change|send|write|export|publish|effect/i.test(g + ' ' + String(p.engine || ''))
        : !p.pure;
      const fam = effect ? 'effect' : /agent|session|baboom/i.test(g) ? 'agent' : /revit|cad|ifc|bim|model/i.test(g) ? 'model' : 'list';
      const ins = (p.ports?.target || p.inputs || []).map(port => ({
        id: port.id || port.name,
        n: port.label || port.name || port.id,
        t: normalizeSocketType(port.type),
        list: port.cardinality === 'many' || Boolean(port.list)
      }));
      const outs = (p.ports?.source || p.outputs || []).map(port => ({
        id: port.id || port.name,
        n: port.label || port.name || port.id,
        t: normalizeSocketType(port.type),
        list: port.cardinality === 'many' || Boolean(port.list)
      }));
      const defs = Array.isArray(p.paramDefs) ? p.paramDefs : [];
      const rawParams = p.params && typeof p.params === 'object' ? p.params : {};
      const seenParams = new Set();
      const params = [];
      for (const d of defs) {
        const key = d.id || d.name;
        if (!key) continue;
        seenParams.add(key);
        params.push({
          n: d.name || d.label || key,
          t: d.type || 'text',
          v: Object.hasOwn(rawParams, key) ? rawParams[key] : (d.default ?? ''),
          o: Array.isArray(d.options) && d.options.length ? d.options : null,
          min: d.min,
          max: d.max,
          u: d.unit || ''
        });
      }
      for (const [k, v] of Object.entries(rawParams)) {
        if (seenParams.has(k)) continue;
        params.push({
          n: k,
          t: typeof v === 'boolean' ? 'bool' : typeof v === 'number' ? 'num' : Array.isArray(v) ? 'list' : 'text',
          v,
          o: null
        });
      }
      byId.set(p.id, {
        id: p.id,
        n: p.title || p.name || p.id,
        g,
        src: p.sub || p.description || (p.engine ? 'Engine · ' + p.engine : 'Built-in node'),
        effect,
        fam,
        icon: effect ? 'send' : fam === 'agent' ? 'brain' : 'canvas',
        ins,
        outs,
        params,
        executable: !p.noEngine && p.available !== false
      });
    }
    for (const c of catList) {
      if (!c || !c.id || byId.has(c.id)) continue;
      const g = c.family || c.category || 'Nodes';
      const effect = c.pure === undefined
        ? /change|send|write|export|publish|effect/i.test(g + ' ' + String(c.descriptor?.engine || ''))
        : !c.pure;
      const fam = effect ? 'effect' : /agent|session|baboom/i.test(g) ? 'agent' : 'list';
      const ins = Array.isArray(c.inputs)
        ? c.inputs.map(p => ({ id: p.id || p.n || p.name, n: p.n || p.label || p.name || p.id, t: normalizeSocketType(p.t || p.type), list: Boolean(p.list) }))
        : c.input ? [{ id: 'in', n: 'Input', t: normalizeSocketType(c.input), list: false }] : [];
      const outs = Array.isArray(c.outputs)
        ? c.outputs.map(p => ({ id: p.id || p.n || p.name, n: p.n || p.label || p.name || p.id, t: normalizeSocketType(p.t || p.type), list: Boolean(p.list) }))
        : c.output ? [{ id: 'out', n: 'Result', t: normalizeSocketType(c.output), list: false }] : [];
      const params = Array.isArray(c.params)
        ? c.params.map(p => ({ n: p.n || p.name || p.id, t: p.t || p.type || 'text', v: p.v ?? p.default ?? '', o: p.o || p.options || null, min: p.min, max: p.max, u: p.u || p.unit || '' }))
        : [];
      byId.set(c.id, {
        id: c.id,
        n: c.name || c.title || c.id,
        g,
        src: c.description || (c.descriptor?.engine ? 'Engine · ' + c.descriptor.engine : 'Built-in node'),
        effect,
        fam,
        icon: effect ? 'send' : fam === 'agent' ? 'brain' : 'canvas',
        ins,
        outs,
        params,
        executable: !c.unavailable
      });
    }
    return [...byId.values()];
  }

  function normalizeBaboomRules(s) {
    const raw = s?.baboomStandard;
    const list = Array.isArray(raw) ? raw : Array.isArray(raw?.rules) ? raw.rules : Array.isArray(raw?.items) ? raw.items : [];
    const out = [];
    for (const r of list) {
      if (Array.isArray(r) && r.length >= 2) {
        const code = String(r[0] || '').trim();
        const summary = String(r[1] || '').trim();
        if (code) out.push({ code, title: `${code} ${summary.split(':')[0].trim()}`, summary, steps: r[2] || ['Use it in ArchHub from the Library or ask BABOOM in the rail.'] });
      } else if (r && typeof r === 'object') {
        const code = String(r.code || r.id || '').trim();
        const namePart = String(r.title || r.name || '').trim();
        const summary = String(r.summary || r.description || r.what || namePart).trim();
        const fullTitle = code && !namePart.startsWith(code) ? `${code} ${namePart || summary.split(':')[0]}`.trim() : (namePart || code);
        const steps = Array.isArray(r.steps) && r.steps.length
          ? r.steps
          : [
              r.tools ? `Use it in ArchHub: ${Array.isArray(r.tools) ? r.tools.join(', ') : r.tools}.` : 'Search it here, or open it on baboom.archhub.io.',
              'Ask BABOOM about this rule from the companion in the rail.'
            ];
        if (fullTitle) out.push({ code: code || fullTitle, title: fullTitle, summary, steps });
      }
    }
    return out;
  }

  function buildDocGroups(sourceDocs, s) {
    const groups = Object.fromEntries(DOC_GROUPS.map(g => [g, []]));
    const seenTitles = new Set();
    const pushItem = (group, item) => {
      const key = item.title.toLowerCase();
      if (seenTitles.has(key)) return;
      seenTitles.add(key);
      groups[group].push({ ...item, group });
    };

    for (const g of DOC_GROUPS) {
      for (const [title, summary, steps] of CORE_DOCS[g] || []) {
        pushItem(g, {
          id: slugify(title),
          title,
          summary,
          steps: steps || [],
          route: g === 'CONFIGURE' ? 'settings' : g === 'START' ? 'home' : 'canvas'
        });
      }
    }

    for (const rule of normalizeBaboomRules(s)) {
      pushItem('OFFICE STANDARD (BABOOM)', {
        id: 'std-' + slugify(rule.code || rule.title),
        title: rule.title,
        summary: rule.summary,
        steps: rule.steps
      });
    }

    for (const d of Array.isArray(sourceDocs) ? sourceDocs : []) {
      if (!d || !d.title) continue;
      const id = String(d.id || slugify(d.title));
      const cat = String(d.category || '').toUpperCase();
      let g = 'WORK';
      if (cat === 'TUTORIALS' || /^tutorial/i.test(id)) g = 'TUTORIALS';
      else if (cat === 'OFFICE STANDARD (BABOOM)' || /baboom|standard/i.test(cat)) g = 'OFFICE STANDARD (BABOOM)';
      else if (cat === 'START' || /^(getting-started|home|composer-canvas|account-web)$/.test(id)) g = 'START';
      else if (cat === 'CONFIGURE' || /brain|model|routing|privacy|setting|updat/.test(id)) g = 'CONFIGURE';
      else if (cat === 'REFERENCE') g = 'REFERENCE';
      pushItem(g, {
        id,
        title: d.title,
        summary: d.summary || '',
        steps: (d.steps || []).map(cleanStepLine).filter(Boolean),
        route: d.route || 'canvas'
      });
    }

    // Keep REFERENCE items last in REFERENCE (`Node reference`, `Glossary`).
    return groups;
  }

  function renderArticleFigure(title, s) {
    if (title === 'Approvals') {
      const card = Array.isArray(s?.approvals) && s.approvals[0];
      return <div className="approve-card insp-card" style={{ padding: 14, borderRadius: 8, border: '1px solid var(--color-line, #2a2a33)', background: '#191920' }}>
        <span className="eyebrow">Needs your approval</span>
        <strong style={{ display: 'block', marginBottom: 4 }}>{card?.title || 'Write sheet register'}</strong>
        <p className="sub" style={{ margin: '0 0 8px' }}>{card?.summary || 'It changes files outside the workflow, so it waits for your Approve. Undo restores workflow parameters; external file writes list their target first.'}</p>
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="btn btn-primary sm" aria-hidden="true">Approve</span>
          <span className="btn sm" aria-hidden="true">Ask why</span>
          <span className="btn sm" aria-hidden="true">Reject</span>
        </div>
      </div>;
    }
    const labels = title === 'First task'
      ? ['Session', 'Collect details', 'Write index']
      : title === 'Canvas and nodes'
        ? ['Open model', 'Collect sheets', 'Check title block']
        : ['Session · Thread', 'Export IFC', 'Package issue'];
    return <svg viewBox="0 0 460 74" width="100%" height="74" role="img" aria-label={title + ' diagram'}>
      {labels.map((lbl, idx) => {
        const x = 12 + idx * 150;
        return <g key={lbl}>
          {idx > 0 && <line x1={x - 26} y1={37} x2={x} y2={37} stroke="#d97757" strokeWidth="2" />}
          <rect x={x} y={15} width={124} height={44} rx={8} fill="#1d1d24" stroke={idx === 0 ? '#d97757' : '#343440'} strokeWidth="1.4" />
          <circle cx={x + 12} cy={37} r={3.5} fill={idx === 0 ? '#56b6c2' : '#d97757'} />
          <text x={x + 22} y={41} fill="#ece8e1" fontSize="11" fontFamily="Inter, sans-serif">{lbl}</text>
        </g>;
      })}
    </svg>;
  }

  function emitToast(u, setLocalToast, message, action = null) {
    if (typeof u?.setToast === 'function') u.setToast(message);
    else if (typeof u?.toast === 'function') u.toast(message);
    if (typeof window.dispatchEvent === 'function' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new window.CustomEvent('archhub:notice', { detail: { message } }));
    }
    setLocalToast({ message, action });
  }

  async function createTutorialCopy(api, s, u) {
    const taskTitle = 'Tutorial · your first workflow';
    const runAct = fn => (typeof u?.act === 'function' ? u.act(fn) : Promise.resolve().then(fn));
    let firstNodeId = null;

    if (typeof api?.createTutorialWorkflow === 'function') {
      const res = await runAct(() => api.createTutorialWorkflow(taskTitle, TUTORIAL_NODES));
      firstNodeId = res?.firstNodeId || res?.nodes?.[0]?.id || null;
    } else {
      if (typeof api?.newSession === 'function') {
        await runAct(() => api.newSession(taskTitle)).catch(() => null);
      } else if (typeof api?.addGraph === 'function') {
        await runAct(() => api.addGraph(taskTitle)).catch(() => null);
      }
      const lib = normalizeLibraryNodes(s).filter(x => x.executable);
      const created = [];
      for (let i = 0; i < TUTORIAL_NODES.length; i++) {
        const stepTitle = TUTORIAL_NODES[i];
        let node = null;
        if (typeof api?.addNode === 'function' && lib.length > 0) {
          const pick = lib[i % lib.length];
          node = await runAct(() => api.addNode(pick.id, { x: 120 + i * 280, y: 140 })).catch(() => null);
          if (node?.id && typeof api?.renameNode === 'function') {
            await runAct(() => api.renameNode(node.id, stepTitle)).catch(() => null);
          }
        } else if (typeof api?.addNote === 'function') {
          node = await runAct(() => api.addNote(stepTitle, { x: 120 + i * 280, y: 140 })).catch(() => null);
        }
        if (node?.id) created.push(node);
      }
      if (created.length >= 2 && typeof api?.connectSockets === 'function') {
        for (let i = 0; i < created.length - 1; i++) {
          const fromOut = created[i].outputs?.[0]?.id;
          const toIn = created[i + 1].inputs?.[0]?.id;
          if (fromOut && toIn) {
            await runAct(() => api.connectSockets({ from: created[i].id, fromPort: fromOut, to: created[i + 1].id, toPort: toIn })).catch(() => null);
          }
        }
      }
      firstNodeId = created[0]?.id || null;
    }

    setTutorialState({
      active: true,
      step: 0,
      taskTitle,
      firstNodeId,
      completedAt: null
    });
    u?.go?.('canvas');
  }

  function subscribeTutorial(cb) {
    tutorialListeners.add(cb);
    return () => tutorialListeners.delete(cb);
  }
  function getTutorial() {
    return tutorialState;
  }

  function TutorialOverlay() {
    const s = useData() || {};
    const u = useApp() || {};
    const tut = React.useSyncExternalStore(subscribeTutorial, getTutorial, getTutorial);

    const nodes = Array.isArray(s?.graph?.nodes) ? s.graph.nodes : [];
    const firstNode = React.useMemo(() => {
      if (tut.firstNodeId) {
        const exact = nodes.find(n => n.id === tut.firstNodeId);
        if (exact) return exact;
      }
      return nodes.find(n => n.title === TUTORIAL_NODES[0])
        || nodes.find(n => !n.fixed && n.kind !== 'session')
        || nodes[0]
        || null;
    }, [nodes, tut.firstNodeId]);

    const targetId = firstNode?.id || tut.firstNodeId;
    const selectedId = u?.selectedNodeId ?? s?.selectedNodeId ?? null;
    const isNodeDone = Boolean(
      firstNode && (
        /^(done|solved)$/i.test(String(firstNode.status || '')) ||
        /^(done|solved)$/i.test(String(firstNode.result?.status || ''))
      )
    );

    React.useLayoutEffect(() => {
      if (!tut.active) return;
      if (tut.step === 0 && selectedId && (!targetId || selectedId === targetId)) {
        setTutorialState(prev => (prev.active && prev.step === 0 ? { ...prev, step: 1 } : prev));
      } else if (tut.step === 1 && isNodeDone) {
        setTutorialState(prev => (prev.active && prev.step === 1 ? { ...prev, step: 2, completedAt: Date.now() } : prev));
      }
    }, [tut.active, tut.step, selectedId, targetId, isNodeDone]);

    const dismissMs = Number(s?.runtimeParameters?.tutorial_complete_ms ?? 6000);
    React.useLayoutEffect(() => {
      if (!tut.active || tut.step !== 2 || !Number.isFinite(dismissMs) || dismissMs <= 0) return undefined;
      const timer = window.setTimeout(() => {
        setTutorialState(prev => (prev.active && prev.step === 2 ? { ...prev, active: false } : prev));
      }, dismissMs);
      return () => window.clearTimeout(timer);
    }, [tut.active, tut.step, dismissMs]);

    const onCanvas = !u?.route || u.route === 'canvas' || u.route === 'task-file';
    if (!tut.active || !onCanvas) return null;

    return <>
      <style>{DOCS_CSS}</style>
      <div className="guide" role="status" aria-live="polite" data-tutorial-step={tut.step + 1}>
        <span className="eyebrow">BABOOM · step {tut.step + 1} of 3</span>
        <p>{TUT_STEPS[tut.step]}</p>
        <button type="button" className="link" data-tutx onClick={event => executeAction('projects.docs.SkipTutorial', { handler: () => setTutorialState(prev => ({ ...prev, active: false })) }, event)}>Skip the tutorial</button>
      </div>
    </>;
  }

  function Docs() {
    const s = useData() || {};
    const u = useApp() || {};
    const [query, setQuery] = React.useState('');
    const [selectedTitle, setSelectedTitle] = React.useState(() => pendingDocTarget?.topic || 'First task');
    const [docNode, setDocNode] = React.useState(() => pendingDocTarget?.nodeId || null);
    const [guide, setGuide] = React.useState(null);
    const [docState, setDocState] = React.useState('idle');
    const [docError, setDocError] = React.useState('');
    const [connectPick, setConnectPick] = React.useState(null);
    const [cuedStep, setCuedStep] = React.useState(null);
    const [localToast, setLocalToast] = React.useState(null);
    const articleRef = React.useRef(null);

    React.useEffect(() => {
      if (pendingDocTarget) {
        if (pendingDocTarget.topic) setSelectedTitle(pendingDocTarget.topic);
        setDocNode(pendingDocTarget.nodeId || null);
        pendingDocTarget = null;
      }
      const onTarget = target => {
        if (target?.topic) setSelectedTitle(target.topic);
        setDocNode(target?.nodeId || null);
        pendingDocTarget = null;
      };
      docTargetListeners.add(onTarget);
      return () => docTargetListeners.delete(onTarget);
    }, []);

    const loadDocs = React.useCallback(() => {
      if (typeof api?.refreshDocs !== 'function') return undefined;
      setDocState('waiting');
      setDocError('');
      return Promise.resolve(api.refreshDocs()).then(pages => {
        if (Array.isArray(pages)) {
          setGuide(pages);
          setDocState(pages.length ? 'loaded' : 'empty');
        } else {
          setDocState('empty');
        }
      }).catch(err => {
        setDocError(err?.message || 'Documentation could not be refreshed.');
        setDocState('error');
      });
    }, []);

    React.useEffect(() => {
      loadDocs();
    }, [loadDocs]);

    const toastMs = Number(s?.runtimeParameters?.toast_visible_ms);
    React.useEffect(() => {
      if (!localToast || !Number.isFinite(toastMs) || toastMs <= 0) return undefined;
      const t = window.setTimeout(() => setLocalToast(null), toastMs);
      return () => window.clearTimeout(t);
    }, [localToast, toastMs]);

    const sourceDocs = guide || s.docs || [];
    const grouped = React.useMemo(() => buildDocGroups(sourceDocs, s), [sourceDocs, s.baboomStandard]);
    const allTopics = React.useMemo(() => DOC_GROUPS.flatMap(g => grouped[g] || []), [grouped]);
    const libNodes = React.useMemo(() => normalizeLibraryNodes(s), [s.libraryPorts, s.catalogue]);
    const glossaryRows = React.useMemo(() => parseGlossaryRows(s.bookGlossary), [s.bookGlossary]);

    const active = allTopics.find(x => x.title === selectedTitle) || allTopics[0];
    const activeNode = active?.title === 'Node reference' && docNode ? libNodes.find(x => x.id === docNode) : null;
    const q = query.trim().toLowerCase();

    const topicMatchesQuery = item => {
      if (!q) return true;
      const hay = `${item.title} ${item.summary} ${(item.steps || []).join(' ')}`.toLowerCase();
      return hay.includes(q);
    };

    const docsFind = raw => {
      const v = String(raw || '').trim();
      if (!v) return;
      const words = v.toLowerCase().split(/\s+/).filter(Boolean);
      const hit = allTopics.find(a => words.some(x => x.length > 3 && a.title.toLowerCase().includes(x.slice(0, 6))))
        || allTopics.find(a => words.every(x => `${a.title} ${a.summary} ${(a.steps || []).join(' ')}`.toLowerCase().includes(x)))
        || allTopics.find(a => words.some(x => x.length > 3 && `${a.title} ${a.summary}`.toLowerCase().includes(x)));
      if (hit) {
        setSelectedTitle(hit.title);
        setDocNode(null);
        emitToast(u, setLocalToast, `Opened “${hit.title}”.`);
      } else {
        emitToast(u, setLocalToast, 'No article matches. Ask an agent instead?', ['Ask an agent', () => u?.go?.('home')]);
      }
    };

    const handleCueStep = idx => {
      setCuedStep(idx);
      const el = articleRef.current?.querySelectorAll?.('.dsteps li')?.[idx];
      el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    };

    const handlePlaceNode = async nodeItem => {
      const runAct = fn => (typeof u?.act === 'function' ? u.act(fn) : Promise.resolve().then(fn));
      const made = await runAct(() => api.addNode(nodeItem.id));
      if (made) {
        u?.setSelectedNodeId?.(made.id);
        u?.go?.('canvas');
      }
    };

    const handleAskBaboom = () => {
      const subject = activeNode ? activeNode.n : active?.title || 'Documentation';
      const prompt = `Explain ${subject} for my task`;
      u?.setCompanion?.(true);
      if (typeof window.dispatchEvent === 'function' && typeof window.CustomEvent === 'function') {
        window.dispatchEvent(new window.CustomEvent('archhub:ask-baboom', { detail: { topic: subject, prompt } }));
      }
      if (typeof api?.sendToBaboom === 'function' && (!api.supportsAction || api.supportsAction('sendToBaboom'))) {
        Promise.resolve(api.sendToBaboom(prompt)).catch(err => {
          emitToast(u, setLocalToast, err?.message || 'BABOOM could not be reached.');
        });
      }
      emitToast(u, setLocalToast, `Asked BABOOM about ${subject}.`);
    };

    const renderGlossary = () => {
      const rows = q ? glossaryRows.filter(([t, d]) => `${t} ${d}`.toLowerCase().includes(q)) : glossaryRows;
      if (!rows.length) return <p className="sub">No glossary entries match “{query}”.</p>;
      return <dl className="gloss">
        {rows.map(([term, def]) => <React.Fragment key={term}>
          <dt>{term}</dt>
          <dd>{window.UI.Prose ? <window.UI.Prose text={def} /> : def}</dd>
        </React.Fragment>)}
      </dl>;
    };

    const renderNodeRef = () => {
      const visible = q ? libNodes.filter(x => `${x.g} ${x.n} ${x.src}`.toLowerCase().includes(q)) : libNodes;
      const groups = [...new Set(visible.map(x => x.g))];
      if (!groups.length) return <p className="sub">No nodes match.</p>;
      return <div className="tablewrap">
        <table className="mini">
          <thead>
            <tr><th>Group</th><th>Nodes</th><th>Count</th></tr>
          </thead>
          <tbody>
            {groups.map(g => {
              const items = visible.filter(x => x.g === g);
              return <tr key={g}>
                <td>{g}</td>
                <td>{items.map((x, i) => <React.Fragment key={x.id}>
                  {i > 0 ? ', ' : ''}
                  <button type="button" className="link" data-docnode={x.id} onClick={event => executeAction('projects.docs.SelectNode', { handler: () => setDocNode(x.id) }, event)}>{x.n}</button>
                </React.Fragment>)}</td>
                <td>{items.length}</td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>;
    };

    const renderNodePage = it => {
      const compatUp = libNodes.filter(x => x.id !== it.id && it.ins[0] && x.outs.some(o => o.t === it.ins[0].t || o.t === 'any' || it.ins[0].t === 'any'));
      const up = compatUp.find(x => !x.effect && x.ins.length === 0) || compatUp.find(x => !x.effect) || compatUp[0] || null;
      const compatDn = libNodes.filter(x => x.id !== it.id && it.outs[0] && x.ins[0] && (x.ins[0].t === it.outs[0].t || x.ins[0].t === 'any' || it.outs[0].t === 'any'));
      const dn = compatDn.find(x => x.id !== up?.id) || compatDn[0] || null;
      const sockRow = (p, side, idx) => <tr key={side + '-' + (p.id || p.n || idx)}>
        <td><i className={'sk t-' + p.t + (p.list ? ' l' : '')} /> {p.n}</td>
        <td>{TYPE_LABELS[p.t] || p.t}{p.list ? ' list' : ''}</td>
        <td>{side}</td>
      </tr>;
      return <>
        <span className="eyebrow">Node reference · {it.g}</span>
        <h2>{it.n}</h2>
        <p className="sub">{it.src}</p>
        <p className={it.effect ? 'f-warn' : 'f-ok'}>
          {it.effect
            ? 'Effect: it changes something outside the file, so it runs only on Run and waits for your Approve.'
            : 'Pure: it re-solves on every edit and changes nothing outside the file.'}
        </p>
        <h3>Sockets</h3>
        <div className="tablewrap">
          <table className="mini">
            <thead><tr><th>Socket</th><th>Type</th><th>Side</th></tr></thead>
            <tbody>
              {it.ins.map((p, idx) => sockRow(p, 'Input', idx))}
              {it.outs.map((p, idx) => sockRow(p, 'Output', idx))}
              {!it.ins.length && !it.outs.length && <tr><td colSpan={3} className="sub">No sockets declared.</td></tr>}
            </tbody>
          </table>
        </div>
        <h3>Parameters</h3>
        {it.params.length ? <div className="tablewrap">
          <table className="mini">
            <thead><tr><th>Parameter</th><th>Type</th><th>Default</th><th>Range or choices</th></tr></thead>
            <tbody>
              {it.params.map((p, idx) => <tr key={p.n + '-' + idx}>
                <td>{p.n}</td>
                <td>{PARAM_TYPE_LABELS[p.t] || p.t}</td>
                <td>{Array.isArray(p.v) ? `${p.v.length} items` : (p.t === 'file' || p.t === 'folder' ? baseName(p.v) : String(p.v ?? ''))}</td>
                <td>{p.o ? p.o.join(', ') : (p.min != null && p.max != null ? `${p.min} to ${p.max}${p.u ? ' ' + p.u : ''}` : '')}</td>
              </tr>)}
            </tbody>
          </table>
        </div> : <p className="sub">No parameters.</p>}
        <h3>Example</h3>
        <div className="pgraph">
          {up && <>
            <span className="pn2"><span className={'tile fam-' + up.fam}><Icon name={up.icon} size={11} /></span>{up.n}</span>
            <span className="pw" />
          </>}
          <span className="pn2 on"><span className={'tile fam-' + it.fam}><Icon name={it.icon} size={11} /></span>{it.n}</span>
          {dn && <>
            <span className="pw" />
            <span className="pn2"><span className={'tile fam-' + dn.fam}><Icon name={dn.icon} size={11} /></span>{dn.n}</span>
          </>}
        </div>
        <div className="sact">
          <button type="button" className="btn btn-primary" data-docplace={it.id} disabled={!it.executable} onClick={event => executeAction('projects.docs.OpenOnCanvas.5', { api, c: it, u, handler: () => handlePlaceNode(it) }, event)}>Place on the Canvas</button>
          <button type="button" className="btn" data-docback onClick={event => executeAction('projects.docs.AllNodes', { handler: () => setDocNode(null) }, event)}>All nodes</button>
        </div>
        <p className="sub">Generated from the node&apos;s own definition. archhub.io/docs shows the same page.</p>
      </>;
    };

    const renderAside = () => {
      if (!active) return <aside className="dside" />;
      const gi = DOC_GROUPS.indexOf(active.group);
      const siblings = (grouped[active.group] || []).filter(x => x.title !== active.title);
      const nextGroup = gi >= 0 && DOC_GROUPS[gi + 1] ? grouped[DOC_GROUPS[gi + 1]] || [] : [];
      const related = [...siblings, ...nextGroup].slice(0, 4);
      const tryAction = DOC_TRY[active.title] || (active.route ? [`Open ${active.title}`, uArg => uArg?.go?.(active.route)] : null);
      const askTarget = activeNode ? activeNode.n : active.title;

      return <aside className="dside">
        {!activeNode && active.steps?.length > 1 && <section>
          <div className="eyebrow">On this page</div>
          {active.steps.map((st, idx) => <button key={idx} type="button" className="tocb" data-dstep={idx} onClick={event => executeAction('projects.docs.CueStep', { handler: () => handleCueStep(idx) }, event)}>
            {st.split(/[.:;]/)[0]}
          </button>)}
        </section>}
        {tryAction && <section className="dtry">
          <div className="eyebrow">Try it</div>
          <button type="button" className="btn btn-primary sm" id="dtry" onClick={event => executeAction('projects.docs.OpenInTheApp.6', { article: active, u, handler: () => tryAction[1](u) }, event)}>
            {tryAction[0]}
          </button>
        </section>}
        {related.length > 0 && <section>
          <div className="eyebrow">Related</div>
          {related.map(r => <button key={r.id} type="button" className="tocb" data-doc={r.title} onClick={event => executeAction('projects.docs.SelectRelated', { handler: () => { setSelectedTitle(r.title); setDocNode(null); } }, event)}>
            {r.title}
          </button>)}
        </section>}
        <section>
          <div className="eyebrow">Still stuck</div>
          <button type="button" className="tocb" data-dask onClick={event => executeAction('projects.docs.AskBaboom', { handler: handleAskBaboom }, event)}>
            Ask BABOOM about {askTarget}
          </button>
        </section>
      </aside>;
    };

    const webSlug = slugify(activeNode ? activeNode.n : active?.title || 'guide');

    return <div className="page docs" data-screen="docs">
      <style>{DOCS_CSS}</style>
      {docState === 'waiting' ? <p className="sub" role="status">Loading guide…</p> : null}
      {docState === 'error' ? <div className="toast" role="alert" style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--color-line, #2a2a33)', background: '#202028', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
        <span>{docError}</span>
        <button type="button" className="btn sm" onClick={event => executeAction('projects.docs.RetryDocs', { handler: loadDocs }, event)}>Retry</button>
      </div> : null}
      {docState === 'empty' ? <span hidden /> : null}
      {docState === 'loaded' ? <span hidden /> : null}
      {localToast && <div className="toast" role="status" aria-live="polite" style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--color-line, #2a2a33)', background: '#202028', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
        <span>{localToast.message}</span>
        {localToast.action && <button type="button" className="btn sm" onClick={event => executeAction('projects.docs.ToastAction', { handler: localToast.action[1] }, event)}>{localToast.action[0]}</button>}
      </div>}
      <div className="spread">
        <h1>Documentation</h1>
        <label className="sfind dfind">
          <Icon name="search" size={15} />
          <input
            className="field"
            id="dq"
            placeholder="Find in the guide: “approve a step”"
            aria-label="Find in the guide"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && query.trim()) docsFind(query.trim());
            }}
          />
        </label>
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <button type="button" className="btn sm" id="cmapb" onClick={event => executeAction('projects.docs.OpenConnectMap', { handler: () => setConnectPick('App') }, event)}>
            <Icon name="link" size={13} /> How everything connects
          </button>
          <a className="btn sm" href={`https://archhub.io/docs/${encodeURIComponent(webSlug)}`} target="_blank" rel="noopener noreferrer">
            Open on the web
          </a>
        </span>
      </div>

      <div className="docgrid d3">
        <nav className="toc" aria-label="Guide topics">
          {DOC_GROUPS.map(group => <React.Fragment key={group}>
            <div className="eyebrow">{group}</div>
            {(grouped[group] || []).map(item => {
              const isOn = active?.title === item.title;
              return <button
                key={item.id}
                type="button"
                className={'tocb' + (isOn ? ' on' : '')}
                data-doc={item.title}
                aria-current={isOn ? 'page' : undefined}
                hidden={!topicMatchesQuery(item)}
                onClick={event => executeAction('projects.docs.SetSelectedDId.1', { d: item, setSelected: () => { setSelectedTitle(item.title); setDocNode(null); } }, event)}
              >
                {item.title}
              </button>;
            })}
          </React.Fragment>)}
        </nav>

        <article className="card" ref={articleRef}>
          {activeNode ? renderNodePage(activeNode) : active ? <>
            <h2>{active.title}</h2>
            <p className="dlead">{active.summary}</p>
            {active.steps?.length > 0 && <ul className="dsteps">
              {active.steps.map((st, idx) => <li key={idx} className={cuedStep === idx ? 'cue' : undefined}>{st}</li>)}
            </ul>}
            {active.title === 'Glossary' && renderGlossary()}
            {active.title === 'Node reference' && renderNodeRef()}
            {active.group === 'TUTORIALS' && <button type="button" className="btn btn-primary" id="starttut" onClick={event => executeAction('projects.docs.StartTutorial', { handler: () => createTutorialCopy(api, s, u) }, event)}>
              Start the tutorial with BABOOM
            </button>}
            {DOC_CAP[active.title] && <figure className="dfig">
              {renderArticleFigure(active.title, s)}
              <figcaption>{DOC_CAP[active.title]}</figcaption>
            </figure>}
          </> : <>
            <h2>Files, nodes, programs…</h2>
            <p>Pick a topic on the left, or type in the box above to find one.</p>
          </>}
        </article>

        {renderAside()}
      </div>

      {connectPick && <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) setConnectPick(null); }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'grid', placeItems: 'center', padding: 20 }}>
        <section className="dialog" role="dialog" aria-modal="true" aria-label="How everything connects" style={{ width: 'min(860px, 95vw)', background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #2a2a33)', borderRadius: 12, padding: 22 }}>
          <div className="spread" style={{ marginBottom: 10 }}>
            <h2 style={{ margin: 0 }}>How everything connects</h2>
            <button type="button" className="btn sm" onClick={event => executeAction('projects.docs.CloseConnectMap', { handler: () => setConnectPick(null) }, event)}>Close</button>
          </div>
          <p className="concept sub">{CONCEPT}</p>
          <div className="cmap">
            <div className="cmapc">
              <svg className="cmapl" viewBox="0 0 680 320" aria-hidden="true">
                {CONNECT_EDGES.map(([a, b, label]) => {
                  const [x1, y1] = [CONNECT_POS[a][0] + 70, CONNECT_POS[a][1] + 20];
                  const [x2, y2] = [CONNECT_POS[b][0] + 70, CONNECT_POS[b][1] + 20];
                  return <g key={a + '-' + b}>
                    <line x1={x1} y1={y1} x2={x2} y2={y2} />
                    <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 5}>{label}</text>
                  </g>;
                })}
              </svg>
              {Object.keys(CONNECT_POS).map(k => <button
                key={k}
                type="button"
                className={'cbox' + (k === connectPick ? ' on' : '')}
                data-cbox={k}
                style={{ left: CONNECT_POS[k][0], top: CONNECT_POS[k][1] }}
                onClick={event => executeAction('projects.docs.PickConnectBox', { handler: () => setConnectPick(k) }, event)}
              >
                {LINKS[k].t}
              </button>)}
            </div>
            <aside className="cmapd">
              <h3 style={{ marginTop: 0 }}>{LINKS[connectPick].t}</h3>
              <p className="sub">{LINKS[connectPick].d}</p>
              <div className="eyebrow">In the app</div>
              <p className="sub">{LINKS[connectPick].w}</p>
              {LINKS[connectPick].u && <a className="btn sm" href={LINKS[connectPick].u} target="_blank" rel="noopener noreferrer">
                <Icon name="link" size={13} /> Open {LINKS[connectPick].u.replace('https://', '')}
              </a>}
            </aside>
          </div>
        </section>
      </div>}
    </div>;
  }

  window.UI.Docs = Docs;
  window.UI.TutorialOverlay = TutorialOverlay;

  // WIRE-projects: each rendered callback is registered with its executable owner.
  function projectsdocsjsxSetSelectedDId1({ d, setSelected }) {
    return typeof setSelected === 'function' ? setSelected(d?.id) : undefined;
  }
  function projectsdocsjsxNodeReference2({ setSelected }) {
    return typeof setSelected === 'function' ? setSelected('nodes') : undefined;
  }
  function projectsdocsjsxGlossary3({ setSelected }) {
    return typeof setSelected === 'function' ? setSelected('glossary') : undefined;
  }
  async function projectsdocsjsxOpenOnCanvas5({ api: apiArg, c, u, handler }) {
    if (typeof handler === 'function') return handler();
    const node = await u.act(() => apiArg.addNode(c.id));
    if (node) {
      u.setSelectedNodeId?.(node.id);
      u.go?.('canvas');
    }
    return node;
  }
  function projectsdocsjsxOpenInTheApp6({ article, u, handler }) {
    if (typeof handler === 'function') return handler();
    return u?.go?.(article?.route);
  }
  function projectsdocsjsxClearSearch9({ setQuery }) {
    return typeof setQuery === 'function' ? setQuery('') : undefined;
  }
  function projectsdocsjsxSelectNode({ handler }) {
    return handler?.();
  }
  function projectsdocsjsxAllNodes({ handler }) {
    return handler?.();
  }
  function projectsdocsjsxSkipTutorial({ handler }) { return handler?.(); }
  function projectsdocsjsxCueStep({ handler }) { return handler?.(); }
  function projectsdocsjsxSelectRelated({ handler }) { return handler?.(); }
  function projectsdocsjsxAskBaboom({ handler }) { return handler?.(); }
  function projectsdocsjsxToastAction({ handler }) { return handler?.(); }
  function projectsdocsjsxOpenConnectMap({ handler }) { return handler?.(); }
  function projectsdocsjsxStartTutorial({ handler }) { return handler?.(); }
  function projectsdocsjsxCloseConnectMap({ handler }) { return handler?.(); }
  function projectsdocsjsxPickConnectBox({ handler }) { return handler?.(); }
  function projectsdocsjsxRetryDocs({ handler }) { return handler?.(); }
  const PROJECT_ACTIONS = {
    'projects.docs.SetSelectedDId.1': 'projectsdocsjsxSetSelectedDId1',
    'projects.docs.NodeReference.2': 'projectsdocsjsxNodeReference2',
    'projects.docs.Glossary.3': 'projectsdocsjsxGlossary3',
    'projects.docs.OpenOnCanvas.5': 'projectsdocsjsxOpenOnCanvas5',
    'projects.docs.OpenInTheApp.6': 'projectsdocsjsxOpenInTheApp6',
    'projects.docs.ClearSearch.9': 'projectsdocsjsxClearSearch9',
    'projects.docs.SelectNode': 'projectsdocsjsxSelectNode',
    'projects.docs.AllNodes': 'projectsdocsjsxAllNodes',
    'projects.docs.SkipTutorial': 'projectsdocsjsxSkipTutorial',
    'projects.docs.CueStep': 'projectsdocsjsxCueStep',
    'projects.docs.SelectRelated': 'projectsdocsjsxSelectRelated',
    'projects.docs.AskBaboom': 'projectsdocsjsxAskBaboom',
    'projects.docs.ToastAction': 'projectsdocsjsxToastAction',
    'projects.docs.OpenConnectMap': 'projectsdocsjsxOpenConnectMap',
    'projects.docs.StartTutorial': 'projectsdocsjsxStartTutorial',
    'projects.docs.CloseConnectMap': 'projectsdocsjsxCloseConnectMap',
    'projects.docs.PickConnectBox': 'projectsdocsjsxPickConnectBox',
    'projects.docs.RetryDocs': 'projectsdocsjsxRetryDocs'
  };
  if (typeof window.registerActions === 'function') {
    window.registerActions(PROJECT_ACTIONS, {
      projectsdocsjsxSetSelectedDId1,
      projectsdocsjsxNodeReference2,
      projectsdocsjsxGlossary3,
      projectsdocsjsxOpenOnCanvas5,
      projectsdocsjsxOpenInTheApp6,
      projectsdocsjsxClearSearch9,
      projectsdocsjsxSelectNode,
      projectsdocsjsxAllNodes,
      projectsdocsjsxSkipTutorial,
      projectsdocsjsxCueStep,
      projectsdocsjsxSelectRelated,
      projectsdocsjsxAskBaboom,
      projectsdocsjsxToastAction,
      projectsdocsjsxOpenConnectMap,
      projectsdocsjsxStartTutorial,
      projectsdocsjsxCloseConnectMap,
      projectsdocsjsxPickConnectBox,
      projectsdocsjsxRetryDocs
    });
  }
})();
