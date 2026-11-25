// Full node surfaces reuse the supplied page, Card, parameter and table grammar.
(() => {
  function executeAction(id, context, event) {
    if (typeof window.executeAction === 'function') return window.executeAction(id, context, event);
    return context?.handler?.(event);
  }
  const {
      A,
      D,
      api,
      useData,
      useApp,
      Btn,
      Card,
      Chip,
      Heading
    } = window.UI,
    Icon = window.AHIcon || (() => null);

  function GraphManager() {
    const s = useData(),
      u = useApp(),
      [name, setName] = React.useState('');
    return <div className="grid">{[...s.graphs].sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned)).map(g => <Card key={g.id} style={{
        padding: 14
      }}><div className="spread"><button className="button-reset fill" style={{
            textAlign: 'left'
          }} onClick={event => executeAction("projects.project-tools.AsyncAwaitUActApi.1", {api,g,u}, event)}><b>{g.pinned ? '★ ' : ''}{g.name}</b><p className="muted">{g.nodes?.length ?? '—'} nodes · {g.workspaceIds?.length || 0} workspaces</p></button><Btn sm title={'Pin ' + g.name} aria-label={'Pin ' + g.name} onClick={event => executeAction("projects.project-tools.UActApiUpdateGraphG.2", {api,g,u}, event)}><Icon name="pin" size={15} /></Btn><Btn sm title={'Rename ' + g.name} aria-label={'Rename ' + g.name} onClick={event => executeAction("projects.project-tools.UShowRenameGraphId.3", {g,u}, event)}><Icon name="edit" size={15} /></Btn><Btn sm title={'Remove ' + g.name} aria-label={'Remove ' + g.name} onClick={event => executeAction("projects.project-tools.UConfirmRemoveGName.4", {api,g,u}, event)}><Icon name="trash" size={15} /></Btn></div></Card>)}<label className="grid">New workflow<input aria-label="New workflow name" value={name} onChange={e => setName(e.target.value)} /></label><Btn p disabled={!name.trim()} onClick={event => executeAction("projects.project-tools.AddGraph.5", {api,name,u}, event)}>Add workflow</Btn><div className="row spread"><h3>{s.graph.name} · history</h3><Btn sm onClick={event => executeAction("projects.project-tools.SaveVersion.6", {api,u}, event)}>Save version</Btn></div>{s.graph.versions?.map(v => <div className="row spread" key={v.id}><span>{v.name} · {v.nodes.length} nodes</span><Btn sm onClick={event => executeAction("projects.project-tools.Restore.7", {api,u,v}, event)}>Restore</Btn></div>)}<div className="flex"><Btn sm onClick={event => executeAction("projects.project-tools.ExportGraph.8", {u}, event)}>Export workflow</Btn><Btn sm onClick={event => executeAction("projects.project-tools.Sync.9", {api,u}, event)}>Sync</Btn></div></div>;
  }

  function ModelReview() {
    const s = useData(), u = useApp();
    const supported = 'Clash & Issues';
    const operations = ['Startup Check', 'Naming Check', 'Model QA', 'Parameter Dictionary', supported, 'Delivery Plan', 'IFC Export & Check', 'Library Admission'];
    const [operation, setOperation] = React.useState(supported);
    const [selection, setSelection] = React.useState(null);
    const nodes = s.graph.nodes.filter(n => n.type === 'daily.ifc_check_bcf');
    const node = nodes.length === 1 ? nodes[0] : nodes.find(n => selection?.scope === s.graph.scopeKey && n.id === selection.id);
    const source = { document: s.graph.id, path: s.sessionFile, scope: s.graph.scopeKey, node: node?.id };
    const hasInput = node && (node.params.ifc || node.params.bcf || s.graph.wires.some(w => w.enabled !== false && w.to === node.id && ['bcf', 'ifc', 'param:bcf', 'param:ifc'].includes(w.toPort)));
    const available = operation === supported;
    const issues = node?.status === 'Done' && Array.isArray(node.output?.issues) ? node.output.issues : null;
    return <main className="page" data-screen="model-review">
      <Heading title="Model review" sub={s.graph.name} />
      <label>Check<select aria-label="Model check" value={operation} onChange={e => setOperation(e.target.value)}>{operations.map(x => <option key={x}>{x}</option>)}</select></label>
      {available ? <Card>
        {nodes.length > 1 && <label>Check node<select aria-label="Check node" value={node?.id || ''} onChange={e => setSelection({ id: e.target.value, scope: s.graph.scopeKey })}>
          <option value="">Choose a node</option>{nodes.map((n, i) => <option key={n.id} value={n.id}>{n.title} ({i + 1})</option>)}</select></label>}
        <p>{node ? (hasInput ? node.error || node.display || node.status : 'Choose an IFC model or BCF issue file in the node parameters.') : nodes.length ? 'Select the check node to review.' : 'Add an IFC/BCF check node to this workflow.'}</p>
        <Btn sm disabled={s.graphOpening || (!node && nodes.length > 0)} onClick={event => executeAction("projects.project-tools.OpenAsNode.10", {api,operation,source,u}, event)}>{node ? 'Edit check node' : 'Add check node'}</Btn>
        <Btn p disabled={!hasInput || s.graphOpening || ['Running', 'Waiting for approval'].includes(node?.status)} onClick={event => executeAction("projects.project-tools.RunCheck.11", {api,operation,source,u}, event)}>Run check</Btn>
        {issues && <><h3>Issues ({issues.length})</h3>{issues.map(issue => <div key={issue.guid}><strong>{issue.title}</strong>{issue.description && <p>{issue.description}</p>}</div>)}
          <Btn sm onClick={event => executeAction("projects.project-tools.ExportIssues.12", {u,source}, event)}>Export issues</Btn></>}
      </Card> : <p role="status">{operation} is unavailable in this release.</p>}
      <window.UI.PrototypeReview />
    </main>;
  }

  const DEFAULT_STD = [
    ['FOLDERS-02', 'Folder trees: state, then data type, then discipline'],
    ['NAMING-01', 'File names: project, originator, type, role, number, date'],
    ['SHEETS-03', 'Sheet numbers and the Office title block'],
    ['DETAILS-04', 'Detail library: one detail per file'],
    ['REVIT-05', 'One Revit template for every discipline']
  ];

  const OFFICE_WORKFLOWS = [
    { id: 'c1', name: 'Sheet register to Excel', by: 'Office', scope: 'Office', uses: 31, trust: 'Office verified', steps: ['Collect sheets', 'Read sheet', 'Write register'], update: false, version: '1.2.0' },
    { id: 'c2', name: 'Door schedule audit', by: 'Yours', scope: 'Ours', uses: 12, trust: 'Yours', steps: ['Open model', 'Collect doors', 'Check fire rating', 'Write report'], update: true, version: '2.0.1' },
    { id: 'c3', name: 'IFC export and check', by: 'Public · bimtools', scope: 'Public', uses: 880, trust: 'Public · review before use', steps: ['Open model', 'Export IFC', 'Validate IFC', 'Publish to share'], update: false, version: '1.0.4' },
    { id: 'u1', name: 'Your usual: morning inbox triage', by: 'From how you work', scope: 'Ours', uses: 0, trust: 'Yours · learned from your work', steps: ['Read inbox', 'Ask an agent', 'Draft reply'], update: false, version: '0.3.0' },
    { id: 'u2', name: 'Your usual: split and describe CAD details', by: 'From how you work', scope: 'Ours', uses: 0, trust: 'Yours · learned from your work', steps: ['Read file', 'Convert DWG to data', 'Split one detail per file'], update: false, version: '1.2.0' },
    { id: 'c4', name: 'Revision cloud cleanup', by: 'Office', scope: 'Office', uses: 19, trust: 'Office verified', steps: ['Collect sheets', 'Find closed clouds', 'Remove clouds'], update: false, version: '2.0.1' },
    { id: 'o0', name: 'Model-health check to QA workbook', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F180', steps: ['Open model', 'Model health', 'Write QA workbook'], update: false, version: '1.0.4' },
    { id: 'o1', name: 'Title-block and text check on issue PDFs', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F181', steps: ['Folder to file list', 'Read scans (OCR)', 'Checklist runner'], update: false, version: '0.3.0' },
    { id: 'o2', name: 'Submittal and redline QC', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F182', steps: ['Read file', 'Checklist runner', 'Draft reply'], update: false, version: '1.2.0' },
    { id: 'o3', name: 'IDS and clash check to BCF', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F183 F213 F215', steps: ['LOIN to IDS', 'Validate IFC', 'BCF read and write'], update: false, version: '2.0.1' },
    { id: 'o4', name: 'MIDP and TIDP from the sheet list', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F185', steps: ['Collect sheets', 'Read sheet', 'Write register'], update: false, version: '1.0.4' },
    { id: 'o5', name: 'QA sampling with second review', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F186', steps: ['Collect sheets', 'Pick sample', 'Verify (a different agent)'], update: false, version: '0.3.0' },
    { id: 'o6', name: 'Template release check', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F187', steps: ['Open model', 'Checklist runner', 'Publish to office share'], update: false, version: '1.2.0' },
    { id: 'o7', name: 'Workspace cleanup and email triage', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F188', steps: ['Folder to file list', 'Name check and fix', 'Read inbox'], update: false, version: '2.0.1' },
    { id: 'o8', name: 'Dubai Municipality submission precheck', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F216 F179', steps: ['Name check and fix', 'House rule check', 'Write report'], update: false, version: '1.0.4' },
    { id: 'o9', name: 'Read the BEP into the project profile', by: 'Office', scope: 'Office', uses: 0, trust: 'Office verified · F168', steps: ['Read file', 'Research and distill', 'Project profile'], update: false, version: '0.3.0' }
  ];

  const COMM_CSS = `
    [data-screen="community"] h1 { font-size: 22px; font-weight: 650; margin: 0 0 6px; letter-spacing: -0.01em; }
    [data-screen="community"] .lead { color: var(--color-ink-soft, #9b958d); font-size: 14px; line-height: 1.5; margin: 0 0 18px; max-width: 780px; }
    [data-screen="community"] .toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
    [data-screen="community"] .field { height: 34px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--color-line, #2a2a33); background: var(--color-bg-panel, #15151a); color: var(--color-ink, #ece8e1); font: inherit; font-size: 13px; }
    [data-screen="community"] .field.sm { height: 32px; padding: 0 10px; }
    [data-screen="community"] .seg { display: inline-flex; border: 1px solid var(--color-line, #2a2a33); border-radius: 8px; overflow: hidden; background: var(--color-bg-panel, #15151a); }
    [data-screen="community"] .seg button { border: 0; background: transparent; color: var(--color-ink-soft, #9b958d); padding: 0 12px; height: 32px; font: 500 13px var(--font-sans, Inter, sans-serif); cursor: pointer; }
    [data-screen="community"] .seg button[aria-pressed="true"] { background: rgba(217,119,87,0.18); color: var(--color-ink, #ece8e1); font-weight: 600; }
    [data-screen="community"] .cgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
    [data-screen="community"] .card.citem { background: var(--color-bg-panel, #15151a); border: 1px solid var(--color-line, #2a2a33); border-radius: 12px; padding: 16px 18px; display: flex; flex-direction: column; gap: 10px; }
    [data-screen="community"] .cih { display: flex; align-items: flex-start; gap: 10px; }
    [data-screen="community"] .tile { width: 28px; height: 28px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; flex: none; background: rgba(255,255,255,0.06); color: var(--color-ink, #ece8e1); }
    [data-screen="community"] .tile.fam-effect { background: rgba(229,178,90,0.16); color: var(--color-warn, #e5b25a); }
    [data-screen="community"] .tile.fam-list { background: rgba(217,119,87,0.15); color: var(--color-accent, #d97757); }
    [data-screen="community"] .cit { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
    [data-screen="community"] .cit b { font-size: 14px; font-weight: 600; line-height: 1.3; }
    [data-screen="community"] .ciby { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--color-ink-soft, #9b958d); flex-wrap: wrap; }
    [data-screen="community"] .ciby .av { width: 16px; height: 16px; border-radius: 50%; background: #2c2c36; color: var(--color-ink, #ece8e1); display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; }
    [data-screen="community"] .verif { display: inline-flex; align-items: center; gap: 3px; color: var(--color-ok, #58b368); font-weight: 500; }
    [data-screen="community"] .chip { font-size: 11px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--color-line, #2a2a33); color: var(--color-ink-soft, #9b958d); white-space: nowrap; }
    [data-screen="community"] .chip.upd { border-color: var(--color-accent, #d97757); color: var(--color-accent, #d97757); }
    [data-screen="community"] .cimeta { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 12px; color: var(--color-ink-soft, #9b958d); }
    [data-screen="community"] .f-ok { color: var(--color-ok, #58b368); }
    [data-screen="community"] .f-warn { color: var(--color-warn, #e5b25a); }
    [data-screen="community"] .f-err { color: var(--color-err, #e06c60); }
    [data-screen="community"] .mini-flow { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; font-size: 12px; color: var(--color-ink, #ece8e1); background: rgba(0,0,0,0.2); padding: 7px 10px; border-radius: 7px; }
    [data-screen="community"] .mini-flow i { font-style: normal; color: var(--color-ink-soft, #9b958d); }
    [data-screen="community"] .sub, [data-screen="community"] .dsub { color: var(--color-ink-soft, #9b958d); font-size: 12.5px; margin: 0; line-height: 1.45; }
    [data-screen="community"] .ciact { display: flex; align-items: center; gap: 8px; margin-top: auto; padding-top: 4px; }
    [data-screen="community"] .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 32px; padding: 0 12px; border-radius: 7px; border: 1px solid var(--color-line, #2a2a33); background: #222229; color: var(--color-ink, #ece8e1); font: 500 13px var(--font-sans, Inter, sans-serif); cursor: pointer; }
    [data-screen="community"] .btn.sm { height: 28px; padding: 0 10px; font-size: 12px; }
    [data-screen="community"] .btn.btn-primary { background: var(--color-accent, #d97757); border-color: var(--color-accent, #d97757); color: #fff; font-weight: 600; }
    [data-screen="community"] .ipf { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; font-size: 12.5px; margin-bottom: 10px; }
    [data-screen="community"] .pgraph { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 12px 0; }
    [data-screen="community"] .pn2 { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 7px; background: #1e1e25; border: 1px solid var(--color-line, #2a2a33); font-size: 12.5px; }
    [data-screen="community"] .pw { width: 18px; height: 2px; background: var(--color-line, #2a2a33); display: inline-block; }
    [data-screen="community"] .pcheck { display: grid; gap: 6px; padding: 12px; border-radius: 8px; background: rgba(0,0,0,0.22); border: 1px solid var(--color-line, #2a2a33); font-size: 12.5px; margin-top: 12px; }
    [data-screen="community"] .dfield { display: grid; gap: 5px; font-size: 12.5px; margin-bottom: 10px; }
    [data-screen="community"] .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  `;

  function isEffectStep(stepText) {
    return /publish|remove|export|send|write|draft/i.test(String(stepText || ''));
  }

  function baseFileName(v) {
    return String(v ?? '').split(/[\\/]/).filter(Boolean).pop() || String(v ?? '');
  }

  function emitCommunityToast(u, setLocalToast, message) {
    if (typeof u?.setToast === 'function') u.setToast(message);
    else if (typeof u?.toast === 'function') u.toast(message);
    if (typeof window.dispatchEvent === 'function' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new window.CustomEvent('archhub:notice', { detail: { message } }));
    }
    setLocalToast(message);
  }

  function resolveStdMetadata(s) {
    const settings = Array.isArray(s?.settings) ? s.settings : [];
    const stdVersion = s?.baboomStandard?.version
      || settings.find(r => /standard version/i.test(`${r.id || ''} ${r.label || ''}`))?.value
      || '2026 · current';
    const stdSite = s?.baboomStandard?.site
      || settings.find(r => /standard website/i.test(`${r.id || ''} ${r.label || ''}`))?.value
      || 'baboom.archhub.io';
    return { stdVersion: String(stdVersion), stdSite: String(stdSite) };
  }

  function buildStandardItems(s, stdVersion) {
    const versionLabel = stdVersion.includes('previous') ? '2025' : '2026';
    const byCode = new Map();
    const raw = s?.baboomStandard;
    const liveRules = Array.isArray(raw) ? raw : Array.isArray(raw?.rules) ? raw.rules : Array.isArray(raw?.items) ? raw.items : [];
    for (const r of liveRules) {
      if (Array.isArray(r) && r.length >= 2) {
        const code = String(r[0] || '').trim();
        const what = String(r[1] || '').trim();
        if (code) byCode.set(code, { id: code, code, kind: 'Standard', name: `${code} ${what.split(':')[0]}`, what, by: 'Office standard', scope: 'Office', verified: true, version: versionLabel, effect: false });
      } else if (r && typeof r === 'object') {
        const code = String(r.code || r.id || '').trim();
        const what = String(r.summary || r.description || r.what || r.title || r.name || '').trim();
        const head = String(r.title || r.name || what.split(':')[0] || '').trim();
        const name = code && !head.startsWith(code) ? `${code} ${head}`.trim() : (head || code);
        if (code) byCode.set(code, { id: code, code, kind: 'Standard', name, what: what || head, by: 'Office standard', scope: 'Office', verified: true, version: String(r.version || versionLabel), effect: false });
      }
    }
    for (const [code, what] of DEFAULT_STD) {
      if (!byCode.has(code)) {
        byCode.set(code, {
          id: code,
          code,
          kind: 'Standard',
          name: `${code} ${what.split(':')[0]}`,
          what,
          by: 'Office standard',
          scope: 'Office',
          verified: true,
          version: versionLabel,
          effect: false
        });
      }
    }
    return [...byCode.values()];
  }

  function buildNodeItems(s) {
    const byId = new Map();
    for (const it of Array.isArray(s?.libraryPorts) ? s.libraryPorts : []) {
      if (!it || !it.id || it.noEngine || it.available === false || it.disabled || it.agentNode) continue;
      const ins = (it.ports?.target || it.inputs || []).map(p => p.label || p.name || p.id).join(', ') || 'no input';
      const outs = (it.ports?.source || it.outputs || []).map(p => p.label || p.name || p.id).join(', ') || 'no output';
      const effect = it.pure === undefined
        ? /change|send|write|export|publish|effect/i.test(`${it.cat || ''} ${it.engine || ''}`)
        : !it.pure;
      byId.set(it.id, {
        id: 'n:' + it.id,
        lib: it.id,
        kind: 'Nodes',
        name: it.title || it.name || it.id,
        by: String(it.sub || it.cat || 'ArchHub').split(' · ')[0] || 'ArchHub',
        scope: 'Office',
        verified: true,
        version: String(it.version || '1.0'),
        effect,
        what: `${ins} → ${outs}`
      });
    }
    for (const c of Array.isArray(s?.catalogue) ? s.catalogue : []) {
      if (!c || !c.id || byId.has(c.id) || c.unavailable || c.disabled || c.agentNode) continue;
      const effect = c.pure === undefined
        ? /change|send|write|export|publish|effect/i.test(`${c.family || ''} ${c.descriptor?.engine || ''}`)
        : !c.pure;
      byId.set(c.id, {
        id: 'n:' + c.id,
        lib: c.id,
        kind: 'Nodes',
        name: c.name || c.title || c.id,
        by: String(c.family || 'ArchHub').split(' · ')[0] || 'ArchHub',
        scope: 'Office',
        verified: true,
        version: String(c.version || '1.0'),
        effect,
        what: c.description || `${c.input || 'no input'} → ${c.output || 'no output'}`
      });
    }
    return [...byId.values()];
  }

  function buildWorkflowItems(s, publishedLocal) {
    const out = [];
    const seen = new Set();
    const authorLabel = s?.profile?.name || 'You';
    const addWf = raw => {
      if (!raw || !raw.name) return;
      const key = String(raw.id || raw.name).toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      const steps = Array.isArray(raw.steps) && raw.steps.length ? raw.steps.map(String) : ['Open session', 'Run workflow'];
      const scope = raw.scope === 'Community' ? 'Public' : (raw.scope || 'Office');
      out.push({
        id: String(raw.id || 'wf-' + out.length),
        kind: 'Workflows',
        name: String(raw.name),
        by: raw.by === 'Yours' ? authorLabel : String(raw.by || raw.author || 'Office'),
        scope,
        uses: Number(raw.uses ?? raw.installs ?? 0),
        trust: raw.trust || (scope === 'Public' ? 'Public · review before use' : 'Office verified'),
        steps,
        update: Boolean(raw.update),
        version: String(raw.version || '1.0.0'),
        verified: raw.verified !== undefined ? Boolean(raw.verified) : scope !== 'Public',
        effect: raw.effect !== undefined ? Boolean(raw.effect) : steps.some(isEffectStep)
      });
    };

    for (const item of publishedLocal) addWf(item);

    const comm = s?.community;
    if (Array.isArray(comm)) {
      for (const item of comm) addWf({ ...item, name: item.name || item.title });
    } else if (comm && typeof comm === 'object') {
      for (const item of Array.isArray(comm.workflows) ? comm.workflows : []) addWf({ ...item, name: item.name || item.title });
      for (const p of Array.isArray(comm.shared) ? comm.shared : []) {
        addWf({
          id: 'shared:' + (p.id || p.title),
          name: p.title || p.name,
          by: authorLabel,
          scope: p.scope === 'Community' ? 'Public' : 'Ours',
          uses: 0,
          steps: Array.isArray(p.steps) && p.steps.length ? p.steps : [p.title || 'Shared workflow'],
          version: p.version || '1.0.0',
          verified: true
        });
      }
      for (const p of Array.isArray(comm.patterns) ? comm.patterns : []) {
        addWf({
          id: 'pat:' + (p.id || p.title),
          name: p.title || p.name,
          by: p.source || 'Peer',
          scope: 'Office',
          uses: 0,
          steps: Array.isArray(p.steps) && p.steps.length ? p.steps : [p.description || p.title || 'Pattern'],
          version: '1.0.0',
          verified: p.status === 'Accepted'
        });
      }
      for (const m of Array.isArray(comm.marketplace) ? comm.marketplace : []) {
        addWf({
          id: 'mkt:' + (m.id || m.name),
          name: m.name || m.title,
          by: m.author || 'Community',
          scope: 'Public',
          uses: Number(m.uses || 0),
          steps: Array.isArray(m.steps) && m.steps.length ? m.steps : [m.description || m.name],
          version: m.version || '1.0.0',
          verified: Boolean(m.verified)
        });
      }
    }

    for (const item of OFFICE_WORKFLOWS) addWf(item);
    return out;
  }

  function inspectPublishTarget(target) {
    const nodes = Array.isArray(target?.nodes) ? target.nodes : [];
    const paths = [];
    const hostsSet = new Set();
    const eff = [];
    const vals = [];

    for (const n of nodes) {
      const nTitle = n.title || n.label || n.id || 'Node';
      const isEff = Boolean(n.effect || (n.pure === false) || isEffectStep(nTitle));
      if (isEff) eff.push(nTitle);

      const paramEntries = [];
      if (Array.isArray(n.parameterSchema) && n.parameterSchema.length && n.params && typeof n.params === 'object') {
        for (const def of n.parameterSchema) {
          paramEntries.push({ name: def.label || def.key, type: def.type || 'text', value: n.params[def.key] });
        }
      } else if (Array.isArray(n.params)) {
        for (const p of n.params) {
          paramEntries.push({ name: p.n || p.label || p.name || '', type: p.t || p.type || 'text', value: p.v ?? p.value ?? '' });
        }
      } else if (n.params && typeof n.params === 'object') {
        const defs = Array.isArray(n.paramDefs) ? n.paramDefs : [];
        for (const [k, v] of Object.entries(n.params)) {
          const def = defs.find(d => d.id === k || d.name === k);
          paramEntries.push({ name: def?.name || k, type: def?.type || 'text', value: v });
        }
      }

      for (const p of paramEntries) {
        const str = String(p.value ?? '');
        if (!str) continue;
        vals.push(`${p.name}=${str}`);
        const isUrl = /^https?:\/\//i.test(str);
        if (!isUrl && (p.type === 'file' || p.type === 'folder' || /^[a-zA-Z]:[\\/]/.test(str) || (/[/\\]/.test(str) && /\.[a-z0-9]{1,8}$/i.test(str)))) {
          paths.push(`${p.name} on ${nTitle}`);
        }
        if (/^(URL|To|Channel|Account)$/i.test(p.name) || isUrl) {
          hostsSet.add(str.replace(/^https?:\/\/([^/]+).*$/i, '$1'));
        }
      }
    }

    const sec = vals.filter(v => /token|secret|password|api[_-]?key|sk-[a-z0-9]/i.test(v));
    const cli = vals.filter(v => /@|client|20\.CLIENTS/i.test(v.split('=').slice(1).join('=')));
    return { paths, hosts: [...hostsSet], eff, sec, cli };
  }

  function Community() {
    const s = useData() || {},
      u = useApp() || {},
      [query, setQuery] = React.useState(''),
      [kind, setKind] = React.useState('All'),
      [scope, setScope] = React.useState('All'),
      [publishedLocal, setPublishedLocal] = React.useState([]),
      [previewModal, setPreviewModal] = React.useState(null),
      [ruleModal, setRuleModal] = React.useState(null),
      [publishOpen, setPublishOpen] = React.useState(false),
      [pubWorkflowId, setPubWorkflowId] = React.useState(''),
      [pubShareWith, setPubShareWith] = React.useState('Office'),
      [pubVersion, setPubVersion] = React.useState('1.0.0'),
      [localToast, setLocalToast] = React.useState('');

    const action = window.UI.useAction ? window.UI.useAction() : { state: 'idle', run: fn => Promise.resolve().then(fn) };
    React.useEffect(() => {
      if (typeof api?.refreshCommunity === 'function') {
        action.run(async () => {
          const result = await api.refreshCommunity();
          return result?.peers?.length || result?.patterns?.length ? result : null;
        });
      }
    }, []);

    const toastMs = Number(s?.runtimeParameters?.toast_visible_ms);
    React.useEffect(() => {
      if (!localToast || !Number.isFinite(toastMs) || toastMs <= 0) return undefined;
      const t = window.setTimeout(() => setLocalToast(''), toastMs);
      return () => window.clearTimeout(t);
    }, [localToast, toastMs]);

    const { stdVersion, stdSite } = resolveStdMetadata(s);
    const workflows = React.useMemo(() => buildWorkflowItems(s, publishedLocal), [s.community, s.profile?.name, publishedLocal]);
    const nodes = React.useMemo(() => buildNodeItems(s), [s.libraryPorts, s.catalogue]);
    const standards = React.useMemo(() => buildStandardItems(s, stdVersion), [s.baboomStandard, stdVersion]);
    const allItems = React.useMemo(() => [...workflows, ...nodes, ...standards], [workflows, nodes, standards]);

    const q = query.trim().toLowerCase();
    const visibleItems = allItems
      .filter(c => (kind === 'All' || c.kind === kind)
        && (scope === 'All' || c.scope === scope)
        && (!q || `${c.name} ${c.by} ${c.what || ''} ${(c.steps || []).join(' ')}`.toLowerCase().includes(q)))
      .slice(0, kind === 'All' && !q ? 24 : 120);

    const publishCandidates = React.useMemo(() => {
      const list = [];
      const seen = new Set();
      const pushCandidate = (id, name, nodesList, stepsList = undefined) => {
        if (!id || seen.has(id)) return;
        seen.add(id);
        list.push({ id, name: name || 'Untitled workflow', nodes: nodesList || [], steps: stepsList });
      };
      if (s.graph?.id || s.graph?.nodes?.length) {
        pushCandidate(s.graph.id || 'open-graph', s.graph.name || 'Current workflow', s.graph.nodes || [], undefined);
      }
      for (const g of Array.isArray(s.graphs) ? s.graphs : []) {
        pushCandidate(g.id, g.name || g.title, g.nodes || [], undefined);
      }
      for (const t of Array.isArray(s.tasks) ? s.tasks : []) {
        if (t.direct) continue;
        pushCandidate(t.id, t.title || t.name, t.workflow || t.nodes || [], (t.steps || []).map(st => st.title || st));
      }
      if (!list.length) pushCandidate('default-wf', 'Current workflow', [], undefined);
      return list;
    }, [s.graph, s.graphs, s.tasks]);

    const selectedPubTarget = publishCandidates.find(x => x.id === pubWorkflowId) || publishCandidates[0];
    const pubAudit = React.useMemo(() => inspectPublishTarget(selectedPubTarget), [selectedPubTarget]);

    const importWorkflowCopy = async c => {
      if (!c) return;
      const copyTitle = c.by === 'ArchHub' ? c.name : `${c.name} (copy)`;
      const runAct = fn => (typeof u?.act === 'function' ? u.act(fn) : Promise.resolve().then(fn));

      if (typeof api?.importCommunityCopy === 'function') {
        await runAct(() => api.importCommunityCopy(c, copyTitle));
      } else {
        if (typeof api?.newSession === 'function') {
          await runAct(() => api.newSession(copyTitle)).catch(() => null);
        } else if (typeof api?.addGraph === 'function') {
          await runAct(() => api.addGraph(copyTitle)).catch(() => null);
        }
        const execNodes = (Array.isArray(s.libraryPorts) ? s.libraryPorts : []).filter(x => !x.noEngine && x.available !== false);
        for (let i = 0; i < (c.steps || []).length; i++) {
          const stepTitle = baseFileName(c.steps[i]);
          if (typeof api?.addNode === 'function' && execNodes.length > 0) {
            const match = execNodes.find(x => x.title?.toLowerCase() === stepTitle.toLowerCase()) || execNodes[i % execNodes.length];
            const made = await runAct(() => api.addNode(match.id, { x: 120 + i * 280, y: 140 })).catch(() => null);
            if (made?.id && typeof api?.renameNode === 'function') {
              await runAct(() => api.renameNode(made.id, stepTitle)).catch(() => null);
            }
          } else if (typeof api?.addNote === 'function') {
            await runAct(() => api.addNote(stepTitle, { x: 120 + i * 280, y: 140 })).catch(() => null);
          }
        }
      }

      setPreviewModal(null);
      emitCommunityToast(u, setLocalToast, `${c.name} imported as a copy. Nothing ran; assign an agent or press Run.`);
      u?.go?.('canvas');
    };

    const handleAddNodeToCanvas = async libId => {
      const runAct = fn => (typeof u?.act === 'function' ? u.act(fn) : Promise.resolve().then(fn));
      const made = await runAct(() => api.addNode(libId));
      if (made?.id) u?.setSelectedNodeId?.(made.id);
      u?.go?.('canvas');
    };

    const handleOpenNodeDocs = libId => {
      window.UI.openDocTopic?.('Node reference', libId);
      u?.go?.('docs');
    };

    const handlePublishConfirm = () => {
      if (pubAudit.sec.length > 0) {
        emitCommunityToast(u, setLocalToast, 'Remove the key first. Nothing was published.');
        return;
      }
      const target = selectedPubTarget;
      const rawSteps = target.steps?.length
        ? target.steps
        : (target.nodes || []).filter(n => !n.fixed && n.kind !== 'session').map(n => n.title || n.label || n.id);
      const cleanSteps = (rawSteps.length ? rawSteps : [target.name]).map(st => baseFileName(st));
      const author = s.profile?.name || 'You';
      const entry = {
        id: 'pub-' + Date.now(),
        kind: 'Workflows',
        name: target.name,
        by: author,
        scope: 'Ours',
        uses: 0,
        trust: `Yours · ${pubShareWith}`,
        steps: cleanSteps,
        update: false,
        version: pubVersion.trim() || '1.0.0',
        verified: true,
        effect: cleanSteps.some(isEffectStep)
      };
      setPublishedLocal(prev => [entry, ...prev]);
      if (typeof api?.proposeCommunityShare === 'function' && (!api.supportsAction || api.supportsAction('proposeCommunityShare'))) {
        Promise.resolve(api.proposeCommunityShare({ title: target.name, scope: pubShareWith === 'Public' ? 'Community' : 'Office', redact: true })).catch(err => {
          emitCommunityToast(u, setLocalToast, err?.message || 'Community share could not be proposed.');
        });
      }
      setPublishOpen(false);
      emitCommunityToast(u, setLocalToast, `${target.name} published to ${pubShareWith}. Paths were reduced to file names.`);
    };

    return <main className="page" data-screen="community">
      <style>{COMM_CSS}</style>
      {action.state === 'waiting' ? <p className="sub" role="status">Loading community catalogue…</p> : null}
      {action.state === 'empty' ? <span hidden /> : null}
      {action.state === 'loaded' ? <span hidden /> : null}
      {action.state === 'error' && <div role="alert" style={{ marginBottom: 12 }}>
        {action.error}
        <Btn sm onClick={event => executeAction('projects.project-tools.RetryCommunity', { action }, event)}>Retry</Btn>
      </div>}
      {localToast && <div className="toast" role="status" aria-live="polite" style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--color-line, #2a2a33)', background: '#202028' }}>
        {localToast}
      </div>}

      <h1>Community</h1>
      <p className="lead">One catalogue of workflows, skills, nodes and the standard. archhub.io/community shows the same items; Open in ArchHub on the site lands here.</p>

      <div className="toolbar">
        <input
          className="field"
          id="cq"
          placeholder="Search the catalogue"
          aria-label="Search the catalogue"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <div className="seg" role="group" aria-label="Catalogue kind">
          {['All', 'Workflows', 'Nodes', 'Standard'].map(x => <button
            key={x}
            type="button"
            data-ck={x}
            aria-pressed={kind === x}
            onClick={event => executeAction('projects.project-tools.FilterKind', { handler: () => setKind(x) }, event)}
          >
            {x}
          </button>)}
        </div>
        <select
          className="field sm"
          id="cscope"
          aria-label="From whom"
          value={scope}
          onChange={e => setScope(e.target.value)}
        >
          <option value="All">From everyone</option>
          <option value="Ours">Yours</option>
          <option value="Office">Office</option>
          <option value="Public">Public</option>
        </select>
        <span className="fill" style={{ flex: 1 }} />
        <button type="button" className="btn btn-primary" id="publish" onClick={event => executeAction('projects.project-tools.OpenPublish', { handler: () => { setPubWorkflowId(publishCandidates[0]?.id || ''); setPublishOpen(true); } }, event)}>
          Publish yours
        </button>
      </div>

      <div className="cgrid">
        {visibleItems.length ? visibleItems.map(c => <article className="card citem" key={c.id} data-kind={c.kind}>
          <div className="cih">
            <span className={'tile fam-' + (c.effect ? 'effect' : 'list')}>
              <Icon name={c.kind === 'Nodes' ? 'canvas' : c.kind === 'Standard' ? 'docs' : 'group'} size={13} />
            </span>
            <div className="cit">
              <b>{c.name}</b>
              <span className="ciby">
                <span className="av">{(c.by || '?')[0]}</span>
                {c.by}
                {c.verified && <span className="verif" title="The author's account is verified"><Icon name="check" size={11} /> Verified</span>}
              </span>
            </div>
            <span className="chip ver">v{c.version}</span>
          </div>

          <div className="cimeta">
            <span>{c.kind === 'Nodes' ? 'Built in' : c.kind === 'Standard' ? 'Office standard' : `${c.uses} install${c.uses === 1 ? '' : 's'}`}</span>
            <span className={c.effect ? 'f-warn' : 'f-ok'}>{c.effect ? 'Writes outside the file' : 'Read only'}</span>
            {c.update && <span className="chip upd">Update from author</span>}
          </div>

          {c.steps ? <div className="mini-flow">
            {c.steps.map((st, idx) => <React.Fragment key={idx}>
              {idx > 0 && <i>›</i>}
              <span>{st}</span>
            </React.Fragment>)}
          </div> : <p className="sub">{c.what || ''}</p>}

          <div className="ciact">
            {c.kind === 'Nodes' ? <>
              <button type="button" className="btn sm" data-cdoc={c.lib} onClick={event => executeAction('projects.project-tools.OpenNodeDocs', { handler: () => handleOpenNodeDocs(c.lib) }, event)}>Docs</button>
              <button type="button" className="btn btn-primary sm" data-cadd={c.lib} onClick={event => executeAction('projects.project-tools.AddNodeToCanvas', { handler: () => handleAddNodeToCanvas(c.lib) }, event)}>Add to canvas</button>
            </> : c.kind === 'Standard' ? <>
              <button type="button" className="btn sm" data-cstd={c.id} onClick={event => executeAction('projects.project-tools.OpenStandardRule', { handler: () => setRuleModal(c) }, event)}>Open the rule</button>
            </> : <>
              <button type="button" className="btn sm" data-prev={c.id} onClick={event => executeAction('projects.project-tools.PreviewWorkflow', { handler: () => setPreviewModal(c) }, event)}>Preview</button>
              <button type="button" className="btn btn-primary sm" data-imp={c.id} onClick={event => executeAction('projects.project-tools.InstallWorkflow', { handler: () => importWorkflowCopy(c) }, event)}>Install</button>
            </>}
          </div>
        </article>) : <p className="sub">Nothing matches. Try a node name, a program or an STD id.</p>}
      </div>

      {window.UI.CommunityTools && <window.UI.CommunityTools />}

      {previewModal && (() => {
        const eff = (previewModal.steps || []).filter(isEffectStep);
        return <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) setPreviewModal(null); }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'grid', placeItems: 'center', padding: 20 }}>
          <section className="dialog" role="dialog" aria-modal="true" aria-label={previewModal.name} style={{ width: 'min(620px, 94vw)', background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #2a2a33)', borderRadius: 12, padding: 22 }}>
            <h2 style={{ marginTop: 0 }}>{previewModal.name}</h2>
            <div className="ipf">
              <span><b>{previewModal.by}</b>{previewModal.verified ? ' Verified' : ' Not verified'}</span>
              <span>v{previewModal.version}</span>
              <span>{previewModal.uses} installs</span>
              <span className={eff.length ? 'f-warn' : 'f-ok'}>{eff.length ? 'Writes outside the file' : 'Read only'}</span>
            </div>
            <p className="dsub">
              Install makes a copy in its own .archhub file. Nothing runs until you press Run{eff.length ? `; ${eff.join(', ')} then wait for your Approve` : ''}.
            </p>
            <div className="pgraph">
              {(previewModal.steps || []).map((st, idx) => <React.Fragment key={idx}>
                {idx > 0 && <span className="pw" />}
                <span className="pn2">
                  <span className={'tile fam-' + (isEffectStep(st) ? 'effect' : 'list')}>
                    <Icon name={isEffectStep(st) ? 'send' : 'library'} size={11} />
                  </span>
                  {st}
                </span>
              </React.Fragment>)}
            </div>
            <p className="dsub" style={{ marginBottom: 16 }}>
              {eff.length ? 'Steps that write outside the workflow will wait for your Approve.' : 'Read-only steps; nothing outside the workflow changes.'}
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" className="btn" onClick={event => executeAction('projects.project-tools.ClosePreview', { handler: () => setPreviewModal(null) }, event)}>Close</button>
              <button type="button" className="btn btn-primary" onClick={event => executeAction('projects.project-tools.ConfirmInstall', { handler: () => importWorkflowCopy(previewModal) }, event)}>Install</button>
            </div>
          </section>
        </div>;
      })()}

      {ruleModal && <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) setRuleModal(null); }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'grid', placeItems: 'center', padding: 20 }}>
        <section className="dialog" role="dialog" aria-modal="true" aria-label={ruleModal.code || ruleModal.id} style={{ width: 'min(520px, 94vw)', background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #2a2a33)', borderRadius: 12, padding: 22 }}>
          <h2 style={{ marginTop: 0 }}>{ruleModal.code || ruleModal.id}</h2>
          <p>{String(ruleModal.what || '').replace(/\.*$/, '')}.</p>
          <p className="dsub" style={{ marginBottom: 16 }}>
            From the Office standard ({stdVersion}). The same rule is on {stdSite}, and BABOOM cites it as STD {ruleModal.code || ruleModal.id}.
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button type="button" className="btn" onClick={event => executeAction('projects.project-tools.CloseStandardRule', { handler: () => setRuleModal(null) }, event)}>Close</button>
          </div>
        </section>
      </div>}

      {publishOpen && <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) setPublishOpen(false); }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'grid', placeItems: 'center', padding: 20 }}>
        <section className="dialog" role="dialog" aria-modal="true" aria-label="Publish a workflow" style={{ width: 'min(560px, 94vw)', background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #2a2a33)', borderRadius: 12, padding: 22 }}>
          <h2 style={{ marginTop: 0 }}>Publish a workflow</h2>
          <label className="dfield">
            Workflow
            <select className="field" id="pubt" aria-label="Workflow" value={selectedPubTarget?.id || ''} onChange={e => setPubWorkflowId(e.target.value)}>
              {publishCandidates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <div className="grid2">
            <label className="dfield">
              Share with
              <select className="field" id="pubs" aria-label="Share with" value={pubShareWith} onChange={e => setPubShareWith(e.target.value)}>
                <option value="Office">Office</option>
                <option value="Public">Public</option>
              </select>
            </label>
            <label className="dfield">
              Version
              <input className="field" id="pubv" aria-label="Version" value={pubVersion} onChange={e => setPubVersion(e.target.value)} />
            </label>
          </div>
          <div id="pubcheck" className="pcheck">
            <b>Privacy check</b>
            <div className={pubAudit.sec.length ? 'f-err' : 'f-ok'}>
              {pubAudit.sec.length
                ? `✕ ${pubAudit.sec.length} value${pubAudit.sec.length > 1 ? 's look' : ' looks'} like a key. Remove it before publishing`
                : '✓ No secrets or keys in the file'}
            </div>
            <div className={pubAudit.paths.length ? 'f-warn' : 'f-ok'}>
              {pubAudit.paths.length
                ? `${pubAudit.paths.length} local path${pubAudit.paths.length > 1 ? 's' : ''} will be published as file names only (${pubAudit.paths.slice(0, 2).join(', ')}${pubAudit.paths.length > 2 ? '…' : ''})`
                : '✓ No local paths'}
            </div>
            <div className={pubAudit.cli.length ? 'f-warn' : 'f-ok'}>
              {pubAudit.cli.length
                ? `${pubAudit.cli.length} value${pubAudit.cli.length > 1 ? 's name' : ' names'} a client or an email. Check before publishing`
                : '✓ No client names found in parameters'}
            </div>
            <b>What it reaches</b>
            <div className={pubAudit.hosts.length ? 'f-warn' : 'f-ok'}>
              {pubAudit.hosts.length
                ? `${pubAudit.hosts.length} network host${pubAudit.hosts.length > 1 ? 's' : ''}: ${pubAudit.hosts.slice(0, 3).join(', ')}`
                : '✓ No network hosts'}
            </div>
            <div className={pubAudit.eff.length ? 'f-warn' : 'f-ok'}>
              {pubAudit.eff.length
                ? `${pubAudit.eff.length} effect node${pubAudit.eff.length > 1 ? 's' : ''}: ${pubAudit.eff.slice(0, 3).join(', ')}. After install they run only on Run and wait for Approve`
                : '✓ Pure: nothing outside the file changes'}
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
            <button type="button" className="btn" onClick={event => executeAction('projects.project-tools.CancelPublish', { handler: () => setPublishOpen(false) }, event)}>Cancel</button>
            <button type="button" className="btn btn-primary" onClick={event => executeAction('projects.project-tools.ConfirmPublish', { handler: handlePublishConfirm }, event)}>Publish</button>
          </div>
        </section>
      </div>}
    </main>;
  }

  function InterfaceStudio() {
    const s = useData(),
      u = useApp(),
      nodes = s.graph.nodes.filter(n => n.kind === 'UI element'),
      [id, setId] = React.useState(null),
      [colour, setColour] = React.useState(A.accent),
      selected = nodes.find(n => n.id === id);
    return <main className="page" data-screen="interface"><Heading title="Interface studio" sub="Build the view from editable nodes, then reuse it as a mod."><Btn sm onClick={event => executeAction("projects.project-tools.Canvas.17", {u}, event)}>Canvas</Btn><Btn p onClick={event => executeAction("projects.project-tools.MakeAMod.18", {u}, event)}>Make a mod</Btn></Heading><div className="settings-grid"><Card style={{
          padding: 22
        }}><h2>Elements</h2><div className="flex" style={{
            margin: '18px 0'
          }}>{['Button', 'Card', 'Text'].map(kind => <Btn sm key={kind} onClick={event => executeAction("projects.project-tools.Add.19", {api,kind,setId,u}, event)}>Add {kind}</Btn>)}</div>{nodes.map(n => <button key={n.id} className="listbutton spread" aria-pressed={n.id === id} onClick={event => executeAction("projects.project-tools.SetIdNId.20", {n,setId}, event)}><span>{n.params.element} · {n.params.label}</span><Icon name="arrow" size={14} /></button>)}{selected && <div className="grid" style={{
            marginTop: 20
          }}>{api.getNodeParameters(selected).map(p => <label key={p.key} className="parameter-row"><span>{p.label}</span>{p.type === 'boolean' ? <D.Toggle label={p.label} checked={selected.params[p.key]} onCheckedChange={v => u.act(() => api.setNodeParam(id, p.key, v))} /> : p.options ? <select aria-label={'Element ' + p.label} value={selected.params[p.key]} onChange={e => u.act(() => api.setNodeParam(id, p.key, e.target.value))}>{p.options.map(v => <option key={v}>{v}</option>)}</select> : <input aria-label={'Element ' + p.label} type={p.type === 'number' ? 'number' : p.type === 'color' ? 'color' : 'text'} value={selected.params[p.key]} onChange={e => u.act(() => api.setNodeParam(id, p.key, p.type === 'number' ? Number(e.target.value) : e.target.value))} />}</label>)}<Btn sm onClick={event => executeAction("projects.project-tools.DeleteElement.21", {api,id,u}, event)}>Delete element</Btn></div>}<div className="row"><h3>Theme</h3><div className="spread" style={{
              marginTop: 14
            }}><input aria-label="Interface accent" type="color" value={colour} onChange={e => setColour(e.target.value)} /><Btn onClick={event => executeAction("projects.project-tools.ApplyColour.22", {api,colour,u}, event)}>Apply colour</Btn></div></div></Card><Card style={{
          padding: 22,
          minHeight: 450
        }}><div className="spread"><h2>Live view</h2><Chip>{nodes.length} elements</Chip></div><div style={{
            position: 'relative',
            height: 420,
            overflow: 'auto',
            marginTop: 18,
            border: '1px dashed ' + A.line,
            borderRadius: 12
          }} onDragOver={e => e.preventDefault()} onDrop={e => {
            e.preventDefault();
            const node = e.dataTransfer.getData('ui-element');
            if (node) {
              const r = e.currentTarget.getBoundingClientRect();
              u.act(() => api.moveNode(node, {
                x: Math.max(0, e.clientX - r.left - 50),
                y: Math.max(0, e.clientY - r.top - 15)
              }));
            }
          }}>{nodes.map(n => <div key={n.id} draggable onDragStart={e => e.dataTransfer.setData('ui-element', n.id)} onClick={() => setId(n.id)} style={{
              position: 'absolute',
              left: n.x,
              top: n.y,
              width: Math.min(360, n.params.width),
              outline: id === n.id ? '1px solid ' + A.accent : 'none',
              borderRadius: 8,
              padding: 6
            }}>{n.params.element === 'Button' ? <button disabled={!n.params.enabled} onClick={event => executeAction("projects.project-tools.UGoNParamsAction.23", {n,u}, event)} style={{
                background: n.params.colour,
                border: 0,
                color: '#fff',
                padding: '10px 18px',
                borderRadius: 8
              }}>{n.params.label}</button> : n.params.element === 'Card' ? <Card style={{
                padding: 22,
                borderColor: n.params.colour
              }}>{n.params.label}</Card> : <p style={{
                color: n.params.colour
              }}>{n.params.label}</p>}</div>)}</div></Card></div></main>;
  }

  function AccountUsage() {
    const s = useData(),
      u = useApp();
    const [requestState, setRequestState] = React.useState(s.profile.signedIn ? 'waiting' : 'empty');
    const [failure, setFailure] = React.useState('');
    const refresh = () => {
      setRequestState('waiting');
      return api.refreshCompany().then(() => setRequestState('loaded'))
        .catch(error => { setFailure(error.message); setRequestState('error'); });
    };
    React.useEffect(() => { if (s.profile.signedIn) refresh(); else setRequestState('empty'); }, [s.profile.signedIn]);
    const body = <section style={{
      marginTop: 24
    }}><Heading title="Usage & office" sub="Your account, seats and subscription stay together." /><div className="settings-grid"><Card style={{
          padding: 22
        }}><h2>Your office</h2><div className="row spread"><span>Node runs this session</span><b>{s.runs.length}</b></div><div className="row spread"><span>Plan</span><b>{s.profile.plan}</b></div><div className="row spread"><span>Office seats</span><input aria-label="Office seats" type="number" min={s.people.length} key={s.usage.seats} defaultValue={s.usage.seats || ''} disabled={!s.profile.signedIn} onBlur={e => { const seats = Number(e.target.value); e.target.value = String(s.usage.seats || ''); if (seats !== s.usage.seats) u.confirm('Update office subscription to ' + seats + ' seats?', () => api.setAccountSeats(seats)); }} /></div><Btn sm onClick={event => executeAction("projects.project-tools.ManageSubscription.24", {u}, event)}>Manage subscription</Btn></Card><Card style={{
          padding: 22
        }}><h2>Account security</h2><p className="muted" style={{
            margin: '14px 0'
          }}>Sign out of connected sessions without changing your office’s data.</p><Btn sm onClick={event => executeAction("projects.project-tools.SignOutEverywhere.25", {api,u}, event)}>Sign out everywhere</Btn><div className="row"><h3>Transfer office ownership</h3>{s.people.filter(p => p.id !== s.profile.id).map(p => <div className="spread row" key={p.id}><span>{p.name} · {p.accessRole || 'Member'}</span><Btn sm onClick={event => executeAction("projects.project-tools.Transfer.26", {api,p,u}, event)}>Transfer</Btn></div>)}</div></Card></div></section>;
    return <>
      {requestState === 'waiting' && <p role="status">Reading your office account…</p>}
      {requestState === 'error' && <div role="alert">{failure}<Btn onClick={event => executeAction('projects.controls.activate', {handler:refresh}, event)}>Retry office</Btn></div>}
      {requestState === 'empty' && <><Btn onClick={event => executeAction('projects.controls.activate', {handler:() => u.act(api.signIn)}, event)}>Sign in</Btn>{body}</>}
      {requestState === 'loaded' && <>{body}</>}
    </>;
  }

  Object.assign(window.UI, {
    GraphManager,
    ModelReview,
    Community,
    InterfaceStudio,
    AccountUsage
  });

  // WIRE-projects: each rendered callback is registered with its executable owner.
  function projectsprojecttoolsjsxAsyncAwaitUActApi1({api: apiArg, g, u}, event) {
    const handler = async () => {
      const result = await u.act(() => apiArg.selectGraph(g.id));
      if (result) u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxUActApiUpdateGraphG2({api: apiArg, g, u}, event) {
    const handler = () => u.act(() => apiArg.updateGraph(g.id, { pinned: !g.pinned }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxUShowRenameGraphId3({g, u}, event) {
    const handler = () => u.show('Rename workflow', { id: g.id, text: g.name });
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxUConfirmRemoveGName4({api: apiArg, g, u}, event) {
    const handler = () => u.confirm('Remove ' + g.name + '?', () => apiArg.removeGraph(g.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxAddGraph5({api: apiArg, name, u}, event) {
    const handler = async () => {
      const result = await u.act(() => apiArg.addGraph(name));
      if (result) u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxSaveVersion6({api: apiArg, u}, event) {
    const handler = () => u.act(apiArg.saveGraphVersion);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxRestore7({api: apiArg, u, v}, event) {
    const handler = async () => {
      const result = await u.act(() => apiArg.restoreGraphVersion(v.id));
      if (result) u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxExportGraph8({u}, event) {
    const handler = () => u.download('Workflow');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxSync9({api: apiArg, u}, event) {
    const handler = () => u.act(apiArg.syncAccount);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxOpenAsNode10({api: apiArg, operation, source, u}, event) {
    const handler = async () => {
      const result = await u.act(() => apiArg.openModelReviewNode(operation, source));
      if (result && apiArg.getSnapshot().graph.scopeKey === source.scope && apiArg.getSnapshot().sessionFile === source.path) {
        await u.go('canvas', source.path);
        if (apiArg.getSnapshot().graph.id === source.document && apiArg.getSnapshot().sessionFile === source.path) u.setSelectedNodeId(result.id);
      }
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxRunCheck11({api: apiArg, operation, source, u}, event) {
    const handler = () => u.act(() => apiArg.reviewModel(operation, source));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxExportIssues12({u, source}, event) {
    const handler = () => u.download('Issues', source);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxBrain13({u}, event) {
    const handler = () => u.go('brain');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxSetTabT14({setTab, t}, event) {
    const handler = () => setTab(t);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxReviewShare15({api: apiArg, redact, scope, title, u}, event) {
    const handler = async () => {
      const c = await u.act(() => apiArg.proposeCommunityShare({ title, scope, redact }));
      if (c) u.go('workshop');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxUActApiReviewCommunityPatternP16({api: apiArg, d, p, u}, event) {
    const handler = async () => {
      const result = await u.act(() => apiArg.reviewCommunityPattern(p.id, d));
      if (d === 'Recheck' && result) u.go('workshop');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxCanvas17({u}, event) {
    const handler = () => u.go('canvas');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxMakeAMod18({u}, event) {
    const handler = () => u.show('Make a mod');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxAdd19({api: apiArg, kind, setId, u}, event) {
    const handler = async () => {
      const n = await u.act(() => apiArg.addInterfaceElement(kind));
      if (n) setId(n.id);
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxSetIdNId20({n, setId}, event) {
    const handler = () => setId(n.id);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxDeleteElement21({api: apiArg, id, u}, event) {
    const handler = () => u.act(() => apiArg.deleteNode(id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxApplyColour22({api: apiArg, colour, u}, event) {
    const handler = () => u.act(() => apiArg.setSetting('Appearance.Accent colour', colour));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxUGoNParamsAction23({n, u}, event) {
    const handler = () => u.go(n.params.action.toLowerCase());
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxManageSubscription24({u}, event) {
    const handler = () => u.show('Subscription');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxSignOutEverywhere25({api: apiArg, u}, event) {
    const handler = () => u.confirm('Sign out of all sessions?', () => apiArg.signOutEverywhere());
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxTransfer26({api: apiArg, p, u}, event) {
    const handler = () => u.confirm('Make ' + p.name + ' the office owner?', () => apiArg.transferOwnership(p.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function projectsprojecttoolsjsxRetryCommunity({action}) { return action.retry(); }
  function projectsprojecttoolsjsxFilterKind({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxOpenPublish({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxOpenNodeDocs({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxAddNodeToCanvas({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxOpenStandardRule({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxPreviewWorkflow({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxInstallWorkflow({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxClosePreview({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxConfirmInstall({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxCloseStandardRule({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxCancelPublish({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxConfirmPublish({handler}) { return handler?.(); }
  const PROJECT_ACTIONS = {
    "projects.project-tools.RetryCommunity": "projectsprojecttoolsjsxRetryCommunity",
    "projects.project-tools.FilterKind": "projectsprojecttoolsjsxFilterKind",
    "projects.project-tools.OpenPublish": "projectsprojecttoolsjsxOpenPublish",
    "projects.project-tools.OpenNodeDocs": "projectsprojecttoolsjsxOpenNodeDocs",
    "projects.project-tools.AddNodeToCanvas": "projectsprojecttoolsjsxAddNodeToCanvas",
    "projects.project-tools.OpenStandardRule": "projectsprojecttoolsjsxOpenStandardRule",
    "projects.project-tools.PreviewWorkflow": "projectsprojecttoolsjsxPreviewWorkflow",
    "projects.project-tools.InstallWorkflow": "projectsprojecttoolsjsxInstallWorkflow",
    "projects.project-tools.ClosePreview": "projectsprojecttoolsjsxClosePreview",
    "projects.project-tools.ConfirmInstall": "projectsprojecttoolsjsxConfirmInstall",
    "projects.project-tools.CloseStandardRule": "projectsprojecttoolsjsxCloseStandardRule",
    "projects.project-tools.CancelPublish": "projectsprojecttoolsjsxCancelPublish",
    "projects.project-tools.ConfirmPublish": "projectsprojecttoolsjsxConfirmPublish",
    "projects.project-tools.AsyncAwaitUActApi.1": "projectsprojecttoolsjsxAsyncAwaitUActApi1",
    "projects.project-tools.UActApiUpdateGraphG.2": "projectsprojecttoolsjsxUActApiUpdateGraphG2",
    "projects.project-tools.UShowRenameGraphId.3": "projectsprojecttoolsjsxUShowRenameGraphId3",
    "projects.project-tools.UConfirmRemoveGName.4": "projectsprojecttoolsjsxUConfirmRemoveGName4",
    "projects.project-tools.AddGraph.5": "projectsprojecttoolsjsxAddGraph5",
    "projects.project-tools.SaveVersion.6": "projectsprojecttoolsjsxSaveVersion6",
    "projects.project-tools.Restore.7": "projectsprojecttoolsjsxRestore7",
    "projects.project-tools.ExportGraph.8": "projectsprojecttoolsjsxExportGraph8",
    "projects.project-tools.Sync.9": "projectsprojecttoolsjsxSync9",
    "projects.project-tools.OpenAsNode.10": "projectsprojecttoolsjsxOpenAsNode10",
    "projects.project-tools.RunCheck.11": "projectsprojecttoolsjsxRunCheck11",
    "projects.project-tools.ExportIssues.12": "projectsprojecttoolsjsxExportIssues12",
    "projects.project-tools.Brain.13": "projectsprojecttoolsjsxBrain13",
    "projects.project-tools.SetTabT.14": "projectsprojecttoolsjsxSetTabT14",
    "projects.project-tools.ReviewShare.15": "projectsprojecttoolsjsxReviewShare15",
    "projects.project-tools.UActApiReviewCommunityPatternP.16": "projectsprojecttoolsjsxUActApiReviewCommunityPatternP16",
    "projects.project-tools.Canvas.17": "projectsprojecttoolsjsxCanvas17",
    "projects.project-tools.MakeAMod.18": "projectsprojecttoolsjsxMakeAMod18",
    "projects.project-tools.Add.19": "projectsprojecttoolsjsxAdd19",
    "projects.project-tools.SetIdNId.20": "projectsprojecttoolsjsxSetIdNId20",
    "projects.project-tools.DeleteElement.21": "projectsprojecttoolsjsxDeleteElement21",
    "projects.project-tools.ApplyColour.22": "projectsprojecttoolsjsxApplyColour22",
    "projects.project-tools.UGoNParamsAction.23": "projectsprojecttoolsjsxUGoNParamsAction23",
    "projects.project-tools.ManageSubscription.24": "projectsprojecttoolsjsxManageSubscription24",
    "projects.project-tools.SignOutEverywhere.25": "projectsprojecttoolsjsxSignOutEverywhere25",
    "projects.project-tools.Transfer.26": "projectsprojecttoolsjsxTransfer26"
  };
  if (typeof window.registerActions === 'function') {
    window.registerActions(PROJECT_ACTIONS, {projectsprojecttoolsjsxRetryCommunity,projectsprojecttoolsjsxFilterKind,projectsprojecttoolsjsxOpenPublish,projectsprojecttoolsjsxOpenNodeDocs,projectsprojecttoolsjsxAddNodeToCanvas,projectsprojecttoolsjsxOpenStandardRule,projectsprojecttoolsjsxPreviewWorkflow,projectsprojecttoolsjsxInstallWorkflow,projectsprojecttoolsjsxClosePreview,projectsprojecttoolsjsxConfirmInstall,projectsprojecttoolsjsxCloseStandardRule,projectsprojecttoolsjsxCancelPublish,projectsprojecttoolsjsxConfirmPublish,projectsprojecttoolsjsxAsyncAwaitUActApi1,projectsprojecttoolsjsxUActApiUpdateGraphG2,projectsprojecttoolsjsxUShowRenameGraphId3,projectsprojecttoolsjsxUConfirmRemoveGName4,projectsprojecttoolsjsxAddGraph5,projectsprojecttoolsjsxSaveVersion6,projectsprojecttoolsjsxRestore7,projectsprojecttoolsjsxExportGraph8,projectsprojecttoolsjsxSync9,projectsprojecttoolsjsxOpenAsNode10,projectsprojecttoolsjsxRunCheck11,projectsprojecttoolsjsxExportIssues12,projectsprojecttoolsjsxBrain13,projectsprojecttoolsjsxSetTabT14,projectsprojecttoolsjsxReviewShare15,projectsprojecttoolsjsxUActApiReviewCommunityPatternP16,projectsprojecttoolsjsxCanvas17,projectsprojecttoolsjsxMakeAMod18,projectsprojecttoolsjsxAdd19,projectsprojecttoolsjsxSetIdNId20,projectsprojecttoolsjsxDeleteElement21,projectsprojecttoolsjsxApplyColour22,projectsprojecttoolsjsxUGoNParamsAction23,projectsprojecttoolsjsxManageSubscription24,projectsprojecttoolsjsxSignOutEverywhere25,projectsprojecttoolsjsxTransfer26});
  }
})();
