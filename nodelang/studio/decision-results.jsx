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
  } = window.UI;
  function DecisionResult({
    id
  }) {
    useData();
    const u = useApp(),
      actionState = window.UI.useAction(),
      [tab, setTab] = React.useState('Ranges'),
      d = api.getDecisionState(id);
    if (!d) return <p role="status">No decision evidence for this result. Select a decision node and run it.</p>;
    if (!['options','intervals','why'].every(key => Array.isArray(d[key]))) return <p role="alert">The decision owner returned incomplete evidence. Re-run the decision node from Canvas.</p>;
    const costs = d.options.map((option) => Number(option.cost)),
      minCost = Math.min(...costs),
      maxCost = Math.max(...costs),
      plotCost = (cost) => 80 + (Number(cost) - minCost) / (maxCost - minCost || 1) * 300;
    function handleDecisionresultsjsx1(t) {
      return setTab(t);
    }
    function handleDecisionresultsjsx2() {
      return u.go('routing');
    }
    function selectDecision(option) { return actionState.run(() => api.setDecisionState(id, {selected:option})); }
    const ACTIONS = {
      "decision-results.select": "selectDecision",
      "decision-results.1": "handleDecisionresultsjsx1",
      "decision-results.2": "handleDecisionresultsjsx2"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        selectDecision,
        handleDecisionresultsjsx1,
        handleDecisionresultsjsx2
      })(id, ...args);
    }
    return <Card style={{
      padding: 18,
      marginTop: 16
    }}><window.UI.ActionStatus action={actionState} /><div className="spread"><h3>Decision evidence</h3><Chip c={d.coverage < 100 ? A.warn : A.ok}>{d.coverage < 100 ? 'Incomplete evidence' : 'Inputs supplied'}</Chip></div><div className="flex" style={{
        margin: '16px 0'
      }}>{['Ranges', 'Options', 'Why', 'Resources'].map((t) => <button key={t} className="tab-button" aria-pressed={tab === t} onClick={(event) => dispatch("decision-results.1", t, event)}>{t}</button>)}</div>{tab === 'Ranges' ? <div className="grid">{d.intervals.map((r, i) => <div key={r.name}><h3>{r.name}</h3><div className="decision-interval">{['low', 'likely', 'high'].map((key) => <label className="grid" key={key}><small className="muted">{key}</small><input aria-label={r.name + ' ' + key} type="number" value={r[key]} onChange={(e) => actionState.run(() => api.setDecisionState(id, {
                interval: i,
                key,
                value: Number(e.target.value)
              }))} /></label>)}</div><label className="spread"><span>Hesitation</span><input aria-label={r.name + ' hesitation'} type="range" min="0" max="1" step=".05" value={r.hesitation} onChange={(e) => actionState.run(() => api.setDecisionState(id, {
              interval: i,
              key: 'hesitation',
              value: Number(e.target.value)
            }))} /></label></div>)}<p className="decision-warning">{d.unstable ? 'Ranking may change within these ranges.' : 'Ranking is stable within the supplied range.'}</p></div> : tab === 'Options' ? <div className="grid"><svg viewBox="0 0 440 190" aria-label="Pareto options" style={{
          width: '100%',
          background: '#121217',
          borderRadius: 8
        }}><path d="M40 15V155H420" stroke="#62606a" fill="none" /><text x="180" y="181" fill="#9b938a" fontSize="10">Cost →</text>{d.options.map((r) => <g key={r.name} role="button" tabIndex={0} aria-label={'Choose ' + r.name} onClick={() => dispatch("decision-results.select", r.name)} onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); dispatch('decision-results.select', r.name); }
          }}><circle cx={plotCost(r.cost)} cy={140 - r.performance} r={d.selected === r.name ? 10 : 7} fill={d.selected === r.name ? A.accent : A.blue} /><text x={plotCost(r.cost) - 15} y={123 - r.performance} fill="#c7c0b8" fontSize="10">{r.name}</text></g>)}</svg><Table rows={d.options} columns={['name', 'cost', 'performance', 'coverage']} /><label className="spread">Evidence coverage<input aria-label="Decision evidence coverage" type="number" min="0" max="100" value={d.coverage} onChange={(e) => actionState.run(() => api.setDecisionState(id, {
            coverage: Number(e.target.value)
          }))} /><span>%</span></label>{d.coverage < 100 && <p className="decision-warning">The frontier is provisional. Missing evidence may change the ranking.</p>}<Chip>{d.selected}</Chip></div> : tab === 'Why' ? <div className="grid"><p className="muted">Baseline → observed difference. Contributions remain tied to the changed input.</p><Table rows={d.why} columns={['input', 'baseline', 'current', 'delta', 'contribution']} /><div className="spread"><span>Coverage lower bound</span><b>{d.lowerBound}%</b></div><label className="spread">Achieved coverage<input aria-label="Achieved allocation coverage" type="number" min="0" max="100" value={d.achieved} onChange={(e) => actionState.run(() => api.setDecisionState(id, {
            achieved: Number(e.target.value)
          }))} /></label><Chip c={d.gap ? A.warn : A.ok}>{d.gap}% allocation gap</Chip></div> : <div className="grid"><h3>Before the run</h3>{d.preview ? <Table rows={[d.preview]} columns={['tokens', 'cost', 'latency', 'egress']} /> : <p className="muted">No run estimate yet.</p>}<p className="muted">Paid use stays within your cap. Writes and outgoing data still reach the shared Approve card.</p><Btn sm onClick={(event) => dispatch("decision-results.2", event)}>Routing &amp; limits</Btn></div>}</Card>;
  }
  function RefineComparison() {
    const s = useData(),
      actionState = window.UI.useAction(),
      r = s.refine;
    function handleDecisionresultsjsx3() {
      return actionState.run(api.compareRefine);
    }
    function handleDecisionresultsjsx4(row) {
      return actionState.run(() => api.setRefine({
        accepted: row.method
      }));
    }
    const ACTIONS = {
      "decision-results.3": "handleDecisionresultsjsx3",
      "decision-results.4": "handleDecisionresultsjsx4"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleDecisionresultsjsx3,
        handleDecisionresultsjsx4
      })(id, ...args);
    }
    return <Card style={{
      padding: 22,
      marginTop: 22
    }}><window.UI.ActionStatus action={actionState} /><Heading title="Refine" sub="Optional. Compare equal-token trials before choosing a result." /><div className="settings-grid">{[['breadth', 'Independent rollouts N'], ['depth', 'Critique rounds D'], ['trials', 'Comparison trials'], ['tokens', 'Tokens per trial']].map(([key, label]) => <label className="grid" key={key}>{label}<input aria-label={label} type="number" min={key === 'trials' ? 3 : 1} value={r[key]} onChange={(e) => actionState.run(() => api.setRefine({
            [key]: Number(e.target.value)
          }))} /></label>)}</div><div className="spread row"><span>Default mode stays off</span><Btn p onClick={(event) => dispatch("decision-results.3", event)}>Compare candidates</Btn></div>{r.results.length > 0 && <><Table rows={r.results} columns={['method', 'trials', 'passed', 'tokens', 'cost']} /><div className="flex" style={{
          marginTop: 16
        }}>{r.results.map((row) => <Btn sm key={row.method} onClick={(event) => dispatch("decision-results.4", row, event)}>Use {row.method}</Btn>)}</div>{r.accepted && <Chip c={A.ok}>Selected · {r.accepted}</Chip>}</>}</Card>;
  }
  Object.assign(window.UI, {
    DecisionResult,
    RefineComparison
  });
})();
