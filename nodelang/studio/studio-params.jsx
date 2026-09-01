// studio-params.jsx — the node inspector: connections, typed parameters, actions.
//
// ─── WHAT THIS IS MODELLED ON ────────────────────────────────────────────────
// Houdini's Parameter Interface editor  — you BUILD a node's interface: drag a type from a
//   palette, set internal name vs label, group into FOLDERS which render as tabs. Internal
//   name is the contract (expressions and scripts reference it); the label is for humans and
//   is freely editable. Ranges are soft; typing past them is allowed to a hard limit.
// TouchDesigner parameter PAGES     — the same idea named plainly: a node's parameters live
//   on pages, and a long interface is a navigation problem, not a scrolling problem.
// Unreal Blueprint pins             — COLOUR encodes the data type, SHAPE encodes cardinality
//   (round = one value, diamond = a list). You read a connection's legality at a glance.
// Grasshopper                       — geometry-ish inputs are not typed into a box; they
//   arrive on a wire. A control for them would be a lie.
// Blender / Nuke                    — the number IS the control: drag to scrub, click to type.
//
// ─── WHAT THAT MEANS HERE ────────────────────────────────────────────────────
//  1. Every parameter has a TYPE, drawn as a socket: colour = type, shape = cardinality.
//  2. You can ADD parameters — pick a type, name it, choose whether it takes a wire. Scalar
//     types get an inline control; data types (elements, view, file…) can only be wired,
//     and the row says so instead of faking a text box.
//  3. Parameters live on PAGES. Tabs appear once there is more than one page; you can add
//     pages, which is how an interface stays readable past a dozen controls.
//  4. Label is editable, internal key is not — renaming the key would break the skill JSON
//     that references it. Both are always visible.
//  5. The number is the control (drag to scrub, shift for fine, click to type). Soft range on
//     the track, hard limit on typing, and the row says when you are past the usual range.
//  6. Three visibly different states: default, overridden-by-you (revert in one click),
//     driven-by-a-wire (control locked, source named).
//  7. Edits are pending until run, and survive switching nodes.

const PM = window.AH;

// ── TYPE REGISTRY ───────────────────────────────────────────────────────────
// One place that decides a type's colour, glyph, socket shape and whether it can be edited
// inline at all. The canvas wire colours are the same values, so a socket in this panel and
// a wire on the canvas are describing the same thing.
// PM_TYPES / PM_WIRE / Socket now come from param-types.jsx — ONE registry, read by the
// cockpit and by Studio alike. Local fallbacks keep this file renderable on its own.
const PM_TYPES = window.PM_TYPES;
const pmType = window.pmType;

const PM_WIRE = window.PM_WIRE;
const Socket = window.Socket;

const PM_OPTS = {
  scale:   ['1:20', '1:50', '1:100', '1:200'],
  align:   ['parallel', 'horizontal', 'vertical'],
  snap_to: ['outer face', 'inner face', 'centre line', 'core face'],
  key:     ['length', 'area', 'mark', 'level'],
  order:   ['desc', 'asc'],
  leader:  ['auto', 'always', 'never'],
};

const PM_META = {
  offset_mm: { label: 'Offset', unit: 'mm', hard: [0, 2000], help: 'Distance from the snapped face to the dimension line.' },
  scale:     { label: 'Scale', help: 'View scale the dimension text is sized for.' },
  align:     { label: 'Alignment', help: 'Direction the dimension line runs.' },
  snap_to:   { label: 'Snap to', help: 'Which face of the wall the witness line lands on.' },
  key:       { label: 'Sort by' }, order: { label: 'Order' }, body: { label: 'Text' },
  family:    { label: 'Tag family' }, leader: { label: 'Leader' },
};
const pmLabel = (spec, labels) => (labels && labels[spec.k]) || spec.label || (PM_META[spec.k] || {}).label || spec.k.replace(/_/g, ' ');

// ── A WIRE IS A NODE ────────────────────────────────────────────────────────
// Everything in the application is a node, so a connection is not a special case with its own
// bespoke panel — it is a node that happens to sit between two others. wireAsNode() adapts one
// into the ordinary node shape and the SAME inspector renders it: typed sockets, the same rows,
// pages, ⋯ menu, add-parameter, cook lifecycle.
//
// Its parameters are the ones a real graph engine gives a connection, not decoration:
//   lacing      — Dynamo's list lacing: how two lists of different length are paired.
//   tree        — Grasshopper's data-tree ops: flatten / graft / simplify.
//   condition   — a rule; the wire only carries when the expression holds.
//   on_fail     — what downstream receives when the rule blocks or the source errors.
//   throttle_ms — rate limit, for a wire fed by a live host.
//   enabled     — mute the connection without deleting it.
Object.assign(PM_OPTS, {
  lacing:  ['shortest', 'longest', 'cross product'],
  tree:    ['none', 'flatten', 'graft', 'simplify'],
  on_fail: ['block', 'pass last', 'pass empty'],
});
Object.assign(PM_META, {
  enabled:     { label: 'Enabled', help: 'Mute the connection without deleting it — downstream sees nothing.' },
  lacing:      { label: 'Lacing', help: 'How two lists of different length are paired: shortest stops at the short one, longest repeats the last item, cross product pairs every combination.' },
  tree:        { label: 'Data tree', help: 'Restructure on the way through — flatten to one list, graft each item into its own branch, simplify removes empty levels.' },
  condition:   { label: 'Condition', help: 'The wire only carries when this holds. Empty means always.' },
  on_fail:     { label: 'On block', help: 'What downstream receives when the condition blocks or the source errors.' },
  throttle_ms: { label: 'Throttle', unit: 'ms', hard: [0, 10000], help: 'Minimum gap between deliveries — for a wire fed by a live host.' },
});

function wireAsNode(w, i, nodes) {
  const from = nodes.find(x => x.id === w.from[0]), to = nodes.find(x => x.id === w.to[0]);
  if (!from || !to) return null;
  const src = (from.outs || []).find(o => o.id === w.from[1]) || (from.outs || [])[0] || { label: 'out', t: 'any' };
  const dst = (to.ins || []).find(o => o.id === w.to[1]) || (to.ins || [])[0] || { label: 'in', t: 'any' };
  const ok = src.t === dst.t || dst.t === 'any' || src.t === 'any';
  return {
    id: 'wire:' + i, cat: 'wire', isWire: true,
    title: src.label + ' → ' + dst.label,
    sub: 'connection · ' + src.t + (ok ? '' : ' ✕ ' + dst.t),
    ins:  [{ id: 'src', label: from.title, t: src.t, val: src.label }],
    outs: [{ id: 'dst', label: to.title,   t: dst.t, val: dst.label }],
    params: [
      { k: 'enabled', v: true, type: 'toggle' },
      { k: 'lacing', v: 'shortest', type: 'select' },
      { k: 'tree', v: 'none', type: 'select' },
      { k: 'condition', v: '', type: 'text', page: 'Rules' },
      { k: 'on_fail', v: 'block', type: 'select', page: 'Rules' },
      { k: 'throttle_ms', v: 0, min: 0, max: 2000, step: 50, type: 'slider', page: 'Rules' },
    ],
    typeOk: ok, srcType: src.t, dstType: dst.t,
  };
}

const PM_PRESETS = {
  'revit.create_dimensions': [
    { id: 'ext50', name: '1:50 exterior', vals: { scale: '1:50', align: 'parallel', offset_mm: 240, snap_to: 'outer face' } },
    { id: 'ext100', name: '1:100 coarse', vals: { scale: '1:100', align: 'parallel', offset_mm: 400, snap_to: 'outer face' } },
    { id: 'core', name: 'core setting-out', vals: { scale: '1:50', align: 'parallel', offset_mm: 120, snap_to: 'core face' } },
  ],
};
PM_PRESETS.a_dims = PM_PRESETS['revit.create_dimensions'];
PM_PRESETS.annotate = PM_PRESETS['revit.create_dimensions'];

// Pending edits keyed by node id, held outside the component so they survive the remount a
// focus change causes. A panel that says "1 change pending" then discards it is not control.
const PM_EDITS = new Map();
const pmEdit = (id, defs) => {
  if (!PM_EDITS.has(id)) PM_EDITS.set(id, { vals: defs, cooked: defs, wired: {}, ran: 0, custom: [], labels: {}, pages: ['Main'], page: 'Main' });
  return PM_EDITS.get(id);
};

// A built-in parameter arrives in the node's own shorthand; normalise it into the same spec
// shape a user-added one has, so one row component renders both.
const pmNorm = (p) => ({
  k: p.k, type: p.type === 'slider' ? 'number' : p.type === 'select' ? 'menu' : 'text',
  min: p.min, max: p.max, step: p.step, opts: PM_OPTS[p.k], page: 'Main', builtin: true,
  unit: (PM_META[p.k] || {}).unit, hard: (PM_META[p.k] || {}).hard, help: (PM_META[p.k] || {}).help,
});
// a node may ship parameters already typed and grouped onto pages
const pmNorm2 = (p) => { const o = pmNorm(p); if (p.type === 'toggle') o.type = 'toggle'; if (p.page) o.page = p.page; return o; };

// ── scrub field: the number IS the control ──────────────────────────────────
// Blender's widget: a compact field with a fill bar showing where the value sits in its
// range. Drag to scrub, shift for fine, click to type. This replaces a separate slider —
// a slider plus a readout is the same control drawn twice, and it cost ~40px a row.
function ScrubValue({ value, step, unit, hard, min, max, onChange, disabled }) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState('');
  const [dragging, setDragging] = React.useState(false);
  const moved = React.useRef(0);
  const pct = (min != null && max != null && max > min && Number.isFinite(+value))
    ? Math.max(0, Math.min(100, ((+value - min) / (max - min)) * 100)) : null;

  const commit = (raw) => {
    const n = parseFloat(String(raw).replace(/[^\d.\-]/g, ''));
    setEditing(false);
    if (isNaN(n)) return;
    const lo = hard ? hard[0] : -Infinity, hi = hard ? hard[1] : Infinity;
    onChange(Math.min(hi, Math.max(lo, n)));
  };

  const down = (e) => {
    if (disabled || editing) return;
    moved.current = 0;
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    setDragging(true);
    let acc = +value || 0;
    const move = (ev) => {
      moved.current += Math.abs(ev.movementX);
      const gain = (ev.shiftKey ? 0.2 : 1) * (step || 1) * 0.5;
      acc += ev.movementX * gain;
      const lo = hard ? hard[0] : -Infinity, hi = hard ? hard[1] : Infinity;
      onChange(Math.min(hi, Math.max(lo, Math.round(acc / (step || 1)) * (step || 1))));
    };
    const up = () => {
      el.releasePointerCapture(e.pointerId);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      setDragging(false);
      if (moved.current < 3) { setDraft(String(value)); setEditing(true); }
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
  };

  if (editing) {
    return (
      <input autoFocus value={draft} onChange={e => setDraft(e.target.value)}
        onBlur={() => commit(draft)}
        onKeyDown={e => { if (e.key === 'Enter') commit(draft); if (e.key === 'Escape') setEditing(false); }}
        style={{ width: 104, textAlign: 'right', padding: '4px 7px', borderRadius: 4, border: `1px solid ${PM.accent}`, background: PM.bg, color: PM.ink, fontFamily: PM.mono, fontSize: 12, outline: 'none' }}/>
    );
  }
  return (
    <span onPointerDown={down} title={disabled ? 'Driven by a wire' : 'Drag to scrub · shift for fine · click to type'}
      style={{
        position: 'relative', width: 104, flexShrink: 0, overflow: 'hidden', boxSizing: 'border-box',
        display: 'inline-flex', alignItems: 'baseline', justifyContent: 'flex-end', gap: 3,
        padding: '4px 7px', borderRadius: 4, userSelect: 'none',
        cursor: disabled ? 'not-allowed' : 'ew-resize', opacity: disabled ? 0.55 : 1,
        border: `1px solid ${dragging ? PM.accent : PM.line}`, background: PM.bg,
      }}>
      {pct != null && <span style={{ position: 'absolute', left: 0, bottom: 0, height: 2, width: pct + '%', background: dragging ? PM.accent : PM.accentHi, opacity: dragging ? 1 : 0.7 }}/>}
      <b style={{ position: 'relative', fontFamily: PM.mono, fontSize: 12.5, fontWeight: 500, color: PM.ink }}>{String(value)}</b>
      {unit && <span style={{ position: 'relative', fontFamily: PM.mono, fontSize: 9, color: PM.inkSoft }}>{unit}</span>}
    </span>
  );
}

const pmChip = (on) => ({
  padding: '5px 9px', borderRadius: PM.rad.sm, cursor: 'pointer', fontFamily: PM.mono,
  fontSize: 10.5, lineHeight: 1.2, whiteSpace: 'nowrap',
  border: `1px solid ${on ? PM.accent : PM.line}`,
  background: on ? PM.accent : 'transparent',
  color: on ? (PM.onFill || '#180f08') : PM.inkSoft,
});

// ── one parameter row ───────────────────────────────────────────────────────
// ONE LINE at rest. The old row stacked label + key + type + control + range captions inside
// a tinted card — ~90px each, so six parameters were 540px of scrolling with every row at
// identical visual weight. Houdini and Blender both keep the list flat and put the control
// ON the line; the key, type, range and help are reference material and live in the tooltip
// and the ⋯ menu. State is now read from the left edge: accent = you changed it, cyan = a
// wire drives it, nothing = default.
function ParamRow({ spec, labels, val, def, wired, onChange, onRevert, onPromote, onUnwire, onRename, onDelete }) {
  const [menu, setMenu] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const [naming, setNaming] = React.useState('');
  const T = pmType(spec.type);
  const dataOnly = T.wire;
  const changed = !wired && !dataOnly && String(val) !== String(def);
  const isNum = spec.type === 'number';
  const soft = isNum && Number.isFinite(+val) && (val < spec.min || val > spec.max);
  const label = pmLabel(spec, labels);
  const tip = spec.k + ' · ' + T.label.toLowerCase() + (spec.list ? '[]' : '')
    + (isNum ? ' · ' + spec.min + '–' + spec.max + (spec.unit ? ' ' + spec.unit : '') : '')
    + (spec.help ? ' — ' + spec.help : '');

  const pick = (v) => { onChange(v); setOpen(false); };

  const control = wired ? (
    <span title={'Driven by ' + wired} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, maxWidth: 118, fontFamily: PM.mono, fontSize: 10.5, color: wired === 'unconnected' ? PM.warn : T.col, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
      ← {wired}
    </span>
  ) : dataOnly ? (
    <button onClick={onPromote} title={T.label + ' can only arrive on a wire — expose a socket'}
      style={{ padding: '3px 8px', borderRadius: 4, border: `1px dashed ${PM.line}`, background: 'transparent', color: PM.inkSoft, cursor: 'pointer', fontFamily: PM.mono, fontSize: 10 }}>expose</button>
  ) : isNum ? (
    <ScrubValue value={val} step={spec.step} unit={spec.unit} hard={spec.hard} min={spec.min} max={spec.max} onChange={onChange}/>
  ) : spec.type === 'toggle' ? (
    <button onClick={() => onChange(!val)} role="switch" aria-checked={!!val} title={label + ' — ' + (val ? 'on' : 'off')}
      style={{ background: 'transparent', border: 0, padding: 0, cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
      <span style={{ width: 30, height: 16, borderRadius: 999, position: 'relative', background: val ? PM.accent : PM.lineSoft, transition: 'background .15s' }}>
        <span style={{ position: 'absolute', top: 1, left: val ? 15 : 1, width: 14, height: 14, borderRadius: '50%', background: PM.ink, transition: 'left .15s' }}/>
      </span>
    </button>
  ) : spec.type === 'colour' ? (
    <button onClick={() => setOpen(o => !o)} title="Choose colour"
      style={{ width: 104, height: 24, borderRadius: 4, border: `1px solid ${open ? PM.accent : PM.line}`, background: String(val) || PM.bg, cursor: 'pointer' }}/>
  ) : (spec.opts && spec.opts.length) ? (
    <button onClick={() => setOpen(o => !o)} title={label + ' — ' + spec.opts.length + ' options'}
      style={{ width: 104, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 4, padding: '4px 7px', borderRadius: 4, cursor: 'pointer', border: `1px solid ${open ? PM.accent : PM.line}`, background: PM.bg, color: PM.ink, fontFamily: PM.mono, fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden' }}>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(val)}</span>
      <span style={{ color: PM.inkSoft, fontSize: 9 }}>{open ? '▴' : '▾'}</span>
    </button>
  ) : (
    <input value={val == null ? '' : val} onChange={e => onChange(e.target.value)} placeholder="value…"
      style={{ width: 104, boxSizing: 'border-box', padding: '4px 7px', borderRadius: 4, border: `1px solid ${PM.line}`, background: PM.bg, color: PM.ink, fontFamily: PM.mono, fontSize: 11, outline: 'none' }}/>
  );

  return (
    <div style={{ borderLeft: `2px solid ${wired ? PM.cyan : changed ? PM.accent : 'transparent'}`, paddingLeft: 8, borderBottom: `1px solid ${PM.lineHair}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minHeight: 34 }}>
        <button onClick={() => (wired ? onUnwire() : onPromote())}
          title={wired ? 'Unwire — return to a local value' : 'Expose as a ' + T.label.toLowerCase() + ' input socket'}
          style={{ border: 0, background: 'transparent', padding: 0, cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
          <Socket type={spec.type} list={spec.list} filled={!!wired}/>
        </button>

        {naming ? (
          <input autoFocus value={naming} onChange={e => setNaming(e.target.value)}
            onBlur={() => { onRename(naming.trim() || label); setNaming(''); }}
            onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') setNaming(''); }}
            style={{ flex: 1, minWidth: 0, padding: '2px 5px', borderRadius: 3, border: `1px solid ${PM.accent}`, background: PM.bg, color: PM.ink, fontFamily: PM.sans, fontSize: 12.5, outline: 'none' }}/>
        ) : (
          <span title={tip} style={{ flex: 1, minWidth: 0, fontFamily: PM.sans, fontSize: 12.5, color: PM.ink, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', cursor: 'help' }}>{label}</span>
        )}

        {soft && <span title={'Beyond the usual range — hard limit ' + (spec.hard ? spec.hard[1] : '—')} style={{ color: PM.warn, fontFamily: PM.mono, fontSize: 11 }}>⚠</span>}
        {changed && <button onClick={onRevert} title={'Revert to default · ' + def} style={{ border: 0, background: 'transparent', color: PM.accent, cursor: 'pointer', fontFamily: PM.mono, fontSize: 12, padding: 0 }}>↺</button>}
        {control}
        <button onClick={() => setMenu(m => !m)} title="Row actions"
          style={{ border: 0, background: 'transparent', color: menu ? PM.ink : PM.inkSoft, cursor: 'pointer', fontFamily: PM.mono, fontSize: 12, padding: '0 1px', flexShrink: 0 }}>⋯</button>
      </div>

      {open && (spec.type === 'colour' ? (
        <div style={{ display: 'flex', gap: 5, paddingBottom: 9 }}>
          {[PM.accent, PM.cyan, PM.ok, PM.warn, PM.purple, PM.inkSoft].map(c => (
            <button key={c} onClick={() => pick(c)} title={c} style={{ width: 22, height: 22, borderRadius: 4, background: c, cursor: 'pointer', border: `2px solid ${String(val).toLowerCase() === c.toLowerCase() ? PM.ink : 'transparent'}` }}/>
          ))}
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, paddingBottom: 9 }}>
          {(spec.opts || []).map(o => <button key={o} onClick={() => pick(o)} style={pmChip(val === o)}>{o}</button>)}
        </div>
      ))}

      {menu && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, paddingBottom: 9 }}>
          <button onClick={() => { setNaming(label); setMenu(false); }} style={pmChip(false)}>✎ rename label</button>
          {!dataOnly && <button onClick={() => { onRevert(); setMenu(false); }} style={pmChip(false)}>↺ reset</button>}
          {!wired && <button onClick={() => { onPromote(); setMenu(false); }} style={pmChip(false)}>⇄ expose</button>}
          {!spec.builtin && <button onClick={() => { onDelete(); setMenu(false); }} style={Object.assign({}, pmChip(false), { color: PM.err, borderColor: PM.err })}>⌫ remove</button>}
          <span style={{ flexBasis: '100%', fontFamily: PM.mono, fontSize: 9, color: PM.inkSoft, lineHeight: 1.5 }}>
            <b style={{ color: PM.ink }}>{spec.k}</b> · {T.label.toLowerCase()}{spec.list ? '[]' : ''}{isNum ? ' · ' + spec.min + '–' + spec.max : ''} · key is fixed, the skill JSON references it
          </span>
        </div>
      )}
    </div>
  );
}

// ── add a parameter ─────────────────────────────────────────────────────────
// Houdini's move: you pick a TYPE first, because the type decides everything else — whether
// it has a control at all, what colour its socket is, what a wire into it may carry.
function AddParam({ page, taken, onAdd, onCancel }) {
  const [name, setName] = React.useState('');
  const [type, setType] = React.useState('number');
  const [list, setList] = React.useState(false);
  const T = pmType(type);
  const key = (name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')) || 'new_param';
  const clash = taken.indexOf(key) >= 0;

  return (
    <div style={{ padding: 11, borderRadius: PM.rad.md, border: `1px solid ${PM.accent}`, background: PM.bg, display: 'flex', flexDirection: 'column', gap: 9 }}>
      <div style={{ fontFamily: PM.mono, fontSize: 9, color: PM.accent, letterSpacing: '0.16em' }}>NEW PARAMETER · {page.toUpperCase()}</div>

      <div>
        <input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="Label — e.g. Max span"
          style={{ width: '100%', padding: '7px 9px', borderRadius: PM.rad.sm, border: `1px solid ${clash ? PM.err : PM.line}`, background: PM.bgPanel, color: PM.ink, fontFamily: PM.sans, fontSize: 12.5, outline: 'none' }}/>
        <div style={{ marginTop: 4, fontFamily: PM.mono, fontSize: 9, color: clash ? PM.err : PM.inkSoft }}>
          key <b style={{ color: clash ? PM.err : PM.ink }}>{key}</b>{clash ? ' · already used on this node' : ' · fixed once created'}
        </div>
      </div>

      <div>
        <div style={{ fontFamily: PM.mono, fontSize: 9, color: PM.inkSoft, letterSpacing: '0.14em', marginBottom: 5 }}>TYPE</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
          {Object.keys(PM_TYPES).map(t => {
            const d = PM_TYPES[t], on = type === t;
            return (
              <button key={t} onClick={() => setType(t)} style={{
                display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', borderRadius: PM.rad.sm, cursor: 'pointer',
                border: `1px solid ${on ? d.col : PM.line}`, background: on ? PM.bgSoft : 'transparent', textAlign: 'left',
              }}>
                <Socket type={t} list={list} filled={on} size={8}/>
                <span style={{ fontFamily: PM.sans, fontSize: 11.5, color: on ? PM.ink : PM.inkSoft }}>{d.label}</span>
              </button>
            );
          })}
        </div>
        <div style={{ marginTop: 6, fontFamily: PM.mono, fontSize: 9.5, color: PM.inkSoft, lineHeight: 1.5 }}>
          {T.wire ? T.label + ' arrives on a wire — it gets a socket and no inline control.'
                  : T.label + ' is edited here, and can still be exposed as a socket later.'}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 4 }}>
        <button onClick={() => setList(false)} style={pmChip(!list)}>○ one value</button>
        <button onClick={() => setList(true)} style={pmChip(list)}>◇ a list</button>
      </div>

      <div style={{ display: 'flex', gap: 5 }}>
        <button onClick={onCancel} style={Object.assign({}, pmChip(false), { flex: 1, textAlign: 'center', justifyContent: 'center', padding: '7px 9px' })}>Cancel</button>
        <button disabled={clash} onClick={() => onAdd({ k: key, label: name.trim() || 'New parameter', type, list, page })}
          style={{ flex: 2, padding: '7px 9px', borderRadius: PM.rad.sm, border: 0, cursor: clash ? 'not-allowed' : 'pointer', opacity: clash ? 0.45 : 1, background: PM.accent, color: PM.onFill || '#180f08', fontFamily: PM.sans, fontSize: 12, fontWeight: 500 }}>
          ＋ Add parameter
        </button>
      </div>
    </div>
  );
}

const pmPin = (s, side, tint) => (
  <div key={side + (s.id || s.label)} style={{ display: 'flex', alignItems: 'center', gap: 8, minHeight: 26, borderBottom: `1px solid ${PM.lineHair}`, paddingLeft: 2 }}>
    <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: side === 'out' ? (PM_WIRE[s.t] || PM.inkSoft) : 'transparent', border: `1.5px solid ${PM_WIRE[s.t] || PM.inkSoft}` }}/>
    <span style={{ flex: 1, minWidth: 0, fontFamily: PM.sans, fontSize: 12, color: PM.ink, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.label || s.id}</span>
    <span style={{ fontFamily: PM.mono, fontSize: 10, color: tint || PM.inkSoft, whiteSpace: 'nowrap' }}>{s.val || s.t}</span>
  </div>
);

const pmHead = (glyph, text, right) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
    <span style={{ fontFamily: PM.mono, fontSize: 10, color: PM.inkSoft }}>{glyph}</span>
    <span style={{ fontFamily: PM.mono, fontSize: 9, color: PM.inkSoft, letterSpacing: '0.18em' }}>{text}</span>
    <span style={{ flex: 1 }}/>
    {right}
  </div>
);

// ── the inspector ───────────────────────────────────────────────────────────
function NodeInspector({ node }) {
  const builtins = React.useMemo(() => (node.params || []).map(pmNorm2), [node.id]);
  const defs = React.useMemo(() => { const d = {}; builtins.forEach(p => d[p.k] = (node.params.find(x => x.k === p.k) || {}).v); return d; }, [node.id]);

  const seedPages = React.useMemo(() => {
    const ps = ['Main']; (node.params || []).forEach(p => { if (p.page && ps.indexOf(p.page) < 0) ps.push(p.page); });
    return ps;
  }, [node.id]);
  const rec = pmEdit(node.id, defs);
  if (rec.pages.length < seedPages.length) rec.pages = seedPages;
  const [vals, _setVals] = React.useState(rec.vals);
  const [cooked, _setCooked] = React.useState(rec.cooked);
  const [wired, _setWired] = React.useState(rec.wired);
  const [ran, _setRan] = React.useState(rec.ran);
  const [custom, _setCustom] = React.useState(rec.custom);
  const [labels, _setLabels] = React.useState(rec.labels);
  const [page, _setPage] = React.useState(rec.page);
  const [pages, _setPages] = React.useState(rec.pages);
  const [adding, setAdding] = React.useState(false);
  const [newPage, setNewPage] = React.useState('');
  const [confirmDel, setConfirmDel] = React.useState(false);

  const thru = (setter, field) => (v) => setter(prev => {
    const next = typeof v === 'function' ? v(prev) : v;
    rec[field] = next; return next;
  });
  const setVals = thru(_setVals, 'vals'), setCooked = thru(_setCooked, 'cooked');
  const setWired = thru(_setWired, 'wired'), setRan = thru(_setRan, 'ran');
  const setCustom = thru(_setCustom, 'custom'), setPage = thru(_setPage, 'page'), setPages = thru(_setPages, 'pages');
  const setLabels = thru(_setLabels, 'labels');

  const all = builtins.concat(custom);
  const allDefs = Object.assign({}, defs); custom.forEach(c => allDefs[c.k] = c.def);
  const set = (k, v) => {
    setVals(s => Object.assign({}, s, { [k]: v }));
    // A LIVE node's parameter is a graph cell: the edit commits through
    // the governed write, so what the panel shows is what the graph
    // holds. Design nodes keep their local behaviour untouched.
    const held = (node.params || []).find(x => x.k === k);
    if (node.live && held && held.rel && window.ARCHHUB_SET_PROP) {
      window.ARCHHUB_SET_PROP(held.rel, String(v)).catch(() => {});
    }
  };

  const editable = all.filter(p => !pmType(p.type).wire);
  const dirty = editable.filter(p => !wired[p.k] && String(vals[p.k]) !== String(cooked[p.k])).map(p => p.k);
  const overridden = editable.filter(p => !wired[p.k] && String(vals[p.k]) !== String(allDefs[p.k])).length;

  const fn = ((node.sub || '').match(/^[\w.]+/) || [])[0];
  const presets = PM_PRESETS[fn] || PM_PRESETS[node.id] || PM_PRESETS[node.cat] || [];
  const activePreset = presets.find(pr => Object.keys(pr.vals).every(k => String(vals[k]) === String(pr.vals[k])));

  const onPage = all.filter(p => (p.page || 'Main') === page);
  const countOn = (pg) => all.filter(p => (p.page || 'Main') === pg).length;

  const promoted = Object.keys(wired).map(k => {
    const spec = all.find(p => p.k === k) || { k, type: 'any' };
    return { id: 'p_' + k, label: pmLabel(spec, labels).toLowerCase(), t: spec.type === 'number' ? 'number' : spec.type, val: wired[k] };
  });

  const addParam = (spec) => {
    const T = pmType(spec.type);
    const def = spec.type === 'number' ? 0 : T.def;
    const full = Object.assign({}, spec, {
      def, min: 0, max: 100, step: 1,
      opts: spec.type === 'menu' ? [] : undefined,
    });
    setCustom(c => c.concat(full));
    if (!T.wire) { setVals(v => Object.assign({}, v, { [spec.k]: def })); setCooked(c => Object.assign({}, c, { [spec.k]: def })); }
    else setWired(w => Object.assign({}, w, { [spec.k]: 'unconnected' }));
    setAdding(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {(node.ins || node.outs || promoted.length > 0) && (
        <div>
          {pmHead('⇄', 'CONNECTIONS')}
          <div style={{ borderTop: `1px solid ${PM.lineHair}` }}>
            {((node.ins || []).length > 0 || promoted.length > 0) && (
              <div>
                <div style={{ fontFamily: PM.mono, fontSize: 8.5, color: PM.inkSoft, letterSpacing: '0.14em', padding: '7px 0 3px' }}>RECEIVES</div>
                {(node.ins || []).map(s => pmPin(s, 'in'))}
                {promoted.map(s => pmPin(s, 'in', s.val === 'unconnected' ? PM.warn : PM.cyan))}
              </div>
            )}
            {(node.outs || []).length > 0 && (
              <div>
                <div style={{ fontFamily: PM.mono, fontSize: 8.5, color: PM.inkSoft, letterSpacing: '0.14em', padding: '7px 0 3px' }}>SENDS</div>
                {node.outs.map(s => pmPin(s, 'out'))}
              </div>
            )}
          </div>
        </div>
      )}

      <div>
        {pmHead('⌗', 'PARAMETERS', overridden > 0 && (
          <button onClick={() => setVals(allDefs)} style={{ border: 0, background: 'transparent', color: PM.inkSoft, cursor: 'pointer', fontFamily: PM.mono, fontSize: 9.5, letterSpacing: '0.06em' }}>↺ REVERT ALL</button>
        ))}

        {/* PAGES — Houdini folders / TouchDesigner pages. A long interface is a navigation
            problem, not a scrolling problem. Hidden until there is more than one. */}
        {(pages.length > 1 || newPage !== '') && (
          <div style={{ display: 'flex', gap: 3, marginBottom: 9, flexWrap: 'wrap', alignItems: 'center' }}>
            {pages.map(pg => (
              <button key={pg} onClick={() => setPage(pg)} style={{
                display: 'flex', alignItems: 'center', gap: 5, padding: '4px 9px', borderRadius: PM.rad.sm, cursor: 'pointer',
                border: 0, borderBottom: `2px solid ${page === pg ? PM.accent : 'transparent'}`,
                background: 'transparent', color: page === pg ? PM.ink : PM.inkSoft, fontFamily: PM.sans, fontSize: 12,
              }}>{pg}<span style={{ fontFamily: PM.mono, fontSize: 9, color: PM.inkSoft }}>{countOn(pg)}</span></button>
            ))}
          </div>
        )}

        {presets.length > 0 && all.length > 0 && page === 'Main' && (
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 4, marginBottom: 10 }}>
            <span style={{ flexBasis: '100%', fontFamily: PM.mono, fontSize: 8.5, color: PM.inkSoft, letterSpacing: '0.14em' }}>PRACTICE STANDARDS</span>
            {presets.map(pr => (
              <button key={pr.id} onClick={() => setVals(v => Object.assign({}, v, pr.vals))} style={{
                padding: '4px 9px', borderRadius: PM.rad.pill, cursor: 'pointer', fontFamily: PM.sans, fontSize: 11, whiteSpace: 'nowrap',
                border: `1px solid ${activePreset === pr ? PM.accent : PM.line}`,
                background: activePreset === pr ? PM.accentSoft : 'transparent',
                color: activePreset === pr ? PM.ink : PM.inkSoft,
              }}>{pr.name}</button>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', borderTop: `1px solid ${PM.lineHair}` }}>
          {onPage.map(spec => (
            <ParamRow key={spec.k} spec={spec} labels={labels} val={vals[spec.k]} def={allDefs[spec.k]} wired={wired[spec.k]}
              onChange={v => set(spec.k, v)}
              onRevert={() => set(spec.k, allDefs[spec.k])}
              onPromote={() => setWired(w => Object.assign({}, w, { [spec.k]: 'graph input' }))}
              onUnwire={() => setWired(w => { const n = Object.assign({}, w); delete n[spec.k]; return n; })}
              onRename={lbl => setLabels(l => Object.assign({}, l, { [spec.k]: lbl }))}
              onDelete={() => { setCustom(c => c.filter(x => x.k !== spec.k)); setWired(w => { const n = Object.assign({}, w); delete n[spec.k]; return n; }); }}/>
          ))}
          {onPage.length === 0 && (
            <div style={{ padding: '14px 11px', borderRadius: PM.rad.md, border: `1px dashed ${PM.line}`, fontFamily: PM.serif, fontStyle: 'italic', fontSize: 13.5, color: PM.inkSoft }}>
              {pages.length > 1 ? 'Nothing on this page yet.' : 'This node takes no parameters — add one below.'}
            </div>
          )}
        </div>

        {adding ? (
          <div style={{ marginTop: 6 }}>
            <AddParam page={page} taken={all.map(p => p.k)} onAdd={addParam} onCancel={() => setAdding(false)}/>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 5, marginTop: 7 }}>
            <button onClick={() => setAdding(true)} style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', padding: '7px 9px', borderRadius: PM.rad.sm, border: `1px dashed ${PM.line}`, background: 'transparent', color: PM.inkSoft, cursor: 'pointer', fontFamily: PM.sans, fontSize: 11.5 }}>
              ＋ Add parameter
            </button>
            {newPage === '' ? (
              <button onClick={() => setNewPage('New page')} title="Group parameters onto a new page" style={{ flexShrink: 0, whiteSpace: 'nowrap', padding: '7px 10px', borderRadius: PM.rad.sm, border: `1px dashed ${PM.line}`, background: 'transparent', color: PM.inkSoft, cursor: 'pointer', fontFamily: PM.sans, fontSize: 11.5 }}>⊞ Page</button>
            ) : (
              <input autoFocus value={newPage} onChange={e => setNewPage(e.target.value)}
                onBlur={() => { const n = newPage.trim(); if (n && pages.indexOf(n) < 0) { setPages(p => p.concat(n)); setPage(n); } setNewPage(''); }}
                onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') setNewPage(''); }}
                style={{ width: 96, padding: '6px 8px', borderRadius: PM.rad.sm, border: `1px solid ${PM.accent}`, background: PM.bg, color: PM.ink, fontFamily: PM.sans, fontSize: 11.5, outline: 'none' }}/>
            )}
          </div>
        )}
      </div>

      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0 9px' }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: dirty.length ? PM.warn : PM.ok }}/>
          <span style={{ flex: 1, fontFamily: PM.mono, fontSize: 10, color: dirty.length ? PM.warn : PM.inkSoft, lineHeight: 1.5 }}>
            {dirty.length
              ? 'Output is stale · ' + dirty.join(', ') + ' changed since the last run'
              : (ran ? 'Output current · ran ' + ran + (ran === 1 ? ' time' : ' times') + ' this session' : 'Output current')
                + (overridden ? ' · ' + overridden + ' off default' : '')}
          </span>
        </div>

        {confirmDel ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ flex: 1, fontFamily: PM.mono, fontSize: 10, color: PM.err, lineHeight: 1.45 }}>
              Delete {node.isWire ? 'this connection' : 'node and its ' + (node.outs || []).length + ' outgoing wire' + ((node.outs || []).length === 1 ? '' : 's')}?
            </span>
            <button onClick={() => setConfirmDel(false)} style={pmBtn()}>Cancel</button>
            <button style={Object.assign({}, pmBtn(), { color: PM.err, borderColor: PM.err })}>Delete</button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 5 }}>
            <button onClick={() => { setRan(r => r + 1); setCooked(vals); }} style={{
              flex: 1, minWidth: 0, minHeight: 34, padding: '7px 10px', borderRadius: PM.rad.sm, border: 0,
              background: dirty.length ? PM.accent : PM.bg,
              color: dirty.length ? (PM.onFill || '#180f08') : PM.inkSoft,
              boxShadow: dirty.length ? 'none' : `inset 0 0 0 1px ${PM.line}`,
              fontFamily: PM.sans, fontSize: 12.5, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap',
            }}>↻ Rerun{dirty.length ? ' · ' + dirty.length : ''}</button>
            <button style={pmIcon()} title={node.isWire ? 'Save this connection\u2019s rules as a reusable skill' : 'Save these parameters as a reusable skill'}>◈</button>
            <button style={pmIcon()} title="Fork the graph from here, keeping everything upstream">⑂</button>
            <button onClick={() => setConfirmDel(true)} style={pmIcon()} title={node.isWire ? 'Delete this connection…' : 'Delete node…'}>⌫</button>
          </div>
        )}
      </div>
    </div>
  );
}

const pmIcon = () => ({
  width: 34, minHeight: 34, flexShrink: 0, padding: 0, borderRadius: PM.rad.sm,
  background: 'transparent', border: `1px solid ${PM.line}`, color: PM.inkSoft,
  fontFamily: PM.mono, fontSize: 13, cursor: 'pointer',
});
const pmBtn = () => ({
  flex: 1, minHeight: 32, padding: '6px 9px', borderRadius: PM.rad.sm,
  background: 'transparent', border: `1px solid ${PM.line}`, color: PM.inkSoft,
  fontFamily: PM.sans, fontSize: 11.5, cursor: 'pointer', whiteSpace: 'nowrap',
});

// PM_TYPES and Socket are exported so the COCKPIT reads the same type vocabulary — one
// registry for both graphs, rather than two names for the same idea.
Object.assign(window, { NodeInspector, wireAsNode });
