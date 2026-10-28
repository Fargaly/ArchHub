(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
      D,
      api,
      useData,
      useApp,
      Btn,
      Card,
      Chip,
      Heading,
      Table
    } = window.UI,
    Icon = window.AHIcon;
  function XrayLayers() {
    const s = useData(),
      u = useApp(),
      layer = s.learning.layer,
      values = s.learning.layers[layer];
    return <Card style={{
      padding: 22,
      marginTop: 22
    }}><Heading title="Six ways to learn" sub="The same workflow can learn from a program, your habits, an intent or a completed session." /><div className="social-tabs">{Object.keys(s.learning.layers).map(l => <button key={l} aria-pressed={layer === l} onClick={() => executeAction("setLearningLayer", u, l)}>{l}</button>)}</div><div className="settings-grid" style={{
        marginTop: 18
      }}>{Object.entries(values).map(([key, value]) => <label className="parameter-row" key={key}><span>{key.replace(/([A-Z])/g, ' $1').replace(/^./, c => c.toUpperCase())}</span>{typeof value === 'boolean' ? <D.Toggle label={layer + ' ' + key} checked={value} onCheckedChange={v => executeAction("setLearningLayer", u, layer, {
            [key]: v
          })} /> : <input aria-label={layer + ' ' + key} type={typeof value === 'number' ? 'number' : 'text'} value={value} onChange={e => executeAction("setLearningLayer", u, layer, {
            [key]: typeof value === 'number' ? Number(e.target.value) : e.target.value
          })} />}</label>)}</div></Card>;
  }
  function HealthHistory() {
    const s = useData(),
      [rows, setRows] = React.useState([]),
      [error, setError] = React.useState(''),
      [status, setStatus] = React.useState('waiting'),
      [attempt, setAttempt] = React.useState(0);
    React.useEffect(() => {
      let active = true;
      setStatus('waiting');
      api.getHealthHistory().then(value => {
        if (active) {
          if (!Array.isArray(value)) throw Error(value?.message || 'History response is invalid. Retry.');
          setRows(value);
          setError('');
          setStatus(value.length ? 'loaded' : 'empty');
        }
      }).catch(error => {
        if (active) {
          setError(error.message || 'Connection history unavailable');
          setStatus('error');
        }
      });
      return () => {
        active = false;
      };
    }, [s.revision, attempt]);
    return <Card style={{
      padding: 22,
      marginTop: 22
    }}><Heading title="Connection history" sub="Checks, errors and the next repair, per program or provider." />{status === 'waiting' && <p role="status">Reading connection history…</p>}{status === 'error' && <div role="alert">{error}<Btn sm onClick={() => executeAction("ui.state", setAttempt, n => n + 1)}>Retry history</Btn></div>}{status === 'loaded' && <Table rows={rows} columns={['source', 'checks', 'errors', 'status']} />}{status === 'empty' && <p className="muted">Check a connection or routing attempt to see its history here.</p>}</Card>;
  }
  function ScheduleResponsibility({
    id
  }) {
    const s = useData(),
      u = useApp(),
      r = s.schedules.find(t => t.id === id);
    return r ? <div className="grid" style={{
      marginTop: 16
    }}>{r.lastResult && <p role="status">Last run: {r.lastResult.status}{r.lastResult.error ? " · " + r.lastResult.error : ""}</p>}<label className="grid">Operation{api.supportsAction?.('setScheduleResponsibility') !== false && <select aria-label={'Scheduled operation ' + r.title} value={r.operation || 'Workflow'} onChange={e => executeAction("setScheduleResponsibility", u, id, {
          operation: e.target.value
        })}>{['Workflow'].map(x => <option key={x}>{x}</option>)}</select>}</label><label className="grid">Responsibility{api.supportsAction?.('setScheduleResponsibility') !== false && <input aria-label={'Responsibility ' + r.title} value={r.responsibility || ''} onChange={e => executeAction("setScheduleResponsibility", u, id, {
          responsibility: e.target.value
        })} />}</label><div className="spread"><span>Self-review after each run</span>{api.supportsAction?.('setScheduleResponsibility') !== false && <D.Toggle label={'Self-review ' + r.title} checked={r.selfReview !== false} onCheckedChange={v => executeAction("setScheduleResponsibility", u, id, {
          selfReview: v
        })} />}</div>{api.supportsAction?.('reviewScheduledWork') !== false && <Btn sm onClick={async () => {
        const c = await executeAction("reviewScheduledWork", u, id);
        if (c) executeAction("ui.show", u, 'Approve', {
          id: c.id
        });
      }}>Review lesson</Btn>}</div> : null;
  }
  function NodeDetails({
    id
  }) {
    const s = useData(),
      u = useApp(),
      n = s.graph.nodes.find(n => n.id === id);
    if (!n) return null;
    return <div className="grid"><h2>{n.title}</h2><p className="muted">{s.catalogue.find(c => c.name === n.kind)?.description || 'An editable part of your workflow.'}</p><Chip>{n.frozen ? 'Frozen' : n.status}</Chip><Table rows={api.getNodeParameters(n).map(p => ({
        parameter: p.label,
        type: p.type,
        value: typeof n.params[p.key]==='object' ? JSON.stringify(n.params[p.key]) : String(n.params[p.key]),
        unit: p.unit
      }))} /><div className="flex"><Btn p onClick={() => {
          executeAction("ui.setSelectedNodeId", u, id);
          executeAction("ui.go", u, 'canvas');
        }}>Open properties</Btn><Btn sm onClick={() => executeAction("ui.show", u, 'Node output', {
          id
        })}>View output</Btn></div></div>;
  }
  function ReviewDetails({
    taskId
  }) {
    const s = useData(),
      u = useApp(),
      t = s.tasks.find(t => t.id === taskId),
      [scope, setScope] = React.useState('All changes'),
      [comment, setComment] = React.useState('');
    return t ? <Card style={{
      padding: 18
    }}><div className="spread"><h3>Review scope</h3><select aria-label="Review scope" value={scope} onChange={e => setScope(e.target.value)}>{['All changes', 'This file', 'Selected lines', 'Last turn'].map(v => <option key={v}>{v}</option>)}</select></div><div className="grid" style={{
        marginTop: 14
      }}><label className="grid">Plan mode<select aria-label="Plan mode" value={t.planMode || 'Confirm each step'} onChange={e => executeAction("setTaskPlanMode", u, taskId, e.target.value)}>{['Run on its own', 'Confirm each step', 'Keep planning'].map(v => <option key={v}>{v}</option>)}</select></label><textarea aria-label="Review comment" placeholder="Comment on the selected changes…" value={comment} onChange={e => setComment(e.target.value)} /><div className="flex"><Btn sm disabled={!comment.trim()} onClick={async () => {
            const saved = await executeAction("addTaskReview", u, taskId, scope, comment);
            if (saved) executeAction("ui.state", setComment, '');
          }}>Add comment</Btn><Btn sm onClick={() => executeAction("addTaskReview", u, taskId, scope, 'Accepted')}>Accept scope</Btn><Btn sm onClick={() => executeAction("addTaskReview", u, taskId, scope, 'Changes requested')}>Request changes</Btn></div>{t.reviews?.map((r, i) => <div className="spread row" style={{
          opacity: r.resolved ? .45 : 1
        }} key={i}><span>{r.scope}: {r.comment}</span><Btn sm onClick={() => executeAction("resolveTaskReview", u, taskId, i, !r.resolved)}>{r.resolved ? 'Reopen finding' : 'Resolve finding'}</Btn></div>)}</div></Card> : null;
  }
  function Steer({
    id
  }) {
    const u = useApp(),
      [text, setText] = React.useState('');
    return <Card style={{
      padding: 18
    }}><h3>Steer the work</h3><div className="flex" style={{
        marginTop: 12
      }}><input aria-label="Steer instruction" className="fill" value={text} onChange={e => setText(e.target.value)} placeholder="Keep the fire rating; change only the location." /><Btn sm disabled={!text.trim()} onClick={async () => {
          const saved = await executeAction("steerTask", u, id, text);
          if (saved) executeAction("ui.state", setText, '');
        }}>Redirect</Btn></div><div className="flex" style={{
        marginTop: 12
      }}><Btn sm onClick={() => executeAction("steerTask", u, id, 'Pause')}>Pause</Btn><Btn sm onClick={() => executeAction("steerTask", u, id, 'Continue')}>Continue</Btn></div></Card>;
  }
  function HomeAwareness() {
    const s = useData(),
      u = useApp();
    return <div className="home-awareness"><div className="spread"><span className="eyebrow">Office awareness</span><button className="icon-button" aria-label="Refresh open items" title="Refresh" onClick={() => executeAction("refreshOfficeAwareness", u)}><Icon name="refresh" size={15} /></button></div><div className="awareness-items">{[...s.officeItems].sort((a, b) => (a.when === 'Overdue' ? -1 : 1) - (b.when === 'Overdue' ? -1 : 1) || String(a.when).localeCompare(String(b.when))).map(r => <button key={r.id} onClick={() => {executeAction("ui.setTask",u,r.id);executeAction("ui.go",u,"workshop");}}><span className={'status-dot ' + (r.when === 'Overdue' ? 'attention' : '')} /><span><b>{r.title}</b><small>{r.when} · {r.owner}</small></span></button>)}</div><div className="spread row"><span className="muted">{s.officeUpdated || 'Office context ready'}</span>{api.supportsAction?.('settleTimesheet') !== false && <Btn sm onClick={() => executeAction("ui.show", u, 'Timesheet')}>Timesheet draft</Btn>}</div></div>;
  }
  Object.assign(window.UI, {
    XrayLayers,
    HealthHistory,
    ScheduleResponsibility,
    NodeDetails,
    ReviewDetails,
    Steer,
    HomeAwareness
  });
})();
