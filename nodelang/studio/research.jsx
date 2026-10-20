// Research → Distill is one decision, bound to Brain, Workshop and Docs.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {
      A,
      api,
      useData,
      useApp,
      Btn,
      Card,
      Chip
    } = window.UI,
    Icon = window.AHIcon;
  function Research() {
    const s = useData(),
      u = useApp(),
      r = s.learning.research;
    const [source, setSource] = React.useState(''),
      [decision, setDecision] = React.useState(r?.decision || 'Learn only'),
      [why, setWhy] = React.useState('Keep the useful pattern and fit it to our existing nodes.'),
      [license, setLicense] = React.useState('Unknown');
    return <section className="research-section"><div className="spread" style={{
        margin: '26px 0 16px'
      }}><div><h2>Research → Distill</h2><p className="muted" style={{
            fontSize: 12,
            marginTop: 5
          }}>One source, one decision, applied where it belongs.</p></div><Icon name="docs" /></div><Card style={{
        padding: 22
      }}><div className="flex"><input aria-label="Research source" placeholder="Link, source account, repository or file" className="fill" value={source} onChange={e => setSource(e.target.value)} /><Btn sm title="Choose a research file" aria-label="Choose a research file" onClick={event => executeAction("projects.research.ChooseAResearchFile.1", {u}, event)}><Icon name="folder" size={16} /></Btn><Btn p disabled={!source.trim()} onClick={event => executeAction("projects.research.ReadSource.2", {api,source,u}, event)}>Read source</Btn></div>{s.files.length > 0 && <label className="flex muted" style={{
          fontSize: 11,
          marginTop: 14
        }}>Or choose a project file<select aria-label="Research file" value="" onChange={e => {
            setSource(e.target.value);
          }}><option value="">Choose file…</option>{s.files.map(f => <option key={f.id} value={f.path}>{f.name}</option>)}</select></label>}</Card>{r && <><div className="research-evidence"><Card style={{
            padding: 22
          }}><div className="spread"><h3>Source and origin</h3><Chip>{r.status}</Chip></div><p className="mono" style={{
              fontSize: 11,
              margin: '16px 0',
              overflowWrap: 'anywhere'
            }}>{r.source}</p><p className="muted" style={{
              fontSize: 12
            }}>Origin: {r.origin}</p><p style={{
              fontSize: 13,
              marginTop: 16
            }}>{r.finding}</p><div className="spread" style={{
              marginTop: 18
            }}><span className="muted" style={{
                fontSize: 11
              }}>LICENSE · {r.licenseStatus}</span><Btn sm title="Check source license" aria-label="Check source license" onClick={event => executeAction("projects.research.CheckSourceLicense.3", {api,u}, event)}><Icon name="shield" size={16} /></Btn></div></Card><Card className="decision-card"><span className="eyebrow">One decision</span><h2>What belongs in ArchHub?</h2><div className="decision-options">{['Adopt', 'Learn only', 'Skip'].map(v => <button key={v} aria-pressed={decision === v} onClick={event => executeAction("projects.research.SetDecisionV.4", {setDecision,v}, event)}>{v}</button>)}</div><label className="grid">License<select aria-label="Research license" value={license} onChange={e => setLicense(e.target.value)}>{['Unknown', 'MIT', 'Apache-2.0', 'GPL / AGPL', 'Proprietary'].map(l => <option key={l}>{l}</option>)}</select></label><label className="grid">Why<textarea aria-label="Research decision reason" rows={3} value={why} onChange={e => setWhy(e.target.value)} /></label>{decision === 'Adopt' && !['MIT', 'Apache-2.0'].includes(license) && <p className="muted" style={{
              fontSize: 11
            }}>Choose Learn only until the license permits adoption.</p>}<Btn p disabled={!!r.decision && (r.decision !== 'Adopt' || !!r.work) || !why.trim() || decision === 'Adopt' && !['MIT', 'Apache-2.0'].includes(license)} onClick={event => executeAction("projects.research.UActApiSaveResearchDecisionDecision.5", {api,decision,license,u,why}, event)}>{r.decision === 'Adopt' && !r.work ? 'Retry application work' : r.decision ? 'Decision saved' : 'Save and apply decision'}</Btn></Card></div>{r.decision && <Card style={{
          padding: 22,
          marginTop: 16
        }}><div className="spread"><h2>{r.decision} · {s.learning.concept}</h2><Chip c={A.ok}>{r.status}</Chip></div><p className="muted" style={{
            margin: '14px 0'
          }}>{r.why}</p><div className="research-destinations">{[['brain', 'Brain', r.destinations?.brain || 'Open'], ['workshop', 'Workshop', r.destinations?.workshop || 'Open'], ['docs', 'Docs', r.destinations?.docs || 'Open']].map(([route, name, status]) => <button key={route} onClick={event => executeAction("projects.research.UGoRoute.6", {route,u}, event)}><Icon name={route} size={18} /><span><b>{name}</b><small>{status}</small></span><Icon name="arrow" size={16} /></button>)}</div></Card>}</>}</section>;
  }
  window.UI.Research = Research;

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsresearchjsxChooseAResearchFile1({u}, event) {
  const handler = u.pickFile;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsresearchjsxReadSource2({api,source,u}, event) {
  const handler = () => u.act(() => api.readResearchSource(source));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsresearchjsxCheckSourceLicense3({api,u}, event) {
  const handler = () => u.act(api.checkResearchLicense);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsresearchjsxSetDecisionV4({setDecision,v}, event) {
  const handler = () => setDecision(v);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsresearchjsxUActApiSaveResearchDecisionDecision5({api,decision,license,u,why}, event) {
  const handler = () => u.act(() => api.saveResearchDecision({
              decision,
              why,
              license
            }));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsresearchjsxUGoRoute6({route,u}, event) {
  const handler = () => u.go(route);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
const PROJECT_ACTIONS = {
  "projects.research.ChooseAResearchFile.1": "projectsresearchjsxChooseAResearchFile1",
  "projects.research.ReadSource.2": "projectsresearchjsxReadSource2",
  "projects.research.CheckSourceLicense.3": "projectsresearchjsxCheckSourceLicense3",
  "projects.research.SetDecisionV.4": "projectsresearchjsxSetDecisionV4",
  "projects.research.UActApiSaveResearchDecisionDecision.5": "projectsresearchjsxUActApiSaveResearchDecisionDecision5",
  "projects.research.UGoRoute.6": "projectsresearchjsxUGoRoute6"
};
window.registerActions(PROJECT_ACTIONS, {projectsresearchjsxChooseAResearchFile1,projectsresearchjsxReadSource2,projectsresearchjsxCheckSourceLicense3,projectsresearchjsxSetDecisionV4,projectsresearchjsxUActApiSaveResearchDecisionDecision5,projectsresearchjsxUGoRoute6});
})();
