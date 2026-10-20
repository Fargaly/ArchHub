// Cross-program concept learning, from the existing Book/X-RAY requirements.
(() => {
  const {
      A,
      api,
      useData,
      useApp,
      Btn,
      Card,
      Chip,
      Heading,
      Table
    } = window.UI,
    Icon = window.AHIcon;
  function Xray() {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction(),
      l = s.learning;
    function handleXrayjsx1() {
      return u.go('settings/Brain');
    }
    function handleXrayjsx2() {
      return actionState.run(api.runLearning);
    }
    async function handleXrayjsx3() {
      const r = await actionState.run(() => api.distilLearning(l.destination));
      if (r) u.go(l.destination === 'Node' ? 'canvas' : l.destination === 'Memory' ? 'brain' : l.destination === 'Hook' ? 'settings/Hooks' : 'workshop');
    }
    const ACTIONS = {
      "xray.1": "handleXrayjsx1",
      "xray.2": "handleXrayjsx2",
      "xray.3": "handleXrayjsx3"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleXrayjsx1,
        handleXrayjsx2,
        handleXrayjsx3
      })(id, ...args);
    }
    return <main className="page learning-page" data-screen="xray"><window.UI.ActionStatus action={actionState} /><Heading title="X-RAY" sub="Understand the concept. Keep the best of each program."><Btn sm onClick={(event) => dispatch("xray.1", event)}>Settings</Btn><Btn p onClick={(event) => dispatch("xray.2", event)}>Compare</Btn></Heading><div className="learning-grid"><Card className="learning-brief"><div className="flex"><Icon name="eye" /><h2>What are we learning?</h2></div><label className="grid">Concept<input aria-label="Learning concept" value={l.concept} onChange={(e) => actionState.run(() => api.setLearning({
              concept: e.target.value
            }))} /></label><div className="two-columns">{[0, 1].map((i) => <label className="grid" key={i}>{i === 0 ? 'From program' : 'Compare with'}<select aria-label={i === 0 ? 'Learning source' : 'Learning comparison'} value={l.hosts[i]} onChange={(e) => actionState.run(() => api.setLearning({
                hosts: l.hosts.map((h, n) => n === i ? e.target.value : h)
              }))}>{['Revit', 'AutoCAD', 'Rhino', 'Blender', 'IFC'].map((h) => <option key={h}>{h}</option>)}</select></label>)}</div><div className="concept-flow"><div><Icon name="canvas" /><b>{l.hosts[0]}</b></div><Icon name="arrow" /><div className="concept-core"><Icon name="brain" /><b>{l.concept}</b><small>Shared concept</small></div><Icon name="arrow" /><div><Icon name="canvas" /><b>{l.hosts[1]}</b></div></div><div className="spread"><Chip c={l.status === 'Compared' ? A.ok : A.inkSoft}>{l.status}</Chip><span className="muted" style={{
              fontSize: 11
            }}>Official and open sources only</span></div></Card><aside className="grid" style={{
          alignContent: 'start'
        }}><Card style={{
            padding: 22
          }}><h2>Sources</h2>{l.sources.map((source) => <div className="source-row" key={source.name}><span className="source-icon"><Icon name="docs" size={16} /></span><span className="fill"><b>{source.name}</b><small className="muted" style={{
                  display: 'block',
                  marginTop: 5
                }}>{source.kind}</small></span><Icon name="check" size={14} /></div>)}</Card><Card style={{
            padding: 22
          }}><div className="flex"><Icon name="shield" /><h3>Learn cleanly</h3></div><p className="muted" style={{
              marginTop: 12,
              fontSize: 12
            }}>Understand the behaviour through official APIs, open standards and licensed sources. The data stays in its program until the node needs it.</p></Card></aside></div><div className="learning-notes">{[['baseline', 'The shared behaviour', 'What the programs have in common.'], ['residual', 'The useful differences', 'Keep what each program does best.'], ['why', 'Why it belongs', 'Fit the result to the way you work.']].map(([key, title, sub]) => <Card key={key} style={{
          padding: 20
        }}><span className="eyebrow">{key === 'baseline' ? 'Common core' : key === 'residual' ? 'Differences' : 'Intent'}</span><h2 style={{
            margin: '12px 0 6px'
          }}>{title}</h2><p className="muted" style={{
            fontSize: 11,
            marginBottom: 14
          }}>{sub}</p><textarea aria-label={'Learning ' + key} rows={4} value={l[key]} onChange={(e) => actionState.run(() => api.setLearning({
            [key]: e.target.value
          }))} /></Card>)}</div>{l.findings.length > 0 && <Card style={{
        padding: 22,
        marginTop: 20
      }}><Heading title="What we found" sub="The concept and deviations remain traceable to their sources." /><Table rows={l.findings} columns={['concept', 'shared', 'deviation', 'source']} /><div className="spread" style={{
          marginTop: 20
        }}><div className="flex"><span className="muted">Distil into</span><select aria-label="Learning destination" value={l.destination} onChange={(e) => actionState.run(() => api.setLearning({
              destination: e.target.value
            }))}>{['Node', 'Hook', 'Task', 'Memory'].map((t) => <option key={t}>{t}</option>)}</select></div><Btn p onClick={(event) => dispatch("xray.3", event)}>Use the finding</Btn></div></Card>}<window.UI.XrayLayers /><window.UI.Research /></main>;
  }
  window.UI.Xray = Xray;
})();
