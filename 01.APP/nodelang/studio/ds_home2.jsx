// Home (plate archhub-home-cleanup-native.png, Penpot rev 1189): Your work · Recent files · Pipeline · Meeting input.
// Under the one AppHeader; the floating composer is the shell's. Every row is live store data.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const api = window.ArchHubAPI;
  const {D, useData, useApp, Btn, Empty} = window.UI;
  function Sheet({
    mark = false,
    large = false
  }) {
    const s = useData(),
      w = s.watcher;
    const points = w.geometry.walls.flatMap(line => [[line[0],line[1]],[line[2],line[3]]]);
    const xs = points.map(p=>p[0]), ys=points.map(p=>p[1]);
    const bounds = points.length ? [Math.min(...xs),Math.min(...ys),Math.max(1,Math.max(...xs)-Math.min(...xs)),Math.max(1,Math.max(...ys)-Math.min(...ys))] : [0,0,1,1];
    return <svg width={large ? '100%' : 86} height={large ? 112 : 60} viewBox={bounds.join(' ')} aria-label={w.host || 'Source preview'} style={{
      borderRadius: 6,
      background: '#e7e3db',
      display: 'block'
    }}><g fill="none" stroke={mark ? '#bc5a45' : '#6d695e'} strokeWidth="1" vectorEffect="non-scaling-stroke">{w.geometry.walls.map(([x1, y1, x2, y2], i) => <path key={i} d={`M${x1} ${y1}L${x2} ${y2}`} />)}</g></svg>;
  }
  const statusText = st => ({'IN REVIEW': 'Waits for your OK', WIP: 'Working', PLANNED: 'Planned', DONE: 'Completed', ARCHIVED: 'Archived', STOPPED: 'Stopped'})[st] || st;
  function Home() {
    const s = useData(), u = useApp();
    const [query, setQuery] = React.useState(''), [status, setStatus] = React.useState(''), [meetingOpen, setMeetingOpen] = React.useState(null);
    const tasks = (s.tasks || []).filter(t => t.status !== 'ARCHIVED');
    const list = tasks.filter(t => (!status || t.status === status) && (!query || t.title.toLowerCase().includes(query.toLowerCase())));
    const task = tasks.find(t => t.id === u.task) || list[0];
    const live = s.liveAgents || [];
    // Same rows as the Workshop's People & agents: joined sessions, then running agents that have not joined.
    // One identity everywhere: the Workshop's people rows (declared name, never a provider-merged label).
    const agents = window.UI.workshopPeople ? window.UI.workshopPeople(s).people.filter(p => p.key !== 'founder').map(p => ({key: p.key, name: p.name, state: p.state, detail: [p.detail, p.meta].filter(Boolean).join(' · '), on: Boolean(p.handle)}))
      : live.map(a => ({key: a.handle, name: a.name, state: a.status || 'Joined', detail: a.task || '', on: true}));
    const people = live.filter(a => (task?.declarations || []).some(d => d.agent === a.agent)).map(a => a.name);
    const ownerName = task && window.UI.workshopPeople ? window.UI.workshopPeople(s).whoIs(task.owner).name : task?.owner;  // the session's declared name, not its label
    const by = task ? ['You', ...(people.length ? people : [(s.providers || []).find(p => p.id === task.owner)?.name || ownerName].filter(Boolean))] : [];
    const running = (s.hosts || []).filter(h => ['connected', 'listening', 'running'].includes(h.state));
    const m = s.meeting || {};
    // Meeting input is contextual: open while a meeting is chosen or transcribing, otherwise one line you can open.
    const meetingActive = Boolean(m.calendarId || m.status === 'Transcribing' || m.transcript?.length);
    const showMeeting = meetingOpen ?? meetingActive;
    const setMeeting = patch => u.act(() => api.setMeeting(patch));
    return <main className="page home-page" data-screen="home" data-home-page="">
      <header className="home-head"><h1>Your work</h1><div className="flex">
        <Btn onClick={() => executeAction("ui.select", () => u.act(() => api.newSession()).then(r => r && u.go('canvas')))}>New</Btn>
        <Btn p onClick={() => executeAction("ui.select", () => u.act(() => api.openSession()).then(r => r && !r.cancelled && u.go('canvas')))}>Open file...</Btn>
        <Btn onClick={() => executeAction("ui.select", u.pickFlow)}>Import...</Btn>
        <Btn onClick={() => executeAction("ui.select", () => u.go('library'))}>Library</Btn>
      </div></header>
      <section aria-label="Recent files"><h2 className="home-label">Recent files</h2>
        {(s.graphs || []).length ? <div className="home-files">{s.graphs.slice(0, 2).map(g => <button key={g.id} className="button-reset home-file" title={g.path} onClick={() => executeAction("ui.select", () => u.act(() => api.openSession(g.path)).then(r => r && !r.cancelled && u.go('canvas')))}><b>{g.title || g.name}</b><small>{g.path}</small></button>)}</div>
          : <Empty>Files you open or save appear here.</Empty>}
      </section>
      <section className="home-pipeline" aria-label="Pipeline"><h2>Pipeline</h2>
        <div className="home-pipe">
          <div className="home-tasks">
            <label className="home-field home-search"><span>Search tasks</span><input aria-label="Search tasks" placeholder="Find a task..." value={query} onChange={e => setQuery(e.target.value)} /></label>
            <div className="flex"><label className="home-field"><span>Status</span><select aria-label="Task status" value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option>{['IN REVIEW', 'WIP', 'PLANNED', 'STOPPED', 'DONE'].map(v => <option key={v} value={v}>{statusText(v)}</option>)}</select></label>
              <Btn onClick={() => executeAction("ui.select", () => u.show('New task'))}>New task</Btn></div>
            <div className="home-task-rows scroll">{list.map(t => <button key={t.id} className="listbutton home-task-row" title={t.title} aria-selected={task?.id === t.id} onClick={() => executeAction("ui.select", () => u.setTask(t.id))}><b>{t.title}</b><small>{statusText(t.status)}</small></button>)}
              {!list.length && <p className="muted home-none">{tasks.length ? 'No task matches.' : 'No tasks yet.'}</p>}</div>
          </div>
          <div className="home-thread">{task ? <>
            <h3>{task.title}</h3><small className="muted">{by.join(' · ')}</small>
            {(task.messages || []).slice(-3).map(msg => <div key={msg.id} className="home-msg"><small>{msg.sender_key && msg.sender_key === msg.viewer_key ? 'You' : msg.who}</small><window.UI.Prose text={msg.text} lines={6} /></div>)}
            {!(task.messages || []).length && task.description && <div className="home-msg"><small>You</small><window.UI.Prose text={task.description} lines={6} /></div>}
            <div className="flex"><Btn onClick={() => executeAction("ui.select", async () => { if (await executeAction("openTaskGraph", u, task.id)) u.go('canvas'); })}>Review workflow</Btn><Btn onClick={() => executeAction("ui.select", () => u.go('receipts'))}>Activity &amp; receipts</Btn></div>
          </> : <Empty>Create a task to begin.</Empty>}</div>
          <aside className="home-side">
            <div className="spread"><h2>Agents · {live.length} session{live.length === 1 ? '' : 's'}</h2><Btn disabled={!task} onClick={() => executeAction("ui.select", () => u.show('Task details', {id: task.id}))}>Request details</Btn></div>
            {agents.map(a => <div key={a.key} className="home-agent" title={[a.name, a.state, a.detail].filter(Boolean).join(' · ')}><i className={a.on ? 'on' : ''} /><span className="fill">{a.name}</span><small>{a.state}</small></div>)}
            {!agents.length && <p className="muted">{s.agentSummary || 'No agent is running.'}</p>}
            <h3 className="home-label">Programs</h3>
            {running.length ? running.map(h => <p key={h.id}>{h.name} · {h.file || h.state}</p>) : <p className="muted">{s.hostsProbing ? 'Checking programs…' : 'No program connected.'}</p>}
            <h3 className="home-label">People</h3>
            <p>{['You', ...(s.people || []).filter(p => p.email !== s.profile.email).map(p => p.name)].join(' · ')}</p>
            {!showMeeting && <button className="ws-link home-meeting-open" onClick={() => executeAction("ui.select", () => setMeetingOpen(true))}>+ Meeting input</button>}
          </aside>
        {showMeeting && <div className="home-meeting" aria-label="Meeting input">
          <div className="flex"><b>Meeting input</b><small className="muted fill">Transcript → reviewed decisions → owned tasks</small>{!meetingActive && <button className="ws-link" onClick={() => executeAction("ui.select", () => setMeetingOpen(false))}>Hide</button>}</div>
          <div className="flex home-meeting-row">
            <label className="home-field"><span>Meeting</span><select aria-label="Meeting from calendar" value={m.calendarId || ''} onChange={e => setMeeting({calendarId: e.target.value})}><option value="" disabled>Choose a calendar meeting</option>{(s.meetingCalendar || []).map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
            <label className="home-field"><span>Connect through</span><select aria-label="Meeting program" value={m.platform || ''} onChange={e => setMeeting({platform: e.target.value})}><option value="" disabled>Choose</option>{['Teams', 'Zoom', 'Google Meet'].map(p => <option key={p}>{p}</option>)}</select></label>
            <label className="home-field"><span>Assigned agent</span><select aria-label="Meeting agent" value={m.agent || ''} onChange={e => setMeeting({agent: e.target.value})}><option value="" disabled>Choose</option>{(s.providers || []).filter(p => p.enabled).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <div className="home-field home-consent"><span>Everyone consented</span><div className="spread"><span>{m.consent ? 'On' : 'Off'}</span><D.Toggle label="Meeting transcript consent" checked={!!m.consent} onCheckedChange={v => setMeeting({consent: v})} /></div></div>
            <Btn disabled={!m.consent || !m.calendarId || m.status === 'Transcribing'} onClick={() => executeAction("ui.select", () => u.act(api.startMeetingTranscript))}>Start transcript</Btn>
            <Btn disabled={m.status !== 'Transcribing'} onClick={() => executeAction("ui.select", () => u.act(api.stopMeetingTranscript))}>Stop</Btn>
          </div>
          <div className="spread"><small className="muted">{m.transcript?.length ? m.transcript.length + ' transcript turns · ' + (m.actions?.length || 0) + ' decisions' : 'No transcript yet. Decisions and owners appear after the transcript is reviewed.'}</small>
            <Btn disabled={!m.transcript?.length} onClick={() => executeAction("ui.select", async () => { const c = await u.act(api.proposeMeetingSummary); if (c) { u.setTask(c.id); u.go('workshop'); } })}>Review summary</Btn></div>
        </div>}
        </div>
      </section>
    </main>;
  }
  window.UI.Home = Home;
  window.UI.Sheet = Sheet;
})();
