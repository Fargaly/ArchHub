// Account access stays with the user's identity; no founder cloud admin surface.
(() => {
  function executeAction(...args) {
    return window.executeAction(...args);
  }
  const WIRE_ACCESS_JSX_ACTIONS = {
  "settings.access.AccessAction0": "AccessAction0",
  "settings.access.AccessAction1": "AccessAction1",
  "settings.access.AccessAction2": "AccessAction2",
  "settings.access.AccessAction3": "AccessAction3",
  "settings.access.AccessAction4": "AccessAction4"
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
      Heading
    } = window.UI,
    Icon = window.AHIcon;
  function Access() {
    const s = useData(),
      u = useApp();
    const devicesRead = window.UI.useAction();
    React.useEffect(() => { devicesRead.run(api.readDevices); }, []);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_ACCESS_JSX_ACTIONS, {AccessAction0: (event) => (() => u.go('settings/Account'))(event),
AccessAction1: (plan, event) => (() => u.act(() => api.setAccountPlan(plan)))(event),
AccessAction2: (event) => (() => u.show('Invite'))(event),
AccessAction3: (device, event) => (() => u.act(() => api.selectDevice(device.id)))(event),
AccessAction4: () => devicesRead.retry()});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><section className="settings-embedded access-page"><Heading title="Plan & access" sub="One account for your team, workspaces and devices."><Btn sm onClick={event => runAction('settings.access.AccessAction0', event)}>Settings</Btn></Heading><div className="plan-cards">{[['Personal', 'Your projects, connected programs and companion.'], ['Office', 'Your office’s shared work, memory and agents.'], ['Team', 'Shared skills, team controls and coordinated delivery.']].map(([plan, sub]) => <button className="plan-card" key={plan} aria-pressed={s.profile.plan === plan} onClick={event => runAction('settings.access.AccessAction1', plan, event)}><div className="spread"><Icon name={plan === 'Personal' ? 'user' : 'users'} size={23} />{s.profile.plan === plan && <Chip c={A.accent}>Current plan</Chip>}</div><h2>{plan}</h2><p>{sub}</p><span className="muted">{s.profile.plan === plan ? 'Selected' : 'Choose plan'} →</span></button>)}</div><div className="access-columns"><Card style={{
          padding: 22
        }}><div className="spread"><h2>Your team</h2><Btn sm title="Invite a teammate" aria-label="Invite a teammate" onClick={event => runAction('settings.access.AccessAction2', event)}><Icon name="plus" size={16} /></Btn></div>{s.people.map(person => <div className="team-access-row" key={person.id}><div><b>{person.name}</b><small className="muted">{person.task || 'Team member'}</small></div><select aria-label={'Role ' + person.name} value={person.accessRole || 'Member'} onChange={e => u.act(() => api.setTeamAccess(person.id, {
              accessRole: e.target.value
            }))}>{['Owner', 'Member', 'Administrator', 'Viewer'].map(v => <option key={v}>{v}</option>)}</select><label className="grid">Access until<input aria-label={'Access until ' + person.name} type="date" value={person.expires || ''} onChange={e => u.act(() => api.setTeamAccess(person.id, {
                expires: e.target.value
              }))} /></label></div>)}</Card><div className="grid" style={{
          alignContent: 'start'
        }}><WatchSessions /><WatchingShared /><Card style={{
            padding: 22
          }}><h2>Connected devices</h2><p className="muted" style={{
              fontSize: 12,
              margin: '12px 0'
            }}>Choose where the next task runs. Your identity stays with your account.</p>{s.devices.map(device => <button className="device-row" key={device.id} aria-pressed={s.activeDevice === device.id} onClick={event => runAction('settings.access.AccessAction3', device, event)}><Icon name="canvas" /><span className="fill"><b>{device.name}</b><small>{device.status}</small></span>{s.activeDevice === device.id ? <Icon name="check" size={16} /> : <Icon name="arrow" size={16} />}</button>)}<div aria-live="polite" style={{
              fontSize: 12
            }}>{devicesRead.state === 'waiting' && <p role="status">Reading your devices…</p>}{devicesRead.state === 'empty' && <p className="muted">No device list returned.</p>}{devicesRead.state === 'loaded' && <p className="muted" role="note">{s.deviceNotice}</p>}{devicesRead.state === 'error' && <div role="alert"><p>{devicesRead.error}</p><Btn sm onClick={event => runAction('settings.access.AccessAction4', event)}>Retry</Btn></div>}</div></Card><Card style={{
            padding: 22
          }}><h2>Included with your account</h2>{['BABOOM companion', 'Connected programs', 'Your Brain', 'Visual workflows', 'Shared skills', 'Team Workshop'].map(name => <div className="source-row" key={name}><Icon name="check" size={14} /><span>{name}</span><span className="fill" /><span className="muted" style={{
                fontSize: 11
              }}>Included</span></div>)}</Card></div></div><window.UI.AccountUsage /><window.UI.BillingAccount /></section></>;
  }
  function WorkspaceRules({
    id
  }) {
    const s = useData(),
      u = useApp(),
      w = s.workspaces.find(w => w.id === id);
    return w ? <div className="grid"><h2>{w.name}</h2><p className="muted">Private workspaces are never shared publicly.</p><label className="grid">Privacy tier<select aria-label="Workspace privacy tier" value={w.privacy || 'Confidential'} onChange={e => u.act(() => api.setWorkspaceRules(id, {
          privacy: e.target.value
        }))}><option>Internal</option><option>Confidential</option><option>Secret</option></select></label><label className="grid">Workspace rules<textarea aria-label="Workspace rules" rows={4} value={w.rules || ''} placeholder="The rules your agents follow here" onChange={e => u.act(() => api.setWorkspaceRules(id, {
          rules: e.target.value
        }))} /></label><div className="spread"><span>Share learned rules with the team</span><D.Toggle label="Workspace team learning" checked={!!w.shareLearning} onCheckedChange={v => u.act(() => api.setWorkspaceRules(id, {
          shareLearning: v
        }))} /></div><Chip c={A.ok}>Every agent can work here</Chip></div> : null;
  }
  // Invite to watch (D-047): one named account sees one saved session read-only while ArchHub shares it.
  const GUEST_ROLES = ['Watch', 'Comment', 'Edit'];
  const GUEST_MENU_ACTIONS = {
    'settings.access.GuestToggle': 'GuestToggle',
    'settings.access.GuestClose': 'GuestClose',
    'settings.access.GuestPreview': 'GuestPreview',
    'settings.access.GuestStop': 'GuestStop',
    'settings.access.GuestRoleToggle': 'GuestRoleToggle',
    'settings.access.GuestSetRole': 'GuestSetRole',
    'settings.access.GuestRemove': 'GuestRemove'
  };
  window.registerActions(GUEST_MENU_ACTIONS, {
    GuestToggle: ({open, setOpen}) => setOpen(!open),
    GuestClose: ({setOpen}) => setOpen(false),
    GuestPreview: ({grant, sessionLabel, setOpen, u}) => {
      setOpen(false);
      u.setToast?.({text: 'Previewing what ' + (grant.name || grant.grantee) + ' sees.'});
      u.show('Watching', {grant: grant.id, title: sessionLabel});
    },
    GuestStop: ({firstName, grant, setOpen, u}) => {
      setOpen(false);
      return u.act(async () => {
        const res = await api.stopWatcher(grant.id);
        u.setToast?.({text: 'Stopped sharing with ' + firstName + '.'});
        return res;
      });
    },
    GuestRoleToggle: ({roleOpen, setRoleOpen}) => setRoleOpen(!roleOpen),
    GuestSetRole: ({firstName, grant, member, role, setLocalRole, setOpen, setRoleOpen, u}) => {
      setLocalRole(role);
      setRoleOpen(false);
      setOpen(false);
      return u.act(async () => {
        const res = typeof api.setGuestRole === 'function'
          ? await api.setGuestRole(grant.id, role)
          : member && typeof api.setTeamAccess === 'function'
            ? await api.setTeamAccess(member.id, {accessRole: role === 'Watch' ? 'Viewer' : 'Member'})
            : {ok: true};
        u.setToast?.({text: 'Changed ' + firstName + ' to ' + role + '.'});
        return res;
      });
    },
    GuestRemove: ({firstName, grant, setOpen, u}) => {
      setOpen(false);
      return u.act(async () => {
        const res = typeof api.removeGuest === 'function' ? await api.removeGuest(grant.id) : await api.stopWatcher(grant.id);
        u.setToast?.({text: 'Removed ' + firstName + ' from this Canvas.'});
        return res;
      });
    }
  });
  function GuestMenu({grant, onClose}) {
    const s = useData(), u = useApp();
    const [roleOpen, setRoleOpen] = React.useState(false);
    const [localRole, setLocalRole] = React.useState(grant.role || 'Watch');
    const label = grant.name || grant.grantee || 'Guest';
    const firstName = String(label).split(/[\s@]/)[0] || label;
    const sessionLabel = (grant.session || '').split(/[\\/]/).pop() || 'Session';
    const member = (s.people || []).find(p => p.email === grant.grantee || p.name === label);
    const setOpen = next => { if (!next) onClose?.(); };
    return <div role="menu" aria-label={label + ' guest menu'} data-design="guest.menu" style={{
      position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 1100, minWidth: 236,
      background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
      borderRadius: 10, padding: 6, boxShadow: '0 12px 32px rgba(0,0,0,0.45)', display: 'grid', gap: 2
    }}>
      <div style={{padding: '6px 10px', borderBottom: '1px solid var(--color-line-soft, #1e1e24)', marginBottom: 2}}>
        <div style={{fontSize: 13, fontWeight: 600, color: 'var(--color-ink, #ece8e0)'}}>{label}</div>
        <div className="muted" style={{fontSize: 11}}>{localRole} · {grant.expires ? 'until ' + new Date(grant.expires).toLocaleTimeString([], window.UI.zoned({hour: '2-digit', minute: '2-digit'})) : 'while you share it'}</div>
      </div>
      <button type="button" role="menuitem" className="listbutton" onClick={event => executeAction('settings.access.GuestPreview', {grant, sessionLabel, setOpen, u}, event)}>Preview what they see</button>
      <button type="button" role="menuitem" className="listbutton" onClick={event => executeAction('settings.access.GuestStop', {firstName, grant, setOpen, u}, event)}>Stop sharing with {firstName}</button>
      <button type="button" role="menuitem" aria-expanded={roleOpen} className="listbutton spread" onClick={event => executeAction('settings.access.GuestRoleToggle', {roleOpen, setRoleOpen}, event)}><span>Change to role</span><span className="muted">{localRole} ›</span></button>
      {roleOpen && <div role="group" aria-label="Guest role choices" style={{paddingLeft: 10, display: 'grid', gap: 2}}>
        {GUEST_ROLES.map(role => <button type="button" role="menuitemradio" aria-checked={localRole === role} key={role} className="listbutton spread" onClick={event => executeAction('settings.access.GuestSetRole', {firstName, grant, member, role, setLocalRole, setOpen, setRoleOpen, u}, event)}><span>Change to {role}</span><span>{localRole === role ? '✓' : ''}</span></button>)}
      </div>}
      <button type="button" role="menuitem" className="listbutton" style={{color: 'var(--color-err, #e6705f)'}} onClick={event => executeAction('settings.access.GuestRemove', {firstName, grant, setOpen, u}, event)}>Remove from this Canvas</button>
    </div>;
  }
  function GuestAvatar({grant, size = 28}) {
    const [open, setOpen] = React.useState(false);
    const label = grant.name || grant.grantee || 'Guest';
    const ini = String(label).trim().split(/[\s@._-]+/).filter(Boolean).map(w => w[0].toUpperCase()).join('').slice(0, 2) || 'G';
    return <span data-design="guest.avatar" onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }} style={{position: 'relative', display: 'inline-flex', alignItems: 'center'}}>
      <button type="button" className="button-reset" aria-label={'Guest ' + label} aria-haspopup="menu" aria-expanded={open} title={label + ' · watching'} onClick={event => executeAction('settings.access.GuestToggle', {open, setOpen}, event)} style={{
        width: size, height: size, borderRadius: '50%', border: '1.5px dashed var(--color-cyan, #5fb3b3)',
        background: 'var(--color-bg-soft, #1c1c23)', color: 'var(--color-ink, #ece8e0)',
        fontSize: 11, fontWeight: 600, display: 'grid', placeItems: 'center', cursor: 'pointer'
      }}>{ini}</button>
      {open && <><div aria-hidden="true" onMouseDown={() => executeAction('settings.access.GuestClose', {setOpen})} style={{position: 'fixed', inset: 0, zIndex: 1099}} /><GuestMenu grant={grant} onClose={() => executeAction('settings.access.GuestClose', {setOpen})} /></>}
    </span>;
  }
  const WATCH_ACTIONS = {"settings.access.WatchStop": "WatchStop", "settings.access.WatchRetry": "WatchRetry", "settings.access.WatchSend": "WatchSend"};
  const WATCH_ENDS = [['stop', 'When I stop it'], ['1h', 'After 1 hour'], ['today', 'End of today']];
  function WatchSessions() {
    const s = useData(), u = useApp(), read = window.UI.useAction();
    React.useEffect(() => { read.run(api.readWatchGrants); }, []);
    const watch = s.watch || {};
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WATCH_ACTIONS, {
      WatchStop: grant => u.act(() => api.stopWatcher(grant.id)), WatchRetry: () => read.retry(), WatchSend: () => null});
    const active = (watch.grants || []).filter(grant => grant.active);
    return <Card style={{padding: 22}} data-watch-sessions><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><h2>People watching your sessions</h2>
      <p className="muted" style={{fontSize: 12}}>They see one session's steps and results, read-only, while ArchHub shares it. Files, secrets and other sessions stay private.</p>
      {read.state === 'waiting' && <p role="status">Reading who is watching…</p>}
      {read.state === 'error' && <div role="alert"><p>{read.error}</p><Btn sm onClick={event => runAction('settings.access.WatchRetry', event)}>Retry</Btn></div>}
      {read.state === 'empty' && <p className="muted" role="note">No watcher list returned.</p>}
      {read.state === 'loaded' && <span className="visually-hidden">Watchers loaded.</span>}
      {read.state !== 'waiting' && watch.capability === false && <p className="muted" role="note">{watch.reason || 'Read-only watcher invitations are unavailable.'}</p>}
      {watch.capability && !active.length && <p className="muted">Nobody is watching. Right-click a session on Home and choose Invite to watch.</p>}
      {active.map(grant => <div className="team-access-row" key={grant.id}><div className="flex" style={{gap: 10}}><GuestAvatar grant={grant} /><div><b>{grant.grantee}</b><small className="muted" style={{display: 'block'}}>{(grant.session || '').split(/[\\/]/).pop() || 'Session'} · {grant.expires ? 'until ' + new Date(grant.expires).toLocaleString([], window.UI.zoned()) : 'while you share it'}</small></div></div>
        <Btn sm aria-label={'Stop ' + grant.grantee + ' watching'} onClick={event => runAction('settings.access.WatchStop', grant, event)}>Stop</Btn></div>)}</Card>;
  }
  function WatchInvite({path, title}) {
    const u = useApp(), [email, setEmail] = React.useState(''), [ends, setEnds] = React.useState('stop');
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WATCH_ACTIONS, {
      WatchSend: () => u.act(async () => { const result = await api.inviteWatcher(path, email.trim(), ends); u.close(); return result; }),
      WatchStop: () => null, WatchRetry: () => null});
    return <div className="grid" data-watch-invite><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} />
      <p className="muted">They see {title ? <b>{title}</b> : 'this session'} live: its steps and their results, as they happen. They cannot change, run or approve anything. Files, secrets and your other sessions stay private.</p>
      <label className="grid">Who<input type="email" aria-label="Watcher email" value={email} placeholder="name@office.com" autoComplete="off" onChange={event => setEmail(event.target.value)} /></label>
      <label className="grid">Ends<select aria-label="Watching ends" value={ends} onChange={event => setEnds(event.target.value)}>{WATCH_ENDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <p className="muted" style={{fontSize: 12}}>Only Internal projects can be watched. You can stop it any time in Account › Plan &amp; access.</p>
      <Btn p disabled={!/^\S+@\S+\.\S+$/.test(email.trim())} onClick={event => runAction('settings.access.WatchSend', event)}>Send invite</Btn></div>;
  }
  window.UI.Access = Access;
  window.UI.WorkspaceRules = WorkspaceRules;
  // The recipient side: sessions shared with me, and a read-only view built only from the cloud projection.
  const WATCHING_ACTIONS = {"settings.access.WatchOpen": "WatchOpen", "settings.access.WatchingRetry": "WatchingRetry"};
  const when = iso => iso ? new Date(iso).toLocaleString([], window.UI.zoned({dateStyle: 'medium', timeStyle: 'short'})) : '';
  function WatchingShared() {
    const s = useData(), u = useApp(), read = window.UI.useAction();
    React.useEffect(() => { read.run(api.readWatching); }, []);
    const shared = s.watching || {}, rows = shared.watching || [];
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WATCHING_ACTIONS, {
      WatchOpen: (row, index) => u.show('Watching', {grant: row.id, title: 'Shared session ' + (index + 1)}), WatchingRetry: () => read.retry()});
    return <Card style={{padding: 22}} data-watching-shared><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><h2>Sessions shared with you</h2>
      <p className="muted" style={{fontSize: 12}}>You see the steps and results live. You cannot change, run or approve anything.</p>
      {read.state === 'waiting' && <p role="status">Reading shared sessions…</p>}
      {read.state === 'error' && <div role="alert"><p>{read.error}</p><Btn sm onClick={event => runAction('settings.access.WatchingRetry', event)}>Retry</Btn></div>}
      {read.state !== 'waiting' && shared.capability === false && <p className="muted" role="note">{shared.reason || 'Read-only watcher invitations are unavailable.'}</p>}
      {read.state === 'loaded' && shared.capability && !rows.length && <p className="muted">Nothing is shared with you right now.</p>}
      {read.state === 'empty' && <p className="muted">No shared session list returned.</p>}
      {read.state === 'loaded' && <span className="visually-hidden">Shared sessions loaded.</span>}
      {rows.map((row, index) => <div className="source-row" key={row.id} data-watching-row={row.id}><Icon name="canvas" size={14} /><span>Shared session {index + 1}</span><span className="fill" />
        <span className="muted" style={{fontSize: 11}}>{row.state === 'waiting' ? 'Not shared yet' : 'Updated ' + when(row.updated)}{row.expires ? ' · ends ' + when(row.expires) : ''}</span>
        <Btn sm aria-label={'Watch shared session ' + (index + 1)} onClick={event => runAction('settings.access.WatchOpen', row, index, event)}>Watch</Btn></div>)}</Card>;
  }
  // Only the projected facts; a zero count is a fact too. No owner text.
  const watchFacts = n => [n.status, n.result?.error ? 'error' : '', typeof n.result?.items === 'number' ? n.result.items + ' items' : '',
    typeof n.result?.count === 'number' ? 'count ' + n.result.count : ''].filter(Boolean).join(' · ');
  // An anonymous outline around a group's projected members; groups carry no title.
  const groupBox = (g, at) => {
    const ps = g.children.map(id => at[id]).filter(Boolean);
    if (!ps.length) return null;
    const x = Math.min(...ps.map(p => p.x)) - 14, y = Math.min(...ps.map(p => p.y)) - 14;
    return {x, y, w: Math.max(...ps.map(p => p.x)) + 194 - x, h: Math.max(...ps.map(p => p.y)) + 74 - y};
  };
  const WATCH_COLOURS = {done: A.ok, failed: A.danger || A.accent, running: A.accent, approval: A.accent, waiting: A.accent};
  const WATCH_VIEW_ACTIONS = {"settings.access.WatchViewRetry": "WatchViewRetry"};
  function WatchView({grant}) {
    const read = window.UI.useAction(), [held, setHeld] = React.useState(null);
    React.useEffect(() => { read.run(() => api.readWatchedSession(grant)); }, [grant]);
    React.useEffect(() => { if (read.state === 'loaded') setHeld(read.result); }, [read.state, read.result]);
    const poll = held?.pollMs;  // the owner sets the cadence (watch_grants.WATCH_NODE poll_ms)
    React.useEffect(() => {
      if (!poll) return;
      const timer = setInterval(() => { if (!document.hidden) read.run(() => api.readWatchedSession(grant)); }, poll);
      return () => clearInterval(timer);
    }, [grant, poll]);
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WATCH_VIEW_ACTIONS, {WatchViewRetry: () => read.retry()});
    if (read.state === 'error') return <div role="alert" data-watch-view="error"><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><p>{read.error}</p><Btn sm onClick={event => runAction('settings.access.WatchViewRetry', event)}>Retry</Btn></div>;
    if (read.state === 'empty' && !held) return <p className="muted" role="note" data-watch-view="empty">Nothing was returned for this shared session.</p>;
    const view = held;
    if (!view) return <p role="status" data-watch-view="waiting">{read.state === 'waiting' ? 'Opening the shared session…' : 'Waiting for the shared session…'}</p>;    if (view.state !== 'live') return <p className="muted" role="note" data-watch-view={view.state}>{view.message}</p>;
    const nodes = view.projection.nodes, at = Object.fromEntries(nodes.map((n, i) => [n.id, n.position || {x: (i % 6) * 220, y: Math.floor(i / 6) * 120}]));
    const xs = Object.values(at).map(p => p.x), ys = Object.values(at).map(p => p.y);
    const minX = Math.min(0, ...xs) - 20, minY = Math.min(0, ...ys) - 20, width = Math.max(...xs, 0) - minX + 220, height = Math.max(...ys, 0) - minY + 100;
    return <div className="grid" data-watch-view="live"><p className="muted" style={{fontSize: 12}}>Read-only · updated {when(view.updated)}{read.state === 'loaded' && <span className="visually-hidden"> · current</span>}{read.state === 'waiting' && <span className="visually-hidden"> · refreshing</span>}{read.state === 'empty' && <span className="visually-hidden"> · no newer update</span>}</p>
      <svg role="img" aria-label="Shared session, read-only" viewBox={[minX, minY, width, height].join(' ')} style={{width: '100%', maxHeight: '60vh', background: 'var(--panel, transparent)'}}>
        {view.projection.groups.map((g, i) => { const box = groupBox(g, at); return box && <rect key={'g' + i} data-watch-group={i} data-members={g.children.length} x={box.x} y={box.y} width={box.w} height={box.h} rx="12" fill="none" stroke="currentColor" strokeOpacity="0.35" strokeDasharray="6 4" />; })}
        {view.projection.wires.map(([a, b]) => <line key={a + b} x1={at[a].x + 180} y1={at[a].y + 30} x2={at[b].x} y2={at[b].y + 30} stroke="currentColor" strokeOpacity="0.4" />)}
        {nodes.map(n => <g key={n.id} data-watch-node={n.id} data-status={n.status} transform={'translate(' + at[n.id].x + ' ' + at[n.id].y + ')'}>
          <rect width="180" height="60" rx="8" fill="none" stroke={WATCH_COLOURS[n.status] || 'currentColor'} strokeWidth="1.5" />
          <text x="12" y="25" fontSize="13" fill="currentColor">{n.label}</text>
          <text x="12" y="45" fontSize="11" fill="currentColor" opacity="0.7">{watchFacts(n)}</text></g>)}
      </svg></div>;
  }
  window.UI.WatchSessions = WatchSessions;
  window.UI.WatchingShared = WatchingShared;
  window.UI.WatchView = WatchView;
  window.UI.WatchInvite = WatchInvite;
  window.UI.GuestAvatar = GuestAvatar;
  window.UI.GuestMenu = GuestMenu;
})();
