// DSYS-077 / ds_workshop3.jsx. Original two-column room, Task, Tool,
// message hierarchy and one Approve card. Board stages follow Book chapter 4.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
    A,
    D,
    useData,
    useApp,
    Btn,
    Card,
    Chip,
    Av,
    Composer,
    ApprovalCard,
    Empty
  } = window.UI;
  // The task list groups by what it asks of you; a drop sets the group's stage. Archived shows only on its filter.
  const today = t => !t.updated_at || new Date(t.updated_at).toDateString() === new Date().toDateString();
  const groupsFor = (archived, waiting) => [
    ['NEEDS YOU', t => t.status === 'IN REVIEW' || waiting.has(t.id), 'IN REVIEW'],
    ['WORKING', t => (t.status === 'WIP' || t.status === 'PLANNED') && !waiting.has(t.id), 'WIP'],
    ['DONE TODAY', t => t.status === 'DONE' && today(t), 'DONE'],
    ...(archived ? [['ARCHIVED', t => t.status === 'ARCHIVED', 'ARCHIVED']] : [])];
  const color = s => s === 'IN REVIEW' ? A.warn : s === 'DONE' ? A.ok : s === 'STOPPED' ? A.err : s === 'WIP' ? A.accent : A.inkSoft;
  function Task({
    task,
    on,
    select
  }) {
    const u = useApp();
    const steps = task.steps || [],
      completed = steps.filter(step => /^(done|complete|completed)$/i.test(step.status)).length;
    return <button className="listbutton" aria-selected={on} onClick={() => executeAction("ui.select", select)} onKeyDown={e => {
      if (e.code === 'Space') {
        e.preventDefault();
        select();
        executeAction("ui.show", u, 'Task details', {
          id: task.id
        });
      }
    }} draggable onDragStart={e => e.dataTransfer.setData('task', task.id)} style={{
      display: 'grid',
      gridTemplateColumns: '32px 1fr auto',
      gap: 12,
      alignItems: 'center',
      padding: '10px 12px'
    }}><Av id={task.owner || 'Unassigned'} size={30} /><div style={{
        minWidth: 0,
        display: 'grid',
        gap: 3
      }}><div style={{
          fontSize: 14,
          fontWeight: 600,
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }}>{task.title}</div><div style={{
          fontSize: 12.5,
          color: color(task.status)
        }}>{task.status === 'IN REVIEW' ? 'Waits for your OK' : task.status}</div>{task.activity && <div data-agent-activity role="status" style={{fontSize:11, overflowWrap:'anywhere'}}>
          {task.activity.sessions.map(row => <div key={row.provider + ':' + row.session} title={row.session}>
            {row.provider} · {row.tool} · {row.associated === false ? 'Current file unknown' + (row.file ? ' (last observed: ' + row.file + ')' : '') : row.file} · {row.state === 'turn_ended' ? 'Turn ended' : row.state === 'tool_ended' ? 'Tool ended' : row.state === 'unassociated' ? 'Activity unassociated' : 'Working'}
            {row.association_conflict && <span> · File and session association disagree</span>}
          </div>)}
          {task.activity.ownership === 'unknown' && <span>Activity unknown · no owned files</span>}
          {task.activity.touched_after_install && <strong data-touched-after-install style={{color:A.warn}}>Touched after install</strong>}
          {task.activity.stale && <span> · Re-verify row status</span>}
          {(task.activity.limited || task.activity.unavailable) && <span> · Observation incomplete</span>}
        </div>}{task.status === 'WIP' && steps.length > 0 && <span role="progressbar" aria-label={task.title + ' steps'} aria-valuemin={0} aria-valuenow={completed} aria-valuemax={steps.length} style={{
          height: 3,
          background: '#2a2a31',
          borderRadius: 2
        }}><i style={{
            display: 'block',
            width: `${completed / steps.length * 100}%`,
            height: '100%',
            background: A.accent
          }} /></span>}</div>{D.dot(color(task.status))}</button>;
  }
  function Messages({
    task
  }) {
    return <div className="grid" style={{
      gap: 18
    }}>{task.messages.map(m => <div key={m.id} style={{
        display: 'grid',
        gridTemplateColumns: Boolean(m.sender_key) && m.sender_key === m.viewer_key ? '1fr' : '32px 1fr',
        gap: 14
      }}>{(!m.sender_key || m.sender_key !== m.viewer_key) && <Av id={m.provider || window.ArchHubAPI.getSnapshot().providers.find(p => p.name === m.who)?.id || 'claude'} size={32} />}<div style={{
          display: 'grid',
          gap: 8,
          ...(Boolean(m.sender_key) && m.sender_key === m.viewer_key ? {
            justifySelf: 'end',
            maxWidth: 560,
            padding: '12px 16px',
            borderRadius: '14px 14px 4px 14px',
            background: '#24242b'
          } : {})
        }}>{(!m.sender_key || m.sender_key !== m.viewer_key) && <div className="flex"><b style={{
              fontSize: 15
            }}>{m.who}</b><span className="muted" style={{
              fontSize: 12
            }}>{m.model || 'Model not reported'}</span></div>}<p style={{
            fontSize: 15,
            lineHeight: '24px',
            whiteSpace: 'pre-wrap'
          }}>{m.text}</p>{m.reply_to && <span className="muted" style={{fontSize:12}}>↳ reply</span>}{(m.live||[]).length>0 && <div className="flex" data-live-delivery style={{flexWrap:'wrap',gap:6}}>{m.live.map((d,i)=><Chip key={i} c={d.state==='delivered'?A.accent:A.warn}>{d.state==='delivered'?'✓':'✗'} {d.agent} · {d.state==='delivered'?new Date(d.at).toLocaleTimeString()+' · '+d.ms+' ms':d.reason}</Chip>)}</div>}{['pending', 'delivered', 'answered'].includes(m.state) && <span role="status" data-delivery-state={m.state} className="muted">{m.state === 'answered' ? 'Answered' : m.state === 'delivered' ? 'Delivered' : 'Pending'}{m.delivery?.some(row => row.escalated) ? ' · Coordinator notified' : ''}</span>}<window.UI.TurnUsage message={m} /><window.UI.AnswerWidget message={m} />{(!m.sender_key || m.sender_key !== m.viewer_key) && <window.UI.AnswerSources message={m} />}{m.rule && <Chip c={A.purple}>Your rule: {m.rule}</Chip>}</div></div>)}</div>;
  }
  function Win() {
    const s = useData(),
      u = useApp();
    const [showArchived, setShowArchived] = React.useState(false), [query, setQuery] = React.useState('');
    const roomScope = JSON.stringify([s.graph.id, s.profile.email, s.profile.signedIn, s.workshopMessagesScope]);
    const currentScope = React.useRef(roomScope);
    currentScope.current = roomScope;
    const [older, setOlder] = React.useState({scope: roomScope, messages: [], before: null, more: true});
    const previous = older.scope === roomScope ? older : {messages: [], before: null, more: true};
    const task = s.tasks.find(t => t.id === u.task) || s.tasks[0];
    const roomMessages = [...new Map([...previous.messages, ...(s.workshopMessages || [])].map(message => [message.id, message])).values()]
      .filter(message => !task?.messages.some(item => item.id === message.id));
    const list = s.tasks.filter(t => !query || `${t.title} ${t.status}`.toLowerCase().includes(query.toLowerCase()));
    return <div data-screen="workshop" style={{
      display: 'grid',
      gridTemplateColumns: '340px minmax(0,1fr)',
      minHeight: 0
    }}>
  <aside className="pane" style={{
        display: 'flex',
        flexDirection: 'column'
      }}><div className="spread" style={{
          height: 64,
          padding: '0 16px 0 22px',
          flex: 'none'
        }}><h1 style={{
            fontSize: 20
          }}>Workshop</h1><Btn sm onClick={() => executeAction("ui.show", u, 'New task')}>New task</Btn></div><input aria-label="Search tasks" placeholder="⌕ Search tasks" value={query} onChange={e => setQuery(e.target.value)} style={{
          margin: '0 16px 10px'
        }} />
   <div className="scroll" style={{
          flex: 1
        }}>{groupsFor(showArchived, new Set(s.approvals.filter(c => c.status === 'pending').map(c => c.taskId))).map(([name, member, stage]) => <div key={name} onDragOver={e => e.preventDefault()} onDrop={e => {
            e.preventDefault();
            const id = e.dataTransfer.getData('task');
            if (id) executeAction("setTaskStatus", u, id, stage);
          }}><div className="spread label" style={{
              padding: '16px 22px 6px'
            }}><span>{name}</span><span>{list.filter(member).length}</span></div><div style={{
              padding: '0 10px'
            }}>{list.filter(member).map(t => <Task key={t.id} task={t} on={task?.id === t.id} select={() => executeAction("ui.setTask", u, t.id)} />)}</div></div>)}<label className="flex muted" style={{padding: '12px 22px'}}><input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />Show archived</label></div>
   <Card style={{
          margin: 12,
          padding: 14,
          display: 'grid',
          gap: 10,
          flex: 'none'
        }}><p role="status">{s.agentSummary||'Checking running agents…'}</p>{(s.agents||[]).map(p => <button key={p.id} draggable title={'Drag ' + p.name + ' to Canvas'} onDragStart={e => e.dataTransfer.setData('node', 'Agent:' + p.runtime)} className="button-reset spread" onClick={() => executeAction("ui.show", u, 'Agent', {
            id: p.id
          })}><span className="flex"><Av id={p.id} size={22} /><b style={{
                fontSize: 12
              }}>{p.name}</b>{p.session_count > 0 && <span className="mono muted" aria-label={p.session_count + ' sessions'}>{p.session_count}</span>}</span><span className="muted" style={{
              fontSize: 11
            }}>{p.presence === 'working' ? 'Working · ' + p.task : p.presence === 'unknown' ? (p.status_text || 'Status unknown') : 'Idle'}</span></button>)}<Btn sm ghost onClick={() => executeAction("ui.go", u, 'colleagues')}>Team &amp; meetings</Btn></Card>
  </aside>
  <main style={{
        display: 'grid',
        gridTemplateRows: '72px minmax(0,1fr) auto',
        minHeight: 0,
        background: 'radial-gradient(1200px 500px at 50% -10%,#1a1a22 0%,#0c0c0f 60%)'
      }}>
   <header className="spread" style={{
          padding: '0 30px',
          borderBottom: '1px solid ' + A.lineSoft
        }}><div><h1 style={{
              fontSize: 22
            }}>{task?.title || (roomMessages.length ? 'Workshop room' : 'What should the agents do?')}</h1><p className="muted" style={{
              fontSize: 12
            }}>One room · {s.graph.name}{(s.liveAgents||[]).length>0 && <span data-live-agents> · Live: {s.liveAgents.map(a=>'@'+a.handle+(a.status&&a.status!=='unknown'?' ('+a.status+')':'')).join(' ')} · @everyone</span>}</p></div><div className="flex">{task && <Chip c={color(task.status)}>{task.status}</Chip>}<Btn sm onClick={async () => {
              if(!task){executeAction("ui.go",u,"canvas");return;}
              const opened=await executeAction("openTaskGraph",u,task.id);
              if(opened){executeAction("ui.setSelectedNodeId",u,task.id);executeAction("ui.go",u,"canvas");}
            }}>Open on canvas</Btn><Btn sm ghost onClick={() => executeAction("ui.show", u, 'Workshop board')}>Board</Btn><Btn sm ghost onClick={() => executeAction("ui.show", u, 'Founder inbox')}>Inbox</Btn></div></header>
   <div className="scroll" style={{
          padding: '22px 30px'
        }}><div style={{
            maxWidth: 780,
            margin: '0 auto',
            display: 'grid',
            gap: 22
          }}>{(previous.before ? previous.more : s.workshopMessagesMore) && <Btn sm ghost onClick={async () => {
              const page = await executeAction("listWorkshopMessages", u, previous.before || s.workshopMessagesBefore);
              if (currentScope.current === roomScope && Array.isArray(page?.messages)) setOlder({scope: roomScope, messages: [...page.messages, ...previous.messages], before: page.next_before, more: page.more});
            }}>Older messages</Btn>}{roomMessages.length > 0 && <Messages task={{messages: roomMessages}} />}{task ? <><button className="listbutton spread" onClick={() => executeAction("ui.show", u, 'Task details', {
                id: task.id
              })}><span>Owner: {task.humanOwner || s.providers.find(p => p.id === task.owner)?.name || task.owner || 'Unassigned'}</span><span className="muted">Steps &amp; checkpoints →</span></button><Messages task={task} />{task.approvalId && <div style={{
                marginLeft: 46
              }}><ApprovalCard id={task.approvalId} /></div>}{task.status === 'STOPPED' && <Btn onClick={() => executeAction("reassignTask", u, task.id)}>Continue with another agent</Btn>}{task.status === 'DONE' && <div className="flex"><Btn onClick={() => executeAction("ui.go", u, 'watcher')}>Open result</Btn><Btn onClick={() => executeAction("ui.schedule", u, task.title)}>Repeat this</Btn></div>}</> : roomMessages.length === 0 && <Empty>Create a task to begin.</Empty>}</div></div>
   <div style={{
          padding: '12px 30px 22px'
        }}><div style={{
            maxWidth: 780,
            margin: '0 auto'
          }}><Composer taskId={task?.id} placeholder="Reply, or @ another agent…" /></div></div>
  </main>
 </div>;
  }
  window.UI.Workshop = Win;
  window.UI.Messages = Messages;
  window.UI.Task = Task;
})();
