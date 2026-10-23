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
  const stages = ['PLANNED', 'WIP', 'IN REVIEW', 'DONE', 'ARCHIVED'];
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
        }}>{task.status === 'IN REVIEW' ? 'Waits for your OK' : task.status}</div>{task.status === 'WIP' && steps.length > 0 && <span role="progressbar" aria-label={task.title + ' steps'} aria-valuemin={0} aria-valuenow={completed} aria-valuemax={steps.length} style={{
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
        gridTemplateColumns: m.who === 'You' ? '1fr' : '32px 1fr',
        gap: 14
      }}>{m.who !== 'You' && <Av id={m.who === 'BABOOM' ? 'goose' : window.ArchHubAPI.getSnapshot().providers.find(p => p.name === m.who)?.id || 'claude'} size={32} />}<div style={{
          display: 'grid',
          gap: 8,
          ...(m.who === 'You' ? {
            justifySelf: 'end',
            maxWidth: 560,
            padding: '12px 16px',
            borderRadius: '14px 14px 4px 14px',
            background: '#24242b'
          } : {})
        }}>{m.who !== 'You' && <div className="flex"><b style={{
              fontSize: 15
            }}>{m.who}</b><span className="muted" style={{
              fontSize: 12
            }}>{m.model || 'Model not reported'}</span></div>}<p style={{
            fontSize: 15,
            lineHeight: '24px',
            whiteSpace: 'pre-wrap'
          }}>{m.text}</p>{['pending', 'delivered', 'answered'].includes(m.state) && <span role="status" data-delivery-state={m.state} className="muted">{m.state === 'answered' ? 'Answered' : m.state === 'delivered' ? 'Delivered' : 'Pending'}{m.delivery?.some(row => row.escalated) ? ' · Coordinator notified' : ''}</span>}<window.UI.TurnUsage message={m} /><window.UI.AnswerWidget message={m} />{m.who !== 'You' && <window.UI.AnswerSources message={m} />}{m.rule && <Chip c={A.purple}>Your rule: {m.rule}</Chip>}</div></div>)}</div>;
  }
  function Win() {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState('');
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
        }}>{stages.map(stage => <div key={stage} onDragOver={e => e.preventDefault()} onDrop={e => {
            e.preventDefault();
            const id = e.dataTransfer.getData('task');
            if (id) executeAction("setTaskStatus", u, id, stage);
          }}><div className="spread label" style={{
              padding: '16px 22px 6px'
            }}><span>{stage}</span><span>{list.filter(t => t.status === stage).length}</span></div><div style={{
              padding: '0 10px'
            }}>{list.filter(t => t.status === stage).map(t => <Task key={t.id} task={t} on={task?.id === t.id} select={() => executeAction("ui.setTask", u, t.id)} />)}</div></div>)}</div>
   <Card style={{
          margin: 12,
          padding: 14,
          display: 'grid',
          gap: 10,
          flex: 'none'
        }}>{s.providers.filter(p => p.enabled && (p.signedIn || p.sessions?.length)).map(p => <button key={p.id} draggable title={'Drag ' + p.name + ' to Canvas'} onDragStart={e => e.dataTransfer.setData('node', 'Agent:' + p.id)} className="button-reset spread" onClick={() => executeAction("ui.show", u, 'Agent', {
            id: p.id
          })}><span className="flex"><Av id={p.id} size={22} /><b style={{
                fontSize: 12
              }}>{p.name}</b></span><span className="muted" style={{
              fontSize: 11
            }}>{p.presence || (p.sessions?.length ? 'Session discovered' : 'Signed in')}</span></button>)}<Btn sm ghost onClick={() => executeAction("ui.go", u, 'colleagues')}>Team &amp; meetings</Btn></Card>
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
            }}>One room · {s.graph.name}</p></div><div className="flex">{task && <Chip c={color(task.status)}>{task.status}</Chip>}<Btn sm onClick={async () => {
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
