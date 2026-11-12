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
    const owner = (recorded && typeof recorded === 'object' && named(recorded)) || named(step) || '';
    const text = raw.trim();
    if (!text) return {kind: 'unreported', label: 'Planned', owner};
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
  function Home({fileWorkspace = false} = {}) {
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
    const [homeLayout, setHomeLayout] = React.useState({width:300,collapsed:false,resume:'',order:[],hidden:[]});
    const homeRef = React.useRef(homeLayout), homeWrites = React.useRef(Promise.resolve()), sessionsRef = React.useRef(null);
    const initialSessionsSize = React.useRef(window.innerWidth<1100?56:300);
    const [sessionsRail, setSessionsRail] = React.useState(false), [sessionsPeek, setSessionsPeek] = React.useState(false), [homeUndo, setHomeUndo] = React.useState(null);
    const saveHome = patch => {
      const value = {...homeRef.current,...patch};
      homeRef.current = value; setHomeLayout(value);
      const write = homeWrites.current.then(()=>api.setHomeLayout(value));
      homeWrites.current = write.catch(error=>u.setToast(error.message));
      return write;
    };
    React.useEffect(()=>{
      if(fileWorkspace)return undefined;
      let active=true;
      const read=()=>{
        setRequest('waiting');
        return api.readHomeLayout().then(result=>{if(active){homeRef.current=result.homeLayout;setHomeLayout(result.homeLayout);setRequest(s.tasks?.length?'loaded':'empty');}}).catch(error=>{if(active){setFailure(error.message);setRequest('error');retrySave.current=read;}});
      };
      read();
      return()=>{active=false;};
    },[fileWorkspace]);
    const [sending, setSending] = React.useState(false);
    const sendingRef = React.useRef(false);
    const [to, setTo] = React.useState(null);
    const [checkpoint, setCheckpoint] = React.useState('');
    const face = u.taskFace;
    const setFace = u.setTaskFace;
    const [detailId, setDetailId] = React.useState('');
    const [request, setRequest] = React.useState('loaded');
    const [failure, setFailure] = React.useState('');
    const [layoutReady, setLayoutReady] = React.useState(false);
    const retrySave = React.useRef(() => {});
    const inspectorRef = React.useRef(null), canvasRef = React.useRef(null);
    const shellRef = React.useRef(null), tabsRef = React.useRef(null), viewsRef = React.useRef(null);
    const [viewsWidth,setViewsWidth]=React.useState(0),[threadWidth,setThreadWidth]=React.useState(0),[besideShown,setBesideShown]=React.useState(false);
    const singleCanvas=Boolean(beside)&&viewsWidth-(face==='split'?Math.max(300,threadWidth)+6:0)<646;
    const [shellWidth, setShellWidth] = React.useState(window.innerWidth - 64), [tabsWidth, setTabsWidth] = React.useState(600);
    React.useLayoutEffect(()=>{
      if(fileWorkspace)return undefined;
      const frame=window.requestAnimationFrame(()=>{
        if(homeLayout.collapsed||window.innerWidth<1100)sessionsRef.current?.collapse();
        else sessionsRef.current?.resize(homeLayout.width);
      });
      return()=>window.cancelAnimationFrame(frame);
    },[fileWorkspace,homeLayout.collapsed,homeLayout.width,window.innerWidth<1100]);
    const [inspectorRail, setInspectorRail] = React.useState(false);
    const threadRef = React.useRef(null), [threadRail, setThreadRail] = React.useState(false), [threadPeek, setThreadPeek] = React.useState(false);
    React.useLayoutEffect(() => {
      const frame = window.requestAnimationFrame(() => {
        if (shellWidth < 1180) threadRef.current?.collapse();
        else threadRef.current?.expand();
      });
      setThreadPeek(face==='split'&&shellWidth<1180);
      return () => window.cancelAnimationFrame(frame);
    }, [shellWidth < 1180, face]);
    React.useLayoutEffect(() => {
      const observer = new window.ResizeObserver(entries => {
        for (const entry of entries) {
          if (entry.target === shellRef.current) setShellWidth(entry.contentRect.width);
          if (entry.target === tabsRef.current) setTabsWidth(entry.contentRect.width);
          if (entry.target === viewsRef.current) setViewsWidth(entry.contentRect.width);
        }
      });
      if (shellRef.current) observer.observe(shellRef.current);
      if (tabsRef.current) observer.observe(tabsRef.current);
      if (viewsRef.current) observer.observe(viewsRef.current);
      return () => observer.disconnect();
    }, [fileWorkspace,layoutReady]);
    const inspectorSetting = s.settings.find(row => row.id === 'Appearance.Inspector width');
    const inspectorWidth = inspectorSetting?.value ?? 320;
    // Changing defaultSize re-registers the panel; owner updates use resize().
    const initialInspectorWidth = React.useRef(inspectorWidth);
    const [inspection, setInspection] = React.useState({nodeId: null, wireId: null});
    const [propertyTab, setPropertyTab] = React.useState('Task');
    const [splitInspector, setSplitInspector] = React.useState(true);
    const inspectedNode = s.graph.nodes.find(node => node.id === inspection.nodeId);
    const inspectedWire = s.graph.wires.find(wire => wire.id === inspection.wireId);
    const inspect = value => {
      if(!value.nodeId&&!value.wireId&&!inspection.nodeId&&!inspection.wireId)return;
      setInspection(value);
      if(value.nodeId || value.wireId){setSplitInspector(true);inspectorRef.current?.expand();}
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
        let frame = window.requestAnimationFrame(() => {
          frame = window.requestAnimationFrame(() => {
            if(fileWorkspace && !splitInspector)inspectorRef.current?.collapse();
            else inspectorRef.current?.resize(inspectorWidth);
          });
        });
        return () => window.cancelAnimationFrame(frame);
      }
      return undefined;
    }, [inspectorWidth, layoutReady, fileWorkspace, face, splitInspector]);
    React.useEffect(()=>{setSplitInspector(face!=='split');},[face]);
    React.useEffect(() => {
      if (!fileWorkspace) {u.setSelectedNodeId(null);inspect({nodeId:null,wireId:null});}
    }, [fileWorkspace]);
    const waiting = new Set((s.approvals || []).filter(c => c.status === 'pending').flatMap(c => [c.taskId,c.task_id,c.work,...(c.taskIds||[])]));
    const rank=id=>{const index=homeLayout.order.indexOf(id);return index<0?homeLayout.order.length:index;};
    const tasks = (s.tasks || []).filter(t => t.status !== 'ARCHIVED').sort((a,b)=>Number(waiting.has(b.id)||b.status==='IN REVIEW')-Number(waiting.has(a.id)||a.status==='IN REVIEW')||Number(!!b.homePinned)-Number(!!a.homePinned)||rank(a.id)-rank(b.id));
    const list = tasks.filter(t => !homeLayout.hidden.includes(t.id));
    const sessionRows = [
      ...(s.tasks||[]).filter(t=>!homeLayout.hidden.includes(t.id)).sort((a,b)=>tasks.indexOf(a)-tasks.indexOf(b)).map(t=>({...t,kind:(s.graphs||[]).find(row=>row.path===t.sessionPath)?.kind||'agent-session'})),
      ...(s.graphs||[]).filter(row=>row.kind==='workflow'&&!(s.tasks||[]).some(t=>t.sessionPath===row.path)).map(row=>({...row,id:row.path,title:row.title||row.name,sessionPath:row.path,fileOnly:true}))
    ];
    const liveWorking=(s.agentGraph?.sessions||[]).filter(agent=>agent.status==='working');
    const liveIds=new Set();
    for(const agent of liveWorking){
      const row=sessionRows.find(row=>row.id===agent.task&&!liveIds.has(row.id));
      if(row){row.workingNow=true;liveIds.add(row.id);}
      else sessionRows.unshift({id:'live:'+agent.id,title:agent.name,kind:'agent-session',workingNow:true,runtimeAgent:agent});
    }
    const sectionOf=row=>{
      if(row.workingNow)return 'Working now';
      if(row.status==='ARCHIVED'||row.stale||row.status==='stale'||['interrupted','unknown'].includes(row.outcome)||window.UI.taskRowReason(row)==='interrupted')return 'Older / archived';
      if(waiting.has(row.id)||row.status==='IN REVIEW')return 'Needs you';
      const date=new Date(row.updated_at||row.modified||row.updatedAt||0),today=new Date();today.setHours(0,0,0,0);
      return date>=today?'Today':'Older / archived';
    };
    const collapsedSections=homeLayout.sections||['Older / archived'];
    const vendorLabel=/^[^/\n]{1,40} \/ [^/\n]+ \/ /;
    // The row names the work; an agent label is never the title.
    const workTitle=t=>{
      const title=String(t.title||'');
      if(title&&!vendorLabel.test(title)&&!vendorLabel.test(String(t.description||'')))return title;
      const text=[t.scope,(t.declarations||[])[0]?.task,...taskMessages(t).map(message=>message.text),t.runtimeAgent?.status_text].map(value=>String(value||'').split('\n')[0].trim()).find(value=>value&&!vendorLabel.test(value));
      return text?(text.length>60?text.slice(0,59).trimEnd()+'\u2026':text):'Untitled session';
    };
    const toggleSection=name=>saveHome({sections:collapsedSections.includes(name)?collapsedSections.filter(value=>value!==name):[...collapsedSections,name]});
    const focus = homeLayout.resume || u.task || s.focusedTask;
    const task = fileWorkspace ? tasks.find(t => t.id === u.task) : list.find(t => t.id === focus) || list.find(t=>t.homePinned) || list[0];
    React.useEffect(()=>{
      if(!fileWorkspace&&request!=='waiting'&&request!=='error')setRequest(tasks.length?'loaded':'empty');
    },[fileWorkspace,tasks.length,request]);
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
    const plan = task?.planInferred ? [] : Array.isArray(task?.plan) ? task.plan : [];
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
    const lastUpdate = t => {
      const event = (t.activity || []).at(-1), text = (event && describe(event.output || event.text)) || reasonOf(t);
      if (!text) return '';
      const stamp = Date.parse(event?.at || event?.created_at || t.updated_at || '');
      if (!Number.isFinite(stamp)) return text;
      const minutes = Math.max(0, Math.floor((Date.now() - stamp) / 60000));
      return text + ' · ' + (minutes < 1 ? 'now' : minutes < 60 ? minutes + 'm' : minutes < 1440 ? Math.floor(minutes / 60) + 'h' : Math.floor(minutes / 1440) + 'd');
    };
    const selectResume = t => {if(t.fileOnly)return u.act(()=>api.openSession(t.sessionPath)).then(opened=>{if(opened&&!opened.cancelled)u.go('canvas');});u.setTask(t.id);return saveHome({resume:t.id});};
    const openOwner = (t, name=ownerOf(t)) => {
      const agent=[...(s.agents||[]),...(s.providers||[])].find(a=>a.id===name||a.name===name||!name&&a.id===t.owner);
      if(agent)u.show('Agent',{id:agent.id});else u.go('settings/Agents');
    };
    const taskRow = t => <div key={t.id} data-design="home1.row" className={'dx-task-row resume-row'+(task?.id===t.id?' on':'')} data-status={waiting.has(t.id)||t.status==='IN REVIEW'?'review':toneOf(t)} draggable={!t.fileOnly} onDragStart={event=>{event.dataTransfer.setData('task',t.id);event.dataTransfer.setData('text/archhub-home-row',t.id);if(t.sessionPath)event.dataTransfer.setData('session',t.sessionPath);}} onDragOver={event=>event.preventDefault()} onDrop={event=>{event.preventDefault();const id=event.dataTransfer.getData('text/archhub-home-row');if(t.fileOnly||!list.some(row=>row.id===id)||id===t.id)return;const order=list.map(row=>row.id).filter(key=>key!==id);order.splice(order.indexOf(t.id),0,id);executeAction('ui.select',()=>saveHome({order}));}}>
      <button type="button" className="resume-avatar" aria-label={ownerOf(t)?'Open agent '+ownerOf(t):'Resume '+t.title} title={ownerOf(t)||t.title} onClick={()=>executeAction('ui.select',()=>ownerOf(t)?openOwner(t):selectResume(t))}>{ownerOf(t)?<window.UI.Av id={ownerOf(t)} size={28}/>:<Icon name="canvas" size={18}/>}</button>
      <button type="button" className="dx-task" aria-selected={task?.id===t.id} title={t.title} onClick={()=>executeAction('ui.select',()=>selectResume(t))} onDoubleClick={()=>executeAction('ui.select',()=>t.fileOnly?undefined:openTask(t))}><b>{workTitle(t)}</b><span>{waiting.has(t.id)?'Waits for you':window.UI.taskRowReason(t)||statusText(t.status)}{lastUpdate(t)?' · '+lastUpdate(t):''}</span></button>
      {!t.fileOnly&&<><button type="button" className="resume-pin" aria-label={(t.homePinned?'Unpin ':'Pin ')+t.title} aria-pressed={!!t.homePinned} onClick={()=>executeAction('ui.select',()=>u.act(()=>api.setTaskSession(t.id,{homePinned:!t.homePinned})))}><Icon name="pin" size={13}/></button>
      <button type="button" className="resume-hide" aria-label={'Hide '+t.title+' from Home'} onClick={()=>executeAction('ui.select',()=>{setHomeUndo(homeLayout);return saveHome({hidden:[...homeLayout.hidden,t.id],resume:task?.id===t.id?'':homeLayout.resume});})}>×</button></>}
    </div>;
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
    const liveNodes=task?.sessionOpen?s.graph.nodes:[];
    const work=(task?.workflow||[]).filter(node=>node.type!=='thing.session'&&!['fixed-agent','fixed-you','fixed-workshop','start'].includes(node.id));
    const resumeSteps=(work.length?work:plan.map((step,index)=>({id:stepKeys(step)[0]||String(index),title:describe(step),planStep:step}))).map(step=>{
      const live=liveNodes.find(node=>node.id===step.id), activityRow=activity.find(row=>row.id===step.id);
      const planned=stepOf(step.planStep||step,task?.progress),ran=row=>row&&row.status&&row.status!=='Idle';
      const state=ran(live)?stepOf(step,{[step.id]:live.status}):ran(activityRow)?stepOf(step,{[step.id]:activityRow.status}):planned;
      const value=live?.output??activityRow?.output??recordedStep(step.planStep||step,task?.progress)?.output,output=value&&typeof value==='object'&&'approvalId' in value?null:outputRecord(value);
      return {...step,state,value,output:useLabel(output?.name||output?.excerpt||''),preview:useLabel(output?.excerpt||'')};
    });
    const approvalSteps=(s.approvals||[]).filter(card=>card.status==='pending'&&(card.taskId===task?.id||card.work===task?.id||card.taskIds?.includes(task?.id))).filter((card,index,cards)=>cards.findIndex(row=>(row.input_digest||row.id)===(card.input_digest||card.id))===index).map(card=>{
      const refs=card.canvasNodes?.length?card.canvasNodes:[{nodeId:card.nodeId,path:card.path,taskId:card.taskId||card.work}];
      const index=resumeSteps.findIndex(step=>refs.some(ref=>ref.nodeId===step.id&&ref.path===task?.sessionPath&&ref.taskId===task?.id));
      return {card,index};
    });
    const heldIndex=approvalSteps.find(row=>row.index>=0)?.index??-1;
    const currentStep=heldIndex>=0?heldIndex:Math.max(0,resumeSteps.findIndex(step=>step.state.kind!=='done'));
    const stepLine=resumeSteps.length?resumeSteps.every(step=>step.state.kind==='done')?'All '+resumeSteps.length+' steps done':'Step '+(currentStep+1)+' of '+resumeSteps.length+': '+resumeSteps[currentStep].title+(heldIndex>=0?', waits for you':approvalSteps.length?', session waits for you':''):statusText(task?.status);
    const propertiesPane = <aside className="shared-properties" data-properties-pane="" aria-label="Properties">
      <div className="v48-inspector-bar"><Icon name="settings" size={13}/><span>Inspector</span><button type="button" className="button-reset" aria-label="Fold Inspector" onClick={event=>executeAction('ui.select',()=>{inspectorRef.current?.collapse();setSplitInspector(false);},event)}>−</button></div>
      <header className="shared-properties-head">
        <span className="properties-eyebrow">{propertyTab === 'Selection' ? 'PROPERTIES' : propertyTab === 'Automate' ? 'AUTOMATE' : 'THIS TASK'}</span>
        <h2>{propertyTab === 'Selection' ? inspectedNode?.title || task?.title || s.graph.name : task?.title || s.graph.name || 'Task'}</h2>
        <div data-design="inspector.tab" role="tablist" aria-label="Properties view">{[['Task','This task'],['Selection','Properties'],['Automate','Automate']].map(([tab,label]) => <button data-design={'inspector.' + tab.toLowerCase()} type="button" role="tab" aria-selected={propertyTab === tab} key={tab} onClick={() => executeAction('ui.select', () => setPropertyTab(tab))}>{label}</button>)}</div>
      </header>
      <div className="shared-properties-task" hidden={propertyTab !== 'Task'}>{task ? <>{fileWorkspace && propertyTab==='Task' && u.modal?.kind!=='Approve' && approvalSteps.map(({card})=><section key={card.id} className="v48-current-approval"><span>Needs your approval</span><h3>{s.graph.nodes.find(node=>node.id===card.nodeId)?.title || card.title}</h3><window.UI.ApprovalCard id={card.id} compact/>{card.text && <details className="v48-approval-parameters"><summary>All parameters</summary><pre>{card.text}</pre></details>}</section>)}<div className="v48-task-progress" role="progressbar" aria-label="Task progress" aria-valuemin={0} aria-valuemax={resumeSteps.length || 1} aria-valuenow={resumeSteps.filter(step=>step.state.kind==='done').length}>{resumeSteps.map((step,index)=><i key={step.id} data-state={approvalSteps.some(row=>row.index===index)?'awaiting':step.state.kind}/>)}</div><p className="v48-progress-line">{resumeSteps.filter(step=>step.state.kind==='done').length} of {resumeSteps.length} steps done{resumeSteps[currentStep] ? ', now ' + resumeSteps[currentStep].title : ''}</p><label className="grid">Description<textarea data-design="inspector.describe" aria-label="Workflow description" rows={6} key={task.id+':description'} defaultValue={s.graph.documentation || task.scope || task.description || ''} onBlur={e=>{if(e.target.value!==(s.graph.documentation||task.scope||task.description||''))u.act(()=>api.updateGraph(s.graph.id,{documentation:e.target.value}));}} /></label><div className="v48-made"><h3>What it made</h3>{resumeSteps.filter(step=>step.output).map(step=><button type="button" key={step.id} onClick={event=>executeAction('ui.select',()=>inspect({nodeId:step.id,wireId:null}),event)}><span><window.UI.ResultPreview value={step.value??step.preview}/></span><div><b>{step.title}</b><small>{step.output}</small></div></button>)}</div></> : <p className="muted">Select a task</p>}</div>
      <div className="shared-properties-task" hidden={propertyTab !== 'Automate'}><h3>Triggers</h3>{s.graph.nodes.filter(row=>row.type.startsWith('trigger.')).map(row=><button type="button" className="dx-link" key={row.id} onClick={event=>executeAction('ui.select',()=>inspect({nodeId:row.id,wireId:null}),event)}>{row.title}</button>)}{task && <button type="button" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>u.act(api.addAutomation),event)}>Add trigger</button>}</div>
      {task && !fileWorkspace && <div className="dx-preview-actions" hidden={propertyTab !== 'Task'}>
        <Btn sm p onClick={() => executeAction('ui.select', () => u.openTaskFile(task.id))}>Open task</Btn>
      </div>}
      <div className="shared-properties-selection" hidden={propertyTab !== 'Selection'}>{inspectedWire ? <window.UI.WireInspector embedded wire={inspectedWire} s={s} u={u} onClose={clearInspection} /> : inspectedNode ? <window.UI.NodeInspector embedded n={inspectedNode} s={s} u={u}>{inspectedNode.fixed && inspectedNode.type === 'thing.workshop' && <ItemList label="Rules" icon="shield" items={rules} onCommit={next => saveSession({rules: next})} />}</window.UI.NodeInspector> : task ? <>{taskParameters}<window.UI.GraphProperties g={s.graph} s={s} u={u}/></> : <p>Select a node or wire.</p>}</div>
    </aside>;
    if (!Array.isArray(s.tasks)) return <div className="dx-home-root dx-loading-layout" data-home-loading="" aria-busy="true" aria-label="Loading tasks"><div>{[0,1,2].map(row=><div className="dx-skeleton" key={row} />)}</div><aside>{[0,1,2].map(row=><div className="dx-skeleton" key={row} />)}</aside></div>;
    return <div ref={shellRef} className="dx-home-root" data-screen={fileWorkspace ? "task-file" : "home"} data-home-page={fileWorkspace ? undefined : ""} data-start={document.documentElement.dataset.start || 'cold'} onKeyDown={event => { if(event.key === 'Escape' && (inspection.nodeId || inspection.wireId)) {event.preventDefault();event.stopPropagation();clearInspection();} else fileKeys(event);}}>
      {request === 'waiting' ? <p role="status">{fileWorkspace?'Saving':'Loading sessions…'}</p> : null}
      {request === 'error' ? <p role="alert">{failure} <button type="button" onClick={() => executeAction('ui.select', () => retrySave.current())}>Retry</button></p> : null}
      {request === 'loaded' ? <span data-home-ready="" /> : null}
      <div className="dx-home">
        {!fileWorkspace ? <Group id="home-context" className={'dx-home-landing dx-split resume-home'+(sessionsRail&&!sessionsPeek?' sessions-rail':'')} orientation="horizontal" onLayoutChanged={(_,meta)=>{if(meta?.isUserInteraction&&sessionsRef.current){const size=sessionsRef.current.getSize().inPixels;saveHome({collapsed:size<=57,width:size<=57?homeLayout.width:Math.max(240,Math.min(440,Math.round(size)))});}}}>
          <Column id="sessions" panelRef={sessionsRef} collapsible collapsedSize={56} minSize={240} maxSize={440} defaultSize={initialSessionsSize.current} groupResizeBehavior="preserve-pixel-size" onResize={size=>setSessionsRail(size.inPixels<=57)}>
            <aside data-design="home1.list" className="resume-sessions" data-peek={sessionsRail&&sessionsPeek||undefined} aria-label="Sessions"><header><h2>Sessions</h2><button type="button" className="dx-quiet" data-design="home1.fold" aria-label={sessionsRail&&!sessionsPeek?'Open the list':'Fold the list to avatars'} onClick={()=>executeAction('ui.select',()=>{if(window.innerWidth<1100){setSessionsPeek(!sessionsPeek);return undefined;}return saveHome({collapsed:!sessionsRail});})}>{sessionsRail?'›':'‹'}</button></header>
              <div className="resume-session-scroll"><window.UI.SessionList list="home" rows={sessionRows} sectionOf={sectionOf} collapsedSections={collapsedSections} toggleSection={toggleSection} renderRow={row=>row.runtimeAgent?<div className="dx-task-row resume-row" key={row.id}><button type="button" className="resume-avatar" aria-label={'Open agent '+row.title} onClick={()=>executeAction('ui.select',()=>row.runtimeAgent.task?u.openTaskFile(row.runtimeAgent.task):u.go('settings/Agents'))}><window.UI.Av id={row.runtimeAgent.name} size={28}/></button><button type="button" className="dx-task" onClick={()=>executeAction('ui.select',()=>row.runtimeAgent.task?u.openTaskFile(row.runtimeAgent.task):u.go('settings/Agents'))}><b>{workTitle(row)}</b><span>{String(row.runtimeAgent.name||'').split(' / ').at(-1)} · {row.runtimeAgent.status}</span></button></div>:taskRow(row)}/></div>
              {!!homeLayout.hidden.length&&<button type="button" className="dx-quiet" onClick={()=>executeAction('ui.select',()=>saveHome({hidden:[]}))}>+ {homeLayout.hidden.length} hidden</button>}
              {homeUndo&&<button type="button" className="dx-quiet" onClick={()=>executeAction('ui.select',()=>{const previous=homeUndo;setHomeUndo(null);return saveHome(previous);})}>Undo Home change</button>}
            </aside>
          </Column>
          <Separator className="pane-splitter" aria-label="Resize the session list" />
          <Column id="resume" minSize={320}>
            <main className="resume-main"><div className="resume-home-controls"><button type="button" data-design="home1.reset" className="dx-quiet" onClick={()=>executeAction('ui.select',()=>{setHomeUndo(homeLayout);return saveHome({width:300,collapsed:false,resume:'',order:[],hidden:[]});})}>Reset Home</button></div>
              {task?<section className="resume-task" aria-label="Resumed session"><header data-design="home1.head" className="resume-heading"><div><h1>{task.sessionTitle||task.title}</h1><p>{stepLine}</p></div><div className="resume-people">{agents.map(name=><button type="button" key={name} aria-label={'Open agent '+name} title={name} onClick={()=>executeAction('ui.select',()=>openOwner(task))}><window.UI.Av id={name} size={28}/></button>)}</div><Btn data-design="home1.open" sm onClick={()=>executeAction('ui.select',()=>openTask(task))}>Open its Canvas</Btn></header>
                {!resumeSteps.length&&<section className="resume-summary" aria-label="Session activity"><p>{statusText(task.status)}{ownerOf(task)?' · '+ownerOf(task):''}</p>{outputs.map((output,index)=><pre className="resume-preview" key={index}>{useLabel(output.name||output.excerpt)}</pre>)}{!messages.length&&!outputs.length&&<p>{reasonOf(task)||'No messages yet.'}</p>}</section>}<div className="resume-steps">{resumeSteps.map((step,index)=><article key={step.id} data-resume-step={step.id} data-state={step.state.kind} data-made={step.output?'':undefined} data-design="home1.step" className="resume-step"><header><span className="resume-step-tile"><Icon name={step.state.kind==='done'?'check':'canvas'} size={14}/></span><b>{step.title}</b></header><p>{step.state.label}{step.output?' · '+step.output:''}</p>{step.output&&<div className="v48-step-preview resume-made"><window.UI.ResultPreview value={step.value??step.preview}/></div>}{approvalSteps.filter(row=>row.index===index).map(({card})=><window.UI.ApprovalCard key={card.id} id={card.id} compact/>)}</article>)}</div>
                {approvalSteps.filter(row=>row.index<0).map(({card})=><window.UI.ApprovalCard key={card.id} id={card.id} compact/>)}
                {messages.length>0&&<section data-design="home1.thread" className="resume-thread" aria-label="Last thread lines"><h2>In the thread</h2>{messages.slice(-3).map(message=><button type="button" key={message.id} onClick={()=>executeAction('ui.select',()=>u.openTaskFile(task.id,'split'))}><window.UI.Av id={message.who||'Agent'} size={24}/><span><b>{message.who}</b> {describe(message.text)}</span></button>)}</section>}
              </section>:request === 'empty'?<section className="resume-zero"><h1>What do you need?</h1>{['Review a drawing set','Check a model against the standard','Collect files for an issue'].map(prompt=><button type="button" key={prompt} onClick={()=>executeAction('ui.select',()=>{const key=JSON.stringify(['home','']);u.setComposerDraft(current=>({...current,[key]:{text:prompt,revision:(current[key]?.revision||0)+1}}));document.querySelector('.global-composer textarea')?.focus();})}><Icon name="brain" size={18}/>{prompt}</button>)}</section>:null}
            </main>
          </Column>
        </Group> :
          <div className="dx-workspace" data-dx="workspace" data-task-face={face}>
            <div className="v22g-strip">
              <div ref={tabsRef} className="v22g-tabs" role="tablist" aria-label="Open tasks">{visibleTabs.map(tab => <div key={tab.id} className="v22g-tab" data-design={tab.id === task?.id ? 'tab.active' : undefined} data-active={tab.id === task?.id} draggable onDragStart={e => {e.dataTransfer.setData('text/archhub-tab', tab.id);e.dataTransfer.setData('task',tab.id);}} onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault();const from=e.dataTransfer.getData('text/archhub-tab'),held=u.canvasTabs;const moved=held.tabs.find(t=>t.id===from);if(!moved||from===tab.id)return;const tabs=held.tabs.filter(t=>t.id!==from);tabs.splice(tabs.findIndex(t=>t.id===tab.id),0,moved);u.act(()=>u.saveCanvasTabs({...held,tabs}));}} onContextMenu={e => {e.preventDefault();u.show('Task tab menu',{id:tab.id});}}>
                <span className="v22g-tab-state" aria-hidden="true" style={{background:tab.id===task?.id && s.graph.nodes.some(node=>node.status==='Running') ? 'var(--color-accent)' : s.approvals.some(card=>card.work===tab.id && card.status==='pending') ? 'var(--color-warn)' : tasks.find(row=>row.id===tab.id)?.status==='DONE' ? 'var(--color-ok)' : 'var(--v22g-ink3)'}}/><button type="button" role="tab" aria-selected={tab.id === task?.id} data-preview={!tab.kept} onClick={event=>executeAction('ui.select',() => {if(tab.id!==task?.id)u.openTaskFile(tab.id);},event)} onDoubleClick={() => u.act(() => u.keepTaskTab(tab.id))}>{tasks.find(t=>t.id===tab.id)?.title || 'Task unavailable'}</button>
                <button type="button" data-design={tab.id === task?.id ? 'tab.close' : undefined} aria-label={'Close ' + (tasks.find(t=>t.id===tab.id)?.title || 'task')} onClick={event=>executeAction('ui.select',() => u.act(() => u.closeTaskTab(tab.id)),event)}><Icon name="close" size={12} /></button>
              </div>)}{hiddenTabs.length>0&&<details className="v22g-tab-overflow"><summary>{hiddenTabs.length} more</summary><div role="menu" aria-label="More open tasks">{hiddenTabs.map(tab=><button key={tab.id} type="button" role="menuitem" onClick={event=>executeAction("ui.select",()=>{event.currentTarget.closest("details").open=false;return u.openTaskFile(tab.id);})}>{tasks.find(t=>t.id===tab.id)?.title || "Task unavailable"}</button>)}</div></details>}<button type="button" className="dx-quiet" data-design="tab.add" aria-label="Open tasks" onClick={() => u.show('Open tasks')}>+</button></div>
              <div className="v22g-toolbar v48-toolbar"><div className="v48-toolbar-agents">{agents.slice(0,3).map(name=><button type="button" className="button-reset" key={name} title={name} aria-label={'Open agent '+name} onClick={event=>executeAction('ui.select',()=>openOwner(task,name),event)}><window.UI.Av id={name} size={28}/></button>)}{agents.length>3 && <button type="button" className="dx-quiet" aria-label="All session agents" onClick={event=>executeAction('ui.select',()=>u.show('Task details',{id:task.id}),event)}>+{agents.length-3}</button>}</div><div className="v48-save"><button type="button" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>saveFile(false),event)}><Icon name="export" size={13}/>Save</button><details><summary aria-label="Save menu">↓</summary><div className="v48-save-menu">{[['Save as…',()=>saveFile(true)],['Save as skill…',()=>u.show('Save skill')]].map(([label,run])=><button type="button" key={label} onClick={event=>executeAction('ui.select',()=>{event.currentTarget.closest('details').open=false;return run();},event)}>{label}</button>)}</div></details></div><button type="button" className="dx-quiet v48-secondary" onClick={event=>executeAction('ui.select',()=>{setPropertyTab('Automate');setSplitInspector(true);inspectorRef.current?.expand();},event)}><Icon name="clock" size={13}/>Automate</button><button type="button" data-design="toolbar.run" className="dx-quiet dx-primary-run" disabled={singleCanvas&&besideShown} onClick={event=>executeAction('ui.select',() => u.act(async () => {await u.keepTaskTab(task.id);return canvasRef.current?.run();}),event)}>Run all</button>{[['Undo','undo',()=>u.act(api.undo)],['Redo','redo',()=>u.act(api.redo)],['Tidy up','arrange',()=>canvasRef.current?.arrange()]].map(([label,icon,run])=><button key={label} type="button" className="dx-quiet v48-secondary" aria-label={label} title={label} onClick={event=>executeAction('ui.select',run,event)}><Icon name={icon} size={14}/></button>)}<button type="button" data-design="toolbar.thread" className="dx-quiet v22g-foldable" aria-label="Thread" aria-pressed={face === 'split'} onClick={event=>executeAction('ui.select',() => setFace(face === 'split' ? 'canvas' : 'split'),event)}><Icon name="workshop" size={14} /></button><button type="button" data-design="toolbar.more" className="dx-quiet" aria-label="More canvas actions" onClick={event=>executeAction('ui.select',() => canvasRef.current?.more(),event)}>…</button></div>
            </div>
            <Group key={layoutReady ? 'saved' : 'loading'} id="home-context" className="dx-split" orientation="horizontal" onLayoutChanged={(_, meta) => { if (meta?.isUserInteraction && inspectorRef.current) persistWidth(Math.round(inspectorRef.current.getSize().inPixels)); }}>
              <Column id="main" className="dx-col dx-task-column" minSize={320}>
                <div className="dx-surface-body">{!u.libraryOpen && <div className="v22g-library-rail"><button type="button" aria-label="Library" onClick={event=>executeAction('ui.select',()=>u.setLibraryOpen(true),event)}><Icon name="library" size={14}/><span>Library</span></button></div>}<div className="v22g-views-frame" ref={viewsRef}>{singleCanvas&&<div className="v22g-canvas-switch" role="group" aria-label="Visible canvas"><button type="button" aria-pressed={!besideShown} onClick={()=>executeAction('ui.select',()=>setBesideShown(false))}>{task?.title}</button><button type="button" aria-pressed={besideShown} onClick={()=>executeAction('ui.select',()=>setBesideShown(true))}>{s.tasks.find(row=>row.id===beside)?.title}</button></div>}<Group className="v22g-views" orientation="horizontal">{(!singleCanvas||!besideShown)&&<Column id="task-canvas" minSize={320}><div className="v22g-canvas" data-design="canvas.stage"><window.UI.Canvas active embedded externalInspector steps={{done:resumeSteps.filter(step=>step.state.kind==='done').length,total:resumeSteps.length}} planned={work.length?null:resumeSteps.map(step=>({title:step.title,kind:step.state.kind,label:step.state.label}))} occludedWidth={threadRail&&threadPeek?380:0} controlsRef={canvasRef} onInspect={inspect} onHandoff={showCanvas} /></div></Column>}{beside&&(!singleCanvas||besideShown) && <>{!singleCanvas&&<Separator className="pane-splitter" aria-label="Resize session split" />}<Column id="beside-canvas" minSize={320}><div className="v22g-beside"><header className="spread"><button type="button" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>u.openTaskFile(beside),event)}>{s.tasks.find(row=>row.id===beside)?.title || 'Task'} · Open</button><button type="button" className="dx-quiet" aria-label="Close split" onClick={event=>executeAction('ui.select',()=>u.act(()=>u.saveCanvasTabs({...u.canvasTabs,split:''})),event)}>×</button></header>{previewError ? <p role="alert">{previewError}</p> : preview ? <window.UI.Canvas key={beside} active embedded externalInspector preview={preview} onActivate={()=>u.openTaskFile(beside)} /> : <p role="status">Loading task…</p>}</div></Column></>}{face === 'split' && <><Separator className="pane-splitter" aria-label="Resize thread" /><Column id="task-thread" panelRef={threadRef} collapsible collapsedSize={48} onResize={size=>{setThreadRail(size.inPixels<=49);setThreadWidth(size.inPixels);}} defaultSize="44%" minSize={300}>{threadRail&&<button type="button" className="canvas-pane-rail" aria-label="Open Thread" onClick={()=>executeAction("ui.select",()=>setThreadPeek(!threadPeek))}>Thread</button>}<div hidden={threadRail&&!threadPeek} data-thread-peek={threadRail&&threadPeek||undefined} className="dx-main v22g-thread" data-dx="main" data-home-face="split">
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
                </div></Column></>}</Group></div></div>
              </Column>
              <Separator className="pane-splitter" data-collapsed={inspectorRail || undefined} aria-label="Resize the Properties pane" />
              <Column id="params" className="dx-col dx-properties-column" collapsible collapsedSize={48} onResize={size=>setInspectorRail(size.inPixels<=49)} panelRef={inspectorRef} defaultSize={initialInspectorWidth.current} minSize={280} maxSize={480} groupResizeBehavior="preserve-pixel-size">
                {!inspectorRail&&propertiesPane}{inspectorRail && <button type="button" className="v22g-inspector-rail" aria-label="Open Inspector" onClick={event=>executeAction('ui.select',()=>{inspectorRef.current?.expand();setSplitInspector(true);},event)}><Icon name="settings" size={14}/></button>}
              </Column>
            </Group>
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
