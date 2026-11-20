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
  "settings.ds_settings3.NewProject": "NewProject",
  "settings.ds_settings3.CreateProject": "CreateProject",
  "settings.ds_settings3.CancelProject": "CancelProject",
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
  "settings.ds_settings3.UpdatesAutoInstall": "UpdatesAutoInstall",
  "settings.ds_settings3.UpdatesSettingRetry": "UpdatesSettingRetry",
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
  const sheetAreas = [
    {label:'Account', target:'Account', pages:['Account','Brain'], icon:'user', description:'Your account, identity, memory and sync'},
    {label:'Look', target:'Appearance', pages:['Appearance'], icon:'palette', description:'How ArchHub looks and how panels sit'},
    {label:'Projects', target:'Projects', pages:['Projects'], icon:'folder', description:'Units, standards, templates and folders'},
    {label:'Agents', target:'Agents', pages:['Agents','BABOOM','Hooks'], icon:'users', description:'Who works for you, models and permissions'},
    {label:'Connections', target:'Connections', pages:['Connections'], icon:'link', description:'Accounts, programs and tool servers'},
    {label:'You', target:'Privacy', pages:['Privacy','Advanced'], icon:'folder', description:'This PC: workspaces, files and privacy'},
    {label:'Workshop', target:'Workshop', pages:['Workshop'], icon:'workshop', description:'Messages, approvals and conversation rules'},
    {label:'Library & Mods', target:'Library & Mods', pages:['Library & Mods'], icon:'library', description:'Node types, mods and available tools'},
    {label:'Automations', target:'Automations', pages:['Automations'], icon:'clock', description:'Everything that runs by itself'},
    {label:'System', target:'System graph', pages:['System graph','Dependencies'], icon:'settings', description:'Live wiring, programs and dependencies'},
    {label:'Updates & About', target:'Updates & About', pages:['Updates & About'], icon:'update', description:'Version, updates and recovery'}
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
      api.refreshRouter(attempt>0).then(r=>{if(current){setModel(r.default_model);setLoad({status:r.requests.length?'loaded':'empty'});}},
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
    return <Card style={{padding:18}}><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><h2>Models &amp; request profiling</h2><label>Default free model<select aria-label="Default free model" value={model} onChange={e=>{setModel(e.target.value);runAction('settings.ds_settings3.RouterModel',e.target.value);}}>{models.map(m=><option key={m}>{m}</option>)}</select></label><p className="muted">Free first · no paid fallbacks · request metadata kept for 20 days</p><Btn sm onClick={event=>runAction('settings.ds_settings3.RouterRefresh',event)}>Refresh models and requests</Btn><div className="router-table-scroll"><table className="router-requests" aria-label="Router requests"><thead><tr><th scope="col">Agent</th><th scope="col">Model</th><th scope="col">Provider</th><th scope="col">Requests</th><th scope="col">Tokens</th><th scope="col">Measured time</th></tr></thead><tbody>{groups.map(row=><tr key={row.key}><th scope="row">{row.agent}</th><td>{row.model}</td><td>{row.provider}</td><td>{row.count}</td><td>{tokens(row)}</td><td>{time(row)}</td></tr>)}</tbody><tfoot><tr><th scope="row" colSpan={3}>Total</th><td>{total.count}</td><td>{tokens(total)}</td><td>{time(total)}</td></tr></tfoot></table></div>{load.status==='empty'&&<p>No model requests yet.</p>}{load.status==='loaded'&&<p>{r.requests.length} recent requests</p>}<h3>Live agent processes</h3><p>{r.live_agents.complete?'Observed processes':'Process observation incomplete'}</p>{r.live_agents.processes.map(p=><p key={p.pid}>{p.runtime} · PID {p.pid}</p>)}</Card>;
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
          fontSize: 'calc(11px * var(--text-scale,1))',
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
                fontSize: 'calc(12px * var(--text-scale,1))'
              }}>{c.host ? c.detail||c.state : c.credential ? 'Saved in Windows Credential Manager' : c.connected ? c.display_name||'Connected to your account' : c.blocker||'Connect this account to use it'}{c.checked ? ' · checked' : ''}</span></div></div><div style={{
            justifySelf: 'end'
          }}><Btn sm onClick={event => runAction('settings.ds_settings3.ConnectionsAction1', c, event)}>{c.credential ? 'Details' : c.connected ? 'Open' : c.host?'Manage':'Connect'}</Btn></div></div>)}</Card>{status==='empty'&&<Empty>Connect an account or start a program with its ArchHub bridge, then refresh Connections.</Empty>}</div></>;
  }
  function WorkspaceRows() {
    const s = useData(),
      u = useApp();
    const [newProject,setNewProject]=React.useState(false), [projectName,setProjectName]=React.useState(''),
      [projectParent,setProjectParent]=React.useState(''), [creating,setCreating]=React.useState(false);
    const createProject=async()=>{
      if(creating)return;
      setCreating(true);
      try {
        const result=await u.act(()=>api.addWorkspace({create:true,parent:projectParent,name:projectName}));
        if(result?.root){setNewProject(false);setProjectName('');}
      } finally {setCreating(false);}
    };
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {WorkspaceRowsAction0: (event) => (() => u.pickWorkspace())(event),
WorkspaceRowsAction1: (w, event) => (async () => {
            const opened=await u.act(() => api.selectWorkspace(w.id));
            if(opened?.ok)u.go('home');
          })(event),
WorkspaceRowsAction2: (w, event) => (() => u.show('Workspace rules', {
            id: w.id
          }))(event),
WorkspaceRowsAction3: (w, event) => (() => u.confirm('Remove this workspace from the list?', () => api.removeWorkspace(w.id)))(event),
WorkspaceRowsAction4: (event) => (() => u.act(api.listWorkspaces))(event),
NewProject:()=>setNewProject(value=>!value), CreateProject:createProject, CancelProject:()=>setNewProject(false)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><Card><div className="spread" style={{
        padding: 16
      }}><div><h2>Workspaces</h2><small className="muted">Choose the folders ArchHub and your agents work in.</small></div><div className="flex"><Btn sm onClick={event=>runAction('settings.ds_settings3.NewProject',event)}>New project</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction0', event)}>Add workspace</Btn></div></div>{newProject&&<form className="row grid" aria-label="New project" onSubmit={event=>{event.preventDefault();runAction('settings.ds_settings3.CreateProject',event);}}><label>Project name<input aria-label="Project name" value={projectName} disabled={creating} onChange={event=>setProjectName(event.target.value)}/></label><label>Parent workspace<select aria-label="Parent workspace" value={projectParent} disabled={creating} onChange={event=>setProjectParent(event.target.value)}><option value="">Choose a registered folder</option>{s.workspaces.filter(w=>!w.builtIn&&w.available!==false).map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label><p>New project folders: {s.workspaces.find(w=>w.id===projectParent)?.projectTemplate||'Choose a parent folder'}. Existing folders stay as they are.</p><div className="flex"><button type="submit" className="sheet-action" onClick={event=>{event.preventDefault();runAction('settings.ds_settings3.CreateProject',event);}} disabled={creating||!projectName.trim()||!projectParent}>{creating?'Creating…':'Create project'}</button><Btn sm ghost disabled={creating} onClick={event=>runAction('settings.ds_settings3.CancelProject',event)}>Cancel</Btn></div></form>}<div className="row muted" role={s.workspaceHealth?.state === 'error' ? 'alert' : 'status'}>{s.workspaceHealth?.message || 'Reading workspaces…'}{s.workspaceHealth?.state === 'error' && <Btn sm ghost onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction4', event)}>Retry</Btn>}</div>{s.workspaceHealth?.recovery && <div className="row muted">{s.workspaceHealth.recovery.message}</div>}{s.workspaces.map(w => <div key={w.id} className="spread row"><D.Toggle label={'Use ' + w.name} checked={(s.graph.workspaceIds || []).includes(w.id)} onCheckedChange={v => u.act(() => api.setGraphWorkspaces(v ? [...new Set([...(s.graph.workspaceIds || []), w.id])] : (s.graph.workspaceIds || []).filter(id => id !== w.id)))} /><div className="fill"><h3>{w.name}</h3><span className="muted" style={{
            fontSize: 'calc(12px * var(--text-scale,1))'
          }}>{w.folder} · {w.available === false ? 'Folder unavailable' : (s.workspaceHealth?.state === 'ready' || (s.workspaceHealth?.state === 'idle' && w.builtIn)) ? 'Ready' : 'Checking…'}</span></div><div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction1', w, event)}>Open</Btn><Btn sm ghost aria-label={'Privacy ' + w.name} title="Workspace privacy" onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction2', w, event)}><window.AHIcon name="shield" size={16} /></Btn>{!w.builtIn && w.removable !== false && <Btn sm ghost onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction3', w, event)}>Remove</Btn>}</div></div>)}{!s.workspaces.some(w => !w.builtIn) && <Empty>No other workspaces yet.</Empty>}</Card></>;
  }
  function Account() {
    const s = useData(),
      u = useApp();
    const initials = window.UI.profileInitials(s.profile);
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
    }}><h2>Where your work lives</h2><p className="muted">Workflows and settings stay with your account. Client work stays on this machine.</p><div className="flex">{api.supportsAction?.('archiveActivity') !== false && <Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction0', event)}>Archive old activity</Btn>}<window.UI.Soon label="Cloud backup — coming"><Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction1', event)}>Back up now</Btn></window.UI.Soon></div>{s.backups.map(b => <div className="spread" key={b.id}><span>{b.name}</span><Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction2', b, event)}>Roll back</Btn></div>)}</Card></>;
  }
  // The one update card: current build, update state and Check for updates (api.checkForUpdates).
  function UpdateCard({runAction, autoInstall}) {
    const s = useData();
    return <Card style={{
            padding: 16
          }}><div className="spread"><div><h2>ArchHub</h2><p className="muted">{s.update.installed || 'Installed build unavailable'}</p></div>{s.update.available ? <Btn p onClick={event => runAction('settings.ds_settings3.SettingsAction8', event)}>Update</Btn> : <Chip c={s.update.state === 'idle' ? A.ok : A.warn}>{s.update.state === 'idle' ? s.update.detail : s.update.detail || 'Update status unavailable'}</Chip>}</div>
          {s.update.restartRefusal && <p role="alert">{s.update.restartRefusal}</p>}
          {autoInstall !== undefined && <label className="spread" data-setting="Updates.Install automatically" style={{marginTop: 12}}><span>Install updates automatically when I am away or ArchHub is in the tray</span><input type="checkbox" aria-label="Install updates automatically" disabled={autoInstall === null} checked={!!autoInstall} onChange={event => runAction('settings.ds_settings3.UpdatesAutoInstall', event.target.checked, event)} /></label>}
          {s.update.updatedTo && <div role="status" className="spread"><span>Updated {s.update.updatedFrom || 'ArchHub'} → {s.update.updatedTo}</span><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction9', event)}>Dismiss update confirmation</Btn></div>}
          <div className="flex" style={{
              marginTop: 12,
              flexWrap: 'wrap'
            }}><Btn sm disabled={s.update.state === 'checking' || s.update.state === 'restarting'} onClick={event => runAction('settings.ds_settings3.SettingsAction10', event)}>Check for updates</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction11', event)}>What’s new</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction12', event)}>First run</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction13', event)}>Docs</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction14', event)}>Feedback</Btn></div></Card>;
  }
  // Settings → System → Updates: the update card with its own action owner, so its failure shows here.
  function UpdatesPage() {
    const u = useApp();
    // The same stored value the Workshop node's update_auto_apply_on_quit parameter edits; the update policy reads it.
    const [autoInstall, setAutoInstall] = React.useState(null);
    const [load, setLoad] = React.useState('waiting');
    const readSaved = React.useCallback(() => {
      setLoad('waiting');
      return api.getApplicationSettings().then(saved => {
        setAutoInstall(saved.update_auto_apply_on_quit !== false);
        setLoad(Object.keys(saved).length ? 'loaded' : 'empty');
      }, error => {
        setAutoInstall(null);
        setLoad('error');
        throw error;
      });
    }, []);
    React.useEffect(() => { readSaved().catch(error => console.warn('Update setting unreadable:', error.message)); }, [readSaved]);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {
      UpdatesSettingRetry: () => u.act(readSaved),
      UpdatesAutoInstall: next => u.act(async () => {
        const saved = await api.setApplicationSetting('update_auto_apply_on_quit', next);
        setAutoInstall(saved.update_auto_apply_on_quit !== false);
        return saved;
      }),
      SettingsAction8: () => u.show('Update'),
      SettingsAction9: () => u.act(api.acknowledgeUpdate),
      SettingsAction10: () => u.act(api.checkForUpdates),
      SettingsAction11: () => u.show('What’s new'),
      SettingsAction12: () => u.go('first-run'),
      SettingsAction13: () => u.go('docs'),
      SettingsAction14: () => u.go('feedback')
    });
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} />
      {load === 'waiting' && <p className="muted">Reading your update setting…</p>}
      {load === 'error' && <p role="alert">Your update setting could not be read. <Btn sm onClick={event => runAction('settings.ds_settings3.UpdatesSettingRetry', event)}>Retry</Btn></p>}
      {load === 'empty' && <p className="muted">Automatic updates use the default (on) until you change them below.</p>}
      {load === 'loaded' && <p className="muted">Automatic updates are {autoInstall ? 'on' : 'off'}.</p>}
      <UpdateCard runAction={runAction} autoInstall={load === 'loaded' || load === 'empty' ? autoInstall : undefined} /></>;
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
          fontSize: 'calc(20px * var(--text-scale,1))',
          padding: '0 10px 12px'
        }}>Settings</h1><input aria-label="Find a setting" placeholder="⌕ Find a setting" value={query} onChange={e => setQuery(e.target.value)} style={{
          width: '100%',
          height: 34
        }} /><div className="spread" style={{
          padding: '12px 6px 8px',
          fontSize: 'calc(13px * var(--text-scale,1))',
          color: A.inkSoft
        }}><span>Show advanced</span><D.Toggle variant="settings" label="Show advanced" checked={u.advanced} onCheckedChange={u.setAdvanced} /></div>
   {query ? <div className="grid">{matched.map(r => <button key={r.id} className="listbutton" onClick={event => runAction('settings.ds_settings3.SettingsAction0', r, event)}><b>{r.label}</b><p className="muted" style={{
              fontSize: 'calc(11px * var(--text-scale,1))'
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
        }}><label className="flex muted">Scope<select disabled={!s.settingsDestination} aria-label="Settings scope" value={s.settingsScope} onChange={e => {const value=e.target.value,destination=s.settingsDestination;return u.act(() => api.setSettingsScope(value,destination));}}><option>User</option><option>Workspace</option></select></label><span className="fill" /><span className="muted">{s.settingsScope === 'Workspace' ? s.workspaces.find(w => w.id === s.activeWorkspace)?.name : 'Your account'}</span></div>}<div className="settings-health"><span className="status-dot" /><span>{actual === 'Connections' ? (s.connections.filter(c => c.connected).length+(s.hosts||[]).filter(c=>['connected','listening'].includes(c.state)).length) + ' accounts and programs connected' : actual === 'BABOOM' ? s.providers.filter(p => p.enabled && p.signedIn).length + ' providers ready' : actual === 'Agents' ? s.agentHealth||'Checking running agents…' : actual === 'Account' ? s.profile.firm + ' · ' + s.workspaces.length + ' workspace' : actual === 'Updates & About' ? s.update.available ? 'An update is ready' : s.update.detail || 'Update status unavailable' : 'Preferences'}</span></div><div className="flex settings-filter" style={{
          marginBottom: 14
        }}><D.Toggle label="Changed only" checked={changed} onCheckedChange={setChanged} /><span className="muted" style={{
            fontSize: 'calc(12px * var(--text-scale,1))'
          }}>Changed only</span>{full && <><span className="fill" /><span>Show advanced</span><D.Toggle label="Show advanced" checked={u.advanced} onCheckedChange={u.setAdvanced} /></>}</div>
   <div className="grid">
    {actual === 'System graph' && <window.UI.SystemGraph />}
    {actual === 'Account' && <Account />}<window.UI.CapabilityRows page={actual} />
    {actual === 'Connections' && <Connections />}
    {actual === 'Agents' && <RouterSettings />}
    {actual === 'Hooks' && <Permissions />}
    {actual === 'BABOOM' && <Providers />}{actual === 'Agents' && <><Card style={{
            padding: 18
          }}><div className="spread"><h2>Agents at work</h2><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction4', event)}>Open</Btn></div><p role="status">{s.agentSummary||'Checking running agents…'}</p><p className="muted">{s.agentHealth||'Checking running agents…'}</p><Btn sm onClick={event=>runAction('settings.ds_settings3.SettingsAction25',event)}>{s.agentSummary==='Agent status is incomplete.'?'Check again':'Refresh'}</Btn>{(s.agents||[]).filter(p=>p.kind!=='observation').map(p => <div className="spread row" key={p.id}><span className="flex"><window.UI.Av id={p.id} size={24} /><span><b>{p.name}</b><small className="muted" style={{display:'block'}}>{p.title} · {p.model}</small><small style={{display:'block'}}>{p.task}</small>{p.detail&&<small className="muted" style={{display:'block'}}>{p.detail}</small>}</span></span><Chip c={p.presence === 'working' ? A.ok : p.presence === 'unknown' ? A.warn : A.inkSoft}>{p.status_text||'Idle'}</Chip></div>)}<button className="listbutton flex" onClick={event => runAction('settings.ds_settings3.SettingsAction5', event)}>Manage providers<window.AHIcon name="arrow" size={15} /></button></Card><Providers /></>}
    {actual === 'Brain' && <><window.UI.MemoryRules /><Btn onClick={event => runAction('settings.ds_settings3.SettingsAction6', event)}>Community</Btn></>}
    {actual === 'Automations' && <window.UI.Automations embedded />}
    {actual === 'Dependencies' && <Card style={{
            padding: 22
          }}><div className="spread"><div><h2>Managed tools</h2><p className="muted">Versions, health, resources and the features that use each tool.</p></div><Btn p onClick={event => runAction('settings.ds_settings3.SettingsAction7', event)}>Open dependencies</Btn></div><div className="dependency-mini">{s.dependencies.slice(0, 5).map(d => <div className="row spread" key={d.id}><span>{d.name}</span><Chip c={d.state === 'Ready' ? A.ok : A.warn}>{d.state}</Chip></div>)}</div></Card>}
{actual === 'Updates & About' && <UpdateCard runAction={runAction} />}
    <div className="settings-grid">{groups.map(group => <Card key={group} style={{
              padding: '10px 14px 8px'
            }}><h3 style={{
                marginBottom: 8,
                fontSize: 'calc(14.5px * var(--text-scale,1))'
              }}>{group}</h3>{visible.filter(r => r.group === group).map(r => <SettingControl key={r.id} row={r} raw={u.advanced || actual === 'Advanced'} />)}</Card>)}</div>
    {actual === 'Account' && <Storage />}
    {actual === 'Brain' && <div className="flex"><Chip c={A.ok}>{s.brain.length} facts</Chip><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction15', event)}>Export</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction16', event)}>Sync to cloud</Btn></div>}
    {actual === 'Library & Mods' && <window.UI.HostSkills />}{actual === 'Library & Mods' && <div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction17', event)}>Open Library</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction18', event)}>Open Sessions</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction19', event)}>Open Templates</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction20', event)}>Install from folder</Btn></div>}
    {actual === 'BABOOM' && <div className="spread"><h3>Receipts · {s.receipts.length} actions</h3><div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction21', event)}>Open receipts</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction22', event)}>Export</Btn></div></div>}
    {actual === 'Advanced' && <div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction23', event)}>Open log</Btn><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction24', event)}>Docs &amp; website</Btn></div>}
   </div>
  </main>
 </div></>;
  }
  const SHEET_ACTIONS = {'settings.sheet.Refresh':'Refresh'};
  function executeAction(...args) {return window.executeAction(...args);}
  // Board r1963: one-line value box; the full value lives in the tooltip.
  function SheetField({label,value,children,onClick,description,title,unit,named}) {
    const full=title ?? (typeof value==='string'?value:undefined);
    return <div className="sheet-field" data-unit={unit||undefined} data-named={named||undefined}><span>{label}{description&&<small>{description}</small>}</span><div>{children || (onClick ? <button className="button-reset sheet-value" title={full} onClick={event=>executeAction('projects.controls.activate',{handler:onClick},event)}>{value}</button> : <span className="sheet-value" title={full}>{value ?? 'Not reported'}</span>)}</div></div>;
  }
  const shortPath=folder=>{const parts=String(folder).split(/[\\/]/).filter(Boolean);return parts.length>2?'…\\'+parts.slice(-2).join('\\'):folder;};
  function SheetPreference({label,match,raw=false}) {
    const s=useData(),row=s.settings.find(match || (r=>r.label===label));
    // Every element acts or goes: a preference with no settings-owner row is not shown.
    if(!row)return null;
    const unit=row.id==='Appearance.Default zoom'?'%':'';const named=row.id==='Appearance.Text scale'&&row.value===100?'Default':'';
    return <SheetField label={label} unit={unit} named={named} description={({Theme:row.value==='System'?'Follow the operating system':'Choose the application theme','Text size':'Adjust interface text size','Reduce motion':'Limit interface animation',Grid:'Show the grid when a workflow opens','Default zoom':'Set the starting zoom for a workflow','Review before sharing':'Check anything before it leaves this computer','Ask before meeting transcription':'Ask before a meeting is transcribed'})[label]}><SettingControl row={row} raw={raw} /></SheetField>;
  }
  // Subscriptions he already pays for: each signs in through its own app or CLI, never a key typed here.
  function Subscriptions() {
    const s=useData(),u=useApp();
    const rows=(s.providers||[]).filter(p=>typeof p.signIn==='boolean');
    const word=p=>p.state==='not supported'?'Not supported yet':p.state==='not installed'?'Not installed':p.signedIn===true?'Signed in':p.signedIn===false?'Not signed in':'Installed · sign-in not checked';
    return <section><h2>Subscriptions</h2><p>Each one signs in through its own app, in your browser. ArchHub never asks for its key.</p><div className="sheet-fields">{rows.map(p=><div className="spread row" key={p.id}><span><b>{p.name}</b><small className="muted" style={{display:'block'}}>{word(p)}</small></span>{p.state==='not supported'?<window.UI.Soon label={'Sign in to '+p.name}><span>Sign in</span></window.UI.Soon>:p.signIn&&p.signedIn!==true?<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.signInProvider(p.id))},event)}>Sign in</Btn>:null}</div>)}{!rows.length&&<p role="status">Checking subscriptions…</p>}</div></section>;
  }
  // The person's own MCP servers: one field takes an address, a command or an mcp.json snippet.
  function ToolServers() {
    const s=useData(),u=useApp(),[text,setText]=React.useState(''),[load,setLoad]=React.useState({status:'waiting'}),[attempt,setAttempt]=React.useState(0);
    React.useEffect(()=>{let current=true;setLoad({status:'waiting'});api.refreshMcpServers().then(rows=>{if(current)setLoad({status:rows?.length?'loaded':'empty'});},error=>{if(current)setLoad({status:'error',message:error?.message||'Could not read tool servers.'});});return()=>{current=false;};},[attempt]);
    const rows=s.mcpServers||[];
    const row=r=><div className="spread row" key={r.id}><span><b>{r.name}</b><small className="muted" style={{display:'block'}}>{r.where}{r.secrets?' · '+r.secrets+(r.secrets>1?' keys':' key')+' in Credential Manager':''}</small><small style={{display:'block'}}>{r.status}</small></span><span className="flex">{r.status==='Sign in needed'&&<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.signInMcpServer(r.id))},event)}>Sign in</Btn>}<Btn sm ghost disabled={!r.enabled} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.discoverMcpTools(r.id))},event)}>Check</Btn><D.Toggle label={(r.enabled?'Switch off ':'Switch on ')+r.name} checked={r.enabled} onCheckedChange={on=>u.act(()=>api.setMcpServerEnabled(r.id,on))} /><Btn sm ghost aria-label={'Remove '+r.name} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.removeMcpServer(r.id))},event)}>Remove</Btn></span></div>;
    return <section><h2>Tool servers (MCP)</h2><p>Add any MCP server: paste its address, its command, or an mcp.json snippet. Its tools become Library nodes and every agent connected to ArchHub can use them. A server that needs an account signs in in your browser; keys and sign-ins go to Windows Credential Manager.</p>{load.status==='waiting'&&<p role="status">Reading tool servers…</p>}{load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAttempt(value=>value+1)},event)}>Retry tool servers</Btn></div>}{load.status==='empty'&&<p>No tool servers yet.</p>}{load.status==='loaded'&&<div className="sheet-fields">{rows.map(row)}</div>}<textarea aria-label="Add a tool server" rows={3} placeholder={'https://… · npx -y @scope/server · {"mcpServers": {…}}'} value={text} onChange={event=>setText(event.target.value)} /><Btn sm disabled={!text.trim()} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(async()=>{const result=await api.addMcpServer(text);setText('');setLoad({status:'loaded'});return result;})},event)}>Add tool server</Btn></section>;
  }
  function PreferencesTransfer() {
    const s=useData(),u=useApp(),input=React.useRef(null),last=React.useRef(null);
    const [load,setLoad]=React.useState({status:'empty'});
    const destination=s.settingsDestination,scope=s.settingsScope||'User',label={User:'Everywhere',Workspace:'Current workspace',Session:'Current session'}[scope];
    const run=action=>{last.current=action;setLoad({status:'waiting'});return u.act(async()=>{try{const result=await action();setLoad({status:'loaded'});return result;}catch(error){setLoad({status:'error',message:error.message||String(error)});throw error;}});};
    return <section aria-label="Transfer settings"><div className="flex">
      <Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.download('Settings',scope)},event)}>Export {label}</Btn>
      <Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.download('Settings','All')},event)}>Export all scopes</Btn>
      <Btn sm ghost disabled={!destination||load.status==='waiting'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>input.current?.click()},event)}>Import into {label}</Btn>
      <input ref={input} type="file" accept=".json,application/json" aria-label="Import settings file" hidden onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(!file)return;executeAction('projects.controls.activate',{handler:()=>run(async()=>{if(file.size>1048576)throw Error('Choose a settings export up to 1 MiB.');return api.importPreferences(JSON.parse(await file.text()),destination);})},event);}} />
      <Btn sm ghost disabled={!destination||load.status==='waiting'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.confirm('Reset all settings in '+label+'? Other scopes stay as they are.',()=>run(()=>api.resetPreferences(destination)))},event)}>Reset {label}</Btn>
    </div><p className="muted">Transfers Look, project and keyboard preferences. Accounts, sign-ins, permissions and layouts stay with their own controls. Import applies only to {label}.</p>
    {s.settingsScopeNotice&&<Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(()=>api.refreshPreferences())},event)}>Refresh settings scope</Btn>}
    {load.status==='waiting'&&<p role="status">Applying settings...</p>}{load.status==='empty'&&<span className="visually-hidden">No settings transfer requested.</span>}{load.status==='loaded'&&<p role="status">Settings applied to {label}.</p>}{load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(last.current)},event)}>Retry settings transfer</Btn></div>}
    </section>;
  }

  function KeyboardSettings({changedOnly=false}) {
    const s=useData(),u=useApp(),[capturing,setCapturing]=React.useState('');
    const [load,setLoad]=React.useState({status:'waiting'}),failed=React.useRef(null);
    const destination=s.settingsDestination;
    const rows=(s.keyboardCommands||[]).filter(row=>!changedOnly||row.changed);
    React.useEffect(()=>{setLoad(s.keyboardPending?{status:'waiting'}:s.keyboardError?{status:'error',message:s.keyboardError}:{status:rows.length?'loaded':'empty'});},[s.keyboardPending,s.keyboardError,s.keyboardCommands,changedOnly]);
    const run=action=>{failed.current=action;setLoad({status:'waiting'});return u.act(async()=>{try{const result=await action();setLoad({status:(result.keyboardCommands||[]).some(row=>!changedOnly||row.changed)?'loaded':'empty'});return result;}catch(error){setLoad({status:'error',message:error.message||String(error)});throw error;}});};
    React.useEffect(()=>{
      if(!capturing)return undefined;
      const capture=event=>{
        event.preventDefault();event.stopImmediatePropagation();
        if(event.key==='Escape'){setCapturing('');return;}
        const chord=window.UI.shortcutFromEvent(event);
        if(!chord)return;
        setCapturing('');run(()=>api.setKeybinding(capturing,chord,destination));
      };
      document.addEventListener('keydown',capture,true);
      return()=>document.removeEventListener('keydown',capture,true);
    },[capturing]);
    return <div className="sheet-keybindings"><p>Keyboard shortcuts use the selected scope. One shortcut per action, shared by menus and the actual command. Choose a key, then press its replacement. Escape cancels.</p>
      {load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(failed.current||(()=>api.refreshSettingsControls()))},event)}>Retry keyboard shortcuts</Btn></div>}
      {capturing&&<p role="status">Press the new shortcut. Escape cancels.</p>}
      {load.status==='waiting'&&<p role="status">Reading keyboard shortcuts...</p>}{load.status==='empty'&&<p>No keyboard shortcuts to show.</p>}
      {load.status==='loaded'&&<div>{rows.map(row=><div className="spread row" key={row.id} data-setting={'Keyboard.'+row.id}><span><b>{row.label}</b><small className="muted" style={{display:'block'}}>{row.contexts.includes('navigation')?'Everywhere':row.contexts.includes('session')?'In a task':'Canvas'}</small></span><div className="flex"><Btn sm disabled={!destination} aria-label={'Change shortcut for '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setCapturing(row.id)},event)}>{capturing===row.id?'Press keys...':row.value||'Unbound'}</Btn>{row.changed&&<Btn sm ghost disabled={!destination} aria-label={'Reset shortcut for '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(()=>api.setKeybinding(row.id,null,destination))},event)}>Reset</Btn>}<Btn sm ghost disabled={!destination||!row.value} aria-label={'Unbind '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>run(()=>api.setKeybinding(row.id,'',destination))},event)}>Clear</Btn></div></div>)}</div>}
      <Btn sm ghost disabled={!destination} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.confirm('Reset all keyboard shortcuts?',()=>run(()=>api.resetKeybindings(destination)))},event)}>Reset all shortcuts</Btn>
      <p className="muted">Fixed: Escape backs out; Space-drag pans; wheel zooms.</p>
    </div>;
  }
  function Settings({page='Account',full=false}) {
    const s=useData(),u=useApp();
    const group=sections.find(section=>section.name===page || section.pages.includes(page)) || sections[0];
    const deep=page==='Advanced' || (page!=='Hooks' && page!=='Updates & About' && group.pages.includes(page) && page!==group.pages[0]);
    const [advancedOpen,setAdvancedOpen]=React.useState(deep);
    const [query,setQuery]=React.useState('');
    const [changedOnly,setChangedOnly]=React.useState(false);
    const [hostId,setHostId]=React.useState('');
    const [router,setRouter]=React.useState(null),[attempt,setAttempt]=React.useState(0),[load,setLoad]=React.useState({status:'waiting'});
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(SHEET_ACTIONS,{Refresh:()=>setAttempt(value=>value+1)});
    React.useEffect(()=>{let current=true;setLoad({status:'waiting'});Promise.allSettled([api.refreshRouter(),api.readHostAvailability(),api.listAgentsWorking(),api.refreshSettingsControls(),api.readSessionsFolder()]).then(results=>{if(!current)return;const model=results[0],errors=results.filter(result=>result.status==='rejected').map(result=>result.reason.message);if(model.status==='fulfilled')setRouter(model.value);setLoad(errors.length?{status:'error',message:errors.join(' ')}:{status:results[2].value?.length||results[1].value?.length?'loaded':'empty'});});return()=>{current=false;};},[attempt]);
    const go=route=>u.go(route),act=fn=>u.act(fn),connected=(s.hosts||[]).filter(host=>['connected','listening'].includes(host.state));
    const [reveal,setReveal]=React.useState('');
    // The account check ends: after the account request budget (runtime parameter account_http_ms) the row reads Local session.
    const [checkExpired,setCheckExpired]=React.useState(false);
    React.useEffect(()=>{setCheckExpired(false);if(!s.profile.checking)return undefined;const budget=s.runtimeParameters?.account_http_ms,timer=setTimeout(()=>setCheckExpired(true),Number.isSafeInteger(budget)&&budget>0?budget:0);return()=>clearTimeout(timer);},[s.profile.checking,s.runtimeParameters?.account_http_ms]);
    const area=sheetAreas.find(area=>area.pages.includes(page)||area.label===page) || sheetAreas[0];
    const currentCategory=area.pages.includes(page)?page:area.target;
    const isChanged=row=>row.default!==undefined&&JSON.stringify(row.value)!==JSON.stringify(row.default);
    const changedKeys=(s.keyboardCommands||[]).filter(row=>row.changed);
    const changedForArea=item=>s.settings.filter(row=>item.pages.includes(row.page)&&isChanged(row)).length+(item.pages.includes('Appearance')?changedKeys.length:0);
    const needle=query.trim().toLowerCase().replace(/^(where (is|are|do i (change|set|find))|how do i (change|set)|find|change|set)\s+/, '').replace(/^the\s+/, '');
    const words=needle.split(/\s+/).filter(word=>word&&!['mode','setting','settings','option','my','the','a'].includes(word));
    const settingValue=value=>value==null?'':typeof value==='object'?JSON.stringify(value):String(value);
    const settingText=row=>`${row.label||''} ${row.group||''} ${row.page||''} ${row.description||''} ${(row.options||[]).join(' ')} ${settingValue(row.value)}`.toLowerCase();
    const matched=needle?[...[...s.settings,...(s.keyboardCommands||[]).map(row=>({id:'Keyboard.'+row.id,label:row.label+' shortcut',group:'Keyboard',page:'Appearance',value:row.value,keyboard:true}))].filter(row=>words.every(word=>settingText(row).includes(word))),...[{id:'profile-name',label:'Name',page:'Account',value:s.profile.name||'Add your name',open:()=>u.show('My profile')},{id:'profile-email',label:'Email',page:'Account',value:s.profile.email||'Add an email',open:()=>u.show('My profile')}].filter(row=>words.every(word=>settingText(row).includes(word)))]:[];
    const revealSetting=row=>{
      if(row.open){row.open();return;}
      if(row.keyboard){setReveal(row.id);setChangedOnly(false);setQuery('');if(page!=='Appearance')go('settings/Appearance');return;}
      setReveal(row.id);
      setAdvancedOpen(true);
      setChangedOnly(false);
      if(row.page!==page)go('settings/'+row.page);
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
    const hosts=s.hosts||[];
    const chosen=hosts.find(host=>host.id===hostId);
    const status=(s.agents||[]).map(agent=>`${agent.session_count ?? agent.sessions?.length ?? 0} ${agent.name} sessions ${agent.presence||'unknown'}`).join(' · ');
    const preference=(label,match=undefined)=>{const row=s.settings.find(match||(row=>row.label===label));return !row||changedOnly&&JSON.stringify(row.value)===JSON.stringify(row.default)?null:<SheetPreference key={label} label={label} match={match} raw={advancedOpen} />;};
    // Privacy shows only with real settings-owner rows; the secrets note stays either way.
    const follow=[preference('Finish and report'),preference('Only notify when action is needed')].filter(Boolean);
    const knowledge=[preference('Conversation retention')].filter(Boolean);
    const privacyRows=[preference('Review before sharing'),preference('Ask before meeting transcription')].filter(Boolean);
    const idleRetention=[preference('Archive after idle days',row=>/archive_after_idle/i.test(row.id||'')||/archive after idle/i.test(row.label||'')),preference('Stale claim after idle minutes',row=>/stale_claim_after_idle/i.test(row.id||'')||/stale claim after idle/i.test(row.label||''))].filter(Boolean);
    const secretsNote=<><p className="sheet-section-gap">Secrets stay in protected connections, never in .archhub files.</p><button type="button" className="sheet-action secondary" onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Connections')},event)}>Manage protected connections</button></>;
    const accountRows=(s.connections||[]).filter(c=>!c.host);
    const shownLabels=new Set(currentCategory==='Account'?['Review before sharing','Ask before meeting transcription']:currentCategory==='BABOOM'?['Finish and report','Only notify when action is needed','Conversation retention']:[]);
    const visibleRows=s.settings.filter(row=>(changedOnly?isChanged(row):area.pages.includes(row.page)&&!shownLabels.has(row.label))&&(!row.advanced||advancedOpen||changedOnly));
    const lookFamilies={
      'Theme and colour':['Theme','High contrast','Accent colour','Node header colour'],
      'Size and density':['Text scale','Reduce motion','Row spacing'],
      'Panels':['Inspector width'],
      'Canvas':['Canvas grid','Default zoom','Node radius','Zoom percentage'],
      'Keyboard':[]
    };
    const rowFamily=row=>row.page==='Appearance' ? Object.entries(lookFamilies).find(([,labels])=>labels.includes(row.label))?.[0]||row.group||'Canvas' : row.group||'Preferences';
    const groupTitle=row=>(changedOnly?row.page+' \u203a ':'')+rowFamily(row);
    const rowGroups=currentCategory==='Appearance'&&!changedOnly?[...new Set([...Object.keys(lookFamilies),...visibleRows.map(rowFamily)])]:[...new Set(visibleRows.map(groupTitle))];
    const [outline,setOutline]=React.useState([]);
    const content=React.useRef(null);
    React.useEffect(()=>{
      const cards=[...(content.current?.querySelectorAll('.sheet-columns > section, .sheet-owner-card')||[])];
      setOutline(cards.map((node,index)=>{node.id='settings-section-'+index;return {id:node.id,label:node.querySelector('h2,h3')?.textContent||'Preferences'};}));
    },[page,advancedOpen,changedOnly,query,load.status,s.settings]);
    const missingProjectFamilies=['Project register','Units and precision','Office standard','Templates','Location','Revit worksharing','IFC and BCF','Print and PDF','CAD','File naming','CDE folders'].flatMap(label=>label==='IFC and BCF'?['IFC version','IFC export setup','BCF version'].filter(name=>!s.settings.some(row=>row.page==='Projects'&&row.group===label&&row.label===name)):s.settings.some(row=>row.page==='Projects'&&row.group===label)?[]:[label]);
    const jump=id=>document.getElementById(id)?.scrollIntoView({block:'start',behavior:'auto'});

    return <div data-screen={'settings/'+currentCategory} data-settings-full={full?'1':'0'} className="settings-sheet-stage settings-reference"><section className="settings-sheet" aria-label="Settings"><header><h1>Settings</h1><input className="sheet-search" aria-label="Search settings" placeholder="Search, or ask where something is" value={query} onChange={event=>setQuery(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&matched[0]){event.preventDefault();revealSetting(matched[0]);}if(event.key==='Escape')setQuery('');}} />{typeof api.setSettingsScope==='function'&&<label className="sheet-settings-scope">Scope<select disabled={!s.settingsDestination} aria-label="Settings scope" value={s.settingsScope||'User'} onChange={event=>{const value=event.target.value,destination=s.settingsDestination;return act(()=>api.setSettingsScope(value,destination));}}><option value="User">Everywhere</option><option value="Workspace" disabled={!s.settingsScopes?.Workspace}>Current workspace</option><option value="Session" disabled={!s.settingsScopes?.Session}>Current session</option></select></label>}<div className="sheet-view-filter" aria-label="Settings view"><button type="button" className="sheet-action secondary" aria-pressed={!changedOnly} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{setChangedOnly(false);setQuery('');}},event)}>All</button><button type="button" className="sheet-action secondary" aria-pressed={changedOnly} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{setChangedOnly(true);setQuery('');}},event)}>Changed {s.settings.filter(isChanged).length+changedKeys.length}</button></div><button type="button" className="sheet-action" onClick={event=>executeAction('projects.controls.activate',{handler:()=>go(u.settingsOrigin||'home')},event)}>Back to task</button></header><div className="sheet-layout"><nav className="sheet-tabs" aria-label="Settings categories">{sheetAreas.map(item=><button type="button" className="settings-section" aria-label={item.label} aria-current={!needle&&!changedOnly&&area===item?'page':undefined} key={item.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{setQuery('');setChangedOnly(false);go('settings/'+item.target);}},event)}><window.AHIcon name={item.icon} size={16}/><span><b>{item.label}</b><small>{item.description}</small></span>{changedForArea(item)>0&&<span className="sheet-change-count">{changedForArea(item)}</span>}</button>)}</nav><div className="sheet-content" ref={content}>{s.settingsScopeNotice&&<p role="alert">{s.settingsScopeNotice}</p>}<PreferencesTransfer />
      <window.UI.RegisteredActionStatus state={actionState} retry={retryAction}/>{load.status==='waiting'&&<div className="sheet-loading" role="status" aria-label="Reading settings…">{[0,1,2].map(row=><div className="dx-skeleton" key={row} />)}</div>}{load.status==='error'&&<div role="alert">{load.message}<Btn sm onClick={event=>runAction('settings.sheet.Refresh',event)}>Retry settings</Btn></div>}{load.status==='empty'&&<span className="visually-hidden">No connected programs or agent sessions reported.</span>}{load.status==='loaded'&&<span className="visually-hidden">Settings loaded.</span>}
      {needle&&<div className="sheet-results" role="listbox" aria-label="Settings results">{matched.map(row=><button type="button" role="option" className="sheet-result" key={row.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>revealSetting(row)},event)}><b>{row.label}</b><span>{settingValue(row.value)}</span>{row.open?null:<small>Advanced</small>}</button>)}{!matched.length&&<p>No matching setting.</p>}</div>}
      {!needle&&<div className="sheet-page-heading"><div><h2>{changedOnly?'Changed settings':currentCategory===area.target?area.label:currentCategory}</h2><p>{{Account:'Your identity, files and privacy on this computer.',Connections:'The programs and accounts your agents can work with.',BABOOM:'Choose the models your agents use.',Agents:'Which agents you have, and which model each uses.',Hooks:'Decide what agents may do without asking.',Appearance:'Choose how ArchHub looks and how the Canvas opens.','System graph':'Live wiring, tools and diagnostics for this app.'}[currentCategory]||area.description}</p></div><div className="flex">{s.settings.some(row=>row.page===currentCategory)&&api.supportsAction?.('exposeSettingsPage')!==false&&<button type="button" className="sheet-action secondary" onClick={event=>executeAction('projects.controls.activate',{handler:()=>act(()=>api.exposeSettingsPage(currentCategory))},event)}>Put on Canvas</button>}<button type="button" className="sheet-action secondary" aria-expanded={advancedOpen} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAdvancedOpen(value=>!value)},event)}>{advancedOpen?'Hide advanced':'Show advanced'}</button></div></div>}
      {!needle&&area.pages.length>1&&!changedOnly&&<nav className="sheet-subpages" aria-label={area.label+' pages'}>{area.pages.map(target=><Btn sm ghost key={target} aria-current={currentCategory===target?'page':undefined} onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/'+target)},event)}>{target==='BABOOM'?'Models & BABOOM':target}</Btn>)}</nav>}
      <div className="sheet-design-body"><div className="sheet-design-cards"><div className="sheet-columns" hidden={!!needle || changedOnly || load.status==='waiting'}>
      {currentCategory==='Account'&&<><section><h2>Your identity</h2><div className="sheet-fields"><SheetField label="Account" description="How ArchHub knows you on this computer" value={s.profile.checking&&!checkExpired?'Checking…':s.profile.signedIn?(s.profile.email?'Signed in · '+s.profile.email:'Signed in'):'Local session'} onClick={()=>u.show(s.profile.signedIn?'My profile':'Sign in')} /><SheetField label="Name" description="How you appear to your agents and team" value={s.profile.name||'Add your name'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('My profile')},event)} /><SheetField label="Email" description="Where your account messages go" value={s.profile.email||'Add an email'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('My profile')},event)} /></div><h2 className="sheet-section-gap">Files &amp; workspaces</h2><SheetField label="Sessions folder" description="Where each session file is saved" value={shortPath(s.sessionsFolder||'ArchHub/Sessions')} title={s.sessionsFolder||'ArchHub/Sessions'} onClick={()=>act(api.chooseSessionsFolder)} /><SheetField label="Workspace folder" description="The folder your agents work in" value={shortPath(s.workspaces.find(w=>w.id===s.activeWorkspace)?.path||'Choose a folder')} title={s.workspaces.find(w=>w.id===s.activeWorkspace)?.path||'Choose a folder'} onClick={event=>executeAction('projects.controls.activate',{handler:()=>act(api.addWorkspace)},event)} /><p>Workflow files travel with you. Local paths stay editable.</p>{!privacyRows.length&&secretsNote}</section>{privacyRows.length>0&&<section><h2>Privacy</h2><div className="sheet-fields">{privacyRows}</div>{secretsNote}</section>}</>}
      {currentCategory==='Connections'&&<><section><h2>Programs</h2><p>Live program status, document and current agent use.</p><div className="sheet-programs">{hosts.map(host=><button type="button" className="sheet-program" key={host.id} aria-pressed={chosen?.id===host.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setHostId(host.id)},event)}><span className="status-dot" style={{background:host.state==='connected'?A.ok:A.inkSoft}}/><div><b>{host.name}</b><p>Document · {host.document||host.document_name||host.detail||'No document reported'}</p><p>Agents using it · {host.agents?.map(a=>a.name||a).join(', ')||'not reported'}</p></div><span style={{color:host.state==='connected'?A.ok:A.inkSoft}}>{host.state}</span></button>)}{!hosts.length&&<p>No running programs reported.</p>}</div>{chosen&&<div className="sheet-program-access"><h2>Connection details</h2><p>Inspect this connection here.</p><SheetField label={chosen.name} value={(chosen.state||'not reported')+' · '+(chosen.document||chosen.document_name||chosen.detail||'No document reported')} /></div>}</section><section><h2>Accounts</h2><p>Social and work accounts with live connection state.</p><div className="sheet-agents">{accountRows.map(account=><div key={account.id}><b>{account.name}</b><span style={{color:account.connected?A.ok:A.inkSoft}}>{account.connected?(account.display_name||'Connected'):(account.blocker||'Not connected')}</span></div>)}{!accountRows.length&&<p>No accounts connected yet.</p>}</div><div className="flex" style={{marginTop:12}}><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('Connect')},event)}>Connect</Btn><Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAttempt(value=>value+1)},event)}>Refresh</Btn></div></section><Subscriptions /><ToolServers /></>}
      {currentCategory==='Agents'&&<><section><h2>Agents</h2><p>One row per agent app. State and model are live; Connect opens Dependencies when an app is not running.</p><div className="sheet-agents" role="list">{(s.agents||[]).filter(agent=>agent.kind!=='observation').map(agent=><div key={agent.id} role="listitem"><div><b>{agent.name}</b><small className="muted" style={{display:'block'}}>{agent.model||'Model not reported'}</small><small style={{display:'block'}}>{agent.task||agent.status_text}</small></div><div className="flex">{agent.presence==='stopped'?<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('dependencies')},event)}>Connect</Btn>:<span style={{color:agent.presence==='working'?A.ok:agent.presence==='unknown'?A.warn:A.inkSoft}}>{agent.status_text||'Idle'}</span>}</div></div>)}{!(s.agents||[]).some(agent=>agent.kind!=='observation')&&<p>Reading agents…</p>}</div><p className="sheet-session-summary" role="status">{s.agentSummary||status||'No agent sessions reported.'}</p><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>act(api.listAgentsWorking)},event)}>{s.agentSummary==='Agent status is incomplete.'?'Check again':'Refresh'}</Btn></section>{idleRetention.length>0&&<section><h2>Idle retention</h2><p>Runtime and session records leave the live list after this idle window. Reversible.</p><div className="sheet-fields">{idleRetention}</div></section>}</>}
      {currentCategory==='BABOOM'&&<><section><h2>Models</h2><p>{router?.catalogue_error||"Free models first. Changes apply on the next message."}</p><div className="sheet-fields sheet-models"><SheetField label="Default model">{router?<select aria-label="Default model" title={router.default_model} value={router.default_model} onChange={event=>act(()=>api.setRouterSettings({default_model:event.target.value})).then(result=>{if(result)setRouter(result);})}>{[...new Set([router.default_model,...router.models,...router.fallback_models])].map(model=><option key={model}>{model}</option>)}</select>:<span role="status">{load.status==='error'?load.message:'Reading models…'}</span>}</SheetField><SheetField label="Fallback order" value={router?(router.fallback_models.join(' → ')||'None'):undefined} /><SheetField label="Prefer free models">{router?<D.Toggle label="Prefer free models" checked={router.free_first} onCheckedChange={value=>act(()=>api.setRouterSettings({free_first:value})).then(result=>{if(result)setRouter(result);})}/>:<span>Reading…</span>}</SheetField></div><p className="sheet-session-summary">{status||'No agent sessions reported.'}</p></section>{(follow.length>0||knowledge.length>0)&&<section>{follow.length>0&&<><h2>Follow through</h2><div className="sheet-fields">{follow}</div></>}{knowledge.length>0&&<><h2 className="sheet-knowledge">Knowledge</h2><div className="sheet-fields">{knowledge}</div><p>Digest conversations into knowledge, then remove them.</p></>}</section>}</>}
      {currentCategory==='Hooks'&&<section className='sheet-canvas-defaults'><Permissions /></section>}
      {currentCategory==='Updates & About'&&<section className='sheet-canvas-defaults'><UpdatesPage /></section>}
      {currentCategory==='System graph'&&<><section><h2>Live wiring</h2><p>Drawn from the running app. These are not stored records.</p><div className="sheet-wiring"><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Agents')},event)}><b>Agents</b><small>{status||'No sessions reported'}</small></button><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Agents')},event)}><b>Router</b><small>{router?.default_model||'Reading router…'}</small></button><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('workshop')},event)}><b>Workshop</b><small>Session Link</small></button><button onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('settings/Connections')},event)}><b>Programs</b><small>{connected.map(host=>host.name).join(' · ')||'No programs connected'}</small></button></div>{preference('Keep running in tray')}</section><section><h2>Tools &amp; diagnostics</h2><div className="sheet-tools">{[['Dependencies','dependencies'],['Hooks','settings/Hooks'],['Updates','settings/Updates & About'],['Diagnostics','receipts']].map(([label,route])=><Btn key={label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>go(route)},event)}>{label}</Btn>)}</div><p className="sheet-diagnostics">Loading, failed and stopped states stay local to the affected tool.</p></section></>}
      {currentCategory==='BABOOM'&&advancedOpen&&<section><h2>Providers and request profiling</h2><Providers /><RouterSettings /></section>}
      {currentCategory==='System graph'&&advancedOpen&&<section><h2>System graph</h2><window.UI.SystemGraph /></section>}
      {currentCategory==='Brain'&&<section><h2>Brain and cloud sync</h2><window.UI.MemoryRules /></section>}
      {currentCategory==='Privacy'&&<section><h2>Workspaces and files</h2><WorkspaceRows /></section>}
      {currentCategory==='Automations'&&<section><h2>Automations</h2><window.UI.Automations embedded /></section>}
      {currentCategory==='Library & Mods'&&<section><h2>Library &amp; Mods</h2><window.UI.HostSkills /><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('library')},event)}>Open Library</Btn></section>}
      {currentCategory==='Dependencies'&&<section><h2>Managed tools</h2><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('dependencies')},event)}>Open dependencies</Btn></section>}
      {currentCategory==='Workshop'&&<section><h2>Workshop</h2><p>Conversation rules come from the same setting owners as your nodes.</p><Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>go('workshop')},event)}>Open Workshop</Btn></section>}
      {currentCategory==='Projects'&&<><section><h2>Project folders</h2><p>Use your registered workspaces. Folder selection and privacy use the existing workspace owner.</p><WorkspaceRows /></section>{missingProjectFamilies.length>0&&<section><h2>Project preferences</h2>{missingProjectFamilies.map(label=><window.UI.Soon block key={label} label={label}><p>{label}</p></window.UI.Soon>)}</section>}</>}
      </div>{!needle&&<div className="sheet-owner-cards" hidden={load.status==='waiting'}>{rowGroups.map(title=><section className="sheet-owner-card" key={title}><h3>{title}</h3>{currentCategory==='Appearance'&&title!=='Keyboard'&&!visibleRows.some(row=>groupTitle(row)===title)&&<p>No settings reported for this group.</p>}{currentCategory==='Appearance'&&!changedOnly&&title==='Keyboard'&&<KeyboardSettings />}{visibleRows.filter(row=>groupTitle(row)===title).map(row=><SettingControl key={row.id} row={row} raw={advancedOpen} />)}</section>)}{changedOnly&&changedKeys.length>0&&<section className="sheet-owner-card"><h3>Look - Keyboard</h3><KeyboardSettings changedOnly /></section>}{changedOnly&&!visibleRows.length&&!changedKeys.length&&<p>No settings differ from their defaults.</p>}</div>}</div>{!needle&&!changedOnly&&(outline.length>0||currentCategory==='Appearance')&&<aside className="sheet-design-side">{currentCategory==='Appearance'&&<section className="sheet-live-preview" aria-label="Live preview"><h3>Live preview</h3>{s.graph?.nodes?.length && window.UI.Canvas ? <>
        <div className="sheet-preview-stage" inert>
          <window.UI.Ctx.Provider value={{...u, libraryOpen:false, selectedNodeId:null}}>
            <window.UI.Canvas key={s.graph.scopeKey||s.graph.id} preview={s.graph} embedded externalInspector docked />
          </window.UI.Ctx.Provider>
        </div>
        <p>Changes apply to this workflow preview immediately.</p>
      </> : <p>Open a workflow to preview its real nodes here.</p>}</section>}<nav className="sheet-outline" aria-label="On this page"><b>On this page</b>{outline.map(row=><button type="button" key={row.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>jump(row.id)},event)}>{row.label}</button>)}</nav></aside>}</div></div></div></section></div>;
  }
  window.UI.Settings = Settings;
  window.UI.requestGroups = requestGroups;
  window.UI.Account = Account;
  window.UI.Connections = Connections;
  window.UI.WorkspaceRows = WorkspaceRows;
  window.UI.Storage = Storage;
  window.UI.settingsDoors = doors;
})();
