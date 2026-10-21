// Watcher reads the existing connector evidence owner without opening a host.
(() => {
  const {
    api,
    useData,
    useApp,
    Heading,
    Btn,
    Card,
    Table
  } = window.UI;
  function Watcher() {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction();
    const ACTIONS = {
      "watcher.read": "readSource",
      "watcher.connections": "openConnections"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        readSource: () => actionState.run(api.readHostAvailability),
        openConnections: () => u.go('settings/Connections')
      })(id, ...args);
    }
    return <main className="page watcher-page" data-screen="watcher">
   <Heading title="Watcher" sub={s.watcher.host || 'Host source and operation evidence'}>
    <Btn disabled={actionState.state === 'waiting'} onClick={() => dispatch('watcher.read')}>Read source</Btn>
    <Btn onClick={() => dispatch('watcher.connections')}>Connections</Btn>
   </Heading>
   <window.UI.ActionStatus action={actionState} empty="Read the source to discover current host availability and supported operations." />
   {actionState.result?.operations?.length > 0 && <Card><Table rows={actionState.result.operations} columns={['host', 'operation', 'status', 'reason']} /></Card>}
   {s.watcher.host && <window.UI.WatcherDimensions />}
  </main>;
  }
  window.UI.Watcher = Watcher;
})();
