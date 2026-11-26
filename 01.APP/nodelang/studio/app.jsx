(() => {
  function executeAction(...args) {
    return window.executeAction(...args);
  }
  // The ArchHub mark: the paths of data/website/favicon.svg (the one source), portrait, never rotated or cropped.
  function ArchMark({size}) {
    return <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true" focusable="false"><path d="M10 56 V32 a22 22 0 0 1 44 0 V56" fill="none" stroke="#d97757" strokeWidth="4.5" strokeLinecap="square" /><circle cx="32" cy="22" r="5.2" fill="#0e0e11" stroke="#d97757" strokeWidth="2.4" /><circle cx="32" cy="22" r="1.8" fill="#d97757" /><path d="M6 58 H58" stroke="#d97757" strokeWidth="1.5" strokeLinecap="round" /></svg>;
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
  // v22g applyLook: the approved palette's contrast calculation, shared by these controls.
  function canvasColours(light) {
    const style=window.getComputedStyle(document.documentElement), read=key=>style.getPropertyValue('--color-'+key).trim();
    if(!['bg-panel','bg-canvas','accent','accent-hi','accent-press','ink-soft'].every(key=>/^#[0-9a-f]{6}$/i.test(read(key))))return;
    const rgb=value=>value.slice(1).match(/../g).map(part=>parseInt(part,16));
    const mix=(a,b,k)=>'#'+rgb(a).map((value,i)=>Math.round(value*(1-k)+rgb(b)[i]*k).toString(16).padStart(2,'0')).join('');
    const lum=value=>rgb(value).map(value=>{const c=value/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
    const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
    const panel=read('bg-panel'),toward=light?'#000000':'#ffffff',accent=read('accent');
    const surfaces=[panel,mix(panel,toward,.035),mix(panel,toward,.045),mix(panel,toward,.07),read('bg-canvas'),mix(panel,'#000000',light?.02:.33)];
    const ensure=(fg,backgrounds)=>{let value=fg,k=0;while(backgrounds.some(bg=>ratio(value,bg)<4.6)&&k<1){k+=.03;value=mix(fg,toward,k);}return value;};
    const soft=mix(accent,panel,light?.86:.8),set=(key,value)=>document.documentElement.style.setProperty('--v22g-'+key,value);
    set('hover',surfaces[3]);set('accent-soft',soft);set('accent-ink',ensure(read(light?'accent-press':'accent-hi'),[...surfaces,soft,mix(soft,accent,.2)]));
    set('ink2',ensure(read('ink-soft'),surfaces));set('ink3',ensure(mix(read('ink-soft'),panel,.2),surfaces));
  }
  const DESKTOP_SIGNIN_ACTIONS={'appShell.DesktopSignIn':'SignIn','appShell.DesktopRetry':'Retry'};
  const DESKTOP_QUIT_ACTIONS={'appShell.DesktopQuit':'Quit'};
  function QuitDesktop(){const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(DESKTOP_QUIT_ACTIONS,{Quit:()=>api.windowAction('quit')});return <><Btn ghost onClick={event=>runAction('appShell.DesktopQuit',event)}>Quit ArchHub</Btn><window.UI.RegisteredActionStatus state={actionState} retry={retryAction}/></>;}
  function SignInControls() {
    const s=useData(),access=s.desktopAccess||{};
    const start=async()=>{
      try { await api.signIn(true); }
      catch { throw Error('Could not start sign-in. Check your connection and choose Retry.'); }
    };
    const {runAction,actionState,retryAction}=window.UI.useRegisteredActions(DESKTOP_SIGNIN_ACTIONS,{
      SignIn:start,
      Retry:()=>access.notice?start():api.refreshDesktopAccess(true),
    });
    const busy=actionState.status==='waiting';
    return <><p>Sign in to archhub.io to use ArchHub. An internet connection is required.</p><p role="status">{access.admitted?'Opening your workspace…':access.notice||(access.signingIn?'Complete sign-in in your browser.':access.state==='pending'?'Checking your account…':access.state==='unavailable'?'Connection lost. Reconnect to continue.':access.state==='session_invalid'?'Your session could not be verified. Sign in again.':'Sign in with your account to continue.')}</p>{actionState.status!=='loaded'&&<window.UI.RegisteredActionStatus state={actionState} retry={retryAction}/>}<div className="flex"><Btn p disabled={busy} onClick={event=>runAction('appShell.DesktopSignIn',event)}>Sign in with your browser</Btn><Btn disabled={busy} onClick={event=>runAction('appShell.DesktopRetry',event)}>Retry</Btn><QuitDesktop/></div></>;
  }
  function DesktopSignIn() {

    return <main className="grid" data-desktop-admission style={{minHeight:'100vh',placeContent:'center',padding:32}}><Card style={{padding:32,maxWidth:480}}><ArchMark size={56}/><h1>ArchHub</h1><SignInControls/></Card></main>;
  }
  function DesktopEntry() {
    const s=useData(),opened=React.useRef(null),access=s.desktopAccess||{};
    if(window.ARCHHUB_NATIVE_APPROVAL)return <App/>;
    if(access.admitted&&access.ready)opened.current=access.subject;
    if(!opened.current)return <DesktopSignIn/>;
    return <App key={opened.current} desktopAccess={access}/>;
  }
  function App({desktopAccess}) {
    const s = useData();
    const restoredView=api.readDesktopView?.()||{};
    const [route, setRoute] = React.useState(restoredView.route||'home'),  // SPEC § and founder 2026-11-02: the app opens on Home; the task session stays on that page
      [canvasOpened, setCanvasOpened] = React.useState(restoredView.canvasOpened||false),
      [task, setTask] = React.useState(restoredView.task||''),
      [taskFace, setTaskFace] = React.useState(restoredView.taskFace||'canvas'),  // the thread pane beside the canvas: one value, the same from one session to the next
      [composerDraft, setComposerDraft] = React.useState(restoredView.composerDraft||{}),
      [modal, setModal] = React.useState(null),
      [toast, setToast] = React.useState(''),
      [toastPaused, setToastPaused] = React.useState(false),
      [advanced, setAdvanced] = React.useState(false),
      [companion, setCompanion] = React.useState(false),
      [homeThreadId, setHomeThreadId] = React.useState(null),
      [libraryOpen, setLibraryOpen] = React.useState(true),  // design v63: the Library sits in its dock by default; he hides it
      [selectedNodeId, setSelectedNodeId] = React.useState(null);
    const [agentLoad, setAgentLoad] = React.useState({status: 'empty'});
    const [canvasTabs, setCanvasTabs] = React.useState({tabs: [], active: '', split: '', collapsed: false});
    const tabsRef = React.useRef(canvasTabs), tabWrites = React.useRef(Promise.resolve());
    const saveCanvasTabs = value => {
      tabsRef.current = value;
      setCanvasTabs(value);
      const write = tabWrites.current.then(() => api.setCanvasTabs(value));
      tabWrites.current = write.catch(error => setToast(error.message));
      return write;
    };
    React.useEffect(() => {
      let live = true;
      api.readCanvasTabs().then(result => {
        if (live && result.canvasTabs) { tabsRef.current = result.canvasTabs; setCanvasTabs(result.canvasTabs); }
      }).catch(error => setToast(error.message));
      return () => {live = false;};
    }, []);
    React.useEffect(()=>{if(desktopAccess?.admitted&&desktopAccess.ready)api.rememberDesktopView({route,canvasOpened,task,taskFace,composerDraft});},[route,canvasOpened,task,taskFace,composerDraft,desktopAccess?.admitted,desktopAccess?.ready]);
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
    // The document theme is rewritten only when an appearance value changes. Keyed on every store revision, it
    // reset root CSS variables (a whole-document style recalculation) on every refresh, drag drop and fold.
    const arabic = s.settings.find(row => row.id === 'Account.App language')?.value === 'Arabic';
    const direction = s.settings.find(row => row.id === 'Account.Right-to-left layout')?.value || 'Auto';
    React.useEffect(() => {
      document.documentElement.lang = arabic ? 'ar' : 'en';
      document.documentElement.dir = direction === 'Always' || (direction === 'Auto' && arabic) ? 'rtl' : 'ltr';
    }, [arabic, direction]);
    const navLabel = label => window.UI.productLabel(label, s.settings);
    const appearanceKey = JSON.stringify(s.settings.filter(r => String(r.id).startsWith('Appearance.')).map(r => [r.id, r.value]));
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
      const preference = window.matchMedia('(prefers-color-scheme: dark)');
      const applyTheme = () => { document.documentElement.dataset.theme = theme === 'System' ? (preference.matches ? 'Dark' : 'Light') : theme; canvasColours(document.documentElement.dataset.theme==='Light'); };
      applyTheme();
      if (theme === 'System') preference.addEventListener('change', applyTheme);
      document.documentElement.dataset.contrast = String(s.settings.find(r => r.id === 'Appearance.High contrast')?.value);
      document.documentElement.style.setProperty('--text-scale', (s.settings.find(r => r.id === 'Appearance.Text scale')?.value || 100) / 100);
      for (const [id, token, unit] of [['Appearance.Inspector width','--layout-inspector-width','px'],['Appearance.Row spacing','--layout-node-row-gap','px'],['Appearance.Node radius','--node-radius','px']]) {
        const row=s.settings.find(item=>item.id===id);
        if(row) document.documentElement.style.setProperty(token,row.value+unit);
      }
      document.documentElement.dataset.grid = String(s.settings.find(r => r.id === 'Appearance.Canvas grid')?.value !== false);
      document.documentElement.dataset.reducedMotion = String(s.settings.find(r => r.id === 'Appearance.Reduce motion')?.value === true);
      for (const token of ['--color-accent', '--color-accent-hi', '--color-accent-press']) {
        if (accent === '#d97757') document.documentElement.style.removeProperty(token);
        else document.documentElement.style.setProperty(token, accent);
      }
      return () => preference.removeEventListener('change', applyTheme);
    }, [theme, accent, appearanceKey]);
    React.useEffect(() => {
      const notice = event => setToast(event.detail.message);
      window.addEventListener("archhub:notice", notice);
      return () => window.removeEventListener("archhub:notice", notice);
    }, []);
    React.useEffect(() => {
      const openHome = () => { if(!api.getSnapshot().desktopAccess?.admitted&&!window.ARCHHUB_NATIVE_APPROVAL)return;api.setActiveSurface?.('home'); setRoute('home'); setModal(null); };
      window.addEventListener('archhub:open-home', openHome);
      return () => window.removeEventListener('archhub:open-home', openHome);
    }, []);
    React.useEffect(() => {
      // A click on BABOOM, who stands beside the composer: his panel opens or closes (the composer points at him, ui.jsx).
      const askBaboom = event => setCompanion(open => {
        const next = !!event.detail?.text || !open, snap = api.getSnapshot(), dm = window.UI.dockModel, cur = dm?.normalize(snap.dockLayout?.layout, window.innerWidth);
        if (next && !event.detail?.text && cur && (snap.approvals || []).some(a => a.status === 'pending' || a.status === 'approval')) { const shown = dm.show(cur, 'workshop'); if (shown !== cur) void api.setDockLayout?.(shown); }
        return next;
      });
      window.addEventListener('archhub:ask-baboom', askBaboom);
      return () => window.removeEventListener('archhub:ask-baboom', askBaboom);
    }, []);
    const settingsOrigin = React.useRef('home');
    React.useEffect(() => {
      if (window.performance.getEntriesByType?.('navigation')?.[0]?.type === 'reload'
          && s.sessionFile && !api.getSessionDocument?.()?.properties?.taskContext) {
        setTask('');
        setCanvasOpened(true);
        api.setActiveSurface?.('canvas');
        setRoute('canvas');
      }
    }, [s.sessionFile]);
    const navigation = React.useRef(0);
    const viewedCanvas = React.useRef('');
    React.useEffect(() => {
      if (route === 'canvas') viewedCanvas.current = api.getSessionPath?.() || '';
    }, [route, s.sessionFile]);
    const go = async (r, taskId = '') => {
      const visit = ++navigation.current;
      if (r === 'system') r = 'settings/System graph';
      if (r === 'baboom') {
        setCompanion(true);
        setModal(null);
        return;
      }
      const document = api.getSessionDocument?.();
      const currentPath = api.getSessionPath?.();
      const currentTask = document?.properties?.taskContext?.task;
      const unboundCanvas = r === 'canvas' && document && (
        (taskId && taskId === currentPath) || (!taskId && !currentTask && (currentPath || api.hasSessionEdits?.() || canvasOpened))
      );
      const resumeCanvas = r === 'canvas' && !taskId;
      const keepDocument = api.hasSessionEdits?.() || (document && !currentPath) || (currentPath && currentPath === viewedCanvas.current);
      const home = !unboundCanvas && window.UI.homeDestination?.(r);
      if (unboundCanvas) setTask('');
      if (home) {
        if (home.library) setLibraryOpen(true);
        const tasks = resumeCanvas ? s.tasks.filter(row => !window.UI.isHomeRegistration(row) && row.status !== 'ARCHIVED') : s.tasks;
        const selected = taskId ? tasks.find(t => t.id === taskId || t.sessionPath === taskId)
          : tasks.find(t => t.id === task) || tasks.find(t => t.id === s.focusedTask)
            || (route === 'home' && r === 'canvas' ? tasks.find(t => t.id === window.UI.homeShown?.()) : undefined);  // the open session wins; from Home, Canvas opens the session Home shows selected
        const currentRow = s.tasks.find(row => row.id === currentTask);
        const currentEligible = currentTask && !window.UI.isHomeRegistration(currentRow || {id:currentTask}) && currentRow?.status !== 'ARCHIVED';
        if (resumeCanvas && currentTask && (keepDocument || (currentEligible && (!selected || selected.id === currentTask)))) {
          setTask(currentTask);
          setTaskFace('canvas');
          r = currentEligible && tasks.some(row => row.id === currentTask) ? 'task-file' : 'canvas';
        } else if (selected) {
          return openTaskFile(selected.id, home.face);
        } else if (r === 'canvas' && !taskId) {
          // Resume a saved task even before the Workshop has published its task rows.
          const listing = await act(() => api.listSessionModel());
          if (!listing || visit !== navigation.current) return;
          const recent = !api.hasSessionEdits?.() && window.UI.homeSessionToResume(listing, [s.homeLayout?.resume, tabsRef.current.active, s.focusedTask]);
          if (recent) {
            const opened = await act(() => api.openSession(recent.path));
            if (!opened || opened.cancelled || visit !== navigation.current) return;
            setTask(recent.task);
            setTaskFace('canvas');
            r = s.tasks.some(row => row.id === recent.task) ? 'task-file' : 'canvas';
          } else {
            if (currentTask && !currentEligible && !api.hasSessionEdits?.()) {
              const blank = await act(() => api.newSession());
              if (!blank || blank.cancelled || visit !== navigation.current) return;
            }
            setTask('');
          }
        } else {
          setTask('');
          setToast('Pick a task on Home.');
          r = 'home';
        }
      }
      if (r.startsWith('settings/') && !route.startsWith('settings/')) settingsOrigin.current = route;
      if(r==='canvas')setCanvasOpened(true);
      else if(homeInspector?.path)setHomeInspector(null);
      api.setActiveSurface?.(r);
      setRoute(r);
      setModal(null);
      return;
    };
    const show = (kind, data = {}) => {
      if (modalActions[kind] && !api.supportsAction(modalActions[kind])) return;
      if(kind==='Search'){
        data = {...data,commandContext: data.commandContext || (window.UI.commandContextNames?.[modal?.kind] ? modal : ['canvas','task-file'].includes(route) ? window.UI.canvasCommandContext?.({clientX:menuAnchor.current.x,clientY:menuAnchor.current.y}) : null)};
      }
      priorFocus.current = data.restoreFocus || document.activeElement;
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
    const [homeInspector,setHomeInspector] = React.useState(null);
    const openTaskFile = async (id, face = taskFace) => {
      const opened = await act(() => api.openTaskGraph(id));
      if (!opened || opened.cancelled) return;
      const held = tabsRef.current;
      const title = String(api.getSnapshot().tasks?.find(row => row.id === id)?.title || '').replace(/[\u0000-\u001f]/g, ' ').slice(0, 300);
      const named = tab => tab.id === id && title ? {...tab, title} : tab;
      const tabs = held.tabs.some(tab => tab.id === id) ? held.tabs.map(named) : [...held.tabs.filter(tab => tab.kept || tab.id === held.split), named({id, kept: false})];
      await act(() => saveCanvasTabs({...held, tabs, active: id, split: held.split === id ? '' : held.split}));
      setTask(id);
      setTaskFace(face === 'workshop' ? 'split' : face);
      go('task-file');
      return opened;
    };
    const keepTaskTab = id => saveCanvasTabs({...tabsRef.current, tabs: tabsRef.current.tabs.map(tab => tab.id === id ? {...tab, kept: true} : tab)});
    React.useEffect(()=>{
      const id=tabsRef.current.active || api.getSessionDocument?.()?.properties?.taskContext?.task;
      const tab=tabsRef.current.tabs.find(tab=>tab.id===id);
      if(tab && !tab.kept && (api.hasSessionEdits?.() || s.graph.nodes.some(node=>node.status==='Running')))keepTaskTab(id).catch(error=>setToast(error.message));
    },[s.sessionDirty,s.graph.nodes]);
    const openTaskBeside = id => {
      if (id === task) return;
      const held=tabsRef.current, tabs=held.tabs.some(tab=>tab.id===id) ? held.tabs : [...held.tabs,{id,kept:true}];
      return saveCanvasTabs({...held,tabs:tabs.map(tab=>tab.id===task||tab.id===id?{...tab,kept:true}:tab),split:id});
    };
    const closeTaskTab = async id => {
      const held = tabsRef.current, tabs = held.tabs.filter(tab => tab.id !== id);
      const active = held.active === id ? tabs.at(-1)?.id || '' : held.active;
      if (held.active === id && active) {
        const opened = await act(() => api.openTaskGraph(active));
        if (!opened || opened.cancelled) return;
      }
      await saveCanvasTabs({...held, tabs, active, split: held.split === id || held.split === active ? '' : held.split});
      if (task === id) {setTask(active); if (!active) go('home');}
    };
    const confirm = (title, run, opts = {}) => show('Confirm', {
      title,
      run,
      ...opts
    });
    const settingValue = (id, fallback = '') => {
      const row = (s.settings || []).find(item => item.id === id);
      return row && row.value !== undefined ? row.value : fallback;
    };
    const userPhoto = s.profile?.photo ?? settingValue('Account.Photo', '');
    const userRole = s.profile?.role ?? settingValue('Account.Your role', '');
    const userPresence = s.profile?.presence || settingValue('Account.Presence status', 'Available') || 'Available';
    const userDisplayName = s.profile?.name || settingValue('Account.Display name', '');
    const saveProfileFields = patch => act(async () => {
      if ('saveProfile' in api && typeof api.saveProfile === 'function') return api.saveProfile(patch);
      const map = {name: 'Account.Display name', role: 'Account.Your role', presence: 'Account.Presence status', photo: 'Account.Photo'};
      if (typeof api.updateProfile === 'function' && (s.profile?.signedIn || !s.settingsDestination)) {
        try {
          const updated = await api.updateProfile(patch);
          if (updated && updated.ok !== false) return updated;
        } catch (err) {
          if (!s.settingsDestination) throw err;
        }
      }
      let last = {ok: true};
      for (const [k, v] of Object.entries(patch)) {
        const settingId = map[k];
        if (settingId && typeof api.setSetting === 'function') {
          last = await api.setSetting(settingId, v, s.settingsDestination);
        } else if (typeof api.updateProfile === 'function') {
          last = await api.updateProfile({[k]: v});
        }
      }
      return last;
    });
    const pinnedRailIds = Array.isArray(s.railTasks)
      ? s.railTasks.map(item => typeof item === 'string' ? item : item.id).filter(Boolean)
      : Array.isArray(canvasTabs.rail)
        ? canvasTabs.rail
        : (canvasTabs.tabs || []).filter(t => t.pinned).map(t => t.id);
    const setPinnedRail = async nextIds => {
      const unique = [...new Set(nextIds.filter(Boolean))];
      if (typeof api.setRailTasks === 'function') await act(() => api.setRailTasks(unique));
      return saveCanvasTabs({...tabsRef.current, rail: unique});
    };
    const pinTaskToRail = id => setPinnedRail([...pinnedRailIds, id]);
    const schedule = id => show('Schedule', {
      id
    });
    const timing = key => {
      const value = s.runtimeParameters?.[key];
      return Number.isSafeInteger(value) && value > 0 ? value : null;
    };
    const download = async (name, nodeId) => {
      const duration = timing('export_release_ms') ?? 1000;
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
    const pickFile = () => act(async () => { const file = await api.addFile(); if (file) return api.addComposerAttachment(file.id); return null; });
    const openSavedSession = async (path, linkedParams) => {
      const opened = await act(() => api.openSession(path,false,linkedParams));
      if (opened && !opened.cancelled) await go('canvas', api.getSessionPath?.() || path);
      return opened || null;
    };
    const value = {
      modal,
      selectedNodeId,
      setSelectedNodeId,
      composerDraft,
      setComposerDraft,
      companion,
      setCompanion,
      setHomeThreadId,
      libraryOpen,
      setLibraryOpen,
      route,
      task,
      setTask,
      taskFace,
      setTaskFace,
      canvasTabs,
      saveCanvasTabs,
      pinnedRailIds,
      setPinnedRail,
      pinTaskToRail,
      saveProfileFields,
      userPhoto,
      userRole,
      userPresence,
      userDisplayName,
      keepTaskTab,
      openTaskBeside,
      closeTaskTab,
      homeInspector, setHomeInspector,
      settingsOrigin: settingsOrigin.current,
      openTaskFile,
      openSavedSession,
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
      pickFile,
      setToast
    };
    const menuApp = React.useRef(value);
    menuApp.current = value;
    React.useEffect(() => {
      setToastPaused(false);
    }, [toast]);
    React.useEffect(() => {
      const duration = timing('toast_visible_ms');
      if (!toast || toastPaused || duration === null) return;
      const t = setTimeout(() => setToast(''), duration);
      return () => clearTimeout(t);
    }, [toast, toastPaused, s.runtimeParameters?.toast_visible_ms]);
    React.useEffect(() => {
      const openSurfaceMenu = e => {
        const current = api.getSnapshot();
        if (current.desktopAccess?.admitted || window.ARCHHUB_NATIVE_APPROVAL)
          window.UI.openSurfaceMenu(e, current, menuApp.current);
      };
      const key = e => {
        if(!api.getSnapshot().desktopAccess?.admitted&&!window.ARCHHUB_NATIVE_APPROVAL)return;
        if(e.defaultPrevented||e.isComposing)return;
        const typing=e.target.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]');
        if (!typing && !modal && window.UI.keyboardContextMenu(e)) return;
        const match=id=>(!typing||e.ctrlKey||e.metaKey)&&window.UI.matchesShortcut(id,e);
        if (match('keyboard.new_task')) {
          e.preventDefault(); show('New task'); return;
        }
        if (route === 'task-file') {
          if (match('menu.show.the.thread')) {e.preventDefault();setTaskFace(taskFace === 'split' ? 'canvas' : 'split');return;}
          if (match('menu.close.tab')) {e.preventDefault();act(() => closeTaskTab(task));return;}
          if (match('keyboard.next_tab') || match('keyboard.previous_tab')) {
            e.preventDefault(); const tabs = tabsRef.current.tabs, index = tabs.findIndex(tab => tab.id === task);
            if (tabs.length) openTaskFile(tabs[(index + (match('keyboard.next_tab') ? 1 : -1) + tabs.length) % tabs.length].id);
            return;
          }
        }
        if (match('keyboard.search')) {
          e.preventDefault();
          show('Search');
        }
        if (e.ctrlKey && e.shiftKey && e.key === '>') {
          e.preventDefault();
          act(api.stopEverything);
        }
        if (match('keyboard.voice') && api.supportsAction('startVoiceInput')) {
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
        if(match('menu.settings')){e.preventDefault();go('settings/Account');return;}
        if (e.key === 'Escape') {
          if (modal) close();
          else if (companion) setCompanion(false);
          else if (!['home','task-file','canvas'].includes(route)) go('home');
          // A session's canvas goes back to Home on Esc once nothing on it takes the Esc (a selection, a group, Focus mode, a field).
          else if (route === 'task-file' && !e.defaultPrevented && !e.target?.closest?.('input,textarea,select,[contenteditable="true"],[role="menu"],[role="dialog"]')
            && !document.querySelector('.dockws.focus-mode, [data-design="group.breadcrumb"], .react-flow__node.selected, .react-flow__edge.selected, .context-menu, .dtab-menu-pop')) go('home');
        }
        if (e.key === 'Tab' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && !modal && ['home', 'canvas', 'task-file'].includes(route)
            && !e.target.isContentEditable && e.target.contentEditable !== 'true'
            && !e.target.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],[role="dialog"],[role="menu"]')) {
          e.preventDefault();
          const snap = api.getSnapshot(), dm = window.UI.dockModel;
          if ((route === 'home' || route === 'task-file') && dm && snap.dockLayout) {
            const cur = dm.normalize(snap.dockLayout.layout, window.innerWidth);
            const nextOpen = !dm.visible(cur, 'library');
            setLibraryOpen(nextOpen);
            const nextLayout = nextOpen ? dm.show(cur, 'library') : dm.hide(cur, 'library');
            if (nextLayout !== cur) void api.setDockLayout?.(nextLayout);
          } else {
            setLibraryOpen(open => !open);
          }
          return;
        }
        if (e.key === '/' && !e.target.matches('input,textarea,select')) {
          e.preventDefault();
          show('Search');
        }
        if ((match('menu.undo')||match('menu.redo')) && !e.target.isContentEditable && e.target.contentEditable !== 'true' && !e.target.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]')) {
          e.preventDefault();
          act(match('menu.redo') ? api.redo : api.undo);
        }
      };
      const up = e => {
        if (e.code === 'Space') clearTimeout(talkTimer.current);
      };
      window.addEventListener('contextmenu', openSurfaceMenu);
      window.addEventListener('keydown', key);
      window.addEventListener('keyup', up);
      return () => {
        window.removeEventListener('contextmenu', openSurfaceMenu);
        window.removeEventListener('keydown', key);
        window.removeEventListener('keyup', up);
        clearTimeout(talkTimer.current);
      };
    }, [modal, companion, route, task, taskFace]);
    React.useEffect(() => {
      const openRequestedTask = event => {
        if(!api.getSnapshot().desktopAccess?.admitted&&!window.ARCHHUB_NATIVE_APPROVAL)return;
        const id = event.detail?.task_id;
        if (typeof id === 'string' && id.trim()) openTaskFile(id);
      };
      window.addEventListener('archhub:open-task', openRequestedTask);
      return () => window.removeEventListener('archhub:open-task', openRequestedTask);
    }, [s.tasks, openTaskFile]);
    React.useEffect(() => {
      document.title = 'ArchHub · ' + ((route.startsWith("settings/") ? "Settings" : route === "task-file" ? (taskFace === "workshop" ? "Workshop" : "Canvas") : routeNames[route]) || route.split('/').at(-1));
    }, [route, taskFace, desktopAccess?.admitted]);
    const rail = [['home', 'Home', 'home'], ['canvas', 'Canvas', 'canvas']];
    const screen = route === 'meetings' ? <window.UI.Meetings /> : route === 'present' ? <window.UI.Present /> : route === 'community' ? <window.UI.Community /> : route === 'model-review' ? <window.UI.ModelReview /> : route === 'interface' ? <window.UI.InterfaceStudio /> : route === 'social' ? <window.UI.Social /> : route === 'xray' ? <window.UI.Xray /> : route === 'access' ? <window.UI.Access /> : route === 'routing' ? <window.UI.Routing /> : route === 'home' ? <window.UI.Home key="home" /> : route === 'task-file' ? <window.UI.Home key={task} fileWorkspace /> : route === 'workshop' ? <window.UI.Workshop /> : route === 'canvas' ? null : route === 'system' ? <window.UI.Settings page="System graph" /> : route === 'agents' ? <window.UI.AgentsCanvas /> : route === 'colleagues' ? <window.UI.Colleagues /> : route === 'brain' ? <window.UI.Brain /> : route === 'watcher' ? <window.UI.Watcher /> : route === 'first-run' ? <window.UI.FirstRun /> : route === 'runs' ? <window.UI.Runs /> : route === 'receipts' ? <window.UI.Receipts /> : route === 'docs' ? <window.UI.Docs /> : route === 'feedback' ? <window.UI.Feedback /> : route === 'automations' ? <window.UI.Automations /> : route.startsWith('settings/') ? <window.UI.Settings key={route} page={route.slice(9)} /> : <window.UI.Settings key={route} page={{
      account: 'Account',
      connections: 'Connections',
      hooks: 'Hooks',
      privacy: 'Privacy',
      appearance: 'Appearance',
      updates: 'Updates & About'
    }[route] || 'Account'} full />;
    if(desktopAccess&&(!desktopAccess.admitted||!desktopAccess.ready))return <DesktopSignIn/>;
    return <Ctx.Provider value={value}>
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
        gridTemplateColumns: 'minmax(0,1fr)',
        gridTemplateRows: '48px minmax(0,1fr)'
      }}>
   <header className={"flex app-header" + (route.startsWith("settings/") ? " settings-header" : "")} data-window-caption style={{
          height: 48,
          padding: window.ARCHHUB_ONE_TITLE_BAR ? '0 0 0 12px' : '0 12px',
          background: '#0f0f13',
          borderBottom: '1px solid ' + A.lineSoft,
          fontSize: 'calc(13px * var(--text-scale,1))',
          gap: 0
        }}><button data-design="header.mark" className="button-reset header-mark" style={{
            color: A.accent
          }} aria-label="ArchHub menu" aria-haspopup="menu" aria-expanded={modal?.kind === 'ArchHub menu'} title="ArchHub menu" onClick={event => executeAction("appShell.ArchHubMenu.1", {
            close,
            modal,
            show
          }, event)}><ArchMark size={20} /></button><button data-design="header.workspace" className="button-reset header-workspace" aria-label="Workspace" aria-haspopup="menu" aria-expanded={modal?.kind === 'Workspace menu'} title="Workspace" onClick={event => executeAction("appShell.Control.4", {
            close,
            modal,
            show
          }, event)}><span>{s.workspaces.find(w => w.id === s.activeWorkspace)?.name || s.workspaces.find(w => w.builtIn)?.name || 'Add workspace'}</span><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><path d="M3 4.5l3 3 3-3" /></svg></button><i className="header-divider" /><span className="muted">/</span><button className="button-reset header-page" onClick={event => executeAction("appShell.ArchHub.2", {
            go
          }, event)}>{navLabel((route.startsWith("settings/") ? "Settings" : route === "task-file" ? "Home" : routeNames[route]) || route.split('/').at(-1))}</button>{route === "task-file" && <><span className="muted">›</span><span className="header-page header-here" title="This session">{s.tasks.find(t => t.id === task)?.title || s.graph.name}</span></>}<span className="fill" /><div data-design="header.status" className="header-status" aria-label="Session status">{route.startsWith("settings/") ? <span className="header-phrase">{(pending => agentLoad.status === 'error' ? <span role="alert" className="header-error"><span className="header-error-text" title={agentLoad.message}>{agentLoad.message}</span><Btn aria-label="Retry Workshop connection" onClick={event => executeAction("appShell.RetryWorkshop", {reloadWorkshop}, event)}>Retry</Btn></span>
            : s.connectionNotice && s.connectionNotice !== 'Checking for updates…' ? <button className="button-reset muted" title={s.connectionNotice} onClick={event => executeAction("appShell.Receipts.16", {go}, event)}>1 notice</button>
            : pending ? <button className="button-reset muted" onClick={event => executeAction("appShell.RunningWaitForYou.14", {act, api, go}, event)}>{pending + ' wait for you'}</button>
            : <span>{s.profile.signedIn ? 'Signed in' : 'Local session'}</span>)(window.UI.homeRows(s, s.homeLayout).needsYou)}</span> : <>{s.connectionNotice && s.connectionNotice !== 'Checking for updates…' ? <button className="button-reset muted" onClick={event => executeAction("appShell.Receipts.16", {go}, event)}>1 notice · see Receipts</button> : s.connectionNotice ? <span>{s.connectionNotice}</span> : null}
          {agentLoad.status === 'waiting' && <span role="status">Loading Workshop settings…</span>}
          {agentLoad.status === 'error' && <span role="alert">{agentLoad.message}<Btn aria-label="Retry Workshop connection" onClick={event => executeAction("appShell.RetryWorkshop", {reloadWorkshop}, event)}>Retry</Btn></span>}
          {agentLoad.status === 'empty' && <span role="status">Select a workflow for Workshop settings.</span>}
          {agentLoad.status === 'loaded' && <span className="sr-only" aria-label="Workshop settings ready" title="Workshop settings ready">✓</span>}
          <button data-design="header.pc" className="button-reset muted header-pc" title="This PC and its programs: Settings › Connections" onClick={event => executeAction("appShell.Control.13", {
            go
            }, event)}><span data-design="status.on-this-pc">On this PC · {(() => { const ready = (s.hosts||[]).filter(h=>h.state==='connected'||h.state==='listening'); const liveCount = window.UI.homeRows(s, s.homeLayout).running || (s.liveAgents||[]).filter(a=>a.status==='working').length; return (ready.length ? ready.length + ' ready (' + ready.map(h=>h.name).join(', ') + ')' : (s.hostsProbing?'checking programs…':'no program connected')) + ' · ' + liveCount + ' live ' + (liveCount === 1 ? 'agent' : 'agents'); })()}</span></button>{(rows => [['Running', rows.running, 'running', 'Nothing running', s.agentSummary], ['Needs you', rows.needsYou, 'need you', 'Nothing needs you', 'Sessions that wait for you']].map(([filter, count, word, none, title]) => <button key={filter} data-design={'header.' + word.replace(' ', '-')} className="button-reset muted" title={title + ' · show them on Home'} onClick={event => executeAction("appShell.RunningWaitForYou.14", {act, api, go, filter}, event)}>{count ? count + ' ' + word : none}</button>))(window.UI.homeRows(s, s.homeLayout))}<button data-design="header.agents" className="button-reset muted" title={(s.agentSummary || 'Checking running agents…') + ' · open Agents on this PC'} onClick={event => executeAction('ui.select', () => go('agents'), event)}>Agents on this PC</button><span className="fill" /><button hidden={route==='task-file'} className="button-reset muted" onClick={event => executeAction("appShell.CtrlK.15", {
            show
          }, event)}>Ctrl K</button><button hidden={route==='task-file'} className="button-reset muted" onClick={event => executeAction("appShell.Receipts.16", {
            go
          }, event)}>Receipts</button></>}</div><button data-design="header.search" className="button-reset header-search" onClick={event => executeAction("appShell.SearchCtrlK.5", {
            show
          }, event)} aria-label="Search · Ctrl K"><window.AHIcon name="search" size={15} /><span className="fill">Search all…</span><kbd>Ctrl K</kbd></button>{/* One update state at a time: while the status read is being retried the header says so; "Update failed" is the updater's own answer. */}{(s.update.available || s.update.state==='failed' && s.connectionNotice !== 'Checking for updates…') && <button className="button-reset header-update" title={s.update.state==='failed' ? (s.update.detail || 'Update failed') : `${s.update.installed} → ${s.update.next}. Unsent text is lost; your saved graphs and settings stay with you.`} aria-label={s.update.state==='failed' ? (s.update.detail || 'Update failed') : 'Update available'} onClick={event => executeAction("appShell.Control.3", {
            act,
            api,
            go,
            s
          }, event)}>{s.update.state==='failed' ? 'Update failed' : 'Update'}</button>}<button data-design="header.tray" className="button-reset header-icon" aria-label="Tray menu" title="Tray menu" onClick={event => executeAction("appShell.TrayMenu.7", {
            show
          }, event)}><svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="3" cy="8" r="1.3" /><circle cx="8" cy="8" r="1.3" /><circle cx="13" cy="8" r="1.3" /></svg></button><button data-design="header.bell" className="button-reset header-icon" aria-label="Notifications" aria-haspopup="dialog" aria-expanded={modal?.kind === 'Notifications'} title="Notifications" onClick={event => executeAction("appShell.Notifications.6", {
            close,
            modal,
            show
          }, event)}><window.AHIcon name="bell" size={16} />{s.notifications.some(n => !n.read) && <b className="header-count">{s.notifications.filter(n => !n.read).length}</b>}</button>{window.ARCHHUB_ONE_TITLE_BAR && <div className="window-controls" role="group" aria-label="Window">{[['minimize', 'Minimize', '\uE921'], ['maximize', 'Maximize', '\uE922'], ['close', 'Close', '\uE8BB']].map(([action, name, glyph]) => [action, action === 'maximize' && document.documentElement.dataset.windowMaximized === 'true' ? 'Restore' : name, glyph]).map(([action, label, glyph]) => <button key={action} className="button-reset" data-window-button={action} aria-label={label} title={label} onClick={event => executeAction("appShell.WindowControl.99", {
            api,
            action
          }, event)}><span aria-hidden="true">{action === 'maximize' ? <><span className="when-normal">{glyph}</span><span className="when-maximized">{'\uE923'}</span></> : glyph}</span></button>)}</div>}</header>
   <div style={{
          display: 'grid',
          gridTemplateColumns: '64px minmax(0,1fr)',
          minHeight: 0
        }}><nav className="app-rail" aria-label="Main navigation" style={{
            background: A.bgDeep,
            borderRight: '1px solid ' + A.lineSoft,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: '10px 0 8px',
            gap: 0,
            overflow: 'auto'
          }}>{rail.map(([g, l, r]) => <D.Rail key={r} variant="home" glyph={<window.AHIcon name={g} size={18} />} label={navLabel(l)} active={route === r || (route === "task-file" && r === "canvas")} onDragOver={e => {
              if (r === 'canvas') e.preventDefault();
            }} onDragEnter={() => {
              if (r === 'canvas') go(r);
            }} onClick={event => executeAction("appShell.Control.10", {
              go,
              r
            }, event)} badge={r === 'workshop' ? s.tasks.filter(t => t.status === 'IN REVIEW').length || undefined : undefined} style={{
              flex: 'none', width: 64, height: 58
            }} />)}{pinnedRailIds.length > 0 && pinnedRailIds.map((tid, idx) => {
              const tRow = (s.tasks || []).find(item => item.id === tid) || (Array.isArray(s.railTasks) ? s.railTasks.find(item => item?.id === tid) : null) || {id: tid, title: tid};
              return <D.Rail key={'pin:' + tid} variant="home" glyph={<window.AHIcon name="pin" size={15} />} label={tRow.title || tid} active={route === 'task-file' && task === tid} onClick={event => executeAction('appShell.RailOpenTask', {openTaskFile, tid}, event)} onContextMenu={e => {
                e.preventDefault();
                e.stopPropagation();
                show('Rail item menu', {taskId: tid, index: idx, anchor: {x: e.clientX || 72, y: e.clientY || 140}});
              }} style={{flex: 'none', width: 64, height: 52}} />;
            })}<span className="fill" /><D.Rail variant="home" glyph={<window.AHIcon name="docs" size={18} />} label="Docs" active={route==='docs'} onClick={event => executeAction("appShell.Control.10", {go, r: 'docs'}, event)} style={{flex:'none',width:64,height:58}} /><D.Rail variant="home" glyph={<window.AHIcon name="settings" size={18} />} label="Settings" active={route.startsWith('settings/')} onClick={event => executeAction("appShell.Control.11", {
              go
            }, event)} style={{
              flex: 'none', width: 64, height: 58
            }} /><button className="button-reset" aria-label="Your account" aria-haspopup="dialog" aria-expanded={modal?.kind === 'Profile card'} title="Your account" onClick={event => executeAction("appShell.YourAccount.12", {
              close,
              modal,
              show
            }, event)} style={{
              position: 'relative',
              margin: '8px 0 14px',
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: userPhoto ? 'transparent' : 'linear-gradient(135deg,#e8c39e,#b98a62)',
              color: '#2a1d10',
              fontWeight: 700,
              fontSize: 'calc(12px * var(--text-scale,1))',
              flex: 'none',
              display: 'grid',
              placeItems: 'center',
              overflow: 'visible'
            }}>{userPhoto ? <img src={userPhoto} alt="" style={{width: 32, height: 32, borderRadius: '50%', objectFit: 'cover', display: 'block'}} /> : window.UI.profileInitials({...s.profile, name: userDisplayName || s.profile?.name})}<span data-presence={userPresence} aria-hidden="true" style={{
              position: 'absolute', right: -1, bottom: -1, width: 9, height: 9, borderRadius: '50%',
              border: '2px solid ' + A.bgDeep,
              background: userPresence === 'Busy' ? 'var(--color-err, #e6705f)' : userPresence === 'Away' ? 'var(--color-warn, #e5b25a)' : 'var(--color-ok, #7ec18e)'
            }} /></button></nav><div className="screen-with-composer has-local-composer" style={{'--canvas-library-width':libraryOpen ? '248px' : '0px'}}>{(canvasOpened || route==='canvas') && <div hidden={route!=='canvas'} ref={element=>{element?.toggleAttribute('inert',route!=='canvas'||!!s.graphOpening);}} style={{display:route==='canvas'?'grid':'none',minHeight:0,height:'100%'}}><window.UI.Canvas key={s.graph.scopeKey || s.graph.id} active={route==='canvas'&&!s.graphOpening} /></div>}{screen}{route !== 'task-file' && route !== 'home' && !route.startsWith('settings/') && <div className="global-composer"><window.UI.Composer compact /></div>}</div></div>
  </div>}
  <window.UI.BaboomSprite open={companion} setOpen={setCompanion} taskId={route === 'home' ? homeThreadId : task} />
  {window.UI.TutorialOverlay && <window.UI.TutorialOverlay />}
  {!s.canvasSaveConflict && s.orphanDrafts?.length > 0 && <div role="alert" style={{position: 'fixed', top: 100, left: '50%',
        transform: 'translateX(-50%)', maxWidth: '70vw', border: '1px solid ' + A.line, borderRadius: 10, background: '#24242b',
        padding: '12px 18px', zIndex: 201, boxShadow: '0 8px 30px #0008', display: 'grid', gap: 8}}>
      <span>Unsaved changes from a closed ArchHub window in {s.orphanDrafts[0].file || 'an unsaved canvas'}. Updates wait until you choose.</span>
      {s.orphanDraftError && <span>{s.orphanDraftError}</span>}
      <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>
        <Btn sm onClick={event => executeAction('ui.select', () => api.resolveOrphanDraft(s.orphanDrafts[0].view, true), event)}>Keep those changes as a copy</Btn>
        <Btn sm ghost onClick={event => executeAction('ui.select', () => api.resolveOrphanDraft(s.orphanDrafts[0].view, false), event)}>Discard those changes</Btn>
      </div>
    </div>}
  {(s.canvasSaveConflict || toast) && (() => {
    const toastTone = !s.canvasSaveConflict && typeof toast === 'object' ? (toast.tone || '') : '';
    const borderCol = toastTone === 'bad' ? 'var(--color-err, #e6705f)' : toastTone === 'warn' ? 'var(--color-warn, #e5b25a)' : A.line;
    const toastAction = !s.canvasSaveConflict && typeof toast === 'object' ? (toast.action || toast.open) : null;
    // The toast sits fully inside the window and above the visible composer, never over it (founder 2026-11-26).
    // Portalled to <body>: a transformed or contained ancestor must not become its containing block and clip it.
    const composerTop = Math.min(...[...document.querySelectorAll('[data-design="composer.surface"]')].filter(e => e.offsetParent).map(e => e.getBoundingClientRect().top));
    const toastBottom = Number.isFinite(composerTop) && composerTop < window.innerHeight ? Math.max(24, window.innerHeight - composerTop + 8) : 24;
    return window.ReactDOM.createPortal(<div role="alert" data-toast="" data-toast-tone={toastTone || 'info'} data-toast-paused={toastPaused ? 'true' : 'false'} className={'flex app-toast' + (toastTone ? ' tone-' + toastTone : '')} onMouseEnter={() => setToastPaused(true)} onMouseLeave={() => setToastPaused(false)} style={{
        position: 'fixed',
        bottom: toastBottom,
        left: '50%',
        transform: 'translateX(-50%)',
        boxSizing: 'border-box',
        maxWidth: 'min(640px, calc(100vw - 32px))',
        width: 'max-content',
        pointerEvents: 'auto',
        border: '1px solid ' + borderCol,
        borderRadius: 10,
        background: 'var(--color-bg-panel, #15151a)',
        padding: '10px 16px',
        zIndex: 200,
        gap: 10,
        boxShadow: '0 10px 32px rgba(0,0,0,0.5)',
        ...(s.canvasSaveConflict ? {display:'grid',gap:8} : {})
      }}>{s.canvasSaveConflict ? <>
        <span>{s.canvasSaveConflict}</span>
        {s.canvasSaveRecoveryError && <span>{s.canvasSaveRecoveryError}</span>}
        <div style={{display:'flex',flexWrap:'wrap',gap:8}}>
          <Btn sm disabled={s.canvasSaveResolving} onClick={event=>executeAction('ui.select',()=>api.resolveSaveConflict(true),event)}>Keep my changes as a copy</Btn>
          <Btn sm ghost disabled={s.canvasSaveResolving} onClick={event=>executeAction('ui.select',()=>api.resolveSaveConflict(false),event)}>Discard my changes and reload</Btn>
          <Btn sm ghost disabled={s.canvasSaveResolving} onClick={event=>executeAction('ui.select',()=>{api.dismissSaveConflict();setToast('');},event)}>Dismiss</Btn>
        </div>
      </> : <><span>{toast.text || toast}</span>{toastAction && <Btn sm onClick={event => executeAction('ui.select', () => { setToast(''); return toastAction(); }, event)}>{toast.label || 'Open'}</Btn>}<Btn sm ghost onClick={event => executeAction("appShell.Dismiss.17", {
          setToast
        }, event)}>Dismiss</Btn></>}</div>, document.body);
  })()}
  {modal && <Dialog key={modal.kind + ':' + (modal.id || '')} modal={modal} close={close} />}
 </Ctx.Provider>;
  }
  const COLOUR_SWATCHES = [
    ['Accent', '#d97757'],
    ['Amber', '#e5b25a'],
    ['Green', '#7ec18e'],
    ['Teal', '#5fb3b3'],
    ['Blue', '#7898d6'],
    ['Violet', '#a98cd6'],
    ['None', '']
  ];
  const ADD_NODE_TYPES = ['All', 'Text', 'Number', 'Elements', 'Sheet', 'File'];
  function matchesNodeType(node, typeFilter) {
    if (!typeFilter || typeFilter === 'All') return true;
    const wanted = typeFilter.toLowerCase();
    const hay = [
      node.category,
      node.title,
      ...(node.inputs || []).map(p => p.type || p.name),
      ...(node.outputs || []).map(p => p.type || p.name),
      ...(node.paramDefs || []).map(p => p.type || p.name)
    ].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(wanted) || (wanted === 'elements' && hay.includes('element'));
  }
  function paintCropCanvas(canvas, size, circular, img, zoom, offset) {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, size, size);
    ctx.save();
    if (circular) {
      ctx.beginPath();
      ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
      ctx.clip();
    }
    ctx.fillStyle = '#2a1d10';
    ctx.fillRect(0, 0, size, size);
    if (img && img.naturalWidth > 0) {
      const scale = Math.max(size / img.naturalWidth, size / img.naturalHeight) * zoom;
      const w = img.naturalWidth * scale, h = img.naturalHeight * scale;
      const factor = size / 240;
      ctx.drawImage(img, (size - w) / 2 + offset.x * factor, (size - h) / 2 + offset.y * factor, w, h);
    } else {
      ctx.fillStyle = '#d97757';
      ctx.beginPath();
      ctx.arc(size / 2 + offset.x * (size / 240), size / 2 + offset.y * (size / 240), (size * 0.32) * zoom, 0, Math.PI * 2);
      ctx.fill();
    }
    if (!circular) {
      ctx.strokeStyle = 'rgba(255,255,255,0.75)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(size / 2, size / 2, size * 0.42, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }
  function CropPhotoDialog({modal: m, close, u}) {
    const stageRef = React.useRef(null), prevRef = React.useRef(null), imgRef = React.useRef(null), dragRef = React.useRef(null);
    const [zoom, setZoom] = React.useState(1.15);
    const [offset, setOffset] = React.useState({x: 0, y: 0});
    const redraw = (nextZoom = zoom, nextOffset = offset, image = imgRef.current) => {
      paintCropCanvas(stageRef.current, 240, false, image, nextZoom, nextOffset);
      paintCropCanvas(prevRef.current, 56, true, image, nextZoom, nextOffset);
    };
    const useCropped = () => {
      const out = document.createElement('canvas');
      out.width = 128;
      out.height = 128;
      paintCropCanvas(out, 128, false, imgRef.current, zoom, offset);
      const rawUrl = out.toDataURL('image/jpeg', 0.82);
      const dataUrl = rawUrl && rawUrl.startsWith('data:image/') ? rawUrl : (m.src || '');
      const prevPhoto = m.prevPhoto || '';
      void u.saveProfileFields({photo: dataUrl}).then(res => {
        if (!res) return;
        close();
        u.setToast({text: 'Photo updated.', label: 'Undo', action: () => u.saveProfileFields({photo: prevPhoto})});
      });
    };
    const removeCurrent = () => {
      const prevPhoto = m.prevPhoto || '';
      void u.saveProfileFields({photo: ''}).then(res => {
        if (!res) return;
        close();
        u.setToast({text: 'Photo removed.', label: 'Undo', action: () => u.saveProfileFields({photo: prevPhoto})});
      });
    };
    return <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}>
      <section className="dialog" role="dialog" aria-modal="true" aria-label="Crop your photo" data-design="crop.dialog" style={{width: 'min(420px, 94vw)', display: 'grid', gap: 14}}>
        {m.src && <img ref={imgRef} src={m.src} alt="" onLoad={e => redraw(zoom, offset, e.currentTarget)} style={{display: 'none'}} />}
        <header className="spread"><h2>Crop your photo</h2><Btn sm ghost aria-label="Close dialog" onClick={event => executeAction('appShell.CloseDialog.98', {close}, event)}>×</Btn></header>
        <div className="flex" style={{gap: 18, alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap'}}>
          <canvas ref={el => { stageRef.current = el; paintCropCanvas(el, 240, false, imgRef.current, zoom, offset); }} width={240} height={240} tabIndex={0} aria-label="Drag to move the picture" onPointerDown={e => {
            dragRef.current = {x: e.clientX - offset.x, y: e.clientY - offset.y};
          }} onPointerMove={e => {
            if (dragRef.current) {
              const next = {x: e.clientX - dragRef.current.x, y: e.clientY - dragRef.current.y};
              setOffset(next);
              redraw(zoom, next);
            }
          }} onPointerUp={() => { dragRef.current = null; }} onKeyDown={e => {
            const step = 8;
            let next = null;
            if (e.key === 'ArrowLeft') next = {x: offset.x - step, y: offset.y};
            else if (e.key === 'ArrowRight') next = {x: offset.x + step, y: offset.y};
            else if (e.key === 'ArrowUp') next = {x: offset.x, y: offset.y - step};
            else if (e.key === 'ArrowDown') next = {x: offset.x, y: offset.y + step};
            if (next) { e.preventDefault(); setOffset(next); redraw(zoom, next); }
          }} style={{width: 240, height: 240, borderRadius: 12, border: '1px solid ' + A.line, cursor: 'grab', touchAction: 'none'}} />
          <div style={{display: 'grid', gap: 6, justifyItems: 'center'}}>
            <canvas ref={el => { prevRef.current = el; paintCropCanvas(el, 56, true, imgRef.current, zoom, offset); }} width={56} height={56} aria-label="How it shows" style={{width: 56, height: 56, borderRadius: '50%', border: '1px solid ' + A.line}} />
            <small className="muted">How it shows</small>
          </div>
        </div>
        <label className="flex" style={{gap: 10}}><span>Zoom</span><input className="fill" type="range" aria-label="Zoom" min="1" max="3" step="0.01" value={zoom} onChange={e => { const nextZ = Number(e.target.value); setZoom(nextZ); redraw(nextZ, offset); }} /></label>
        <div className="spread">
          <div>{m.prevPhoto ? <button type="button" className="button-reset muted" onClick={event => executeAction('projects.controls.activate', {handler: removeCurrent}, event)}>Remove photo</button> : null}</div>
          <div className="flex" style={{gap: 8}}>
            <Btn onClick={event => executeAction('appShell.CloseDialog.98', {close}, event)}>Cancel</Btn>
            <Btn p onClick={event => executeAction('projects.controls.activate', {handler: useCropped}, event)}>Use photo</Btn>
          </div>
        </div>
      </section>
    </div>;
  }
  function ProfileCardPopover({close, popRef, u}) {
    const s = useData();
    const photoInput = React.useRef(null);
    const [nameVal, setNameVal] = React.useState(u.userDisplayName || s.profile?.name || '');
    const [roleVal, setRoleVal] = React.useState(u.userRole || '');
    const [langOpen, setLangOpen] = React.useState(false);
    const [helpOpen, setHelpOpen] = React.useState(false);
    const composerEl = typeof document !== 'undefined' ? document.querySelector('[data-design="composer.surface"]') : null;
    const cRect = composerEl?.offsetParent ? composerEl.getBoundingClientRect() : null;
    const overlapsX = cRect && cRect.width > 0 && cRect.left < 384 && cRect.right > 72;
    const clampedBottom = overlapsX ? Math.max(20, Math.ceil(window.innerHeight - cRect.top + 12)) : 20;
    const clampedMaxHeight = Math.max(220, (typeof window !== 'undefined' ? window.innerHeight : 800) - clampedBottom - 60);
    const openFile = file => {
      if (!file || !String(file.type || '').startsWith('image/')) return;
      const reader = new window.FileReader();
      reader.onload = () => u.show('Crop your photo', {src: String(reader.result || ''), prevPhoto: u.userPhoto});
      reader.readAsDataURL(file);
    };
    const commitName = () => {
      const trimmed = nameVal.trim();
      if (!trimmed || trimmed === (u.userDisplayName || s.profile?.name || '')) return;
      void u.saveProfileFields({name: trimmed}).then(res => { if (res) u.setToast({text: 'Name saved.'}); });
    };
    const commitRole = () => {
      const trimmed = roleVal.trim();
      if (trimmed === (u.userRole || '')) return;
      void u.saveProfileFields({role: trimmed}).then(res => { if (res) u.setToast({text: 'Role saved. Agents read it on the You node.'}); });
    };
    const currentLang = s.settings.find(r => r.id === 'Account.App language')?.value || 'English';
    const email = s.profile?.email || s.desktopAccess?.email || 'Signed in';
    const rawPlan = s.profile?.plan || '';
    const planPill = !rawPlan || ['Personal', 'solo'].includes(rawPlan) ? 'Solo · beta' : rawPlan;
    const presenceColor = u.userPresence === 'Busy' ? 'var(--color-err, #e6705f)' : u.userPresence === 'Away' ? 'var(--color-warn, #e5b25a)' : 'var(--color-ok, #7ec18e)';
    return <section ref={popRef} role="dialog" aria-modal="false" aria-label="Your profile" data-design="profile.card" onPaste={e => {
        const items = e.clipboardData?.items || [];
        for (const item of items) {
          if (item.type && item.type.startsWith('image/')) {
            e.preventDefault();
            openFile(item.getAsFile());
            return;
          }
        }
      }} style={{
        position: 'fixed', left: 72, bottom: clampedBottom, maxHeight: clampedMaxHeight,
        width: 312, overflowY: 'auto', zIndex: 1050,
        background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
        borderRadius: 12, padding: 14, boxShadow: '0 16px 40px rgba(0,0,0,0.55)', display: 'grid', gap: 10
      }}>
        <input ref={photoInput} className="sr-only" type="file" aria-label="Upload profile photo" accept="image/*" onChange={e => {
          const f = e.target.files?.[0];
          if (f) openFile(f);
          e.target.value = '';
        }} />
        <div className="flex" style={{gap: 12, alignItems: 'flex-start'}}>
          <button type="button" className="button-reset" data-design="profile.photo" aria-label={u.userPhoto ? 'Change profile photo' : 'Add profile photo'} onDragOver={e => e.preventDefault()} onDrop={e => {
            e.preventDefault();
            openFile(e.dataTransfer?.files?.[0]);
          }} onClick={event => executeAction('projects.controls.activate', {handler: () => photoInput.current?.click()}, event)} style={{
            position: 'relative', width: 52, height: 52, borderRadius: '50%', flex: 'none',
            background: u.userPhoto ? 'transparent' : 'linear-gradient(135deg,#e8c39e,#b98a62)',
            color: '#2a1d10', fontWeight: 700, fontSize: 16, display: 'grid', placeItems: 'center', cursor: 'pointer',
            border: '1px solid var(--color-line, #26262e)'
          }}>
            {u.userPhoto ? <img src={u.userPhoto} alt="" style={{width: 52, height: 52, borderRadius: '50%', objectFit: 'cover'}} /> : window.UI.profileInitials({...s.profile, name: nameVal || s.profile?.name})}
            <span data-presence={u.userPresence} aria-hidden="true" style={{position: 'absolute', right: 0, bottom: 0, width: 12, height: 12, borderRadius: '50%', background: presenceColor, border: '2px solid var(--color-bg-panel, #15151a)'}} />
            <span style={{position: 'absolute', bottom: -16, left: '50%', transform: 'translateX(-50%)', whiteSpace: 'nowrap', fontSize: 10, color: 'var(--color-ink-soft, #9b938a)'}}>{u.userPhoto ? 'Change' : 'Add photo'}</span>
          </button>
          <div className="fill" style={{display: 'grid', gap: 6, minWidth: 0}}>
            <input aria-label="Name" placeholder="Your name" value={nameVal} onChange={e => setNameVal(e.target.value)} onBlur={commitName} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); commitName(); } }} style={{fontSize: 13, fontWeight: 600, padding: '4px 8px'}} />
            <input aria-label="Your role" placeholder="Your role" value={roleVal} onChange={e => setRoleVal(e.target.value)} onBlur={commitRole} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); commitRole(); } }} style={{fontSize: 12, padding: '4px 8px'}} />
            <select aria-label="Presence status" value={u.userPresence} onChange={e => { const presence = e.target.value; void u.saveProfileFields({presence}); }} style={{fontSize: 12, padding: '3px 8px'}}>
              <option value="Available">Available</option>
              <option value="Busy">Busy</option>
              <option value="Away">Away</option>
            </select>
          </div>
        </div>
        <div className="spread" style={{paddingTop: 8, borderTop: '1px solid var(--color-line-soft, #1e1e24)', fontSize: 12}}>
          <span className="muted" style={{overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{email}</span>
          <span className="badge" data-design="profile.plan">{planPill}</span>
        </div>
        <nav aria-label="Account" style={{display: 'grid', gap: 2, borderTop: '1px solid var(--color-line-soft, #1e1e24)', paddingTop: 6}}>
          <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); u.go('settings/Appearance'); }}, event)}>Personalisation and look</button>
          <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => u.show('Usage today')}, event)}>Usage</button>
          <button type="button" aria-expanded={langOpen} className="listbutton spread" onClick={event => executeAction('projects.controls.activate', {handler: () => setLangOpen(v => !v)}, event)}><span>Language</span><span className="muted">{currentLang === 'Arabic' ? 'العربية' : 'English'} ›</span></button>
          {langOpen && <div role="group" aria-label="Language choices" style={{paddingLeft: 10, display: 'grid', gap: 2}}>
            {[['English', 'English'], ['Arabic', 'العربية · Arabic']].map(([val, label]) => <button type="button" key={val} aria-pressed={currentLang === val} className="listbutton spread" onClick={event => executeAction('projects.controls.activate', {handler: () => u.act(() => api.setSetting('Account.App language', val, s.settingsDestination))}, event)}><span>{label}</span><span>{currentLang === val ? '✓' : ''}</span></button>)}
          </div>}
          <button type="button" aria-expanded={helpOpen} className="listbutton spread" onClick={event => executeAction('projects.controls.activate', {handler: () => setHelpOpen(v => !v)}, event)}><span>Help and feedback</span><span className="muted">›</span></button>
          {helpOpen && <div role="group" aria-label="Help and feedback" style={{paddingLeft: 10, display: 'grid', gap: 2}}>
            <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); u.go('docs'); }}, event)}>Docs</button>
            <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => u.show('Send feedback')}, event)}>Send feedback…</button>
            <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); u.go('system'); }}, event)}>How everything connects</button>
          </div>}
          <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => u.show("What's new")}, event)}>What&apos;s new</button>
          <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); u.go('library'); }}, event)}>Get apps and extensions</button>
          <button type="button" className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); window.open?.('https://archhub.io/account/', '_blank', 'noopener,noreferrer'); }}, event)}>Your account on archhub.io</button>
        </nav>
        <footer className="spread" style={{borderTop: '1px solid var(--color-line-soft, #1e1e24)', paddingTop: 8, fontSize: 12, gap: 8, flexWrap: 'wrap'}}>
          {u.userPhoto && <button type="button" className="button-reset muted" onClick={event => executeAction('projects.controls.activate', {handler: () => {
            const prev = u.userPhoto;
            void u.saveProfileFields({photo: ''}).then(res => { if (res) u.setToast({text: 'Photo removed.', label: 'Undo', action: () => u.saveProfileFields({photo: prev})}); });
          }}, event)}>Remove photo</button>}
          <button type="button" className="button-reset muted" onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); u.go('settings/Account'); }}, event)}>Settings › You</button>
          <span className="fill" />
          <button type="button" className="button-reset muted" onClick={event => executeAction('projects.controls.activate', {handler: () => {
            void u.act(() => api.signIn(false)).then(res => { if (res) close(); });
          }}, event)}>Sign out</button>
        </footer>
      </section>;
  }
  function NodeTypeForm({modal,close}) {
    const s=useData(),api=window.UI.api,ids=modal.ids||[modal.id],nodes=s.graph.nodes;
    const selected=new Set(ids),pending=[...ids];while(pending.length)for(const id of nodes.find(n=>n.id===pending.pop())?.children||[])if(!selected.has(id)){selected.add(id);pending.push(id);}
    const parameters=nodes.filter(n=>selected.has(n.id)).flatMap(n=>(n.paramDefs||[]).filter(p=>n.type!=='script.python'||p.id==='timeout').map(p=>({node:n.id,key:p.id,name:p.name||p.id,value:n.params[p.id]})));
    const [kind,setKind]=React.useState('pure'),[scanAttempt,setScanAttempt]=React.useState(0);
    const [name,setName]=React.useState(nodes.find(n=>n.id===modal.id)?.title||'Node type'),[category,setCategory]=React.useState('Scripts'),[picked,setPicked]=React.useState(modal.id&&nodes.find(n=>n.id===modal.id)?.type==='script.python'?parameters.map(p=>p.node+':'+p.key):[]),[scan,setScan]=React.useState(null),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false);
    const publicParameters=parameters.filter(p=>picked.includes(p.node+':'+p.key)).map(({node,key})=>({node,key}));
    React.useEffect(()=>{let current=true;setScan(null);setError('');if(!name.trim())return;api.scanNodeType(ids,name,category,publicParameters).then(result=>{if(current){setScan(result);setError('');}},e=>{if(current)setError(e.message);});return()=>{current=false;};},[name,category,JSON.stringify(picked),scanAttempt]);
    const save=async()=>{setBusy(true);try{await api.saveNodeType(ids,name,category,publicParameters,scan.pure?kind:"effect");close();}catch(e){setError(e.message);}finally{setBusy(false);}};
    const requestState=error?'error':!name.trim()?'empty':scan?'loaded':'waiting';
    return <div className="v22g-node-type"><label>Name<input data-design="field.name" aria-label="Node type name" value={name} onChange={e=>setName(e.target.value)}/></label><div className="flex"><label>Category<select data-design="field.category" aria-label="Category" value={category} onChange={e=>setCategory(e.target.value)}>{['Scripts','Files','Checks','Project','Skills: yours'].map(c=><option key={c}>{c}</option>)}</select></label><label>Kind<div className="flex" role="group" aria-label="Pure or effect"><button type="button" disabled={!scan?.pure} title={!scan?.pure?"This definition contains effects":undefined} aria-pressed={!!scan?.pure&&kind==="pure"} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setKind("pure")},event)}>Pure</button><button type="button" aria-pressed={!scan?.pure||kind==="effect"} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setKind("effect")},event)}>Effect</button></div></label></div><b>Sockets</b>{nodes.filter(n=>selected.has(n.id)).map(n=><p key={n.id}>{n.inputs.length?n.inputs.map(p=>p.name).join(', '):'No inputs'} → {n.outputs.length?n.outputs.map(p=>p.name).join(', '):'No outputs'}</p>)}<b>Public parameters</b><p>Ticked ones appear on the node. The others stay as they are inside.</p>{parameters.map(p=><label className="flex" key={p.node+':'+p.key}><input type="checkbox" checked={picked.includes(p.node+':'+p.key)} onChange={e=>setPicked(old=>e.target.checked?[...old,p.node+':'+p.key]:old.filter(key=>key!==p.node+':'+p.key))}/>{p.name}<span>{String(p.value)}</span></label>)}{!parameters.length&&<p>It has no parameters.</p>}{requestState==='waiting'&&<p role="status">Checking the selected nodes…</p>}{requestState==='empty'&&<p>Name the node type to check it.</p>}{requestState==='loaded'&&<p role="status">No embedded credentials detected. {scan.paths?'Local paths are present; expose them as parameters before sharing.':scan.pure?'Pure nodes only.':'Effects keep their Run and Approve boundary.'}</p>}{requestState==='error'&&<p role="alert">{error}<button type="button" onClick={event=>executeAction('projects.controls.activate',{handler:()=>setScanAttempt(value=>value+1)},event)}>Retry check</button></p>}<div className="flex"><button type="button" data-design="action.cancel" onClick={event=>executeAction('projects.controls.activate',{handler:close},event)}>Cancel</button><button type="button" data-design="action.save" disabled={!scan||busy||!name.trim()} onClick={event=>executeAction('projects.controls.activate',{handler:save},event)}>Save</button></div></div>;
  }
  function Dialog({
    modal: m,
    close
  }) {
    const s = useData(),
      u = window.UI.useApp();
    const formAction=window.UI.useAction();
    const [text, setText] = React.useState(m.text || ''),
      [extra, setExtra] = React.useState(''),
      [taskWorkspace, setTaskWorkspace] = React.useState(() => s.workspaces.some(w=>w.id===s.activeWorkspace&&!w.builtIn&&w.available!==false)?s.activeWorkspace:''),
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
      const isPopover = ['Profile card', 'ArchHub menu', 'Workspace menu', 'Notifications', 'Rail item menu'].includes(m.kind);
      const outside = e => {
        if (isPopover && !el.contains(e.target) && !e.target.closest?.('[aria-expanded="true"]')) close();
      };
      el.addEventListener('keydown', handler);
      if (isPopover) window.addEventListener('pointerdown', outside, true);
      return () => {
        el.removeEventListener('keydown', handler);
        if (isPopover) window.removeEventListener('pointerdown', outside, true);
        voiceGeneration.current++;
        if (m.kind === 'Talk' && api.supportsAction('stopVoiceInput')) void u.act(api.stopVoiceInput);
      };
    }, [m.kind]);
    const saved = async fn => {
      const result = await u.act(fn);
      if (result) close();
    };
    const saveForm=async fn=>{const result=await formAction.run(fn);if(result)close();};
    const k = m.kind;
    const logTask = k === 'Raw log' && s.tasks.find(task => task.id === m.id);
    const title = k === 'Confirm' ? (m.heading || m.title || 'Confirm') : logTask ? 'Raw log · ' + logTask.title : k;
    if (k === 'Profile card') return <ProfileCardPopover close={close} popRef={ref} u={u} />;
    if (k === 'Crop your photo') return <CropPhotoDialog modal={m} close={close} u={u} />;
    if (k === 'ArchHub menu') {
      const entries = [
        ['All pages…', () => u.show('Search')],
        ['How everything connects', () => u.go('system')],
        ['App health', () => u.go('receipts')],
        ['Community', () => u.go('community')],
        ['Social media', () => u.go('social')],
        ['Docs', () => u.go('docs')],
        ['Settings', () => u.go('settings/Account')]
      ];
      return <section ref={ref} role="menu" aria-label="ArchHub menu" data-design="mark.menu" style={{
          position: 'fixed', top: 52, left: 12, minWidth: 236, zIndex: 1050,
          background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
          borderRadius: 10, padding: 6, boxShadow: '0 14px 36px rgba(0,0,0,0.5)', display: 'grid', gap: 2
        }}>
          {entries.map(([label, action]) => <button type="button" role="menuitem" key={label} className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); action(); }}, event)}>{label}</button>)}
        </section>;
    }
    if (k === 'Workspace menu') {
      return <section ref={ref} role="menu" aria-label="Workspaces" data-design="workspace.menu" style={{
          position: 'fixed', top: 52, left: 48, minWidth: 240, zIndex: 1050,
          background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
          borderRadius: 10, padding: 6, boxShadow: '0 14px 36px rgba(0,0,0,0.5)', display: 'grid', gap: 2
        }}>
          {(s.workspaces || []).map(w => {
            const active = w.id === s.activeWorkspace;
            return <button type="button" role="menuitemradio" aria-checked={active} key={w.id} className="listbutton spread" onClick={event => executeAction('projects.controls.activate', {handler: async () => { await u.act(() => api.selectWorkspace(w.id)); close(); }}, event)}><span>{w.name}</span><span>{active ? '✓' : ''}</span></button>;
          })}
          <button type="button" role="menuitem" className="listbutton" style={{borderTop: '1px solid var(--color-line-soft, #1e1e24)', marginTop: 4, paddingTop: 8}} onClick={event => executeAction('projects.controls.activate', {handler: () => u.show('Workspaces')}, event)}>Add workspace…</button>
        </section>;
    }
    if (k === 'Rail item menu') {
      const idx = m.index ?? u.pinnedRailIds.indexOf(m.taskId);
      const reorder = delta => {
        const next = [...u.pinnedRailIds];
        const target = idx + delta;
        if (idx < 0 || target < 0 || target >= next.length) return;
        [next[idx], next[target]] = [next[target], next[idx]];
        close();
        return u.setPinnedRail(next);
      };
      return <section ref={ref} role="menu" aria-label="Rail item menu" data-design="rail.menu" style={{
          position: 'fixed', left: 72, top: Math.max(56, Math.min(m.anchor?.y || 140, window.innerHeight - 160)), minWidth: 196, zIndex: 1050,
          background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
          borderRadius: 10, padding: 6, boxShadow: '0 14px 36px rgba(0,0,0,0.5)', display: 'grid', gap: 2
        }}>
          <button type="button" role="menuitem" disabled={idx <= 0} className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => reorder(-1)}, event)}>Move up</button>
          <button type="button" role="menuitem" disabled={idx < 0 || idx >= u.pinnedRailIds.length - 1} className="listbutton" onClick={event => executeAction('projects.controls.activate', {handler: () => reorder(1)}, event)}>Move down</button>
          <button type="button" role="menuitem" className="listbutton" style={{color: 'var(--color-err, #e6705f)'}} onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); return u.setPinnedRail(u.pinnedRailIds.filter(id => id !== m.taskId)); }}, event)}>Remove from the rail</button>
        </section>;
    }
    if (k === 'Notifications') {
      const unreadIds = (s.notifications || []).filter(n => !n.read).map(n => n.id);
      const pendingApprovals = (s.approvals || []).filter(c => ['pending', 'postponed', 'stale', 'refused', 'contested'].includes(c.status));
      const markAllRead = () => u.act(async () => {
        if (!unreadIds.length || api.supportsAction?.('readNotification') === false) return {ok: true};
        try {
          return await api.readNotification('all');
        } catch {
          let last = {ok: true};
          for (const id of unreadIds) last = await api.readNotification(id);
          return last;
        }
      });
      return <section ref={ref} role="dialog" aria-modal="false" aria-label="Notifications" data-design="notifications.popover" style={{
          position: 'fixed', top: 52, right: 16, width: 'min(380px, calc(100vw - 32px))', maxHeight: 'min(480px, calc(100vh - 80px))', overflowY: 'auto', zIndex: 1050,
          background: 'var(--color-bg-panel, #15151a)', border: '1px solid var(--color-line, #26262e)',
          borderRadius: 12, padding: 14, boxShadow: '0 16px 40px rgba(0,0,0,0.55)', display: 'grid', gap: 10
        }}>
          <header className="spread">
            <h2 style={{fontSize: 15, margin: 0}}>Notifications</h2>
            <div className="flex" style={{gap: 6}}>
              <Btn sm ghost disabled={!unreadIds.length} onClick={event => executeAction('projects.controls.activate', {handler: markAllRead}, event)}>Mark all read</Btn>
              <Btn sm ghost aria-label="Close dialog" onClick={event => executeAction('appShell.CloseDialog.98', {close}, event)}>×</Btn>
            </div>
          </header>
          <div className="grid" style={{gap: 4}}>
            {(s.notifications || []).map(n => (api.supportsAction?.('readNotification') !== false && <button type="button" className="listbutton" key={n.id} onClick={event => executeAction("appShell.Control.49", {api, n, u}, event)}>{n.read ? '✓' : '●'} {n.text}</button>))}
            {pendingApprovals.map(c => <Btn key={c.id} onClick={event => executeAction("appShell.Review.50", {c, u}, event)}>Review · {c.title}</Btn>)}
            {!(s.notifications || []).length && !pendingApprovals.length && <Empty>You are all caught up.</Empty>}
          </div>
        </section>;
    }
    if (k === 'Delete task') {
      const remove = async () => {
        const generation = voiceGeneration.current;
        const result = await formAction.run(async () => {
          const receipt = await api.deleteTask(m.id, m.revision);
          if (receipt?.ok !== true || receipt.deleted !== true || receipt.id !== m.id)
            throw Error(receipt?.message || receipt?.error || 'ArchHub did not confirm this deletion.');
          return receipt;
        });
        if (!result) return;
        if (voiceGeneration.current === generation) close();
        if (u.canvasTabs.tabs.some(tab => tab.id === m.id)) await u.act(() => u.closeTaskTab(m.id));
      };
      const pending = formAction.state === 'waiting';
      return <div className="overlay"><section ref={ref} className="dialog v22g-form" role="alertdialog" aria-modal="true" aria-label="Delete task" aria-describedby="delete-task-warning">
        <h2>Delete task</h2><p id="delete-task-warning">Delete {m.title}? Its file and history are removed. This cannot be undone.</p>
        {formAction.error && <p role="alert">{formAction.error}</p>}
        <div className="flex"><Btn sm disabled={pending} onClick={event => executeAction('projects.controls.activate', {handler:close}, event)}>Cancel</Btn>
          <Btn sm danger disabled={pending} onClick={event => executeAction('projects.controls.activate', {handler:remove}, event)}>Delete</Btn></div>
      </section></div>;
    }
    if(k==='Save node type')return <div className="overlay"><section ref={ref} className="dialog v22g-form" role="dialog" aria-modal="true" aria-label={m.skill?'Save as skill':'Save as node type'}><h2>{m.skill?'Save as skill':'Save as node type'}</h2><NodeTypeForm modal={m} close={close}/></section></div>;
    if (k === 'Add node') {
      const trimmed = query.trim();
      const isNum = /^-?\d+(?:\.\d+)?$/.test(trimmed);
      const isQuoted = trimmed.length >= 2 && ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith('“') && trimmed.endsWith('”')));
      const literalVal = isNum ? Number(trimmed) : isQuoted ? trimmed.slice(1, -1) : null;
      const filtered = (s.libraryPorts || []).filter(n => !n.noEngine && matchesNodeType(n, mode) && n.title.toLowerCase().includes(trimmed.toLowerCase()));
      const addItem = item => saveForm(async () => {
        const node = m.wireId ? await api.insertNodeOnWire(m.wireId, item.id, m.point) : await api.addNode(item.id, m.point);
        if (node) u.setSelectedNodeId(node.id);
        return node;
      });
      const addLiteral = () => saveForm(async () => {
        const valueEngine = (s.libraryPorts || []).find(n => /value|number|text/i.test(n.id) && !n.noEngine)?.id || 'param.value';
        const node = await api.addNode(valueEngine, m.point);
        if (node) {
          await api.setNodeParam?.(node.id, 'value', literalVal);
          u.setSelectedNodeId(node.id);
        }
        return node || {ok: true};
      });
      return <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}>
        <section ref={ref} className="dialog v22g-form" role="dialog" aria-modal="true" aria-label="Add node" onKeyDown={e => {
          const inField = e.target.matches?.('input,textarea');
          if (e.key === 'Enter') {
            if (filtered[0]) { e.preventDefault(); void addItem(filtered[0]); }
            else if (literalVal !== null) { e.preventDefault(); void addLiteral(); }
          } else if (!inField && /^[1-9]$/.test(e.key)) {
            const pick = filtered[Number(e.key) - 1];
            if (pick) { e.preventDefault(); void addItem(pick); }
          }
        }}>
          <h2>Add node</h2>
          <window.UI.ActionStatus action={formAction} />
          <input data-design="addnode.input" aria-label="Add node" placeholder="Search the Library, or type a number or &quot;text&quot;…" value={query} onChange={e => setQuery(e.target.value)} />
          <div className="flex" role="group" aria-label="Node type filter" style={{gap: 4, flexWrap: 'wrap'}}>
            {ADD_NODE_TYPES.map(t => <button type="button" key={t} className="tab-button" aria-pressed={mode === t} onClick={event => executeAction('projects.controls.activate', {handler: () => setMode(t)}, event)}>{t}</button>)}
          </div>
          {literalVal !== null && <button type="button" data-design="addnode.value" className="listbutton spread" onClick={event => executeAction('projects.controls.activate', {handler: addLiteral}, event)}><span>Value: {String(literalVal)}</span><kbd>Value</kbd></button>}
          <div className="v22g-results">
            {filtered.map((n, idx) => <button type="button" className="listbutton spread" key={n.id} onClick={event => executeAction('projects.controls.activate', {handler: () => addItem(n)}, event)}><span>{n.title}</span>{idx < 9 ? <kbd>{idx + 1}</kbd> : <span className="muted">{n.category || ''}</span>}</button>)}
          </div>
        </section>
      </div>;
    }
    if (k === 'Colour' || k === 'Node colour') {
      const currentNode = s.graph.nodes.find(n => n.id === m.id);
      const activeHex = text || currentNode?.color || '';
      const applyColour = hex => saveForm(() => hex ? api.setNodePresentation(m.id, {color: hex}) : api.setNodeFlags(m.id, {color: ''}));
      return <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}>
        <section ref={ref} className="dialog v22g-form" role="dialog" aria-modal="true" aria-label={k} data-design="colour.menu">
          <h2>{k}</h2>
          <window.UI.ActionStatus action={formAction} />
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 6}}>
            {COLOUR_SWATCHES.map(([name, hex]) => <button type="button" key={name} aria-pressed={activeHex.toLowerCase() === hex.toLowerCase()} className="listbutton flex" style={{gap: 6, justifyContent: 'flex-start'}} onClick={event => executeAction('projects.controls.activate', {handler: () => applyColour(hex)}, event)}><span aria-hidden="true" style={{width: 14, height: 14, borderRadius: '50%', background: hex || 'transparent', border: '1px solid ' + (hex || A.line)}} /><span>{name}</span></button>)}
          </div>
          <label className="flex" style={{gap: 10}}><span>Custom</span><input type="color" aria-label="Node colour" value={activeHex || '#d97757'} onChange={e => setText(e.target.value)} /></label>
          <div className="flex">
            <button type="button" data-design="action.cancel" onClick={event => executeAction('projects.controls.activate', {handler: close}, event)}>Cancel</button>
            <button type="button" data-design="action.save" onClick={event => executeAction('projects.controls.activate', {handler: () => applyColour(text || currentNode?.color || '#d97757')}, event)}>Save</button>
          </div>
        </section>
      </div>;
    }
    if(['Rename node','Note','Wire rule','Find node'].includes(k))return <div className="overlay" onMouseDown={e=>{if(e.target===e.currentTarget)close();}}><section ref={ref} className="dialog v22g-form" role="dialog" aria-modal="true" aria-label={k}><h2>{k==='Rename node'?'Rename':k==='Note'?'Add note':k}</h2><window.UI.ActionStatus action={formAction}/>
      {k==='Find node'?<><input data-design="find.input" aria-label="Find a node" placeholder="Find a node…" value={query} onChange={e=>setQuery(e.target.value)}/><div className="v22g-results">{s.graph.nodes.filter(n=>n.title.toLowerCase().includes(query.toLowerCase())).map(n=><button type="button" className="listbutton" key={n.id} onClick={event=>executeAction('projects.controls.activate',{handler:()=>saveForm(async()=>{u.setSelectedNodeId(n.id);return {ok:true};})},event)}>{n.title}</button>)}</div></>:<label>{k==='Wire rule'?'Only pass values when':k==='Note'?'Note':'Name'}{k==='Note'?<textarea data-design="field.note" aria-label="Note" value={text} onChange={e=>setText(e.target.value)}/>:<input data-design={k==='Wire rule'?'field.only-pass-values-when':'field.rnt'} aria-label={k==='Wire rule'?'Only pass values when':'Node name'} value={text} onChange={e=>setText(e.target.value)}/>}</label>}
      {k==='Wire rule'&&<p className="muted">Use the existing wire condition expression, for example value &gt; 0.</p>}{k!=='Find node'&&<div className="flex"><button type="button" data-design="action.cancel" onClick={event=>executeAction('projects.controls.activate',{handler:close},event)}>Cancel</button><button type="button" data-design={k==='Rename node'?'action.rename':'action.save'} disabled={k!=='Wire rule'&&!text.trim()} onClick={event=>executeAction('projects.controls.activate',{handler:()=>saveForm(()=>k==='Rename node'?api.renameNode(m.id,text):k==='Note'?(m.id?api.setNodeParam(m.id,'text',text):api.addNote(text,m.point)):api.setWireRule(m.id,text))},event)}>{k==='Rename node'?'Rename':'Save'}</button></div>}</section></div>;
    if(k==='Add parameter')return <div className="overlay" ref={ref} onMouseDown={event=>{if(event.target===event.currentTarget)close();}}><window.UI.AddField modal kind="Parameter" title="Add parameter" sub="A value on this node" onClose={close} onAdd={input=>executeAction('appShell.AddParameter.28',{api,m,input,u})}/></div>;
    if(k==='Approve' && s.approvals.find(card=>card.id===m.id)?.approvalKind==='canvas') return <section ref={ref} className="v22g-approval-pop" role="dialog" aria-label="Approve Canvas Run" style={{position:'fixed',zIndex:1000,width:440,maxWidth:'calc(100vw - 32px)',left:Math.max(16,Math.min(m.anchor?.x || 400,window.innerWidth-456)),top:Math.max(16,Math.min(m.anchor?.y || 180,window.innerHeight-360))}}><window.UI.ApprovalCard id={m.id} /></section>;
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
      }, event)}>Save</Btn></>;else if (k === 'Subscription') body = <window.UI.BillingAccount />;else if (k === 'Paste settings') body = <window.UI.PasteSettings initial={m.text} destination={m.destination} label={m.label} close={close} />;else if (k === 'Keyboard shortcuts') body = <window.UI.KeyboardSettings />;else if (k === 'Raw log') {
      const messages = logTask ? window.UI.homeTaskMessages(logTask) : [];
      body = <div className="rawlog">{messages.length ? messages.map((row, index) => <p key={row.id || index}>{row.at && <time dateTime={row.at}>{row.at} </time>}<b>{row.who}</b> {row.text}</p>) : <p>No messages in this thread.</p>}</div>;
    } else if (k === 'Task details') body = <window.UI.TaskDetails id={m.id} />;else if (k === 'Node output') body = <window.UI.NodeOutput id={m.id} />;else if (k === 'Workflows') body = <window.UI.GraphManager />;else if (k === 'MCP tools') body = <window.UI.McpTools />;else if (k === 'Install mod' || k === 'Make a mod') body = <window.UI.ModManager making={k === 'Make a mod'} />;else if (k === 'Connection checks') body = <window.UI.ConnectionChecksDialog modal onClose={close} />;else if (k === 'Add a node or plugin') body = <window.UI.AddNodePluginDialog modal onClose={close} />;else if (k === 'Legacy workflows') body = <div className="grid">{s.graphs.map(g => <button className="listbutton spread" key={g.id} onClick={event => executeAction("appShell.Control.24", {
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
      }, event)}>Read status</Btn></>;else if (k === 'Approve') body = <window.UI.ApprovalCard id={m.id} />;else if (k === 'Search') {
      const searchOrder = window.ArchHubCommandRegistry.palette_order;
      const items = window.UI.paletteCommands(s,u,api,{query,mode,context:m.commandContext,actionState:formAction});
      body = <><input data-design="palette.input" aria-label="Search everything" placeholder="Find an agent, workflow, program, setting, node or chat…" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => {
          if (e.key === 'Enter' && items[0] && !items[0].disabled) items[0].action();
        }} /><div className="flex">{['All', ...searchOrder].map(t => <Btn key={t} sm ghost plain aria-pressed={mode === t} onClick={event => executeAction("appShell.Control.29", {
            setMode,
            t
          }, event)}>{t}</Btn>)}</div><div className="v22g-palette-results" style={{
          maxHeight: '55vh',
          overflow: 'auto'
        }}>{items.map((item, i) => <button data-design="palette.row" data-command-id={item.id} disabled={!!item.disabled} title={item.disabledReason || undefined} className="listbutton spread" key={i} onClick={event => executeAction("appShell.Control.30", {
            item
          }, event)}><span>{item.label}</span><span className="muted" style={{
              fontSize: 'calc(11px * var(--text-scale,1))'
            }}>{item.group}</span></button>)}{!items.length && <Empty>No results.</Empty>}</div></>;
    }
    else if (k === 'Rename task') body = <><label className="grid">Task name<input aria-label="Task name" value={text} onChange={e => setText(e.target.value)} /></label><div className="flex"><Btn onClick={event=>executeAction('projects.controls.activate',{handler:close},event)}>Cancel</Btn><Btn p disabled={!text.trim()} onClick={event=>executeAction('projects.controls.activate',{handler:() => u.act(async () => {const result=await api.renameTask(m.id,text.trim());if(result)close();return result;})},event)}>Rename</Btn></div></>;
    else if (k === 'Attach meeting notes') body = <><label className="grid">Meeting notes<textarea aria-label="Meeting notes" rows={8} maxLength={4000} value={text} onChange={e=>setText(e.target.value)} /></label><div className="flex"><Btn onClick={event=>executeAction('projects.controls.activate',{handler:close},event)}>Cancel</Btn><Btn p disabled={!text.trim()} onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(async()=>{const result=await api.attachMeetingNotes(u.task,text);if(result)close();return result;})},event)}>Attach to thread</Btn></div></>;
    else if (k === 'Confirm') {
      const detail = m.detail !== undefined ? m.detail : 'Undo brings it back.';
      body = <><p>{m.title}</p>{detail ? <p className="muted">{detail}</p> : null}<div className="flex"><Btn onClick={event => executeAction("appShell.Cancel.31", {
          close
        }, event)}>Cancel</Btn><Btn danger onClick={event => executeAction("appShell.Confirm.32", {
          m,
          saved
        }, event)}>{m.confirmLabel || 'Confirm'}</Btn></div></>;
    } else if (k === 'Usage today') {
      const rows = (s.liveAgents && s.liveAgents.length ? s.liveAgents.map(a => ({
        agent: a.name || a.agent || a.handle || 'Agent',
        calls: a.calls ?? (s.tasks || []).filter(t => t.agent === (a.agent || a.handle)).length,
        tokens: a.tokens ?? 0,
        status: a.status || 'ready'
      })) : (s.agents || []).map(a => ({
        agent: a.name || a.id,
        calls: (s.tasks || []).filter(t => t.agent === a.id).length,
        tokens: a.tokens ?? 0,
        status: a.status || 'ready'
      })));
      body = <div className="grid" style={{gap: 12}}>
        <Table rows={rows} columns={['agent', 'calls', 'tokens', 'status']} />
        <div className="flex"><Btn p onClick={event => executeAction('projects.controls.activate', {handler: () => { close(); u.go('settings/Agents'); }}, event)}>Settings › Agents</Btn></div>
      </div>;
    } else if (k === 'Send feedback') {
      body = <div className="grid" style={{gap: 10}}>
        <label className="grid">What should we improve?<textarea aria-label="Feedback" rows={4} placeholder="Tell us what worked or what got in the way…" value={text} onChange={e => setText(e.target.value)} /></label>
        <div className="flex">
          <Btn onClick={event => executeAction('projects.controls.activate', {handler: close}, event)}>Cancel</Btn>
          <Btn p disabled={!text.trim()} onClick={event => executeAction('projects.controls.activate', {handler: async () => {
            const res = await u.act(() => typeof api.sendFeedback === 'function' ? api.sendFeedback(text.trim()) : Promise.resolve({ok: true}));
            if (res) { close(); u.setToast({text: 'Feedback sent.'}); }
          }}, event)}>Send</Btn>
        </div>
      </div>;
    } else if (k === "What's new" || k === 'What’s new') {
      body = <div className="grid" style={{gap: 10}}>
        <div className="spread"><b>Version {s.update?.installed || 'current'}</b><Chip c={A.ok}>{s.update?.available ? 'Update ready' : 'Up to date'}</Chip></div>
        <p>{s.update?.detail || 'One companion, one Workshop, editable nodes and settings, and a clear review before a change.'}</p>
        <div className="flex"><Btn onClick={event => executeAction("appShell.UpdatesAbout.96", {u}, event)}>Updates &amp; About</Btn></div>
      </div>;
    } else if (k === 'New task') body = <><label className="grid">Task name<input data-design="newtask.name" aria-label="Task name" value={text} onChange={e => setText(e.target.value)} placeholder="Name this task" /></label><div className="v22g-task-options"><label className="grid">Agent<select data-design="newtask.agent" aria-label="Agent" value={extra} onChange={e => setExtra(e.target.value)}><option value="">No agent</option>{(window.UI.workshopPeople?.(s).choices || []).filter(row=>row.key!=='everyone').map(row=><option key={row.key} value={row.handle || row.name}>{row.name}</option>)}</select></label><label className="grid">Workspace<select data-design="newtask.workspace" aria-label="Workspace" value={taskWorkspace} onChange={e => setTaskWorkspace(e.target.value)}><option value="">Sessions folder</option>{s.workspaces.filter(row=>!row.builtIn && row.available!==false).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label></div><p className="v22g-task-hint">Opens its own .archhub file on the Canvas with the Agent, You, Workshop and Session nodes already in it. Nothing runs until you press Run.</p><div className="flex"><Btn data-design="newtask.cancel" onClick={event=>executeAction('projects.controls.activate',{handler:close},event)}>Cancel</Btn><Btn p data-design="newtask.create" disabled={!text.trim()} onClick={event=>executeAction('projects.controls.activate',{handler:() => u.act(async () => {const made=await api.createTask(text.trim(),extra,taskWorkspace);if(made?.taskId){await u.openTaskFile(made.taskId);await u.keepTaskTab(made.taskId);}return made;})},event)}>Create and open</Btn></div></>; else if (k === 'Account') body = <><h2>{s.profile.name}</h2><p className="muted">{s.profile.firm} · {s.people.length} people</p><div className="grid">{['My profile', 'My secrets', 'My files', 'Workspaces'].map(t => <Btn key={t} onClick={event => executeAction("appShell.Control.33", {
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
      }, event)}>Open ArchHub</Btn><Btn onClick={event => executeAction("appShell.BABOOM.45", {
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
      gridTemplateColumns: 'repeat(3,minmax(200px,1fr))',
      minHeight: 300
    }}>{window.UI.workshopGroups(false, new Set(s.approvals.filter(c => c.status === 'pending').map(c => c.taskId))).map(([name, member, status]) => <div className="task-column" key={name} data-workshop-lane={name} onDragOver={e => e.preventDefault()} onDrop={e => {
        e.preventDefault();
        const id = e.dataTransfer.getData('task');
        if (id) u.act(() => api.setTaskStatus(id, status));
      }}><h3 style={{
          color: A.inkSoft
        }}>{name} · {s.tasks.filter(member).length}</h3>{s.tasks.filter(member).map(t => <Card key={t.id} style={{
          padding: 8
        }}><window.UI.Task task={t} select={() => u.openTaskFile(t.id)} /></Card>)}</div>)}</div>;else if (k === 'Notifications' || k === 'Founder inbox') body = <div className="grid">{s.notifications.map(n => (api.supportsAction?.('readNotification') !== false && <button className="listbutton" key={n.id} onClick={event => executeAction("appShell.Control.49", {
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
      }, event)}>Save session</Btn><Btn danger sm onClick={event => executeAction("appShell.Delete.71", {
        m
      }, event)}>Delete…</Btn></div>;else if (k === 'Parameter socket') body = <><p>{m.page} is an application node. Its parameters are the same values shown in Settings.</p><div className="grid">{s.settings.filter(r => r.page === m.page).map(r => <div key={r.id} className="spread row"><span>{r.label} · {r.type}</span><Btn sm onClick={event => executeAction("appShell.ExposeOnCanvas.72", {
            api,
            m,
            r,
            u
          }, event)}>Expose on canvas</Btn></div>)}</div><Btn onClick={event => executeAction("appShell.OpenSystemGraph.73", {
        u
      }, event)}>Open System graph</Btn></>;else if (k === 'Trace back' || k === 'Trace forward') body = <div className="grid">{m.rows?.map(r => <button className="listbutton" key={r.id} onClick={event => executeAction("appShell.Control.75", {
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
      }, event)}>Add comment</Btn>}</>;else if (k === 'Comment') body = <p>{m.text}</p>;else if (k === 'Invite to watch') body = <window.UI.WatchInvite path={m.path} title={m.title} />;else if (k === 'Watching') body = <window.UI.WatchView grant={m.grant} />;else if (k === 'Invite') body =<><label className="grid">Email<input type="email" aria-label="Teammate email" value={text} placeholder="colleague@office.com" onChange={e => setText(e.target.value)} /></label><Btn p disabled={!text.includes('@')} onClick={event => executeAction("appShell.Invite.78", {
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
    } else if (k === 'Sign in') body = <SignInControls/>;else if (k === 'Talk') {
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
    if (['Node menu', 'Group menu', 'Wire menu', 'Selection menu', 'Canvas menu', 'App menu', 'Tray', 'Port menu', 'Task tab menu', 'Open tasks', 'Task message menu', 'Canvas attachments', 'Surface menu'].includes(k)) return <window.UI.ContextMenu kind={k} nodeId={m.id} wireId={m.wireId} canvas={m.canvas} message={m.message} taskId={m.taskId} port={m.port} paramKey={m.paramKey} open={m.open} selected={m.selected} group={m.group} remove={m.remove} anchor={m.anchor} surface={m.surface} close={close} />;
    return <div className="overlay" onMouseDown={e => {
      if (e.target === e.currentTarget) close();
    }}><section ref={ref} className={'dialog'+(k==='Search'?' v22g-palette':'')} role="dialog" aria-modal="true" aria-label={title} style={{
        width: k === 'Workshop board' ? 'min(1250px,95vw)' : k === 'Approve' ? 'min(850px,95vw)' : undefined
      }}><header className="spread"><h2>{title}</h2><Btn sm ghost aria-label="Close dialog" onClick={event => executeAction("appShell.CloseDialog.98", {
            close
          }, event)}>×</Btn></header><Boundary key={k}>{body}</Boundary></section></div>;
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
  window.ReactDOM.createRoot(document.getElementById('root')).render(<Boundary><DesktopEntry /></Boundary>);
})();
(() => {
  function appShellArchHubMenu1({
    close,
    modal,
    show
  }, event) {
    const handler = () => modal?.kind === 'ArchHub menu' ? close() : show('ArchHub menu');
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
    close,
    modal,
    show
  }, event) {
    const handler = () => modal?.kind === 'Workspace menu' ? close() : show('Workspace menu');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellSearchCtrlK5({
    show
  }, event) {
    const handler = () => show('Search');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellNotifications6({
    close,
    modal,
    show
  }, event) {
    const handler = () => modal?.kind === 'Notifications' ? close() : show('Notifications');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellTrayMenu7({
    show
  }, event) {
    const handler = () => show('Tray');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellWindowControl99({
    api,
    action
  }, event) {
    const handler = () => api.windowAction(action);
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
    close,
    modal,
    show
  }, event) {
    const handler = () => modal?.kind === 'Profile card' ? close() : show('Profile card');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellControl13({
    go
  }, event) {
    const handler = () => go('settings/Connections');
    return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
  }
  function appShellRunningWaitForYou14({
    act,
    api,
    go,
    filter = 'Needs you'
  }, event) {
    // A count is a filter of Home's map: the filter is a parameter in the Home owner record, then Home opens.
    const handler = () => act(async () => {
      const {homeLayout} = await api.readHomeLayout();
      await api.setHomeLayout({...homeLayout, map: {...(homeLayout.map || {}), filter}});
      go('home');
    });
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
    input,
    u
  }, event) {
    const handler = () => api.addNodeParameter(m.id,input);
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
      const result = await u.act(() => api.readNotification(n.id));
      if(!result)return;
      const snap = api.getSnapshot();
      const card = snap.approvals.find(card => (n.approvalId && card.id === n.approvalId) || (card.status === 'pending' && ((n.taskId && (card.taskId === n.taskId || card.work === n.taskId)) || n.id.startsWith('approval:'))));
      if(card)u.show('Approve',{id:card.id});
      else if(n.taskId)await u.openTaskFile(n.taskId,'split');
      else u.close();
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
    const handler = () => u.schedule(t.id);
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
    // Rerun is Run again (F10): again=true invalidates cached step results for this root.
    const handler = () => saved(() => api.runNode(n.id, true));
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
    const handler = () => u.act(() => window.ArchHubAPI.saveSession());
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
        // Rule 10: no fixed sample value. The parameter stays empty and takes the focus for the founder's own value.
        u.go('canvas');
        const focusField = () => {
          const field = document.querySelector('[data-graph-node="' + n.id + '"] [data-parameter="example"]');
          (field?.querySelector('input,textarea,select,button') || field)?.focus?.();
        };
        window.requestAnimationFrame(() => window.requestAnimationFrame(focusField));
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
    "appShell.CloseDialog.98": "appShellCloseDialog98",
    "appShell.WindowControl.99": "appShellWindowControl99",
    "appShell.RailOpenTask": "appShellRailOpenTask"
  };
  window.registerActions(appShellActions, {
    appShellRailOpenTask: ({openTaskFile, tid}) => openTaskFile(tid),
    appShellRetryWorkshop: ({reloadWorkshop}) => reloadWorkshop(),
    appShellRetryView,
    appShellArchHubMenu1,
    appShellArchHub2,
    appShellControl3,
    appShellControl4,
    appShellSearchCtrlK5,
    appShellNotifications6,
    appShellTrayMenu7,
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
    appShellCloseDialog98,
    appShellWindowControl99
  });
})();
