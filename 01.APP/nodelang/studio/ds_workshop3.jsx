// ds_workshop3.jsx: the Workshop's shared parts (task rows, messages, the To list and the composer) used by the Workshop
// dock panel, the Canvas thread and the dialogs; the standalone Workshop page is gone (founder 2026-11-26).
// Send is the composer's existing @mention path (/api/router/chat -> workshop_live.send_as_founder, live injection).
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {A, D, useData, useApp, Btn, Chip, Av} = window.UI;
  // The shared text blocks (ui.jsx); plain text where a host renders this file without them.
  const Prose = props => window.UI.Prose ? React.createElement(window.UI.Prose, props) : <p>{props.text}</p>;
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
  const rowNote = window.UI.taskRowReason;
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
    }} draggable onDragStart={e => {e.dataTransfer.setData('task', task.id);if(task.sessionPath)e.dataTransfer.setData('session',task.sessionPath);}}>
      <span className="ws-task-icon" aria-hidden="true">{String(task.title || '?').trim().charAt(0).toUpperCase()}</span><div className="ws-task-line"><span className="ws-task-title">{task.title}</span>{(ownerName || task.owner) && <span className="ws-small ws-task-owner">{ownerName || task.owner}</span>}<span className="ws-task-state" style={{color: color(task.status)}}>{statusText(task.status)}</span>{rowNote(task) && <span className="ws-small" data-task-row-state={rowNote(task)}>{rowNote(task)}</span>}</div>
      {Array.isArray(a?.sessions) && <div data-agent-activity role="status" className="ws-activity">
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
  function Messages({task, roles = {}, whoIs = who => ({name: who || 'Agent', detail: '', meta: ''}), onReply}) {
    const [inspect, setInspect] = React.useState(null);
    const all = task.messages;
    return <div className="ws-msgs">{all.map(m => {
      const own = Boolean(m.sender_key) && m.sender_key === m.viewer_key;
      const sender = own ? {name: 'You'} : whoIs(m.who, m.sender_key);
      const parent = m.reply_to && all.find(x => x.id === m.reply_to);
      const notice = !own && m.who === 'Workshop coordination';
      return <div key={m.id} className={'ws-msg' + (own ? ' own' : '') + (notice ? ' notice' : '')}>{!own && <Av id={sender.name} size={28} />}
        <div className="ws-msg-body" style={own ? {justifySelf: 'end', maxWidth: 640, padding: '12px 16px', borderRadius: '12px 12px 4px 12px', background: '#1a1a20', border: '1px solid #26262e'} : {}}>
          <div className="ws-msg-head">{!own && <b title={sender.meta || m.who}>{sender.name}</b>}{!own && (sender.detail || roles[m.who]) && <span className="ws-small">{sender.detail || roles[m.who]}</span>}
            {m.to && <span className="ws-small">→ {m.to.split(', ').map(label => whoIs(label).name).join(', ')}</span>}</div>
          {parent && <span className="ws-small ws-reply-ref">↳ reply to {parent.sender_key === parent.viewer_key ? 'You' : whoIs(parent.who, parent.sender_key).name}: {String(parent.text || '').slice(0, 80)}</span>}
          <Prose text={m.text} />
          <div className="flex ws-msg-foot">
            {window.UI.deliveryAttention?.(m) && <Chip c={A.warn} data-delivery-attention="" role="status">{window.UI.deliveryAttention(m)}</Chip>}
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
        {key: 'baboom', handle: '', name: 'BABOOM', detail: 'Free models first'}, ...startChoices(s.chatAgents)];
      return {agents, people, choices, whoIs};
  }
  // START a chat agent (never a joined session): the server's one answer to "which chat agents can start here"
  // (api.listChatAgents, asked when a Recipient menu opens). Last in the list, so the default stays BABOOM.
  function startChoices(chat) {
    const row = (key, name, detail, extra) => ({key, handle: undefined, name, detail, reason: detail, ...extra});
    if (!chat || chat.status === 'waiting') return [row('start-waiting', 'Start a chat', 'Checking which agents this PC can start…', {})];
    if (chat.status === 'error') return [row('start-error', 'Start a chat', 'Could not check which agents can start: ' + chat.error + ' Choose to retry.', {act: api.listChatAgents})];
    if (!chat.rows.length) return [row('start-none', 'Start a chat', 'No chat agent can be started on this PC.', {})];
    return chat.rows.map(r => r.startable ? {key: 'start:' + r.id, handle: 'start:' + r.id, start: r.id, name: r.name, detail: 'Start a new chat · it can read files, not change them'}
      : row('start:' + r.id, r.name, r.reason || r.name + ' cannot be started on this PC.', {}));
  }
  // One composer turn: a start choice sends the plain prompt with agent=<id> (the server starts that chat agent or
  // refuses); any other choice is the @mention of a joined session, or BABOOM.
  function chatTurn(choices, to, body) {
    const chosen = choices.find(c => c.handle === to) || {};
    if (chosen.start) return {prompt: body, agent: chosen.start, resume: Boolean(chosen.resume)};
    return {prompt: (!to || new RegExp('(^|\\s)@' + to + '\\b').test(body) ? '' : '@' + to + ' ') + body, agent: 'BABOOM', resume: false};
  }
  // Inside a session (design v63 C1-C2): "All agents" is this session's agents. Send goes to the session's thread and to them;
  // BABOOM answers only when picked. An assigned agent that has not joined has no handle and cannot receive yet.
  function sessionAll(choices, agents) {
    const handles = [...new Set(choices.filter(c => c.handle && c.key !== 'baboom' && c.key !== 'everyone' && !c.start
      && agents.some(name => [c.name, c.handle, c.key].includes(name))).map(c => c.handle))];
    return {key: 'session', handle: 'session', name: 'All agents', handles,
      detail: handles.length ? 'This session · ' + handles.length + ' agent' + (handles.length > 1 ? 's' : '') : 'No agent of this session has joined yet'};
  }
  const sessionTurn = (all, body) => ({prompt: all.handles.map(handle => '@' + handle).join(' ') + ' ' + body, agent: 'BABOOM', resume: false});  // The chat agent a thread is talking to: the one this app started in it (state.chatThreads), or, after a restart,
  // the chat agent that sent the thread's last answer. '' when none, or when that chat ended.
  function threadChat(s, task) {
    const key = task?.id || '', rows = s.chatAgents?.rows || [];
    if (!task || (s.chatEnded || {})[key]) return '';
    if ((s.chatThreads || {})[key] !== undefined) return s.chatThreads[key];
    const last = [...(task.messages || []), ...(task.agentLog || [])].filter(m => !(m.sender_key && m.sender_key === m.viewer_key)).at(-1);
    return rows.find(r => last && r.name === last.who)?.id || '';
  }
  // A thread's own choices: its running chat first ("continue"), then the shared list; an ended chat says so on its start row.
  function threadChoices(s, task, choices) {
    const chat = threadChat(s, task), ended = (s.chatEnded || {})[task?.id || ''];
    const row = (s.chatAgents?.rows || []).find(r => r.id === chat);
    const marked = choices.map(c => ended && c.start === ended ? {...c, detail: 'Your chat in this thread ended · start a new one'} : c);
    return row ? [{key: 'chat:' + row.id, handle: 'chat:' + row.id, start: row.id, resume: true, name: row.name + ' chat', detail: 'This thread\'s chat · your next message continues it'}, ...marked] : marked;
  }
  // Who a thread's composer addresses when the user has not picked: its running chat, then an ended chat's start choice.
  function threadDefault(s, task) {
    const chat = threadChat(s, task), ended = (s.chatEnded || {})[task?.id || ''];
    return chat ? 'chat:' + chat : ended ? 'start:' + ended : null;
  }  // DESIGNSYS-050 4.9 AgentPicker: one styled To-list; an agent that has not joined is shown but cannot receive yet.
  function AgentPicker({choices, to, setTo, startOpen = false, label = 'Recipient'}) {
    const [listOpen, setListOpen] = React.useState(startOpen);
    const chosen = choices.find(c => c.handle === to);
    return <div className="ws-to" onKeyDown={e => e.key === 'Escape' && setListOpen(false)}>
      <button type="button" className="ws-link" aria-haspopup="listbox" aria-expanded={listOpen} aria-label={label} onClick={() => executeAction("ui.select", () => { if (!listOpen) api.listChatAgents?.(); setListOpen(!listOpen); })}>{chosen?.key === 'session' ? <span className="ws-to-icon" aria-hidden="true"><window.AHIcon name="workshop" size={13}/></span> : <window.UI.Av id={chosen?.name || to || 'BABOOM'} size={22}/>}<span className="recipient-name">{chosen?.resume || chosen?.key === 'session' ? chosen.name : chosen?.start ? 'Start ' + chosen.name : '@' + (chosen?.name || to || 'BABOOM')}</span><window.AHIcon name="arrow" size={12} style={{transform:'rotate(90deg)'}}/></button>
      {listOpen && <div role="listbox" aria-label="Recipients" className="ws-to-list">{choices.map(c => <button type="button" role="option" key={c.key} data-chat-start={c.key.startsWith('start') ? c.start || 'unavailable' : undefined} data-chat-continue={c.resume ? c.start : undefined} aria-selected={c.handle === to} disabled={c.handle === undefined && !c.act} className="listbutton spread" title={c.reason || (c.handle === undefined ? c.name + ' is running but has not joined this Workshop, so it cannot receive messages yet' : (c.start && !c.resume ? 'Start a new ' : 'Send to ') + c.name)} onClick={() => executeAction("ui.select", () => { if (c.act) { c.act(); return; } setTo(c.handle); setListOpen(false); })}><span>{c.start && !c.resume ? 'Start ' + c.name : c.name}</span><span className="ws-small" data-agent-gate={c.gate || undefined} data-agent-breaches={c.breaches == null ? undefined : String(c.breaches)}>{[c.detail, gateLine(c.gate, c.breaches)].filter(Boolean).join(' · ')}</span></button>)}</div>}
    </div>;
  }
  function TaskComposer({choices, to, setTo, sendRef, replyTo, setReplyTo, draft, setDraft, onSend, docked = false, thread = false, busy = false}) {
    const s = useData(), u = useApp();
    const [localText, setLocalText] = React.useState(''), [sending, setSending] = React.useState(false);
    const [expanded, setExpanded] = React.useState(false);
    const field = React.useRef(null);
    window.UI.useAskBaboom(setTo, field, setDraft || setLocalText);
    const text = draft === undefined ? localText : draft, setText = setDraft || setLocalText;
    const files = s.composerAttachments || [];
    const send = async (body = text) => {
      if (onSend) return onSend();
      if (!body.trim()) return null;
      const turn = chatTurn(choices, to, body);
      const prompt = turn.prompt + (files.length ? '\nAttached project file nodes: ' + JSON.stringify(files.map(f => ({id: f.id, path: f.path}))) : '');
      if (body === text) setText('');
      setSending(true);
      try {
        const sent = await u.act(() => api.sendChatTurn({...turn, prompt}, replyTo && replyTo.handle === to ? replyTo.id : undefined, undefined));
        if (!sent) { if (body === text) setText(body); return null; }
        files.forEach(f => api.removeComposerAttachment(f.id));
        setReplyTo?.(null);
        await api.listTasks?.();
        return sent;
      } finally {
        setSending(false);
      }
    };
    if (sendRef) sendRef.current = send;
    if (docked) return <D.Composer as="form" className="dx-composer v22g-composer v48-composer" data-design="composer.surface" data-expanded={expanded} data-dx="composer" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setExpanded(false);}} onSubmit={e=>{e.preventDefault();send();}}>
      <span data-design={thread ? 'thread.to' : 'composer.to'}><AgentPicker choices={choices} to={to} setTo={setTo} /></span>
      <textarea dir="auto" ref={field} data-design={thread ? 'thread.msg' : 'composer.msg'} aria-label="Message" placeholder={(c => c?.key === 'session' ? 'Message the agents' : 'Message ' + (c?.name || to || 'agents'))(choices.find(c=>c.handle===to))} rows={1} value={text} onFocus={()=>setExpanded(true)} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}}} />
      <button type="button" className="dx-quiet" data-design={thread ? 'thread.more' : 'composer.attach'} aria-label="Attach" onClick={()=>u.show('Canvas attachments')}>+</button>
      <Btn p type="button" data-design="composer.send" aria-busy={busy} disabled={!text.trim()||busy} onClick={event=>executeAction('ui.select',send,event)}><window.AHIcon name="send" size={13}/>Send</Btn>
    </D.Composer>;
    return <D.Composer as="form" className="ws-composer" onSubmit={e => { e.preventDefault(); executeAction("ui.select", send); }} style={{width: '100%', padding: '14px 16px', gap: 8}}>
      <AgentPicker choices={choices} to={to} setTo={setTo} />
      {replyTo && <div className="flex ws-small">Replying to {replyTo.name}<button type="button" className="ws-link" aria-label="Stop replying" onClick={() => executeAction("ui.select", () => setReplyTo(null))}>×</button></div>}
      {files.length > 0 && <div className="flex">{files.map(f => <button type="button" key={f.id} className="ws-link" onClick={() => executeAction("ui.select", () => u.act(() => api.removeComposerAttachment(f.id)))}>{f.name || f.path} ×</button>)}</div>}
      <textarea dir="auto" ref={field} className="composer-input ws-input" rows={2} aria-label="Message" placeholder="Message this task…" value={text} onChange={e => setText(e.target.value)} onKeyDown={e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
      }} />
      <div className="flex ws-tools">
        {u.pickFile && <button type="button" className="ws-link" onClick={() => executeAction("ui.select", u.pickFile)}>Attach</button>}
        {u.voice && api.supportsAction?.('startVoiceInput') !== false && <button type="button" className="ws-link" onClick={() => executeAction("ui.select", () => u.voice(setText))}>Voice</button>}
        <span className="fill" /><Btn p type="submit" aria-busy={sending} disabled={!text.trim()}>Send</Btn>
      </div>
    </D.Composer>;
  }
  window.UI.TaskComposer = TaskComposer;
  window.UI.TaskSession = TaskSession;
  window.UI.AgentPicker = AgentPicker;
  window.UI.workshopPeople = workshopPeople;
  window.UI.chatTurn = chatTurn;
  window.UI.sessionAll = sessionAll;
  window.UI.sessionTurn = sessionTurn;
  window.UI.threadChoices = threadChoices;
  window.UI.threadDefault = threadDefault;
  window.UI.Messages = Messages;
  window.UI.Task = Task;
})();
