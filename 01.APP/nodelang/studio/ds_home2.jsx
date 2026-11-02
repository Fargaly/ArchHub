// Home plate: archhub-current-home.svg (Penpot rev 1444). Live task data fills the plate's slots.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const api = window.ArchHubAPI;
  const {D, useData, useApp, Btn} = window.UI;
  function Sheet({mark = false, large = false}) {
    const s = useData(), w = s.watcher;
    const points = w.geometry.walls.flatMap(line => [[line[0], line[1]], [line[2], line[3]]]);
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    const bounds = points.length ? [Math.min(...xs), Math.min(...ys), Math.max(1, Math.max(...xs) - Math.min(...xs)), Math.max(1, Math.max(...ys) - Math.min(...ys))] : [0, 0, 1, 1];
    return <svg width={large ? '100%' : 86} height={large ? 112 : 60} viewBox={bounds.join(' ')} aria-label={w.host || 'Source preview'} style={{borderRadius: 6, background: 'var(--current-color-ce7e3db)', display: 'block'}}><g fill="none" stroke={mark ? 'var(--color-accent)' : 'var(--current-color-c6b675f)'} strokeWidth="1" vectorEffect="non-scaling-stroke">{w.geometry.walls.map(([x1, y1, x2, y2], i) => <path key={i} d={`M${x1} ${y1}L${x2} ${y2}`} />)}</g></svg>;
  }
  const statusText = st => ({'IN REVIEW': 'Needs you', WIP: 'Working', PLANNED: 'Planned', DONE: 'Completed', ARCHIVED: 'Archived', STOPPED: 'Stopped'})[st] || st || '';
  const KEY = 'archhub.home.layout.v1';
  const readLayout = () => { try { return JSON.parse(window.localStorage.getItem(KEY) || 'null') || {}; } catch (error) { return {error: error instanceof Error ? error.message : String(error)}; } };
  let homeSetFace = detail => { void detail; };
  const ensureHomeView = () => {
    if (ensureHomeView.bound) return;
    ensureHomeView.bound = true;
    window.addEventListener('archhub:home-view', event => {
      if (event.detail === 'canvas' || event.detail === 'workshop') homeSetFace(event.detail);
    });
  };
  const writeLayout = value => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(value));
      return {ok: true};
    } catch (error) {
      return {ok: false, error: error instanceof Error ? error.message : String(error)};
    }
  };
  const describe = value => {
    if (value == null || value === '') return '';
    if (Array.isArray(value)) return value.map(describe).filter(Boolean).join(' · ');
    if (typeof value === 'object') {
      const head = ['title', 'name', 'text', 'label', 'what', 'summary'].map(key => value[key]).find(item => typeof item === 'string' && item);
      const rest = Object.entries(value).filter(([key, item]) => item != null && item !== '' && !['id', 'title', 'name', 'text', 'label', 'what', 'summary'].includes(key)).slice(0, 8)
        .map(([key, item]) => key + ' ' + (typeof item === 'object' ? describe(item) : String(item)));
      return [head, ...rest].filter(Boolean).join(' · ');
    }
    return String(value);
  };
  const sameList = (before, after) => {
    const left = Array.isArray(before) ? before.map(item => String(item)) : [];
    const right = Array.isArray(after) ? after.map(item => String(item)) : [];
    return left.length === right.length && left.every((item, index) => item === right[index]);
  };
  const commitList = (before, after, save) => {
    if (sameList(before, after)) return false;
    save(after);
    return true;
  };
  const RP = window.ReactResizablePanels;
  const Group = RP ? RP.Group : ({children, className, id}) => <div id={id} className={className}>{children}</div>;
  const Column = RP ? RP.Panel : ({children, className}) => <div className={className}>{children}</div>;
  const Separator = RP ? RP.Separator : () => null;
  const portFace = p => ({id: p.id, l: p.name || p.id, t: p.type || p.dataType || 'any', list: !!p.list});
  function ItemList({label, items, choices, onCommit}) {
    const source = Array.isArray(items) ? items.map(item => String(item)) : [];
    const stamp = source.join('\u0001');
    const [hold, setHold] = React.useState({stamp, rows: source});
    const rows = hold.stamp === stamp ? hold.rows : source;
    const setRows = next => setHold({stamp, rows: typeof next === 'function' ? next(rows) : next});
    const commit = next => {
      const cleaned = (Array.isArray(next) ? next : []).map(item => String(item)).filter(item => item !== '');
      if (!commitList(source, cleaned, onCommit)) return false;
      setRows(cleaned);
      return true;
    };
    return <div className="dx-fact" data-dx-list={label}>
      <span>{label}</span>
      {rows.length === 0 ? <b>Not yet recorded</b> : null}
      {rows.map((row, index) => choices ? <select key={stamp + ':' + index} aria-label={label + ' ' + (index + 1)} value={row} onChange={event => { if (event.target.value === row) return; const next = rows.slice(); next[index] = event.target.value; commit(next); }}>
        <option value="">Choose</option>
        {row && !choices.some(choice => choice.value === row) && <option value={row}>{row}</option>}
        {choices.map(choice => <option key={choice.key} value={choice.value}>{choice.name}</option>)}
      </select> : <input key={stamp + ':' + index} aria-label={label + ' ' + (index + 1)} defaultValue={row} onBlur={event => { if (event.target.value === row) return; const next = rows.slice(); next[index] = event.target.value; commit(next); }} />)}
      <button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => setRows(current => [...current, '']))}>{choices ? '+ Add agent' : '+ Add'}</button>
    </div>;
  }
  function NodeFace({n, owner}) {
    const state = n.status || n.result?.status || '';
    return <D.Node data-workflow-node={n.id} title={n.title || n.type || 'Node'} sub={n.type || ''} glyph={String(n.title || n.type || '?').trim().charAt(0).toUpperCase()} gc="var(--color-accent)" w={280} ins={(n.inputs || []).map(portFace)} outs={(n.outputs || []).map(portFace)} foot={[state, owner].filter(Boolean).join(' · ')} footc={state === 'Done' ? 'var(--color-ok)' : state ? 'var(--color-warn)' : undefined} />;
  }
  function Home() {
    const s = useData(), u = useApp();
    const [query, setQuery] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [history, setHistory] = React.useState(false);
    const [text, setText] = React.useState('');
    const [sending, setSending] = React.useState(false);
    const [to, setTo] = React.useState('');
    const [checkpoint, setCheckpoint] = React.useState('');
    const [face, setFace] = React.useState('workshop');
    const [request, setRequest] = React.useState('loaded');
    const [failure, setFailure] = React.useState('');
    const retrySave = React.useRef(() => {});
    homeSetFace = setFace;
    ensureHomeView();
    const saved = readLayout();
    const tasks = (s.tasks || []).filter(t => history || t.status !== 'ARCHIVED');
    const waiting = new Set((s.approvals || []).filter(c => c.status === 'pending').map(c => c.taskId));
    const list = tasks.filter(t => (!status || t.status === status) && (!query || `${t.title} ${t.status}`.toLowerCase().includes(query.toLowerCase())));
    const focus = u.task || s.focusedTask || tasks.find(t => t.sessionOpen)?.id;
    const task = tasks.find(t => t.id === focus) || list[0];
    const people = window.UI.workshopPeople ? window.UI.workshopPeople(s) : {people: [], choices: [], whoIs: label => ({name: label || 'Agent'})};
    const ownerOf = t => {
      if (!t) return '';
      const live = (s.liveAgents || []).find(a => a.agent === t.owner || (t.declarations || []).some(d => d.agent === a.agent));
      if (live) return live.name && live.name !== live.agent ? live.name : (live.name || '');
      return (s.providers || []).find(p => p.id === t.owner)?.name || t.owner || '';
    };
    const needs = list.filter(t => t.status === 'IN REVIEW' || t.status === 'STOPPED' || waiting.has(t.id));
    const working = list.filter(t => t.status === 'WIP' && !waiting.has(t.id));
    const planned = list.filter(t => t.status === 'PLANNED' && !waiting.has(t.id));
    const done = history ? list.filter(t => t.status === 'DONE' || t.status === 'ARCHIVED') : [];
    const rules = Array.isArray(task?.rules) ? task.rules.map(item => typeof item === 'string' ? item : describe(item)) : [];
    const agents = Array.isArray(task?.agents) ? task.agents.map(item => typeof item === 'string' ? item : describe(item)) : [];
    const folders = describe(task?.folders);
    const references = describe(task?.references);
    const session = task?.sessionPath || '';
    const fileName = session ? session.split(/[/\\]/).pop() : '';
    const plan = Array.isArray(task?.plan) ? task.plan : [];
    const workflow = Array.isArray(task?.workflow) ? task.workflow : [];
    const activity = Array.isArray(task?.activity) ? task.activity : [];
    const outputs = [task?.result, ...(activity.map(row => row.output).filter(v => v != null && v !== ''))].filter(Boolean);
    const messages = [...new Map([...(task?.fileMessages || []), ...((task?.messages || []).filter(m => m.role === 'task'))].map((m, i) => [m.id || 'file-' + i, m])).values()];
    const sameFile = !!(task?.sessionPath && s.sessionFile && task.sessionPath === s.sessionFile);
    const nodes = (sameFile ? s.graph?.nodes || [] : []).filter(n => !workflow.length || workflow.some(row => row.id === n.id));
    const showCanvas = async () => { setFace('canvas'); if (task) await u.act(() => api.openTaskGraph(task.id)); };
    const choices = people.choices?.length ? people.choices : [{key: 'baboom', handle: '', name: 'BABOOM'}];
    const recipient = to || (task && (s.liveAgents || []).find(a => a.agent === task.owner)?.handle) || choices[0]?.handle || '';
    const model = (people.people || []).find(p => p.handle && p.handle === recipient)?.model || '';
    const running = (s.hosts || []).filter(h => ['connected', 'listening', 'running'].includes(h.state));
    const footer = (running.length ? running.map(h => [h.name, h.file].filter(Boolean).join(' · ')).join(' · ') : 'No program selected.') + ' Model policy: Free first.';
    const persistLayout = value => {
      setRequest('waiting');
      const result = writeLayout(value);
      if (!result.ok) {
        setFailure(result.error || 'Could not save the layout.');
        setRequest('error');
        retrySave.current = () => persistLayout(value);
        return result;
      }
      setFailure('');
      setRequest(tasks.length ? 'loaded' : 'empty');
      return result;
    };
    const saveSession = patch => {
      if (!task) return Promise.resolve(false);
      setRequest('waiting');
      retrySave.current = () => saveSession(patch);
      return u.act(() => api.setTaskSession(task.id, patch)).then(result => {
        if (result == null || result.ok === false) {
          setFailure(result?.message || result?.error || 'Could not save the task parameters.');
          setRequest('error');
          return result;
        }
        setFailure('');
        setRequest('loaded');
        return result;
      }).catch(error => {
        setFailure(error instanceof Error ? error.message : String(error));
        setRequest('error');
        return {ok: false, error: error instanceof Error ? error.message : String(error)};
      });
    };
    const agentChoices = (s.liveAgents || []).map(agent => ({key: agent.handle || agent.agent, value: agent.agent, name: agent.name && agent.name !== agent.agent ? agent.name : agent.agent})).filter(choice => choice.value);
    const openTask = async t => { u.setTask(t.id); await u.act(() => api.openTaskGraph(t.id)); };
    const send = async () => {
      const body = text.trim();
      if (!body || sending) return;
      const prompt = (!recipient || new RegExp('(^|\\s)@' + recipient + '\\b').test(body) ? '' : '@' + recipient + ' ') + body;
      setText('');
      setSending(true);
      try { await u.act(() => api.apiRouterChat(prompt, 'BABOOM')); await api.listTasks?.(); }
      finally { setSending(false); }
    };
    const TaskRow = ({t}) => <button type="button" className={task?.id === t.id ? 'dx-task on' : 'dx-task'} aria-selected={task?.id === t.id} onClick={() => executeAction('ui.select', () => openTask(t))}>
      <b>{t.title}</b>
      <span>{statusText(t.status)}</span>
      <small>{ownerOf(t)}</small>
    </button>;
    return <div className="dx-home-root" data-screen="home" data-home-page="">
      {request === 'waiting' ? <p role="status">Saving</p> : null}
      {request === 'error' ? <p role="alert">{failure} <button type="button" onClick={() => executeAction('ui.select', () => retrySave.current())}>Retry</button></p> : null}
      {request === 'empty' ? <p>Not yet recorded</p> : null}
      {request === 'loaded' ? <span data-home-ready="" /> : null}
      <Group id="home-layout" className="dx-home" orientation="horizontal" defaultLayout={saved.outer} onLayoutChanged={(layout, meta) => { if (meta?.isUserInteraction) persistLayout({...readLayout(), outer: layout}); }}>
        <Column id="tasks" className="dx-col" defaultSize={256} minSize={200} groupResizeBehavior="preserve-pixel-size">
          <aside className="dx-tasks" data-dx="tasks" aria-label="Tasks">
            <div className="dx-tasks-head">
              <h2>Tasks</h2>
              <button type="button" className="dx-link" onClick={() => executeAction('ui.show', u, 'New task')}>+ New task</button>
            </div>
            <div className="dx-find">
              <input aria-label="Find a task" placeholder="Find a task…" value={query} onChange={e => setQuery(e.target.value)} />
              <label className="dx-status">Status
                <select aria-label="Status" value={status} onChange={e => setStatus(e.target.value)}>
                  <option value="">All</option>
                  {['IN REVIEW', 'WIP', 'PLANNED', 'STOPPED', 'DONE'].map(v => <option key={v} value={v}>{statusText(v)}</option>)}
                </select>
              </label>
            </div>
            <div className="dx-tasks-list">
              <h3>NEEDS REVIEW</h3>
              {needs.map(t => <TaskRow key={t.id} t={t} />)}
              <h3>WORKING</h3>
              {working.map(t => <TaskRow key={t.id} t={t} />)}
              <h3>PLANNED</h3>
              {planned.map(t => <TaskRow key={t.id} t={t} />)}
              {history && done.map(t => <TaskRow key={t.id} t={t} />)}
            </div>
            <footer className="dx-tasks-foot">
              <b>Completed &amp; archived</b>
              <span>All work stays searchable</span>
              <button type="button" className="dx-link" aria-pressed={history} onClick={() => executeAction('ui.select', () => setHistory(!history))}>History →</button>
            </footer>
          </aside>
        </Column>
        <Separator className="pane-splitter" aria-label="Resize the Tasks pane" />
        <Column id="workspace" className="dx-col" minSize={720}>
          <div className="dx-workspace" data-dx="workspace">
            <header className="dx-head" data-dx="head">
              <h1>{task?.title || ''}</h1>
              <div className="dx-actions">
                <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => document.getElementById('dx-outputs')?.focus())}>Review output</button>
                <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => document.getElementById('dx-activity')?.focus())}>Activity &amp; receipts</button>
                <button type="button" className="dx-quiet" disabled={!task} onClick={() => executeAction('ui.select', showCanvas)}>Canvas ↗</button>
                <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => u.act(() => api.newSession()).then(r => r && setFace('canvas')))}>New file</button>
                <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => u.act(() => api.openSession()).then(r => r && !r.cancelled && setFace('canvas')))}>Open file…</button>
                <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', u.pickFlow)}>Import…</button>
                <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => u.go('library'))}>Library</button>
              </div>
            </header>
            {task?.description ? <p className="dx-desc" data-dx="description">{task.description}</p> : null}
            <Group id="home-context" className="dx-split" orientation="horizontal" defaultLayout={saved.inner} onLayoutChanged={(layout, meta) => { if (meta?.isUserInteraction) persistLayout({...readLayout(), inner: layout}); }}>
              <Column id="params" className="dx-col" defaultSize={320} minSize={240} groupResizeBehavior="preserve-pixel-size">
                <section className="dx-params" data-dx="params" aria-label="Task parameters">
                  <div className="dx-params-head"><h2>Task parameters</h2></div>
                  <label className="dx-fact">Scope<input key={(task?.id || '') + ':scope:' + describe(task?.scope)} aria-label="Scope" defaultValue={describe(task?.scope)} placeholder="Not yet recorded" onBlur={e => { if (e.target.value === describe(task?.scope)) return; saveSession({scope: e.target.value}); }} /></label>
                  <ItemList label="Rules" items={rules} onCommit={next => saveSession({rules: next})} />
                  <ItemList label="Assigned agents" items={agents} choices={agentChoices} onCommit={next => saveSession({agents: next})} />
                  <label className="dx-fact">Folders<b>{folders || 'Not yet recorded'}</b></label>
                  <label className="dx-fact">References<b>{references || 'Not yet recorded'}</b></label>
                  <label className="dx-fact">Session<b>{session || (task ? 'Association not verified' : 'Not yet recorded')}</b></label>
                  <label className="dx-fact">Saved workflow<b>{fileName || (task ? 'File association not verified' : 'Not yet recorded')}</b></label>
                  <label className="dx-fact">Checkpoints
                    {(task?.checkpoints || []).length ? <select aria-label="Checkpoints" value={checkpoint} onChange={e => setCheckpoint(e.target.value)}><option value="">No checkpoint selected</option>{task.checkpoints.map(c => <option key={c.id} value={c.id}>{c.title || c.id}</option>)}</select> : <b>No checkpoint selected</b>}
                  </label>
                  <div className="dx-param-actions">
                    <button type="button" className="dx-quiet" disabled={!task} onClick={() => executeAction('ui.select', showCanvas)}>Open in Canvas</button>
                    <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => document.getElementById('dx-activity')?.focus())}>Activity</button>
                    <button type="button" className="dx-quiet" disabled={!task} onClick={() => executeAction('ui.select', () => u.act(() => api.checkpointTask(task.id)))}>Save checkpoint</button>
                    <button type="button" className="dx-quiet" disabled={!task || !checkpoint} onClick={() => executeAction('ui.select', () => u.act(() => api.restoreTaskCheckpoint(task.id, checkpoint)))}>Restore</button>
                  </div>
                </section>
              </Column>
              <Separator className="pane-splitter" aria-label="Resize the task parameters" />
              <Column id="main" className="dx-col" minSize={480}>
                <div className="dx-main" data-dx="main">
                  <div className="dx-toggle" data-dx="views" role="group" aria-label="Task view">
                    <button type="button" aria-pressed={face === 'workshop'} onClick={() => executeAction('ui.select', () => setFace('workshop'))}>Workshop</button>
                    <button type="button" aria-pressed={face === 'canvas'} onClick={() => executeAction('ui.select', showCanvas)}>Canvas</button>
                    <span>{task ? statusText(task.status) : ''}</span>
                  </div>
                  <div className="dx-mid">
                    <section className="dx-panel" data-dx="workflow" data-home-face={face} aria-label={face === 'canvas' ? 'Canvas · same task' : 'Workflow'}>
                      <h2>{face === 'canvas' ? 'Canvas · same task' : 'Workflow'}</h2>
                      {face === 'canvas' ? <p className="dx-logic-label">Workflow · logic</p> : null}
                      {nodes.length ? <div className={face === 'canvas' ? 'dx-logic' : 'dx-nodes'}>{nodes.map((n, index) => <React.Fragment key={n.id}>{face === 'canvas' && index > 0 && <span className="dx-arrow" aria-hidden="true">→</span>}<NodeFace n={n} owner={ownerOf(task)} /></React.Fragment>)}</div> : <p className="dx-empty">No nodes in this workflow yet.</p>}
                    </section>
                    <section className="dx-panel" data-dx="plan" aria-label="Plan and progress">
                      <h2>Plan and progress</h2>
                      {plan.length ? plan.map((step, index) => <p key={index}><b>{describe(step)}</b><span>{ownerOf(task)}</span></p>) : <p>Not yet recorded</p>}
                    </section>
                  </div>
                  <div className="dx-low">
                    <section className="dx-panel dx-slim" id="dx-activity" tabIndex={-1} data-dx="activity" aria-label="Activity">
                      <h2>Activity</h2>
                      {activity.length ? activity.map(row => <p key={row.id}>{[row.status, describe(row.output)].filter(Boolean).join(' · ')}</p>) : <p>Not yet recorded</p>}
                    </section>
                    <section className="dx-panel dx-slim" id="dx-outputs" tabIndex={-1} data-dx="outputs" aria-label="Outputs">
                      <h2>Outputs</h2>
                      {outputs.length ? outputs.map((row, index) => <p key={index}>{describe(row)}</p>) : <p>Not yet recorded</p>}
                    </section>
                  </div>
                  <section className="dx-talk" data-dx="conversation" aria-label="Conversation">
                    <h2>Conversation</h2>
                    {task?.description ? <article className="dx-msg"><b>Your request</b><p>{task.description}</p></article> : null}
                    {messages.map(m => {
                      const own = Boolean(m.sender_key) && m.sender_key === m.viewer_key;
                      const sender = own ? 'You' : (people.whoIs ? people.whoIs(m.who, m.sender_key).name : m.who);
                      const delivery = (m.live || []).map(d => d.state || d.reason).filter(Boolean).join(' · ');
                      return <article key={m.id} className="dx-msg"><span aria-hidden="true">{String(sender || '?').slice(0, 2).toUpperCase()}</span><div><b>{sender}</b><p>{m.text}</p>{own && !delivery ? <small>Delivery unverified</small> : delivery ? <small>{delivery}</small> : null}</div></article>;
                    })}
                  </section>
                  <form className="dx-composer" data-dx="composer" onSubmit={e => { e.preventDefault(); executeAction('ui.select', send); }}>
                    <label className="dx-to">To
                      <select aria-label="Recipient" value={recipient} onChange={e => setTo(e.target.value)}>
                        {choices.map(c => <option key={c.key} value={c.handle || ''}>{c.name}</option>)}
                      </select>
                    </label>
                    <textarea aria-label="Message" placeholder="Message this task…" rows={2} value={text} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} />
                    <div className="dx-tools">
                      {u.pickFile && <button type="button" className="dx-link" onClick={() => executeAction('ui.select', u.pickFile)}>Attach</button>}
                      {u.voice && <button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => u.voice(setText))}>Voice</button>}
                      <span className="dx-model"><b>{model ? 'Model · ' + model : 'Model'}</b><small>Free models first</small></span>
                      <Btn p type="submit" aria-busy={sending} disabled={!text.trim()}>Send</Btn>
                    </div>
                  </form>
                  <p className="dx-foot" data-dx="footer">{footer}</p>
                </div>
              </Column>
            </Group>
          </div>
        </Column>
      </Group>
    </div>;
  }
  window.UI.Home = Home;
  window.UI.Sheet = Sheet;
  window.UI.homeListSame = sameList;
  window.UI.homeCommitList = commitList;
  window.UI.homeDescribe = describe;
})();
