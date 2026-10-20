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
  const useData = () => React.useSyncExternalStore(api.subscribe, api.getSnapshot, api.getSnapshot);
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
    'Open Templates': 'home',
    'Open receipts': 'docs',
    'Settings': 'settings',
    '×': 'close',
    'Check': 'check',
    'Check all': 'check',
    'Retry': 'refresh',
    'Rerun': 'refresh',
    'Fork': 'canvas',
    'Open graph': 'canvas'
  };
  const Btn = ({
    p,
    sm,
    ghost,
    danger,
    children,
    ...props
  }) => {
    const label = typeof children === 'string' ? children : null;
    const icon = !p && label && actionIcons[label];
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
  const Av = ({
    id,
    size = 28
  }) => {
    const s = useData();
    const p = s.providers.find(p => p.id === id) || {
      name: id,
      ini: id?.slice(0, 2),
      col: A.userAv
    };
    return <D.Avatar agent={p} size={size} />;
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
  function Composer({
    taskId,
    placeholder = 'Ask for anything, or @ an agent…',
    compact = false,
    onSent
  }) {
    const s = useData(),
      u = useApp();
    const [text, setText] = React.useState(''),
      [provider, setProvider] = React.useState(''),
      [sending, setSending] = React.useState(false),
      [contextOpen, setContextOpen] = React.useState(false);
    const pending = React.useRef(false);
    const send = async () => {
      if (pending.current || !text.trim()) return;
      pending.current = true;
      setSending(true);
      try {
        const t = await u.act(() => api.sendToBaboom(text, {
          taskId,
          scope: u.selectedNodeId || s.graph.id,
          provider
        }));
        if (t) {
          setText('');
          u.setTask(t.id);
          onSent?.(t);
          if (!taskId && !onSent) u.go('workshop');
        }
      } finally {
        pending.current = false;
        setSending(false);
      }
    };
    return <D.Composer variant="home" as="form" onSubmit={e => {
      e.preventDefault();
      executeAction("sharedUI.Send", {send}, e);
    }} style={{
      width: '100%',
      padding: compact ? '10px 12px' : '14px 16px'
    }}>
  <div className="spread composer-scope" style={{
        fontSize: 11,
        marginBottom: 8
      }}><button type="button" className="tab-button" aria-label="Composer scope" onClick={event => executeAction("sharedUI.ComposerScope.1", {
          contextOpen,
          setContextOpen
        }, event)}><window.AHIcon name="canvas" size={12} /> {u.selectedNodeId ? api.contextLabel(u.selectedNodeId) : s.graph.name}</button><button type="button" className="icon-button" aria-label="Mention context" title="Add nodes, graphs, agents or sessions" onClick={event => executeAction("sharedUI.MentionContext.2", {
          contextOpen,
          setContextOpen
        }, event)}>＠</button></div>{contextOpen && <div className="composer-mentions" role="region" aria-label="Context choices">{[['Nodes', s.graph.nodes], ['Graphs', s.graphs], ['Agents', s.providers], ['Sessions', s.tasks]].map(([label, rows]) => <details key={label}><summary>{label}</summary>{rows.slice(0, 20).map(r => <button type="button" key={r.id} onClick={event => executeAction("sharedUI.Control.3", {
            api,
            r,
            setContextOpen,
            u
          }, event)}>{r.title || r.name}</button>)}</details>)}</div>}{s.composerAttachments.length > 0 && <div className="composer-context">{s.composerAttachments.map(id => <button type="button" key={id} onClick={event => executeAction("sharedUI.Control.4", {
          api,
          id,
          u
        }, event)}>{api.contextLabel(id)} ×</button>)}</div>}<textarea className="composer-input" rows={compact ? 2 : 2} aria-label="Message" placeholder={placeholder} value={text} onChange={e => {
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
        }, event)}><window.AHIcon name={icon} size={15} /></button>)}<select aria-label="Agent picker" value={provider} onChange={e => setProvider(e.target.value)} style={{
          fontSize: 12
        }}><option value="">BABOOM chooses · free first</option>{s.providers.filter(p => p.enabled && p.signedIn).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><span className="fill" /><Btn sm onClick={event => executeAction("sharedUI.TalkF2.8", {
          setText,
          u
        }, event)} title="Talk · F2">🎙 Talk</Btn><Btn p sm type="submit" aria-label="Send ↵" title="Send · Enter" disabled={sending || !text.trim()}><window.AHIcon name="send" size={15} /></Btn></div>
 </D.Composer>;
  }
  function ApprovalCard({
    id,
    compact = false
  }) {
    const s = useData(),
      u = useApp(),
      c = s.approvals.find(c => c.id === id);
    const [busy, setBusy] = React.useState(false),
      [decisionError, setDecisionError] = React.useState('');
    if (!c) return <Empty>No action is waiting for approval.</Empty>;
    const decide = async mode => {
      setBusy(true);
      setDecisionError('');
      try {
        const result = await u.act(() => mode === 'decline' ? api.decline(id) : api.approve(id, mode));
        if (result?.ok === false) setDecisionError(result.message);
      } catch (error) {
        setDecisionError(error.message || 'Approval was refused');
      } finally {
        setBusy(false);
      }
    };
    return <Card data-approval={id} style={{
      border: '1px solid ' + (c.status === 'pending' ? A.warn : A.line),
      borderRadius: 14,
      boxShadow: c.status === 'pending' ? '0 0 0 3px ' + A.warn + '18,0 8px 28px #0007' : undefined
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
        }}>R</span><div className="fill"><h2>{c.title}</h2><p className="muted" style={{
            fontSize: 12
          }}>{s.nativeApproval ? c.summary || c.description || c.target || '' : <>{c.target || s.files.find(f => f.id === s.activeFile)?.name || 'Project model'} · {s.watcher.view} · one undo step</>}</p></div><Chip c={c.status === 'pending' ? A.warn : A.ok}>{c.status === 'pending' ? s.nativeApproval ? 'Needs your OK' : c.kind === 'social' || c.kind === 'email' ? 'Sends from your account' : c.kind === 'memory' ? 'Updates your Brain' : 'Writes to your model' : c.status}</Chip></div>
  {window.UI.ApprovalRubric && <window.UI.ApprovalRubric id={id} />}<Table rows={c.rows} columns={c.kind === 'qc' ? ['element', 'before', 'after', 'decision'] : ['element', 'before', 'after']} />
  {c.kind === 'qc' && <div className="grid" style={{
        padding: 16
      }}>{c.rows.map((row, i) => <div className="spread" key={i}><span className="flex"><window.UI.Sheet mark />{row.element} · {row.decision || 'Needs review'}</span><div className="flex"><Btn sm onClick={event => executeAction("sharedUI.AcceptRow.9", {
              api,
              i,
              id,
              u
            }, event)}>Accept row {i + 1}</Btn><Btn sm onClick={event => executeAction("sharedUI.RejectRow.10", {
              api,
              i,
              id,
              u
            }, event)}>Reject row {i + 1}</Btn></div></div>)}</div>}
  {decisionError && <p role="alert">{decisionError}</p>}
  {s.nativeApproval && c.status === 'refused' ? <p role="alert">This review is closed. Request a fresh review before trying again.</p> : c.status === 'postponed' ? <div className="row spread"><span>Saved for later review.</span><Btn p onClick={event => executeAction("sharedUI.ResumeReview.11", {
          api,
          id,
          u
        }, event)}>Resume review</Btn></div> : c.status === 'stale' || c.status === 'refused' ? <div className="row spread"><span>{c.status === 'refused' ? 'The program is disconnected. Reconnect, then review again.' : 'The content changed after this review.'}</span><Btn p onClick={event => executeAction("sharedUI.ReviewLatest.12", {
          api,
          id,
          u
        }, event)}>Review latest</Btn></div> : c.status === 'pending' ? <div className="flex" style={{
        padding: '14px 18px',
        background: '#16161b',
        flexWrap: 'wrap'
      }}><Btn p sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.ApproveOnce.13", {
          decide
        }, event)}>Approve once</Btn>{!s.nativeApproval && <Btn sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.ApproveSimilarThisSession.14", {
          decide
        }, event)}>Approve similar this session</Btn>}<Btn sm={compact} disabled={busy} onClick={event => executeAction("sharedUI.Decline.15", {
          decide
        }, event)}>Decline</Btn>{!s.nativeApproval && <><Btn sm ghost onClick={event => executeAction("sharedUI.Postpone.16", {
            api,
            id,
            u
          }, event)}>Postpone</Btn><Btn sm ghost onClick={event => executeAction("sharedUI.WhyThisChange.17", {
            id,
            u
          }, event)}>Why this change?</Btn><span className="muted" style={{
            fontSize: 12
          }}>You can undo this</span><Btn sm ghost onClick={event => executeAction("sharedUI.NotSure.18", {
            u
          }, event)}>Not sure</Btn></>}</div> : <div className="spread row"><span style={{
          color: c.status === 'approved' ? A.ok : A.inkSoft
        }}>{c.status === 'approved' ? s.nativeApproval ? 'Approval recorded' : c.kind === 'qc' ? 'Review recorded' : c.kind === 'memory' ? 'Memory updated' : c.kind === 'meeting-summary' ? 'Summary sent' : c.kind === 'community' ? 'Pattern shared' : 'Applied and checked' : 'Nothing changed'}</span>{c.status === 'approved' && !s.nativeApproval && <Btn sm onClick={event => executeAction("sharedUI.Undo.19", {
          api,
          u
        }, event)}>Undo</Btn>}</div>}
 </Card>;
  }
  function SettingControl({
    row,
    raw = false
  }) {
    const u = useApp();
    const changed = row.default !== undefined && JSON.stringify(row.value) !== JSON.stringify(row.default);
    return <div className="setting-row" data-setting={row.id}><label htmlFor={'setting-' + row.id} style={{
        display: 'grid',
        gap: 3
      }}><span>{changed && <span className="changed">● </span>}{row.label}</span>{raw && <span className="muted" style={{
          fontSize: 10
        }}>{row.type} · parameter socket</span>}</label><div className="flex" style={{
        gap: 6,
        minWidth: 0
      }}>
  <D.Socket t={row.type === 'boolean' ? 'boolean' : row.type === 'number' ? 'number' : 'text'} hit role="button" tabIndex={0} aria-label={'Wire ' + row.label} onClick={event => executeAction("sharedUI.Control.20", {
          row,
          u
        }, event)} onKeyDown={e => {
          if (e.key === 'Enter') u.openSystem(row.page);
        }} />
  {row.type === 'boolean' ? <D.Toggle variant="settings" label={row.label} checked={row.value} onCheckedChange={v => u.act(() => api.setSetting(row.id, v))} /> : row.options ? <select id={'setting-' + row.id} aria-label={row.label} value={row.value} onChange={e => u.act(() => api.setSetting(row.id, e.target.value))}>{row.options.map(v => <option key={v}>{v}</option>)}</select> : <input id={'setting-' + row.id} aria-label={row.label} type={row.type === 'number' ? 'number' : row.type === 'color' ? 'color' : 'text'} min={0} value={row.value} onChange={e => u.act(() => api.setSetting(row.id, row.type === 'number' ? Number(e.target.value) : e.target.value))} />}
  {changed && <button className="reset" aria-label={'Reset ' + row.label} onClick={event => executeAction("sharedUI.Reset.21", {
          api,
          row,
          u
        }, event)}>Reset</button>}
 </div></div>;
  }
  window.UI = {
    api,
    A,
    D,
    Ctx,
    useApp,
    useData,
    Btn,
    Card,
    Chip,
    Av,
    Heading,
    Empty,
    Table,
    Composer,
    ApprovalCard,
    SettingControl
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
    u
  }, event) {
    const handler = () => u.act(() => api.resetSetting(row.id));
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
    "sharedUI.Retry.22": "sharedUIRetry22"
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
    sharedUIRetry22
  });
})();
