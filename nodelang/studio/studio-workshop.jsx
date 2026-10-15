// WORKSHOP-72 PASS2: DSYS-077 window; 074/075 behavior with the shipped v3 skin.
// Tasks/messages/approvals are projections of the existing authority; DSYS-078 uses the same selector.
(() => {
const W = window.AH;
const derive = build => window.ArchHubTheme ? window.ArchHubTheme.derive(build) : build(W);

// Projects stays hidden until the project backend lands. Legacy "tasks" opens the Board.


// Conversation retention. After 20 idle days a conversation's messages move to
// a file in the user's data folder; this notice says so on the conversation and
// hands the archive back. It reads with a GET, so looking never delays retention.


// ═══════════════════════════════ LIVE SEAM ═══════════════════════════════
// Work review and Canvas share the authenticated view's durable graph selection.
// Programs this task may use: saved as requirements.hosts through the existing
// Work creation and configuration paths. None is ever chosen by default.
const WORKSHOP_PROGRAMS = [{id:'revit', label:'Revit'}, {id:'acad', label:'AutoCAD'},
  {id:'max', label:'3ds Max'}, {id:'rhino', label:'Rhino'}, {id:'blender', label:'Blender'}];
const WorkshopPrograms = {
  LIST:WORKSHOP_PROGRAMS,
  from:requirements => WORKSHOP_PROGRAMS.map(program => program.id)
    .filter(id => Array.isArray(requirements?.hosts) && requirements.hosts.includes(id)),
  // The next requirements object with only the programs replaced, or null when nothing changes.
  change:(requirements, selected) => {
    const next = WORKSHOP_PROGRAMS.map(program => program.id).filter(id => selected.includes(id));
    if (JSON.stringify(next) === JSON.stringify(WorkshopPrograms.from(requirements)) &&
        (next.length || !Array.isArray(requirements?.hosts))) return null;
    const out = {...(requirements || {})};
    if (next.length) out.hosts = next; else delete out.hosts;
    return out;
  },
};
window.WorkshopPrograms = WorkshopPrograms;


const workshopProjectedNodes = state => {
  const nodes = state?.topology?.graph?.nodes ?? state?.topology?.canvas?.nodes ?? state?.graph?.nodes ?? state?.canvas?.nodes;
  const drawn = Array.isArray(nodes) ? nodes : [];
  // Work lives in the Workshop: the product canvas does not draw it, and its full projection still names it here.
  const hidden = state?.topology?.canvas?.hidden_work;
  if (!Array.isArray(hidden) || !hidden.length) return drawn;
  const ids = new Set(drawn.map(node => node?.id));
  return [...drawn, ...hidden.filter(row => typeof row?.id === 'string' && !ids.has(row.id))];
};
const workshopProjectedWires = state => {
  const wires = state?.topology?.graph?.wires ?? state?.graph?.wires;
  return Array.isArray(wires) ? wires : [];
};


// Workshop task cards read from the transcript only: a message that names a Work id is an event of that
// Work, and every event of one Work folds into one card at the place its first event appeared. The card's
// state is the verb of its latest event. No progress, tool count or task id is authored.
const wsSender = message => typeof message?.relayed_from === 'string' ? message.relayed_from : message?.sender_root;
const wsText = message => typeof message?.relayed_from === 'string' && typeof message.agent_text === 'string'
  ? message.agent_text : String(message?.body || '');
// An agent's reply that carries a workflow plan (a fenced JSON block with "actions"): its prose and
// the plan's steps, so the thread shows the plan as steps, never as a JSON dump (design audit gap 1).
const wsPlanReply = text => {
  const found = /```(?:json)?\s*\n([\s\S]*?)\n```/.exec(String(text || ''));
  if (!found) return null;
  let plan = null;
  try { plan = JSON.parse(found[1]); } catch (_) { return null; }
  if (!plan || typeof plan !== 'object' || !Array.isArray(plan.actions)) return null;
  const steps = plan.actions.filter(row => row && row.op === 'node')
    .map(row => ({id:String(row.root || row.id || row.ref || row.title || row.engine || 'step'),
      t:String(row.title || row.engine || 'step'), p:String(row.engine || ''), state:String(row.state || row.status || 'open')}));
  const prose = (String(text).slice(0, found.index) + String(text).slice(found.index + found[0].length)).trim();
  return {prose, steps, title:typeof plan.title === 'string' ? plan.title : '', raw:found[1]};
};
const workshopTaskItems = window.ARCHHUB_WORKSHOP_TASK_SOURCE.items;
// One participant tone for the agents rail and the transcript avatars: palette tokens only, chosen from
// the participant root so the same agent keeps its colour.

const wsSeconds = value => {
  const number = typeof value === 'string' ? Date.parse(value) / 1000 : value;
  return !Number.isFinite(number) || number <= 0 ? null : number > 1e12 ? number / 1000 : number;
};
const wsClockText = (value, seconds) => {
  const at = wsSeconds(value); if (at === null) return '';
  const d = new Date(at * 1000), p = n => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes()) + (seconds ? ':' + p(d.getSeconds()) : '');
};

// An avatar's initial is the name's first whole character: charAt(0) splits an emoji into a lone surrogate.
const wsInitial = (name, fallback) => (Array.from(String(name || '').trim())[0] || fallback).toUpperCase();
// Counted and cut in code points: a cut never splits a supplementary character (an emoji) into a lone surrogate.


const wsRouteLabel = route => String(route || '').replace(/^openrouter\//, '').replace(/^lmstudio\//, 'LM Studio · ').replace(/^ollama\//, 'Ollama · ');


const wsTranscript = (state, descriptor) => {
  const held = state?.workshop;
  const graphOk = held?.graph_id === undefined || held.graph_id === state?.canvas?.graph_id;
  const scopeOk = held?.scope_root === undefined || held.scope_root === state?.canvas?.root;
  return held?.root === descriptor?.root && graphOk && scopeOk ? held : null;
};
const wsNative = (state,descriptor) => window.ARCHHUB_WORKSHOP_TASK_SOURCE.native(state,descriptor?.root);


// Shared by the rail and the view, which render in two different component trees (the design's
// subscribe store): saved agent connections and Session Link disconnect outcomes.


// Only a confirmed remote revocation reads as disconnected; everything else says what is known.


// Agents: the transcript's agent participants in the design's rail-row shape.

// The rail's default list: agents that are here now (and you). Disconnected sessions stay in the
// graph and in the transcript; they are listed only when asked for.


// The window lists individual sessions. App grouping remains the Connections lens's job.


// Address only identities advertised by the existing transport. Never guess a recipient.
const wsResolveAddress = (body, fallback, rows) => {
  let message = String(body || '').trim(), target = fallback || '';
  const aliases = [{label:'all', target:''}, ...rows].filter(row => row.label).sort((a,b) => b.label.length - a.label.length);
  const expression = label => new RegExp('(^|\\s)@' + String(label).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=\\s|$)', 'ig');
  const found = aliases.filter(row => expression(row.label).test(message));
  if (new Set(found.map(row => row.target)).size > 1) throw new Error('Address one agent or @all in each message.');
  if (found.length) {
    target = found[0].target;
    for (const row of found) message = message.replace(expression(row.label), '$1').trim();
  }
  if (/(^|\s)@\S+/.test(message)) throw new Error('Choose an agent listed in this Workshop.');
  if (!message) throw new Error('Enter a message after the address.');
  return {target, message};
};

const wsParam = (node, pattern) => {
  const row = (node?.params || []).find(param => pattern.test(String(param.k || '')));
  return row && row.v != null && String(row.v).trim() ? String(row.v) : '';
};
// Tasks: Work named in the transcript (workshopTaskItems) plus the native Work status.
// ── agent Work proposals as the design's task cards (design studio-workshop.jsx:221-223,
// :404-410): the decision sits inline on the card, first choice primary; the lead reads
// "Approved: …" or "Declined: …" from persisted graph state. An agent proposes;
// nothing exists or is granted until the founder approves (nodelang/work_proposals.py).
const {proposal:wsProposalTask,isProposal:isWorkProposal} = window.ARCHHUB_WORKSHOP_TASK_SOURCE;
// The founder's Approve: read the proposals (the operation status first when it is not
// held yet), then bind exactly this one through the existing bind.
const approveWorkProposal = async (authority, root, messageId) => {
  // A status read the view starts meanwhile replaces the held status; the read then refuses
  // as "changed while reading" and is simply read again against the new status.
  const read = async (left = 3) => {
    try { return await authority.readWorkProposals(root); }
    catch (failure) {
      const message = String(failure?.message);
      if (left > 0 && /operation status first/.test(message)) { await authority.refreshNativeWork(root, null); return read(left - 1); }
      if (left > 0 && /changed while reading/.test(message)) return read(left - 1);
      throw failure;
    }
  };
  const row = (await read()).rows.find(item => item.message_id === messageId);
  if (!row) throw new Error('This proposal is not in the loaded messages; scroll to it and approve again.');
  if (row.problem) throw new Error(row.problem);
  if (row.work_root) return {work_root:row.work_root};
  const result = await authority.bindWorkProposals(root, [row]);
  return {work_root:result.bound[0].work_root};
};
const declineWorkProposal = async (authority, root, messageId) => {
  if (!authority || typeof authority.readWorkProposals !== 'function' || typeof authority.declineWorkProposals !== 'function') {
    throw new Error('This Workshop cannot decline proposals yet.');
  }
  let read = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try { read = await authority.readWorkProposals(root); break; }
    catch (error) {
      if (/operation status first/i.test(error?.message || '')) {
        if (typeof authority.refreshNativeWork === 'function') await authority.refreshNativeWork(root, null);
        continue;
      }
      if (/changed while reading/i.test(error?.message || '') && attempt < 2) continue;
      throw error;
    }
  }
  const row = (read?.rows || []).find(item => item.message_id === messageId);
  if (!row) throw new Error('Proposal ' + messageId + ' is not in the loaded messages.');
  if (row.work_root) return {declined:null, work_root:row.work_root};
  if (row.declined) return {declined:row.declined};
  const result = await authority.declineWorkProposals(root, [row]);
  return {declined:result.declined[0]};
};
const wsTasks = window.ARCHHUB_WORKSHOP_TASK_SOURCE.tasks;


const WS_S1_FRAME_W = 1496;
const WS_S1_RAIL_W = 44;
const WS_S1_LEFT_W = 248;
const WS_S1_INSPECTOR_W = 320;
const WS_S1_CANVAS_VIEWPORT_W = WS_S1_FRAME_W - WS_S1_RAIL_W - WS_S1_LEFT_W - WS_S1_INSPECTOR_W;


const WS_WATCH_TABLE_VISIBLE_ROWS = 6;
const WS_WATCH_TABLE_ROW_H = 24;
const WS_WATCH_TABLE_H = WS_WATCH_TABLE_VISIBLE_ROWS * WS_WATCH_TABLE_ROW_H;


// Flow: the projected topology, laid into the design's three columns by wire depth.


// ═════════════════════════════ END LIVE SEAM ═════════════════════════════

const ST = derive(W => ({
  working:  { col:W.accent, label:'WORKING', pulse:true },
  waiting:  { col:W.warn,   label:'WAITING FOR INPUT' },
  available:{ col:W.ok,     label:'AVAILABLE' },
  off:      { col:W.err,    label:'DISCONNECTED' },
  stale:    { col:W.inkMuted, label:'NO RECENT ACTIVITY' },
  unverified:{ col:W.inkMuted, label:'CONNECTION UNVERIFIED' },
}));

// Tints and hairlines are DERIVED from the palette (token + alpha), never new hexes —
// tokens.jsx is the only place a colour is defined.
const CHIP = derive(W => ({
  block:{ bg:W.err + '1f',  c:W.err,      l:'NEEDS YOU' },
  run:  { bg:W.warn + '1f', c:W.warn,     l:'RUNNING' },
  paused:{ bg:W.err + '14',  c:W.err,      l:'PAUSED' },
  review:{ bg:W.cyan + '1c', c:W.cyan,    l:'SUBMITTED' },
  done: { bg:W.ok + '1c',   c:W.ok,       l:'DELIVERED' },
  open: { bg:W.bgSoft,      c:W.inkMuted, l:'OPEN' },
  queued:{ bg:W.bgSoft,     c:W.inkMuted, l:'QUEUED' },
  BLOCK_EDGE:W.err + '66',   // blocked border
  WIRE:W.inkMuted + '55',    // idle wire
}));

// ── atoms ──
const Av = ({ a, s=22 }) => (
  <span aria-hidden="true" title={a.name} style={{ width:s, height:s, borderRadius: a.round ? '50%' : Math.round(s/4), background:a.col,
    color: a.round ? W.onUserAv : (a.status==='off' ? W.inkSoft : (a.ink || W.onFill)),
    display:'grid', placeItems:'center', fontSize:Math.round(s*0.45), fontWeight:600, flex:'none',
    fontFamily:W.sans, opacity: a.status==='off' ? .6 : 1 }}>{a.ini}</span>
);

const Lbl = ({ children, c }) => <span style={{ fontFamily:W.sans, fontSize:W.fs.label.sz, fontWeight:W.fs.label.wt, letterSpacing:W.fs.label.letter, color: c || W.inkSoft }}>{children}</span>;


// Disabled controls use a dashed border, never alpha (design DECISIONS.md).

// Compact icon button — glyph + tooltip. Icons carry the repeated actions so the surface
// does not fill with labelled buttons; words stay for decisions only.


const wsCleanTitle = (value, fallback) => {
  const text = String(value || '').trim();
  if (!text || /^(block|done|live|run|open|queued|idle)$/i.test(text)) return fallback;
  return text || fallback;
};


// ── task card: the container for its own thread ──


// ── agents rail (replaces the Nodes Library while Workshop is open) ──


// ── live graph pane (preset C) ── geometry is expressed in PERCENT of the pane, so it fits
// the narrow in-app column and a wide window alike with no measurement step to go wrong.
// Columns: left 4/38/72 %, width 24% → right edges 28/62/96 %.
const COL_L = c => 4 + c * 34, COL_R = c => COL_L(c) + 24;


// ── assign (design 67caa887: W1 pick · W2 review · W3 assigned · W5 refusals) ──
// Candidates are the rail's own agents; only a verified one (a live, renewed connection
// attached to this Workshop) can be picked. There is no free-text field: nothing here
// starts, enrols or names a session. The server re-checks the connection at commit.
const wsStatusText = {available:'AVAILABLE', working:'WORKING', waiting:'WAITING FOR INPUT',
  stale:'NO RECENT ACTIVITY', unverified:'CONNECTION UNVERIFIED', off:'DISCONNECTED'};
const wsNewAssignmentId = () => 'app:workshop-assignment:' + window.crypto.randomUUID().replaceAll('-', '');
// An assignment whose reply was lost, kept per room+Work until the projection or a retry
// settles it: Back, another task or closing the panel never forgets its assignment_id.
const wsPendingAssignments = new Map();
const wsPendingKey = (room, work) => String(room) + '\u0000' + String(work);
const wsLostReplyText = 'The last assignment reply was lost. Retry sends the same assignment id, so it cannot assign twice.';
const AssignSection = ({ task, room, agents, assign, assignments = [] }) => {
  const key = wsPendingKey(room, task.work);
  const held = assignments.find(row => row && row.work === task.work) || null;   // the graph's answer
  // A fresh mount starts from any unconfirmed request for this Work, exactly as a
  // Work switch does: the pending record is the one truth for what is shown AND sent.
  const [pick, setPick] = React.useState(() => wsPendingAssignments.get(key)?.agent || null);
  const [phase, setPhase] = React.useState(() => wsPendingAssignments.has(key) ? 'review' : 'pick');   // pick · review · sending
  const [notice, setNotice] = React.useState(() => wsPendingAssignments.has(key)
    ? {kind:'uncertain', text:wsLostReplyText} : null);      // {kind:'refused'|'uncertain', text}
  const shown = React.useRef(key);                           // the room+Work this panel shows now
  const alive = React.useRef(true);
  React.useEffect(() => () => { alive.current = false; }, []);
  // Another Work: reset DURING render, so no frame ever shows the previous Work's
  // review or notice (an effect would run after that stale frame was drawn).
  const [shownKey, setShownKey] = React.useState(key);
  if (shownKey !== key) {
    const pending = wsPendingAssignments.get(key);
    shown.current = key;
    setShownKey(key);
    setPick(pending ? pending.agent : null); setPhase(pending ? 'review' : 'pick');
    setNotice(pending ? {kind:'uncertain', text:wsLostReplyText} : null);
  }
  React.useEffect(() => {
    // The projection settles an uncertain request: assigned (by its id or otherwise) ends it.
    const pending = wsPendingAssignments.get(key);
    if (pending && held) { wsPendingAssignments.delete(key); if (alive.current && shown.current === key) { setNotice(null); setPhase('pick'); } }
  }, [key, held && held.assignment]);
  const candidates = agents.filter(a => !a.self);
  const chosen = candidates.find(a => a.id === pick) || null;
  const send = async () => {
    const target = key, work = task.work;
    let pending = wsPendingAssignments.get(target);
    // A pending (unconfirmed) request is retried exactly as it was: same agent, same id.
    if (!assign || (!pending && !chosen)) return;
    const wasPending = Boolean(pending);
    if (!pending) pending = {agent:chosen.id, id:wsNewAssignmentId()};
    wsPendingAssignments.set(target, pending);
    setPhase('sending'); setNotice(null);
    const current = () => alive.current && shown.current === target;   // a late reply never touches another Work
    try {
      await assign({work, agent_session:pending.agent, assignment_id:pending.id});
      wsPendingAssignments.delete(target);
      if (current()) { setPhase('pick'); setPick(null); }
    } catch (error) {
      // Only the server's explicit refusal of THIS id settles a pending request (the
      // projection settles it too, above). A lost reply keeps it; so does any failure
      // before the POST when an earlier attempt of this id may already have landed.
      if (error.assignmentUncertain || (wasPending && !error.assignmentRefused)) {
        if (current()) {
          setNotice({kind:'uncertain', text:error.assignmentPreflight
            ? 'Nothing was sent: ' + error.message + ' The earlier assignment is still unconfirmed; retry sends the same assignment id.'
            : error.message});
          setPhase('review');
        }
      } else {
        wsPendingAssignments.delete(target);
        if (current()) { setNotice({kind:'refused', text:error.message}); setPhase('pick'); }
      }
    }
  };
  if (held) {
    const owner = agents.find(a => a.id === held.agent_session) || {id:held.agent_session, name:held.agent_session,
      col:W.bgSoft, ink:W.ink, ini:'?'};
    return (
      <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}` }} aria-label="Assigned agent">
        <Lbl>ASSIGNED TO</Lbl>
        <div style={{ display:'flex', gap:8, alignItems:'center', marginTop:8, padding:'7px 8px', border:`1px solid ${W.line}`, borderRadius:8 }}>
          <Av a={owner} s={22}/>
          <div style={{ minWidth:0 }}><div style={{ fontSize:12.5, overflowWrap:'anywhere' }}>{owner.name}</div>
            <div style={{ fontFamily:W.mono, fontSize:W.fs.dataSm.sz, color:W.inkSoft }}>assigned · it claims the Work itself</div></div>
        </div>
        <div style={{ fontSize:11.5, lineHeight:1.5, color:W.inkSoft, marginTop:8 }}>One agent at a time: this Work cannot take another assignee while this one holds it.</div>
      </div>);
  }
  // While a request is unconfirmed, its record decides everything on screen: the
  // review names ITS agent (never a later pick), the pick list is not offered, and
  // send() retries that same record -- what is shown is what is dispatched.
  const pendingNow = wsPendingAssignments.get(key);
  const shownPhase = pendingNow && phase === 'pick' ? 'review' : phase;
  const shownNotice = notice || (pendingNow && shownPhase !== 'sending' ? {kind:'uncertain', text:wsLostReplyText} : null);
  const reviewAgent = pendingNow
    ? (candidates.find(a => a.id === pendingNow.agent) || {id:pendingNow.agent, name:pendingNow.agent})
    : chosen;
  return (
    <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}` }} aria-label="Assign this Work">
      <Lbl>{shownPhase === 'pick' ? 'ASSIGNED TO · nobody' : 'ASSIGN · REVIEW'}</Lbl>
      {shownNotice && <div role="alert" style={{ marginTop:8, padding:'8px 10px', borderRadius:8,
          border:`1px solid ${shownNotice.kind === 'refused' ? W.err : W.warn}` }}>
        <Lbl c={shownNotice.kind === 'refused' ? W.err : W.warn}>{shownNotice.kind === 'refused' ? 'NOT ASSIGNED' : 'NOT CONFIRMED'}</Lbl>
        <div style={{ fontSize:11.5, lineHeight:1.5, color:W.inkSoft, marginTop:4 }}>{shownNotice.text}</div>
      </div>}
      {shownPhase === 'pick' ? <>
        <div style={{ fontSize:11.5, lineHeight:1.5, color:W.inkSoft, marginTop:6 }}>Pick an agent that is running now. It gets this Work as a task to claim; assigning grants it nothing else.</div>
        <div role="radiogroup" aria-label="Running agents" style={{ marginTop:8, display:'grid', gap:4 }}>
          {candidates.length ? candidates.map(a => (
            <button key={a.id} type="button" role="radio" aria-checked={pick === a.id} disabled={!a.verified}
              onClick={() => setPick(a.id)}
              style={{ display:'flex', gap:8, alignItems:'center', textAlign:'left', padding:'6px 8px', borderRadius:8,
                border:`1px solid ${pick === a.id ? W.accent : W.line}`, background:'transparent', color:W.ink,
                opacity:a.verified ? 1 : 0.55, cursor:a.verified ? 'pointer' : 'not-allowed' }}>
              <Av a={a} s={20}/>
              <span style={{ flex:1, minWidth:0 }}><span style={{ display:'block', fontSize:12 }}>{a.name}</span>
                <span style={{ display:'block', fontFamily:W.mono, fontSize:W.fs.dataSm.sz, color:W.inkSoft }}>
                  {a.verified ? (a.seen ? 'renewed · ' + a.seen : 'connection verified') :
                   a.status === 'off' ? 'disconnected from this app' : a.status === 'stale' ? 'connection not renewed' : 'connection unverified'}</span></span>
              <span style={{ fontFamily:W.mono, fontSize:W.fs.dataSm.sz, color:W.inkSoft }}>{wsStatusText[a.status] || ''}</span>
            </button>)) :
            <div style={{ fontSize:11.5, color:W.inkSoft }}>No agent is attached to this Workshop.</div>}
        </div>
        <div style={{ display:'flex', gap:6, marginTop:10 }}>
          <button type="button" disabled={!chosen || !chosen.verified || !assign}
            onClick={() => { setNotice(null); setPhase('review'); }}>{chosen ? 'Assign to ' + chosen.name + '…' : 'Assign…'}</button>
        </div>
      </> : <div style={{ marginTop:8, padding:'10px 12px', border:`1px solid ${W.line}`, borderRadius:10 }}>
        <div style={{ fontFamily:W.serif, fontSize:17 }}>Assign this Work</div>
        <div style={{ display:'flex', gap:8, alignItems:'center', marginTop:8, fontSize:12 }}>
          <div style={{ flex:1, minWidth:0 }}><Lbl>WORK</Lbl><div style={{ overflowWrap:'anywhere' }}>{task.title}</div></div>
          <div aria-hidden="true">→</div>
          <div style={{ flex:1, minWidth:0 }}><Lbl>AGENT</Lbl><div data-assign-agent={reviewAgent ? reviewAgent.id : ''}>{reviewAgent ? reviewAgent.name : ''}</div></div>
        </div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginTop:10, fontSize:11, lineHeight:1.5, color:W.inkSoft }}>
          <div><b style={{ color:W.ok }}>Does</b><br/>records the assignment · adds it to the agent's Work list · raises an attention item</div>
          <div><b style={{ color:W.err }}>Does not</b><br/>claim the Work · grant any file writes · start or enrol a session</div>
        </div>
        <div style={{ fontFamily:W.mono, fontSize:W.fs.dataSm.sz, color:W.inkSoft, marginTop:8 }}>connection re-checked at commit · assignment id reused on retry</div>
        <div style={{ display:'flex', gap:6, marginTop:10 }}>
          <button type="button" disabled={shownPhase === 'sending' || !(chosen || pendingNow)} onClick={send}>
            {pendingNow && shownNotice?.kind === 'uncertain' ? 'Retry the same assignment' : shownPhase === 'sending' ? 'Assigning…' : 'Assign · founder'}</button>
          {/* Back keeps an unconfirmed request: its assignment id stays until it is settled. */}
          <button type="button" disabled={shownPhase === 'sending' || !!pendingNow} onClick={() => { setPhase('pick'); setNotice(null); }}>Back</button>
        </div>
      </div>}
    </div>);
};

// ── context panel ──
// Founder decision 2026-09-30: agents propose Work; the founder binds the checked
// proposals in one action. Each shows its grants per governed root and its reviewers.


// ── the view ──
// "Open as nodes" for a workflow card: its step nodes live in the workflow's own scope
// (governed Work, hidden at the product scope), so walk there FIRST, then focus and switch
// to the canvas. The walk goes through the existing scope-open path only (the signed
// authority.open loop, or window.ARCHHUB_SCOPE_OPEN) -- no second navigation path. A
// workflow whose scope_path does not end at its own scope is refused, with a message, and
// the mode never switches. A focus with no workflow (e.g. a session's Agent node, already
// drawn) just focuses and switches, as before.
async function openWorkflowAsNodes({ focus, workflow, authority, scopeOpen, refreshTopology, currentScope, setFocusId, requestCanvasReveal, setMode, setError }) {
  let canvas = null;
  if (workflow) {
    const path = Array.isArray(workflow.scope_path) ? workflow.scope_path : null;
    if (!path || !path.length || path[path.length - 1] !== workflow.scope) {
      if (setError) setError("This workflow's scope cannot be opened from here. Open it from the Workshop.");
      return false;
    }
    try {
      if (authority && typeof authority.open === 'function' && typeof authority.load === 'function') {
        canvas = await authority.load();
        const top = canvas && canvas.scope && Array.isArray(canvas.scope.trail) && canvas.scope.trail[0]
          ? canvas.scope.trail[0].root : null;
        if (top && canvas.scope.current !== top && canvas.scope.current !== path[path.length - 1]) canvas = await authority.open(top);
        for (const step of path) { if (!canvas || canvas.scope.current !== step) canvas = await authority.open(step); }
      } else if (typeof scopeOpen === 'function') {
        canvas = await scopeOpen(path);
      } else {
        if (setError) setError('The canvas scope could not be opened in this view.');
        return false;
      }
      // Refresh the topology AFTER the walk so the just-drafted member nodes are in the snapshot
      // the canvas draws (wfAct left it stale). Then verify the member is actually present before
      // switching; a failed refresh falls back to the walk projection and still verifies.
      if (typeof refreshTopology === 'function') {
        try { const fresh = await refreshTopology(); if (fresh) canvas = fresh; } catch (_) { /* use the walk projection */ }
        // A late refresh must never overwrite a view the person has since changed away from.
        if (typeof currentScope === 'function' && currentScope() !== workflow.scope) return false;
        const sameScope = !canvas || !canvas.scope || canvas.scope.current === workflow.scope;
        const present = canvas && Array.isArray(canvas.nodes) && canvas.nodes.some(node => node.id === focus);
        if (!sameScope || !present) {
          if (setError) setError("The workflow's nodes are not on this canvas yet. Open it again in a moment.");
          return false;
        }
      }
    } catch (failure) {
      if (setError) setError((failure && failure.message) || 'The workflow scope could not be opened.');
      return false;
    }
  }
  if (workflow && requestCanvasReveal) {
    const ids = Array.isArray(workflow.members) && workflow.members.length
      ? workflow.members : focus ? [focus] : [];
    if (ids.length) requestCanvasReveal(ids);
  }
  if (focus && setFocusId) setFocusId(focus);
  setMode('canvas');
  return true;
}

// The workflow card's "Open as nodes" opens ITS OWN workflow -- never the current task or
// selection. It focuses one of the workflow's members so a drawn node is selected after the
// scope walk. (The generic Open buttons keep using openAsNodes, which follows the selection.)
function openShownWorkflowAsNodes(workflow, deps) {
  const focus = (workflow && Array.isArray(workflow.members) && workflow.members[0])
    || (workflow && workflow.root) || '';
  return openWorkflowAsNodes({ ...deps, focus, workflow: workflow || null });
}


// Only menu focus/open state is local; the target stays in the existing composer route.
const WorkshopAgentPicker = ({ aliases, target, label, avatar, disabled, onSelect }) => {
  const [open,setOpen]=React.useState(false), trigger=React.useRef(null), menu=React.useRef(null), first=React.useRef(0);
  const menuId=React.useId();
  const focus=index=>menu.current?.querySelectorAll('[role=option]')[index]?.focus();
  const close=()=>{setOpen(false);trigger.current?.focus();};
  const show=index=>{first.current=index;setOpen(true);};
  React.useEffect(()=>{if(open)focus(first.current);},[open]);
  React.useEffect(()=>{if(disabled)setOpen(false);},[disabled]);
  return <div style={{position:'relative'}} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))setOpen(false);}}>
    <button ref={trigger} type="button" data-workshop-agent-picker="" aria-label="Reply agent" aria-haspopup="listbox"
      aria-controls={menuId} aria-expanded={open} disabled={disabled} onClick={()=>open?setOpen(false):show(Math.max(0,aliases.findIndex(a=>a.target===target)))}
      onKeyDown={event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();show(event.key==='ArrowUp'?aliases.length-1:0);}}}
      style={{display:'inline-flex',alignItems:'center',gap:6,height:30,padding:'0 10px',borderRadius:7,background:W.workshop.buttonBackground,
        color:W.ink,fontFamily:W.sans,fontSize:12.5,border:0,cursor:'pointer'}}>{avatar}{label}<span aria-hidden="true">▾</span></button>
    {open&&<div ref={menu} id={menuId} role="listbox" aria-label="Reply agents" style={{position:'absolute',bottom:38,left:0,minWidth:180,
      padding:4,borderRadius:8,background:W.surf2,boxShadow:W.elev.e2,border:`1px solid ${W.line}`,zIndex:4}}>
      {aliases.map((a,index)=><div key={a.target} role="option" aria-selected={a.target===target} tabIndex={-1}
        onClick={()=>{onSelect(a.target);close();}} onKeyDown={event=>{
          if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();focus(event.key==='Home'?0:event.key==='End'?aliases.length-1:(index+(event.key==='ArrowDown'?1:-1)+aliases.length)%aliases.length);}
          else if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect(a.target);close();}
          else if(event.key==='Escape'){event.preventDefault();close();}else if(event.key==='Tab')setOpen(false);
        }} style={{padding:'8px 10px',borderRadius:5,fontSize:13,color:W.ink,background:a.target===target?W.workshop.buttonBackground:'transparent',cursor:'pointer'}}>{a.label}</div>)}
    </div>}
  </div>;
};

const WorkshopView = ({ state, descriptor, target = '', setTarget = () => {}, setMode, setFocusId,
  requestCanvasReveal, onLeave, onHome, onDocs, onSettings, onLibrary, onChats, onCockpit, onAddNode, account, sel, setSel, embedded = false }) => {
  const authority = window.ARCHHUB_STUDIO_AUTHORITY || window.ARCHHUB_EXISTING_WORKSHOP;
  const transcript = wsTranscript(state, descriptor);
  const native = wsNative(state, descriptor);
  const [draft, setDraft] = React.useState('');
  const [busy, setBusy] = React.useState(false), busyRef = React.useRef(false);
  const [error, setError] = React.useState('');
  const [contacts, setContacts] = React.useState([]);
  const [selection, ownSelect] = React.useState(null);
  const [search, setSearch] = React.useState('');
  const searchRef = React.useRef(null);
  const acceptedDecisions = React.useRef(new Set());
  const selected = sel?.task || selection;
  const viewport = React.useRef(null), content = React.useRef(null), approvalRef = React.useRef(null);
  const scroll = React.useRef(null), mounted = React.useRef(true);
  if (!scroll.current) scroll.current = createWorkshopMessageScroll(() => {});
  const scope = JSON.stringify([state?.canvas?.graph_id, state?.canvas?.root, descriptor.root]);
  const heldScope = React.useRef(scope); heldScope.current = scope;
  const current = () => mounted.current && heldScope.current === scope;
  React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const graphNodes = workshopProjectedNodes(state);
  const selectedNativeWork = selected && !(transcript?.workflows || []).some(row => row.root === selected) &&
    graphNodes.some(row => row.id === selected) ? selected : native?.work || null;
  const openedRoot = React.useRef(null);
  // Reuse the visible-page refresh: first navigation opens once, messages settle before status.
  React.useEffect(() => {
    if (!descriptor.root || descriptor.unavailable || !authority) return;
    let gone = false, timer, active = false;
    let lastNativeRead = 0;
    const refresh = async () => {
      if (gone || document.hidden || active) return;
      active = true; clearTimeout(timer);
      try {
        const opening = openedRoot.current !== descriptor.root && typeof authority.openWorkshop === 'function';
        if (opening) openedRoot.current = descriptor.root;
        const projection = await (opening ? authority.openWorkshop(descriptor.root) : authority.refreshWorkshop?.(descriptor.root));
        if (!gone && !document.hidden && projection && !busyRef.current && Date.now() - lastNativeRead >= 10000 &&
            descriptor.native_work_available !== false && typeof authority.refreshNativeWork === 'function') {
          lastNativeRead = Date.now();
          await authority.refreshNativeWork(descriptor.root, selectedNativeWork);
        }
      } catch (failure) { if (!gone) setError(failure.message || 'Workshop could not be refreshed.'); }
      finally { active = false; if (!gone) timer = setTimeout(refresh, 2500); }
    };
    refresh();
    const visible = () => { clearTimeout(timer); if (!document.hidden) refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => { gone = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visible); };
  }, [authority, descriptor.root, descriptor.unavailable, selectedNativeWork]);
  // Agent data and task creation admission are requested only from an open window.
  React.useEffect(() => {
    if (!descriptor.root || descriptor.unavailable || !authority) return;
    let gone = false;
    if (typeof authority.nativeAgents === 'function') Promise.resolve(authority.nativeAgents(descriptor.root))
      .then(read => { if (!gone && Array.isArray(read?.contacts)) setContacts(read.contacts); })
      .catch(failure => { if (!gone) setError(failure.message || 'Agent connections could not be read.'); });
    authority.refreshWorkshopPresentation?.(descriptor.root)?.catch(failure => {
      if (!gone) setError(failure.message || 'Workshop preferences could not be read.');
    });
    return () => { gone = true; };
  }, [authority, descriptor.root, descriptor.unavailable]);
  const messages = transcript?.messages || [];
  React.useEffect(() => {
    const focusSearch = event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault(); event.stopPropagation(); searchRef.current?.focus();
    }};
    document.addEventListener('keydown', focusSearch, true);
    return () => document.removeEventListener('keydown', focusSearch, true);
  }, []);
  const names = new Map((transcript?.participants || []).map(row => [row.root, row.label]));
  const model = window.ARCHHUB_WORKSHOP_MODEL({state, descriptor, selected});
  const tasks = model.tasks;
  const creating = !!model.draft;
  const hasThread = !creating && (tasks.length > 0 || messages.length > 0);
  const agents = model.members;
  const activeTask = creating ? null : model.tasks.find(row => row.work === selected) || model.tasks.find(row => row.work === model.approval?.work) || model.tasks[0] || null;
  const assignedAgents = model.assigned;
  const lead = assignedAgents[0] || agents.find(row => row.row?.attached || row.row?.connected === true) || null;
  const aliases = [...(transcript?.participants || []).filter(row => row.attached && row.root !== transcript?.self)
    .map(row => ({label:row.label, target:row.root})), ...contacts.map(row => ({label:row.label, target:'contact:' + row.root}))];
  const modelAgent = transcript?.model_agent;
  if (modelAgent) aliases.push({label:window.ARCHHUB_WORKSHOP_AGENT_MODEL(modelAgent,state), target:'model:' + modelAgent.root});
  const taskAgent = transcript?.assignments?.find(row=>row.work===activeTask?.work)?.agent_session || activeTask?.owner;
  const taskReply = aliases.find(row=>row.target===taskAgent)?.target || '';
  const replyTarget = target || (activeTask ? taskReply : aliases.find(row=>row.target===lead?.id)?.target || aliases[0]?.target) ||
    (!activeTask && modelAgent ? 'model:' + modelAgent.root : !activeTask && contacts.find(row => row.connected === true) ? 'contact:' + contacts.find(row => row.connected === true).root : '');
  const replyName = aliases.find(row => row.target === replyTarget)?.label || 'Not available yet';
  const selectTask = task => { if (creating) authority?.cancelWorkshopTask?.(descriptor.root); ownSelect(task.work); setSel?.({agent:null, task:task.work,review:false});
    const assigned = transcript?.assignments?.find(row => row.work === task.work)?.agent_session || task.owner;
    setTarget(assigned && aliases.some(row => row.target === assigned) ? assigned : '');
  };
  const reviewTask = task => {
    selectTask(task);
    setTimeout(() => { const card = approvalRef.current?.querySelector('[data-workshop-approval-card]') || approvalRef.current;
      card?.scrollIntoView?.({block:'center'}); card?.focus?.(); }, 0);
  };
  React.useEffect(() => {
    if (sel?.task && sel?.review === true) { const card = approvalRef.current?.querySelector('[data-workshop-approval-card]') || approvalRef.current;
      card?.scrollIntoView?.({block:'center'}); card?.focus?.(); }
  }, [sel?.task, sel?.review, model.approval?.id]);
  React.useLayoutEffect(() => {
    scroll.current.update(viewport.current, scope + '|' + (activeTask?.work || ''), !!transcript && !transcript.error, !!state?.workshopPage?.before);
  }, [scope, activeTask?.work, transcript?.content_cursor, messages.length]);
  const run = async action => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError('');
    try { await action(); return true; }
    catch (failure) { if (current()) setError(failure.message || 'The action was not confirmed.'); return false; }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const send = () => run(async () => {
    if (!draft.trim() || transcript?.can_send !== true || (!replyTarget && !draft.trim().startsWith('@'))) return;
    const address = wsResolveAddress(draft, replyTarget, aliases);
    if (creating) {
      if (typeof authority?.createWorkshopTask !== 'function') throw new Error('Task creation is not available yet.');
      const result = await authority.createWorkshopTask(descriptor.root,{message:address.message,target:address.target});
      if (current()) {setTarget(address.target);setDraft('');ownSelect(result.created_root);setSel?.({agent:null,task:result.created_root,review:false});}
      return;
    }
    const contact = contacts.find(row => 'contact:' + row.root === address.target);
    if (contact) {
      if (contact.connected === false) throw new Error('Refresh this agent connection before sending.');
      await authority.sendNativeContact(descriptor.root, contact, address.message);
    } else if (address.target.startsWith('model:')) {
      if (!modelAgent || address.target !== 'model:' + modelAgent.root) throw new Error('Refresh this model before sending.');
      await authority.sendModelConversation(descriptor.root, modelAgent, address.message);
    } else await authority.workshopAction(descriptor.root, 'send', null, {target:address.target, message:address.message,
      ...(address.target && graphNodes.some(node=>node.id===activeTask?.work && node.engine==='work') ? {work:activeTask.work} : {})});
    if (current()) { setTarget(address.target); setDraft(''); }
  });
  const approval = model.approval;
  const decisionAvailable = (card,operation,choice) => {
    const key = [scope,card?.kind,card?.id,card?.kind === 'native' ? operation?.input_digest : card?.workflow?.digest || card?.input_digest || ''].join('|');
    if (!card || acceptedDecisions.current.has(key)) return false;
    if (choice === 'approve' && Number.isFinite(operation?.review_expires_at) && operation.review_expires_at <= Date.now()/1000) return false;
    return choice === 'approve' ? card.kind === 'proposal' ? typeof authority?.bindWorkProposals === 'function' :
      card.kind === 'native' ? typeof authority?.approveNativeWork === 'function' && !!operation?.input_digest :
        card.kind === 'workflow' && typeof authority?.workshopWorkflow === 'function' && !!card.workflow?.digest :
      card.kind === 'proposal' ? typeof authority?.declineWorkProposals === 'function' :
        card.kind === 'native' && operation?.mode === 'agent' && typeof authority?.nativeWorkAction === 'function';
  };
  const decide = (choice,card = approval,operation = native) => run(async () => {
    if (!decisionAvailable(card,operation,choice)) return;
    const key = [scope,card.kind,card.id,card.kind === 'native' ? operation?.input_digest : card.workflow?.digest || card.input_digest || ''].join('|');
    if (card.kind === 'proposal') {
      const message = card.proposal.decision?.find(row => row.action === (choice === 'approve' ? 'approve-proposal' : 'decline-proposal'))?.message;
      if (!message) throw new Error('Read this proposal before deciding.');
      await (choice === 'approve' ? approveWorkProposal(authority, descriptor.root, message)
        : declineWorkProposal(authority, descriptor.root, message));
    } else if (card.kind === 'native') {
      if (choice === 'approve') await authority.approveNativeWork(descriptor.root, operation.input_digest);
      else await authority.nativeWorkAction(descriptor.root, 'stop_native', operation.work);
    } else if (choice === 'approve') await authority.workshopWorkflow(descriptor.root, 'workflow-approve',
      {workflow:card.workflow.root, digest:card.workflow.digest});
    acceptedDecisions.current.add(key);
    try { await authority.refreshTopologyCanvas?.(); await authority.refreshWorkshop?.(descriptor.root); }
    catch (_) { /* A refresh failure never replays an accepted decision. */ }
  });
  const openCanvas = () => run(async () => {
    const workflow = (transcript?.workflows || []).find(row => row.root === activeTask?.work ||
      row.members?.includes(activeTask?.work) || row.nodes?.some(node => node.root === activeTask?.work)) || null;
    const deps = {authority, scopeOpen:window.ARCHHUB_SCOPE_OPEN, setFocusId, requestCanvasReveal, setMode, setError,
      refreshTopology:typeof authority?.refreshTopologyCanvas === 'function' ? () => authority.refreshTopologyCanvas() : null,
      currentScope:() => authority.getSnapshot()?.topology?.canvas?.scope?.current || authority.getSnapshot()?.canvas?.root};
    if (workflow) await openShownWorkflowAsNodes(workflow,deps);
    else await openWorkflowAsNodes({...deps,focus:activeTask?.graphRoot || activeTask?.work || descriptor.node_root || descriptor.root,workflow:null});
  });
  const K = W.workshop;
  const isPlanned = row => row.boardLane === 'planned' || row.planned || ['planned','open','queued'].includes(row.state);
  const tone = row => row.approving || row.state === 'needs-user' || (row.proposal && row.state === 'block') ? W.warn : isPlanned(row) ? W.inkSoft :
    ['done','submitted','completed'].includes(row.state) ? W.ok : ['failed','stopped','block'].includes(row.state) ? W.err :
    ['run','running','open','working'].includes(row.state) ? W.accent : W.inkSoft;
  const statusLine = row => row.approving || row.state === 'needs-user' || (row.proposal && row.state === 'block') ?
    row.work === model.approval?.work && Number.isSafeInteger(model.count) ? `Approve ${model.count}${model.output_label ? ' ' + model.output_label : ''}` : 'waits for you' :
    row.boardLane === 'done' ? [row.result_summary || row.latest?.result_summary || 'Not available yet',
      wsClockText(row.completed_at ?? row.done_at ?? row.updated_at ?? row.latest?.created_at)].filter(Boolean).join(' · ') :
    isPlanned(row) ? row.depends_on?.length ? 'starts after ' + row.depends_on.map(id=>tasks.find(task=>task.work===id)?.title||graphNodes.find(node=>node.id===id)?.title||id).join(', ') : 'ready to start' :
    /^claimed$/i.test(row.status || row.nodeStatus || '') ? 'ready to start' :
    String(row.statusLine || row.status || row.nodeStatus || row.latest?.state || row.state || 'Not available yet').replaceAll('_',' ');
  const presence = row => row?.presence === 'needs-user' ? W.warn : row?.presence === 'working' ? W.accent : null;
  const tile = (row, size = 28, ring = presence(row)) => <span data-workshop-avatar={row?.id || ''}
    style={{position:'relative',width:size,height:size,flex:'none',display:'inline-block'}}>
    <i style={{position:'absolute',inset:0,borderRadius:size/3.5,background:`linear-gradient(180deg, ${row?.col || W.purple} 0%, ${row?.col || W.purple}cc 100%)`,
      color:'#fff',display:'grid',placeItems:'center',fontStyle:'normal',fontSize:Math.max(11,size*.44),fontWeight:700,boxShadow:'0 1px 0 rgba(255,255,255,.25) inset'}}>
      {row?.ini || wsInitial(row?.name,'?')}</i>{ring && <i data-presence-ring="" style={{position:'absolute',inset:-3,borderRadius:size/3.5+3,border:`2px solid ${ring}`,boxShadow:`0 0 10px ${ring}66`}}/>}</span>;
  const dot = color => <i style={{width:8,height:8,borderRadius:'50%',background:color,boxShadow:`0 0 8px ${color}aa`,display:'inline-block',flex:'none'}}/>;
  const chip = (label,color) => <span style={{display:'inline-flex',alignItems:'center',gap:6,height:24,padding:'0 9px',borderRadius:999,background:`${color}1f`,color,fontSize:12,fontWeight:600}}>{label}</span>;
  const button = (primary = false, small = false) => ({display:'inline-flex',alignItems:'center',gap:7,height:small?30:36,padding:small?'0 12px':'0 16px',borderRadius:8,
    fontFamily:W.sans,fontSize:small?13:14,fontWeight:600,cursor:'pointer',background:primary?`linear-gradient(180deg, ${W.accentHi || W.accent} 0%, ${W.accent} 100%)`:K.buttonBackground,
    color:primary?'#fff':W.ink,boxShadow:primary?`0 1px 0 rgba(255,255,255,.25) inset, 0 4px 14px ${W.accent}44`:'0 1px 0 rgba(255,255,255,.06) inset',border:primary?0:`1px solid ${W.line}`});
  const eventRoots = new Set((activeTask?.events || []).map(message => message.root));
  const taskMessages = activeTask ? messages.filter(message => eventRoots.has(message.root) ||
    (!message.task_root && !message.work_root && !(message.reference_roots || message.refs || []).some(id=>tasks.some(task=>task.work===id)) && !/\b(?:assembly-instance|work):[A-Za-z0-9_-]+/.test(wsText(message)) &&
      !(transcript?.workflows || []).some(row=>row.source_message===message.root && row.root!==selected && row.root!==model.workflow?.root)) ||
    ((message.task_root === activeTask.work || message.work_root === activeTask.work) &&
      !(transcript?.workflows || []).some(row => row.source_message === message.root && row.root !== selected))) : messages;
  const planMessage = model.workflow?.source_message ? messages.find(message => message.root === model.workflow.source_message)
    : [...taskMessages].reverse().find(message => wsPlanReply(wsText(message))?.steps?.length);
  const plan = model.plans.length ? model.plans : wsPlanReply(wsText(planMessage))?.steps || [];
  const plainText = message => {
    const structured = wsPlanReply(message.agent_text || wsText(message));
    const body = structured ? structured.prose : message.agent_text || message.body || '';
    if (isWorkProposal(message)) return model.tasks.find(row => row.proposal === (message.message_id || message.root))?.intent || 'Not available yet';
    return String(body).replace(/\b(?:assembly-instance|work|app|room):[A-Za-z0-9_.:@-]+/g,
      id => graphNodes.find(row => row.id === id)?.title || model.tasks.find(row => row.work === id)?.title || 'task');
  };
  const rawMessages = model.workflow?.source_message && selected === model.workflow.root
    ? messages.filter(message => message.root === model.workflow.source_message ||
      (transcript?.reviews || []).some(review => review.workflow === model.workflow.root && review.review_message === message.root)) : taskMessages;
  const visibleMessages = rawMessages.filter(message => !window.ARCHHUB_WORKSHOP_TASK_SOURCE.lifecycle(message));
  const planElement = plan.length > 0 && <div data-workshop-plan="" style={{borderRadius:12,background:W.surf,boxShadow:W.elev.e1,overflow:'hidden'}}>
    <div style={{display:'flex',alignItems:'center',gap:10,padding:'12px 14px'}}><span style={{fontSize:13,fontWeight:600,flex:1}}>Run</span>
      <span style={{fontSize:12.5,color:W.inkSoft}}>{plan.filter(step=>['done','completed','settled','published'].includes(graphNodes.find(n=>n.id===(step.root||step.id))?.status || step.state)).length} of {plan.length} steps</span>
      <span role="progressbar" aria-label="Run progress" aria-valuemin={0} aria-valuemax={plan.length}
        aria-valuenow={plan.filter(step=>['done','completed','settled','published'].includes(graphNodes.find(n=>n.id===(step.root||step.id))?.status || step.state)).length}
        style={{width:120,height:4,borderRadius:2,background:K.progressBackground}}><i style={{display:'block',height:'100%',borderRadius:2,
          width:`${100*plan.filter(step=>['done','completed','settled','published'].includes(graphNodes.find(n=>n.id===(step.root||step.id))?.status || step.state)).length/plan.length}%`,background:`linear-gradient(90deg, ${W.ok}, ${W.warn})`}}/></span></div>
    {plan.map((step,index) => { const node=graphNodes.find(row=>row.id===(step.root||step.id));
      const st=String(node?.status||node?.state||step.state||'').toLowerCase(),done=['done','completed','settled','published'].includes(st),waits=['block','blocked','waiting','awaiting_approval','needs-user'].includes(st)||node?.id===approval?.work;
      const c=done?W.ok:waits?W.warn:W.inkSoft;
      return <div key={step.root||step.id||index} data-workshop-plan-step={step.root||step.id||''} style={{display:'grid',gridTemplateColumns:'28px 1fr auto auto',gap:12,alignItems:'center',padding:'7px 14px',borderTop:`1px solid ${W.lineSoft}`}}>
        <span style={{width:26,height:26,borderRadius:7,background:`${c}22`,color:c,display:'grid',placeItems:'center',fontSize:13}}>{done?'✓':waits?'⏸':'○'}</span>
        <span data-workshop-step-title="" style={{fontSize:14,color:W.ink}}>{wsCleanTitle(step.title||step.t||node?.title,'Not available yet')}</span>
        <span style={{fontSize:12.5,color:W.inkSoft}}>{step.duration ?? node?.duration ?? ''}</span>
        <span data-workshop-step-result="" style={{fontSize:12.5,color:c,textAlign:'right'}}>{done||waits?chip(step.result||node?.result_summary||(done?'done':'waits for you'),c):step.result||node?.result_summary||'next'}</span>
      </div>;})}</div>;
  const planAnchor=visibleMessages.some(message=>message.root===planMessage?.root) ? planMessage.root :
    [...visibleMessages].reverse().find(message=>wsSender(message)===(model.workflow?.proposed_by||lead?.id))?.root;
  const hostLine=(state?.hosts||window.ARCHHUB_LIVE?.hosts||[]).filter(row=>row.state==='connected'||row.status==='connected').map(row=>[row.name,row.file].filter(Boolean).join(' · ')).join(' · ');
  const AppRail=window.ARCHHUB_APP_RAIL;
  const navigate=name=>{ if(name==='Workshop')return; if(name==='Canvas')return openCanvas();
    const route={Home:onHome||onLeave,Chats:onChats,Cockpit:onCockpit,Library:onLibrary||onAddNode,Docs:onDocs,Settings:onSettings,Account:onSettings}[name];route?.();};
  const agentFor=task=>agents.find(row=>row.id===transcript?.assignments?.find(a=>a.work===task.work)?.agent_session)||agents.find(row=>row.id===task.owner);
  const liveAccount = account || state.account || (typeof window.acLoad === 'function' ? window.acLoad() : null);
  const accountName = liveAccount?.name || liveAccount?.email || names.get(transcript?.self) || '';
  const accountInitials = liveAccount?.initials || accountName.trim().split(/\s+/).map(word=>Array.from(word)[0]).slice(0,2).join('').toUpperCase() || '?';
  const accountColour = liveAccount?.colour || liveAccount?.color || liveAccount?.avatar_color || W.userAv;
  const beginTask = () => run(async()=>{await authority?.beginWorkshopTask?.(descriptor.root);setDraft('');ownSelect(null);setSel?.({agent:null,task:null,review:false});setTarget(aliases.find(row=>row.target===lead?.id)?.target||aliases[0]?.target||'');});
  const taskProgress=task=>{const projected=graphNodes.find(n=>n.id===(task.graphRoot||task.work));
    const value=task.progress ?? projected?.progress; return Number.isFinite(value)?Math.max(0,Math.min(100,value)):null;};
  const renderSection=section=><section key={section.id} data-workshop-section={section.id}>
    <div style={{display:'flex',alignItems:'center',gap:8,padding:'18px 22px 8px',fontSize:12,fontWeight:600,color:W.inkSoft,letterSpacing:'.05em'}}>
      {section.label}<span style={{minWidth:20,height:18,borderRadius:9,background:K.buttonBackground,display:'grid',placeItems:'center',fontSize:11,color:W.ink}}>{section.rows.length}</span></div>
    {section.rows.filter(task=>!search||task.title?.toLowerCase().includes(search.toLowerCase())).map(task=>{const a=agentFor(task),selectedTask=activeTask?.work===task.work,needs=section.id==='needs-user',prog=taskProgress(task),c=needs?W.warn:tone(task);
      return <div key={task.work} data-workshop-task-row={task.work} data-state={needs?'needs-user':task.state} role="option" aria-selected={selectedTask} tabIndex={0}
        onClick={()=>selectTask(task)} onKeyDown={event=>event.key==='Enter'&&selectTask(task)}
        style={{position:'relative',display:'grid',gridTemplateColumns:'32px 1fr auto',gap:12,alignItems:'center',margin:'2px 10px',padding:'10px 12px',borderRadius:10,
          background:selectedTask?W.surf2:'transparent',boxShadow:selectedTask?W.elev.e1:'none',cursor:'pointer'}}>
        {tile(a,30,needs?W.warn:['run','running','executing'].includes(task.state)?W.accent:null)}<div style={{minWidth:0,display:'grid',gap:3}}>
          <div style={{fontSize:14,fontWeight:600,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{wsCleanTitle(task.title,'Untitled task')}</div>
          <div style={{display:'flex',alignItems:'center',gap:6,fontSize:12.5,color:c}}><span style={{flex:1}}>{statusLine(task)}</span>
            {selectedTask&&model.approval?.work===task.work&&<button type="button" data-workshop-primary="" data-workshop-row-review={task.work} onClick={e=>{e.stopPropagation();reviewTask(task);}} style={{...button(false,true),height:18,padding:'0 7px',fontSize:11}}>Review</button>}</div>
          {prog!==null&&<span role="progressbar" aria-label="Task progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={prog}
            style={{height:3,borderRadius:2,background:K.progressBackground,marginTop:3}}><i style={{display:'block',height:'100%',borderRadius:2,width:prog+'%',background:c}}/></span>}</div>{dot(c)}
        {selectedTask&&needs&&<i style={{position:'absolute',left:-10,top:12,bottom:12,width:3,borderRadius:3,background:W.warn}}/>}</div>;})}</section>;
  const ApprovalCard=window.ARCHHUB_APPROVAL_CARD;
  const approvalElement=(card=model.approval,taskModel=model,compact=false)=>{if(!card)return null; const active=card.id===approval?.id;
    return <div ref={active?approvalRef:undefined} tabIndex={-1} data-approval-anchor={card.id} style={{marginLeft:compact?0:46}}>
      <ApprovalCard approval={card} accent={active} approveLabel="Approve" surface={compact?'workshop-tile':'workshop'} busy={busy} canApprove={decisionAvailable(card,taskModel.native,'approve')} canDecline={decisionAvailable(card,taskModel.native,'decline')}
        onApprove={async()=>{if(await decide('approve',card,taskModel.native)===false)throw new Error('Approval could not be confirmed.');}}
        onDecline={async()=>{if(await decide('decline',card,taskModel.native)===false)throw new Error('Decline could not be confirmed.');}}/></div>;};
  const layout=[1,2,4].includes(model.layout)?model.layout:1;
  const setLayout=value=>run(async()=>{ if(typeof authority?.setWorkshopLayout!=='function')return; await authority.setWorkshopLayout(descriptor.root,value); });
  const modelLabel=a=>a?.modelLabel||(a?window.ARCHHUB_WORKSHOP_AGENT_MODEL?.(a.row||a,state):null)||'Not available yet';
  const selectedTiles=[activeTask,...tasks.filter(t=>t.work!==activeTask?.work)].filter(Boolean).slice(0,layout);
  const composer=<div data-workshop72-composer="" style={{width:hasThread?K.thread:640,maxWidth:'calc(100% - 48px)',margin:'0 auto',borderRadius:14,background:W.surf2,boxShadow:W.elev.e2,border:`1px solid ${W.line}`,padding:'14px 16px',display:'grid',gap:12}}>
    <textarea aria-label="Workshop message" placeholder={`Reply to ${replyName}, or @ another agent…`} value={draft} disabled={busy||transcript?.can_send!==true}
      onChange={event=>setDraft(event.target.value)} onKeyDown={event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();send();}}}
      style={{fontFamily:W.sans,fontSize:15,color:W.ink,background:'transparent',border:0,padding:0,resize:'none',height:18,minHeight:18,outline:'none'}}/>
    <div style={{display:'flex',alignItems:'center',gap:8}}>
      <WorkshopAgentPicker aliases={aliases} target={replyTarget} label={replyName} onSelect={setTarget} disabled={!aliases.length||busy}
        avatar={tile(agents.find(a=>a.id===replyTarget)||lead,16,null)}/><span style={{flex:1}}/>
      <button type="button" aria-label="Send" data-workshop-send="" data-workshop-primary="" disabled={busy||transcript?.can_send!==true||!draft.trim()||(!replyTarget&&!draft.trim().startsWith('@'))} onClick={send} style={button(!!draft.trim()&&!approval&&!model.status.waiting,true)}>Send</button></div>
      {(error||transcript?.error)&&<div role="alert" style={{fontSize:13,color:W.err}}>{error||transcript.error}</div>}</div>;
  return <main data-workshop-s1="" data-workshop72="" data-workshop-v3="" data-screen-label="5.1v3_workshop" data-workshop-id={model.id}
    style={{gridColumn:'1 / -1',gridRow:'1 / -1',minHeight:0,overflow:'hidden',display:'grid',width:'100%',height:'100%',gridTemplateRows:embedded ? '1fr' : `1fr ${K.status}px`,background:K.background,color:W.ink,fontFamily:W.sans,margin:0}}>
    <div style={{display:'grid',gridTemplateColumns:embedded ? `${K.list}px minmax(0,1fr)` : `${K.rail}px ${K.list}px minmax(0,1fr)`,minHeight:0}}>
      {!embedded && <AppRail active="Workshop" workshop waiting={model.status.waiting}
        account={{...liveAccount, initials:accountInitials, colour:accountColour}} onNavigate={navigate}/>}
      <aside data-workshop72-list="" style={{width:K.list,boxSizing:'border-box',background:K.listBackground,borderRight:`1px solid ${W.lineSoft}`,display:'flex',flexDirection:'column',minHeight:0}}>
        <div style={{display:'flex',alignItems:'center',gap:10,height:64,flex:'none',padding:'0 16px 0 22px'}}><span style={{fontSize:20,fontWeight:700,letterSpacing:'-.01em',flex:1}}>Workshop</span>
          <button type="button" data-workshop-primary="" disabled={busy||transcript?.can_send!==true||typeof authority?.beginWorkshopTask!=='function'} onClick={beginTask} style={button(false,true)}>New task</button></div>
        <div style={{margin:'0 16px',height:36,flex:'none',borderRadius:8,background:'#18181d',border:`1px solid ${W.lineSoft}`,display:'flex',alignItems:'center',gap:8,padding:'0 12px',fontSize:13.5,color:W.inkSoft}}>
          <span>⌕</span><input ref={searchRef} aria-label="Search tasks" placeholder="Search tasks" value={search} onChange={e=>setSearch(e.target.value)} style={{minWidth:0,flex:1,border:0,background:'transparent',color:W.ink,fontFamily:W.sans,fontSize:13.5,outline:'none'}}/>
          <span style={{fontSize:11,border:`1px solid ${W.line}`,borderRadius:4,padding:'1px 5px'}}>Ctrl K</span></div>
        <div className="ah-scroll" data-workshop72-sections="" style={{overflowY:'auto',flex:1,minHeight:0}}>{tasks.length>0&&(model.viewSections||[]).map(renderSection)}
          {!tasks.length&&<div role="status" aria-disabled={transcript?.ok!==true} style={{padding:'24px 16px',fontSize:13,color:W.inkSoft}}>{transcript?.ok===true?'No tasks yet.':'Not available yet'}</div>}</div>
        <div data-workshop-agents="" style={{margin:12,padding:'12px 14px',borderRadius:10,background:W.surf,boxShadow:W.elev.e1,display:'grid',gap:10}}>
          {agents.map(a=><div key={a.id} style={{display:'flex',alignItems:'center',gap:10,fontSize:13,minWidth:0}}>{tile(a,22)}
            <span style={{fontWeight:600,whiteSpace:'nowrap',flexShrink:0}}>{a.name}</span>
            <span title={modelLabel(a)} style={{color:W.inkSoft,fontSize:12,whiteSpace:'nowrap',minWidth:0,overflow:'hidden',textOverflow:'ellipsis',flex:1}}>{modelLabel(a)}</span>
            <span style={{fontSize:12,color:presence(a)||W.inkSoft,whiteSpace:'nowrap',flexShrink:0}}>{a.liveState||'Not available yet'}</span></div>)}
          {!agents.length&&<span aria-disabled="true" style={{fontSize:13,color:W.inkSoft}}>Not available yet</span>}</div></aside>
      <section data-workshop72-main="" style={{display:'grid',gridTemplateRows:hasThread?`${K.header}px 1fr auto`:'1fr',minHeight:0,background:K.threadBackground}}>
        {hasThread?<><header style={{display:'flex',alignItems:'center',gap:16,padding:'0 36px',borderBottom:`1px solid ${W.lineSoft}`}}>
          <div style={{display:'grid',gap:4,minWidth:0}}><span data-workshop-head="" style={{fontSize:22,fontWeight:700,letterSpacing:'-.01em'}}>{activeTask?.title||model.title}</span>
            <span style={{display:'flex',alignItems:'center',gap:10,fontSize:13,color:W.inkSoft}}>
              {assignedAgents.map(a=><React.Fragment key={a.id}>{tile(a,18,null)}{a.name}<span>·</span></React.Fragment>)}
              {model.reviewers.map(a=><React.Fragment key={a.id}>{tile(a,18,null)}{a.name} reviews<span>·</span></React.Fragment>)}
              {[native?.document || (state?.hosts || []).filter(row=>row.state==='connected'||row.status==='connected').map(row=>row.file).filter(Boolean).join(' · '),activeTask?.elapsed||native?.elapsed].filter(Boolean).join(' · ')}</span></div><span style={{flex:1}}/>
          <span role="radiogroup" aria-label="Task layout" style={{display:'inline-flex',border:`1px solid ${W.line}`,borderRadius:6,overflow:'hidden'}}>{[1,2,4].map(n=><span key={n} role="radio" aria-checked={layout===n}
            aria-disabled={typeof authority?.setWorkshopLayout!=='function'||busy} tabIndex={0} onClick={()=>setLayout(n)} onKeyDown={e=>(e.key==='Enter'||e.key===' ')&&setLayout(n)}
            style={{width:32,height:26,display:'grid',placeItems:'center',fontSize:12,background:layout===n?K.buttonBackground:'transparent',color:layout===n?W.ink:W.inkSoft,cursor:'pointer',borderLeft:n===1?0:`1px solid ${W.line}`}}>{n}</span>)}</span>
          {approval&&chip(<>{dot(W.warn)}Waiting for you</>,W.warn)}<button type="button" data-workshop-primary="" disabled={descriptor.unavailable||!state?.canvas?.graph_id||!authority||!setMode}
            title={descriptor.unavailable?'Not available yet':undefined} onClick={openCanvas} style={button(false,true)}>Open on canvas</button></header>
        {layout===1?<div ref={viewport} className="ah-scroll" aria-label="Workshop conversation" onScroll={e=>scroll.current.scroll(e.currentTarget)} style={{overflowY:'auto',overflowX:'hidden',padding:'18px 0',minHeight:0}}>
          <div ref={content} data-workshop72-thread="" style={{width:K.thread,maxWidth:'calc(100% - 48px)',margin:'0 auto',display:'grid',gap:14}}>
            {visibleMessages.map(message=>{const sender=wsSender(message),a=agents.find(row=>row.id===sender),self=sender===transcript?.self;
              const elapsed=message.elapsed??message.duration;
              const messageMeta=[a?modelLabel(a):null,typeof elapsed==='number'?elapsed+' s':elapsed,message.cost_label??(message.cost!==undefined?String(message.cost):null)].filter(v=>v!==null&&v!==undefined&&v!=='');
              return <article key={message.root} data-workshop-message={message.root} data-user-bubble={self?'':undefined}
                style={self?{position:'relative',justifySelf:'end',maxWidth:560,padding:'12px 16px',borderRadius:'14px 14px 4px 14px',background:K.bubbleBackground,fontSize:15,lineHeight:'23px',boxShadow:W.elev.e1}:{display:'grid',gridTemplateColumns:'32px 1fr',gap:14}}>
                {self?<><div>{plainText(message)}</div><time dateTime={String(message.created_at||'')} style={{position:'absolute',right:16,bottom:-14,fontSize:12.5,lineHeight:'14px',color:W.inkSoft}}>{wsClockText(message.created_at)}</time></>:<>{tile(a||{name:message.relayed_label||names.get(sender)},32,null)}<div style={{display:'grid',gap:model.reviewers.some(review=>review.id===sender)?6:12,minWidth:0}}>
                  <div style={{display:'flex',alignItems:'baseline',gap:10}}><b style={{fontSize:15,fontWeight:700}}>{a?.name||message.relayed_label||names.get(sender)||'Agent'}</b>
                    <span style={{fontSize:12.5,color:W.inkSoft}}>{messageMeta.join(' · ')}</span><time dateTime={String(message.created_at||'')} style={{fontSize:12.5,color:W.inkSoft}}>{wsClockText(message.created_at)}</time></div>
                  <div style={{fontSize:15,lineHeight:'24px',whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{plainText(message)}</div>{message.root===planAnchor&&planElement}</div></>}
              </article>;})}{!planAnchor&&planElement&&<div style={{marginLeft:46}}>{planElement}</div>}{approvalElement()}
            {!transcript&&<div role="status" style={{fontSize:13,color:W.inkSoft}}>{descriptor.unavailable?'Not available yet':'Loading messages…'}</div>}</div></div>
          :<div data-workshop-tiles={layout} style={{display:'grid',gridTemplateColumns:'1fr 1fr',gridTemplateRows:layout===4?'1fr 1fr':'1fr',gap:12,padding:16,minHeight:0}}>
            {selectedTiles.map(task=>{const tm=window.ARCHHUB_WORKSHOP_MODEL({state,descriptor,selected:task.work}),a=agentFor(task),
              taskLines=(task.events?.length?task.events:tm.messages.filter(m=>m.work_root===task.work||m.task_root===task.work||m.root===task.workflow?.source_message)).filter(m=>!window.ARCHHUB_WORKSHOP_TASK_SOURCE.lifecycle(m)),
              lines=taskLines.flatMap(m=>plainText(m).split('\n')).slice(-2),c=tm.needs_user?W.warn:tone(task);
              return <div key={task.work} data-workshop-tile={task.work} role="option" aria-selected={task.work===activeTask?.work} tabIndex={0} onClick={()=>selectTask(task)} onKeyDown={e=>e.key==='Enter'&&selectTask(task)}
                style={{background:W.surf,border:`1px solid ${task.work===activeTask?.work?W.accent:W.line}`,borderRadius:12,display:'grid',gridTemplateRows:'44px 1fr',minHeight:0,overflow:'auto',boxShadow:W.elev.e2}}>
                <div style={{display:'flex',alignItems:'center',gap:10,padding:'0 14px',borderBottom:`1px solid ${W.lineSoft}`}}>{tile(a,20)}<span style={{fontSize:14,fontWeight:600,flex:1}}>{task.title}</span><span style={{fontSize:12.5,color:c}}>{statusLine(task)}</span>{dot(c)}</div>
                <div style={{padding:14,display:'grid',gap:10,alignContent:'start'}}>{lines.map((line,i)=><div key={i} style={{fontSize:13,lineHeight:'19px',color:i===lines.length-1?W.ink:W.inkSoft}}>{line}</div>)}
                  {!lines.length&&<div aria-disabled="true" style={{fontSize:13,color:W.inkSoft}}>Not available yet</div>}
                  {tm.approval&&<div onClick={e=>e.stopPropagation()}>{approvalElement(tm.approval,tm,true)}</div>}</div></div>;})}</div>}
        <div style={{padding:'0 0 22px'}}>{composer}</div></>:<div data-workshop-empty="" style={{display:'grid',alignContent:'center',justifyItems:'center',gap:18,padding:24}}>
          <div style={{fontSize:22,fontWeight:600}}>What should the agents do?</div><div style={{display:'flex',gap:8}}>{agents.map(a=><span key={a.id} role="radio" aria-checked={replyTarget===a.id} tabIndex={0}
            onClick={()=>setTarget(a.id)} onKeyDown={e=>e.key==='Enter'&&setTarget(a.id)} style={{display:'inline-flex',alignItems:'center',gap:8,height:32,padding:'0 12px 0 6px',border:`1px solid ${replyTarget===a.id?W.accent:W.line}`,borderRadius:999,background:replyTarget===a.id?W.accentSoft:'transparent',fontSize:13,cursor:'pointer'}}>
              {tile(a,20,null)}{a.name}<span style={{color:W.inkSoft,fontSize:12}}>{modelLabel(a)}</span></span>)}</div>{composer}</div>}</section></div>
    {!embedded && <footer data-workshop-s1-status="" data-workshop72-status="" style={{height:K.status,boxSizing:'border-box',display:'flex',alignItems:'center',gap:18,padding:'0 16px',fontSize:12,color:W.inkSoft,borderTop:`1px solid ${W.lineSoft}`,background:K.railBackground}}>
      <span style={{display:'flex',alignItems:'center',gap:6,color:model.status.connected?W.ok:W.inkSoft}}>{dot(model.status.connected?W.ok:W.inkSoft)}{model.status.connected?'Connected':'Not available yet'}</span><span>{hostLine}</span>
      {model.viewSections?.find(s=>s.id==='working')?.rows.length>0&&<span style={{color:W.accent}}>{model.viewSections.find(s=>s.id==='working').rows.length} working</span>}
      {model.status.waiting>0&&<span style={{color:W.warn}}>{model.status.waiting} need you</span>}<span style={{flex:1}}/><span>{modelLabel(lead)}</span></footer>}
    <style>{`[data-workshop72] * {box-sizing:content-box;} [data-workshop72] button {box-sizing:border-box;} [data-workshop-send]::after {content:'↵';} [data-workshop72] button:disabled {cursor:default;} [data-workshop72] input::placeholder, [data-workshop72] textarea::placeholder {color:${W.inkSoft};opacity:1;}`}</style></main>;
};

// Presentation only: retain row identities/geometry, never a second transcript.
const createWorkshopMessageScroll = onAway => {
  let identity = null, ready = false, olderMode = false, following = true, anchors = [], position = 0, expected = null, away = false;
  const rows = viewport => Array.from(viewport.querySelectorAll('[data-workshop-message]')).slice(0, 100);
  const top = viewport => viewport.getBoundingClientRect().top + (viewport.clientTop || 0);
  const report = () => {
    if (away !== !following) { away = !following; onAway(away); }
  };
  const capture = viewport => {
    const edge = top(viewport);
    position = viewport.scrollTop;
    anchors = rows(viewport).filter(row => row.getBoundingClientRect().bottom > edge).map(row => ({
      root:row.getAttribute('data-workshop-message'), offset:row.getBoundingClientRect().top - edge,
    }));
  };
  const move = (viewport, value) => {
    viewport.scrollTop = Math.max(0, Math.min(value, viewport.scrollHeight - viewport.clientHeight));
    expected = viewport.scrollTop;
    capture(viewport);
    report();
  };
  const restore = viewport => {
    if (following) return move(viewport, viewport.scrollHeight);
    const current = new Map(rows(viewport).map(row => [row.getAttribute('data-workshop-message'), row]));
    const anchor = anchors.find(row => current.has(row.root));
    move(viewport, anchor ? viewport.scrollTop + current.get(anchor.root).getBoundingClientRect().top -
      top(viewport) - anchor.offset : position);
  };
  return {
    update(viewport, key, successful, older, jump = false) {
      ready = !!successful;
      if (!viewport || !ready) return;
      olderMode = older;
      if (identity !== key) {
        identity = key; following = false; anchors = []; position = 0;
        return move(viewport, 0);
      }
      if (jump && !older) following = true;
      restore(viewport);
    },
    scroll(viewport) {
      if (!viewport || !ready) return;
      // Browser scroll events also follow our own assignments. They must not
      // turn a clamped reading anchor into permission to follow new arrivals.
      if (expected !== null && Math.abs(viewport.scrollTop - expected) < 1) return;
      expected = null;
      following = !olderMode && viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop <= 48;
      capture(viewport); report();
    },
    reflow(viewport) { if (viewport && ready) restore(viewport); },
    jump(viewport) { if (viewport && ready && !olderMode) { following = true; move(viewport, viewport.scrollHeight); } },
  };
};

// The conversation panel is a live lens; no browser-owned message history.


window.WorkshopView = WorkshopView;

window.WorkshopAssignSection = AssignSection;   // the Work context panel's ASSIGN section (JSDOM court)
})();
