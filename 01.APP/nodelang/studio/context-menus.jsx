// Menus stay anchored to the object. Dialogs are reserved for a decision/form.
(() => {
  const {
      api,
      useData,
      useApp
    } = window.UI,
    Icon = window.AHIcon;
  function ContextMenu({
    kind,
    nodeId,
    port,
    open,
    selected = [],
    group,
    remove,
    close,
    anchor
  }) {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction(),
      n = s.graph.nodes.find((n) => n.id === nodeId);
    const run = async (fn) => {
      const result = await actionState.run(fn);
      if (result?.approvalId) u.show('Approve', {
        id: result.approvalId
      });else if (result) close();
    };
    let groups = [];
    if (kind === 'Port menu' && n) groups = [[...['Visible', 'Faint', 'Hidden'].map((v) => [v + ' wires', 'link', '', () => actionState.run(() => api.setPortVisibility(n.id, port, v))])]];else if (kind === 'Node menu' && n) groups = [[['Open', 'arrow', 'Enter', () => {
      close();
      if (open) open();else u.go('canvas');
    }], ['Properties', 'settings', '', () => {
      close();
      u.show('Node', {id: n.id});
    }], ['Output', 'eye', '', () => u.show('Node output', {
      id: n.id
    })]], [['Rerun', 'refresh', '', () => run(() => api.runNode(n.id))], ['Run to here', 'play', '', () => run(() => api.runToHere(n.id))], [n.frozen ? 'Unfreeze' : 'Freeze', 'shield', '', () => actionState.run(() => api.setNodeFlags(n.id, {
      frozen: !n.frozen
    }))], [n.pinned ? 'Unpin output' : 'Pin output', 'pin', '', () => actionState.run(() => api.setNodeFlags(n.id, {
      pinned: !n.pinned
    }))]], [['Fork', 'canvas', '', () => run(() => api.forkNode(n.id))], ['Repeat this', 'clock', '', () => u.schedule(n.id)], ['Trace back', 'back', '', () => u.trace(n.id, 'back')], ['Trace forward', 'arrow', '', () => u.trace(n.id, 'forward')], ...(n.children ? [['Ungroup', 'group', '', () => run(() => api.ungroupNode(n.id))]] : [])], [['Delete…', 'trash', 'Del', () => u.confirm('Delete ' + n.title + '?', () => api.deleteNode(n.id)), true]]];else if (kind === 'Canvas menu') groups = [[['Add node', 'plus', 'Ctrl K', () => u.show('Search')], ['Arrange', 'arrange', '', () => run(api.arrangeGraph)], ['Group · Ctrl G', 'group', 'Ctrl G', () => actionState.run(() => {
      if (typeof group !== 'function') throw Error('Select nodes on Canvas and reopen the Group menu.');
      return group();
    }), false, selected.length < 2], ['Save as skill', 'pin', '', () => u.show('Save skill')]], [['Delete…', 'trash', 'Del', () => actionState.run(() => { if (typeof remove !== 'function') throw Error('Select nodes on Canvas and reopen the Delete menu.'); return remove(); }), true]]];else if (kind === 'Tray') groups = [[['Open ArchHub', 'home', '', () => run(() => api.windowAction('open'))], ['BABOOM', 'brain', 'F2', () => {
      close();
      u.go('baboom');
    }], ['Stop everything', 'stop', '', () => run(api.stopEverything)]], [['Hide', 'eye', '', () => run(() => api.windowAction('hide'))], ['Quit', 'close', '', () => run(() => api.windowAction('quit')), true]]];else {
      const names = {
        meetings: 'Meetings',
        dependencies: 'Dependencies',
        home: 'Home',
        workshop: 'Workshop',
        canvas: 'Canvas',
        docs: 'Docs',
        colleagues: 'Team',
        brain: 'Brain',
        watcher: 'Watcher',
        social: 'Social media',
        xray: 'X-RAY',
        'model-review': 'Model review',
        community: 'Community',
        present: 'Present',
        interface: 'Interface studio',
        access: 'Plan & access',
        routing: 'Model routing',
        automations: 'Automations',
        runs: 'Runs',
        receipts: 'Logs & receipts',
        feedback: 'Feedback',
        system: 'System graph',
        'first-run': 'First run'
      };
      groups = [Object.entries(names).map(([route, label]) => [label, route === 'home' ? 'home' : route === 'workshop' ? 'workshop' : route === 'docs' ? 'docs' : 'canvas', '', () => u.go(route)]), [['Settings', 'settings', 'Ctrl ,', () => u.go('settings/Account')]]];
    }
    const left = Math.max(8, Math.min(anchor?.x || 100, window.innerWidth - 266)),
      top = Math.max(8, Math.min(anchor?.y || 58, window.innerHeight - 520));
    function handleContextmenusjsx1(action, event) {
      return action(event);
    }
    const ACTIONS = {
      "context-menus.1": "handleContextmenusjsx1"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleContextmenusjsx1
      })(id, ...args);
    }
    return <><div className="context-dismiss" onMouseDown={close} /><section className="context-menu" role="menu" aria-label={kind} style={{
        left,
        top
      }} onKeyDown={(e) => {
        const buttons = [...e.currentTarget.querySelectorAll('button:not(:disabled)')];
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          const at = buttons.indexOf(document.activeElement);
          buttons[(at + (e.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length]?.focus();
        }
        if (e.key === 'Escape') close();
      }}><window.UI.ActionStatus action={actionState} />{groups.map((rows, i) => <div className="context-group" key={i}>{rows.map(([label, icon, key, action, danger, disabled]) => <button key={label} disabled={disabled} className={danger ? 'danger' : ''} onClick={(event) => dispatch("context-menus.1", action, event)}><Icon name={icon} size={15} /><span>{label}</span><kbd>{key}</kbd></button>)}</div>)}</section></>;
  }
  window.UI.ContextMenu = ContextMenu;
})();
