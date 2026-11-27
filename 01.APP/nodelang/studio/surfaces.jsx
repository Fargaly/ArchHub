// Full views reached through the existing Settings doors. All use the plate
// Card/Row/Composer primitives and the same adapter records as their Settings row.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {
    api,
    useData,
    useApp,
    Btn,
    Table
  } = window.UI;
  // ArchHub menu › App health (design: archhub-directions diagDialog; "Logs & receipts" lives here, never a page).
  // Checks from their owners, and Activity from the run receipts beside every session file, notifications and the update.
  function AppHealth({close}) {
    const s = useData(),
      u = useApp(),
      [runs, setRuns] = React.useState({status: 'waiting', rows: []}),
      [attempt, setAttempt] = React.useState(0),
      lastRun = JSON.stringify(s.graph?.canvasRun || null);  // a finished run re-reads Activity while the dialog is open
    React.useEffect(() => {
      let current = true;
      setRuns(held => held.rows.length ? held : {...held, status: 'waiting'});
      api.readHostAvailability?.().catch(() => null);
      api.listAgentsWorking?.().catch(() => null);
      api.recentRuns(60).then(rows => { if (current) setRuns({status: (rows || []).length ? 'loaded' : 'empty', rows: rows || []}); },
        error => { if (current) setRuns({status: 'error', rows: [], message: error.message || String(error)}); });
      return () => { current = false; };
    }, [attempt, lastRun]);
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
    const when = at => at ? new Date((at > 1e12 ? at : at * 1000)).toLocaleString([], window.UI.zoned()) : '';
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
      {(s.runs || []).length > 0 && <><h3>Runs</h3>{s.runs.map(r => <div className="drow" key={r.id}><span /><b>{r.title}</b><span>{r.status}</span><span className="flex">
        <Btn sm onClick={event => executeAction('ui.select', () => u.show('Run', {id: r.id}), event)}>Open</Btn>
        <Btn sm onClick={event => executeAction('ui.select', () => u.act(() => api.sendToBaboom(r.title)), event)}>Retry</Btn></span></div>)}</>}
      {(s.tasks || []).some(t => t.status === 'STOPPED') && <><h3>Stopped work</h3>{s.tasks.filter(t => t.status === 'STOPPED').map(t => <div className="drow" key={t.id}><span /><b>{t.title}</b><span>stopped</span>
        <Btn sm onClick={event => executeAction('ui.select', () => u.act(() => api.reassignTask(t.id)), event)}>Retry</Btn></div>)}</>}
      <div className="flex">
        <Btn sm onClick={event => executeAction('ui.select', () => navigator.clipboard?.writeText(report).then(() => u.setToast('Report copied.')), event)}>Copy report</Btn>
        <Btn sm disabled={!activity.length} onClick={event => executeAction('ui.select', () => u.download('Receipts', activity), event)}>Export</Btn>
        <Btn sm disabled={!undoName} title={undoName ? 'Undo ' + undoName : 'Nothing to undo'} onClick={event => executeAction('ui.select', () => u.act(api.undo), event)}>{undoName ? 'Undo ' + undoName : 'Nothing to undo'}</Btn>
      </div>
    </div>;
  }
  Object.assign(window.UI, {
    AppHealth
  });

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsToggleAutomationPause({api,u,paused,setBusy}) {
  setBusy(true);
  return u.act(() => api.automationPause(!paused)).finally(() => setBusy(false));
}
const PROJECT_ACTIONS = {
  'projects.automations.togglePause':'projectsToggleAutomationPause'
};
window.registerActions(PROJECT_ACTIONS, {projectsToggleAutomationPause});
})();
