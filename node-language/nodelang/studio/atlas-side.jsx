// atlas-side.jsx — the RIGHT sidebar: the cockpit's agentic surface.
// Three lenses, all node-driven: ACTIVITY (agent notifications + the Attention
// node's ranked feed), SESSIONS (live conversations with the founder's agents),
// HISTORY (the run-tree of the whole grand map). Everything here is produced by
// nodes on the map — nothing is hardcoded importance.

const { HB } = window;

// Matches the left rail's chrome spec (see ltab / secStyle / PanelLabel) so the two
// panels framing the map align row-for-row.
const tabBtn = (on) => ({ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: '10px 0', border: 'none', borderBottom: `2px solid ${on ? HB.accent : 'transparent'}`, background: 'transparent', cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, letterSpacing: '0.06em', color: on ? HB.ink : HB.inkMute });
const sideSec = { padding: '15px 16px', borderBottom: `1px solid ${HB.lineSoft}` };
const sideLabel = { fontFamily: HB.mono, fontSize: 8.5, color: HB.inkMute, letterSpacing: '0.16em', marginBottom: 9 };

function ago(t) { const s = Math.floor((Date.now() - t) / 1000); if (s < 60) return s + 's'; const m = Math.floor(s / 60); if (m < 60) return m + 'm'; const h = Math.floor(m / 60); if (h < 24) return h + 'h'; return Math.floor(h / 24) + 'd'; }

// The Sessions lens used to render four hand-written conversations between the founder and
// invented agents, complete with plausible replies. Nothing in them had ever happened. The
// real record of the founder talking to his app is the agent-task queue: each row is an
// instruction the cockpit sent and the answer the app posted back. That is what renders now.
const TASK_TONE = { done: 'ok', failed: 'err', running: 'accent', claimed: 'accent', queued: 'mute' };

function taskStamp(row) {
  const s = row.finished_at || row.claimed_at || row.created_at;
  return s ? s * 1000 : null;
}

function AgenticPanel({ M, DB, assign, attention, onGoto, onTuneAttention, attNode, setColl, flash, control, tasks, onRelay, onReloadTasks }) {
  const [tab, setTab] = React.useState('activity');
  const rows = tasks || [];
  const ctl = control || null;

  // recent runs across the whole map → the notification stream
  const recent = [];
  M.nodes.forEach(n => ((n.rt && n.rt.runs) || []).forEach(r => recent.push({ ...r, node: n })));
  recent.sort((a, b) => b.t - a.t);
  const stream = recent.slice(0, 12);
  const agentsByNode = (id) => (assign[id] || []).map(aid => DB.agents.find(a => a.id === aid)).filter(Boolean);
  const totalRuns = recent.length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', borderBottom: `1px solid ${HB.line}`, flexShrink: 0, background: HB.card }}>
        {[['activity', 'Activity', 'bolt'], ['routing', 'Routing', 'sliders'], ['sessions', 'Sessions', 'agent'], ['history', 'History', 'pulse']].map(([k, l, ic]) => (
          <button key={k} onClick={() => setTab(k)} style={tabBtn(tab === k)}><CKIcon name={ic} size={12}/>{l}</button>
        ))}
      </div>

      <div className="hb-scroll" style={{ flex: 1, overflow: 'auto' }}>
        {tab === 'activity' && (
          <div>
            {/* the Attention node owns importance */}
            <div style={{ ...sideSec, background: HB.paper2 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: HB.accent, boxShadow: `0 0 0 3px ${HB.accent}22` }}/>
                <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.accent, letterSpacing: '0.16em', flex: 1 }}>WHAT MATTERS NOW</div>
                <button onClick={onTuneAttention} title="Open the Attention node to tune its weights" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, border: `1px solid ${HB.line}`, background: HB.card, color: HB.inkSoft, borderRadius: 6, padding: '3px 8px', cursor: 'pointer', fontFamily: HB.mono, fontSize: 9 }}><CKIcon name="gear" size={10}/>tune</button>
              </div>
              <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, marginBottom: 10, lineHeight: 1.4 }}>ranked by the <b style={{ color: HB.inkSoft }}>Attention</b> node — a parametric node you control, not a fixed rule.</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {attention.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>Nothing flagged. The graph is calm.</div>}
                {attention.map((it, i) => { const c = { red: HB.red, accent: HB.accent, blue: HB.blue, green: HB.green }[it.tone]; const ic = { blocked: 'x', gap: 'eye', agent: 'agent' }[it.kind]; return (
                  <button key={i} onClick={() => onGoto(it)} className="hb-rowh" style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textAlign: 'left', border: `1px solid ${HB.line}`, borderLeft: `3px solid ${c}`, background: HB.card }}>
                    <span style={{ width: 22, height: 22, borderRadius: 6, display: 'grid', placeItems: 'center', background: c + '1c', color: c, flexShrink: 0 }}><CKIcon name={ic} size={12}/></span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontSize: 12.5, fontWeight: 600, color: HB.ink, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.label}</span>
                      <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{it.sub}{it.score != null ? ` · ${it.score}` : ''}</span>
                    </span>
                    <CKIcon name="eye" size={13} color={HB.inkMute}/>
                  </button>
                ); })}
              </div>
            </div>

            {/* agentic notifications — the run stream */}
            <div style={sideSec}>
              <div style={{ ...sideLabel, display: 'flex', justifyContent: 'space-between' }}><span>AGENT ACTIVITY</span><span style={{ color: HB.inkDim }}>{totalRuns} total</span></div>
              {stream.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>No runs yet. Run a node — its agents report here.</div>}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {stream.map((r, i) => { const ags = agentsByNode(r.node.id); return (
                  <button key={r.id} onClick={() => onGoto({ nodeId: r.node.id, dom: r.node.dom })} className="hb-rowh" style={{ display: 'flex', alignItems: 'flex-start', gap: 9, padding: '8px', borderRadius: 8, cursor: 'pointer', textAlign: 'left', border: 'none', background: 'transparent' }}>
                    <span style={{ width: 18, height: 18, borderRadius: 5, marginTop: 1, display: 'grid', placeItems: 'center', background: (r.ok ? HB.green : HB.red) + '1e', color: r.ok ? HB.green : HB.red, flexShrink: 0, fontSize: 10 }}>{r.ok ? '✓' : '✗'}</span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontSize: 12, color: HB.ink, display: 'block' }}><b style={{ fontWeight: 600 }}>{ags[0] ? ags[0].name : 'System'}</b> ran <span style={{ color: HB.inkSoft }}>{r.node.title}</span></span>
                      <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{r.result}{r.ms ? ' · ' + r.ms + 'ms' : ''} · {ago(r.t)} ago</span>
                    </span>
                  </button>
                ); })}
              </div>
            </div>
          </div>
        )}

        {tab === 'routing' && (() => {
          const models = DB.models || [];
          const live = models.filter(m => m.status !== 'disabled');
          // task classes present anywhere in the fleet, plus the ones the app always needs
          const classes = [...new Set(['intent', 'vision', 'compose', 'critique', 'extract', 'fallback', 'offline',
            ...models.flatMap(m => m.tasks || [])])];
          // There used to be a hardcoded monthly call volume per task class here, multiplied by
          // each model's rate into a dollar figure the panel printed as SPEND. No call was ever
          // counted. The cockpit does not meter model usage, so it now shows the routing it can
          // prove and says plainly that no spend has been measured.
          const ownerOf = (cls) => (live.find(m => (m.tasks || []).includes(cls)) || {}).id || '';
          const route = (cls, id) => {
            setColl && setColl('models', ms => ms.map(m => {
              const has = (m.tasks || []).includes(cls);
              if (m.id === id && !has) return { ...m, tasks: [...(m.tasks || []), cls] };
              if (m.id !== id && has) return { ...m, tasks: (m.tasks || []).filter(t => t !== cls) };
              return m;
            }));
            const nm = (models.find(m => m.id === id) || {}).name || 'none';
            flash && flash(cls + ' → ' + nm);
          };
          const issues = (DB.issues || []);
          const openIss = issues.filter(i => i.status !== 'resolved');
          const agents = DB.agents || [];
          return (
            <div>
              <div style={sideSec}>
                <div style={{ ...sideLabel, display: 'flex', justifyContent: 'space-between' }}>
                  <span>MODEL ROUTING</span><span style={{ color: HB.inkSoft }}>{classes.length} task classes</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                  {classes.map(cls => (
                    <div key={cls} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.ink, width: 62, flexShrink: 0 }}>{cls}</span>
                      <select value={ownerOf(cls)} onChange={e => route(cls, e.target.value)}
                        style={{ flex: 1, minWidth: 0, padding: '5px 6px', borderRadius: 6, border: '1px solid ' + HB.line, background: HB.paper, color: HB.ink, fontFamily: HB.mono, fontSize: 10 }}>
                        <option value="">— unrouted —</option>
                        {live.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
                <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkSoft, marginTop: 9, lineHeight: 1.5 }}>
                  Reassigning a class rewrites the fleet. The change is saved with your model list.
                </div>
              </div>

              <div style={sideSec}>
                <div style={sideLabel}>SPEND</div>
                <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkSoft, lineHeight: 1.5 }}>
                  Not measured. Nothing here counts model calls, so the cockpit has no spend figure to give you.
                </div>
                <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginTop: 7, lineHeight: 1.5 }}>
                  Rates you entered per model are shown with each model; a total needs real usage, and usage is not reported to the cloud.
                </div>
              </div>

              <div style={{ ...sideSec, borderBottom: 'none' }}>
                <div style={{ ...sideLabel, display: 'flex', justifyContent: 'space-between' }}>
                  <span>INCIDENTS</span><span style={{ color: openIss.length ? HB.red : HB.green }}>{openIss.length} open</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {openIss.slice(0, 6).map(it => (
                    <div key={it.id} style={{ padding: '8px 9px', borderRadius: 7, background: HB.paper2, border: '1px solid ' + HB.line }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: it.level === 'error' ? HB.red : HB.amber, flexShrink: 0 }}/>
                        <span style={{ fontFamily: HB.sans, fontSize: 12, color: HB.ink, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.title}</span>
                        <span style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkSoft }}>×{it.count || 1}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 7 }}>
                        <select value={it.owner || ''} onChange={e => { var nm = e.target.value; setColl && setColl('issues', xs => xs.map(x => x.id === it.id ? { ...x, owner: nm } : x)); flash && flash(nm ? 'Assigned to ' + nm : 'Unassigned'); }}
                          style={{ flex: 1, minWidth: 0, padding: '4px 5px', borderRadius: 5, border: '1px solid ' + HB.line, background: HB.paper, color: HB.ink, fontFamily: HB.mono, fontSize: 9.5 }}>
                          <option value="">— unassigned —</option>
                          {agents.map(a => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
                        </select>
                        <button onClick={() => { setColl && setColl('issues', xs => xs.map(x => x.id === it.id ? { ...x, status: 'resolved' } : x)); flash && flash('Resolved'); }}
                          style={{ fontFamily: HB.mono, fontSize: 9.5, padding: '4px 8px', borderRadius: 5, border: '1px solid ' + HB.green, background: 'transparent', color: HB.green, cursor: 'pointer', flexShrink: 0 }}>resolve</button>
                      </div>
                    </div>
                  ))}
                  {!openIss.length && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkSoft }}>Queue clear.</div>}
                </div>
              </div>
            </div>
          );
        })()}

        {tab === 'sessions' && (
          <div>
            <div style={{ ...sideSec, borderBottom: `1px solid ${HB.line}` }}>
              <div style={{ ...sideLabel, display: 'flex', justifyContent: 'space-between' }}>
                <span>WHAT YOU ASKED YOUR APP</span>
                <button onClick={() => onReloadTasks && onReloadTasks()} style={{ border: `1px solid ${HB.line}`, background: 'transparent', color: HB.inkSoft, borderRadius: 5, padding: '2px 7px', cursor: 'pointer', fontFamily: HB.mono, fontSize: 9 }}>refresh</button>
              </div>
              <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, marginBottom: 10, lineHeight: 1.5 }}>
                Every instruction the cockpit queued for your ArchHub app, and the answer it posted back.
              </div>
              {rows.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>No instructions yet. Ask the cockpit something and the exchange lands here.</div>}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {rows.slice(0, 24).map(r => {
                  const tone = { ok: HB.green, err: HB.red, accent: HB.accent, mute: HB.inkMute }[TASK_TONE[r.status] || 'mute'];
                  const at = taskStamp(r);
                  return (
                    <div key={r.id} style={{ border: `1px solid ${HB.line}`, borderLeft: `3px solid ${tone}`, borderRadius: 10, overflow: 'hidden', background: HB.card }}>
                      <div style={{ padding: '9px 11px' }}>
                        <div style={{ fontSize: 12.5, color: HB.ink, lineHeight: 1.45 }}>{r.directive}</div>
                        <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginTop: 4 }}>
                          {r.status}{r.claimed_by ? ' · ' + r.claimed_by : ''}{at ? ' · ' + ago(at) + ' ago' : ''}
                        </div>
                      </div>
                      {r.result ? (
                        <div style={{ borderTop: `1px solid ${HB.lineSoft}`, padding: '9px 11px', background: HB.paper2, fontSize: 12, color: HB.ink, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{r.result}</div>
                      ) : (
                        <div style={{ borderTop: `1px solid ${HB.lineSoft}`, padding: '7px 11px', background: HB.paper2, fontFamily: HB.serif, fontStyle: 'italic', fontSize: 12.5, color: HB.inkMute }}>
                          {r.status === 'queued' ? 'Waiting for your app to claim it.' : 'No answer posted.'}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            {ctl && (ctl.agents || []).length > 0 && (
              <div style={{ ...sideSec, borderBottom: 'none' }}>
                <div style={sideLabel}>AGENTS YOUR APP REPORTED</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                  {(ctl.agents || []).map((a, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 9px', borderRadius: 7, background: HB.paper2, border: `1px solid ${HB.lineSoft}` }}>
                      <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: a.status === 'online' ? HB.green : HB.inkMute }}/>
                      <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: HB.ink }}>{a.provider || a.runtime || 'agent'}</span>
                      <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{String(a.session || '').slice(0, 8)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'history' && (
          <div style={sideSec}>
            <div style={sideLabel}>GRAND-MAP HISTORY · RUN TREE</div>
            {recent.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>No history yet. Every node run, edit, and variant is recorded here as a tree.</div>}
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {(() => {
                // group by node, newest first; show each node's runs as a small branch
                const byNode = {}; recent.forEach(r => { (byNode[r.node.id] = byNode[r.node.id] || { node: r.node, runs: [] }).runs.push(r); });
                const groups = Object.values(byNode).sort((a, b) => b.runs[0].t - a.runs[0].t);
                return groups.map((g, gi) => (
                  <div key={g.node.id} style={{ display: 'flex', gap: 10 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                      <span style={{ width: 11, height: 11, borderRadius: 3, background: (M.domains.find(d => d.key === g.node.dom) || {}).col || HB.accent, marginTop: 5 }}/>
                      {gi < groups.length - 1 && <span style={{ flex: 1, width: 1.5, background: HB.line }}/>}
                    </div>
                    <div style={{ flex: 1, paddingBottom: 14 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600, color: HB.ink }}>{g.node.title}</div>
                      <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, marginBottom: 5 }}>{(M.domains.find(d => d.key === g.node.dom) || {}).title}</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, borderLeft: `1.5px solid ${HB.lineSoft}`, paddingLeft: 9 }}>
                        {g.runs.slice(0, 5).map(r => (
                          <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                            <span style={{ width: 7, height: 7, borderRadius: '50%', background: r.ok ? HB.green : HB.red, flexShrink: 0 }}/>
                            <span style={{ fontFamily: HB.mono, fontSize: 10.5, color: HB.inkSoft }}>{r.variantOf ? '⌥ variant' : 'run'} #{r.n}</span>
                            <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginLeft: 'auto' }}>{ago(r.t)} ago</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ));
              })()}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LIBRARY — the left rail's primary drag source, mirroring Studio's NodesPanel:
// searchable, collapsible categories, drag an item onto the map to create it.
// Same gesture in the cockpit as in the app: the graph logic is one concept.
// ─────────────────────────────────────────────────────────────────────────────
const LIB_GROUPS = [
  { cat: 'connector', label: 'HOSTS · CONNECTORS', items: [
    ['Revit', 'open doc · view · selection'], ['Rhino / Grasshopper', 'geometry · definition'],
    ['IFC / Speckle', 'federated exchange'], ['Navisworks', 'clash · appended model'] ] },
  { cat: 'input', label: 'READ · INPUT', items: [
    ['Parameter read', 'element → value'], ['Schedule read', 'tabular extract'],
    ['Sheet index', 'sheets · revisions'], ['Model health', 'warnings · file size'] ] },
  { cat: 'transform', label: 'TRANSFORM', items: [
    ['Map values', 'per-element rewrite'], ['Join / merge', 'two streams → one'],
    ['Units convert', 'metric ↔ imperial'], ['Classify', 'assign Uniclass / OmniClass'] ] },
  { cat: 'logic', label: 'LOGIC', items: [
    ['Filter', 'predicate → subset'], ['Branch', 'route by condition'],
    ['Gate', 'hold until approved'], ['Loop', 'iterate a collection'] ] },
  { cat: 'ai', label: 'AI · AGENTS', items: [
    ['Agent', 'model + tools + brief'], ['Intent', 'natural language → plan'],
    ['Review', 'critique against a rule'], ['Summarise', 'stream → digest'] ] },
  { cat: 'skill', label: 'SKILLS', items: [
    ['Saved field', 'a field you promoted'], ['Saved canvas', 'a whole workflow'],
    ['Shared skill', 'from the marketplace'] ] },
  { cat: 'watch', label: 'WATCH · OUTPUT', items: [
    ['Watcher', 'observe a value live'], ['Preview', 'render the data'],
    ['Publish', 'write back to host'], ['Notify', 'alert a person or channel'] ] },
];

function LibraryPanel({ onCreateNode, onAddDomain, flash }) {
  const [q, setQ] = React.useState('');
  const [open, setOpen] = React.useState(() => Object.fromEntries(LIB_GROUPS.map(g => [g.cat, true])));
  const ql = q.trim().toLowerCase();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <div style={{ padding: '11px 12px 9px', borderBottom: `1px solid ${HB.lineSoft}`, flexShrink: 0 }}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="search the library…"
          style={{ width: '100%', padding: '7px 9px', borderRadius: 7, border: `1px solid ${HB.line}`, background: HB.paper, color: HB.ink, fontFamily: HB.mono, fontSize: 11, outline: 'none' }}/>
        <button onClick={onAddDomain} style={{ marginTop: 8, width: '100%', padding: '8px 0', borderRadius: 7, border: `1px dashed ${HB.accent}`, background: 'transparent', color: HB.accent, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, letterSpacing: '0.08em' }}>＋ NEW DOMAIN</button>
      </div>
      <div className="hb-scroll" style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '6px 8px 14px', minHeight: 0 }}>
        {LIB_GROUPS.map(g => {
          const items = ql ? g.items.filter(([t, s]) => (t + ' ' + s).toLowerCase().includes(ql)) : g.items;
          if (!items.length) return null;
          const col = (window.catCol && window.catCol(g.cat)) || HB.accent;
          const isOpen = ql ? true : open[g.cat];
          return (
            <div key={g.cat} style={{ marginBottom: 6 }}>
              <button onClick={() => setOpen(o => ({ ...o, [g.cat]: !o[g.cat] }))}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 7, padding: '6px 5px', background: 'transparent', border: 0, cursor: 'pointer', color: HB.inkSoft, fontFamily: HB.mono, fontSize: 9, letterSpacing: '0.14em', textAlign: 'left' }}>
                <span style={{ width: 7, height: 7, borderRadius: 2, background: col, flexShrink: 0 }}/>
                <span style={{ flex: 1 }}>{g.label}</span>
                <span style={{ color: HB.inkSoft }}>{items.length} {isOpen ? '▾' : '▸'}</span>
              </button>
              {isOpen && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1, paddingLeft: 4 }}>
                  {items.map(([title, sub]) => (
                    <div key={title} draggable="true"
                      onDragStart={e => { e.dataTransfer.setData('application/x-atlas-node', JSON.stringify({ cat: g.cat, title, sub })); e.dataTransfer.effectAllowed = 'copy'; }}
                      onDoubleClick={() => onCreateNode({ cat: g.cat, title, sub })}
                      title="Drag onto the map, or double-click to place"
                      style={{ padding: '6px 8px', borderRadius: 5, cursor: 'grab', userSelect: 'none', borderLeft: `2px solid transparent` }}
                      onMouseEnter={e => { e.currentTarget.style.background = HB.paper2; e.currentTarget.style.borderLeftColor = col; }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderLeftColor = 'transparent'; }}>
                      <div style={{ fontFamily: HB.sans, fontSize: 12, color: HB.ink }}>{title}</div>
                      <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, marginTop: 1 }}>{sub}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, { AgenticPanel, LibraryPanel });
