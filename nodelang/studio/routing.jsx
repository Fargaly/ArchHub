// Free-first routing, quotas and failover use the existing provider records.
(() => {
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
      SettingControl,
      Table
    } = window.UI,
    Icon = window.AHIcon;
  function Routing() {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction(),
      [scenario, setScenario] = React.useState('Ready');
    function handleRoutingjsx1() {
      return u.go('settings/Agents');
    }
    function handleRoutingjsx2() {
      return actionState.run(() => api.checkModelRouting(scenario));
    }
    function handleRoutingjsx3() {
      return u.go('settings/BABOOM');
    }
    const ACTIONS = {
      "routing.1": "handleRoutingjsx1",
      "routing.2": "handleRoutingjsx2",
      "routing.3": "handleRoutingjsx3"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleRoutingjsx1,
        handleRoutingjsx2,
        handleRoutingjsx3
      })(id, ...args);
    }
    return <main className="page routing-page" data-screen="routing"><window.UI.ActionStatus action={actionState} /><Heading title="Model routing" sub="Free first. A stronger model when the work needs it."><Btn sm onClick={(event) => dispatch("routing.1", event)}>Settings</Btn><select aria-label="Routing condition" value={scenario} onChange={(e) => setScenario(e.target.value)}>{['Ready', 'Rate limit', 'Failed check'].map((x) => <option key={x}>{x}</option>)}</select><Btn p onClick={(event) => dispatch("routing.2", event)}>Check routing</Btn></Heading><div className="routing-banner"><div className="flex"><Icon name="shield" /><div><h2>You set the budget</h2><p>Review the owner’s routing limits and run a check before using a provider.</p></div></div><Chip>{s.routingStatus || 'Run a routing check'}</Chip></div><div className="routing-grid"><Card style={{
          padding: 22
        }}><h2>Providers</h2>{s.providers.map((p) => <div className="routing-provider" key={p.id}><window.UI.Av id={p.id} /><div className="fill"><h3>{p.name}</h3><small className="muted">{p.model}</small></div><D.Toggle label={'Route to ' + p.name} checked={p.enabled} onCheckedChange={(v) => actionState.run(() => api.setProviderEnabled(p.id, v))} /></div>)}</Card><Card style={{
          padding: 22
        }}><h2>Free &amp; local model sources</h2>{s.modelSources.map((source) => <div className="routing-provider" key={source.id}><Icon name={source.id === 'lmstudio' || source.id === 'ollama' ? 'code' : 'cloud'} size={18} /><div className="fill"><h3>{source.name}</h3><small className="muted">{source.ready ? 'Ready' : 'Needs provider setup'}</small></div><D.Toggle label={source.name + ' source'} checked={source.ready} onCheckedChange={(v) => actionState.run(() => api.setModelSource(source.id, {
              ready: v
            }))} /><input aria-label={source.name + ' daily cap'} type="number" min="0" value={source.limit} onChange={(e) => actionState.run(() => api.setModelSource(source.id, {
              limit: Number(e.target.value)
            }))} style={{
              width: 65
            }} /></div>)}</Card></div><div className="settings-grid" style={{
        marginTop: 20
      }}><Card style={{
          padding: 20
        }}><h2 style={{
            marginBottom: 14
          }}>Priority &amp; failover</h2>{s.settings.filter((r) => r.page === 'Agents').map((r) => <SettingControl row={r} key={r.id} raw={u.advanced} />)}</Card><Card style={{
          padding: 20
        }}><h2 style={{
            marginBottom: 14
          }}>Budgets &amp; approval</h2>{s.settings.filter((r) => r.page === 'BABOOM' && ['Limits', 'Brain & routing'].includes(r.group)).map((r) => <SettingControl row={r} key={r.id} raw={u.advanced} />)}</Card></div>{s.routingAttempts && <Card style={{
        padding: 22,
        marginTop: 20
      }}><Heading title="Routing check" sub="The attempt order, availability and budget boundary." /><div className="spread" style={{
          marginBottom: 15
        }}><Chip c={s.routingStatus === 'Checked' ? A.ok : A.warn}>{s.routingStatus}</Chip>{s.routingStatus === 'Budget reached' && <Btn onClick={(event) => dispatch("routing.3", event)}>Review budget</Btn>}</div><Table rows={s.routingAttempts} columns={['provider', 'state', 'cost']} /></Card>}<window.UI.RefineComparison /><window.UI.ModelAvailability /><window.UI.HealthHistory /></main>;
  }
  function CapabilityRows({
    page
  }) {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction(),
      [query, setQuery] = React.useState(''),
      [limit, setLimit] = React.useState(10),
      all = s.capabilities.filter((c) => c.page === page),
      rows = all.filter((c) => !query || c.name.toLowerCase().includes(query.toLowerCase()));
    async function handleRoutingjsx4(c) {
      const n = await actionState.run(() => api.addNode(c.nodeKind));
      if (n) u.setSelectedNodeId(n.id);
      u.go('canvas');
    }
    async function handleRoutingjsx5(c) {
      if (c.route === 'canvas') {
        const n = await actionState.run(() => api.addNode(c.nodeKind));
        if (n) u.setSelectedNodeId(n.id);
      } else if (c.route === 'desktop') {
        await actionState.run(() => api.windowAction('hide'));
        return;
      }
      u.go(c.route);
    }
    function handleRoutingjsx6() {
      return setLimit((n) => n + 20);
    }
    const ACTIONS = {
      "routing.4": "handleRoutingjsx4",
      "routing.5": "handleRoutingjsx5",
      "routing.6": "handleRoutingjsx6"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleRoutingjsx4,
        handleRoutingjsx5,
        handleRoutingjsx6
      })(id, ...args);
    }
    return all.length ? <Card style={{
      padding: 20
    }}><div className="spread" style={{
        marginBottom: 16
      }}><h3>Capabilities <span className="muted">{all.length}</span></h3>{all.length > 10 && <input aria-label="Find capability" placeholder="Find a capability…" value={query} onChange={(e) => {
          setQuery(e.target.value);
          setLimit(10);
        }} />}</div>{rows.slice(0, limit).map((c) => <div key={c.id} data-capability={c.id}><div className="capability-row"><div className="flex"><span className="source-icon"><Icon name={c.route === 'social' ? 'workshop' : c.route === 'xray' ? 'eye' : c.route === 'access' ? 'user' : 'canvas'} size={16} /></span><span>{c.name}</span></div><div className="flex"><D.Toggle label={'Enable ' + c.name} checked={c.enabled !== false} onCheckedChange={(v) => actionState.run(() => api.setCapabilityEnabled(c.id, v))} /><Btn sm title={'Add ' + c.name + ' node'} aria-label={'Add ' + c.name + ' node'} onClick={(event) => dispatch("routing.4", c, event)}><Icon name="plus" size={16} /></Btn><Btn sm title={'Open ' + c.name} aria-label={'Open ' + c.name} onClick={(event) => dispatch("routing.5", c, event)}><Icon name="arrow" size={16} /></Btn></div></div>{u.advanced && <details><summary style={{
            padding: '8px 12px',
            fontSize: 11,
            color: A.inkSoft
          }}>Parameters · {api.getCapabilityParameters(c.id).length}</summary><window.UI.CapabilitySettings id={c.id} /></details>}</div>)}{rows.length > limit && <button className="listbutton muted" onClick={(event) => dispatch("routing.6", event)}>Show more capabilities · {rows.length - limit} remaining</button>}{!rows.length && <p className="muted">No matching capability.</p>}</Card> : null;
  }
  window.UI.Routing = Routing;
  window.UI.CapabilityRows = CapabilityRows;
})();
