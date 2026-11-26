// Full views reached through the existing Settings doors. All use the plate
// Card/Row/Composer primitives and the same adapter records as their Settings row.
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
    Empty,
    Table
  } = window.UI;
  function Automations({
    embedded = false
  }) {
    const s = useData(),
      u = useApp();
    const paused = s.desktop?.automationsPaused;
    const [busy, setBusy] = React.useState(false);
    const body = <div className="grid">
      <div className="spread"><h2>Schedules</h2><div className="flex">
        <Btn sm disabled={typeof paused !== 'boolean' || busy} onClick={() => executeAction('projects.automations.togglePause', {api,u,paused,setBusy})}>{paused ? 'Resume all' : 'Pause all'}</Btn>
        <Btn sm onClick={event => executeAction("projects.surfaces.AddSchedule.1", {s,u}, event)}>Add schedule</Btn>
      </div></div>
      {s.schedules.length ? s.schedules.map(t => <Card key={t.id} style={{padding: 16}}>
        <div className="spread"><div>
          <h3><button type="button" className="button-reset" onClick={event => executeAction('projects.surfaces.OpenTaskCanvas', {t,u}, event)}>{t.title}</button></h3>
          <p className="muted">{!t.enabled ? 'Off · ' : paused ? 'Paused · ' : ''}{t.daily ? 'Daily at ' + t.time : t.time}</p>
        </div><div className="flex">
          {t.daily && <input aria-label={'Time ' + t.title} type="time" value={t.time} onChange={e => u.act(() => api.setScheduleTime(t.id, e.target.value))} />}
          <D.Toggle label={t.title + ' schedule'} checked={t.enabled} onCheckedChange={v => u.act(() => api.setScheduleEnabled(t.id, v))} />
          <Btn sm onClick={event => executeAction("projects.surfaces.Reset.2", {api,t,u}, event)}>Reset</Btn>
        </div></div>
        <window.UI.ScheduleResponsibility id={t.id} />
      </Card>) : <Empty>No schedules yet. Repeat a task when you want it to run again.</Empty>}
      <Card style={{
        padding: 16
      }}><h3>Triggers</h3><div className="flex" style={{
          marginTop: 12,
          flexWrap: 'wrap'
        }}>{['Manual', 'Schedule', 'File changed', 'Host event', 'Approval granted', 'Webhook'].map(t => <Btn key={t} sm onClick={event => executeAction("projects.surfaces.AsyncConstNAwaitU.3", {api,t,u}, event)}>{t}</Btn>)}</div></Card></div>;
    return embedded ? body : <main className="page" data-screen="automations"><Heading title="Automations" sub="Repeat work as a node, with the same approval point" />{body}</main>;
  }
  // ArchHub menu › App health (design: archhub-directions diagDialog; "Logs & receipts" lives here, never a page).
  // Checks from their owners, and Activity from the run receipts beside every session file, notifications and the update.
  function AppHealth({close}) {
    const s = useData(),
      u = useApp(),
      [runs, setRuns] = React.useState({status: 'waiting', rows: []}),
      [attempt, setAttempt] = React.useState(0);
    React.useEffect(() => {
      let current = true;
      setRuns(held => ({...held, status: 'waiting'}));
      api.readHostAvailability?.().catch(() => null);
      api.listAgentsWorking?.().catch(() => null);
      api.recentRuns(60).then(rows => { if (current) setRuns({status: (rows || []).length ? 'loaded' : 'empty', rows: rows || []}); },
        error => { if (current) setRuns({status: 'error', rows: [], message: error.message || String(error)}); });
      return () => { current = false; };
    }, [attempt]);
    const agents = (s.agents || []).filter(a => a.kind !== 'observation');
    const ungated = agents.filter(a => a.gate === 'missing').map(a => a.name);
    const live = (s.hosts || []).filter(h => h.state === 'connected' || h.state === 'listening').map(h => h.name || h.id);
    const go = route => () => { close(); return u.go(route); };
    const checks = [
      [!ungated.length, 'Agent gates', ungated.length ? ungated.join(', ') + ' has no Stop gate' : agents.length + ' agents gated', ungated.length ? ['Install gates', go('settings/Agents')] : null],
      [live.length > 0, 'Programs', live.length ? live.join(', ') + ' connected' : s.hostError || 'No program connected', live.length ? null : ['Programs', go('settings/Connections')]],
      [!!s.agentSummary && !/checking|incomplete/i.test(s.agentHealth || s.agentSummary), 'Agents', s.agentSummary || 'Checking running agents…', null],
      [!!s.profile?.signedIn, 'Account', s.profile?.signedIn ? 'Signed in' : 'Not signed in', s.profile?.signedIn ? null : ['Sign in', go('settings/Account')]]
    ];
    const when = at => at ? new Date((at > 1e12 ? at : at * 1000)).toLocaleString() : '';
    const activity = [
      ...runs.rows.map(r => ({at: r.end || r.start || r.at || 0, operation: r.title || 'Canvas run', detail: [r.kind === 'manual' ? 'Run' : String(r.kind || '').replace(/^trigger\./, ''), r.error].filter(Boolean).join(' · '), status: r.state || ''})),
      ...(s.notifications || []).map(n => ({at: Date.parse(n.at || n.created_at || '') / 1000 || 0, operation: n.title || 'Notice', detail: n.text || n.body || '', status: n.read ? 'read' : 'new'})),
      ...(s.update?.updatedTo ? [{at: 0, operation: 'Update installed', detail: s.update.updatedTo, status: 'done'}] : [])
    ].sort((a, b) => b.at - a.at).map(row => ({...row, when: when(row.at)}));
    const undoName = String(s.graph?.undoLabel || s.undoLabel || '').trim();
    const report = checks.map(([ok, name, what]) => (ok ? 'OK ' : 'FIX ') + name + ': ' + what).join('\n');
    return <div className="app-health" data-design="app.health">
      <div className="diag">{checks.map(([ok, name, what, act]) => <div className="drow" key={name}><span className={ok ? 'f-ok' : 'f-warn'} aria-label={ok ? 'Healthy' : 'Needs a fix'}>{ok ? '✓' : '!'}</span><b>{name}</b><span>{what}</span>{act && <Btn sm onClick={event => executeAction('ui.select', act[1], event)}>{act[0]}</Btn>}</div>)}</div>
      <h3>Activity</h3>
      {runs.status === 'waiting' && <p role="status">Reading run receipts…</p>}
      {runs.status === 'error' && <div role="alert"><p>{runs.message}</p><Btn sm onClick={event => executeAction('ui.select', () => setAttempt(value => value + 1), event)}>Retry</Btn></div>}
      {runs.status === 'empty' && (activity.length ? <Table rows={activity.slice(0, 60)} columns={['when', 'operation', 'detail', 'status']} /> : <p className="muted">No runs, notices or updates recorded on this PC yet.</p>)}
      {runs.status === 'loaded' && <Table rows={activity.slice(0, 60)} columns={['when', 'operation', 'detail', 'status']} />}
      <div className="flex">
        <Btn sm onClick={event => executeAction('ui.select', () => navigator.clipboard?.writeText(report).then(() => u.setToast('Report copied.')), event)}>Copy report</Btn>
        <Btn sm disabled={!activity.length} onClick={event => executeAction('ui.select', () => u.download('Receipts', activity), event)}>Export</Btn>
        <Btn sm disabled={!undoName} title={undoName ? 'Undo ' + undoName : 'Nothing to undo'} onClick={event => executeAction('ui.select', () => u.act(api.undo), event)}>{undoName ? 'Undo ' + undoName : 'Nothing to undo'}</Btn>
      </div>
    </div>;
  }
  function Runs() {
    const s = useData(),
      u = useApp();
    return <main className="page" data-screen="runs"><Heading title="Runs" sub="Finished results and stopped work" /><Card>{s.runs.map(r => <div className="spread row" key={r.id}><div><h3>{r.title}</h3><p className="muted">{r.status}</p></div><div className="flex"><Btn sm onClick={event => executeAction("projects.surfaces.Open.6", {r,u}, event)}>Open</Btn><Btn sm onClick={event => executeAction("projects.surfaces.Retry.7", {api,r,u}, event)}>Retry</Btn></div></div>)}{!s.runs.length && <Empty>No runs yet. Run a node or start a task.</Empty>}</Card><div style={{
        height: 20
      }} /><Card>{s.tasks.filter(t => t.status === 'STOPPED').map(t => <div className="spread row" key={t.id}><span>{t.title} · stopped</span><Btn sm onClick={event => executeAction("projects.surfaces.Retry.8", {api,t,u}, event)}>Retry</Btn></div>)}</Card></main>;
  }
  function Feedback() {
    const s = useData(),
      u = useApp();
    const [text, setText] = React.useState('');
    return <main className="page" data-screen="feedback"><Heading title="Feedback" sub="Tell the team what should work better" /><Card style={{
        maxWidth: 800,
        padding: 22,
        display: 'grid',
        gap: 16
      }}><textarea aria-label="Your feedback" rows={5} placeholder="What happened, and what did you want?" value={text} onChange={e => setText(e.target.value)} /><Btn p disabled={!text.trim()} onClick={event => executeAction("projects.surfaces.SendFeedback.9", {api,setText,text,u}, event)}>Send feedback</Btn>{s.feedback.map(f => <div className="row" key={f.id}><p>{f.text}</p><div className="spread"><Chip c={A.ok}>{f.status}</Chip><Btn sm onClick={event => executeAction("projects.surfaces.CheckResponse.10", {api,f,u}, event)}>Check response</Btn></div>{f.response && <p className="muted">{f.response}</p>}{f.updateReady && <Btn p onClick={event => executeAction("projects.surfaces.ViewUpdate.11", {u}, event)}>View update</Btn>}</div>)}</Card></main>;
  }
  function Watcher() {
    const s=useData(),u=useApp();
    const [requestState,setRequestState]=React.useState(s.watcher.status||'empty');
    const [failure,setFailure]=React.useState('');
    const source=s.graph.nodes.find(n=>n.id===s.watcher.source||n.params.engine==='lines.watch');
    const refresh=()=>{
      setRequestState('waiting');
      return api.checkWatcherSource().then(()=>setRequestState(api.getSnapshot().watcher.status))
        .catch(error=>{setFailure(error.message);setRequestState('error');});
    };
    return <main className="page watcher-page" data-screen="watcher">
      <Heading title="Watcher" sub={source?.title||s.graph.name}>
        <Btn onClick={event=>executeAction('projects.watcher.connections',{u},event)}>Connections</Btn>
        <Btn onClick={event=>executeAction('projects.watcher.add',{api,s,u},event)}>Add Watcher</Btn>
        <Btn p onClick={event=>executeAction('projects.watcher.run',{refresh},event)}>Run to here</Btn>
      </Heading>
      {requestState==='waiting'&&<p role="status">Reading the source through its workflow…</p>}
      {requestState==='error'&&<Card><p role="alert">{failure}</p><Btn onClick={event=>executeAction('projects.watcher.run',{refresh},event)}>Retry source</Btn></Card>}
      {requestState==='empty'&&<Empty>Wire geometry into the Watcher, then run to here to inspect the source.</Empty>}
      {requestState==='loaded'&&<Card><window.UI.Sheet large /><Table rows={s.watcher.geometry.walls.map(([x1,y1,x2,y2])=>({x1,y1,x2,y2}))} columns={['x1','y1','x2','y2']} /></Card>}
      {source&&<Card>{s.settings.filter(row=>row.owner===source.id).map(row=><window.UI.SettingControl key={row.id} row={row} />)}</Card>}
    </main>;
  }
  Object.assign(window.UI, {
    Automations,
    AppHealth,
    Runs,
    Feedback,
    Watcher
  });

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectssurfacesjsxAddSchedule1({s,u}, event) {
  const handler = () => u.schedule(s.graph.name);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxReset2({api,t,u}, event) {
  const handler = () => u.act(() => api.removeSchedule(t.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxAsyncConstNAwaitU3({api,t,u}, event) {
  const handler = async () => {
            const n = await u.act(() => api.addNode('Trigger'));
            if (n) {
              await u.act(() => api.setNodeParam(n.id, 'event', t));
              u.go('canvas');
            }
          };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxOpen6({r,u}, event) {
  const handler = () => u.show('Run', {
              id: r.id
            });
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxRetry7({api,r,u}, event) {
  const handler = () => u.act(() => api.sendToBaboom(r.title));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxRetry8({api,t,u}, event) {
  const handler = () => u.act(() => api.reassignTask(t.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxSendFeedback9({api,setText,text,u}, event) {
  const handler = async () => {
          const r = await u.act(() => api.sendFeedback(text));
          if (r) setText('');
        };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxCheckResponse10({api,f,u}, event) {
  const handler = () => u.act(() => api.checkFeedback(f.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectssurfacesjsxViewUpdate11({u}, event) {
  const handler = () => u.show('Update');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsWatcherConnections({u}) { return u.go('settings/Connections'); }
function projectsOpenTaskCanvas({t,u}) { return u.go('canvas', t.taskId || t.task_id || t.path); }
function projectsToggleAutomationPause({api,u,paused,setBusy}) {
  setBusy(true);
  return u.act(() => api.automationPause(!paused)).finally(() => setBusy(false));
}
function projectsWatcherRun({refresh}) { return refresh(); }
function projectsWatcherAdd({api,s,u}) {
  return u.act(()=>{
    const entry=s.catalogue.find(c=>c.descriptor?.engine==='lines.watch');
    if(!entry)throw Error('The Watcher definition is missing. Repair the Library catalogue, then retry.');
    return api.addNode(entry.id);
  });
}
const PROJECT_ACTIONS = {
  'projects.surfaces.OpenTaskCanvas':'projectsOpenTaskCanvas',
  'projects.automations.togglePause':'projectsToggleAutomationPause',
  'projects.watcher.connections':'projectsWatcherConnections',
  'projects.watcher.add':'projectsWatcherAdd',
  'projects.watcher.run':'projectsWatcherRun',
  "projects.surfaces.AddSchedule.1": "projectssurfacesjsxAddSchedule1",
  "projects.surfaces.Reset.2": "projectssurfacesjsxReset2",
  "projects.surfaces.AsyncConstNAwaitU.3": "projectssurfacesjsxAsyncConstNAwaitU3",
  "projects.surfaces.Open.6": "projectssurfacesjsxOpen6",
  "projects.surfaces.Retry.7": "projectssurfacesjsxRetry7",
  "projects.surfaces.Retry.8": "projectssurfacesjsxRetry8",
  "projects.surfaces.SendFeedback.9": "projectssurfacesjsxSendFeedback9",
  "projects.surfaces.CheckResponse.10": "projectssurfacesjsxCheckResponse10",
  "projects.surfaces.ViewUpdate.11": "projectssurfacesjsxViewUpdate11"
};
window.registerActions(PROJECT_ACTIONS, {projectsOpenTaskCanvas,projectsToggleAutomationPause,projectsWatcherConnections,projectsWatcherRun,projectsWatcherAdd,projectssurfacesjsxAddSchedule1,projectssurfacesjsxReset2,projectssurfacesjsxAsyncConstNAwaitU3,projectssurfacesjsxOpen6,projectssurfacesjsxRetry7,projectssurfacesjsxRetry8,projectssurfacesjsxSendFeedback9,projectssurfacesjsxCheckResponse10,projectssurfacesjsxViewUpdate11});
})();
