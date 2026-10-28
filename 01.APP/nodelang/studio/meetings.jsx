(() => {
  // WIRE-social: declarative command bindings consumed by the admission compiler and dispatcher.
  const WIRE_SOCIAL_ACTIONS = {"wire.meetings.calendar":"wire.act","wire.meetings.transcript":"wire.act",
  "wire.meetings.1": "wire.act",
  "wire.meetings.2": "wire.act",
  "wire.meetings.3": "wire.act",
  "wire.meetings.4": "wire.act",
  "wire.meetings.5": "wire.act",
  "wire.meetings.6": "wire.act",
  "wire.meetings.7": "wire.act",
  "wire.meetings.8": "wire.act",
  "wire.meetings.retry": "wire.retry"
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
  function Meetings() {
    const wire = window.UI.useWireSocial();
    function dispatch(id, callback) {
      if (WIRE_SOCIAL_ACTIONS[id] === 'wire.retry') return callback();
      if (WIRE_SOCIAL_ACTIONS[id] !== 'wire.act') throw Error('Refresh this screen to reload its action registry.');
      return wire.act(callback);
    }
    const s = useData(),
      u = useApp(),
      m = s.meeting;
    React.useEffect(() => {
      if (m.status !== 'Transcribing' || !m.pollMs) return;
      let reading = false, disposed = false;
      const timer = setInterval(async () => {
        if (disposed || reading || document.hidden) return;
        reading = true;
        try { await wire.act(api.readMeetingTranscript); } finally { reading = false; }
      }, m.pollMs);
      return () => { disposed = true; clearInterval(timer); };
    }, [m.status, m.calendarId]);
    return <main className="page meeting-page" data-screen="meetings"><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Waiting for the owner…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.meetings.retry",wire.retry)}>Retry</Btn></div>}
    </section><div className="flex"><Btn sm onClick={()=>dispatch('wire.meetings.calendar',api.importMeetingCalendar)}>Read calendar file</Btn><Btn sm onClick={()=>dispatch('wire.meetings.transcript',api.importMeetingTranscript)}>Read transcript file</Btn></div><Heading title="Meetings" sub="People, agents and decisions, connected to the same Workshop."><Btn sm onClick={event => dispatch("wire.meetings.1", () => (() => u.go('colleagues'))(event))}>Team</Btn><Btn sm onClick={event => dispatch("wire.meetings.2", () => (async () => {
          await wire.call(() => api.addNode('Join meeting'));
          u.go('canvas');
        })(event))}>Open as node</Btn><Btn p disabled={!m.calendarId || !m.agent || !m.platform || m.status === 'Transcribing' || m.status === 'Joined'} onClick={event => dispatch("wire.meetings.3", () => (() => wire.call(api.joinMeeting))(event))}>Join with BABOOM</Btn></Heading><div className="meeting-setup"><Card style={{
          padding: 22
        }}><div className="spread"><Icon name="users" size={24} /><Chip c={m.status === 'Transcribing' ? A.ok : A.inkSoft}>{m.status || 'Choose a meeting'}</Chip></div><label className="grid" style={{
            marginTop: 20
          }}>Meeting<select aria-label="Meeting from calendar" value={m.calendarId || ''} onChange={event => wire.act(() => (e => wire.call(() => api.setMeeting({
              calendarId: e.target.value
            })))(event))}><option value="" disabled>Choose a calendar meeting</option>{s.meetingCalendar.map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label><label className="grid" style={{
            marginTop: 14
          }}>Connect through<select aria-label="Meeting program" value={m.platform || ''} onChange={event => wire.act(() => (e => wire.call(() => api.setMeeting({
              platform: e.target.value
            })))(event))}><option value="" disabled>Choose a meeting program</option>{['Teams', 'Zoom', 'Google Meet'].map(p => <option key={p}>{p}</option>)}</select></label><label className="grid" style={{
            marginTop: 14
          }}>Agent<select aria-label="Meeting agent" value={m.agent || ''} onChange={event => wire.act(() => (e => wire.call(() => api.setMeeting({
              agent: e.target.value
            })))(event))}><option value="" disabled>Choose an agent</option>{s.providers.filter(p => p.enabled).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><div className="row spread" style={{
            marginTop: 18
          }}><span>Everyone agreed to a transcript</span><D.Toggle label="Meeting transcript consent" checked={!!m.consent} onCheckedChange={event => wire.act(() => (v => wire.call(() => api.setMeeting({
              consent: v
            })))(event))} /></div><div className="flex"><Btn disabled={!m.consent || !m.calendarId} onClick={event => dispatch("wire.meetings.4", () => (() => wire.call(api.startMeetingTranscript))(event))}>Start transcript</Btn><Btn sm disabled={!m.calendarId} onClick={event => dispatch("wire.meetings.5", () => (() => wire.call(api.stopMeetingTranscript))(event))}>Stop</Btn></div><p className="muted" style={{
            fontSize: 11,
            marginTop: 16
          }}>Transcription starts only after consent.</p></Card><Card style={{
          padding: 22
        }}><h2>In the room</h2>{(m.participants || []).map(p => <div className="row spread" key={p.id}><div><b>{p.name}</b><p className="muted">{p.role}</p></div><span className="status-dot" /></div>)}{m.agentJoinStatus === 'Joined' && <div className="row spread"><span>{s.providers.find(p => p.id === (m.agent || ''))?.name} · Agent</span><Chip c={A.ok}>{m.status}</Chip></div>}</Card></div><div className="meeting-content"><Card style={{
          padding: 22
        }}><div className="spread"><h2>Live transcript</h2><Btn sm title="Refresh transcript" aria-label="Refresh transcript" onClick={event => dispatch("wire.meetings.6", () => (() => wire.call(api.readMeetingTranscript))(event))}><Icon name="refresh" size={16} /></Btn></div><div className="meeting-transcript">{(m.transcript || []).map(turn => <div key={turn.id} className="meeting-turn"><span className="mono muted">{turn.at}</span><div><b>{turn.speaker}</b><p>{turn.text}</p><window.UI.TranscriptProvenance turn={turn} /></div></div>)}{!m.transcript?.length && <p className="muted">Join the meeting and start the consented transcript to see who said what.</p>}</div></Card><Card style={{
          padding: 22
        }}><h2>Decisions &amp; owned tasks</h2>{m.actions.map((text, i) => <div className="meeting-decision" key={i}><p>{text}</p><label className="flex muted">Owner<select aria-label={'Meeting action owner ' + (i + 1)} value={m.actionOwners?.[i] || ''} onChange={event => wire.act(() => (e => wire.call(() => api.setMeetingActionOwner(i, e.target.value)))(event))}><option value="" disabled>Choose an owner</option>{s.people.map(p => <option key={p.id}>{p.name}</option>)}</select></label><Btn sm disabled={!m.actionOwners?.[i] || !!m.actionTasks?.[i]} onClick={event => dispatch("wire.meetings.7", () => (async () => {
              const t = await wire.call(() => api.createMeetingTask(i));
              if (t) {
                u.setTask(t.id);
                u.setToast('Task is in the Workshop');
              }
            })(event))}>{m.actionTasks?.[i] ? 'In Workshop' : 'Make task'}</Btn></div>)}<div className="row"><h3>After the meeting</h3><p className="muted" style={{
              margin: '12px 0'
            }}>The summary names decisions, owners and next actions.</p><Btn p onClick={event => dispatch("wire.meetings.8", () => (async () => {
              const c = await wire.call(api.proposeMeetingSummary);
              if (c) { u.setTask(c.id); u.go('workshop'); }
            })(event))}>Review summary</Btn>{m.summaryStatus && <Chip c={m.summaryStatus === 'Sent' ? A.ok : A.inkSoft}>{m.summaryStatus}</Chip>}</div></Card></div></main>;
  }
  window.UI.Meetings = Meetings;
})();
