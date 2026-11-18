// The native companion owns the desktop sprite; this is its approved conversation face.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
    useData,
    useApp,
    Btn,
    ApprovalCard,
    Messages
  } = window.UI;
  function CompanionConversation({
    open,
    setOpen,
    taskId
  }) {
    const s = useData(),
      u = useApp();
    const log = React.useRef(null);
    const task = s.tasks.find(t => t.id === taskId);
    // It opens on the greeting's first line (one-BABOOM spec 5).
    React.useLayoutEffect(() => {
      if (open && log.current) log.current.scrollTop = 0;
    }, [open]);
    if (!open) return null;
    const conversation = task && u.route === 'home' ? {...task, messages: window.UI.homeTaskMessages(task)} : task;
    // The app has one composer, so this panel has no input of its own: BABOOM stands on the composer's right end
    // (his 80 x 100 box, stepping up to 48 px aside) and the panel sits above him.
    const composer = [...document.querySelectorAll('[data-design="composer.surface"]')].filter(e => e.offsetParent).pop();
    const box = composer?.getBoundingClientRect();
    const bottom = box ? window.innerHeight - box.top + 160 : 172;
    return <section className="pet-bubble" aria-label="BABOOM companion" style={{
      right: box ? Math.max(12, window.innerWidth - box.right) : 24,
      bottom,
      maxHeight: 'min(70vh, calc(100vh - ' + (bottom + 16) + 'px))'
    }}>
   <header className="spread bbm-ph"><div className="flex"><i className="bbm-mini" aria-hidden="true" /><div><b>BABOOM</b><span>Your ArchHub assistant</span></div></div><div className="flex">
   <Btn sm ghost aria-label="Open the Brain" title="Brain" onClick={() => {
            executeAction("ui.state", setOpen, false);
            executeAction("ui.go", u, 'brain');
          }}><window.AHIcon name="brain" size={16} /></Btn>
   <Btn sm ghost aria-label="BABOOM settings" onClick={() => {
            executeAction("ui.state", setOpen, false);
            executeAction("ui.go", u, 'settings/BABOOM');
          }}><window.AHIcon name="settings" size={16} /></Btn>
   <button type="button" className="button-reset bbm-x" aria-label="Close BABOOM" onClick={() => executeAction("ui.state", setOpen, false)}>×</button></div></header>
   <div className="pet-messages" ref={log}><p>Welcome. Ask me about your work or the standard, or tell me what to do. Type below; I answer here.</p><p lang="ar" dir="rtl">أهلاً. اسألني عن شغلك أو الستاندرد، أو قولّي أعمل إيه. اكتب تحت وأنا أرد هنا.</p>{task && <><Messages task={conversation} />{task.approvalId && <ApprovalCard id={task.approvalId} compact />}</>}</div>
   <div className="spread muted" style={{
        fontSize: 11
      }}><span>{s.tasks.filter(t => t.status === 'WIP').length} tasks running</span><button className="button-reset" onClick={() => executeAction("ui.go", u, 'workshop')}>View in Workshop →</button></div>
  </section>;
  }
  window.UI.BaboomSprite = CompanionConversation;
})();
