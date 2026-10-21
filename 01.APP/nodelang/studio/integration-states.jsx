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
      [description, setDescription] = React.useState('');
    const action = window.UI.useAction();
    React.useEffect(() => { action.run(api.refreshMods); }, []);
    const status = <div aria-live="polite">{action.state === 'waiting' && <p role="status">Reading mod packages…</p>}{action.state === 'empty' && <p>No installed packages.</p>}{action.state === 'loaded' && <p>{s.mods.length} packages returned</p>}{action.state === 'error' && <div role="alert">{action.error}<Btn onClick={event => executeAction("projects.integration-states.RetryOwner", {action}, event)}>Retry</Btn></div>}</div>;
    return <div className="grid">{status}<div className="spread"><p className="muted">A local package adds nodes and settings. Review its manifest before enabling it.</p><Btn p onClick={event => executeAction("projects.integration-states.ChooseFolder.4", {api,u}, event)}>Choose folder</Btn></div>{making && <Card style={{
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
          const result = await u.act(() => api.importMcpTool(id, t.id));
          if (result) u.go('canvas');
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
