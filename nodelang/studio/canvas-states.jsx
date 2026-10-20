(() => {
  const {
      D,
      api,
      useData,
      useApp,
      Btn
    } = window.UI,
    Icon = window.AHIcon;
  function GraphProperties() {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction(),
      g = s.graph;
    function handleCanvasstatesjsx1() {
      return u.show('Workspaces');
    }
    function handleCanvasstatesjsx2() {
      return u.show('Graphs');
    }
    function handleCanvasstatesjsx3() {
      return u.go('settings/System graph');
    }
    const ACTIONS = {
      "canvas-states.1": "handleCanvasstatesjsx1",
      "canvas-states.2": "handleCanvasstatesjsx2",
      "canvas-states.3": "handleCanvasstatesjsx3"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleCanvasstatesjsx1,
        handleCanvasstatesjsx2,
        handleCanvasstatesjsx3
      })(id, ...args);
    }
    return <div className="grid"><window.UI.ActionStatus action={actionState} /><div className="spread"><h2>Graph</h2><Icon name="canvas" size={18} /></div><p className="muted">The working space and its shared parameters.</p><label className="grid">Name<input aria-label="Graph name" value={g.name} onChange={(e) => actionState.run(async () => await api.updateGraph(g.id, {
          name: e.target.value
        }))} /></label><label className="grid">Owner<select aria-label="Graph owner" value={g.humanOwner || s.profile.name || 'Unassigned'} onChange={(e) => actionState.run(async () => await api.updateGraph(g.id, {
          humanOwner: e.target.value
        }))}>{s.people.map((p) => <option key={p.id}>{p.name}</option>)}</select></label><label className="grid">Description<textarea aria-label="Graph description" rows={4} value={g.description || ''} placeholder="What does this workflow do?" onChange={(e) => actionState.run(async () => await api.updateGraph(g.id, {
          description: e.target.value
        }))} /></label><div className="row spread"><span>{g.nodes.length} nodes</span><span className="muted">{g.wires.length} relations</span></div><div className="row spread"><span>Keep at the top</span><D.Toggle label="Pin graph" checked={!!g.pinned} onCheckedChange={(v) => actionState.run(() => api.updateGraph(g.id, {
          pinned: v
        }))} /></div><window.UI.GraphMetadata /><Btn sm onClick={(event) => dispatch("canvas-states.1", event)}>Graph workspaces</Btn><Btn sm onClick={(event) => dispatch("canvas-states.2", event)}>Versions &amp; other graphs</Btn><Btn sm onClick={(event) => dispatch("canvas-states.3", event)}>Graph preferences</Btn></div>;
  }
  function CompositeParameters({
    id
  }) {
    const s = useData(),
      actionState = window.UI.useAction(),
      n = s.graph.nodes.find((n) => n.id === id);
    function handleCanvasstatesjsx4(p, i) {
      return actionState.run(() => api.setPromotedParameter(id, p.key, {
        order: i - 1
      }));
    }
    function handleCanvasstatesjsx5(p, i) {
      return actionState.run(() => api.setPromotedParameter(id, p.key, {
        order: i + 1
      }));
    }
    const ACTIONS = {
      "canvas-states.4": "handleCanvasstatesjsx4",
      "canvas-states.5": "handleCanvasstatesjsx5"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleCanvasstatesjsx4,
        handleCanvasstatesjsx5
      })(id, ...args);
    }
    return <details style={{
      marginTop: 16
    }}><summary>Exposed parameters</summary><window.UI.ActionStatus action={actionState} />{api.getNodeParameters(id).sort((a, b) => (n?.parameterPresentation?.[a.key]?.order ?? 0) - (n?.parameterPresentation?.[b.key]?.order ?? 0)).map((p, i) => <div className="row spread" key={p.key}><small>{p.label}</small><div className="flex"><D.Toggle label={'Expose ' + p.label} checked={!n?.parameterPresentation?.[p.key]?.hidden} onCheckedChange={(v) => actionState.run(() => api.setPromotedParameter(id, p.key, {
            hidden: !v
          }))} /><button className="icon-button" title={'Move ' + p.label + ' up'} aria-label={'Move ' + p.label + ' up'} onClick={(event) => dispatch("canvas-states.4", p, i, event)}><Icon name="back" size={13} /></button><button className="icon-button" title={'Move ' + p.label + ' down'} aria-label={'Move ' + p.label + ' down'} onClick={(event) => dispatch("canvas-states.5", p, i, event)}><Icon name="arrow" size={13} /></button></div></div>)}</details>;
  }
  Object.assign(window.UI, {
    GraphProperties,
    CompositeParameters
  });
})();
