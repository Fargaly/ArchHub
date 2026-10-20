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
    } = window.UI,
    Icon = window.AHIcon;
  function AgentChannel({
    id
  }) {
    const [report, setReport] = React.useState(null),
      [preview, setPreview] = React.useState(null),
      [sessions, setSessions] = React.useState(null),
      [busy, setBusy] = React.useState(false),
      [request, setRequest] = React.useState({
        status: "empty",
        error: ""
      }),
      retry = React.useRef(null);
    const supported = ['claude', 'claude-code', 'codex', 'opencode', 'gemini', 'gemini-cli'].includes(id);
    async function run(operation, accept = setReport) {
      retry.current = () => run(operation, accept);
      setBusy(true);
      setRequest({
        status: 'waiting',
        error: ''
      });
      return Promise.resolve().then(operation).then(value => {
        if (!value || value.ok === false) throw Error(value?.message || value?.error || 'The owner returned no result. Check the client and retry.');
        accept(value);
        setRequest({status:value.sessions?.length === 0 ? 'empty':'loaded',error:''});
        return value;
      }).catch(error => {
        setRequest({status:'error',error:error.message});return null;
      }).finally(() => setBusy(false));
    }

    React.useEffect(() => {
      setReport(null);
      setPreview(null);
      setSessions(null);
      setRequest({
        status: 'empty',
        error: ''
      });
    }, [id]);
    if (!supported) return null;
    return <Card style={{
      padding: 18
    }}><div className="spread"><h3>Agent channel</h3>

      <Btn sm disabled={busy} onClick={() => executeAction("getAgentChannel", {
          act: operation => run(operation)
        }, id)}>Check channel</Btn></div>

      {request.status === 'waiting' && <p role="status">Reading the agent owner…</p>}

      {request.status === 'error' && <div role="alert">{request.error}<Btn sm onClick={() => executeAction("ui.retry", retry.current)}>Retry channel action</Btn></div>}

      {request.status === 'empty' && <p>No agent result selected. Check the channel or read native sessions.</p>}

      {request.status === 'loaded' && <p role="status">Agent owner response received.</p>}

      {report && <><p>{report.state}</p><p className="muted">{report.activationPending ? 'Settings saved. The agent still needs to load them; a live reply verifies the connection.' : 'Configuration and a live agent connection are checked separately.'}</p>

        <Chip>{report.hooks?.state}</Chip></>}

      <div className="flex" style={{
        marginTop: 14
      }}>

        <Btn sm disabled={busy} onClick={async () => {
          await executeAction('listAgentSessions',{act:operation=>run(operation,setSessions)});
        }}>Read native sessions</Btn>

        {!['gemini', 'gemini-cli'].includes(id) && <Btn sm disabled={busy} onClick={() => executeAction("installAgentChannel", {
          act: operation => run(operation)
        }, id)}>Connect channel</Btn>}

        {id !== 'opencode' && <Btn sm disabled={busy} onClick={async () => {
          await executeAction("previewAgentChannel", {
            act: operation => run(operation, setPreview)
          }, id);
        }}>Review channel repair</Btn>}

      </div>{preview && <div className="grid" style={{
        marginTop: 14
      }}><p>{preview.description}</p>

        <Btn sm disabled={busy} onClick={() => executeAction("repairAgentChannel", {
          act: operation => run(operation)
        }, id, preview.plan_digest)}>Apply reviewed repair</Btn></div>}

      {sessions && <div style={{
        marginTop: 14
      }}><h3>Native sessions</h3>

        <p className="muted">{sessions.adapters?.[id === 'claude-code' ? 'claude' : id] || 'No adapter status reported'}</p>

        <ul aria-label="Native sessions">{sessions.sessions.filter(row => row.app === (id === 'claude-code' ? 'claude' : id)).map(row => <li key={row.id}>{row.title || 'Untitled session'}</li>)}</ul>

        {sessions.truncated && <p className="muted">Session discovery was truncated.</p>}

        <p className="muted">A discovered session is an address; a reply verifies delivery.</p></div>}

    </Card>;
  }
  function AgentProfile({
    id
  }) {
    const s = useData(),
      u = useApp(),
      p = s.providers.find(r => r.id === id);
    return p ? <div className="grid"><AgentChannel id={id} /><Card style={{
        padding: 18
      }}><h3>Profile</h3><div className="grid" style={{
          marginTop: 15
        }}><label className="grid">Purpose<input aria-label="Agent purpose" value={p.purpose || 'Complete and verify the selected task'} onChange={e => executeAction("setAgentProfile", u, id, {
              purpose: e.target.value
            })} /></label><label className="grid">Owner<select aria-label="Agent owner" value={p.humanOwner || s.profile.name || 'Unassigned'} onChange={e => executeAction("setAgentProfile", u, id, {
              humanOwner: e.target.value
            })}>{s.people.map(r => <option key={r.id}>{r.name}</option>)}</select></label><label className="grid">Administrators<input aria-label="Agent administrators" value={p.admins || s.profile.name || 'Unassigned'} onChange={e => executeAction("setAgentProfile", u, id, {
              admins: e.target.value
            })} /></label><div className="settings-grid">{['Read', 'Write', 'Send', 'Spend'].map(action => <label key={action} className="grid">{action}<select aria-label={action + ' autonomy'} value={p.autonomy?.[action] || 'Review all'} onChange={e => executeAction("setAgentProfile", u, id, {
                autonomy: {
                  ...p.autonomy,
                  [action]: e.target.value
                }
              })}>{['Review all', 'Escalate hard', 'Autonomous'].map(x => <option key={x}>{x}</option>)}</select></label>)}</div><label className="grid">Questions per day<input aria-label="Agent questions per day" type="number" min="0" value={p.questionsPerDay ?? 1} onChange={e => executeAction("setAgentProfile", u, id, {
              questionsPerDay: Math.max(0, Number(e.target.value))
            })} /></label><label className="grid">Memory scope<select aria-label="Agent memory scope" value={p.memoryScope || 'Project'} onChange={e => executeAction("setAgentProfile", u, id, {
              memoryScope: e.target.value
            })}>{['Project', 'User', 'Office'].map(x => <option key={x}>{x}</option>)}</select></label><div><h3>Skills &amp; tools</h3>{s.hostSkills.map(skill => <div className="row spread" key={skill.id}><span>{skill.name} · {skill.host}</span><D.Toggle label={p.name + ' uses ' + skill.name} checked={p.skillIds?.includes(skill.id) ?? true} onCheckedChange={v => executeAction("setAgentProfile", u, id, {
                skillIds: v ? [...new Set([...(p.skillIds || s.hostSkills.map(s => s.id)), skill.id])] : (p.skillIds || s.hostSkills.map(s => s.id)).filter(s => s !== skill.id)
              })} /></div>)}</div></div></Card></div> : null;
  }
  function TaskDetails({
    id
  }) {
    const s = useData(),
      u = useApp(),
      t = s.tasks.find(t => t.id === id),
      [text, setText] = React.useState('');
    return t ? <div className="grid"><div className="spread"><div><h2>{t.title}</h2><p className="muted">Owner: {t.humanOwner || s.profile.name || 'Unassigned'}</p></div><Chip>{t.status}</Chip></div><label className="flex">Delegate<select aria-label="Task delegate" value={t.owner} onChange={e => executeAction("setTaskDelegate", u, id, e.target.value)}>{s.providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><h3>Steps</h3>{(t.steps || []).map((step, i) => <div className="row spread" key={step.id}><span>{i + 1}. {step.title}</span><Chip c={step.status === 'Done' ? A.ok : A.warn}>{step.status}</Chip></div>)}<div className="spread"><h3>Checkpoints</h3><Btn sm onClick={() => executeAction("checkpointTask", u, id)}>Save checkpoint</Btn></div>{t.checkpoints?.map(c => <div className="row spread" key={c.id}><span>{c.title}</span><Btn sm onClick={() => executeAction("restoreTaskCheckpoint", u, id, c.id)}>Restore</Btn></div>)}<p className="muted">Restore returns the task steps; the conversation stays here.</p><window.UI.ReviewDetails taskId={id} /><window.UI.Steer id={id} /><h3>Queued messages</h3><div className="flex"><input aria-label="Queue message" className="fill" value={text} onChange={e => setText(e.target.value)} placeholder="Add a note for the next step" /><Btn p disabled={!text.trim()} onClick={async () => {
          const saved = await executeAction("queueTaskMessage", u, id, text);
          if (saved) executeAction("ui.state", setText, '');
        }}>Queue</Btn></div>{t.queuedMessages?.map(m => <div className="row spread" key={m.id}><p className="muted">{m.text}</p><div className="flex"><Btn sm onClick={() => executeAction("settleQueuedMessage", u, id, m.id, true)}>Send</Btn><Btn sm onClick={() => executeAction("settleQueuedMessage", u, id, m.id, false)}>Withdraw</Btn></div></div>)}</div> : null;
  }
  function NodeOutput({
    id
  }) {
    const s = useData(),
      u = useApp(),
      [tab, setTab] = React.useState('Table'),
      [data, setData] = React.useState(null),
      [json, setJson] = React.useState(''),
      [request, setRequest] = React.useState({
        status: 'waiting',
        error: ''
      }),
      [attempt, setAttempt] = React.useState(0),
      n = s.graph.nodes.find(n => n.id === id);
    React.useEffect(() => {
      let active = true;
      setRequest({
        status: 'waiting',
        error: ''
      });
      Promise.resolve().then(() => api.getNodeOutput(id, tab)).then(result => {
        if (!active) return;
        if (result?.ok === false) throw Error(result.message || result.error);
        setData(result);
        setJson(result.json);
        setRequest({
          status: result.rows.length ? 'loaded' : 'empty',
          error: ''
        });
      }).catch(error => {
        if (active) setRequest({
          status: 'error',
          error: error.message
        });
      });
      return () => {
        active = false;
      };
    }, [id, tab, s.revision, attempt]);
    return <div className="grid"><div className="spread"><h2>{n?.title}</h2><Chip>{n?.pinned ? 'Pinned output' : n?.status}</Chip></div><div className="flex">{['Schema', 'Table', 'JSON'].map(t => <Btn key={t} sm aria-pressed={tab === t} onClick={() => executeAction("ui.state", setTab, t)}>{t}</Btn>)}</div>{request.status === 'waiting' && <p role="status">Reading node output…</p>}{request.status === 'error' && <div role="alert">{request.error}<Btn sm onClick={() => executeAction("ui.state", setAttempt, n => n + 1)}>Retry output</Btn></div>}{request.status === 'empty' && <p>No output yet. Replay this node.</p>}{request.status === 'loaded' && <p role="status">Output loaded.</p>}{data && (tab === 'JSON' ? <div className="grid"><textarea aria-label="Output JSON" className="output-json" rows={12} value={json} onChange={e => setJson(e.target.value)} /><Btn p onClick={() => executeAction("setPinnedOutput", u, id, json)}>Pin edited output</Btn></div> : <Table rows={tab === 'Schema' ? data.schema : data.rows} />)}<window.UI.ResearchReview id={id} /><window.UI.DecisionResult id={id} /><div className="flex"><Btn sm onClick={() => executeAction("runNode", u, id)}>Replay</Btn><Btn sm onClick={() => executeAction("setNodeFlags", u, id, {
          pinned: !n?.pinned
        })}>{n?.pinned ? 'Unpin output' : 'Pin output'}</Btn><Btn sm onClick={() => executeAction("ui.download", u, 'Results', id)}>Export</Btn></div></div>;
  }
  function HostSkills() {
    const s = useData(),
      u = useApp();
    return <Card style={{
      padding: 20
    }}><div className="spread"><h2>Program skills</h2><Btn sm title="Import skill" aria-label="Import skill" onClick={() => executeAction("ui.show", u, 'Import skill')}><Icon name="plus" size={16} /></Btn></div>{s.hostSkills.map(skill => <div className="row" key={skill.id}><div className="spread"><div><h3>{skill.name}</h3><p className="muted">{skill.host} · {skill.format}</p></div><div className="flex"><D.Toggle label={'Enable skill ' + skill.name} checked={skill.enabled} onCheckedChange={v => executeAction("setHostSkillEnabled", u, skill.id, v)} /><Btn sm title={'Open skill ' + skill.name} aria-label={'Open skill ' + skill.name} onClick={() => executeAction("ui.show", u, 'Host skill', {
              id: skill.id
            })}><Icon name="arrow" size={16} /></Btn></div></div><p className="muted" style={{
          fontSize: 11,
          marginTop: 10
        }}>{skill.audit}</p></div>)}</Card>;
  }
  function HostSkill({
    id
  }) {
    const s = useData(),
      u = useApp(),
      skill = s.hostSkills.find(r => r.id === id);
    return skill ? <div className="grid"><h2>{skill.name}</h2><p>{skill.description}</p><div className="row spread"><span>Program</span><b>{skill.host}</b></div><div className="row spread"><span>Network access</span><Chip c={skill.network ? A.warn : A.ok}>{skill.network ? 'Requested' : 'None'}</Chip></div><h3>Included scripts</h3>{skill.scripts.length ? skill.scripts.map(script => <p className="mono" key={script}>{script}</p>) : <p className="muted">No scripts</p>}<Chip>{skill.audit}</Chip><div className="flex"><Btn p onClick={() => executeAction("auditHostSkill", u, id)}>Review access</Btn><Btn sm onClick={async () => {
          const node = await executeAction("addNode", u, skill.name);
          if (node) executeAction("ui.go", u, 'canvas');
        }}>Open as node</Btn></div></div> : null;
  }
  function ConnectorTools({
    connection: c
  }) {
    const s = useData(),
      u = useApp();
    return c ? <div className="grid" style={{
      marginTop: 20
    }}><div className="spread"><span>Used by {s.graphs.reduce((count, g) => count + g.nodes.filter(n => n.params.host === c.name || n.params.source === c.name).length, 0)} nodes</span><Chip>{c.connected ? 'Ready' : 'Disconnected'}</Chip></div><p className="muted">Scopes: {['read', 'reply', 'post'].filter(k => c[k]).join(' · ') || 'None'}</p><div className="flex">{['Read', 'Write'].map(action => <Btn key={action} sm onClick={async () => {
          const n = await executeAction("addNode", u, action === 'Read' ? 'Read from host' : 'Write to host');
          if (n) await executeAction("setNodeParam", u, n.id, 'host', c.name);
          executeAction("ui.go", u, 'canvas');
        }}>{action} node</Btn>)}</div><Btn sm onClick={() => executeAction("ui.show", u, 'Connector bundle')}>Install connector bundle</Btn></div> : null;
  }
  function BrainControls() {
    const s = useData(),
      u = useApp();
    return <Card style={{
      padding: 20,
      marginBottom: 22
    }}><div className="settings-grid">{s.settings.filter(r => r.page === 'Brain' && r.group === 'Recall & storage').map(r => <window.UI.SettingControl key={r.id} row={r} />)}</div>{s.provenance.length > 0 && <><h3 style={{
          margin: '16px 0'
        }}>Read and cited sources</h3>{s.provenance.map(r => <div className="row spread" key={r.id}><div><b>{r.source}</b><p className="muted">Read: {r.read ? 'Yes' : 'No'} · Cited: {r.cited ? 'Yes' : 'No'} · {r.trust}</p></div><div className="flex"><Btn sm onClick={() => executeAction("setSourceEvidence", u, r.id, {
              cited: true
            })}>Cite</Btn><Btn sm onClick={() => executeAction("setSourceEvidence", u, r.id, {
              trust: 'Quarantined'
            })}>Quarantine</Btn><Btn sm onClick={() => executeAction("ui.show", u, 'Correct source', {
              id: r.id,
              text: r.source
            })}>Correct</Btn><Btn sm onClick={() => executeAction("setSourceEvidence", u, r.id, {
              excluded: !r.excluded
            })}>{r.excluded ? 'Include' : 'Exclude'}</Btn></div></div>)}</>}</Card>;
  }
  function ConnectorBundle() {
    const s = useData(),
      u = useApp(),
      input = React.useRef(),
      bundle = s.connectorBundle;
    return <div className="grid"><p className="muted">Review the bundle’s declared tools and configuration before enabling it.</p><input ref={input} className="sr-only" type="file" accept=".mcpb,.json" aria-label="Choose connector bundle" onChange={async e => {
        const f = e.target.files?.[0];
        if (f) await executeAction("inspectConnectorBundle", u, f);
        e.target.value = '';
      }} /><Btn p onClick={() => executeAction("ui.chooseBundle", input)}>Choose bundle</Btn>{bundle && <><h2>{bundle.name}</h2><p>{bundle.description}</p><Chip c={bundle.error ? A.warn : A.ok}>{bundle.status}</Chip>{bundle.error && <p>{bundle.error}</p>}<h3>Tools</h3>{bundle.tools.map((t, i) => <p key={i}>{typeof t === 'string' ? t : t.name}</p>)}<h3>Configuration</h3>{bundle.config.map(r => <label className="parameter-row" key={r.key}><span>{r.label}</span>{r.sensitive ? <Chip>Protected by your account</Chip> : r.type === 'boolean' ? <D.Toggle label={r.label} checked={!!r.value} onCheckedChange={v => executeAction("configureConnectorBundle", u, r.key, v)} /> : <input aria-label={r.label} type={r.type === 'number' ? 'number' : 'text'} value={r.value} onChange={e => executeAction("configureConnectorBundle", u, r.key, r.type === 'number' ? Number(e.target.value) : e.target.value)} />}</label>)}<Btn disabled={!!bundle.error || bundle.status === 'Installed'} p onClick={() => executeAction("installConnectorBundle", u)}>{bundle.status === 'Installed' ? 'Installed' : 'Install reviewed bundle'}</Btn></>}</div>;
  }
  Object.assign(window.UI, {
    AgentChannel,
    AgentProfile,
    TaskDetails,
    NodeOutput,
    HostSkills,
    HostSkill,
    ConnectorTools,
    BrainControls,
    ConnectorBundle
  });
})();
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
    api,
    useData,
    useApp,
    Card,
    D
  } = window.UI;
  function MixedProperties({
    ids
  }) {
    const s = useData(),
      u = useApp(),
      nodes = ids.map(id => s.graph.nodes.find(n => n.id === id)),
      first = nodes[0],
      common = api.getNodeParameters(first).filter(p => nodes.every(n => Object.hasOwn(n.params, p.key)));
    return <Card style={{
      padding: 16,
      marginTop: 16
    }}><h3>{nodes.length} selected</h3><p className="muted" style={{
        margin: '12px 0'
      }}>Change a shared value across the selection.</p>{common.map(p => {
        const mixed = nodes.some(n => JSON.stringify(n.params[p.key]) !== JSON.stringify(first.params[p.key])),
          value = mixed ? '' : first.params[p.key];
        return <label className="parameter-row" key={p.key}><span>{p.label}{mixed && <small className="muted"> · Mixed</small>}</span>{p.type === 'boolean' ? <D.Toggle label={'Selected ' + p.label} checked={!!value} onCheckedChange={v => executeAction("setMultipleNodeParameters", u, ids, p.key, v)} /> : <input aria-label={'Selected ' + p.label} placeholder={mixed ? 'Mixed' : ''} type={p.type === 'number' ? 'number' : 'text'} value={value} onChange={e => executeAction("setMultipleNodeParameters", u, ids, p.key, p.type === 'number' ? Number(e.target.value) : e.target.value)} />}</label>;
      })}</Card>;
  }
  window.UI.MixedProperties = MixedProperties;
})();
