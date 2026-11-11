// Home: Penpot ef7b4b6f; task files and Workshop owners fill the saved design's slots.
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
  const statusText = st => ({'IN REVIEW': 'Needs you', WIP: 'Working', PLANNED: 'Planned', DONE: 'Done', ARCHIVED: 'Archived', STOPPED: 'Blocked'})[st] || st || '';
  const KEY = 'archhub.home.layout.v1';
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
  const writeInspectorWidth = value => api.setInspectorWidth(value);
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
  const factText = value => describe(value);
  const useLabel = value => String(value || '').replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\n·]+/g, path => path.trim().split(/[\\/]/).filter(Boolean).pop() || path);
  const middle = value => {
    const text = String(value || '');
    if (text.length <= 42) return text;
    return text.slice(0, 18) + '\u2026' + text.slice(-18);
  };
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
  const taskMessages = task => [...new Map([...taskNotes(task && task.fileMessages), ...taskNotes(task && task.agentLog), ...taskNotes(task && task.messages)].map((item, index) => [item.id || 'file-' + index, item])).values()];
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
  const sameList = (before, after) => {
    const left = Array.isArray(before) ? before.map(item => JSON.stringify(item)) : [];
    const right = Array.isArray(after) ? after.map(item => JSON.stringify(item)) : [];
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
  function ItemList({label, icon, items, choices, onCommit, action = 'Edit'}) {
    const source = Array.isArray(items) ? items : [];
    const stamp = JSON.stringify(source);
    const [hold, setHold] = React.useState({stamp, rows: source});
    const rows = hold.stamp === stamp ? hold.rows : source;
    const setRows = next => setHold({stamp, rows: typeof next === 'function' ? next(rows) : next});
    const commit = next => {
      const cleaned = (Array.isArray(next) ? next : []).filter(item => item !== '');
      if (!commitList(source, cleaned, onCommit)) return false;
      setRows(cleaned);
      return true;
    };
    return <details className="dx-fact dx-edit-field" data-dx-list={label}>
      <summary aria-label={action.startsWith('Edit ') ? action : undefined}><span>{label}</span><span className="dx-edit-label">{action.startsWith('Edit ') ? 'Edit' : action}</span><b>{source.map(describe).join(' · ') || ''}</b></summary>
      {rows.map((row, index) => choices ? <window.UI.AgentPicker key={stamp + ':' + index} label={label + ' ' + (index + 1)} choices={choices} to={row} setTo={value => { if (value === row) return; const next = rows.slice(); next[index] = value; commit(next); }} /> : <input key={stamp + ':' + index} aria-label={label + ' ' + (index + 1)} defaultValue={describe(row)} onBlur={event => { if (event.target.value === describe(row)) return; const next = rows.slice(); next[index] = event.target.value; commit(next); }} />)}
      <button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => setRows(current => [...current, '']))}>{choices ? '+ Add agent' : '+ Add'}</button>
    </details>;
  }
  function Home({fileWorkspace = false, initialFace = fileWorkspace ? 'canvas' : 'workshop'} = {}) {
    const s = useData(), u = useApp();
    const [preview, setPreview] = React.useState(null), [previewError, setPreviewError] = React.useState('');
    const beside = fileWorkspace ? u.canvasTabs?.split : '';
    React.useEffect(()=>{setPreview(null);setPreviewError('');},[beside]);
    React.useEffect(()=>{
      let live=true;
      if(!beside)return;
      const read=()=>api.readTaskPreview(beside).then(value=>{if(live){setPreview(value);setPreviewError('');}}).catch(error=>{if(live)setPreviewError(error.message);});
      read();
      return()=>{live=false;};
    },[beside,s.tasks]);
    const [query, setQuery] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [history, setHistory] = React.useState(false);
    const [sending, setSending] = React.useState(false);
    const sendingRef = React.useRef(false);
    const [to, setTo] = React.useState(null);
    const [checkpoint, setCheckpoint] = React.useState('');
    const [localFace, setLocalFace] = React.useState(initialFace);
    const face = fileWorkspace ? u.taskFace : localFace;
    const setFace = fileWorkspace ? u.setTaskFace : setLocalFace;
    const [detailId, setDetailId] = React.useState('');
    const [request, setRequest] = React.useState('loaded');
    const [failure, setFailure] = React.useState('');
    const [layoutReady, setLayoutReady] = React.useState(false);
    const retrySave = React.useRef(() => {});
    const inspectorRef = React.useRef(null), canvasRef = React.useRef(null);
    const shellRef = React.useRef(null), tabsRef = React.useRef(null);
    const [shellWidth, setShellWidth] = React.useState(window.innerWidth - 64), [tabsWidth, setTabsWidth] = React.useState(600);
    const [inspectorRail, setInspectorRail] = React.useState(false);
    const threadRef = React.useRef(null), [threadRail, setThreadRail] = React.useState(false), [threadPeek, setThreadPeek] = React.useState(false);
    React.useLayoutEffect(() => {
      const frame = window.requestAnimationFrame(() => {
        if (shellWidth < 1180) threadRef.current?.collapse();
        else threadRef.current?.expand();
      });
      setThreadPeek(false);
      return () => window.cancelAnimationFrame(frame);
    }, [shellWidth < 1180, face]);
    React.useLayoutEffect(() => {
      const observer = new window.ResizeObserver(entries => {
        for (const entry of entries) {
          if (entry.target === shellRef.current) setShellWidth(entry.contentRect.width);
          if (entry.target === tabsRef.current) setTabsWidth(entry.contentRect.width);
        }
      });
      if (shellRef.current) observer.observe(shellRef.current);
      if (tabsRef.current) observer.observe(tabsRef.current);
      return () => observer.disconnect();
    }, [fileWorkspace]);
    const inspectorSetting = s.settings.find(row => row.id === 'Appearance.Inspector width');
    const inspectorWidth = inspectorSetting?.value ?? 320;
    // Changing defaultSize re-registers the panel; owner updates use resize().
    const initialInspectorWidth = React.useRef(inspectorWidth);
    const [inspection, setInspection] = React.useState({nodeId: null, wireId: null});
    const [propertyTab, setPropertyTab] = React.useState('Task');
    const [splitInspector, setSplitInspector] = React.useState(false);
    const inspectedNode = s.graph.nodes.find(node => node.id === inspection.nodeId);
    const inspectedWire = s.graph.wires.find(wire => wire.id === inspection.wireId);
    const inspect = value => {
      setInspection(value);
      if(value.nodeId || value.wireId)setSplitInspector(true);
      setPropertyTab(value.nodeId || value.wireId ? 'Selection' : 'Task');
    };
    React.useEffect(() => {setPropertyTab('Task');}, [fileWorkspace]);
    const clearInspection = () => { canvasRef.current?.clearSelection(); inspect({nodeId:null,wireId:null}); };
    React.useEffect(() => {
      if (!inspectorSetting || layoutReady) return;
      const migrate = async () => {
        try {
          const legacy = s.homeLayout?.inner || JSON.parse(window.localStorage.getItem(KEY) || 'null')?.inner;
          if (legacy) {
            const width = inspectorSetting.overridden ? inspectorWidth : Math.max(280, Math.min(480, Math.round((window.innerWidth - 64) * legacy.params / 100)));
            const result = await writeInspectorWidth(width);
            if (result?.ok === false) throw Error(result.error || 'Could not migrate the Properties width.');
          }
          window.localStorage.removeItem(KEY);
          setLayoutReady(true);
        } catch (error) {
          setFailure(error instanceof Error ? error.message : String(error));
          setRequest('error'); retrySave.current = migrate;
        }
      };
      migrate();
    }, [inspectorSetting, s.homeLayout, layoutReady]);
    React.useLayoutEffect(() => {
      if (layoutReady) {
        const frame = window.requestAnimationFrame(() => {
          if(fileWorkspace && (shellWidth < 1436 || face==='split' && !splitInspector))inspectorRef.current?.collapse();
          else inspectorRef.current?.resize(inspectorWidth);
        });
        return () => window.cancelAnimationFrame(frame);
      }
      return undefined;
    }, [inspectorWidth, layoutReady, fileWorkspace, face, splitInspector, shellWidth]);
    React.useEffect(()=>{setSplitInspector(false);},[face]);
    React.useEffect(() => {
      if (!fileWorkspace && face !== 'canvas') {u.setSelectedNodeId(null);inspect({nodeId:null,wireId:null});}
    }, [face]);
    homeSetFace = setFace;
    ensureHomeView();
    const tasks = (s.tasks || []).filter(t => history || t.status !== 'ARCHIVED').sort((a,b)=>Number(!!b.homePinned)-Number(!!a.homePinned));
    const waiting = new Set((s.approvals || []).filter(c => c.status === 'pending').map(c => c.taskId));
    const list = tasks.filter(t => (!status || t.status === status) && (!query || `${t.title} ${t.status}`.toLowerCase().includes(query.toLowerCase())));
    const focus = u.task || s.focusedTask;
    const task = fileWorkspace ? tasks.find(t => t.id === u.task) : tasks.find(t => t.id === focus);
    const people = window.UI.workshopPeople ? window.UI.workshopPeople(s) : {people: [], choices: [], whoIs: label => ({name: label || 'Agent'})};
    const ownerOf = t => {
      if (!t) return '';
      const live = (s.liveAgents || []).find(a => a.agent === t.owner || (t.declarations || []).some(d => d.agent === a.agent));
      if (live) return live.name && live.name !== live.agent ? live.name : (live.name || '');
      return (s.providers || []).find(p => p.id === t.owner)?.name || t.owner || (t.agents || []).map(describe).filter(Boolean).join(' · ');
    };
    const declared = (Array.isArray(task?.declarations) ? task.declarations : []).find(item => item && typeof item === 'object') || null;
    const declaredPaths = Array.isArray(declared?.paths) ? declared.paths.filter(item => typeof item === 'string' && item) : [];
    const rules = Array.isArray(task?.rules) ? task.rules.map(item => typeof item === 'string' ? item : describe(item)) : [];
    const recordedAgents = Array.isArray(task?.agents) ? task.agents.map(item => typeof item === 'string' ? item : describe(item)).filter(Boolean) : [];
    const agents = recordedAgents.length ? recordedAgents : [ownerOf(task) || declared?.agent].filter(item => typeof item === 'string' && item);
    const folders = Array.isArray(task?.folders) ? task.folders : (task?.folders ? [task.folders] : declaredPaths);
    const references = Array.isArray(task?.references) ? task.references : (task?.references ? [task.references] : []);
    const scopeValue = describe(task?.scope) || declaredPaths.join(' · ');
    const session = task?.sessionPath || (typeof task?.session === 'string' ? task.session : '') || (typeof declared?.session === 'string' ? declared.session : '');
    const fileName = task?.sessionPath ? task.sessionPath.split(/[/\\]/).pop() : '';
    const plan = Array.isArray(task?.plan) ? task.plan : [];
    const activity = Array.isArray(task?.activity) ? task.activity : [];
    const outputs = (Array.isArray(task?.outputs) && task.outputs.length ? task.outputs : [task?.result, ...activity.map(row => row.output)]).map(outputRecord).filter(Boolean);
    const draftKey = JSON.stringify(['task-file', task?.id || '']);
    const text = u.composerDraft[draftKey]?.text || '';
    const setText = value => u.setComposerDraft(current => {
      const draft = current[draftKey] || {text: '', revision: 0};
      return {...current, [draftKey]: {text: typeof value === 'function' ? value(draft.text) : value, revision: draft.revision + 1}};
    });
    const messages = taskMessages(task);
    const showCanvas = () => setFace('canvas');
    const choices = [...(people.choices || [])];
    for (const name of agents) if (!choices.some(choice => [choice.name,choice.handle,choice.key].includes(name))) choices.push({key:name,handle:name,name});
    if (!choices.length) choices.push({key:'baboom',handle:'',name:'BABOOM'});
    const assigned = choices.find(choice => agents.some(name => [choice.name,choice.handle,choice.key].includes(name)));
    const recipient = to ?? assigned?.handle ?? (task && (s.liveAgents || []).find(a => a.agent === task.owner)?.handle) ?? choices[0]?.handle ?? '';
    const running = (s.hosts || []).filter(h => ['connected', 'listening', 'running'].includes(h.state));
    const footer = (running.length ? running.map(h => [h.name, h.file].filter(Boolean).join(' · ')).join(' · ') : 'No program selected.') + ' Model policy: Free first.';
    const persistWidth = async value => {
      setRequest('waiting');
      let result;
      try { result = await writeInspectorWidth(value); }
      catch (error) { result = {ok: false, error: error instanceof Error ? error.message : String(error)}; }
      if (result == null || result.ok === false) {
        setFailure(result?.error || 'Could not save the Properties width.');
        setRequest('error');
        retrySave.current = () => persistWidth(value);
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
    const agentChoices = (s.liveAgents || []).map(agent => ({key: agent.handle || agent.agent, handle: agent.handle ? agent.agent : undefined, name: agent.name && agent.name !== agent.agent ? agent.name : agent.agent, gate: agent.gate, breaches: agent.breaches}));
    const openTask = t => u.openTaskFile(t.id);
    const send = async () => {
      const body = text.trim();
      if (!body || sendingRef.current) return;
      sendingRef.current = true;
      setSending(true);
      const files = s.composerAttachments || [];
      const prompt = (!recipient || new RegExp('(^|\\s)@' + recipient + '\\b').test(body) ? '' : '@' + recipient + ' ') + body +
        (files.length ? '\nAttached project file nodes: ' + JSON.stringify(files.map(file=>({id:file.id,path:file.path}))) : '');
      const clearedRevision = (u.composerDraft[draftKey]?.revision || 0) + 1;
      setText('');
      try {
        const result = await u.act(() => api.apiRouterChat(prompt, 'BABOOM'));
        if (result == null) u.setComposerDraft(current => {
          const held = current[draftKey];
          return held?.revision === clearedRevision ? {...current,[draftKey]:{text:body,revision:held.revision+1}} : current;
        });
        else {for(const file of files) await api.removeComposerAttachment(file.id);await api.listTasks?.();}
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    };
    const reasonOf = t => {
      const review = Array.isArray(t.reviews) ? t.reviews.find(item => item && (item.summary || item.title || item.text || item.reason)) : null;
      const text = review ? (review.summary || review.title || review.text || review.reason) : (t.reason || t.result || t.detail || t.note || '');
      const summary = typeof t.summary === 'string' ? t.summary.split('\n').map(line => line.trim()) : [];
      const reason = typeof text === 'string' && text.trim() ? text.trim().split('\n')[0] : summary.find(line => line && line !== t.title && !['In progress', 'Planned, not started', 'Done', 'Needs you', 'No result yet', 'Keep going', 'Nothing further', 'Not started', 'Waiting for a decision'].includes(line)) || '';
      return /^[A-Z_]+$/.test(reason) ? reason.toLowerCase().replace(/_/g, ' ') : reason;
    };
    const toneOf = t => t.status === 'IN REVIEW' || waiting.has(t.id) ? 'review' : t.status === 'WIP' ? 'working' : t.status === 'STOPPED' ? 'stopped' : t.status === 'PLANNED' ? 'planned' : 'done';
    const openEvidence = async t => {
      await openTask(t);
      const card = (s.approvals || []).find(item => item.taskId === t.id || item.task_id === t.id);
      if (card) return u.show('Action evidence', {id: card.id});
      const node = document.querySelector('[data-dx="outputs"]') || document.querySelector('[data-dx="activity"]');
      if (node) node.focus();
      return true;
    };
    const lastUpdate = t => {
      const event = (t.activity || []).at(-1), text = (event && describe(event.output || event.text)) || reasonOf(t);
      if (!text) return '';
      const stamp = Date.parse(event?.at || event?.created_at || t.updated_at || '');
      if (!Number.isFinite(stamp)) return text;
      const minutes = Math.max(0, Math.floor((Date.now() - stamp) / 60000));
      return text + ' · ' + (minutes < 1 ? 'now' : minutes < 60 ? minutes + 'm' : minutes < 1440 ? Math.floor(minutes / 60) + 'h' : Math.floor(minutes / 1440) + 'd');
    };
    const taskRow = t => {
      const needsEvidence = t.status === 'IN REVIEW' || t.status === 'STOPPED' || waiting.has(t.id);
      return <div key={t.id} className={'dx-task-row' + (task?.id === t.id ? ' on' : '')} data-status={toneOf(t)} draggable={!!t.sessionPath} onDragStart={e=>{e.dataTransfer.setData('task',t.id);if(t.sessionPath)e.dataTransfer.setData('session',t.sessionPath);}}>
        <button type="button" className="dx-task" aria-selected={task?.id === t.id} onClick={() => executeAction('ui.select', () => u.setTask(t.id))} onDoubleClick={() => executeAction('ui.select', () => openTask(t))}>
          <b title={t.title}>{t.title}</b>
          <span className={!ownerOf(t) ? "muted" : undefined} title={ownerOf(t)}>{ownerOf(t) || "Not assigned"}</span>
          <span data-task-row-state={window.UI.taskRowReason(t) || undefined}>{window.UI.taskRowReason(t) || statusText(t.status)}</span>
          <span data-line="reason" title={lastUpdate(t)}>{lastUpdate(t)}</span>
        </button>
        {needsEvidence ? <button type="button" className="dx-evidence" aria-label={'Evidence for ' + t.title} onClick={() => executeAction('ui.select', () => openEvidence(t))}><Icon name="eye" size={14} /></button> : null}
      </div>;
    };
    const openFile = () => u.act(() => api.openSession()).then(result => { if (result && !result.cancelled) u.go('canvas'); return result; });
    const saveFile = asCopy => u.act(() => asCopy ? api.saveSessionAs() : api.saveSession());
    const fileKeys = event => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const tag = event.target && event.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (event.target && event.target.isContentEditable)) return;
      const key = String(event.key || '').toLowerCase();
      if (key === 'n') { event.preventDefault(); u.show('New task'); }
      else if (key === 'o') { event.preventDefault(); openFile(); }
      else if (key === 's') { event.preventDefault(); saveFile(event.shiftKey); }
    };
    const replyToMessage = message => {
      const sender = message.sender_key || message.who || '';
      const choice = choices.find(item => item.handle === sender || item.name === sender || item.key === sender);
      if (choice && choice.handle) setTo(choice.handle);
      const field = document.querySelector('.dx-composer textarea');
      if (field) field.focus();
    };
    const taskParameters = (<section className="dx-params" data-dx="params" aria-label="Task parameters">
                  <div className="dx-params-head"><h2>Task parameters</h2><p>Applies to this task file</p></div>
                  <details className="dx-fact dx-edit-field"><summary><span>Scope</span><span className="dx-edit-label">Edit</span><b>{useLabel(scopeValue) || ''}</b></summary><input key={(task?.id || '') + ':scope:' + scopeValue} aria-label="Scope" title={scopeValue} defaultValue={scopeValue} onBlur={e => { if (e.target.value === scopeValue) return false; return saveSession({scope: e.target.value}); }} /></details>
                  <ItemList action={fileWorkspace ? "Add" : "Edit"} label="Rules" icon="shield" items={rules} onCommit={next => saveSession({rules: next})} />
                  <ItemList action={fileWorkspace ? "Add" : "Edit"} label="Assigned agents" icon="users" items={agents} choices={agentChoices} onCommit={next => saveSession({agents: next})} />
                  {!fileWorkspace && <ItemList label="Folders" icon="folder" items={folders} onCommit={next => saveSession({folders: next})} />}
                  <ItemList action="Edit references" label="References" icon="link" items={references} onCommit={next => saveSession({references: next})} />
                  {[[fileWorkspace ? "Saved node" : "Session & saved workflow", (fileName || session) && task?.title ? task.title + '.archhub' : 'Not saved']].map(([label, value]) => {
                    const full = factText(value);
                    return fileWorkspace ? <details className="dx-fact dx-edit-field" key={label}><summary><span>{label}</span><span className="dx-edit-label">Details</span><b>{middle(full)}</b></summary><p>{(task?.workflow || []).length} nodes · {(task?.parameters || []).length} parameter groups</p></details> : <label className="dx-fact" key={label}><span>{label}</span><b className="dx-path" title={full}>{middle(full)}</b></label>;
                  })}
                  <details className="dx-fact dx-edit-field"><summary><span>Checkpoints</span><button type="button" className="dx-link dx-edit-label" onClick={event => {event.preventDefault();return executeAction('ui.select', () => u.act(() => api.checkpointTask(task.id)));}}>Save checkpoint</button><b>{task?.checkpoints?.find(c => c.id === checkpoint)?.title || ((task?.checkpoints || []).length ? 'No checkpoint selected' : 'No checkpoints yet')}</b></summary>
                    <span className="dx-checkpoint-row">
                      {(task?.checkpoints || []).length ? <select aria-label="Checkpoints" value={checkpoint} onChange={e => setCheckpoint(e.target.value)}><option value="">No checkpoint selected</option>{task.checkpoints.map(c => <option key={c.id} value={c.id}>{c.title || c.id}</option>)}</select> : null}
                      <button type="button" className="dx-quiet" disabled={!task || !checkpoint} onClick={() => executeAction('ui.select', () => u.act(() => api.restoreTaskCheckpoint(task.id, checkpoint)))}>Restore</button>
                    </span>
                  </details>
                  {fileWorkspace && <><ItemList action="Edit folders" label="Folders" icon="folder" items={folders} onCommit={next => saveSession({folders: next})} /><div className="dx-fact"><span>Recurrence</span><b>{(s.schedules || []).find(row => row.taskId === task?.id)?.time || "Not scheduled"}</b><button type="button" className="dx-link" onClick={() => executeAction("ui.select", () => u.schedule(task.id))}>Edit</button></div></>}
                  <details className="dx-plan-summary"><summary><span>Plan and progress</span><b>{plan.length ? plan.filter(step => stepOf(step, task?.progress).kind === 'done').length + ' of ' + plan.length + ' steps complete' : 'No plan recorded'}</b></summary><ol className="dx-stepper">{plan.map((step, index) => {
                        const recorded = stepOf(step, task?.progress);
                        const label = typeof step === 'object' ? (step.title || step.text || step.name || step.what || describe(step)) : String(step);
                        return <li key={index} data-step={recorded.kind}><Icon name={recorded.kind === 'done' ? 'check' : recorded.kind === 'working' ? 'clock' : 'arrow'} size={14} /><b>{label}</b><span>{recorded.label}</span><small>{recorded.owner}</small></li>;
                      })}</ol></details>
                </section>);
    const composerForm = <window.UI.TaskComposer docked thread={face === 'split'} choices={choices} to={recipient} setTo={setTo} draft={text} setDraft={setText} onSend={send} busy={sending} />;
    const composer = <div className="v22g-composer-dock">{composerForm}</div>;
    const tabs = u.canvasTabs?.tabs || [], tabCount = Math.max(1, Math.floor((tabsWidth - 100) / 150));
    const visibleTabs = tabs.length <= tabCount ? tabs : tabs.filter(tab => tab.id === task?.id || tabs.filter(row => row.id !== task?.id).indexOf(tab) < tabCount - 1);
    const hiddenTabs = tabs.filter(tab => !visibleTabs.includes(tab));
    const propertiesPane = <aside className="shared-properties" data-properties-pane="" aria-label="Properties">
      <header className="shared-properties-head">
        {!fileWorkspace && <span className="properties-eyebrow">TASK PROPERTIES</span>}
        <h2>{fileWorkspace ? face === 'canvas' ? inspectedNode?.title || s.graph.name || task?.title || 'Workflow' : 'Task parameters' : task?.title || 'Task properties'}</h2>
        {fileWorkspace ? <p>{face === 'canvas' ? inspectedNode ? 'Node parameters' : 'Workflow parameters' : 'Applies to this task file'}</p> : task && <p data-status={toneOf(task)}>{statusText(task.status)}</p>}
        <div data-design="inspector.tab" role="tablist" aria-label="Properties view">{['Task','Selection'].map(tab => <button data-design={'inspector.' + tab.toLowerCase()} type="button" role="tab" aria-selected={propertyTab === tab} key={tab} onClick={() => executeAction('ui.select', () => setPropertyTab(tab))}>{tab}</button>)}</div>
      </header>
      <div className="shared-properties-task" hidden={propertyTab !== 'Task'}>{task ? <>{fileWorkspace && <label className="grid">Describe the workflow<textarea data-design="inspector.describe" aria-label="Workflow description" rows={3} defaultValue={s.graph.documentation || ''} onBlur={e=>{if(e.target.value!==(s.graph.documentation||''))u.act(()=>api.updateGraph(s.graph.id,{documentation:e.target.value}));}} /></label>}{taskParameters}</> : <p className="muted">Select a task</p>}</div>
      {task && !fileWorkspace && <div className="dx-preview-actions" hidden={propertyTab !== 'Task'}>
        <Btn sm p onClick={() => executeAction('ui.select', () => u.openTaskFile(task.id))}>Open task</Btn>
      </div>}
      <div className="shared-properties-selection" hidden={propertyTab !== 'Selection'}>{inspectedWire ? <window.UI.WireInspector embedded wire={inspectedWire} s={s} u={u} onClose={clearInspection} /> : inspectedNode ? <window.UI.NodeInspector embedded n={inspectedNode} s={s} u={u}>{inspectedNode.fixed && inspectedNode.type === 'thing.workshop' && <ItemList label="Rules" icon="shield" items={rules} onCommit={next => saveSession({rules: next})} />}</window.UI.NodeInspector> : fileWorkspace && face === 'canvas' ? <window.UI.GraphProperties g={s.graph} s={s} u={u} /> : <p>Select a node or wire.</p>}</div>
    </aside>;
    if (!Array.isArray(s.tasks)) return <div className="dx-home-root dx-loading-layout" data-home-loading="" aria-busy="true" aria-label="Loading tasks"><div>{[0,1,2].map(row=><div className="dx-skeleton" key={row} />)}</div><aside>{[0,1,2].map(row=><div className="dx-skeleton" key={row} />)}</aside></div>;
    return <div ref={shellRef} className="dx-home-root" data-screen={fileWorkspace ? "task-file" : "home"} data-home-page={fileWorkspace ? undefined : ""} data-start={document.documentElement.dataset.start || 'cold'} onKeyDown={event => { if(event.key === 'Escape' && (inspection.nodeId || inspection.wireId)) {event.preventDefault();event.stopPropagation();clearInspection();} else fileKeys(event);}}>
      {request === 'waiting' ? <p role="status">Saving</p> : null}
      {request === 'error' ? <p role="alert">{failure} <button type="button" onClick={() => executeAction('ui.select', () => retrySave.current())}>Retry</button></p> : null}
      {request === 'empty' ? <p role="status">No tasks yet.</p> : null}
      {request === 'loaded' ? <span data-home-ready="" /> : null}
      <div className="dx-home">
        {!fileWorkspace ? <Group id="home-context" className="dx-home-landing dx-split" orientation="horizontal" onLayoutChanged={(_, meta) => {if(meta?.isUserInteraction && inspectorRef.current) persistWidth(Math.round(inspectorRef.current.getSize().inPixels));}}>
          <Column id="main" className="dx-task-index" minSize={320}><div className="dx-home-list">          <aside className="dx-tasks" data-dx="tasks" aria-label="Tasks">
            <div className="dx-tasks-head">
              <h1>Tasks</h1>
            </div>
            {!task && <p className="dx-task-hint">Select a task to see its properties.</p>}
            <div className="dx-find">
              <input aria-label="Find a task" placeholder="Search tasks" value={query} onChange={e => setQuery(e.target.value)} />
              <label className="dx-status" data-active={!status}><span className="sr-only">Status</span>
                <select aria-label="Status" value={status} onChange={e => { setStatus(e.target.value); setHistory(e.target.value === 'ARCHIVED'); }}>
                  <option value="">All tasks</option>
                  {['IN REVIEW', 'WIP', 'PLANNED', 'STOPPED', 'DONE', 'ARCHIVED'].map(v => <option key={v} value={v}>{statusText(v)}</option>)}
                </select>
              </label>
              <button type="button" className="dx-quiet" aria-pressed={status === 'IN REVIEW'} onClick={() => executeAction('ui.select', () => setStatus(status === 'IN REVIEW' ? '' : 'IN REVIEW'))}>Needs you</button>
              <button type="button" className="dx-quiet" data-view-link="" onClick={() => executeAction('ui.select', () => u.go('automations'))}>Automations</button>
              <button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => u.go('agents'))}>Agents {s.agentWorkingCount||0}</button>
              <button type="button" className="dx-new-task" onClick={() => executeAction('ui.show', u, 'New task')}>New task</button>
            </div>
            <div className="dx-task-columns" aria-hidden="true"><span>Task</span><span>Assigned to</span><span>Status</span><span>Last update</span></div>
            <div className="dx-tasks-list">
              {list.map(taskRow)}
            </div>
          </aside></div></Column>
          <Separator className="pane-splitter" aria-label="Resize the Properties pane" />
          <Column id="params" className="dx-home-preview" panelRef={inspectorRef} defaultSize={initialInspectorWidth.current} minSize={280} maxSize={480} groupResizeBehavior="preserve-pixel-size">{propertiesPane}</Column>
        </Group> :
          <div className="dx-workspace" data-dx="workspace" data-task-face={face}>
            <div className="v22g-strip">
              <div ref={tabsRef} className="v22g-tabs" role="tablist" aria-label="Open tasks">{visibleTabs.map(tab => <div key={tab.id} className="v22g-tab" data-design={tab.id === task?.id ? 'tab.active' : undefined} data-active={tab.id === task?.id} draggable onDragStart={e => {e.dataTransfer.setData('text/archhub-tab', tab.id);e.dataTransfer.setData('task',tab.id);}} onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault();const from=e.dataTransfer.getData('text/archhub-tab'),held=u.canvasTabs;const moved=held.tabs.find(t=>t.id===from);if(!moved||from===tab.id)return;const tabs=held.tabs.filter(t=>t.id!==from);tabs.splice(tabs.findIndex(t=>t.id===tab.id),0,moved);u.act(()=>u.saveCanvasTabs({...held,tabs}));}} onContextMenu={e => {e.preventDefault();u.show('Task tab menu',{id:tab.id});}}>
                <span className="v22g-tab-state" aria-hidden="true" style={{background:tab.id===task?.id && s.graph.nodes.some(node=>node.status==='Running') ? 'var(--color-accent)' : s.approvals.some(card=>card.work===tab.id && card.status==='pending') ? 'var(--color-warn)' : tasks.find(row=>row.id===tab.id)?.status==='DONE' ? 'var(--color-ok)' : 'var(--v22g-ink3)'}}/><button type="button" role="tab" aria-selected={tab.id === task?.id} data-preview={!tab.kept} onClick={event=>executeAction('ui.select',() => {if(tab.id!==task?.id)u.openTaskFile(tab.id);},event)} onDoubleClick={() => u.act(() => u.keepTaskTab(tab.id))}>{tasks.find(t=>t.id===tab.id)?.title || 'Task unavailable'}</button>
                <button type="button" data-design={tab.id === task?.id ? 'tab.close' : undefined} aria-label={'Close ' + (tasks.find(t=>t.id===tab.id)?.title || 'task')} onClick={event=>executeAction('ui.select',() => u.act(() => u.closeTaskTab(tab.id)),event)}><Icon name="close" size={12} /></button>
              </div>)}{hiddenTabs.length>0&&<details className="v22g-tab-overflow"><summary>{hiddenTabs.length} more</summary><div role="menu" aria-label="More open tasks">{hiddenTabs.map(tab=><button key={tab.id} type="button" role="menuitem" onClick={event=>executeAction("ui.select",()=>{event.currentTarget.closest("details").open=false;return u.openTaskFile(tab.id);})}>{tasks.find(t=>t.id===tab.id)?.title || "Task unavailable"}</button>)}</div></details>}<button type="button" className="dx-quiet" data-design="tab.add" aria-label="Open tasks" onClick={() => u.show('Open tasks')}>+</button></div>
              <div className="v22g-toolbar"><button type="button" data-design="toolbar.run" className="dx-quiet dx-primary-run" onClick={event=>executeAction('ui.select',() => u.act(async () => {await u.keepTaskTab(task.id);return canvasRef.current?.run();}),event)}>Run</button><button type="button" data-design="toolbar.thread" className="dx-quiet v22g-foldable" aria-label="Thread" aria-pressed={face === 'split'} onClick={event=>executeAction('ui.select',() => setFace(face === 'split' ? 'canvas' : 'split'),event)}><Icon name="workshop" size={14} /></button><button type="button" data-design="toolbar.more" className="dx-quiet" aria-label="More canvas actions" onClick={event=>executeAction('ui.select',() => canvasRef.current?.more(),event)}>…</button></div>
            </div>
            <Group key={layoutReady ? 'saved' : 'loading'} id="home-context" className="dx-split" orientation="horizontal" onLayoutChanged={(_, meta) => { if (meta?.isUserInteraction && inspectorRef.current) persistWidth(Math.round(inspectorRef.current.getSize().inPixels)); }}>
              <Column id="main" className="dx-col dx-task-column" minSize={320}>
                <div className="dx-surface-body">{!u.libraryOpen && <div className="v22g-library-rail"><button type="button" aria-label="Library" onClick={event=>executeAction('ui.select',()=>u.setLibraryOpen(true),event)}><Icon name="library" size={14}/><span>Library</span></button></div>}<Group className="v22g-views" orientation="horizontal"><Column id="task-canvas" minSize={320}><div className="v22g-canvas" data-design="canvas.stage"><window.UI.Canvas active embedded externalInspector controlsRef={canvasRef} onInspect={inspect} onHandoff={showCanvas} /></div></Column>{beside && <><Separator className="pane-splitter" aria-label="Resize session split" /><Column id="beside-canvas" minSize={320}><div className="v22g-beside"><header className="spread"><button type="button" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>u.openTaskFile(beside),event)}>{s.tasks.find(row=>row.id===beside)?.title || 'Task'} · Open</button><button type="button" className="dx-quiet" aria-label="Close split" onClick={event=>executeAction('ui.select',()=>u.act(()=>u.saveCanvasTabs({...u.canvasTabs,split:''})),event)}>×</button></header>{previewError ? <p role="alert">{previewError}</p> : preview ? <window.UI.Canvas key={beside} active embedded externalInspector preview={preview} onActivate={()=>u.openTaskFile(beside)} /> : <p role="status">Loading task…</p>}</div></Column></>}{face === 'split' && <><Separator className="pane-splitter" aria-label="Resize thread" /><Column id="task-thread" panelRef={threadRef} collapsible collapsedSize={48} onResize={size=>setThreadRail(size.inPixels<=49)} defaultSize="44%" minSize={300}>{threadRail&&<button type="button" className="canvas-pane-rail" aria-label="Open Thread" onClick={()=>executeAction("ui.select",()=>setThreadPeek(!threadPeek))}>Thread</button>}<div hidden={threadRail&&!threadPeek} data-thread-peek={threadRail&&threadPeek||undefined} className="dx-main v22g-thread" data-dx="main" data-home-face="split">
                  <div className="dx-thread-layout"><aside className="dx-threads" aria-label="Threads"><header><h2>Threads</h2><button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => u.go('home'))}>All tasks</button></header>{tasks.map(t => <button type="button" className="dx-thread-row" key={t.id} aria-selected={t.id === task?.id} onClick={() => executeAction('ui.select', () => u.openTaskFile(t.id, 'workshop'))}><b>{t.title}</b>{ownerOf(t) ? <span>You → {ownerOf(t)}</span> : null}<span>{window.UI.taskRowReason(t) || statusText(t.status)}{reasonOf(t) ? ' · ' + reasonOf(t) : ''}</span></button>)}</aside>
                  <div className="dx-work-scroll">
                  <div className="dx-mid" data-plan={plan.length ? 'shown' : 'hidden'}>
                    <div className="dx-stage">
                    <section className="dx-talk dx-thread" data-dx="conversation" aria-label="Conversation">
                      <div className="spread v22g-thread-head"><div><b>Thread</b><p>{ownerOf(task) || task?.title} · {statusText(task?.status)}</p></div><button type="button" data-design="thread.close" className="dx-quiet" aria-label="Close thread" onClick={event=>executeAction('ui.select',()=>{setThreadPeek(false);setFace('canvas');},event)}><Icon name="close" size={14}/></button></div><button type="button" data-design="thread.rules" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>{const node=s.graph.nodes.find(row=>row.fixed && row.type==='thing.workshop');if(node)inspect({nodeId:node.id});},event)}>Rules · {rules.length ? rules.join(' · ') : 'No rules set'}</button><p className="dx-thread-status">{ownerOf(task) && <span>You → {ownerOf(task)}</span>}<span>{statusText(task?.status)}</span></p>
                      {window.UI.taskRowReason(task || {}) === 'interrupted' ? <div className="dx-task-notice" role="status"><p>Interrupted · outcome unknown{reasonOf(task) ? ' · ' + reasonOf(task) : ''}</p><button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => u.go('receipts'))}>View activity</button></div> : null}
                      {window.UI.taskRowReason(task || {}) === 'limit reached' ? <div className="dx-task-notice" role="status"><p>Limit reached{task?.limits ? ' · ' + describe(task.limits) : ''}{reasonOf(task) ? ' · ' + reasonOf(task) : ''}</p><button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => u.go('runs'))}>View active runs</button></div> : null}
                      {task?.blocked_by ? <div className="dx-task-notice" role="status"><p>Blocked by {describe(task.blocked_by)}</p>{tasks.some(t => t.id === task.blocked_by) ? <button type="button" className="dx-link" onClick={() => executeAction('ui.select', () => u.openTaskFile(task.blocked_by, 'workshop'))}>View dependency</button> : null}</div> : null}
                      {!messages.length && !plan.length && !activity.length && !outputs.length && !scopeValue && !rules.length && !agents.length && !folders && !references && !session && !fileName ? <p className="dx-empty-task" data-dx="empty">Nothing recorded for this task yet.</p> : null}
                      {messages.map(m => {
                        const own = Boolean(m.sender_key) && m.sender_key === m.viewer_key || m.who === 'You';
                        const sender = own ? 'You' : (people.whoIs ? people.whoIs(m.who, m.sender_key).name : m.who);
                        const delivery = ((m.live || []).length ? m.live : m.delivery || []).map(d => [d.state || d.reason, d.agent ? (people.whoIs ? people.whoIs(d.agent).name : d.agent) : ''].filter(Boolean).join(' · ').replace(/_/g, ' ')).filter(Boolean).join(' · ') || String(m.state || '').replace(/_/g, ' ');
                        const attention = window.UI.deliveryAttention?.(m);
                        const who = m.sender_key || m.who || sender;
                        const open = detailId === (m.id || who);
                        return <article key={m.id} data-design="thread.message" data-pinned={task?.pinnedMessages?.includes(m.id)} className="dx-msg" onContextMenu={e=>{e.preventDefault();u.show('Task message menu',{taskId:task.id,message:m,open:()=>replyToMessage(m)});}}><span className="dx-avatar" style={{background:'var(--color-bg-soft)',color:'var(--color-ink-soft)'}} aria-hidden="true" title={sender}>{own && (!s.profile.name || s.profile.name === 'You') ? 'You' : String(own ? s.profile.name : sender || '?').trim().split(/\s+/).map(word => word[0]).join('').slice(0,2).toUpperCase()}</span><div className="dx-msg-line"><div><div className="dx-msg-heading"><b>{sender}</b><span>→ {m.to ? (people.whoIs ? people.whoIs(m.to).name : m.to) : own ? ownerOf(task) || 'Agent' : 'You'}</span></div><p>{typeof m.text === 'object' ? describe(m.text) : m.text}</p><span hidden={!attention} className="dx-delivery-chip" data-delivery-attention={attention || undefined} role="status">{attention}</span>{m.event ? <p className="dx-delivery">Task event: {describe(m.event)}</p> : null}{open ? <p className="dx-delivery">{[m.id, m.created_at, delivery].filter(Boolean).join(' · ') || 'No delivery record'}</p> : null}</div><span className="dx-msg-actions"><button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => replyToMessage(m))}>Reply</button><button type="button" className="dx-quiet" aria-expanded={open} onClick={() => executeAction('ui.select', () => setDetailId(open ? '' : (m.id || who)))}>Details</button></span></div></article>;
                      })}
                    </section>
                    </div>
                  </div>
                  {(activity.length || outputs.length) ? <div className="dx-low">
                    {outputs.length ? <section className="dx-panel dx-slim" id="dx-outputs" tabIndex={-1} data-dx="outputs" aria-label="Outputs">
                      <h2>Outputs</h2>
                      {outputs.map((row, index) => <article key={index} className="dx-output" data-output=""><span className="dx-output-preview">{row.thumb ? <img alt="" src={row.thumb} /> : <Icon name="docs" size={18} />}</span><div><b>{row.name || 'Output'}</b>{row.excerpt ? <p>{row.excerpt}</p> : null}</div></article>)}
                    </section> : null}
                  </div> : null}
                  </div>
                  </div>
                  <div className="dx-task-activity">
                    <section className="dx-panel" data-dx="activity" aria-label="Activity"><h2>Activity</h2>{activity.length ? activity.map(row => <p key={row.id}>{[statusText(row.status),describe(row.output)].filter(Boolean).join(' · ')}</p>) : <div className="dx-empty-activity"><p>Nothing has run yet.</p><button type="button" className="dx-link" onClick={() => executeAction('projects.ds_screens.Run.15', {api,u})}>Run workflow</button></div>}</section></div>
                  <p className="dx-foot" data-dx="footer">{footer}</p>
                </div></Column></>}</Group></div>
              </Column>
              <Separator className="pane-splitter" data-collapsed={inspectorRail || undefined} aria-label="Resize the Properties pane" />
              <Column id="params" className="dx-col dx-properties-column" collapsible collapsedSize={48} onResize={size=>setInspectorRail(size.inPixels<=49)} panelRef={inspectorRef} defaultSize={initialInspectorWidth.current} minSize={280} maxSize={480} groupResizeBehavior="preserve-pixel-size">
                {!inspectorRail&&shellWidth>=1436&&propertiesPane}{(inspectorRail||shellWidth<1436) && <button type="button" className="v22g-inspector-rail" aria-label="Open Inspector" onClick={event=>executeAction('ui.select',()=>{if(shellWidth>=1436)inspectorRef.current?.expand();setSplitInspector(true);},event)}><Icon name="settings" size={14}/></button>}
              </Column>
            </Group>{shellWidth<1436&&splitInspector&&<div className="v22g-inspector-peek"><button type="button" className="dx-quiet" aria-label="Close Inspector" onClick={()=>executeAction("ui.select",()=>setSplitInspector(false))}>×</button>{propertiesPane}</div>}
          </div>
        }
      </div>
      {fileWorkspace && composer}
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
  window.UI.homeMiddle = middle;
})();
