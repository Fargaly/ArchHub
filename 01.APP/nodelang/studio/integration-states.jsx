// Expanded states belong to their existing Settings nodes and adapter records.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {
      A,
      D,
      api,
      useData,
      useApp,
      Btn,
      Card,
      Chip,
    } = window.UI,
    Icon = window.AHIcon;

  const PKG_RULES = [
    'It lists what it adds and what it needs before you install it.',
    'No secrets inside. A package with a key or password is refused.',
    'Anything that changes something outside the file runs only on Run and waits for your Approve.',
    'It gets no more authority than you or the agent that adds it, and cannot switch off a guard.',
    'It wraps other tools; it never ships someone else\'s code inside it.',
    'You can switch it off or remove it in one click; a broken one never stops ArchHub opening.'
  ];

  const SCAN_RULES = [
    [/curl|wget|powershell|invoke-/i, 'it downloads or runs code at install'],
    [/token|secret|password|api[_-]?key/i, 'it asks for a key in its manifest'],
    [/\.exe|\.dll|\.msi/i, 'it ships an unsigned binary']
  ];

  function scanImportManifest(value) {
    const text = String(value || '');
    return SCAN_RULES.filter(([re]) => re.test(text)).map(([, reason]) => reason);
  }

  function notifyToast(u, message) {
    if (u?.setToast) u.setToast(message);
    else if (typeof window.CustomEvent === 'function') window.dispatchEvent(new window.CustomEvent('archhub:notice', { detail: { message: typeof message === 'string' ? message : message.text } }));
  }

  function OverlayShell({ title, onClose, children }) {
    const boxRef = React.useRef(null);
    React.useLayoutEffect(() => {
      const el = boxRef.current;
      if (!el) return;
      const first = el.querySelector('input:not([type=file]),textarea') || el.querySelector('button,select');
      first?.focus?.({ preventScroll: true });
      const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); onClose?.(); } };
      el.addEventListener('keydown', onKey);
      return () => el.removeEventListener('keydown', onKey);
    }, [title]);
    return <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose?.(); }} style={{ position: 'fixed', inset: 0, zIndex: 900, background: 'rgba(0,0,0,.55)', display: 'grid', placeItems: 'center', padding: 16 }}>
      <section ref={boxRef} className="dialog" role="dialog" aria-modal="true" aria-label={title} style={{ width: 'min(480px, 94vw)', background: A.bgPanel, color: A.ink, border: '1px solid ' + A.line, borderRadius: A.rad?.lg ?? 8, padding: 18, display: 'grid', gap: 12 }}>
        <header className="spread" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>{title}</h2>
          {onClose && <Btn sm ghost aria-label="Close dialog" onClick={event => executeAction('ui.select', () => onClose(), event)}>×</Btn>}
        </header>
        {children}
      </section>
    </div>;
  }

  function ImportModDialog({ kind = 'Install a mod', embedded = false, modal = false, onClose, onImported }) {
    const u = useApp();
    const [value, setValue] = React.useState('');
    const trimmed = value.trim();
    const bad = scanImportManifest(trimmed);
    const mcp = /MCP/i.test(kind);
    const close = onClose || u?.close;

    const submit = async () => {
      if (!trimmed) {
        notifyToast(u, 'Name what to import first.');
        return false;
      }
      if (bad.length) {
        notifyToast(u, `Not imported: ${bad[0]}.`);
        return false;
      }
      if (typeof onImported === 'function') await onImported(trimmed);
      else if (typeof api?.importMod === 'function' && u?.act) await u.act(() => api.importMod(trimmed));
      notifyToast(u, `${trimmed} imported. Its node is in the Library.`);
      close?.();
      return true;
    };

    const content = <div className="grid" style={{ display: 'grid', gap: 10 }}>
      <label className="dfield grid" htmlFor="impv" style={{ display: 'grid', gap: 4, fontSize: 12, color: A.inkSoft }}>
        <span>{mcp ? 'Server name or command' : 'File'}</span>
        <input className="field" id="impv" aria-label={mcp ? 'Server name or command' : 'File'} placeholder={mcp ? 'notion' : 'Choose a file…'} value={value} onChange={e => setValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); void submit(); } }} style={{ width: '100%', boxSizing: 'border-box', background: A.bgSoft, color: A.ink, border: '1px solid ' + A.line, borderRadius: A.rad?.sm ?? 5, padding: '7px 9px' }} />
      </label>
      <div className="pcheck" id="impscan" role="status" aria-live="polite" style={{ display: 'grid', gap: 4, padding: 10, border: '1px solid ' + A.line, borderRadius: A.rad?.md ?? 6, fontSize: 12.5 }}>
        <b>Checked before it lands</b>
        {!trimmed ? <div className="sd" style={{ color: A.inkSoft }}>Type a name to scan it.</div>
          : bad.length ? bad.map(reason => <div key={reason} className="f-err" style={{ color: A.err }}>✕ Refused: {reason}</div>)
            : <>
              <div className="f-ok" style={{ color: A.ok }}>✓ No download or code run at install</div>
              <div className="f-ok" style={{ color: A.ok }}>✓ No key requested in the manifest</div>
              <div className="f-ok" style={{ color: A.ok }}>✓ No unsigned binary</div>
            </>}
      </div>
      <p className="dsub" style={{ margin: 0, fontSize: 12, color: A.inkSoft }}>Its tools appear in the Library under their source. Writes always go through Approve.</p>
      <div className="flex" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        {!embedded && close && <Btn sm onClick={event => executeAction('ui.select', () => close(), event)}>Cancel</Btn>}
        <Btn p sm onClick={event => executeAction('ui.select', () => submit(), event)}>Import</Btn>
      </div>
    </div>;

    if (embedded || modal) return content;
    return <OverlayShell title={kind} onClose={close}>{content}</OverlayShell>;
  }

  function summarizePackage(pkg) {
    if (!pkg) return {
      adds: ['Nodes, skills or rules declared in the selected package manifest'],
      needs: ['Programs, folders or network access declared in the manifest (writes wait for your Approve)']
    };
    const nodes = Array.isArray(pkg.nodes) ? pkg.nodes.map(n => typeof n === 'string' ? n : (n?.title || n?.name || n?.id)).filter(Boolean) : [];
    const skills = Array.isArray(pkg.skills || pkg.tutorials) ? (pkg.skills || pkg.tutorials).map(s => typeof s === 'string' ? s : (s?.title || s?.name || s?.id)).filter(Boolean) : [];
    const rules = Array.isArray(pkg.rules || pkg.hooks || pkg.settings) ? (pkg.rules || pkg.hooks || pkg.settings).map(r => typeof r === 'string' ? r : (r?.title || r?.name || r?.id)).filter(Boolean) : [];
    const adds = [
      ...(nodes.length ? [`${nodes.length} ${nodes.length === 1 ? 'node' : 'nodes'}: ${nodes.join(', ')}`] : []),
      ...(skills.length ? [`${skills.length} ${skills.length === 1 ? 'skill' : 'skills'}: ${skills.join(', ')}`] : []),
      ...(rules.length ? [`${rules.length} ${rules.length === 1 ? 'rule' : 'rules'}: ${rules.join(', ')}`] : []),
    ];
    const perms = Array.isArray(pkg.permissions) ? pkg.permissions.filter(Boolean) : [];
    const needs = perms.length ? perms.map(p => String(p)) : ['Writes wait for your Approve', 'No network unless declared'];
    return {
      adds: adds.length ? adds : ['1 node from ' + (pkg.name || 'package')],
      needs
    };
  }

  function AddNodePluginDialog({ modal = false, onClose }) {
    const s = useData(), u = useApp();
    const close = onClose || u?.close;
    const [step, setStep] = React.useState('pick');
    const [manifestText, setManifestText] = React.useState('');
    const [pickedPkg, setPickedPkg] = React.useState(null);
    const reviewed = pickedPkg || (s?.mods || []).find(m => m.status === 'Ready for review') || null;
    const scanTarget = manifestText.trim() || (reviewed ? JSON.stringify(reviewed) : '');
    const refusedReasons = scanImportManifest(scanTarget);
    const { adds, needs } = summarizePackage(reviewed || (manifestText.trim() ? { name: manifestText.trim() } : null));

    const chooseSource = async key => {
      if (key === 'comm') {
        close?.();
        u?.go?.('community');
        return;
      }
      if (key === 'agent') {
        const prompt = 'Build a node that ';
        if (u?.setComposerDraft) {
          const draftKey = JSON.stringify([u.route || 'canvas', u.task || '']);
          u.setComposerDraft(current => ({ ...current, [draftKey]: { text: prompt, revision: (current?.[draftKey]?.revision || 0) + 1 } }));
        }
        if (typeof window.CustomEvent === 'function') {
          window.dispatchEvent(new window.CustomEvent('archhub:ask-baboom', { detail: { text: prompt } }));
        }
        close?.();
        const ta = document.querySelector('.composer-input, .dx-composer textarea');
        if (ta) { ta.focus(); }
        return;
      }
      setStep('file');
      if (typeof api?.inspectMod === 'function' && u?.act) {
        const inspected = await u.act(api.inspectMod);
        if (inspected && typeof inspected === 'object') setPickedPkg(inspected);
      }
    };

    const readLocalManifest = async e => {
      const file = e.target.files?.[0];
      if (!file) return;
      const raw = typeof file.text === 'function' ? await file.text() : file.name;
      setManifestText(file.name + '\n' + raw);
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') setPickedPkg({ name: parsed.name || file.name, version: parsed.version || '', ...parsed });
      } catch {
        setPickedPkg({ name: file.name.replace(/\.[^.]+$/, '') });
      }
    };

    const installFromFile = async () => {
      if (refusedReasons.length) {
        notifyToast(u, `Not imported: ${refusedReasons[0]}.`);
        return;
      }
      if (!reviewed && !manifestText.trim()) {
        notifyToast(u, 'Name what to import first.');
        return;
      }
      if (reviewed?.id && reviewed?.digest && typeof api?.installMod === 'function' && u?.act) {
        const done = await u.act(() => api.installMod(reviewed.id));
        if (!done) return;
      }
      notifyToast(u, 'Installed. Its nodes are in the Library.');
      close?.();
    };

    const rulesBlock = <details className="pkgrules" style={{ fontSize: 12.5, color: A.inkSoft }}>
      <summary style={{ cursor: 'pointer', color: A.ink }}>The six rules</summary>
      <ol style={{ margin: '6px 0 0', paddingLeft: 18, display: 'grid', gap: 3 }}>
        {PKG_RULES.map(rule => <li key={rule}>{rule}</li>)}
      </ol>
    </details>;

    const title = step === 'pick' ? 'Add a node or plugin' : refusedReasons.length ? 'This package was refused' : 'Will install' + (reviewed?.name ? ': ' + reviewed.name + (reviewed.version ? ' ' + reviewed.version : '') : '');

    const body = step === 'pick' ? <div className="grid" style={{ display: 'grid', gap: 10 }}>
      <p className="dsub" style={{ margin: 0, fontSize: 12.5, color: A.inkSoft }}>People and agents add to ArchHub the same way, under six rules.</p>
      <div className="pkgsrc" style={{ display: 'grid', gap: 6 }}>
        {[['From Community', 'users', 'comm'], ['From a file', 'folder', 'file'], ['Ask an agent to build one', 'workshop', 'agent']].map(([label, ic, key]) =>
          <button key={key} type="button" className="listbutton aopt" data-pkgsrc={key} onClick={event => executeAction('ui.select', () => chooseSource(key), event)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 6, border: '1px solid ' + A.line, background: A.bgSoft, color: A.ink, textAlign: 'left' }}>
            <span className="tile fam-agent" style={{ width: 20, height: 20, borderRadius: 5, display: 'grid', placeItems: 'center', background: A.cyan, color: A.onFill, flex: 'none' }}><Icon name={ic} size={12} /></span>
            <b>{label}</b>
          </button>)}
      </div>
      {rulesBlock}
      <div className="flex" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        {close && <Btn sm onClick={event => executeAction('ui.select', () => close(), event)}>Cancel</Btn>}
      </div>
    </div> : <div className="grid" style={{ display: 'grid', gap: 10 }}>
      <label className="dfield grid" htmlFor="pkgfile-input" style={{ display: 'grid', gap: 4, fontSize: 12, color: A.inkSoft }}>
        <span>Package file or manifest</span>
        <input id="pkgfile-input" className="field" aria-label="Package file or manifest" placeholder="Choose or paste a package name or manifest…" value={manifestText} onChange={e => setManifestText(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', background: A.bgSoft, color: A.ink, border: '1px solid ' + A.line, borderRadius: A.rad?.sm ?? 5, padding: '7px 9px' }} />
      </label>
      <input type="file" aria-label="Choose package file" accept=".json,.archhub" onChange={readLocalManifest} style={{ fontSize: 12, color: A.inkSoft }} />
      {refusedReasons.length > 0 ? <div className="fail-card insp-card" role="alert" style={{ padding: 12, border: '1px solid ' + A.err, borderRadius: 6 }}>
        <span className="eyebrow f-err" style={{ color: A.err, fontWeight: 600, fontSize: 11, textTransform: 'uppercase' }}>Refused</span>
        <p style={{ margin: '6px 0 0', fontSize: 12.5 }}>Refused: {refusedReasons.join('; ')}. Packages may not carry keys or unsigned binaries; connect the service in Settings › Connections instead.</p>
      </div> : <>
        <p className="dsub" style={{ margin: 0, fontSize: 12, color: A.inkSoft }}>From a file. Nothing runs until you use it.</p>
        <div>
          <div className="eyebrow" style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: A.inkMuted }}>It adds</div>
          <ul className="dsteps" style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12.5 }}>{adds.map(line => <li key={line}>{line}</li>)}</ul>
        </div>
        <div>
          <div className="eyebrow" style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: A.inkMuted }}>It needs</div>
          <ul className="dsteps" style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12.5 }}>{needs.map(line => <li key={line}>{line}</li>)}</ul>
        </div>
      </>}
      {rulesBlock}
      <div className="flex" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Btn sm onClick={event => executeAction('ui.select', () => setStep('pick'), event)}>Back</Btn>
        {close && <Btn sm onClick={event => executeAction('ui.select', () => close(), event)}>Cancel</Btn>}
        {!refusedReasons.length && <Btn p sm onClick={event => executeAction('ui.select', () => installFromFile(), event)}>Install</Btn>}
      </div>
    </div>;

    if (modal) return body;
    return <OverlayShell title={title} onClose={close}>{body}</OverlayShell>;
  }

  const FIXED_FURNITURE = new Set(['thing.session', 'thing.you', 'thing.workshop']);
  const FIXED_IDS = new Set(['fixed-agent', 'fixed-you', 'fixed-workshop', 'start']);
  const normalizePortType = raw => {
    const t = String(raw || 'any').toLowerCase();
    return ({ string: 'text', str: 'text', int: 'number', integer: 'number', float: 'number', bool: 'boolean', path: 'file', folder: 'file', colour: 'color', list: 'elements' })[t] || t;
  };
  const portIsList = port => Boolean(port && (port.list || port.cardinality === 'many' || String(port.type || '').toLowerCase() === 'list'));

  function computeConnectionChecks(graph) {
    const allNodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
    const allWires = Array.isArray(graph?.wires) ? graph.wires : [];
    const stepNodes = allNodes.filter(n => n && !n.fixed && !FIXED_FURNITURE.has(n.type) && !FIXED_IDS.has(n.id) && n.type !== 'note' && !(n.children?.length > 0) && !(n.frameMembers?.length > 0) && n.kind !== 'Group');
    const stepIds = new Set(stepNodes.map(n => n.id));
    const byId = new Map(allNodes.map(n => [n.id, n]));
    const endNode = (w, side) => typeof w[side] === 'object' && w[side] ? w[side].node : (side === 'from' ? (w.from ?? w.a) : (w.to ?? w.b));
    const endPort = (w, side) => typeof w[side] === 'object' && w[side] ? w[side].socket : (side === 'from' ? (w.fromPort ?? w.ap) : (w.toPort ?? w.bp));
    const wireEnabled = w => w && w.enabled !== false && w.props?.enabled !== false;

    const mine = allWires.filter(w => stepIds.has(endNode(w, 'from')) || stepIds.has(endNode(w, 'to')));
    const activeWires = mine.filter(wireEnabled);

    const findPort = (node, portId, side) => {
      if (!node || !portId) return null;
      const list = side === 'out' ? (node.outputs || node.outs || []) : (node.inputs || node.ins || []);
      return list.find(p => (p.id ?? p.n) === portId || p.name === portId || p.id === 'param:' + portId) || null;
    };

    const bad = mine.filter(w => {
      const a = byId.get(endNode(w, 'from')), b = byId.get(endNode(w, 'to'));
      const p = findPort(a, endPort(w, 'from'), 'out'), q = findPort(b, endPort(w, 'to'), 'in');
      if (w.rejected) return true;
      if (!p || !q) return false;
      const pt = normalizePortType(p.type ?? p.t), qt = normalizePortType(q.type ?? q.t);
      const typeMismatch = pt !== 'any' && pt !== 'unknown' && qt !== 'any' && qt !== 'unknown' && pt !== qt;
      const listMismatch = p.cardinality !== 'unknown' && q.cardinality !== 'unknown' && pt !== 'any' && qt !== 'any' && portIsList(p) !== portIsList(q);
      return typeMismatch || listMismatch;
    });

    const isTrigger = n => Boolean(n.trigger || /^trigger\./i.test(n.type || '') || /^trigger$/i.test(n.category || n.kind || ''));
    const isEffect = n => Boolean(n.effect || n.pure === false || /^(effect|output|send)$/i.test(n.fam || n.category || n.kind || ''));

    const orphan = stepNodes.filter(n => !isTrigger(n) && !activeWires.some(w => endNode(w, 'to') === n.id));
    const dead = stepNodes.filter(n => !isEffect(n) && !activeWires.some(w => endNode(w, 'from') === n.id));

    const findings = [
      ...bad.map(w => {
        const a = byId.get(endNode(w, 'from')), b = byId.get(endNode(w, 'to'));
        const ap = findPort(a, endPort(w, 'from'), 'out'), bp = findPort(b, endPort(w, 'to'), 'in');
        return {
          node: b || a,
          level: 'f-err',
          text: `Type mismatch: ${(a?.title || endNode(w, 'from'))}.${ap?.name || ap?.n || endPort(w, 'from')} into ${(b?.title || endNode(w, 'to'))}.${bp?.name || bp?.n || endPort(w, 'to')}`
        };
      }),
      ...orphan.map(n => ({ node: n, level: 'f-warn', text: `${n.title} gets no input, so it never runs` })),
      ...dead.map(n => ({ node: n, level: 'f-warn', text: `${n.title} feeds nothing; its result is not used` }))
    ];

    return { stepNodes, mine, findings };
  }

  function ConnectionChecksDialog({ modal = false, onClose, onSelectNode, onFitNode, graph: suppliedGraph }) {
    const s = useData(), u = useApp();
    const close = onClose || u?.close;
    const graph = suppliedGraph || s?.graph || { nodes: [], wires: [] };
    const { stepNodes, mine, findings } = computeConnectionChecks(graph);

    const pickFinding = item => {
      const target = item?.node;
      if (target?.id) {
        u?.setSelectedNodeId?.(target.id);
        window.UI.centreWhenShown = { nodeId: target.id, ...(u?.task ? { task: u.task } : { path: api?.getSessionPath?.() || '' }) };
        onSelectNode?.(target.id);
        if (onFitNode) onFitNode(target.id);
        else window.UI.requestCanvasFit?.(false);
      }
      close?.();
    };

    const content = <div className="grid" style={{ display: 'grid', gap: 10 }}>
      <p className="dsub" style={{ margin: 0, fontSize: 12.5, color: A.inkSoft }}>
        {mine.length} wires and {stepNodes.length} nodes checked. {findings.length ? `${findings.length} to look at. Click one to select it.` : 'Every socket type matches, every node gets an input and every result is used.'}
      </p>
      {findings.length > 0 && <div className="diag" style={{ display: 'grid', gap: 6 }}>
        {findings.map((item, idx) => <button key={idx} type="button" className="listbutton drow lint" data-lint={idx} onClick={event => executeAction('ui.select', () => pickFinding(item), event)} style={{ display: 'grid', gridTemplateColumns: '18px minmax(0, 1fr)', gap: 8, alignItems: 'center', padding: '8px 10px', borderRadius: 6, background: A.bgSoft, border: '1px solid ' + A.lineSoft, color: A.ink, textAlign: 'left', fontSize: 12.5 }}>
          <span className={item.level} style={{ color: item.level === 'f-err' ? A.err : A.warn, fontWeight: 700 }}>{item.level === 'f-err' ? '✕' : '!'}</span>
          <span>{item.text}</span>
        </button>)}
      </div>}
      <div className="flex" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        {close && <Btn sm onClick={event => executeAction('ui.select', () => close(), event)}>Close</Btn>}
      </div>
    </div>;

    if (modal) return content;
    return <OverlayShell title="Connection checks" onClose={close}>{content}</OverlayShell>;
  }

  function McpTools() {
    const s = useData(),
      u = useApp(),
      [id, setId] = React.useState(s.mcpServers[0]?.id),
      [kind, setKind] = React.useState('Tools'),
      server = s.mcpServers.find(r => r.id === id);
    const action = window.UI.useAction();
    React.useEffect(() => { action.run(async () => { const rows = await api.refreshMcpServers(); setId(rows[0]?.id); return rows.length ? rows : null; }); }, []);
    const status = <div aria-live="polite">{action.state === 'waiting' && <p role="status">Reading tool servers…</p>}{action.state === 'empty' && <p>No tool servers. Connect a server in Connections.</p>}{action.state === 'loaded' && <p>{s.mcpServers.length} servers returned</p>}{action.state === 'error' && <div role="alert">{action.error}<Btn onClick={event => executeAction("projects.integration-states.RetryOwner", {action}, event)}>Retry</Btn></div>}</div>;
    if(!server)return status;
    return <div className="grid">{status}<p className="muted">Discover tools from your connected programs, then add only the tools you need.</p><label className="grid">Tool server<select aria-label="Tool server" value={id} onChange={e => setId(e.target.value)}>{s.mcpServers.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label><select aria-label="MCP content" value={kind} onChange={e => setKind(e.target.value)}>{['Tools', 'Resources', 'Prompts'].map(v => <option key={v}>{v}</option>)}</select><div className="spread"><Chip c={server.status.includes('failed') ? A.warn : A.ok}>{server.status}</Chip><Btn p onClick={event => executeAction("projects.integration-states.DiscoverTools.1", {api,id,kind,u}, event)}>Discover tools</Btn></div>{server.status === 'Connection failed' && <div className="row spread"><span>The server could not be reached.</span><Btn onClick={event => executeAction("projects.integration-states.Reconnect.2", {api,id,u}, event)}>Reconnect</Btn></div>}{server.tools.map(t => <div className="row spread" key={t.id}><span>{t.name}</span><Btn sm title={'Import ' + t.name} aria-label={'Import ' + t.name} onClick={event => executeAction("projects.integration-states.AsyncAwaitUActApi.3", {api,id,t,u}, event)}><Icon name="plus" size={16} /></Btn></div>)}</div>;
  }
  function ModManager({
    making = false
  }) {
    const s = useData(),
      u = useApp(),
      [name, setName] = React.useState(''),
      [description, setDescription] = React.useState(''),
      [pkgDialogOpen, setPkgDialogOpen] = React.useState(false);
    const action = window.UI.useAction();
    React.useEffect(() => { action.run(api.refreshMods); }, []);
    const status = <div aria-live="polite">{action.state === 'waiting' && <p role="status">Reading mod packages…</p>}{action.state === 'empty' && <p>No installed packages.</p>}{action.state === 'loaded' && <p>{s.mods.length} packages returned</p>}{action.state === 'error' && <div role="alert">{action.error}<Btn onClick={event => executeAction("projects.integration-states.RetryOwner", {action}, event)}>Retry</Btn></div>}</div>;
    return <div className="grid">{status}<ImportModDialog embedded onClose={u?.close} /><div className="spread"><p className="muted">A local package adds nodes and settings. Review its manifest before enabling it.</p><div className="flex"><Btn onClick={event => executeAction('ui.select', () => setPkgDialogOpen(true), event)}>Add a node or plugin</Btn><Btn p onClick={event => executeAction("projects.integration-states.ChooseFolder.4", {api,u}, event)}>Choose folder</Btn></div></div>{pkgDialogOpen && <AddNodePluginDialog onClose={() => setPkgDialogOpen(false)} />}{making && <Card style={{
        padding: 16
      }}><label className="grid">Name<input aria-label="Mod name" value={name} onChange={e => setName(e.target.value)} /></label><label className="grid">What should it do?<textarea aria-label="Mod description" value={description} onChange={e => setDescription(e.target.value)} /></label><Btn disabled={!name.trim()} onClick={event => executeAction("projects.integration-states.PrepareMod.5", {api,description,name,u}, event)}>Prepare mod</Btn></Card>}{s.mods.map(m => <Card key={m.id} style={{
        padding: 18
      }}><div className="spread"><h3>{m.name}</h3><Chip c={m.status === 'Load error' ? A.warn : A.ok}>{m.status || 'Installed'}</Chip></div><p className="muted" style={{
          margin: '10px 0'
        }}>{m.error || m.description || 'Nodes and settings for your workspace'}</p><small className="muted">{m.files?.length || 0} files · {Array.isArray(m.nodes) ? m.nodes.length : Object.keys(m.nodes || {}).length} nodes · {Array.isArray(m.settings) ? m.settings.length : Object.keys(m.settings || {}).length} settings</small>{m.status === 'Ready for review' && <div className="grid" style={{
          padding: '14px 0'
        }}>{[['Nodes', m.nodes], ['Settings', m.settings], ['Requested access', m.permissions]].map(([label, items]) => <div key={label}><b>{label}</b><p className="muted">{Array.isArray(items) ? items.map(v => typeof v === 'string' ? v : JSON.stringify(v)).join(' · ') || 'None declared' : JSON.stringify(items)}</p></div>)}</div>}<div className="flex" style={{
          marginTop: 12
        }}>{m.status === 'Load error' ? <Btn p onClick={event => executeAction("projects.integration-states.Retry.6", {api,m,u}, event)}>Retry</Btn> : m.status === 'Ready for review' ? <Btn p onClick={event => executeAction("projects.integration-states.InstallReviewedMod.7", {api,m,u}, event)}>Install reviewed mod</Btn> : <D.Toggle label={'Enable ' + m.name} checked={m.enabled} onCheckedChange={v => u.act(() => api.setModEnabled(m.id, v))} />}<Btn sm title={m.shared ? 'Stop sharing' : 'Share mod'} aria-label={m.shared ? 'Stop sharing' : 'Share mod'} onClick={event => executeAction("projects.integration-states.UActApiShareModM.8", {api,m,u}, event)}><Icon name="link" size={16} />{m.shared && 'Shared'}</Btn><Btn sm title="Remove mod" aria-label="Remove mod" onClick={event => executeAction("projects.integration-states.RemoveMod.9", {api,m,u}, event)}><Icon name="trash" size={16} /></Btn></div></Card>)}</div>;
  }
  function BrainSuggestions() {
    const s = useData(),
      u = useApp();
    const rows = s.suggestions.filter(r => r.status === 'Suggested').slice(0, Math.max(0, s.settings.find(r => r.id === 'BABOOM.Suggestions per day')?.value));
    return rows.length ? <Card style={{
      padding: 20,
      marginBottom: 22
    }}><div className="spread"><h2>At a natural break</h2><Chip>Suggestions</Chip></div>{rows.map(r => <div className="row spread" key={r.id}><div><p>{r.text}</p><small className="muted">{r.source}</small></div><div className="flex"><Btn p sm onClick={event => executeAction("projects.integration-states.ReviewMemory.10", {api,r,u}, event)}>Review memory</Btn><Btn sm title="Dismiss suggestion" aria-label="Dismiss suggestion" onClick={event => executeAction("projects.integration-states.DismissSuggestion.11", {api,r,u}, event)}><Icon name="close" size={16} /></Btn></div></div>)}</Card> : null;
  }
  Object.assign(window.UI, {
    PKG_RULES,
    scanImportManifest,
    ImportModDialog,
    AddNodePluginDialog,
    ConnectionChecksDialog,
    McpTools,
    ModManager,
    BrainSuggestions
  });

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsintegrationstatesjsxDiscoverTools1({api,id,kind,u}, event) {
  const handler = () => u.act(() => api.discoverMcpTools(id, kind));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxReconnect2({api,id,u}, event) {
  const handler = () => u.act(() => api.reconnectMcp(id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxAsyncAwaitUActApi3({api,id,t,u}, event) {
  const handler = async () => {
          const document = api.getSessionDocument();
          const target = document?.properties?.taskContext?.task || api.getSessionPath();
          const result = await u.act(() => api.importMcpTool(id, t.id));
          if (result && !result.cancelled && document?.id === api.getSessionDocument()?.id) u.go('canvas', target);
        };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxChooseFolder4({api,u}, event) {
  const handler = () => u.act(api.inspectMod);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxPrepareMod5({api,description,name,u}, event) {
  const handler = async () => { const result = await u.act(() => api.prepareMod(name, description)); if (result) u.go('workshop'); };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxRetry6({api,m,u}, event) {
  const handler = () => u.act(() => api.retryMod(m.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxInstallReviewedMod7({api,m,u}, event) {
  const handler = () => u.act(() => api.installMod(m.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxUActApiShareModM8({api,m,u}, event) {
  const handler = async () => { const result = await u.act(() => api.shareMod(m.id)); if (result) u.go('workshop'); };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxRemoveMod9({api,m,u}, event) {
  const handler = () => u.confirm('Remove ' + m.name + '?', () => api.removeMod(m.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxReviewMemory10({api,r,u}, event) {
  const handler = async () => {
            const c = await u.act(() => api.proposeMemory(r.id));
            if (c) u.go('workshop');
          };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxDismissSuggestion11({api,r,u}, event) {
  const handler = () => u.act(() => api.dismissSuggestion(r.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsintegrationstatesjsxRetryOwner({action}) { return action.retry(); }
const PROJECT_ACTIONS = {
  "projects.integration-states.RetryOwner": "projectsintegrationstatesjsxRetryOwner",
  "projects.integration-states.DiscoverTools.1": "projectsintegrationstatesjsxDiscoverTools1",
  "projects.integration-states.Reconnect.2": "projectsintegrationstatesjsxReconnect2",
  "projects.integration-states.AsyncAwaitUActApi.3": "projectsintegrationstatesjsxAsyncAwaitUActApi3",
  "projects.integration-states.ChooseFolder.4": "projectsintegrationstatesjsxChooseFolder4",
  "projects.integration-states.PrepareMod.5": "projectsintegrationstatesjsxPrepareMod5",
  "projects.integration-states.Retry.6": "projectsintegrationstatesjsxRetry6",
  "projects.integration-states.InstallReviewedMod.7": "projectsintegrationstatesjsxInstallReviewedMod7",
  "projects.integration-states.UActApiShareModM.8": "projectsintegrationstatesjsxUActApiShareModM8",
  "projects.integration-states.RemoveMod.9": "projectsintegrationstatesjsxRemoveMod9",
  "projects.integration-states.ReviewMemory.10": "projectsintegrationstatesjsxReviewMemory10",
  "projects.integration-states.DismissSuggestion.11": "projectsintegrationstatesjsxDismissSuggestion11"
};
window.registerActions(PROJECT_ACTIONS, {projectsintegrationstatesjsxRetryOwner,projectsintegrationstatesjsxDiscoverTools1,projectsintegrationstatesjsxReconnect2,projectsintegrationstatesjsxAsyncAwaitUActApi3,projectsintegrationstatesjsxChooseFolder4,projectsintegrationstatesjsxPrepareMod5,projectsintegrationstatesjsxRetry6,projectsintegrationstatesjsxInstallReviewedMod7,projectsintegrationstatesjsxUActApiShareModM8,projectsintegrationstatesjsxRemoveMod9,projectsintegrationstatesjsxReviewMemory10,projectsintegrationstatesjsxDismissSuggestion11});
})();
