// Full node surfaces reuse the supplied page, Card, parameter and table grammar.
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
      Heading,
      Table,

    } = window.UI,
    Icon = window.AHIcon;
  function GraphManager() {
    const s = useData(),
      u = useApp(),
      [name, setName] = React.useState('');
    return <div className="grid">{[...s.graphs].sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned)).map(g => <Card key={g.id} style={{
        padding: 14
      }}><div className="spread"><button className="button-reset fill" style={{
            textAlign: 'left'
          }} onClick={event => executeAction("projects.project-tools.AsyncAwaitUActApi.1", {api,g,u}, event)}><b>{g.pinned ? '★ ' : ''}{g.name}</b><p className="muted">{g.nodes?.length ?? '—'} nodes · {g.workspaceIds?.length || 0} workspaces</p></button><Btn sm title={'Pin ' + g.name} aria-label={'Pin ' + g.name} onClick={event => executeAction("projects.project-tools.UActApiUpdateGraphG.2", {api,g,u}, event)}><Icon name="pin" size={15} /></Btn><Btn sm title={'Rename ' + g.name} aria-label={'Rename ' + g.name} onClick={event => executeAction("projects.project-tools.UShowRenameGraphId.3", {g,u}, event)}><Icon name="edit" size={15} /></Btn><Btn sm title={'Remove ' + g.name} aria-label={'Remove ' + g.name} onClick={event => executeAction("projects.project-tools.UConfirmRemoveGName.4", {api,g,u}, event)}><Icon name="trash" size={15} /></Btn></div></Card>)}<label className="grid">New graph<input aria-label="New graph name" value={name} onChange={e => setName(e.target.value)} /></label><Btn p disabled={!name.trim()} onClick={event => executeAction("projects.project-tools.AddGraph.5", {api,name,u}, event)}>Add graph</Btn><div className="row spread"><h3>{s.graph.name} · history</h3><Btn sm onClick={event => executeAction("projects.project-tools.SaveVersion.6", {api,u}, event)}>Save version</Btn></div>{s.graph.versions?.map(v => <div className="row spread" key={v.id}><span>{v.name} · {v.nodes.length} nodes</span><Btn sm onClick={event => executeAction("projects.project-tools.Restore.7", {api,u,v}, event)}>Restore</Btn></div>)}<div className="flex"><Btn sm onClick={event => executeAction("projects.project-tools.ExportGraph.8", {u}, event)}>Export graph</Btn><Btn sm onClick={event => executeAction("projects.project-tools.Sync.9", {api,u}, event)}>Sync</Btn></div></div>;
  }
  function ModelReview() {
    const s = useData(),
      u = useApp(),
      [operation, setOperation] = React.useState(s.modelReview.operation);
    const operations = ['Startup Check', 'Naming Check', 'Model QA', 'Parameter Dictionary', 'Clash & Issues', 'Delivery Plan', 'IFC Export & Check', 'Library Admission'];
    return <main className="page" data-screen="model-review"><Heading title="Model review" sub="A revision-linked check, with an owner for every issue."><Btn sm onClick={event => executeAction("projects.project-tools.OpenAsNode.10", {api,operation,u}, event)}>Open as node</Btn><Btn p onClick={event => executeAction("projects.project-tools.RunCheck.11", {api,operation,u}, event)}>Run check</Btn></Heading><div className="settings-health"><span className="status-dot" />{s.graph.name} · {s.modelReview.revision ?? 'Choose a source'}</div><div className="flex" style={{
        marginBottom: 22
      }}><label className="flex">Check<select aria-label="Model check" value={operation} onChange={e => setOperation(e.target.value)}>{operations.map(x => <option key={x}>{x}</option>)}</select></label><span className="fill" /><Btn sm onClick={event => executeAction("projects.project-tools.ExportIssues.12", {u}, event)}>Export issues</Btn></div>{s.modelReview.results.length ? <><Card><Table rows={s.modelReview.results} columns={['check', 'status', 'detail', 'revision']} /></Card><Heading title="Issues" sub="Track the finding through review and closure." />{[...s.modelReview.issues].sort((a, b) => (a.type || 'Error').localeCompare(b.type || 'Error')).map(issue => <Card key={issue.id} style={{
          padding: 18,
          marginBottom: 12
        }}><div className="spread"><h3>{issue.type || (/clash|clearance/i.test(issue.title) ? 'Clash' : /missing|empty/i.test(issue.title) ? 'Missing' : 'Error')} · {issue.title}</h3><Chip c={issue.status === 'Closed' ? A.ok : A.warn}>{issue.status}</Chip></div><div className="flex" style={{
            marginTop: 16
          }}><label className="flex">Type<select aria-label="Issue type" value={issue.type || 'Error'} onChange={e => u.act(() => api.updateReviewIssue(issue.id, {
                type: e.target.value
              }))}>{['Discrepancy', 'Error', 'Clash', 'Missing'].map(x => <option key={x}>{x}</option>)}</select></label><label className="flex">Owner<select aria-label="Issue owner" value={issue.owner} onChange={e => u.act(() => api.updateReviewIssue(issue.id, {
                owner: e.target.value
              }))}>{s.people.map(p => <option key={p.id}>{p.name}</option>)}</select></label><label className="flex">Severity<select aria-label="Issue severity" value={issue.severity} onChange={e => u.act(() => api.updateReviewIssue(issue.id, {
                severity: e.target.value
              }))}>{['Low', 'Normal', 'High'].map(v => <option key={v}>{v}</option>)}</select></label><label className="flex">Status<select aria-label="Issue status" value={issue.status} onChange={e => u.act(() => api.updateReviewIssue(issue.id, {
                status: e.target.value
              }))}>{['Open', 'In review', 'Closed'].map(v => <option key={v}>{v}</option>)}</select></label></div></Card>)}</> : <Card style={{
        padding: 40,
        textAlign: 'center'
      }}><Icon name="shield" size={32} /><h2 style={{
          margin: '16px 0'
        }}>Check the model before delivery</h2><p className="muted">Choose a check to inspect its results, revision and issues.</p></Card>}<window.UI.PrototypeReview /></main>;
  }
  function Community() {
    const s = useData(),
      u = useApp(),
      [tab, setTab] = React.useState('Discover'),
      [title, setTitle] = React.useState('Checked door clearance'),
      [scope, setScope] = React.useState('Office'),
      [redact, setRedact] = React.useState(true);
    const action = window.UI.useAction();
    React.useEffect(() => { action.run(async () => { const result = await api.refreshCommunity(); return result.peers.length || result.patterns.length ? result : null; }); }, []);
    const status = <div aria-live="polite">{action.state === 'waiting' && <p role="status">Reading Community…</p>}{action.state === 'empty' && <p>No incoming patterns or subscriptions.</p>}{action.state === 'loaded' && <p>{s.community.peers.length} peers returned</p>}{action.state === 'error' && <div role="alert">{action.error}<Btn onClick={event => executeAction("projects.project-tools.RetryCommunity", {action}, event)}>Retry</Btn></div>}</div>;
    return <main className="page" data-screen="community">{status}<Heading title="Community" sub="Share reusable knowledge with clear sources and boundaries."><Btn sm onClick={event => executeAction("projects.project-tools.Brain.13", {u}, event)}>Brain</Btn></Heading><div className="social-tabs" style={{
        marginBottom: 22
      }}>{['Discover', 'Shared', 'Review'].map(t => <button key={t} aria-pressed={tab === t} onClick={event => executeAction("projects.project-tools.SetTabT.14", {setTab,t}, event)}>{t}</button>)}</div>{tab === 'Discover' ? <div className="settings-grid"><Card style={{
          padding: 22
        }}><h2>Knowledge networks</h2>{s.community.peers.map(p => <div className="row spread" key={p.id}><div><h3>{p.name}</h3><small className="muted">Verified patterns · no raw project models</small></div><D.Toggle label={'Subscribe ' + p.name} checked={p.subscribed} onCheckedChange={() => u.act(() => api.subscribeCommunity(p.id))} /></div>)}</Card><Card style={{
          padding: 22
        }}><h2>Share a pattern</h2><label className="grid" style={{
            marginTop: 16
          }}>Pattern<input aria-label="Pattern title" value={title} onChange={e => setTitle(e.target.value)} /></label><label className="grid" style={{
            marginTop: 14
          }}>Audience<select aria-label="Share audience" value={scope} onChange={e => setScope(e.target.value)}><option>Office</option><option>Community</option></select></label><div className="spread row"><span>Remove client details</span><D.Toggle label="Remove client details" checked={redact} onCheckedChange={setRedact} /></div><Btn p disabled={!title.trim()} onClick={event => executeAction("projects.project-tools.ReviewShare.15", {api,redact,scope,title,u}, event)}>Review share</Btn></Card></div> : tab === 'Shared' ? <div className="grid">{s.community.shared.length ? s.community.shared.map(p => <Card key={p.id} style={{
          padding: 22
        }}><div className="spread"><h2>{p.title}</h2><Chip c={A.ok}>{p.status}</Chip></div><p className="muted">{p.scope} · {p.redact ? 'Client details removed' : 'Includes source details'}</p><small>{p.source}</small></Card>) : <Card style={{
          padding: 32
        }}>Your reviewed patterns appear here after sharing.</Card>}</div> : <div className="grid">{s.community.patterns.map(p => <Card key={p.id} style={{
          padding: 22
        }}><div className="spread"><h2>{p.title}</h2><Chip c={p.status === 'Accepted' ? A.ok : A.warn}>{p.stale ? 'Needs recheck' : p.status}</Chip></div><p style={{
            margin: '14px 0'
          }}>{p.description}</p><p className="muted">Source: {p.source} · Evidence confidence: {Math.round(p.confidence * 100)}%</p><div className="flex" style={{
            marginTop: 18
          }}>{['Accept', 'Quarantine', 'Reject', 'Recheck'].map(d => <Btn key={d} sm p={d === 'Accept'} onClick={event => executeAction("projects.project-tools.UActApiReviewCommunityPatternP.16", {api,d,p,u}, event)}>{d}</Btn>)}</div></Card>)}</div>}<window.UI.CommunityTools /></main>;
  }
  function InterfaceStudio() {
    const s = useData(),
      u = useApp(),
      nodes = s.graph.nodes.filter(n => n.kind === 'UI element'),
      [id, setId] = React.useState(null),
      [colour, setColour] = React.useState(A.accent),
      selected = nodes.find(n => n.id === id);
    return <main className="page" data-screen="interface"><Heading title="Interface studio" sub="Build the view from editable nodes, then reuse it as a mod."><Btn sm onClick={event => executeAction("projects.project-tools.Canvas.17", {u}, event)}>Canvas</Btn><Btn p onClick={event => executeAction("projects.project-tools.MakeAMod.18", {u}, event)}>Make a mod</Btn></Heading><div className="settings-grid"><Card style={{
          padding: 22
        }}><h2>Elements</h2><div className="flex" style={{
            margin: '18px 0'
          }}>{['Button', 'Card', 'Text'].map(kind => <Btn sm key={kind} onClick={event => executeAction("projects.project-tools.Add.19", {api,kind,setId,u}, event)}>Add {kind}</Btn>)}</div>{nodes.map(n => <button key={n.id} className="listbutton spread" aria-pressed={n.id === id} onClick={event => executeAction("projects.project-tools.SetIdNId.20", {n,setId}, event)}><span>{n.params.element} · {n.params.label}</span><Icon name="arrow" size={14} /></button>)}{selected && <div className="grid" style={{
            marginTop: 20
          }}>{api.getNodeParameters(selected).map(p => <label key={p.key} className="parameter-row"><span>{p.label}</span>{p.type === 'boolean' ? <D.Toggle label={p.label} checked={selected.params[p.key]} onCheckedChange={v => u.act(() => api.setNodeParam(id, p.key, v))} /> : p.options ? <select aria-label={'Element ' + p.label} value={selected.params[p.key]} onChange={e => u.act(() => api.setNodeParam(id, p.key, e.target.value))}>{p.options.map(v => <option key={v}>{v}</option>)}</select> : <input aria-label={'Element ' + p.label} type={p.type === 'number' ? 'number' : p.type === 'color' ? 'color' : 'text'} value={selected.params[p.key]} onChange={e => u.act(() => api.setNodeParam(id, p.key, p.type === 'number' ? Number(e.target.value) : e.target.value))} />}</label>)}<Btn sm onClick={event => executeAction("projects.project-tools.DeleteElement.21", {api,id,u}, event)}>Delete element</Btn></div>}<div className="row"><h3>Theme</h3><div className="spread" style={{
              marginTop: 14
            }}><input aria-label="Interface accent" type="color" value={colour} onChange={e => setColour(e.target.value)} /><Btn onClick={event => executeAction("projects.project-tools.ApplyColour.22", {api,colour,u}, event)}>Apply colour</Btn></div></div></Card><Card style={{
          padding: 22,
          minHeight: 450
        }}><div className="spread"><h2>Live view</h2><Chip>{nodes.length} elements</Chip></div><div style={{
            position: 'relative',
            height: 420,
            overflow: 'auto',
            marginTop: 18,
            border: '1px dashed ' + A.line,
            borderRadius: 12
          }} onDragOver={e => e.preventDefault()} onDrop={e => {
            e.preventDefault();
            const node = e.dataTransfer.getData('ui-element');
            if (node) {
              const r = e.currentTarget.getBoundingClientRect();
              u.act(() => api.moveNode(node, {
                x: Math.max(0, e.clientX - r.left - 50),
                y: Math.max(0, e.clientY - r.top - 15)
              }));
            }
          }}>{nodes.map(n => <div key={n.id} draggable onDragStart={e => e.dataTransfer.setData('ui-element', n.id)} onClick={() => setId(n.id)} style={{
              position: 'absolute',
              left: n.x,
              top: n.y,
              width: Math.min(360, n.params.width),
              outline: id === n.id ? '1px solid ' + A.accent : 'none',
              borderRadius: 8,
              padding: 6
            }}>{n.params.element === 'Button' ? <button disabled={!n.params.enabled} onClick={event => executeAction("projects.project-tools.UGoNParamsAction.23", {n,u}, event)} style={{
                background: n.params.colour,
                border: 0,
                color: '#fff',
                padding: '10px 18px',
                borderRadius: 8
              }}>{n.params.label}</button> : n.params.element === 'Card' ? <Card style={{
                padding: 22,
                borderColor: n.params.colour
              }}>{n.params.label}</Card> : <p style={{
                color: n.params.colour
              }}>{n.params.label}</p>}</div>)}</div></Card></div></main>;
  }
  function AccountUsage() {
    const s = useData(),
      u = useApp();
    const [requestState,setRequestState]=React.useState(s.profile.signedIn?'waiting':'empty');
    const [failure,setFailure]=React.useState('');
    const refresh=()=>{
      setRequestState('waiting');
      return api.refreshCompany().then(()=>setRequestState('loaded'))
        .catch(error=>{setFailure(error.message);setRequestState('error');});
    };
    React.useEffect(() => { if(s.profile.signedIn) refresh();else setRequestState('empty'); }, [s.profile.signedIn]);
    const body = <section style={{
      marginTop: 24
    }}><Heading title="Usage & office" sub="Your account, seats and subscription stay together." /><div className="settings-grid"><Card style={{
          padding: 22
        }}><h2>Your office</h2><div className="row spread"><span>Node runs this session</span><b>{s.runs.length}</b></div><div className="row spread"><span>Plan</span><b>{s.profile.plan}</b></div><div className="row spread"><span>Office seats</span><input aria-label="Office seats" type="number" min={s.people.length} key={s.usage.seats} defaultValue={s.usage.seats || ''} disabled={!s.profile.signedIn} onBlur={e => { const seats=Number(e.target.value); e.target.value=String(s.usage.seats || ''); if(seats !== s.usage.seats) u.confirm('Update office subscription to ' + seats + ' seats?', () => api.setAccountSeats(seats)); }} /></div><Btn sm onClick={event => executeAction("projects.project-tools.ManageSubscription.24", {u}, event)}>Manage subscription</Btn></Card><Card style={{
          padding: 22
        }}><h2>Account security</h2><p className="muted" style={{
            margin: '14px 0'
          }}>Sign out of connected sessions without changing your office’s data.</p><Btn sm onClick={event => executeAction("projects.project-tools.SignOutEverywhere.25", {api,u}, event)}>Sign out everywhere</Btn><div className="row"><h3>Transfer office ownership</h3>{s.people.filter(p => p.id !== s.profile.id).map(p => <div className="spread row" key={p.id}><span>{p.name} · {p.accessRole || 'Member'}</span><Btn sm onClick={event => executeAction("projects.project-tools.Transfer.26", {api,p,u}, event)}>Transfer</Btn></div>)}</div></Card></div></section>;
    return <>
      {requestState==='waiting'&&<p role="status">Reading your office account…</p>}
      {requestState==='error'&&<div role="alert">{failure}<Btn onClick={event=>executeAction('projects.controls.activate',{handler:refresh},event)}>Retry office</Btn></div>}
      {requestState==='empty'&&<><Btn onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(api.signIn)},event)}>Sign in</Btn>{body}</>}
      {requestState==='loaded'&&<>{body}</>}
    </>;
  }
  Object.assign(window.UI, {
    GraphManager,
    ModelReview,
    Community,
    InterfaceStudio,
    AccountUsage
  });

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsprojecttoolsjsxAsyncAwaitUActApi1({api,g,u}, event) {
  const handler = async () => {
            const result = await u.act(() => api.selectGraph(g.id));
            if (result) u.go('canvas');
          };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxUActApiUpdateGraphG2({api,g,u}, event) {
  const handler = () => u.act(() => api.updateGraph(g.id, {
            pinned: !g.pinned
          }));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxUShowRenameGraphId3({g,u}, event) {
  const handler = () => u.show('Rename graph', {
            id: g.id,
            text: g.name
          });
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxUConfirmRemoveGName4({api,g,u}, event) {
  const handler = () => u.confirm('Remove ' + g.name + '?', () => api.removeGraph(g.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxAddGraph5({api,name,u}, event) {
  const handler = async () => {
        const result = await u.act(() => api.addGraph(name));
        if (result) u.go('canvas');
      };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxSaveVersion6({api,u}, event) {
  const handler = () => u.act(api.saveGraphVersion);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxRestore7({api,u,v}, event) {
  const handler = async () => {
          const result = await u.act(() => api.restoreGraphVersion(v.id));
          if (result) u.go('canvas');
        };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxExportGraph8({u}, event) {
  const handler = () => u.download('Graph');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxSync9({api,u}, event) {
  const handler = () => u.act(api.syncAccount);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxOpenAsNode10({api,operation,u}, event) {
  const handler = async () => {
          const result = await u.act(() => api.addNode('TBP ' + operation));
          if (result) u.go('canvas');
        };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxRunCheck11({api,operation,u}, event) {
  const handler = () => u.act(() => api.reviewModel(operation));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxExportIssues12({u}, event) {
  const handler = () => u.download('Issues');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxBrain13({u}, event) {
  const handler = () => u.go('brain');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxSetTabT14({setTab,t}, event) {
  const handler = () => setTab(t);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxReviewShare15({api,redact,scope,title,u}, event) {
  const handler = async () => {
            const c = await u.act(() => api.proposeCommunityShare({
              title,
              scope,
              redact
            }));
            if (c) u.go('workshop');
          };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxUActApiReviewCommunityPatternP16({api,d,p,u}, event) {
  const handler = async () => { const result = await u.act(() => api.reviewCommunityPattern(p.id, d)); if (d === 'Recheck' && result) u.go('workshop'); };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxCanvas17({u}, event) {
  const handler = () => u.go('canvas');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxMakeAMod18({u}, event) {
  const handler = () => u.show('Make a mod');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxAdd19({api,kind,setId,u}, event) {
  const handler = async () => {
              const n = await u.act(() => api.addInterfaceElement(kind));
              if (n) setId(n.id);
            };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxSetIdNId20({n,setId}, event) {
  const handler = () => setId(n.id);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxDeleteElement21({api,id,u}, event) {
  const handler = () => u.act(() => api.deleteNode(id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxApplyColour22({api,colour,u}, event) {
  const handler = () => u.act(() => api.setSetting('Appearance.Accent colour', colour));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxUGoNParamsAction23({n,u}, event) {
  const handler = () => u.go(n.params.action.toLowerCase());
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxManageSubscription24({u}, event) {
  const handler = () => u.show('Subscription');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxSignOutEverywhere25({api,u}, event) {
  const handler = () => u.confirm('Sign out of all sessions?', () => api.signOutEverywhere());
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxTransfer26({api,p,u}, event) {
  const handler = () => u.confirm('Make ' + p.name + ' the office owner?', () => api.transferOwnership(p.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsprojecttoolsjsxRetryCommunity({action}) { return action.retry(); }
const PROJECT_ACTIONS = {
  "projects.project-tools.RetryCommunity": "projectsprojecttoolsjsxRetryCommunity",
  "projects.project-tools.AsyncAwaitUActApi.1": "projectsprojecttoolsjsxAsyncAwaitUActApi1",
  "projects.project-tools.UActApiUpdateGraphG.2": "projectsprojecttoolsjsxUActApiUpdateGraphG2",
  "projects.project-tools.UShowRenameGraphId.3": "projectsprojecttoolsjsxUShowRenameGraphId3",
  "projects.project-tools.UConfirmRemoveGName.4": "projectsprojecttoolsjsxUConfirmRemoveGName4",
  "projects.project-tools.AddGraph.5": "projectsprojecttoolsjsxAddGraph5",
  "projects.project-tools.SaveVersion.6": "projectsprojecttoolsjsxSaveVersion6",
  "projects.project-tools.Restore.7": "projectsprojecttoolsjsxRestore7",
  "projects.project-tools.ExportGraph.8": "projectsprojecttoolsjsxExportGraph8",
  "projects.project-tools.Sync.9": "projectsprojecttoolsjsxSync9",
  "projects.project-tools.OpenAsNode.10": "projectsprojecttoolsjsxOpenAsNode10",
  "projects.project-tools.RunCheck.11": "projectsprojecttoolsjsxRunCheck11",
  "projects.project-tools.ExportIssues.12": "projectsprojecttoolsjsxExportIssues12",
  "projects.project-tools.Brain.13": "projectsprojecttoolsjsxBrain13",
  "projects.project-tools.SetTabT.14": "projectsprojecttoolsjsxSetTabT14",
  "projects.project-tools.ReviewShare.15": "projectsprojecttoolsjsxReviewShare15",
  "projects.project-tools.UActApiReviewCommunityPatternP.16": "projectsprojecttoolsjsxUActApiReviewCommunityPatternP16",
  "projects.project-tools.Canvas.17": "projectsprojecttoolsjsxCanvas17",
  "projects.project-tools.MakeAMod.18": "projectsprojecttoolsjsxMakeAMod18",
  "projects.project-tools.Add.19": "projectsprojecttoolsjsxAdd19",
  "projects.project-tools.SetIdNId.20": "projectsprojecttoolsjsxSetIdNId20",
  "projects.project-tools.DeleteElement.21": "projectsprojecttoolsjsxDeleteElement21",
  "projects.project-tools.ApplyColour.22": "projectsprojecttoolsjsxApplyColour22",
  "projects.project-tools.UGoNParamsAction.23": "projectsprojecttoolsjsxUGoNParamsAction23",
  "projects.project-tools.ManageSubscription.24": "projectsprojecttoolsjsxManageSubscription24",
  "projects.project-tools.SignOutEverywhere.25": "projectsprojecttoolsjsxSignOutEverywhere25",
  "projects.project-tools.Transfer.26": "projectsprojecttoolsjsxTransfer26"
};
window.registerActions(PROJECT_ACTIONS, {projectsprojecttoolsjsxRetryCommunity,projectsprojecttoolsjsxAsyncAwaitUActApi1,projectsprojecttoolsjsxUActApiUpdateGraphG2,projectsprojecttoolsjsxUShowRenameGraphId3,projectsprojecttoolsjsxUConfirmRemoveGName4,projectsprojecttoolsjsxAddGraph5,projectsprojecttoolsjsxSaveVersion6,projectsprojecttoolsjsxRestore7,projectsprojecttoolsjsxExportGraph8,projectsprojecttoolsjsxSync9,projectsprojecttoolsjsxOpenAsNode10,projectsprojecttoolsjsxRunCheck11,projectsprojecttoolsjsxExportIssues12,projectsprojecttoolsjsxBrain13,projectsprojecttoolsjsxSetTabT14,projectsprojecttoolsjsxReviewShare15,projectsprojecttoolsjsxUActApiReviewCommunityPatternP16,projectsprojecttoolsjsxCanvas17,projectsprojecttoolsjsxMakeAMod18,projectsprojecttoolsjsxAdd19,projectsprojecttoolsjsxSetIdNId20,projectsprojecttoolsjsxDeleteElement21,projectsprojecttoolsjsxApplyColour22,projectsprojecttoolsjsxUGoNParamsAction23,projectsprojecttoolsjsxManageSubscription24,projectsprojecttoolsjsxSignOutEverywhere25,projectsprojecttoolsjsxTransfer26});
})();
