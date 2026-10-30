// ds_workshop3.jsx: the Workshop command center (plate archhub-workshop-command-center-native.png); layout in style.css .ws-*.
// Work | the task conversation | People & agents. Every row is live Workshop data; Send is the
// composer's existing @mention path (/api/router/chat -> workshop_live.send_as_founder, live injection).
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {A, D, useData, useApp, Btn, Chip, Av, ApprovalCard, Empty} = window.UI;
  const api = window.ArchHubAPI;
  // The list groups by what it asks of you; a drop sets the group's stage (the Board draws the same groups).
  const groupsFor = (archived, waiting) => [
    ['NEEDS ATTENTION', t => t.status === 'IN REVIEW' || t.status === 'STOPPED' || waiting.has(t.id), 'IN REVIEW'],
    ['IN PROGRESS', t => (t.status === 'WIP' || t.status === 'PLANNED') && !waiting.has(t.id), 'WIP'],
    ...(archived ? [['COMPLETED AND ARCHIVED', t => t.status === 'DONE' || t.status === 'ARCHIVED', 'DONE']] : [])];
  window.UI.workshopGroups = groupsFor;
  const color = s => s === 'IN REVIEW' ? A.warn : s === 'DONE' ? A.ok : s === 'STOPPED' ? A.err : s === 'WIP' ? A.ink : A.inkSoft;
  const statusText = s => ({'IN REVIEW': 'Waits for your OK', WIP: 'Working', PLANNED: 'Planned', DONE: 'Completed', ARCHIVED: 'Archived', STOPPED: 'Stopped'})[s] || s;
  const sessionState = row => row.state === 'turn_ended' ? 'Turn ended' : row.state === 'tool_ended' ? 'Tool ended' : row.state === 'unassociated' ? 'Activity unassociated' : 'Working';
  function Task({task, on, select, ownerName}) {
    const u = useApp();
    const steps = task.steps || [], completed = steps.filter(step => /^(done|complete|completed)$/i.test(step.status)).length, a = task.activity;
    return <button className="listbutton ws-task" aria-selected={on} onClick={() => executeAction("ui.select", select)} onKeyDown={e => {
      if (e.code === 'Space') {
        e.preventDefault();
        select();
        executeAction("ui.show", u, 'Task details', {id: task.id});
      }
    }} draggable onDragStart={e => e.dataTransfer.setData('task', task.id)}>
      <div className="ws-task-title">{task.title}</div><div className="ws-task-state" style={{color: color(task.status)}}>{statusText(task.status)}</div>
      {(ownerName || task.owner) && <div className="ws-small">{ownerName || task.owner}</div>}
      {a && <div data-agent-activity role="status" className="ws-activity">
        {a.sessions.map(row => <div key={row.provider + ':' + row.session} title={row.session}>
          {row.provider} · {row.tool} · {row.associated === false ? 'Current file unknown' + (row.file ? ' (last observed: ' + row.file + ')' : '') : row.file} · {sessionState(row)}
          {row.association_conflict && <span> · File and session association disagree</span>}
        </div>)}
        {a.ownership === 'unknown' && <span>Activity unknown · no owned files</span>}
        {a.touched_after_install && <strong data-touched-after-install style={{color: A.warn}}>Touched after install</strong>}
        {a.stale && <span> · Re-verify row status</span>}
        {(a.limited || a.unavailable) && <span> · Observation incomplete</span>}
      </div>}
      {task.status === 'WIP' && steps.length > 0 && <span role="progressbar" className="ws-progress" aria-label={task.title + ' steps'} aria-valuemin={0} aria-valuenow={completed} aria-valuemax={steps.length}><i style={{width: `${completed / steps.length * 100}%`}} /></span>}
    </button>;
  }
  function Messages({task, roles = {}}) {
    return <div className="ws-msgs">{task.messages.map(m => {
      const own = Boolean(m.sender_key) && m.sender_key === m.viewer_key;
      return <div key={m.id} className={'ws-msg' + (own ? ' own' : '')}>{!own && <Av id={m.provider || window.ArchHubAPI.getSnapshot().providers.find(p => p.name === m.who)?.id || 'claude'} size={28} />}
        <div className="ws-msg-body" style={own ? {justifySelf: 'end', maxWidth: 560, padding: '12px 16px', borderRadius: '14px 14px 4px 14px', background: '#24242b'} : {}}>
          {!own && <div className="flex"><b>{m.who}</b>{roles[m.who] && <span className="ws-small">{roles[m.who]}</span>}</div>}{m.to && <span className="ws-small">To {m.to}</span>}<p>{m.text}</p>
          {m.reply_to && <span className="ws-small">↳ reply</span>}
          {(m.live || []).length > 0 && <div className="flex ws-live" data-live-delivery>{m.live.map((d, i) => <Chip key={i} c={d.state === 'delivered' ? A.inkSoft : A.warn}>{d.state === 'delivered' ? '✓' : '✗'} {d.agent} · {d.state === 'delivered' ? new Date(d.at).toLocaleTimeString() + ' · ' + d.ms + ' ms' : d.reason}</Chip>)}</div>}
          {['pending', 'delivered', 'answered'].includes(m.state) && <span role="status" data-delivery-state={m.state} className="ws-small">{m.state === 'answered' ? 'Answered' : m.state === 'delivered' ? 'Delivered' : 'Pending'}{m.delivery?.some(row => row.escalated) ? ' · Coordinator notified' : ''}</span>}
          {window.UI.TurnUsage && <window.UI.TurnUsage message={m} />}{window.UI.AnswerWidget && <window.UI.AnswerWidget message={m} />}{!own && window.UI.AnswerSources && <window.UI.AnswerSources message={m} />}{m.rule && <Chip c={A.purple}>Your rule: {m.rule}</Chip>}
        </div></div>;
    })}</div>;
  }
  // "To" is a joined agent session, Everyone, or BABOOM (free first); Send goes live into the chosen session.
  // People & agents and the To list come from one place: the Workshop people panel, the Workshop composer and the Canvas composer.
  function workshopPeople(s) {
      const agents = s.liveAgents || [];
      // People & agents: each joined session, then running agents that have not joined, then the founder.
      const people = [...agents.map(a => ({key: a.handle, id: (s.providers || []).some(p => p.id === a.app) ? a.app : a.name, name: a.name, role: (a.task || 'No task declared') + (a.status && a.status !== 'unknown' ? ' · ' + a.status : ''), handle: a.handle})),
        ...(s.agents || []).filter(p => !agents.some(a => a.app === p.runtime)).map(p => ({key: p.id, id: p.id, name: p.name,
          role: 'Not joined · ' + (p.presence === 'working' ? 'Working · ' + p.task : p.presence === 'unknown' ? (p.status_text || 'Status unknown') : 'Idle')})),
        {key: 'founder', id: 'You', name: 'You', role: 'Founder · workspace owner'}];
      // The To list: every agent in People & agents (one not joined is shown, but cannot receive yet), Everyone, BABOOM.
      const choices = [...(agents.length > 1 ? [{key: 'everyone', handle: 'everyone', name: 'Everyone', detail: agents.length + ' joined sessions'}] : []),
        ...people.filter(p => p.key !== 'founder').map(p => ({key: p.key, handle: p.handle, name: p.name, detail: p.role})),
        {key: 'baboom', handle: '', name: 'BABOOM', detail: 'Free models first'}];
      return {agents, people, choices};
  }
  // DESIGNSYS-050 4.9 AgentPicker: one styled To-list; an agent that has not joined is shown but cannot receive yet.
  function AgentPicker({choices, to, setTo}) {
    const [listOpen, setListOpen] = React.useState(false);
    return <div className="ws-to" onKeyDown={e => e.key === 'Escape' && setListOpen(false)}>
      <button type="button" className="ws-link" aria-haspopup="listbox" aria-expanded={listOpen} aria-label="Recipient" onClick={() => executeAction("ui.select", () => setListOpen(!listOpen))}>To {choices.find(c => c.handle === to)?.name || 'BABOOM'} ▾</button>
      {listOpen && <div role="listbox" aria-label="Recipients" className="ws-to-list">{choices.map(c => <button type="button" role="option" key={c.key} aria-selected={c.handle === to} disabled={c.handle === undefined} className="listbutton spread" title={c.handle === undefined ? c.name + ' is running but has not joined this Workshop, so it cannot receive messages yet' : 'Send to ' + c.name} onClick={() => executeAction("ui.select", () => { setTo(c.handle); setListOpen(false); })}><span>{c.name}</span><span className="ws-small">{c.detail}</span></button>)}</div>}
    </div>;
  }
  function TaskComposer({choices, to, setTo, sendRef}) {
    const s = useData(), u = useApp();
    const [text, setText] = React.useState(''), [sending, setSending] = React.useState(false);
    const files = s.composerAttachments || [];
    const send = async (body = text) => {
      if (!body.trim()) return;
      const prompt = (!to || new RegExp('(^|\\s)@' + to + '\\b').test(body) ? '' : '@' + to + ' ') + body +
        (files.length ? '\nAttached project file nodes: ' + JSON.stringify(files.map(f => ({id: f.id, path: f.path}))) : '');
      if (body === text) setText('');
      setSending(true);
      try {
        const sent = await u.act(() => api.apiRouterChat(prompt, 'BABOOM'));
        if (!sent) { if (body === text) setText(body); return; }
        files.forEach(f => api.removeComposerAttachment(f.id));
        await api.listTasks?.();
      } finally {
        setSending(false);
      }
    };
    sendRef.current = send;
    return <D.Composer as="form" className="ws-composer" onSubmit={e => { e.preventDefault(); executeAction("ui.select", send); }} style={{width: '100%', padding: '14px 16px', gap: 8}}>
      <AgentPicker choices={choices} to={to} setTo={setTo} />
      {files.length > 0 && <div className="flex">{files.map(f => <button type="button" key={f.id} className="ws-link" onClick={() => executeAction("ui.select", () => u.act(() => api.removeComposerAttachment(f.id)))}>{f.name || f.path} ×</button>)}</div>}
      <textarea className="composer-input ws-input" rows={2} aria-label="Message" placeholder="Message this task…" value={text} onChange={e => setText(e.target.value)} onKeyDown={e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
      }} />
      <div className="flex ws-tools">
        {u.pickFile && <button type="button" className="ws-link" onClick={() => executeAction("ui.select", u.pickFile)}>Attach</button>}
        {u.voice && api.supportsAction?.('startVoiceInput') !== false && <button type="button" className="ws-link" onClick={() => executeAction("ui.select", () => u.voice(setText))}>Voice</button>}
        <span className="fill" /><Btn p type="submit" aria-busy={sending} disabled={!text.trim()}>Send</Btn>
      </div>
    </D.Composer>;
  }
  function Win() {
    const s = useData(), u = useApp();
    const [history, setHistory] = React.useState(false), [query, setQuery] = React.useState(''), [to, setTo] = React.useState(null),
      [notesOpen, setNotesOpen] = React.useState(false), [notes, setNotes] = React.useState(''), sendRef = React.useRef(null);
    const roomScope = JSON.stringify([s.graph.id, s.profile.email, s.profile.signedIn, s.workshopMessagesScope]);
    const currentScope = React.useRef(roomScope);
    currentScope.current = roomScope;
    const [older, setOlder] = React.useState({scope: roomScope, messages: [], before: null, more: true});
    const previous = older.scope === roomScope ? older : {messages: [], before: null, more: true};
    const tasks = s.tasks || [], task = tasks.find(t => t.id === u.task) || tasks[0];
    const roomMessages = [...new Map([...previous.messages, ...(s.workshopMessages || [])].map(message => [message.id, message])).values()]
      .filter(message => !task?.messages.some(item => item.id === message.id));
    const list = tasks.filter(t => !query || `${t.title} ${t.status}`.toLowerCase().includes(query.toLowerCase()));
    const waiting = new Set((s.approvals || []).filter(c => c.status === 'pending').map(c => c.taskId));
    const {agents, people, choices} = workshopPeople(s);
    const roles = Object.fromEntries(agents.filter(a => a.task).map(a => [a.name, a.task]));
    // A task's people: the joined sessions that declared it, else its runtime's provider name.
    const sessionsOf = t => agents.filter(a => (t.declarations || []).some(d => d.agent === a.agent));
    const nameFor = t => sessionsOf(t).map(a => a.name).join(' and ') || (s.providers || []).find(p => p.id === t.owner)?.name || t.owner;
    const recipient = to ?? (task && (sessionsOf(task)[0] || agents.find(a => a.app === task.owner)) || agents[0])?.handle ?? '';
    const request = task?.description || task?.messages.find(m => m.sender_key && m.sender_key === m.viewer_key)?.text;
    return <div data-screen="workshop" className="ws">
  <aside data-workshop-column="work" className="ws-col ws-work">
    <div className="spread ws-head"><h2>Work</h2><button className="ws-link" onClick={() => executeAction("ui.show", u, 'New task')}>+ New task</button></div>
    <input aria-label="Search work" className="ws-search" placeholder="Search work…" value={query} onChange={e => setQuery(e.target.value)} />
    <div className="scroll ws-list">{groupsFor(history, waiting).map(([name, member, stage]) => {
      const rows = list.filter(member);
      return <div key={name} className="ws-group" data-workshop-group={name} onDragOver={e => e.preventDefault()} onDrop={e => {
        e.preventDefault();
        const id = e.dataTransfer.getData('task');
        if (id) executeAction("setTaskStatus", u, id, stage);
      }}><div className="spread ws-label"><span>{name}</span><span>{rows.length}</span></div>{rows.map(t => <Task key={t.id} task={t} ownerName={nameFor(t)} on={task?.id === t.id} select={() => executeAction("ui.setTask", u, t.id)} />)}</div>;
    })}</div>
    <div className="ws-foot"><span>Completed &amp; archived</span><span className="ws-small">All work stays searchable</span>
      <button className="ws-link" aria-pressed={history} onClick={() => executeAction("ui.select", () => setHistory(!history))}>{history ? 'Hide history' : 'Show history →'}</button></div>
  </aside>
  <main data-workshop-column="thread" className="ws-thread">
    <header className="spread"><div><h1>{task?.title || (roomMessages.length ? 'Workshop room' : 'What should the agents do?')}</h1><p className="ws-sub">{task ? [nameFor(task), statusText(task.status)].filter(Boolean).join(' · ') : 'One room · ' + (s.graph.name || 'Workshop')}</p></div>
      <button className="ws-link" onClick={() => executeAction("ui.select", async () => {
        if (!task) { executeAction("ui.go", u, "canvas"); return; }
        const opened = await executeAction("openTaskGraph", u, task.id);
        if (opened) { executeAction("ui.setSelectedNodeId", u, task.id); executeAction("ui.go", u, "canvas"); }
      })}>Open in Canvas ↗</button></header>
    <div className="scroll ws-body"><div className="ws-stack">
      {request && <section data-workshop-request className="ws-request"><div className="ws-label">THE REQUEST</div><p>{request}</p></section>}
      {(previous.before ? previous.more : s.workshopMessagesMore) && <Btn sm ghost onClick={async () => {
        const page = await executeAction("listWorkshopMessages", u, previous.before || s.workshopMessagesBefore);
        if (currentScope.current === roomScope && Array.isArray(page?.messages)) setOlder({scope: roomScope, messages: [...page.messages, ...previous.messages], before: page.next_before, more: page.more});
      }}>Older messages</Btn>}
      {roomMessages.length > 0 && <Messages task={{messages: roomMessages}} roles={roles} />}
      {task ? <><Messages task={task} roles={roles} />{task.approvalId && <ApprovalCard id={task.approvalId} />}{task.status === 'STOPPED' && <Btn onClick={() => executeAction("reassignTask", u, task.id)}>Continue with another agent</Btn>}{task.status === 'DONE' && <div className="flex"><Btn onClick={() => executeAction("ui.go", u, 'watcher')}>Open result</Btn><Btn onClick={() => executeAction("ui.schedule", u, task.title)}>Repeat this</Btn></div>}</> : roomMessages.length === 0 && <Empty>Create a task to begin.</Empty>}
    </div></div>
    <div className="ws-dock"><div>{D.Composer ? <TaskComposer choices={choices} to={recipient} setTo={setTo} sendRef={sendRef} /> : window.UI.Composer && <window.UI.Composer taskId={task?.id} />}</div></div>
  </main>
  <aside data-workshop-column="people" className="ws-col ws-people">
    <h2>People &amp; agents</h2><p className="ws-small ws-note">{people.length + ' in this Workshop · ' + agents.length + ' joined'}</p>
    <div className="scroll ws-people-list">{people.map(p => <button key={p.key} className={'button-reset ws-person' + (recipient && p.handle === recipient ? ' to' : '')} title={p.handle ? 'Send to ' + p.name : p.name} onClick={() => p.handle ? executeAction("ui.select", () => setTo(p.handle)) : executeAction("ui.show", u, 'Agent', {id: p.id})}><Av id={p.id} size={28} /><span><b>{p.name}</b><span className="ws-small">{p.role}</span></span></button>)}</div>
    <hr className="ws-rule" />
    <h2>Meeting input</h2><p className="ws-small ws-note">Notes for this task go to {recipient ? (agents.find(a => a.handle === recipient)?.name || 'Everyone') : 'BABOOM'}.</p>
    {notesOpen ? <div className="grid"><textarea aria-label="Meeting notes" rows={6} value={notes} onChange={e => setNotes(e.target.value)} placeholder="Paste meeting notes…" /><div className="flex"><Btn sm p disabled={!notes.trim()} onClick={() => executeAction("ui.select", async () => { await sendRef.current?.('Meeting notes:\n' + notes); setNotes(''); setNotesOpen(false); })}>Send notes</Btn><Btn sm ghost onClick={() => executeAction("ui.select", () => setNotesOpen(false))}>Cancel</Btn></div></div>
      : <button className="ws-link" onClick={() => executeAction("ui.select", () => setNotesOpen(true))}>+ Paste notes</button>}
  </aside>
 </div>;
  }
  window.UI.Workshop = Win;
  window.UI.AgentPicker = AgentPicker;
  window.UI.workshopPeople = workshopPeople;
  window.UI.Messages = Messages;
  window.UI.Task = Task;
})();
