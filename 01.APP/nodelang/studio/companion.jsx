// The native companion owns the desktop sprite; this is its approved conversation face (app.js:1148-1181).
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
    api,
    useData,
    useApp,
    Btn
  } = window.UI;
  function tipForSurface(surface) {
    if (surface === 'home') return 'Home is your queue. Pick a row to answer it here; type below to start a task.';
    if (surface === 'canvas' || surface === 'task-file' || surface === 'task')
      return 'Click a node to see its properties. Run runs every step; writes wait for your Approve.';
    if (surface === 'docs') return 'Type a question below and I open the article.';
    if (String(surface || '').startsWith('settings'))
      return 'Type what you want to change below, for example "light theme".';
    return 'Ask me anything about ArchHub.';
  }
  function clampBesideLeftDock(panel, rightPx, bottomPx) {
    if (!panel) return;
    panel.style.maxWidth = '';
    panel.style.right = rightPx + 'px';
    panel.style.bottom = bottomPx + 'px';
    const dock = document.querySelector('.dock.left');
    const own = panel.getBoundingClientRect();
    if (dock && own.width > 0) {
      const dr = dock.getBoundingClientRect();
      if (dr.width > 40 && own.left < dr.right + 8 && own.top < dr.bottom) {
        const room = window.innerWidth - rightPx - dr.right - 16;
        panel.style.maxWidth = Math.max(180, room) + 'px';
      }
    }
  }
  function visibleComposerField() {
    return [...document.querySelectorAll('[data-design="composer.msg"]')].filter(e => e.offsetParent).pop() || null;
  }
  function CompanionConversation({
    open,
    setOpen,
    taskId
  }) {
    const s = useData(),
      u = useApp();
    const panelRef = React.useRef(null),
      log = React.useRef(null),
      wasOpen = React.useRef(false);
    const [teachOpen, setTeachOpen] = React.useState(false);
    const task = (s.tasks || []).find(t => t.id === taskId);
    const rawMsgs = task
      ? (u.route === 'home' && window.UI.homeTaskMessages
          ? window.UI.homeTaskMessages(task)
          : [...(task.fileMessages || []), ...(task.messages || [])])
      : [];
    const recentMsgs = rawMsgs.slice(-6);
    const taskOf = card => (s.tasks || []).find(t => [card.taskId, card.task_id, card.work, ...(card.taskIds || [])].includes(t.id));
    const waiting = (s.approvals || []).filter(card => card.status === 'pending' || card.status === 'approval')
      .filter((card, idx, all) => all.findIndex(row => (row.input_digest || row.id) === (card.input_digest || card.id)) === idx);
    React.useLayoutEffect(() => {
      if (!open) {
        wasOpen.current = false;
        setTeachOpen(false);
        return;
      }
      if (log.current) {
        log.current.scrollTop = wasOpen.current ? log.current.scrollHeight : 0;
      }
      wasOpen.current = true;
      const onKey = e => {
        if (e.key === 'Escape' && !e.target?.closest?.('textarea,input')) setOpen(false);
      };
      const place = () => {
        const panel = panelRef.current;
        if (!panel) return;
        const composer = [...document.querySelectorAll('[data-design="composer.surface"]')].filter(e => e.offsetParent).pop();
        const box = composer?.getBoundingClientRect();
        const rightPx = box ? Math.max(12, Math.min(window.innerWidth - 200, window.innerWidth - box.right)) : 24;
        const rawBottom = box ? window.innerHeight - box.top + 108 : 172;
        const bottomPx = Math.max(12, Math.min(rawBottom, Math.max(12, window.innerHeight - 220)));
        clampBesideLeftDock(panel, rightPx, bottomPx);
      };
      place();
      window.addEventListener('keydown', onKey);
      window.addEventListener('resize', place);
      const dock = document.querySelector('.dock.left');
      const obs = typeof window.ResizeObserver === 'function' ? new window.ResizeObserver(place) : null;
      if (obs && dock) obs.observe(dock);
      return () => {
        window.removeEventListener('keydown', onKey);
        window.removeEventListener('resize', place);
        obs?.disconnect();
      };
    }, [open, setOpen, recentMsgs.length, waiting.length, teachOpen, u.route]);
    if (!open) return null;
    const composer = [...document.querySelectorAll('[data-design="composer.surface"]')].filter(e => e.offsetParent).pop();
    const box = composer?.getBoundingClientRect();
    const initialRight = box ? Math.max(12, Math.min(window.innerWidth - 200, window.innerWidth - box.right)) : 24;
    const initialBottom = Math.max(12, Math.min(box ? window.innerHeight - box.top + 108 : 172, Math.max(12, window.innerHeight - 220)));
    const tipText = tipForSurface(u.route);
    const askBaboom = () => {
      const field = visibleComposerField();
      if (field) field.focus();
    };
    const giveBaboomTask = () => {
      const scopeBtn = document.querySelector('[data-design="composer.to"][aria-pressed="false"]');
      if (scopeBtn) scopeBtn.click();
      const field = visibleComposerField();
      if (field) {
        field.placeholder = 'Say what BABOOM should do. It gets its own task and Canvas';
        field.focus();
      }
    };
    const approveCard = card => u.act(async () => {
      const res = await api.approve(card.id);
      if (res && res.ok !== false) await api.listTasks?.();
      return res;
    });
    const showCard = card => {
      const targetTask = taskOf(card);
      setOpen(false);
      if (targetTask && u.openTaskFile) {
        return Promise.resolve(u.openTaskFile(targetTask.id, 'canvas')).then(() => {
          if (card.nodeId) u.setSelectedNodeId?.(card.nodeId);
        });
      }
      if (card.nodeId) u.setSelectedNodeId?.(card.nodeId);
      return u.go?.('canvas');
    };
    return <section ref={panelRef} role="dialog" aria-modal="false" className="pet-bubble bbm-panel" aria-label="BABOOM companion" style={{
      right: initialRight,
      bottom: initialBottom,
      maxHeight: 'min(460px, calc(100vh - ' + (initialBottom + 16) + 'px))',
      gap: 10
    }}>
      <header className="spread bbm-ph"><div className="flex"><i className="spr bbm-mini" data-pose="idle" aria-hidden="true" /><div><b>BABOOM</b><span>Your ArchHub assistant</span></div></div><button type="button" className="button-reset bbm-x" aria-label="Close BABOOM" data-bbmx="" onClick={() => executeAction("ui.state", setOpen, false)}>×</button></header>
      <div className="pbacts" style={{display: 'flex', flexWrap: 'wrap', gap: 6}}>
        <Btn sm plain data-bb="ask" onClick={event => executeAction("ui.select", askBaboom, event)}>Ask BABOOM</Btn>
        <Btn sm plain data-bb="work" onClick={event => executeAction("ui.select", giveBaboomTask, event)}>Give BABOOM a task</Btn>
        <Btn sm plain data-bb="teach" aria-expanded={teachOpen} onClick={event => executeAction("ui.select", () => setTeachOpen(v => !v), event)}>Teach me this page</Btn>
      </div>
      <p className="pbtip" hidden={!teachOpen} style={{margin: 0, fontSize: 'calc(12px * var(--text-scale,1))', color: 'var(--color-ink-soft)'}}>{tipText}</p>
      <div className="bbm-log pet-messages" aria-live="polite" ref={log} style={{display: 'flex', flexDirection: 'column', gap: 8}}>
        <p className="bbm-msg" style={{margin: 0}}>Welcome. Ask me about your work or the standard, or tell me what to do. Type below; I answer here.</p>
        <p className="bbm-msg" lang="ar" dir="rtl" style={{margin: 0}}>أهلاً. اسألني عن شغلك أو الستاندرد، أو قولّي أعمل إيه. اكتب تحت وأنا أرد هنا.</p>
        {recentMsgs.map((m, idx) => {
          const own = m.who === 'You' || (Boolean(m.sender_key) && m.sender_key === m.viewer_key);
          const body = typeof m.text === 'string' ? m.text : String(m.text ?? '');
          return <p key={m.id || idx} className={'bbm-msg' + (own ? ' me' : '')} style={{
            margin: 0,
            padding: '8px 11px',
            borderRadius: own ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
            background: own ? 'var(--color-accent-soft, var(--color-bg-soft))' : 'var(--color-bg-soft)',
            alignSelf: own ? 'flex-end' : 'flex-start',
            maxWidth: '92%'
          }}>{body}</p>;
        })}
        {waiting.map(card => {
          const parentTask = taskOf(card);
          const stepName = (card.nodeId && ((parentTask?.workflow || []).find(n => n.id === card.nodeId)?.title || s.graph?.nodes?.find(n => n.id === card.nodeId)?.title)) || card.title || 'Step';
          const taskName = parentTask?.title || parentTask?.name || card.target || s.graph?.name || 'Workspace';
          return <div key={card.id} className="bbm-msg bbm-act" style={{
            display: 'grid',
            gap: 8,
            padding: '9px 12px',
            borderRadius: '12px 12px 12px 4px',
            background: 'var(--color-bg-soft)',
            border: '1px solid var(--color-line)'
          }}>
            <span>{stepName + ' in ' + taskName + ' needs your approval.'}</span>
            <span className="acts" style={{display: 'flex', flexWrap: 'wrap', gap: 6}}>
              <Btn p sm plain data-bbmok={card.id} onClick={event => executeAction("ui.select", () => approveCard(card), event)}>Approve</Btn>
              <Btn sm plain data-bbmshow={card.id} onClick={event => executeAction("ui.select", () => showCard(card), event)}>Show</Btn>
            </span>
          </div>;
        })}
      </div>
    </section>;
  }
  window.UI.BaboomSprite = CompanionConversation;
})();
