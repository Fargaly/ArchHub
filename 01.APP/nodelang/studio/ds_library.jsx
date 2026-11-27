// DSYS-064 Library shelf: canonical category tree, family tiles, plain sources, socket preview and package controls.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {
    A,
    api,
    useData,
    useApp,
    Empty
  } = window.UI;

  const PROGS_G = ['Revit', 'AutoCAD', 'Excel', 'Outlook', '3ds Max', 'Rhino', 'Blender'];

  const SETTINGS_AREAS = [
    { key: 'Account', label: 'Account', page: 'Account', pages: ['Account', 'Brain'], icon: 'user', description: 'Your ArchHub account: the same values in the app and on archhub.io', outs: [{ n: 'account', t: 'text' }] },
    { key: 'Projects', label: 'Projects', page: 'Projects', pages: ['Projects'], icon: 'folder', description: 'Units, the standard, templates, naming and folders', outs: [{ n: 'standard', t: 'text' }, { n: 'project folder', t: 'file' }] },
    { key: 'Agents', label: 'Agents', page: 'Agents', pages: ['Agents', 'BABOOM', 'Hooks', 'Workshop', 'Automations', 'Library & Mods'], icon: 'users', description: 'Who works for you, on which model, what they may do, the Workshop, automations and tools', outs: [{ n: 'policy', t: 'text' }] },
    { key: 'Connections', label: 'Connections', page: 'Connections', pages: ['Connections'], icon: 'link', description: 'Accounts, programs, your phone and notifications', outs: [{ n: 'accounts', t: 'text' }, { n: 'programs', t: 'text' }] },
    { key: 'You', label: 'This PC', page: 'Appearance', pages: ['Appearance', 'Privacy', 'Advanced', 'System graph', 'Dependencies', 'Updates & About'], icon: 'settings', description: 'This PC: how ArchHub looks, workspaces, files, privacy, updates and the app', outs: [{ n: 'profile', t: 'text' }, { n: 'look', t: 'text' }] }
  ];

  const TYPE_NAMES = {
    event: 'Event',
    elements: 'Elements',
    text: 'Text',
    file: 'File',
    number: 'Number',
    color: 'Colour',
    boolean: 'Boolean',
    any: 'Any'
  };

  const FAM_COLORS = () => ({
    model: A.blue || '#7898d6',
    list: A.purple || '#a98cd6',
    check: A.warn || '#e5b25a',
    agent: A.cyan || '#5fb3b3',
    effect: A.accent || '#d97757',
    look: A.accent || '#d97757'
  });

  function socketColor(t) {
    return ({
      elements: A.accent || '#d97757',
      number: A.warn || '#e5b25a',
      text: A.inkSoft || '#9b938a',
      file: A.ok || '#7ec18e',
      color: A.accent || '#d97757',
      boolean: A.purple || '#a98cd6',
      event: A.cyan || '#5fb3b3',
      any: A.inkSoft || '#9b938a'
    })[t] || A.inkSoft || '#9b938a';
  }

  function normalizeSocketType(raw) {
    const t = String(raw || 'any').toLowerCase();
    return ({ string: 'text', str: 'text', int: 'number', integer: 'number', float: 'number', object: 'elements', dict: 'elements', list: 'elements', path: 'file', folder: 'file', colour: 'color', bool: 'boolean', unknown: 'any' })[t] || (TYPE_NAMES[t] ? t : 'text');
  }

  function programOf(c, portItem) {
    if (portItem?.program && PROGS_G.includes(portItem.program)) return portItem.program;
    if (c.prog && PROGS_G.includes(c.prog)) return c.prog;
    if (c.program && PROGS_G.includes(c.program)) return c.program;
    if (c.g && PROGS_G.includes(c.g)) return c.g;
    if (c.g === 'Mods') return 'Revit';
    const engine = String(c.descriptor?.engine || portItem?.engine || '').toLowerCase();
    const hostParam = engine === 'thing.host' ? String(portItem?.params?.host || c.params?.host || '').toLowerCase() : '';
    const text = `${c.name || ''} ${c.description || ''}`;
    if (engine.startsWith('revit.') || hostParam === 'revit' || /\brevit\b/i.test(text)) return 'Revit';
    if (engine.startsWith('acad.') || engine.startsWith('autocad.') || engine === 'cad.host_lines' || hostParam === 'acad' || /\b(autocad|dwg)\b/i.test(text)) return 'AutoCAD';
    if (hostParam === 'excel' || /\b(excel|workbook|xlsx)\b/i.test(text) || String(portItem?.params?.operation || '').startsWith('excel.')) return 'Excel';
    if (engine.startsWith('outlook.') || engine === 'library.draft_email' || hostParam === 'outlook' || /\boutlook\b/i.test(text)) return 'Outlook';
    if (engine.startsWith('max.') || hostParam === 'max' || /\b3ds\s*max\b/i.test(text)) return '3ds Max';
    if (engine.startsWith('rhino.') || hostParam === 'rhino' || /\brhino\b/i.test(text)) return 'Rhino';
    if (engine.startsWith('blender.') || hostParam === 'blender' || /\bblender\b/i.test(text)) return 'Blender';
    return '';
  }

  function serviceOf(c, portItem) {
    const engine = String(c.descriptor?.engine || portItem?.engine || '').toLowerCase();
    const host = String(portItem?.params?.host || portItem?.params?.connector || c.service || '').toLowerCase();
    if (engine.startsWith('notion.') || host === 'notion' || /\bnotion\b/i.test(c.name || '')) return 'Notion';
    if (engine.startsWith('dropbox.') || host === 'dropbox' || /\bdropbox\b/i.test(c.name || '')) return 'Dropbox';
    if (/\byoutube\b/i.test(`${c.name || ''} ${c.src || ''}`)) return 'YouTube';
    if (/\bspeckle\b/i.test(`${c.name || ''} ${engine}`)) return 'Speckle';
    if (engine === 'connector.call' || String(c.family || '').toLowerCase() === 'connectors') return 'connected account';
    return '';
  }

  function isEffectCard(c, portItem) {
    if (typeof c.effect === 'boolean') return c.effect;
    if (c.approvalRequired || portItem?.approvalRequired) return true;
    if (/needs Approve|\bafter approval\b|\bafter Approve\b/i.test(`${c.src || ''} ${c.description || ''}`)) return true;
    if (portItem && typeof portItem.pure === 'boolean') return !portItem.pure;
    return /^(output|send|effect)$/i.test(c.family || '');
  }

  function familyAndIcon(c, portItem) {
    const effect = isEffectCard(c, portItem);
    const engine = String(c.descriptor?.engine || portItem?.engine || '').toLowerCase();
    const cat = String(c.family || portItem?.cat || '').toLowerCase();
    const fam = c.fam || (effect ? 'effect'
      : /^(governance|enforce|check|checks)$/i.test(cat) ? 'check'
      : /^(ai|agents|models|trigger|skill)$/i.test(cat) ? 'agent'
      : /^(shape|input|workspaces|list)$/i.test(cat) ? 'list'
      : /^(settings|look)$/i.test(cat) ? 'look'
      : 'model');
    const icon = c.icon || (
      engine === 'script.python' || cat === 'math' ? 'code'
      : cat === 'file' || cat === 'files' || cat === 'workspaces' ? 'folder'
      : cat === 'trigger' ? 'clock'
      : cat === 'governance' || cat === 'enforce' ? 'check'
      : cat === 'ai' || cat === 'models' ? 'brain'
      : cat === 'agents' || cat === 'note' ? 'users'
      : cat === 'skill' ? 'group'
      : cat === 'shape' ? 'library'
      : cat === 'transform' || cat === 'logic' ? 'arrange'
      : cat === 'text' ? 'edit'
      : cat === 'document' || cat === 'daily work' ? 'docs'
      : cat === 'watch' ? 'eye'
      : cat === 'output' || cat === 'workshop' ? 'send'
      : cat === 'settings' ? 'settings'
      : cat === 'connectors' ? 'link'
      : 'canvas'
    );
    return { fam, icon, effect };
  }

  function plainSrc(c, portItem, prog, mods) {
    const effect = isEffectCard(c, portItem);
    const ap = effect ? ' · waits for your Approve' : '';
    if (c.src) {
      const s0 = String(c.src).replace(/ ?\(needs Approve\)/i, '');
      if (/^Host broker/i.test(s0)) return `Runs in ${prog || c.prog || c.program || 'the program'}${ap}`;
      if (/^Built-in · /i.test(s0)) return s0.replace(/^Built-in · /i, '') + ap;
      if (/^(Built-in|Recipe|Batch|Watcher)$/i.test(s0)) return 'Built into ArchHub' + ap;
      if (/^Connections · /i.test(s0)) return s0.replace(/^Connections · /i, 'Through your ') + ap;
      if (/^Connections$/i.test(s0)) return `Through your ${serviceOf(c, portItem) || 'connected account'}${ap}`;
      return s0 + (s0.includes('waits for your Approve') ? '' : ap);
    }
    if (c.modId) {
      const mod = (mods || []).find(m => m.id === c.modId);
      return `${mod?.name || c.modName || 'Mod'}${ap}`;
    }
    const service = !prog ? serviceOf(c, portItem) : '';
    if (service) return `Through your ${service}${ap}`;
    const engine = String(c.descriptor?.engine || portItem?.engine || '').toLowerCase();
    if (prog || engine.startsWith('host.') || engine.startsWith('hosts.') || c.id === 'h_read') {
      return `Runs in ${prog || 'the program'}${ap}`;
    }
    return 'Built into ArchHub' + ap;
  }

  function hostConnected(prog, s) {
    if (!prog || s?.hostsProbing || !Array.isArray(s?.hosts) || !s.hosts.length) return true;
    const key = prog.toLowerCase();
    const alias = { revit: 'revit', autocad: 'acad', excel: 'excel', outlook: 'outlook', '3ds max': 'max', rhino: 'rhino', blender: 'blender' }[key] || key;
    const match = s.hosts.find(h => {
      const id = String(h.id || '').toLowerCase(), name = String(h.name || h.label || '').toLowerCase();
      return id === key || id === alias || name === key;
    });
    if (!match) return true;
    return ['connected', 'listening', 'running', 'ready'].includes(String(match.state || '').toLowerCase());
  }

  function whyOff(c, prog, s) {
    if (c.disabled) {
      return c.modName ? `From the ${c.modName} mod, which is off. Turn it on in Settings › Agents › Tools in the Library.`
        : c.g === 'Mods' ? 'From the Revit tools mod, which is off. Turn it on in Settings › Agents › Tools in the Library.'
        : 'Not switched on for your account yet.';
    }
    if (prog && !hostConnected(prog, s)) {
      return `${prog} is not connected on this PC. Connect it in Settings › Connections › Programs.`;
    }
    if (c.unavailable) {
      return c.reason || 'Not available in this build.';
    }
    return '';
  }

  function cardPreviewModel(c, portItem, srcLine, offReason) {
    const params = Array.isArray(c.params)
      ? c.params.map(p => ({ id: p.n, n: p.n || p.id, t: p.t === 'sel' || p.t === 'enum' ? 'choice' : (p.t || 'text') }))
      : (portItem?.paramDefs || []).filter(p => !(portItem?.engine === 'skill' && ['skill', 'session_file'].includes(p.id)))
          .map(p => ({ id: p.id, n: p.name || p.id, t: p.type === 'enum' || p.type === 'sel' ? 'choice' : (p.type || 'text') }));
    const paramIds = new Set(params.map(p => p.id));
    const ins = Array.isArray(c.ins)
      ? c.ins.map(p => ({ n: p.n || p.name || p.id, t: normalizeSocketType(p.t || p.type), list: Boolean(p.list || p.cardinality === 'many') }))
      : (portItem?.ports?.target || []).filter(p => !paramIds.has(p.id))
          .map(p => ({ n: p.name || p.id, t: normalizeSocketType(p.type), list: Boolean(p.list || p.cardinality === 'many' || p.type === 'list') }));
    const outs = Array.isArray(c.outs)
      ? c.outs.map(p => ({ n: p.n || p.name || p.id, t: normalizeSocketType(p.t || p.type), list: Boolean(p.list || p.cardinality === 'many') }))
      : (portItem?.ports?.source || [])
          .map(p => ({ n: p.name || p.id, t: normalizeSocketType(p.type), list: Boolean(p.list || p.cardinality === 'many' || p.type === 'list') }));
    return {
      title: c.name,
      src: c.src || srcLine,
      ins,
      outs,
      params,
      disabled: Boolean(c.disabled),
      off: offReason
    };
  }

  function notifyToast(u, message) {
    if (u?.setToast) u.setToast(message);
    else if (typeof window.CustomEvent === 'function') window.dispatchEvent(new window.CustomEvent('archhub:notice', { detail: { message: typeof message === 'string' ? message : message.text } }));
  }

  function SessionList({list, query='', onOpen, rows: suppliedRows, renderRow, sectionOf, collapsedSections=[], toggleSection}) {
    const s = useData(), u = useApp();
    const [kind, setKind] = React.useState(s.sessionListFilters?.[list] || 'all');
    const [request, setRequest] = React.useState('waiting'), [failure, setFailure] = React.useState(''), [attempt, setAttempt] = React.useState(0);
    React.useEffect(() => {
      let live = true;
      setRequest('waiting');
      api.readSessionListFilters().then(result => {if(live){setKind(result.sessionListFilters[list] || 'all');setRequest('loaded');}}).catch(error=>{if(live){setFailure(error.message);setRequest('error');}});
      return () => {live = false;};
    }, [list, attempt]);
    const choose = value => u.act(async () => {await api.setSessionListFilter(list,value);setKind(value);});
    const rows = (suppliedRows||s.graphs||[]).filter(row=>(kind==='all'||row.kind===kind)&&(row.title||row.name).toLowerCase().includes(query.toLowerCase()));
    const status = request==='loaded'&&!rows.length?'empty':request;
    const render=row=>renderRow?renderRow(row):<button type="button" className="listbutton" key={row.path} onClick={()=>executeAction('ui.select',async()=>{const opened=await u.act(()=>api.openSession(row.path));if(opened&&!opened.cancelled)onOpen?.();})}>{row.title||row.name}</button>;
    const sections=['Needs you','Working now','Today','Earlier this week','Older / archived'];
    const content=sectionOf?sections.map(name=>{const items=rows.filter(row=>sectionOf(row)===name);return items.length?<section className="home-session-section" key={name} data-home-section={name}><button type="button" className="home-section-heading" aria-expanded={!collapsedSections.includes(name)} onClick={()=>executeAction('ui.select',()=>toggleSection(name))}><span>{collapsedSections.includes(name)?'›':'⌄'} {name==='Older / archived'?'Older':name}</span><b>{items.length}</b></button>{!collapsedSections.includes(name)&&items.map(render)}</section>:null;}):rows.map(render);
    return <>{status==='waiting'&&<p role="status">Loading sessions…</p>}{status==='error'&&<p role="alert">{failure}<button type="button" onClick={()=>executeAction('ui.select',()=>setAttempt(attempt+1))}>Retry</button></p>}{(status==='loaded'||status==='empty')&&<><div className="shelf-tabs" role="group" aria-label="Saved document filter">{[['all','All'],['workflow','Workflows'],['agent-session','Agent sessions']].map(([value,label])=><button type="button" className="tab-button" key={value} aria-pressed={kind===value} onClick={()=>executeAction('ui.select',()=>choose(value))}>{label}</button>)}</div>{status==='loaded'&&<div className="session-section-list">{content}</div>}{status==='empty'&&<p>No sessions found.</p>}</>}</>;
  }
  window.UI.SessionList = SessionList;

  function LibraryShelf({
    onClose,
    onAdd
  }) {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState(''),
      [options, setOptions] = React.useState(false),
      [preview, setPreview] = React.useState(null),
      [localDialog, setLocalDialog] = React.useState(null),
      // "From Community" in Add a node opens this section; it may mount after that choice.
      [commOpen, setCommOpen] = React.useState(() => { const asked = Boolean(window.UI.openLibraryCommunity); window.UI.openLibraryCommunity = false; return asked; }),
      [commItem, setCommItem] = React.useState(null);
    // Library › Community: the shared catalogue lives here, not on a page of its own.
    const commRead = window.UI.useAction();
    const readCommunity = () => commRead.run(() => api.refreshCommunity());
    React.useEffect(() => { readCommunity(); }, []);
    React.useEffect(() => {
      const openComm = () => { window.UI.openLibraryCommunity = false; setCommOpen(true); };
      window.addEventListener('archhub:library-community', openComm);
      return () => window.removeEventListener('archhub:library-community', openComm);
    }, []);
    const shelfRef = React.useRef(null),
      optionsButton = React.useRef(null),
      optionsMenu = React.useRef(null);
    React.useLayoutEffect(() => { if (options) optionsMenu.current?.querySelector('button')?.focus({ preventScroll: true }); }, [options]);

    const pathKey = p => api?.sessionPathKey ? api.sessionPathKey(p || '') : String(p || '').replace(/\\/g, '/').toLowerCase();
    const activeTaskRow = (s.tasks || []).find(t => u?.task && t.id === u.task);
    const openSessionKey = pathKey(api?.getSessionPath?.() || s.sessionFile || activeTaskRow?.sessionPath || '');

    const isArchivedSession = (sessionFile, id) => {
      const sk = pathKey(sessionFile);
      const g = (s.graphs || []).find(row => (sk && pathKey(row.path) === sk) || row.id === id);
      if (g && (g.state === 'archived' || g.archived === true)) return true;
      const t = (s.tasks || []).find(row => (sk && pathKey(row.sessionPath) === sk) || row.id === id);
      return Boolean(t && (t.status === 'ARCHIVED' || t.archived === true));
    };

    const isOpenSession = (sessionFile, id) => {
      if (u?.task && id === u.task) return true;
      const sk = pathKey(sessionFile);
      return Boolean(sk && openSessionKey && sk === openSessionKey);
    };

    const agentSessions = new Set((s.templates || []).filter(t => t.kind === 'agent-session').map(t => t.id));
    const portById = new Map((s.libraryPorts || []).map(item => [item.id, item]));
    const savedWorkflows = new Map((s.libraryPorts || []).filter(item => item.engine === 'skill' && item.params?.session_file)
      .map(item => [item.id, item.params]));

    // Include disabled mods' nodes so disabled mod cards stay visible with .off and explain why.
    const disabledModCards = (s.mods || []).filter(m => m.enabled === false && m.status !== 'Ready for review').flatMap(mod =>
      (Array.isArray(mod.nodes) ? mod.nodes : []).map(node => ({
        id: 'mod:' + mod.id + ':' + node.id,
        name: node.title || node.name || node.id,
        family: node.category || 'host',
        description: node.summary || mod.description || '',
        modId: mod.id,
        modName: mod.name,
        itemId: node.id,
        disabled: true
      }))
    );

    const baseCatalogue = [
      ...(s.catalogue || []).filter(c => !agentSessions.has(c.id)),
      ...disabledModCards.filter(dc => !(s.catalogue || []).some(c => c.id === dc.id))
    ].filter(c => {
      if (!savedWorkflows.has(c.id)) return true;
      const sf = savedWorkflows.get(c.id)?.session_file;
      return !isOpenSession(sf, c.id) && !isArchivedSession(sf, c.id);
    });

    // Extra saved workflow sessions from s.graphs / s.tasks not already in savedWorkflows.
    const knownPaths = new Set([...savedWorkflows.values()].map(v => pathKey(v.session_file)).filter(Boolean));
    const extraWorkflowRows = [
      ...(s.graphs || []).filter(g => g.kind === 'workflow' && g.path && !knownPaths.has(pathKey(g.path)) && !isOpenSession(g.path, g.id) && !isArchivedSession(g.path, g.id))
        .map(g => ({ id: 'sess:' + g.path, name: g.title || g.name, sessionFile: g.path, steps: Array.isArray(g.nodes) ? g.nodes.length : (g.steps ?? 0), direct: false })),
      ...(s.tasks || []).filter(t => !t.archived && t.status !== 'ARCHIVED' && t.declaration !== true && !String(t.id || '').startsWith('declared-') && (t.sessionPath || t.workflow || t.steps) && !isOpenSession(t.sessionPath, t.id) && !knownPaths.has(pathKey(t.sessionPath || '')))
        .filter(t => !(s.graphs || []).some(g => g.kind === 'workflow' && pathKey(g.path) === pathKey(t.sessionPath || '')))
        .map(t => ({ id: 'sess:' + t.id, taskId: t.id, name: t.title || t.name, sessionFile: t.sessionPath || '', steps: Array.isArray(t.workflow) ? t.workflow.filter(n => !n.fixed).length : (Array.isArray(t.steps) ? t.steps.length : (t.steps ?? 0)), direct: Boolean(t.direct) }))
    ];

    const rawTree = s.libraryTree?.length ? s.libraryTree : [];
    const hasSettingsGroup = rawTree.some(row => row.id === 'settings');
    const tree = rawTree.length
      ? (hasSettingsGroup ? rawTree : [...rawTree, { id: 'settings', label: 'Settings', icon: 'settings', categories: ['settings'] }])
      : [
          ...([...new Set(baseCatalogue.map(c => c.family))].map(f => ({ id: f, label: f, icon: 'library', categories: [f] }))),
          ...(extraWorkflowRows.length ? [{ id: 'skill', label: 'Workflows and skills', icon: 'group', categories: ['skill'] }] : []),
          ...(typeof api?.exposeSettingsPage === 'function' ? [{ id: 'settings', label: 'Settings', icon: 'settings', categories: ['settings'] }] : [])
        ];
    const listed = tree.flatMap(row => row.categories);
    const allGroups = [
      ...tree,
      ...[...new Set(baseCatalogue.map(c => c.family))].filter(f => !listed.includes(f)).map(f => ({ id: f, label: f, icon: 'library', categories: [f] }))
    ];

    const collapsed = s.libraryCollapsed || rawTree.map(row => row.id);
    const toggleSection = name => u.act(() => api.setLibraryCollapsed(collapsed.includes(name) ? collapsed.filter(value => value !== name) : [...collapsed, name]));

    const q = query.trim().toLowerCase();
    const foundCard = (c, group) => {
      if (!q) return true;
      const prog = programOf(c, portById.get(c.id));
      return `${c.name} ${c.description || ''} ${c.descriptor?.engine || ''} ${prog} ${group.label}`.toLowerCase().includes(q);
    };
    const matchingSettingsAreas = typeof api?.exposeSettingsPage === 'function'
      ? SETTINGS_AREAS.filter(area => !q || `${area.key} ${area.label} ${area.description} ${area.pages.join(' ')} settings`.toLowerCase().includes(q))
      : [];
    const matchingExtraWorkflows = extraWorkflowRows.filter(w => !q || `${w.name} workflows and skills`.toLowerCase().includes(q));

    const placeNode = async c => {
      const portItem = portById.get(c.id);
      const prog = programOf(c, portItem);
      const off = whyOff(c, prog, s);
      if (off) {
        notifyToast(u, `${c.name}: ${off}`);
        return null;
      }
      if (u?.route === 'home') {
        const created = onAdd
          ? await onAdd(c)
          : await u.act(async () => {
              const made = await api.createTask(c.name);
              const tid = made?.taskId || made?.id;
              if (tid && typeof api.openTaskGraph === 'function') await api.openTaskGraph(tid);
              await api.addNode(c.id);
              await api.listTasks?.();
              if (tid) u.setTask?.(tid);
              return made;
            });
        if (created && created.ok !== false) {
          const tid = created.taskId || created.id;
          notifyToast(u, {
            text: `New session "${c.name}" with ${c.name} as its first step. Double-click it to work inside.`,
            label: 'Open',
            open: () => u?.openTaskFile ? u.openTaskFile(tid) : u?.go?.('task-file', tid)
          });
        }
        return created;
      }
      if (onAdd) return onAdd(c);
      const node = await u.act(() => api.addNode(c.id));
      if (node && node.ok !== false) {
        if (node.id) u?.setSelectedNodeId?.(node.id);
        notifyToast(u, `${c.name} added. Drag from its sockets to wire it.`);
      }
      return node;
    };

    const placeWorkflowSession = async wf => {
      if (wf.catalogueCard) return placeNode(wf.catalogueCard);
      const node = await u.act(() => api.insertSession ? api.insertSession(wf.sessionFile) : api.addNode(wf.id));
      if (node && node.ok !== false) {
        if (node.id) u?.setSelectedNodeId?.(node.id);
        notifyToast(u, `${wf.name} added. Drag from its sockets to wire it.`);
      }
      return node;
    };

    const placeSettingsArea = async (area, backingCard) => {
      const targetPage = (s.settings || []).find(r => area.pages.includes(r.page))?.page || area.page;
      const hasPageRows = !(s.settings || []).length || (s.settings || []).some(r => r.page === targetPage);
      const node = (typeof api?.exposeSettingsPage === 'function' && (!backingCard || hasPageRows))
        ? await u.act(() => api.exposeSettingsPage(targetPage))
        : backingCard ? await u.act(() => api.addNode(backingCard.id)) : null;
      if (node && node.ok !== false) {
        if (node.id) u?.setSelectedNodeId?.(node.id);
        notifyToast(u, `Settings › ${area.label} added. Drag from its sockets to wire it.`);
      }
      return node;
    };

    const workflowStepCount = (c, portItem) => {
      const sf = savedWorkflows.get(c.id)?.session_file;
      const sk = pathKey(sf);
      const t = (s.tasks || []).find(row => sk && pathKey(row.sessionPath) === sk);
      if (Array.isArray(t?.workflow)) return t.workflow.filter(n => !n.fixed).length;
      const g = (s.graphs || []).find(row => sk && pathKey(row.path) === sk);
      if (Array.isArray(g?.nodes)) return g.nodes.length;
      const m = String(c.description || portItem?.sub || '').match(/(\d+)\s*(?:steps?|nodes?)/i);
      return m ? Number(m[1]) : 0;
    };

    const famPalette = FAM_COLORS();
    const renderTile = (fam, icon) => (
      <span className={'tile fam-' + fam} style={{ width: 20, height: 20, borderRadius: 5, display: 'grid', placeItems: 'center', background: famPalette[fam] || famPalette.model, color: A.onFill || '#180f08', flex: 'none' }}>
        <window.AHIcon name={icon} size={12} />
      </span>
    );

    const renderWorkflowRow = wf => {
      const sub = `Your workflow · ${wf.direct ? 'direct thread' : wf.steps + ' steps'} · drops in as one node`;
      const showPrev = () => setPreview({
        title: wf.name,
        src: sub,
        ins: wf.ins || [{ n: 'task', t: 'event', list: false }],
        outs: wf.outs || [{ n: 'result', t: 'elements', list: true }],
        params: wf.params || [],
        disabled: false,
        off: ''
      });
      return <button type="button" key={wf.id} data-design="library.row" data-sess={wf.sessionFile || wf.id}
        className="listbutton shelf-node libi sessi"
        draggable
        onDragStart={e => {
          if (wf.cardId) e.dataTransfer.setData('node', wf.cardId);
          if (wf.sessionFile) e.dataTransfer.setData('session', wf.sessionFile);
          if (wf.taskId) e.dataTransfer.setData('task', wf.taskId);
        }}
        onMouseEnter={showPrev}
        onFocus={showPrev}
        onClick={event => executeAction('ui.select', () => placeWorkflowSession(wf), event)}
        title={`Drag onto the canvas, or click, to add ${wf.name} as one node`}
        aria-label={'Add ' + wf.name}
        style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left' }}>
        {renderTile('agent', 'group')}
        <span className="shelf-node-copy ln" style={{ minWidth: 0, flex: 1 }}>
          <b>{wf.name}</b>
          <em style={{ fontStyle: 'normal', fontSize: 'calc(11px * var(--text-scale,1))', color: A.inkSoft, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</em>
        </span>
      </button>;
    };

    const renderCardRow = c => {
      if (savedWorkflows.has(c.id)) {
        const portItem = portById.get(c.id);
        const pm = cardPreviewModel(c, portItem, '', '');
        return renderWorkflowRow({
          id: c.id,
          cardId: c.id,
          catalogueCard: c,
          name: c.name,
          sessionFile: savedWorkflows.get(c.id)?.session_file || '',
          steps: workflowStepCount(c, portItem),
          ins: pm.ins,
          outs: pm.outs,
          params: pm.params
        });
      }
      const portItem = portById.get(c.id);
      const prog = programOf(c, portItem);
      const { fam, icon } = familyAndIcon(c, portItem);
      const off = whyOff(c, prog, s);
      const srcLine = plainSrc(c, portItem, prog, s.mods);
      const subtitle = off || srcLine;
      const showPrev = () => setPreview(cardPreviewModel(c, portItem, srcLine, off));
      return <button type="button" key={c.id} data-design="library.row" data-lib={c.id}
        className={'listbutton shelf-node libi' + (off ? ' off' : '')}
        aria-disabled={off ? 'true' : undefined}
        draggable={!off}
        onDragStart={e => { if (!off) e.dataTransfer.setData('node', c.id); }}
        onMouseEnter={showPrev}
        onFocus={showPrev}
        onClick={event => executeAction('projects.ds_library.AddC.4', { add: placeNode, c }, event)}
        title={off || c.src || srcLine}
        aria-label={'Add ' + c.name}
        style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', opacity: off ? 0.55 : 1 }}>
        {renderTile(fam, icon)}
        <span className="shelf-node-copy ln" style={{ minWidth: 0, flex: 1 }}>
          <b>{c.name}</b>
          <em style={{ fontStyle: 'normal', fontSize: 'calc(11px * var(--text-scale,1))', color: off ? A.warn : A.inkSoft, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{subtitle}</em>
        </span>
      </button>;
    };

    const renderSettingsAreaRow = (area, backingCard = null) => {
      const showPrev = () => setPreview({
        title: area.label,
        src: `Settings › ${area.label}`,
        ins: [],
        outs: area.outs,
        params: [],
        disabled: false,
        off: ''
      });
      return <button type="button" key={'sput:' + area.key} data-design="library.row" data-sput={area.key}
        className="listbutton shelf-node libi setli"
        draggable
        onDragStart={e => { if (backingCard) e.dataTransfer.setData('node', backingCard.id); }}
        onMouseEnter={showPrev}
        onFocus={showPrev}
        onClick={event => executeAction('ui.select', () => placeSettingsArea(area, backingCard), event)}
        title={`Place ${area.label} as a node: the same values as the Settings page`}
        aria-label={'Add ' + area.label}
        style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left' }}>
        {renderTile('look', area.icon)}
        <span className="shelf-node-copy ln" style={{ minWidth: 0, flex: 1 }}>
          <b>{area.label}</b>
          <em style={{ fontStyle: 'normal', fontSize: 'calc(11px * var(--text-scale,1))', color: A.inkSoft, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{area.description}</em>
        </span>
      </button>;
    };

    const settingsAreaCardId = area => 'settings_' + area.label.toLowerCase().replace(/\s+/g, '_');

    const sections = allGroups.map(group => {
      const areaBackingIds = new Set(SETTINGS_AREAS.map(settingsAreaCardId));
      const cards = baseCatalogue.filter(c => group.categories.includes(c.family) && !(group.id === 'settings' && (String(c.id || '').startsWith('thing:setting:') || areaBackingIds.has(c.id))) && foundCard(c, group));
      const extraWf = group.id === 'skill' ? matchingExtraWorkflows : [];
      const setAreas = group.id === 'settings'
        ? matchingSettingsAreas.map(area => ({ area, card: baseCatalogue.find(c => c.id === settingsAreaCardId(area)) || null }))
            .filter(({ card }) => Boolean(card) || typeof api?.exposeSettingsPage === 'function')
        : [];
      const count = cards.length + extraWf.length + setAreas.length;
      return { group, cards, extraWf, setAreas, count };
    }).filter(sec => sec.count > 0);

    const isOpen = group => Boolean(q) || !collapsed.includes(group.id);
    const commItems = (window.UI.communityWorkflows?.(s) || []).filter(c => !q || `${c.name} ${c.by} ${(c.steps || []).join(' ')}`.toLowerCase().includes(q));
    const commShown = Boolean(q) || commOpen;
    const openImportDialog = () => {
      u?.show?.('Install mod');
      setLocalDialog('import');
    };
    const openPkgAddDialog = () => {
      setLocalDialog('pkgadd');
    };

    return <aside ref={shelfRef} className="pane library-shelf" data-screen="library" aria-label="Library shelf">
      <header className="spread libh" style={{ gap: 8 }}>
        <b>Library</b>
        <span className="kb" style={{ marginLeft: 'auto', font: '500 11px ' + (A.mono || 'monospace'), color: A.inkMuted, border: '1px solid ' + A.line, borderRadius: 3, padding: '0 5px' }}>Tab</span>
        <button type="button" id="libx" className="button-reset icon-btn" aria-label="Collapse library" title="Collapse library" onClick={event => executeAction('projects.ds_library.CloseLibrary.1', { onClose }, event)} style={{ display: 'grid', placeItems: 'center', width: 26, height: 26, borderRadius: 5, color: A.inkSoft }}>
          <window.AHIcon name="back" size={14} />
        </button>
      </header>
      <div className="shelf-search libsr">
        <input id="libq" className="field" data-design="library.search" aria-label="Search nodes" placeholder="Search nodes, tools, skills" value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              const first = shelfRef.current?.querySelector('.libi:not(.off)');
              if (first) { e.preventDefault(); first.click(); }
            }
            if (e.key === 'Escape') e.currentTarget.blur();
          }} />
        <span className="shelf-options-anchor" onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setOptions(false); }}>
          <button type="button" id="libmore" ref={optionsButton} className="shelf-options icon-btn" aria-label="Library options" aria-haspopup="menu" aria-expanded={options} title="Library & Mods" onClick={event => executeAction('ui.select', () => setOptions(shown => !shown), event)}>
            <window.AHIcon name="more" size={15} />
          </button>
          {options && <section ref={optionsMenu} className="context-menu shelf-options-menu" role="menu" aria-label="Library options" onClick={() => setOptions(false)} onKeyDown={e => {
            const buttons = [...e.currentTarget.querySelectorAll('button')];
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault();
              buttons[(buttons.indexOf(document.activeElement) + (e.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length]?.focus();
            }
            if (e.key === 'Escape') { e.stopPropagation(); setOptions(false); optionsButton.current?.focus(); }
          }}>
            <div className="context-group">
              <button type="button" role="menuitem" onClick={event => executeAction('projects.ds_library.LibraryMods.15', { u }, event)}><window.AHIcon name="library" size={15} /><span>{'Library & Mods'}</span></button>
              <button type="button" role="menuitem" onClick={event => executeAction('ui.select', openImportDialog, event)}><window.AHIcon name="plus" size={15} /><span>Import a node…</span></button>
            </div>
          </section>}
        </span>
      </div>
      <div className="scroll fill libl libtree">
        {s.libraryStatus === 'waiting' && !(s.catalogue || []).length ? <p role="status" data-library-loading="">Loading the Library…</p>
          : s.libraryStatus === 'error' && !(s.catalogue || []).length ? <p role="alert">{s.libraryError} <button type="button" onClick={event => executeAction('ui.select', () => api.loadLibrary(), event)}>Retry</button></p>
          : null}
        {sections.map(({ group, cards, extraWf, setAreas, count }) => {
          const opened = isOpen(group);
          let body = null;
          if (opened) {
            if (group.id === 'host') {
              const groupedIds = new Set();
              const progBlocks = PROGS_G.map(prog => {
                const matching = cards.filter(c => programOf(c, portById.get(c.id)) === prog);
                matching.forEach(c => groupedIds.add(c.id));
                return matching.length ? <React.Fragment key={prog}>
                  <div className="libsub" style={{ padding: '6px 10px 2px 28px', fontSize: 11, fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase', color: A.inkMuted }}>{prog}</div>
                  {matching.map(renderCardRow)}
                </React.Fragment> : null;
              });
              const rest = cards.filter(c => !groupedIds.has(c.id));
              body = <>{progBlocks}{rest.map(renderCardRow)}</>;
            } else if (group.id === 'skill') {
              body = <>{cards.map(renderCardRow)}{extraWf.map(renderWorkflowRow)}</>;
            } else if (group.id === 'settings') {
              body = <>{setAreas.map(({ area, card }) => renderSettingsAreaRow(area, card))}{cards.map(renderCardRow)}</>;
            } else {
              body = cards.map(renderCardRow);
            }
          }
          return <section key={group.id} className={'shelf-group libcat' + (opened ? ' open' : '')} data-library-category={group.id} data-open={opened || undefined}>
            <button type="button" className="shelf-category libch" data-libcat={group.id} aria-expanded={opened} onClick={event => executeAction('projects.ds_library.ToggleSection.13', { f: group.id, toggleSection }, event)}>
              <window.AHIcon name="arrow" size={10} style={{ transform: opened ? 'rotate(90deg)' : undefined }} />
              <window.AHIcon name={group.icon} size={13} />
              <b>{group.label}</b>
              <em>{count}</em>
            </button>
            {body}
          </section>;
        })}
        {(!q || commItems.length > 0) && <section className={'shelf-group libcat' + (commShown ? ' open' : '')} data-library-category="community" data-open={commShown || undefined}>
          <button type="button" className="shelf-category libch" data-libcat="community" aria-expanded={commShown} onClick={event => executeAction('ui.select', () => setCommOpen(v => !v), event)}>
            <window.AHIcon name="arrow" size={10} style={{ transform: commShown ? 'rotate(90deg)' : undefined }} />
            <window.AHIcon name="users" size={13} />
            <b>Community</b>
            <em>{commItems.length}</em>
          </button>
          {commShown && <>
            {commItems.map(c => <button type="button" key={'comm:' + c.id} data-design="library.row" data-comm={c.id}
              className="listbutton shelf-node libi"
              onClick={event => executeAction('ui.select', () => setCommItem(c), event)}
              title={`${c.by} · v${c.version}`}
              aria-label={'Preview ' + c.name}
              style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left' }}>
              {renderTile(c.effect ? 'effect' : 'list', 'group')}
              <span className="shelf-node-copy ln" style={{ minWidth: 0, flex: 1 }}>
                <b>{c.name}</b>
                <em style={{ fontStyle: 'normal', fontSize: 'calc(11px * var(--text-scale,1))', color: A.inkSoft, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.by} · {c.effect ? 'Writes outside the file' : 'Read only'}</em>
              </span>
            </button>)}
            {commRead.state === 'waiting' && <p className="hint" role="status" style={{ margin: '4px 10px 6px 28px', fontSize: 12, color: A.inkMuted }}>Reading the Community…</p>}
            {commRead.state === 'error' && <p className="hint" role="alert" style={{ margin: '4px 10px 6px 28px', fontSize: 12, color: A.warn }}>{commRead.error} <button type="button" onClick={event => executeAction('ui.select', readCommunity, event)}>Retry</button></p>}
            {commRead.state === 'empty' ? <p className="hint" data-comm-empty="" style={{ margin: '4px 10px 6px 28px', fontSize: 12, color: A.inkMuted }}>Nothing shared with you yet. Workflows from your office and the people you follow appear here.</p> : null}
            {commRead.state === 'loaded' ? (!commItems.length && <p className="hint" data-comm-empty="" style={{ margin: '4px 10px 6px 28px', fontSize: 12, color: A.inkMuted }}>Nothing shared with you yet. Workflows from your office and the people you follow appear here.</p>) : null}
            <button type="button" className="listbutton shelf-node libi" id="publish" onClick={event => executeAction('ui.select', () => setLocalDialog('publish'), event)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left' }}>
              {renderTile('list', 'send')}
              <span className="shelf-node-copy ln"><b>Publish a workflow…</b></span>
            </button>
          </>}
        </section>}
        {Boolean(q) && !sections.length && !commItems.length && <Empty>Nothing matches.</Empty>}
      </div>
      <button type="button" className="libcomm button-reset" id="pkgadd" onClick={event => executeAction('ui.select', openPkgAddDialog, event)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', border: '1px dashed ' + A.line, borderRadius: 6, color: A.inkSoft, fontSize: 12, cursor: 'pointer', width: '100%' }}>
        <window.AHIcon name="plus" size={13} />
        <span>Add a node or plugin</span>
      </button>
      <div className="libprev" aria-live="polite" style={{ display: preview ? 'block' : 'none', borderTop: '1px solid ' + A.lineSoft, padding: '10px 2px 4px', fontSize: 12, minHeight: preview ? 72 : 0 }}>
        {preview && <>
          <b style={{ display: 'block' }}>{preview.title}</b>
          <em style={{ display: 'block', fontStyle: 'normal', color: A.inkMuted, fontSize: 11, marginBottom: 6 }}>{preview.src}</em>
          {preview.ins.map((p, idx) => <div className="skr" key={'in:' + p.n + ':' + idx} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
            <i className={'sk t-' + p.t + (p.list ? ' l' : '')} style={{ display: 'inline-block', width: 9, height: 9, borderRadius: p.list ? 2 : '50%', transform: p.list ? 'rotate(45deg) scale(.88)' : undefined, border: '2px solid ' + socketColor(p.t), flex: 'none' }} />
            <span>{p.n}</span>{' '}
            <em style={{ marginLeft: 'auto', fontStyle: 'normal', fontFamily: A.mono, fontSize: 11, color: A.inkMuted }}>· {TYPE_NAMES[p.t] || p.t}{p.list ? ' list' : ''} · in</em>
          </div>)}
          {preview.outs.map((p, idx) => <div className="skr" key={'out:' + p.n + ':' + idx} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
            <i className={'sk t-' + p.t + (p.list ? ' l' : '')} style={{ display: 'inline-block', width: 9, height: 9, borderRadius: p.list ? 2 : '50%', transform: p.list ? 'rotate(45deg) scale(.88)' : undefined, border: '2px solid ' + socketColor(p.t), flex: 'none' }} />
            <span>{p.n}</span>{' '}
            <em style={{ marginLeft: 'auto', fontStyle: 'normal', fontFamily: A.mono, fontSize: 11, color: A.inkMuted }}>· {TYPE_NAMES[p.t] || p.t}{p.list ? ' list' : ''} · out</em>
          </div>)}
          {preview.params.map((p, idx) => <div className="skr" key={'param:' + p.n + ':' + idx} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
            <span className="pp" style={{ width: 9, color: A.inkMuted }}>◦</span>
            <span>{p.n}</span>{' '}
            <em style={{ marginLeft: 'auto', fontStyle: 'normal', fontFamily: A.mono, fontSize: 11, color: A.inkMuted }}>{p.t}</em>
          </div>)}
          {preview.disabled ? <p className="hint" style={{ margin: '6px 0 0', fontSize: 11, color: A.warn }}>This mod is disabled. Enable it in Settings › Nodes.</p>
            : preview.off ? <p className="hint" style={{ margin: '6px 0 0', fontSize: 11, color: A.warn }}>{preview.off}</p> : null}
        </>}
      </div>
      {localDialog === 'import' && !u?.modal && window.UI.ImportModDialog && window.ReactDOM?.createPortal
        ? window.ReactDOM.createPortal(<window.UI.ImportModDialog kind="Install a mod" onClose={() => setLocalDialog(null)} />, document.body)
        : localDialog === 'import' && !u?.modal && window.UI.ImportModDialog
        ? <window.UI.ImportModDialog kind="Install a mod" onClose={() => setLocalDialog(null)} />
        : null}
      {commItem && window.UI.CommunityPreview && <window.UI.CommunityPreview item={commItem} onClose={() => setCommItem(null)} />}
      {localDialog === 'publish' && window.UI.PublishCommunityDialog && <window.UI.PublishCommunityDialog onClose={() => setLocalDialog(null)} />}
      {localDialog === 'pkgadd' && window.UI.AddNodePluginDialog && (window.ReactDOM?.createPortal
        ? window.ReactDOM.createPortal(<window.UI.AddNodePluginDialog onClose={() => setLocalDialog(null)} />, document.body)
        : <window.UI.AddNodePluginDialog onClose={() => setLocalDialog(null)} />)}
    </aside>;
  }
  window.UI.LibraryShelf = LibraryShelf;

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsdslibraryjsxToggleSection13({f,toggleSection}) {return toggleSection(f);}
async function projectsdslibraryjsxNewSession14({api,u}) {const result=await u.act(api.newSession);if(result)u.go('canvas');}

function projectsdslibraryjsxLibraryMods15({u}) {return u.go('settings/Library & Mods');}
function projectsdslibraryjsxCloseLibrary1({onClose}, event) {
  const handler = onClose;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxSetFamilyF3({f,setFamily}, event) {
  const handler = () => setFamily(f);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxAddC4({add,c}, event) {
  const handler = () => add(c);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxOnClose5({onClose}, event) {
  const handler = onClose;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxUShowSkillIdT6({api,t,u}, event) {
  const handler = () => u.act(() => api.openSession(t.path));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxExportRecipe8({u}, event) {
  const handler = () => u.download('Recipe');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxMCPTools10({u}, event) {
  const handler = () => u.show('MCP tools');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxInstallMod11({u}, event) {
  const handler = () => u.show('Install mod');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
const PROJECT_ACTIONS = {
  "projects.ds_library.CloseLibrary.1": "projectsdslibraryjsxCloseLibrary1",
  "projects.ds_library.SetFamilyF.3": "projectsdslibraryjsxSetFamilyF3",
  "projects.ds_library.AddC.4": "projectsdslibraryjsxAddC4",
  "projects.ds_library.OnClose.5": "projectsdslibraryjsxOnClose5",
  "projects.ds_library.UShowSkillIdT.6": "projectsdslibraryjsxUShowSkillIdT6",
  "projects.ds_library.ExportRecipe.8": "projectsdslibraryjsxExportRecipe8",
  "projects.ds_library.MCPTools.10": "projectsdslibraryjsxMCPTools10",
  "projects.ds_library.InstallMod.11": "projectsdslibraryjsxInstallMod11",
  "projects.ds_library.ToggleSection.13":"projectsdslibraryjsxToggleSection13",
  "projects.ds_library.NewSession.14":"projectsdslibraryjsxNewSession14",
  "projects.ds_library.LibraryMods.15":"projectsdslibraryjsxLibraryMods15"
};
window.registerActions(PROJECT_ACTIONS, {projectsdslibraryjsxToggleSection13,projectsdslibraryjsxNewSession14,projectsdslibraryjsxLibraryMods15,projectsdslibraryjsxCloseLibrary1,projectsdslibraryjsxSetFamilyF3,projectsdslibraryjsxAddC4,projectsdslibraryjsxOnClose5,projectsdslibraryjsxUShowSkillIdT6,projectsdslibraryjsxExportRecipe8,projectsdslibraryjsxMCPTools10,projectsdslibraryjsxInstallMod11});
})();
