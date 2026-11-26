(() => {
  const WIRE_DEPENDENCIES_JSX_ACTIONS = {
  "settings.dependencies.choose-folder": "chooseFolder",
  "settings.dependencies.DependenciesAction1": "DependenciesAction1",
  "settings.dependencies.DependenciesAction2": "DependenciesAction2",
  "settings.dependencies.DependenciesAction3": "DependenciesAction3",
  "settings.dependencies.DependenciesAction4": "DependenciesAction4",
  "settings.dependencies.DependenciesAction5": "DependenciesAction5",
  "settings.dependencies.DependenciesAction6": "DependenciesAction6",
  "settings.dependencies.DependenciesAction8": "DependenciesAction8",
  "settings.dependencies.DependenciesAction9": "DependenciesAction9",
  "settings.dependencies.DependenciesAction10": "DependenciesAction10"
};
  const {
      A,
      D,
      api,
      useData,
      useApp,
      Btn,
      Chip,

    } = window.UI,
    Icon = window.AHIcon;
  // Settings › This PC › Dependencies (founder 2026-11-26: all settings in one place, never a page of its own).
  // Programs come from the host owner (the header's "ready" count reads the same rows); agent tools from the
  // managed-dependency owner. Counters count those rows; nothing is shown as 0 before it was read.
  function DependenciesSection() {
    const s = useData(),
      u = useApp(),
      [q, setQ] = React.useState(''),
      [filter, setFilter] = React.useState('All'),
      [id, setId] = React.useState('');
    const ready = h => h.state === 'connected' || h.state === 'listening';
    // The host owner's own words: connected or listening is Ready, an absent program is Not installed, the rest Not running.
    const hostState = h => ready(h) ? 'Ready' : h.state === 'absent' || /not installed/i.test(h.detail || '') ? 'Not installed' : 'Not running';
    const programs = (s.hosts || []).map(h => ({id: 'host:' + h.id, name: h.name || h.id, group: 'Program', state: hostState(h), detail: h.detail || '', host: true}));
    const all = [...programs, ...(s.dependencies || [])];
    const rows = all.filter(t => !q || (t.name + ' ' + t.group).toLowerCase().includes(q.toLowerCase())).filter(t => filter === 'All' || filter === 'Installed' && t.state !== 'Not installed' || filter === 'Updates' && t.state === 'Update ready' || filter === 'Needs attention' && t.state === 'Needs repair');
    const selected = all.find(t => t.id === id && !t.host);
    const programsRead = programs.length > 0 || !!s.hostError || s.hostsProbing === false && Array.isArray(s.hosts);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DEPENDENCIES_JSX_ACTIONS, {
      DependenciesAction1: (event) => (() => u.act(async () => { await api.readHostAvailability(); return api.checkDependencies(); }))(event),
      DependenciesAction2: (t, event) => (() => setFilter(t))(event),
      DependenciesAction3: (t, event) => (() => t.host ? u.go('settings/Connections') : setId(id === t.id ? '' : t.id))(event),
      DependenciesAction4: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Install')))(event),
      DependenciesAction5: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Update')))(event),
      DependenciesAction6: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Repair')))(event),
      DependenciesAction8: (event) => (() => u.act(() => api.manageDependency(selected.id, 'Check')))(event),
      DependenciesAction9: (event) => (() => u.download('Dependency logs'))(event),
      DependenciesAction10: (event) => (() => u.act(() => api.manageDependency(selected.id, 'Remove')))(event)});
    const count = state => all.filter(t => [].concat(state).includes(t.state)).length;
    // Design: Settings › This PC › Dependencies (archhub-directions, row 'deps').
    const metrics = [['check', 'Ready', count('Ready')], ['clock', 'Not running', count('Not running')], ['upload', 'Updates', count('Update ready')],
      ['shield', 'Needs repair', count('Needs repair')], ['close', 'Not installed', count('Not installed')]];
    return <section className="sheet-pc-card sheet-owner-card sheet-card-wide dependencies-section" data-design-section="Dependencies" aria-label="Dependencies">
      <header className="sheet-card-head"><span className="sheet-card-icon fam-system"><Icon name="code" size={12} /></span><h3>Dependencies</h3><Btn sm p onClick={event => runAction('settings.dependencies.DependenciesAction1', event)}>Check all</Btn></header>
      <window.UI.RegisteredActionStatus state={actionState} retry={retryAction} />
      {!programsRead ? <p role="status">Reading programs…</p> : <div className="dependency-metrics">{metrics.map(([icon, label, value]) => <div className="dependency-metric" key={label}><Icon name={icon} size={14} /><b>{value}</b><small>{label}</small></div>)}</div>}
      {s.hostError && <p role="alert">{s.hostError}</p>}
      <div className="flex dependency-filter"><input aria-label="Find a tool or program" placeholder="Find a tool or program…" value={q} onChange={event => setQ(event.target.value)} />{['All', 'Installed', 'Updates', 'Needs attention'].map(name => <Btn sm ghost key={name} aria-pressed={filter === name} onClick={event => runAction('settings.dependencies.DependenciesAction2', name, event)}>{name}</Btn>)}</div>
      <div className="dependency-rows" role="list">{rows.map(t => <div role="listitem" key={t.id} className={'sheet-property-row dependency-row' + (selected?.id === t.id ? ' selected' : '')}>
        <button type="button" className="button-reset sheet-property-copy" onClick={event => runAction('settings.dependencies.DependenciesAction3', t, event)}><b>{t.name}</b><small>{t.group}{t.version ? ' · ' + t.version : ''}{t.detail ? ' · ' + t.detail : ''}</small></button>
        <div className="sheet-property-control"><Chip c={t.state === 'Ready' ? A.ok : t.state === 'Update ready' ? A.accent : t.state === 'Not installed' ? A.inkSoft : A.warn}>{t.state}</Chip>
          {!t.host && t.state === 'Not installed' && <Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction4', t, event)}>Install</Btn>}
          {!t.host && t.state === 'Update ready' && <Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction5', t, event)}>Update</Btn>}
          {!t.host && t.state === 'Needs repair' && <Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction6', t, event)}>Repair</Btn>}</div></div>)}
        {programsRead && !rows.length && <p>{all.length ? 'No tools match this filter.' : 'No programs or agent tools found on this PC yet. Check all reads them again.'}</p>}
        {programsRead && !(s.dependencies || []).length && all.length > 0 && <p className="muted">Agent tools are read when you choose Check all.</p>}</div>
      {selected && <div className="package-detail"><h4>{selected.name}</h4><p className="muted">{selected.description}</p>
        <div className="package-facts">{[['Version', selected.version], ['Available', selected.availableVersion], ['Disk', selected.diskMb + ' MB'], ['Memory', selected.ramMb == null ? 'Not running' : Math.round(selected.ramMb) + ' MB'], ['Integrity', selected.integrity]].map(([label, value]) => <div className="spread" key={label}><span className="muted">{label}</span><span>{value}</span></div>)}</div>
        <div className="spread"><b>Activity</b><Btn sm aria-label="Refresh logs" title="Refresh logs" onClick={event => runAction('settings.dependencies.DependenciesAction8', event)}><Icon name="refresh" size={14} /></Btn></div>
        <div className="package-log">{(selected.logs || []).map((log, i) => <p key={i}>{log}</p>)}</div>
        <div className="flex"><Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction9', event)}>Export logs</Btn><Btn sm disabled={selected.state === 'Not installed'} onClick={event => runAction('settings.dependencies.DependenciesAction10', event)}>Remove</Btn></div></div>}
    </section>;
  }
  function CapabilitySettings({
    id
  }) {
    useData();
    const u = useApp(),
      c = api.getCapabilityState(id);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DEPENDENCIES_JSX_ACTIONS, {chooseFolder: key => api.pickCapabilityFolder(id, key)});
    if (!c) return <window.UI.Empty>Open this capability node on its canvas to edit the exact instance.</window.UI.Empty>;
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div className="capability-parameters">{api.getCapabilityParameters(id).map(p => <label className="parameter-row" key={p.key}><span>{p.label}<small className="muted"> · {p.type}{p.unit ? ' · ' + p.unit : ''}</small></span>{p.type === 'boolean' ? <D.Toggle label={c.name + ' ' + p.label} checked={c.params[p.key]} onCheckedChange={v => u.act(() => api.setCapabilityParameter(id, p.key, v))} /> : p.options?.length ? <select aria-label={c.name + ' ' + p.label} value={c.params[p.key]} onChange={e => u.act(() => api.setCapabilityParameter(id, p.key, e.target.value))}>{p.options.map(v => <option key={v}>{v}</option>)}</select> : <span className="flex"><input aria-label={c.name + ' ' + p.label} type={p.type === 'number' ? 'number' : p.type === 'color' ? 'color' : 'text'} value={c.params[p.key]} onChange={e => u.act(() => api.setCapabilityParameter(id, p.key, p.type === 'number' ? Number(e.target.value) : e.target.value))} />{p.type === 'path' && <button className="icon-button" title={'Choose ' + p.label} aria-label={'Choose ' + c.name + ' ' + p.label} onClick={() => runAction('settings.dependencies.choose-folder', p.key)}><Icon name="folder" size={15} /></button>}</span>}</label>)}</div></>;
  }
  Object.assign(window.UI, {
    DependenciesSection,
    CapabilitySettings
  });
})();
