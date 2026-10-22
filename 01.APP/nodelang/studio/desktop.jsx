// Desktop work is projected by the existing native companion and host owners.
(() => {
  const {
    api,
    useApp,
    Heading,
    Empty,
    Btn,
    Card,
    Chip
  } = window.UI;
  function DesktopScene() {
    const s = window.UI.useData(), desktop = s.desktop, u = useApp(),
      actionState = window.UI.useAction(),
      [frame, setFrame] = React.useState(null),
      [busy, setBusy] = React.useState(false);
    async function refresh() {
      setBusy(true);
      try {
        const value = await actionState.run(api.getDesktopCompanion);
        if (value && value.ok !== false) setFrame(value);else setFrame(null);
      } finally {
        setBusy(false);
      }
    }
    function handleDesktopjsx1(event) {
      return refresh();
    }
    function handleDesktopjsx2() {
      return u.go('settings/BABOOM');
    }
    function handleProgram(event) { return actionState.run(() => api.setDesktopProgram(event.target.value)); }
    function handleSuggest() { return actionState.run(api.offerDesktopAction); }
    async function handlePrepare() {
      const card = await actionState.run(api.prepareDesktopAction);
      if (card?.id) u.show('Approve', {id:card.id});
    }
    function handleReview() { return u.show('Approve', {id:desktop.taskId}); }
    const ACTIONS = {
      "desktop.1": "handleDesktopjsx1",
      "desktop.2": "handleDesktopjsx2",
      "desktop.program": "handleProgram", "desktop.suggest": "handleSuggest",
      "desktop.prepare": "handlePrepare", "desktop.review": "handleReview"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleDesktopjsx1,
        handleDesktopjsx2, handleProgram, handleSuggest, handlePrepare, handleReview
      })(id, ...args);
    }
    return <main className="page" data-screen="desktop"><window.UI.ActionStatus action={actionState} /><Heading title="Desktop" sub="BABOOM runs over your programs through the native companion.">
   <Btn disabled={busy} onClick={(event) => dispatch("desktop.1", event)}>Read companion state</Btn><Btn onClick={(event) => dispatch("desktop.2", event)}>BABOOM settings</Btn></Heading>
   {api.supportsAction?.('setDesktopProgram') && <Card style={{padding:22}}>
    <label>Working in <select aria-label="Working in" value={desktop.program || ''} onChange={e => dispatch("desktop.program", e)}>
     <option value="">Select a connected program</option>{['Revit','AutoCAD'].map(program => <option key={program}>{program}</option>)}
    </select></label><Chip>{desktop.stage}</Chip>
    {(desktop.offers || []).map(offer => <p key={offer.action}>{offer.title}: {offer.payload.source.element.label}{offer.action === 'move' ? ' · ' + offer.payload.offsetMm + ' mm offset' : ''}</p>)}
    <div className="row"><Btn disabled={!desktop.program} onClick={() => dispatch("desktop.suggest")}>Suggest</Btn>
     <Btn disabled={!desktop.offers?.length} onClick={() => dispatch("desktop.prepare")}>Prepare the change</Btn>
     {desktop.taskId && <Btn onClick={() => dispatch("desktop.review")}>Review change</Btn>}</div>
   </Card>}
   {frame ? <Card style={{
        padding: 22
      }}><div className="spread"><h2>BABOOM</h2><Chip>{frame.status}</Chip></div><p>{frame.message}</p>
    {frame.revision !== undefined && <p className="muted">Native frame revision {frame.revision}</p>}</Card> : <Empty>Read the current native frame to see BABOOM's state.</Empty>}
  </main>;
  }
  window.UI.DesktopScene = DesktopScene;
})();
