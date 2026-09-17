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

// He drew a composer under the sessions: you type to your app and the
// exchange lands in the same list. The panel was handed the relay and never
// used it, so the sidebar could only watch (2026-09-07). This sends through
// the same door the ask bar uses and refreshes the list on the answer.
function SessionComposer({ onRelay, onReloadTasks, flash }) {
  const [draft, setDraft] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const send = () => {
    const said = draft.trim();
    if (!said || busy || !onRelay) return;
    setBusy(true);
    Promise.resolve(onRelay(said, true))
      .then(d => {
        const text = String((d && d.message) || '').slice(0, 160);
        if (flash) flash(text || 'Sent to your app');
        setDraft('');
        if (onReloadTasks) onReloadTasks();
      })
      .catch(e => { if (flash) flash('Not sent: ' + String((e && e.message) || e).slice(0, 120)); })
      .then(() => setBusy(false));
  };
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
      <input value={draft} onChange={e => setDraft(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') send(); }}
        placeholder={busy ? 'Sending…' : 'Message your app…'}
        style={{ flex: 1, padding: '7px 10px', borderRadius: 8, border: '1px solid ' + HB.line,
          background: HB.card, color: HB.ink, fontSize: 12, outline: 'none', fontFamily: HB.sans }}/>
      <button onClick={send} disabled={busy || !draft.trim()} style={{ border: '1px solid ' + HB.line,
        background: draft.trim() && !busy ? HB.accent : 'transparent',
        color: draft.trim() && !busy ? '#fff' : HB.inkMute, borderRadius: 8, padding: '0 12px',
        cursor: draft.trim() && !busy ? 'pointer' : 'default', fontFamily: HB.mono, fontSize: 10 }}>send</button>
    </div>
  );
}


function AgenticPanel({ M, DB, assign, attention, onGoto, onTuneAttention, attNode, setColl, flash, control, tasks, tasksLoaded, serverErrors, onRelay, onReloadTasks }) {
  const [tab, setTab] = React.useState('activity');
  const [openRows, setOpenRows] = React.useState({});   // session cards the founder folded open or shut
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
                      <span style={{ fontSize: 12, color: HB.ink, display: 'block' }}><b style={{ fontWeight: 600 }}>{ags[0] ? ags[0].name : r.app ? 'Your app' : 'System'}</b> ran <span style={{ color: HB.inkSoft }}>{r.node.title}</span></span>
                      <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{r.result}{r.ms ? ' · ' + r.ms + 'ms' : ''} · {ago(r.t)} ago</span>
                    </span>
                  </button>
                ); })}
              </div>
            </div>
          </div>
        )}

        {tab === 'routing' && (() => {
          // MODEL ROUTING shows what the app publishes with its map: control.models and
          // control.routes (the contract is published_models_form in nodelang/cloud_relay.py).
          // This panel used to route task classes over a model list kept in this page that
          // nothing filled, and told the founder a change reached the fleet when no router saw it.
          // Until the app publishes, it says so; a route is changed in the app, not here.
          const published = ctl && Array.isArray(ctl.models) ? ctl.models : null;
          const routes = ctl && Array.isArray(ctl.routes) ? ctl.routes : [];
          // INCIDENTS are the failures the cloud holds: instructions your app answered with a
          // refusal or an error (failed task rows), and server errors since the cloud last
          // restarted. Identical failures fold into one row that carries their real count.
          const fold = (items) => {
            const byKey = new Map();
            items.forEach(it => {
              const was = byKey.get(it.key);
              if (was) { was.count += 1; was.t = Math.max(was.t || 0, it.t || 0); }
              else byKey.set(it.key, { ...it, count: 1 });
            });
            return [...byKey.values()].sort((a, b) => (b.t || 0) - (a.t || 0));
          };
          const errorsLoaded = !!(serverErrors && serverErrors.loaded);
          const failed = tasksLoaded ? rows.filter(r => r.status === 'failed').map(r => ({
            key: 'task:' + r.directive, source: 'your app', title: String(r.directive || 'instruction'), detail: String(r.result || ''), t: taskStamp(r) })) : [];
          const serverRows = errorsLoaded ? (serverErrors.rows || []).map(e => ({
            key: 'error:' + e.where + ':' + e.kind, source: 'cloud', title: String(e.kind || 'error') + ' \u00b7 ' + String(e.where || ''), detail: String(e.message || ''), t: e.ts ? e.ts * 1000 : null })) : [];
          const incidents = fold([...failed, ...serverRows]);
          const events = incidents.reduce((n, it) => n + it.count, 0);
          const known = !!tasksLoaded || errorsLoaded;
          const clearText = [
            tasksLoaded ? 'Nothing failed in the last ' + rows.length + ' instruction' + (rows.length === 1 ? '' : 's') : 'The task queue could not be read',
            errorsLoaded ? 'the cloud has recorded no server error since it last restarted' : 'the cloud error log could not be read',
          ].join('; ') + '.';
          return (
            <div>
              <div style={sideSec}>
                <div style={{ ...sideLabel, display: 'flex', justifyContent: 'space-between' }}>
                  <span>MODEL ROUTING</span><span style={{ color: HB.inkSoft }}>{published ? published.length + ' model' + (published.length === 1 ? '' : 's') : 'not published'}</span>
                </div>
                {!published && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute, lineHeight: 1.5 }}>Your app has not published its model list, so there is no routing to show. It appears here once the app sends it with the map.</div>}
                {published && published.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>Your app published an empty model list.</div>}
                {published && published.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    {published.map((m, i) => (
                      <div key={m.name + ':' + i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 9px', borderRadius: 7, background: HB.paper2, border: '1px solid ' + HB.lineSoft }}>
                        <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: m.available ? HB.green : HB.inkMute }}/>
                        <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: HB.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.name}</span>
                        <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{m.provider}{m.available ? '' : ' \u00b7 unavailable'}</span>
                      </div>
                    ))}
                  </div>
                )}
                {published && routes.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 10 }}>
                    {routes.map(r => (
                      <div key={r.task} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.ink, width: 62, flexShrink: 0 }}>{r.task}</span>
                        <span style={{ flex: 1, minWidth: 0, fontFamily: HB.mono, fontSize: 10, color: HB.inkSoft, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.model}</span>
                      </div>
                    ))}
                  </div>
                )}
                {published && <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkSoft, marginTop: 9, lineHeight: 1.5 }}>
                  {routes.length ? 'Routing as your app reported it. Change it in the app.' : 'Your app did not report which model serves each task.'}
                </div>}
              </div>

              <div style={sideSec}>
                <div style={sideLabel}>SPEND</div>
                <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkSoft, lineHeight: 1.5 }}>
                  Not measured. Nothing here counts model calls, so the cockpit has no spend figure to give you.
                </div>
              </div>

              <div style={{ ...sideSec, borderBottom: 'none' }}>
                <div style={{ ...sideLabel, display: 'flex', justifyContent: 'space-between' }}>
                  <span>INCIDENTS</span>
                  <span style={{ color: !known ? HB.inkMute : events ? HB.red : HB.green }}>{!known ? 'not known' : events ? events + ' recorded' : 'none recorded'}</span>
                </div>
                {!known && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute, lineHeight: 1.5 }}>The cockpit could not read the task queue or the cloud error log, so it cannot tell whether anything failed.</div>}
                {known && incidents.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkSoft, lineHeight: 1.5 }}>{clearText}</div>}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {incidents.slice(0, 8).map(it => (
                    <div key={it.key} title={it.detail} style={{ padding: '8px 9px', borderRadius: 7, background: HB.paper2, border: '1px solid ' + HB.line }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: HB.red, flexShrink: 0 }}/>
                        <span style={{ fontFamily: HB.sans, fontSize: 12, color: HB.ink, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.title}</span>
                        <span style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkSoft }}>{'\u00d7' + it.count}</span>
                      </div>
                      <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginTop: 5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.source}{it.t ? ' \u00b7 ' + ago(it.t) + ' ago' : ''}{it.detail ? ' \u00b7 ' + it.detail : ''}</div>
                    </div>
                  ))}
                  {incidents.length > 8 && <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{incidents.length - 8} more not shown</div>}
                </div>
              </div>
            </div>
          );
        })()}

        {tab === 'sessions' && (
          <div>
            <div style={{ ...sideSec, borderBottom: `1px solid ${HB.line}` }}>
              <div style={{ ...sideLabel, display: 'flex', justifyContent: 'space-between' }}>
                <span>CONVERSATIONS WITH YOUR AGENTS</span>
                <button onClick={() => onReloadTasks && onReloadTasks()} style={{ border: `1px solid ${HB.line}`, background: 'transparent', color: HB.inkSoft, borderRadius: 5, padding: '2px 7px', cursor: 'pointer', fontFamily: HB.mono, fontSize: 9 }}>refresh</button>
              </div>
              <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, marginBottom: 10, lineHeight: 1.5 }}>
                What you said to your app, and what it said back. Type below to say something new.
              </div>
              {rows.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>No instructions yet. Ask the cockpit something and the exchange lands here.</div>}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {rows.slice(0, 24).map((r, i) => {
                  const tone = { ok: HB.green, err: HB.red, accent: HB.accent, mute: HB.inkMute }[TASK_TONE[r.status] || 'mute'];
                  const at = taskStamp(r);
                  // His card: each exchange is a card that folds open to the conversation
                  // inside it, and the newest opens by itself as the first card did in his
                  // design. The rows are still the real task queue; nothing here is seeded.
                  const open = openRows[r.id] !== undefined ? openRows[r.id] : i === 0;
                  return (
                    <div key={r.id} style={{ border: `1px solid ${HB.line}`, borderRadius: 10, overflow: 'hidden', background: HB.card }}>
                      <button onClick={() => setOpenRows(o => ({ ...o, [r.id]: !open }))} aria-expanded={open}
                        style={{ display: 'flex', alignItems: 'center', gap: 9, width: '100%', textAlign: 'left', padding: '10px 11px', border: 'none', background: 'transparent', cursor: 'pointer' }}>
                        <span style={{ width: 26, height: 26, borderRadius: 7, display: 'grid', placeItems: 'center', background: HB.accentSoft, color: HB.accentHi, flexShrink: 0 }}><CKIcon name="agent" size={13}/></span>
                        <span style={{ flex: 1, minWidth: 0 }}>
                          <span style={{ fontSize: 12.5, fontWeight: 600, color: HB.ink, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.directive}</span>
                          <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{r.claimed_by || 'your app'}{at ? ' \u00b7 ' + ago(at) + ' ago' : ''}</span>
                        </span>
                        <span title={r.status} style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: tone }}/>
                        <span style={{ fontFamily: HB.mono, fontSize: 15, color: HB.inkMute, width: 14, textAlign: 'center' }}>{open ? '\u25be' : '\u25b8'}</span>
                      </button>
                      {open && (
                        // His treatment inside the card: what the founder said sits right in an
                        // accent bubble with its state under it, what the app answered sits left
                        // in a bordered card, both capped so the exchange reads as a conversation.
                        <div style={{ borderTop: `1px solid ${HB.lineSoft}`, padding: '10px 11px', display: 'flex', flexDirection: 'column', gap: 6, background: HB.paper2 }}>
                          <div style={{ display: 'flex', flexDirection: 'row-reverse', gap: 8 }}>
                            <span style={{ maxWidth: '82%', padding: '7px 10px', borderRadius: 10, fontSize: 12, lineHeight: 1.45, background: HB.accent, color: '#fff' }}>{r.directive}</span>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'row-reverse', gap: 8 }}>
                            <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: tone }}>{r.status}</span>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'row', gap: 8 }}>
                            <span style={{ maxWidth: '82%', padding: '7px 10px', borderRadius: 10, fontSize: 12, lineHeight: 1.5, background: HB.card, color: r.result ? HB.ink : HB.inkMute, border: `1px solid ${HB.line}`, whiteSpace: 'pre-wrap', fontFamily: r.result ? HB.sans : HB.serif, fontStyle: r.result ? 'normal' : 'italic' }}>
                              {r.result || (r.status === 'queued' ? 'Waiting for your app to claim it.' : 'No answer posted.')}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <SessionComposer onRelay={onRelay} onReloadTasks={onReloadTasks} flash={flash}/>
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
// The COCKPIT library. It held the desktop studio's node palette -- Revit,
// Rhino, IFC, parameter reads -- which do nothing here: the founder asked
// what a Revit host node would even do in the cockpit (2026-09-07). The
// cockpit is where he runs the business and directs the agents, so its
// library is the work he actually places on this map. Host and geometry
// nodes stay in the studio, on the canvas that can run them.
const LIB_GROUPS = [
  { cat: 'ai', label: 'AGENTS', items: [
    ['Agent', 'a runtime that claims Work'], ['Assignment', 'give this to an agent'],
    ['Review', 'an agent critiques the result'], ['Handoff', 'pass Work between agents'] ] },
  { cat: 'logic', label: 'WORK', items: [
    ['Work item', 'something to be done'], ['Gate', 'hold until approved'],
    ['Court', 'the check that proves it'], ['Blocker', 'why it cannot proceed'] ] },
  { cat: 'input', label: 'BRAIN', items: [
    ['Recall', 'ask the brain a question'], ['Remember', 'commit a fact'],
    ['Fact', 'one thing the brain holds'], ['Digest', 'summarise a stream'] ] },
  { cat: 'watch', label: 'WATCH', items: [
    ['Metric', 'a number to follow'], ['Alert', 'tell me when it moves'],
    ['Report', 'a view assembled on demand'], ['Log', 'what happened, in order'] ] },
  { cat: 'transform', label: 'MAP', items: [
    ['Domain', 'a place on this map'], ['Field', 'a domain of domains'],
    ['Capability', 'something the product does'], ['Wire', 'this depends on that'] ] },
  { cat: 'connector', label: 'REACH', items: [
    ['Host', 'an application on a machine'], ['Cloud service', 'something running remotely'],
    ['Person', 'someone who is told'], ['Schedule', 'when it runs by itself'] ] },
];

function LibraryPanel({ onCreateNode, onAddDomain, flash }) {
  const [q, setQ] = React.useState('');
  const [open, setOpen] = React.useState(() => Object.fromEntries(LIB_GROUPS.map(g => [g.cat, true])));
  const [ghost, setGhost] = React.useState(null);
  const ql = q.trim().toLowerCase();
  // POINTER drag, not HTML5 drag-and-drop. The founder could not drag a node
  // onto the canvas at all: QtWebEngine does not carry an HTML5 drag reliably
  // inside the desktop shell, and a drag that never starts leaves no error to
  // read (2026-09-07). Pointer capture works in every shell and gives a real
  // preview of what is being carried.
  const startLibraryDrag = (event, item, col) => {
    if (event.button !== 0) return;
    const from = { x: event.clientX, y: event.clientY };
    let carrying = false;
    const move = (moved) => {
      if (!carrying) {
        if (Math.abs(moved.clientX - from.x) + Math.abs(moved.clientY - from.y) < 5) return;
        carrying = true;
      }
      setGhost({ item, col, x: moved.clientX, y: moved.clientY });
    };
    const up = (ended) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      setGhost(null);
      if (!carrying) return;
      const drop = window.__atlasDropLibraryItem;
      const landed = drop && drop(item, ended.clientX, ended.clientY);
      if (!landed && flash) flash('Drop it on the map to place ' + item.title);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <div style={{ padding: '11px 12px 9px', borderBottom: `1px solid ${HB.lineSoft}`, flexShrink: 0 }}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="search the library…"
          style={{ width: '100%', padding: '7px 9px', borderRadius: 7, border: `1px solid ${HB.line}`, background: HB.paper, color: HB.ink, fontFamily: HB.mono, fontSize: 11, outline: 'none' }}/>
        <button onClick={onAddDomain} style={{ marginTop: 8, width: '100%', padding: '8px 0', borderRadius: 7, border: `1px dashed ${HB.accent}`, background: 'transparent', color: HB.accent, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, letterSpacing: '0.08em' }}>＋ NEW DOMAIN</button>
      </div>
      {ghost && (
        <div style={{ position: 'fixed', left: ghost.x + 12, top: ghost.y + 10, zIndex: 9999, pointerEvents: 'none',
          padding: '6px 10px', borderRadius: 6, background: HB.paper2, color: HB.ink,
          border: `1px solid ${ghost.col}`, borderLeft: `3px solid ${ghost.col}`,
          boxShadow: '0 8px 22px rgba(0,0,0,.35)', fontFamily: HB.sans, fontSize: 12, whiteSpace: 'nowrap' }}>
          {ghost.item.title}
        </div>
      )}
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
                    <div key={title}
                      onPointerDown={e => startLibraryDrag(e, { cat: g.cat, title, sub }, col)}
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
