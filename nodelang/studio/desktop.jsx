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
    const u = useApp(),
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
    const ACTIONS = {
      "desktop.1": "handleDesktopjsx1",
      "desktop.2": "handleDesktopjsx2"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleDesktopjsx1,
        handleDesktopjsx2
      })(id, ...args);
    }
    return <main className="page" data-screen="desktop"><window.UI.ActionStatus action={actionState} /><Heading title="Desktop" sub="BABOOM runs over your programs through the native companion.">
   <Btn disabled={busy} onClick={(event) => dispatch("desktop.1", event)}>Read companion state</Btn><Btn onClick={(event) => dispatch("desktop.2", event)}>BABOOM settings</Btn></Heading>
   {frame ? <Card style={{
        padding: 22
      }}><div className="spread"><h2>BABOOM</h2><Chip>{frame.status}</Chip></div><p>{frame.message}</p>
    {frame.revision !== undefined && <p className="muted">Native frame revision {frame.revision}</p>}</Card> : <Empty>Read the current native frame to see BABOOM's state.</Empty>}
  </main>;
  }
  window.UI.DesktopScene = DesktopScene;
})();
