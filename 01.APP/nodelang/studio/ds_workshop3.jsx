// ds_workshop3.jsx: the Workshop command center (plate archhub-workshop-command-center-native.png); layout in style.css .ws-*.
// Work | the task conversation | People & agents. Every row is live Workshop data; Send is the
// composer's existing @mention path (/api/router/chat -> workshop_live.send_as_founder, live injection).
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {A, D, useData, useApp, Btn, Chip, Av, ApprovalCard, Empty} = window.UI;
  // The shared text blocks (ui.jsx); plain text where a host renders this file without them.
  const Prose = props => window.UI.Prose ? React.createElement(window.UI.Prose, props) : <p>{props.text}</p>;
  const Clamp = props => window.UI.Clamp ? React.createElement(window.UI.Clamp, props) : <span className="ws-small">{props.text}</span>;
  const api = window.ArchHubAPI;
  // The list groups by what it asks of you; a drop sets the group's stage (the Board draws the same groups).
  const laneOf = t => {
    if (t.status === 'stale') return 'stale';
    const route = String(t.wsRoute || t.route || '');
    if (route === 'planned' || route === 'PLANNED' || t.started === false) return 'PLANNED';
    if (route === 'started' || route === 'WIP') return 'WIP';
    return t.status;
  };
  const groupsFor = (archived, waiting, searching) => [
    ['NEEDS ATTENTION', t => t.status === 'IN REVIEW' || t.status === 'STOPPED' || waiting.has(t.id), 'IN REVIEW'],
    ['IN PROGRESS', t => laneOf(t) === 'WIP' && t.status !== 'PLANNED' && t.status !== 'stale' && !waiting.has(t.id), 'WIP'],
    ['PLANNED', t => (laneOf(t) === 'PLANNED' || t.status === 'PLANNED') && t.status !== 'stale' && !waiting.has(t.id), 'PLANNED'],
    ...(searching ? [['STALE', t => t.status === 'stale' || laneOf(t) === 'stale', 'PLANNED']] : []),
    ...(archived ? [['COMPLETED AND ARCHIVED', t => t.status === 'DONE' || t.status === 'ARCHIVED', 'DONE']] : [])];
  window.UI.workshopGroups = groupsFor;
  const color = s => s === 'IN REVIEW' ? A.warn : s === 'DONE' ? A.ok : s === 'STOPPED' ? A.err : s === 'WIP' ? A.ink : A.inkSoft;
  const statusText = s => ({'IN REVIEW': 'Needs you', WIP: 'Working', PLANNED: 'Planned', DONE: 'Completed', ARCHIVED: 'Archived', STOPPED: 'Stopped', stale: 'Stale'})[s] || s;
  const sessionState = row => row.state === 'turn_ended' ? 'Turn ended' : row.state === 'tool_ended' ? 'Tool ended' : row.state === 'unassociated' ? 'Activity unassociated' : 'Working';
  const shownModel = value => { const model = String(value || '').trim(); return model && model !== 'Model not reported' ? model : ''; };
  const oneLine = text => String(text || '').split('\n').map(line => line.trim()).find(Boolean) || '';
  const rowNote = task => {
    if (task.blockedBy) return 'blocked by ' + task.blockedBy;
    if (task.rowState === 'interrupted' || task.outcome === 'interrupted') return 'interrupted';
    if (task.rowState === 'limit reached' || task.capacity === 'LIMIT_REACHED') return 'limit reached';
    return '';
  };
  const gateLine = (gate, breaches) => {
    const gateText = gate === 'live' ? 'Gate live' : gate === 'missing' ? 'Gate missing' : gate === 'unavailable' ? 'Gate unavailable' : '';
    const breachText = breaches === 'unavailable' ? 'Breaches unavailable' : Number.isFinite(breaches) ? (breaches === 0 ? '0 breaches' : breaches + ' breaches') : '';
    return [gateText, breachText].filter(Boolean).join(' · ');
  };
  function TaskSession({task}) {
    const nodes = task.workflow || [], activity = task.activity || [], plan = task.plan || [], agents = task.agents || [];
    const progress = task.progress && typeof task.progress === 'object' ? task.progress : {};
    const parameters = new Map((task.parameters || []).map(row => [row.id, row.params || {}]));
    const notes = task.fileMessages || [];
    const shown = nodes.length || activity.length || plan.length || agents.length || Object.keys(progress).length || notes.length;
    if (!shown) return null;
    const text = value => value == null || typeof value === 'object' ? JSON.stringify(value) : String(value);
    return <section data-task-session={task.id} className="ws-flow">
      {nodes.length > 0 && <div><div className="ws-label">WORKFLOW</div><div className="ws-nodes">{nodes.map(node => <div key={node.id} className="ws-node" data-workflow-node={node.id}><b>{node.title || node.type}</b><span className="ws-small">{node.type}</span>{Object.entries(parameters.get(node.id) || {}).map(([key, value]) => <span key={key} className="ws-small" data-node-param={key}>{key}: {text(value)}</span>)}</div>)}</div></div>}
      <div data-task-activity><div className="ws-label">ACTIVITY</div>
        {agents.length > 0 && <p className="ws-small">Agents · {agents.join(', ')}</p>}
        {plan.length > 0 && <ol className="ws-plan">{plan.map((step, index) => <li key={index}>{step}</li>)}</ol>}
        {Object.keys(progress).length > 0 && <p className="ws-small" data-task-progress>{Object.entries(progress).map(([key, value]) => key + ' ' + text(value)).join(' · ')}</p>}
        {activity.map(row => <p key={row.id} className="ws-small" data-activity-row={row.id}>{row.status}{row.output != null && row.output !== '' ? ' · ' + text(row.output) : ''}</p>)}
        {notes.map(note => <div key={note.id} className="home-msg"><small>{note.who || 'Agent'}</small><p>{note.text}</p></div>)}
      </div>
    </section>;
  }
  function Task({task, on, select, ownerName}) {
    const u = useApp();
    const steps = task.steps || [], completed = steps.filter(step => /^(done|complete|completed)$/i.test(step.status)).length, a = task.activity;
    return <button className="listbutton ws-task" title={task.description || task.title} aria-selected={on} onClick={() => executeAction("ui.select", select)} onKeyDown={e => {
      if (e.code === 'Space') {
        e.preventDefault();
        select();
        executeAction("ui.show", u, 'Task details', {id: task.id});
      }
    }} draggable onDragStart={e => e.dataTransfer.setData('task', task.id)}>
      <span className="ws-task-icon" aria-hidden="true">{String(task.title || '?').trim().charAt(0).toUpperCase()}</span><div className="ws-task-line"><span className="ws-task-title">{task.title}</span>{(ownerName || task.owner) && <span className="ws-small ws-task-owner">{ownerName || task.owner}</span>}<span className="ws-task-state" style={{color: color(task.status)}}>{statusText(task.status)}</span>{rowNote(task) && <span className="ws-small" data-task-row-state={rowNote(task)}>{rowNote(task)}</span>}</div>
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
      {task.status === 'DONE' && oneLine(task.result) && <span className="ws-small ws-task-outcome" data-task-outcome={task.id}>{oneLine(task.result)}</span>}
      {task.status === 'WIP' && steps.length > 0 && <span role="progressbar" className="ws-progress" aria-label={task.title + ' steps'} aria-valuemin={0} aria-valuenow={completed} aria-valuemax={steps.length}><i style={{width: `${completed / steps.length * 100}%`}} /></span>}
    </button>;
  }
  // The pane layout library, loaded by the Studio build; a host without it renders the same columns unresizable.
  const RP = window.ReactResizablePanels;
  const Group = RP ? RP.Group : ({children, className, id, ...rest}) => <div id={id} className={className} data-screen={rest['data-screen']}>{children}</div>;
  const Column = RP ? RP.Panel : ({children}) => children;
  const Separator = RP ? RP.Separator : () => null;
  const RAIL = 48, LAYOUT_KEY = 'archhub.workshop.layout.v1';
  const readLayout = () => { try { return JSON.parse(window.localStorage.getItem(LAYOUT_KEY) || 'null') || {}; } catch (error) { return {error: String(error)}; } };
  const writeLayout = value => { try { if (value) window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(value)); else window.localStorage.removeItem(LAYOUT_KEY); return true; } catch (error) { return {error: String(error)}; } };
  const subscribeWidth = notify => { if (!window.addEventListener) return () => {}; window.addEventListener('resize', notify); return () => window.removeEventListener('resize', notify); };
  // Receipt words (designer 01a18ba7): Stored in the Workshop, Started in the session, Replied, Unavailable (no door), Uncertain.
  const receipt = (d, replied) => replied ? 'Replied' : d.state === 'delivered' ? 'Started' : /no live door|not a running|no joined agent|reads the message in the Workshop/i.test(d.reason || '') ? 'Unavailable' : 'Uncertain';
  const ownMessage = message => Boolean(message?.sender_key) && message.sender_key === message.viewer_key || message?.who === 'You' || message?.role === 'task';
  function TaskBrief({task}) {
    const what = oneLine(task.description || task.title);
    const result = oneLine(task.result);
    const next = (Array.isArray(task.plan) ? task.plan : task.steps || []).map(step => oneLine(typeof step === 'string' ? step : (step?.title || step?.text || step?.name || step?.what || ''))).find(Boolean);
    return <section data-task-summary className="ws-summary">
      <p><b>What</b> {what || 'Not yet recorded'}</p>
      <p><b>State</b> {statusText(task.status)}</p>
      <p><b>Latest result</b> {result || 'Not yet recorded'}</p>
      <p><b>Next</b> {next || 'Not yet recorded'}</p>
    </section>;
  }
  function AgentLog({messages, extra}) {
    const [open, setOpen] = React.useState(false);
    if (!messages.length && !extra) return null;
    return <section data-agent-log className="ws-agent-log">
      <button type="button" className="ws-link" aria-expanded={open} onClick={() => executeAction('ui.select', () => setOpen(!open))}>Agent log</button>
      {open && <div className="ws-agent-log-body">{extra}{messages.map(message => <article key={message.id}><b>{message.who || 'Agent'}</b><p>{message.text}</p></article>)}</div>}
    </section>;
  }
  function Messages({task, roles = {}, whoIs = who => ({name: who || 'Agent', detail: '', meta: ''}), onReply}) {
    const [inspect, setInspect] = React.useState(null);
    const all = task.messages;
    return <div className="ws-msgs">{all.map(m => {
      const own = Boolean(m.sender_key) && m.sender_key === m.viewer_key;
      const sender = own ? {name: 'You'} : whoIs(m.who, m.sender_key);
      const parent = m.reply_to && all.find(x => x.id === m.reply_to);
      const replies = all.filter(x => x.reply_to === m.id);
      const notice = !own && m.who === 'Workshop coordination';
      return <div key={m.id} className={'ws-msg' + (own ? ' own' : '') + (notice ? ' notice' : '')}>{!own && <Av id={sender.name} size={28} />}
        <div className="ws-msg-body" style={own ? {justifySelf: 'end', maxWidth: 640, padding: '12px 16px', borderRadius: '12px 12px 4px 12px', background: '#1a1a20', border: '1px solid #26262e'} : {}}>
          <div className="ws-msg-head">{!own && <b title={sender.meta || m.who}>{sender.name}</b>}{!own && (sender.detail || roles[m.who]) && <span className="ws-small">{sender.detail || roles[m.who]}</span>}
            {m.to && <span className="ws-small">→ {m.to.split(', ').map(label => whoIs(label).name).join(', ')}</span>}</div>
          {parent && <span className="ws-small ws-reply-ref">↳ reply to {parent.sender_key === parent.viewer_key ? 'You' : whoIs(parent.who, parent.sender_key).name}: {String(parent.text || '').slice(0, 80)}</span>}
          <Prose text={m.text} />
          <div className="flex ws-msg-foot">
            {(m.live || []).length > 0 ? <span className="flex ws-live" data-live-delivery>{m.live.map((d, i) => <Chip key={i} c={d.state === 'delivered' ? A.inkSoft : A.warn}>{receipt(d, replies.some(r => whoIs(r.who, r.sender_key).name === d.agent))} · {d.agent}</Chip>)}</span>
              : m.to && own && <span className="ws-small">Stored</span>}
            {['pending', 'delivered', 'answered'].includes(m.state) && <span role="status" data-delivery-state={m.state} className="ws-small">{m.state === 'answered' ? 'Answered' : m.state === 'delivered' ? 'Delivered' : 'Pending'}{m.delivery?.some(row => row.escalated) ? ' · Coordinator notified' : ''}</span>}
            {!own && onReply && sender.handle && <button type="button" className="ws-link" onClick={() => executeAction("ui.select", () => onReply({id: m.id, handle: sender.handle, name: sender.name}))}>Reply</button>}
            <button type="button" className="ws-link" aria-expanded={inspect === m.id} onClick={() => executeAction("ui.select", () => setInspect(inspect === m.id ? null : m.id))}>{inspect === m.id ? 'Hide details' : 'Inspect'}</button>
          </div>
          {inspect === m.id && <pre className="ws-inspect">{JSON.stringify({id: m.id, from: m.who, sender: m.sender_key, sent: m.created_at, reply_to: m.reply_to || null, delivery: m.live || []}, null, 2) + '\n\n' + (m.raw || m.text)}</pre>}
          {window.UI.TurnUsage && <window.UI.TurnUsage message={m} />}{window.UI.AnswerWidget && <window.UI.AnswerWidget message={m} />}{!own && window.UI.AnswerSources && <window.UI.AnswerSources message={m} />}{m.rule && <Chip c={A.purple}>Your rule: {m.rule}</Chip>}
        </div></div>;
    })}</div>;
  }
  // "To" is a joined agent session, Everyone, or BABOOM (free first); Send goes live into the chosen session.
  // People & agents and the To list come from one place: the Workshop people panel, the Workshop composer and the Canvas composer.
  function workshopPeople(s) {
      const agents = s.liveAgents || [];
      // Identity from what the session declared: its name (display_name) or host · project; provider and session id are
      // secondary metadata; two sessions of one provider never share a name (the session id is added when they would).
      const named = agents.map(a => {
        const [host, project, session = ''] = String(a.agent || '').split(' / ');
        const declared = a.name && a.name !== a.agent;
        return {a, name: declared ? a.name : [host || a.app, project].filter(Boolean).join(' · '), short: session.replace(/^session-/, '').slice(0, 6),
          meta: [host || a.app, session && 'session ' + session.replace(/^session-/, '').slice(0, 8)].filter(Boolean).join(' · ')};
      });
      named.forEach(n => { if (named.filter(o => o.name === n.name).length > 1 && n.short) n.name += ' · ' + n.short; });
      const row = (key, id, name, state, detail, handle, meta, model, gate, breaches) => ({key, id, name, state, detail, handle, meta, model: shownModel(model), gate: gate || '', breaches, role: [state, detail].filter(Boolean).join(' · ')});
      const people = [...named.map(({a, name, meta}) => row(a.handle, name, name, a.status && a.status !== 'unknown' ? a.status : 'Joined', a.task || 'No task declared', a.handle, meta, a.model, a.gate, a.breaches)),
        ...(s.agents || []).filter(p => !agents.some(a => a.app === p.runtime)).map(p => row(p.id, p.id, p.name,
          'Not joined · ' + (p.presence === 'working' ? 'Working' : p.presence === 'unknown' ? (p.status_text || 'Status unknown') : 'Idle'), p.presence === 'working' ? p.task : '', undefined, p.runtime, p.model, p.gate, p.breaches)),
        row('founder', 'You', 'You', 'Founder', 'Workspace owner', undefined, '', '', '', null)];
      // A message sender or recipient label -> the same identity as its People row.
      const whoIs = (label, session) => {
        const n = named.find(x => (session && x.a.session === session) || x.a.agent === label || x.a.name === label);
        return n ? {name: n.name, detail: n.a.task || '', meta: n.meta, handle: n.a.handle} : {name: label === '*' ? 'Everyone' : String(label || 'Agent').split(' / ').slice(0, 2).join(' · '), detail: '', meta: label || ''};
      };
      // The To list: every agent in People & agents (one not joined is shown, but cannot receive yet), Everyone, BABOOM.
      const choices = [...(agents.length > 1 ? [{key: 'everyone', handle: 'everyone', name: 'Everyone', detail: agents.length + ' joined sessions'}] : []),
        ...people.filter(p => p.key !== 'founder').map(p => ({key: p.key, handle: p.handle, name: p.name, detail: p.role, gate: p.gate, breaches: p.breaches})),
        {key: 'baboom', handle: '', name: 'BABOOM', detail: 'Free models first'}];
      return {agents, people, choices, whoIs};
  }  // DESIGNSYS-050 4.9 AgentPicker: one styled To-list; an agent that has not joined is shown but cannot receive yet.
  function AgentPicker({choices, to, setTo, startOpen = false}) {
    const [listOpen, setListOpen] = React.useState(startOpen);
    return <div className="ws-to" onKeyDown={e => e.key === 'Escape' && setListOpen(false)}>
      <button type="button" className="ws-link" aria-haspopup="listbox" aria-expanded={listOpen} aria-label="Recipient" onClick={() => executeAction("ui.select", () => setListOpen(!listOpen))}>To {choices.find(c => c.handle === to)?.name || 'BABOOM'} ▾</button>
      {listOpen && <div role="listbox" aria-label="Recipients" className="ws-to-list">{choices.map(c => <button type="button" role="option" key={c.key} aria-selected={c.handle === to} disabled={c.handle === undefined} className="listbutton spread" title={c.handle === undefined ? c.name + ' is running but has not joined this Workshop, so it cannot receive messages yet' : 'Send to ' + c.name} onClick={() => executeAction("ui.select", () => { setTo(c.handle); setListOpen(false); })}><span>{c.name}</span><span className="ws-small" data-agent-gate={c.gate || undefined} data-agent-breaches={c.breaches == null ? undefined : String(c.breaches)}>{[c.detail, gateLine(c.gate, c.breaches)].filter(Boolean).join(' · ')}</span></button>)}</div>}
    </div>;
  }
  function TaskComposer({choices, to, setTo, sendRef, replyTo, setReplyTo}) {
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
        const sent = await u.act(() => api.apiRouterChat(prompt, 'BABOOM', replyTo && replyTo.handle === to ? replyTo.id : undefined));
        if (!sent) { if (body === text) setText(body); return; }
        files.forEach(f => api.removeComposerAttachment(f.id));
        setReplyTo?.(null);
        await api.listTasks?.();
      } finally {
        setSending(false);
      }
    };
    sendRef.current = send;
    return <D.Composer as="form" className="ws-composer" onSubmit={e => { e.preventDefault(); executeAction("ui.select", send); }} style={{width: '100%', padding: '14px 16px', gap: 8}}>
      <AgentPicker choices={choices} to={to} setTo={setTo} />
      {replyTo && <div className="flex ws-small">Replying to {replyTo.name}<button type="button" className="ws-link" aria-label="Stop replying" onClick={() => executeAction("ui.select", () => setReplyTo(null))}>×</button></div>}
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
      [notesOpen, setNotesOpen] = React.useState(false), [notes, setNotes] = React.useState(''), sendRef = React.useRef(null), [replyTo, setReplyTo] = React.useState(null),
      [project, setProject] = React.useState('ArchHub');
    const roomScope = JSON.stringify([s.graph.id, s.profile.email, s.profile.signedIn, s.workshopMessagesScope]);
    const currentScope = React.useRef(roomScope), bodyRef = React.useRef(null), stuck = React.useRef(null);
    currentScope.current = roomScope;
    const [older, setOlder] = React.useState({scope: roomScope, messages: [], before: null, more: true});
    const previous = older.scope === roomScope ? older : {messages: [], before: null, more: true};
    const known = [...new Set((s.tasks || []).map(t => t.project).filter(Boolean))];
    const tasks = (s.tasks || []).filter(t => !t.project || t.project === project), focus = u.task || s.focusedTask || tasks.find(t => t.sessionOpen)?.id, task = tasks.find(t => t.id === focus) || tasks[0];
    const roomMessages = [...new Map([...previous.messages, ...(s.workshopMessages || [])].map(message => [message.id, message])).values()]
      .filter(message => (!message.project || message.project === project) && !(task?.agentLog || []).some(item => item.id === message.id) && !(task?.messages || []).some(item => item.id === message.id));
    const list = tasks.filter(t => !query || `${t.title} ${t.status}`.toLowerCase().includes(query.toLowerCase()));
    const waiting = new Set((s.approvals || []).filter(c => c.status === 'pending').map(c => c.taskId));
    const {agents, people, choices, whoIs} = workshopPeople(s);
    // Work | thread | People: react-resizable-panels (D-018). Drag below a side's minimum snaps it to a 48 px rail (VS Code sash);
    // the layout and the collapsed sides are kept under one key; a narrow window folds the sides to rails by itself.
    const width = React.useSyncExternalStore ? React.useSyncExternalStore(subscribeWidth, () => window.innerWidth || 1440, () => 1440) : 1440;
    const narrow = {people: width < 1244, work: width < 964};
    const [layoutEpoch, setLayoutEpoch] = React.useState(0), [rails, setRails] = React.useState({});
    const saved = readLayout(), workRef = React.useRef(null), peopleRef = React.useRef(null);
    const folded = side => narrow[side] || Boolean(saved.collapsed && saved.collapsed[side]);
    const rail = side => (size => { const on = size.inPixels <= RAIL + 1; if (Boolean(rails[side]) !== on) setRails(current => ({...current, [side]: on})); });
    const keepLayout = (layout, meta) => { if (meta && meta.isUserInteraction) writeLayout({layout, collapsed: {work: Boolean(workRef.current && workRef.current.isCollapsed()), people: Boolean(peopleRef.current && peopleRef.current.isCollapsed())}}); };
    const reply = r => { setTo(r.handle); setReplyTo(r); };
    const roles = Object.fromEntries(agents.filter(a => a.task).map(a => [a.name, a.task]));
    // A task's people: the joined sessions that declared it, else its runtime's provider name.
    // Live data: a new message keeps the thread at its end (like Slack) when it was there; a task change opens at its end.
    const messageCount = roomMessages.length + ((task?.messages || []).length);
    const stickToEnd = el => {
      const box = bodyRef.current, key = (task?.id || 'room') + ':' + messageCount;
      if (!el || !box || stuck.current === key) return;
      if (String(stuck.current).split(':')[0] !== (task?.id || 'room') || box.scrollHeight - box.scrollTop - box.clientHeight < 240) box.scrollTop = box.scrollHeight;
      stuck.current = key;
    };
    const sessionsOf = t => agents.filter(a => a.agent === t.owner || (t.declarations || []).some(d => d.agent === a.agent));  // owner is the session label
    const nameFor = t => sessionsOf(t).map(a => a.name).join(' and ') || (s.providers || []).find(p => p.id === t.owner)?.name || t.owner;
    const recipient = to ?? (task && (sessionsOf(task)[0] || agents.find(a => a.app === task.owner)) || agents[0])?.handle ?? '';
    const request = task?.description || task?.messages.find(m => m.sender_key && m.sender_key === m.viewer_key)?.text;
    const taskMessages = [...(task?.fileMessages || []), ...(task?.messages || [])];
    const briefMessages = taskMessages.filter(message => message.role === 'task' || ownMessage(message) || (!message.sender_key && !message.to)).map(message => ({...message, text: oneLine(message.text)}));
    const boundLog = [...(task?.agentLog || []), ...(task?.messages || []).filter(message => message.role !== 'task' && !ownMessage(message))];
    return <Group key={layoutEpoch + ':' + narrow.work + narrow.people} id="workshop-layout" orientation="horizontal" data-screen="workshop" className={'ws' + (rails.work ? ' l-rail' : '') + (rails.people ? ' r-rail' : '')}
      defaultLayout={narrow.work || narrow.people || folded('work') || folded('people') ? undefined : saved.layout} onLayoutChanged={keepLayout}>
  <Column id="work" panelRef={workRef} collapsible collapsedSize={RAIL} minSize={200} defaultSize={folded('work') ? RAIL : 248} groupResizeBehavior="preserve-pixel-size" onResize={rail('work')}>
  <aside id="ws-work" data-workshop-column="work" className="ws-col ws-work">
    <div className="spread ws-head"><h2>Work</h2><button className="ws-link" title="New task" onClick={() => executeAction("ui.show", u, 'New task')}>+<span className="pane-text"> New task</span></button></div>
    {known.length > 0 && <select aria-label="Project room" value={known.includes(project) ? project : known[0]} onChange={e => setProject(e.target.value)}>{known.map(name => <option key={name} value={name}>{name}</option>)}</select>}
    <input aria-label="Search work" className="ws-search" placeholder="Search work…" value={query} onChange={e => setQuery(e.target.value)} />
    <div className="scroll ws-list">{groupsFor(history, waiting, query).map(([name, member, stage]) => {
      const rows = list.filter(member);
      return <div key={name} className="ws-group" data-workshop-group={name} onDragOver={e => e.preventDefault()} onDrop={e => {
        e.preventDefault();
        const id = e.dataTransfer.getData('task');
        if (id) executeAction("setTaskStatus", u, id, stage);
      }}><div className="spread ws-label"><span>{name}</span><span>{rows.length}</span></div>{rows.map(t => <Task key={t.id} task={t} ownerName={nameFor(t)} on={task?.id === t.id} select={async () => { executeAction("ui.setTask", u, t.id); await executeAction("openTaskGraph", u, t.id); }} />)}</div>;
    })}</div>
    <div className="ws-foot"><span>Completed &amp; archived</span><span className="ws-small">All work stays searchable</span>
      <button className="ws-link" aria-pressed={history} onClick={() => executeAction("ui.select", () => setHistory(!history))}>{history ? 'Hide history' : 'Show history →'}</button>
      <button className="ws-link" title="Back to the default column sizes" onClick={() => executeAction("ui.select", () => { writeLayout(null); setRails({}); setLayoutEpoch(layoutEpoch + 1); })}>Reset layout</button></div>
  </aside>
  </Column>
  <Separator className="pane-splitter" aria-label="Resize the Work pane" />
  <Column id="thread" minSize={360}>
  <main data-workshop-column="thread" className="ws-thread">
    <header className="spread"><div><h1>{task?.title || (roomMessages.length ? 'Workshop room' : 'What should the agents do?')}</h1><p className="ws-sub">{task ? [nameFor(task), statusText(task.status)].filter(Boolean).join(' · ') : 'One room · ' + (s.graph.name || 'Workshop')}</p></div>
      <button className="ws-link" onClick={() => executeAction("ui.select", async () => {
        if (!task) { executeAction("ui.go", u, "canvas"); return; }
        const opened = await executeAction("openTaskGraph", u, task.id);
        if (opened) { executeAction("ui.setTask", u, opened.taskId || task.id); executeAction("ui.setSelectedNodeId", u, opened.taskId || task.id); executeAction("ui.go", u, "canvas"); }
      })}>Open in Canvas ↗</button></header>
    <div className="scroll ws-body" ref={bodyRef}><div className="ws-stack">
      {(s.approvals || []).filter(card => card.approvalKind === 'ask' && card.status === 'pending' && card.id !== task?.approvalId).map(card => <ApprovalCard key={card.id} id={card.id} />)}
      {task ? <><TaskBrief task={{...task, description: request || task.description}} />
        {task.summary && <section data-workshop-standing className="ws-request"><div className="ws-label">WHERE THIS STANDS</div><Prose text={task.summary} lines={8} /></section>}
        <TaskSession task={task} />
        <Messages task={{...task, messages: briefMessages}} roles={roles} whoIs={whoIs} onReply={reply} />
        <AgentLog messages={boundLog} extra={(previous.before ? previous.more : s.workshopMessagesMore) ? <Btn sm ghost onClick={async () => {
          const page = await executeAction("listWorkshopMessages", u, previous.before || s.workshopMessagesBefore);
          if (currentScope.current === roomScope && Array.isArray(page?.messages)) setOlder({scope: roomScope, messages: [...page.messages, ...previous.messages], before: page.next_before, more: page.more});
        }}>Older messages</Btn> : null} />
        {task.approvalId && <ApprovalCard id={task.approvalId} />}
        {task.status === 'STOPPED' && <Btn onClick={() => executeAction("reassignTask", u, task.id)}>Continue with another agent</Btn>}
        {task.status === 'DONE' && task.result && <section data-workshop-result className="ws-request"><div className="ws-label">RESULT</div><Prose text={task.result} lines={6} /></section>}
        {task.status === 'DONE' && <div className="flex"><Btn onClick={() => executeAction("ui.go", u, 'watcher')}>Open result</Btn><Btn onClick={() => executeAction("ui.schedule", u, task.title)}>Repeat this</Btn></div>}
      </> : <>
        {(previous.before ? previous.more : s.workshopMessagesMore) && <Btn sm ghost onClick={async () => {
          const page = await executeAction("listWorkshopMessages", u, previous.before || s.workshopMessagesBefore);
          if (currentScope.current === roomScope && Array.isArray(page?.messages)) setOlder({scope: roomScope, messages: [...page.messages, ...previous.messages], before: page.next_before, more: page.more});
        }}>Older messages</Btn>}
        {roomMessages.length > 0 && <Messages task={{messages: roomMessages}} roles={roles} whoIs={whoIs} onReply={reply} />}
        {roomMessages.length === 0 && <Empty>Create a task to begin.</Empty>}
      </>}
      <i ref={stickToEnd} aria-hidden="true" />
    </div></div>
    <div className="ws-dock"><div>{D.Composer ? <TaskComposer choices={choices} to={recipient} setTo={setTo} sendRef={sendRef} replyTo={replyTo} setReplyTo={setReplyTo} /> : window.UI.Composer && <window.UI.Composer taskId={task?.id} />}</div></div>
  </main>
  </Column>
  <Separator className="pane-splitter" aria-label="Resize the People and agents pane" />
  <Column id="people" panelRef={peopleRef} collapsible collapsedSize={RAIL} minSize={240} defaultSize={folded('people') ? RAIL : 280} groupResizeBehavior="preserve-pixel-size" onResize={rail('people')}>
  <aside id="ws-people" data-workshop-column="people" className="ws-col ws-people">
    <h2>People &amp; agents</h2><p className="ws-small ws-note">{s.liveAgents === undefined ? 'Loading agents…' : people.length + ' in this Workshop · ' + agents.length + ' joined'}</p>{s.liveAgents !== undefined && !agents.length && <p className="ws-small ws-note">No agent session has joined yet. A session that joins appears here and can be messaged.</p>}
    <div className="scroll ws-people-list">{people.map(p => <div key={p.key} className={'ws-person' + (recipient && p.handle === recipient ? ' to' : '')}><button className="button-reset ws-person-name" title={[(p.handle ? 'Send to ' : '') + p.name, p.role, p.model, p.meta].filter(Boolean).join(' · ')} onClick={() => p.handle ? executeAction("ui.select", () => setTo(p.handle)) : executeAction("ui.show", u, 'Agent', {id: p.id})}><Av id={p.id} size={28} /><span className="pane-text"><b>{p.name}</b><span className="ws-small">{p.state}</span>{p.model ? <span className="ws-small" data-agent-model={p.model}>{p.model}</span> : null}</span></button>{p.detail && <span className="pane-text"><Clamp text={p.detail} /></span>}</div>)}</div>
    <hr className="ws-rule" />
    <h2>Meeting input</h2><p className="ws-small ws-note">Notes for this task go to {recipient ? (agents.find(a => a.handle === recipient)?.name || 'Everyone') : 'BABOOM'}.</p>
    {notesOpen ? <div className="grid"><textarea aria-label="Meeting notes" rows={6} value={notes} onChange={e => setNotes(e.target.value)} placeholder="Paste meeting notes…" /><div className="flex"><Btn sm p disabled={!notes.trim()} onClick={() => executeAction("ui.select", async () => { await sendRef.current?.('Meeting notes:\n' + notes); setNotes(''); setNotesOpen(false); })}>Send notes</Btn><Btn sm ghost onClick={() => executeAction("ui.select", () => setNotesOpen(false))}>Cancel</Btn></div></div>
      : <button className="ws-link" onClick={() => executeAction("ui.select", () => setNotesOpen(true))}>+ Paste notes</button>}
  </aside>
  </Column>
 </Group>;
  }
  window.UI.Workshop = Win;
  window.UI.TaskSession = TaskSession;
  window.UI.AgentPicker = AgentPicker;
  window.UI.workshopPeople = workshopPeople;
  window.UI.Messages = Messages;
  window.UI.Task = Task;
})();
