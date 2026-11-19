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
  // A Workshop card's Show asks for the cursor in that thread's composer. The ask outlives the screen's remount when the
  // thread opens, and ends on the first composer render that shows that thread (focused) or another thread (dropped).
  let focusAsk = null, homeShown = '';
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
  // A session label is "agent / project folder / session id": people read the first two; the id stays in Workshop Inspect.
  const humanLabel = label => String(label || '').split(' / ').slice(0, 2).join(' · ');
  // One owner for the Home list and the header's count: every session row and the section it sits in.
  const homeRows = (s, layout) => {
    const hidden = layout?.hidden || [], order = layout?.order || [];
    // A held run names its session by task id or by the session file it runs in.
    const held = (s.approvals || []).filter(c => c.status === 'pending');
    const namesOf = c => [c.taskId,c.task_id,c.work,...(c.taskIds||[]),c.path,...(c.canvasNodes||[]).flatMap(ref=>[ref.taskId,ref.path])].filter(Boolean);
    const waiting = new Set(held.flatMap(namesOf).flatMap(name => [name,...(s.tasks||[]).filter(t=>t.sessionPath===name).map(t=>t.id)]));
    const rank=id=>{const index=order.indexOf(id);return index<0?order.length:index;};
    const tasks = (s.tasks || []).filter(t => t.status !== 'ARCHIVED').sort((a,b)=>Number(waiting.has(b.id)||b.status==='IN REVIEW')-Number(waiting.has(a.id)||a.status==='IN REVIEW')||Number(!!b.homePinned)-Number(!!a.homePinned)||rank(a.id)-rank(b.id));
    const sessionRows = [
      ...(s.tasks||[]).filter(t=>!hidden.includes(t.id)).sort((a,b)=>tasks.indexOf(a)-tasks.indexOf(b)).map(t=>({...t,kind:(s.graphs||[]).find(row=>row.path===t.sessionPath)?.kind||'agent-session'})),
      ...(s.graphs||[]).filter(row=>row.kind==='workflow'&&!(s.tasks||[]).some(t=>t.sessionPath===row.path)).map(row=>({...row,id:row.path,title:row.title||row.name,sessionPath:row.path,fileOnly:true}))
    ];
    // One row per piece of work: a further live agent on it is an avatar on that row, never a second row.
    for(const agent of (s.agentGraph?.sessions||[]).filter(agent=>agent.status==='working')){
      const row=sessionRows.find(row=>row.id===agent.task);
      if(row){row.workingNow=true;if(agent.name&&!(row.members||[]).some(member=>member.name===agent.name))row.members=[...(row.members||[]),{name:agent.name,live:true}];}
      else sessionRows.unshift({id:'live:'+agent.id,title:agent.name,kind:'agent-session',workingNow:true,runtimeAgent:agent});
    }
    // A held run that belongs to no listed session is a row too: it needs him, so it is shown and counted.
    for(const card of held.filter((card,index)=>held.findIndex(other=>(other.input_digest||other.id)===(card.input_digest||card.id))===index))
      if(!namesOf(card).some(name=>sessionRows.some(row=>row.id===name||row.sessionPath===name)))
        sessionRows.unshift({id:'approval:'+card.id,title:card.title||'A run waits for your approval',kind:'agent-session',approval:card.id,who:card.who||''});
    // A piece of work (F337) that lost its agent stays an open row; old per-agent-run rows go under Older.
    const pieceOfWork=row=>(row.members||[]).length>0&&!String(row.id).startsWith('declared-')&&row.status!=='DONE'&&row.status!=='ARCHIVED';
    // A dead piece of work (no live agent for 24 h) sits under Older and still offers Continue.
    const interruptedWork=row=>pieceOfWork(row)&&(row.outcome==='interrupted'||row.outcome==='unknown'||!!row.stale);
    const sectionOf=row=>{
      if(row.approval||waiting.has(row.id))return 'Needs you';  // a held run needs him, whoever is working
      if(row.workingNow)return 'Working now';
      if(interruptedWork(row)&&!row.stale)return 'Needs you';
      if(row.status==='ARCHIVED'||row.stale||row.status==='stale'||['interrupted','unknown'].includes(row.outcome)||window.UI.taskRowReason(row)==='interrupted')return 'Older / archived';
      if(row.status==='IN REVIEW')return 'Needs you';
      const date=new Date(row.updated_at||row.modified||row.updatedAt||0),today=new Date();today.setHours(0,0,0,0);
      return date>=today?'Today':'Older / archived';
    };
    const list = tasks.filter(t => !hidden.includes(t.id));
    // The session Home shows selected: the one asked for, else the pinned one, else the first listed (the Canvas rail opens the same one).
    const resumed = focus => list.find(t => t.id === focus) || list.find(t=>t.homePinned) || list[0];
    // The header, the map's bar and its cards read these: what needs him, and what an agent works on now that does not.
    const needs = row => sectionOf(row) === 'Needs you', working = row => sectionOf(row) === 'Working now';
    // The held run of a row, when it has one (the card's "needs your approval" line opens it).
    const heldOf = row => held.find(card => namesOf(card).some(name => name === row.id || name === row.sessionPath));
    return {waiting, tasks, list, resumed, sessionRows, sectionOf, needs, working, heldOf, interruptedWork,
      needsYou: sessionRows.filter(needs).length, running: sessionRows.filter(working).length};
  };
  // Home's map of the work: every session as a card in its group, wired by its input links. Sessions come from the session
  // files (/api/session-model); a row with no file yet (a live agent, a task) is a card too, so the map shows what the header counts.
  const MAP_STATES = ['Needs you', 'Failed', 'Working', 'Idle'];
  const stepTitle = step => typeof step === 'object' && step ? step.title || step.text || step.name || step.what || describe(step) : String(step);
  // room: the map's own width over height when known; a narrow room stacks cards and wraps groups so names stay readable.
  // kind: All / Agent sessions / Workflows (the list's filter); olderOpen: the Older section unfolded; order: his own arrangement (task ids).
  const homeMap = ({listed, rows, params, hidden = [], titleOf, room = null, kind = 'all', olderOpen = false, order = []}) => {
    const p = {...params, collapsed: params.collapsed || []};
    // What a card says comes from the session's own row: its steps and their states, its held run or its failed step.
    const facts = (row, filePlan) => {
      const work = (row?.workflow || []).filter(node => node.type !== 'thing.session' && !['fixed-agent', 'fixed-you', 'fixed-workshop', 'start'].includes(node.id));
      const plan = row && Array.isArray(row.plan) && !row.planInferred ? row.plan : filePlan || [];
      const ran = id => String((row?.activity || []).find(item => item.id === id)?.status || '');
      const steps = work.length ? work.map(node => ({title: node.title || node.id, kind: /running/i.test(ran(node.id)) ? 'working' : stepOf(node, {[node.id]: ran(node.id)}).kind}))
        : plan.map(step => ({title: stepTitle(step), kind: stepOf(step, row?.progress).kind}));
      const held = row ? rows.heldOf(row) : null, failed = steps.find(step => step.kind === 'error');
      const at = steps.findIndex(step => ['working', 'awaiting', 'error'].includes(step.kind)), done = steps.filter(step => step.kind === 'done').length;
      return {steps, done, finished: steps.length > 0 && done === steps.length,
        now: at >= 0 ? 'Step ' + (at + 1) + ' of ' + steps.length + ' · ' + steps[at].title : steps.length ? done + ' of ' + steps.length + ' steps done'
          : row && window.UI.taskRowReason?.(row) ? 'Stopped: ' + window.UI.taskRowReason(row) : 'No steps yet',
        // Work that lost its agent (F337) stays open with Continue: any agent picks it up on the same graph and thread.
        need: held ? {text: (held.title || 'A run') + ' needs your approval', approval: held.id} : failed ? {text: failed.title + ' failed', failed: true}
          : row && rows.interruptedWork(row) && !row.stale ? {text: 'Interrupted · waiting for an agent', resume: true} : null,
        // The lead is the card's agent; everyone else on this piece of work is a small avatar on the same card, never a second card.
        members: [...new Set((row?.members || []).map(member => member.name).filter(Boolean))].slice(1),
        state: row && rows.needs(row) ? 'Needs you' : failed ? 'Failed' : row && rows.working(row) ? 'Working' : 'Idle'};
    };
    // A card is a piece of work (founder 2026-11-19): agents are members of it, never cards. A session whose task row is
    // archived (the one-time retire of declare-made sessions, or his own archive) is no card; its file stays where it is.
    const work = session => session.state !== 'archived' && !hidden.includes(session.task)
      && rows.sessionRows.find(item => item.id === session.task)?.status !== 'ARCHIVED';
    const files = (listed?.groups || []).flatMap(group => group.sessions).filter(work).map(session => {
      const row = rows.sessionRows.find(item => item.id === session.task), fact = facts(row, session.context?.plan);
      return {id: session.id, path: session.path, task: session.task || '', parent: row?.parent || '', title: session.title, project: session.project?.label || 'No project',
        kind: row?.kind || session.kind || 'agent-session', older: !!row && rows.sectionOf(row) === 'Older / archived',
        agent: humanLabel((session.members || [])[0]?.name || row?.owner || ''), pinned: !!session.pinned, ...fact,
        finished: fact.finished || session.state === 'done' || row?.status === 'DONE', armed: (session.automation || []).filter(trigger => trigger.armed).length, links: session.inputLinks || []};
    });
    const filed = new Set(files.flatMap(card => [card.task, card.path]).filter(Boolean));
    // An archived row (a refused start the owner archived, an old run) is not work on the map.
    // A live agent with no session is present in the Workshop dock, not a card.
    const loose = rows.sessionRows.filter(row => row.status !== 'ARCHIVED' && !row.runtimeAgent && !filed.has(row.id) && !filed.has(row.sessionPath || row.path || '')).map(row => ({id: row.approval ? row.id : 'row:' + row.id, path: row.sessionPath || '',
      task: row.runtimeAgent ? row.runtimeAgent.task || '' : row.fileOnly || row.approval ? '' : row.id, parent: row.parent || '', title: row.approval ? row.title : titleOf(row),
      project: row.runtimeAgent ? String(row.runtimeAgent.name || '').split(' / ')[1] || 'No project' : row.workspace || row.project || 'No project',
      agent: humanLabel(row.runtimeAgent?.name || (row.members || [])[0]?.name || row.owner || row.who || ''), pinned: !!row.homePinned, ...facts(row, null), armed: 0, links: [],
      kind: row.kind || 'agent-session', older: !row.approval && rows.sectionOf(row) === 'Older / archived',
      ...(row.approval ? {need: {text: row.title + ' needs your approval', approval: row.approval}} : {}), ...(row.status === 'DONE' ? {finished: true} : {})}));
    const every = [...files, ...loose];
    // Projects > tasks > subtasks (one task owner, parent_id): a subtask sits in its top task's group, wired from its parent,
    // one column to the right; a parent folded with 'task:<id>' hides every subtask under it.
    const byTask = new Map(every.filter(card => card.task).map(card => [card.task, card]));
    const above = card => card.parent && card.parent !== card.task ? byTask.get(card.parent) || null : null;
    const chainUp = card => { const chain = []; for (let up = above(card); up && !chain.includes(up) && chain.length < 32; up = above(up)) chain.push(up); return chain; };
    const rootOf = card => chainUp(card).at(-1) || card;
    for (const card of every) { card.subtasks = every.filter(other => above(other) === card).length; card.subtasksFolded = card.subtasks > 0 && p.collapsed.includes('task:' + card.task); }
    const cards = every.filter(card => (p.done === 'Show' || !card.finished || card.pinned) && (p.filter === 'All' || card.state === (p.filter === 'Running' ? 'Working' : 'Needs you'))
      && (kind === 'all' || card.kind === kind) && !chainUp(card).some(up => up.subtasksFolded));
    // Old runs keep their own section, folded until he opens it (the list's Older / archived), whatever the grouping.
    const ownKey = card => card.older ? 'Older / archived' : p.group === 'Agent' ? card.agent || 'No agent yet' : p.group === 'State' ? card.state : card.project;
    const keyOf = card => ownKey(rootOf(card));
    const rank = card => { const at = order.indexOf(card.task || card.id); return at < 0 ? order.length : at; };  // his drag order, then the rest
    cards.sort((a, b) => (p.order === 'Name' ? 0 : MAP_STATES.indexOf(a.state) - MAP_STATES.indexOf(b.state)) || (p.order === 'Name' ? 0 : rank(a) - rank(b)) || a.title.localeCompare(b.title));
    const keys = [...new Set(cards.map(keyOf))].sort((a, b) => Number(a === 'Older / archived') - Number(b === 'Older / archived') || (p.group === 'State' ? MAP_STATES.indexOf(a) - MAP_STATES.indexOf(b) : a.localeCompare(b)));
    const folded = key => key === 'Older / archived' ? !olderOpen : p.collapsed.includes(key);
    // An input link is one wire, card edge to card edge: this session feeds that one. The session model holds no socket type
    // for a link, so the wire shows the design's default (files, a list); its hover says what the link really carries.
    const links = cards.flatMap(card => card.links.map((link, index) => ({id: card.id + ':' + index, from: link.source.id, to: card.id, fromPort: 'out', toPort: 'in',
      type: 'file', list: true, label: link.output + ' → ' + link.input})))
      .concat(cards.filter(above).map(card => ({id: 'subtask:' + card.id, from: above(card).id, to: card.id, fromPort: 'out', toPort: 'in', type: 'text', list: false, label: 'Subtask'})))
      .filter(wire => cards.some(card => card.id === wire.from));
    const wide = 300, plain = p.card === 'State only', gapX = p.density === 'Compact' ? 36 : 56, gapY = p.density === 'Compact' ? 14 : 24;
    const nodes = [], groups = [], inside = new Map();
    let x = 0, y = 0, band = 0;
    const laid = keys.map(key => {
      const members = cards.filter(card => keyOf(card) === key), ids = new Set(members.map(card => card.id)), level = new Map();
      const depth = (id, trail = []) => level.has(id) ? level.get(id) : trail.includes(id) ? 0 : (level.set(id, Math.max(0, ...links.filter(wire => wire.to === id && ids.has(wire.from)).map(wire => depth(wire.from, [...trail, id]) + 1))), level.get(id));
      const linked = members.filter(card => links.some(wire => ids.has(wire.from) && ids.has(wire.to) && (wire.from === card.id || wire.to === card.id))).sort((a, b) => depth(a.id) - depth(b.id));
      const rest = members.filter(card => !linked.includes(card)), chain = linked.length ? Math.max(...linked.map(card => depth(card.id))) + 1 : 0, narrow = !!room && room < 1, side = Math.min(narrow ? 1 : 2, rest.length), used = {};
      const cells = [...linked.map(card => { const column = depth(card.id); used[column] = (used[column] || 0) + 1; return {card, column, row: used[column] - 1}; }),
        // A narrow room puts the unlinked sessions under the chain, not beside it.
        ...rest.map((card, index) => ({card, column: (narrow ? 0 : chain) + index % Math.max(1, side), row: (narrow ? Math.max(0, ...Object.values(used)) : 0) + Math.floor(index / Math.max(1, side))}))];
      const tall = 58 + (plain ? 0 : 46) + (members.some(card => card.need) ? 40 : 0) + (members.some(card => card.subtasks) ? 28 : 0), columns = narrow ? Math.max(chain, side) : chain + side, lines = Math.max(1, ...cells.map(cell => cell.row + 1));
      return {key, members, cells, tall, collapsed: folded(key), w: folded(key) ? wide : 48 + columns * wide + (columns - 1) * gapX, h: folded(key) ? 64 : 58 + lines * (tall + gapY)};
    });
    const limit = Math.max(room ? wide + 48 : 1200, Math.sqrt(laid.reduce((sum, group) => sum + group.w * group.h, 0) * (room || 1.6)) * 1.05);
    for (const group of laid) {
      const id = 'group:' + group.key;
      if (room && x > 0 && x + group.w > limit) { x = 0; y += band + 40; band = 0; }  // in a measured room a group that would cross the edge starts the next row
      groups.push({key: group.key, count: group.members.length, collapsed: group.collapsed});
      for (const card of group.members) inside.set(card.id, group.collapsed ? id : card.id);
      nodes.push({id, group: true, collapsed: group.collapsed, title: group.key, count: group.members.length, x, y, w: group.w, h: group.h});
      if (!group.collapsed) for (const {card, column, row} of group.cells) nodes.push({...card, x: x + 24 + column * (wide + gapX), y: y + 46 + row * (group.tall + gapY), w: wide, h: group.tall});
      x += group.w + 40; band = Math.max(band, group.h);
      if (x > limit) { x = 0; y += band + 40; band = 0; }
    }
    // A collapsed group stands in for its members on every wire that crosses its edge.
    const wires = links.map(wire => ({...wire, from: inside.get(wire.from), to: inside.get(wire.to)})).filter(wire => wire.from !== wire.to);
    const layout = JSON.stringify(nodes.map(node => [node.id, node.x, node.y, node.w, node.h]));
    return {params: p, nodes, wires, groups, total: every.length, armed: every.reduce((sum, card) => sum + card.armed, 0), layout,
      signature: layout + JSON.stringify([nodes.map(node => [node.title, node.state, node.agent, node.now, node.steps, node.need, node.subtasks, node.subtasksFolded]), wires, p.card])};
  };
  // Inspector › This task › Session (design sessTabHTML): Done when, who works on it (read only each), inputs from other
  // sessions, run budget. Done when and input links are the session model's (POST /api/session-model); read-only agents and
  // the run budget are the Session node's own values, the same ones its card shows. One value, one owner each.
  function SessionInspector({s, u, task}) {
    const path = api.getSessionPath(), session = s.graph.nodes.find(row => row.fixed && row.type === 'thing.session');
    const [attempt, setAttempt] = React.useState(0), [load, setLoad] = React.useState({status: 'waiting'});
    const stamp = path + ':' + (s.graph.revision || '') + ':' + s.graph.nodes.length + ':' + attempt;
    React.useEffect(() => {
      if (!path) return undefined;
      let current = true; setLoad(held => held.status === 'loaded' ? held : {status: 'waiting'});
      Promise.all([api.readSessionModel(path), api.sessionInputLinks(path)]).then(([row, rows]) => { if (current) setLoad({status: row ? 'loaded' : 'empty', row, links: rows || []}); },
        error => { if (current) setLoad({status: 'error', message: error.message}); });
      return () => { current = false; };
    }, [stamp]);
    if (!path || !session) return null;
    if (load.status === 'waiting') return <section className="v48-session-inspector" aria-label="Session"><h3>Session</h3><p role="status">Reading this session…</p></section>;
    if (load.status === 'error') return <section className="v48-session-inspector" aria-label="Session"><h3>Session</h3><p role="alert">{load.message}</p><button type="button" className="dx-link" onClick={event => executeAction('ui.select', () => setAttempt(value => value + 1), event)}>Retry session</button></section>;
    if (load.status === 'empty') return <section className="v48-session-inspector" aria-label="Session"><h3>Session</h3><p className="muted">This file has no session record yet.</p></section>;
    const model = {state: 'loaded', row: load.row}, links = load.links, setModel = next => setLoad(held => ({...held, row: next.row}));
    const checks = s.graph.nodes.filter(row => !row.fixed && (/check/i.test(row.type) || /check/i.test(row.category || '') || /check/i.test(row.title || '')));
    const done = model.state === 'loaded' ? model.row.doneCheck : null, tries = done?.tries || 0;
    const doneState = !done ? 'Not set' : done.blocked ? 'Blocked · failed 3 of 3' : tries ? 'Failed ' + tries + ' of 3' : 'Not run yet';
    const setDone = node => u.act(() => api.setSessionModel(path, {doneCheck: node ? {node} : null}).then(row => { setModel({state: 'loaded', row}); return row; }));
    const readOnly = session.params.read_only_agents || [], members = (task?.members || []).map(row => row.name).concat(task?.members?.length ? [] : task?.agents || []);
    const setReadOnly = (name, on) => u.act(() => api.setNodeParam(session.id, 'read_only_agents', on ? [...new Set([...readOnly, name])] : readOnly.filter(row => row !== name)));
    const budget = (session.parameterSchema || []).find(row => row.key === 'run_budget');
    if (load.status === 'loaded') return <section className="v48-session-inspector" data-design="inspector.session" aria-label="Session">
      <h3>Session</h3>
      <label className="grid">Done when<select data-design="inspector.session.donewhen" aria-label="Done when" value={done?.node || ''} onChange={event => setDone(event.target.value)}>
        <option value="">{checks.length ? 'Pick a check on this canvas…' : 'Add a Check node to this canvas first'}</option>{checks.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}</select></label>
      <p className="muted" data-design="inspector.session.donestate">{doneState}{done ? ' · three failures in a row block Done' : ''}</p>
      <h4>Who works on it</h4>
      {members.length ? members.map(name => <label key={name} className="v48-session-param"><span>{name}</span><span>Read only <input type="checkbox" aria-label={name + ' read only'} checked={readOnly.includes(name)} onChange={event => setReadOnly(name, event.target.checked)}/></span></label>) : <p className="muted">No agent yet.</p>}
      <h4>Inputs from other sessions</h4>
      {links.length ? links.map(link => <p key={link.source.id + link.output} className="v48-session-param"><span>{link.source.path}<em>{link.output}</em></span><b>{link.state === 'ready' ? 'Ready' : link.state === 'failed' ? 'Failed' : link.state === 'waiting' ? 'Waiting' : 'Source missing'}</b></p>) : <p className="muted">No input links. Wire another session's output into this one to make one.</p>}
      {budget && <label className="grid">Run budget<window.UI.ValueWidget n={session} p={budget} value={session.params.run_budget} u={u}/></label>}
    </section>;
    return null;
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
    const homeRef = React.useRef(homeLayout), homeWrites = React.useRef(Promise.resolve());
    // The map: the sessions read from their owner, the picked card, and the Home changes Undo and Redo step through.
    const [listing, setListing] = React.useState({status: 'waiting', groups: null, error: ''}), [attempt, setAttempt] = React.useState(0), [mapChoices, setMapChoices] = React.useState(null);
    const [room, setRoom] = React.useState(null);  // the map's aspect in quarter steps (view state, never saved)
    const [picked, setPicked] = React.useState(''), [pauseBusy, setPauseBusy] = React.useState(false), [, redraw] = React.useState(0), mapHistory = React.useRef({past: [], future: []});
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
        return api.readHomeLayout().then(result=>{if(active){homeRef.current=result.homeLayout;setHomeLayout(result.homeLayout);setMapChoices(result.homeMap);setRequest(s.tasks?.length?'loaded':'empty');}}).catch(error=>{if(active){setFailure(error.message);setRequest('error');retrySave.current=read;}});
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
    const canvasRef = React.useRef(null);
    const dockRef = React.useRef(null), dockWrites = React.useRef(Promise.resolve()), [mapHost, setMapHost] = React.useState(null);
    const shellRef = React.useRef(null), tabsRef = React.useRef(null), viewsRef = React.useRef(null);
    const [viewsWidth,setViewsWidth]=React.useState(0),[threadWidth,setThreadWidth]=React.useState(0),[besideShown,setBesideShown]=React.useState(false);
    const singleCanvas=Boolean(beside)&&viewsWidth-(face==='split'?Math.max(300,threadWidth)+6:0)<646;
    const [shellWidth, setShellWidth] = React.useState(window.innerWidth - 64), [tabsWidth, setTabsWidth] = React.useState(600);
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
    // Show / Hide Library and Add node keep working: they show or fold the Library panel of the dock.
    // Only his own Show / Hide moves the dock; the dock's state flowing back into libraryOpen moves nothing (opening never writes the layout).
    // The dock owns whether the Library shows; libraryOpen mirrors it and carries his asks. One effect handles both ways, so a value
    // it mirrored is never read back as an ask (two effects did, and a session opening with its thread looped: React error 185).
    const libraryOpenWas = React.useRef(u.libraryOpen), [libraryShown, setLibraryShown] = React.useState(null), libraryShownWas = React.useRef(null);
    React.useLayoutEffect(() => {
      const asked = libraryOpenWas.current !== u.libraryOpen, moved = libraryShownWas.current !== libraryShown;
      libraryOpenWas.current = u.libraryOpen;
      libraryShownWas.current = libraryShown;
      if (asked && fileWorkspace && dockRef.current && dockRef.current.visible('library') !== u.libraryOpen) {
        if (u.libraryOpen) dockRef.current.show('library'); else dockRef.current.hide('library');
      } else if (!asked && moved && libraryShown !== null && libraryShown !== u.libraryOpen) {
        libraryOpenWas.current = libraryShown;
        u.setLibraryOpen(libraryShown);
      }
    }, [u.libraryOpen, libraryShown, fileWorkspace]);
    const [inspection, setInspection] = React.useState({nodeId: null, wireId: null});
    const [propertyTab, setPropertyTab] = React.useState('Task');
    const inspectedNode = s.graph.nodes.find(node => node.id === inspection.nodeId);
    const inspectedWire = s.graph.wires.find(wire => wire.id === inspection.wireId);
    // Stable (it uses only state setters): the canvas is memoized and keeps its render when Home re-renders.
    const inspect = React.useCallback(value => {
      // Decided on the latest inspection, not this render's: a deferred select then clear must end cleared.
      setInspection(old => !value.nodeId&&!value.wireId&&!old.nodeId&&!old.wireId ? old : value);
      // Selecting a node never changes his layout: the Inspector shows the selection where he keeps it, and opens only when he opens it.
      setPropertyTab(value.nodeId || value.wireId ? 'Selection' : 'Task');
    }, []);
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
    React.useEffect(() => {
      if (!fileWorkspace) {u.setSelectedNodeId(null);inspect({nodeId:null,wireId:null});}
    }, [fileWorkspace]);
    const rows = homeRows(s, homeLayout), {tasks, resumed} = rows;
    const vendorLabel=/^[^/\n]{1,40} \/ [^/\n]+ \/ /;
    // What a live session declared it is doing (its Workshop declaration), else the first line of what it last said.
    const liveDoing=agent=>agent?people.whoIs(agent.name).detail||agent.message?.text||'':'';
    // The row names the work; an agent label is never the title. With nothing said yet it is the agent and its project folder.
    const workTitle=t=>{
      const title=String(t.title||'');
      if(title&&!vendorLabel.test(title)&&!vendorLabel.test(String(t.description||'')))return title;
      const text=[t.scope,(t.declarations||[])[0]?.task,...taskMessages(t).map(message=>message.text),liveDoing(t.runtimeAgent)].map(value=>String(value||'').split('\n')[0].trim()).find(value=>value&&!vendorLabel.test(value));
      return text?(text.length>60?text.slice(0,59).trimEnd()+'\u2026':text):humanLabel(t.runtimeAgent?.name||title)||'Untitled session';
    };
    // A live agent with no task (design v61 C2): what it declared it is doing, else the agent and a short id (its folder is the group it sits in).
    const liveName=row=>{const name=String(row.runtimeAgent.name||''),title=workTitle(row);
      return title!==humanLabel(name)?title:[name.split(' / ')[0],name.split(' / ')[2]?.replace(/^session-/,'').slice(0,6)].filter(Boolean).join(' · ');};
    const focus = u.task || homeLayout.resume || s.focusedTask;  // the session he came up from (its card is selected) before Home's saved selection
    const task = fileWorkspace ? tasks.find(t => t.id === u.task) : resumed(focus);
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
    const showCanvas = React.useCallback(() => setFace('canvas'), [setFace]);
    const resetDock = React.useCallback(() => dockRef.current?.reset(), []);
    const choices = window.UI.threadChoices(s, task, [...(people.choices || [])]);
    // An assigned agent that has not joined is listed but cannot receive yet (no handle), like the Workshop To-list.
    for (const name of agents) if (!choices.some(choice => [choice.name,choice.handle,choice.key].includes(name))) choices.push({key:name,handle:undefined,name});
    // In a session the composer talks to this session: All agents is its default, its thread's running chat comes first, BABOOM only by a pick.
    const allAgents = window.UI.sessionAll(choices, agents);
    choices.unshift(allAgents);
    const recipient = to ?? window.UI.threadDefault(s, task) ?? 'session';
    React.useEffect(() => { setTo(null); }, [task?.id]);  // a pick (BABOOM, one agent) belongs to the session it was made in
    const running = (s.hosts || []).filter(h => ['connected', 'listening', 'running'].includes(h.state));
    const footer = (running.length ? running.map(h => [h.name, h.file].filter(Boolean).join(' · ')).join(' · ') : 'No program selected.') + ' Model policy: Free first.';
    const persist = async (write, refusal) => {
      setRequest('waiting');
      let result;
      try { result = await write(); }
      catch (error) { result = {ok: false, error: error instanceof Error ? error.message : String(error)}; }
      if (result == null || result.ok === false) {
        setFailure(result?.error || refusal);
        setRequest('error');
        retrySave.current = () => persist(write, refusal);
        return result;
      }
      setFailure('');
      setRequest(tasks.length ? 'loaded' : 'empty');
      return result;
    };
    const persistWidth = value => persist(() => writeInspectorWidth(value), 'Could not save the Properties width.');
    // Dock layout edits are written in the order they were made; a refused write shows here with Retry.
    const saveDock = layout => { dockWrites.current = dockWrites.current.then(() => persist(() => api.setDockLayout(layout), 'Could not save the panel layout.')); };
    const showWork = async ({task: target, path, nodeId, approvalId}) => {
      // A held step in a file with no task opens that file and its step; only a card with neither opens the approval itself.
      if (!target && path) { const opened = await u.act(() => api.openSession(path)); if (opened && !opened.cancelled) { u.go('canvas'); if (nodeId) { window.UI.centreWhenShown = {nodeId, path}; u.setSelectedNodeId(nodeId); } } return; }
      if (!target) { if (approvalId) u.show('Approve', {id: approvalId}); return; }
      if (target.id !== task?.id) await u.openTaskFile(target.id);
      // Show selects the step and brings it to the centre of the free area (design panTo), once the canvas draws it.
      if (nodeId) { window.UI.centreWhenShown = {nodeId, task: target.id}; u.setSelectedNodeId(nodeId); inspect({nodeId, wireId: null}); return; }
      // A Workshop card's Show of a thread: the one composer now has that task as its context; put the cursor in it.
      focusAsk = {task: target.id, from: target.id === task?.id ? '' : task?.id || ''};   // settled by placeComposer below
    };
    const [layoutName, setLayoutName] = React.useState('Build');
    const syncDock = layout => {  // a report only; the effect above mirrors it
      setLibraryShown(window.UI.dockModel.visible(layout, 'library'));
      setLayoutName(window.UI.dockModel.presetName(layout));  // read from the dock's own layout record, never kept beside it
    };
    // Agents working on other tasks right now (the live agent owner); the toolbar pill lists them and opens their task.
    const workingElsewhere = (s.agentGraph?.sessions || []).filter(agent => agent.status === 'working' && agent.task !== task?.id);
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
      if (recipient === 'session' && !allAgents.handles.length) { sendingRef.current = false; setSending(false); u.setToast('No agent of this session has joined yet. Add one in Session › Who works on it, or pick BABOOM.'); return; }
      const turn = recipient === 'session' ? window.UI.sessionTurn(allAgents, body) : window.UI.chatTurn(choices, recipient, body);
      const prompt = turn.prompt + (files.length ? '\nAttached project file nodes: ' + JSON.stringify(files.map(file=>({id:file.id,path:file.path}))) : '');
      const clearedRevision = (u.composerDraft[draftKey]?.revision || 0) + 1;
      setText('');
      try {
        const result = await u.act(() => api.sendChatTurn({...turn, prompt}, undefined, task && !task.fileOnly ? task.id : undefined));
        if (result != null && turn.agent !== 'BABOOM') setTo(null);   // the thread's chat is now the default (threadDefault)
        if (result == null && turn.resume) setTo(null);               // ended: the default becomes Start again
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
    const openOwner = (t, name=ownerOf(t)) => {
      const agent=[...(s.agents||[]),...(s.providers||[])].find(a=>a.id===name||a.name===name||!name&&a.id===t.owner);
      if(agent)u.show('Agent',{id:agent.id});else u.go('settings/Agents');
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
    const placeComposer = element => {
      if (!element || !focusAsk || (task?.id || '') === focusAsk.from) return;
      if (task?.id === focusAsk.task) element.querySelector('textarea')?.focus();
      focusAsk = null;
    };
    const composer = <div className="v22g-composer-dock" ref={placeComposer} data-composer-task={task?.id || ''}>{composerForm}</div>;
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
    // The canvas gets the same objects while their values hold, so the memoized canvas skips Home's re-renders.
    const doneSteps=resumeSteps.filter(step=>step.state.kind==='done').length, totalSteps=resumeSteps.length;
    const canvasSteps=React.useMemo(()=>({done:doneSteps,total:totalSteps}),[doneSteps,totalSteps]);
    const plannedKey=work.length?'':JSON.stringify(resumeSteps.map(step=>[step.title,step.state.kind,step.state.label]));
    const canvasPlanned=React.useMemo(()=>plannedKey?JSON.parse(plannedKey).map(([title,kind,label])=>({title,kind,label})):null,[plannedKey]);
    const approvalSteps=(s.approvals||[]).filter(card=>card.status==='pending'&&(card.taskId===task?.id||card.work===task?.id||card.taskIds?.includes(task?.id))).filter((card,index,cards)=>cards.findIndex(row=>(row.input_digest||row.id)===(card.input_digest||card.id))===index).map(card=>{
      const refs=card.canvasNodes?.length?card.canvasNodes:[{nodeId:card.nodeId,path:card.path,taskId:card.taskId||card.work}];
      const index=resumeSteps.findIndex(step=>refs.some(ref=>ref.nodeId===step.id&&ref.path===task?.sessionPath&&ref.taskId===task?.id));
      return {card,index};
    });
    const heldIndex=approvalSteps.find(row=>row.index>=0)?.index??-1;
    const currentStep=heldIndex>=0?heldIndex:Math.max(0,resumeSteps.findIndex(step=>step.state.kind!=='done'));
    // A step named like the session says nothing its title does not: the title shows once, with the session's state under it.
    const heading=String(task?.sessionTitle||task?.title||'').trim().toLowerCase();
    const repeats=step=>String(step.title||'').trim().toLowerCase()===heading;
    const stepLine=resumeSteps.length?resumeSteps.every(step=>step.state.kind==='done')?'All '+resumeSteps.length+' steps done':(repeats(resumeSteps[currentStep])?statusText(task?.status):'Step '+(currentStep+1)+' of '+resumeSteps.length+': '+resumeSteps[currentStep].title)+(heldIndex>=0?', waits for you':approvalSteps.length?', session waits for you':''):statusText(task?.status);
    const propertiesPane = <aside className="shared-properties" data-properties-pane="" aria-label="Properties">
      <header className="shared-properties-head">
        <span className="properties-eyebrow">{propertyTab === 'Selection' ? 'PROPERTIES' : propertyTab === 'Automate' ? 'AUTOMATE' : 'THIS TASK'}</span>
        <h2>{propertyTab === 'Selection' ? inspectedNode?.title || task?.title || s.graph.name : task?.title || s.graph.name || 'Task'}</h2>
        <div data-design="inspector.tab" role="tablist" aria-label="Properties view">{[['Task','This task'],['Selection','Properties'],['Automate','Automate']].map(([tab,label]) => <button data-design={'inspector.' + tab.toLowerCase()} type="button" role="tab" aria-selected={propertyTab === tab} key={tab} onClick={() => executeAction('ui.select', () => setPropertyTab(tab))}>{label}</button>)}</div>
      </header>
      <div className="shared-properties-task" hidden={propertyTab !== 'Task'}>{task ? <>{fileWorkspace && propertyTab==='Task' && u.modal?.kind!=='Approve' && approvalSteps.map(({card})=><section key={card.id} className="v48-current-approval"><span>Needs your approval</span><h3>{s.graph.nodes.find(node=>node.id===card.nodeId)?.title || card.title}</h3><window.UI.ApprovalCard id={card.id} compact/>{card.text && <details className="v48-approval-parameters"><summary>All parameters</summary><pre>{card.text}</pre></details>}</section>)}<div className="v48-task-progress" role="progressbar" aria-label="Task progress" aria-valuemin={0} aria-valuemax={resumeSteps.length || 1} aria-valuenow={resumeSteps.filter(step=>step.state.kind==='done').length}>{resumeSteps.map((step,index)=><i key={step.id} data-state={approvalSteps.some(row=>row.index===index)?'awaiting':step.state.kind}/>)}</div><p className="v48-progress-line">{resumeSteps.filter(step=>step.state.kind==='done').length} of {resumeSteps.length} steps done{resumeSteps[currentStep] ? ', now ' + resumeSteps[currentStep].title : ''}</p><label className="grid">Description<textarea data-design="inspector.describe" aria-label="Workflow description" rows={6} key={task.id+':description'} defaultValue={s.graph.documentation || task.scope || task.description || ''} onBlur={e=>{if(e.target.value!==(s.graph.documentation||task.scope||task.description||''))u.act(()=>api.updateGraph(s.graph.id,{documentation:e.target.value}));}} /></label><div className="v48-made"><h3>What it made</h3>{resumeSteps.filter(step=>step.output).map(step=><button type="button" key={step.id} onClick={event=>executeAction('ui.select',()=>inspect({nodeId:step.id,wireId:null}),event)}><span><window.UI.ResultPreview value={step.value??step.preview}/></span><div><b>{step.title}</b><small>{step.output}</small></div></button>)}</div>{fileWorkspace && <SessionInspector s={s} u={u} task={task}/>}</> : <p className="muted">Select a task</p>}</div>
      <div className="shared-properties-task" hidden={propertyTab !== 'Automate'}><h3>Triggers</h3>{s.graph.nodes.filter(row=>row.type.startsWith('trigger.')).map(row=><button type="button" className="dx-link" key={row.id} onClick={event=>executeAction('ui.select',()=>inspect({nodeId:row.id,wireId:null}),event)}>{row.title}</button>)}{task && <button type="button" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>u.act(api.addAutomation),event)}>Add trigger</button>}</div>
      {task && !fileWorkspace && <div className="dx-preview-actions" hidden={propertyTab !== 'Task'}>
        <Btn sm p onClick={() => executeAction('ui.select', () => u.openTaskFile(task.id))}>Open task</Btn>
      </div>}
      <div className="shared-properties-selection" hidden={propertyTab !== 'Selection'}>{inspectedWire ? <window.UI.WireInspector embedded wire={inspectedWire} s={s} u={u} onClose={clearInspection} /> : inspectedNode ? <window.UI.NodeInspector embedded n={inspectedNode} s={s} u={u}>{inspectedNode.fixed && inspectedNode.type === 'thing.workshop' && <ItemList label="Rules" icon="shield" items={rules} onCommit={next => saveSession({rules: next})} />}</window.UI.NodeInspector> : task ? <>{taskParameters}<window.UI.GraphProperties g={s.graph} s={s} u={u}/></> : <p>Select a node or wire.</p>}</div>
    </aside>;
    // The sessions are read from their owner when Home opens and when the set of sessions or a state changes: never on a timer.
    const sessionsStamp = fileWorkspace ? '' : (s.tasks || []).map(t => t.id + ':' + t.status + ':' + (t.sessionPath || '')).join('|') + '#' + (s.graphs || []).length;
    React.useEffect(() => {
      if (fileWorkspace) return undefined;
      let live = true;
      api.listSessionModel().then(result => { if (live) setListing({status: 'loaded', groups: result.groups, error: ''}); })
        .catch(error => { if (live) setListing(current => ({...current, status: 'error', error: error.message})); });
      return () => { live = false; };
    }, [fileWorkspace, attempt, sessionsStamp]);
    // Every map value is a parameter in the Home owner record (settings_owner.home_layout); its choices and defaults come from that owner.
    // A change made elsewhere (the header's counts set the filter) reaches this open Home through the owner's published record.
    const published = fileWorkspace || !Array.isArray(s.homeLayout?.hidden) ? '' : JSON.stringify(s.homeLayout);
    React.useEffect(() => {
      if (published && published !== JSON.stringify(homeRef.current)) { homeRef.current = JSON.parse(published); setHomeLayout(homeRef.current); }
    }, [published]);
    const heldMap = homeLayout.map || {};
    // The map holds work only (design app.js:345): no "Agent sessions" filter; an agent's own chat is under Agents on this PC.
    const sessionKind = s.sessionListFilters?.home === 'workflow' ? 'workflow' : 'all', olderOpen = !(homeLayout.sections || ['Older / archived']).includes('Older / archived');
    const chart = homeMap({listed: listing, rows, hidden: homeLayout.hidden, room, kind: sessionKind, olderOpen, order: homeLayout.order, titleOf: row => row.runtimeAgent ? liveName(row) : workTitle(row),
      params: {...Object.fromEntries(Object.entries(mapChoices || {}).map(([key, options]) => [key, options[0]])), ...heldMap}});
    const writeMap = (next, from, to) => {
      const held = mapHistory.current;
      mapHistory.current = from ? {...held, [from]: held[from].slice(0, -1), [to]: [...held[to], heldMap]} : {past: [...held.past, heldMap], future: []};
      redraw(count => count + 1);
      return saveHome({map: next});
    };
    const changeMap = patch => writeMap(patch ? {...heldMap, ...patch} : {}, '', '');
    const stepMap = (from, to) => mapHistory.current[from].length ? writeMap(mapHistory.current[from].at(-1), from, to) : undefined;
    // The Older section's fold is the list's own record (homeLayout.sections); every other group's is a map parameter.
    const toggleGroup = key => key === 'Older / archived' ? saveHome({sections: olderOpen ? [...(homeLayout.sections || []), key] : (homeLayout.sections || ['Older / archived']).filter(item => item !== key)}) : changeMap({collapsed: chart.params.collapsed.includes(key) ? chart.params.collapsed.filter(item => item !== key) : [...chart.params.collapsed, key]});
    // A card's session: its task, else the task whose session file it is (one file, however its path is spelled).
    const samePath = (a, b) => !!a && !!b && String(a).split('\\').join('/').toLowerCase() === String(b).split('\\').join('/').toLowerCase();
    const cardTask = card => card ? tasks.find(t => card.task && t.id === card.task) || tasks.find(t => samePath(t.sessionPath, card.path)) || null : null;
    // Selection belongs to the Home owner (its resume record and the open session); the layout is never touched by it.
    // Only a card with no task (a live agent, a held run) is held here; 'none' is an explicit empty pick (the pane).
    const pick = card => {
      const id = card ? card.task || cardTask(card)?.id : '';
      setPicked(card ? (id ? '' : card.id) : 'none');
      if (card && !id) return undefined;
      u.setTask(id);
      return saveHome({resume: id});
    };
    const openCard = card => {
      // The card's own task id opens it: never the current selection, and never waiting for the task list to catch up with the map.
      const id = card.task || cardTask(card)?.id;
      if (card.approval) return u.show('Approve', {id: card.approval});
      if (id) return u.openTaskFile(id);
      if (card.path) return u.act(() => api.openSession(card.path)).then(opened => { if (opened && !opened.cancelled) u.go('canvas'); });
      return u.go('settings/Agents');
    };
    // The Library on Home: a node starts a new session named after it, with that node as its first step; never added into the last open session.
    const startSessionWith = item => u.act(async () => {
      const title = item.title || item.name || item.id, created = await api.createTask(title);
      await api.openTaskGraph(created.taskId);
      await api.addNode(item.id);
      await api.listTasks?.();
      setPicked(''); u.setTask(created.taskId);
      u.setToast('New session ' + title + '. Double-click it to work inside.');
      return created;
    });
    const paused = s.desktop?.automationsPaused;
    // Coming up from a session (the path's Home, Esc or the rail) its card is the selected one: the same owner record.
    const pickedCard = picked === 'none' ? null : chart.nodes.find(node => !node.group && (picked ? node.id === picked : !!node.task && node.task === focus)) || null, pickedTask = pickedCard && task && task.id === pickedCard.task;
    React.useEffect(() => { if (!fileWorkspace) homeShown = cardTask(pickedCard)?.id || ''; }, [fileWorkspace, pickedCard?.id]);  // what the rail's Canvas opens from Home
    const resumeView = task ? <section className="resume-task" aria-label="Resumed session"><header data-design="home1.head" className="resume-heading"><div><h1>{task.sessionTitle||task.title}</h1><p>{stepLine}</p></div><div className="resume-people">{agents.map(name=><button type="button" key={name} aria-label={'Open agent '+name} title={name} onClick={()=>executeAction('ui.select',()=>openOwner(task))}><window.UI.Av id={name} size={28}/></button>)}</div><Btn data-design="home1.open" sm onClick={()=>executeAction('ui.select',()=>openTask(task))}>Open its Canvas</Btn></header>
                {!resumeSteps.length&&<section className="resume-summary" aria-label="Session activity"><p>{statusText(task.status)}{ownerOf(task)?' · '+ownerOf(task):''}</p>{outputs.map((output,index)=><pre className="resume-preview" key={index}>{useLabel(output.name||output.excerpt)}</pre>)}{!messages.length&&!outputs.length&&<p>{reasonOf(task)||'No messages yet.'}</p>}</section>}<div className="resume-steps">{resumeSteps.map((step,index)=>repeats(step)&&!step.output&&!approvalSteps.some(row=>row.index===index)?null:<article key={step.id} data-resume-step={step.id} data-state={step.state.kind} data-made={step.output?'':undefined} data-design="home1.step" className="resume-step"><header><span className="resume-step-tile"><Icon name={step.state.kind==='done'?'check':'canvas'} size={14}/></span><b>{step.title}</b></header><p>{step.state.label}{step.output?' · '+step.output:''}</p>{step.output&&<div className="v48-step-preview resume-made"><window.UI.ResultPreview value={step.value??step.preview}/></div>}{approvalSteps.filter(row=>row.index===index).map(({card})=><window.UI.ApprovalCard key={card.id} id={card.id} compact/>)}</article>)}</div>
                {approvalSteps.filter(row=>row.index<0).map(({card})=><window.UI.ApprovalCard key={card.id} id={card.id} compact/>)}
                {messages.length>0&&<section data-design="home1.thread" className="resume-thread" aria-label="Last thread lines"><h2>In the thread</h2>{messages.slice(-3).map(message=><button type="button" key={message.id} onClick={()=>executeAction('ui.select',()=>u.openTaskFile(task.id,'split'))}><window.UI.Av id={message.who||'Agent'} size={24}/><span><b>{message.who}</b> {describe(message.text)}</span></button>)}</section>}
              </section> : null;
    // No session yet: three starts for the composer.
    const zeroState = <section className="resume-zero"><h1>What do you need?</h1>{['Review a drawing set','Check a model against the standard','Collect files for an issue'].map(prompt=><button type="button" key={prompt} onClick={()=>executeAction('ui.select',()=>{const key=JSON.stringify(['home','']);u.setComposerDraft(current=>({...current,[key]:{text:prompt,revision:(current[key]?.revision||0)+1}}));document.querySelector('.global-composer textarea')?.focus();})}><Icon name="brain" size={18}/>{prompt}</button>)}</section>;
    // Hiding and Reset Home are one step each that Undo (the toast's button) takes back exactly.
    const undoable = (text, patch) => { const before = homeRef.current; u.setToast({text, label: 'Undo', open: () => saveHome(before)}); return saveHome(patch); };
    const hideFromHome = t => { setPicked('none'); return undoable((t.sessionTitle || t.title) + ' is hidden from Home. It is still in its file.', {hidden: [...homeLayout.hidden, t.id], resume: ''}); };
    const resetHome = () => { mapHistory.current = {past: [...mapHistory.current.past, heldMap], future: []}; return undoable('Home is back as it was first.', {map: {}, hidden: [], order: [], sections: ['Older / archived'], resume: ''}); };
    // A card dragged on the map: the cards in their dropped order (top to bottom, left to right) are his order of the work.
    const arrange = placed => saveHome({order: [...new Set(placed.map(card => card.task || card.id).filter(id => /^[A-Za-z0-9_-]{1,128}$/.test(id)))]});  // the owner keeps ids only
    const fieldLabels = {group: 'Group by', order: 'Order', card: 'Card', density: 'Density', done: 'Finished sessions', filter: 'Show'};
    const mapInspector = <aside className="shared-properties" data-properties-pane="" data-home-inspector="" aria-label="Properties">
      {pickedCard ? <>
        <header className="shared-properties-head"><span className="properties-eyebrow">SESSION</span><h2>{pickedCard.title}</h2><p className="muted">{[pickedCard.state, pickedCard.project, pickedCard.agent || 'No agent yet'].join(' · ')}</p></header>
        <div className="shared-properties-task">{pickedTask ? resumeView : <Btn sm p onClick={event => executeAction('ui.select', () => openCard(pickedCard), event)}>Open</Btn>}
          {pickedTask && <div className="dx-preview-actions">
            <button type="button" className="dx-quiet" aria-pressed={!!task.homePinned} onClick={event => executeAction('ui.select', () => u.act(() => api.setTaskSession(task.id, {homePinned: !task.homePinned})), event)}>{task.homePinned ? 'Unpin' : 'Pin to Home'}</button>
            <button type="button" className="dx-quiet" onClick={event => executeAction('ui.select', () => hideFromHome(task), event)}>Hide from Home</button>
          </div>}
          {/* A subtask is a task of its own (its own session file) whose row names this task as its parent. */}
          {pickedTask && <form className="dx-preview-actions" data-home-subtask-form="" onSubmit={event => { event.preventDefault(); const form = event.currentTarget, title = String(new FormData(form).get('subtask') || '').trim();
            return title && executeAction('ui.select', () => u.act(async () => { const made = await api.createTask(title, '', '', task.id); form.reset(); u.setToast('Subtask added under ' + (task.sessionTitle || task.title) + '.'); return made; }), event); }}>
            <input name="subtask" aria-label="New subtask" placeholder="New subtask" maxLength={2000} /><button type="submit" className="dx-quiet">Add subtask</button></form>}</div>
      </> : <>
        <header className="shared-properties-head"><span className="properties-eyebrow">HOME</span><h2>Map of the work</h2><p className="muted">Every value here is a parameter of Home. Change one and the map re-arranges. Select a session for its own properties.</p></header>
        <div className="shared-properties-task">
          {Object.entries(mapChoices || {}).map(([key, options]) => <label className="dx-fact" key={key}><span>{fieldLabels[key] || key}</span><select aria-label={fieldLabels[key] || key} value={chart.params[key]} onChange={event => { const value = event.target.value; return executeAction('ui.select', () => changeMap({[key]: value})); }}>{options.map(option => <option key={option}>{option}</option>)}</select></label>)}
          <h3>{chart.params.group === 'Agent' ? 'Agents' : chart.params.group === 'State' ? 'States' : 'Projects'}</h3>
          {chart.groups.map(group => <div className="dx-fact" key={group.key}><span>{group.key} · {group.count}</span><button type="button" className="dx-link" aria-label={(group.collapsed ? 'Expand ' : 'Collapse ') + group.key} onClick={event => executeAction('ui.select', () => toggleGroup(group.key), event)}>{group.collapsed ? 'Expand' : 'Collapse'}</button></div>)}
          {!!homeLayout.hidden.length && <button type="button" className="dx-quiet" onClick={event => executeAction('ui.select', () => saveHome({hidden: []}), event)}>Show {homeLayout.hidden.length} hidden</button>}
          <button type="button" data-design="home1.reset" className="dx-quiet" onClick={event => executeAction('ui.select', () => resetHome(), event)}>Reset Home</button>
        </div>
      </>}
    </aside>;
    if (!Array.isArray(s.tasks)) return <div className="dx-home-root dx-loading-layout" data-home-loading="" aria-busy="true" aria-label="Loading tasks"><div>{[0,1,2].map(row=><div className="dx-skeleton" key={row} />)}</div><aside>{[0,1,2].map(row=><div className="dx-skeleton" key={row} />)}</aside></div>;
    return <div ref={shellRef} className="dx-home-root" data-screen={fileWorkspace ? "task-file" : "home"} data-home-page={fileWorkspace ? undefined : ""} data-start={document.documentElement.dataset.start || 'cold'} onKeyDown={event => { if(event.key === 'Escape' && (inspection.nodeId || inspection.wireId)) {event.preventDefault();event.stopPropagation();clearInspection();} else fileKeys(event);}}>
      {request === 'waiting' ? <p role="status">{fileWorkspace?'Saving':'Loading sessions…'}</p> : null}
      {request === 'error' ? <p role="alert">{failure} <button type="button" onClick={() => executeAction('ui.select', () => retrySave.current())}>Retry</button></p> : null}
      {request === 'loaded' ? <span data-home-ready="" /> : null}
      <div className="dx-home">
        {!fileWorkspace ? <div className="dx-workspace home-map" data-dx="workspace" data-home-map="" data-task-face="canvas">
            <div className="v22g-strip"><div className="v22g-toolbar v48-toolbar home-map-bar" role="toolbar" aria-label="Map of the work">
              {[['Running', rows.running, 'running'], ['Needs you', rows.needsYou, 'need you']].map(([value, count, word]) => <button type="button" className="dx-quiet" key={value} data-home-filter={value} aria-pressed={chart.params.filter === value} title={chart.params.filter === value ? 'Show every session' : 'Show only these sessions'} onClick={event => executeAction('ui.select', () => changeMap({filter: chart.params.filter === value ? 'All' : value}), event)}><b>{count}</b> {word}</button>)}
              {chart.armed > 0 && <button type="button" className="dx-quiet" data-home-pause="" disabled={typeof paused !== 'boolean' || pauseBusy} onClick={event => executeAction('projects.automations.togglePause', {api, u, paused, setBusy: setPauseBusy}, event)}>{paused ? 'Resume all' : 'Pause all'} · {chart.armed} automation{chart.armed === 1 ? '' : 's'} {paused ? 'paused' : 'armed'}</button>}
              <span className="fill" />
              <div className="home-map-kind" role="group" aria-label="Saved document filter">{[['all', 'All'], ['workflow', 'Workflows']].map(([value, label]) => <button type="button" className="dx-quiet" key={value} data-home-kind={value} aria-pressed={sessionKind === value} onClick={event => executeAction('ui.select', () => u.act(() => api.setSessionListFilter('home', value)), event)}>{label}</button>)}</div>
              {[['Undo', 'undo', 'past', 'future'], ['Redo', 'redo', 'future', 'past']].map(([label, icon, from, to]) => <button key={label} type="button" className="dx-quiet" aria-label={label} title={label + ' the last Home change'} disabled={!mapHistory.current[from].length} onClick={event => executeAction('ui.select', () => stepMap(from, to), event)}><Icon name={icon} size={14} /></button>)}
            </div></div>
            <window.UI.Dock face="canvas" rightWidth={inspectorWidth} onRightWidth={persistWidth} onSave={saveDock} onLayout={syncDock} controls={dockRef} onMapHost={setMapHost}
              panels={{workshop: <window.UI.DockWorkshop onShow={showWork} />, library: <window.UI.LibraryShelf onClose={() => u.setLibraryOpen(false)} onAdd={startSessionWith} />, insp: mapInspector}}>
              <div className="dx-col dx-task-column home-map-stage">
                {listing.status === 'error' ? <p role="alert">{listing.error} <button type="button" onClick={() => executeAction('ui.select', () => setAttempt(attempt + 1))}>Retry</button></p> : null}
                {mapChoices && chart.nodes.length ? <window.UI.HomeMap onArrange={arrange} onRoom={(w, h) => setRoom(Math.max(.25, Math.round(w / Math.max(1, h) * 4) / 4))} chart={chart} picked={pickedCard?.id || ""} onPick={pick} onOpen={openCard} onReview={card => u.show('Approve', {id: card.need.approval})} onCollapse={toggleGroup} mapHost={mapHost} />
                  : request === 'empty' ? <main className="resume-main">{zeroState}</main>
                  : mapChoices && listing.status === 'loaded' ? <main className="resume-main">{chart.total ? <section className="resume-zero"><h1>No session matches</h1><button type="button" onClick={event => executeAction('ui.select', () => changeMap({filter: 'All', done: 'Show'}), event)}>Show every session</button></section> : zeroState}</main> : null}
                {/* The composer belongs to the map's own column: between the docks at every width, never over them. */}
                {/* The picked card's session is the composer's recipient (design v61 C1-C3, the Composer's homeSession); none picked: a new session. */}
                <div className="global-composer"><window.UI.Composer compact homeSession={cardTask(pickedCard) || undefined} key={cardTask(pickedCard)?.id || ''} /></div>
              </div>
            </window.UI.Dock>
          </div> :
          <div className="dx-workspace" data-dx="workspace" data-task-face={face}>
            <div className="v22g-strip">
              <div ref={tabsRef} className="v22g-tabs" role="tablist" aria-label="Open tasks">{visibleTabs.map(tab => <div key={tab.id} className="v22g-tab" data-design={tab.id === task?.id ? 'tab.active' : undefined} data-active={tab.id === task?.id} draggable onDragStart={e => {e.dataTransfer.setData('text/archhub-tab', tab.id);e.dataTransfer.setData('task',tab.id);}} onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault();const from=e.dataTransfer.getData('text/archhub-tab'),held=u.canvasTabs;const moved=held.tabs.find(t=>t.id===from);if(!moved||from===tab.id)return;const tabs=held.tabs.filter(t=>t.id!==from);tabs.splice(tabs.findIndex(t=>t.id===tab.id),0,moved);u.act(()=>u.saveCanvasTabs({...held,tabs}));}} onContextMenu={e => {e.preventDefault();u.show('Task tab menu',{id:tab.id});}}>
                <span className="v22g-tab-state" aria-hidden="true" style={{background:tab.id===task?.id && s.graph.nodes.some(node=>node.status==='Running') ? 'var(--color-accent)' : s.approvals.some(card=>card.work===tab.id && card.status==='pending') ? 'var(--color-warn)' : tasks.find(row=>row.id===tab.id)?.status==='DONE' ? 'var(--color-ok)' : 'var(--v22g-ink3)'}}/><button type="button" role="tab" aria-selected={tab.id === task?.id} data-preview={!tab.kept} onClick={event=>executeAction('ui.select',() => {if(tab.id!==task?.id)u.openTaskFile(tab.id);},event)} onDoubleClick={() => u.act(() => u.keepTaskTab(tab.id))}>{tasks.find(t=>t.id===tab.id)?.title || 'Task unavailable'}</button>
                {/* Design tab: how many held runs of this task need him, and a dot while its file saves. */}
                {(count => count > 0 && <span className="v22g-tab-needs" data-design="tab.needs" aria-label={count + (count === 1 ? ' needs you' : ' need you')} title={count + (count === 1 ? ' needs you' : ' need you')}>{count}</span>)((s.approvals || []).filter(card => card.status === 'pending' && [card.work, card.taskId, ...(card.taskIds || [])].includes(tab.id)).length)}
                {tab.id === task?.id && s.sessionDirty && <span className="v22g-tab-saving" data-design="tab.saving" role="status" aria-label="Saving" title="Saving"/>}
                <button type="button" data-design={tab.id === task?.id ? 'tab.close' : undefined} aria-label={'Close ' + (tasks.find(t=>t.id===tab.id)?.title || 'task')} onClick={event=>executeAction('ui.select',() => u.act(() => u.closeTaskTab(tab.id)),event)}><Icon name="close" size={12} /></button>
              </div>)}{hiddenTabs.length>0&&<details className="v22g-tab-overflow"><summary>{hiddenTabs.length} more</summary><div role="menu" aria-label="More open tasks">{hiddenTabs.map(tab=><button key={tab.id} type="button" role="menuitem" onClick={event=>executeAction("ui.select",()=>{event.currentTarget.closest("details").open=false;return u.openTaskFile(tab.id);})}>{tasks.find(t=>t.id===tab.id)?.title || "Task unavailable"}</button>)}</div></details>}<button type="button" className="dx-quiet" data-design="tab.add" aria-label="Open another task" title="Open another task" onClick={() => u.show('Open tasks')}>+</button></div>
              <div className="v22g-toolbar v48-toolbar"><div className="v48-toolbar-agents">{agents.slice(0,3).map(name=><button type="button" className="button-reset" key={name} title={name} aria-label={'Open agent '+name} onClick={event=>executeAction('ui.select',()=>openOwner(task,name),event)}><window.UI.Av id={name} size={28}/></button>)}{agents.length>3 && <button type="button" className="dx-quiet" aria-label="All session agents" onClick={event=>executeAction('ui.select',()=>u.show('Task details',{id:task.id}),event)}>+{agents.length-3}</button>}
                {workingElsewhere.length>0 && <details className="v22g-tab-overflow"><summary data-design="toolbar.agents.more" aria-label={workingElsewhere.length+' more agent'+(workingElsewhere.length>1?'s':'')+' working'} title="Agents working on other tasks">+{workingElsewhere.length}</summary><div role="menu" aria-label="Agents working on other tasks">{workingElsewhere.map(agent=><button key={agent.id} type="button" role="menuitem" onClick={event=>executeAction('ui.select',()=>{event.currentTarget.closest('details').open=false;return agent.task?u.openTaskFile(agent.task):u.go('settings/Agents');},event)}>{[agent.name,'working',tasks.find(row=>row.id===agent.task)?.title].filter(Boolean).join(' · ')}</button>)}</div></details>}</div><div className="v48-save"><button type="button" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>saveFile(false),event)}><Icon name="export" size={13}/>Save</button><details><summary aria-label="Save menu">↓</summary><div className="v48-save-menu">{[['Save as…',()=>saveFile(true)],['Save as skill…',()=>u.show('Save skill')]].map(([label,run])=><button type="button" key={label} onClick={event=>executeAction('ui.select',()=>{event.currentTarget.closest('details').open=false;return run();},event)}>{label}</button>)}</div></details></div><button type="button" className="dx-quiet v48-secondary" onClick={event=>executeAction('ui.select',()=>{setPropertyTab('Automate');dockRef.current?.show('insp');},event)}><Icon name="clock" size={13}/>Automate</button><button type="button" data-design="toolbar.run" className="dx-quiet dx-primary-run" disabled={singleCanvas&&besideShown} onClick={event=>executeAction('ui.select',() => u.act(async () => {await u.keepTaskTab(task.id);return canvasRef.current?.run();}),event)}>Run all</button>{[['Undo','undo',()=>u.act(api.undo)],['Redo','redo',()=>u.act(api.redo)],['Tidy up','arrange',()=>canvasRef.current?.arrange()]].map(([label,icon,run])=><button key={label} type="button" className="dx-quiet v48-secondary" aria-label={label} title={label} onClick={event=>executeAction('ui.select',run,event)}><Icon name={icon} size={14}/></button>)}<button type="button" data-design="toolbar.layout" className="dx-quiet v48-secondary" aria-label={'Layout: '+layoutName} title={'Layout: '+layoutName+'. Click for Build: Workshop, Library and Map on the left, the Inspector on the right'} aria-pressed={layoutName==='Build'} onClick={event=>executeAction('ui.select',()=>dockRef.current?.reset(),event)}><Icon name="library" size={14}/></button><button type="button" data-design="toolbar.thread" className="dx-quiet v22g-foldable" aria-label="Thread" aria-pressed={face === 'split'} onClick={event=>executeAction('ui.select',() => setFace(face === 'split' ? 'canvas' : 'split'),event)}><Icon name="workshop" size={14} /></button><button type="button" data-design="toolbar.more" className="dx-quiet" aria-label="More canvas actions" onClick={event=>executeAction('ui.select',() => canvasRef.current?.more(),event)}>…</button></div>
            </div>
            <window.UI.Dock face={face} rightWidth={inspectorWidth} onRightWidth={persistWidth} onSave={saveDock} onLayout={syncDock} controls={dockRef} onMapHost={setMapHost}
              panels={{workshop: <window.UI.DockWorkshop onShow={showWork} />, library: <window.UI.LibraryShelf onClose={() => u.setLibraryOpen(false)} />, insp: propertiesPane}}>
              <div className="dx-col dx-task-column">
                <div className="dx-surface-body"><div className="v22g-views-frame" ref={viewsRef}>{singleCanvas&&<div className="v22g-canvas-switch" role="group" aria-label="Visible canvas"><button type="button" aria-pressed={!besideShown} onClick={()=>executeAction('ui.select',()=>setBesideShown(false))}>{task?.title}</button><button type="button" aria-pressed={besideShown} onClick={()=>executeAction('ui.select',()=>setBesideShown(true))}>{s.tasks.find(row=>row.id===beside)?.title}</button></div>}<Group className="v22g-views" orientation="horizontal">{(!singleCanvas||!besideShown)&&<Column id="task-canvas" minSize={320}><div className="v22g-canvas" data-design="canvas.stage"><window.UI.Canvas active embedded externalInspector steps={canvasSteps} planned={canvasPlanned} occludedWidth={threadRail&&threadPeek?380:0} controlsRef={canvasRef} onInspect={inspect} onHandoff={showCanvas} docked mapHost={mapHost} onResetDock={resetDock} /></div></Column>}{beside&&(!singleCanvas||besideShown) && <>{!singleCanvas&&<Separator className="pane-splitter" aria-label="Resize session split" />}<Column id="beside-canvas" minSize={320}><div className="v22g-beside"><header className="spread"><button type="button" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>u.openTaskFile(beside),event)}>{s.tasks.find(row=>row.id===beside)?.title || 'Task'} · Open</button><button type="button" className="dx-quiet" aria-label="Close split" onClick={event=>executeAction('ui.select',()=>u.act(()=>u.saveCanvasTabs({...u.canvasTabs,split:''})),event)}>×</button></header>{previewError ? <p role="alert">{previewError}</p> : preview ? <window.UI.Canvas key={beside} active embedded externalInspector preview={preview} onActivate={()=>u.openTaskFile(beside)} /> : <p role="status">Loading task…</p>}</div></Column></>}{face === 'split' && <><Separator className="pane-splitter" aria-label="Resize thread" /><Column id="task-thread" panelRef={threadRef} collapsible collapsedSize={48} onResize={size=>{setThreadRail(size.inPixels<=49);setThreadWidth(size.inPixels);}} defaultSize="44%" minSize={300}>{threadRail&&<button type="button" className="canvas-pane-rail" aria-label="Open Thread" onClick={()=>executeAction("ui.select",()=>setThreadPeek(!threadPeek))}>Thread</button>}<div hidden={threadRail&&!threadPeek} data-thread-peek={threadRail&&threadPeek||undefined} className="dx-main v22g-thread" data-dx="main" data-home-face="split">
                  <div className="dx-thread-layout"><aside className="dx-threads" aria-label="Threads"><header><h2>Threads</h2><button type="button" className="dx-quiet" onClick={() => executeAction('ui.select', () => u.go('home'))}>All tasks</button></header>{tasks.map(t => <button type="button" className="dx-thread-row" key={t.id} aria-selected={t.id === task?.id} onClick={() => executeAction('ui.select', () => u.openTaskFile(t.id, 'workshop'))}><b>{t.title}</b>{ownerOf(t) ? <span>You → {ownerOf(t)}</span> : null}<span>{window.UI.taskRowReason(t) || statusText(t.status)}{reasonOf(t) ? ' · ' + reasonOf(t) : ''}</span></button>)}</aside>
                  <div className="dx-work-scroll">
                  <div className="dx-mid" data-plan={plan.length ? 'shown' : 'hidden'}>
                    <div className="dx-stage">
                    <section className="dx-talk dx-thread" data-dx="conversation" aria-label="Conversation">
                      <div className="spread v22g-thread-head"><div><b>Thread</b><p>{ownerOf(task) || task?.title} · {statusText(task?.status)}</p></div><button type="button" data-design="thread.close" className="dx-quiet" aria-label="Close thread" onClick={event=>executeAction('ui.select',()=>{setThreadPeek(false);setFace('canvas');},event)}><Icon name="close" size={14}/></button></div><button type="button" data-design="thread.rules" className="dx-quiet" onClick={event=>executeAction('ui.select',()=>{const node=s.graph.nodes.find(row=>row.fixed && row.type==='thing.workshop');if(node){inspect({nodeId:node.id});dockRef.current?.show('insp');}},event)}>Rules · {rules.length ? rules.join(' · ') : 'No rules set'}</button><p className="dx-thread-status">{ownerOf(task) && <span>You → {ownerOf(task)}</span>}<span>{statusText(task?.status)}</span></p>
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
                      {/* Design: a held step of this task is answered inside the thread too: Review shows the step, Ask why asks the agent in the composer. */}
                      {approvalSteps.map(({card}) => { const step = s.graph.nodes.find(node => node.id === card.nodeId)?.title || card.title;
                        return <section key={card.id} className="v48-thread-approval" data-design="thread.approval" data-approval={card.id}><span>Needs your approval</span><b>{step}</b>
                          <p>{card.who ? card.who + ' asked' : 'Asked'}{card.summary ? ' · ' + card.summary : ''}</p>
                          <div className="flex"><button type="button" className="dx-quiet" onClick={event => executeAction('ui.select', () => showWork({task, nodeId: card.nodeId, approvalId: card.id}), event)}>Review on the node</button>
                            <button type="button" className="dx-primary-run" onClick={event => executeAction('ui.select', () => u.act(() => api.approve(card.id)), event)}>Approve</button>
                            <button type="button" className="dx-quiet" onClick={event => executeAction('ui.select', () => setText('Why do you need to run ' + step + '?'), event)}>Ask why</button>
                            <button type="button" className="dx-quiet" onClick={event => executeAction('ui.select', () => u.act(() => api.decline(card.id)), event)}>Reject</button></div></section>; })}
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
              </div>
            </window.UI.Dock>
          </div>
        }
      </div>
      {fileWorkspace && composer}
    </div>;
  }
  window.UI.Home = Home;
  window.UI.homeShown = () => homeShown;  // the session Home shows selected now (its own optimistic list), '' if none
  window.UI.homeRows = homeRows;
  window.UI.homeMap = homeMap;
  window.UI.Sheet = Sheet;
  window.UI.homeListSame = sameList;
  window.UI.homeCommitList = commitList;
  window.UI.homeDescribe = describe;
  window.UI.homeStepOf = stepOf;
  window.UI.homeDestination = homeDestination;
  window.UI.homeTaskMessages = taskMessages;
  window.UI.homeMiddle = middle;
})();
