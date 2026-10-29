// DSYS-062/063: six original first-run steps, one card and one primary action.
(() => {
  const WIRE_DS_FIRSTRUN_JSX_ACTIONS = {
  "settings.ds_firstrun.FirstRunAction0": "FirstRunAction0",
  "settings.ds_firstrun.FirstRunAction1": "FirstRunAction1",
  "settings.ds_firstrun.FirstRunAction2": "FirstRunAction2",
  "settings.ds_firstrun.FirstRunAction3": "FirstRunAction3",
  "settings.ds_firstrun.FirstRunAction4": "FirstRunAction4",
  "settings.ds_firstrun.FirstRunAction5": "FirstRunAction5",
  "settings.ds_firstrun.FirstRunAction6": "FirstRunAction6",
  "settings.ds_firstrun.FirstRunAction7": "FirstRunAction7",
  "settings.ds_firstrun.FirstRunAction8": "FirstRunAction8",
  "settings.ds_firstrun.FirstRunAction9": "FirstRunAction9",
  "settings.ds_firstrun.FirstRunAction10": "FirstRunAction10",
  "settings.ds_firstrun.FirstRunAction11": "FirstRunAction11",
  "settings.ds_firstrun.FirstRunAction12": "FirstRunAction12"
};
  const {
    A,
    api,
    useData,
    useApp,
    Btn,
    Card,
    Heading,
    Chip,
    ApprovalCard
  } = window.UI;
  function FirstRun() {
    const s = useData(),
      u = useApp();
    const [step, setStep] = React.useState(0),
      [task, setTask] = React.useState(null),
      [first, setFirst] = React.useState('');
    // Step 3 offers what Home offers first (most-run template); with none, the founder types the first task.
    const starter = s.templates.slice().sort((a, b) => (b.runs ?? 0) - (a.runs ?? 0))[0];
    const hostOpen = (s.hosts || []).some(h => h.state === 'connected' || h.state === 'listening');
    React.useEffect(() => { if (step === 0 && s.profile.signedIn) setStep(1); }, [step, s.profile.signedIn]);
    const titles = ['Sign in to ArchHub', 'Your programs', 'What should the agent look at first?', 'First: a read-only audit', 'The agent wants to change your model', 'Your first result'];
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_DS_FIRSTRUN_JSX_ACTIONS, {FirstRunAction0: (event) => (async () => {
              const result = await api.signIn(true);
              if (result?.ok === false) throw Error(result.message || 'Sign in failed. Retry in your browser.');
            })(event),
FirstRunAction1: (event) => (() => setStep(1))(event),
FirstRunAction2: (event) => (() => setStep(2))(event),
FirstRunAction3: (event) => (() => setStep(3))(event),
FirstRunAction4: (event) => (async () => {
              if (!starter && !first.trim()) throw Error('Type your first task, then press Do this task.');
              const t = await u.act(() => starter ? api.startTemplate(starter.id) : api.sendToBaboom(first.trim()));
              if (t) {
                setTask(t.id);
                setStep(4);
              }
            })(event),
FirstRunAction5: (event) => (() => u.go('canvas'))(event),
FirstRunAction6: (event) => (() => { u.setTask(task); u.go('workshop'); })(event),
FirstRunAction7: (event) => (() => { if (s.tasks.find(t => t.id === task)?.status !== 'DONE') throw Error('Open this task in Workshop and wait for its checked result, then retry.'); setStep(5); })(event),
FirstRunAction8: (event) => (() => u.go('canvas'))(event),
FirstRunAction9: (event) => (() => u.schedule(task))(event),
FirstRunAction10: (event) => (() => u.go('home'))(event),
FirstRunAction11: (event) => (() => setStep(step + 1))(event),
FirstRunAction12: (event) => (() => u.act(() => api.openProgram('revit')))(event)});
    return <>{actionState.status === 'waiting' ? <p role="status">Waiting for the account or task owner…</p> : actionState.status === 'error' ? <window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /> : actionState.status === 'loaded' ? <p role="status">{actionState.message || 'Request confirmed'}</p> : actionState.status === 'empty' ? <p className="muted">Choose how to get started.</p> : null}<main className="page" data-screen="first-run" style={{
      display: 'grid',
      placeItems: 'center'
    }}><div style={{
        width: 'min(720px,100%)',
        display: 'grid',
        gap: 20
      }}><div className="spread"><h2>ArchHub</h2><span className="muted">{step + 1} / 6</span></div><Card style={{
          padding: 28,
          display: 'grid',
          gap: 20
        }}><Heading title={titles[step]} />{step === 0 && <window.UI.OnboardingProfile />}{step === 0 ? <><p className="muted">Your account brings your agents, skills and Brain with you.</p><Btn p onClick={event => runAction('settings.ds_firstrun.FirstRunAction0', event)}>Sign in with your browser</Btn><Btn ghost onClick={event => runAction('settings.ds_firstrun.FirstRunAction1', event)}>Continue and sign in later</Btn></> : step === 1 ? <><window.UI.Connections /><Btn p onClick={event => runAction('settings.ds_firstrun.FirstRunAction2', event)}>Next</Btn></> : step === 2 ? <><window.UI.WorkspaceRows /><Btn p onClick={event => runAction('settings.ds_firstrun.FirstRunAction3', event)}>Next</Btn></> : step === 3 ? <>{starter ? <p><b>{starter.title}</b>{starter.chain?.length ? ' · ' + starter.chain.slice(0, 4).join(' → ') : ''}</p> : <><label style={{display: 'grid', gap: 6}}>Type your first task<textarea aria-label="Type your first task" rows={3} value={first} onChange={e => setFirst(e.target.value)} /></label>{!hostOpen && <Btn onClick={event => runAction('settings.ds_firstrun.FirstRunAction12', event)}>Open Revit</Btn>}</>}<Btn p disabled={!starter && !first.trim()} onClick={event => runAction('settings.ds_firstrun.FirstRunAction4', event)}>Do this task</Btn><Btn ghost onClick={event => runAction('settings.ds_firstrun.FirstRunAction5', event)}>Plan · as nodes</Btn></> : step === 4 ? <><ApprovalCard id={s.tasks.find(t => t.id === task)?.approvalId} /><div className="flex"><Btn sm ghost onClick={event => runAction('settings.ds_firstrun.FirstRunAction6', event)}>Ask why</Btn><Btn p onClick={event => runAction('settings.ds_firstrun.FirstRunAction7', event)}>Next</Btn></div></> : <><Chip c={A.ok}>{s.tasks.find(t => t.id === task)?.status === 'DONE' ? 'Your change is checked' : 'Check the task status before continuing'}</Chip><div className="flex"><Btn onClick={event => runAction('settings.ds_firstrun.FirstRunAction8', event)}>Open on canvas</Btn><Btn onClick={event => runAction('settings.ds_firstrun.FirstRunAction9', event)}>Run it every morning</Btn></div><Btn p onClick={event => runAction('settings.ds_firstrun.FirstRunAction10', event)}>Go to Home</Btn></>}{step > 0 && step < 5 && <Btn ghost onClick={event => runAction('settings.ds_firstrun.FirstRunAction11', event)}>Skip</Btn>}</Card></div></main></>;
  }
  window.UI.FirstRun = FirstRun;
})();
