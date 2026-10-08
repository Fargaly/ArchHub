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
const mayDo = agent => agent.may || agent.permissions || agent.scope || 'not projected';
const presence = agent => agent.ago || agent.presence || (agent.verified ? 'verified recently' : 'not verified');

const labelStyle = {fontFamily:W.mono, fontSize:9, letterSpacing:'0.18em', color:W.inkMuted};
const chipStyle = {fontFamily:W.mono, fontSize:9, letterSpacing:'0.08em', paddingTop:2, paddingBottom:2,
  paddingLeft:6, paddingRight:6, borderRadius:W.rad?.xs || 3, borderWidth:1, borderStyle:'solid', borderColor:W.line, color:W.inkSoft};
const buttonStyle = primary => ({paddingTop:3, paddingBottom:3, paddingLeft:9, paddingRight:9, borderRadius:W.rad?.sm || 5, cursor:'pointer',
  fontFamily:W.mono, fontSize:10.5, letterSpacing:'0.04em',
  background:primary ? W.accent : 'transparent', borderWidth:1, borderStyle:'solid', borderColor:primary ? W.accent : W.line,
  color:primary ? W.onFill : W.inkSoft});

const BoardCard = ({task, onSelect, onDecide}) => h('article', {
  'data-workshop-board-card':task.work,
  onClick:() => onSelect && onSelect(task.work),
  style:{background:W.bgPanel, borderWidth:1, borderStyle:'solid', borderColor:approvalBlocked(task) || task.state === 'block' ? W.err : W.line,
    borderRadius:W.rad?.lg || 8, padding:W.sp?.md || 12, display:'flex', flexDirection:'column',
    gap:W.sp?.sm || 8, minWidth:0, cursor:onSelect ? 'pointer' : 'default'},
}, [
  h('div', {key:'head', style:{display:'flex', alignItems:'center', gap:W.sp?.sm || 8, minWidth:0}}, [
    h('strong', {key:'title', style:{fontSize:13, fontWeight:500, color:W.ink, overflowWrap:'anywhere'}}, task.title || task.work),
    h('span', {key:'agent', style:{...chipStyle, marginLeft:'auto'}}, agentName(task) || 'no agent'),
  ]),
  h('div', {key:'meta', style:{display:'flex', gap:W.sp?.sm || 8, flexWrap:'wrap', fontSize:11.5, color:W.inkSoft}}, [
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

const groupTasks = tasks => {
  const grouped = Object.fromEntries(laneSpec.map(([id]) => [id, []]));
  for (const task of tasks || []) {
    const spec = laneSpec.find(([, , admits]) => admits(task)) || laneSpec[0];
    grouped[spec[0]].push(task);
  }
  return grouped;
};

const WorkshopBoardView = ({tasks, selected, onSelect, onDecide}) => {
  const grouped = groupTasks(tasks);
  return h('section', {'aria-label':'Workshop board',
    style:{display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(14rem,1fr))', gap:W.sp?.md || 12,
      alignContent:'start', minWidth:0}},
    laneSpec.map(([id, label]) => {
      const all = grouped[id] || [];
      const shown = id === 'done' ? all.slice(0, 7) : all;
      return h('section', {key:id, 'data-workshop-lane':id,
        style:{display:'flex', flexDirection:'column', gap:W.sp?.sm || 8, minWidth:0}}, [
        h('header', {key:'h', style:{display:'flex', alignItems:'center', gap:W.sp?.sm || 8,
          paddingBottom:W.sp?.sm || 8, borderBottomWidth:1, borderBottomStyle:'solid', borderBottomColor:W.lineSoft}}, [
          h('h3', {key:'title', style:{margin:0, fontSize:13, lineHeight:1.3, fontWeight:500, color:W.ink}}, label),
          h('span', {key:'count', style:{...labelStyle, marginLeft:'auto'}}, String(all.length)),
        ]),
        ...shown.map(task => h(BoardCard, {key:task.work, task:{...task, selected:selected === task.work}, onSelect, onDecide})),
        id === 'done' && all.length > shown.length ? h('div', {key:'more', style:{fontSize:11.5, color:W.inkMuted}}, `+${all.length - shown.length} more`) : null,
      ]);
    }));
};

const WorkshopAgentsView = ({agents, details}) => {
  const [open, setOpen] = React.useState(!!details);
  const rows = agents || [];
  return h('section', {'aria-label':'Workshop agents list',
    style:{display:'flex', flexDirection:'column', gap:W.sp?.sm || 8, minWidth:0}}, [
    h('div', {key:'tools', style:{display:'flex', justifyContent:'flex-end'}},
      h('button', {type:'button', 'aria-label':'Details', 'aria-pressed':open, style:buttonStyle(false), onClick:() => setOpen(!open)}, 'Details')),
    ...rows.map(agent => h('article', {key:agent.id || agent.name,
      style:{background:W.bgPanel, borderWidth:1, borderStyle:'solid', borderColor:W.line, borderRadius:W.rad?.lg || 8,
        padding:W.sp?.md || 12, display:'grid', gap:W.sp?.xs || 4}}, [
      h('div', {key:'name', style:{display:'flex', gap:W.sp?.sm || 8, flexWrap:'wrap', alignItems:'center'}}, [
        h('strong', {key:'n', style:{fontSize:13, fontWeight:500}}, agent.name || agent.id),
        h('span', {key:'kind', style:chipStyle}, agent.kind || (/^mcp-/.test(agent.runtime || agent.id || '') ? 'cloud' : 'local')),
        h('span', {key:'presence', style:{fontSize:11.5, color:W.inkSoft}}, presence(agent)),
      ]),
      h('div', {key:'doing', style:{fontSize:12, color:W.inkSoft, overflowWrap:'anywhere'}}, agent.doing || agent.running || 'Nothing active'),
      h('div', {key:'may', style:{fontSize:12, color:W.inkSoft, overflowWrap:'anywhere'}}, mayDo(agent)),
      open ? h('div', {key:'detail', style:{fontFamily:W.mono, fontSize:10, color:W.inkMuted, overflowWrap:'anywhere'}},
        [agent.id, agent.host, agent.runtime].filter(Boolean).join(' · ')) : null,
    ])),
  ]);
};

window.WorkshopBoardView = WorkshopBoardView;
window.WorkshopAgentsView = WorkshopAgentsView;
window.WorkshopBoard = {groupTasks};
})();
