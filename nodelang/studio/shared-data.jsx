// shared-data.jsx — shared presentation data and read-only projection selectors.

// The existing Work/task and proposal projections, shared by both Workshop faces.
window.ARCHHUB_WORKSHOP_TASK_SOURCE = (() => {
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

const WORKSHOP_WORK_REF = /\b((?:assembly-instance|work):[A-Za-z0-9_-]{6,})/;
const WORKSHOP_TASK_STATES = [
  [/^\s*(archived|cancelled|canceled)\b/i, 'archived'],
  [/\b(fail(?:ed|s)?|refused|rejected|blocked|error|needs? (?:you|review|input|approval))\b/i, 'block'],
  [/^\s*(delivered|accepted|completed|merged)\b/i, 'done'],
  [/^\s*(submitted)\b/i, 'review'],
  [/^\s*(claimed|started|running|working on|assigned)\b/i, 'run'],
];
// An agent's relayed reply is that agent speaking: its sender is the contact the relay answered for,
// its text the agent's own text (never the relay's header or the relay author).
const wsSender = message => typeof message?.relayed_from === 'string' ? message.relayed_from : message?.sender_root;
const wsText = message => typeof message?.relayed_from === 'string' && typeof message.agent_text === 'string'
  ? message.agent_text : String(message?.body || '');
const wsLifecycleEvent = message => !message?.agent_text &&
  (!!message?.lifecycle_event || message?.category === 'lifecycle' ||
    /^\s*(?:claimed|started|assigned|submitted|completed|delivered|accepted|archived|cancelled|failed|blocked)\s+(?:Work\b|work:|assembly-instance:)/i.test(wsText(message)));
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
const workshopTaskItems = (messages, nodes, plannedItems) => {
  const byId = new Map((Array.isArray(nodes) ? nodes : []).map(node => [node.id, node]));
  const cards = new Map(), items = [];
  (Array.isArray(messages) ? messages : []).forEach(message => {
    const referenced = message.work_root || message.task_root || (message.reference_roots || message.refs || []).find(id => byId.has(id));
    const match = referenced ? [null,referenced] : WORKSHOP_WORK_REF.exec(wsText(message));
    if (!match) { items.push({kind:'message', message}); return; }
    let card = cards.get(match[1]);
    if (!card) { card = {kind:'task', work:match[1], node:byId.get(match[1]) || null, events:[]}; cards.set(match[1], card); items.push(card); }
    card.events.push(message);
  });
  cards.forEach(card => {
    const latest = wsText(card.events[card.events.length - 1]);
    card.state = (WORKSHOP_TASK_STATES.find(([pattern]) => pattern.test(latest)) || [null, 'open'])[1];
    const [kind, id] = card.work.split(':');
    card.title = card.node?.title || null;
    card.owner = wsSender(card.events[card.events.length - 1]);
  });
  (Array.isArray(plannedItems) ? plannedItems : []).forEach(row => {
    if (!row || typeof row.id !== 'string' || !row.id || typeof row.title !== 'string' || !row.title.trim() || cards.has(row.id)) return;
    const depends = Array.isArray(row.depends_on) ? row.depends_on.filter(item => typeof item === 'string' && item.trim()) : [];
    const waits = row.approving === true || /(?:needs?|waits? for).*(?:you|approval)|approval/i.test([row.state, row.status, row.done_when, row.lead].filter(Boolean).join(' '));
    const card = {kind:'task', work:row.id, node:null, events:[], state:'open', owner:null, title:row.title,
      status:String(row.state || 'PLANNED'), planned:true, done_when:String(row.done_when || ''),
      depends_on:depends, blocks:depends.length ? depends.join(' \u00b7 ') : '\u2014',
      approving:waits, lead:waits ? 'waits for you' : row.done_when ? 'Done when: ' + String(row.done_when) : 'Unowned planned proposal.'};
    cards.set(row.id, card); items.push(card);
  });
  return items;
};
const wsSeconds = value => {
  const number = typeof value === 'string' ? Date.parse(value) / 1000 : value;
  return !Number.isFinite(number) || number <= 0 ? null : number > 1e12 ? number / 1000 : number;
};
const wsClockText = (value, seconds) => {
  const at = wsSeconds(value); if (at === null) return '';
  const d = new Date(at * 1000), p = n => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes()) + (seconds ? ':' + p(d.getSeconds()) : '');
};

const wsParam = (node, pattern) => {
  const row = (node?.params || []).find(param => pattern.test(String(param.k || '')));
  return row && row.v != null && String(row.v).trim() ? String(row.v) : '';
};

const wsTasks = (items, nodes, wires, native, names) => {
  const cards = items.filter(item => item.kind === 'task');
  if (native?.work && !cards.some(card => card.work === native.work)) {
    const node = nodes.find(row => row.id === native.work) || null;
    const [kind, id] = String(native.work).split(':');
    const card = {kind:'task', work:native.work, node, events:[], state:'open', owner:null, nativeOnly:true,
      title:node?.title || null};
    cards.push(card); items.push(card);
  }
  const titles = new Map(nodes.map(node => [node.id, node.title || node.id]));
  return cards.map(card => {
    const events = card.events, latest = events[events.length - 1] || null;
    const nativeApproving = native?.work === card.work && native.state === 'awaiting_approval' && native.approved !== true;
    const approving = nativeApproving || card.approving === true;
    const running = native?.work === card.work && ['attaching', 'preparing', 'executing', 'recovering'].includes(native.state);
    const projectedState = String(card.node?.state || card.node?.status || '').toLowerCase();
    const state = nativeApproving ? 'block' : running ? 'run' :
      ['done','completed','complete'].includes(projectedState) ? 'done' :
      ['run','running','working','executing'].includes(projectedState) ? 'run' : card.state;
    const blocks = [...new Set(wires.filter(wire => wire.from?.[0] === card.work).map(wire => titles.get(wire.to?.[0])).filter(Boolean))];
    const categories = [...new Set(events.map(event => event.category).filter(Boolean))];
    const [, short] = String(card.work).split(':');
    // The design's task id slot ("T-01"): derived from the Work id, stable across pages; never a counter.
    return {id:'T-' + (short || card.work).slice(0, 6), work:card.work, graphRoot:card.work, title:card.title, owner:card.owner, state,
      node:card.node ? card.node.id : null, latest,
      nodeStatus:card.node?.status || card.node?.sub || card.status || '',
      status:card.status || '',
      progress:card.node?.progress, completed_at:card.node?.completed_at, done_at:card.node?.done_at, updated_at:card.node?.updated_at,
      result_summary:card.node?.result_summary,
      statusLine:card.node?.status_line,
      planned:card.planned === true, done_when:card.done_when || '', depends_on:Array.isArray(card.depends_on) ? card.depends_on : [],
      intent:wsParam(card.node, /^(description|intent|summary)$/i) || card.title,
      criteria:card.done_when || wsParam(card.node, /criteri/i) || '\u2014',
      blocks:card.blocks || (blocks.length ? blocks.join(' \u00b7 ') : '\u2014'),
      lead:latest ? wsText(latest) : native?.work === card.work ? 'Native Work status: ' + String(native.state || 'unknown').replaceAll('_', ' ') + '.' : card.lead || '',
      thread:events.slice(0, -1).map(event => ({root:event.root, from:wsSender(event),
        toRoots:Array.isArray(event.recipient_roots) ? event.recipient_roots : [],
        to:Array.isArray(event.recipient_roots) && event.recipient_roots.length ? event.recipient_roots.map(root => names.get(root) || root).join(', ') : 'Workshop',
        text:wsText(event)})),
      approving, nativeApproving, events,
      tools:{n:events.length, list:categories.length ? categories.join(' \u00b7 ') : '\u2014',
        t:latest ? (wsClockText(latest.created_at) || String(latest.state || '')) : String(native?.state || '')}};
  });
};

const PROPOSAL_MARKER = 'ArchHub work proposal v1\n';
const isWorkProposal = message => String(message?.body || '').startsWith(PROPOSAL_MARKER);
const wsProposalTask = (message, held = {}) => {
  const id = message.message_id || message.root;
  let payload = null;
  try { payload = JSON.parse(String(message.body).slice(PROPOSAL_MARKER.length)); } catch (_) { payload = null; }
  // The same shape the bind admits (studio-existing-workshop.js readWorkProposals): anything
  // else is shown as unreadable and offers no decision; nothing below reads an unchecked field.
  const text = value => typeof value === 'string' && value.length > 0;
  const shapedGrants = payload?.write_grants, shapedReviewers = payload?.requirements?.artifact_reviewers ?? [];
  const readable = !!payload && typeof payload === 'object' && !Array.isArray(payload) && text(payload.title) &&
    typeof payload.description === 'string' && ['general', 'artifact-publication'].includes(payload.purpose) &&
    Number.isSafeInteger(payload.priority) && !!payload.container && typeof payload.container === 'object' &&
    text(payload.container.container_id) && Array.isArray(shapedGrants) && shapedGrants.length > 0 &&
    !shapedGrants.some(grant => !grant || !text(grant.path) || !text(grant.scope) || !Array.isArray(grant.operations) ||
      !grant.operations.length || grant.operations.some(operation => !text(operation))) &&
    Array.isArray(shapedReviewers) && !shapedReviewers.some(reviewer => !text(reviewer));
  const grants = readable ? shapedGrants : [];
  const reviewers = readable ? shapedReviewers : [];
  const container = readable ?
    'CDE ' + payload.container.container_id + (text(payload.container.tier) ? ' · ' + payload.container.tier : '') : '';
  const work = typeof held.work_root === 'string' && held.work_root ? held.work_root : null;
  const lead = !readable ? 'This proposal cannot be read; it cannot be approved.'
    : work ? `Approved: ${payload.title}. Work ${work} is created; nothing runs until it is claimed.`
    : held.declined ? `Declined: ${payload.title}. Nothing exists or is granted.`
    : (held.error ? held.error + ' ' : '') +
      `Proposes this Work${payload.description ? ': ' + String(payload.description).replace(/\.?\s*$/, '.') : '.'} Reviewers: ${reviewers.length ? reviewers.join(', ') : 'none'}. Nothing exists or is granted until you approve.`;
  const gate = readable && text(payload.container.gate_kind) ?
    payload.container.gate_kind + (text(payload.container.gate_spec?.path) ? ' · ' + payload.container.gate_spec.path : '') : '';
  // Waiting on the founder reads NEEDS YOU (design T-01 "block"); declined is no longer pending.
  const preview = readable ? payload.preview : null;
  const elements = preview?.elements || payload?.elements;
  const labels = preview?.new_labels || payload?.new_labels;
  const changes = readable ? payload.changes || preview?.changes || preview?.rows ||
    (Array.isArray(elements) && Array.isArray(labels) ? elements.map((element,i)=>({
      id:element.id || element.root || String(element),label:element.label || element.name || String(element),
      now:element.now ?? element.before ?? '—',after:labels[i]?.label ?? labels[i]})).filter(row=>row.after!==undefined) : []) : [];
  return {work:'proposal:' + id, id:'PROPOSAL', proposal:id, title:readable ? payload.title : 'Unreadable proposal',
    changes, preview, summary:readable ? payload.description || payload.title : 'This proposal cannot be read.',
    state:work ? 'open' : held.declined || !readable ? 'queued' : 'block', owner:message.sender_root || null, lead, thread:[], latest:message, progress:0, artifact:null,
    graphRoot:work,
    intent:readable ? (payload.description || payload.title) : '—', criteria:gate || '—', blocks:'—',
    permissions:{write:grants.length ? grants.map(grant => grant.path + ' (' + (grant.operations || []).join(', ') + ')').join(' · ') : 'none requested',
      gate:work ? 'approved by you' : 'your approval before any Work exists'},
    tools:{n:grants.length, t:container,
      list:grants.length ? grants.map(grant => grant.path + ' · ' + grant.scope + ' · ' + (grant.operations || []).join(', ')).join(' · ') : 'no write grants'},
    decision:!readable || work || held.declined ? null : [
      {label:'Approve', action:'approve-proposal', message:id, disabled:!!held.pending},
      {label:'Decline', action:'decline-proposal', message:id, disabled:!!held.pending}]};
};

return {items:workshopTaskItems, tasks:wsTasks, proposal:wsProposalTask, isProposal:isWorkProposal, lifecycle:wsLifecycleEvent,
  eventState:message => (WORKSHOP_TASK_STATES.find(([pattern])=>pattern.test(wsText(message))) || [null,'planned'])[1],
  workIdentity:workshopWorkSelectionIdentity, admitted:admittedWorkshopWork, selected:selectedWorkshopWork,
  nodes:workshopProjectedNodes, wires:workshopProjectedWires, native:(state,root) => {
    const identity = workshopWorkSelectionIdentity(state,root), actor = identity ? JSON.parse(identity) : [];
    return identity && state.nativeWork?.root === root && state.nativeWork.scope === state.canvas?.root &&
      state.nativeWork.owner === actor[0] && state.nativeWork.view === actor[1] ? state.nativeWork : null;
  }};
})();

// The existing five-column board classifier is shared before either face loads.
window.ARCHHUB_WORKSHOP_BOARD = {
  groupTasks(tasks, agents) {
    const live = new Set();
    for (const agent of agents || []) {
      if (agent?.verified !== true || ['off','stale','unverified','unknown'].includes(agent.status)) continue;
      if (Array.isArray(agent.live_roots)) agent.live_roots.filter(Boolean).forEach(root => live.add(root));
      else if (!Array.isArray(agent.children) && agent.root) live.add(agent.root);
    }
    const grouped = {planned:[],wip:[],review:[],done:[],archived:[]};
    const blocked = task => ['block','blocked','paused'].includes(task.state);
    const approval = task => ['approving','needs-user','needs_user','awaiting_approval'].includes(task.state) || task.approving || (task.proposal && task.decision?.some(row => row.action === 'approve-proposal')) ||
      /waiting for (?:your|founder) approval/i.test(task.tools?.t || task.status || task.lead || '');
    for (const task of tasks || []) {
      const lane = ['archived','cancelled'].includes(task.state) ? 'archived' : task.state === 'done' ? 'done' :
        ['review','submitted'].includes(task.state) || approval(task) ? 'review' :
          (['run','running','executing'].includes(task.state) || blocked(task)) && live.has(task.owner) ? 'wip' : 'planned';
      grouped[lane].push({...task,boardLane:lane});
    }
    Object.values(grouped).forEach(rows => rows.sort((a,b) => (Number(!!approval(b))-Number(!!approval(a))) || (Number(blocked(b))-Number(blocked(a)))));
    return grouped;
  },
};

// WORKSHOP-72: one selector, one authority snapshot, two faces. No retained copy.
const workshopPresentationIdentity = (state = {}) => {
  const canvas = state.canvas || {}, topology = state.topology?.canvas || {};
  const current = canvas.authorization?.subject, projected = topology.authorization?.subject;
  const conflict = !!((current && projected && current !== projected) ||
    (canvas.graph_id && topology.application_root && canvas.graph_id !== topology.application_root));
  return {subject:conflict ? null : current || projected,
    graph:conflict ? null : canvas.graph_id || topology.application_root, conflict};
};
window.ARCHHUB_WORKSHOP_AGENT_MODEL = (agent = {}, state = {}) => {
  const identity = workshopPresentationIdentity(state), account = identity.subject;
  if (identity.conflict) return null;
  const presentation = state.workshopPresentation;
  const bound = !!presentation && typeof account === 'string' && account.length > 0 && presentation.subject === account && presentation.graph_id === identity.graph;
  const registry = (bound ? presentation.models : null) || state.models || state.model_registry;
  const models = Array.isArray(registry?.groups) ? registry.groups.flatMap(group => group.items || []) :
    Array.isArray(registry) ? registry : registry?.items || [];
  const id = agent.model?.route || agent.model?.id || agent.model || agent.model_id || agent.row?.model ||
    agent.config?.model || agent.params?.find(param => param.k === 'model')?.v;
  const freeOnly = agent.free_only === true || agent.free === true || /opencode|openrouter/.test(String(agent.runtime || agent.row?.runtime || ''));
  const row = models.find(model => [model.id,model.route,model.model].includes(id) &&
    (!freeOnly || model.free === true || model.is_free === true || /(?:^openrouter\/free$|:free$)/.test(String(model.route || model.id || ''))));
  return row?.name || row?.label || null;
};
window.ARCHHUB_WORKSHOP_MODEL = ({state = {}, descriptor = {}, selected, hostLine = '', modelChip = ''} = {}) => {
  const root = descriptor.root || '';
  const candidate = state.workshop;
  const held = candidate?.root === root && (candidate.graph_id === undefined || candidate.graph_id === state.canvas?.graph_id) &&
    (candidate.scope_root === undefined || candidate.scope_root === state.canvas?.root) ? candidate : null;
  const source = window.ARCHHUB_WORKSHOP_TASK_SOURCE;
  const operation = source.native(state,root);
  const projected = state.topology?.graph || state.graph || {nodes:[], wires:[]};
  const drawn = projected.nodes || state.topology?.canvas?.nodes || state.canvas?.nodes || [];
  const ids = new Set(drawn.map(row => row.id));
  const graph = {...projected, nodes:drawn.concat((state.topology?.canvas?.hidden_work || []).filter(row => row?.id && !ids.has(row.id)))};
  const assigned = held?.assignments || [];
  const groupRoot = descriptor.node_root || root;
  const groupNode = graph.nodes.find(row => row.id === groupRoot);
  const declaredMemberIds = new Set((groupNode?.members || []).map(member => typeof member === 'string' ? member : member?.id || member?.root).filter(Boolean));
  const memberIds = new Set(graph.nodes.filter(row => row.id !== groupRoot &&
    (row.group === groupRoot || (typeof row.group !== 'string' && declaredMemberIds.has(row.id)))).map(row => row.id));
  const graphMemberId = participant => {
    const candidates = [...new Set([participant.app_root, participant.account_root, participant.node_root,
      participant.agent_root, participant.root].filter(id => typeof id === 'string' && memberIds.has(id)))];
    return candidates.length === 1 ? candidates[0] : null;
  };
  const roster = (held?.participants || []).filter(row => row.root !== held?.self && row.is_agent !== false)
    .map(row => {
      const tones = [window.AH.accent, window.AH.cyan, window.AH.purple, window.AH.blue];
      const runtime = String(row.runtime || '').toLowerCase();
      const colours = window.AH.workshop.agentColour;
      const face = /claude/.test(runtime) ? {col:colours.claude,ini:'C'} : /codex/.test(runtime) ? {col:colours.codex,ini:'X'} :
        /opencode/.test(runtime) ? {col:colours.opencode,ini:'O'} : null;
      const col = face?.col || tones[[...String(row.root)].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % tones.length];
      const verified = (row.connected === true && (!Number.isFinite(row.expires_at) || row.expires_at > Date.now() / 1000)) || (row.is_agent === true && row.connection_status === 'connected' &&
        row.connection_basis === 'authenticated-request' && Number.isFinite(row.observed_at) && row.observed_at > 0 &&
        Number.isFinite(row.expires_at) && row.expires_at > row.observed_at && row.expires_at > Date.now() / 1000);
      const name = /claude/.test(runtime) ? 'Claude Code' : /codex/.test(runtime) ? 'Codex' :
        /opencode/.test(runtime) ? 'OpenCode' : /antigravity/.test(runtime) ? 'Antigravity' :
        /gemini/.test(runtime) ? 'Gemini' : runtime === 'baboom' ? 'BABOOM' :
        /^Runtime-/i.test(row.label || '') ? '' : row.label;
      return {...row, id:row.root, label:name, name, row, col, ink:window.AH.onFill, verified,
        modelLabel:window.ARCHHUB_WORKSHOP_AGENT_MODEL(row,state),
        liveState:row.state || row.connection_status || (verified ? 'connected' : 'Unavailable'),
        presence:verified ? 'online' : 'unknown', progress:Number.isFinite(row.progress) ? row.progress : null,
        graph_member_id:graphMemberId(row), graph_group_id:groupRoot,
        live_roots:verified ? [row.root] : [],
        ini:face?.ini || Array.from(String(row.label || '?'))[0].toUpperCase()};
    }).filter(row => row.verified && row.name && row.attached !== false && row.selectable !== false &&
      !['disconnected', 'stale', 'retired', 'off'].includes(row.connection_status));

  const proposalReceipts = Object.fromEntries(Object.values(held?.proposal_decisions || {}).map(row => [row.message_id,
    {work_root:row.work_root, declined:row.declined || (row.state === 'declined' ? row : null)}]));
  const names = new Map((held?.participants || []).map(row => [row.root, row.label]));
  const items = source.items(held?.messages || [], graph.nodes || [], held?.planned_items);
  const rows = source.tasks(items, graph.nodes || [], graph.wires || [], operation, names).concat(
    (held?.messages || []).filter(source.isProposal).map(message => source.proposal(message, proposalReceipts[message.message_id || message.root])));
  for (const row of rows) row.owner = assigned.find(assignment=>assignment.work===row.work)?.agent_session || row.owner;
  const workflows = held?.workflows || [];
  const workflowTasks = workflows.map(row => ({work:row.root, title:row.title, owner:row.proposed_by,
    workflow:row, state:row.state || row.status || (row.approval?.current === true ? 'planned' : 'review'),
    depends_on:row.depends_on || [],elapsed:row.elapsed,completed_at:row.completed_at,result_summary:row.result_summary,
    approving:row.approval?.current !== true}));
  const graphTasks = (state.topology?.canvas?.hidden_work || []).filter(node => node.engine === 'work' &&
    !rows.some(row=>row.work===node.id) && !workflowTasks.some(row=>row.work===node.id))
    .map(node=>({work:node.id,title:node.title || node.label,state:node.state || node.status || 'planned',
      owner:assigned.find(row=>row.work===node.id)?.agent_session,graphRoot:node.id,events:[],nodeStatus:node.status,
      completed_at:node.completed_at,done_at:node.done_at,updated_at:node.updated_at,result_summary:node.result_summary}));
  const byWork = new Map();
  for (const item of [...rows,...workflowTasks,...graphTasks].filter(row => row.work)) {
    const work = item.graphRoot || item.work, previous = byWork.get(work);
    byWork.set(work, previous && item.proposal ? {...item,...previous,work} : previous ?
      {...previous,...item,work,approving:previous.approving || item.approving,
        state:previous.nativeApproving ? 'block' : item.state} : {...item,work});
  }
  const unique = [...byWork.values()];
  const active = unique.find(row => row.work === selected) || unique.find(row => row.work === operation?.work) || unique[0] || null;
  const nativeWaiting = operation?.state === 'awaiting_approval' && operation.approved !== true && (!selected || selected === operation.work);
  const workflow = workflows.find(row => row.root === selected) || workflows.find(row => row.members?.includes(active?.work) ||
    row.nodes?.some(node => node.root === active?.work)) || (!selected ? workflows.find(row => row.approval?.current !== true) || workflows.at(-1) : null);
  const pendingProposal = row => row.proposal && row.decision?.some(choice => choice.action === 'approve-proposal');
  const proposal = unique.find(row => row.work === selected && pendingProposal(row)) ||
    (!selected ? unique.find(pendingProposal) : null);
  const approval = nativeWaiting ? {...operation, kind:'native', id:operation.work, work:operation.work,
    title:operation.title || active?.title || descriptor.label, input_digest:operation.input_digest, rows:operation.changes || operation.approval_rows || [],
    count:operation.result_count ?? operation.element_count ?? operation.row_count, unit:operation.change_unit || operation.output_label}
    : proposal ? {...proposal, kind:'proposal', id:proposal.work, work:proposal.work, title:proposal.title, proposal, rows:proposal.changes || []}
    : workflow && workflow.approval?.current !== true ? {...workflow, kind:'workflow', id:workflow.root,
      work:workflow.root, title:workflow.title, workflow, rows:workflow.changes || []} : null;
  if (approval) {
    approval.state = 'needs-user';
    const hostKey = approval.host_id || (typeof approval.host === 'string' ? approval.host : approval.host?.id);
    const host = (state.hosts || []).find(row => hostKey && [row.id,row.root,row.name].includes(hostKey));
    approval.host = typeof approval.host === 'object' ? approval.host?.name || approval.host?.label || host?.name : host?.name || approval.host;
    approval.document = approval.document_label || approval.document || host?.file;
    // `scope` on native/workflow authority is a Cell id, never a display label.
    approval.scope = approval.scope_label || approval.selection_label || approval.preview?.scope_label || '';
  }
  const grouped = window.ARCHHUB_WORKSHOP_BOARD.groupTasks(unique, roster);
  const lanes = new Map(Object.values(grouped).flat().map(row=>[row.work,row.boardLane]));
  for (const task of unique) task.boardLane = lanes.get(task.work);
  const sections = ['review', 'wip', 'planned', 'done', 'archived'].map((lane, index) => ({
    id:lane, label:['IN REVIEW', 'WIP', 'PLANNED', 'DONE', 'ARCHIVED'][index], rows:grouped[lane],
  }));
  const resolveAgent = id => roster.find(row => row.id === id || row.root === id);
  const exactAssignments = assigned.filter(row => !active || row.work === active.work).map(row => row.agent_session);
  const owners = [...new Set(exactAssignments)].map(resolveAgent).filter(Boolean);
  const reviewers = [...new Set((held?.reviews || []).filter(row => workflow && row.workflow === workflow.root)
    .map(row => row.judged_by).filter(Boolean))].map(resolveAgent).filter(Boolean);
  const taskAgents = [...new Map(owners.concat(reviewers).map(row => [row.id,row])).values()];
  if (approval && !approval.agent && !approval.agent_label) approval.agent_label = owners.map(row => row.name).filter(Boolean).join(', ');
  for (const member of roster) {
    const ownedTasks = unique.filter(task => task.owner === member.id || assigned.some(row => row.agent_session === member.id && row.work === task.work));
    const liveWorking = ['working','run','running','executing'].includes(member.state);
    const waits = ['needs-user','needs_user','awaiting_approval','waiting'].includes(member.state) || !liveWorking &&
      (ownedTasks.some(task => task.approving || pendingProposal(task) || ['review','submitted'].includes(task.state)) ||
        nativeWaiting && owners.some(agent => agent.id === member.id));
    const running = liveWorking || !waits && ownedTasks.some(task => ['run','running','executing'].includes(task.state));
    member.presence = waits ? 'needs-user' : running ? 'working' : member.verified ? 'online' : 'unknown';
    member.liveState = waits ? 'waiting' : running ? 'working' : String(member.liveState).replaceAll('_',' ').replaceAll('-',' ');
  }
  const ready = roster.filter(row => row.verified);
  const node = (graph.nodes || []).find(row => row.id === groupRoot);
  const status = approval ? 'Waits for you' : operation?.state === 'awaiting_approval' && operation.approved === true ? 'Approved' : operation?.state ? operation.state.replaceAll('_', ' ') :
    active?.status || active?.nodeStatus || active?.state || held?.state || 'Unavailable';
  const needsUser = task => task.approving || pendingProposal(task) || ['review','submitted','needs-user','needs_user','awaiting_approval'].includes(task.state);
  const waiting = unique.filter(task=>!['done','archived','cancelled'].includes(task.state) && needsUser(task)).length;
  const today = new Date().toDateString();
  const doneToday = task => {
    const value = task.completed_at ?? task.done_at ?? task.updated_at ?? task.latest?.created_at;
    if (value == null) return false;
    const time = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
    return !Number.isNaN(time.valueOf()) && time.toDateString() === today;
  };
  const viewSections = [
    {id:'needs-user',label:'NEEDS YOU',rows:unique.filter(task => !['done','archived','cancelled'].includes(task.state) && needsUser(task))},
    {id:'working',label:'WORKING',rows:unique.filter(task => !['done','archived','cancelled'].includes(task.state) && !needsUser(task))},
    {id:'done-today',label:'DONE TODAY',rows:grouped.done.filter(doneToday)},
  ];
  const stepSource = workflow?.nodes?.length ? workflow.nodes : (active?.events || []).filter(source.lifecycle)
    .map(event=>({root:event.root,title:event.step_title || active.title,state:source.eventState(event),duration:event.duration}));
  const steps = stepSource.map(step => {
    const live = graph.nodes.find(node => node.id === (step.root || step.id));
    return {...step,title:step.title || step.label || live?.label || 'Unavailable',
      state:live?.state || live?.status || step.state || step.status || 'Unavailable',
      duration:live?.duration ?? live?.elapsed ?? step.duration ?? step.elapsed,
      result:live?.result_word ?? live?.result ?? step.result_word ?? step.result ?? step.output_label};
  });
  const presentation = state.workshopPresentation;
  const identity = workshopPresentationIdentity(state), account = identity.subject;
  const presentationBound = !!presentation && typeof account === 'string' && account.length > 0 &&
    presentation.subject === account && presentation.graph_id === identity.graph;
  const layout = presentationBound && [1,2,4].includes(presentation.layout) ? presentation.layout : 1;
  return {id:root, root, title:active?.title || descriptor.label || 'Workshop', tasks:unique, sections,
    viewSections, layout, needs_user:!!approval, steps, models:presentationBound ? presentation.models : undefined,
    draft:state.workshopTaskDraft?.root === root && state.workshopTaskDraft.graph_id === identity.graph &&
      state.workshopTaskDraft.scope_root === state.canvas?.root && state.workshopTaskDraft.subject === account ? state.workshopTaskDraft : null,
    members:roster, ready, assigned:owners, reviewers, task_agents:taskAgents, messages:held?.messages || [], approval,
    plans:steps, workflow, native:operation, graph, node,
    status:{text:status, waiting, connected:held?.ok === true && !held.error, hostLine, modelChip},
    count:approval?.count ?? node?.result_count ?? node?.element_count ?? node?.row_count,
    output_label:operation?.output_label || approval?.unit || node?.output_label || '', transcript:held};
};

const HOSTS = [
  { id: 'revit',   name: 'Revit 2025',     port: 48884, status: 'connected',    color: '#0696D7', file: 'Tower-A_central.rvt'   },
  { id: 'blender', name: 'Blender 4.2',    port: 9876,  status: 'connected',    color: '#E87D0D', file: 'site_massing.blend'    },
  { id: 'autocad', name: 'AutoCAD 2025',   port: 48885, status: 'reconnecting', color: '#E51937', file: 'L01_floorplan.dwg'     },
  { id: '3dsmax',  name: '3ds Max 2025',   port: 48886, status: 'idle',         color: '#0696D7', file: '—'                     },
  { id: 'speckle', name: 'Speckle',        port: null,  status: 'connected',    color: '#0F62FE', file: 'tower-a/main'          },
];

const LLMS = [
  { id: 'claude-sonnet-4.5', name: 'Claude Sonnet 4.5', vendor: 'Anthropic', latency: 420, cost: '$3/M', selected: true },
  { id: 'gpt-5',             name: 'GPT-5',             vendor: 'OpenAI',    latency: 510, cost: '$5/M' },
  { id: 'gemini-2.5-pro',    name: 'Gemini 2.5 Pro',    vendor: 'Google',    latency: 380, cost: '$2/M' },
  { id: 'qwen3-32b',         name: 'qwen3:32b (local)', vendor: 'Ollama',    latency: 980, cost: 'free' },
];

const SKILLS = [
  { id: 'sk-1',  name: 'Sketch → Production',          host: ['blender','speckle','revit'], stages: 6, runs: 47, fav: true,  cat: 'Pipeline' },
  { id: 'sk-2',  name: 'Dimension walls in active view', host: ['revit'],                   stages: 1, runs: 312, fav: true, cat: 'Annotate' },
  { id: 'sk-3',  name: 'Construction Doc Sprint',       host: ['revit'],                    stages: 4, runs: 18, fav: false, cat: 'Pipeline' },
  { id: 'sk-4',  name: 'Place doors & windows from plan', host: ['revit'],                  stages: 2, runs: 89, fav: true,  cat: 'Modeling' },
  { id: 'sk-5',  name: 'Site massing → Speckle',         host: ['blender','speckle'],       stages: 2, runs: 34, fav: false, cat: 'Pipeline' },
  { id: 'sk-6',  name: 'Detail callouts on sheet',       host: ['revit'],                   stages: 1, runs: 22, fav: false, cat: 'Annotate' },
  { id: 'sk-7',  name: 'Generate elevation tags',        host: ['revit'],                   stages: 1, runs: 67, fav: false, cat: 'Annotate' },
  { id: 'sk-8',  name: '3ds Max camera matrix',          host: ['3dsmax'],                  stages: 1, runs: 8,  fav: false, cat: 'Render' },
  { id: 'sk-9',  name: 'AutoCAD layer cleanup',          host: ['autocad'],                 stages: 1, runs: 41, fav: false, cat: 'Cleanup' },
  { id: 'sk-10', name: 'Curtain wall from façade image', host: ['revit'],                   stages: 3, runs: 12, fav: true,  cat: 'Vision' },
];

const RECENT_CHATS = [
  { id: 'c1', title: 'Tower A — schedule wall types',     when: 'now',         host: 'revit',   pinned: true },
  { id: 'c2', title: 'Convert sketch to 6m gabled mass',  when: '12 min',      host: 'blender', pinned: false },
  { id: 'c3', title: 'Why are doors flipping?',           when: '1 h',         host: 'revit',   pinned: false },
  { id: 'c4', title: 'Site massing → Speckle stream',     when: 'yesterday',   host: 'speckle', pinned: false },
  { id: 'c5', title: 'Camera rig — 12 angles',            when: '2 d',         host: '3dsmax',  pinned: false },
  { id: 'c6', title: 'L01 layer cleanup pass',            when: '3 d',         host: 'autocad', pinned: false },
];

const TASKS = [
  { id: 't1', label: 'Auto-update connector DLL',  state: 'running',  pct: 64, host: 'revit'   },
  { id: 't2', label: 'Sync Skills repo (28 files)', state: 'running', pct: 92, host: null      },
  { id: 't3', label: 'Reconnect AutoCAD (retry 2)', state: 'healing', pct: 30, host: 'autocad' },
  { id: 't4', label: 'Index Speckle commits',      state: 'queued',   pct: 0,  host: 'speckle' },
];

const FINANCE = {
  monthSpend: 47.82,
  budget: 200,
  lastWeek: [3.2, 5.1, 4.8, 8.9, 6.1, 11.4, 8.3],
  byProvider: [
    { name: 'Anthropic', amt: 28.10, pct: 58 },
    { name: 'OpenAI',    amt: 12.40, pct: 26 },
    { name: 'Google',    amt:  4.30, pct: 9  },
    { name: 'OpenRouter',amt:  3.02, pct: 7  },
  ],
};

const CHAT_TRANSCRIPT = [
  { role: 'user', text: 'Dimension all walls in the active view, exterior only.' },
  { role: 'assistant', text: 'I\'ll match the saved Skill `Dimension walls in active view` and constrain to exterior. Running on Revit (Tower-A_central.rvt).', skill: 'Dimension walls in active view', tools: ['revit.get_active_view', 'revit.filter_walls', 'revit.create_dimension'] },
  { role: 'tool',  text: 'revit.filter_walls(category=Walls, exterior=true) → 47 walls' },
  { role: 'tool',  text: 'revit.create_dimension(refs=[...47]) → ✓ 47 dimensions placed in 4.2s' },
  { role: 'assistant', text: 'Done — 47 exterior walls dimensioned in the active view. Save this run as a Skill variant?' },
];

// Tiny inline SVG icons (no emoji, no fontawesome)
const Icon = ({ name, size=16, stroke=1.6, color='currentColor' }) => {
  const p = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color, strokeWidth: stroke, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'chat':     return <svg {...p}><path d="M21 12a8 8 0 1 1-3.5-6.6L21 4l-1 4.2A8 8 0 0 1 21 12Z"/></svg>;
    case 'skill':    return <svg {...p}><path d="M12 2 4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6l-8-4Z"/></svg>;
    case 'flow':     return <svg {...p}><circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/><path d="M8 7l3 9M16 7l-3 9"/></svg>;
    case 'gauge':    return <svg {...p}><path d="M3 12a9 9 0 0 1 18 0"/><path d="m12 12 4-3"/></svg>;
    case 'plug':     return <svg {...p}><path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 0 1-10 0V8ZM12 17v5"/></svg>;
    case 'gear':     return <svg {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>;
    case 'send':     return <svg {...p}><path d="m22 2-7 20-4-9-9-4 20-7Z"/></svg>;
    case 'star':     return <svg {...p}><path d="m12 2 3 7 7 .6-5.3 4.6L18 22l-6-3.6L6 22l1.3-7.8L2 9.6 9 9l3-7Z"/></svg>;
    case 'starF':    return <svg viewBox="0 0 24 24" width={size} height={size} fill={color}><path d="m12 2 3 7 7 .6-5.3 4.6L18 22l-6-3.6L6 22l1.3-7.8L2 9.6 9 9l3-7Z"/></svg>;
    case 'plus':     return <svg {...p}><path d="M12 5v14M5 12h14"/></svg>;
    case 'search':   return <svg {...p}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>;
    case 'play':     return <svg {...p}><path d="M6 4v16l14-8L6 4Z"/></svg>;
    case 'check':    return <svg {...p}><path d="m4 12 5 5L20 6"/></svg>;
    case 'alert':    return <svg {...p}><path d="M12 2 1 21h22L12 2Z"/><path d="M12 9v5M12 18v.01"/></svg>;
    case 'spark':    return <svg {...p}><path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"/></svg>;
    case 'home':     return <svg {...p}><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/></svg>;
    case 'history':  return <svg {...p}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>;
    case 'folder':   return <svg {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/></svg>;
    case 'sun':      return <svg {...p}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>;
    case 'moon':     return <svg {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>;
    case 'mic':      return <svg {...p}><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>;
    case 'image':    return <svg {...p}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5-9 9"/></svg>;
    case 'code':     return <svg {...p}><path d="m8 6-6 6 6 6M16 6l6 6-6 6"/></svg>;
    case 'wrench':   return <svg {...p}><path d="M14.7 6.3a4 4 0 0 1 5 5L17 14l-4-4 1.7-3.7Z"/><path d="m13 10-9 9 2 2 9-9"/></svg>;
    case 'dot':      return <svg viewBox="0 0 8 8" width={size} height={size}><circle cx="4" cy="4" r="3" fill={color}/></svg>;
    case 'x':        return <svg {...p}><path d="m6 6 12 12M18 6 6 18"/></svg>;
    case 'cmd':      return <svg {...p}><path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6Z"/></svg>;
    case 'arrowR':   return <svg {...p}><path d="M5 12h14M13 5l7 7-7 7"/></svg>;
    case 'menu':     return <svg {...p}><path d="M4 6h16M4 12h16M4 18h16"/></svg>;
    case 'paint':    return <svg {...p}><circle cx="12" cy="12" r="9"/><circle cx="7.5" cy="10.5" r="1.2" fill="currentColor"/><circle cx="11" cy="7" r="1.2" fill="currentColor"/><circle cx="15.5" cy="9" r="1.2" fill="currentColor"/><circle cx="16" cy="14" r="1.2" fill="currentColor"/></svg>;
    default:         return null;
  }
};

// Hook: typewriter for fake LLM streaming
function useTypewriter(text, speed=14, deps=[]) {
  const [shown, setShown] = React.useState('');
  React.useEffect(() => {
    setShown('');
    if (!text) return;
    let i = 0;
    const t = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) clearInterval(t);
    }, speed);
    return () => clearInterval(t);
  }, deps);
  return shown;
}

// Self-healing connector: cycles AutoCAD: reconnecting -> connected -> idle -> reconnecting...
// to demonstrate the "self-healing" feel without user action.
function useSelfHealingHosts() {
  const [hosts, setHosts] = React.useState(HOSTS);
  React.useEffect(() => {
    const id = setInterval(() => {
      setHosts(prev => prev.map(h => {
        if (h.id !== 'autocad') return h;
        const order = ['reconnecting', 'connected', 'connected', 'connected', 'idle'];
        const next = order[(order.indexOf(h.status) + 1) % order.length];
        return { ...h, status: next };
      }));
    }, 4200);
    return () => clearInterval(id);
  }, []);
  return [hosts, setHosts];
}

Object.assign(window, { HOSTS, LLMS, SKILLS, RECENT_CHATS, TASKS, FINANCE, CHAT_TRANSCRIPT, Icon, useTypewriter, useSelfHealingHosts });

// Read the full reviewed Brain arguments, never the server's shortened summary.
window.ARCHHUB_APPROVAL_REVIEW_ROWS = approval => {
  const rows = Array.isArray(approval.rows) ? approval.rows : Array.isArray(approval.changes) ? approval.changes : [];
  const operations = (approval.workflow?.nodes || (approval.kind === 'workflow' ? approval.nodes : []) || [])
    .filter(node => node.engine === 'brain.write').flatMap(node => {
      const raw = node.params?.arguments?.value ?? node.params?.ops?.value;
      if (raw === undefined) return [];
      try {
        const parsed = JSON.parse(raw), ops = node.params?.arguments ? parsed.ops : parsed;
        if (Array.isArray(ops)) return ops.map((op,index) => ({id:node.root + ':' + index,
          label:op.fragment?.id || node.title || node.root, now:'—', after:JSON.stringify(op)}));
      } catch (_) { /* Preserve unreadable source in the review instead of hiding it. */ }
      return [{id:node.root,label:node.title || node.root,now:'—',after:String(raw)}];
    });
  return [...rows,...operations];
};

// DSYS-076/077: every approval surface uses this one thin view; callers retain
// the existing producer's reviewed identity, decision route and receipt handling.
window.ARCHHUB_APPROVAL_CARD = function ApprovalCard({approval = {}, onApprove, onDecline,
    canApprove = true, canDecline = true, busy = false, surface = 'workshop', approveLabel = 'Approve', accent = true, variant}) {
  const A = window.AH;
  const [pending,setPending] = React.useState(false);
  const [error,setError] = React.useState('');
  const [expandedKey,setExpandedKey] = React.useState(null);
  const [sheetsOpen,setSheetsOpen] = React.useState(false);
  const [receiptLabel,setReceiptLabel] = React.useState('');
  const held = React.useRef({key:null,active:false,settled:false});
  const key = [approval.id || approval.root,approval.input_digest || approval.digest || approval.workflow?.digest || '',approval.state].join(':');
  if (held.current.key !== key) held.current = {key,active:false,settled:false};
  const needsUser = approval.state === 'needs-user';
  const decide = async (callback,available) => {
    if (busy || !available || !callback || held.current.active || held.current.settled) return;
    held.current.active = true; setPending(true); setError('');
    try { const result = await callback(); held.current.settled = true;
      setError(result?.warning || ''); setReceiptLabel(result?.warning ? 'Approval recorded' : 'Issued'); }
    catch (failure) { setError(failure?.message || 'Decision could not be confirmed.'); }
    finally { held.current.active = false; setPending(false); }
  };
  const button = primary => ({display:'inline-flex',alignItems:'center',gap:7,height:36,
    border:primary ? 0 : `1px solid ${A.line}`,borderRadius:8,
    padding:'0 16px',fontFamily:A.sans,fontSize:14,fontWeight:600,
    background:primary ? `linear-gradient(180deg, ${A.accentHi || A.accent} 0%, ${A.accent} 100%)` : A.workshop?.buttonBackground || A.bgPanel,
    boxShadow:primary ? `0 1px 0 rgba(255,255,255,.25) inset, 0 4px 14px ${A.accent}44` : '0 1px 0 rgba(255,255,255,.06) inset',
    color:primary ? '#fff' : A.ink,cursor:'pointer'});
  const rows = window.ARCHHUB_APPROVAL_REVIEW_ROWS(approval);
  const total = Number.isSafeInteger(approval.count) && approval.count >= rows.length ? approval.count : rows.length;
  const expanded = expandedKey === key;
  const crop = approval.plan_crop || approval.preview?.plan_crop;
  const cropUrl = typeof crop === 'string' ? crop : crop?.url || crop?.data_url;
  const cropSafe = typeof cropUrl === 'string' && /^(?:data:image\/(?:png|jpeg|webp);base64,|blob:|\/api\/)/.test(cropUrl);
  const affected = approval.affected_items || crop?.affected_items || [];
  const markers = affected.filter(item => Number.isFinite(item.x) && Number.isFinite(item.y));
  const markColour = needsUser ? A.warn : A.accent;
  const previewKind = approval.preview_kind || approval.preview?.kind;
  const subline = [surface === 'workshop' ? '' : approval.agent?.name || approval.agent_label || (typeof approval.agent === 'string' ? approval.agent : ''),
    approval.host,approval.document || approval.target,approval.scope,
    approval.unchanged_scope === true ? 'nothing else changes' : ''].filter(Boolean).join(' · ');
  if (variant === 'set-approve') return <section data-approval-component="shared" data-approval-variant="set-approve"
      data-approval-surface={surface} data-workshop-approval-card={approval.id || ''} data-approval-state={approval.state}
      style={{borderRadius:14,background:'linear-gradient(180deg, #202027 0%, #1a1a20 100%)',
        boxShadow:needsUser ? `0 0 0 1px ${A.warn}, 0 0 0 4px ${A.warn}22, 0 8px 28px rgba(0,0,0,.5)` : A.elev?.e1,
        padding:18,display:'grid',gap:14,minWidth:0}}>
    <header style={{display:'flex',alignItems:'center',gap:12}}>
      {approval.agent_label && <span style={{width:34,height:34,borderRadius:9,display:'grid',placeItems:'center',background:A.accent,color:'#fff',fontSize:15,fontWeight:700,flex:'none'}}>{Array.from(approval.agent_label)[0]}</span>}
      <div style={{flex:1,minWidth:0}}><div style={{fontSize:17,fontWeight:700}}>{approval.title}</div>
        <div style={{fontSize:13,color:A.inkSoft,marginTop:2}}>{approval.package?.sheets?.length || 0} sheets{subline ? ' · '+subline : ''}</div></div>
      <span style={{height:24,padding:'0 9px',borderRadius:999,background:`${A.warn}1f`,color:A.warn,fontSize:12,fontWeight:600,display:'inline-flex',alignItems:'center'}}>{held.current.settled ? receiptLabel : 'Needs your OK'}</span>
    </header>
    <window.ARCHHUB_PACKAGE_SHEETS sheets={approval.package?.sheets || []} compact/>
    <div style={{fontSize:13,color:A.inkSoft,overflowWrap:'anywhere'}}>Package → {approval.package?.destination || 'Destination unavailable'}</div>
    <div style={{display:'flex',gap:8}}><button type="button" data-workshop-primary="approve" title="Approve and issue · Ctrl+K" disabled={busy || pending || held.current.settled || !canApprove || !onApprove || !approval.package?.available}
      onClick={()=>decide(onApprove,canApprove)} style={button(true)}>{held.current.settled ? receiptLabel : pending ? 'Issuing…' : approveLabel}</button>
      <button type="button" data-approval-open-sheets="" title="Open sheets · Ctrl+K" aria-expanded={sheetsOpen} onClick={()=>setSheetsOpen(!sheetsOpen)} style={button(false)}>Open sheets</button></div>
    {sheetsOpen && <div data-watch-preview="" data-package-watcher=""><div role="tablist" aria-label="Package Watcher"><button type="button" role="tab" aria-selected="true" style={button(false)}>PDF sheets</button></div>
      <div role="tabpanel" aria-label="PDF sheets" style={{paddingTop:12}}><window.ARCHHUB_PACKAGE_SHEETS sheets={approval.package?.sheets || []}/></div></div>}
    {error && <div role="alert" style={{fontSize:13,color:A.err}}>{error}</div>}
  </section>;
  return <section tabIndex={-1} data-approval-component="shared" data-approval-surface={surface}
      data-workshop-approval-card={approval.id || approval.root || ''} data-workshop-approval-kind={approval.kind || previewKind || ''}
      data-approval-state={approval.state || 'unavailable'} style={{borderRadius:14,background:A.surf2 || A.bgPanel,
        boxShadow:needsUser ? A.glow?.warn : A.elev?.e1,overflow:'hidden',fontFamily:A.sans,color:A.ink}}>
    <header style={{display:'flex',alignItems:'center',gap:12,padding:'16px 18px'}}>
      {approval.host && <span data-approval-host="" style={{width:36,height:36,borderRadius:9,background:'linear-gradient(180deg,#3f7be0,#2b5fb8)',
        color:'#fff',display:'grid',placeItems:'center',fontWeight:800,fontSize:15}}>{Array.from(approval.host)[0]}</span>}
      <div style={{flex:1}}><div style={{fontSize:16,fontWeight:700}}>{approval.title || 'Unavailable'}</div>
        {subline && <div data-approval-meta="" style={{fontSize:13,color:A.inkSoft,marginTop:2}}>{subline}</div>}</div>
      {approval.writes_to_model === true && <span data-approval-writes-model="" style={{display:'inline-flex',alignItems:'center',gap:6,height:24,
        padding:'0 9px',borderRadius:999,background:`${markColour}1f`,color:markColour,fontSize:12,fontWeight:600}}>Writes to your model</span>}
    </header>
    <div data-approval-preview={previewKind || 'diff'} style={{display:'grid',gridTemplateColumns:surface === 'workshop' && (cropSafe || total > 0) ? '220px 1fr' : '1fr',gap:16,padding:'0 18px 16px'}}>
      {cropSafe ? <svg data-approval-plan="host-crop" width="220" height="100"
          viewBox={`0 0 ${crop?.width || 220} ${crop?.height || 100}`} style={{borderRadius:10,background:A.bg,border:`1px solid ${A.lineSoft}`}}>
        {cropSafe && <image href={cropUrl} width={crop?.width || 220} height={crop?.height || 100}/>}
        {markers.map((item,i) => <circle data-approval-affected={item.id || i} key={item.id || i}
          cx={item.x} cy={item.y} r={item.radius || 4.5} fill={markColour} stroke={A.bg} strokeWidth="1.5"/>)}
      </svg> : total > 0 && <div data-approval-plan="unavailable" style={{height:100,boxSizing:'border-box',borderRadius:10,
          background:A.bg,border:`1px solid ${A.lineSoft}`,display:'grid',alignContent:'center',justifyItems:'center',gap:8}}>
        <strong style={{fontSize:22,fontWeight:700}}>{total} {approval.unit || 'changes'}</strong>
        <span style={{fontSize:13,color:A.inkSoft}}>Spatial preview unavailable</span>
      </div>}
      {previewKind === 'post' ? <div data-approval-post="" style={{whiteSpace:'pre-wrap',fontSize:14}}>{approval.post?.text || approval.post_text || approval.preview?.text || 'Unavailable'}</div> :
        previewKind === 'email' ? <div data-approval-email="" style={{fontSize:14,whiteSpace:'pre-wrap'}}>
          {[approval.email?.to,approval.email?.subject,approval.email?.body].filter(Boolean).map((value,i) => <div key={i}>{value}</div>)}
          {(approval.email?.attachments || []).map((attachment,i) => <div data-approval-attachment="" key={attachment.id || i}>{attachment.name || attachment.filename}</div>)}
        </div> : previewKind === 'sign-in' ? <div data-approval-sign-in="" style={{fontSize:14}}>{approval.sign_in?.line || approval.preview?.line || 'Unavailable'}</div> :
        rows.length ? <div data-approval-diff="" style={{borderRadius:10,border:`1px solid ${A.lineSoft}`,overflow:'hidden'}}>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',padding:'6px 14px',fontSize:12,color:A.inkSoft,fontWeight:600,background:'#15151a'}}><span>{approval.item_label || 'Item'}</span><span>Now</span><span>After</span></div>
          {(expanded ? rows : rows.slice(0,3)).map((row,i) => <div data-workshop-change-row="" key={row.id || i} style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',padding:'7px 14px',borderTop:`1px solid ${A.lineSoft}`,fontSize:14,fontWeight:500}}>
            <span>{String(row.label ?? row.element ?? row.id ?? 'Unavailable')}</span><span style={{color:A.inkSoft}}>{String(row.now ?? row.before ?? '—')}</span><span style={{color:A.ok,fontWeight:600}}>{String(row.after ?? 'Unavailable')}</span></div>)}
          {rows.length > 3 && <button type="button" data-approval-more="" aria-expanded={expanded}
            onClick={() => setExpandedKey(expanded ? null : key)} style={{display:'block',width:'100%',textAlign:'left',padding:'7px 14px',
              background:'transparent',border:0,borderTop:`1px solid ${A.lineSoft}`,fontFamily:A.sans,fontSize:13,color:A.inkSoft,cursor:'pointer'}}>
            {expanded ? 'Show fewer' : `+ ${rows.length - 3} more${approval.unit ? ` ${approval.unit}` : ''}`}</button>}
        </div> : <div data-approval-summary="" style={{fontSize:14,lineHeight:'22px',whiteSpace:'pre-wrap'}}>{approval.summary || approval.description || approval.intent || approval.title || 'Unavailable'}</div>}
    </div>
    {/* Change detail is disclosed apart from the spatial preview: on every preview kind, a count above the supplied rows says so. */}
    {total > rows.length && <div data-approval-missing="" style={{padding:'0 18px 14px',fontSize:13,color:A.inkSoft}}>{total - rows.length} {total - rows.length === 1 ? 'change' : 'changes'} not supplied by the host</div>}
    <footer style={{display:'flex',alignItems:'center',gap:10,padding:'14px 18px',background:'#16161b',borderTop:`1px solid ${A.lineSoft}`}}>
      <button type="button" data-workshop-primary="approve" disabled={busy || pending || held.current.settled || !canApprove || !onApprove} title={!canApprove || !onApprove ? 'Unavailable' : undefined}
        onClick={() => decide(onApprove,canApprove)} style={button(accent)}>{approveLabel}</button>
      <button type="button" data-workshop-primary="decline" disabled={busy || pending || held.current.settled || !canDecline || !onDecline} title={!canDecline || !onDecline ? 'Unavailable' : undefined}
        onClick={() => decide(onDecline,canDecline)} style={button(false)}>Decline</button>
      <span style={{flex:1}}/>{approval.undo_available === true && <span data-approval-undo="" style={{fontSize:13,color:A.inkSoft}}>You can undo this</span>}
    </footer>
    {error && <div role="alert" style={{fontSize:13,padding:'0 18px 14px',color:A.err}}>{error}</div>}
  </section>;
};

// Package previews show only supplied sheet images and file identities; no invented drawing geometry.
window.ARCHHUB_PACKAGE_SHEETS = ({sheets = [],compact = false}) => {
  const A = window.AH;
  const safe = url => typeof url === 'string' && /^(?:data:image\/(?:png|jpeg|webp);base64,|blob:|\/api\/)/.test(url);
  return <div data-package-sheets="" style={{display:'flex',gap:10,alignItems:'center',flexWrap:compact ? 'nowrap' : 'wrap',overflow:compact ? 'hidden' : undefined}}>
    {(compact ? sheets.slice(0,6) : sheets).map((sheet,index)=><figure data-package-sheet={sheet.id || sheet.path} key={sheet.id || sheet.path || index} title={sheet.name}
      style={{margin:0,flex:'none',width:compact ? 86 : 160}}>
      {safe(sheet.thumbnail_url) ? <img alt={sheet.name || 'Package sheet'} src={sheet.thumbnail_url} style={{display:'block',width:'100%',height:compact ? 60 : 112,objectFit:'contain',borderRadius:5,background:'#f4f1ea'}}/>
        : <div data-sheet-preview-unavailable="" style={{height:compact ? 60 : 112,background:'#f4f1ea',borderRadius:5,color:'#68645d',fontSize:compact ? 10 : 12,display:'grid',placeItems:'center',padding:4,boxSizing:'border-box',textAlign:'center'}}>{sheet.name}<br/>Preview unavailable</div>}
      {!compact && <figcaption style={{fontSize:12,color:A.inkSoft,overflowWrap:'anywhere',marginTop:6}}>{sheet.name}</figcaption>}
    </figure>)}
    {compact && sheets.length > 6 && <span style={{fontSize:13,color:A.inkSoft}}>+{sheets.length - 6}</span>}
    {!sheets.length && <span style={{fontSize:13,color:A.inkSoft}}>Package sheets unavailable</span>}
  </div>;
};

// One application rail, shared by Home, Workshop and every graph canvas.
window.ARCHHUB_APP_RAIL = ({active = 'Home', waiting = 0, account = {}, workshop = false, compact = false, persistent = false, empty = false, onNavigate}) => {
  const W = window.AH;
  const initials = account.initials || String(account.name || account.email || '?').trim().split(/\s+/).map(word => Array.from(word)[0]).slice(0, 2).join('').toUpperCase();
  const item = (g, label) => <window.AH_DS.Btn key={label} type="button" role="link" aria-label={label}
    title={label === 'Home' ? 'All sessions' : label === 'Chats' ? 'Chats · Ctrl+K, search Chats' : label} aria-keyshortcuts={label === 'Settings' ? 'Control+,' : undefined}
    data-rail-panel={label} data-rail-home={label === 'Home' ? '' : undefined}
    aria-current={active === label ? 'true' : undefined} onClick={() => onNavigate?.(label)}
    style={{width:empty ? 56 : compact ? 44 : 64,height:empty || compact ? 52 : 58,padding:0,border:0,background:'transparent',fontFamily:W.sans,display:'grid',placeItems:'center',alignContent:'center',gap:4,position:'relative',color:active===label?W.ink:W.inkSoft,cursor:'pointer'}}>
    <span style={{width:36,height:30,borderRadius:8,display:'grid',placeItems:'center',fontSize:16,background:active===label?W.bgHover:'transparent',boxShadow:active===label?W.elev?.e1:'none'}}>{g}</span>
    <span style={{fontSize:compact ? 10 : 11,fontWeight:active===label?600:500}}>{label}</span>
    {label==='Workshop'&&waiting>0&&<b style={{position:'absolute',top:3,right:10,minWidth:18,height:18,borderRadius:9,background:W.warn,color:W.onFill,fontSize:11,fontWeight:700,display:'grid',placeItems:'center'}}>{waiting}</b>}
  </window.AH_DS.Btn>;
  return <window.AH_DS.Rail data-app-rail="" data-workshop72-rail={workshop ? '' : undefined} aria-label="Main navigation"
    style={{width:empty ? 56 : compact ? 44 : 64,boxSizing:'border-box',background:W.bg,borderRight:`1px solid ${W.lineSoft}`,display:'grid',gridTemplateRows:'auto 1fr auto',paddingTop:compact ? 6 : 12,justifyItems:'center',gridColumn:'1',gridRow:workshop && !persistent ? undefined : '1 / span 2'}}>
    <div style={{display:'grid',gap:compact?2:4}}>{(persistent ? [['⌂','Home'],['◌','Chats'],['◎','Workshop'],['⬡','Canvas'],['▦','Library'],['?','Docs']] : empty ? [['⌂','Home'],['◎','Workshop'],['▦','Library'],['?','Docs']] : compact ? [['◌','Chats'],['▦','Library'],['?','Docs'],['◫','Cockpit']] : workshop ? [['⌂','Home'],['◎','Workshop'],['⬡','Canvas'],['▦','Library'],['?','Docs']] : [['⌂','Home'],['◌','Chats'],['◎','Workshop'],['⬡','Canvas'],['▦','Library'],['?','Docs']]).map(([g,l])=>item(g,l))}</div><span/>
    <div style={{paddingBottom:10,display:'grid',gap:4,justifyItems:'center'}}>{item('⚙','Settings')}
      {!empty && <window.AH_DS.Btn type="button" data-rail-panel="Account" aria-current={active === 'Account' ? 'true' : undefined} data-workshop-account-avatar={workshop ? '' : undefined} aria-label="Account" title={account.email || 'Account'} onClick={()=>onNavigate?.('Account')}
        style={{width:compact?28:32,height:compact?28:32,padding:0,border:0,borderRadius:'50%',background:account.colour||account.color||account.avatar_color||W.userAv,color:W.onUserAv,display:'grid',placeItems:'center',fontFamily:W.sans,fontSize:12,fontWeight:700,cursor:'pointer'}}>{initials}</window.AH_DS.Btn>}
    </div></window.AH_DS.Rail>;
};
