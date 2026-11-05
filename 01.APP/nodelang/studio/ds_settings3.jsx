// DSYS-083/084/085/086/087: Frame/Nav/P/R row grammar retained; each of
// the Book's 15 pages is now a live projection of the single settings schema.
(() => {
  const WIRE_DS_SETTINGS3_JSX_ACTIONS = {
  "settings.ds_settings3.RouterRefresh": "RouterRefresh",
  "settings.ds_settings3.RouterModel": "RouterModel",
  "settings.ds_settings3.PermissionsSave": "PermissionsSave",
  "settings.ds_settings3.PermissionsRefresh": "PermissionsRefresh",
  "settings.ds_settings3.PermissionsRemove": "PermissionsRemove",
  "settings.ds_settings3.PermissionsAdd": "PermissionsAdd",
  "settings.ds_settings3.ConnectionsAction0": "ConnectionsAction0",
  "settings.ds_settings3.ConnectionsAction1": "ConnectionsAction1",
  "settings.ds_settings3.ConnectionsAction2": "ConnectionsAction2",
  "settings.ds_settings3.WorkspaceRowsAction0": "WorkspaceRowsAction0",
  "settings.ds_settings3.WorkspaceRowsAction1": "WorkspaceRowsAction1",
  "settings.ds_settings3.WorkspaceRowsAction2": "WorkspaceRowsAction2",
  "settings.ds_settings3.WorkspaceRowsAction3": "WorkspaceRowsAction3",
  "settings.ds_settings3.WorkspaceRowsAction4": "WorkspaceRowsAction4",
  "settings.ds_settings3.AccountAction0": "AccountAction0",
  "settings.ds_settings3.AccountAction1": "AccountAction1",
  "settings.ds_settings3.AccountAction2": "AccountAction2",
  "settings.ds_settings3.StorageAction0": "StorageAction0",
  "settings.ds_settings3.StorageAction1": "StorageAction1",
  "settings.ds_settings3.StorageAction2": "StorageAction2",
  "settings.ds_settings3.SettingsAction0": "SettingsAction0",
  "settings.ds_settings3.SettingsAction1": "SettingsAction1",
  "settings.ds_settings3.SettingsAction2": "SettingsAction2",
  "settings.ds_settings3.SettingsAction3": "SettingsAction3",
  "settings.ds_settings3.SettingsAction4": "SettingsAction4",
  "settings.ds_settings3.SettingsAction5": "SettingsAction5",
  "settings.ds_settings3.SettingsAction6": "SettingsAction6",
  "settings.ds_settings3.SettingsAction7": "SettingsAction7",
  "settings.ds_settings3.SettingsAction8": "SettingsAction8",
  "settings.ds_settings3.SettingsAction9": "SettingsAction9",
  "settings.ds_settings3.SettingsAction10": "SettingsAction10",
  "settings.ds_settings3.SettingsAction11": "SettingsAction11",
  "settings.ds_settings3.SettingsAction12": "SettingsAction12",
  "settings.ds_settings3.SettingsAction13": "SettingsAction13",
  "settings.ds_settings3.SettingsAction14": "SettingsAction14",
  "settings.ds_settings3.SettingsAction15": "SettingsAction15",
  "settings.ds_settings3.SettingsAction16": "SettingsAction16",
  "settings.ds_settings3.SettingsAction17": "SettingsAction17",
  "settings.ds_settings3.SettingsAction18": "SettingsAction18",
  "settings.ds_settings3.SettingsAction19": "SettingsAction19",
  "settings.ds_settings3.SettingsAction20": "SettingsAction20",
  "settings.ds_settings3.SettingsAction21": "SettingsAction21",
  "settings.ds_settings3.SettingsAction22": "SettingsAction22",
  "settings.ds_settings3.SettingsAction23": "SettingsAction23",
  "settings.ds_settings3.SettingsAction24": "SettingsAction24",
  "settings.ds_settings3.SettingsAction25": "SettingsAction25"
};
  const {
    A,
    D,
    api,
    useData,
    useApp,
    Btn,
    Card,
    Heading,
    Chip,
    Empty,
    SettingControl,
    Providers
  } = window.UI;
  const doors = {
    'Account': 'account',
    'Connections': 'connections',
    'BABOOM': 'baboom',
    'Agents': 'colleagues',
    'Brain': 'brain',
    'System graph': 'system',
    'Workshop': 'workshop',
    'Library & Mods': 'library',
    'Automations': 'automations',
    'Hooks': 'hooks',
    'Dependencies': 'dependencies',
    'Privacy': 'privacy',
    'Appearance': 'appearance',
    'Updates & About': 'updates',
    'Advanced': 'system'
  };
  const sections = [
    {name:'Account', pages:['Account','Privacy'], tabs:['Profile','Privacy']},
    {name:'Connections', pages:['Connections'], tabs:['Connections']},
    {name:'Automation & Brain', pages:['BABOOM','Agents','Brain','Workshop','Automations'], tabs:['Preferences','Agents','Brain','Workshop','Automations']},
    {name:'Interface', pages:['Appearance'], tabs:['Preferences']},
    {name:'System', pages:['System graph','Library & Mods','Hooks','Dependencies','Updates & About','Advanced'], tabs:['Preferences','Library & Mods','Hooks','Dependencies','Updates & About','Advanced']}
  ];
  const sheetCategories = [
    {label:'Workspace', pages:[['Account','Account'],['Connections','Connections']]},
    {label:'Workflow', pages:[['Models','BABOOM'],['Hooks','Hooks']]},
    {label:'Application', pages:[['Appearance','Appearance'],['System','System graph']]}
  ];
  function requestGroups(requests, agents, providers) {
    const groups = new Map();
    for (const row of requests) {
      const identity = [...agents,...providers].find(agent => agent.id === row.agent || agent.name === row.agent || agent.sessions?.some(session=>session.root===row.agent));
      const agent = identity?.name || row.agent_name || (/^(BABOOM|Claude Code|Codex|OpenCode|Gemini|Goose)$/i.test(row.agent||'') ? row.agent : 'Unidentified agent');
      const key = JSON.stringify([identity?.id||row.agent||agent,row.model,row.provider]);
      if (!groups.has(key)) groups.set(key,{key,agent,model:row.model,provider:row.provider,count:0,tokens:0,measuredTokens:0,ms:0,measuredTime:0});
      const group = groups.get(key); group.count++;
      if (Number.isFinite(row.tokens)) {group.tokens+=row.tokens;group.measuredTokens++;}
      if (Number.isFinite(row.ms) && row.ms > 0) {group.ms+=row.ms;group.measuredTime++;}
    }
    return [...groups.values()];
  }
  function RouterSettings() {
    const s=useData(),u=useApp();
    const [model,setModel]=React.useState('');
    const [attempt,setAttempt]=React.useState(0),[load,setLoad]=React.useState({status:'waiting'});
    React.useEffect(()=>{
      let current=true;setLoad({status:'waiting'});
      api.refreshRouter().then(r=>{if(current){setModel(r.default_model);setLoad({status:r.requests.length?'loaded':'empty'});}},
        error=>{if(current)setLoad({status:'error',message:error.message});});
      return()=>{current=false;};
    },[attempt]);
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS,{
      RouterRefresh:()=>setAttempt(value=>value+1),
      RouterModel:value=>u.act(()=>api.setRouterSettings({default_model:value}))
    });
    if(load.status==='waiting')return <p role="status">Reading router settings…</p>;
    if(load.status==='error')return <div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.ds_settings3.RouterRefresh',event)}>Retry router</Btn></div>;
    const r=s.router;
    const models=[...new Set([r.default_model,...r.fallback_models,...r.models])];
    const groups=requestGroups(r.requests,s.agents||[],s.providers||[]);
    const total=groups.reduce((sum,row)=>({count:sum.count+row.count,tokens:sum.tokens+row.tokens,ms:sum.ms+row.ms,measuredTokens:sum.measuredTokens+row.measuredTokens,measuredTime:sum.measuredTime+row.measuredTime}),{count:0,tokens:0,ms:0,measuredTokens:0,measuredTime:0});
    const time=row=>row.measuredTime ? `${row.ms.toLocaleString()} ms${row.measuredTime<row.count ? ' (partial)' : ''}` : 'Not measured';
    const tokens=row=>row.measuredTokens ? `${row.tokens.toLocaleString()}${row.measuredTokens<row.count ? ' (partial)' : ''}` : 'Not reported';
    return <Card style={{padding:18}}><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><h2>Models &amp; request profiling</h2><label>Default free model<select aria-label="Default free model" value={model} onChange={e=>{setModel(e.target.value);runAction('settings.ds_settings3.RouterModel',e.target.value);}}>{models.map(m=><option key={m}>{m}</option>)}</select></label><p className="muted">Free first · no paid fallbacks · request metadata kept for 20 days</p><Btn sm onClick={event=>runAction('settings.ds_settings3.RouterRefresh',event)}>Refresh requests</Btn><div className="router-table-scroll"><table className="router-requests" aria-label="Router requests"><thead><tr><th scope="col">Agent</th><th scope="col">Model</th><th scope="col">Provider</th><th scope="col">Requests</th><th scope="col">Tokens</th><th scope="col">Measured time</th></tr></thead><tbody>{groups.map(row=><tr key={row.key}><th scope="row">{row.agent}</th><td>{row.model}</td><td>{row.provider}</td><td>{row.count}</td><td>{tokens(row)}</td><td>{time(row)}</td></tr>)}</tbody><tfoot><tr><th scope="row" colSpan={3}>Total</th><td>{total.count}</td><td>{tokens(total)}</td><td>{time(total)}</td></tr></tfoot></table></div>{load.status==='empty'&&<p>No model requests yet.</p>}{load.status==='loaded'&&<p>{r.requests.length} recent requests</p>}<h3>Live agent processes</h3><p>{r.live_agents.complete?'Observed processes':'Process observation incomplete'}</p>{r.live_agents.processes.map(p=><p key={p.pid}>{p.runtime} · PID {p.pid}</p>)}</Card>;
  }
  // Run mode and per-tool modes: parameters of the one decision every agent's hook runs.
  function Permissions() {
    const [p,setP]=React.useState(null),[tool,setTool]=React.useState('');
    const [attempt,setAttempt]=React.useState(0),[load,setLoad]=React.useState({status:'waiting'});
    React.useEffect(()=>{
      let current=true;setLoad({status:'waiting'});
      api.readPermissions().then(r=>{if(current){setP(r);setLoad({status:Object.keys(r.tools).length?'loaded':'empty'});}},
        error=>{if(current)setLoad({status:'error',message:error.message});});
      return()=>{current=false;};
    },[attempt]);
    const save=values=>api.setPermissions(values).then(r=>{setP(r);setLoad({status:Object.keys(r.tools).length?'loaded':'empty'});return r;});
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS,{
      PermissionsRefresh:()=>setAttempt(value=>value+1),
      PermissionsSave:values=>save(values),
      PermissionsRemove:name=>{const next={...p.tools};delete next[name];return save({tools:next});},
      PermissionsAdd:()=>save({tools:{...p.tools,[tool.trim()]:'Ask'}}).then(r=>{setTool('');return r;})
    });
    if(load.status==='waiting')return <p role="status">Reading permissions…</p>;
    if(load.status==='error')return <div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.ds_settings3.PermissionsRefresh',event)}>Retry permissions</Btn></div>;
    return <Card style={{padding:18}}><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><h2>Permissions</h2>
      <label>Run mode<select aria-label="Run mode" value={p.runMode} onChange={e=>runAction('settings.ds_settings3.PermissionsSave',{runMode:e.target.value})}>{p.runModes.map(m=><option key={m}>{m}</option>)}</select></label>
      <p className="muted">Routine work in your own folders never asks. Plan only: agents read and plan, nothing changes.</p>
      {load.status==='empty'&&<p>No tool modes yet: every tool follows the run mode.</p>}
      {load.status==='loaded'&&<table aria-label="Tool modes"><thead><tr><th>Tool</th><th>Mode</th><th /></tr></thead><tbody>{Object.entries(p.tools).map(([name,mode])=><tr key={name}><td>{name}</td><td><select aria-label={'Mode for '+name} value={mode} onChange={e=>runAction('settings.ds_settings3.PermissionsSave',{tools:{...p.tools,[name]:e.target.value}})}>{p.toolModes.map(m=><option key={m}>{m}</option>)}</select></td><td><Btn sm ghost aria-label={'Remove '+name} onClick={()=>runAction('settings.ds_settings3.PermissionsRemove',name)}>×</Btn></td></tr>)}</tbody></table>}
      <div className="flex"><input aria-label="Tool name or pattern" placeholder="Tool name, e.g. WebFetch or mcp__slack__*" value={tool} onChange={e=>setTool(e.target.value)} /><Btn sm disabled={!tool.trim()} onClick={event=>runAction('settings.ds_settings3.PermissionsAdd',event)}>Add tool</Btn></div></Card>;
  }
  function Connections() {
    const s = useData(),
      u = useApp();
    const [filter, setFilter] = React.useState('All');
    const [attempt, setAttempt] = React.useState(0), [load, setLoad] = React.useState({status:'waiting'});
    React.useEffect(()=>{
      let current=true;
      setLoad({status:'waiting'});
      Promise.allSettled([api.refreshSocialConnections,api.readHostAvailability,api.refreshSettingsControls].map(read=>read())).then(results=>{
        if(!current)return;
        const errors=results.filter(r=>r.status==='rejected').map(r=>r.reason.message);
        setLoad({status:errors.length?'error':'loaded',message:errors.join(' ')});
      });
      return()=>{current=false;};
    },[s.profile?.id,attempt]);
    const connections = [...(s.hosts||[]).map(c=>({...c,id:'host:'+c.id,host:true,connected:['connected','listening'].includes(c.state)})), ...s.connections,
      ...s.secrets.filter(c=>!s.connections.some(row=>row.vault_entry===c.vault_entry&&c.vault_entry)).map(c=>({...c,id:'credential:'+c.id,credential:true}))];
    const status=load.status==='loaded'&&!connections.length?'empty':load.status;
    const group = c => c.host || ['Revit', 'AutoCAD', 'Rhino', '3ds Max', 'Office'].includes(c.name) ? 'Programs' : ['Instagram', 'Facebook', 'WhatsApp Business', 'LinkedIn', 'X', 'TikTok', 'YouTube'].includes(c.name) ? 'Social' : 'Work apps';
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {ConnectionsAction0: (g, event) => (() => setFilter(g))(event),
ConnectionsAction1: (c, event) => (() => c.host ? u.go(c.connected?'watcher':'settings/Dependencies') : c.credential ? u.show('My secrets') : c.connected ? u.show('Connection', {
              id: c.id
            }) : u.show('Connect', {
              id: c.id
            }))(event),ConnectionsAction2:()=>setAttempt(value=>value+1)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div className="grid">{status==='waiting'&&<p role="status">Reading programs and accounts…</p>}{s.hostsProbing&&status!=='waiting'&&<p role="status">Checking programs…</p>}{s.hostError&&<p role="alert">{s.hostError}</p>}{status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.ds_settings3.ConnectionsAction2',event)}>Retry Connections</Btn></div>}<div className="flex">{['All', 'Programs', 'Social', 'Work apps'].map(g => <Btn sm ghost key={g} aria-pressed={filter === g} onClick={event => runAction('settings.ds_settings3.ConnectionsAction0', g, event)}>{g}</Btn>)}</div><Card>{status==='loaded'&&<div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 130px',
          padding: '14px 16px 8px',
          fontSize: 11,
          color: A.inkSoft
        }}><span>PROGRAM OR ACCOUNT</span><span /></div>}{connections.filter(c => filter === 'All' || group(c) === filter).map((c, i) => <div key={c.id} style={{
          display: 'grid',
          gridTemplateColumns: '1fr 130px',
          alignItems: 'center',
          padding: '8px 16px',
          borderTop: '1px solid ' + A.lineSoft
        }}><div className="flex"><span style={{
              width: 36,
              height: 36,
              borderRadius: 9,
              background: [A.blue, A.ok, A.purple, A.accent][i % 4],
              color: '#fff',
              display: 'grid',
              placeItems: 'center',
              fontWeight: 800
            }}>{c.name[0]}</span><div><h3>{c.name}</h3><span className="muted" style={{
                fontSize: 12
              }}>{c.host ? c.detail||c.state : c.credential ? 'Saved in Windows Credential Manager' : c.connected ? c.display_name||'Connected to your account' : c.blocker||'Connect this account to use it'}{c.checked ? ' · checked' : ''}</span></div></div><div style={{
            justifySelf: 'end'
          }}><Btn sm onClick={event => runAction('settings.ds_settings3.ConnectionsAction1', c, event)}>{c.credential ? 'Details' : c.connected ? 'Open' : c.host?'Manage':'Connect'}</Btn></div></div>)}</Card>{status==='empty'&&<Empty>Connect an account or start a program with its ArchHub bridge, then refresh Connections.</Empty>}</div></>;
  }
  function WorkspaceRows() {
    const s = useData(),
      u = useApp();
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {WorkspaceRowsAction0: (event) => (() => u.pickWorkspace())(event),
WorkspaceRowsAction1: (w, event) => (async () => {
            await u.act(() => api.selectWorkspace(w.id));
            u.go('canvas');
          })(event),
WorkspaceRowsAction2: (w, event) => (() => u.show('Workspace rules', {
            id: w.id
          }))(event),
WorkspaceRowsAction3: (w, event) => (() => u.confirm('Remove this workspace from the list?', () => api.removeWorkspace(w.id)))(event),
WorkspaceRowsAction4: (event) => (() => u.act(api.listWorkspaces))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><Card><div className="spread" style={{
        padding: 16
      }}><div><h2>Workspaces</h2><small className="muted">Choose the folders ArchHub and your agents work in.</small></div><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction0', event)}>Add workspace</Btn></div><div className="row muted" role={s.workspaceHealth?.state === 'error' ? 'alert' : 'status'}>{s.workspaceHealth?.message || 'Reading workspaces…'}{s.workspaceHealth?.state === 'error' && <Btn sm ghost onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction4', event)}>Retry</Btn>}</div>{s.workspaceHealth?.recovery && <div className="row muted">{s.workspaceHealth.recovery.message}</div>}{s.workspaces.map(w => <div key={w.id} className="spread row"><D.Toggle label={'Use ' + w.name} checked={(s.graph.workspaceIds || []).includes(w.id)} onCheckedChange={v => u.act(() => api.setGraphWorkspaces(v ? [...new Set([...(s.graph.workspaceIds || []), w.id])] : (s.graph.workspaceIds || []).filter(id => id !== w.id)))} /><div className="fill"><h3>{w.name}</h3><span className="muted" style={{
            fontSize: 12
          }}>{w.folder} · {w.available === false ? 'Folder unavailable' : (s.workspaceHealth?.state === 'ready' || (s.workspaceHealth?.state === 'idle' && w.builtIn)) ? 'Ready' : 'Checking…'}</span></div><div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction1', w, event)}>Open</Btn><Btn sm ghost aria-label={'Privacy ' + w.name} title="Workspace privacy" onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction2', w, event)}><window.AHIcon name="shield" size={16} /></Btn>{!w.builtIn && w.removable !== false && <Btn sm ghost onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction3', w, event)}>Remove</Btn>}</div></div>)}{!s.workspaces.some(w => !w.builtIn) && <Empty>No other workspaces yet.</Empty>}</Card></>;
  }
  function Account() {
    const s = useData(),
      u = useApp();
    const initials = s.profile.name.split(' ').map(n => n[0]).slice(0, 2).join('');
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {AccountAction0: (event) => (() => u.act(api.syncAccount))(event),
AccountAction1: (event) => (() => s.profile.signedIn ? u.act(() => api.signIn(false)) : u.show('Sign in'))(event),
AccountAction2: (label, event) => (() => u.show(label))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div className="account-overview">
      <section className="account-identity" aria-label="Your identity">
        <div className="account-avatar">{initials}</div>
        <div className="fill"><div className="flex"><h2>{s.profile.name}</h2><Chip c={s.profile.signedIn ? A.ok : A.inkSoft}>{s.profile.signedIn ? 'Signed in' : 'Signed out'}</Chip></div><p className="muted">{s.profile.email}</p><div className="account-sync"><span className="status-dot" /><span>{s.sync}</span><Btn sm ghost onClick={event => runAction('settings.ds_settings3.AccountAction0', event)}>Sync</Btn></div></div>
        <Btn sm ghost onClick={event => runAction('settings.ds_settings3.AccountAction1', event)}>{s.profile.signedIn ? 'Sign out' : 'Sign in with your browser'}</Btn>
      </section>
      <div className="account-shortcuts">{[['My profile','user','How you appear to your team'],['My secrets','shield','Your protected connections'],['My files','docs',s.files.length+' project files']].map(([label, icon, detail]) => <button className="account-shortcut" key={label} aria-label={label} onClick={event => runAction('settings.ds_settings3.AccountAction2', label, event)}><span className="account-shortcut-icon"><window.AHIcon name={icon} size={20} /></span><span className="fill"><b>{label}</b><small>{detail}</small></span><window.AHIcon name="arrow" size={15} /></button>)}</div>
      <window.UI.AccountIdentity />
      <WorkspaceRows />
    </div></>;
  }
  function Storage() {
    const s = useData(),
      u = useApp();
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {StorageAction0: (event) => (() => u.act(api.archiveActivity))(event),
StorageAction1: (event) => (() => u.act(api.backUpNow))(event),
StorageAction2: (b, event) => (() => u.confirm('Prepare this verified backup for recovery?', () => api.rollBack(b.id)))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><Card style={{
      padding: 16,
      display: 'grid',
      gap: 12
    }}><h2>Where your work lives</h2><p className="muted">Workflows and settings stay with your account. Client work stays on this machine.</p><div className="flex">{api.supportsAction?.('archiveActivity') !== false && <Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction0', event)}>Archive old activity</Btn>}<Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction1', event)}>Back up now</Btn></div>{s.backups.map(b => <div className="spread" key={b.id}><span>{b.name}</span><Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction2', b, event)}>Roll back</Btn></div>)}</Card></>;
  }
  function AdvancedSettings({
    page = 'Account',
    full = false
  }) {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState(''),
      [changed, setChanged] = React.useState(false);
    const actual = s.pages.includes(page) ? page : sections.find(section=>section.name===page)?.pages[0] || 'Account';
    const section = sections.find(section=>section.pages.includes(actual));
    const matched = [...s.settings, ...s.capabilities.map(c => ({
      id: c.id,
      page: c.page,
      label: c.name,
      group: 'Capabilities',
      capability: true
    }))].filter(r => `${r.label} ${r.group} ${r.page}`.toLowerCase().includes(query.toLowerCase()));
    const visible = s.settings.filter(r => r.page === actual && (!r.advanced || u.advanced || actual === 'Advanced') && (!changed || JSON.stringify(r.value) !== JSON.stringify(r.default)));
    const groups = [...new Set(visible.map(r => r.group))];
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {SettingsAction0: (r, event) => (() => {
            setQuery('');
            if (r.capability) {
              u.show('Capability', {
                id: r.id
              });
              return;
            }
            u.go('settings/' + r.page);
            requestAnimationFrame(() => document.querySelector(`[data-setting="${r.id}"]`)?.scrollIntoView({
              block: 'center'
            }));
          })(event),
SettingsAction1: (p, event) => (() => u.go('settings/' + p))(event),
SettingsAction2: (event) => (() => u.go(doors[actual]))(event),
SettingsAction3: (event) => (() => u.act(() => api.resetPage(actual)))(event),
SettingsAction4: (event) => (() => u.go('colleagues'))(event),
SettingsAction5: (event) => (() => u.go('settings/BABOOM'))(event),
SettingsAction6: (event) => (() => u.go('community'))(event),
SettingsAction7: (event) => (() => u.go('dependencies'))(event),
SettingsAction8: (event) => (() => u.show('Update'))(event),
SettingsAction9: (event) => (() => u.act(api.acknowledgeUpdate))(event),
SettingsAction10: (event) => (() => u.act(api.checkForUpdates))(event),
SettingsAction11: (event) => (() => u.show('What’s new'))(event),
SettingsAction12: (event) => (() => u.go('first-run'))(event),
SettingsAction13: (event) => (() => u.go('docs'))(event),
SettingsAction14: (event) => (() => u.go('feedback'))(event),
SettingsAction15: (event) => (() => u.download('Brain'))(event),
SettingsAction16: (event) => (() => u.act(api.syncAccount))(event),
SettingsAction17: (event) => (() => u.go('library'))(event),
SettingsAction18: (event) => (() => u.go('skills'))(event),
SettingsAction19: (event) => (() => u.go('home'))(event),
SettingsAction20: (event) => (() => u.show('Install mod'))(event),
SettingsAction21: (event) => (() => u.go('receipts'))(event),
SettingsAction22: (event) => (() => u.download('Receipts'))(event),
SettingsAction23: (event) => (() => u.go('receipts'))(event),
SettingsAction24: (event) => (() => u.go('docs'))(event),
SettingsAction25: () => u.act(api.listAgentsWorking)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div data-screen={'settings/' + actual} style={{
      display: 'grid',
      gridTemplateColumns: full ? 'minmax(0,1fr)' : 'var(--layout-settings-sidebar-width) minmax(0,1fr)',
      minHeight: 0
    }}>
  {!full && <aside className="pane settings-side" style={{
        padding: '18px 12px'
      }}><h1 style={{
          fontSize: 20,
          padding: '0 10px 12px'
        }}>Settings</h1><input aria-label="Find a setting" placeholder="⌕ Find a setting" value={query} onChange={e => setQuery(e.target.value)} style={{
          width: '100%',
          height: 34
        }} /><div className="spread" style={{
          padding: '12px 6px 8px',
          fontSize: 13,
          color: A.inkSoft
        }}><span>Show advanced</span><D.Toggle variant="settings" label="Show advanced" checked={u.advanced} onCheckedChange={u.setAdvanced} /></div>
   {query ? <div className="grid">{matched.map(r => <button key={r.id} className="listbutton" onClick={event => runAction('settings.ds_settings3.SettingsAction0', r, event)}><b>{r.label}</b><p className="muted" style={{
              fontSize: 11
            }}>{r.page} › {r.group}</p></button>)}{!matched.length && <Empty>No matching setting.</Empty>}</div> : sections.map(group => <button className="listbutton flex settings-section" key={group.name} aria-selected={section===group} onClick={event => runAction('settings.ds_settings3.SettingsAction1', group.pages[0], event)}>{group.name}</button>)}
  <div className="settings-subpages">{section.pages.map((p,i)=><button className="listbutton" key={p} aria-selected={actual===p} onClick={event=>runAction('settings.ds_settings3.SettingsAction1',p,event)}>{p==='System graph'?'Live wiring':p}</button>)}</div>
  </aside>}
  <main className={'page penpot-settings' + (actual === 'Account' ? ' account-settings' : '')} style={{
        padding: '22px 32px'
      }}><nav className="settings-tabs" aria-label={section.name}>{section.pages.map((p,i)=><button className="tab-button" aria-current={actual===p?'page':undefined} key={p} onClick={event=>runAction('settings.ds_settings3.SettingsAction1',p,event)}>{section.tabs[i]}</button>)}{actual==='Account'&&<><button className="tab-button" onClick={event=>runAction('settings.ds_settings3.SettingsAction2',event)}>Plan &amp; access</button><button className="tab-button" onClick={event=>runAction('settings.ds_settings3.SettingsAction12',event)}>First run</button></>}{actual==='Appearance'&&<button className="tab-button" onClick={()=>u.go('interface')}>Interface studio</button>}</nav><div className="settings-title"><span className="settings-page-header-icon"><window.AHIcon name={["user", "link", "voice", "users", "brain", "canvas", "workshop", "library", "clock", "shield", "code", "shield", "palette", "update", "settings"][s.pages.indexOf(actual)]} size={21} /></span><Heading title={actual==='System graph'?'Live wiring':actual} sub={{
          Account: 'Your identity, workspaces and project files.',
          Connections: 'The programs and accounts your agents can work with.',
          BABOOM: 'Your companion’s providers, voice, presence and boundaries.',
          Agents: 'How your agents choose, finish and hand over work.',
          Brain: 'What your agents remember, and how they learn.',
          Appearance: 'Make ArchHub comfortable for the way you work.',
          Advanced: 'Fine control over loading, performance and connection limits.',
          Privacy: 'Control what stays local and what can leave your workspace.',
          'Updates & About': 'One update, with your work kept intact.'
        }[actual] || 'Your preferences for ' + actual.toLowerCase() + '.'}><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction2', event)}>{actual === 'System graph' ? 'Open workflow' : actual === 'BABOOM' ? 'Open BABOOM' : 'Show as node'}</Btn><Btn sm ghost onClick={event => runAction('settings.ds_settings3.SettingsAction3', event)}>Reset preferences</Btn></Heading></div>
   {u.advanced && <div className="flex settings-scope" style={{
          marginBottom: 14
        }}><label className="flex muted">Scope<select aria-label="Settings scope" value={s.settingsScope} onChange={e => u.act(() => api.setSettingsScope(e.target.value))}><option>User</option><option>Workspace</option></select></label><span className="fill" /><span className="muted">{s.settingsScope === 'Workspace' ? s.workspaces.find(w => w.id === s.activeWorkspace)?.name : 'Your account'}</span></div>}<div className="settings-health"><span className="status-dot" /><span>{actual === 'Connections' ? (s.connections.filter(c => c.connected).length+(s.hosts||[]).filter(c=>['connected','listening'].includes(c.state)).length) + ' accounts and programs connected' : actual === 'BABOOM' ? s.providers.filter(p => p.enabled && p.signedIn).length + ' providers ready' : actual === 'Agents' ? s.agentHealth||'Checking running agents…' : actual === 'Account' ? s.profile.firm + ' · ' + s.workspaces.length + ' workspace' : actual === 'Updates & About' ? s.update.available ? 'An update is ready' : s.update.detail || 'Update status unavailable' : 'Preferences'}</span></div><div className="flex settings-filter" style={{
          marginBottom: 14
        }}><D.Toggle label="Changed only" checked={changed} onCheckedChange={setChanged} /><span className="muted" style={{
            fontSize: 12
          }}>Changed only</span>{full && <><span className="fill" /><span>Show advanced</span><D.Toggle label="Show advanced" checked={u.advanced} onCheckedChange={u.setAdvanced} /></>}</div>
   <div className="grid">
    {actual === 'System graph' && <window.UI.SystemGraph />}
    {actual === 'Account' && <Account />}<window.UI.CapabilityRows page={actual} />
    {actual === 'Connections' && <Connections />}
    {actual === 'Agents' && <RouterSettings />}
    {actual === 'Hooks' && <Permissions />}
    {actual === 'BABOOM' && <Providers />}{actual === 'Agents' && <><Card style={{
            padding: 18
          }}><div className="spread"><h2>Agents at work</h2><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction4', event)}>Open</Btn></div><p role="status">{s.agentSummary||'Checking running agents…'}</p><p className="muted">{s.agentHealth||'Checking running agents…'}</p><Btn sm onClick={event=>runAction('settings.ds_settings3.SettingsAction25',event)}>{s.agentSummary==='Agent status is incomplete.'?'Check again':'Refresh'}</Btn>{(s.agents||[]).map(p => <div className="spread row" key={p.id}><span className="flex"><window.UI.Av id={p.id} size={24} /><span><b>{p.name}</b><small className="muted" style={{display:'block'}}>{p.title} · {p.model}</small><small style={{display:'block'}}>{p.task}</small>{p.detail&&<small className="muted" style={{display:'block'}}>{p.detail}</small>}</span></span><Chip c={p.presence === 'working' ? A.ok : p.presence === 'unknown' ? A.warn : A.inkSoft}>{p.status_text||'Status unknown'}</Chip></div>)}<button className="listbutton flex" onClick={event => runAction('settings.ds_settings3.SettingsAction5', event)}>Manage providers<window.AHIcon name="arrow" size={15} /></button></Card><Providers /></>}
    {actual === 'Brain' && <><window.UI.MemoryRules /><Btn onClick={event => runAction('settings.ds_settings3.SettingsAction6', event)}>Community</Btn></>}
    {actual === 'Automations' && <window.UI.Automations embedded />}
    {actual === 'Dependencies' && <Card style={{
            padding: 22
          }}><div className="spread"><div><h2>Managed tools</h2><p className="muted">Versions, health, resources and the features that use each tool.</p></div><Btn p onClick={event => runAction('settings.ds_settings3.SettingsAction7', event)}>Open dependencies</Btn></div><div className="dependency-mini">{s.dependencies.slice(0, 5).map(d => <div className="row spread" key={d.id}><span>{d.name}</span><Chip c={d.state === 'Ready' ? A.ok : A.warn}>{d.state}</Chip></div>)}</div></Card>}
{actual === 'Updates & About' && <Card style={{
            padding: 16
          }}><div className="spread"><div><h2>ArchHub</h2><p className="muted">{s.update.installed || 'Installed build unavailable'}</p></div>{s.update.available ? <Btn p onClick={event => runAction('settings.ds_settings3.SettingsAction8', event)}>Update</Btn> : <Chip c={s.update.state === 'idle' ? A.ok : A.warn}>{s.update.state === 'idle' ? s.update.detail : s.update.detail || 'Update status unavailable'}</Chip>}</div>
          {s.update.restartRefusal && <p role="alert">{s.update.restartRefusal}</p>}
          {s.update.updatedTo && <div role="status" className="spread"><span>Updated {s.update.updatedFrom || 'ArchHub'} → {s.update.updatedTo}</span><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction9', event)}>Dismiss update confirmation</Btn></div>}
          <div className="flex" style={{
              marginTop: 12
            }}><Btn sm disabled={s.update.state === 'checking' || s.update.state === 'restarting'} onClick={event => runAction('settings.ds_settings3.SettingsAction10', event)}>Check for updates</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction11', event)}>What’s new</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction12', event)}>First run</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction13', event)}>Docs</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction14', event)}>Feedback</Btn></div></Card>}
    <div className="settings-grid">{groups.map(group => <Card key={group} style={{
              padding: '10px 14px 8px'
            }}><h3 style={{
                marginBottom: 8,
                fontSize: 14.5
              }}>{group}</h3>{visible.filter(r => r.group === group).map(r => <SettingControl key={r.id} row={r} raw={u.advanced || actual === 'Advanced'} />)}</Card>)}</div>
    {actual === 'Account' && <Storage />}
    {actual === 'Brain' && <div className="flex"><Chip c={A.ok}>{s.brain.length} facts</Chip><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction15', event)}>Export</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction16', event)}>Sync to cloud</Btn></div>}
    {actual === 'Library & Mods' && <window.UI.HostSkills />}{actual === 'Library & Mods' && <div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction17', event)}>Open Library</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction18', event)}>Open Skills</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction19', event)}>Open Templates</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction20', event)}>Install from folder</Btn></div>}
    {actual === 'BABOOM' && <div className="spread"><h3>Receipts · {s.receipts.length} actions</h3><div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction21', event)}>Open receipts</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction22', event)}>Export</Btn></div></div>}
    {actual === 'Advanced' && <div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction23', event)}>Open log</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction24', event)}>Docs &amp; website</Btn></div>}
   </div>
  </main>
 </div></>;
  }
  const SHEET_ACTIONS = {'settings.sheet.Refresh':'Refresh'};
  function executeAction(...args) {return window.executeAction(...args);}
  function SheetField({label,value,children,onClick}) {
    return <div className="sheet-field"><span>{label}</span><div>{children || (onClick ? <button className="button-reset" onClick={event=>executeAction('projects.controls.activate',{handler:onClick},event)}>{value}</button> : <span>{value ?? 'Not reported'}</span>)}</div></div>;
  }
  function SheetPreference({label,match}) {
    const s=useData(),u=useApp(),row=s.settings.find(match || (r=>r.label===label));
    return <SheetField label={label}>{row ? <SettingControl row={row} /> : <button className="button-reset muted" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.go('settings/Advanced')},event)}>Not available</button>}</SheetField>;
  }
  function Settings({page='Account',full=false}) {
    const s=useData(),u=useApp();
    const group=sections.find(section=>section.name===page || section.pages.includes(page)) || sections[0];
    const deep=page==='Advanced' || (page!=='Hooks' && group.pages.includes(page) && page!==group.pages[0]);
    const [advancedOpen,setAdvancedOpen]=React.useState(deep);
    const [query,setQuery]=React.useState('');
    const [hostId,setHostId]=React.useState('');
    const [router,setRouter]=React.useState(null),[attempt,setAttempt]=React.useState(0),[load,setLoad]=React.useState({status:'waiting'});
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(SHEET_ACTIONS,{Refresh:()=>setAttempt(value=>value+1)});
    React.useEffect(()=>{let current=true;setLoad({status:'waiting'});Promise.allSettled([api.refreshRouter(),api.readHostAvailability(),api.listAgentsWorking(),api.refreshSettingsControls()]).then(results=>{if(!current)return;const model=results[0],errors=results.filter(result=>result.status==='rejected').map(result=>result.reason.message);if(model.status==='fulfilled')setRouter(model.value);setLoad(errors.length?{status:'error',message:errors.join(' ')}:{status:results[2].value?.length||results[1].value?.length?'loaded':'empty'});});return()=>{current=false;};},[attempt]);
    const go=route=>u.go(route),act=fn=>u.act(fn),connected=(s.hosts||[]).filter(host=>['connected','listening'].includes(host.state));
    const [reveal,setReveal]=React.useState('');
    const needle=query.trim().toLowerCase();
    const settingValue=value=>value==null?'':typeof value==='object'?JSON.stringify(value):String(value);
    const settingText=row=>`${row.label||''} ${row.group||''} ${row.page||''} ${settingValue(row.value)}`.toLowerCase();
    const matched=needle?[...s.settings.filter(row=>settingText(row).includes(needle)),...[{id:'profile-name',label:'Name',page:'Account',value:s.profile.name||'Add a name',open:()=>u.show('My profile')},{id:'profile-email',label:'Email',page:'Account',value:s.profile.email||'Add an email',open:()=>u.show('My profile')}].filter(row=>settingText(row).includes(needle))]:[];
    const revealSetting=row=>{
      if(row.open){row.open();return;}
      setReveal(row.id);
      setAdvancedOpen(true);
      const home=sections.find(section=>section.pages.includes(row.page));
      if(home&&home!==group)go('settings/'+home.pages[0]);
      setQuery('');
    };
    React.useEffect(()=>{
      if(!reveal)return undefined;
      const node=document.querySelector(`[data-setting="${reveal}"]`);
      if(!node)return undefined;
      if(typeof node.scrollIntoView==='function')node.scrollIntoView({block:'center'});
      setReveal('');
      return undefined;
    },[reveal,advancedOpen,page,query]);
    const rawRows=s.settings.filter(row=>group.pages.includes(row.page));
    const hosts=s.hosts||[];
    const chosen=hosts.find(host=>host.id===hostId)||hosts[0];
    const status=(s.agents||[]).map(agent=>`${agent.session_count ?? agent.sessions?.length ?? 0} ${agent.name} sessions ${agent.presence||'unknown'}`).join(' · ');
    const preference=(label,match=undefined)=><SheetPreference key={label} label={label} match={match} />;
    const currentCategory=page==='Hooks'?page:group.pages[0];
    return <div data-screen={'settings/'+currentCategory} data-settings-full={full?'1':'0'} className="settings-sheet-stage"><section className="settings-sheet" aria-label="Settings"><header><h1>Settings</h1><input className="sheet-search" aria-label="Search settings" placeholder="Search settings…" value={query} onChange={event=>setQuery(event.target.value)} /><button type="button" className="sheet-action" onClick={event=>executeAction('projects.controls.activate',{handler:()=>go(u.settingsOrigin||'home')},event)}>{u.settingsOrigin==='task-file'?'Back to task':u.settingsOrigin==='canvas'?'Back to Canvas':'Done'}</button></header><div className="sheet-layout"><nav className="sheet-tabs" aria-label="Settings categories">{sheetCategories.map(category=><div className="sheet-category" key={category.label}><span>{category.label}</span>{category.pages.map(([label,target])=><button type="button" className="settings-section" aria-current={currentCategory===target?'page':undefined} key={target} onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/'+target)},event)}>{label}</button>)}</div>)}</nav><div className="sheet-content">
      <window.UI.RegisteredActionStatus state={actionState} retry={retryAction}/>{load.status==='waiting'&&<p role="status">Reading settings…</p>}{load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.sheet.Refresh',event)}>Retry settings</Btn></div>}{load.status==='empty'&&<span className="visually-hidden">No connected programs or agent sessions reported.</span>}{load.status==='loaded'&&<span className="visually-hidden">Settings loaded.</span>}
      {needle&&<div className="sheet-results" role="listbox" aria-label="Settings results">{matched.map(row=><button type="button" role="option" className="sheet-result" key={row.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>revealSetting(row)},event)}><b>{row.label}</b><span>{settingValue(row.value)}</span>{row.open?null:<small>Advanced</small>}</button>)}{!matched.length&&<p>No matching setting.</p>}</div>}
      <div className="sheet-columns" hidden={!!needle}>
      {group.name==='Account'&&<><section><h2>Your identity</h2><div className="sheet-fields"><SheetField label="Name" value={s.profile.name||'Add a name'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('My profile')},event)} /><SheetField label="Email" value={s.profile.email||'Add an email'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('My profile')},event)} /></div><h2 className="sheet-section-gap">Files &amp; workspaces</h2><SheetField label="Workspace folder" value={s.workspaces.find(w=>w.id===s.activeWorkspace)?.path||'Choose a folder'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>act(api.addWorkspace)},event)} /><p>Workflow files travel with you. Local paths stay editable.</p></section><section><h2>Privacy</h2><div className="sheet-fields">{preference('Review before sharing')}{preference('Ask before meeting transcription')}</div><p className="sheet-section-gap">Secrets stay in protected connections, never in .archhub files.</p><button type="button" className="sheet-action secondary" onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Connections')},event)}>Manage protected connections</button></section></>}
      {group.name==='Connections'&&<><section><h2>Programs</h2><p>Live program status, document and current agent use.</p><div className="sheet-programs">{hosts.map(host=><button type="button" className="sheet-program" key={host.id} aria-pressed={chosen?.id===host.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setHostId(host.id)},event)}><span className="status-dot" style={{background:host.state==='connected'?A.ok:A.inkSoft}}/><div><b>{host.name}</b><p>Document · {host.document||host.document_name||host.detail||'No document reported'}</p><p>Agents using it · {host.agents?.map(a=>a.name||a).join(', ')||'not reported'}</p></div><span style={{color:host.state==='connected'?A.ok:A.inkSoft}}>{host.state}</span></button>)}{!hosts.length&&<p>No running programs reported.</p>}</div><div className="sheet-program-access"><h2>Connection details</h2><p>Inspect this connection here.</p>{chosen?<div className="sheet-field"><span>{chosen.name}</span><div>{chosen.state||'not reported'} · {chosen.document||chosen.document_name||chosen.detail||'No document reported'}</div></div>:<p>No connection selected.</p>}</div></section><section><h2>Agent sessions</h2><div className="sheet-agents">{(s.agents||[]).map(agent=><div key={agent.id}><b>{agent.name}</b><span style={{color:agent.presence==='working'?A.ok:A.inkSoft}}>{agent.session_count??agent.sessions?.length??0} {agent.presence||'unknown'}</span></div>)}{!s.agents?.length&&<p>No agent sessions reported.</p>}</div><p className="sheet-divider">Agents reach programs directly. No sign-in queue.</p>{s.connections?.length>0&&<button type="button" className="button-reset" onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAdvancedOpen(true)},event)}>Manage connected accounts</button>}</section></>}
      {group.name==='Automation & Brain'&&<><section><h2>Models</h2><p>Free models first. Changes apply on the next message.</p><div className="sheet-fields sheet-models"><SheetField label="Default model">{router?<select aria-label="Default model" value={router.default_model} onChange={event=>act(()=>api.setRouterSettings({default_model:event.target.value})).then(result=>{if(result)setRouter(result);})}>{[...new Set([router.default_model,...router.models,...router.fallback_models])].map(model=><option key={model}>{model}</option>)}</select>:<span role="status">{load.status==='error'?load.message:'Reading models…'}</span>}</SheetField><SheetField label="Fallback order" value={router?.fallback_models.join(' → ')} /><SheetField label="Prefer free models">{router?<div className="spread"><span>{router.free_first?'On':'Off'}</span><D.Toggle label="Prefer free models" checked={router.free_first} onCheckedChange={value=>act(()=>api.setRouterSettings({free_first:value})).then(result=>{if(result)setRouter(result);})}/></div>:<span>Reading…</span>}</SheetField></div><p className="sheet-session-summary">{status||'No agent sessions reported.'}</p></section><section><h2>Follow through</h2><div className="sheet-fields">{preference('Finish and report')}{preference('Only notify when action is needed')}</div><h2 className="sheet-knowledge">Knowledge</h2><SheetField label="Conversation retention" value={s.settings.find(row=>row.label==='Conversation retention')?.value} /><p>Digest conversations into knowledge, then remove them.</p></section></>}
      {group.name==='Interface'&&<><section><h2>Theme &amp; colour</h2><p>Keep the same language across your workspace.</p><div className="sheet-themes">{['Dark','Light','System'].map(theme=><button key={theme} className={'sheet-theme theme-'+theme.toLowerCase()} aria-label={theme+' theme'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{const row=s.settings.find(r=>r.page==='Appearance'&&r.label==='Theme');row?act(()=>api.setSetting(row.id,theme)):setAdvancedOpen(true);}},event)}><span/><b>{theme}</b></button>)}</div>{preference('Accent colour')}</section><section><h2>Reading &amp; motion</h2><div className="sheet-fields">{preference('Text scale')}{preference('Reduce motion')}{preference('High contrast')}</div></section><section className="sheet-canvas-defaults"><h2>Canvas defaults</h2><div>{preference('Show grid',r=>r.page==='Appearance'&&r.label==='Canvas grid')}{preference('Default zoom',r=>r.page==='Appearance'&&r.label===(window.ARCHHUB_BOOT?.nograph?'Default zoom':'Zoom percentage'))}</div></section></>}
      {page==='Hooks'&&<section className='sheet-canvas-defaults'><Permissions /></section>}
      {group.name==='System'&&page!=='Hooks'&&<><section><h2>Live wiring</h2><p>Drawn from the running app. These are not stored records.</p><div className="sheet-wiring"><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Agents')},event)}><b>Agents</b><small>{status||'No sessions reported'}</small></button><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Agents')},event)}><b>Router</b><small>{router?.default_model||'Reading router…'}</small></button><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('workshop')},event)}><b>Workshop</b><small>Session Link</small></button><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Connections')},event)}><b>Programs</b><small>{connected.map(host=>host.name).join(' · ')||'No programs connected'}</small></button></div>{preference('Keep running in tray')}</section><section><h2>Tools &amp; diagnostics</h2><div className="sheet-tools">{[['Dependencies','dependencies'],['Hooks','settings/Hooks'],['Updates','settings/Updates & About'],['Diagnostics','receipts']].map(([label,route])=><Btn key={label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>go(route)},event)}>{label}</Btn>)}</div><p className="sheet-diagnostics">Loading, failed and stopped states stay local to the affected tool.</p></section></>}
      </div></div></div><footer className="sheet-footer"><span>Everyday controls first. Detailed parameters remain available.</span><button type="button" className="sheet-action" aria-expanded={advancedOpen} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAdvancedOpen(open=>!open)},event)}>Advanced</button></footer></section>{advancedOpen&&!needle&&<section className="sheet-advanced" aria-label={'Advanced · '+group.name}><header><h2>Advanced · {group.name}</h2><button type="button" className="sheet-action" onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAdvancedOpen(false)},event)}>Done</button></header><div className="sheet-advanced-rows">{rawRows.map(row=><SettingControl key={row.id} row={row} raw />)}{!rawRows.length&&<p>No raw parameters for this section.</p>}</div>{group.name==='Automation & Brain'&&<RouterSettings />}{page==='Brain'&&<window.UI.MemoryRules />}{page==='Automations'&&<window.UI.Automations embedded />}{page==='Library & Mods'&&<window.UI.HostSkills />}{page==='BABOOM'&&<Providers />}{page==='System graph'&&<window.UI.SystemGraph />}</section>}</div>;
  }
  window.UI.Settings = Settings;
  window.UI.requestGroups = requestGroups;
  window.UI.Account = Account;
  window.UI.Connections = Connections;
  window.UI.WorkspaceRows = WorkspaceRows;
  window.UI.Storage = Storage;
  window.UI.settingsDoors = doors;
})();
