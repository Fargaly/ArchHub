// Home plate: archhub-current-home.svg (Penpot rev 1444). Live task data fills the plate's slots.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const api = window.ArchHubAPI;
  const {useData, useApp, Btn} = window.UI;
  const Icon = window.AHIcon;
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
      if (event.detail === 'canvas' || event.detail === 'workshop') {
        window.ArchHubHomeFace = event.detail;
        homeSetFace(event.detail);
      }
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
  const factText = value => describe(value) || 'Not yet recorded';
  const outputRecord = value => {
    if (value == null || value === '') return null;
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return {name: '', excerpt: String(value), thumb: ''};
    if (Array.isArray(value)) return outputRecord(value.find(item => item != null && item !== ''));
    const name = ['name', 'title', 'file', 'path'].map(key => value[key]).find(item => typeof item === 'string' && item) || '';
    const excerpt = ['excerpt', 'text', 'summary', 'preview'].map(key => value[key]).find(item => typeof item === 'string' && item) || describe(value);
    const thumb = ['thumbnail', 'thumb', 'image'].map(key => value[key]).find(item => typeof item === 'string' && /^https?:|^data:image\//.test(item)) || '';
    return excerpt || name || thumb ? {name, excerpt, thumb} : null;
  };
  const stepKeys = step => {
    if (step == null) return [];
    if (typeof step !== 'object') return [String(step)];
    return [step.id, step.key, step.title, step.name, step.what, step.text].filter(item => typeof item === 'string' && item);
  };
  const progressBag = progress => {
    if (!progress || typeof progress !== 'object' || Array.isArray(progress)) return null;
    const nested = progress.steps;
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) return nested;
    return progress;
  };
  const recordedStep = (step, progress) => {
    const bag = progressBag(progress);
    if (!bag) return null;
    for (const key of stepKeys(step)) {
      if (Object.hasOwn(bag, key)) return bag[key];
    }
    return null;
  };
  const taskNotes = rows => (Array.isArray(rows) ? rows : []).filter(item => item && typeof item === 'object' && (!item.role || item.role === 'task'));
  const taskMessages = task => [...new Map([...taskNotes(task && task.fileMessages), ...taskNotes(task && task.messages)].map((item, index) => [item.id || 'file-' + index, item])).values()];
  const homeDestination = route => {
    if (route === 'workshop' || route === 'canvas') return {route: 'home', face: route, library: false};
    if (route === 'library' || route === 'skills') return {route: 'home', face: 'canvas', library: true};
    return null;
  };
  const stepOf = (step, progress) => {
    const recorded = recordedStep(step, progress);
    const raw = recorded == null || recorded === '' ? '' : (typeof recorded === 'object' ? String(recorded.status || recorded.state || '') : String(recorded));
    const named = source => source && typeof source === 'object' ? String(source.ownerName || source.owner || source.agent || source.who || '').trim() : '';
    const owner = (recorded && typeof recorded === 'object' && named(recorded)) || named(step) || 'not reported';
    const text = raw.trim();
    if (!text) return {kind: 'unreported', label: 'not reported', owner};
    if (/error|fail/i.test(text)) return {kind: 'error', label: 'error', owner};
    if (/block/i.test(text)) return {kind: 'blocked', label: 'blocked', owner};
    if (/done|complete|saved/i.test(text)) return {kind: 'done', label: 'done', owner};
    if (/await/i.test(text)) return {kind: 'awaiting', label: 'awaiting', owner};
    if (/work|current|wip/i.test(text)) return {kind: 'working', label: 'working', owner};
    if (/next|planned/i.test(text)) return {kind: 'next', label: text, owner};
    return {kind: 'recorded', label: text, owner};
  };
  const markColor = key => {
    let hash = 0;
    const text = String(key || 'person');
    for (let i = 0; i < text.length; i++) hash = (hash * 33 + text.charCodeAt(i)) >>> 0;
    return 'hsl(' + (hash % 360) + ' 42% 38%)';
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
  function ItemList({label, icon, items, choices, onCommit}) {
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
      <span>{icon ? <Icon name={icon} size={14} /> : null}{label}</span>
      {rows.length === 0 ? <b>Not yet recorded</b> : null}
      {rows.map((row, index) => choices ? <select key={stamp + ':' + index} aria-label={label + ' ' + (index + 1)} value={row} onChange={event => { if (event.target.value === row) return; const next = rows.slice(); next[index] = event.target.value; commit(next); }}>
        <option value="">Choose</option>
        {row && !choices.some(choice => choice.value === row) && <option value={row}>{row}</option>}
        {choices.map(choice => <option key={choice.key} value={choice.value}>{choice.name}</option>)}
      </select> : <input key={stamp + ':' + index} aria-label={label + ' ' + (index + 1)} defaultValue={row} onBlur={event => { if (event.target.value === row) return; const next = rows.slice(); next[index] = event.target.value; commit(next); }} />)}
      <button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => setRows(current => [...current, '']))}>{choices ? '+ Add agent' : '+ Add'}</button>
    </div>;
  }
  function Home() {
    const s = useData(), u = useApp();
    const [query, setQuery] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [history, setHistory] = React.useState(false);
    const [drafts, setDrafts] = React.useState({});
    const [sending, setSending] = React.useState(false);
    const [to, setTo] = React.useState('');
    const [checkpoint, setCheckpoint] = React.useState('');
    const [face, setFace] = React.useState(() => window.ArchHubHomeFace === 'canvas' ? 'canvas' : 'workshop');
    const [fileOpen, setFileOpen] = React.useState(false);
    const [detailId, setDetailId] = React.useState('');
    const [runMode, setRunMode] = React.useState({status: 'waiting', value: '', message: ''});
    const [request, setRequest] = React.useState('loaded');
    const [failure, setFailure] = React.useState('');
    const retrySave = React.useRef(() => {});
    React.useEffect(() => {
      let live = true;
      if (typeof api.readPermissions !== 'function') {
        setRunMode({status: 'empty', value: '', message: ''});
        return undefined;
      }
      api.readPermissions().then(result => {
        if (!live) return;
        const mode = result && typeof result.runMode === 'string' ? result.runMode : '';
        setRunMode({status: mode ? 'loaded' : 'empty', value: mode, message: ''});
      }).catch(error => {
        if (!live) return;
        setRunMode({status: 'error', value: '', message: error instanceof Error ? error.message : String(error)});
      });
      return () => { live = false; };
    }, []);
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
    const declared = (Array.isArray(task?.declarations) ? task.declarations : []).find(item => item && typeof item === 'object') || null;
    const declaredPaths = Array.isArray(declared?.paths) ? declared.paths.filter(item => typeof item === 'string' && item) : [];
    const rules = Array.isArray(task?.rules) ? task.rules.map(item => typeof item === 'string' ? item : describe(item)) : [];
    const recordedAgents = Array.isArray(task?.agents) ? task.agents.map(item => typeof item === 'string' ? item : describe(item)).filter(Boolean) : [];
    const agents = recordedAgents.length ? recordedAgents : [ownerOf(task) || declared?.agent].filter(item => typeof item === 'string' && item);
    const folders = describe(task?.folders) || declaredPaths.join(' · ');
    const references = describe(task?.references);
    const scopeValue = describe(task?.scope) || declaredPaths.join(' · ');
    const session = task?.sessionPath || (typeof task?.session === 'string' ? task.session : '') || (typeof declared?.session === 'string' ? declared.session : '');
    const fileName = task?.sessionPath ? task.sessionPath.split(/[/\\]/).pop() : '';
    const plan = Array.isArray(task?.plan) ? task.plan : [];
    const recordedActivity = Array.isArray(task?.activity) ? task.activity : [];
    const activity = recordedActivity.length ? recordedActivity : (task && (task.result || ownerOf(task) || declared) ? [{id: task.id, status: statusText(task.status), output: task.result || ''}] : []);
    const outputs = (Array.isArray(task?.outputs) && task.outputs.length ? task.outputs : [task?.result, ...activity.map(row => row.output)]).map(outputRecord).filter(Boolean);
    const source = String(task?.description || '').trim();
    const sourceSentence = source && source !== task?.title ? source.split(/(?<=[.!?])\s/)[0] : '';
    const shortSource = sourceSentence.length > 140 ? sourceSentence.slice(0, 139).replace(/\s+\S*$/, '').replace(/[,\s;:]+$/, '') + '…' : sourceSentence;
    const draftKey = task?.id || '';
    const text = drafts[draftKey] || '';
    const setText = value => setDrafts(current => ({...current, [draftKey]: typeof value === 'function' ? value(current[draftKey] || '') : value}));
    const messages = taskMessages(task);
    const seenTask = React.useRef('');
    React.useEffect(() => {
      let live = true;
      if (task?.id && typeof api.openTaskGraph === 'function' && seenTask.current && seenTask.current !== task.id) {
        const id = task.id;
        u.act(() => api.openTaskGraph(id)).catch(error => {
          if (!live) return;
          setFailure(error instanceof Error ? error.message : String(error));
          setRequest('error');
        });
      }
      if (task?.id) seenTask.current = task.id;
      return () => { live = false; };
    }, [task?.id]);
    const showCanvas = async () => { u.go('canvas'); if (task) await u.act(() => api.openTaskGraph(task.id)); };
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
    const recentFiles = (Array.isArray(s.graphs) ? s.graphs : []).filter(row => row && (row.path || row.id));
    const closeFile = () => setFileOpen(false);
    const makeFile = () => { closeFile(); return u.act(() => api.newSession()).then(result => { if (result && !result.cancelled) setFace('canvas'); return result; }); };
    const openFile = () => { closeFile(); return u.act(() => api.openSession()).then(result => { if (result && !result.cancelled) setFace('canvas'); return result; }); };
    const saveFile = asCopy => { closeFile(); return u.act(() => asCopy ? api.saveSessionAs() : api.saveSession()); };
    const importFile = () => { closeFile(); return u.pickFlow?.(); };
    const openRecent = row => { closeFile(); return u.act(() => api.openSession(row.path || row.id)).then(result => { if (result && !result.cancelled) setFace('canvas'); return result; }); };
    const fileKeys = event => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const tag = event.target && event.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (event.target && event.target.isContentEditable)) return;
      const key = String(event.key || '').toLowerCase();
      if (key === 'n') { event.preventDefault(); makeFile(); }
      else if (key === 'o') { event.preventDefault(); openFile(); }
      else if (key === 's') { event.preventDefault(); saveFile(event.shiftKey); }
    };
    const runLabel = runMode.status === 'loaded' ? 'Run mode: ' + runMode.value : runMode.status === 'error' ? runMode.message : runMode.status === 'waiting' ? 'Reading run mode' : 'Run mode: not reported';
    const replyToMessage = message => {
      const sender = message.sender_key || message.who || '';
      const choice = choices.find(item => item.handle === sender || item.name === sender || item.key === sender);
      if (choice && choice.handle) setTo(choice.handle);
      const field = document.querySelector('.dx-composer textarea');
      if (field) field.focus();
    };
    return <div className="dx-home-root" data-screen="home" data-home-page="" data-start={document.documentElement.dataset.start || 'cold'} onKeyDown={fileKeys}>
      {s.liveAgents === undefined ? <p role="status" data-home-loading="">Opening your tasks…</p> : null}
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
            <div className="dx-tasks-foot">
              <b>Completed &amp; archived</b>
              <span>All work stays searchable</span>
              <button type="button" className="dx-link" aria-pressed={history} onClick={() => executeAction('ui.select', () => setHistory(!history))}>History →</button>
            </div>
          </aside>
        </Column>
        <Separator className="pane-splitter" aria-label="Resize the Tasks pane" />
        <Column id="workspace" className="dx-col" minSize={720}>
          <div className="dx-workspace" data-dx="workspace">
            <header className="dx-head" data-dx="head" onContextMenu={event => { event.preventDefault(); setFileOpen(true); }}>
              <h1>{task?.title || ''}</h1>
              <div className="dx-actions">
                <button type="button" className="dx-quiet" aria-label="File" aria-expanded={fileOpen} title="File" onClick={() => executeAction('ui.select', () => setFileOpen(!fileOpen))}><span>File</span></button>
                <div className="dx-runmode" data-run-mode={runMode.status === 'loaded' ? runMode.value : 'unreported'} role={runMode.status === 'error' ? 'alert' : 'status'}>{runLabel}{runMode.status === 'error' ? <button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => { setRunMode({status: 'waiting', value: '', message: ''}); api.readPermissions().then(result => { const mode = result && typeof result.runMode === 'string' ? result.runMode : ''; setRunMode({status: mode ? 'loaded' : 'empty', value: mode, message: ''}); }).catch(error => setRunMode({status: 'error', value: '', message: error instanceof Error ? error.message : String(error)})); })}>Retry</button> : null}</div>
                {fileOpen ? <div role="menu" aria-label="File" className="dx-file-menu" data-dx="file-menu" onKeyDown={event => { if (event.key === 'Escape') setFileOpen(false); }}>
                  <p className="dx-file-kicker">File</p>
                  <button type="button" role="menuitem" className="dx-file-item" onClick={() => executeAction('ui.select', makeFile)}><span>New</span><kbd>Ctrl N</kbd></button>
                  <button type="button" role="menuitem" className="dx-file-item" onClick={() => executeAction('ui.select', openFile)}><span>Open…</span><kbd>Ctrl O</kbd></button>
                  <button type="button" role="menuitem" className="dx-file-item" onClick={() => executeAction('ui.select', importFile)}><span>Import…</span></button>
                  <button type="button" role="menuitem" className="dx-file-item" onClick={() => executeAction('ui.select', () => saveFile(false))}><span>Save</span><kbd>Ctrl S</kbd></button>
                  <button type="button" role="menuitem" className="dx-file-item" onClick={() => executeAction('ui.select', () => saveFile(true))}><span>Save as…</span><kbd>Ctrl Shift S</kbd></button>
                  <hr className="dx-file-rule" />
                  <div className="dx-file-recent" role="group" aria-label="Recent files">
                    <p>Recent files</p>
                    {recentFiles.length ? recentFiles.map(row => <button key={row.path || row.id} type="button" role="menuitem" className="dx-file-item" onClick={() => executeAction('ui.select', () => openRecent(row))}><span>{row.title || row.name || row.path}</span></button>) : <p>No recent files reported</p>}
                  </div>
                </div> : null}
              </div>
            </header>
            {shortSource ? <p className="dx-desc" data-dx="description">{shortSource}</p> : null}
            <Group id="home-context" className="dx-split" orientation="horizontal" defaultLayout={saved.inner} onLayoutChanged={(layout, meta) => { if (meta?.isUserInteraction) persistLayout({...readLayout(), inner: layout}); }}>
              <Column id="params" className="dx-col" defaultSize={320} minSize={240} groupResizeBehavior="preserve-pixel-size">
                <section className="dx-params" data-dx="params" aria-label="Task parameters">
                  <div className="dx-params-head"><h2>Task parameters</h2></div>
                  <label className="dx-fact"><span><Icon name="fit" size={14} />Scope</span><input key={(task?.id || '') + ':scope:' + scopeValue} aria-label="Scope" defaultValue={scopeValue} placeholder="Not yet recorded" onBlur={e => { if (e.target.value === scopeValue) return; saveSession({scope: e.target.value}); }} /></label>
                  <ItemList label="Rules" icon="shield" items={rules} onCommit={next => saveSession({rules: next})} />
                  <ItemList label="Assigned agents" icon="users" items={agents} choices={agentChoices} onCommit={next => saveSession({agents: next})} />
                  <label className="dx-fact"><span><Icon name="folder" size={14} />Folders</span><b>{factText(folders)}</b></label>
                  <label className="dx-fact"><span><Icon name="link" size={14} />References</span><b>{factText(references)}</b></label>
                  <label className="dx-fact"><span><Icon name="clock" size={14} />Session</span><b>{factText(session)}</b></label>
                  <label className="dx-fact"><span><Icon name="canvas" size={14} />Saved workflow</span><b>{factText(fileName)}</b></label>
                  <label className="dx-fact"><span><Icon name="pin" size={14} />Checkpoints</span>
                    <span className="dx-checkpoint-row">
                      {(task?.checkpoints || []).length ? <select aria-label="Checkpoints" value={checkpoint} onChange={e => setCheckpoint(e.target.value)}><option value="">No checkpoint selected</option>{task.checkpoints.map(c => <option key={c.id} value={c.id}>{c.title || c.id}</option>)}</select> : <b>No checkpoint selected</b>}
                      <button type="button" className="dx-quiet" disabled={!task} onClick={() => executeAction('ui.select', () => u.act(() => api.checkpointTask(task.id)))}>Save checkpoint</button>
                      <button type="button" className="dx-quiet" disabled={!task || !checkpoint} onClick={() => executeAction('ui.select', () => u.act(() => api.restoreTaskCheckpoint(task.id, checkpoint)))}>Restore</button>
                    </span>
                  </label>
                </section>
              </Column>
              <Separator className="pane-splitter" aria-label="Resize the task parameters" />
              <Column id="main" className="dx-col" minSize={480}>
                <div className="dx-main" data-dx="main" data-home-face={face}>
                  <div className="dx-toggle" data-dx="views" role="group" aria-label="Task view">
                    <button type="button" aria-label="Workshop view" aria-pressed={face === 'workshop'} onClick={() => executeAction('ui.select', () => setFace('workshop'))}>Workshop</button>
                    <button type="button" aria-label="Canvas view" aria-pressed={face === 'canvas'} onClick={() => executeAction('ui.select', showCanvas)}>Canvas</button>
                  </div>
                  {face === 'canvas' ? <div className="dx-board" data-dx="canvas-commands" role="toolbar" aria-label="Canvas commands">
                    <button type="button" onClick={() => executeAction('ui.select', () => u.show('Search'))}>+ Add node</button>
                    <button type="button" aria-pressed={!!u.libraryOpen} onClick={() => executeAction('ui.select', () => u.setLibraryOpen(value => !value))}>Library</button>
                    <button type="button" onClick={() => executeAction('ui.select', () => u.go('watcher'))}>Program view</button>
                    <button type="button" onClick={() => executeAction('ui.select', () => u.go('present'))}>Present</button>
                    <button type="button" onClick={() => executeAction('ui.select', () => u.go('model-review'))}>Model review</button>
                    <button type="button" onClick={() => executeAction('ui.select', () => { const fit = window.UI.requestCanvasFit; return typeof fit === 'function' ? fit() : false; })}>Overview</button>
                  </div> : null}
                  <div className="dx-mid">
                    {face === 'workshop' ? <section className="dx-talk dx-thread" data-dx="conversation" aria-label="Conversation">
                      <h2>Conversation</h2>
                      {messages.map(m => {
                        const own = Boolean(m.sender_key) && m.sender_key === m.viewer_key;
                        const sender = own ? 'You' : (people.whoIs ? people.whoIs(m.who, m.sender_key).name : m.who);
                        const delivery = (m.live || []).map(d => d.state || d.reason).filter(Boolean).join(' · ');
                        const who = m.sender_key || m.who || sender;
                        const open = detailId === (m.id || who);
                        return <article key={m.id} className="dx-msg"><span className="dx-avatar" style={{background: markColor(who)}} aria-hidden="true" title={sender}>{String(sender || '?').slice(0, 2).toUpperCase()}</span><div className="dx-msg-line"><div><b>{sender}</b><p>{typeof m.text === 'object' ? describe(m.text) : m.text}</p><p className="dx-delivery">{delivery || 'Delivery unverified'}</p>{open ? <p className="dx-delivery">{[m.id, m.created_at, delivery].filter(Boolean).join(' · ') || 'No delivery record'}</p> : null}</div><span className="dx-msg-actions"><button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => replyToMessage(m))}>Reply</button><button type="button" className="dx-quiet" aria-expanded={open} onClick={() => executeAction('ui.select', () => setDetailId(open ? '' : (m.id || who)))}>Details</button></span></div></article>;
                      })}
                    </section> : <section className="dx-panel" data-dx="workflow" data-home-face={face} aria-label="Workflow">
                      <h2>Workflow · logic</h2>
                      <div className="dx-canvas-mount" data-dx="graph">{window.UI.Canvas ? <window.UI.Canvas active embedded /> : <p className="dx-empty">No nodes in this workflow yet.</p>}</div>
                    </section>}
                    <section className="dx-panel" data-dx="plan" aria-label="Plan and progress">
                      <h2>Plan and progress</h2>
                      {plan.length ? <ol className="dx-stepper">{plan.map((step, index) => {
                        const recorded = stepOf(step, task?.progress);
                        const label = typeof step === 'object' ? (step.title || step.text || step.name || step.what || describe(step)) : String(step);
                        return <li key={index} data-step={recorded.kind}><Icon name={recorded.kind === 'done' ? 'check' : recorded.kind === 'working' ? 'clock' : 'arrow'} size={14} /><b>{label}</b><span>{recorded.label}</span><small>{recorded.owner}</small></li>;
                      })}</ol> : <p>Not yet recorded</p>}
                    </section>
                  </div>
                  <div className="dx-low">
                    <section className="dx-panel dx-slim" id="dx-activity" tabIndex={-1} data-dx="activity" aria-label="Activity">
                      <h2>Activity</h2>
                      {activity.length ? activity.map(row => <p key={row.id}>{[row.status, describe(row.output)].filter(Boolean).join(' · ')}</p>) : <p>Not yet recorded</p>}
                    </section>
                    <section className="dx-panel dx-slim" id="dx-outputs" tabIndex={-1} data-dx="outputs" aria-label="Outputs">
                      <h2>Outputs</h2>
                      {outputs.length ? outputs.map((row, index) => <article key={index} className="dx-output" data-output=""><span className="dx-output-preview">{row.thumb ? <img alt="" src={row.thumb} /> : <Icon name="docs" size={18} />}</span><div><b>{row.name || 'Output'}</b>{row.excerpt ? <p>{row.excerpt}</p> : null}</div></article>) : <p>Not yet recorded</p>}
                    </section>
                  </div>
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
  window.UI.homeStepOf = stepOf;
  window.UI.homeDestination = homeDestination;
  window.UI.homeTaskMessages = taskMessages;
})();
