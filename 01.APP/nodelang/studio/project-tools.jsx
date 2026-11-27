// Full node surfaces reuse the supplied page, Card, parameter and table grammar.
(() => {
  function executeAction(id, context, event) {
    if (typeof window.executeAction === 'function') return window.executeAction(id, context, event);
    return context?.handler?.(event);
  }
  const {

      api,
      useData,
      useApp,
      Btn,
      Card,
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


  const COMM_CSS = `
    .comm-dlg .field { height: 34px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--color-line, #2a2a33); background: var(--color-bg-panel, #15151a); color: var(--color-ink, #ece8e1); font: inherit; font-size: 13px; }
    .comm-dlg .tile { width: 28px; height: 28px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; flex: none; background: rgba(255,255,255,0.06); color: var(--color-ink, #ece8e1); }
    .comm-dlg .tile.fam-effect { background: rgba(229,178,90,0.16); color: var(--color-warn, #e5b25a); }
    .comm-dlg .tile.fam-list { background: rgba(217,119,87,0.15); color: var(--color-accent, #d97757); }
    .comm-dlg .f-ok { color: var(--color-ok, #58b368); }
    .comm-dlg .f-warn { color: var(--color-warn, #e5b25a); }
    .comm-dlg .f-err { color: var(--color-err, #e06c60); }
    .comm-dlg .sub, .comm-dlg .dsub { color: var(--color-ink-soft, #9b958d); font-size: 12.5px; margin: 0; line-height: 1.45; }
    .comm-dlg .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 32px; padding: 0 12px; border-radius: 7px; border: 1px solid var(--color-line, #2a2a33); background: #222229; color: var(--color-ink, #ece8e1); font: 500 13px var(--font-sans, Inter, sans-serif); cursor: pointer; }
    .comm-dlg .btn.sm { height: 28px; padding: 0 10px; font-size: 12px; }
    .comm-dlg .btn.btn-primary { background: var(--color-accent, #d97757); border-color: var(--color-accent, #d97757); color: #fff; font-weight: 600; }
    .comm-dlg .ipf { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; font-size: 12.5px; margin-bottom: 10px; }
    .comm-dlg .pgraph { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 12px 0; }
    .comm-dlg .pn2 { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 7px; background: #1e1e25; border: 1px solid var(--color-line, #2a2a33); font-size: 12.5px; }
    .comm-dlg .pw { width: 18px; height: 2px; background: var(--color-line, #2a2a33); display: inline-block; }
    .comm-dlg .pcheck { display: grid; gap: 6px; padding: 12px; border-radius: 8px; background: rgba(0,0,0,0.22); border: 1px solid var(--color-line, #2a2a33); font-size: 12.5px; margin-top: 12px; }
    .comm-dlg .dfield { display: grid; gap: 5px; font-size: 12.5px; margin-bottom: 10px; }
    .comm-dlg .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  `;

  function isEffectStep(stepText) {
    return /publish|remove|export|send|write|draft/i.test(String(stepText || ''));
  }

  function baseFileName(v) {
    return String(v ?? '').split(/[\\/]/).filter(Boolean).pop() || String(v ?? '');
  }


  function buildWorkflowItems(s) {
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

  // Community lives in the Library (catalogue rows) and in two dialogs (preview, publish); no page of its own.
  function notify(u, message) {
    if (typeof u?.setToast === 'function') u.setToast(message);
    else if (typeof u?.toast === 'function') u.toast(message);
  }

  function CommunityOverlay({label, width, onClose, children}) {
    const body = <div className="overlay comm-dlg" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }} onKeyDown={e => { if (e.key === 'Escape') onClose(); }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000, display: 'grid', placeItems: 'center', padding: 20 }}>
      <style>{COMM_CSS}</style>
      <section className="dialog" role="dialog" aria-modal="true" aria-label={label} style={{ width: `min(${width}px, 94vw)`, background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #2a2a33)', borderRadius: 12, padding: 22 }}>{children}</section>
    </div>;
    return window.ReactDOM?.createPortal ? window.ReactDOM.createPortal(body, document.body) : body;
  }

  function CommunityPreview({item, onClose}) {
    const s = useData() || {}, u = useApp() || {};
    const eff = (item.steps || []).filter(isEffectStep);
    const install = async () => {
      const copyTitle = item.by === 'ArchHub' ? item.name : `${item.name} (copy)`;
      const runAct = fn => (typeof u?.act === 'function' ? u.act(fn) : Promise.resolve().then(fn));
      if (typeof api?.importCommunityCopy === 'function') {
        await runAct(() => api.importCommunityCopy(item, copyTitle));
      } else {
        if (typeof api?.newSession === 'function') await runAct(() => api.newSession(copyTitle)).catch(() => null);
        else if (typeof api?.addGraph === 'function') await runAct(() => api.addGraph(copyTitle)).catch(() => null);
        const execNodes = (Array.isArray(s.libraryPorts) ? s.libraryPorts : []).filter(x => !x.noEngine && x.available !== false);
        for (let i = 0; i < (item.steps || []).length; i++) {
          const stepTitle = baseFileName(item.steps[i]);
          if (typeof api?.addNode === 'function' && execNodes.length > 0) {
            const match = execNodes.find(x => x.title?.toLowerCase() === stepTitle.toLowerCase()) || execNodes[i % execNodes.length];
            const made = await runAct(() => api.addNode(match.id, { x: 120 + i * 280, y: 140 })).catch(() => null);
            if (made?.id && typeof api?.renameNode === 'function') await runAct(() => api.renameNode(made.id, stepTitle)).catch(() => null);
          } else if (typeof api?.addNote === 'function') {
            await runAct(() => api.addNote(stepTitle, { x: 120 + i * 280, y: 140 })).catch(() => null);
          }
        }
      }
      onClose();
      notify(u, `${item.name} imported as a copy. Nothing ran; assign an agent or press Run.`);
      u?.go?.('canvas');
    };
    return <CommunityOverlay label={item.name} width={620} onClose={onClose}>
      <h2 style={{ marginTop: 0 }}>{item.name}</h2>
      <div className="ipf">
        <span><b>{item.by}</b>{item.verified ? ' Verified' : ' Not verified'}</span>
        <span>v{item.version}</span>
        <span>{item.uses} installs</span>
        <span className={eff.length ? 'f-warn' : 'f-ok'}>{eff.length ? 'Writes outside the file' : 'Read only'}</span>
      </div>
      <p className="dsub">Install makes a copy in its own .archhub file. Nothing runs until you press Run{eff.length ? `; ${eff.join(', ')} then wait for your Approve` : ''}.</p>
      <div className="pgraph">
        {(item.steps || []).map((st, idx) => <React.Fragment key={idx}>
          {idx > 0 && <span className="pw" />}
          <span className="pn2"><span className={'tile fam-' + (isEffectStep(st) ? 'effect' : 'list')}><Icon name={isEffectStep(st) ? 'send' : 'library'} size={11} /></span>{st}</span>
        </React.Fragment>)}
      </div>
      <p className="dsub" style={{ marginBottom: 16 }}>{eff.length ? 'Steps that write outside the workflow will wait for your Approve.' : 'Read-only steps; nothing outside the workflow changes.'}</p>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" className="btn" onClick={event => executeAction('projects.project-tools.ClosePreview', { handler: onClose }, event)}>Close</button>
        <button type="button" className="btn btn-primary" onClick={event => executeAction('projects.project-tools.ConfirmInstall', { handler: install }, event)}>Install</button>
      </div>
    </CommunityOverlay>;
  }

  function PublishCommunityDialog({onClose}) {
    const s = useData() || {}, u = useApp() || {},
      [pubWorkflowId, setPubWorkflowId] = React.useState(''),
      [pubShareWith, setPubShareWith] = React.useState('Office'),
      [pubVersion, setPubVersion] = React.useState('1.0.0');
    const publishCandidates = React.useMemo(() => {
      const list = [], seen = new Set();
      const pushCandidate = (id, name, nodesList, stepsList = undefined) => {
        if (!id || seen.has(id)) return;
        seen.add(id);
        list.push({ id, name: name || 'Untitled workflow', nodes: nodesList || [], steps: stepsList });
      };
      if (s.graph?.id || s.graph?.nodes?.length) pushCandidate(s.graph.id || 'open-graph', s.graph.name || 'Current workflow', s.graph.nodes || []);
      for (const g of Array.isArray(s.graphs) ? s.graphs : []) pushCandidate(g.id, g.name || g.title, g.nodes || []);
      for (const t of Array.isArray(s.tasks) ? s.tasks : []) if (!t.direct) pushCandidate(t.id, t.title || t.name, t.workflow || t.nodes || [], (t.steps || []).map(st => st.title || st));
      if (!list.length) pushCandidate('default-wf', 'Current workflow', []);
      return list;
    }, [s.graph, s.graphs, s.tasks]);
    const target = publishCandidates.find(x => x.id === pubWorkflowId) || publishCandidates[0];
    const pubAudit = React.useMemo(() => inspectPublishTarget(target), [target]);
    const confirm = () => {
      if (pubAudit.sec.length > 0) { notify(u, 'Remove the key first. Nothing was published.'); return; }
      if (typeof api?.proposeCommunityShare === 'function' && (!api.supportsAction || api.supportsAction('proposeCommunityShare'))) {
        Promise.resolve(api.proposeCommunityShare({ title: target.name, scope: pubShareWith === 'Public' ? 'Community' : 'Office', redact: true, version: pubVersion.trim() || '1.0.0' }))
          .then(() => api.refreshCommunity?.())
          .catch(err => notify(u, err?.message || 'Community share could not be proposed.'));
      }
      onClose();
      notify(u, `${target.name} sent for review before it is shared with ${pubShareWith}. Paths are reduced to file names.`);
    };
    const row = (bad, warn, okText) => <div className={bad ? 'f-err' : warn ? 'f-warn' : 'f-ok'}>{bad || warn || okText}</div>;
    return <CommunityOverlay label="Publish a workflow" width={560} onClose={onClose}>
      <h2 style={{ marginTop: 0 }}>Publish a workflow</h2>
      <label className="dfield">Workflow
        <select className="field" id="pubt" aria-label="Workflow" value={target?.id || ''} onChange={e => setPubWorkflowId(e.target.value)}>
          {publishCandidates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </label>
      <div className="grid2">
        <label className="dfield">Share with
          <select className="field" id="pubs" aria-label="Share with" value={pubShareWith} onChange={e => setPubShareWith(e.target.value)}><option value="Office">Office</option><option value="Public">Public</option></select>
        </label>
        <label className="dfield">Version
          <input className="field" id="pubv" aria-label="Version" value={pubVersion} onChange={e => setPubVersion(e.target.value)} />
        </label>
      </div>
      <div id="pubcheck" className="pcheck">
        <b>Privacy check</b>
        {row(pubAudit.sec.length && `✕ ${pubAudit.sec.length} value${pubAudit.sec.length > 1 ? 's look' : ' looks'} like a key. Remove it before publishing`, '', '✓ No secrets or keys in the file')}
        {row('', pubAudit.paths.length && `${pubAudit.paths.length} local path${pubAudit.paths.length > 1 ? 's' : ''} will be published as file names only (${pubAudit.paths.slice(0, 2).join(', ')}${pubAudit.paths.length > 2 ? '…' : ''})`, '✓ No local paths')}
        {row('', pubAudit.cli.length && `${pubAudit.cli.length} value${pubAudit.cli.length > 1 ? 's name' : ' names'} a client or an email. Check before publishing`, '✓ No client names found in parameters')}
        <b>What it reaches</b>
        {row('', pubAudit.hosts.length && `${pubAudit.hosts.length} network host${pubAudit.hosts.length > 1 ? 's' : ''}: ${pubAudit.hosts.slice(0, 3).join(', ')}`, '✓ No network hosts')}
        {row('', pubAudit.eff.length && `${pubAudit.eff.length} effect node${pubAudit.eff.length > 1 ? 's' : ''}: ${pubAudit.eff.slice(0, 3).join(', ')}. After install they run only on Run and wait for Approve`, '✓ Pure: nothing outside the file changes')}
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
        <button type="button" className="btn" onClick={event => executeAction('projects.project-tools.CancelPublish', { handler: onClose }, event)}>Cancel</button>
        <button type="button" className="btn btn-primary" onClick={event => executeAction('projects.project-tools.ConfirmPublish', { handler: confirm }, event)}>Publish</button>
      </div>
    </CommunityOverlay>;
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
    CommunityPreview,
    PublishCommunityDialog,
    communityWorkflows: buildWorkflowItems,
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
  function projectsprojecttoolsjsxBrain13({u}, event) {
    const handler = () => u.go('settings/Brain');
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
  function projectsprojecttoolsjsxClosePreview({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxConfirmInstall({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxCancelPublish({handler}) { return handler?.(); }
  function projectsprojecttoolsjsxConfirmPublish({handler}) { return handler?.(); }
  const PROJECT_ACTIONS = {
    "projects.project-tools.ClosePreview": "projectsprojecttoolsjsxClosePreview",
    "projects.project-tools.ConfirmInstall": "projectsprojecttoolsjsxConfirmInstall",
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
    "projects.project-tools.Brain.13": "projectsprojecttoolsjsxBrain13",
    "projects.project-tools.SetTabT.14": "projectsprojecttoolsjsxSetTabT14",
    "projects.project-tools.ReviewShare.15": "projectsprojecttoolsjsxReviewShare15",
    "projects.project-tools.UActApiReviewCommunityPatternP.16": "projectsprojecttoolsjsxUActApiReviewCommunityPatternP16",
    "projects.project-tools.ManageSubscription.24": "projectsprojecttoolsjsxManageSubscription24",
    "projects.project-tools.SignOutEverywhere.25": "projectsprojecttoolsjsxSignOutEverywhere25",
    "projects.project-tools.Transfer.26": "projectsprojecttoolsjsxTransfer26"
  };
  if (typeof window.registerActions === 'function') {
    window.registerActions(PROJECT_ACTIONS, {projectsprojecttoolsjsxClosePreview,projectsprojecttoolsjsxConfirmInstall,projectsprojecttoolsjsxCancelPublish,projectsprojecttoolsjsxConfirmPublish,projectsprojecttoolsjsxAsyncAwaitUActApi1,projectsprojecttoolsjsxUActApiUpdateGraphG2,projectsprojecttoolsjsxUShowRenameGraphId3,projectsprojecttoolsjsxUConfirmRemoveGName4,projectsprojecttoolsjsxAddGraph5,projectsprojecttoolsjsxSaveVersion6,projectsprojecttoolsjsxRestore7,projectsprojecttoolsjsxExportGraph8,projectsprojecttoolsjsxSync9,projectsprojecttoolsjsxBrain13,projectsprojecttoolsjsxSetTabT14,projectsprojecttoolsjsxReviewShare15,projectsprojecttoolsjsxUActApiReviewCommunityPatternP16,projectsprojecttoolsjsxManageSubscription24,projectsprojecttoolsjsxSignOutEverywhere25,projectsprojecttoolsjsxTransfer26});
  }
})();
