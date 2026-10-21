// The native companion owns the desktop sprite; this is its approved conversation face.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
    useData,
    useApp,
    Btn,
    Chip,
    Composer,
    ApprovalCard,
    Messages
  } = window.UI;
  function CompanionConversation({
    open,
    setOpen
  }) {
    const s = useData(),
      u = useApp();
    const [activeTask, setActiveTask] = React.useState(null);
    const task = s.tasks.find(t => t.id === (activeTask || u.task));
    if (!open) return null;
    return <section className="pet-bubble" aria-label="BABOOM companion" style={{
      right: 24,
      bottom: 55
    }}>
   <header className="spread"><div className="flex"><h2>BABOOM</h2><Chip>{s.connectionNotice || 'Workshop'}</Chip></div><div className="flex">
   <Btn sm ghost aria-label="BABOOM settings" onClick={() => {
            executeAction("ui.state", setOpen, false);
            executeAction("ui.go", u, 'settings/BABOOM');
          }}><window.AHIcon name="settings" size={16} /></Btn>
   <Btn sm ghost aria-label="Close BABOOM" onClick={() => executeAction("ui.state", setOpen, false)}>×</Btn></div></header>
   <div className="pet-messages">{task ? <><Messages task={task} />{task.approvalId && <ApprovalCard id={task.approvalId} compact />}</> : <p className="muted">Tell me what you want to do. I’ll follow it through.</p>}</div>
   <Composer compact taskId={task?.id} onSent={t => setActiveTask(t.id)} /><div className="spread muted" style={{
        fontSize: 11
      }}><span>{s.tasks.filter(t => t.status === 'WIP').length} tasks running</span><button className="button-reset" onClick={() => executeAction("ui.go", u, 'workshop')}>View in Workshop →</button></div>
  </section>;
  }
  window.UI.BaboomSprite = CompanionConversation;
})();
