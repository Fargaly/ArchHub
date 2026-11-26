// Shared UI state only. Domain state and actions belong to src/api.js.
(() => {
  function executeAction(...args) {
    return window.executeAction(...args);
  }
  const api = window.ArchHubAPI,
    A = window.AH,
    D = window.AH_DS;
  // Workshop elevation tokens are copied from DSYS-077/082, not a new theme.
  A.workshop = {
    buttonBackground: '#26262d'
  };
  const Ctx = React.createContext(null);
  const useApp = () => React.useContext(Ctx);
  // F178.2: no dependency label until the task owner supplies a real blocked_by field.
  const blockedDependencyReason = () => '';
  // Named parameters of a held run as readable rows: a file shows its name, never its folder path.
  const approvalRows = text => {
    let held = null;
    try { held = JSON.parse(text); } catch (error) { console.warn('Approval text is not structured; shown as written: ' + error.message); return null; }
    const named = held && typeof held === 'object' && held.parameters && typeof held.parameters === 'object' && !Array.isArray(held.parameters) ? Object.entries(held.parameters) : [];
    const leaf = value => String(typeof value === 'object' && value !== null ? JSON.stringify(value) : value).replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\n"]+/g, path => path.trim().split(/[\\/]/).filter(Boolean).pop() || path);
    return named.length ? named.slice(0, 8).map(([name, value]) => [name.replace(/_/g, ' '), leaf(value)]) : null;
  };
  const taskRowReason = task => {
    const state = String(task.rowState || '').toLowerCase().replace(/_/g, ' ');
    if (state === 'interrupted' || task.outcome === 'interrupted') return 'interrupted';
    if (state === 'limit reached' || task.capacity === 'LIMIT_REACHED') return 'limit reached';
    return blockedDependencyReason();
  };
  const noopSubscribe = () => () => {};
  const emptySnapshot = () => ({});
  const useData = () => {
    const a = api || window.ArchHubAPI || window.UI?.api;
    return React.useSyncExternalStore(a?.subscribe || noopSubscribe, a?.getSnapshot || emptySnapshot, a?.getSnapshot || emptySnapshot);
  };
  const actionIcons = {
    'Start': 'play',
    'Review': 'eye',
    'Open': 'arrow',
    'Open sheets': 'eye',
    'Open on canvas': 'canvas',
    'Run every day': 'clock',
    'Talk': 'mic',
    '🎙 Talk': 'mic',
    'Send ↵': 'send',
    'Send': 'send',
    'Edit': 'edit',
    'Forget': 'trash',
    'Remove': 'trash',
    'Delete…': 'trash',
    'Delete node…': 'trash',
    'Export': 'export',
    'Sync': 'refresh',
    'Sync to cloud': 'cloud',
    'Reset': 'refresh',
    'Arrange': 'arrange',
    'Group': 'group',
    'Ungroup': 'group',
    'Fit': 'fit',
    '↶': 'undo',
    '↷': 'redo',
    'Run': 'play',
    'Open notes': 'docs',
    'Make task': 'plus',
    'Repeat this': 'clock',
    'Trace back': 'back',
    'Trace forward': 'arrow',
    'Save skill': 'pin',
    'Add': 'plus',
    'Open Library': 'library',
    'Open Skills': 'pin',
    'Open Templates': 'library',
    'Open receipts': 'docs',
    'Settings': 'settings',
    '×': 'close',
    'Check': 'check',
    'Check all': 'check',
    'Retry': 'refresh',
    'Rerun': 'refresh',
    'Fork': 'canvas',
    'Open workflow': 'canvas'
  };
  const Btn = ({
    p,
    sm,
    ghost,
    danger,
    plain,  // a text label (a filter chip named Settings) never becomes its action icon
    children,
    ...props
  }) => {
    const label = typeof children === 'string' ? children : null;
    const icon = !p && !plain && label && actionIcons[label];
    return <D.Btn variant="workshop" primary={p} sm={sm} kind={danger ? 'danger' : ghost ? 'ghost' : undefined} {...props} aria-label={props['aria-label'] || (icon ? label : undefined)} title={props.title || (icon ? label : undefined)} className={[props.className, icon ? 'icon-action' : ''].filter(Boolean).join(' ')} style={{
      ...(icon ? {
        width: 30,
        minWidth: 30,
        padding: 0,
        background: 'transparent',
        borderColor: 'transparent'
      } : {}),
      ...props.style
    }}>{icon ? <window.AHIcon name={icon} size={16} /> : children}</D.Btn>;
  };
  const Card = ({
    children,
    style,
    ...props
  }) => <D.Card variant="home" style={style} {...props} className={['app-card', props.className].filter(Boolean).join(' ')}>{children}</D.Card>;
  const Chip = ({
    children,
    c = A.accent
  }) => <span className="badge" style={{
    background: c + '1f',
    color: c,
    fontWeight: 600
  }}>{children}</span>;
  function AvatarMenu({id, person = false, selectionNodeId, onClose}) {
    const s = useData(), u = useApp();
    const [sub, setSub] = React.useState('');
    const people = s.people || [];
    const personRow = person ? (people.find(p => p.id === id || p.name === id) || {id, name: id}) : people.find(p => p.id === id || p.name === id);
    const agentRow = !personRow && ((s.agents || []).find(a => a.id === id || a.name === id)
      || (s.providers || []).find(p => p.id === id || p.name === id)
      || (s.liveAgents || []).find(a => a.agent === id || a.handle === id || a.name === id));
    const isPerson = Boolean(person || personRow);
    const rawName = String(personRow?.name || agentRow?.name || id || 'Agent').split(/\s+\/\s+/).at(-1).trim();
    const handle = String(agentRow?.handle || agentRow?.id || rawName).toLowerCase().replace(/[^a-z0-9._-]+/g, '-');
    if (isPerson) {
      const targetNode = selectionNodeId || personRow?.selectionNodeId || personRow?.nodeId || '';
      return <div role="menu" aria-label={rawName + ' menu'} data-design="person.menu" style={{
        position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 1100, minWidth: 216,
        background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
        borderRadius: 10, padding: 6, boxShadow: '0 12px 32px rgba(0,0,0,0.45)', display: 'grid', gap: 2
      }}>
        <div style={{padding: '6px 10px', borderBottom: '1px solid var(--color-line-soft, #1e1e24)', marginBottom: 2}}>
          <div style={{fontSize: 13, fontWeight: 600, color: 'var(--color-ink, #ece8e0)'}}>{rawName}</div>
          {personRow?.accessRole && <div className="muted" style={{fontSize: 11}}>{personRow.accessRole}</div>}
        </div>
        <button type="button" role="menuitem" className="listbutton" onClick={event => executeAction('sharedUI.PersonMention', {handle, onClose, rawName, u}, event)}>Mention {rawName}</button>
        <button type="button" role="menuitem" className="listbutton" onClick={event => executeAction('sharedUI.PersonSelection', {onClose, rawName, targetNode, u}, event)}>Go to their selection</button>
      </div>;
    }
    const tasks = (s.tasks || []).filter(t => t.status !== 'ARCHIVED');
    const workTasks = tasks.filter(t => t.agent === id || t.agent === rawName || t.delegate === id || (t.messages || []).some(m => m.who === rawName || m.who === id));
    const providerObj = (s.providers || []).find(p => p.id === (agentRow?.provider || agentRow?.id || id)) || agentRow;
    const models = [...new Set([providerObj?.model, ...(providerObj?.models || []), ...(agentRow?.models || [])].filter(Boolean))];
    const working = Boolean(agentRow?.status === 'working' || agentRow?.presence === 'working' || workTasks.some(t => t.status === 'WIP' || t.status === 'RUNNING'));
    const nodeMatch = (s.graph?.nodes || []).find(n => n.id === id || n.title === rawName || n.params?.agent === id || n.params?.agent === rawName);
    return <div role="menu" aria-label={rawName + ' menu'} data-design="avatar.menu" style={{
      position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 1100, minWidth: 236,
      background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
      borderRadius: 10, padding: 6, boxShadow: '0 12px 32px rgba(0,0,0,0.45)', display: 'grid', gap: 2
    }}>
      <div style={{padding: '6px 10px', borderBottom: '1px solid var(--color-line-soft, #1e1e24)', marginBottom: 2}}>
        <div style={{fontSize: 13, fontWeight: 600, color: 'var(--color-ink, #ece8e0)'}}>{rawName}</div>
        <div className="muted" style={{fontSize: 11}}>{providerObj?.model || agentRow?.runtime || (working ? 'Working now' : 'Ready')}</div>
      </div>
      <button type="button" role="menuitem" className="listbutton" onClick={event => executeAction('sharedUI.AvGoNode', {nodeMatch, onClose, rawName, u, workTasks}, event)}>Go to its node</button>
      <button type="button" role="menuitem" className="listbutton" onClick={event => executeAction('sharedUI.AvOpenThread', {onClose, u, workTasks}, event)}>Open its thread</button>
      <button type="button" role="menuitem" className="listbutton" onClick={event => executeAction('sharedUI.AvMessage', {handle, onClose, u}, event)}>Message</button>
      <button type="button" role="menuitem" aria-expanded={sub === 'assign'} className="listbutton spread" onClick={event => executeAction('sharedUI.AvSubToggle', {key: 'assign', setSub, sub}, event)}><span>Assign to a task…</span><span className="muted">›</span></button>
      {sub === 'assign' && <div role="group" aria-label="Assign task choices" style={{paddingLeft: 10, display: 'grid', gap: 2}}>
        {tasks.length ? tasks.slice(0, 8).map(t => <button type="button" role="menuitem" key={t.id} className="listbutton" onClick={event => executeAction('sharedUI.AvAssignTask', {api, handle, id, onClose, rawName, t, u}, event)}>{t.title}</button>) : <span className="muted" style={{fontSize: 11, padding: '4px 8px'}}>No open tasks yet.</span>}
      </div>}
      <button type="button" role="menuitem" aria-expanded={sub === 'work'} className="listbutton spread" onClick={event => executeAction('sharedUI.AvSubToggle', {key: 'work', setSub, sub}, event)}><span>See its work ({workTasks.length})</span><span className="muted">›</span></button>
      {sub === 'work' && <div role="group" aria-label="Agent work items" style={{paddingLeft: 10, display: 'grid', gap: 2}}>
        {workTasks.length ? workTasks.map(t => <button type="button" role="menuitem" key={t.id} className="listbutton" onClick={event => executeAction('sharedUI.AvOpenWork', {onClose, t, u}, event)}>{t.title}</button>) : <span className="muted" style={{fontSize: 11, padding: '4px 8px'}}>Nothing assigned right now.</span>}
      </div>}
      <button type="button" role="menuitem" aria-expanded={sub === 'model'} className="listbutton spread" onClick={event => executeAction('sharedUI.AvSubToggle', {key: 'model', setSub, sub}, event)}><span>Switch model…</span><span className="muted">›</span></button>
      {sub === 'model' && <div role="group" aria-label="Model choices" style={{paddingLeft: 10, display: 'grid', gap: 2}}>
        {(models.length ? models : ['Default model']).map(mdl => <button type="button" role="menuitemradio" aria-checked={mdl === providerObj?.model} key={mdl} className="listbutton spread" onClick={event => executeAction('sharedUI.AvSwitchModel', {api, id: providerObj?.id || id, mdl, onClose, rawName, u}, event)}><span>{mdl}</span><span>{mdl === providerObj?.model ? '✓' : ''}</span></button>)}
      </div>}
      <button type="button" role="menuitem" disabled={!working} className="listbutton" style={{color: working ? 'var(--color-err, #e6705f)' : undefined}} onClick={event => executeAction('sharedUI.AvStop', {api, id, onClose, rawName, u}, event)}>Stop</button>
    </div>;
  }
  const Av = ({
    id,
    size = 28,
    menu = false,
    person = false,
    selectionNodeId
  }) => {
    const s = (window.UI?.useData && window.UI.useData !== useData ? window.UI.useData : useData)() || {};
    const [open, setOpen] = React.useState(false);
    const p = (s.agents||[]).find(p => p.id === id) || (s.providers||[]).find(p => p.id === id) || (s.people||[]).find(p => p.id === id || p.name === id) || {
      name: id,
      ini: String(id || '').trim().split(/[\s._-]+/).filter(Boolean).map(w => w[0].toUpperCase()).join('').slice(0, 2),  // initials of the display name
      col: A.userAv
    };
    const name=String(p.name||id||'Agent').split(/\s+\/\s+/).at(-1).trim();
    const initials=name.split(/[\s._-]+/).filter(Boolean).map(word=>word[0].toUpperCase()).join('').slice(0,2)||'?';
    const hue=Array.from(String(p.name||id)).reduce((hash,char)=>(hash*31+char.charCodeAt(0))%360,0);
    const palette=[A.accent,A.blue,A.purple,A.ok,A.warn,A.cyan];
    const badge=<D.Avatar agent={{...p,name,ini:initials,col:palette[hue%6]||'#d97757'}} size={size}/>;
    if (!menu) return <span className="agent-avatar" title={p.name||id}>{badge}</span>;
    return <span className="agent-avatar-wrap" onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }} style={{position:'relative',display:'inline-flex',alignItems:'center'}}>
      <button type="button" className="button-reset agent-avatar" title={p.name||id} aria-label={(person ? 'Person ' : 'Agent ') + name} aria-haspopup="menu" aria-expanded={open} onClick={event => executeAction('sharedUI.AvatarToggle', {open, setOpen}, event)}>{badge}</button>
      {open && <><div aria-hidden="true" onMouseDown={() => setOpen(false)} style={{position:'fixed',inset:0,zIndex:1099}} /><AvatarMenu id={id} person={person} selectionNodeId={selectionNodeId} onClose={() => setOpen(false)} /></>}
    </span>;
  };
  function Heading({
    title,
    sub,
    children
  }) {
    return <div className="spread title"><div><h1>{title}</h1>{sub && <p className="muted" style={{
          marginTop: 4,
          fontSize: 13
        }}>{sub}</p>}</div><div className="flex">{children}</div></div>;
  }
  function Empty({
    children
  }) {
    return <div style={{
      padding: 24,
      color: A.inkSoft,
      border: '1px dashed ' + A.line,
      borderRadius: 10
    }}>{children}</div>;
  }
  function Table({
    rows,
    columns
  }) {
    const cols = columns || Object.keys(rows[0] || {});
    return rows.length ? <table className="table"><thead><tr>{cols.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={r.id || i}>{cols.map(c => <td key={c}>{typeof r[c] === 'object' ? JSON.stringify(r[c]) : String(r[c] ?? '—')}</td>)}</tr>)}</tbody></table> : <Empty>Nothing here yet.</Empty>;
  }
  // A click on BABOOM that opens his panel points a composer at him ('' is BABOOM in the To list) and puts the caret in
  // the one on screen. The click that closes the panel changes nothing: a thread's running chat stays its recipient.
  // A line of his menu that the user finishes in his own words arrives with those words: they start the composer.
  function useAskBaboom(setTo, field, setText) {
    const type = React.useRef(setText);
    type.current = setText;
    React.useEffect(() => {
      const askBaboom = event => {
        const words = event.detail?.text;
        if (!words && document.querySelector('[aria-label="BABOOM companion"]')) return;
        setTo('');
        if (words && field.current?.offsetParent) type.current(words);
        if (field.current?.offsetParent) field.current.focus();
      };
      window.addEventListener('archhub:ask-baboom', askBaboom);
      return () => window.removeEventListener('archhub:ask-baboom', askBaboom);
    }, []);
  }
  function Composer({
    taskId,
    placeholder = 'Ask for anything, or @ an agent…',
    compact = false,
    onSent,
    homeSession
  }) {
    const s = useData(),
      u = useApp();
    // Home (design v61 C1-C3): the session selected on Home is the recipient and the message lands in its thread while Home stays;
    // a new session only when none is selected or he picks New session on the scope chip.
    const [freshPick, setFreshPick] = React.useState(false);
    const toSession = u.route === 'home' && !taskId && !onSent && homeSession && !freshPick ? homeSession : null;
    const homeThreadId = toSession?.id || null;
    React.useLayoutEffect(() => {
      if (u.route !== 'home' || taskId || onSent) return;
      u.setHomeThreadId(homeThreadId);
      return () => u.setHomeThreadId(null);
    }, [u.route, taskId, onSent, homeThreadId, u.setHomeThreadId]);
    const [localDraft,setLocalDraft] = React.useState({text:'',revision:0});
    // The draft belongs to where it will go: the task, the session picked on Home (homeSession has no taskId), or a new
    // session (New session on the scope chip, or nothing picked). One key per route and actual target.
    const draftKey = JSON.stringify([u.route,taskId || toSession?.id || '']);
    const {text} = onSent ? localDraft : u.composerDraft[draftKey] || {text:'',revision:0},
      setDraft = onSent ? setLocalDraft : update => u.setComposerDraft(current => ({
        ...current,[draftKey]:update(current[draftKey] || {text:'',revision:0})
      }));
    const setText = value => setDraft(current => ({text:typeof value === 'function' ? value(current.text) : value,revision:current.revision+1}));
    const [to, setTo] = React.useState(''),
      [sending, setSending] = React.useState(false),
      [contextOpen, setContextOpen] = React.useState(false);
    const pending = React.useRef(0), sentRevision = React.useRef(null);
    const choices = window.UI.workshopPeople ? window.UI.workshopPeople(s).choices : [];
    const inputRef = React.useRef(null), [composerWidth, setComposerWidth] = React.useState(760);
    React.useLayoutEffect(() => {
      const observer = new window.ResizeObserver(entries => setComposerWidth(entries[0].contentRect.width));
      if (inputRef.current) observer.observe(inputRef.current.closest('form'));
      return () => observer.disconnect();
    }, []);
    useAskBaboom(setTo, inputRef, setText);
    const send = async () => {
      if (!text.trim()) return;
      // A second submit in the same tick (Enter twice) still sees this draft: it is the same message, sent once.
      const revision = (onSent ? localDraft : u.composerDraft[draftKey] || {revision: 0}).revision;
      // The same target and revision is the same message; another target's draft at an equal revision is its own send.
      if (sentRevision.current === draftKey + '#' + revision) return;
      sentRevision.current = draftKey + '#' + revision;
      // A failed send gives its text back only while the box still holds the draft this send cleared: never over newer
      // typing, and never over a later message that was sent meanwhile (its cleared box is not this send's).
      const cleared = revision + 1;
      const restore = () => setDraft(current => current.revision === cleared ? {text, revision: current.revision + 1} : current);
      // DESIGNSYS-050 4.9: the same To-list as the Workshop; a joined agent is @mentioned, a start choice starts that chat agent.
      const turn = window.UI.chatTurn(choices, to, text), {prompt: message, agent} = turn;
      // Each send leaves at once: the draft clears now (a second message 1 s later is its own send)
      // and comes back only if this send fails while the box is still empty.
      setDraft(current => ({text:'',revision:current.revision+1}));
      pending.current += 1;
      setSending(true);
      try {
        if (toSession) {
          const sent = await u.act(() => agent === 'BABOOM' ? api.sendToBaboom(message, {taskId: toSession.id, scope: s.graph.id}) : api.sendChatTurn(turn, undefined, toSession.id));
          if (!sent) { restore(); return; }
          await api.listTasks?.();
          u.setToast({text: 'Sent to ' + (toSession.sessionTitle || toSession.title) + '. It is in that session’s thread.', open: () => u.openTaskFile(toSession.id)});  // Home stays; Open goes in
          return;
        }
        const t = await u.act(() => {
          if(u.route==='home'&&!taskId&&!onSent)return api.createTask(message);
          if ((!taskId || agent !== 'BABOOM') && typeof api.apiRouterChat === 'function') return api.sendChatTurn(turn, undefined, taskId || undefined);
          return api.sendToBaboom(message, {taskId, scope: u.selectedNodeId || s.graph.id});
        });
        if (!t) restore();
        if (t) {
          if(u.route==='home'&&!taskId&&!onSent){
            // BABOOM or a chat agent: a start opens its session only once it answered; a refused start leaves nothing behind
            // (the server archives the empty session), Home stays, the typed text comes back and the refusal is the toast
            const answered=await u.act(()=>api.sendChatTurn({...turn,fresh:true},undefined,t.taskId));   // fresh: this session was made for this start
            await api.listTasks?.();
            if(answered){await u.openTaskFile(t.taskId);return;}
            restore();return;}
          if (typeof t.answer === 'string') {
            onSent?.(t);
            return;
          }
          u.setTask(t.id);
          onSent?.(t);
          if (!taskId && !onSent) u.go('workshop');
        }
      } finally {
        pending.current -= 1;
        if (!pending.current) setSending(false);
      }
    };
    return <D.Composer data-design="composer.surface" variant="home" as="form" onSubmit={e => {
      e.preventDefault();
      executeAction("sharedUI.Send", {send}, e);
    }} style={{
      width: '100%',
      padding: compact ? '10px 12px' : '14px 16px'
    }}>
  <div className="spread composer-scope" style={{
        fontSize: 11,
        marginBottom: 8
      }}>{u.route === 'home' && homeSession && !taskId && !onSent
        ? <button type="button" className="tab-button" data-design="composer.to" aria-label={'Composer scope: ' + (toSession ? (toSession.sessionTitle || toSession.title) : 'New session') + '. Change'} aria-pressed={!toSession} title={toSession ? 'Messages go to this session. Press for a new session.' : 'A new session starts. Press to message ' + (homeSession.sessionTitle || homeSession.title) + '.'} onClick={event => executeAction('ui.select', () => setFreshPick(!freshPick), event)}><window.AHIcon name={toSession ? 'workshop' : 'plus'} size={12} /> {toSession ? (toSession.sessionTitle || toSession.title) : 'New session'}</button>
        : <button type="button" className="tab-button" data-design="composer.to" aria-label="Composer scope" title={u.route==='home'?'New session':u.selectedNodeId ? api.contextLabel(u.selectedNodeId) : s.graph.name} onClick={event => executeAction("sharedUI.ComposerScope.1", {
          contextOpen,
          setContextOpen
        }, event)}><window.AHIcon name="canvas" size={12} /> {u.route==='home'?'New session':u.selectedNodeId ? api.contextLabel(u.selectedNodeId) : s.graph.name}</button>}<button type="button" className="icon-button" aria-label="Mention context" title="Add nodes, workflows, agents or sessions" onClick={event => executeAction("sharedUI.MentionContext.2", {
          contextOpen,
          setContextOpen
        }, event)}>＠</button></div>{contextOpen && <div className="composer-mentions" role="region" aria-label="Context choices">{u.route==='home'&&<div className="flex"><button type="button" onClick={event=>executeAction('sharedUI.Commands.6',{u},event)}>Commands</button>{['Sketch','Mark','Mask'].map(tool=><button type="button" key={tool} onClick={event=>executeAction('sharedUI.Control.7',{api,tool,u},event)}>{tool}</button>)}</div>}{[['Nodes', s.graph.nodes], ['Workflows', s.graphs], ['Agents', s.providers], ['Sessions', s.tasks]].map(([label, rows]) => <details key={label}><summary>{label}</summary>{rows.slice(0, 20).map(r => <button type="button" key={r.id} onClick={event => executeAction("sharedUI.Control.3", {
            api,
            r,
            setContextOpen,
            u
          }, event)}>{r.title || r.name}</button>)}</details>)}</div>}{s.composerAttachments.length > 0 && <div className="composer-context">{s.composerAttachments.map(id => <button type="button" key={id} onClick={event => executeAction("sharedUI.Control.4", {
          api,
          id,
          u
        }, event)}>{api.contextLabel(id)} ×</button>)}</div>}<textarea dir="auto" ref={inputRef} data-design="composer.msg" className="composer-input" rows={u.route==='home'?1:2} aria-label="Message" placeholder={composerWidth<420?"Message…":composerWidth<640?"Ask or @ an agent…":placeholder} value={text} onChange={e => {
        setText(e.target.value);
        if (e.target.value.endsWith('@')) setContextOpen(true);
      }} onKeyDown={e => {
        if (e.key === 'Enter' && (e.ctrlKey || !e.shiftKey)) {
          e.preventDefault();
          send();
        }
      }} />
  <div className="flex composer-tools"><button type="button" className="icon-button" title="Add context" aria-label="Add context" onClick={event => executeAction("sharedUI.AddContext.5", {
          u
        }, event)}><window.AHIcon name="plus" size={16} /></button><button type="button" className="icon-button" title="Commands" aria-label="Commands" onClick={event => executeAction("sharedUI.Commands.6", {
          u
        }, event)}><span>/</span></button>{[['Sketch', 'palette'], ['Mark', 'eye'], ['Mask', 'shield']].map(([tool, icon]) => <button type="button" key={tool} className="icon-button" title={tool} aria-label={tool} onClick={event => executeAction("sharedUI.Control.7", {
          api,
          tool,
          u
        }, event)}><window.AHIcon name={icon} size={15} /></button>)}{window.UI.AgentPicker && <window.UI.AgentPicker choices={choices} to={to} setTo={setTo} />}<span className="fill" />{u.route!=='home' && api.supportsAction?.('startVoiceInput') !== false && <Btn sm onClick={event => executeAction("sharedUI.TalkF2.8", {
          setText,
          u
        }, event)} title="Talk · F2">🎙 Talk</Btn>}<Btn data-design="composer.send" p sm type="submit" aria-label="Send ↵" title="Send · Enter" aria-busy={sending} disabled={!text.trim()}><window.AHIcon name="send" size={15} />{u.route==='home'?'Send':null}</Btn></div>
 {s.composerAnswer&&<div className="composer-answer" role="status" aria-label="Model answer"><small className="muted">{s.composerAnswer.provider} · {s.composerAnswer.model}</small><p style={{whiteSpace:'pre-wrap'}}>{s.composerAnswer.answer}</p>{!s.composerAnswer.request_id&&(s.composerAnswer.steps||[]).map((step,i)=><small key={step.id||i} className="muted" style={{display:'block'}}>{step.tool} · {step.status}</small>)}</div>}
 </D.Composer>;
  }
  const approvalDecisions = new Set();
  function ApprovalCard({
    id,
    compact = false
  }) {
    const s = useData(),
      u = useApp(),
      c = s.approvals.find(c => c.id === id);
    const [busy, setBusy] = React.useState(false),
      [justApproved, setJustApproved] = React.useState(false),
      [decisionError, setDecisionError] = React.useState('');
    if (!c) return <Empty>No action is waiting for approval.</Empty>;
    const warnCol = A.warn || '#e5b25a',
      okCol = A.ok || '#7ec18e',
      errCol = A.err || '#e6705f',
      lineCol = A.line || '#26262e',
      inkSoftCol = A.inkSoft || '#9b938a',
      bgSoftCol = A.bgSoft || '#1c1c23',
      radLg = A.rad?.lg || 12,
      radMd = A.rad?.md || 8;
    const taskRow = (s.tasks || []).find(t => t.id === (c.taskId || c.work));
    const taskLabel = c.taskTitle || taskRow?.title || '';
    const whoLabel = c.who || c.agent || taskRow?.agent || '';
    const reasonText = c.why || c.reason || '';
    const decide = async mode => {
      const digest = c.input_digest || id;
      if (approvalDecisions.has(digest) || api.getSnapshot().approvals.find(card=>card.id===id)?.status !== 'pending') return;
      approvalDecisions.add(digest);
      setBusy(true);
      setDecisionError('');
      try {
        const result = await u.act(() => mode === 'decline' ? api.decline(id) : api.approve(id, mode));
        if (result?.ok === false) setDecisionError(result.message);
        if (result && result.ok !== false) {
          if (mode !== 'decline') setJustApproved(true);
          await api.listTasks?.();
        }
      } catch (error) {
        setDecisionError(error.message || 'Approval was refused');
      } finally {
        approvalDecisions.delete(digest);
        setBusy(false);
      }
    };
    const extraEvidence = <>
      {c.preview && <div data-design="approval.preview" style={{fontSize: 12, padding: '8px 10px', borderRadius: radMd, background: bgSoftCol, border: '1px solid ' + lineCol}}>{c.preview}</div>}
      {reasonText && <p data-design="approval.reason" className="muted" style={{fontSize: 12, margin: 0}}>Why: {reasonText}</p>}
      {c.diff && <pre data-design="approval.diff" style={{margin: 0, whiteSpace: 'pre-wrap', font: '12px/1.45 "JetBrains Mono", monospace', background: bgSoftCol, border: '1px solid ' + lineCol, borderRadius: radMd, padding: '8px 10px'}}>{typeof c.diff === 'string' ? c.diff : JSON.stringify(c.diff, null, 2)}</pre>}
    </>;
    if (c.approvalKind === 'ask' || c.approvalKind === 'canvas') {
      const word = c.status === 'approved' ? 'Approved. Running now.' : c.status === 'declined' ? 'Refused' : c.status === 'failed' ? (c.error || 'The held action failed') : c.status;
      return <Card data-design={c.approvalKind === 'canvas' ? 'approval.panel' : 'approval.card'} data-approval={id} data-ask-card="" tabIndex={0} onKeyDown={e => {
        if (e.key === 'Enter' && c.status === 'pending' && !busy && !e.target.closest?.('button,a,input,textarea,select,summary')) {
          e.preventDefault();
          void decide('once');
        }
      }} style={{
        border: '1px solid ' + (c.status === 'pending' ? warnCol : lineCol),
        borderRadius: radLg,
        padding: 16,
        display: 'grid',
        gap: 10,
        maxHeight: c.approvalKind === 'canvas' && !compact ? 340 : undefined,
        overflowY: c.approvalKind === 'canvas' ? 'auto' : undefined
      }}>
        <div className="flex" style={{alignItems: 'flex-start', gap: 12}}>
          <div className="fill">
            <div style={{fontSize: 11, fontWeight: 600, letterSpacing: '0.03em', color: c.status === 'pending' ? warnCol : okCol, marginBottom: 2}}>{c.status === 'pending' ? 'Needs your approval' : 'Approval status'}</div>
            <h2 style={{fontSize: 15, margin: 0}}>{c.title}</h2>
            <p className="muted" style={{fontSize: 12, margin: '4px 0 0'}}>{[taskLabel, whoLabel ? whoLabel + ' asked' : ''].filter(Boolean).join(' · ') || 'Held action'}</p>
          </div>
          <Chip c={c.status === 'pending' ? warnCol : c.status === 'failed' ? errCol : okCol}>{c.status === 'pending' ? 'Needs your OK' : c.status === 'approved' ? 'Released' : word}</Chip>
        </div>
        {c.summary && <p style={{fontSize: 13, margin: 0, color: inkSoftCol, lineHeight: c.approvalKind === 'canvas' ? 1.45 : undefined}}>{c.summary}</p>}
        {extraEvidence}
        {c.text && compact && approvalRows(c.text) ? <><dl className="approval-rows">{approvalRows(c.text).map(([name,value])=><React.Fragment key={name}><dt>{name}</dt><dd>{value}</dd></React.Fragment>)}</dl><details className="approval-details"><summary>Details</summary><pre>{c.text}</pre></details></> : c.text ? <div><div style={{fontSize: 11, color: inkSoftCol, marginBottom: 4}}>{c.textLabel || 'Text'}</div><pre style={{margin: 0, whiteSpace: 'pre-wrap', font: '13px/1.45 Inter, sans-serif', background: bgSoftCol, border: '1px solid ' + lineCol, borderRadius: radMd, padding: '10px 12px'}}>{c.text}</pre></div> : null}
        {decisionError && <p role="alert">{decisionError}</p>}
        {(justApproved || c.status === 'approved') && <p role="status" data-design="approval.confirmed" style={{margin: 0, color: okCol, fontWeight: 600}}>Approved. Running now.</p>}
        {c.status === 'pending' ? <div className="flex" style={{gap: 8, flexWrap: 'wrap'}}><Btn p sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.ApproveOnce.13", {decide}, event)}>Approve <kbd style={{marginLeft: 4, fontSize: 10}}>Enter</kbd></Btn><Btn sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.ApprovalAskWhy", {c, u}, event)}>Ask why</Btn><Btn sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.Decline.15", {decide}, event)}>Reject</Btn></div> : c.status !== 'approved' ? <p style={{margin: 0, color: c.status === 'failed' ? errCol : inkSoftCol}}>{word}</p> : null}
      </Card>;
    }
    return <Card data-approval={id} style={{
      border: '1px solid ' + (c.status === 'pending' ? warnCol : lineCol),
      borderRadius: 14,
      boxShadow: c.status === 'pending' ? '0 0 0 3px ' + warnCol + '18,0 8px 28px #0007' : undefined
    }}>
  <div className="flex" style={{
        padding: '16px 18px'
      }}><span style={{
          width: 36,
          height: 36,
          borderRadius: 9,
          background: '#2b5fb8',
          display: 'grid',
          placeItems: 'center',
          fontWeight: 800
        }}>R</span><div className="fill">{c.status === 'pending' && <div style={{fontSize: 11, fontWeight: 600, color: warnCol}}>Needs your approval</div>}<h2>{c.title}</h2>{(taskLabel || whoLabel) && <p className="muted" style={{fontSize: 12, margin: '2px 0 0'}}>{[taskLabel, whoLabel ? 'by ' + whoLabel : ''].filter(Boolean).join(' · ')}</p>}<p className="muted" style={{
            fontSize: 12
          }}>{s.nativeApproval ? c.summary || c.description || c.target || '' : <>{c.target || (s.files || []).find(f => f.id === s.activeFile)?.name || 'Project model'} · {s.watcher?.view} · one undo step</>}</p></div><Chip c={c.status === 'pending' ? warnCol : okCol}>{c.status === 'pending' ? s.nativeApproval ? 'Needs your OK' : c.kind === 'social' || c.kind === 'email' ? 'Sends from your account' : c.kind === 'memory' ? 'Updates your Brain' : 'Writes to your model' : c.status}</Chip></div>
  {(c.preview || reasonText || c.diff) && <div style={{padding: '0 18px 12px', display: 'grid', gap: 8}}>{extraEvidence}</div>}
  {window.UI.ApprovalRubric && <window.UI.ApprovalRubric id={id} />}<Table rows={c.rows || []} columns={c.kind === 'qc' ? ['element', 'before', 'after', 'decision'] : ['element', 'before', 'after']} />
  {c.kind === 'qc' && <div className="grid" style={{
        padding: 16
      }}>{(c.rows || []).map((row, i) => <div className="spread" key={i}><span className="flex"><window.UI.Sheet mark />{row.element} · {row.decision || 'Needs review'}</span><div className="flex">{api.supportsAction?.('reviewProofRow') !== false && <Btn sm onClick={event => executeAction("sharedUI.AcceptRow.9", {
              api,
              i,
              id,
              u
            }, event)}>Accept row {i + 1}</Btn>}{api.supportsAction?.('reviewProofRow') !== false && <Btn sm onClick={event => executeAction("sharedUI.RejectRow.10", {
              api,
              i,
              id,
              u
            }, event)}>Reject row {i + 1}</Btn>}</div></div>)}</div>}
  {decisionError && <p role="alert">{decisionError}</p>}
  {(justApproved || c.status === 'approved') && <p role="status" data-design="approval.confirmed" style={{padding: '8px 18px 0', margin: 0, color: okCol, fontWeight: 600}}>Approved. Running now.</p>}
  {['executing','unconfirmed'].includes(c.status) ? <p role="alert">Host outcome is unconfirmed. Inspect the source before another edit; this request will not replay.</p> : s.nativeApproval && c.status === 'refused' ? <p role="alert">This review is closed. Request a fresh review before trying again.</p> : c.status === 'postponed' ? <div className="row spread"><span>Saved for later review.</span>{api.supportsAction?.('resumeApproval') !== false && <Btn p onClick={event => executeAction("sharedUI.ResumeReview.11", {
          api,
          id,
          u
        }, event)}>Resume review</Btn>}</div> : ['stale', 'refused', 'contested', 'superseded'].includes(c.status) ? <div className="row spread"><span>{c.status === 'contested' ? 'Another review was requested.' : c.status === 'superseded' ? 'A newer review is available.' : c.status === 'refused' ? 'The program is disconnected. Reconnect, then review again.' : 'The content changed after this review.'}</span>{api.supportsAction?.('refreshApproval') !== false && <Btn p onClick={event => executeAction("sharedUI.ReviewLatest.12", {
          api,
          id,
          u
        }, event)}>Review latest</Btn>}</div> : c.status === 'pending' ? <div className="flex" style={{
        padding: '14px 18px',
        background: '#16161b',
        flexWrap: 'wrap'
      }}><Btn p sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.ApproveOnce.13", {
          decide
        }, event)}>Approve once{A.rad ? <> <kbd style={{marginLeft: 4, fontSize: 10}}>Enter</kbd></> : null}</Btn>{!s.nativeApproval && api.supportsAction?.('approve', 'session') !== false && <Btn sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.ApproveSimilarThisSession.14", {
          decide
        }, event)}>Approve similar this session</Btn>}{api.supportsAction?.('decline') !== false && <Btn sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.Decline.15", {
          decide
        }, event)}>Decline</Btn>}{!s.nativeApproval && <>{api.supportsAction?.('postponeApproval') !== false && <Btn sm ghost onClick={event => executeAction("sharedUI.Postpone.16", {
            api,
            id,
            u
          }, event)}>Postpone</Btn>}<Btn sm ghost onClick={event => executeAction("sharedUI.WhyThisChange.17", {
            id,
            u
          }, event)}>Why this change?</Btn><span className="muted" style={{
            fontSize: 12
          }}>You can undo this</span><Btn sm ghost onClick={event => executeAction("sharedUI.NotSure.18", {
            u
          }, event)}>Not sure</Btn></>}</div> : <div className="spread row"><span style={{
          color: c.status === 'approved' ? okCol : inkSoftCol
        }}>{c.status === 'approved' ? s.nativeApproval ? 'Approval recorded' : c.kind === 'qc' ? 'Review recorded' : c.kind === 'memory' ? 'Memory updated' : c.kind === 'meeting-summary' ? 'Summary sent' : c.kind === 'community' ? 'Pattern shared' : 'Applied and checked' : 'Nothing changed'}</span>{c.status === 'approved' && !s.nativeApproval && c.approvalKind !== 'watcher' && <Btn sm onClick={event => executeAction("sharedUI.Undo.19", {
          api,
          u
        }, event)}>Undo</Btn>}</div>}
 </Card>;
  }
  function shortcutFromEvent(event) {
    if(event.isComposing || ['Control','Shift','Alt','Meta','Dead'].includes(event.key))return '';
    const key=event.key===' '?'Space':event.key.length===1?event.key.toUpperCase():event.key;
    return [(event.ctrlKey||event.metaKey)&&'Ctrl',event.shiftKey&&'Shift',event.altKey&&'Alt',key].filter(Boolean).join(' ');
  }
  function shortcutFor(id) {
    const commands=window.ArchHubCommandRegistry?.commands||[];
    const row=commands.find(row=>row.id===id),identity=row?.keyFrom||id;
    const defaults=commands.find(row=>row.id===identity)?.shortcut||'';
    const overrides=api.getSnapshot().keybindings||{};
    const chord=Object.hasOwn(overrides,identity)?overrides[identity]:defaults;
    return chord.split(' ').map(part=>({Del:'Delete',Esc:'Escape'}[part]||part)).join(' ');
  }
  function matchesShortcut(id,event) {
    return !api.getSnapshot().keyboardPending && !event.isComposing && !event.repeat && !!shortcutFor(id) && shortcutFor(id)===shortcutFromEvent(event);
  }
  // A row is changed here when this Settings scope holds its own value (scopeOwned, from the scope owner); a row
  // without scopes is changed when it differs from its default. Reset removes the own value to inherit the parent.
  const settingOverridden = row => typeof row.scopeOwned === 'boolean' ? row.scopeOwned : row.default !== undefined && JSON.stringify(row.value) !== JSON.stringify(row.default);
  // Account › Photo: the picture itself with Change (the account popover's crop dialog) and Reset, never its data text.
  function PhotoControl({value}) {
    const u = useApp(), profile = useData().profile || {}, input = React.useRef(null);
    const pick = file => {
      if (!file || !String(file.type || '').startsWith('image/')) return;
      const reader = new window.FileReader();
      reader.onload = () => u.show('Crop your photo', {src: String(reader.result || ''), prevPhoto: value});
      reader.readAsDataURL(file);
    };
    return <span className="photo-control" data-design="settings.photo">
      {value ? <img src={value} alt="Your photo" width={40} height={40} /> : <span className="photo-empty" aria-label="No photo">{profileInitials(profile)}</span>}
      <input ref={input} type="file" accept="image/*" hidden aria-label="Choose a photo" onChange={event => { pick(event.target.files?.[0]); event.target.value = ''; }} />
      <Btn sm onClick={event => executeAction('projects.controls.activate', {handler: () => input.current?.click()}, event)}>Change</Btn>
      {value && <Btn sm ghost aria-label="Reset Photo" onClick={event => executeAction('projects.controls.activate', {handler: () => u.saveProfileFields({photo: ''})}, event)}>Reset</Btn>}
    </span>;
  }
  function SettingControl({
    row,
    presentation, unit,
    raw = false
  }) {
    const u = useApp(), data = useData(), destination = data.settingsDestination;
    const disabled = (row.id.startsWith('Appearance.')||row.id.startsWith('Projects.')||row.id.startsWith('Agents.')||(row.id.startsWith('Account.') && row.storageKey)) && (!destination||data.settingsScopePending);
    const changed = settingOverridden(row);
    return <div className="setting-row" data-setting={row.id}><label htmlFor={'setting-' + row.id} style={{
        display: 'grid',
        gap: 3
      }}><span>{changed && <span className="changed">● </span>}{row.label}</span>{raw && <span className="muted" style={{
          fontSize: 11
        }}>{row.type} · parameter socket</span>}</label><div className="flex" style={{
        gap: 6,
        minWidth: 0
      }}>
  {raw && api.supportsAction?.('exposeSettingsPage') !== false && <D.Socket t={row.type === 'boolean' ? 'boolean' : row.type === 'number' ? 'number' : 'text'} hit role="button" tabIndex={0} aria-label={'Wire ' + row.label} onClick={event => executeAction("sharedUI.Control.20", {
          row,
          u
        }, event)} onKeyDown={e => {
          if (e.key === 'Enter') u.openSystem(row.page);
        }} />}
  {row.id === 'Account.Photo' ? <PhotoControl value={row.value} /> : presentation==='seg' && row.options ? <div className="sheet-segments" role="group" aria-label={row.label}>{row.options.map(option=><button type="button" key={option} aria-pressed={option===row.value} disabled={disabled||Boolean(row.disabledOptions?.[option])} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.setSetting(row.id,option,destination))},event)}>{productLabel(option,data.settings)}</button>)}</div> :
   presentation==='step' && row.type==='number' ? <span className="sheet-stepper">
     <button type="button" disabled={disabled||row.value<=row.min} aria-label={'Decrease '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.setSetting(row.id,Number(row.value)-1,destination))},event)}>−</button>
     <input id={'setting-'+row.id} aria-label={row.label} type="number" disabled={disabled} min={row.min} max={row.max} step="1" value={row.value} onChange={event=>{
       if(event.target.value!==''&&event.target.validity.valid){
         const value=event.target.valueAsNumber;
         u.act(()=>api.setSetting(row.id,value,destination));
       }
     }}/>
     <button type="button" disabled={disabled||row.value>=row.max} aria-label={'Increase '+row.label} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.setSetting(row.id,Number(row.value)+1,destination))},event)}>+</button>{unit&&<small>{unit}</small>}
   </span> :
   row.control === 'range' ? <><input id={'setting-' + row.id} aria-label={row.label} disabled={disabled} type="range" min={row.min} max={row.max} step="1" value={row.value} onChange={event => {
    const value = Number(event.target.value);
    return u.act(() => api.setSetting(row.id, value, destination));
  }}/><output htmlFor={'setting-' + row.id}>{row.value}</output></> : row.type === 'boolean' ? <D.Toggle disabled={disabled} variant="settings" label={row.label} checked={row.value} onCheckedChange={v => u.act(() => api.setSetting(row.id, v, destination))} /> : row.id === 'Appearance.Theme' && row.options ? (
    <div className="theme-swatches" role="group" aria-label={row.label}>
      {row.options.map(value => <button key={value} type="button" data-theme-option={value}
        aria-pressed={row.value === value} disabled={disabled || Boolean(row.disabledOptions?.[value])}
        title={row.disabledOptions?.[value]} onClick={event => executeAction('projects.controls.activate', {handler: () => u.act(() => api.setSetting(row.id, value, destination))}, event)}>
        <i aria-hidden="true" /><span>{value}</span>
      </button>)}
    </div>
  ) : row.options ? <select disabled={disabled} id={'setting-' + row.id} aria-label={row.label} value={row.value} onChange={e => {const value=e.target.value;return u.act(() => api.setSetting(row.id, value, destination));}}>{row.options.map(v => <option key={v} value={v} disabled={Boolean(row.disabledOptions?.[v])} title={row.disabledOptions?.[v]}>{productLabel(v,data.settings)}</option>)}</select> : row.type === 'number' ? <span className="sheet-stepper"><button disabled={disabled} type="button" className="sheet-step" aria-label={'Decrease ' + row.label} onClick={event => executeAction('projects.controls.activate', {handler: () => u.act(() => api.setSetting(row.id, Number(row.value || 0) - 1, destination))}, event)}>−</button><input disabled={disabled} id={'setting-' + row.id} aria-label={row.label} type="number" value={row.value} onChange={e => {const value=Number(e.target.value);return u.act(() => api.setSetting(row.id, value, destination));}} /><button disabled={disabled} type="button" className="sheet-step" aria-label={'Increase ' + row.label} onClick={event => executeAction('projects.controls.activate', {handler: () => u.act(() => api.setSetting(row.id, Number(row.value || 0) + 1, destination))}, event)}>+</button></span> : <input disabled={disabled} id={'setting-' + row.id} aria-label={row.label} type={row.type === 'color' ? 'color' : 'text'} value={row.value} onChange={e => {const value=e.target.value;return u.act(() => api.setSetting(row.id, value, destination));}} />}
  {changed && row.id !== 'Account.Photo' && <button disabled={disabled} className="reset" aria-label={'Reset ' + row.label} onClick={event => executeAction("sharedUI.Reset.21", {
          api,
          row,
          u,
          destination
        }, event)}>Reset</button>}
 </div></div>;
  }
  // ADAPTIVE (founder: "why is the app static … why not dynamic?"): one text renderer for every long text
  // surface. A small markdown subset (paragraphs, lists, ``` code, `code`, **bold**) like Slack/Discord, wrapped
  // anywhere, collapsed to `lines` with Show more when it is longer.
  const inline = text => String(text).split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/).map((part, i) => part.startsWith('`') && part.endsWith('`') && part.length > 1 ? <code key={i}>{part.slice(1, -1)}</code> : part.startsWith('**') && part.endsWith('**') && part.length > 3 ? <b key={i}>{part.slice(2, -2)}</b> : part);
  const blocks = text => String(text || '').split(/```[^\n]*\n?/).flatMap((chunk, i) => i % 2 ? [<pre key={'c' + i}><code>{chunk.replace(/\n$/, '')}</code></pre>] :
    chunk.split(/\n\s*\n/).filter(p => p.trim()).map((para, j) => {
      const lines = para.split('\n');
      const list = lines.every(l => /^\s*([-*•]|\d+[.)])\s+/.test(l));
      return list ? <ul key={i + '-' + j}>{lines.map((l, k) => <li key={k}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ''))}</li>)}</ul> : <p key={i + '-' + j}>{lines.map((l, k) => <React.Fragment key={k}>{k > 0 && <br />}{inline(l)}</React.Fragment>)}</p>;
    }));
  function Prose({text, lines = 12}) {
    const [open, setOpen] = React.useState(false);
    // shortcut: "long" is estimated from line breaks and length (about 80 characters a line); measure if it misfires.
    const long = String(text || '').split('\n').length > lines || String(text || '').length > lines * 80;
    return <div className="prose-wrap"><div className={'prose' + (long && !open ? ' clamped' : '')} style={{'--prose-lines': lines}}>{blocks(text)}</div>{long && <button type="button" className="prose-more" aria-expanded={open} onClick={event => executeAction("sharedUI.Toggle.23", {toggle: () => setOpen(!open)}, event)}>{open ? 'Show less' : 'Show more'}</button>}</div>;
  }
  // A short label clamped to `lines`; the full text on hover and on click.
  function Clamp({text, lines = 2}) {
    const [open, setOpen] = React.useState(false);
    return <button type="button" className={'button-reset clamp' + (open ? ' open' : '')} style={{'--clamp-lines': lines}} title={text} aria-expanded={open} onClick={event => executeAction("sharedUI.Toggle.23", {toggle: () => setOpen(!open)}, event)}>{text}</button>;
  }
  function deliveryAttention(message) {
    const rows = Array.isArray(message.live) && message.live.length ? message.live : Array.isArray(message.delivery) ? message.delivery : [];
    const states = [message.state, ...rows.map(row => row.state || row.reason)].filter(Boolean).map(value => String(value).toLowerCase().replace(/_/g, ' '));
    const failed = states.find(state => /fail|error|denied|refused|not delivered|undelivered|timeout/.test(state));
    return failed || (states.some(state => /queue|pending/.test(state)) ? 'Queued' : '');
  }
  // The avatar letters come from the real name, else the account email; never from a placeholder.
  const profileInitials = profile => (profile.name ? profile.name.split(' ').filter(Boolean).map(n => n[0]).join('').slice(0, 2) : (profile.email || '').slice(0, 1)).toUpperCase();
  // A part the design shows that no engine or owner runs yet: drawn as designed, inert, with one "Coming soon" chip.
  // It never hides the part and never lets it act; one look everywhere (style.css .soon).
  // label is required: it names the held part for a screen reader, because the inert part itself is not read out.
  function Soon({children, block = false, label}) {
    if (!label) throw Error('UI.Soon needs a label naming the part it holds.');
    const SOON = 'Coming soon: not built yet';
    const Tag = block ? 'div' : 'span';
    return <Tag className="soon" data-soon="" data-block={block ? '' : undefined} role="group" aria-label={label + '. ' + SOON} aria-disabled="true" title={SOON}><Tag className="soon-part" ref={part => part?.setAttribute('inert', '')}>{children}</Tag><span className="soon-chip">Coming soon</span></Tag>;
  }
  const arabicLabels = {
    Home:'الرئيسية', Canvas:'لوحة العمل', Settings:'الإعدادات', Account:'الحساب', Projects:'المشروعات',
    Agents:'الوكلاء', Library:'المكتبة', Workshop:'الورشة', Community:'المجتمع', Docs:'المستندات', Help:'المساعدة',
    'This PC':'هذا الكمبيوتر', Connections:'الاتصالات', You:'أنت', Profile:'الملف الشخصي', Storage:'التخزين',
    'App language':'لغة التطبيق', 'Right-to-left layout':'تخطيط من اليمين إلى اليسار', 'Agents reply in':'لغة ردود الوكلاء',
    English:'الإنجليزية', Arabic:'العربية', Both:'كلتاهما', Auto:'تلقائي', Always:'دائمًا', Never:'أبدًا',
    Copy:'نسخ', Paste:'لصق', Cut:'قص', Delete:'حذف', Archive:'أرشفة', Rename:'إعادة تسمية',
    Duplicate:'تكرار', Group:'تجميع', Ungroup:'فك التجميع', Undo:'تراجع', Redo:'إعادة', Select:'تحديد',
    'Select all':'تحديد الكل', 'Fit to view':'ملاءمة العرض', 'Open in Canvas':'فتح في لوحة العمل',
    'New task':'مهمة جديدة', 'New session':'جلسة جديدة', 'Search settings':'البحث في الإعدادات',
    'Search, or ask where something is':'ابحث أو اسأل عن مكان أحد الإعدادات', 'All projects':'كل المشروعات',
    'Changed settings':'الإعدادات المعدّلة', 'Reset':'إعادة التعيين', 'Save':'حفظ', 'Cancel':'إلغاء',
    'Menus and labels':'القوائم والتسميات', 'Every agent, every thread':'كل وكيل في كل محادثة',
    'Auto turns it on with Arabic':'يُفعَّل تلقائيًا عند اختيار العربية'
  };
  function productLabel(label, settings) {
    if (!settings?.some(row => row.id === 'Account.App language' && row.value === 'Arabic')) return label;
    return Object.hasOwn(arabicLabels, label) ? arabicLabels[label] : label;
  }
  window.UI = {
    productLabel,
    shortcutFor, shortcutFromEvent, matchesShortcut,
    Soon,
    useAskBaboom,
    profileInitials,
    deliveryAttention,
    taskRowReason,
    api,
    Prose,
    Clamp,
    A,
    D,
    Ctx,
    useApp,
    useData,
    Btn,
    Card,
    Chip,
    Av,
    AvatarMenu,
    Heading,
    Empty,
    Table,
    Composer,
    ApprovalCard,
    SettingControl,
    PhotoControl,
    settingOverridden
  };
})();

// WIRE-social: request state for the owned surfaces; data stays with ArchHubAPI.
(() => {
  function useWireSocial() {
    const data = window.UI.useData();
    const [request, setRequest] = React.useState({
      status: 'waiting',
      message: '',
      result: null
    });
    const last = React.useRef(null),
      mounted = React.useRef(true),
      generation = React.useRef(0);
    React.useEffect(() => {
      mounted.current = true;
      return () => {
        mounted.current = false;
        generation.current++;
      };
    }, []);
    const call = async callback => {
      const result = await callback();
      if (result?.ok === false) throw Error(result.message || result.error || result.reason || 'The owner refused this action. Review its settings and retry.');
      if (mounted.current && result !== undefined) setRequest(previous => ({
        ...previous,
        result
      }));
      return result;
    };
    const act = async callback => {
      const own = ++generation.current;
      last.current = callback;
      setRequest(previous => ({
        ...previous,
        status: 'waiting',
        message: ''
      }));
      return call(callback).then(result => {
        if (mounted.current && own === generation.current) setRequest(previous => ({
          ...previous,
          status: result?.social && !result.social.drafts.length && !result.social.inbox.length && !result.presentation.slides.length ? 'empty' : 'loaded'
        }));
        return result;
      }, failure => {
        if (mounted.current && own === generation.current) setRequest(previous => ({
          ...previous,
          status: 'error',
          message: failure.message || 'Check the source and connection, then retry.'
        }));
        return null;
      });
    };
    React.useEffect(() => {
      act(async () => {
        await window.ArchHubAPI.ready;
        return window.ArchHubAPI.refreshSocialState();
      });
    }, [data.graph.id]);
    return {
      ...request,
      act,
      call,
      retry: () => last.current && act(last.current)
    };
  }
  window.UI.useWireSocial = useWireSocial;
})();
// WIRE-social end
// WIRE-settings
(() => {
  function executeAction(...args) {
    return window.executeAction(...args);
  }
  function useRegisteredActions(actions, handlers) {
    const [actionState, setActionState] = React.useState({
      status: 'empty'
    });
    const last = React.useRef(null);
    const pending = React.useRef(false);
    const runAction = (id, ...args) => {
      const handler = handlers[actions[id]];
      if (typeof handler !== 'function') throw Error('Unknown settings action: ' + id);
      if (pending.current) return Promise.resolve(null);
      last.current = {
        id,
        args
      };
      pending.current = true;
      setActionState({
        status: 'waiting'
      });
      return Promise.resolve().then(() => handler(...args)).then(result => {
        if (result?.ok === false) throw Error(result.error || result.message || 'The owner refused this action.');
        if (result === null) throw Error('The action did not complete. Review the app message and retry.');
        setActionState({
          status: 'loaded',
          message: result?.message || ''
        });
        return result;
      }).catch(error => {
        setActionState({
          status: 'error',
          message: error.message || 'Could not complete this action.'
        });
        return null;
      }).finally(() => {
        pending.current = false;
      });
    };
    return {
      runAction,
      actionState,
      retryAction: () => last.current && runAction(last.current.id, ...last.current.args)
    };
  }
  function RegisteredActionStatus({
    state,
    retry
  }) {
    return state.status === 'waiting' ? <p role="status">Waiting for confirmation…</p> : state.status === 'error' ? <div role="alert"><p>{state.message}</p><button onClick={event => executeAction("sharedUI.Retry.22", {
        retry
      }, event)}>Retry</button></div> : state.status === 'loaded' ? <p role="status">{state.message || 'Action completed'}</p> : state.status === 'empty' ? null : null;
  }
  const WIRE_STATUS_ACTIONS = {
    'settings.retry': 'retry'
  };
  Object.assign(window.UI, {
    useRegisteredActions,
    RegisteredActionStatus,
    settingsStatusActions: WIRE_STATUS_ACTIONS
  });
})();
// WIRE-settings end
(() => {
  function sharedUIComposerScope1({
    contextOpen,
    setContextOpen
  }, event) {
    const handler = () => setContextOpen(!contextOpen);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIMentionContext2({
    contextOpen,
    setContextOpen
  }, event) {
    const handler = () => setContextOpen(!contextOpen);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIControl3({
    api,
    r,
    setContextOpen,
    u
  }, event) {
    const handler = () => {
      u.act(() => api.addComposerAttachment(r.id));
      setContextOpen(false);
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIControl4({
    api,
    id,
    u
  }, event) {
    const handler = () => u.act(() => api.removeComposerAttachment(id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIAddContext5({
    u
  }, event) {
    const handler = u.pickFile;
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUICommands6({
    u
  }, event) {
    const handler = () => u.show('Search');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIControl7({
    api,
    tool,
    u
  }, event) {
    const handler = async () => {
      await u.act(() => api.setWatcherOptions({
        activeTool: tool
      }));
      u.go('watcher');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUITalkF28({
    setText,
    u
  }, event) {
    const handler = () => u.voice(setText);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIAcceptRow9({
    api,
    i,
    id,
    u
  }, event) {
    const handler = () => u.act(() => api.reviewProofRow(id, i, 'Accept'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIRejectRow10({
    api,
    i,
    id,
    u
  }, event) {
    const handler = () => u.act(() => api.reviewProofRow(id, i, 'Reject'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIResumeReview11({
    api,
    id,
    u
  }, event) {
    const handler = () => u.act(() => api.resumeApproval(id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIReviewLatest12({
    api,
    id,
    u
  }, event) {
    const handler = async () => {
      const next = await u.act(() => api.refreshApproval(id));
      if (next) u.show('Approve', {
        id: next.id
      });
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIApproveOnce13({
    decide
  }, event) {
    const handler = () => decide('once');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIApproveSimilarThisSession14({
    decide
  }, event) {
    const handler = () => decide('session');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIDecline15({
    decide
  }, event) {
    const handler = () => decide('decline');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIPostpone16({
    api,
    id,
    u
  }, event) {
    const handler = () => u.act(() => api.postponeApproval(id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIWhyThisChange17({
    id,
    u
  }, event) {
    const handler = () => u.show('Action evidence', {
      id
    });
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUINotSure18({
    u
  }, event) {
    const handler = () => u.show('Not sure', {
      text: 'The linked model or required evidence is missing. Keep the action pending until it is available.'
    });
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIUndo19({
    api,
    u
  }, event) {
    const handler = () => u.act(api.undo);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIControl20({
    row,
    u
  }, event) {
    const handler = () => u.openSystem(row.page);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIReset21({
    api,
    row,
    u,
    destination
  }, event) {
    const handler = () => u.act(() => api.resetSetting(row.id, destination));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function sharedUIRetry22({
    retry
  }, event) {
    const handler = retry;
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  const sharedUIActions = {
    "sharedUI.Send": "sharedUISend",
    "sharedUI.ComposerScope.1": "sharedUIComposerScope1",
    "sharedUI.MentionContext.2": "sharedUIMentionContext2",
    "sharedUI.Control.3": "sharedUIControl3",
    "sharedUI.Control.4": "sharedUIControl4",
    "sharedUI.AddContext.5": "sharedUIAddContext5",
    "sharedUI.Commands.6": "sharedUICommands6",
    "sharedUI.Control.7": "sharedUIControl7",
    "sharedUI.TalkF2.8": "sharedUITalkF28",
    "sharedUI.AcceptRow.9": "sharedUIAcceptRow9",
    "sharedUI.RejectRow.10": "sharedUIRejectRow10",
    "sharedUI.ResumeReview.11": "sharedUIResumeReview11",
    "sharedUI.ReviewLatest.12": "sharedUIReviewLatest12",
    "sharedUI.ApproveOnce.13": "sharedUIApproveOnce13",
    "sharedUI.ApproveSimilarThisSession.14": "sharedUIApproveSimilarThisSession14",
    "sharedUI.Decline.15": "sharedUIDecline15",
    "sharedUI.Postpone.16": "sharedUIPostpone16",
    "sharedUI.WhyThisChange.17": "sharedUIWhyThisChange17",
    "sharedUI.NotSure.18": "sharedUINotSure18",
    "sharedUI.Undo.19": "sharedUIUndo19",
    "sharedUI.Control.20": "sharedUIControl20",
    "sharedUI.Reset.21": "sharedUIReset21",
    "sharedUI.Retry.22": "sharedUIRetry22",
    "sharedUI.Toggle.23": "sharedUIToggle23",
    "sharedUI.AvatarToggle": "sharedUIAvatarToggle",
    "sharedUI.AvGoNode": "sharedUIAvGoNode",
    "sharedUI.AvOpenThread": "sharedUIAvOpenThread",
    "sharedUI.AvMessage": "sharedUIAvMessage",
    "sharedUI.AvSubToggle": "sharedUIAvSubToggle",
    "sharedUI.AvAssignTask": "sharedUIAvAssignTask",
    "sharedUI.AvOpenWork": "sharedUIAvOpenWork",
    "sharedUI.AvSwitchModel": "sharedUIAvSwitchModel",
    "sharedUI.AvStop": "sharedUIAvStop",
    "sharedUI.PersonMention": "sharedUIPersonMention",
    "sharedUI.PersonSelection": "sharedUIPersonSelection",
    "sharedUI.ApprovalAskWhy": "sharedUIApprovalAskWhy"
  };
  const focusComposerWith = (u, mention) => {
    const target = u.task || '';
    const key = JSON.stringify([u.route || 'home', target]);
    u.setComposerDraft?.(current => {
      const prev = current[key]?.text || '';
      const prefix = prev && !prev.endsWith(' ') ? prev + ' ' : prev;
      return {...current, [key]: {text: prefix + mention + ' ', revision: (current[key]?.revision || 0) + 1}};
    });
    window.requestAnimationFrame?.(() => document.querySelector('[data-design="composer.msg"]')?.focus?.());
  };
  window.registerActions(sharedUIActions, {
    sharedUISend: ({send}) => send(),
    sharedUIComposerScope1,
    sharedUIMentionContext2,
    sharedUIControl3,
    sharedUIControl4,
    sharedUIAddContext5,
    sharedUICommands6,
    sharedUIControl7,
    sharedUITalkF28,
    sharedUIAcceptRow9,
    sharedUIRejectRow10,
    sharedUIResumeReview11,
    sharedUIReviewLatest12,
    sharedUIApproveOnce13,
    sharedUIApproveSimilarThisSession14,
    sharedUIDecline15,
    sharedUIPostpone16,
    sharedUIWhyThisChange17,
    sharedUINotSure18,
    sharedUIUndo19,
    sharedUIControl20,
    sharedUIReset21,
    sharedUIRetry22,
    sharedUIToggle23: ({toggle}) => toggle(),
    sharedUIAvatarToggle: ({open, setOpen}) => setOpen(!open),
    sharedUIAvGoNode: ({nodeMatch, onClose, rawName, u, workTasks}) => {
      onClose?.();
      if (nodeMatch) {
        u.setSelectedNodeId?.(nodeMatch.id);
        u.go?.('canvas');
        return;
      }
      if (workTasks?.[0]) {
        void u.openTaskFile?.(workTasks[0].id);
        return;
      }
      u.setToast?.({text: rawName + ' has no node on this canvas yet.'});
    },
    sharedUIAvOpenThread: ({onClose, u, workTasks}) => {
      onClose?.();
      if (workTasks?.[0]) return u.openTaskFile?.(workTasks[0].id, 'split');
      return u.go?.('workshop');
    },
    sharedUIAvMessage: ({handle, onClose, u}) => {
      onClose?.();
      focusComposerWith(u, '@' + handle);
    },
    sharedUIAvSubToggle: ({key, setSub, sub}) => setSub(sub === key ? '' : key),
    sharedUIAvAssignTask: ({api, handle, id, onClose, rawName, t, u}) => {
      onClose?.();
      return u.act?.(async () => {
        const res = typeof api.setTaskDelegate === 'function' ? await api.setTaskDelegate(t.id, id) : typeof api.setTaskSession === 'function' ? await api.setTaskSession(t.id, handle) : {ok: true};
        u.setToast?.({text: 'Assigned ' + rawName + ' to ' + t.title + '.'});
        return res;
      });
    },
    sharedUIAvOpenWork: ({onClose, t, u}) => {
      onClose?.();
      return u.openTaskFile?.(t.id);
    },
    sharedUIAvSwitchModel: ({api, id, mdl, onClose, rawName, u}) => {
      onClose?.();
      return u.act?.(async () => {
        const res = typeof api.setProviderModel === 'function' ? await api.setProviderModel(id, mdl) : {ok: true};
        u.setToast?.({text: 'Switched ' + rawName + ' to ' + mdl + '.'});
        return res;
      });
    },
    sharedUIAvStop: ({api, id, onClose, rawName, u}) => {
      onClose?.();
      return u.act?.(async () => {
        const res = typeof api.stopAgentSession === 'function' ? await api.stopAgentSession(id) : typeof api.stopEverything === 'function' ? await api.stopEverything() : {ok: true};
        u.setToast?.({text: 'Stopped ' + rawName + '.'});
        return res;
      });
    },
    sharedUIPersonMention: ({handle, onClose, rawName, u}) => {
      onClose?.();
      focusComposerWith(u, '@' + (handle || rawName));
    },
    sharedUIPersonSelection: ({onClose, rawName, targetNode, u}) => {
      onClose?.();
      if (targetNode) {
        u.setSelectedNodeId?.(targetNode);
        u.go?.('canvas');
        return;
      }
      u.setToast?.({text: rawName + ' has nothing selected on this canvas.'});
    },
    sharedUIApprovalAskWhy: ({c, u}) => {
      const target = c.taskId || c.work || u.task;
      if (target && u.openTaskFile) {
        const key = JSON.stringify(['task-file', target]);
        u.setComposerDraft?.(current => ({...current, [key]: {text: 'Why does ' + c.title + ' need approval?', revision: (current[key]?.revision || 0) + 1}}));
        u.close?.();
        return u.openTaskFile(target, 'split');
      }
      return u.show?.('Ask why');
    }
  });
})();
