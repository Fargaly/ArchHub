(() => {
  const WIRE_DEPENDENCIES_JSX_ACTIONS = {
  "settings.dependencies.choose-folder": "chooseFolder",
  "settings.dependencies.DependenciesAction1": "DependenciesAction1",
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
  // Its owner is the npm agent-tool inventory (managed_dependencies); programs and their connections are Connections'.
  // The inventory is read when the section opens: waiting, the refusal with Retry, or the real rows; never zeros unread.
  function DependenciesSection() {
    const s = useData(),
      u = useApp(),
      [q, setQ] = React.useState(''),
      [id, setId] = React.useState(''),
      [load, setLoad] = React.useState({status: (s.dependencies || []).length ? 'loaded' : 'waiting'}),
      [attempt, setAttempt] = React.useState(0);
    React.useEffect(() => {
      if (!attempt && (api.getSnapshot().dependencies || []).length) return undefined;
      let current = true;
      setLoad({status: 'waiting'});
      // npm answers in ~10-20 s on a busy PC; past 90 s the row says so with Retry.
      window.UI.budgetedRead('npm', () => api.checkDependencies(), 90000).then(() => { if (current) setLoad({status: (api.getSnapshot().dependencies || []).length ? 'loaded' : 'empty'}); },
        error => { if (current) setLoad({status: 'error', message: error.message || String(error)}); });
      return () => { current = false; };
    }, [attempt]);
    const all = s.dependencies || [];
    const rows = all.filter(t => !q || (t.name + ' ' + t.group).toLowerCase().includes(q.toLowerCase()));
    const selected = all.find(t => t.id === id);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DEPENDENCIES_JSX_ACTIONS, {
      DependenciesAction1: (event) => (() => setAttempt(value => value + 1))(event),
      DependenciesAction3: (t, event) => (() => setId(id === t.id ? '' : t.id))(event),
      DependenciesAction4: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Install')))(event),
      DependenciesAction5: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Update')))(event),
      DependenciesAction6: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Repair')))(event),
      DependenciesAction8: (event) => (() => u.act(() => api.manageDependency(selected.id, 'Check')))(event),
      DependenciesAction9: (event) => (() => u.download('Dependency logs'))(event),
      DependenciesAction10: (event) => (() => u.act(() => api.manageDependency(selected.id, 'Remove')))(event)});
    const count = state => all.filter(t => t.state === state).length;
    // Design: Settings › This PC › Dependencies (archhub-directions, row 'deps').
    const metrics = [['Ready', count('Ready')], ['Updates', count('Update ready')], ['Needs repair', count('Needs repair')], ['Not installed', count('Not installed')]];
    const check = <Btn sm p disabled={load.status === 'waiting'} onClick={event => runAction('settings.dependencies.DependenciesAction1', event)}>Check all</Btn>;
    return <section className="sheet-pc-card sheet-owner-card sheet-card-wide dependencies-section" data-design-section="Dependencies" aria-label="Dependencies">
      <header className="sheet-card-head"><span className="sheet-card-icon fam-model"><Icon name="code" size={12} /></span><h3>Dependencies</h3></header>
      <window.UI.RegisteredActionStatus state={actionState} retry={retryAction} />
      <div className="sheet-property-row sheet-property-full" data-row="deps"><span className="sheet-property-copy">Agent tools<small>The agent command-line tools ArchHub installs and updates with npm. Programs and their connections are in Connections. Check all reads them again</small></span>
      <div className="sheet-property-control">
      {load.status === 'waiting' && <div className="dependency-metrics"><span role="status">Reading the agent tools on this PC (npm answers in a few seconds)…</span></div>}
      {load.status === 'empty' && <div className="dependency-metrics"><span>npm reported no agent tools on this PC.</span><span className="fill" />{check}</div>}
      {load.status === 'error' && <div className="dependency-metrics" role="alert"><span>{load.message}</span><span className="fill" /><Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction1', event)}>Retry</Btn></div>}
      {load.status === 'loaded' && <><div className="dependency-metrics">{metrics.map(([label, value]) => <div className="dependency-metric" key={label}><b>{value}</b><small>{label}</small></div>)}<span className="fill" />{check}</div>
      <input className="dependency-find" aria-label="Find a tool" placeholder="Find a tool…" value={q} onChange={event => setQ(event.target.value)} />
      <div className="dependency-rows" role="list">{rows.map(t => <div role="listitem" key={t.id} className={'sheet-property-row dependency-row' + (selected?.id === t.id ? ' selected' : '')}>
        <button type="button" className="button-reset sheet-property-copy" aria-expanded={selected?.id === t.id} onClick={event => runAction('settings.dependencies.DependenciesAction3', t, event)}><b>{t.name}</b><small>Agent tool · npm{t.version ? ' · ' + t.version : ''}</small></button>
        <div className="sheet-property-control"><Chip c={t.state === 'Ready' ? A.ok : t.state === 'Update ready' ? A.accent : t.state === 'Not installed' ? A.inkSoft : A.warn}>{t.state}</Chip>
          {t.state === 'Not installed' && <Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction4', t, event)}>Install</Btn>}
          {t.state === 'Update ready' && <Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction5', t, event)}>Update</Btn>}
          {t.state === 'Needs repair' && <Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction6', t, event)}>Repair</Btn>}</div></div>)}
        {!rows.length && <p>No tool matches “{q}”.</p>}</div></>}
      {selected && <div className="package-detail"><h4>{selected.name}</h4><p className="muted">{selected.description}</p>
        <div className="package-facts">{[['Version', selected.version], ['Available', selected.availableVersion], ['Disk', selected.diskMb + ' MB'], ['Memory', selected.ramMb == null ? 'Not running' : Math.round(selected.ramMb) + ' MB'], ['Integrity', selected.integrity]].map(([label, value]) => <div className="spread" key={label}><span className="muted">{label}</span><span>{value}</span></div>)}</div>
        <div className="spread"><b>Activity</b><Btn sm aria-label="Refresh logs" title="Refresh logs" onClick={event => runAction('settings.dependencies.DependenciesAction8', event)}><Icon name="refresh" size={14} /></Btn></div>
        <div className="package-log">{(selected.logs || []).map((log, i) => <p key={i}>{log}</p>)}</div>
        <div className="flex"><Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction9', event)}>Export logs</Btn><Btn sm disabled={selected.state === 'Not installed'} onClick={event => runAction('settings.dependencies.DependenciesAction10', event)}>Remove</Btn></div></div>}
      </div></div>
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
