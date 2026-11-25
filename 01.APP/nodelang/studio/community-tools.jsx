(() => {
  const {
    api,
    useData,
    Btn,
    Card,
    Chip
  } = window.UI;
  function CommunityTools() {
    const s = useData() || {},
      actionState = window.UI.useAction(),
      c = s.community && !Array.isArray(s.community) ? s.community : { groups: [], joinStatus: '' },
      groups = Array.isArray(c.groups) ? c.groups : [],
      [group, setGroup] = React.useState(''),
      [invite, setInvite] = React.useState('');
    async function handleCommunitytoolsjsx1() {
      const result = await actionState.run(() => api.createCommunityGroup(group));
      if (result) setGroup('');
    }
    async function handleCommunitytoolsjsx2(g) {
      const result = await actionState.run(() => api.issueCommunityInvite(g.id, invite));
      if (result) setInvite('');
    }
    function handleCommunitytoolsjsx3(g, r) {
      return actionState.run(() => api.revokeCommunityInvite(g.id, r.id));
    }
    function handleCommunitytoolsjsx4() {
      return actionState.run(api.verifyCommunityInvite);
    }
    function handleCommunitytoolsjsx5() {
      return actionState.run(api.joinCommunityGroup);
    }
    const ACTIONS = {
      'community-tools.1': 'handleCommunitytoolsjsx1',
      'community-tools.2': 'handleCommunitytoolsjsx2',
      'community-tools.3': 'handleCommunitytoolsjsx3',
      'community-tools.4': 'handleCommunitytoolsjsx4',
      'community-tools.5': 'handleCommunitytoolsjsx5'
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleCommunitytoolsjsx1,
        handleCommunitytoolsjsx2,
        handleCommunitytoolsjsx3,
        handleCommunitytoolsjsx4,
        handleCommunitytoolsjsx5
      })(id, ...args);
    }
    return <div className="grid" style={{ marginTop: 24 }}>
      <window.UI.ActionStatus action={actionState} />
      <details>
        <summary>Community groups</summary>
        <Card style={{ padding: 20, marginTop: 14 }}>
          <div className="flex">
            <input
              aria-label="Community group name"
              placeholder="Group name"
              className="fill"
              value={group}
              onChange={e => setGroup(e.target.value)}
            />
            <Btn p disabled={!group.trim()} onClick={event => dispatch('community-tools.1', event)}>Create group</Btn>
          </div>
          {!groups.length && <p className="muted">No community groups returned.</p>}
          {groups.map(g => <div className="row" key={g.id}>
            <div className="spread">
              <h3>{g.name}</h3>
              <Chip>{(g.members || []).length} members</Chip>
            </div>
            <p className="muted">Owner · {g.owner} · {g.status}</p>
            <div className="flex" style={{ marginTop: 12 }}>
              <input
                aria-label={'Invite member to ' + g.name}
                type="email"
                placeholder="Colleague’s email"
                value={invite}
                onChange={e => setInvite(e.target.value)}
              />
              <Btn sm disabled={!invite.includes('@')} onClick={event => dispatch('community-tools.2', g, event)}>Invite member</Btn>
            </div>
            {(g.invites || []).map(r => <div className="spread row" key={r.id}>
              <span>{r.email} · {r.status}</span>
              <Btn sm disabled={r.status === 'Revoked'} onClick={event => dispatch('community-tools.3', g, r, event)}>Revoke invitation</Btn>
            </div>)}
          </div>)}
          <h3 style={{ marginTop: 20 }}>Community invitation</h3>
          <p className="muted">No verified invitation · account {s.profile?.email || s.profile?.name || 'Unassigned'}</p>
          <Chip>{c.joinStatus}</Chip>
          <div className="flex" style={{ marginTop: 12 }}>
            <Btn sm onClick={event => dispatch('community-tools.4', event)}>Verify invitation</Btn>
            <Btn p disabled={c.joinStatus !== 'Verified · account matches'} onClick={event => dispatch('community-tools.5', event)}>Join group</Btn>
          </div>
        </Card>
      </details>
    </div>;
  }
  window.UI.CommunityTools = CommunityTools;
})();
