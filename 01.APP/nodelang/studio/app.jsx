(() => {
  function executeAction(...args) {
    return window.executeAction(...args);
  }
  const {
    A,
    D,
    api,
    Ctx,
    useData,
    Btn,
    Card,
    Chip,
    Empty,
    Table
  } = window.UI;
  const routeNames = window.ArchHubRouteNames;
  const modalActions = {'Talk':'startVoiceInput','Timesheet':'settleTimesheet','Import skill':'importHostSkill','Contest decision':'contestDecision','Add comment':'addComment','Change plan':'changePlan','Connector bundle':'inspectConnectorBundle','Notifications':'readNotification'};
  function App() {
    const s = useData();
    const [route, setRoute] = React.useState('home'),
      [canvasOpened, setCanvasOpened] = React.useState(false),
      [task, setTask] = React.useState(''),
      [composerDraft, setComposerDraft] = React.useState({}),
      [modal, setModal] = React.useState(null),
      [toast, setToast] = React.useState(''),
      [advanced, setAdvanced] = React.useState(false),
      [companion, setCompanion] = React.useState(false),
      [libraryOpen, setLibraryOpen] = React.useState(false),
      [selectedNodeId, setSelectedNodeId] = React.useState(null);
    const [agentLoad, setAgentLoad] = React.useState({status: 'empty'});
    const agentLoadGeneration = React.useRef(0);
    const reloadWorkshop = async () => {
      const generation = ++agentLoadGeneration.current;
      setAgentLoad({status: 'waiting'});
      try {
        const result = await api.refreshAgentSurface();
        if (generation === agentLoadGeneration.current)
          setAgentLoad({status: result === null ? 'empty' : 'loaded'});
      } catch (error) {
        if (generation === agentLoadGeneration.current)
          setAgentLoad({status: 'error', message: error.message || 'Workshop settings could not be read.'});
      }
    };
    const talkTimer = React.useRef(),
      flowInput = React.useRef(),
      fileInput = React.useRef(),
      priorFocus = React.useRef(null),
      menuAnchor = React.useRef({
        x: 100,
        y: 58
      });
    React.useEffect(() => {
      const point = e => {
        menuAnchor.current = {
          x: e.clientX,
          y: e.clientY
        };
      };
      window.addEventListener('pointerdown', point, true);
      window.addEventListener('contextmenu', point, true);
      return () => {
        window.removeEventListener('pointerdown', point, true);
        window.removeEventListener('contextmenu', point, true);
      };
    }, []);
    // WIRE-agents: hydrate domain parameters after the existing graph owner loads.
    React.useEffect(() => {
      if (!s.graph.id) {
        setAgentLoad({status: 'empty'});
        return;
      }
      void reloadWorkshop();
      return () => {
        agentLoadGeneration.current++;
      };
    }, [s.graph.id, s.profile.id]);
    React.useEffect(()=>{
      if(!s.graph.id||typeof api.readHostAvailability!=='function')return;
      let active=true;
      api.readHostAvailability().catch(error=>{if(active)setToast(error.message);});
      return()=>{active=false;};
    },[s.graph.id,s.profile.id]);
    // WIRE-agents end.
    const theme = s.settings.find(r => r.id === 'Appearance.Theme')?.value || 'Dark',
      accent = s.settings.find(r => r.id === 'Appearance.Accent colour')?.value || '#d97757';
    const originalColours = React.useRef({
      accent: A.accent,
      accentHi: A.accentHi,
      accentPress: A.accentPress
    });
    if (accent === '#d97757') Object.assign(A, originalColours.current);else {
      A.accent = accent;
      A.accentHi = accent;
      A.accentPress = accent;
    }
    React.useEffect(() => {
      document.documentElement.dataset.theme = theme;
      document.documentElement.dataset.contrast = String(s.settings.find(r => r.id === 'Appearance.High contrast')?.value);
      document.documentElement.style.setProperty('--text-scale', (s.settings.find(r => r.id === 'Appearance.Text scale')?.value || 100) / 100);
      document.documentElement.dataset.grid = String(s.settings.find(r => r.id === 'Appearance.Canvas grid')?.value !== false);
    }, [theme, s.revision]);
    React.useEffect(() => {
      const notice = event => setToast(event.detail.message);
      window.addEventListener("archhub:notice", notice);
      return () => window.removeEventListener("archhub:notice", notice);
    }, []);
    const go = r => {
      if (r === 'system') r = 'settings/System graph';
      if (r === 'baboom') {
        setCompanion(true);
        setModal(null);
        return;
      }
      if (r === 'library' || r === 'skills') {
        r = 'canvas';
        setLibraryOpen(true);
      }
      if(r==='canvas')setCanvasOpened(true);
      api.setActiveSurface?.(r);
      setRoute(r);
      setModal(null);
    };
    const show = (kind, data = {}) => {
      if (modalActions[kind] && !api.supportsAction(modalActions[kind])) return;
      priorFocus.current = document.activeElement;
      setModal({
        kind,
        anchor: menuAnchor.current,
        ...data
      });
    };
    const close = () => {
      setModal(null);
      priorFocus.current?.focus?.();
    };
    const act = async fn => {
      try {
        const result = await fn();
        if (result?.ok === false) {
          setToast(result.message || result.error || 'Could not complete that action. Retry.');
          return null;
        }
        if (result?.uiCommand === 'voice') voice(text => api.setNodeParam(result.nodeId, 'transcript', text));else if (result?.uiCommand === 'desktop') await api.windowAction('hide');else if (result?.uiCommand === 'access') go('access');else if (result?.uiCommand === 'meetings') go('meetings');else if (result?.uiCommand === 'speak') {
          const spoken = await api.speak(result.text);
          if (!spoken.ok) setToast(result.text);
        }
        return result;
      } catch (e) {
        setToast(e.message || 'Could not complete that action. Retry.');
        return null;
      }
    };
    const confirm = (title, run) => show('Confirm', {
      title,
      run
    });
    const schedule = id => show('Schedule', {
      id
    });
    const timing = key => {
      const value = s.runtimeParameters?.[key];
      return Number.isSafeInteger(value) && value > 0 ? value : null;
    };
    const download = async (name, nodeId) => {
      const duration = timing('export_release_ms');
      if (duration === null) { setToast('Reload System graph settings, then retry export.'); return; }
      const data = await act(() => api.exportData(name, nodeId));
      if (!data) return;
      const url = URL.createObjectURL(new Blob([data.content], {
        type: data.type
      }));
      const a = document.createElement('a');
      a.href = url;
      a.download = data.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), duration);
      setToast('Export saved');
    };
    const voice = onText => {
      show('Talk', {
        onText
      });
    };
    const trace = async (id, direction) => {
      const rows = await act(() => api.traceNode(id, direction));
      if (rows) show(direction === 'back' ? 'Trace back' : 'Trace forward', {
        rows
      });
    };
    const openSystem = async page => {
      const n = await act(() => api.exposeSettingsPage(page));
      if (n) go('canvas');
    };
    const pickWorkspace = async () => {
      const result = await api.addWorkspace();
      setToast(result.message);
      return result;
    };
    const pickFlow = () => flowInput.current?.click();
    const pickFile = () => act(async () => { const file = await api.addFile(); if (file) return api.addComposerAttachment(file.id); return null; });
    const value = {
      selectedNodeId,
      setSelectedNodeId,
      composerDraft,
      setComposerDraft,
      companion,
      setCompanion,
      libraryOpen,
      setLibraryOpen,
      route,
      task,
      setTask,
      go,
      show,
      close,
      act,
      confirm,
      schedule,
      download,
      voice,
      trace,
      advanced,
      setAdvanced,
      openSystem,
      pickWorkspace,
      pickFlow,
      pickFile,
      setToast
    };
    React.useEffect(() => {
      const duration = timing('toast_visible_ms');
      if (!toast || duration === null) return;
      const t = setTimeout(() => setToast(''), duration);
      return () => clearTimeout(t);
    }, [toast, s.runtimeParameters?.toast_visible_ms]);
    React.useEffect(() => {
      const key = e => {
        if (e.ctrlKey && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          show('Search');
        }
        if (e.ctrlKey && e.shiftKey && e.key === '>') {
          e.preventDefault();
          act(api.stopEverything);
        }
        if (e.key === 'F2' && api.supportsAction('startVoiceInput')) {
          e.preventDefault();
          voice(text => show('Voice command', {
            text
          }));
        }
        if (e.code === 'Space' && api.supportsAction('startVoiceInput') && !e.repeat && !e.target.matches('input,textarea,select,button')) {
          e.preventDefault();
          const duration = timing('voice_hold_ms');
          if (duration === null) { setToast('Reload System graph settings, then retry voice input.'); return; }
          talkTimer.current = setTimeout(() => voice(text => show('Voice command', {
            text
          })), duration);
        }
        if (e.key === 'Escape') {
          if (modal) close();else if (companion) setCompanion(false);else if (route !== 'home') go('home');
        }
        if (e.key === '/' && !e.target.matches('input,textarea,select')) {
          e.preventDefault();
          show('Search');
        }
        if (e.ctrlKey && e.key.toLowerCase() === 'z' && !e.target.isContentEditable && e.target.contentEditable !== 'true' && !e.target.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]')) {
          e.preventDefault();
          act(e.shiftKey ? api.redo : api.undo);
        }
      };
      const up = e => {
        if (e.code === 'Space') clearTimeout(talkTimer.current);
      };
      window.addEventListener('keydown', key);
      window.addEventListener('keyup', up);
      return () => {
        window.removeEventListener('keydown', key);
        window.removeEventListener('keyup', up);
        clearTimeout(talkTimer.current);
      };
    }, [modal, companion, route]);
    React.useEffect(() => {
      document.title = 'ArchHub · ' + (routeNames[route] || route.split('/').at(-1));
    }, [route]);
    const rail = [['home', 'Home', 'home'], ['workshop', 'Workshop', 'workshop'], ['canvas', 'Canvas', 'canvas'], ['docs', 'Docs', 'docs']];
    const screen = route === 'meetings' ? <window.UI.Meetings /> : route === 'dependencies' ? <window.UI.Dependencies /> : route === 'present' ? <window.UI.Present /> : route === 'community' ? <window.UI.Community /> : route === 'model-review' ? <window.UI.ModelReview /> : route === 'interface' ? <window.UI.InterfaceStudio /> : route === 'social' ? <window.UI.Social /> : route === 'xray' ? <window.UI.Xray /> : route === 'access' ? <window.UI.Access /> : route === 'routing' ? <window.UI.Routing /> : route === 'home' ? <window.UI.Home /> : route === 'workshop' ? <window.UI.Workshop /> : route === 'canvas' ? null : route === 'system' ? <window.UI.Settings page="System graph" /> : route === 'colleagues' ? <window.UI.Colleagues /> : route === 'brain' ? <window.UI.Brain /> : route === 'watcher' ? <window.UI.Watcher /> : route === 'first-run' ? <window.UI.FirstRun /> : route === 'runs' ? <window.UI.Runs /> : route === 'receipts' ? <window.UI.Receipts /> : route === 'docs' ? <window.UI.Docs /> : route === 'feedback' ? <window.UI.Feedback /> : route === 'automations' ? <window.UI.Automations /> : route.startsWith('settings/') ? <window.UI.Settings key={route} page={route.slice(9)} /> : <window.UI.Settings key={route} page={{
      account: 'Account',
      connections: 'Connections',
      hooks: 'Hooks',
      dependencies: 'Dependencies',
      privacy: 'Privacy',
      appearance: 'Appearance',
      updates: 'Updates & About'
    }[route] || 'Account'} full />;
    return <Ctx.Provider value={value}>
  <input className="sr-only" ref={flowInput} aria-label="Import flow file" type="file" accept=".json,.yaml,.yml" onChange={async e => {
        const f = e.target.files?.[0];
        if (f) {
          try {
            const content = await f.text();
            const recipe = /\.ya?ml$/i.test(f.name);
            const flow = recipe ? null : JSON.parse(content);
            const r = await act(() => recipe ? api.importRecipe(content) : api.importFlow(flow));
            if (r) {
              go('canvas');
              setToast(r.count ? r.count + ' nodes imported' : 'Recipe added as a node');
            }
          } catch (error) {
            setToast('Choose a valid Node-RED or Langflow JSON file.');
          }
        }
        e.target.value = '';
      }} />
  <input className="sr-only" ref={fileInput} aria-label="Choose project file" type="file" multiple onChange={async e => {
        for (const f of e.target.files || []) {
          const record = await act(() => api.addFile(f.name));
          if (record) await act(() => api.addComposerAttachment(record.id));
        }
        e.target.value = '';
      }} />
  {s.app.quit || s.app.hidden ? <window.UI.DesktopScene /> : <div className="app-window" style={{
        height: '100%',
        display: 'grid',
        gridTemplateRows: route === 'canvas' ? '36px minmax(0,1fr)' : '36px minmax(0,1fr) 22px'
      }}>
   <header className="flex" style={{
          height: 36,
          padding: '0 12px',
          background: '#0f0f13',
          borderBottom: '1px solid ' + A.lineSoft,
          fontSize: 12
        }}><button className="button-reset" style={{
            width: 40,
            color: A.accent,
            fontSize: 20
          }} aria-label="ArchHub menu" title="ArchHub menu" onClick={event => executeAction("appShell.ArchHubMenu.1", {
            show
          }, event)}>⬡</button><button className="button-reset muted" onClick={event => executeAction("appShell.ArchHub.2", {
            go
          }, event)}>ArchHub</button><span className="muted">›</span><span>{routeNames[route] || route.split('/').at(-1)}</span><span className="fill" />{(s.update.available || s.update.updatedTo || s.update.state === 'failed') && <button className={(s.update.available ? 'button-reset' : 'icon-button') + ' update-badge'} title={s.update.available ? `${s.update.installed} → ${s.update.next}. Unsent text is lost; your saved graphs and settings stay with you.` : s.update.updatedTo ? 'Update installed' : 'Update needs attention'} aria-label={s.update.available ? 'Update available' : s.update.updatedTo ? 'Update installed' : 'Update needs attention'} onClick={event => executeAction("appShell.Control.3", {
            act,
            api,
            go,
            s
          }, event)}>{s.update.available ? 'Relaunch to update' : <window.AHIcon name="update" />}<i /></button>}<button className="button-reset muted" onClick={event => executeAction("appShell.Control.4", {
            show
          }, event)}>{s.workspaces.find(w => w.id === s.activeWorkspace)?.name || s.workspaces.find(w => w.builtIn)?.name || 'Add workspace'} ▾</button><button className="button-reset muted" style={{
            padding: '0 14px'
          }} onClick={event => executeAction("appShell.SearchCtrlK.5", {
            show
          }, event)} aria-label="Search · Ctrl K"><span className="flex"><window.AHIcon name="search" size={14} />Search<span className="mono">Ctrl K</span></span></button><button className="button-reset muted" aria-label="Notifications" title="Notifications" onClick={event => executeAction("appShell.Notifications.6", {
            show
          }, event)}><window.AHIcon name="bell" size={16} /> {s.notifications.filter(n => !n.read).length}</button><button className="button-reset" style={{
            padding: '0 14px'
          }} aria-label="Tray menu" title="Tray menu" onClick={event => executeAction("appShell.TrayMenu.7", {
            show
          }, event)}>⬡</button><button className="button-reset muted" aria-label="Minimize" title="Minimize" onClick={event => executeAction("appShell.Minimize.8", {
            act,
            api
          }, event)}>−</button><button className="button-reset muted" aria-label="Close window" title="Hide to tray" style={{
            padding: '0 12px'
          }} onClick={event => executeAction("appShell.CloseWindow.9", {
            act,
            api
          }, event)}>×</button></header>
   <div style={{
          display: 'grid',
          gridTemplateColumns: '64px minmax(0,1fr)',
          minHeight: 0
        }}><nav aria-label="Main navigation" style={{
            background: '#0f0f13',
            borderRight: '1px solid ' + A.lineSoft,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            paddingTop: 12,
            overflow: 'auto'
          }}>{rail.map(([g, l, r]) => <D.Rail key={r} variant="home" glyph={<window.AHIcon name={g} />} label={l} active={route === r} onDragOver={e => {
              if (r === 'canvas') e.preventDefault();
            }} onDragEnter={() => {
              if (r === 'canvas') go(r);
            }} onClick={event => executeAction("appShell.Control.10", {
              go,
              r
            }, event)} badge={r === 'workshop' ? s.tasks.filter(t => !['DONE','ARCHIVED'].includes(t.status)).length + (s.declaredTasks || []).length : undefined} style={{
              width: 64,
              height: 58,
              flex: 'none'
            }} />)}<span className="fill" /><D.Rail variant="home" glyph={<window.AHIcon name="settings" />} label="Settings" active={route.startsWith('settings/')} onClick={event => executeAction("appShell.Control.11", {
              go
            }, event)} style={{
              width: 64,
              height: 58,
              flex: 'none'
            }} /><button className="button-reset" aria-label="Your account" title="Your account" onClick={event => executeAction("appShell.YourAccount.12", {
              show
            }, event)} style={{
              margin: '8px 0 14px',
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: 'linear-gradient(135deg,#e8c39e,#b98a62)',
              color: '#2a1d10',
              fontWeight: 700,
              fontSize: 12,
              flex: 'none'
            }}>{s.profile.name.split(' ').map(n => n[0]).join('').slice(0, 2)}</button></nav><div className={'screen-with-composer ' + (route !== 'home' ? 'has-local-composer' : '')} style={{'--canvas-library-width':libraryOpen ? '248px' : '0px'}}>{(canvasOpened || route==='canvas') && <div hidden={route!=='canvas'} ref={element=>{element?.toggleAttribute('inert',route!=='canvas'||!!s.graphOpening);}} style={{display:route==='canvas'?'grid':'none',minHeight:0,height:'100%'}}><window.UI.Canvas key={s.graph.scopeKey || s.graph.id} active={route==='canvas'&&!s.graphOpening} /></div>}{screen}{route === 'canvas' && <div className="canvas-status" role="status"><span>{s.connectionNotice || '● Local session'}</span><span>{(s.agentSummary||'Checking running agents…')} · {s.approvals.filter(c=>c.status==='pending').length} wait for you</span>{agentLoad.status==='error' && <button className="button-reset" onClick={event=>executeAction('appShell.RetryWorkshop',{reloadWorkshop},event)}>Retry Workshop connection</button>}</div>}{['home','canvas'].includes(route) && <div className={'global-composer'+(route==='canvas'?' canvas-composer':'')}><window.UI.Composer compact /></div>}</div></div>
   {route !== 'canvas' && <footer className="flex" style={{
          fontSize: 11,
          gap: 16,
          padding: '0 14px',
          background: '#0f0f13',
          borderTop: '1px solid ' + A.lineSoft,
          color: A.inkSoft
        }}><span style={{
            color: A.ok
          }}>{s.connectionNotice || '● Local session'}</span>
          {agentLoad.status === 'waiting' && <span role="status">Loading Workshop settings…</span>}
          {agentLoad.status === 'error' && <span role="alert">{agentLoad.message}<Btn aria-label="Retry Workshop connection" onClick={event => executeAction("appShell.RetryWorkshop", {reloadWorkshop}, event)}>Retry</Btn></span>}
          {agentLoad.status === 'empty' && <span role="status">Select a workflow for Workshop settings.</span>}
          {agentLoad.status === 'loaded' && <span className="sr-only" aria-label="Workshop settings ready" title="Workshop settings ready">✓</span>}
          <button className="button-reset muted" onClick={event => executeAction("appShell.Control.13", {
            go
            }, event)}>{(s.hosts||[]).filter(h=>h.state==='connected'||h.state==='listening').map(h=>h.name+(h.detail?' · '+h.detail:'')).join(' · ') || s.files.find(f => f.id === s.activeFile)?.name || (s.hostsProbing?'Checking programs…':'Open Connections to connect a program')}</button><button className="button-reset muted" title={(s.agents||[]).map(a=>a.name+' · '+a.task).join(' · ')} onClick={event => executeAction("appShell.RunningWaitForYou.14", {
            go
          }, event)}>{s.agentSummary||'Checking running agents…'} · {s.approvals.filter(c => c.status === 'pending').length} wait for you</button><span className="fill" /><button className="button-reset muted" onClick={event => executeAction("appShell.CtrlK.15", {
            show
          }, event)}>Ctrl K</button><button className="button-reset muted" onClick={event => executeAction("appShell.Receipts.16", {
            go
          }, event)}>Receipts</button></footer>}
  </div>}
  <window.UI.BaboomSprite open={companion} setOpen={setCompanion} />
  {toast && <div role="alert" className="flex" style={{
        position: 'fixed',
        bottom: 36,
        left: '50%',
        transform: 'translateX(-50%)',
        maxWidth: '70vw',
        border: '1px solid ' + A.line,
        borderRadius: 10,
        background: '#24242b',
        padding: '12px 18px',
        zIndex: 200,
        boxShadow: '0 8px 30px #0008'
      }}><span>{toast}</span><Btn sm ghost onClick={event => executeAction("appShell.Dismiss.17", {
          setToast
        }, event)}>Dismiss</Btn></div>}
  {modal && <Dialog key={modal.kind + ':' + (modal.id || '')} modal={modal} close={close} />}
 </Ctx.Provider>;
  }
  function Dialog({
    modal: m,
    close
  }) {
    const s = useData(),
      u = window.UI.useApp();
    const [text, setText] = React.useState(m.text || ''),
      [extra, setExtra] = React.useState(''),
      [query, setQuery] = React.useState(''),
      [mode, setMode] = React.useState('All'),
      [listening, setListening] = React.useState(false),
      [voiceError, setVoiceError] = React.useState('');
    const ref = React.useRef(),
      voiceGeneration = React.useRef(0);
    React.useLayoutEffect(() => {
      voiceGeneration.current++;
      const el = ref.current;
      if (!el) return;
      // The first field takes the typing (Ctrl K → type a node name), not the header's close button.
      const f = el.querySelector('input:not([type=file]),textarea') || el.querySelector('button,select');
      f?.focus();
      const handler = e => {
        if (e.key !== 'Tab') return;
        const nodes = [...el.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')].filter(x => x.offsetParent !== null);
        if (!nodes.length) return;
        if (e.shiftKey && document.activeElement === nodes[0]) {
          e.preventDefault();
          nodes.at(-1).focus();
        } else if (!e.shiftKey && document.activeElement === nodes.at(-1)) {
          e.preventDefault();
          nodes[0].focus();
        }
      };
      el.addEventListener('keydown', handler);
      return () => {
        el.removeEventListener('keydown', handler);
        voiceGeneration.current++;
        if (m.kind === 'Talk' && api.supportsAction('stopVoiceInput')) void u.act(api.stopVoiceInput);
      };
    }, [m.kind]);
    const saved = async fn => {
      const result = await u.act(fn);
      if (result) close();
    };
    const k = m.kind;
    if (modalActions[k] && !api.supportsAction(modalActions[k])) return null;
    let body;
    if (k === 'Compatible nodes') body = <><input aria-label="Search compatible nodes" placeholder="Find a compatible node…" value={query} onChange={e => setQuery(e.target.value)} /><div className="grid">{api.compatibleNodes(m.endpoint).filter(c => c.name.toLowerCase().includes(query.toLowerCase())).map(c => <button className="listbutton spread" key={c.id} onClick={event => executeAction("appShell.Control.18", {
          api,
          c,
          close,
          m,
          u
        }, event)}><span>{c.name}</span><span className="muted">{c.input} → {c.output}</span></button>)}</div></>;else if (k === 'Capability') body = <><h2>{s.capabilities.find(c => c.id === m.id)?.name}</h2><window.UI.CapabilitySettings id={m.id} /></>;else if (k === 'Action evidence') body = <window.UI.ActionEvidence id={m.id} />;else if (k === 'Node') body = <window.UI.NodeDetails id={m.id} />;else if (k === 'Timesheet') body = <><Table rows={s.timesheet.rows} /><Chip>{s.timesheet.status}</Chip><div className="flex">{api.supportsAction?.('settleTimesheet') !== false && <Btn p onClick={event => executeAction("appShell.AcceptDraft.19", {
          api,
          u
        }, event)}>Accept draft</Btn>}{api.supportsAction?.('settleTimesheet') !== false && <Btn onClick={event => executeAction("appShell.Dismiss.20", {
          api,
          u
        }, event)}>Dismiss</Btn>}</div></>;else if (k === 'Contest decision') body = <><h2>{m.title}</h2><textarea aria-label="Contest reason" value={text} onChange={e => setText(e.target.value)} />{api.supportsAction?.('contestDecision') !== false && <Btn p disabled={!text.trim()} onClick={event => executeAction("appShell.RequestReview.21", {
        api,
        m,
        saved,
        text
      }, event)}>Request review</Btn>}</>;else if (k === 'Connector bundle') body = <window.UI.ConnectorBundle />;else if (k === 'Host skill') body = <window.UI.HostSkill id={m.id} />;else if (k === 'Correct source') body = <><input aria-label="Source reference" value={text} onChange={e => setText(e.target.value)} /><Btn p onClick={event => executeAction("appShell.Save.22", {
        api,
        m,
        saved,
        text
      }, event)}>Save</Btn></>;else if (k === 'Import skill') body = <><p className="muted">Choose the program and the skill instructions. Review scripts and network access before enabling.</p><select aria-label="Skill program" value={mode === 'All' ? 'Revit' : mode} onChange={e => setMode(e.target.value)}>{s.connections.map(c => <option key={c.id}>{c.name}</option>)}</select>{api.supportsAction?.('importHostSkill') !== false && <input type="file" aria-label="Choose SKILL.md" accept=".md" onChange={async e => {
        const f = e.target.files?.[0];
        if (f) {
          const body = await f.text();
          const skill = await u.act(() => api.importHostSkill({
            name: '',
            host: mode === 'All' ? 'Revit' : mode,
            text: body
          }));
          if (skill) u.show('Host skill', {
            id: skill.id
          });
        }
      }} />}</>;else if (k === 'Rename workflow') body = <><input aria-label="Workflow name" value={text} onChange={e => setText(e.target.value)} /><Btn p disabled={!text.trim()} onClick={event => executeAction("appShell.Save.23", {
        api,
        m,
        saved,
        text
      }, event)}>Save</Btn></>;else if (k === 'Subscription') body = <window.UI.BillingAccount />;else if (k === 'Task details') body = <window.UI.TaskDetails id={m.id} />;else if (k === 'Node output') body = <window.UI.NodeOutput id={m.id} />;else if (k === 'Workflows') body = <window.UI.GraphManager />;else if (k === 'MCP tools') body = <window.UI.McpTools />;else if (k === 'Install mod' || k === 'Make a mod') body = <window.UI.ModManager making={k === 'Make a mod'} />;else if (k === 'Legacy workflows') body = <div className="grid">{s.graphs.map(g => <button className="listbutton spread" key={g.id} onClick={event => executeAction("appShell.Control.24", {
        api,
        g,
        u
      }, event)}><span>{g.name}</span><span className="muted">{g.nodes.length} nodes</span></button>)}<label className="grid">New workflow<input aria-label="New workflow name" value={text} onChange={e => setText(e.target.value)} /></label><Btn p onClick={event => executeAction("appShell.AddGraph.25", {
        api,
        text,
        u
      }, event)}>Add workflow</Btn></div>;else if (k === 'Workspace rules') body = <window.UI.WorkspaceRules id={m.id} />;else if (k === 'Dimensions') body = <window.UI.WatcherDimensions />;else if (k === 'Update') body = <><p>{s.update.detail || 'Update status unavailable'}</p><p>{s.update.installed} → {s.update.next}</p><p>Restart now. Unsent text is lost; your saved workflows and settings stay with you.</p>{s.update.restartRefusal && <p role="alert">{s.update.restartRefusal}</p>}<Btn p disabled={!s.update.available || !!s.update.restartRefusal} onClick={event => executeAction("appShell.RestartAndUpdate.26", {
        api,
        saved
      }, event)}>Restart and update</Btn><Btn onClick={event => executeAction("appShell.ReadStatus.27", {
        api,
        u
      }, event)}>Read status</Btn></>;else if (k === 'Add parameter') body = <><label className="grid">Parameter name<input aria-label="Parameter name" value={text} onChange={e => setText(e.target.value)} /></label><label className="grid">Type<select aria-label="Parameter type" value={mode === 'All' ? 'text' : mode} onChange={e => setMode(e.target.value)}>{['text', 'number', 'boolean'].map(t => <option key={t}>{t}</option>)}</select></label><Btn p disabled={!text.trim()} onClick={event => executeAction("appShell.AddParameter.28", {
        api,
        m,
        mode,
        saved,
        text
      }, event)}>Add parameter</Btn></>;else if (k === 'Approve') body = <window.UI.ApprovalCard id={m.id} />;else if (k === 'Search') {
      const items = [...s.catalogue.map(c => ({
        label: c.name,
        group: 'Add node',
        action: async () => {
          await u.act(() => api.addNode(c.name));
          u.go('canvas');
        }
      })), ...s.templates.map(t => ({
        label: t.title,
        group: 'Skills',
        action: () => u.show('Skill', {
          id: t.id
        })
      })), ...s.tasks.map(t => ({
        label: t.title,
        group: 'Chats',
        action: () => {
          u.setTask(t.id);
          u.go('workshop');
        }
      })), ...Object.entries(routeNames).map(([r, label]) => ({
        label,
        group: 'Pages',
        action: () => u.go(r)
      }))].filter(x => (mode === 'All' || x.group === mode) && x.label.toLowerCase().includes(query.toLowerCase()));
      body = <><input aria-label="Search everything" placeholder="Find a node, skill or chat…" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => {
          if (e.key === 'Enter') items[0]?.action();
        }} /><div className="flex">{['All', 'Add node', 'Skills', 'Chats', 'Pages'].map(t => <Btn key={t} sm ghost aria-pressed={mode === t} onClick={event => executeAction("appShell.Control.29", {
            setMode,
            t
          }, event)}>{t}</Btn>)}</div><div style={{
          maxHeight: '55vh',
          overflow: 'auto'
        }}>{items.map((item, i) => <button className="listbutton spread" key={i} onClick={event => executeAction("appShell.Control.30", {
            item
          }, event)}><span>{item.label}</span><span className="muted" style={{
              fontSize: 11
            }}>{item.group}</span></button>)}{!items.length && <Empty>No results.</Empty>}</div></>;
    } else if (k === 'Confirm') body = <><p>{m.title}</p><p className="muted">Undo brings it back.</p><div className="flex"><Btn onClick={event => executeAction("appShell.Cancel.31", {
          close
        }, event)}>Cancel</Btn><Btn danger onClick={event => executeAction("appShell.Confirm.32", {
          m,
          saved
        }, event)}>Confirm</Btn></div></>;else if (k === 'New task') body = <window.UI.Composer onSent={t => {
      u.setTask(t.id);
      u.go('workshop');
    }} />;else if (k === 'Account') body = <><h2>{s.profile.name}</h2><p className="muted">{s.profile.firm} · {s.people.length} people</p><div className="grid">{['My profile', 'My secrets', 'My files', 'Workspaces'].map(t => <Btn key={t} onClick={event => executeAction("appShell.Control.33", {
          t,
          u
        }, event)}>{t}</Btn>)}<Btn onClick={event => executeAction("appShell.AccountSettings.34", {
          u
        }, event)}>Account settings</Btn><Btn ghost onClick={event => executeAction("appShell.SignOut.35", {
          api,
          saved
        }, event)}>Sign out</Btn></div></>;else if (k === 'My profile') body = <><label className="grid">Name<input aria-label="Profile name" value={text || s.profile.name} onChange={e => setText(e.target.value)} /></label><label className="grid">Firm<input aria-label="Firm" value={extra || s.profile.firm} onChange={e => setExtra(e.target.value)} /></label><Btn p onClick={event => executeAction("appShell.Save.36", {
        api,
        extra,
        s,
        saved,
        text
      }, event)}>Save</Btn></>;else if (k === 'My secrets') body = <><p className="muted">Your connected accounts are protected. No secret values are shown or copied.</p>{s.secrets.map(x => <div className="spread row" key={x.id}><div><h3>{x.name}</h3><p className="muted">{x.status}</p></div>{x.disconnectable !== false && api.supportsAction?.('disconnectSecret') !== false && <Btn sm onClick={event => executeAction("appShell.Disconnect.37", {
          api,
          u,
          x
        }, event)}>Disconnect</Btn>}</div>)}<Btn onClick={event => executeAction("appShell.ConnectAnAccount.38", {
        u
      }, event)}>Connect an account</Btn></>;else if (k === 'My files') body = <><Btn onClick={event => executeAction("appShell.AddFile.39", {
        u
      }, event)}>Add file</Btn>{s.files.map(f => <div className="spread row" key={f.id}><div><h3>{f.name}</h3><p className="muted">{f.kind}</p></div><div className="flex"><Btn sm onClick={event => executeAction("appShell.Open.40", {
            api,
            f,
            u
          }, event)}>Open</Btn><Btn sm ghost onClick={event => executeAction("appShell.Remove.41", {
            api,
            f,
            u
          }, event)}>Remove</Btn></div></div>)}</>;else if (k === 'Workspaces') body = <window.UI.WorkspaceRows />;else if (k === 'App menu') body = <div className="grid">{Object.entries(routeNames).map(([r, l]) => <Btn key={r} sm ghost onClick={event => executeAction("appShell.Control.42", {
        r,
        u
      }, event)}>{l}</Btn>)}<Btn sm onClick={event => executeAction("appShell.Settings.43", {
        u
      }, event)}>Settings</Btn></div>;else if (k === 'Tray') body = <div className="grid"><Btn onClick={event => executeAction("appShell.OpenArchHub.44", {
        api,
        saved
      }, event)}>⬡ Open ArchHub</Btn><Btn onClick={event => executeAction("appShell.BABOOM.45", {
        close,
        u
      }, event)}>BABOOM</Btn><Btn onClick={event => executeAction("appShell.StopEverything.46", {
        api,
        saved
      }, event)}>Stop everything</Btn><Btn onClick={event => executeAction("appShell.Hide.47", {
        api,
        saved
      }, event)}>Hide</Btn><Btn danger onClick={event => executeAction("appShell.Quit.48", {
        api,
        saved
      }, event)}>Quit</Btn></div>;else if (k === 'Workshop board') body = <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(5,minmax(160px,1fr))',
      minHeight: 300
    }}>{['PLANNED', 'WIP', 'IN REVIEW', 'DONE', 'ARCHIVED'].map(status => <div className="task-column" key={status} onDragOver={e => e.preventDefault()} onDrop={e => {
        e.preventDefault();
        const id = e.dataTransfer.getData('task');
        if (id) u.act(() => api.setTaskStatus(id, status));
      }}><h3 style={{
          color: A.inkSoft
        }}>{status} · {s.tasks.filter(t => t.status === status).length}</h3>{s.tasks.filter(t => t.status === status).map(t => <Card key={t.id} style={{
          padding: 8
        }}><window.UI.Task task={t} select={() => {
            u.setTask(t.id);
            u.go('workshop');
          }} /></Card>)}</div>)}</div>;else if (k === 'Notifications' || k === 'Founder inbox') body = <div className="grid">{s.notifications.map(n => (api.supportsAction?.('readNotification') !== false && <button className="listbutton" key={n.id} onClick={event => executeAction("appShell.Control.49", {
        api,
        n,
        u
      }, event)}>{n.read ? '✓' : '●'} {n.text}</button>))}{s.approvals.filter(c => ['pending', 'postponed', 'stale', 'refused', 'contested'].includes(c.status)).map(c => <Btn key={c.id} onClick={event => executeAction("appShell.Review.50", {
        c,
        u
      }, event)}>Review · {c.title}</Btn>)}</div>;else if (k === 'Schedule') body = <><label className="grid">Every day at<input aria-label="Schedule time" type="time" value={text || '08:00'} onChange={e => setText(e.target.value)} /></label><Btn p onClick={event => executeAction("appShell.AddSchedule.51", {
        api,
        m,
        saved,
        text
      }, event)}>Add schedule</Btn></>;else if (k === 'Skill') {
      const t = s.templates.find(t => t.id === m.id);
      body = <><h2>{t?.title}</h2><p className="muted">{t?.chain.join(' → ')}</p><div className="flex"><Btn p onClick={event => executeAction("appShell.Start.52", {
            api,
            m,
            u
          }, event)}>Start</Btn><Btn onClick={event => executeAction("appShell.AddAsNode.53", {
            api,
            t,
            u
          }, event)}>Add as node</Btn><Btn onClick={event => executeAction("appShell.RunEveryDay.54", {
            t,
            u
          }, event)}>Run every day</Btn></div></>;
    } else if (k === 'Node menu' || k === 'Node') {
      const n = s.graph.nodes.find(n => n.id === m.id);
      body = n ? <div className="grid"><h2>{n.title}</h2><div className="flex"><Chip>{n.frozen ? 'Frozen' : n.status}</Chip>{n.pinned && <Chip>Pinned output</Chip>}</div><Btn sm onClick={event => executeAction("appShell.Output.55", {
          n,
          u
        }, event)}>Output</Btn><Btn sm onClick={event => executeAction("appShell.Control.56", {
          api,
          n,
          u
        }, event)}>{n.frozen ? 'Unfreeze' : 'Freeze'}</Btn><Btn sm onClick={event => executeAction("appShell.Control.57", {
          api,
          n,
          u
        }, event)}>{n.pinned ? 'Unpin output' : 'Pin output'}</Btn><Btn sm onClick={event => executeAction("appShell.RunToHere.58", {
          api,
          close,
          n,
          u
        }, event)}>Run to here</Btn><Btn sm onClick={event => executeAction("appShell.Open.59", {
          close,
          m,
          u
        }, event)}>Open</Btn><Btn sm onClick={event => executeAction("appShell.Rerun.60", {
          api,
          n,
          saved
        }, event)}>Rerun</Btn><Btn sm onClick={event => executeAction("appShell.Fork.61", {
          api,
          n,
          saved
        }, event)}>Fork</Btn><Btn sm onClick={event => executeAction("appShell.RepeatThis.62", {
          n,
          u
        }, event)}>Repeat this</Btn><Btn sm onClick={event => executeAction("appShell.TraceBack.63", {
          n,
          u
        }, event)}>Trace back</Btn><Btn sm onClick={event => executeAction("appShell.TraceForward.64", {
          n,
          u
        }, event)}>Trace forward</Btn>{n.children && <Btn sm onClick={event => executeAction("appShell.Ungroup.65", {
          api,
          n,
          saved
        }, event)}>Ungroup</Btn>}<Btn danger sm onClick={event => executeAction("appShell.Delete.66", {
          api,
          n,
          u
        }, event)}>Delete…</Btn></div> : <Empty>Choose a node.</Empty>;
    } else if (k === 'Canvas menu') body = <div className="grid"><Btn sm onClick={event => executeAction("appShell.AddNode.67", {
        u
      }, event)}>Add node</Btn><Btn sm onClick={event => executeAction("appShell.Arrange.68", {
        api,
        saved
      }, event)}>Arrange</Btn><Btn sm onClick={event => executeAction("appShell.GroupCtrlG.69", {
        close,
        m
      }, event)} disabled={m.selected.length < 2}>Group · Ctrl G</Btn><Btn sm onClick={event => executeAction("appShell.SaveAsSkill.70", {
        u
      }, event)}>Save as skill</Btn><Btn danger sm onClick={event => executeAction("appShell.Delete.71", {
        m
      }, event)}>Delete…</Btn></div>;else if (k === 'Parameter socket') body = <><p>{m.page} is an application node. Its parameters are the same values shown in Settings.</p><div className="grid">{s.settings.filter(r => r.page === m.page).map(r => <div key={r.id} className="spread row"><span>{r.label} · {r.type}</span><Btn sm onClick={event => executeAction("appShell.ExposeOnCanvas.72", {
            api,
            m,
            r,
            u
          }, event)}>Expose on canvas</Btn></div>)}</div><Btn onClick={event => executeAction("appShell.OpenSystemGraph.73", {
        u
      }, event)}>Open System graph</Btn></>;else if (k === 'Type mismatch') body = <><p style={{
        color: A.warn
      }}>{m.reason}</p><p className="muted">Insert a converter between these sockets.</p><Btn p onClick={event => executeAction("appShell.InsertConvert.74", {
        api,
        m,
        saved
      }, event)}>Insert Convert</Btn></>;else if (k === 'Trace back' || k === 'Trace forward') body = <div className="grid">{m.rows?.map(r => <button className="listbutton" key={r.id} onClick={event => executeAction("appShell.Control.75", {
        u
      }, event)}><h3>{r.title}</h3><p className="muted">{r.relation}</p></button>)}</div>;else if (k === 'Edit rule' || k === 'Remember') body = <><textarea aria-label="Learned rule" rows={3} value={text} onChange={e => setText(e.target.value)} /><Btn p disabled={!text.trim()} onClick={event => executeAction("appShell.Save.76", {
        api,
        k,
        m,
        saved,
        text
      }, event)}>Save</Btn></>;else if (k === 'Add comment') body = <><textarea aria-label="Comment text" rows={3} placeholder="Your comment…" value={text} onChange={e => setText(e.target.value)} />{api.supportsAction?.('addComment') !== false && <Btn p disabled={!text.trim()} onClick={event => executeAction("appShell.AddComment.77", {
        api,
        m,
        saved,
        text
      }, event)}>Add comment</Btn>}</>;else if (k === 'Comment') body = <p>{m.text}</p>;else if (k === 'Invite') body = <><label className="grid">Email<input type="email" aria-label="Teammate email" value={text} placeholder="colleague@office.com" onChange={e => setText(e.target.value)} /></label><Btn p disabled={!text.includes('@')} onClick={event => executeAction("appShell.Invite.78", {
        api,
        saved,
        text
      }, event)}>Invite</Btn></>;else if (k === 'Change plan') body = <><select aria-label="Plan" value={text || 'Office'} onChange={e => setText(e.target.value)}><option>Office</option><option>Team</option><option>Personal</option></select>{api.supportsAction?.('changePlan') !== false && <Btn p onClick={event => executeAction("appShell.Apply.79", {
        api,
        m,
        saved,
        text
      }, event)}>Apply</Btn>}</>;else if (k === 'Save skill') body = <><input aria-label="Skill name" placeholder="Name this skill" value={text} onChange={e => setText(e.target.value)} /><Btn p disabled={!text.trim()} onClick={event => executeAction("appShell.SaveSkill.80", {
        api,
        saved,
        text
      }, event)}>Save skill</Btn></>;else if (k === 'Agent') {
      const p = (s.agents||[]).find(p => p.id === m.id) || s.providers.find(p => p.id === m.id);
      body = p?.runtime ? <div className="grid"><h2>{p.name}</h2><p>{p.status_text} · {p.task}</p><p className="muted">{p.title} · {p.model}</p>{p.detail&&<p>{p.detail}</p>}</div> : p ? <div className="grid"><window.UI.Providers /><window.UI.AgentProfile id={p.id} /><label className="grid">Model{api.supportsAction?.('setProviderModel') !== false && <select aria-label="Provider model" value={p.model} onChange={e => u.act(() => api.setProviderModel(p.id, e.target.value))}>{[...new Set([p.model, ...(p.models||[])])].map(x => <option key={x}>{x}</option>)}</select>}</label><Btn onClick={event => executeAction("appShell.AgentSettings.81", {
          u
        }, event)}>Agent settings</Btn></div> : <Empty>No agent selected.</Empty>;
    } else if (k === 'Teammate') {
      const p = s.people.find(p => p.id === m.id);
      body = <><h2>{p?.name}</h2><p className="muted">{p?.role} · {p?.task}</p><Btn onClick={event => executeAction("appShell.MessageInWorkshop.82", {
          close,
          u
        }, event)}>Message in Workshop</Btn></>;
    } else if (k === 'Connection' || k === 'Connect') {
      const c = s.connections.find(c => c.id === m.id);
      body = <><h2>{c?.name}</h2><p className="muted">{c?.connected ? 'Connected to your account' : 'Sign in with your browser. Nothing to copy or paste.'}</p><div className="flex"><Btn p onClick={event => executeAction("appShell.Control.83", {
            api,
            m,
            saved
          }, event)}>{c?.connected ? 'Reconnect' : 'Sign in with your browser'}</Btn><Btn onClick={event => executeAction("appShell.CheckAgain.84", {
            api,
            m,
            u
          }, event)}>Check again</Btn>{c?.connected && <Btn danger onClick={event => executeAction("appShell.Disconnect.85", {
            api,
            c,
            m,
            u
          }, event)}>Disconnect</Btn>}</div>{c?.checked && <Chip c={A.ok}>Checked</Chip>}<window.UI.ConnectorTools connection={c} /></>;
    } else if (k === 'Sign in') body = <><p>Sign in with your account and bring your work with you.</p><Btn p onClick={event => executeAction("appShell.SignInWithYourBrowser.86", {
        api,
        saved
      }, event)}>Sign in with your browser</Btn><Btn onClick={event => executeAction("appShell.ContinueAndSignInLater.87", {
        close
      }, event)}>Continue and sign in later</Btn></>;else if (k === 'Talk') {
      const talk = () => {
        const generation = voiceGeneration.current;
        return api.startVoiceInput({
          onTranscript: value => { if (generation === voiceGeneration.current) setText(value); },
          onStatus: value => { if (generation === voiceGeneration.current) setListening(value); },
          onError: value => { if (generation === voiceGeneration.current) setVoiceError(value); }
        });
      };
      body = <><p>Speak one sentence using your Windows speech language. Review it before sending.</p>{api.supportsAction?.('stopVoiceInput') !== false && <Btn onClick={event => executeAction("appShell.Control.88", {
          api,
          listening,
          u,
          talk
        }, event)}>{listening ? 'Stop listening' : '🎙 Start talking'}</Btn>}{voiceError && <p role="status" className="muted">{voiceError}</p>}<textarea aria-label="Spoken sentence" rows={3} value={text} onChange={e => setText(e.target.value)} /><div className="flex"><Btn p disabled={!text.trim()} onClick={event => executeAction("appShell.UseSentence.89", {
            close,
            m,
            text
          }, event)}>Use sentence</Btn><Btn disabled={!text.trim()} onClick={event => executeAction("appShell.SendToBABOOM.90", {
            api,
            text,
            u
          }, event)}>Send to BABOOM</Btn></div></>;
    } else if (k === 'Voice command') body = <><p>{m.text}</p><Btn p onClick={event => executeAction("appShell.Send.91", {
        api,
        m,
        u
      }, event)}>Send</Btn></>;else if (k === 'Examples') {
      const c = s.catalogue.find(c => c.id === m.id);
      body = <><h2>{c?.name}</h2><p>{c?.description} · {s.graph.name}</p><Btn p onClick={event => executeAction("appShell.UseExample.92", {
          api,
          c,
          u
        }, event)}>Use example</Btn></>;
    } else if (k === 'Run') {
      const r = s.runs.find(r => r.id === m.id);
      body = <><h2>{r?.title}</h2><Chip c={A.ok}>{r?.status}</Chip>{r?.rows ? <Table rows={r.rows} /> : <p className="muted">No saved output for this run.</p>}<Btn disabled={!r?.rows} onClick={event => executeAction("appShell.Export.93", {
          r,
          u
        }, event)}>Export</Btn></>;
    } else if (k === 'Image edit') body = <><p>{m.action} inside your mask</p><input aria-label="Image instruction" placeholder="For example: glass façade" value={text} onChange={e => setText(e.target.value)} /><Btn p onClick={event => executeAction("appShell.ReviewChange.94", {
        api,
        m,
        text,
        u
      }, event)}>Review change</Btn></>;else if (k === 'Tool check') body = <><p>Check each managed tool from its Settings row.</p><div className="grid">{s.settings.filter(r => r.page === 'Dependencies').map(r => <window.UI.SettingControl key={r.id} row={r} />)}</div></>;else if (k === 'Meeting notes') body = <><h2>{s.meeting.title || "Meeting notes"}</h2><p>{s.meeting.actions.join(" · ") || "No meeting notes available."}</p><Btn onClick={event => executeAction("appShell.OpenTeam.95", {
        u
      }, event)}>Open team</Btn></>;else if (k === 'What’s new') body = <><p>One companion, one Workshop, editable nodes and settings, and a clear review before a change.</p><Btn onClick={event => executeAction("appShell.UpdatesAbout.96", {
        u
      }, event)}>Updates &amp; About</Btn></>;else if (k === 'Ask why') body = <p>The read-only steps find untagged doors and check the prefix before the write step. Approve once runs that proposed change.</p>;else if (k === 'Website') body = <><h2>ArchHub</h2><p>The same catalogue powers the app and its documentation.</p><Btn onClick={event => executeAction("appShell.OpenDocs.97", {
        u
      }, event)}>Open docs</Btn></>;else body = <p>{m.text || 'Choose an action from the app.'}</p>;
    if (['Node menu', 'Canvas menu', 'App menu', 'Tray', 'Port menu'].includes(k)) return <window.UI.ContextMenu kind={k} nodeId={m.id} port={m.port} open={m.open} selected={m.selected} group={m.group} remove={m.remove} anchor={m.anchor} close={close} />;
    return <div className="overlay" onMouseDown={e => {
      if (e.target === e.currentTarget) close();
    }}><section ref={ref} className="dialog" role="dialog" aria-modal="true" aria-label={k} style={{
        width: k === 'Workshop board' ? 'min(1250px,95vw)' : k === 'Approve' ? 'min(850px,95vw)' : undefined
      }}><header className="spread"><h2>{k}</h2><Btn sm ghost aria-label="Close dialog" onClick={event => executeAction("appShell.CloseDialog.98", {
            close
          }, event)}>×</Btn></header>{body}</section></div>;
  }
  class Boundary extends React.Component {
    constructor(p) {
      super(p);
      this.state = {
        error: null
      };
    }
    static getDerivedStateFromError(error) {
      return {
        error
      };
    }
    render() {
      return this.state.error ? <div role="alert" style={{
        padding: 40
      }}><h1>Could not open this view</h1><p>{this.state.error.message}</p><button onClick={event => executeAction('appShell.RetryView', {
          boundary: this
        }, event)}>Retry</button></div> : this.props.children;
    }
  }
  window.ReactDOM.createRoot(document.getElementById('root')).render(<Boundary><App /></Boundary>);
})();
(() => {
  function appShellArchHubMenu1({
    show
  }, event) {
    const handler = () => show('App menu');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellArchHub2({
    go
  }, event) {
    const handler = () => go('home');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl3({
    act,
    api,
    go,
    s
  }, event) {
    const handler = () => s.update.available ? act(api.installUpdate) : go('settings/Updates & About');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl4({
    show
  }, event) {
    const handler = () => show('Workspaces');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSearchCtrlK5({
    show
  }, event) {
    const handler = () => show('Search');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellNotifications6({
    show
  }, event) {
    const handler = () => show('Notifications');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellTrayMenu7({
    show
  }, event) {
    const handler = () => show('Tray');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellMinimize8({
    act,
    api
  }, event) {
    const handler = () => act(() => api.windowAction('minimize'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellCloseWindow9({
    act,
    api
  }, event) {
    const handler = () => act(() => api.windowAction('hide'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl10({
    go,
    r
  }, event) {
    const handler = () => go(r);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl11({
    go
  }, event) {
    const handler = () => go('settings/Account');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellYourAccount12({
    show
  }, event) {
    const handler = () => show('Account');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl13({
    go
  }, event) {
    const handler = () => go('watcher');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRunningWaitForYou14({
    go
  }, event) {
    const handler = () => go('workshop');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellCtrlK15({
    show
  }, event) {
    const handler = () => show('Search');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellReceipts16({
    go
  }, event) {
    const handler = () => go('receipts');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellDismiss17({
    setToast
  }, event) {
    const handler = () => setToast('');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl18({
    api,
    c,
    close,
    m,
    u
  }, event) {
    const handler = async () => {
      const n = await u.act(() => api.addCompatibleNode(m.endpoint, c.id, m.position));
      if (n) close();
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAcceptDraft19({
    api,
    u
  }, event) {
    const handler = () => u.act(() => api.settleTimesheet('Accept'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellDismiss20({
    api,
    u
  }, event) {
    const handler = () => u.act(() => api.settleTimesheet('Dismiss'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRequestReview21({
    api,
    m,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.contestDecision(m.id, text));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSave22({
    api,
    m,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.setSourceEvidence(m.id, {
      source: text
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSave23({
    api,
    m,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.updateGraph(m.id, {
      name: text
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl24({
    api,
    g,
    u
  }, event) {
    const handler = async () => {
      await u.act(() => api.selectGraph(g.id));
      u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAddGraph25({
    api,
    text,
    u
  }, event) {
    const handler = async () => {
      await u.act(() => api.addGraph(text));
      u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRestartAndUpdate26({
    api,
    saved
  }, event) {
    const handler = () => saved(api.installUpdate);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellReadStatus27({
    api,
    u
  }, event) {
    const handler = () => u.act(api.refreshApplicationUpdate);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAddParameter28({
    api,
    m,
    mode,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.addNodeParameter(m.id, {
      label: text,
      type: mode,
      value: mode === 'number' ? 0 : mode === 'boolean' ? false : ''
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl29({
    setMode,
    t
  }, event) {
    const handler = () => setMode(t);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl30({
    item
  }, event) {
    const handler = item.action;
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellCancel31({
    close
  }, event) {
    const handler = close;
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellConfirm32({
    m,
    saved
  }, event) {
    const handler = () => saved(m.run);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl33({
    t,
    u
  }, event) {
    const handler = () => u.show(t);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAccountSettings34({
    u
  }, event) {
    const handler = () => u.go('settings/Account');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSignOut35({
    api,
    saved
  }, event) {
    const handler = () => saved(() => api.signIn(false));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSave36({
    api,
    extra,
    s,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.updateProfile({
      name: text || s.profile.name,
      firm: extra || s.profile.firm
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellDisconnect37({
    api,
    u,
    x
  }, event) {
    const handler = () => u.confirm('Disconnect ' + x.name + '?', () => api.disconnectSecret(x.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellConnectAnAccount38({
    u
  }, event) {
    const handler = () => u.go('settings/Connections');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAddFile39({
    u
  }, event) {
    const handler = u.pickFile;
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellOpen40({
    api,
    f,
    u
  }, event) {
    const handler = async () => {
      await u.act(() => api.selectFile(f.id));
      u.go('watcher');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRemove41({
    api,
    f,
    u
  }, event) {
    const handler = () => u.confirm('Remove ' + f.name + ' from this list?', () => api.removeFile(f.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl42({
    r,
    u
  }, event) {
    const handler = () => u.go(r);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSettings43({
    u
  }, event) {
    const handler = () => u.go('settings/Account');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellOpenArchHub44({
    api,
    saved
  }, event) {
    const handler = () => saved(() => api.windowAction('open'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellBABOOM45({
    close,
    u
  }, event) {
    const handler = () => {
      close();
      u.go('baboom');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellStopEverything46({
    api,
    saved
  }, event) {
    const handler = () => saved(api.stopEverything);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellHide47({
    api,
    saved
  }, event) {
    const handler = () => saved(() => api.windowAction('hide'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellQuit48({
    api,
    saved
  }, event) {
    const handler = () => saved(() => api.windowAction('quit'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl49({
    api,
    n,
    u
  }, event) {
    const handler = async () => {
      await u.act(() => api.readNotification(n.id));
      u.go('workshop');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellReview50({
    c,
    u
  }, event) {
    const handler = () => u.show('Approve', {
      id: c.id
    });
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAddSchedule51({
    api,
    m,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.addSchedule(m.id, text || '08:00'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellStart52({
    api,
    m,
    u
  }, event) {
    const handler = async () => {
      const task = await u.act(() => api.startTemplate(m.id));
      if (task) {
        u.setTask(task.id);
        u.go('workshop');
      }
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAddAsNode53({
    api,
    t,
    u
  }, event) {
    const handler = async () => {
      const node = await u.act(() => api.addTemplateNode(t.id));
      if (node) u.setSelectedNodeId(node.id);
      u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRunEveryDay54({
    t,
    u
  }, event) {
    const handler = () => u.schedule(t.title);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellOutput55({
    n,
    u
  }, event) {
    const handler = () => u.show('Node output', {
      id: n.id
    });
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl56({
    api,
    n,
    u
  }, event) {
    const handler = () => u.act(() => api.setNodeFlags(n.id, {
      frozen: !n.frozen
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl57({
    api,
    n,
    u
  }, event) {
    const handler = () => u.act(() => api.setNodeFlags(n.id, {
      pinned: !n.pinned
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRunToHere58({
    api,
    close,
    n,
    u
  }, event) {
    const handler = async () => {
      const result = await u.act(() => api.runToHere(n.id));
      if (result?.approvalId) u.show('Approve', {
        id: result.approvalId
      });else close();
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellOpen59({
    close,
    m,
    u
  }, event) {
    const handler = () => {
      close();
      if (m.open) m.open();else u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRerun60({
    api,
    n,
    saved
  }, event) {
    const handler = () => saved(() => api.runNode(n.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellFork61({
    api,
    n,
    saved
  }, event) {
    const handler = () => saved(() => api.forkNode(n.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRepeatThis62({
    n,
    u
  }, event) {
    const handler = () => u.schedule(n.id);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellTraceBack63({
    n,
    u
  }, event) {
    const handler = () => u.trace(n.id, 'back');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellTraceForward64({
    n,
    u
  }, event) {
    const handler = () => u.trace(n.id, 'forward');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellUngroup65({
    api,
    n,
    saved
  }, event) {
    const handler = () => saved(() => api.ungroupNode(n.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellDelete66({
    api,
    n,
    u
  }, event) {
    const handler = () => u.confirm('Delete ' + n.title + '?', () => api.deleteNode(n.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAddNode67({
    u
  }, event) {
    const handler = () => u.show('Search');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellArrange68({
    api,
    saved
  }, event) {
    const handler = () => saved(api.arrangeGraph);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellGroupCtrlG69({
    close,
    m
  }, event) {
    const handler = () => {
      m.group?.();
      close();
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSaveAsSkill70({
    u
  }, event) {
    const handler = () => u.show('Save skill');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellDelete71({
    m
  }, event) {
    const handler = () => {
      m.remove?.();
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellExposeOnCanvas72({
    api,
    m,
    r,
    u
  }, event) {
    const handler = async () => {
      const n = await u.act(() => api.addNode(m.page));
      if (n) {
        await u.act(() => api.setNodeParam(n.id, r.label, r.value));
        u.go('canvas');
      }
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellOpenSystemGraph73({
    u
  }, event) {
    const handler = () => u.go('system');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellInsertConvert74({
    api,
    m,
    saved
  }, event) {
    const handler = () => saved(() => api.insertConvert(m.wire));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl75({
    u
  }, event) {
    const handler = () => {
      u.go('canvas');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSave76({
    api,
    k,
    m,
    saved,
    text
  }, event) {
    const handler = () => saved(() => k === 'Remember' ? api.remember(text) : api.editMemory(m.id, text));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAddComment77({
    api,
    m,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.addComment({
      text,
      x: m.x,
      y: m.y,
      element: m.element
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellInvite78({
    api,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.invitePerson(text));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellApply79({
    api,
    m,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.changePlan(m.id, text || 'Office'));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSaveSkill80({
    api,
    saved,
    text
  }, event) {
    const handler = () => saved(() => api.saveSkill(text));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellAgentSettings81({
    u
  }, event) {
    const handler = () => u.go('settings/Agents');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellMessageInWorkshop82({
    close,
    u
  }, event) {
    const handler = () => {
      close();
      u.go('workshop');
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl83({
    api,
    m,
    saved
  }, event) {
    const handler = () => saved(() => api.setConnection(m.id, {
      connected: true
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellCheckAgain84({
    api,
    m,
    u
  }, event) {
    const handler = () => u.act(() => api.checkConnection(m.id));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellDisconnect85({
    api,
    c,
    m,
    u
  }, event) {
    const handler = () => u.confirm('Disconnect ' + c.name + '?', () => api.setConnection(m.id, {
      connected: false
    }));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSignInWithYourBrowser86({
    api,
    saved
  }, event) {
    const handler = () => saved(() => api.signIn(true));
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellContinueAndSignInLater87({
    close
  }, event) {
    const handler = close;
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl88({
    api,
    listening,
    u,
    talk
  }, event) {
    const handler = () => listening ? u.act(api.stopVoiceInput) : talk();
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellUseSentence89({
    close,
    m,
    text
  }, event) {
    const handler = () => {
      close();
      m.onText?.(text);
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSendToBABOOM90({
    api,
    text,
    u
  }, event) {
    const handler = async () => {
      const t = await u.act(() => api.sendToBaboom(text));
      if (t) {
        u.setTask(t.id);
        u.go('workshop');
      }
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSend91({
    api,
    m,
    u
  }, event) {
    const handler = async () => {
      const t = await u.act(() => api.sendToBaboom(m.text));
      if (t) {
        u.setTask(t.id);
        u.go('workshop');
      }
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellUseExample92({
    api,
    c,
    u
  }, event) {
    const handler = async () => {
      const n = await u.act(() => api.addNode(c.name));
      if (n) {
        await u.act(() => api.setNodeParam(n.id, 'example', 'Level 3'));
        u.go('canvas');
      }
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellExport93({
    r,
    u
  }, event) {
    const handler = () => u.download('Run ' + r.id);
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellReviewChange94({
    api,
    m,
    text,
    u
  }, event) {
    const handler = async () => {
      const t = await u.act(() => api.sendToBaboom(m.action + ' inside the mask: ' + (text || 'selected area')));
      if (t) u.show('Approve', {
        id: t.approvalId
      });
    };
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellOpenTeam95({
    u
  }, event) {
    const handler = () => u.go('colleagues');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellUpdatesAbout96({
    u
  }, event) {
    const handler = () => u.go('updates');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellOpenDocs97({
    u
  }, event) {
    const handler = () => u.go('docs');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellCloseDialog98({
    close
  }, event) {
    const handler = close;
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRetryView({
    boundary
  }) {
    return boundary.setState({
      error: null
    });
  }
  const appShellActions = {
    "appShell.RetryWorkshop": "appShellRetryWorkshop",
    "appShell.RetryView": "appShellRetryView",
    "appShell.ArchHubMenu.1": "appShellArchHubMenu1",
    "appShell.ArchHub.2": "appShellArchHub2",
    "appShell.Control.3": "appShellControl3",
    "appShell.Control.4": "appShellControl4",
    "appShell.SearchCtrlK.5": "appShellSearchCtrlK5",
    "appShell.Notifications.6": "appShellNotifications6",
    "appShell.TrayMenu.7": "appShellTrayMenu7",
    "appShell.Minimize.8": "appShellMinimize8",
    "appShell.CloseWindow.9": "appShellCloseWindow9",
    "appShell.Control.10": "appShellControl10",
    "appShell.Control.11": "appShellControl11",
    "appShell.YourAccount.12": "appShellYourAccount12",
    "appShell.Control.13": "appShellControl13",
    "appShell.RunningWaitForYou.14": "appShellRunningWaitForYou14",
    "appShell.CtrlK.15": "appShellCtrlK15",
    "appShell.Receipts.16": "appShellReceipts16",
    "appShell.Dismiss.17": "appShellDismiss17",
    "appShell.Control.18": "appShellControl18",
    "appShell.AcceptDraft.19": "appShellAcceptDraft19",
    "appShell.Dismiss.20": "appShellDismiss20",
    "appShell.RequestReview.21": "appShellRequestReview21",
    "appShell.Save.22": "appShellSave22",
    "appShell.Save.23": "appShellSave23",
    "appShell.Control.24": "appShellControl24",
    "appShell.AddGraph.25": "appShellAddGraph25",
    "appShell.RestartAndUpdate.26": "appShellRestartAndUpdate26",
    "appShell.ReadStatus.27": "appShellReadStatus27",
    "appShell.AddParameter.28": "appShellAddParameter28",
    "appShell.Control.29": "appShellControl29",
    "appShell.Control.30": "appShellControl30",
    "appShell.Cancel.31": "appShellCancel31",
    "appShell.Confirm.32": "appShellConfirm32",
    "appShell.Control.33": "appShellControl33",
    "appShell.AccountSettings.34": "appShellAccountSettings34",
    "appShell.SignOut.35": "appShellSignOut35",
    "appShell.Save.36": "appShellSave36",
    "appShell.Disconnect.37": "appShellDisconnect37",
    "appShell.ConnectAnAccount.38": "appShellConnectAnAccount38",
    "appShell.AddFile.39": "appShellAddFile39",
    "appShell.Open.40": "appShellOpen40",
    "appShell.Remove.41": "appShellRemove41",
    "appShell.Control.42": "appShellControl42",
    "appShell.Settings.43": "appShellSettings43",
    "appShell.OpenArchHub.44": "appShellOpenArchHub44",
    "appShell.BABOOM.45": "appShellBABOOM45",
    "appShell.StopEverything.46": "appShellStopEverything46",
    "appShell.Hide.47": "appShellHide47",
    "appShell.Quit.48": "appShellQuit48",
    "appShell.Control.49": "appShellControl49",
    "appShell.Review.50": "appShellReview50",
    "appShell.AddSchedule.51": "appShellAddSchedule51",
    "appShell.Start.52": "appShellStart52",
    "appShell.AddAsNode.53": "appShellAddAsNode53",
    "appShell.RunEveryDay.54": "appShellRunEveryDay54",
    "appShell.Output.55": "appShellOutput55",
    "appShell.Control.56": "appShellControl56",
    "appShell.Control.57": "appShellControl57",
    "appShell.RunToHere.58": "appShellRunToHere58",
    "appShell.Open.59": "appShellOpen59",
    "appShell.Rerun.60": "appShellRerun60",
    "appShell.Fork.61": "appShellFork61",
    "appShell.RepeatThis.62": "appShellRepeatThis62",
    "appShell.TraceBack.63": "appShellTraceBack63",
    "appShell.TraceForward.64": "appShellTraceForward64",
    "appShell.Ungroup.65": "appShellUngroup65",
    "appShell.Delete.66": "appShellDelete66",
    "appShell.AddNode.67": "appShellAddNode67",
    "appShell.Arrange.68": "appShellArrange68",
    "appShell.GroupCtrlG.69": "appShellGroupCtrlG69",
    "appShell.SaveAsSkill.70": "appShellSaveAsSkill70",
    "appShell.Delete.71": "appShellDelete71",
    "appShell.ExposeOnCanvas.72": "appShellExposeOnCanvas72",
    "appShell.OpenSystemGraph.73": "appShellOpenSystemGraph73",
    "appShell.InsertConvert.74": "appShellInsertConvert74",
    "appShell.Control.75": "appShellControl75",
    "appShell.Save.76": "appShellSave76",
    "appShell.AddComment.77": "appShellAddComment77",
    "appShell.Invite.78": "appShellInvite78",
    "appShell.Apply.79": "appShellApply79",
    "appShell.SaveSkill.80": "appShellSaveSkill80",
    "appShell.AgentSettings.81": "appShellAgentSettings81",
    "appShell.MessageInWorkshop.82": "appShellMessageInWorkshop82",
    "appShell.Control.83": "appShellControl83",
    "appShell.CheckAgain.84": "appShellCheckAgain84",
    "appShell.Disconnect.85": "appShellDisconnect85",
    "appShell.SignInWithYourBrowser.86": "appShellSignInWithYourBrowser86",
    "appShell.ContinueAndSignInLater.87": "appShellContinueAndSignInLater87",
    "appShell.Control.88": "appShellControl88",
    "appShell.UseSentence.89": "appShellUseSentence89",
    "appShell.SendToBABOOM.90": "appShellSendToBABOOM90",
    "appShell.Send.91": "appShellSend91",
    "appShell.UseExample.92": "appShellUseExample92",
    "appShell.Export.93": "appShellExport93",
    "appShell.ReviewChange.94": "appShellReviewChange94",
    "appShell.OpenTeam.95": "appShellOpenTeam95",
    "appShell.UpdatesAbout.96": "appShellUpdatesAbout96",
    "appShell.OpenDocs.97": "appShellOpenDocs97",
    "appShell.CloseDialog.98": "appShellCloseDialog98"
  };
  window.registerActions(appShellActions, {
    appShellRetryWorkshop: ({reloadWorkshop}) => reloadWorkshop(),
    appShellRetryView,
    appShellArchHubMenu1,
    appShellArchHub2,
    appShellControl3,
    appShellControl4,
    appShellSearchCtrlK5,
    appShellNotifications6,
    appShellTrayMenu7,
    appShellMinimize8,
    appShellCloseWindow9,
    appShellControl10,
    appShellControl11,
    appShellYourAccount12,
    appShellControl13,
    appShellRunningWaitForYou14,
    appShellCtrlK15,
    appShellReceipts16,
    appShellDismiss17,
    appShellControl18,
    appShellAcceptDraft19,
    appShellDismiss20,
    appShellRequestReview21,
    appShellSave22,
    appShellSave23,
    appShellControl24,
    appShellAddGraph25,
    appShellRestartAndUpdate26,
    appShellReadStatus27,
    appShellAddParameter28,
    appShellControl29,
    appShellControl30,
    appShellCancel31,
    appShellConfirm32,
    appShellControl33,
    appShellAccountSettings34,
    appShellSignOut35,
    appShellSave36,
    appShellDisconnect37,
    appShellConnectAnAccount38,
    appShellAddFile39,
    appShellOpen40,
    appShellRemove41,
    appShellControl42,
    appShellSettings43,
    appShellOpenArchHub44,
    appShellBABOOM45,
    appShellStopEverything46,
    appShellHide47,
    appShellQuit48,
    appShellControl49,
    appShellReview50,
    appShellAddSchedule51,
    appShellStart52,
    appShellAddAsNode53,
    appShellRunEveryDay54,
    appShellOutput55,
    appShellControl56,
    appShellControl57,
    appShellRunToHere58,
    appShellOpen59,
    appShellRerun60,
    appShellFork61,
    appShellRepeatThis62,
    appShellTraceBack63,
    appShellTraceForward64,
    appShellUngroup65,
    appShellDelete66,
    appShellAddNode67,
    appShellArrange68,
    appShellGroupCtrlG69,
    appShellSaveAsSkill70,
    appShellDelete71,
    appShellExposeOnCanvas72,
    appShellOpenSystemGraph73,
    appShellInsertConvert74,
    appShellControl75,
    appShellSave76,
    appShellAddComment77,
    appShellInvite78,
    appShellApply79,
    appShellSaveSkill80,
    appShellAgentSettings81,
    appShellMessageInWorkshop82,
    appShellControl83,
    appShellCheckAgain84,
    appShellDisconnect85,
    appShellSignInWithYourBrowser86,
    appShellContinueAndSignInLater87,
    appShellControl88,
    appShellUseSentence89,
    appShellSendToBABOOM90,
    appShellSend91,
    appShellUseExample92,
    appShellExport93,
    appShellReviewChange94,
    appShellOpenTeam95,
    appShellUpdatesAbout96,
    appShellOpenDocs97,
    appShellCloseDialog98
  });
})();
