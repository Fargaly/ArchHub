(() => {
  const WIRE_DEPENDENCIES_JSX_ACTIONS = {
  "settings.dependencies.choose-folder": "chooseFolder",
  "settings.dependencies.DependenciesAction0": "DependenciesAction0",
  "settings.dependencies.DependenciesAction1": "DependenciesAction1",
  "settings.dependencies.DependenciesAction2": "DependenciesAction2",
  "settings.dependencies.DependenciesAction3": "DependenciesAction3",
  "settings.dependencies.DependenciesAction4": "DependenciesAction4",
  "settings.dependencies.DependenciesAction5": "DependenciesAction5",
  "settings.dependencies.DependenciesAction6": "DependenciesAction6",
  "settings.dependencies.DependenciesAction7": "DependenciesAction7",
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
      Card,
      Chip,
      Heading,

    } = window.UI,
    Icon = window.AHIcon;
  function Dependencies() {
    const s = useData(),
      u = useApp(),
      [q, setQ] = React.useState(''),
      [filter, setFilter] = React.useState('All'),
      [id, setId] = React.useState(s.dependencies[0]?.id),
      selected = s.dependencies.find(t => t.id === id);
    const rows = s.dependencies.filter(t => !q || (t.name + ' ' + t.group).toLowerCase().includes(q.toLowerCase())).filter(t => filter === 'All' || filter === 'Installed' && t.state !== 'Not installed' || filter === 'Updates' && t.state === 'Update ready' || filter === 'Needs attention' && t.state === 'Needs repair');
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DEPENDENCIES_JSX_ACTIONS, {DependenciesAction0: (event) => (() => u.go('settings/Dependencies'))(event),
DependenciesAction1: (event) => (() => u.act(api.checkDependencies))(event),
DependenciesAction2: (t, event) => (() => setFilter(t))(event),
DependenciesAction3: (t, event) => (() => setId(t.id))(event),
DependenciesAction4: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Install')))(event),
DependenciesAction5: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Update')))(event),
DependenciesAction6: (t, event) => (() => u.act(() => api.manageDependency(t.id, 'Repair')))(event),
DependenciesAction7: (name, event) => (() => u.go(name === 'BABOOM' ? 'settings/BABOOM' : name === 'Watcher' ? 'watcher' : 'canvas'))(event),
DependenciesAction8: (event) => (() => u.act(() => api.manageDependency(selected.id, 'Check')))(event),
DependenciesAction9: (event) => (() => u.download('Dependency logs'))(event),
DependenciesAction10: (event) => (() => u.act(() => api.manageDependency(selected.id, 'Remove')))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><main className="page dependencies-page" data-screen="dependencies"><Heading title="Dependencies" sub="The tools behind your work, managed in one place."><Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction0', event)}>Settings</Btn><Btn p onClick={event => runAction('settings.dependencies.DependenciesAction1', event)}>Check all</Btn></Heading><div className="dependency-metrics">{[[s.dependencies.filter(t => t.state === 'Ready').length, 'Ready', 'check'], [s.dependencies.filter(t => t.state === 'Update ready').length, 'Updates', 'update'], [s.dependencies.filter(t => t.state === 'Needs repair').length, 'Needs attention', 'shield'], [(s.dependencies.reduce((n, t) => n + (t.state === 'Not installed' ? 0 : t.diskMb), 0) / 1024).toFixed(1) + ' GB', 'Managed storage', 'cloud']].map(([value, label, icon]) => <Card key={label} className="dependency-metric"><Icon name={icon} /><b>{value}</b><span className="muted">{label}</span></Card>)}</div><div className="dependency-toolbar"><input aria-label="Search dependencies" className="fill" placeholder="Find a tool or program connector…" value={q} onChange={e => setQ(e.target.value)} />{['All', 'Installed', 'Updates', 'Needs attention'].map(t => <button key={t} className="tab-button" aria-pressed={filter === t} onClick={event => runAction('settings.dependencies.DependenciesAction2', t, event)}>{t}</button>)}</div><div className="dependency-columns"><div className="grid" style={{
          alignContent: 'start'
        }}>{rows.map(t => <Card key={t.id} className={'package-card ' + (id === t.id ? 'selected' : '')}><button className="package-summary" onClick={event => runAction('settings.dependencies.DependenciesAction3', t, event)}><span className="package-icon"><Icon name={t.group === 'Programs' ? 'canvas' : t.group === 'Models' ? 'brain' : 'code'} size={22} /></span><span className="fill"><b>{t.name}</b><small>{t.group} · {t.version}</small></span><span className={'status-dot ' + (t.state === 'Not installed' ? 'off' : '')} /><span className="package-status">{t.state}</span></button><div className="package-footer"><span>{t.state === 'Not installed' ? 'Not on disk' : t.diskMb + ' MB'} · {t.ramMb} MB RAM</span><div className="flex">{t.state === 'Not installed' ? <Btn sm p onClick={event => runAction('settings.dependencies.DependenciesAction4', t, event)}>Install</Btn> : <><Btn sm title={'Update ' + t.name} aria-label={'Update ' + t.name} onClick={event => runAction('settings.dependencies.DependenciesAction5', t, event)}><Icon name="update" size={15} /></Btn><Btn sm title={'Repair ' + t.name} aria-label={'Repair ' + t.name} onClick={event => runAction('settings.dependencies.DependenciesAction6', t, event)}><Icon name="refresh" size={15} /></Btn></>}</div></div></Card>)}{!rows.length && <Card style={{
            padding: 30
          }}>No tools match this filter.</Card>}</div>{selected && <Card className="package-detail"><div className="spread"><span className="package-icon"><Icon name="code" size={25} /></span><Chip c={selected.state === 'Needs repair' ? A.warn : A.ok}>{selected.state}</Chip></div><h2 style={{
            margin: '20px 0 8px'
          }}>{selected.name}</h2><p className="muted">{selected.description}</p><div className="package-facts">{[['Version', selected.version], ['Available', selected.availableVersion], ['Disk', selected.diskMb + ' MB'], ['Memory', selected.ramMb + ' MB'], ['Source', 'Managed package'], ['Integrity', selected.integrity]].map(([label, value]) => <div className="spread" key={label}><span className="muted">{label}</span><span>{value}</span></div>)}</div><h3>Used by</h3>{selected.usedBy.map(name => <button key={name} className="listbutton" onClick={event => runAction('settings.dependencies.DependenciesAction7', name, event)}>{name} →</button>)}<div className="spread" style={{
            marginTop: 20
          }}><h3>Activity</h3><Btn sm title="Refresh logs" aria-label="Refresh logs" onClick={event => runAction('settings.dependencies.DependenciesAction8', event)}><Icon name="refresh" size={14} /></Btn></div><div className="package-log">{selected.logs.map((log, i) => <p key={i}>{log}</p>)}</div><div className="flex" style={{
            marginTop: 18
          }}><Btn sm onClick={event => runAction('settings.dependencies.DependenciesAction9', event)}>Export logs</Btn><Btn sm disabled={selected.state === 'Not installed'} onClick={event => runAction('settings.dependencies.DependenciesAction10', event)}>Remove</Btn></div></Card>}</div></main></>;
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
    Dependencies,
    CapabilitySettings
  });
})();
