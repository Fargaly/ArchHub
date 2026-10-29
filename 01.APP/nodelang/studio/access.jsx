// Account access stays with the user's identity; no founder cloud admin surface.
(() => {
  const WIRE_ACCESS_JSX_ACTIONS = {
  "settings.access.AccessAction0": "AccessAction0",
  "settings.access.AccessAction1": "AccessAction1",
  "settings.access.AccessAction2": "AccessAction2",
  "settings.access.AccessAction3": "AccessAction3"
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
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_ACCESS_JSX_ACTIONS, {AccessAction0: (event) => (() => u.go('settings/Account'))(event),
AccessAction1: (plan, event) => (() => u.act(() => api.setAccountPlan(plan)))(event),
AccessAction2: (event) => (() => u.show('Invite'))(event),
AccessAction3: (device, event) => (() => u.act(() => api.selectDevice(device.id)))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><main className="page access-page" data-screen="access"><Heading title="Plan & access" sub="One account for your team, workspaces and devices."><Btn sm onClick={event => runAction('settings.access.AccessAction0', event)}>Settings</Btn></Heading><div className="plan-cards">{[['Personal', 'Your projects, connected programs and companion.'], ['Office', 'Your office’s shared work, memory and agents.'], ['Team', 'Shared skills, team controls and coordinated delivery.']].map(([plan, sub]) => <button className="plan-card" key={plan} aria-pressed={s.profile.plan === plan} onClick={event => runAction('settings.access.AccessAction1', plan, event)}><div className="spread"><Icon name={plan === 'Personal' ? 'user' : 'users'} size={23} />{s.profile.plan === plan && <Chip c={A.accent}>Current plan</Chip>}</div><h2>{plan}</h2><p>{sub}</p><span className="muted">{s.profile.plan === plan ? 'Selected' : 'Choose plan'} →</span></button>)}</div><div className="access-columns"><Card style={{
          padding: 22
        }}><div className="spread"><h2>Your team</h2><Btn sm title="Invite a teammate" aria-label="Invite a teammate" onClick={event => runAction('settings.access.AccessAction2', event)}><Icon name="plus" size={16} /></Btn></div>{s.people.map(person => <div className="team-access-row" key={person.id}><div><b>{person.name}</b><small className="muted">{person.task || 'Team member'}</small></div><select aria-label={'Role ' + person.name} value={person.accessRole || 'Member'} onChange={e => u.act(() => api.setTeamAccess(person.id, {
              accessRole: e.target.value
            }))}>{['Owner', 'Member', 'Administrator', 'Viewer'].map(v => <option key={v}>{v}</option>)}</select><label className="grid">Access until<input aria-label={'Access until ' + person.name} type="date" value={person.expires || ''} onChange={e => u.act(() => api.setTeamAccess(person.id, {
                expires: e.target.value
              }))} /></label></div>)}</Card><div className="grid" style={{
          alignContent: 'start'
        }}><Card style={{
            padding: 22
          }}><h2>Connected devices</h2><p className="muted" style={{
              fontSize: 12,
              margin: '12px 0'
            }}>Choose where the next task runs. Your identity stays with your account.</p>{s.devices.map(device => <button className="device-row" key={device.id} aria-pressed={s.activeDevice === device.id} onClick={event => runAction('settings.access.AccessAction3', device, event)}><Icon name="canvas" /><span className="fill"><b>{device.name}</b><small>{device.status}</small></span>{s.activeDevice === device.id ? <Icon name="check" size={16} /> : <Icon name="arrow" size={16} />}</button>)}</Card><Card style={{
            padding: 22
          }}><h2>Included with your account</h2>{['BABOOM companion', 'Connected programs', 'Your Brain', 'Visual workflows', 'Shared skills', 'Team Workshop'].map(name => <div className="source-row" key={name}><Icon name="check" size={14} /><span>{name}</span><span className="fill" /><span className="muted" style={{
                fontSize: 11
              }}>Included</span></div>)}</Card></div></div><window.UI.AccountUsage /><window.UI.BillingAccount /></main></>;
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
  window.UI.Access = Access;
  window.UI.WorkspaceRules = WorkspaceRules;
})();
