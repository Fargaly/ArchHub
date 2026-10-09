// workshop-board.jsx — Workshop board and agent list surfaces.
(() => {
const W = window.AH;
const h = React.createElement;

const laneSpec = [
  ['backlog', 'Backlog', task => ['created', 'queued'].includes(task.state) && !task.owner && !task.agent],
  ['claimed', 'Claimed', task => ['open', 'claim', 'claimed'].includes(task.state) || (!!task.owner && !['approving', 'run', 'block', 'blocked', 'done', 'review'].includes(task.state))],
  ['running', 'Running', task => ['run', 'running', 'executing', 'review'].includes(task.state)],
  ['blocked', 'Blocked', task => ['approving', 'block', 'blocked', 'paused'].includes(task.state) || task.approving],
  ['done', 'Done', task => task.state === 'done'],
];
const stop = event => event && typeof event.stopPropagation === 'function' && event.stopPropagation();
const line = task => task.tools?.t || task.status || task.lead || '';
const approvalBlocked = task => task.state === 'approving' || /waiting for (?:your|founder) approval/i.test(line(task));
const agentName = task => task.agent || task.agent_name || task.owner_label || task.ownerName || (task.owner ? null : 'no agent');
const hostName = task => task.host || task.host_label || task.runtime || task.tools?.host || 'host unknown';
const mayDo = agent => agent.may || agent.permissions || agent.scope || '';
const presence = agent => agent.ago || agent.presence || (agent.verified ? 'verified recently' : 'not verified');
const activeAgentIds = agents => new Set((agents || []).filter(agent => agent && agent.status !== 'off').map(agent => agent.id || agent.root || agent.name).filter(Boolean));

const labelStyle = {fontFamily:W.mono, fontSize:14, letterSpacing:'0.12em', color:W.inkMuted};
const chipStyle = {fontFamily:W.mono, fontSize:13, letterSpacing:'0.02em', paddingTop:3, paddingBottom:3,
  paddingLeft:6, paddingRight:6, borderRadius:W.rad?.xs || 3, borderWidth:1, borderStyle:'solid', borderColor:W.line, color:W.inkSoft};
const buttonStyle = primary => ({paddingTop:3, paddingBottom:3, paddingLeft:9, paddingRight:9, borderRadius:W.rad?.sm || 5, cursor:'pointer',
  fontFamily:W.sans, fontSize:14, letterSpacing:0,
  background:primary ? W.accent : 'transparent', borderWidth:1, borderStyle:'solid', borderColor:primary ? W.accent : W.line,
  color:primary ? W.onFill : W.inkSoft});

const BoardCard = ({task, onSelect, onDecide}) => h('article', {
  'data-workshop-board-card':task.work,
  onClick:() => onSelect && onSelect(task.work),
  style:{background:W.bgPanel, borderWidth:1, borderStyle:'solid', borderColor:approvalBlocked(task) || task.state === 'block' ? W.err : W.line,
    borderRadius:8, padding:16, display:'flex', flexDirection:'column',
    gap:8, minWidth:0, cursor:onSelect ? 'pointer' : 'default'},
}, [
  h('div', {key:'head', style:{display:'flex', alignItems:'center', gap:W.sp?.sm || 8, minWidth:0}}, [
    h('strong', {key:'title', style:{fontSize:18, lineHeight:1.25, fontWeight:700, color:W.ink, overflowWrap:'anywhere'}}, task.title || task.work),
    h('span', {key:'agent', style:{...chipStyle, marginLeft:'auto'}}, agentName(task) || 'no agent'),
  ]),
  h('div', {key:'meta', style:{display:'flex', gap:8, flexWrap:'wrap', fontSize:16, color:W.inkSoft, lineHeight:1.45}}, [
    h('span', {key:'host', style:chipStyle}, hostName(task)),
    h('span', {key:'status'}, line(task)),
  ]),
  approvalBlocked(task)
    ? h('div', {key:'actions', style:{display:'flex', gap:W.sp?.sm || 8, flexWrap:'wrap'}},
      (task.decision || [{label:'Approve', action:'approve'}, {label:'Reject', action:'reject'}]).map((choice, index) =>
        h('button', {key:choice.label || choice.action, type:'button', style:buttonStyle(index === 0),
          onClick:event => { stop(event); onDecide && onDecide(task.work, choice); }}, choice.label || choice.action)))
    : null,
]);

const groupTasks = (tasks, agents) => {
  const live = activeAgentIds(agents);
  const grouped = Object.fromEntries(laneSpec.map(([id]) => [id, []]));
  for (const task of tasks || []) {
    const current = ['run', 'running', 'executing', 'review'].includes(task.state) && task.owner && !live.has(task.owner)
      ? {...task, state:'claimed'} : task;
    const spec = laneSpec.find(([, , admits]) => admits(current)) || laneSpec[0];
    grouped[spec[0]].push(task);
  }
  return grouped;
};

const WorkshopBoardView = ({tasks, agents, selected, onSelect, onDecide}) => {
  const grouped = groupTasks(tasks, agents);
  return h('section', {'aria-label':'Workshop board',
    style:{display:'grid', gridTemplateColumns:'repeat(5,minmax(210px,1fr))', gap:14,
      alignContent:'start', minWidth:'1050px', height:'100%'}},
    laneSpec.map(([id, label]) => {
      const all = grouped[id] || [];
      const shown = id === 'done' ? all.slice(0, 7) : all;
      return h('section', {key:id, 'data-workshop-lane':id,
        style:{display:'flex', flexDirection:'column', gap:14, minWidth:0, background:W.bgSoft, borderRadius:8,
          padding:12}}, [
        h('header', {key:'h', style:{display:'flex', alignItems:'center', gap:W.sp?.sm || 8,
          paddingBottom:W.sp?.sm || 8, borderBottomWidth:1, borderBottomStyle:'solid', borderBottomColor:W.lineSoft}}, [
          h('h3', {key:'title', style:{margin:0, fontFamily:W.mono, fontSize:16, lineHeight:1.3, fontWeight:500, color:W.inkMuted, letterSpacing:'0.12em', textTransform:'uppercase'}}, label),
          h('span', {key:'count', style:{...labelStyle, marginLeft:'auto'}}, String(all.length)),
        ]),
        ...shown.map(task => h(BoardCard, {key:task.work, task:{...task, selected:selected === task.work}, onSelect, onDecide})),
        id === 'done' && all.length > shown.length ? h('div', {key:'more', style:{fontSize:16, color:W.inkMuted, padding:'12px 16px'}}, `+${all.length - shown.length} more`) : null,
      ]);
    }));
};

const WorkshopAgentsView = ({agents}) => {
  const rows = agents || [];
  return h('section', {'aria-label':'Workshop agents list',
    style:{display:'flex', flexDirection:'column', gap:W.sp?.md || 12, minWidth:0}}, [
    ...rows.map(agent => h('article', {key:agent.id || agent.name,
      style:{background:W.bgPanel, borderWidth:1, borderStyle:'solid', borderColor:W.line, borderRadius:W.rad?.lg || 8,
        padding:20, display:'grid', gap:8}}, [
      h('div', {key:'name', style:{display:'flex', gap:W.sp?.sm || 8, flexWrap:'wrap', alignItems:'center'}}, [
        h('span', {key:'dot', style:{width:10, height:10, borderRadius:W.rad?.pill || 999, background:agent.status === 'off' ? W.inkMuted : W.ok}}),
        h('strong', {key:'n', style:{fontSize:18, fontWeight:700}}, agent.name || agent.id),
        h('span', {key:'kind', style:chipStyle}, agent.kind || (/^mcp-/.test(agent.runtime || agent.id || '') ? 'cloud' : 'local')),
      ]),
      h('div', {key:'doing', style:{fontFamily:W.mono, fontSize:16, lineHeight:1.35, color:W.inkSoft, overflowWrap:'anywhere'}},
        [presence(agent), agent.doing || agent.running || 'Nothing active', mayDo(agent) ? 'may: ' + mayDo(agent) : ''].filter(Boolean).join(' · ')),
    ])),
    h('article', {key:'baboom', style:{background:W.bgPanel, borderWidth:1, borderStyle:'solid', borderColor:W.line, borderRadius:W.rad?.lg || 8,
      padding:W.sp?.md || 12, display:'flex', gap:W.sp?.sm || 8, alignItems:'baseline'}}, [
      h('span', {key:'dot', style:{width:10, height:10, borderRadius:W.rad?.pill || 999, background:W.cyan}}),
      h('strong', {key:'n', style:{fontSize:18, fontWeight:700}}, 'BABOOM'),
      h('span', {key:'kind', style:chipStyle}, 'companion'),
      h('span', {key:'text', style:{fontFamily:W.mono, fontSize:16, color:W.inkSoft}}, 'listens: failed runs, stuck tasks, approvals · says at the next pause'),
    ]),
    h('article', {key:'add', style:{background:W.bgSoft, borderWidth:1, borderStyle:'solid', borderColor:W.line, borderRadius:W.rad?.lg || 8,
      padding:W.sp?.md || 12, display:'grid', gap:W.sp?.xs || 4}}, [
      h('strong', {key:'h', style:{fontSize:18, fontWeight:700}}, 'Add an agent'),
      h('div', {key:'t', style:{fontFamily:W.mono, fontSize:16, lineHeight:1.35, color:W.inkSoft}}, 'local: Connect Claude Code / Codex / Gemini CLI (existing registration) · cloud: share the MCP link with Claude.ai, Notion, Spark'),
    ]),
  ]);
};

const WorkshopProjectsView = ({projects, onOpen}) => h('section', {'aria-label':'Workshop projects list',
  style:{display:'flex', flexDirection:'column', gap:W.sp?.md || 12, minWidth:0}},
  (projects || []).map(project => h('article', {key:project.id, onClick:onOpen,
    style:{background:W.bgPanel, borderWidth:1, borderStyle:'solid', borderColor:W.line, borderRadius:W.rad?.lg || 8,
      padding:W.sp?.lg || 16, cursor:onOpen ? 'pointer' : 'default'}}, [
    h('div', {key:'head', style:{display:'flex', alignItems:'center', gap:W.sp?.sm || 8}}, [
      h('strong', {key:'name', style:{fontSize:14, fontWeight:600, color:W.ink}}, project.name),
      h('span', {key:'status', style:{...chipStyle, marginLeft:'auto', color:project.blocked ? W.warn : W.ok}}, project.status || 'quiet'),
    ]),
    h('div', {key:'bar', style:{height:4, borderRadius:W.rad?.pill || 999, background:W.bgHover, marginTop:W.sp?.md || 12, overflow:'hidden'}},
      h('i', {style:{display:'block', width:Math.max(0, Math.min(100, project.progress || 0)) + '%', height:'100%', background:project.blocked ? W.warn : W.ok}})),
    h('div', {key:'meta', style:{fontFamily:W.mono, fontSize:11.5, color:W.inkSoft, marginTop:W.sp?.sm || 8, overflowWrap:'anywhere'}},
      `${project.tasks || 0} tasks · ${project.done || 0} done · ${project.blocked || 0} blocked · ${project.hosts || 'no host'} · agents: ${project.agents || 'none'}${project.due ? ' · due ' + project.due : ''}`),
  ])));

const WorkshopApprovalsView = ({tasks, selected, onSelect, onDecide}) => h('section', {'aria-label':'Workshop approvals list',
  style:{display:'flex', flexDirection:'column', gap:W.sp?.md || 12, minWidth:0}},
  (tasks || []).length ? (tasks || []).map(task => h(BoardCard, {key:task.work, task:{...task, selected:selected === task.work}, onSelect, onDecide}))
    : [h('div', {key:'empty', role:'status', style:{fontSize:12.5, color:W.inkSoft}}, 'No work is waiting for founder approval.')]);

const WorkshopTaskPage = ({task, agent, onDecide}) => {
  if (!task) return h('div', {role:'status', style:{fontSize:12.5, color:W.inkSoft}}, 'No task selected.');
  const owner = task.owner && agent ? agent(task.owner) : null;
  const thread = Array.isArray(task.thread) ? task.thread : [];
  const stepRows = thread.length ? thread.slice(0, 3) : [{text:task.lead || line(task), from:task.owner, root:'current'}];
  return h('section', {'aria-label':'Workshop selected task',
    style:{display:'grid', gridTemplateColumns:'repeat(2,minmax(0,1fr))', gap:W.sp?.md || 12, minWidth:0}}, [
    h('article', {key:'task', style:{background:W.bgPanel, border:`1px solid ${W.line}`, borderRadius:W.rad?.lg || 8, padding:W.sp?.lg || 16}}, [
      h('h3', {key:'h', style:{...labelStyle, marginTop:0}}, 'TASK'),
      h('div', {key:'state', style:{fontSize:15, color:W.ink}}, `${(line(task) || task.state || 'open')} · ${owner ? owner.name : agentName(task) || 'no agent'}`),
      h('p', {key:'lead', style:{fontSize:13, lineHeight:1.6, color:W.inkSoft}}, task.lead || task.intent || task.title),
    ]),
    h('article', {key:'linked', style:{background:W.bgPanel, border:`1px solid ${W.line}`, borderRadius:W.rad?.lg || 8, padding:W.sp?.lg || 16}}, [
      h('h3', {key:'h', style:{...labelStyle, marginTop:0}}, 'LINKED'),
      h('div', {key:'links', style:{fontSize:13, lineHeight:1.7, color:W.inkSoft}}, [
        h('div', {key:'w'}, `Work: ${task.work}`),
        h('div', {key:'h'}, `Host: ${hostName(task)}`),
        task.tools?.list ? h('div', {key:'t'}, `Tools: ${task.tools.list}`) : null,
      ]),
    ]),
    h('article', {key:'steps', style:{gridColumn:'1 / -1', background:W.bgPanel, border:`1px solid ${W.line}`, borderRadius:W.rad?.lg || 8, padding:W.sp?.lg || 16}}, [
      h('h3', {key:'h', style:{...labelStyle, marginTop:0}}, 'STEPS'),
      ...stepRows.map((row, index) => h('div', {key:row.root || index, style:{display:'grid', gridTemplateColumns:'165px 1fr auto', gap:W.sp?.md || 12,
        alignItems:'center', border:`1px solid ${W.lineSoft}`, borderRadius:W.rad?.md || 6, padding:W.sp?.sm || 8, marginTop:W.sp?.sm || 8}}, [
        h('span', {key:'state', style:{...chipStyle, color:index === 0 ? W.ok : approvalBlocked(task) ? W.warn : W.inkMuted}}, index === 0 ? 'done' : approvalBlocked(task) ? 'waiting' : 'next'),
        h('span', {key:'text', style:{fontSize:13, color:W.ink}}, row.text || task.title),
        approvalBlocked(task) && index === 1 ? h('span', {key:'actions', style:{fontSize:12, color:W.inkSoft}}, 'Approve · Reject') : h('span', {key:'blank'}, ''),
      ])),
    ]),
    h('article', {key:'thread', style:{gridColumn:'1 / -1', background:W.bgPanel, border:`1px solid ${W.line}`, borderRadius:W.rad?.lg || 8, padding:W.sp?.lg || 16}}, [
      h('h3', {key:'h', style:{...labelStyle, marginTop:0}}, 'THREAD'),
      ...(thread.length ? thread : [{text:task.lead || task.title, from:task.owner, root:'summary'}]).slice(0, 4).map((row, index) =>
        h('p', {key:row.root || index, style:{fontSize:12.5, lineHeight:1.6, color:W.inkSoft}}, row.text || row.body || task.title)),
      approvalBlocked(task) && task.decision ? h('div', {key:'actions', style:{display:'flex', gap:W.sp?.sm || 8}}, task.decision.map((choice, index) =>
        h('button', {key:choice.label || choice.action, type:'button', style:buttonStyle(index === 0),
          onClick:() => onDecide && onDecide(task.work, choice)}, choice.label || choice.action))) : null,
    ]),
  ]);
};

window.WorkshopBoardView = WorkshopBoardView;
window.WorkshopAgentsView = WorkshopAgentsView;
window.WorkshopProjectsView = WorkshopProjectsView;
window.WorkshopApprovalsView = WorkshopApprovalsView;
window.WorkshopTaskPage = WorkshopTaskPage;
window.WorkshopBoard = {groupTasks};
})();
