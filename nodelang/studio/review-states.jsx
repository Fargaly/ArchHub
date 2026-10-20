// Shared research decisions extend the existing card, property and approval components.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
    A,
    D,
    api,
    useData,
    useApp,
    Btn,
    Card,
    Chip,
    Table
  } = window.UI;
  function GraphMetadata() {
    const s = useData(),
      u = useApp(),
      g = s.graph,
      [name, setName] = React.useState(''),
      [value, setValue] = React.useState('');
    return <div className="grid"><label className="grid">Documentation<input aria-label="Graph documentation" value={g.documentation || ''} onChange={e => executeAction("updateGraph", u, g.id, {
          documentation: e.target.value
        })} /></label><Btn sm onClick={() => executeAction("ui.go", u, 'docs')}>Read documentation</Btn><label className="listbutton">{g.thumbnail && <img alt="Graph thumbnail" src={g.thumbnail} style={{
          width: '100%',
          maxHeight: 90,
          objectFit: 'cover'
        }} />}Choose thumbnail<input aria-label="Graph thumbnail" type="file" accept="image/*" onChange={e => {
          if (e.target.files[0]) executeAction("setGraphThumbnail", u, e.target.files[0]);
        }} /></label><h3>Custom properties</h3>{(g.customProperties || []).map((r, i) => <div className="spread" key={i}><span>{r.name}</span><input aria-label={'Graph property ' + r.name} value={r.value} onChange={e => executeAction("updateGraph", u, g.id, {
          customProperties: g.customProperties.map((x, j) => j === i ? {
            ...x,
            value: e.target.value
          } : x)
        })} /><Btn sm onClick={() => executeAction("updateGraph", u, g.id, {
          customProperties: g.customProperties.filter((_, j) => j !== i)
        })}>Remove</Btn></div>)}<input aria-label="Custom property name" placeholder="Property" value={name} onChange={e => setName(e.target.value)} /><input aria-label="Custom property value" placeholder="Value" value={value} onChange={e => setValue(e.target.value)} /><Btn sm disabled={!name.trim()} onClick={async () => {
        const saved = await executeAction("updateGraph", u, g.id, {
          customProperties: [...(g.customProperties || []), {
            name,
            value
          }]
        });
        if(saved){executeAction('ui.state',setName,'');executeAction('ui.state',setValue,'');}
      }}>Add property</Btn><label className="spread">Court status<select aria-label="Graph court status" value={g.courtStatus || 'Not reviewed'} onChange={e => executeAction("updateGraph", u, g.id, {
          courtStatus: e.target.value
        })}>{['Not reviewed', 'Needs review', 'Pass', 'Fail', 'Inconclusive'].map(x => <option key={x}>{x}</option>)}</select></label><Btn sm onClick={() => executeAction("ui.go", u, 'runs')}>Run history</Btn></div>;
  }
  function IntakeRules() {
    const s = useData(),
      u = useApp();
    return <details className="row"><summary>Document intake · firm dictionary</summary>{s.intakeRules.map(r => <div className="settings-grid" key={r.id}>{['synonym', 'canonical', 'unit', 'shorthand'].map(key => <label className="grid" key={key}>{key}<input aria-label={'Intake ' + key} value={r[key]} onChange={e => executeAction("setIntakeRule", u, r.id, {
            [key]: e.target.value
          })} /></label>)}</div>)}<Btn sm onClick={() => executeAction("setIntakeRule", u, null, {})}>Add dictionary row</Btn></details>;
  }
  function UncertainLinks() {
    const s = useData(),
      u = useApp();
    return <details className="row"><summary>Founder inbox · uncertain links</summary>{s.uncertainLinks.map(r => <Card key={r.id} style={{
        padding: 18,
        marginTop: 12
      }}><div className="spread"><h3>{r.from} → {r.to}</h3><Chip c={A.warn}>{r.status}</Chip></div><p className="muted">{r.relation} · entropy {r.entropy} · {r.source}</p><div className="flex" style={{
          marginTop: 14
        }}><Btn sm onClick={() => executeAction("reviewBrainLink", u, r.id, 'Accepted')}>Accept link</Btn><Btn sm onClick={() => executeAction("reviewBrainLink", u, r.id, 'Rejected')}>Reject link</Btn></div></Card>)}</details>;
  }
  function OnboardingProfile() {
    const s = useData(),
      u = useApp();
    return <div className="grid"><label>Your work<select aria-label="Onboarding role" value={s.onboarding.role} onChange={e => executeAction("setOnboarding", u, {
          role: e.target.value
        })}>{['Architect', 'BIM coordinator', 'Project manager', 'Engineer'].map(x => <option key={x}>{x}</option>)}</select></label><label>How should we start?<select aria-label="Onboarding assessment" value={s.onboarding.assessment} onChange={e => executeAction("setOnboarding", u, {
          assessment: e.target.value
        })}>{['Read first, review writes', 'Explain each step', 'Show the plan as nodes'].map(x => <option key={x}>{x}</option>)}</select></label><small className="muted">{s.onboarding.role} · {s.onboarding.assessment}</small></div>;
  }
  function AnswerSources({
    message
  }) {
    const u = useApp(),
      rows = message.sources || [{
        sourceId: 'Nile Tower · P03',
        excerpt: 'Reviewed project context',
        status: 'Included'
      }];
    return <details style={{
      marginTop: 10
    }}><summary>Sources</summary>{rows.length === 0 && <p className="muted">This message has no attributed sources.</p>}{rows.map((r, i) => <div className="row" key={i} style={{
        opacity: r.status === 'Excluded' ? .45 : 1
      }}><small>{api.contextLabel(r.sourceId)} · {r.status}</small><input aria-label={'Correct source ' + message.id} value={r.excerpt} onChange={e => executeAction("correctAnswerSource", u, message.id, i, {
          excerpt: e.target.value,
          status: 'Corrected'
        })} /><Btn sm onClick={() => executeAction("correctAnswerSource", u, message.id, i, {
          status: r.status === 'Excluded' ? 'Included' : 'Excluded'
        })}>{r.status === 'Excluded' ? 'Restore source' : 'Exclude source'}</Btn></div>)}</details>;
  }
  function TranscriptProvenance({
    turn
  }) {
    const u = useApp();
    return <details><summary className="muted">whisper.cpp + provider pass · {turn.acceptedPass || 'compare'}</summary><p>whisper.cpp: {turn.primary || turn.text}</p><p>Provider pass: {turn.secondary || 'No provider transcript has been received'}</p><div className="flex"><Btn sm onClick={() => executeAction("setTranscriptPass", u, turn.id, 'primary')}>Use whisper.cpp</Btn><Btn sm onClick={() => executeAction("setTranscriptPass", u, turn.id, 'secondary')}>Use provider pass</Btn></div></details>;
  }
  function ApprovalRubric({
    id
  }) {
    const s = useData(),
      u = useApp(),
      c = s.approvals.find(c => c.id === id);
    return <details style={{
      padding: 16
    }}><summary>Review checklist &amp; evidence</summary>{['Target and revision match', 'Changes fit the requested scope', 'Evidence supports the result'].map(label => <label key={label} className="row spread"><span>{label}</span><D.Toggle label={label} checked={!!c?.rubric?.[label]} onCheckedChange={v => executeAction("setApprovalRubric", u, id, label, v)} /></label>)}<small className="muted">The checklist records your review; the Approve card remains your decision.</small></details>;
  }
  function ResearchReview({
    id
  }) {
    const s = useData(),
      u = useApp(),
      n = s.graph.nodes.find(n => n.id === id);
    if (!n) return null;
    const kind = n.kind;
    return <div className="grid">{kind === 'Fuzzy score' && <Card style={{
        padding: 16
      }}><h3>Stakeholder fusion</h3><Table rows={n.fuzzyEvidence || []} columns={['criterion', 'stakeholder', 'rating', 'client', 'fusion', 'fused']} /></Card>}{kind === 'Provenance stamp' && <Card style={{
        padding: 16
      }}><h3>Provenance</h3>{n.provenance ? <Table rows={[n.provenance]} /> : <p className="muted">Create a content hash for this output.</p>}<Btn sm onClick={() => executeAction("verifyOutputStamp", u, id)}>Verify content hash</Btn><small className="muted">Cryptographic signing requires the identity service.</small></Card>}{kind === 'Select target' && <Card style={{
        padding: 16
      }}><Chip c={n.params.matchCount === 1 ? A.ok : A.warn}>{n.status}</Chip><p>Expected {n.params.expected} · found {n.params.matchCount}</p>{(n.output || []).map(r => <Btn key={r.element} sm onClick={() => {
          executeAction("setNodeParam", u, id, 'selector', r.element);
          executeAction("setNodeParam", u, id, 'matchCount', 1);
          executeAction("setResearchReview", u, id, {
            selected: r.element
          });
        }}>Choose {r.element}</Btn>)}<Btn sm onClick={() => {
          executeAction("ui.close", u);
          executeAction("ui.go", u, 'canvas');
        }}>Correct selector</Btn></Card>}{/Recall-settings/.test(kind) && <Card style={{
        padding: 16
      }}><h3>Last successful preset</h3><Table rows={n.successfulPresets || []} /><Btn p onClick={() => executeAction("setResearchReview", u, id, {
          usePreset: true
        })}>Use &amp; prefill</Btn></Card>}{/Procedural test-scene/.test(kind) && <Card style={{
        padding: 16
      }}><h3>Condition matrix</h3><Table rows={Array.isArray(n.output) ? n.output : []} /></Card>}{kind === 'OSM to 3D' && <svg aria-label="OSM site context preview" viewBox="0 0 400 160" style={{
        background: '#141419',
        width: '100%'
      }}>{(Array.isArray(n.output) ? n.output : []).filter(feature => typeof feature.path === 'string').map((feature, i) => <path key={feature.id || i} d={feature.path} fill="#4b494b" stroke="#b5ada0" />)}</svg>}</div>;
  }
  function NodeRunPolicy({
    id
  }) {
    const s = useData(),
      u = useApp(),
      n = s.graph.nodes.find(n => n.id === id);
    return <details style={{
      margin: '12px 0'
    }}><summary>Run policy</summary><label className="grid">On error<select aria-label="On error" value={n?.onError || 'Stop this branch'} onChange={e => executeAction("setNodeRunPolicy", u, id, {
          onError: e.target.value
        })}>{['Stop this branch', 'Continue other branches', 'Retry'].map(x => <option key={x}>{x}</option>)}</select></label><label className="spread">Retries<input aria-label="Node retry count" type="number" min="0" max="10" value={n?.retries || 0} onChange={e => executeAction("setNodeRunPolicy", u, id, {
          retries: Number(e.target.value)
        })} /></label><label className="spread">Preview off<D.Toggle label="Node preview off" checked={!!n?.previewOff} onCheckedChange={v => executeAction("setNodeRunPolicy", u, id, {
          previewOff: v
        })} /></label><Btn sm onClick={() => executeAction("setNodeRunPolicy", u, id, {
        hostHighlighted: true
      })}>Highlight target in program</Btn>{n?.hostHighlighted && <small className="muted">{n.params.selector || n.params.element || n.title} · selection preview</small>}</details>;
  }
  Object.assign(window.UI, {
    NodeRunPolicy,
    GraphMetadata,
    IntakeRules,
    UncertainLinks,
    OnboardingProfile,
    AnswerSources,
    TranscriptProvenance,
    ApprovalRubric,
    ResearchReview
  });
})();
