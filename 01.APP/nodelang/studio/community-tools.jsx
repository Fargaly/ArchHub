(() => {
  const {
    api,
    useData,
    useApp,
    Btn,
    Card,
    Chip,
    Table
  } = window.UI;
  function CommunityTools() {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction(),
      c = s.community,
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
    function handleCommunitytoolsjsx6(r) {
      return actionState.run(() => api.installMarketplaceItem(r.id));
    }
    async function handleCommunitytoolsjsx7() {
      const a = await actionState.run(api.proposeMarketplaceListing);
      if (a) u.show('Approve', {
        id: a.id
      });
    }
    async function handleCommunitytoolsjsx8() {
      const a = await actionState.run(api.proposeProjectCharge);
      if (a) u.show('Approve', {
        id: a.id
      });
    }
    const ACTIONS = {
      "community-tools.1": "handleCommunitytoolsjsx1",
      "community-tools.2": "handleCommunitytoolsjsx2",
      "community-tools.3": "handleCommunitytoolsjsx3",
      "community-tools.4": "handleCommunitytoolsjsx4",
      "community-tools.5": "handleCommunitytoolsjsx5",
      "community-tools.6": "handleCommunitytoolsjsx6",
      "community-tools.7": "handleCommunitytoolsjsx7",
      "community-tools.8": "handleCommunitytoolsjsx8"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleCommunitytoolsjsx1,
        handleCommunitytoolsjsx2,
        handleCommunitytoolsjsx3,
        handleCommunitytoolsjsx4,
        handleCommunitytoolsjsx5,
        handleCommunitytoolsjsx6,
        handleCommunitytoolsjsx7,
        handleCommunitytoolsjsx8
      })(id, ...args);
    }
    return <div className="grid" style={{
      marginTop: 24
    }}><window.UI.ActionStatus action={actionState} /><details><summary>Community groups</summary><Card style={{
          padding: 20,
          marginTop: 14
        }}><div className="flex"><input aria-label="Community group name" placeholder="Group name" className="fill" value={group} onChange={(e) => setGroup(e.target.value)} /><Btn p disabled={!group.trim()} onClick={(event) => dispatch("community-tools.1", event)}>Create group</Btn></div>{!c.groups.length && <p className="muted">No community groups returned.</p>}{c.groups.map((g) => <div className="row" key={g.id}><div className="spread"><h3>{g.name}</h3><Chip>{g.members.length} members</Chip></div><p className="muted">Owner · {g.owner} · {g.status}</p><div className="flex" style={{
              marginTop: 12
            }}><input aria-label={'Invite member to ' + g.name} type="email" placeholder="Colleague’s email" value={invite} onChange={(e) => setInvite(e.target.value)} /><Btn sm disabled={!invite.includes('@')} onClick={(event) => dispatch("community-tools.2", g, event)}>Invite member</Btn></div>{g.invites.map((r) => <div className="spread row" key={r.id}><span>{r.email} · {r.status}</span><Btn sm disabled={r.status === 'Revoked'} onClick={(event) => dispatch("community-tools.3", g, r, event)}>Revoke invitation</Btn></div>)}</div>)}<h3 style={{
            marginTop: 20
          }}>Community invitation</h3><p className="muted">No verified invitation · account {s.profile.email || s.profile.name || 'Unassigned'}</p><Chip>{c.joinStatus}</Chip><div className="flex" style={{
            marginTop: 12
          }}><Btn sm onClick={(event) => dispatch("community-tools.4", event)}>Verify invitation</Btn><Btn p disabled={c.joinStatus !== 'Verified · account matches'} onClick={(event) => dispatch("community-tools.5", event)}>Join group</Btn></div></Card></details><details><summary>Marketplace · shared nodes, skills &amp; templates</summary><Card style={{
          padding: 20,
          marginTop: 14
        }}><input aria-label="Search marketplace" placeholder="Find a node, skill or template…" value={c.marketQuery} onChange={(e) => actionState.run(() => api.setMarketplace({
            marketQuery: e.target.value
          }))} /><div className="reference-grid" style={{
            marginTop: 16
          }}>{c.marketplace.filter((r) => r.name.toLowerCase().includes(c.marketQuery.toLowerCase())).map((r) => <Card key={r.id} style={{
              padding: 18
            }}><div className="spread"><h3>{r.name}</h3><Chip>{r.kind}</Chip></div><p className="muted">{r.author} · {r.license}</p><p style={{
                margin: '12px 0'
              }}>{r.description}</p><div className="spread"><b>{r.price ? '$' + r.price : 'Free'}</b><Btn sm disabled={r.installed} onClick={(event) => dispatch("community-tools.6", r, event)}>{r.installed ? 'In Library' : 'Add to Library'}</Btn></div></Card>)}</div><details style={{
            marginTop: 20
          }}><summary>Publish a listing</summary><div className="grid" style={{
              marginTop: 12
            }}><label>Node, skill or template<input aria-label="Listing title" value={c.listing.title} onChange={(e) => actionState.run(() => api.setMarketplace({
                  listing: {
                    ...c.listing,
                    title: e.target.value
                  }
                }))} /></label><label>Price · USD<input aria-label="Listing price" type="number" min="0" value={c.listing.price} onChange={(e) => actionState.run(() => api.setMarketplace({
                  listing: {
                    ...c.listing,
                    price: Number(e.target.value)
                  }
                }))} /></label><label>Creator share · %<input aria-label="Creator revenue share" type="number" min="0" max="100" value={c.listing.creatorShare} onChange={(e) => actionState.run(() => api.setMarketplace({
                  listing: {
                    ...c.listing,
                    creatorShare: Number(e.target.value)
                  }
                }))} /></label><small className="muted">Platform share · {100 - c.listing.creatorShare}%. Charges require owner review before collection.</small><Btn p disabled={!c.listing.title.trim()} onClick={(event) => dispatch("community-tools.7", event)}>Review listing</Btn></div></details></Card></details><details><summary>Client project charges</summary><Card style={{
          padding: 20,
          marginTop: 14
        }}><p className="muted">Prepare a reviewed project or workflow-run charge. Collection requires owner review.</p>{[['client', 'Client'], ['project', 'Project'], ['basis', 'Charge basis'], ['amount', 'Amount · USD']].map(([key, label]) => <label className="parameter-row" key={key}><span>{label}</span>{key === 'basis' ? <select aria-label={label} value={c.charge[key]} onChange={(e) => actionState.run(() => api.setProjectCharge({
              [key]: e.target.value
            }))}>{['Per project', 'Per workflow run'].map((x) => <option key={x}>{x}</option>)}</select> : <input aria-label={label} type={key === 'amount' ? 'number' : 'text'} min={key === 'amount' ? 0 : undefined} value={c.charge[key]} onChange={(e) => actionState.run(() => api.setProjectCharge({
              [key]: key === 'amount' ? Number(e.target.value) : e.target.value
            }))} />}</label>)}<Btn p onClick={(event) => dispatch("community-tools.8", event)}>Review charge</Btn>{c.charges.length > 0 && <Table rows={c.charges} columns={['client', 'project', 'basis', 'amount', 'status']} />}</Card></details></div>;
  }
  window.UI.CommunityTools = CommunityTools;
})();
