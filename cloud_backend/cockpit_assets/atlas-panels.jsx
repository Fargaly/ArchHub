// atlas-panels.jsx — the permanent RIGHT panel states (macro / micro / bulk) + modals.
// Macro: overview + create domain/node + groups. Micro: node inspector. Bulk: multi-select ops.

const { HB, hsc, HBtn, HIconBtn, HPill, HDot, HAvatar, STC, catCol } = window;

const insLabel = { fontFamily: HB.mono, fontSize: 8.5, color: HB.accent, fontWeight: 700, letterSpacing: '0.14em', marginBottom: 7 };
const insInput = (mono) => ({ width: '100%', background: HB.paper2, border: `1px solid ${HB.line}`, color: HB.ink, borderRadius: 7, padding: '8px 10px', fontSize: 12.5, fontFamily: mono ? HB.mono : HB.sans, outline: 'none', resize: 'vertical' });
const secStyle = { padding: '15px 16px', borderBottom: `1px solid ${HB.lineSoft}` };

/* ════ SYSTEM — macro, nothing selected: whole-system overview ════ */
function SystemPanel({ M, counts, total, STATUS, attention, onGoto, onAddDomain, onEnter, openRoom }) {
  const domOf = {}; M.nodes.forEach(n => domOf[n.id] = n.dom);
  let cross = 0; M.wires.forEach(w => { if (domOf[w.a] && domOf[w.b] && domOf[w.a] !== domOf[w.b]) cross++; });
  const toneCol = { red: HB.red, accent: HB.accent, blue: HB.blue, green: HB.green };
  const toneIcon = { blocked: 'x', gap: 'eye', agent: 'agent' };
  return (
    <div>
      {attention && attention.length > 0 && (
        <div style={{ ...secStyle, borderBottom: `1px solid ${HB.line}`, background: HB.paper2 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: HB.accent, boxShadow: `0 0 0 3px ${HB.accent}22` }}/>
            <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.accent, letterSpacing: '0.18em' }}>WHAT MATTERS NOW</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {attention.map((it, i) => { const c = toneCol[it.tone]; return (
              <button key={i} onClick={() => onGoto(it)} className="hb-rowh" style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textAlign: 'left', border: `1px solid ${HB.line}`, borderLeft: `3px solid ${c}`, background: HB.card }}>
                <span style={{ width: 22, height: 22, borderRadius: 6, display: 'grid', placeItems: 'center', background: c + '1c', color: c, flexShrink: 0 }}><CKIcon name={toneIcon[it.kind]} size={12}/></span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: HB.ink, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.label}</span>
                  <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{it.sub}</span>
                </span>
                <CKIcon name="eye" size={13} color={HB.inkMute}/>
              </button>
            ); })}
          </div>
        </div>
      )}
      <div style={{ ...secStyle, borderBottom: `1px solid ${HB.line}` }}>
        <div style={{ fontFamily: HB.mono, fontSize: 8.5, color: HB.accent, letterSpacing: '0.2em' }}>MACRO · THE WHOLE SYSTEM</div>
        <div style={{ fontFamily: HB.serif, fontSize: 24, letterSpacing: '-0.02em', marginTop: 2 }}>{M.domains.length} domains, wired</div>
        <div style={{ fontFamily: HB.mono, fontSize: 11, color: HB.inkSoft, marginTop: 6, lineHeight: 1.5 }}>{total} capabilities · {M.wires.length} wires · {cross} cross-domain links. Hover a domain to trace its links; double-click to open.</div>
      </div>
      <div style={secStyle}>
        <div style={insLabel}>STATUS ACROSS THE SYSTEM</div>
        {STATUS.filter(s => counts[s]).map(s => (
          <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '4px 0' }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: STC[s] }}/>
            <span style={{ fontSize: 12.5, textTransform: 'capitalize', flex: 1 }}>{s}</span>
            <span style={{ flex: 2, height: 6, borderRadius: 3, background: HB.paper2, overflow: 'hidden' }}><span style={{ display: 'block', height: '100%', width: `${counts[s] / total * 100}%`, background: STC[s] }}/></span>
            <span style={{ fontFamily: HB.mono, fontSize: 10.5, color: HB.inkMute, width: 26, textAlign: 'right' }}>{counts[s]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ════ DOMAIN — a domain selected (macro) or open (micro) ════ */
// ─── LIVE DOMAIN CONTROL — drives the founder's RUNNING application ─────────────
// Renders what the app pushed (M.control: agents on his machine, governed work, host
// states); every button relays through /founder/api/command to the app itself.
// Hosts the app can bring to CONNECTED itself: Office through COM, Rhino and
// Blender launched with the shipped ArchHub bridge. Max needs MaxMCP (said so).
const OPENABLE = ['excel', 'word', 'powerpoint', 'outlook', 'rhino', 'blender'];

function LiveDomainControl({ M, d, members, onRelay }) {
  const ctl = M.control || null;
  const [ask, setAsk] = React.useState('');
  const [log, setLog] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const engines = members.filter(n => n.engine);
  const title = String(d.title || d.key || '');
  const low = title.toLowerCase();
  const isHosts = /host|connector/.test(String(d.key || '') + ' ' + low) || members.some(n => n.cat === 'host' || /host|connector/i.test(String(n.sub || '')));
  const agents = ctl ? (ctl.agents || []) : [];
  // Work is scoped to THIS domain when its title names the domain (or a word of
  // it); when nothing matches, the whole list is shown and labelled as such.
  const allItems = ctl ? (ctl.work_items || []) : [];
  const words = [low, String(d.key || '').toLowerCase(), ...low.split(/[^a-z0-9]+/).filter(w => w.length > 3)];
  const scoped = allItems.filter(w => { const t = String(w.title || '').toLowerCase(); return words.some(x => x && t.includes(x)); });
  const items = scoped.length ? scoped : allItems;
  const itemsLabel = scoped.length ? 'GOVERNED WORK · THIS DOMAIN' : 'GOVERNED WORK · ALL';
  const hosts = ctl ? (ctl.hosts || []) : [];
  const say = async (command, execute) => {
    if (!onRelay || busy) return;
    setBusy(true);
    try { const r = await onRelay(command, execute); setLog(l => [{ t: Date.now(), ok: !!r.ok && !r.pending_app, text: String(r.message || '').slice(0, 400) }, ...l].slice(0, 6)); }
    catch (e) { setLog(l => [{ t: Date.now(), ok: false, text: String(e) }, ...l].slice(0, 6)); }
    finally { setBusy(false); }
  };
  const runAll = async () => { for (const n of engines) { await say('run engine ' + n.engine, true); } };
  const pill = (state) => { const c = state === 'connected' ? HB.green : state === 'running' ? HB.blue : state === 'installed' ? HB.amber : HB.inkMute;
    return <span style={{ fontFamily: HB.mono, fontSize: 8.5, letterSpacing: '0.12em', color: c, border: `1px solid ${c}55`, borderRadius: 999, padding: '2px 7px' }}>{String(state || '').toUpperCase()}</span>; };
  const row = { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: `1px solid ${HB.line}` };
  const small = { fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute };
  return (
    <div style={secStyle}>
      <div style={insLabel}>IN YOUR APP · LIVE {ctl ? '' : '· waiting for the app push'}</div>
      {!ctl && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>Your ArchHub app has not pushed its control state yet. Open ArchHub on your machine; the push follows within a minute.</div>}
      {engines.length > 0 && <div style={{ marginTop: 8 }}>
        <div style={{ ...small, marginBottom: 4 }}>ENGINES · {engines.length}</div>
        {engines.slice(0, 12).map(n => <div key={n.id} style={row}>
          <span style={{ flex: 1, minWidth: 0, fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.title} <span style={small}>{n.engine}</span></span>
          <HBtn onClick={() => say('run engine ' + n.engine, true)} disabled={busy}>▸ Run</HBtn>
        </div>)}
        {engines.length > 1 && <div style={{ marginTop: 6 }}><HBtn primary onClick={runAll} disabled={busy}>▸ Run all {engines.length} in ArchHub</HBtn></div>}
      </div>}
      {ctl && <div style={{ marginTop: 10 }}>
        <div style={{ ...small, marginBottom: 4 }}>AGENTS ON YOUR MACHINE · {agents.length}</div>
        {agents.length === 0 && <div style={small}>none registered</div>}
        {agents.slice(0, 8).map((a, i) => <div key={i} style={row}><span style={{ width: 7, height: 7, borderRadius: '50%', background: a.status === 'online' ? HB.green : HB.inkMute }}/><span style={{ flex: 1, fontSize: 12 }}>{a.provider || a.runtime || 'agent'} <span style={small}>{a.runtime && a.runtime !== a.provider ? a.runtime : ''}</span></span><span style={small}>{String(a.session || '').slice(0, 8)}</span>
          <HBtn onClick={() => { const what = ask || ('review the ' + title + ' domain'); say('tell ' + (a.provider || a.runtime) + ': ' + what, true); }} disabled={busy}>→ Tell</HBtn></div>)}
      </div>}
      {ctl && (ctl.work_summary || items.length > 0) && <div style={{ marginTop: 10 }}>
        <div style={{ ...small, marginBottom: 4 }}>{itemsLabel}</div>
        {ctl.work_summary && <div style={{ fontSize: 12, color: HB.ink, marginBottom: 4 }}>{ctl.work_summary}</div>}
        {items.slice(0, 8).map((w, i) => <div key={i} style={row}><span style={{ flex: 1, fontSize: 12 }}>{w.title}</span><span style={small}>{w.state}{w.agent ? ' · ' + w.agent : ''}</span></div>)}
      </div>}
      {ctl && isHosts && hosts.length > 0 && <div style={{ marginTop: 10 }}>
        <div style={{ ...small, marginBottom: 4 }}>HOSTS · {hosts.filter(h => h.state === 'connected').length} connected of {hosts.length}</div>
        {hosts.map(h => <div key={h.id} style={row}><span style={{ flex: 1, minWidth: 0, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.name} <span style={small}>{h.state === 'connected' ? '' : (h.detail || '')}</span></span>{pill(h.state)}
          {OPENABLE.includes(h.id) && h.state !== 'connected' && <HBtn onClick={() => say('open ' + h.id, true)} disabled={busy}>▸ Open</HBtn>}</div>)}
      </div>}
      <div style={{ marginTop: 10 }}>
        <div style={{ ...small, marginBottom: 4 }}>ASK OR INSTRUCT YOUR APP · about {title}</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input value={ask} onChange={e => setAsk(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') say(ask + ' (about ' + title + ')', false); }} placeholder={'e.g. what is blocked in ' + title + '?'} style={{ ...insInput(true), flex: 1 }}/>
          <HBtn onClick={() => say(ask + ' (about ' + title + ')', false)} disabled={busy || !ask}>Ask</HBtn>
        </div>
        {log.map(l => <div key={l.t} style={{ marginTop: 6, padding: '6px 8px', borderRadius: 6, background: HB.paper, borderLeft: `2px solid ${l.ok ? HB.green : HB.amber}`, fontSize: 11.5, whiteSpace: 'pre-wrap' }}>{l.text}</div>)}
      </div>
    </div>
  );
}

function DomainPanel({ M, domKey, DB, counts, STATUS, CATS, macro, patchDomain, assign, toggleAgent, onEnter, onAddNode, onUngroup, openRoom, selectBy, onClose, onRelay }) {
  const [tab, setTab] = React.useState('control');
  const d = M.domains.find(x => x.key === domKey) || {};
  const members = M.nodes.filter(n => n.dom === domKey);
  const ids = new Set(members.map(n => n.id));
  const intra = M.wires.filter(w => ids.has(w.a) && ids.has(w.b)).length;
  const domOf = {}; M.nodes.forEach(n => domOf[n.id] = n.dom);
  const ports = {}; M.wires.forEach(w => { let other; if (ids.has(w.a) && !ids.has(w.b)) other = domOf[w.b]; else if (ids.has(w.b) && !ids.has(w.a)) other = domOf[w.a]; if (other) ports[other] = (ports[other] || 0) + 1; });
  const inbound = {}, outbound = {}; M.wires.forEach(w => { const aIn = ids.has(w.a), bIn = ids.has(w.b); if (aIn && !bIn) outbound[domOf[w.b]] = (outbound[domOf[w.b]] || 0) + 1; else if (bIn && !aIn) inbound[domOf[w.a]] = (inbound[domOf[w.a]] || 0) + 1; });
  const ifaceCount = new Set([...Object.keys(inbound), ...Object.keys(outbound)]).size;
  const st = {}; members.forEach(n => st[n.status] = (st[n.status] || 0) + 1);
  const agentCount = members.filter(n => (assign[n.id] || []).length).length;
  const myAgents = assign[domKey] || [];
  const params = d.params || [];
  const setParam = (i, k, v) => { const p = params.map((x, j) => j === i ? { ...x, [k]: v } : x); patchDomain(domKey, { params: p }); };
  const addParam = () => patchDomain(domKey, { params: [...params, { k: 'key', v: 'value' }] });
  const delParam = (i) => patchDomain(domKey, { params: params.filter((_, j) => j !== i) });

  return (
    <div>
      <div style={{ position: 'sticky', top: 0, zIndex: 2, background: HB.card, borderBottom: `1px solid ${HB.line}`, padding: '14px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', background: d.col + '22', color: d.col, flexShrink: 0, marginTop: 2 }}><CKIcon name="grid" size={16}/></span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: HB.mono, fontSize: 8.5, color: d.col, letterSpacing: '0.16em' }}>{d.grouped ? '⊞ GRAND NODE · GROUPED' : 'SUPER-NODE · DOMAIN'} · {members.length} INSIDE</div>
            <input value={d.title || ''} onChange={e => patchDomain(domKey, { title: e.target.value })} style={{ width: '100%', border: 'none', background: 'transparent', fontFamily: HB.serif, fontSize: 23, letterSpacing: '-0.02em', color: HB.ink, outline: 'none', padding: 0, marginTop: 2 }}/>
          </div>
          <HIconBtn name="x" onClick={onClose}/>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 11 }}>
          <HBtn primary onClick={onEnter} style={{ flex: 1, justifyContent: 'center' }}><CKIcon name="eye" size={13}/>Open</HBtn>
          <HBtn onClick={onAddNode} style={{ flex: 1, justifyContent: 'center' }}><CKIcon name="plus" size={13}/>Add node</HBtn>
          {d.grouped && onUngroup && <HBtn onClick={() => onUngroup(domKey)} style={{ flex: 1, justifyContent: 'center' }}><CKIcon name="grid" size={13}/>Ungroup</HBtn>}
        </div>
        <div style={{ display: 'flex', gap: 4, marginTop: 11 }}>
          {[['control', 'Control'], ['params', `Params ${params.length}`], ['links', `Interface ${ifaceCount}`]].map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)} style={{ flex: 1, padding: '6px 0', borderRadius: 7, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, border: `1px solid ${tab === k ? HB.accent : HB.line}`, background: tab === k ? HB.accentSoft : 'transparent', color: tab === k ? HB.accentHi : HB.inkSoft }}>{l}</button>
          ))}
        </div>
      </div>

      <div style={{ padding: 0 }}>
        {tab === 'control' && (
          <div>
            <LiveDomainControl M={M} d={d} members={members} onRelay={onRelay}/>
            <div style={secStyle}>
              <div style={insLabel}>INTENT</div>
              <textarea value={d.sub || ''} onChange={e => patchDomain(domKey, { sub: e.target.value })} rows={2} placeholder="What this domain owns…" style={insInput()}/>
            </div>
            <div style={secStyle}>
              <div style={insLabel}>DOMAIN STATUS · ROLLS UP TO ROADMAP</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {STATUS.map(s => <button key={s} onClick={() => patchDomain(domKey, { status: s })} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 999, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, textTransform: 'capitalize', border: `1px solid ${d.status === s ? STC[s] : HB.line}`, background: d.status === s ? STC[s] + '20' : 'transparent', color: d.status === s ? STC[s] : HB.inkSoft }}><span style={{ width: 7, height: 7, borderRadius: 2, background: STC[s] }}/>{s}</button>)}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 10, height: 8 }}>
                {STATUS.filter(s => st[s]).map(s => <span key={s} title={`${s}: ${st[s]}`} style={{ flex: st[s], background: STC[s], height: 8, borderRadius: 2 }}/>)}
              </div>
              <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginTop: 6 }}>composition of {members.length} nodes · {intra} internal wires</div>
            </div>
            <div style={secStyle}>
              <div style={insLabel}>OWNED BY AGENTS · WHOLE DOMAIN</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {DB.agents.map(a => { const on = myAgents.includes(a.id); return (
                  <button key={a.id} onClick={() => toggleAgent(domKey, a.id)} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textAlign: 'left', border: `1px solid ${on ? HB.accent : HB.line}`, background: on ? HB.accentSoft : HB.paper2 }}>
                    <span style={{ position: 'relative', flexShrink: 0, display: 'grid', placeItems: 'center' }}><HAvatar name={a.name} size={26}/>{on && <span style={{ position: 'absolute', inset: -2, borderRadius: '50%', border: `2px solid ${HB.accent}` }}/>}</span>
                    <span style={{ flex: 1, minWidth: 0 }}><span style={{ fontSize: 12.5, fontWeight: 500, display: 'block' }}>{a.name}</span><span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{(DB.models.find(m => m.id === a.model) || {}).name}</span></span>
                    {on ? <span style={{ color: HB.accent }}><CKIcon name="check" size={15}/></span> : <span style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, letterSpacing: '0.1em' }}>ASSIGN</span>}
                  </button>
                ); })}
              </div>
              {agentCount > 0 && <div style={{ fontFamily: HB.mono, fontSize: 10, color: HB.accent, marginTop: 8 }}>◇ plus {agentCount} member nodes individually owned</div>}
            </div>
            <div style={secStyle}>
              <div style={insLabel}>QUICK SELECT INSIDE</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{STATUS.filter(s => st[s]).map(s => <button key={s} onClick={() => selectBy(n => n.dom === domKey && n.status === s)} style={chip(STC[s])}><span style={{ width: 7, height: 7, borderRadius: 2, background: STC[s] }}/>{s} {st[s]}</button>)}</div>
            </div>
          </div>
        )}
        {tab === 'params' && (
          <div style={secStyle}>
            <div style={insLabel}>DOMAIN PARAMETERS</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {params.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>No parameters. Add config that governs the whole domain.</div>}
              {params.map((p, i) => (
                <div key={i} style={{ display: 'flex', gap: 6 }}>
                  <input value={p.k} onChange={e => setParam(i, 'k', e.target.value)} style={{ ...insInput(true), flex: 1, fontSize: 11.5 }}/>
                  <input value={p.v} onChange={e => setParam(i, 'v', e.target.value)} style={{ ...insInput(true), flex: 1.3, fontSize: 11.5 }}/>
                  <button onClick={() => delParam(i)} style={{ border: `1px solid ${HB.line}`, background: HB.paper2, color: HB.red, borderRadius: 6, width: 30, cursor: 'pointer' }}>✕</button>
                </div>
              ))}
            </div>
            <HBtn small onClick={addParam} style={{ marginTop: 10 }}><CKIcon name="plus" size={12}/>Add parameter</HBtn>
            <div style={{ marginTop: 16 }}><div style={insLabel}>EVIDENCE · FEDERATION</div><input value={d.evidence_ref || ''} onChange={e => patchDomain(domKey, { evidence_ref: e.target.value })} placeholder="dir:app/web_ui/… · doc:…" style={insInput(true)}/></div>
          </div>
        )}
        {tab === 'links' && (
          <div style={secStyle}>
            <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginBottom: 12, lineHeight: 1.5 }}>The domain's interface — ports reflected up from its {members.length} member nodes' cross-domain wiring.</div>
            <div style={{ ...insLabel, color: HB.blue }}>▸ INBOUND PORTS · fed by ({Object.keys(inbound).length})</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 16 }}>
              {Object.entries(inbound).sort((a, b) => b[1] - a[1]).map(([k, ct]) => { const dd = M.domains.find(x => x.key === k); return (
                <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '7px 10px', borderRadius: 7, border: `1px solid ${HB.lineSoft}`, background: HB.paper2 }}>
                  <span style={{ width: 9, height: 9, borderRadius: '50%', background: dd ? dd.col : HB.inkMute, flexShrink: 0 }}/>
                  <span style={{ fontSize: 12.5 }}>{dd ? dd.title : k}</span>
                  <span style={{ marginLeft: 'auto', fontFamily: HB.mono, fontSize: 11, color: HB.blue }}>{ct} →</span>
                </div>
              ); })}
              {!Object.keys(inbound).length && <Empty>Nothing feeds this domain.</Empty>}
            </div>
            <div style={{ ...insLabel, color: HB.green }}>OUTBOUND PORTS ▸ · drives ({Object.keys(outbound).length})</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {Object.entries(outbound).sort((a, b) => b[1] - a[1]).map(([k, ct]) => { const dd = M.domains.find(x => x.key === k); return (
                <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '7px 10px', borderRadius: 7, border: `1px solid ${HB.lineSoft}`, background: HB.paper2 }}>
                  <span style={{ width: 9, height: 9, borderRadius: '50%', background: dd ? dd.col : HB.inkMute, flexShrink: 0 }}/>
                  <span style={{ fontSize: 12.5 }}>{dd ? dd.title : k}</span>
                  <span style={{ marginLeft: 'auto', fontFamily: HB.mono, fontSize: 11, color: HB.green }}>→ {ct}</span>
                </div>
              ); })}
              {!Object.keys(outbound).length && <Empty>Drives no other domain.</Empty>}
            </div>
            {!ifaceCount && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', color: HB.inkMute, fontSize: 13, marginTop: 10 }}>Self-contained — no external ports.</div>}
          </div>
        )}
      </div>
    </div>
  );
}

/* ════ BULK — multiple selected ════ */
function BulkPanel({ sel, selNodes, M, DB, STATUS, bulkStatus, bulkDomain, bulkAgent, onGroup, onDelete, clearSel, domName }) {
  const byDom = {}; selNodes.forEach(n => byDom[n.dom] = (byDom[n.dom] || 0) + 1);
  return (
    <div>
      <div style={{ ...secStyle, borderBottom: `1px solid ${HB.line}`, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', background: HB.accent, color: (window.AH && window.AH.onFill) || '#180f08', flexShrink: 0, fontFamily: HB.serif, fontSize: 16 }}>{sel.size}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: HB.mono, fontSize: 8.5, color: HB.accent, letterSpacing: '0.2em' }}>BULK · MACRO CONTROL</div>
          <div style={{ fontFamily: HB.serif, fontSize: 21, letterSpacing: '-0.01em' }}>{sel.size} nodes selected</div>
        </div>
        <HIconBtn name="x" onClick={clearSel}/>
      </div>

      <div style={secStyle}>
        <div style={insLabel}>SET STATUS · ALL</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
          {STATUS.map(s => <button key={s} onClick={() => bulkStatus(s)} style={chip(STC[s])}><span style={{ width: 7, height: 7, borderRadius: 2, background: STC[s] }}/>{s}</button>)}
        </div>
      </div>

      <div style={secStyle}>
        <div style={insLabel}>MOVE TO DOMAIN · ALL</div>
        <select onChange={e => e.target.value && bulkDomain(e.target.value)} value="" style={insInput()}>
          <option value="">choose domain…</option>
          {M.domains.map(d => <option key={d.key} value={d.key}>{d.title}</option>)}
        </select>
      </div>

      <div style={secStyle}>
        <div style={insLabel}>ASSIGN AGENT · ALL · WIRED TO FOUNDER BRAIN</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {DB.agents.map(a => (
            <button key={a.id} onClick={() => bulkAgent(a.id)} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textAlign: 'left', border: `1px solid ${HB.line}`, background: HB.paper2, color: HB.ink }}>
              <span style={{ width: 22, height: 22, borderRadius: 6, display: 'grid', placeItems: 'center', background: HB.accentSoft, color: HB.accent, flexShrink: 0 }}><CKIcon name="agent" size={12}/></span>
              <span style={{ fontSize: 12.5 }}>{a.name}</span>
            </button>
          ))}
        </div>
      </div>

      <div style={secStyle}>
        <div style={insLabel}>SELECTION SPANS</div>
        {Object.entries(byDom).map(([d, n]) => <div key={d} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: HB.mono, fontSize: 11, color: HB.inkSoft, padding: '3px 0' }}><span>{domName(d)}</span><span>{n}</span></div>)}
      </div>

      <div style={{ padding: 16, display: 'flex', gap: 8 }}>
        <HBtn primary onClick={onGroup} style={{ flex: 1, justifyContent: 'center' }}><CKIcon name="grid" size={13}/>Group</HBtn>
        <HBtn danger onClick={onDelete} style={{ flex: 1, justifyContent: 'center' }}><CKIcon name="trash" size={13}/>Delete all</HBtn>
      </div>
    </div>
  );
}

/* ════ STEM editor — the node's own parameters, fields, triggers & ports ════ */
/* This is the stem design: the node is grown & controlled by the user. Every
   param is a live widget; any param promotes to a wireable input port; fields &
   triggers are added in place. Mirrors stem-sandbox.jsx NodeBody. */
const ptypeOf = (p) => p.t || ((p.v === true || p.v === false || p.v === 'true' || p.v === 'false') ? 'boolean' : (String(p.v).trim() !== '' && !isNaN(parseFloat(p.v)) && isFinite(+p.v) ? 'number' : (/^#[0-9a-fA-F]{3,8}$/.test(String(p.v)) ? 'color' : 'string')));
const PARAM_WIRE = { string: 'string', number: 'number', boolean: 'boolean', color: 'string', trigger: 'exec' };
const ptypeCol = (t) => (window.typeColOf ? window.typeColOf(PARAM_WIRE[t] || 'any') : HB.inkMute);

function StemParams({ node, patchNode }) {
  const params = node.params || [];
  const ports = node.ports || { ins: [], outs: [] };
  const promoted = new Set((ports.ins || []).map(x => x.id));
  const setParam = (i, patch) => {
    patchNode(node.id, { params: params.map((p, j) => j === i ? { ...p, ...patch } : p) });
    // A live-graph parameter commits through the governed write; the
    // local patch above keeps the panel instant either way.
    const held = params[i];
    if (patch.v !== undefined && held && held.rel && window.ARCHHUB_SET_PROP) {
      window.ARCHHUB_SET_PROP(held.rel, String(patch.v)).catch(() => {});
    }
  };
  const delParam = (i) => { const p = params[i]; patchNode(node.id, { params: params.filter((_, j) => j !== i), ports: { ...ports, ins: (ports.ins || []).filter(x => x.id !== p.k) } }); };
  const addParam = (t) => {
    const n = params.length + 1;
    const base = t === 'trigger' ? { k: 'on', v: 'on save', t: 'trigger' }
      : t === 'boolean' ? { k: 'flag' + n, v: false, t: 'boolean' }
      : t === 'number' ? { k: 'value' + n, v: 0, t: 'number' }
      : t === 'color' ? { k: 'color' + n, v: '#d97757', t: 'color' }
      : { k: 'field' + n, v: '', t: 'string' };
    const patch = { params: [...params, base] };
    if (t === 'trigger') patch.ports = { ...ports, ins: [...(ports.ins || []), { id: 'exec', t: 'exec' }] };
    patchNode(node.id, patch);
  };
  const promote = (p) => { const has = promoted.has(p.k); const ins = has ? (ports.ins || []).filter(x => x.id !== p.k) : [...(ports.ins || []), { id: p.k, t: PARAM_WIRE[ptypeOf(p)] || 'any' }]; patchNode(node.id, { ports: { ...ports, ins } }); };

  const wrap = { display: 'flex', flexDirection: 'column', gap: 7 };
  const card = (on) => ({ border: `1px solid ${on ? HB.accent : HB.line}`, borderRadius: 8, padding: '8px 9px', background: on ? HB.accentSoft : HB.paper2, display: 'flex', flexDirection: 'column', gap: 7 });
  const keyInput = { flex: 1, minWidth: 0, border: 'none', background: 'transparent', color: HB.ink, fontFamily: HB.mono, fontSize: 11.5, outline: 'none', padding: 0 };
  const fieldStyle = { flex: 1, padding: '5px 8px', background: HB.card, border: `1px solid ${HB.line}`, borderRadius: 6, color: HB.ink, fontFamily: HB.mono, fontSize: 11.5, outline: 'none' };
  const tag = (t) => ({ fontFamily: HB.mono, fontSize: 8.5, color: ptypeCol(t), padding: '1px 6px', borderRadius: 999, border: `1px solid ${ptypeCol(t)}`, flexShrink: 0, textTransform: 'lowercase' });
  const promoteBtn = (on) => ({ width: 16, height: 16, flexShrink: 0, borderRadius: on ? 3 : '50%', cursor: 'pointer', background: on ? HB.accent : 'transparent', border: `1.5px solid ${on ? HB.accent : HB.inkMute}`, color: on ? '#fff' : HB.inkMute, fontSize: 9, lineHeight: 1, padding: 0, display: 'grid', placeItems: 'center' });
  const addBtn = { display: 'inline-flex', alignItems: 'center', gap: 3, padding: '5px 9px', borderRadius: 6, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10, border: `1px dashed ${HB.line}`, background: HB.card, color: HB.inkSoft };

  const widget = (p, i, t) => {
    if (t === 'boolean') { const on = p.v === true || p.v === 'true'; return (
      <button onClick={() => setParam(i, { v: !on })} style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 0, cursor: 'pointer', padding: 0 }}>
        <span style={{ width: 30, height: 17, borderRadius: 99, background: on ? HB.accent : HB.line, position: 'relative', flexShrink: 0 }}><span style={{ position: 'absolute', top: 2, left: on ? 15 : 2, width: 13, height: 13, borderRadius: '50%', background: '#fff', transition: 'left .15s' }}/></span>
        <span style={{ fontFamily: HB.mono, fontSize: 11, color: HB.ink }}>{String(on)}</span>
      </button>
    ); }
    if (t === 'number') return <input type="number" value={p.v} onChange={e => setParam(i, { v: e.target.value })} style={fieldStyle}/>;
    if (t === 'color') return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input type="color" value={/^#[0-9a-fA-F]{6}$/.test(String(p.v)) ? p.v : '#d97757'} onChange={e => setParam(i, { v: e.target.value })} style={{ width: 22, height: 22, border: 0, background: 'none', padding: 0, cursor: 'pointer', borderRadius: 5 }}/>
        <input value={p.v} onChange={e => setParam(i, { v: e.target.value })} style={fieldStyle}/>
      </div>
    );
    if (t === 'trigger') return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.amber }}>▷ fires</span>
        <input value={p.v} onChange={e => setParam(i, { v: e.target.value })} style={fieldStyle} placeholder="on save · cron · webhook…"/>
      </div>
    );
    return <input value={p.v} onChange={e => setParam(i, { v: e.target.value })} style={fieldStyle} placeholder="value…"/>;
  };

  return (
    <div style={wrap}>
      {params.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 12.5, color: HB.inkMute }}>No parameters yet — add a field, toggle, or trigger below to grow this node.</div>}
      {params.map((p, i) => { const t = ptypeOf(p); const on = promoted.has(p.k); return (
        <div key={i} style={card(on)}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <button onClick={() => promote(p)} title={on ? 'demote to dial' : 'promote to wireable input port'} style={promoteBtn(on)}>◇</button>
            <input value={p.k} onChange={e => setParam(i, { k: e.target.value })} style={keyInput}/>
            <span style={tag(t)}>{t}</span>
            <button onClick={() => delParam(i)} style={{ border: 'none', background: 'transparent', color: HB.inkMute, cursor: 'pointer', padding: 0, display: 'grid', placeItems: 'center' }}><CKIcon name="x" size={12}/></button>
          </div>
          {widget(p, i, t)}
          {on && <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.accent }}>▶ exposed as input port · wireable on the map</div>}
        </div>
      ); })}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
        {[['field', '＋ Field'], ['number', '＋ Number'], ['boolean', '＋ Toggle'], ['color', '＋ Color'], ['trigger', '＋ Trigger']].map(([t, l]) => <button key={t} onClick={() => addParam(t)} style={addBtn}>{l}</button>)}
      </div>
      {(ports.ins || []).length > 0 && <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, paddingTop: 2 }}><b style={{ color: HB.accent }}>{ports.ins.length}</b> port{ports.ins.length > 1 ? 's' : ''} promoted — now wireable knobs on the node</div>}
    </div>
  );
}

/* ════ MICRO — single node inspector ════ */
function NodeInspector({ M, node, DB, assign, STATUS, CATS, patchNode, delNode, toggleAgent, onClose, openRoom, focusNode, domName, onRun, onVariant, onWatch }) {
  const [tab, setTab] = React.useState('control');
  const RT = window.RT;
  const outs = M.wires.filter(w => w.a === node.id);
  const ins = M.wires.filter(w => w.b === node.id);
  const sigSelf = window.sigOf ? window.sigOf(node) : 'value';
  const dom = M.domains.find(d => d.key === node.dom);
  const myAgents = assign[node.id] || [];
  const pipe = (window.nodePipeline ? window.nodePipeline(node) : (node.pipeline || []));
  const setPipe = (p) => patchNode(node.id, { pipeline: p });
  const setStage = (i, k, v) => setPipe(pipe.map((s, j) => j === i ? { ...s, [k]: v } : s));
  const addStage = () => setPipe([...pipe, { id: node.id + '_s' + Date.now().toString(36), t: 'new stage', role: 'process', status: 'vision' }]);
  const delStage = (i) => setPipe(pipe.filter((_, j) => j !== i));

  return (
    <div>
      <div style={{ position: 'sticky', top: 0, zIndex: 2, background: HB.card, borderBottom: `1px solid ${HB.line}`, padding: '14px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span style={{ width: 30, height: 30, borderRadius: 7, display: 'grid', placeItems: 'center', background: catCol(node.cat) + '1e', color: catCol(node.cat), flexShrink: 0, marginTop: 2 }}><CKIcon name="bolt" size={15}/></span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: HB.mono, fontSize: 8.5, color: dom ? dom.col : HB.accent, letterSpacing: '0.14em' }}>{(node.cat || '').toUpperCase()} · {dom ? dom.title : node.dom}</div>
            <input value={node.title} onChange={e => patchNode(node.id, { title: e.target.value })} style={{ width: '100%', border: 'none', background: 'transparent', fontFamily: HB.serif, fontSize: 21, letterSpacing: '-0.01em', color: HB.ink, outline: 'none', padding: 0, marginTop: 2 }}/>
          </div>
          <HIconBtn name="x" onClick={onClose}/>
        </div>
        {/* run bar — the node is executable, like in the app */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 11 }}>
          <button onClick={() => onRun && onRun(node.id)} disabled={RT && RT.rtState(node) === 'running'} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, padding: '8px 16px', borderRadius: 8, border: 'none', background: HB.accent, color: (window.AH && window.AH.onFill) || '#180f08', cursor: 'pointer', fontFamily: HB.mono, fontSize: 12, fontWeight: 700 }}>
            {RT && RT.rtState(node) === 'running' ? '◴ running…' : '▸ Run'}
          </button>
          {RT && <RT.RTChip state={RT.rtState(node)}/>}
          <button onClick={() => onWatch && onWatch(node.id)} title="Drop a watcher node wired to this — shows its live result on the map" style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 5, padding: '7px 11px', borderRadius: 8, border: `1px solid ${HB.line}`, background: HB.paper2, color: HB.inkSoft, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5 }}>◉ Watch</button>
        </div>
        <div style={{ display: 'flex', gap: 4, marginTop: 11 }}>
          {[['control', 'Control'], ['pipeline', `Pipeline ${pipe.length}`], ['runs', `Runs ${RT ? RT.rtRuns(node).length : 0}`], ['wires', `Ports ${outs.length + ins.length}`]].map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)} style={{ flex: 1, padding: '6px 0', borderRadius: 7, cursor: 'pointer', fontFamily: HB.mono, fontSize: 9.5, border: `1px solid ${tab === k ? HB.accent : HB.line}`, background: tab === k ? HB.accentSoft : 'transparent', color: tab === k ? HB.accentHi : HB.inkSoft }}>{l}</button>
          ))}
        </div>
      </div>

      <div style={{ padding: 16 }}>
        {tab === 'control' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div><div style={insLabel}>INTENT</div><textarea value={node.sub} onChange={e => patchNode(node.id, { sub: e.target.value })} rows={2} style={insInput()}/></div>
            <div>
              <div style={{ ...insLabel, display: 'flex', alignItems: 'center', gap: 6 }}>PARAMETERS · FIELDS · TRIGGERS<span style={{ fontFamily: HB.mono, fontSize: 8, color: HB.accent, letterSpacing: '0.04em', textTransform: 'none' }}>— the stem: grow & wire this node</span></div>
              <StemParams node={node} patchNode={patchNode}/>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div><div style={insLabel}>DOMAIN</div><select value={node.dom} onChange={e => patchNode(node.id, { dom: e.target.value })} style={insInput()}>{M.domains.map(d => <option key={d.key} value={d.key}>{d.title}</option>)}</select></div>
              <div><div style={insLabel}>CATEGORY</div><select value={node.cat} onChange={e => patchNode(node.id, { cat: e.target.value })} style={insInput()}>{CATS.map(c => <option key={c}>{c}</option>)}</select></div>
            </div>
            <div>
              <div style={insLabel}>STATUS · THE LIVE ROADMAP</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {STATUS.map(s => <button key={s} onClick={() => patchNode(node.id, { status: s })} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 999, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, textTransform: 'capitalize', border: `1px solid ${node.status === s ? STC[s] : HB.line}`, background: node.status === s ? STC[s] + '20' : 'transparent', color: node.status === s ? STC[s] : HB.inkSoft }}><span style={{ width: 7, height: 7, borderRadius: 2, background: STC[s] }}/>{s}</button>)}
              </div>
            </div>
            <div>
              <div style={insLabel}>OWNED BY AGENTS · WIRED TO FOUNDER BRAIN</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {DB.agents.map(a => { const on = myAgents.includes(a.id); return (
                  <button key={a.id} onClick={() => toggleAgent(node.id, a.id)} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textAlign: 'left', border: `1px solid ${on ? HB.accent : HB.line}`, background: on ? HB.accentSoft : HB.paper2 }}>
                    <span style={{ position: 'relative', flexShrink: 0, display: 'grid', placeItems: 'center' }}><HAvatar name={a.name} size={26}/>{on && <span style={{ position: 'absolute', inset: -2, borderRadius: '50%', border: `2px solid ${HB.accent}` }}/>}</span>
                    <span style={{ flex: 1, minWidth: 0 }}><span style={{ fontSize: 12.5, fontWeight: 500, display: 'block' }}>{a.name}</span><span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{(DB.models.find(m => m.id === a.model) || {}).name}</span></span>
                    {on ? <span style={{ color: HB.accent }}><CKIcon name="check" size={15}/></span> : <span style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, letterSpacing: '0.1em' }}>ASSIGN</span>}
                  </button>
                ); })}
              </div>
            </div>
            <HBtn danger small onClick={() => delNode(node.id)} style={{ alignSelf: 'flex-start' }}><CKIcon name="trash" size={12}/>Delete node</HBtn>
          </div>
        )}
        {tab === 'pipeline' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={insLabel}>INTERNAL PIPELINE · THIS NODE IS A MICRO-DOMAIN</div>
            <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginBottom: 2 }}>double-click the node on the map to expand its pipeline in place</div>
            {pipe.map((s, i) => { const col = { in: HB.blue, process: HB.purple, out: HB.green }[s.role] || HB.purple; return (
              <div key={s.id || i} style={{ display: 'flex', alignItems: 'center', gap: 7, border: `1px solid ${HB.line}`, borderRadius: 8, padding: '7px 9px', background: HB.paper2 }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: STC[s.status] || col, flexShrink: 0 }}/>
                <input value={s.t} onChange={e => setStage(i, 't', e.target.value)} style={{ flex: 1, border: 'none', background: 'transparent', color: HB.ink, fontSize: 12, outline: 'none', fontFamily: HB.sans }}/>
                <select value={s.role} onChange={e => setStage(i, 'role', e.target.value)} style={{ border: `1px solid ${HB.line}`, background: HB.card, color: col, borderRadius: 5, fontFamily: HB.mono, fontSize: 9.5, padding: '2px 4px' }}>{['in', 'process', 'out'].map(r => <option key={r}>{r}</option>)}</select>
                <button onClick={() => delStage(i)} style={{ border: 'none', background: 'transparent', color: HB.inkMute, cursor: 'pointer' }}><CKIcon name="x" size={12}/></button>
              </div>
            ); })}
            <HBtn small onClick={addStage} style={{ alignSelf: 'flex-start', marginTop: 4 }}><CKIcon name="plus" size={12}/>Add stage</HBtn>
          </div>
        )}
        {tab === 'runs' && RT && (
          <RT.RunsBody node={node} onRun={() => onRun && onRun(node.id)} onVariant={(r) => onVariant && onVariant(node.id, r)}/>
        )}
        {tab === 'wires' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 11px', borderRadius: 8, background: HB.paper2, border: `1px solid ${HB.lineSoft}` }}>
              <span style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, letterSpacing: '0.1em' }}>EMITS</span>
              <span style={{ fontFamily: HB.mono, fontSize: 10.5, color: catCol(node.cat), padding: '2px 8px', borderRadius: 999, border: `1px solid ${catCol(node.cat)}`, textTransform: 'lowercase' }}>{sigSelf}</span>
              <span style={{ marginLeft: 'auto', fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{ins.length} in · {outs.length} out</span>
            </div>
            <div><div style={{ ...insLabel, color: HB.green }}>OUT PORTS → ({outs.length})</div>{outs.length === 0 && <Empty>Drives nothing yet.</Empty>}{outs.map((w, i) => { const t = M.nodes.find(n => n.id === w.b); return <WireRow key={i} dir="→" node={t} why={w.why} sig={sigSelf} sigCol={catCol(node.cat)} onClick={() => t && focusNode(t.id)}/>; })}</div>
            <div><div style={{ ...insLabel, color: HB.blue }}>IN PORTS ← ({ins.length})</div>{ins.length === 0 && <Empty>Nothing feeds it.</Empty>}{ins.map((w, i) => { const s = M.nodes.find(n => n.id === w.a); const sg = window.sigOf ? window.sigOf(s) : 'value'; return <WireRow key={i} dir="←" node={s} why={w.why} sig={sg} sigCol={s ? catCol(s.cat) : HB.inkMute} onClick={() => s && focusNode(s.id)}/>; })}</div>
          </div>
        )}
        {tab === 'evidence' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div><div style={insLabel}>EVIDENCE · THE FEDERATION LINK</div><input value={node.evidence_ref || ''} onChange={e => patchNode(node.id, { evidence_ref: e.target.value })} placeholder="file:path · test:id · brain:…" style={insInput(true)}/></div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <Stat label="AUTHORITY" value={node.authority_source || 'vision'}/><Stat label="VERIFIED" value={node.last_verified || 'never'}/>
              <Stat label="BIM PHASE" value={node.bim_phase || '—'}/><Stat label="STANDARD" value={node.standard || '—'}/>
            </div>
            {(node.params || []).length > 0 && <div><div style={insLabel}>PARAMETERS</div><div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>{node.params.map((p, i) => <div key={i} style={{ display: 'flex', gap: 8, fontFamily: HB.mono, fontSize: 11, padding: '6px 9px', borderRadius: 6, background: HB.paper2, border: `1px solid ${HB.lineSoft}` }}><span style={{ color: HB.inkMute }}>{p.k}</span><span style={{ marginLeft: 'auto', color: HB.ink }}>{p.v}</span></div>)}</div></div>}
          </div>
        )}
      </div>
    </div>
  );
}

const WireRow = ({ dir, node, why, sig, sigCol, onClick }) => <div className="hb-rowh" onClick={onClick} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 9px', borderRadius: 7, cursor: 'pointer', marginBottom: 2 }}><span style={{ color: dir === '→' ? HB.green : HB.blue, fontFamily: HB.mono, fontSize: 13, marginTop: 1 }}>{dir}</span><div style={{ flex: 1, minWidth: 0 }}><div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span style={{ fontSize: 12.5, fontWeight: 500 }}>{node ? node.title : '—'}</span>{sig && <span style={{ fontFamily: HB.mono, fontSize: 8.5, color: sigCol || HB.inkMute, padding: '1px 6px', borderRadius: 999, border: `1px solid ${sigCol || HB.line}`, flexShrink: 0 }}>{sig}</span>}</div>{why && <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginTop: 2, lineHeight: 1.4 }}>{why}</div>}</div>{node && <HPill k={node.status}>{node.status}</HPill>}</div>;
const Stat = ({ label, value }) => <div style={{ padding: '8px 10px', borderRadius: 7, background: HB.paper2, border: `1px solid ${HB.lineSoft}` }}><div style={{ fontFamily: HB.mono, fontSize: 8, color: HB.inkMute, letterSpacing: '0.12em' }}>{label}</div><div style={{ fontFamily: HB.mono, fontSize: 11.5, color: HB.ink, marginTop: 3, wordBreak: 'break-word' }}>{value}</div></div>;
const Empty = ({ children }) => <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>{children}</div>;
const chip = (col) => ({ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 999, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, textTransform: 'capitalize', border: `1px solid ${HB.line}`, background: 'transparent', color: HB.inkSoft });
const miniAct = (col, fill) => ({ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '5px 9px', borderRadius: 6, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10, border: `1px solid ${col}`, background: fill ? col : 'transparent', color: fill ? '#fff' : HB.inkSoft });

/* ════ name modal (group / domain) ════ */
function NameModal({ title, placeholder, colors, onSave, onClose }) {
  const [name, setName] = React.useState('');
  const [col, setCol] = React.useState(colors ? colors[0] : null);
  const ref = React.useRef(null);
  React.useEffect(() => { ref.current && ref.current.focus(); }, []);
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 90, background: 'rgba(0,0,0,0.32)', display: 'grid', placeItems: 'center', animation: 'hbFade .14s' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 400, background: HB.card, border: `1px solid ${HB.line}`, borderRadius: 14, padding: 20, boxShadow: '0 30px 80px rgba(0,0,0,.3)' }}>
        <div style={{ fontFamily: HB.serif, fontSize: 22, letterSpacing: '-0.01em', marginBottom: 14 }}>{title}</div>
        <input ref={ref} value={name} onChange={e => setName(e.target.value)} onKeyDown={e => e.key === 'Enter' && name.trim() && onSave(name.trim(), col)} placeholder={placeholder} style={{ ...insInput(), fontSize: 14, padding: '10px 12px' }}/>
        {colors && <div style={{ display: 'flex', gap: 7, marginTop: 12 }}>{colors.map(c => <button key={c} onClick={() => setCol(c)} style={{ width: 26, height: 26, borderRadius: 7, background: c, border: col === c ? `2px solid ${HB.ink}` : '2px solid transparent', cursor: 'pointer' }}/>)}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
          <HBtn ghost onClick={onClose}>Cancel</HBtn>
          <HBtn primary onClick={() => name.trim() && onSave(name.trim(), col)}><CKIcon name="check" size={13}/>Create</HBtn>
        </div>
      </div>
    </div>
  );
}

/* ════ FIELD — a super grand node: a group of domains ════ */
function FieldPanel({ M, fieldId, patchField, onUngroup, onEnterDomain, onClose }) {
  const f = (M.fields || []).find(x => x.id === fieldId) || {};
  const doms = M.domains.filter(d => (f.domKeys || []).includes(d.key));
  const nodeCount = M.nodes.filter(n => (f.domKeys || []).includes(n.dom)).length;
  return (
    <div>
      <div style={{ position: 'sticky', top: 0, zIndex: 2, background: HB.card, borderBottom: `1px solid ${HB.line}`, padding: '14px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span style={{ width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', background: (f.col || HB.blue) + '22', color: f.col || HB.blue, flexShrink: 0, marginTop: 2, fontSize: 16 }}>⬡</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: HB.mono, fontSize: 8.5, color: f.col || HB.blue, letterSpacing: '0.16em' }}>FIELD · SUPER GRAND NODE · {doms.length} DOMAINS</div>
            <input value={f.title || ''} onChange={e => patchField(fieldId, { title: e.target.value })} style={{ width: '100%', border: 'none', background: 'transparent', fontFamily: HB.serif, fontSize: 23, letterSpacing: '-0.02em', color: HB.ink, outline: 'none', padding: 0, marginTop: 2 }}/>
          </div>
          <HIconBtn name="x" onClick={onClose}/>
        </div>
        <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginTop: 8 }}>{doms.length} grand nodes · {nodeCount} capabilities inside</div>
      </div>
      <div style={secStyle}>
        <div style={insLabel}>MEMBER DOMAINS</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {doms.map(d => (
            <button key={d.key} onClick={() => onEnterDomain(d.key)} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textAlign: 'left', border: `1px solid ${HB.line}`, background: HB.paper2, color: HB.ink }}>
              <span style={{ width: 9, height: 9, borderRadius: 3, background: d.col, flexShrink: 0 }}/>
              <span style={{ flex: 1, fontSize: 12.5 }}>{d.title}</span>
              <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.inkMute }}>{M.nodes.filter(n => n.dom === d.key).length}</span>
            </button>
          ))}
        </div>
      </div>
      <div style={{ padding: 16 }}>
        <HBtn onClick={() => onUngroup(fieldId)} style={{ width: '100%', justifyContent: 'center' }}><CKIcon name="grid" size={13}/>Ungroup field — keep domains</HBtn>
      </div>
    </div>
  );
}

/* ════ MULTI — a mixed selection of domains (and loose nodes), ready to group up ════ */
function MultiPanel({ selDomains, selNodes, M, onGroupField, clearSel }) {
  const doms = M.domains.filter(d => selDomains.includes(d.key));
  const total = selDomains.length + selNodes.size;
  return (
    <div>
      <div style={{ ...secStyle, borderBottom: `1px solid ${HB.line}`, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', background: HB.blue, color: '#fff', flexShrink: 0, fontFamily: HB.serif, fontSize: 16 }}>{total}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: HB.mono, fontSize: 8.5, color: HB.blue, letterSpacing: '0.2em' }}>MIXED SELECTION</div>
          <div style={{ fontFamily: HB.serif, fontSize: 21, letterSpacing: '-0.01em' }}>{selDomains.length} domain{selDomains.length !== 1 ? 's' : ''}{selNodes.size ? ` + ${selNodes.size} node${selNodes.size !== 1 ? 's' : ''}` : ''}</div>
        </div>
        <HIconBtn name="x" onClick={clearSel}/>
      </div>
      <div style={secStyle}>
        <div style={insLabel}>SELECTED DOMAINS</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {doms.map(d => <div key={d.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: HB.mono, fontSize: 11.5, color: HB.inkSoft, padding: '3px 0' }}><span style={{ width: 8, height: 8, borderRadius: 2, background: d.col }}/>{d.title}</div>)}
          {selNodes.size > 0 && <div style={{ fontFamily: HB.mono, fontSize: 10.5, color: HB.inkMute, marginTop: 4 }}>+ {selNodes.size} loose node{selNodes.size !== 1 ? 's' : ''} → wrapped into a grand node</div>}
        </div>
      </div>
      <div style={{ padding: 16 }}>
        <HBtn primary onClick={onGroupField} style={{ width: '100%', justifyContent: 'center' }}><CKIcon name="grid" size={13}/>Group</HBtn>
        <div style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, marginTop: 9, textAlign: 'center', lineHeight: 1.5 }}>Grouping makes one node out of what you picked. The same node primitive, one tier up.</div>
      </div>
    </div>
  );
}


// MULTI-FIELD — 2+ fields selected. This is the rung that makes grouping unbounded: fields
// group into a bigger field, and that field can be grouped again, with no cap.
function MultiFieldPanel({ M, ids, onGroup, clearSel }) {
  const all = M.fields || [];
  const byId = {}; all.forEach(f => byId[f.id] = f);
  const depthOf = (id, seen) => { const f = byId[id]; if (!f) return 0; const g = seen || new Set(); if (g.has(id)) return 0; g.add(id); const k = (f.fieldIds || []).map(x => depthOf(x, g)); return 1 + (k.length ? Math.max(...k) : 0); };
  const picked = ids.map(id => byId[id]).filter(Boolean);
  const nextTier = 1 + Math.max(...picked.map(f => depthOf(f.id)));
  const SUP = ['', '', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
  const sup = nextTier > 1 ? (SUP[nextTier] != null ? SUP[nextTier] : '^' + nextTier) : '';
  return (
    <div>
      <div style={secStyle}>
        <div style={insLabel}>MULTI SELECTION</div>
        <div style={{ fontFamily: HB.serif, fontSize: 21, color: HB.ink, marginTop: 4 }}>{picked.length} fields</div>
        <div style={{ fontFamily: HB.mono, fontSize: 10.5, color: HB.inkSoft, marginTop: 6, lineHeight: 1.6 }}>
          Group these into one field a tier up. Depth is unbounded — the result can be grouped again.
        </div>
      </div>
      <div style={secStyle}>
        <div style={insLabel}>MEMBERS</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 8 }}>
          {picked.map(f => (
            <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 9px', borderRadius: 6, background: HB.paper2 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: f.col || HB.blue, flexShrink: 0 }}/>
              <span style={{ flex: 1, fontFamily: HB.sans, fontSize: 12, color: HB.ink }}>{f.title}</span>
              <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>tier {depthOf(f.id)} · {(f.domKeys || []).length + (f.fieldIds || []).length}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={secStyle}>
        <HBtn primary onClick={onGroup} style={{ width: '100%', justifyContent: 'center' }}>⊞ Group{sup}</HBtn>
        <HBtn onClick={clearSel} style={{ width: '100%', justifyContent: 'center', marginTop: 8 }}>Clear</HBtn>
      </div>
    </div>
  );
}

function WirePanel({ M, w, onDelete, onGoto, onClose }) {
  const nodeById = {}; M.nodes.forEach(n => nodeById[n.id] = n);
  const domById = {}; M.domains.forEach(d => domById[d.key] = d);
  const domOfN = {}; M.nodes.forEach(n => domOfN[n.id] = n.dom);
  // every real wire this visible line stands for
  const members = M.wires.filter(x => {
    const da = domOfN[x.a] || x.a, db = domOfN[x.b] || x.b;
    return w.cross
      ? (da === w.da && db === w.db) || (da === w.db && db === w.da)
      : (x.a === w.a && x.b === w.b) || (x.a === w.b && x.b === w.a);
  });
  const A = domById[w.da], B = domById[w.db];
  const sig = (id) => { const n = nodeById[id]; return n ? (window.sigOf ? window.sigOf(n) : n.cat) : '—'; };
  return (
    <div>
      <div style={secStyle}>
        <div style={insLabel}>{w.cross ? 'CROSS-DOMAIN WIRE' : 'WIRE'}</div>
        <div style={{ fontFamily: HB.serif, fontSize: 20, lineHeight: 1.15, marginTop: 4 }}>
          {(A ? A.title : w.da)} <span style={{ color: HB.accent }}>→</span> {(B ? B.title : w.db)}
        </div>
        <div style={{ fontFamily: HB.mono, fontSize: 11, color: HB.inkSoft, marginTop: 6 }}>
          {members.length} underlying wire{members.length === 1 ? '' : 's'}
          {w.cross ? ' · rolled up into one line' : ''}
        </div>
      </div>
      <div style={secStyle}>
        <div style={insLabel}>WHAT IS WIRED TO WHAT</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1, marginTop: 8 }}>
          {members.slice(0, 24).map((x, i) => {
            const a = nodeById[x.a], bb = nodeById[x.b];
            return (
              <div key={i} style={{ padding: '7px 8px', borderRadius: 5, background: i % 2 ? 'transparent' : HB.paper2 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: HB.sans, fontSize: 12 }}>
                  <button onClick={() => a && onGoto(a.id)} style={{ border: 0, background: 'transparent', padding: 0, color: HB.ink, cursor: a ? 'pointer' : 'default', fontSize: 12, textAlign: 'left' }}>{a ? a.title : x.a}</button>
                  <span style={{ color: HB.accent, flexShrink: 0 }}>→</span>
                  <button onClick={() => bb && onGoto(bb.id)} style={{ border: 0, background: 'transparent', padding: 0, color: HB.ink, cursor: bb ? 'pointer' : 'default', fontSize: 12, textAlign: 'left' }}>{bb ? bb.title : x.b}</button>
                </div>
                <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, marginTop: 2 }}>
                  {sig(x.a)} → {sig(x.b)}{x.why ? ' · ' + x.why : ''}
                </div>
              </div>
            );
          })}
          {members.length > 24 && <div style={{ fontFamily: HB.mono, fontSize: 10, color: HB.inkDim, padding: '6px 8px' }}>+{members.length - 24} more</div>}
        </div>
      </div>
      <div style={{ ...secStyle, borderBottom: 'none', display: 'flex', gap: 8 }}>
        <HBtn danger onClick={onDelete} style={{ flex: 1, justifyContent: 'center' }}>Remove {members.length > 1 ? 'all ' + members.length : 'wire'}</HBtn>
        <HBtn onClick={onClose} style={{ justifyContent: 'center' }}>Close</HBtn>
      </div>
    </div>
  );
}

Object.assign(window, { WirePanel, MultiFieldPanel, SystemPanel, DomainPanel, BulkPanel, FieldPanel, MultiPanel, NodeInspector, NameModal });
