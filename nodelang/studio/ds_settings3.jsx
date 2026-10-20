// DSYS-083/084/085/086/087: Frame/Nav/P/R row grammar retained; each of
// the Book's 15 pages is now a live projection of the single settings schema.
(() => {
  const WIRE_DS_SETTINGS3_JSX_ACTIONS = {
  "settings.ds_settings3.ConnectionsAction0": "ConnectionsAction0",
  "settings.ds_settings3.ConnectionsAction1": "ConnectionsAction1",
  "settings.ds_settings3.WorkspaceRowsAction0": "WorkspaceRowsAction0",
  "settings.ds_settings3.WorkspaceRowsAction1": "WorkspaceRowsAction1",
  "settings.ds_settings3.WorkspaceRowsAction2": "WorkspaceRowsAction2",
  "settings.ds_settings3.WorkspaceRowsAction3": "WorkspaceRowsAction3",
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
  "settings.ds_settings3.SettingsAction24": "SettingsAction24"
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
  function Connections() {
    const s = useData(),
      u = useApp();
    const [filter, setFilter] = React.useState('All');
    const group = c => ['Revit', 'AutoCAD', 'Rhino', '3ds Max', 'Office'].includes(c.name) ? 'Programs' : ['Instagram', 'Facebook', 'WhatsApp Business', 'LinkedIn', 'X', 'TikTok', 'YouTube'].includes(c.name) ? 'Social' : 'Work apps';
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_SETTINGS3_JSX_ACTIONS, {ConnectionsAction0: (g, event) => (() => setFilter(g))(event),
ConnectionsAction1: (c, event) => (() => c.connected ? u.show('Connection', {
              id: c.id
            }) : u.show('Connect', {
              id: c.id
            }))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div className="grid"><div className="flex">{['All', 'Programs', 'Social', 'Work apps'].map(g => <Btn sm ghost key={g} aria-pressed={filter === g} onClick={event => runAction('settings.ds_settings3.ConnectionsAction0', g, event)}>{g}</Btn>)}</div><Card><div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 130px',
          padding: '14px 16px 8px',
          fontSize: 11,
          color: A.inkSoft
        }}><span>PROGRAM OR ACCOUNT</span><span /></div>{s.connections.filter(c => filter === 'All' || group(c) === filter).map((c, i) => <div key={c.id} style={{
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
              }}>{c.connected ? 'Connected to your account' : 'Not connected'}{c.checked ? ' · checked' : ''}</span></div></div><div style={{
            justifySelf: 'end'
          }}><Btn sm onClick={event => runAction('settings.ds_settings3.ConnectionsAction1', c, event)}>{c.connected ? 'Open' : 'Connect'}</Btn></div></div>)}</Card></div></>;
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
WorkspaceRowsAction3: (w, event) => (() => u.confirm('Remove this workspace from the list?', () => api.removeWorkspace(w.id)))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><Card><div className="spread" style={{
        padding: 16
      }}><div><h2>Workspaces</h2><small className="muted">Choose the folders available to this graph.</small></div><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction0', event)}>Add</Btn></div>{s.workspaces.map(w => <div key={w.id} className="spread row"><D.Toggle label={'Use ' + w.name + ' in this graph'} checked={(s.graph.workspaceIds || []).includes(w.id)} onCheckedChange={v => u.act(() => api.setGraphWorkspaces(v ? [...new Set([...(s.graph.workspaceIds || []), w.id])] : (s.graph.workspaceIds || []).filter(id => id !== w.id)))} /><div className="fill"><h3>{w.name}</h3><span className="muted" style={{
            fontSize: 12
          }}>{w.folder} · open to all your agents</span></div><div className="flex"><Btn sm onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction1', w, event)}>Open</Btn><Btn sm ghost aria-label={'Privacy ' + w.name} title="Workspace privacy" onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction2', w, event)}><window.AHIcon name="shield" size={16} /></Btn><Btn sm ghost onClick={event => runAction('settings.ds_settings3.WorkspaceRowsAction3', w, event)}>Remove</Btn></div></div>)}{!s.workspaces.length && <Empty>Add a folder to work in.</Empty>}</Card></>;
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
    }}><h2>Where your work lives</h2><p className="muted">Graphs and settings stay with your account. Client work stays on this machine.</p><div className="flex">{api.supportsAction?.('archiveActivity') !== false && <Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction0', event)}>Archive old activity</Btn>}<Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction1', event)}>Back up now</Btn></div>{s.backups.map(b => <div className="spread" key={b.id}><span>{b.name}</span><Btn sm onClick={event => runAction('settings.ds_settings3.StorageAction2', b, event)}>Roll back</Btn></div>)}</Card></>;
  }
  function Settings({
    page = 'Account',
    full = false
  }) {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState(''),
      [changed, setChanged] = React.useState(false);
    const actual = s.pages.includes(page) ? page : 'Account';
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
SettingsAction24: (event) => (() => u.go('docs'))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><div data-screen={'settings/' + actual} style={{
      display: 'grid',
      gridTemplateColumns: full ? 'minmax(0,1fr)' : '260px minmax(0,1fr)',
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
            }}>{r.page} › {r.group}</p></button>)}{!matched.length && <Empty>No matching setting.</Empty>}</div> : s.pages.map((p, i) => <button className="listbutton flex" aria-label={p} key={p} aria-selected={actual === p} onClick={event => runAction('settings.ds_settings3.SettingsAction1', p, event)} style={{
          height: 34,
          fontSize: 13.5,
          padding: '0 12px'
        }}><span style={{
            width: 18
          }}><window.AHIcon name={["user", "link", "voice", "users", "brain", "canvas", "workshop", "library", "clock", "shield", "code", "shield", "palette", "update", "settings"][i]} size={16} /></span>{p}</button>)}
  </aside>}
  <main className={'page' + (actual === 'Account' ? ' account-settings' : '')} style={{
        padding: '22px 32px'
      }}><span className="settings-page-header-icon"><window.AHIcon name={["user", "link", "voice", "users", "brain", "canvas", "workshop", "library", "clock", "shield", "code", "shield", "palette", "update", "settings"][s.pages.indexOf(actual)]} size={21} /></span><Heading title={actual} sub={{
          Account: 'Your identity, workspaces and project files.',
          Connections: 'The programs and accounts your agents can work with.',
          BABOOM: 'Your companion’s providers, voice, presence and boundaries.',
          Agents: 'How your agents choose, finish and hand over work.',
          Brain: 'What your agents remember, and how they learn.',
          Appearance: 'Make ArchHub comfortable for the way you work.',
          Advanced: 'Fine control over loading, performance and connection limits.',
          Privacy: 'Control what stays local and what can leave your workspace.',
          'Updates & About': 'One update, with your work kept intact.'
        }[actual] || 'Your preferences for ' + actual.toLowerCase() + '.'}><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction2', event)}>{actual === 'System graph' ? 'Open graph' : actual === 'BABOOM' ? 'Open BABOOM' : 'Open'}</Btn><Btn sm ghost onClick={event => runAction('settings.ds_settings3.SettingsAction3', event)}>Reset</Btn></Heading>
   <div className="flex settings-scope" style={{
          marginBottom: 14
        }}><label className="flex muted">Scope<select aria-label="Settings scope" value={s.settingsScope} onChange={e => u.act(() => api.setSettingsScope(e.target.value))}><option>User</option><option>Workspace</option></select></label><span className="fill" /><span className="muted">{s.settingsScope === 'Workspace' ? s.workspaces.find(w => w.id === s.activeWorkspace)?.name : 'Your account'}</span></div><div className="settings-health"><span className="status-dot" /><span>{actual === 'Connections' ? s.connections.filter(c => c.connected).length + ' accounts and programs connected' : actual === 'BABOOM' ? s.providers.filter(p => p.enabled && p.signedIn).length + ' providers ready' : actual === 'Account' ? s.profile.firm + ' · ' + s.workspaces.length + ' workspace' : actual === 'Updates & About' ? s.update.available ? 'An update is ready' : s.update.detail || 'Update status unavailable' : 'Available backend preferences'}</span></div><div className="flex settings-filter" style={{
          marginBottom: 14
        }}><D.Toggle label="Changed only" checked={changed} onCheckedChange={setChanged} /><span className="muted" style={{
            fontSize: 12
          }}>Changed only</span>{full && <><span className="fill" /><span>Show advanced</span><D.Toggle label="Show advanced" checked={u.advanced} onCheckedChange={u.setAdvanced} /></>}</div>
   <div className="grid">
    {actual === 'Account' && <Account />}<window.UI.CapabilityRows page={actual} />
    {actual === 'Connections' && <Connections />}
    {actual === 'BABOOM' && <Providers />}{actual === 'Agents' && <Card style={{
            padding: 18
          }}><div className="spread"><h2>Agents at work</h2><Btn sm onClick={event => runAction('settings.ds_settings3.SettingsAction4', event)}>Open</Btn></div>{s.providers.map(p => <div className="spread row" key={p.id}><span className="flex"><window.UI.Av id={p.id} size={24} />{p.name}</span><Chip c={p.enabled && p.signedIn ? A.ok : A.inkSoft}>{s.tasks.find(t => t.owner === p.id && t.status === 'WIP')?.title || (p.enabled && p.signedIn ? 'Ready' : 'Off')}</Chip></div>)}<button className="listbutton flex" onClick={event => runAction('settings.ds_settings3.SettingsAction5', event)}>Manage providers<window.AHIcon name="arrow" size={15} /></button></Card>}
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
  window.UI.Settings = Settings;
  window.UI.Account = Account;
  window.UI.Connections = Connections;
  window.UI.WorkspaceRows = WorkspaceRows;
  window.UI.Storage = Storage;
  window.UI.settingsDoors = doors;
})();
