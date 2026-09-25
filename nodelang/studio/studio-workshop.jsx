// studio-workshop.jsx — WORKSHOP: the mode the conversation becomes when a Workshop is open.
// Loaded by studio.html BEFORE studio-lm.jsx renders; studio-lm reads window.WorkshopView and
// window.WorkshopAgentsRail. The components below are the design bundle's studio-workshop.jsx
// (archhub/project) taken as sent: same tokens, same task-card-as-container rule as the proposal
// board. Presets = directions A/B/C.
//
// LIVE SEAM. The design's seeded scene (its agent roster, run facts, flow, seeded tasks and activity
// log) is replaced by ONE mapping of the owner projections, directly below: agents are the transcript
// participants with their verified connection facts, tasks are Work (messages that name a Work,
// through workshopTaskItems, plus the native Work status), the flow is the projected topology, and
// activity is the transcript's tool records. A part with no live source draws the design's own
// absent state. Nothing below the seam is authored data.
(() => {
const W = window.AH;
const derive = build => window.ArchHubTheme ? window.ArchHubTheme.derive(build) : build(W);

// Conversation retention. After 20 idle days a conversation's messages move to
// a file in the user's data folder; this notice says so on the conversation and
// hands the archive back. It reads with a GET, so looking never delays retention.
const archiveDay = seconds => (typeof seconds === 'number' && isFinite(seconds))
  ? new Date(seconds * 1000).toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'})
  : 'an unknown date';
const archiveButton = {padding:'4px 10px', border:`1px solid ${W.line}`, borderRadius:5, background:'transparent',
  color:W.ink, fontFamily:W.sans, fontSize:12, cursor:'pointer', flex:'none'};
const ConversationArchiveNotice = ({ root }) => {
  const [row, setRow] = React.useState(null);
  const [note, setNote] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const load = React.useCallback(() => {
    if (!root || !window.ARCHHUB_CONVERSATION_RETENTION) return;
    window.ARCHHUB_CONVERSATION_RETENTION()
      .then(data => setRow((data.archived || []).find(item => item.conversation === root && item.archived_at) || null))
      .catch(() => setRow(null));
  }, [root]);
  React.useEffect(load, [load]);
  if (!row) return null;
  const act = (call, done) => {
    if (!call) return;
    setBusy(true); setNote('');
    call(row.conversation).then(done).catch(error => setNote(error.message || 'Refused.')).finally(() => setBusy(false));
  };
  const removed = row.removed_messages || 0;
  return (
    <div role="status" style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 12px', border:`1px solid ${W.line}`,
      borderRadius:7, background:W.bgPanel, fontSize:12.5, color:W.inkSoft }}>
      <span style={{ flex:1, minWidth:0 }}>
        Archived on {archiveDay(row.archived_at)}{removed ? ` · ${removed} message${removed === 1 ? '' : 's'} moved to the archive file` : ''}{note ? ` · ${note}` : ''}
      </span>
      <button disabled={busy || !row.archive_exists} style={archiveButton}
        onClick={() => act(window.ARCHHUB_CONVERSATION_ARCHIVE_OPEN, () => setNote('opened in Explorer'))}>Open archive</button>
      <button disabled={busy || !row.archive_exists} style={archiveButton}
        onClick={() => act(window.ARCHHUB_CONVERSATION_RESTORE, result => { setNote(`restored ${result.restored}`); load(); })}>Restore</button>
    </div>
  );
};

// ═══════════════════════════════ LIVE SEAM ═══════════════════════════════
// Work review and Canvas share the authenticated view's durable graph selection.
const workshopSelectionId = value => typeof value === 'string' && value.length > 0 && value.length <= 1024;
const workshopWorkSelectionIdentity = (state, root) => {
  const canvas = state?.canvas, projected = state?.topology?.canvas || canvas;
  const authorization = projected?.authorization;
  if (!canvas || state.error || state.topology?.error ||
      !state.workshops?.some(row => row.root === root) ||
      (state.topology?.canvas && (projected.application_root !== canvas.graph_id ||
        projected.scope?.current !== canvas.root))) return null;
  const key = [authorization?.subject, authorization?.session, canvas.graph_id, canvas.root, root];
  return key.every(workshopSelectionId) ? JSON.stringify(key) : null;
};
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
const admittedWorkshopWork = (state, key, work, nodes) => {
  if (!key || !workshopSelectionId(work) || !nodes.some(node => node.id === work)) return false;
  const [owner, view, , scope, root] = JSON.parse(key), native = state?.nativeWork;
  if (!native || native.owner !== owner || native.view !== view ||
      native.scope !== scope || native.root !== root) return false;
  return native.state === 'idle' ? Array.isArray(native.available_work) && native.available_work.includes(work) :
    native.state !== 'unavailable' && typeof native.state === 'string' && native.work === work;
};
const selectedWorkshopWork = (state, root, nodes = workshopProjectedNodes(state)) => {
  const key = workshopWorkSelectionIdentity(state, root);
  const candidate = state?.nativeWork?.state !== 'idle' ? state?.nativeWork?.work :
    (state?.topology?.selected ?? state?.canvas?.selected);
  return admittedWorkshopWork(state, key, candidate, nodes) ? candidate : '';
};
// Workshop task cards read from the transcript only: a message that names a Work id is an event of that
// Work, and every event of one Work folds into one card at the place its first event appeared. The card's
// state is the verb of its latest event. No progress, tool count or task id is authored.
const WORKSHOP_WORK_REF = /\b((?:assembly-instance|work):[A-Za-z0-9_-]{6,})/;
const WORKSHOP_TASK_STATES = [
  [/\b(fail(?:ed|s)?|refused|rejected|blocked|error|needs? (?:you|review|input|approval))\b/i, 'block'],
  [/^\s*(delivered|accepted|completed|merged)\b/i, 'done'],
  [/^\s*(submitted)\b/i, 'review'],
  [/^\s*(claimed|started|running|working on|assigned)\b/i, 'run'],
];
const workshopTaskItems = (messages, nodes) => {
  const byId = new Map((Array.isArray(nodes) ? nodes : []).map(node => [node.id, node]));
  const cards = new Map(), items = [];
  (Array.isArray(messages) ? messages : []).forEach(message => {
    const match = WORKSHOP_WORK_REF.exec(String(message?.body || ''));
    if (!match) { items.push({kind:'message', message}); return; }
    let card = cards.get(match[1]);
    if (!card) { card = {kind:'task', work:match[1], node:byId.get(match[1]) || null, events:[]}; cards.set(match[1], card); items.push(card); }
    card.events.push(message);
  });
  cards.forEach(card => {
    const latest = String(card.events[card.events.length - 1].body || '');
    card.state = (WORKSHOP_TASK_STATES.find(([pattern]) => pattern.test(latest)) || [null, 'open'])[1];
    const [kind, id] = card.work.split(':');
    card.title = card.node?.title || `${kind} · ${id.slice(0, 8)}`;
    card.owner = card.events[card.events.length - 1].sender_root;
  });
  return items;
};
// One participant tone for the agents rail and the transcript avatars: palette tokens only, chosen from
// the participant root so the same agent keeps its colour.
const workshopAgentTone = (root, self) => {
  if (self) return {bg:W.userAv, fg:W.onUserAv};
  const tones = [W.accent, W.cyan, W.purple, W.blue];
  const bg = tones[[...String(root || '')].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % tones.length];
  return {bg, fg:W.onFill};
};
const wsSeconds = value => !Number.isFinite(value) || value <= 0 ? null : value > 1e12 ? value / 1000 : value;
const wsClockText = (value, seconds) => {
  const at = wsSeconds(value); if (at === null) return '';
  const d = new Date(at * 1000), p = n => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes()) + (seconds ? ':' + p(d.getSeconds()) : '');
};
const wsAgo = value => {
  const s = Math.max(0, Date.now() / 1000 - wsSeconds(value));
  return s < 60 ? Math.round(s) + 's' : s < 3600 ? Math.round(s / 60) + 'm' : s < 86400 ? Math.round(s / 3600) + 'h' : Math.round(s / 86400) + 'd';
};
const wsLine = (text, limit = 140) => {
  const line = String(text || '').split('\n').find(row => row.trim()) || '';
  return line.length > limit ? line.slice(0, limit - 1) + '\u2026' : line;
};
const wsTranscript = (state, descriptor) => {
  const held = state?.workshop;
  return held?.root === descriptor?.root ? held : null;
};
const wsNative = (state, descriptor) => state?.nativeWork?.root === descriptor?.root &&
  state.nativeWork.scope === state?.canvas?.root ? state.nativeWork : null;
const wsObserved = row => typeof row.observed_at === 'number' && Number.isFinite(row.observed_at) && row.observed_at > 0;
const wsVerified = (row, clock) => row.is_agent === true && row.connection_status === 'connected' &&
  row.connection_basis === 'authenticated-request' && wsObserved(row) && typeof row.expires_at === 'number' &&
  Number.isFinite(row.expires_at) && row.expires_at > row.observed_at && row.expires_at > clock;

// Shared by the rail and the view, which render in two different component trees (the design's
// subscribe store): saved agent connections and Session Link disconnect outcomes.
const store = {subs:new Set(), contacts:[], contactsLoading:false, contactError:'', refreshContacts:null,
  pending:{}, outcomes:{}};
const storeChanged = patch => { Object.assign(store, patch); store.subs.forEach(notify => notify()); };
const useStore = () => {
  const [, bump] = React.useState(0);
  React.useEffect(() => { const cb = () => bump(n => n + 1); store.subs.add(cb); return () => store.subs.delete(cb); }, []);
  return store;
};
// Only a confirmed remote revocation reads as disconnected; everything else says what is known.
const wsLinkStatus = row => {
  const outcome = store.outcomes[row.root];
  if (store.pending[row.root]) return 'Disconnecting\u2026';
  if (outcome?.error) return outcome.error;
  if (outcome?.outcome === 'revoked') return 'Session Link disconnected; its grant was revoked';
  if (outcome?.outcome === 'no_channel') return 'No Session Link channel was attached';
  if (outcome?.outcome === 'detached_without_revocation') return 'Channel closed; the host reported no grant to revoke';
  if (outcome?.outcome === 'uncertain' || row.session_link === 'retiring') return 'Disconnect unconfirmed; its grant may still be live. Retry Session Link disconnect.';
  if (row.session_link === 'attached') return 'Session Link attached';
  if (row.session_link === 'attaching') return 'Session Link attaching';
  return '';
};
// Agents: the transcript's agent participants in the design's rail-row shape.
const wsAgents = (transcript, cards, clock) => {
  const rows = (Array.isArray(transcript?.participants) ? transcript.participants : []).filter(row => row.is_agent !== false);
  const messages = Array.isArray(transcript?.messages) ? transcript.messages : [];
  const agents = rows.map(row => {
    const self = row.root === transcript?.self, name = String(row.label || row.root);
    const tone = workshopAgentTone(row.root, self), verified = wsVerified(row, clock);
    const owned = cards.filter(card => card.owner === row.root);
    const latest = [...messages].reverse().find(message => message.sender_root === row.root);
    const status = row.connection_status === 'disconnected' || row.attached === false ? 'off' :
      verified ? (owned.some(card => card.state === 'block') ? 'waiting' : owned.some(card => card.state === 'run') ? 'working' : 'available') :
      row.connection_status === 'stale' || (row.connection_status === 'connected' && wsObserved(row)) ? 'stale' : 'unverified';
    const seen = wsObserved(row) ? new Date(row.observed_at * 1000).toLocaleString() : '';
    return {id:row.root, row, self, name, role:self ? 'YOU' : 'AGENT',
      prov:row.runtime || (row.attached === false ? 'history participant \u00b7 detached' : 'agent session'),
      col:tone.bg, ink:tone.fg, ini:(name.trim().charAt(0) || '?').toUpperCase(), round:self, status,
      ago:status === 'off' && wsObserved(row) ? wsAgo(row.observed_at) : '',
      doing:status === 'off' ? 'Disconnected from this app.' + (seen ? ' Last seen ' + wsClockText(row.observed_at) + '.' : '') :
        latest ? wsLine(latest.body, 90) : seen ? 'Last seen ' + wsClockText(row.observed_at) + '.' : 'No message from this agent on this page.',
      model:row.runtime || 'runtime not projected', seen, verified,
      tools:[row.runtime, row.connection_basis, row.session_link && row.session_link !== 'none' ? 'session link \u00b7 ' + row.session_link : '']
        .filter(Boolean),
      card:owned[owned.length - 1] || null};
  });
  return [...agents.filter(a => a.verified), ...agents.filter(a => !a.verified)];
};
// The rail's default list: agents that are here now (and you). Disconnected sessions stay in the
// graph and in the transcript; they are listed only when asked for.
const WS_SHOW_OFFLINE = '__show-disconnected__';
const wsShownAgents = (agents, showOff) => showOff ? agents : agents.filter(a => a.status !== 'off' || a.self);
const wsParam = (node, pattern) => {
  const row = (node?.params || []).find(param => pattern.test(String(param.k || '')));
  return row && row.v != null && String(row.v).trim() ? String(row.v) : '';
};
// Tasks: Work named in the transcript (workshopTaskItems) plus the native Work status.
const wsTasks = (items, nodes, wires, native, names) => {
  const cards = items.filter(item => item.kind === 'task');
  if (native?.work && !cards.some(card => card.work === native.work)) {
    const node = nodes.find(row => row.id === native.work) || null;
    const [kind, id] = String(native.work).split(':');
    const card = {kind:'task', work:native.work, node, events:[], state:'open', owner:null, nativeOnly:true,
      title:node?.title || (id ? `${kind} · ${id.slice(0, 8)}` : native.work)};
    cards.push(card); items.push(card);
  }
  const titles = new Map(nodes.map(node => [node.id, node.title || node.id]));
  return cards.map(card => {
    const events = card.events, latest = events[events.length - 1] || null;
    const approving = native?.work === card.work && native.state === 'awaiting_approval';
    const running = native?.work === card.work && ['attaching', 'preparing', 'executing', 'recovering'].includes(native.state);
    const state = approving ? 'block' : running ? 'run' : card.state;
    const blocks = [...new Set(wires.filter(wire => wire.from?.[0] === card.work).map(wire => titles.get(wire.to?.[0])).filter(Boolean))];
    const categories = [...new Set(events.map(event => event.category).filter(Boolean))];
    const [, short] = String(card.work).split(':');
    return {id:(short || card.work).slice(0, 8), work:card.work, title:card.title, owner:card.owner, state,
      node:card.node ? card.node.id : null, latest,
      intent:wsParam(card.node, /^(description|intent|summary)$/i) || card.title,
      criteria:wsParam(card.node, /criteri/i) || '\u2014',
      blocks:blocks.length ? blocks.join(' \u00b7 ') : '\u2014',
      lead:latest ? String(latest.body || '') : native?.work === card.work ? 'Native Work status: ' + String(native.state || 'unknown').replaceAll('_', ' ') + '.' : '',
      thread:events.slice(0, -1).map(event => ({root:event.root, from:event.sender_root,
        to:Array.isArray(event.recipient_roots) && event.recipient_roots.length ? event.recipient_roots.map(root => names.get(root) || root).join(', ') : 'Workshop',
        text:String(event.body || '')})),
      approving, events,
      tools:{n:events.length, list:categories.length ? categories.join(' \u00b7 ') : '\u2014',
        t:latest ? (wsClockText(latest.created_at) || String(latest.state || '')) : String(native?.state || '')}};
  });
};
// Flow: the projected topology, laid into the design's three columns by wire depth.
const wsFlow = (nodes, wires, tasks, limit = 12) => {
  const wired = new Set(wires.flatMap(wire => [wire.from?.[0], wire.to?.[0]]));
  const named = new Set(tasks.map(task => task.work));
  const ranked = [...nodes].sort((a, b) => (named.has(b.id) - named.has(a.id)) || (wired.has(b.id) - wired.has(a.id)));
  const shown = ranked.slice(0, limit), ids = new Set(shown.map(node => node.id));
  const edges = wires.filter(wire => ids.has(wire.from?.[0]) && ids.has(wire.to?.[0]) && wire.from[0] !== wire.to[0])
    .map(wire => [wire.from[0], wire.to[0]]);
  const depth = new Map(shown.map(node => [node.id, 0]));
  for (let pass = 0; pass < shown.length; pass += 1) {
    edges.forEach(([a, b]) => { if (depth.get(b) < depth.get(a) + 1) depth.set(b, Math.min(depth.get(a) + 1, shown.length)); });
  }
  const deepest = Math.max(0, ...depth.values());
  const ys = shown.map(node => Number.isFinite(node.y) ? node.y : 0), min = Math.min(...ys, 0), range = Math.max(...ys, 0) - min || 1;
  const flow = shown.map(node => {
    const task = tasks.find(row => row.work === node.id);
    return {id:node.id, t:node.title || node.id, p:String(node.status || node.sub || '\u2014'),
      col:deepest <= 2 ? depth.get(node.id) : Math.min(2, Math.floor(depth.get(node.id) * 3 / (deepest + 1))),
      y:56 + ((Number.isFinite(node.y) ? node.y : 0) - min) / range * 344,
      state:task ? task.state : 'idle'};
  });
  [0, 1, 2].forEach(col => {
    let floor = -Infinity;
    flow.filter(n => n.col === col).sort((a, b) => a.y - b.y).forEach(n => { n.y = Math.round(Math.max(n.y, floor)); floor = n.y + 58; });
  });
  return {flow, wires:edges, more:Math.max(0, nodes.length - shown.length)};
};
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
    color: a.round ? W.onUserAv : (a.status==='off' ? W.inkMuted : (a.ink || W.onFill)),
    display:'grid', placeItems:'center', fontSize:Math.round(s*0.45), fontWeight:600, flex:'none',
    fontFamily:W.sans, opacity: a.status==='off' ? .6 : 1 }}>{a.ini}</span>
);
const Dot = ({ c, pulse }) => <span style={{ width:6, height:6, borderRadius:'50%', background:c, flex:'none', animation: pulse ? 'lmPulse 1.3s infinite' : 'none' }}/>;
const Lbl = ({ children, c }) => <span style={{ fontFamily:W.mono, fontSize:9, letterSpacing:'0.18em', color: c || W.inkMuted }}>{children}</span>;
const Chip = ({ s }) => { const k = CHIP[s] || CHIP.open; return <span style={{ fontFamily:W.mono, fontSize:9, letterSpacing:'0.1em', padding:'2px 6px', borderRadius:3, background:k.bg, color:k.c }}>{k.l}</span>; };
const Mini = ({ children, acc, onClick, title, disabled }) => (
  <span role={onClick ? 'button' : undefined} tabIndex={onClick && !disabled ? 0 : undefined} title={title} aria-pressed={onClick ? !!acc : undefined}
    aria-disabled={onClick && disabled ? 'true' : undefined}
    onClick={disabled ? undefined : onClick} onKeyDown={onClick && !disabled ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e); } } : undefined}
    style={{ display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px', borderRadius:5,
    background: acc ? W.accentDim : W.bg, border:`1px ${disabled ? 'dashed' : 'solid'} ${acc ? W.accentSoft : W.line}`, color: acc ? W.accent : W.inkSoft,
    fontFamily:W.mono, fontSize:10, letterSpacing:'0.04em', cursor: onClick && !disabled ? 'pointer' : 'default' }}>{children}</span>
);
// Disabled controls use a dashed border, never alpha (design DECISIONS.md).
const Btn = ({ children, pri, sm, onClick, disabled, title }) => (
  <button type="button" onClick={onClick} disabled={disabled} title={title} style={{ padding: sm ? '3px 9px' : '5px 12px', borderRadius:5, cursor: disabled ? 'default' : 'pointer', margin:0,
    fontFamily: sm ? W.mono : W.sans, fontSize: sm ? 10.5 : 11.5, fontWeight: pri ? 500 : 400, letterSpacing: sm ? '0.04em' : 0,
    background: pri && !disabled ? W.accent : 'transparent', border:`1px ${disabled ? 'dashed' : 'solid'} ${pri && !disabled ? W.accent : W.line}`,
    color: pri && !disabled ? W.onFill : W.inkSoft }}>{children}</button>
);
// Compact icon button — glyph + tooltip. Icons carry the repeated actions so the surface
// does not fill with labelled buttons; words stay for decisions only.
const IBtn = ({ g, title, acc, on, onClick, s = 24, disabled }) => (
  <button type="button" title={title} aria-label={title} aria-pressed={on === undefined ? undefined : !!on} disabled={disabled}
    onClick={e => { e.stopPropagation(); onClick && onClick(e); }} style={{ width:s, height:s, display:'grid', placeItems:'center', padding:0, margin:0, cursor: disabled ? 'default' : 'pointer',
    borderRadius:5, background: on ? W.accentDim : 'transparent', border:`1px ${disabled ? 'dashed' : 'solid'} ${on ? W.accentSoft : W.line}`,
    color: on || acc ? W.accent : W.inkSoft, fontFamily:W.mono, fontSize:12, lineHeight:1 }}>{g}</button>
);
const PRow = ({ k, v, c, last }) => (
  <div style={{ display:'flex', justifyContent:'space-between', gap:10, padding:'5px 0', borderBottom: last ? 0 : `1px solid ${W.lineSoft}`, fontSize:11.5 }}>
    <span style={{ fontFamily:W.mono, fontSize:10, letterSpacing:'0.04em', color:W.inkMuted }}>{k}</span>
    <span style={{ color: c || W.ink, textAlign:'right', overflowWrap:'anywhere' }}>{v}</span>
  </div>
);
const agentOf = (agents, names, self, root) => {
  const found = agents.find(a => a.id === root);
  if (found) return found;
  const name = String(names.get(root) || root || 'Workshop'), tone = workshopAgentTone(root, root === self);
  return {id:root, name, col:tone.bg, ink:tone.fg, ini:(name.trim().charAt(0) || '?').toUpperCase(), round:root === self, status:'available', tools:[]};
};
// ── task card: the container for its own thread ──
const TaskCard = ({ t, sel, onSelect, onDecide, compact, agent, busy }) => {
  const [open, setOpen] = React.useState(false);
  const [all, setAll] = React.useState(false);
  const [detail, setDetail] = React.useState(null);   // 'diff' | 'notes'
  const o = agent(t.owner);
  const thread = all ? t.thread : t.thread.slice(0, 2);
  return (
    <div data-workshop-task={t.work} data-workshop-message={t.latest ? t.latest.root : undefined} aria-current={sel ? 'true' : undefined}
      onClick={() => onSelect(t.work)} style={{ background:W.bgPanel, borderRadius:9, cursor:'pointer',
      borderWidth:1, borderStyle: t.state==='queued' ? 'dashed' : 'solid', borderColor: t.state==='block' ? CHIP.BLOCK_EDGE : W.line,
      opacity: t.state==='queued' ? .75 : 1, boxShadow: sel ? `0 0 0 3px ${W.accent}1a` : 'none', overflow:'hidden' }}>
      <div style={{ display:'flex', alignItems:'center', gap:9, padding:'10px 13px', borderBottom:`1px solid ${W.lineSoft}`, flexWrap:'wrap' }}>
        <Dot c={(CHIP[t.state] || CHIP.open).c} pulse={t.state==='run'}/>
        <span title={t.work} style={{ fontFamily:W.mono, fontSize:9.5, letterSpacing:'0.1em', color:W.inkMuted }}>{t.id}</span>
        <span style={{ fontSize:13, fontWeight:500, letterSpacing:'-0.005em', overflowWrap:'anywhere' }}>{t.title}</span>
        {t.owner && <Av a={o} s={18}/>}
        <div style={{ flex:1 }}/>
        <Chip s={t.state}/>
      </div>
      <div style={{ padding:'11px 13px', display:'flex', flexDirection:'column', gap:12 }}>
        {t.artifact && (
          <div style={{ display:'flex', gap:11, flexWrap:'wrap' }}>
            <div style={{ width: compact ? '100%' : 150, height:88, borderRadius:6, border:`1px solid ${W.lineSoft}`, display:'grid', placeItems:'center', flex:'none',
              background:`repeating-linear-gradient(135deg,${W.bgInk} 0 6px,${W.bgSoft} 6px 12px)` }}>
              <span style={{ fontFamily:W.mono, fontSize:9.5, letterSpacing:'0.1em', color:W.inkMuted }}>DRAFT PATCH</span>
            </div>
            <div style={{ flex:'1 1 170px', minWidth:170, fontSize:12.5, lineHeight:1.55, color:W.inkSoft, overflowWrap:'anywhere' }}>{t.artifact.name}
              <div style={{ display:'flex', gap:6, marginTop:10, flexWrap:'wrap' }}>
                <IBtn g="⇄" title="What changed — size and digest of the draft patch" on={detail==='diff'} onClick={() => setDetail(detail==='diff' ? null : 'diff')}/>
                <IBtn g="✎" title="Review notes — the artifact summary" on={detail==='notes'} onClick={() => setDetail(detail==='notes' ? null : 'notes')}/>
                <IBtn g="↓" title="Download patch" disabled={busy || !t.artifact.download} onClick={() => t.artifact.download && t.artifact.download()}/>
              </div>
              {detail === 'diff' && (
                <div style={{ marginTop:9, fontFamily:W.mono, fontSize:10.5, lineHeight:1.8, color:W.inkMuted, overflowWrap:'anywhere' }}>
                  + {t.artifact.bytes} bytes<br/>SHA-256 {t.artifact.digest}<br/>Draft only · review and verify before applying
                </div>
              )}
              {detail === 'notes' && (
                <div style={{ marginTop:9, display:'flex', flexDirection:'column', gap:7, fontSize:11.5, lineHeight:1.5 }}>
                  <div>{t.artifact.summary || 'No summary was recorded with this patch.'}</div>
                </div>
              )}
            </div>
          </div>
        )}
        {t.lead && <div style={{ display:'flex', gap:9, fontSize:12.5, lineHeight:1.55, color:W.inkSoft, overflowWrap:'anywhere' }}>{t.owner && <Av a={o} s={18}/>}<div>{t.owner && <><b style={{ color:W.ink, fontWeight:500 }}>{o.name}</b> · </>}{t.lead}</div></div>}
        {thread.length > 0 && (
          <div style={{ marginLeft:compact ? 0 : 27, paddingLeft:13, borderLeft:`1px solid ${W.lineSoft}`, display:'flex', flexDirection:'column', gap:11 }}>
            {thread.map((m, i) => { const f = agent(m.from); return (
              <div key={m.root || i} style={{ display:'flex', gap:9, fontSize:12.5, lineHeight:1.55, color:W.inkSoft, overflowWrap:'anywhere' }}>
                <Av a={f} s={18}/>
                <div><b style={{ color:W.ink, fontWeight:500 }}>{f.name} → {m.to}</b> · {m.text}</div>
              </div> ); })}
            {t.thread.length > 2 && (
              <span role="button" tabIndex={0} onClick={e => { e.stopPropagation(); setAll(!all); }} style={{ fontFamily:W.mono, fontSize:10, color:W.accent, cursor:'pointer' }}>
                {all ? '▴ collapse thread' : `▾ ${t.thread.length - 2} more in this thread`}
              </span>
            )}
          </div>
        )}
        {t.decision && (
          <div style={{ display:'flex', gap:7, flexWrap:'wrap' }}>
            {t.decision.map((d, i) => <Btn key={d.label} pri={i===0} disabled={d.disabled} onClick={e => { e.stopPropagation(); onDecide(t.work, d); }}>{d.label}</Btn>)}
          </div>
        )}
      </div>
      <div style={{ display:'flex', alignItems:'center', gap:9, padding:'8px 13px', borderTop:`1px solid ${W.lineSoft}`, background:W.bgSoft, flexWrap:'wrap',
        fontFamily:W.mono, fontSize:10, letterSpacing:'0.04em', color:W.inkMuted }}>
        <span onClick={e => { e.stopPropagation(); setOpen(!open); }} title="Events on this Work" style={{ color:W.inkSoft, cursor:'pointer' }}>{open ? '▾' : '▸'} ⇄ {t.tools.n}</span>
        <span>{open ? t.tools.list : t.tools.list.split(' · ')[0] + ' …'}</span>
        <div style={{ flex:1 }}/><span>{t.tools.t}</span>
      </div>
    </div>
  );
};

// ── agents rail (replaces the Nodes Library while Workshop is open) ──
const AgentsRail = ({ context, sel, onSelect, onAddAgent, compact }) => {
  useStore();
  const {descriptor, graphId, scopeRoot, transcript:held, state} = context;
  const transcript = held?.root === descriptor.root && held.graph_id === graphId &&
    held.scope_root === scopeRoot && !held.error ? held : null;
  const [now, setNow] = React.useState(() => Date.now() / 1000);
  const clock = Math.max(now, Date.now() / 1000);
  const nodes = workshopProjectedNodes(state);
  const items = workshopTaskItems(transcript?.messages, nodes);
  const names = new Map((transcript?.participants || []).map(row => [row.root, row.label]));
  const tasks = wsTasks(items, nodes, workshopProjectedWires(state), wsNative(state, descriptor), names);
  const agents = wsAgents(transcript, tasks, clock);
  const expiries = agents.filter(a => a.verified).map(a => a.row.expires_at);
  const expiry = expiries.length ? Math.min(...expiries) : null;
  React.useEffect(() => {
    if (expiry === null) return;
    const timer = setTimeout(() => setNow(Date.now() / 1000),
      Math.min(2147483647, Math.max(1, (expiry - Date.now() / 1000) * 1000 + 1)));
    return () => clearTimeout(timer);
  }, [expiry, now]);
  const all = transcript?.participants || [];
  const canAddress = row => row.attached === true && row.root !== transcript?.self &&
    all.some(participant => participant.root === transcript?.self && participant.attached === true) &&
    transcript?.can_send !== false;
  // Only agents that are here now are listed; a disconnected session is history, one toggle away.
  // Nothing is removed from the graph.
  const [showOff, setShowOff] = React.useState(false);
  const offCount = agents.filter(a => a.status === 'off' && !a.self).length;
  const shown = wsShownAgents(agents, showOff);
  const current = shown.some(a => a.id === sel) ? sel : shown[0]?.id;
  return (
  <section aria-label="Workshop agents" style={{ background:W.bgPanel, borderRight:`1px solid ${W.line}`, overflow:'auto', display:'flex', flexDirection:'column', minHeight:0 }} className="ah-scroll">
    <div style={{ padding:'9px 12px 9px 14px', borderBottom:`1px solid ${W.lineSoft}`, display:'flex', alignItems:'center', gap:8 }}>
      <Lbl>CONNECTED AGENTS</Lbl><div style={{ flex:1 }}/>
      {onAddAgent && <IBtn g="＋" title="Connect another agent — opens the node library" s={22} onClick={onAddAgent}/>}
    </div>
    {!transcript && <p role="status" style={{ fontSize:11.5, lineHeight:1.4, color:W.inkSoft, padding:'9px 14px', margin:0 }}>No live agent data for this Workshop. Waiting for its current connection status.</p>}
    {transcript && !agents.length && <p role="status" style={{ fontSize:11.5, lineHeight:1.4, color:W.inkSoft, padding:'9px 14px', margin:0 }}>No agent has joined this Workshop.</p>}
    {transcript && agents.length > 0 && !shown.length && <p role="status" style={{ fontSize:11.5, lineHeight:1.4, color:W.inkSoft, padding:'9px 14px', margin:0 }}>No agent is connected right now.</p>}
    {shown.map(a => { const s = ST[a.status]; const on = current === a.id; const addressable = canAddress(a.row); return (
      <div key={a.id} role="button" tabIndex={0} aria-pressed={on} data-workshop-agent={a.id}
        title={[a.id, addressable ? 'Select, and address messages to this agent' : 'Select', a.seen ? 'Last seen: ' + a.seen : ''].filter(Boolean).join('\n')}
        onClick={() => onSelect(a.id, addressable)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(a.id, addressable); } }}
        style={{ display:'flex', gap:9, padding:'9px 14px', cursor:'pointer',
        borderBottom:`1px solid ${W.lineSoft}`, background: on ? W.bgSoft : 'transparent', boxShadow: on ? `inset 2px 0 0 ${W.accent}` : 'none',
        opacity: a.status==='off' ? .55 : 1 }}>
        <Av a={a} s={compact ? 22 : 28}/>
        <div style={{ minWidth:0, flex:1 }}>
          <div style={{ display:'flex', alignItems:'center', gap:6, flexWrap:'wrap' }}>
            <span style={{ fontSize:12.5, fontWeight:500, letterSpacing:'-0.005em', overflowWrap:'anywhere' }}>{a.name}</span>
            <span style={{ fontFamily:W.mono, fontSize:8.5, letterSpacing:'0.12em', padding:'1px 5px', borderRadius:3, border:`1px solid ${W.line}`, color:W.inkMuted }}>{a.role}</span>
          </div>
          <div role={store.pending[a.id] || store.outcomes[a.id] ? 'status' : undefined} style={{ fontFamily:W.mono, fontSize:9.5, color:W.inkMuted, letterSpacing:'0.03em', marginTop:2, overflowWrap:'anywhere' }}>{a.prov}</div>
          {!compact && <>
            <div style={{ display:'flex', alignItems:'center', gap:5, marginTop:5, fontFamily:W.mono, fontSize:9, letterSpacing:'0.1em', color:s.col }}>
              <Dot c={s.col} pulse={s.pulse}/>{s.label}{a.ago ? ` · ${a.ago}` : ''}
            </div>
            <div style={{ fontSize:11.5, color:W.inkSoft, lineHeight:1.4, marginTop:5, overflowWrap:'anywhere' }}>{a.doing}</div>
            {a.status==='off' && store.refreshContacts && <span role="button" tabIndex={0} onClick={e => { e.stopPropagation(); store.refreshContacts(); }} title="Refresh connection status" style={{ fontFamily:W.mono, fontSize:13, color:W.accent, cursor:'pointer', display:'inline-block', marginTop:6 }}>⟳</span>}
          </>}
        </div>
      </div> ); })}
    {offCount > 0 && <button type="button" data-workshop-disconnected-toggle="" aria-pressed={showOff}
      onClick={() => setShowOff(value => !value)}
      style={{ margin:'8px 14px', alignSelf:'flex-start', fontFamily:W.mono, fontSize:10, letterSpacing:'0.06em',
        color:W.inkMuted, background:'transparent', border:`1px solid ${W.line}`, borderRadius:4, padding:'3px 8px', cursor:'pointer' }}>
      {showOff ? 'Hide disconnected' : `Show disconnected (${offCount})`}
    </button>}
    <div style={{ flex:1 }}/>
    <div style={{ padding:'11px 14px', borderTop:`1px solid ${W.lineSoft}` }}>
      <Lbl>SCOPE</Lbl>
      <div style={{ fontSize:11.5, color:W.inkSoft, lineHeight:1.5, marginTop:7 }}>Write access: <b style={{ color:W.ink, fontWeight:500 }}>not projected</b> for these agents. Recent activity is not a running task.</div>
    </div>
  </section>
  );
};

// ── live graph pane (preset C) ── geometry is expressed in PERCENT of the pane, so it fits
// the narrow in-app column and a wide window alike with no measurement step to go wrong.
// Columns: left 4/38/72 %, width 24% → right edges 28/62/96 %.
const COL_L = c => 4 + c * 34, COL_R = c => COL_L(c) + 24;
const GraphPane = ({ flow, selTask, tidy, chain, onArrange, onChain, onOpen }) => {
  const NH = 46;
  const nodes = flow.flow;
  const st = id => { const n = nodes.find(x => x.id === id); return n ? n.state : 'idle'; };
  const col = s => s==='block' ? W.err : s==='run' ? W.accent : s==='paused' ? W.err : s==='done' ? W.ok : s==='review' ? W.cyan : W.inkMuted;
  const pos = id => nodes.find(n => n.id === id);
  // Arrange: tidy each column into an even stack. Same nodes, same wires — only layout.
  const Y = n => tidy ? 56 + nodes.filter(m => m.col === n.col).indexOf(n) * 104 : n.y;
  const wired = new Set(flow.wires.flat());
  const lit = id => {
    if (chain) return wired.has(id);          // the whole connected chain
    return !!selTask && id === selTask;       // just the selected task's node
  };
  const into = flow.wires.length ? pos(flow.wires[0][1]) : null;
  return (
    <section aria-label="Workshop live graph" style={{ position:'relative', background:W.bgCanvas, borderLeft:`1px solid ${W.line}`, overflow:'hidden' }}>
      <div style={{ position:'absolute', inset:0, opacity:.55,
        backgroundImage:`linear-gradient(${W.lineSoft} 1px,transparent 1px),linear-gradient(90deg,${W.lineSoft} 1px,transparent 1px)`, backgroundSize:'40px 40px' }}/>
      {flow.wires.map(([a, b], i) => {
        const p = pos(a), q = pos(b);
        const acc = st(a)==='run' || st(b)==='run';
        if (p.col === q.col) {
          const y1 = Y(p) + NH/2, y2 = Y(q) + NH/2, top = Math.min(y1, y2), h = Math.max(Math.abs(y2 - y1), 2);
          const ya = y1 <= y2 ? 0 : h, yb = y1 <= y2 ? h : 0;
          return (
            <svg key={i} width="4%" height={h} viewBox={`0 0 100 ${h}`} preserveAspectRatio="none"
              style={{ position:'absolute', left:`${COL_R(p.col)}%`, top, overflow:'visible' }} fill="none">
              <path d={`M0 ${ya} C 100 ${ya}, 100 ${yb}, 0 ${yb}`} stroke={acc ? W.accent : CHIP.WIRE} strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
            </svg>
          );
        }
        const fwd = q.col > p.col;
        const from = fwd ? p : q, dest = fwd ? q : p;
        const l = COL_R(from.col), r = COL_L(dest.col);
        const y1 = Y(from) + NH/2, y2 = Y(dest) + NH/2;
        const top = Math.min(y1, y2), h = Math.max(Math.abs(y2 - y1), 2);
        const ya = y1 <= y2 ? 0 : h, yb = y1 <= y2 ? h : 0;
        return (
          <svg key={i} width={`${r - l}%`} height={h} viewBox={`0 0 100 ${h}`} preserveAspectRatio="none"
            style={{ position:'absolute', left:`${l}%`, top, overflow:'visible' }} fill="none">
            <path d={`M0 ${ya} C 45 ${ya}, 55 ${yb}, 100 ${yb}`} stroke={acc ? W.accent : CHIP.WIRE} strokeWidth="1.5"
              vectorEffect="non-scaling-stroke"/>
          </svg>
        );
      })}
      <div style={{ position:'absolute', top:12, left:12, display:'flex', gap:6, zIndex:3, alignItems:'center' }}>
        <IBtn g="▦" title="Arrange — tidy each column into an even stack" on={tidy} onClick={onArrange}/>
        <IBtn g="⎇" title="Select the whole connected chain" on={chain} onClick={onChain}/>
        {onOpen && <IBtn g="⌗" title="Open as nodes" onClick={onOpen}/>}
        <Mini acc>live</Mini>
      </div>
      {nodes.map(n => { const s = n.state; return (
        <div key={n.id} data-node={n.id} aria-current={lit(n.id) ? 'true' : undefined} style={{ position:'absolute', left:`${COL_L(n.col)}%`, top:Y(n), width:'24%', maxWidth:170, padding:'8px 10px', borderRadius:7, transition:'top .18s',
          background:W.bgPanel, border:`1px solid ${lit(n.id) ? W.accent : (s==='block' ? CHIP.BLOCK_EDGE : W.line)}`,
          boxShadow: lit(n.id) ? `0 0 0 3px ${W.accent}1a` : 'none', overflowWrap:'anywhere' }}>
          <div style={{ fontSize:11.5, fontWeight:500, letterSpacing:'-0.005em' }}>{n.t}</div>
          <div style={{ fontFamily:W.mono, fontSize:9, letterSpacing:'0.04em', marginTop:3, color: s==='idle' ? W.inkMuted : col(s) }}>{n.p}</div>
        </div> ); })}
      <div role={nodes.length ? undefined : 'status'} style={{ position:'absolute', bottom:12, left:12, right:12, zIndex:3, background:W.bgPanel + 'eb',
        border:`1px solid ${W.line}`, borderRadius:7, padding:'9px 11px', fontSize:11.5, lineHeight:1.5, color:W.inkSoft }}>
        {!nodes.length ? 'No topology projection is held for this scope.' : <>
          Wires carry behaviour.{into ? <> Removing the wire into <b style={{ color:W.ink, fontWeight:500 }}>{into.t}</b> stops what it receives;</> : ''} editing a parameter marks everything downstream stale.
          {flow.more > 0 && ` ${flow.more} more on the Canvas.`}</>}
      </div>
    </section>
  );
};

// ── context panel ──
const ContextPanel = ({ selAgent, selTask, tasks, agent, descriptor, activity, activityNote, counts, listening, controls, controlsOpen, onControls }) => {
  const t = tasks.find(x => x.work === selTask);
  const a = selAgent;
  const showTask = !!t;
  const o = showTask ? (t.owner ? agent(t.owner) : null) : a;
  const facts = o && o.row ? o.row : null;
  const tools = o ? o.tools || [] : [];
  const current = showTask ? t : a ? a.card : null;
  const label = showTask ? `SELECTED · TASK ${t.id}` : a ? 'SELECTED · AGENT' : 'SELECTED · WORKSHOP';
  const who = o || {name:descriptor.label, col:W.accent, ink:W.onFill, ini:(String(descriptor.label || 'W').trim().charAt(0) || 'W').toUpperCase()};
  return (
    <aside aria-label="Workshop context" className="ah-scroll" style={{ background:W.bgPanel, borderLeft:`1px solid ${W.line}`, overflow:'auto', minHeight:0 }}>
      <div style={{ padding:'11px 16px', borderBottom:`1px solid ${W.lineSoft}`, display:'flex', alignItems:'center', gap:8 }}>
        <Lbl>{label}</Lbl><div style={{ flex:1 }}/>
        <span style={{ margin:'-6px 0', display:'inline-flex' }}>
          <IBtn g="⋯" s={22} on={controlsOpen} onClick={onControls}
            title="Workshop controls — history, agent connection, Work on a project"/>
        </span>
      </div>
      {controlsOpen ? controls : <>
      <div style={{ padding:'13px 16px', borderBottom:`1px solid ${W.lineSoft}`, display:'flex', gap:10, alignItems:'flex-start' }}>
        <Av a={who} s={28}/>
        <div style={{ minWidth:0 }}><div style={{ fontSize:14, fontWeight:500, overflowWrap:'anywhere' }}>{showTask ? t.title : a ? a.name : descriptor.label}</div>
          <div style={{ fontFamily:W.mono, fontSize:9.5, color:W.inkMuted, marginTop:2, overflowWrap:'anywhere' }}>{showTask ? `owner: ${o ? o.name : 'not named on this page'}` : a ? `${a.role.toLowerCase()} · ${a.model}` : `${listening} listening`}</div></div>
      </div>
      <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}`, fontSize:12, lineHeight:1.55, color:W.inkSoft, overflowWrap:'anywhere' }}>
        {showTask ? (t.lead || 'No event names this Work on this page.') : a ? a.doing : 'Select an agent in the rail or a task card to see it here.'}
      </div>
      <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}` }}>
        <Lbl>{showTask ? 'TASK' : a ? 'CURRENT TASK' : 'TASKS'}</Lbl>
        <div style={{ marginTop:8 }}>
          {!showTask && !a ? <>
            <PRow k="needs you" v={counts.block} c={counts.block ? W.err : W.inkMuted}/>
            <PRow k="running" v={counts.run} c={counts.run ? W.warn : W.inkMuted}/>
            <PRow k="submitted" v={counts.review} c={counts.review ? W.cyan : W.inkMuted}/>
            <PRow k="delivered" v={counts.done} c={counts.done ? W.ok : W.inkMuted} last/>
          </> : <>
            <PRow k="intent" v={current ? current.intent : '—'}/>
            <PRow k="criteria" v={current ? current.criteria : '—'}/>
            <PRow k="blocks" v={current ? current.blocks : '—'}/>
            <PRow k="state" v={current ? (CHIP[current.state] || CHIP.open).l : '—'} c={current ? (CHIP[current.state] || CHIP.open).c : W.inkMuted} last/>
          </>}
        </div>
      </div>
      <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}` }}>
        <Lbl>PERMISSIONS</Lbl>
        <div style={{ marginTop:8 }}>
          {facts ? <>
            <PRow k="read" v={facts.attached === false ? 'history only · detached' : 'this Workshop'}/>
            <PRow k="write" v="not projected" c={W.inkMuted}/>
            <PRow k="gate" v={wsLinkStatus(facts) || 'no Session Link channel'} last/>
          </> : <div style={{ fontSize:11.5, lineHeight:1.5, color:W.inkSoft }}>No participant is named for this selection, so no permission is projected.</div>}
        </div>
      </div>
      <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}` }}>
        <Lbl>CONNECTED TOOLS</Lbl>
        {tools.length ? <div style={{ display:'flex', flexWrap:'wrap', gap:6, marginTop:8 }}>{tools.map(x => <Mini key={x}>{x}</Mini>)}</div> :
          <div style={{ fontSize:11.5, lineHeight:1.5, color:W.inkSoft, marginTop:8 }}>No tools are projected for this {showTask ? 'task' : a ? 'agent' : 'Workshop'}.</div>}
      </div>
      <div style={{ padding:'12px 16px' }}>
        <Lbl>ACTIVITY · TOOL RECORDS</Lbl>
        {activity.length ? <div style={{ fontFamily:W.mono, fontSize:10, lineHeight:1.9, color:W.inkMuted, marginTop:8, overflowWrap:'anywhere' }}>
          {activity.map((row, i) => <React.Fragment key={row.root || i}>{i > 0 && <br/>}{row.at ? row.at + ' ' : ''}{row.dir} {row.text}</React.Fragment>)}
        </div> : <div style={{ fontSize:11.5, lineHeight:1.5, color:W.inkSoft, marginTop:8 }}>{activityNote}</div>}
      </div>
      </>}
    </aside>
  );
};
// ── the view ──
const WorkshopView = ({ state, descriptor, target, setTarget, setMode, setFocusId, onLeave, sel, setSel, externalRail }) => {
  useStore();
  const authority = window.ARCHHUB_STUDIO_AUTHORITY || window.ARCHHUB_EXISTING_WORKSHOP;
  const existing = !window.ARCHHUB_STUDIO_AUTHORITY;
  const nativeAvailable = existing && descriptor.native_work_available !== false;
  const transcript = wsTranscript(state, descriptor);
  const [preset, setPreset] = React.useState('conversation');   // conversation · board · graph
  const [ownSel, setOwnSel] = React.useState({ agent:null, task:null });
  const S = sel || ownSel, setS = setSel || setOwnSel;
  const [tidy, setTidy] = React.useState(false);
  const [chain, setChain] = React.useState(false);
  const [controlsOpen, setControlsOpen] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const [paging, setPaging] = React.useState(false);
  const pageIntent = React.useRef(0);
  const messageViewport = React.useRef(null), messageContent = React.useRef(null);
  const [awayFromLatest, setAwayFromLatest] = React.useState(false);
  const messageScroll = React.useRef(null), latestJump = React.useRef(false);
  if (!messageScroll.current) messageScroll.current = createWorkshopMessageScroll(setAwayFromLatest);
  const [draft, setDraft] = React.useState('');
  const [messageTextSize, setMessageTextSize] = React.useState(13.5); // the design's message size until chosen under ⋯
  const [execution, setExecution] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const busyRef = React.useRef(false);
  const mounted = React.useRef(true);
  const fileIntent = React.useRef(0);
  // Retention: the first read after a person navigates to a room is an explicit
  // open (open=1), marked BEFORE the request so a failed open is never retried
  // as one. Timer polls and reads after an error are never opens.
  const openedRoot = React.useRef('');
  const [actionError, setActionError] = React.useState('');
  const [nativeSyncError, setNativeSyncError] = React.useState('');
  const projectedWorkNodes = workshopProjectedNodes(state);
  const nativeTarget = selectedWorkshopWork(state, descriptor.root, projectedWorkNodes);
  const setNativeTarget = async work => {
    const key = workshopWorkSelectionIdentity(state, descriptor.root);
    if (!admittedWorkshopWork(state, key, work, projectedWorkNodes)) throw new Error('Choose a currently admitted Work.');
    setPublicReview(false);
    if (existing) await authority.selectTopology(work);
    else await authority.select(work);
  };
  const [publicReview, setPublicReview] = React.useState(false);
  const [repair, setRepair] = React.useState({title:'', description:'', criterion:'', verification:'', path:'', model:'nex-agi/nex-n2.5-pro:free'});
  const [sourceFile, setSourceFile] = React.useState(null);
  const [readingFile, setReadingFile] = React.useState(false);
  const [creationUncertain, setCreationUncertain] = React.useState(false);
  const [revisionBase, setRevisionBase] = React.useState(null);
  // Founder correction of one OPEN Work's acceptance gate, on the same Work.
  const [gateEditor, setGateEditor] = React.useState(null);
  const gateEditorFrom = (read, prior = null) => {
    const spec = read.requirements.gate?.spec;
    const currentPath = typeof spec?.path === 'string' ? spec.path : '';
    const keep = {};
    if (Array.isArray(spec?.args)) keep.args = spec.args;
    if (typeof spec?.timeout_seconds === 'number') keep.timeout_seconds = spec.timeout_seconds;
    return {work:read.work, target:read.target, digest:read.digest, revision:read.revision, state:read.state,
      editable:read.editable, wired:read.wired, kind:read.requirements.gate?.kind || '',
      currentPath, path:currentPath, keep, result:prior?.result || null,
      submission:null, uncertain:false, refreshPending:false};
  };
  const openGateEditor = async work => {
    if (busyRef.current || !work) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try {
      const read = await authority.readWorkRequirements(descriptor.root, work);
      if (!scopeCurrent()) return;
      setGateEditor(value => {
        const next = gateEditorFrom(read, value?.work === work ? value : null);
        // An ordinary read cannot prove which correction produced this gate.
        // Retain the exact request until its receipt or explicit discard.
        if (value?.work === work && value.submission) {
          return {...next, path:value.submission.gate.spec.path, submission:value.submission, uncertain:true, checked:true};
        }
        return next;
      });
    } catch (error) { if (scopeCurrent()) setActionError(error.message || 'The Work requirements could not be read.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const saveGate = async event => {
    event.preventDefault();
    const edit = gateEditor;
    if (busyRef.current || !edit || !edit.editable || edit.refreshPending) return;
    const path = edit.submission ? edit.submission.gate.spec.path : edit.path.trim();
    if (!path || (!edit.submission && path === edit.currentPath)) return;
    const submission = edit.submission || {revision_id:window.crypto.randomUUID().replaceAll('-', ''),
      expected_revision:edit.revision, expected_target:edit.target, expected_digest:edit.digest,
      gate:{kind:'pytest', spec:{...edit.keep, path, selector:path}}};
    busyRef.current = true; setBusy(true); setActionError('');
    // Hold the exact correction before sending; an uncertain save is retried unchanged.
    setGateEditor(value => ({...value, submission, uncertain:false}));
    let saved;
    try {
      saved = await authority.reviseWorkRequirements(descriptor.root, edit.work, submission);
    } catch (error) {
      if (scopeCurrent()) {
        setGateEditor(value => ({...value, submission, uncertain:true}));
        setActionError((error.message || 'The corrected gate was not confirmed.') +
          ' Retry sends this same correction. Reopen to inspect the current gate; only the correction receipt confirms this attempt.');
      }
      busyRef.current = false; if (mounted.current) setBusy(false);
      return;
    }
    try {
      if (!scopeCurrent()) return;
      setGateEditor(value => ({...value, submission:null, uncertain:false, refreshPending:true,
        result:saved.requirements_revision}));
      const reopened = await authority.readWorkRequirements(descriptor.root, edit.work);
      if (!scopeCurrent()) return;
      setGateEditor(value => gateEditorFrom(reopened, value));
      try { await authority.refreshWorkshop(descriptor.root); await authority.refreshTopologyCanvas(); }
      catch (_) { setActionError('The corrected gate is saved. Refresh the Workshop and canvas to display the updated value.'); }
    } catch (_) {
      if (scopeCurrent()) setActionError('The corrected gate is saved, but this editor could not reload it. Reopen the current gate before making another change.');
    } finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  // Founder configuration of an OPEN Work's inputs, requirements and CDE, on the same Work.
  const [configEditor, setConfigEditor] = React.useState(null);
  const configLines = raw => raw.split('\n').map(line => line.trim()).filter(Boolean);
  const configEditorFrom = (current, prior = null) => {
    const value = name => current.fields[name].value;
    const cde = value('cde-container'), requirements = value('requirements'), inputs = value('inputs');
    return {work:current.work, revision:current.revision, fields:current.fields, state:current.state,
      drafts:current.drafts || [], invalidDrafts:current.invalid_drafts || [], draft:null, baselineFields:current.fields,
      editable:current.editable, artifactReady:current.artifact_ready, blocker:current.artifact_blocker || '',
      purpose:prior?.purpose || 'general',
      allowedPaths:Array.isArray(cde?.allowed_paths) ? cde.allowed_paths.join('\n') : '',
      reviewers:Array.isArray(requirements?.artifact_reviewers) ? requirements.artifact_reviewers.join('\n') : '',
      publicInputs:inputs?.data_class === 'public-text',
      result:prior?.result || null, submission:null, uncertain:false, checked:false, refreshPending:false};
  };
  const configChanges = edit => {
    const fields = edit.draft ? {...edit.draft.fields} : {};
    const entry = (name, value) => ({expected_target:edit.fields[name].target,
      expected_digest:edit.fields[name].digest, value});
    const cde = edit.fields['cde-container'].value, requirements = edit.fields.requirements.value;
    const inputs = edit.fields.inputs.value;
    const paths = configLines(edit.allowedPaths), reviewers = configLines(edit.reviewers);
    if (JSON.stringify(paths) !== JSON.stringify(Array.isArray(cde?.allowed_paths) ? cde.allowed_paths : [])) {
      fields['cde-container'] = entry('cde-container', {...(cde || {}), allowed_paths:paths});
    }
    const currentReviewers = Array.isArray(requirements?.artifact_reviewers) ? requirements.artifact_reviewers : [];
    if (JSON.stringify(reviewers) !== JSON.stringify(currentReviewers)) {
      const next = {...(requirements || {})};
      if (reviewers.length) next.artifact_reviewers = reviewers; else delete next.artifact_reviewers;
      fields.requirements = entry('requirements', next);
    }
    if (edit.publicInputs !== (inputs?.data_class === 'public-text')) {
      const next = {...(inputs || {})};
      if (edit.publicInputs) next.data_class = 'public-text'; else delete next.data_class;
      fields.inputs = entry('inputs', next);
    }
    return fields;
  };
  const reviewConfigDraft = revisionId => {
    setConfigEditor(edit => {
      const draft = edit.drafts.find(item => item.revision_id === revisionId);
      const fields = {...edit.baselineFields};
      if (draft) Object.entries(draft.fields).forEach(([name, entry]) => {
        fields[name] = {...fields[name], value:entry.value};
      });
      const cde = fields['cde-container'].value, requirements = fields.requirements.value;
      return {...edit, fields, draft:draft || null, purpose:draft?.purpose || 'general',
        allowedPaths:(cde?.allowed_paths || []).join('\n'),
        reviewers:(requirements?.artifact_reviewers || []).join('\n'),
        publicInputs:fields.inputs.value?.data_class === 'public-text', result:null};
    });
  };
  const openConfigEditor = async work => {
    if (busyRef.current || !work) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try {
      const current = await authority.readWorkConfiguration(descriptor.root, work);
      if (!scopeCurrent()) return;
      setConfigEditor(value => {
        const next = configEditorFrom(current, value?.work === work ? value : null);
        // An unconfirmed configuration keeps its exact identity until it is retried or discarded.
        if (value?.work === work && value.submission) {
          return {...next, submission:value.submission, uncertain:true, checked:true};
        }
        return next;
      });
    } catch (error) { if (scopeCurrent()) setActionError(error.message || 'The Work configuration could not be read.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const saveConfiguration = async event => {
    event.preventDefault();
    const edit = configEditor;
    if (busyRef.current || !edit || !edit.editable || edit.refreshPending || edit.draft?.stale) return;
    const fields = edit.submission ? null : configChanges(edit);
    if (!edit.submission && !Object.keys(fields).length) return;
    const unchangedDraft = edit.draft && edit.purpose === edit.draft.purpose &&
      JSON.stringify(fields) === JSON.stringify(edit.draft.fields);
    const submission = edit.submission || {revision_id:unchangedDraft ? edit.draft.revision_id :
      window.crypto.randomUUID().replaceAll('-', ''),
      expected_revision:unchangedDraft ? edit.draft.expected_revision : edit.revision, purpose:edit.purpose, fields};
    busyRef.current = true; setBusy(true); setActionError('');
    setConfigEditor(value => ({...value, submission, uncertain:false}));
    let saved;
    try {
      saved = await authority.configureWork(descriptor.root, edit.work, submission);
    } catch (error) {
      if (scopeCurrent()) {
        setConfigEditor(value => ({...value, submission, uncertain:true}));
        setActionError((error.message || 'The Work configuration was not confirmed.') +
          ' Retry sends this same configuration. Reopen the configuration to see whether it applied.');
      }
      busyRef.current = false; if (mounted.current) setBusy(false);
      return;
    }
    try {
      if (!scopeCurrent()) return;
      setConfigEditor(value => ({...value, submission:null, uncertain:false, refreshPending:true,
        result:saved.work_configuration}));
      const reopened = await authority.readWorkConfiguration(descriptor.root, edit.work);
      if (!scopeCurrent()) return;
      setConfigEditor(value => configEditorFrom(reopened, value));
      try { await authority.refreshWorkshop(descriptor.root); await authority.refreshTopologyCanvas(); }
      catch (_) { setActionError('The Work configuration is saved. Refresh the Workshop and canvas to display it.'); }
    } catch (_) {
      if (scopeCurrent()) setActionError('The Work configuration is saved, but this editor could not reload it. Reopen it before making another change.');
    } finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const discardConfigAttempt = () => {
    setConfigEditor(value => value && ({...value, submission:null, uncertain:false, checked:false}));
    setActionError('');
  };
  const discardConfigDraft = async () => {
    const edit = configEditor;
    if (busyRef.current || !edit?.draft || edit.submission) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try {
      await authority.discardWorkConfiguration(descriptor.root, edit.work,
        {revision_id:edit.draft.revision_id, expected_revision:edit.revision});
      const current = await authority.readWorkConfiguration(descriptor.root, edit.work);
      if (scopeCurrent()) setConfigEditor(configEditorFrom(current));
    } catch (error) {
      if (scopeCurrent()) setActionError(error.message || 'Discard was not confirmed. Reopen the configuration.');
    } finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const discardGateAttempt = () => {
    setGateEditor(value => value && ({...value, submission:null, uncertain:false, path:value.currentPath}));
    setActionError('');
  };
  const revisionSubmission = React.useRef(null);
  const protectedEditors = existing && typeof authority.openConversationEditor === 'function';
  const editors = React.useRef({message:null, work:null, keys:null});
  const [editorsReady, setEditorsReady] = React.useState(!protectedEditors);
  const [editorError, setEditorError] = React.useState('');
  const editorOpening = React.useRef(false);
  const prepareEditors = async () => {
    if (!protectedEditors || editorOpening.current) return;
    editorOpening.current = true; setEditorError('');
    try {
      const held = editors.current;
      if (!held.keys) held.keys = [window.crypto.randomUUID(), window.crypto.randomUUID()];
      for (const [index, name] of ['message', ...(nativeAvailable ? ['work'] : [])].entries()) {
        if (held[name]) await held[name].retry();
        else held[name] = await authority.openConversationEditor(descriptor.root, held.keys[index], name);
        if (!mounted.current) { await held[name].close(); return; }
        // A lost save acknowledgement may resolve to clear while newer local
        // text still exists. Re-arm protection before enabling that editor.
        if (name === 'message' ? draft.length > 0 : sourceFile || readingFile || creationUncertain ||
            ['title','description','criterion','verification','path'].some(key => repair[key].length > 0) ||
            repair.model !== 'nex-agi/nex-n2.5-pro:free' || native?.state && native.state !== 'idle') {
          await held[name].dirty();
        }
      }
      if (mounted.current) setEditorsReady(true);
    } catch (error) {
      if (mounted.current) { setEditorsReady(false); setEditorError(error.message || 'Draft protection is unavailable.'); }
    } finally { editorOpening.current = false; }
  };
  const protectDraft = name => {
    const editor = editors.current[name];
    if (!protectedEditors || !editor) return;
    editor.dirty().catch(error => {
      if (mounted.current) { setEditorsReady(false); setEditorError(error.message || 'Retry draft protection before continuing.'); }
    });
  };
  const native = state?.nativeWork?.root === descriptor.root && state.nativeWork.scope === state?.canvas?.root ?
    state.nativeWork : null;
  const artifactWork = nativeTarget || native?.work;
  const [publicationView, setPublicationView] = React.useState(null);
  React.useEffect(() => { setPublicationView(null); }, [descriptor.root, state?.canvas?.root, artifactWork]);
  const savedPublications = (native?.existing_artifacts || []).filter(row => row.work === artifactWork);
  const savedArtifacts = (native?.artifacts || []).filter(row => row.work === artifactWork &&
    !(native?.artifact?.result === row.result && native?.artifact?.receipt === row.receipt));
  const failedProjects = (native?.failures || []).filter(row => row.work === artifactWork);
  const localDeliveries = (native?.local_deliveries || []).filter(row => row.work === artifactWork);
  const targetAvailable = native?.available_work?.includes(nativeTarget) && projectedWorkNodes.some(node => node.id === nativeTarget);
  const scopeCurrent = () => mounted.current && authority.getSnapshot()?.canvas?.graph_id === state?.canvas?.graph_id &&
    authority.getSnapshot()?.canvas?.root === state?.canvas?.root &&
    authority.getSnapshot()?.workshops?.some(row => row.root === descriptor.root);
  React.useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; fileIntent.current += 1; };
  }, []);
  React.useEffect(() => {
    prepareEditors();
    return () => {
      // No unload/expiry inference: close preserves dirty/unknown records. If
      // navigation or lost transport prevents closure, the open record remains.
      for (const editor of Object.values(editors.current)) {
        if (editor && typeof editor.close === 'function') editor.close().catch(() => {});
      }
    };
  }, [authority, descriptor.root]);
  React.useEffect(() => {
    let disposed = false;
    if (nativeAvailable) authority.refreshNativeWork(descriptor.root, nativeTarget || null).catch(error => {
      if (!disposed && mounted.current) setActionError(error.message || 'Read the native Workshop status to continue.');
    });
    return () => { disposed = true; };
  }, [authority, descriptor.root, nativeAvailable, nativeTarget]);
  const page = state?.workshopPage?.root === descriptor.root ? state.workshopPage : null;
  const olderPage = typeof page?.before === 'string';
  const content = transcript?.storage === 'conversation-content';
  const feed = page?.feed || 'all';
  const feedIdentity = JSON.stringify([state?.canvas?.graph_id, state?.canvas?.root, descriptor.root]);
  const chooseFeed = async value => {
    const intent = ++pageIntent.current;
    latestJump.current = true;
    setPaging(true); setActionError('');
    try { await authority.showWorkshopFeed(descriptor.root, value); }
    catch (error) {
      if (pageIntent.current === intent) setActionError(error.message || 'The Workshop feed could not be read.');
    } finally { if (mounted.current && pageIntent.current === intent) setPaging(false); }
  };
  React.useEffect(() => {
    if (content && !paging && !busy && !page?.feedInitialized && typeof authority.showWorkshopFeed === 'function') {
      chooseFeed('messages');
    }
  }, [content, feedIdentity, authority, page?.feedInitialized, paging, busy]);
  const navigatePage = async latest => {
    if (latest && !olderPage && transcript && !transcript.error) {
      messageScroll.current.jump(messageViewport.current);
      return;
    }
    const intent = ++pageIntent.current;
    latestJump.current = latest;
    setPaging(true); setActionError('');
    try {
      if (latest) await authority.showLatestWorkshop(descriptor.root);
      else await authority.loadOlderWorkshop(descriptor.root);
    } catch (error) {
      if (pageIntent.current === intent) {
        latestJump.current = false;
        setActionError(error.message || 'The message page could not be read.');
      }
    } finally { if (pageIntent.current === intent) setPaging(false); }
  };
  React.useEffect(() => { setPublicReview(false); }, [native?.request_id]);
  const projectReviewExpired = native?.mode === 'project' && (native.review_expired === true ||
    (Number.isFinite(native.review_expires_at) && Date.now() / 1000 >= native.review_expires_at));
  const artifactReview = ['project', 'agent'].includes(native?.mode);
  const artifactReviewExpired = artifactReview && (native.review_expired === true ||
    (Number.isFinite(native.review_expires_at) && Date.now() / 1000 >= native.review_expires_at));
  const selectedRepairMode = native?.artifacts_work === nativeTarget ? native.selected_work_mode : null;
  const [stoppingNative, setStoppingNative] = React.useState(false);
  const stopNative = async () => {
    if (stoppingNative || native?.mode !== 'agent') return;
    setStoppingNative(true);
    try { await authority.nativeWorkAction(descriptor.root, 'stop_native', native.work); }
    catch (error) { if (scopeCurrent()) setActionError(error.message || 'Read the native operation status before continuing.'); }
    finally { if (mounted.current) setStoppingNative(false); }
  };
  const nativeAct = async (action, artifact = null) => {
    if (busyRef.current || (action !== 'refresh' && !editorsReady)) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try {
      if (!['refresh', 'read_publication'].includes(action) && protectedEditors) await editors.current.work.dirty();
      if (action === 'refresh') await authority.refreshNativeWork(descriptor.root, nativeTarget || null);
      else if (action === 'prepare_revision') {
        const work = native.work;
        await setNativeTarget(work);
        await authority.nativeWorkAction(descriptor.root, 'release', work);
        if (scopeCurrent()) await authority.nativeWorkAction(descriptor.root, 'prepare_project', work);
      }
      else if (action === 'approve') await authority.approveNativeWork(descriptor.root, native?.input_digest);
      else if (action === 'refresh_project_review') await authority.nativeWorkAction(descriptor.root, action,
        native.work, {delegation:native.delegation, input_digest:native.input_digest});
      else if (action === 'recover_project' || action === 'recover_review') {
        await setNativeTarget(artifact.work);
        await authority.nativeWorkAction(descriptor.root, action,
          artifact.work, {result:artifact.result, receipt:artifact.receipt});
      }
      else if (action === 'abandon_project') await authority.nativeWorkAction(descriptor.root, action,
        artifact.work, {grant:artifact.grant, result:artifact.result, input_digest:artifact.input_digest});
      else if (action === 'recover_local_project') {
        await setNativeTarget(artifact.work);
        await authority.nativeWorkAction(descriptor.root, action,
          artifact.work, {result:artifact.result, resolution:artifact.resolution});
      }
      else if (action === 'read_publication') {
        const result = await authority.readExistingPublication(descriptor.root, artifact.work, artifact.publication);
        if (scopeCurrent()) setPublicationView(result);
        return;
      }
      else if (action === 'read_artifact') {
        const result = await authority.nativeWorkAction(descriptor.root, action, artifact?.work,
          artifact ? {result:artifact.result, receipt:artifact.receipt} : {});
        if (!scopeCurrent()) return;
        const url = URL.createObjectURL(new Blob([new TextEncoder().encode(result.artifact_text)], {type:'text/plain;charset=utf-8'}));
        const link = document.createElement('a');
        try {
          link.href = url; link.download = result.artifact.name;
          document.body.appendChild(link); link.click();
        } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
        return;
      }
      else await authority.nativeWorkAction(descriptor.root, action, nativeTarget);
      if (scopeCurrent()) await authority.refreshWorkshop(descriptor.root);
    } catch (error) { if (scopeCurrent()) setActionError(action === 'prepare_revision' ?
      'Read the operation status. If closing is pending, recover the closed result; then prepare this selected Work. ' + (error.message || '') :
      error.message || 'Read the operation status to reconcile this action.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const selectSourceFile = async event => {
    const file = event.target.files?.[0], intent = ++fileIntent.current;
    setSourceFile(null); setPublicReview(false); setActionError('');
    setRepair(value => ({...value, path:''}));
    if (!file) { setReadingFile(false); return; }
    setReadingFile(true);
    try {
      const selected = await authority.readProjectFile(descriptor.root, file);
      if (intent !== fileIntent.current || !scopeCurrent()) return;
      setSourceFile(selected); setRepair(value => ({...value, path:selected.path}));
    } catch (error) {
      if (intent === fileIntent.current && scopeCurrent()) setActionError(error.message || 'The source file could not be read.');
    } finally { if (intent === fileIntent.current && mounted.current) setReadingFile(false); }
  };
  const createRepairWork = async event => {
    event.preventDefault();
    if (busyRef.current || !editorsReady || !sourceFile || readingFile || creationUncertain) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try {
      if (protectedEditors) await editors.current.work.dirty();
      if (revisionBase) {
        const localSource = revisionBase.local_source;
        const expectedRequest = revisionBase.request_id || (revisionSubmission.current &&
          'local-revision-' + revisionSubmission.current.revision_id);
        const operationMatches = localSource ?
          (native?.state === 'idle' || (native?.state === 'local_delivery_abandoned' &&
            native.work === revisionBase.work && native.request_id === expectedRequest &&
            native.local_resolution?.result === localSource.result && native.local_resolution?.resolution === localSource.resolution)) :
          revisionBase.request_id === native?.request_id && revisionBase.work === native?.work;
        if (revisionBase.graph !== state?.canvas?.graph_id || revisionBase.scope !== state?.canvas?.root ||
            revisionBase.owner !== native?.owner || revisionBase.view !== native?.view ||
            !operationMatches) {
          throw new Error('Return to this revision’s original Workshop operation before saving it.');
        }
        let held = revisionSubmission.current;
        if (!held) {
          const revisionId = window.crypto.randomUUID().replaceAll('-', '');
          held = {revision_id:revisionId, base_digest:revisionBase.input_digest,
            inputs:{...revisionBase.inputs, model:repair.model.trim(), artifact_name:revisionId + '.patch',
              files:[{path:repair.path, content:sourceFile.content, sha256:sourceFile.sha256},
                ...revisionBase.inputs.files.slice(1)]},
            requirements:{acceptance_criteria:[{criterion:repair.criterion.trim(), verification:repair.verification.trim()},
              ...revisionBase.requirements.acceptance_criteria.slice(1)]}};
          revisionSubmission.current = held;
        }
        if (localSource && native?.state === 'idle') setRevisionBase(value => ({...value,
          request_id:'local-revision-' + held.revision_id}));
        const saved = await authority.nativeWorkAction(descriptor.root, 'revise_project', revisionBase.work,
          {draft:held, ...(localSource || {})});
        if (!scopeCurrent()) return;
        setRevisionBase(null); revisionSubmission.current = null; setSourceFile(null);
        setRepair({title:'', description:'', criterion:'', verification:'', path:'', model:'nex-agi/nex-n2.5-pro:free'});
        await authority.refreshWorkshop(descriptor.root);
        try { await authority.refreshTopologyCanvas(); }
        catch (_) { setActionError('Revised inputs are saved. Refresh the canvas to display their updated wires.'); }
        if (scopeCurrent() && saved.work_revision.current_input_digest !== saved.work_revision.input_digest) {
          setActionError('This revision was already saved, but the Work changed afterward. Reopen its current inputs before preparing.');
        }
        return;
      }
      const node = projectedWorkNodes.find(row => row.id === descriptor.root);
      const result = await authority.createProjectWork(descriptor.root, {...repair, content:sourceFile.content,
        x:Number.isFinite(node?.x) ? node.x + 280 : 200, y:Number.isFinite(node?.y) ? node.y : 200});
      if (mounted.current) {
        setSourceFile(null); setRepair({title:'', description:'', criterion:'', verification:'', path:'', model:'nex-agi/nex-n2.5-pro:free'});
        setCreationUncertain(true);
      }
      if (result.navigated || !scopeCurrent()) return;
      // Select the newly created Work through the same durable view operation.
      if (result.original_graph === state?.canvas?.graph_id && result.original_scope === state?.canvas?.root) {
        await authority.refreshTopologyCanvas();
        await authority.selectTopology(result.created_root);
      }
      window.location.reload();
    } catch (error) {
      if (scopeCurrent()) {
        if (revisionBase && error.revisionRejectedNoWrite) revisionSubmission.current = null;
        setActionError(error.message || 'Work creation could not be confirmed. Refresh the canvas before trying again.');
        if (error.creationUncertain) setCreationUncertain(true);
      }
    } finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const beginWorkRevision = async (delivery = null) => {
    const localSource = delivery || (native?.state === 'local_delivery_abandoned' ? native.local_resolution : null);
    if (busyRef.current || !editorsReady || revisionBase ||
        (localSource ? !['idle','local_delivery_abandoned'].includes(native?.state) : native?.state !== 'published')) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try {
      if (protectedEditors) await editors.current.work.dirty();
      const work = localSource?.work || native.work;
      const result = await authority.nativeWorkAction(descriptor.root, 'read_project', work);
      if (!scopeCurrent()) return;
      const pending = result.draft.pending_revision;
      if (pending && (!localSource || pending.result !== localSource.result || pending.resolution !== localSource.resolution)) {
        throw new Error('Open the exact local delivery associated with this saved revision.');
      }
      const draft = pending ? {...result.draft, inputs:pending.inputs, requirements:pending.requirements,
        input_digest:pending.base_digest} : result.draft;
      const file = draft.inputs.files[0], criterion = draft.requirements.acceptance_criteria[0];
      if (typeof file?.content !== 'string' || typeof file?.path !== 'string' ||
          typeof criterion?.criterion !== 'string' || typeof criterion?.verification !== 'string') {
        throw new Error('This Work’s editable inputs are incomplete.');
      }
      setRevisionBase({...draft, work:result.work, graph:state?.canvas?.graph_id, scope:state?.canvas?.root,
        owner:result.owner, view:result.view, request_id:native.state === 'idle' ? null : native.request_id,
        ...(localSource ? {local_source:{result:localSource.result, resolution:localSource.resolution}} : {})});
      revisionSubmission.current = pending ? {revision_id:pending.revision_id, base_digest:pending.base_digest,
        inputs:pending.inputs, requirements:pending.requirements} : null;
      setRepair({title:draft.title, description:draft.description, model:draft.inputs.model,
        path:file.path, criterion:criterion.criterion, verification:criterion.verification});
      setSourceFile({...file, bytes:new TextEncoder().encode(file.content).byteLength});
    } catch (error) { if (scopeCurrent()) setActionError(error.message || 'The Work could not be opened for revision.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  React.useEffect(() => {
    let disposed = false, timer, active = false;
    let nativeCursor = authority.getSnapshot()?.workshop?.content_cursor || null;
    let lastNativeRead = Date.now();
    const refresh = async () => {
      if (disposed || document.hidden || active) return;
      clearTimeout(timer);
      active = true; setRefreshing(true);
      try {
        let projection;
        try {
          const opening = openedRoot.current !== descriptor.root && typeof authority.openWorkshop === 'function';
          if (opening) openedRoot.current = descriptor.root;
          projection = await (opening ? authority.openWorkshop(descriptor.root) : authority.refreshWorkshop(descriptor.root));
        } finally {
          if (!disposed) setRefreshing(false);
        }
        const snapshot = authority.getSnapshot();
        const operation = snapshot?.nativeWork;
        const cursor = projection?.content_cursor || (projection ? String(projection.revision) : null);
        const settling = operation?.root === descriptor.root &&
          ['attaching', 'recovering', 'preparing', 'executing', 'uncertain', 'publication_uncertain'].includes(operation.state);
        // Reuse the existing visible-page poll. An external worker's result
        // must refresh this panel too; do not start another background timer.
        if (!disposed && !document.hidden && nativeAvailable && !busyRef.current && !revisionSubmission.current &&
            cursor && (cursor !== nativeCursor || settling) && Date.now() - lastNativeRead >= 10000) {
          lastNativeRead = Date.now();
          try {
            const status = await authority.refreshNativeWork(descriptor.root, nativeTarget || null);
            if (!disposed && status) { nativeCursor = cursor; setNativeSyncError(''); }
          } catch (error) {
            if (!disposed) setNativeSyncError(error.message || 'Task status could not refresh. Read operation status to retry.');
          }
        }
      } catch (_) {}
      finally {
        active = false;
        if (!disposed) {
          timer = setTimeout(refresh, 2500);
        }
      }
    };
    const visibility = () => { clearTimeout(timer); if (!document.hidden) refresh(); };
    document.addEventListener('visibilitychange', visibility);
    refresh();
    return () => { disposed = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibility); };
  }, [authority, descriptor.root, nativeAvailable, nativeTarget]);
  const participants = transcript?.participants || [];
  const nativeContacts = store.contacts, contactError = store.contactError, contactsLoading = store.contactsLoading;
  // The recipient picker offers connections that are here now; an offline one is one choice away.
  const [showOfflineContacts, setShowOfflineContacts] = React.useState(false);
  const offlineContacts = nativeContacts.filter(row => row.connected === false && 'contact:' + row.root !== target).length;
  const pickerContacts = showOfflineContacts ? nativeContacts :
    nativeContacts.filter(row => row.connected !== false || 'contact:' + row.root === target);
  const contactRead = React.useRef(0), currentTarget = React.useRef(target);
  currentTarget.current = target;
  const refreshContacts = React.useCallback(async () => {
    if (!existing || !authority.nativeAgents) return;
    const request = ++contactRead.current;
    storeChanged({contactsLoading:true, contactError:''});
    try {
      const result = await authority.nativeAgents(descriptor.root);
      if (request !== contactRead.current || !mounted.current) return;
      if (!Array.isArray(result.contacts) || result.contacts.length > 64 || result.contacts.some(row =>
          !workshopSelectionId(row.root) || typeof row.label !== 'string' ||
          !/^[a-f0-9]{64}$/.test(row.binding_digest) || ![true,false,null].includes(row.connected))) {
        throw new Error('The saved agent connections could not be read.');
      }
      storeChanged({contacts:result.contacts});
      if (result.status !== 'ok') storeChanged({contactError:'Saved connections loaded; live agent availability could not be checked.'});
      try {
        const choice = JSON.parse(window.sessionStorage.getItem('archhub.native-contact.selection.v1') || 'null');
        if (!currentTarget.current && choice?.graph === state?.canvas?.graph_id && choice.root === descriptor.root &&
            result.contacts.some(row => row.root === choice.contact)) {
          setTarget('contact:' + choice.contact);
          window.sessionStorage.removeItem('archhub.native-contact.selection.v1');
        }
      } catch (_) { /* Selection storage is presentation only. */ }
    } catch (error) {
      if (request === contactRead.current && mounted.current) storeChanged({contactError:error?.message || 'Agent connections are unavailable.'});
    } finally {
      if (request === contactRead.current && mounted.current) storeChanged({contactsLoading:false});
    }
  }, [authority, existing, descriptor.root, state?.canvas?.graph_id]);
  React.useEffect(() => {
    storeChanged({contacts:[], contactError:'', contactsLoading:false,
      refreshContacts:existing && authority.nativeAgents ? refreshContacts : null});
    refreshContacts();
    return () => { contactRead.current += 1; storeChanged({refreshContacts:null}); };
  }, [refreshContacts]);
  const contactTarget = nativeContacts.find(row => 'contact:' + row.root === target) || null;
  const modelAgent = existing ? transcript?.model_agent : null;
  const modelTarget = modelAgent && target === 'model:' + modelAgent.root ? modelAgent : null;
  // The Workshop itself is the default recipient (design studio-workshop.jsx composer,
  // "to: Workshop"): opening a room no longer pre-addresses one model agent.
  const names = new Map(participants.map(row => [row.root, row.label]));
  const messages = transcript?.messages || [];
  // THE LIVE SCENE: every design surface below reads these, never a seed.
  const taskItems = workshopTaskItems(messages, projectedWorkNodes);
  const tasks = wsTasks(taskItems, projectedWorkNodes, workshopProjectedWires(state), native, names).map(t => {
    const decision = t.approving ? [
      {label:artifactReview ? 'Approve this repair' : 'Approve this input', action:'approve',
        disabled:busy || !editorsReady || (artifactReview && (artifactReviewExpired || native.approved === true || !native.review_text || !native.input_digest))},
      {label:artifactReview ? 'Generate repair artifact' : 'Run approved review', action:'execute',
        disabled:busy || !editorsReady || (artifactReview && (artifactReviewExpired || native.approved !== true))},
    ] : null;
    const held = native?.artifact && native.work === t.work && native.artifact.outcome !== 'failed' ? native.artifact : null;
    const artifact = held ? {name:held.name, bytes:held.bytes, digest:held.digest, summary:held.summary,
      download:['settled', 'published', 'publication_uncertain', 'release_pending'].includes(native.state) && editorsReady ? () => nativeAct('read_artifact') : null} : null;
    return {...t, decision, artifact};
  });
  const agents = wsAgents(transcript, tasks, Date.now() / 1000);
  const agent = root => agentOf(agents, names, transcript?.self, root);
  const flow = wsFlow(projectedWorkNodes, workshopProjectedWires(state), tasks);
  const selAgentId = agents.some(a => a.id === S.agent) ? S.agent : agents[0]?.id || null;
  const selAgent = agents.find(a => a.id === selAgentId) || null;
  const selTask = tasks.some(t => t.work === S.task) ? S.task : null;
  const counts = {block:tasks.filter(t => t.state==='block').length, run:tasks.filter(t => t.state==='run' || t.state==='open').length,
    review:tasks.filter(t => t.state==='review').length, paused:tasks.filter(t => t.state==='paused').length, done:tasks.filter(t => t.state==='done').length};
  const toolRecords = messages.filter(message => message.category === 'tool' &&
    (!selTask || String(message.body || '').includes(selTask))).slice(-5).reverse();
  const activity = toolRecords.map(message => ({root:message.root, at:wsClockText(message.created_at, true),
    dir:message.sender_root === transcript?.self ? '←' : '→', text:wsLine(message.body, 60)}));
  const activityNote = !transcript ? 'Loading messages\u2026' : feed === 'messages' ?
    'Tool records are on the Tool activity feed, under ⋯.' : 'No tool record on this page.';
  const listening = participants.filter(row => row.attached && row.root !== transcript?.self).length;
  const joined = participants.some(row => row.root === transcript?.self && row.attached) &&
    (!existing || transcript?.can_send === true);
  const openAsNodes = () => {
    const focus = selTask || nativeTarget || (projectedWorkNodes.some(node => node.id === descriptor.root) ? descriptor.root : '');
    if (focus && setFocusId) setFocusId(focus);
    setMode('canvas');
  };
  const selectTask = id => setS({ agent:S.agent, task: id === selTask ? null : id });
  const setSelAgent = id => setS({ agent:id, task:null });
  const decide = (work, choice) => { if (choice && choice.action) nativeAct(choice.action); };
  // Disconnect only an agent with its own Session Link channel; base-transport participants never offer it.
  const canDisconnect = typeof authority?.disconnectAgent === 'function';
  const disconnectable = row => canDisconnect && row.is_agent === true && row.root !== transcript?.self &&
    (['attached', 'attaching', 'retiring'].includes(row.session_link) || store.outcomes[row.root]?.outcome === 'uncertain');
  const disconnectAgent = async row => {
    if (store.pending[row.root]) return;
    storeChanged({pending:{...store.pending, [row.root]:true}, outcomes:{...store.outcomes, [row.root]:null}});
    try {
      const result = await authority.disconnectAgent(descriptor.root, row.root);
      storeChanged({outcomes:{...store.outcomes, [row.root]:{outcome:result.outcome}}});
    } catch (error) {
      storeChanged({outcomes:{...store.outcomes, [row.root]:{error:error.message || 'The disconnect could not be confirmed. Retry to reconcile it.'}}});
    } finally {
      storeChanged({pending:Object.fromEntries(Object.entries(store.pending).filter(([root]) => root !== row.root))});
    }
  };
  const messagePageIdentity = JSON.stringify([state?.canvas?.graph_id, state?.canvas?.root,
    descriptor.root, feed, page?.before ?? null, transcript?.owner ?? null, transcript?.view ?? null]);
  React.useLayoutEffect(() => {
    const successful = !!transcript && !transcript.error &&
      (!content || transcript.page_before === (page?.before ?? null));
    messageScroll.current.update(messageViewport.current, messagePageIdentity, successful, olderPage, latestJump.current);
    if (successful && !olderPage) latestJump.current = false;
  }, [messagePageIdentity, transcript, messageTextSize, preset]);
  React.useEffect(() => {
    if (typeof ResizeObserver !== 'function') return;
    const observer = new ResizeObserver(() => messageScroll.current.reflow(messageViewport.current));
    if (messageViewport.current) observer.observe(messageViewport.current);
    if (messageContent.current) observer.observe(messageContent.current);
    return () => observer.disconnect();
  }, [preset]);
  const act = async (action) => {
    // Sending never waits for draft protection: the message route stands on its own,
    // and a protected editor is used only once it is ready.
    if (busyRef.current) return;
    const details = action === 'send' ? {target, message:draft.trim(), ...(execution ? {execution_root:execution} : {})} : {};
    busyRef.current = true; setBusy(true); setActionError('');
    try {
      if (action === 'send' && target.startsWith('contact:')) {
        if (!contactTarget || contactTarget.connected === false) throw new Error('Refresh this agent connection before sending.');
        await authority.sendNativeContact(descriptor.root, contactTarget, draft.trim(),
          protectedEditors && editorsReady ? editors.current.message : null);
      } else if (action === 'send' && target.startsWith('model:')) {
        if (!modelTarget) throw new Error('Refresh this conversation and its model node before sending.');
        await authority.sendModelConversation(descriptor.root, modelTarget, draft.trim(),
          protectedEditors && editorsReady ? editors.current.message : null);
      } else {
        await authority.workshopAction(descriptor.root, action, null, details,
          protectedEditors && editorsReady ? editors.current.message : null);
      }
      if (action === 'send' && mounted.current) setDraft('');
    } catch (error) { setActionError(error.message || 'The action could not be confirmed. Retry to reconcile it.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  // The design's Send stays drawn as the primary action; an empty draft sends nothing, and a recipient that
  // cannot receive says why instead of a silent no-op.
  const sendDisabled = busy || !joined;
  const send = () => {
    if (sendDisabled || !draft.trim()) return;
    // No target is the design's default: the message goes to the Workshop, and every
    // attached participant reads it. Picking one agent addresses only that agent.
    if ((target.startsWith('contact:') && (!contactTarget || contactTarget.connected === false)) ||
        (target.startsWith('model:') && !modelTarget)) { setActionError('Refresh this recipient before sending.'); return; }
    act('send');
  };
  const addressable = participants.filter(row => row.attached && row.root !== transcript?.self);
  const connectedContact = nativeContacts.find(row => row.connected === true);
  const firstRecipient = modelAgent ? 'model:' + modelAgent.root : connectedContact ? 'contact:' + connectedContact.root :
    addressable[0] ? addressable[0].root : '';
  const targetName = target.startsWith('model:') ? (modelAgent ? `Agent · ${modelAgent.model}` : 'the model') :
    target.startsWith('contact:') ? (contactTarget ? contactTarget.label : 'this connection') : (names.get(target) || target);
  // Relocated controls (feed, paging, text size, Session Link disconnect, saved connections, Work on a
  // project) sit behind the context panel's ⋯, so the design's layout is unchanged while it is folded.
  const selRow = selAgent ? selAgent.row : null;
  const controls = <>
    <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}` }}>
      <Lbl>HISTORY</Lbl>
      <div role={transcript?.error ? 'alert' : 'status'} style={{ fontFamily:W.mono, fontSize:10, lineHeight:1.6, color:transcript?.error ? W.err : W.inkMuted, marginTop:8, overflowWrap:'anywhere' }}>
        {transcript?.error || (paging ? 'Loading message page\u2026' : refreshing ? 'Updating messages\u2026' :
          transcript ? (olderPage ? 'Earlier messages synchronized' : 'Messages synchronized') : 'Loading messages\u2026')}
        {transcript && !transcript.error ? ` \u00b7 ${messages.length} displayed \u00b7 ${listening} listening` : ''}
        {transcript && !transcript.error && content ? ` \u00b7 ${transcript.total} ${feed === 'activity' ? 'tool records' : feed === 'messages' ? 'notes' : 'records'} available` : ''}
      </div>
      {content && typeof authority.showWorkshopFeed === 'function' && <div role="group" aria-label="Workshop feed" style={{ display:'flex', flexWrap:'wrap', gap:6, marginTop:8 }}>
        {[['messages', 'Notes & replies'], ['activity', 'Tool activity'], ['all', 'All history']].map(([key, label]) =>
          <Mini key={key} acc={feed === key} disabled={busy || paging} onClick={() => chooseFeed(key)}>{label}</Mini>)}
      </div>}
      <div style={{ display:'flex', flexWrap:'wrap', gap:6, marginTop:8 }}>
        <Mini disabled={busy || paging || !transcript?.next_before || !!transcript?.error} onClick={() => navigatePage(false)}>Older messages</Mini>
        <Mini disabled={busy} title="Jump to latest messages" onClick={() => navigatePage(true)}>{'\u2193 Latest'}</Mini>
        {awayFromLatest && <Lbl>READING EARLIER</Lbl>}
      </div>
      <div role="group" aria-label="Workshop message text size" style={{ display:'flex', flexWrap:'wrap', gap:6, marginTop:8, alignItems:'center' }}>
        <Lbl>TEXT</Lbl>
        {[13.5, 16, 18, 20].map(size => <Mini key={size} acc={messageTextSize === size} onClick={() => setMessageTextSize(size)}>{size} px</Mini>)}
      </div>
    </div>
    {selRow && <div style={{ padding:'12px 16px', borderBottom:`1px solid ${W.lineSoft}` }}>
      <Lbl>AGENT CONNECTION · {selAgent.name}</Lbl>
      <div style={{ marginTop:8 }}>
        <PRow k="status" v={ST[selAgent.status].label} c={ST[selAgent.status].col}/>
        <PRow k="session link" v={wsLinkStatus(selRow) || 'none'}/>
        <PRow k="last seen" v={selAgent.seen || '—'} last/>
      </div>
      <div style={{ display:'flex', flexWrap:'wrap', gap:6, marginTop:8 }}>
        {disconnectable(selRow) && <Btn sm disabled={!!store.pending[selRow.root]} onClick={() => disconnectAgent(selRow)}>
          {selRow.session_link === 'retiring' || store.outcomes[selRow.root]?.outcome === 'uncertain' ? 'Retry Session Link disconnect' : 'Disconnect Session Link channel'}</Btn>}
        {existing && authority.nativeAgents && <Btn sm disabled={busy || contactsLoading} onClick={refreshContacts}>{'\u21bb Refresh agent connections'}</Btn>}
      </div>
      <div style={{ fontSize:11.5, color:W.inkSoft, lineHeight:1.5, marginTop:8 }}>
        Disconnecting a Session Link channel does not end the agent session or undo work already delivered.
      </div>
    </div>}
    {nativeAvailable && <section aria-label="Native Workshop review" style={{ padding:'12px 16px', fontSize:12, color:W.inkSoft }}>
        <h3 style={{margin:'0 0 8px'}}>Work on a project</h3>
        <button disabled={busy} onClick={() => nativeAct('refresh')}>Read operation status</button>
        <p role="status">{native?.state || 'Read status to connect to the native Workshop.'}</p>
        {native?.review_recovered && <p style={{fontSize:12, color:W.inkSoft}}>
          Reviewing a saved result. No new model run has occurred.
        </p>}
        {(!native || native.state === 'idle' || revisionBase) && <>
          <details open={!!revisionBase} style={{marginBottom:16}}>
            <summary>{revisionBase ? 'Revise this Work' : 'Create a repair Work node'}</summary>
            <p style={{fontSize:12, color:W.inkSoft, lineHeight:1.5}}>
              {revisionBase ? 'Saving replaces this Work’s source inputs and criteria together; earlier values and results remain saved.' :
                'Choose one public text source file. Creating Work saves its text, your request, and criteria on the graph.'}
              No model runs until you review and approve the prepared input, then generate a draft patch. This does not apply changes to your source.
            </p>
            {revisionBase && <p style={{fontSize:12, color:W.inkSoft}}>
              Update the source, model and acceptance criteria for this same Work. Earlier results stay saved.
              Its task wording stays bound to the existing plan. Saving requires fresh input approval before another run.
              {revisionBase.inputs.files.length > 1 || revisionBase.requirements.acceptance_criteria.length > 1 ?
                ' This editor changes the first source and criterion; additional saved sources and criteria are retained.' : ''}
            </p>}
            <form onSubmit={createRepairWork} onChangeCapture={() => protectDraft('work')}>
              <fieldset disabled={busy || !editorsReady || !!revisionSubmission.current} style={{border:0, margin:0, padding:0, minWidth:0}}>
              <label style={{display:'block', margin:'10px 0'}}>Work title
                <input aria-label="Repair Work title" required maxLength={160} value={repair.title}
                  disabled={busy || !!revisionBase} onChange={event => setRepair(value => ({...value, title:event.target.value}))}
                  style={{display:'block', width:'100%', marginTop:4}}/>
              </label>
              <label style={{display:'block', margin:'10px 0'}}>Requested change
                <textarea aria-label="Requested source change" required maxLength={12000} value={repair.description}
                  disabled={busy || !!revisionBase} onChange={event => setRepair(value => ({...value, description:event.target.value}))}
                  style={{display:'block', width:'100%', minHeight:72, marginTop:4}}/>
              </label>
              {!revisionBase && <label style={{display:'block', margin:'10px 0'}}>Repair runtime
                <select aria-label="Repair runtime" value={repair.runtime || 'openrouter'} disabled={busy}
                  onChange={event => setRepair(value => ({...value, runtime:event.target.value,
                    model:event.target.value === 'claude' ? 'sonnet' : 'nex-agi/nex-n2.5-pro:free'}))}>
                  <option value="openrouter">Free OpenRouter</option>
                  <option value="claude">Native Claude</option>
                </select>
              </label>}
              <label style={{display:'block', margin:'10px 0'}}>{repair.runtime === 'claude' ? 'Claude model' : 'Free OpenRouter model'}
                <input aria-label={repair.runtime === 'claude' ? 'Claude repair model' : 'Free OpenRouter repair model'} required maxLength={repair.runtime === 'claude' ? 160 : 256} value={repair.model}
                  disabled={busy} onChange={event => setRepair(value => ({...value, model:event.target.value}))}
                  style={{display:'block', width:'100%', marginTop:4}}/>
              </label>
              <p style={{fontSize:11, color:W.inkSoft}}>{repair.runtime === 'claude' ?
                'Uses the installed Claude account. The Work stores a 12-turn, 768 MiB process budget and a 180-second turn timeout. Review and approval are required before a model turn.' :
                'Use an explicit :free model or openrouter/free. This choice is saved with the Work; there is no automatic fallback.'}</p>
              <label style={{display:'block', margin:'10px 0'}}>One source file · UTF-8 · up to 64 KiB
                <input aria-label="Repair source file" type="file" disabled={busy} onChange={selectSourceFile}
                  style={{display:'block', width:'100%', marginTop:4}}/>
              </label>
              {readingFile && <p role="status">Reading and hashing the selected file…</p>}
              {sourceFile && <div style={{fontSize:11, color:W.inkSoft, overflowWrap:'anywhere'}}>
                {sourceFile.bytes.toLocaleString()} bytes · SHA-256 {sourceFile.sha256}
              </div>}
              <label style={{display:'block', margin:'10px 0'}}>Relative source path
                <input aria-label="Relative source path" required maxLength={512} value={repair.path}
                  placeholder="src/example.js" disabled={busy || !sourceFile}
                  onChange={event => setRepair(value => ({...value, path:event.target.value}))}
                  style={{display:'block', width:'100%', marginTop:4}}/>
              </label>
              <label style={{display:'block', margin:'10px 0'}}>Acceptance criterion
                <textarea aria-label="Repair acceptance criterion" required maxLength={4000} value={repair.criterion}
                  disabled={busy} onChange={event => setRepair(value => ({...value, criterion:event.target.value}))}
                  style={{display:'block', width:'100%', minHeight:56, marginTop:4}}/>
              </label>
              <label style={{display:'block', margin:'10px 0'}}>How to verify it
                <textarea aria-label="Repair verification method" required maxLength={4000} value={repair.verification}
                  disabled={busy} onChange={event => setRepair(value => ({...value, verification:event.target.value}))}
                  style={{display:'block', width:'100%', minHeight:56, marginTop:4}}/>
              </label>
              <button type="submit" disabled={busy || readingFile || !sourceFile || creationUncertain ||
                !repair.title.trim() || !repair.description.trim() || !repair.path.trim() ||
                !repair.criterion.trim() || !repair.verification.trim() || !repair.model.trim()}>{revisionBase ? 'Save revised inputs' : 'Create repair Work'}</button>
              {creationUncertain && <>
                <p role="alert" style={{fontSize:12, color:W.err}}>Inspect the refreshed canvas for a created Work node before submitting again.</p>
                <button type="button" disabled={busy} onClick={() => window.location.reload()}>Refresh canvas</button>
              </>}
              </fieldset>
              {revisionBase && revisionSubmission.current && <button type="submit" disabled={busy}>Reconcile this revision</button>}
              {revisionBase && !revisionSubmission.current && <button type="button" disabled={busy} onClick={() => {
                fileIntent.current += 1; setReadingFile(false); setRevisionBase(null); setSourceFile(null);
                setRepair({title:'', description:'', criterion:'', verification:'', path:'', model:'nex-agi/nex-n2.5-pro:free'});
                setActionError('');
              }}>Discard revision draft</button>}
            </form>
          </details>
          {!revisionBase && <>
          <select aria-label="Work node to review or repair" value={nativeTarget} disabled={busy}
            onChange={event => {setNativeTarget(event.target.value).catch(error => setActionError(error.message));}}>
            <option value="" disabled>Choose a Work node on this canvas</option>
            {projectedWorkNodes.filter(node => native?.available_work?.includes(node.id)).map(node =>
              <option key={node.id} value={node.id}>{node.title}</option>)}
          </select>
          {nativeTarget && <details style={{margin:'10px 0'}}>
            <summary>Acceptance gate</summary>
            {gateEditor?.work !== nativeTarget ?
              <button type="button" disabled={busy} onClick={() => openGateEditor(nativeTarget)}>Open current gate</button> :
              <form onSubmit={saveGate}>
                <p style={{fontSize:12, color:W.inkSoft, lineHeight:1.5}}>
                  Current gate: {gateEditor.kind || 'none'} {gateEditor.currentPath}. Work state: {gateEditor.state}.
                  {gateEditor.editable ?
                    ' Saving replaces only this gate on the same Work; every other requirement keeps its saved content. A test file that does not exist yet is accepted, and completion still fails until it exists.' :
                    ' Only an OPEN, unclaimed Work accepts a gate correction. The Work keeps its identity when its claim is released.'}
                </p>
                <label style={{display:'block', margin:'10px 0'}}>Pytest path inside the CDE of this Work
                  <input aria-label="Acceptance gate pytest path" required maxLength={1024} value={gateEditor.path}
                    disabled={busy || !gateEditor.editable || !!gateEditor.submission || gateEditor.refreshPending}
                    onChange={event => setGateEditor(value => ({...value, path:event.target.value, result:null}))}
                    style={{display:'block', width:'100%', marginTop:4}}/>
                </label>
                {gateEditor.refreshPending ? <>
                  <p role="status" style={{fontSize:12}}>The corrected gate is saved. Reopen the current gate before making another change.</p>
                  <button type="button" disabled={busy} onClick={() => openGateEditor(gateEditor.work)}>Reopen current gate</button>
                </> : gateEditor.uncertain ? <>
                  <p role="status" style={{fontSize:12}}>This correction was not confirmed. Retrying sends exactly the same correction.</p>
                  <button type="submit" disabled={busy || !gateEditor.editable}>Retry the same correction</button>
                  <button type="button" disabled={busy} onClick={() => openGateEditor(gateEditor.work)}>Reopen current gate</button>
                  {gateEditor.checked && <button type="button" disabled={busy} onClick={discardGateAttempt}>Discard this attempt</button>}
                </> : <button type="submit" disabled={busy || !gateEditor.editable || !gateEditor.path.trim() ||
                  gateEditor.path.trim() === gateEditor.currentPath}>Save corrected gate</button>}
                {gateEditor.result && !gateEditor.refreshPending && <p role="status" style={{fontSize:12}}>
                  {gateEditor.result.reused ? 'This correction was already saved.' : 'Gate corrected on the same Work.'}
                </p>}
                {gateEditor.result && <details style={{fontSize:11, overflowWrap:'anywhere'}}>
                  <summary>Saved value</summary>
                  Requirements value {gateEditor.result.target}, digest {gateEditor.result.input_digest}.
                </details>}
              </form>}
          </details>}
          {nativeTarget && <details style={{margin:'10px 0'}}>
            <summary>Work configuration</summary>
            {configEditor?.work !== nativeTarget ?
              <button type="button" disabled={busy} onClick={() => openConfigEditor(nativeTarget)}>Open current configuration</button> :
              <form onSubmit={saveConfiguration}>
                {!!configEditor.drafts.length && <label style={{display:'block', margin:'10px 0'}}>Agent proposals
                  <select aria-label="Review agent configuration proposal" value={configEditor.draft?.revision_id || ''}
                    disabled={busy || !!configEditor.submission || configEditor.refreshPending}
                    onChange={event => reviewConfigDraft(event.target.value)} style={{display:'block', width:'100%'}}>
                    <option value="">Current configuration</option>
                    {configEditor.drafts.map(draft => <option key={draft.revision_id} value={draft.revision_id}>
                      {draft.stale ? 'Outdated - ' : ''}
                      {Object.keys(draft.fields).join(', ')} · {draft.proposing_actor} · {draft.revision_id.slice(0, 8)}
                    </option>)}
                  </select>
                </label>}
                {configEditor.draft && <section aria-label="Proposed configuration changes">
                  {configEditor.draft.stale && <p role="status">The Work changed after this proposal was saved.
                    Discard it or request an updated proposal; it cannot be approved.</p>}
                  <button type="button" disabled={busy || !!configEditor.submission}
                    onClick={discardConfigDraft} title="Discard this proposal; preserve its history">Discard proposal</button>
                  <p style={{fontSize:12}}>Review the proposed inputs, criteria and destination below. Approval changes
                    this Work's configuration; it does not run the Work. You can refine the fields before approving.</p>
                  {Object.entries(configChanges(configEditor)).map(([name, entry]) => <details key={name}>
                    <summary>{name === 'cde-container' ? 'Destination and allowed paths' :
                      name === 'requirements' ? 'Criteria and reviewers' : 'Inputs'} — proposed change</summary>
                    <div style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap:8}}>
                      <div><strong>Current</strong><pre style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere', maxHeight:240, overflow:'auto'}}>
                        {JSON.stringify(configEditor.baselineFields[name].value, null, 2)}</pre></div>
                      <div><strong>Proposed</strong><pre style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere', maxHeight:240, overflow:'auto'}}>
                        {JSON.stringify(entry.value, null, 2)}</pre></div>
                    </div>
                  </details>)}
                </section>}
                {!!configEditor.invalidDrafts.length && <p role="status" style={{fontSize:12}}>
                  {configEditor.invalidDrafts.length} damaged proposal(s) could not be opened. Current configuration remains available.</p>}
                <p style={{fontSize:12, color:W.inkSoft, lineHeight:1.5}}>
                  Work state: {configEditor.state}. Inputs {configEditor.fields.inputs.wired ? 'wired' : 'unwired'},
                  requirements {configEditor.fields.requirements.wired ? 'wired' : 'unwired'},
                  CDE {configEditor.fields['cde-container'].wired ? 'wired' : 'unwired'}.
                  {configEditor.editable ?
                    ' Saving binds or revises only the fields you change, on this same Work; other keys keep their saved content.' :
                    ' Only an OPEN, unclaimed Work accepts a configuration change. The Work keeps its identity when its claim is released.'}
                  {configEditor.artifactReady ? ' Artifact input requirements are present; execution and review are separate.' :
                    configEditor.blocker ? ' Not yet ready for artifact publication: ' + configEditor.blocker : ''}
                </p>
                <label style={{display:'block', margin:'10px 0'}}>CDE allowed paths, one per line
                  <textarea aria-label="Work CDE allowed paths" maxLength={16000} value={configEditor.allowedPaths}
                    disabled={busy || !configEditor.editable || !!configEditor.submission || configEditor.refreshPending}
                    onChange={event => setConfigEditor(value => ({...value, allowedPaths:event.target.value, result:null}))}
                    style={{display:'block', width:'100%', minHeight:48, marginTop:4}}/>
                </label>
                <label style={{display:'block', margin:'10px 0'}}>Artifact reviewer Agent Sessions, one per line
                  <textarea aria-label="Work artifact reviewers" maxLength={8000} value={configEditor.reviewers}
                    disabled={busy || !configEditor.editable || !!configEditor.submission || configEditor.refreshPending}
                    onChange={event => setConfigEditor(value => ({...value, reviewers:event.target.value, result:null}))}
                    style={{display:'block', width:'100%', minHeight:48, marginTop:4}}/>
                </label>
                <label style={{display:'block', margin:'10px 0'}}><input type="checkbox" checked={configEditor.publicInputs}
                  disabled={busy || !configEditor.editable || !!configEditor.submission || configEditor.refreshPending}
                  onChange={event => setConfigEditor(value => ({...value, publicInputs:event.target.checked, result:null}))}/>
                  {' '}Work inputs are public text</label>
                <label style={{display:'block', margin:'10px 0'}}>Purpose
                  <select aria-label="Work configuration purpose" value={configEditor.purpose}
                    disabled={busy || !configEditor.editable || !!configEditor.submission || configEditor.refreshPending}
                    onChange={event => setConfigEditor(value => ({...value, purpose:event.target.value}))}
                    style={{display:'block', marginTop:4}}>
                    <option value="general">General Work</option>
                    <option value="artifact-publication">Artifact publication: public inputs and independent reviewers</option>
                  </select>
                </label>
                {configEditor.refreshPending ? <>
                  <p role="status" style={{fontSize:12}}>The Work configuration is saved. Reopen it before making another change.</p>
                  <button type="button" disabled={busy} onClick={() => openConfigEditor(configEditor.work)}>Reopen configuration</button>
                </> : configEditor.uncertain ? <>
                  <p role="status" style={{fontSize:12}}>This configuration was not confirmed. Retrying sends exactly the same configuration.</p>
                  <button type="submit" disabled={busy || !configEditor.editable}>Retry the same configuration</button>
                  <button type="button" disabled={busy} onClick={() => openConfigEditor(configEditor.work)}>Reopen configuration</button>
                  {configEditor.checked && <button type="button" disabled={busy} onClick={discardConfigAttempt}>Discard this attempt</button>}
                </> : <button type="submit" disabled={busy || !configEditor.editable || configEditor.draft?.stale ||
                  !Object.keys(configChanges(configEditor)).length}>{configEditor.draft ?
                    'Approve configuration changes' : 'Save configuration'}</button>}
                {configEditor.result && !configEditor.refreshPending && <p role="status" style={{fontSize:12}}>
                  {configEditor.result.reused ? 'This configuration was already saved.' : 'Configuration saved on the same Work.'}
                </p>}
                {configEditor.result && <details style={{fontSize:11, overflowWrap:'anywhere'}}>
                  <summary>Saved values</summary>
                  Configuration digest {configEditor.result.input_digest}.
                </details>}
              </form>}
          </details>}
          <label style={{display:'block', margin:'10px 0'}}><input type="checkbox" checked={publicReview}
            onChange={event => setPublicReview(event.target.checked)} disabled={busy}/>
            I confirm this Work, its source text, and instructions are public and may be sent to its selected model after approval.</label>
          <button disabled={busy || !editorsReady || !!native?.revision_pending || !targetAvailable || !publicReview ||
            !['project', 'agent'].includes(selectedRepairMode)}
            onClick={() => nativeAct(selectedRepairMode === 'agent' ? 'prepare_native' : 'prepare_project')}>Prepare repair</button>
          <button disabled={busy || !editorsReady || !!native?.revision_pending || !targetAvailable || !publicReview} onClick={() => nativeAct('prepare')}>Prepare review</button>
          </>}
        </>}
        {native?.state === 'published' && native.mode === 'project' && !revisionBase && <details style={{margin:'12px 0'}}>
          <summary>Work options</summary>
          <button disabled={busy || !editorsReady || !!native.revision_pending} onClick={() => beginWorkRevision()}>Revise inputs and criteria</button>
          {native.work_revision?.applied && native.work_revision.current_input_digest === native.work_revision.input_digest && <>
            <p role="status">Revised inputs saved on the same Work. Prepare them for review and approval.</p>
            <button disabled={busy || !editorsReady} onClick={() => nativeAct('prepare_revision')}>Prepare revised Work</button>
          </>}
          {native.work_revision?.applied && native.work_revision.current_input_digest !== native.work_revision.input_digest &&
            <p role="status">This revision was already saved, but the Work changed afterward. Reopen its current inputs before preparing.</p>}
        </details>}
        {native?.review_text && <details><summary>Exact model input · {native.model}</summary>
          <pre style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere', fontSize:11,
            maxHeight:220, overflow:'auto', padding:8, background:W.bg}}>{native.review_text}</pre>
        </details>}
        {artifactReview && native.input_digest && <div style={{fontSize:11, color:W.inkSoft, overflowWrap:'anywhere', margin:'8px 0'}}>
          Draft artifact: {native.artifact_name} · Input SHA-256: {native.input_digest}
        </div>}
        {native?.state === 'awaiting_approval' && <>
          {projectReviewExpired && <p role="status">This review expired. Refresh it to review the same input and approve again.</p>}
          {projectReviewExpired && native.approved === false && <button disabled={busy || !editorsReady || !!native.revision_pending}
            onClick={() => nativeAct('refresh_project_review')}>Refresh review</button>}
          {native.mode === 'agent' && artifactReviewExpired && <p role="status">This native review expired. Stop its retained session; the Work and its unapproved input remain saved.</p>}
          <button disabled={busy || !editorsReady || (artifactReview &&
            (artifactReviewExpired || native.approved === true || !native.review_text || !native.input_digest))}
            onClick={() => nativeAct('approve')}>{artifactReview ? 'Approve this repair' : 'Approve this input'}</button>
          <button disabled={busy || !editorsReady || (artifactReview && (artifactReviewExpired || native.approved !== true))}
            onClick={() => nativeAct('execute')}>{artifactReview ? 'Generate repair artifact' : 'Run approved review'}</button>
          {artifactReview && native.approved === true && <p role="status" style={{fontSize:12}}>This exact repair input is approved.</p>}
        </>}
        {native?.mode === 'agent' && ['attaching', 'preparing', 'awaiting_approval', 'executing', 'uncertain'].includes(native.state) &&
          <button type="button" title="Stop native session" aria-label="Stop native session" disabled={stoppingNative}
            onClick={stopNative} style={{padding:6, verticalAlign:'middle'}}>
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 14 14"><rect x="3" y="3" width="8" height="8" rx="1" fill="currentColor"/></svg>
          </button>}
        {native?.result_text && (artifactReview ?
          <div style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere', lineHeight:1.6}}>{native.result_text}</div> :
          <WorkshopReview text={native.result_text}/>)}
        {artifactReview && native.artifact && native.artifact.outcome !== 'failed' && <div style={{fontSize:12, overflowWrap:'anywhere', margin:'12px 0'}}>
          <strong>{native.artifact.name}</strong>
          <div>{native.artifact.bytes} bytes · SHA-256 {native.artifact.digest}</div>
          {native.artifact.summary && native.artifact.summary !== native.result_text && <p>{native.artifact.summary}</p>}
          <div style={{color:W.inkSoft}}>Draft patch generated. Review and verification are required before applying it.</div>
          <button disabled={busy || !editorsReady || !['settled', 'published', 'publication_uncertain', 'release_pending'].includes(native.state)}
            onClick={() => nativeAct('read_artifact')}>Download patch</button>
        </div>}
        {savedPublications.length > 0 && <section aria-label="Agent publications" style={{margin:'16px 0'}}>
          <h4 style={{fontSize:13, margin:'8px 0'}}>Agent results</h4>
          {savedPublications.map(artifact => <div key={artifact.publication}
            style={{fontSize:12, overflowWrap:'anywhere', padding:'10px 0', borderTop:`1px solid ${W.line}`}}>
            <strong>{artifact.name}</strong>
            <span style={{color:W.inkSoft}}> · {artifact.bytes} bytes · {artifact.available ? 'Draft' : 'Work or evidence changed'}</span>
            <button title="Inspect verified patch" aria-label={`Inspect ${artifact.name}`} disabled={busy || !editorsReady || !artifact.available}
              onClick={() => nativeAct('read_publication', artifact)}>↗</button>
          </div>)}
          {publicationView?.work === artifactWork && <section aria-label="Selected agent result">
            <strong>{publicationView.name}</strong>
            <button title="Close result" aria-label="Close result" onClick={() => setPublicationView(null)}>×</button>
            <p style={{fontSize:12, color:W.inkSoft}}>Draft only. Opening this patch does not apply it or approve the Work.</p>
            <pre tabIndex={0} style={{maxHeight:400, overflow:'auto', fontSize:12, whiteSpace:'pre'}}>{publicationView.artifact_text}</pre>
          </section>}
        </section>}
        {savedArtifacts.length > 0 && <section aria-label="Saved Work patches" style={{margin:'16px 0'}}>
          <h4 style={{fontSize:13, margin:'8px 0'}}>Saved patches for this Work</h4>
          {savedArtifacts.map(artifact => <div key={artifact.result + ':' + artifact.receipt}
            style={{fontSize:12, overflowWrap:'anywhere', padding:'10px 0', borderTop:`1px solid ${W.line}`}}>
            <strong>{artifact.name}</strong>
            <div>{artifact.bytes} bytes · SHA-256 {artifact.digest}</div>
            {artifact.summary && <p>{artifact.summary}</p>}
            <p style={{color:W.inkSoft}}>Saved draft patch. Review and verify it before applying.</p>
            <button disabled={busy || !editorsReady} onClick={() => nativeAct('read_artifact', artifact)}>Download saved patch</button>
            {native?.state === 'idle' && artifact.mode !== 'agent' && <details style={{marginTop:8}}>
              <summary>Continue this Work</summary>
              <p>Resume review of this saved result and revise the same task. This does not rerun the model.</p>
              <button disabled={busy || !editorsReady} onClick={() => nativeAct('recover_review', artifact)}>Resume review</button>
            </details>}
          </div>)}
        </section>}
        {failedProjects.length > 0 && <section aria-label="Failed project attempts" style={{margin:'16px 0'}}>
          <h4 style={{fontSize:13, margin:'8px 0'}}>Failed attempts for this Work</h4>
          {failedProjects.map(failure => <div key={failure.receipt} style={{fontSize:12, overflowWrap:'anywhere', margin:'10px 0'}}>
            <div>{failure.error}</div>
            <div style={{color:W.inkSoft}}>Receipt: {failure.receipt}</div>
            <p>Prepare a retry of this same Work after its prior worker has disconnected. You will review and approve fresh input before any model runs.</p>
            <button disabled={busy || !editorsReady || !['idle', 'settled', 'published', 'publication_uncertain', 'uncertain'].includes(native?.state)}
              onClick={() => nativeAct('recover_project', failure)}>Prepare retry of this Work</button>
          </div>)}
        </section>}
        {localDeliveries.length > 0 && <details style={{margin:'12px 0'}}>
          <summary>Unreceived project results · {localDeliveries.length}</summary>
          {localDeliveries.map(delivery => <div key={delivery.grant} style={{fontSize:12, margin:'10px 0'}}>
            <p>No patch was received. The provider may have processed the request; its outcome is unknown.</p>
            {delivery.state === 'local_delivery_abandoned' ? <>
              <p role="status">Local delivery closed. Its original result remains saved.</p>
              <button disabled={busy || !editorsReady || !!revisionBase || !['idle', 'local_delivery_abandoned'].includes(native?.state)}
                onClick={() => beginWorkRevision(delivery)}>{native?.revision_pending ? 'Finish saved revision' : 'Revise inputs and criteria'}</button>
              <p>Prepare this Work under a fresh worker once the previous worker disconnects. Review and approval are required before another model runs.</p>
              <button disabled={busy || !editorsReady || !!revisionBase || !!native?.revision_pending || !['idle', 'local_delivery_abandoned'].includes(native?.state)}
                onClick={() => nativeAct('recover_local_project', delivery)}>Prepare this Work again</button>
              </> : <>
                <p>Close local delivery to leave this attempt. This does not cancel the provider request or run it again.</p>
                <button disabled={busy || !editorsReady || !['idle', 'uncertain'].includes(native?.state)}
                  onClick={() => nativeAct('abandon_project', delivery)}>Close local delivery</button>
              </>}
          </div>)}
        </details>}
        {native?.state === 'uncertain' &&
          <button disabled={busy || !editorsReady} onClick={() => nativeAct('reconcile')}>Recover recorded result</button>}
        {['settled', 'publication_uncertain'].includes(native?.state) &&
          !(native?.mode === 'agent' && native.native_result?.outcome === 'failed') &&
          <button disabled={busy || !editorsReady} onClick={() => nativeAct('publish')}>Publish result to Workshop</button>}
        {(['published', 'local_delivery_abandoned', 'release_pending'].includes(native?.state) ||
          (native?.mode === 'agent' && native.state === 'settled' && native.native_result?.state === 'settled' &&
            native.native_result?.outcome === 'failed' && native.native_result?.receipt) ||
          (native?.mode === 'agent' && native.state === 'native_cancelled' &&
            native.native_cancellation?.state === 'cancelled' && native.native_cancellation.releasable === true)) &&
          <button disabled={busy || !editorsReady || !!revisionBase || !!native.revision_pending} onClick={() => nativeAct('release')}>
            {native.state === 'release_pending' ? 'Recover closed result' :
              native.state === 'native_cancelled' ? 'Close cancelled review' : 'Close result'}</button>}
        {native?.error && <p role="alert">{native.error}</p>}
        {nativeSyncError && <p role="status">{nativeSyncError}</p>}
    </section>}
  </>;
  // The proposed workflow's approval row reads the native Work gate: approve, stop, or nothing pending.
  const approvalWork = native?.work ? (projectedWorkNodes.find(node => node.id === native.work)?.title || native.work) : '';
  const awaiting = native?.state === 'awaiting_approval';
  const running = ['attaching', 'preparing', 'executing', 'recovering'].includes(native?.state);
  const approval = awaiting && native.approved !== true
    ? {bg:W.err + '1f', c:W.err, l:`AWAITING YOUR APPROVAL · ${String(approvalWork).toUpperCase()}`}
    : (awaiting && native.approved === true) || running
      ? {bg:W.cyan + '1c', c:W.cyan, l:`APPROVED · WORK: ${String(approvalWork).toUpperCase()}`}
      : {bg:W.bgSoft, c:W.inkMuted, l:'NOTHING AWAITS APPROVAL'};
  const chainNodes = [...flow.flow].sort((a, b) => a.col - b.col || a.y - b.y);
  // As in the design, the proposed workflow answers the owner's opening message when the page starts with one.
  const openingAsk = taskItems[0]?.kind === 'message' && taskItems[0].message.sender_root === transcript?.self ? 0 : -1;
  const room = {name:descriptor.label, col:W.accent, ink:W.onFill, ini:(String(descriptor.label || 'W').trim().charAt(0) || 'W').toUpperCase()};
  const workflowCard = chainNodes.length > 0 && (
    <div style={{ display:'flex', gap:12 }}>
      <Av a={room} s={28}/>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'baseline', gap:8, marginBottom:4 }}>
          <span style={{ fontSize:12.5, fontWeight:500 }}>{descriptor.label}</span>
          <span style={{ fontFamily:W.mono, fontSize:9, color:W.inkMuted, border:`1px solid ${W.line}`, borderRadius:3, padding:'1px 5px' }}>canvas</span>
        </div>
        <div style={{ fontFamily:W.serif, fontSize:15, lineHeight:1.6, marginBottom:11 }}>
          Here is the workflow on this canvas. {chainNodes.length} nodes, {chainNodes.filter(n => n.state === 'block').length} of them yours to confirm.
        </div>
        <div style={{ background:W.bg, border:`1px solid ${W.lineSoft}`, borderRadius:7, padding:'12px 13px', display:'flex', flexWrap:'wrap', alignItems:'center', columnGap:0, rowGap:10 }}>
          {chainNodes.map((n, i, arr) => (
            <React.Fragment key={n.id}>
              <div style={{ border:`1px solid ${n.state==='block' ? W.accent : W.line}`, background:W.bgPanel, borderRadius:5, padding:'6px 9px', fontSize:11, lineHeight:1.25, maxWidth:220, overflowWrap:'anywhere' }}>
                {n.t}<div style={{ fontFamily:W.mono, fontSize:8.5, color:W.inkMuted, letterSpacing:'0.06em', marginTop:2 }}>{n.p}</div>
              </div>
              {i < arr.length - 1 && <span style={{ width:22, height:1, background:W.line, flex:'none' }}/>}
            </React.Fragment>
          ))}
          <div style={{ flexBasis:'100%', height:11 }}/>
          <div style={{ display:'flex', alignItems:'center', gap:7, width:'100%' }}>
            <span style={{ fontFamily:W.mono, fontSize:9, letterSpacing:'0.1em', padding:'2px 6px', borderRadius:3,
              background:approval.bg, color:approval.c, overflowWrap:'anywhere' }}>
              {approval.l}
            </span>
            <div style={{ flex:1 }}/>
            <IBtn g="⌗" title="Open as nodes" onClick={openAsNodes}/>
            {native?.mode === 'agent' && (running || awaiting)
              ? <IBtn g="⊘" title="Stop native session — stops the builders" disabled={stoppingNative} onClick={stopNative}/>
              : awaiting && native.approved !== true
                ? <Btn sm pri disabled={busy || !editorsReady || (artifactReview && (artifactReviewExpired || !native.review_text || !native.input_digest))} onClick={() => nativeAct('approve')}>Approve</Btn>
                : null}
          </div>
        </div>
      </div>
    </div>
  );

  // Delivery state, relayed replies, agent-proposed workflows and independent review
  // (workshop_workflow.py). Every state shown here is read from the Workshop's own
  // receipts; a stored message is only stored until a receipt says otherwise.
  const DELIVERY_TONE = {replied:W.ok, started:W.cyan, unavailable:W.err, uncertain:W.warn, stored:W.inkMuted};
  const contactLabel = root => (nativeContacts.find(row => row.root === root) || {}).label || names.get(root) || String(root || 'agent');
  const workflowApi = authority && typeof authority.workshopWorkflow === 'function' ? authority : null;
  const wfAct = async (action, fields) => {
    if (busyRef.current || !workflowApi) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try { await workflowApi.workshopWorkflow(descriptor.root, action, fields); }
    catch (error) { setActionError(error.message || 'The workflow action could not be confirmed.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const saveParam = async (relation, value) => {
    if (busyRef.current || !workflowApi) return;
    busyRef.current = true; setBusy(true); setActionError('');
    try { await workflowApi.workshopWorkflowParam(descriptor.root, relation, value); }
    catch (error) { setActionError(error.message || 'The parameter was not saved.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const chip = (label, tone, title, key) => <span key={key} title={title} style={{ fontFamily:W.mono, fontSize:9.5, letterSpacing:'0.04em',
    color:tone, border:`1px solid ${tone}`, borderRadius:3, padding:'1px 5px', overflowWrap:'anywhere' }}>{label}</span>;
  const deliveryChips = message => {
    if (!Array.isArray(message.delivery)) return null;
    const rows = message.delivery.length ? message.delivery : [{recipient:null, state:message.state}];
    return <div aria-label="Delivery state" style={{ display:'flex', gap:6, flexWrap:'wrap', marginTop:6 }}>
      {rows.map((row, index) => chip((row.recipient ? contactLabel(row.recipient) + ' · ' : '') + String(row.state).toUpperCase(),
        DELIVERY_TONE[row.state] || W.inkMuted, row.reason || (row.state === 'uncertain' ? 'Delivery may have happened; it is never resent automatically.' : ''),
        (row.recipient || 'stored') + ':' + index))}
    </div>;
  };
  const relayedActions = message => {
    if (!workflowApi) return null;
    const reviewers = nativeContacts.filter(row => row.root !== message.relayed_from).slice(0, 3);
    const proposal = /"actions"\s*:/.test(message.agent_text);
    if (!proposal && !reviewers.length) return null;
    return <div style={{ display:'flex', gap:6, flexWrap:'wrap', alignItems:'center', marginTop:8 }}>
      {chip('sha256 ' + String(message.artifact_digest || '').slice(0, 12), W.inkMuted, 'Artifact digest of this reply', 'digest')}
      {proposal && <Btn sm disabled={busy} onClick={() => wfAct('workflow-draft', {message:message.root})}>Draft as workflow</Btn>}
      {reviewers.map(row => <Btn sm key={row.root} disabled={busy} title="A different agent reviews this reply; its verdict is evidence, not a court pass."
        onClick={() => wfAct('artifact-review', {artifact:message.root, reviewer:row.root})}>{'Review with ' + row.label}</Btn>)}
    </div>;
  };
  const HIDDEN_PARAMS = new Set(['engine', 'definition', 'version']);
  const proposedWorkflows = Array.isArray(transcript?.workflows) ? transcript.workflows : [];
  const artifactReviews = Array.isArray(transcript?.reviews) ? transcript.reviews : [];
  const workflowsPanel = (proposedWorkflows.length > 0 || artifactReviews.length > 0) && (
    <div aria-label="Agent-proposed workflows and reviews" style={{ display:'flex', flexDirection:'column', gap:12 }}>
      {proposedWorkflows.map(wf => {
        const approved = wf.approval && wf.approval.current === true;
        const status = approved ? chip('APPROVED · READY TO RUN', W.ok, 'Approval ' + String(wf.approval.digest).slice(0, 12), 's')
          : wf.approval ? chip('CHANGED SINCE APPROVAL', W.warn, 'Review and approve again before it runs.', 's')
          : chip('AWAITING YOUR APPROVAL', W.err, 'A proposal is not approval.', 's');
        return <div key={wf.root} style={{ background:W.bgPanel, border:`1px solid ${W.line}`, borderRadius:7, padding:'12px 13px' }}>
          <div style={{ display:'flex', alignItems:'center', gap:8, flexWrap:'wrap', marginBottom:8 }}>
            <span style={{ fontSize:12.5, fontWeight:500 }}>{wf.title}</span>
            {chip('proposed by ' + contactLabel(wf.proposed_by), W.inkMuted, wf.proposed_by, 'p')}
            {status}
          </div>
          {wf.reason && <div role="status" style={{ fontSize:11.5, color:W.warn, marginBottom:8 }}>{wf.reason}</div>}
          <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {(wf.nodes || []).map(node => <div key={node.root} style={{ border:`1px solid ${W.lineSoft}`, borderRadius:5, padding:'7px 9px' }}>
              <div style={{ fontSize:11.5, marginBottom:4 }}>{node.title} <span style={{ fontFamily:W.mono, fontSize:9, color:W.inkMuted }}>{node.engine}</span></div>
              {Object.entries(node.params || {}).filter(([label]) => !HIDDEN_PARAMS.has(label)).map(([label, param]) =>
                <form key={param.relation + ':' + param.value} onSubmit={e => { e.preventDefault(); if (param.editable) saveParam(param.relation, e.currentTarget.elements.value.value); }}
                  style={{ display:'flex', alignItems:'center', gap:6, margin:'3px 0' }}>
                  <span style={{ fontFamily:W.mono, fontSize:9.5, color:W.inkMuted, minWidth:88 }}>{label}</span>
                  {param.editable
                    ? <><input name="value" aria-label={label} defaultValue={param.value} disabled={busy} maxLength={12000}
                        style={{ flex:1, minWidth:0, border:`1px solid ${W.line}`, borderRadius:4, background:W.bg, color:W.ink, fontSize:11.5, padding:'3px 6px' }}/>
                      <Btn sm disabled={busy} onClick={e => saveParam(param.relation, e.currentTarget.form.elements.value.value)}>Save</Btn></>
                    : <span style={{ fontSize:11.5, color:W.inkSoft, overflowWrap:'anywhere' }}>{label === 'agent' || label === 'reviewer' ? contactLabel(param.value) : param.value}</span>}
                </form>)}
            </div>)}
          </div>
          <div style={{ display:'flex', gap:8, marginTop:10, alignItems:'center' }}>
            <span style={{ fontFamily:W.mono, fontSize:9, color:W.inkMuted }}>{wf.digest ? 'behavior ' + wf.digest.slice(0, 12) : ''}</span>
            <div style={{ flex:1 }}/>
            <Btn sm disabled={busy || !wf.digest || approved} onClick={() => wfAct('workflow-approve', {workflow:wf.root, digest:wf.digest})}>Approve</Btn>
            <Btn sm pri disabled={busy || !approved} onClick={() => wfAct('workflow-execute', {workflow:wf.root})}>Run approved</Btn>
          </div>
        </div>;
      })}
      {artifactReviews.map(review => <div key={review.review} style={{ display:'flex', gap:6, flexWrap:'wrap', alignItems:'center', fontSize:11.5 }}>
        <span>Independent review of {String(review.artifact_digest).slice(0, 12)}</span>
        {chip('judged by ' + contactLabel(review.judged_by), W.cyan, review.judged_by, 'j')}
        {chip('produced by ' + contactLabel(review.claimed_by), W.inkMuted, review.claimed_by, 'c')}
        {chip(String(review.state).toUpperCase(), DELIVERY_TONE[review.state] || W.inkMuted, '', 'st')}
        {review.verdict && chip('VERDICT ' + String(review.verdict).toUpperCase(), review.verdict === 'pass' ? W.ok : review.verdict === 'fail' ? W.err : W.warn,
          'Review evidence from the reviewer; not a court pass.', 'v')}
      </div>)}
    </div>
  );

  const msgRow = message => {
    const relayed = typeof message.relayed_from === 'string' && typeof message.agent_text === 'string';
    // A relayed reply is recorded by this application, but it is the agent's own text.
    const isUser = !relayed && message.sender_root === transcript?.self;
    const a = relayed ? {...agent(message.relayed_from), name:contactLabel(message.relayed_from),
      ini:(contactLabel(message.relayed_from).trim().charAt(0) || 'A').toUpperCase()} : agent(message.sender_root);
    const to = Array.isArray(message.recipient_roots) ?
      (message.recipient_roots.length ? message.recipient_roots.map(root => names.get(root) || root).join(', ') : 'Workshop') :
      (names.get(message.recipient_root) || message.recipient_root || 'Workshop');
    return (
      <div key={message.root} data-workshop-message={message.root} style={{ display:'flex', gap:12 }}>
        {isUser ? <span aria-hidden="true" style={{ width:28, height:28, borderRadius:'50%', background:W.userAv, color:W.onUserAv, display:'grid', placeItems:'center', fontSize:12, fontWeight:700, flex:'none' }}>{a.ini}</span> : <Av a={a} s={28}/>}
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ display:'flex', alignItems:'baseline', gap:8, marginBottom:4, flexWrap:'wrap' }}>
            <span title={message.sender_root} style={{ fontSize:12.5, fontWeight:500, overflowWrap:'anywhere' }}>{a.name}</span>
            <span title={[message.state === 'acted' ? 'Acted on \u00b7 verification separate' : message.state, message.category, message.reply_to_root ? 'Reply' : ''].filter(Boolean).join(' \u00b7 ')}
              style={{ fontFamily:W.mono, fontSize:9.5, color:W.inkMuted, border:`1px solid ${W.line}`, borderRadius:3, padding:'1px 5px', overflowWrap:'anywhere' }}>to {to}</span>
          </div>
          <div style={{ fontSize:messageTextSize, lineHeight:1.6, fontFamily: isUser ? W.sans : W.serif, letterSpacing: isUser ? 0 : '-0.003em', whiteSpace:'pre-wrap', overflowWrap:'anywhere' }}>
            {relayed ? message.agent_text :
              String(message.body || '').startsWith('Model review evidence. Independent review is still required.\n') ?
              <WorkshopReview text={message.body.slice(message.body.indexOf('\n') + 1)}/> : message.body}
          </div>
          {relayed ? relayedActions(message) : deliveryChips(message)}
        </div>
      </div>
    );
  };

  const composer = (
    <div style={{ borderTop:`1px solid ${W.lineSoft}`, padding:'12px 0 16px' }}>
      <div style={{ maxWidth: preset==='conversation' ? 760 : 'none', margin:'0 auto', padding:'0 26px' }}>
        {protectedEditors && !editorsReady && <div role={editorError ? 'alert' : 'status'} style={{ fontSize:11.5, color:W.inkSoft, marginBottom:8 }}>
          {editorError || 'Connecting draft protection\u2026'}
          {editorError && <span style={{ marginLeft:8 }}><Btn sm onClick={prepareEditors}>Retry</Btn></span>}
        </div>}
        {actionError && <div role="alert" style={{ fontSize:11.5, color:W.err, marginBottom:8 }}>{actionError}</div>}
        {state?.workshopNotice && <div role="status" style={{ fontSize:11.5, color:W.inkSoft, marginBottom:8 }}>{state.workshopNotice}</div>}
        <div style={{ background:W.bgPanel, border:`1px solid ${W.line}`, borderRadius:9, padding:'11px 13px' }}>
          {!joined && !existing ? <Btn pri disabled={busy || !transcript?.can_join} onClick={() => act('attach')}>{busy ? 'Joining\u2026' : 'Join Workshop'}</Btn> : <>
          <input aria-label="Workshop message" value={draft} maxLength={12000} disabled={busy || !joined}
            onChange={e => { if (editorsReady) protectDraft('message'); setDraft(e.target.value); }} onKeyDown={e => { if (e.key === 'Enter') send(); }}
            placeholder={!joined ? 'Messaging requires an admitted Workshop participant.' : !target ? 'Reply to the Workshop…' : `Message ${targetName}…`}
            style={{ width:'100%', border:0, background:'transparent', outline:'none', color:W.ink, fontFamily:W.serif, fontSize:16.5, letterSpacing:'-0.01em', padding:'2px 0 9px' }}/>
          <div style={{ display:'flex', alignItems:'center', gap:6, flexWrap:'wrap' }}>
            <select aria-label="Recipient" value={target} disabled={busy || !joined} onChange={e => {
              if (e.target.value === WS_SHOW_OFFLINE) setShowOfflineContacts(value => !value); else setTarget(e.target.value);
            }} style={{ padding:'3px 8px', borderRadius:5, background:W.accentDim,
              border:`1px solid ${W.accentSoft}`, color:W.accent, fontFamily:W.mono, fontSize:10, letterSpacing:'0.04em', cursor:'pointer', maxWidth:'min(100%, 240px)' }}>
              <option value="">to: Workshop (everyone)</option>
              {modelAgent && <option value={'model:' + modelAgent.root}>{`to: @Agent · ${modelAgent.model}`}</option>}
              {pickerContacts.length > 0 && <optgroup label="Connected agent environments">
                {pickerContacts.map(row => <option key={row.root} value={'contact:' + row.root}>
                  {`to: @${row.label} · ${row.connected === true ? row.app : row.connected === false ? 'offline' : 'availability unknown'}`}
                </option>)}
              </optgroup>}
              {addressable.map(row => <option key={row.root} value={row.root}>{`to: @${row.label}`}</option>)}
              {(offlineContacts > 0 || showOfflineContacts) && <option value={WS_SHOW_OFFLINE}>
                {showOfflineContacts ? 'hide disconnected' : `show disconnected (${offlineContacts})`}</option>}
            </select>
            <IBtn g="@" title="Address one agent" acc={!!target} disabled={busy || !joined || (!target && !firstRecipient)} onClick={() => setTarget(target ? '' : firstRecipient)}/>
            <IBtn g="⌗" title="Open as nodes" onClick={openAsNodes}/>
            {!existing && transcript && <select aria-label="Connected task node" value={execution} disabled={busy} onChange={e => setExecution(e.target.value)} style={{ padding:'3px 8px', borderRadius:5, background:W.bg,
              border:`1px solid ${W.line}`, color:W.inkSoft, fontFamily:W.mono, fontSize:10, letterSpacing:'0.04em', cursor:'pointer', maxWidth:'100%' }}>
              <option value="">Message only</option>
              {(transcript.execution_nodes || []).map(row => <option key={row.root} value={row.root}>{row.label}</option>)}
            </select>}
            <div style={{ flex:1 }}/>
            <span style={{ fontFamily:W.mono, fontSize:10, color:W.inkMuted }}>{agents.filter(a => a.status !== 'off').length} agents listening</span>
            <Btn pri disabled={sendDisabled} onClick={send}>{busy ? 'Sending\u2026' : execution ? 'Assign task' : 'Send ↵'}</Btn>
          </div>
          </>}
        </div>
        {contactError && <p role="status" style={{ margin:'8px 0 0', fontSize:11.5, color:W.inkSoft }}>{contactError}</p>}
      </div>
    </div>
  );

  const bar = (
    <div style={{ gridColumn:'1 / -1', display:'flex', alignItems:'center', gap:10, padding:'0 14px', height:34, minWidth:0,
      borderBottom:`1px solid ${W.line}`, background:W.bgPanel }}>
      <span style={{ display:'inline-flex', alignItems:'center', gap:6, padding:'3px 9px', border:`1px solid ${W.accentSoft}`,
        background:W.accentDim, borderRadius:5, fontFamily:W.mono, fontSize:9.5, letterSpacing:'0.14em', color:W.accent }}>
        <Dot c={W.accent} pulse/>WORKSHOP
      </span>
      <span title={descriptor.root} style={{ fontFamily:W.mono, fontSize:10.5, color:W.inkSoft, letterSpacing:'0.04em', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', minWidth:0 }}>{descriptor.label}</span>
      <span style={{ width:1, height:16, background:W.line, flex:'none' }}/>
      <span style={{ fontFamily:W.mono, fontSize:10, color:W.inkMuted, whiteSpace:'nowrap' }}>
        {counts.block} needs you · {counts.run} running{counts.paused ? ` · ${counts.paused} paused` : ''}{counts.review ? ` · ${counts.review} submitted` : ''} · {counts.done} delivered
      </span>
      <div style={{ flex:1 }}/>
      <Lbl>LAYOUT</Lbl>
      <WorkshopLayoutStrip layout={preset} setLayout={setPreset}/>
      <IBtn g="✕" title="Leave Workshop — back to the plain conversation" s={22} onClick={() => (onLeave ? onLeave() : setMode('chat'))}/>
    </div>
  );

  const stream = (
    <section aria-label="Workshop conversation" style={{ display:'flex', flexDirection:'column', minHeight:0, minWidth:0, background:W.bg, overflow:'hidden' }}>
      <div ref={messageViewport} className="ah-scroll" onScroll={() => messageScroll.current.scroll(messageViewport.current)}
        style={{ flex:1, overflow:'auto', overflowAnchor:'none', padding:'20px 0 10px' }}>
        <div ref={messageContent} style={{ maxWidth: preset==='conversation' ? 760 : 'none', margin:'0 auto', padding:'0 26px', display:'flex', flexDirection:'column', gap:20 }}>
          {transcript?.error && <div role="alert" style={{ fontSize:12.5, color:W.err }}>{transcript.error}</div>}
          {!transcript && <div role="status" style={{ fontFamily:W.serif, fontSize:15, color:W.inkSoft }}>Loading messages…</div>}
          <ConversationArchiveNotice root={descriptor.root}/>
          {!content && transcript?.has_older && <div style={{ fontSize:12.5, color:W.inkSoft }}>Showing the available recent messages.</div>}
          {openingAsk < 0 && workflowCard}
          {workflowsPanel}
          {transcript && !transcript.error && !messages.length && <div style={{ fontFamily:W.serif, fontSize:15, color:W.inkSoft }}>{olderPage ? 'No messages on this page.' : 'No messages have been sent in this Workshop yet.'}</div>}
          {taskItems.map((item, index) => {
            if (item.kind !== 'task') return msgRow(item.message);
            const t = tasks.find(x => x.work === item.work);
            return t && <TaskCard key={'task:' + t.work} t={t} sel={selTask===t.work} onSelect={selectTask} onDecide={decide} compact={preset==='graph'} agent={agent} busy={busy}/>;
          }).flatMap((row, index) => index === openingAsk ? [row, <React.Fragment key="workflow">{workflowCard}</React.Fragment>] : [row])}
        </div>
      </div>
      {composer}
    </section>
  );

  const board = (
    <section aria-label="Workshop task board" style={{ display:'flex', flexDirection:'column', minHeight:0, minWidth:0, background:W.bg, overflow:'hidden' }}>
      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:14, display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(252px,1fr))', gap:12, alignContent:'start' }}>
        {[['block','NEEDS YOU'],['run','RUNNING'],['done','DELIVERED']].map(([s, l]) => { const rows = tasks.filter(t => t.state===s || (s==='run' && ['paused', 'review', 'open', 'queued'].includes(t.state))); return (
          <div key={s} style={{ display:'flex', flexDirection:'column', gap:10, minWidth:0 }}>
            <div style={{ display:'flex', alignItems:'center', gap:7, paddingBottom:8, borderBottom:`1px solid ${W.lineSoft}` }}>
              <Dot c={CHIP[s].c} pulse={s==='run'}/><h3 style={{ margin:0, fontWeight:400, fontSize:'inherit', lineHeight:'inherit', display:'inline-flex' }}><Lbl c={CHIP[s].c}>{l}</Lbl></h3><div style={{ flex:1 }}/><Lbl>{rows.length}</Lbl>
            </div>
            {s === 'block' && !tasks.length && <div role="status" style={{ fontSize:11.5, lineHeight:1.5, color:W.inkSoft }}>No message on this page names a Work, so there is nothing to group.</div>}
            {rows.map(t => <TaskCard key={t.work} t={t} sel={selTask===t.work} onSelect={selectTask} onDecide={decide} compact agent={agent} busy={busy}/>)}
          </div>
        ); })}
      </div>
      {composer}
    </section>
  );

  const cols = externalRail
    ? (preset==='graph' ? 'minmax(0,1fr) minmax(0,1fr)' : preset==='board' ? 'minmax(0,1fr) 300px' : 'minmax(0,1fr) 320px')
    : (preset==='graph' ? '200px minmax(0,1fr) minmax(0,1fr)' : preset==='board' ? '212px minmax(0,1fr) 300px' : '262px minmax(0,1fr) 320px');
  return (
    <main style={{ gridColumn:'1 / -1', gridRow:'2', minHeight:0, overflow:'hidden', display:'grid',
      gridTemplateColumns:cols, gridTemplateRows:'34px minmax(0,1fr)' }}>
      {bar}
      {!externalRail && <AgentsRail context={{descriptor, graphId:state?.canvas?.graph_id, scopeRoot:state?.canvas?.root, transcript, state}}
        sel={selAgentId} onSelect={setSelAgent} compact={preset!=='conversation'}/>}
      {preset==='board' ? board : stream}
      {preset==='graph'
        ? <GraphPane flow={flow} selTask={selTask} tidy={tidy} chain={chain}
            onArrange={() => setTidy(t => !t)} onChain={() => setChain(c => !c)} onOpen={openAsNodes}/>
        : <ContextPanel selAgent={selTask ? null : selAgent} selTask={selTask} tasks={tasks} agent={agent} descriptor={descriptor}
            activity={activity} activityNote={activityNote} counts={counts} listening={listening}
            controls={controls} controlsOpen={controlsOpen} onControls={() => setControlsOpen(o => !o)}/>}
      <style>{`
        [aria-label="Native Workshop review"] button,
        [aria-label="Native Workshop review"] select,
        [aria-label="Native Workshop review"] input:not([type="checkbox"]),
        [aria-label="Native Workshop review"] textarea {
          background:${W.bg}; color:${W.ink}; border:1px solid ${W.line};
          border-radius:5px; padding:5px 9px; font-family:${W.sans}; font-size:11.5px; max-width:100%; box-sizing:border-box;
        }
        [aria-label="Native Workshop review"] button {margin:4px 4px 4px 0; cursor:pointer; background:transparent; color:${W.inkSoft}; padding:5px 12px;}
        [aria-label="Native Workshop review"] summary {font-family:${W.mono}; font-size:10px; letter-spacing:0.04em; color:${W.inkSoft}; cursor:pointer;}
        [aria-label="Native Workshop review"] h3, [aria-label="Native Workshop review"] h4 {font-family:${W.mono}; font-size:9px; font-weight:400; letter-spacing:0.18em; text-transform:uppercase; color:${W.inkMuted};}
        [aria-label="Native Workshop review"] button:disabled {border-style:dashed; cursor:default;}
      `}</style>
    </main>
  );
};

// ── layout strip: the design bar's three presets ──
const WORKSHOP_LAYOUTS = [['conversation', '≡', 'Conversation'], ['board', '▤', 'Task board'], ['graph', '⌗', 'Chat + live graph']];
const WorkshopLayoutStrip = ({layout, setLayout}) => (
  <div role="group" aria-label="Workshop layout" style={{ display:'flex', border:`1px solid ${W.line}`, borderRadius:5, overflow:'hidden' }}>
    {WORKSHOP_LAYOUTS.map(([k, g, l]) => (
      <button key={k} type="button" onClick={() => setLayout(k)} title={l} aria-label={l} aria-pressed={layout === k} style={{ width:28, height:22, border:0, borderRadius:0, margin:0, cursor:'pointer', padding:0,
        background: layout===k ? W.ink : 'transparent', color: layout===k ? W.bg : W.inkSoft, fontFamily:W.mono, fontSize:12 }}>{g}</button>
    ))}
  </div>
);
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
        identity = key; following = !older; anchors = []; position = 0;
        return move(viewport, following ? viewport.scrollHeight : 0);
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
const WorkshopReview = ({text}) => {
  let review;
  try {review = JSON.parse(text);} catch (_) {}
  if (!review || typeof review.summary !== 'string' || !Array.isArray(review.next_actions) ||
      !Array.isArray(review.risks) || [...review.next_actions, ...review.risks].some(value => typeof value !== 'string')) {
    return <div style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere'}}>{text}</div>;
  }
  return <div style={{lineHeight:1.6, overflowWrap:'anywhere'}}>
    <p>{review.summary}</p>
    <ul style={{paddingLeft:20}}>{review.next_actions.map((action,index) => <li key={index}>{action}</li>)}</ul>
    {review.risks.length > 0 && <><div style={{color:W.inkSoft}}>Risks</div>
      <ul style={{paddingLeft:20}}>{review.risks.map((risk,index) => <li key={index}>{risk}</li>)}</ul></>}
    <div style={{fontSize:11, color:W.inkSoft}}>Independent review is still required.</div>
    {typeof review.uncertainty === 'number' && Number.isFinite(review.uncertainty) &&
      <div style={{fontSize:11, color:W.inkSoft}}>Model uncertainty: {Math.round(review.uncertainty * 100)}%</div>}
  </div>;
};

window.WorkshopView = WorkshopView;
window.WorkshopAgentsRail = AgentsRail;
})();