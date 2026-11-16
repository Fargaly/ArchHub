// The native companion owns the desktop sprite; this is its approved conversation face.
// DESIGNV51 S11/S13: BABOOM is parked in the rail above Docs on every page, never over content; its bubble opens above it.
(() => {
  function executeAction(...args) {
    return window.executeAction(...args);
  }
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
    setOpen,
    rail
  }) {
    const s = useData(),
      u = useApp();
    const [activeTask, setActiveTask] = React.useState(null);
    const petRef = React.useRef(null), bubbleRef = React.useRef(null);
    const [top, setTop] = React.useState(56);
    const task = s.tasks.find(t => t.id === (activeTask || u.task));
    const waiting = s.approvals.filter(c => c.status === 'pending');
    React.useLayoutEffect(() => {
      if (!open || !bubbleRef.current) return;
      const pet = petRef.current?.getBoundingClientRect();
      setTop(pet ? Math.max(56, pet.top - bubbleRef.current.offsetHeight - 10) : 56);
    }, [open, waiting.length, task?.id]);
    const pet = rail && <button ref={petRef} type="button" className="rail-pet" aria-label="BABOOM" aria-expanded={!!open} title="BABOOM, your companion agent"
      onClick={event => executeAction('projects.controls.activate', {handler: () => setOpen(!open)}, event)}><span className="spr" aria-hidden="true" />{waiting.length > 0 && <b className="pb">{waiting.length}</b>}</button>;
    if (!open) return pet || null;
    const state = waiting.length ? 'Needs your OK' : s.agentWorkingCount ? 'Working' : 'Here';
    return <>{pet}<section ref={bubbleRef} className="pet-bubble" role="dialog" aria-label="BABOOM companion" style={rail ? {left: 8, top} : {right: 24, bottom: 55}}
      onKeyDown={event => { if (event.key === 'Escape') setOpen(false); }}>
   <header className="spread pbh"><div className="flex"><b>BABOOM</b><Chip>{state}</Chip></div><div className="flex">
   <a className="link" href="https://baboom.archhub.io" target="_blank" rel="noopener">BABOOM site</a>
   <Btn sm ghost aria-label="BABOOM settings" onClick={event => executeAction('projects.controls.activate', {handler: () => { setOpen(false); u.go('settings/BABOOM'); }}, event)}><window.AHIcon name="settings" size={16} /></Btn>
   <Btn sm ghost aria-label="Close BABOOM" onClick={event => executeAction('projects.controls.activate', {handler: () => setOpen(false)}, event)}>×</Btn></div></header>
   <p className="pbrole">Your companion agent: assistant, guide, teacher and colleague.</p>
   <div className="pbacts"><Btn sm onClick={event => executeAction('projects.controls.activate', {handler: () => bubbleRef.current?.querySelector('textarea')?.focus()}, event)}><window.AHIcon name="workshop" size={13} /> Ask BABOOM</Btn>
     <Btn sm onClick={event => executeAction('projects.controls.activate', {handler: () => { setOpen(false); u.show('New task'); }}, event)}><window.AHIcon name="plus" size={13} /> Give BABOOM a task</Btn></div>
   {waiting[0] && <div className="pbcard" data-approval={waiting[0].id}><span className="eyebrow">{s.tasks.find(t => t.id === (waiting[0].taskId || waiting[0].work))?.title || 'Waits for you'}</span><h3>{waiting[0].title}</h3>{waiting[0].summary && <p>{waiting[0].summary}</p>}
     <div className="flex"><Btn sm p onClick={event => executeAction('projects.controls.activate', {handler: () => { setOpen(false); u.show('Approve', {id: waiting[0].id}); }}, event)}>Review</Btn><Btn sm onClick={event => executeAction('projects.controls.activate', {handler: () => { setOpen(false); u.go('workshop'); }}, event)}>Open in Workshop</Btn></div></div>}
   <div className="pet-messages">{task ? <><Messages task={task} />{task.approvalId && task.approvalId !== waiting[0]?.id && <ApprovalCard id={task.approvalId} compact />}</> : !waiting.length && <p className="muted">Tell me what you want to do. I’ll follow it through.</p>}</div>
   <Composer compact taskId={task?.id} onSent={t => setActiveTask(t.id)} /><div className="spread muted" style={{
        fontSize: 11
      }}><span>{s.tasks.filter(t => t.status === 'WIP').length} tasks running</span><button className="button-reset" onClick={event => executeAction('projects.controls.activate', {handler: () => u.go('workshop')}, event)}>View in Workshop →</button></div>
  </section></>;
  }
  window.UI.BaboomSprite = CompanionConversation;
})();
