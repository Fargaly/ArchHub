// Canvas dock: panels tab together, stack with a splitter, dock left/right/bottom, float, fold to their header, or step aside in Focus mode.
// Behaviour and look are ported from archhub-directions app.js ("the layout is the user's"); settings_owner.dock_layout owns the record.
(() => {
  const PANELS = {
    workshop: ['Workshop', 'workshop'],
    library: ['Library', 'library'],
    map: ['Map', 'canvas'],
    insp: ['Inspector', 'settings'],
    people: ['People and agents', 'users'],
    thread: ['Thread', 'workshop'],
  };
  const CORE = ['workshop', 'library', 'map', 'insp'];
  const HOME = {workshop: 'left', library: 'left', map: 'left', insp: 'right', people: 'right', thread: 'right'};
  const SIDES = ['left', 'right'];
  const ALL_SIDES = ['left', 'right', 'bottom'];
  const LEFT = {min: 200, max: 520, base: 268}, RIGHT = {min: 280, max: 480, base: 320}, BOTTOM = {min: 140, max: 480, base: 220};
  const clone = layout => JSON.parse(JSON.stringify(layout));
  const slot = id => ({p: [id], a: id, h: 1, c: false});
  const NARROW = 1280;  // below this window width the right dock starts folded to icons, so the canvas keeps its room
  // Workshop over Library|Map on the left; the Inspector on the right, open as before the dock.
  const defaultLayout = width => ({
    left: {w: LEFT.base, c: false, st: [{p: ['workshop'], a: 'workshop', h: 1.15, c: false}, {p: ['library', 'map'], a: 'library', h: 1, c: false}]},
    right: {c: false, st: [slot('insp')]},
  });
  const PRESETS = {
    Build: () => defaultLayout(NARROW),
    Review: () => ({
      left: {w: LEFT.base, c: false, st: [{p: ['workshop'], a: 'workshop', h: 1.15, c: false}, {p: ['map'], a: 'map', h: 1, c: false}]},
      right: {c: false, st: [slot('insp')]},
      closed: ['library'],
      preset: 'Review',
    }),
    Meeting: () => ({
      left: {w: LEFT.base, c: false, st: [slot('workshop')]},
      right: {c: false, st: [slot('people')]},
      closed: ['library', 'map', 'insp'],
      preset: 'Meeting',
    }),
  };
  const presetLayout = (name, width) => (PRESETS[name] ? PRESETS[name](width) : defaultLayout(width));
  const validCmd = cmd => cmd != null && typeof cmd === 'object' && cmd.x != null && cmd.x !== '' && typeof cmd.x !== 'boolean'
    && cmd.y != null && cmd.y !== '' && typeof cmd.y !== 'boolean' && Number.isFinite(Number(cmd.x)) && Number.isFinite(Number(cmd.y))
    ? {x: Math.max(0, Math.min(1, Number(cmd.x))), y: Math.max(0, Math.min(1, Number(cmd.y)))} : null;

  // A held record becomes a layout where every known panel sits in at most one place and default core panels return unless explicitly closed.
  const normalize = (held, width) => {
    if (!held || !held.left || !held.right) return defaultLayout(width);
    const seen = new Set();
    const closedSet = new Set((Array.isArray(held.closed) ? held.closed : []).filter(id => PANELS[id]));
    const normSlots = list => (Array.isArray(list) ? list : []).map(sl => {
      const p = (Array.isArray(sl.p) ? sl.p : []).filter(id => PANELS[id] && !seen.has(id) && seen.add(id));
      return {p, a: p.includes(sl.a) ? sl.a : p[0], h: sl.h > 0 ? Math.max(.05, Math.min(20, sl.h)) : 1, c: sl.c === true};
    }).filter(sl => sl.p.length);
    const dock = side => ({
      ...(side === 'left' ? {w: Math.max(LEFT.min, Math.min(LEFT.max, Math.round(held.left.w) || LEFT.base))} : {}),
      c: held[side].c === true,
      st: normSlots(held[side].st),
    });
    const left = dock('left'), right = dock('right');
    const bottomSlots = held.bottom ? normSlots(held.bottom.st) : [];
    const floatSource = Array.isArray(held.float) ? held.float : Array.isArray(held.floating) ? held.floating : [];
    const floating = floatSource.filter(f => f && PANELS[f.id] && !seen.has(f.id) && seen.add(f.id)).map(f => ({
      id: f.id,
      x: Math.max(8, Math.round(Number(f.x) || 160)),
      y: Math.max(8, Math.round(Number(f.y) || 72)),
      w: Math.max(220, Math.min(640, Math.round(Number(f.w) || 320))),
      h: Math.max(160, Math.min(640, Math.round(Number(f.h) || 380))),
    }));
    const cmd = validCmd(held.cmd);
    const next = {left, right, ...(cmd ? {cmd} : {})};
    if (bottomSlots.length) {
      next.bottom = {
        h: Math.max(BOTTOM.min, Math.min(BOTTOM.max, Math.round(held.bottom?.h) || BOTTOM.base)),
        c: held.bottom?.c === true,
        st: bottomSlots,
      };
    }
    if (floating.length) next.float = floating;
    for (const id of CORE) if (!seen.has(id) && !closedSet.has(id)) {
      const st = next[HOME[id]].st;
      if (st.length) st[st.length - 1].p.push(id); else st.push(slot(id));
    }
    const keptClosed = [...closedSet].filter(id => !seen.has(id) && CORE.includes(id));
    if (keptClosed.length) next.closed = keptClosed;
    if (held.focus === true) next.focus = true;
    if (typeof held.preset === 'string' && PRESETS[held.preset] && held.preset !== 'Build') next.preset = held.preset;
    if (typeof held.savedName === 'string' && held.savedName.trim()) {
      next.savedName = held.savedName.trim().slice(0, 80);
      if (held.savedChanged === true) next.savedChanged = true;
    }
    return next;
  };

  const sideSlots = (layout, side) => side === 'bottom' ? (layout.bottom?.st || []) : (layout[side]?.st || []);
  const where = (layout, id) => {
    for (const side of ALL_SIDES) {
      const st = sideSlots(layout, side);
      const index = st.findIndex(sl => sl.p.includes(id));
      if (index >= 0) return {side, index};
    }
    const floatIdx = (layout.float || []).findIndex(f => f.id === id);
    if (floatIdx >= 0) return {side: 'float', index: floatIdx};
    return null;
  };
  const visible = (layout, id) => {
    if (layout?.focus) return false;
    const at = where(layout, id);
    if (!at) return false;
    if (at.side === 'float') return true;
    const d = at.side === 'bottom' ? layout.bottom : layout[at.side];
    return !!d && !d.c && !d.st[at.index].c && d.st[at.index].a === id;
  };
  const stripPanel = (next, id) => {
    for (const s of ALL_SIDES) {
      const d = s === 'bottom' ? next.bottom : next[s];
      if (!d) continue;
      for (const sl of d.st) {
        sl.p = sl.p.filter(panel => panel !== id);
        if (sl.a === id) sl.a = sl.p[0];
      }
      d.st = d.st.filter(sl => sl.p.length);
    }
    if (next.bottom && !next.bottom.st.length) delete next.bottom;
    if (Array.isArray(next.float)) {
      next.float = next.float.filter(f => f.id !== id);
      if (!next.float.length) delete next.float;
    }
    if (Array.isArray(next.closed)) {
      next.closed = next.closed.filter(c => c !== id);
      if (!next.closed.length) delete next.closed;
    }
    if (next.savedName) next.savedChanged = true;
  };
  // pos: 'tab' joins the slot at index; 'above' / 'below' stack a new slot beside it; 'dock' joins the dock's last slot.
  const place = (layout, id, side, index, pos) => {
    if (!PANELS[id] || !ALL_SIDES.includes(side)) return layout;
    const currentDock = side === 'bottom' ? layout.bottom : layout[side];
    const currentTarget = currentDock ? (pos === 'dock' ? currentDock.st[currentDock.st.length - 1] : currentDock.st[index]) : null;
    if (currentTarget && currentTarget.p.length === 1 && currentTarget.p[0] === id) return layout;
    const next = clone(layout);
    if (side === 'bottom' && !next.bottom) next.bottom = {h: BOTTOM.base, c: false, st: []};
    const d = side === 'bottom' ? next.bottom : next[side];
    const target = pos === 'dock' ? d.st[d.st.length - 1] : d.st[index];
    stripPanel(next, id);
    const dest = side === 'bottom' ? (next.bottom || (next.bottom = {h: BOTTOM.base, c: false, st: []})) : next[side];
    const keptTarget = target && dest.st.includes(target) ? target : (pos === 'dock' ? dest.st[dest.st.length - 1] : null);
    if (keptTarget && (pos === 'tab' || pos === 'dock')) { keptTarget.p.push(id); keptTarget.a = id; keptTarget.c = false; }
    else dest.st.splice(keptTarget ? dest.st.indexOf(keptTarget) + (pos === 'below' ? 1 : 0) : dest.st.length, 0, slot(id));
    dest.c = false;
    delete next.focus;
    return next;
  };
  const floatPanel = (layout, id, rect = {}) => {
    if (!PANELS[id]) return layout;
    const next = clone(layout);
    stripPanel(next, id);
    const list = Array.isArray(next.float) ? next.float : [];
    list.push({
      id,
      x: Math.max(8, Math.round(Number(rect.x ?? 180))),
      y: Math.max(8, Math.round(Number(rect.y ?? 72))),
      w: Math.max(220, Math.min(640, Math.round(Number(rect.w ?? 320)))),
      h: Math.max(160, Math.min(640, Math.round(Number(rect.h ?? 380)))),
    });
    next.float = list;
    delete next.focus;
    return next;
  };
  const closePanel = (layout, id) => {
    if (!PANELS[id] || !where(layout, id)) return layout;
    const next = clone(layout);
    stripPanel(next, id);
    if (CORE.includes(id)) next.closed = [...new Set([...(next.closed || []), id])];
    return next;
  };
  const movePanel = (layout, id, to, rect) => {
    if (!to) return closePanel(layout, id);
    if (to === 'float') return floatPanel(layout, id, rect);
    return place(layout, id, to, 0, 'dock');
  };
  const show = (layout, id) => {
    if (!PANELS[id]) return layout;
    const at = where(layout, id);
    if (!at) return place(layout, id, HOME[id] || 'right', 0, 'dock');
    if (visible(layout, id)) return layout;
    const next = clone(layout);
    delete next.focus;
    if (at.side === 'float') return next;
    const d = at.side === 'bottom' ? next.bottom : next[at.side];
    const sl = d.st[at.index];
    sl.a = id; sl.c = false; d.c = false;
    return next;
  };
  const showAll = layout => {
    let next = clone(layout);
    delete next.closed;
    delete next.focus;
    next.left.c = false;
    next.right.c = false;
    if (next.bottom) next.bottom.c = false;
    for (const id of Object.keys(PANELS)) {
      if (!where(next, id)) next = place(next, id, HOME[id] || 'right', 0, 'dock');
    }
    return next;
  };
  const hide = (layout, id) => {
    if (!visible(layout, id)) return layout;
    const at = where(layout, id);
    if (at.side === 'float') return closePanel(layout, id);
    const next = clone(layout);
    const d = at.side === 'bottom' ? next.bottom : next[at.side];
    d.st[at.index].c = true;
    return next;
  };
  const toggleSlot = (layout, side, index) => {
    const next = clone(layout);
    const d = side === 'bottom' ? next.bottom : next[side];
    if (d?.st?.[index]) d.st[index].c = !d.st[index].c;
    return next;
  };
  const toggleDock = (layout, side) => {
    const next = clone(layout);
    const d = side === 'bottom' ? next.bottom : next[side];
    if (d) d.c = !d.c;
    return next;
  };
  // Two stacked neighbours share their height by the dragged pixel sizes; each keeps at least its 34 px header.
  const resizeSlots = (layout, side, index, upper, lower) => {
    const next = clone(layout), d = side === 'bottom' ? next.bottom : next[side];
    const a = d.st[index], b = d.st[index + 1];
    const total = upper + lower, kept = Math.max(34, Math.min(total - 34, upper)), sum = a.h + b.h;
    a.h = Math.max(.05, Math.round(sum * kept / total * 1000) / 1000);
    b.h = Math.max(.05, Math.round((sum - a.h) * 1000) / 1000);
    return next;
  };
  const setLeftWidth = (layout, width) => ({...layout, left: {...layout.left, w: Math.max(LEFT.min, Math.min(LEFT.max, Math.round(width)))}});
  const setBottomHeight = (layout, height) => layout.bottom
    ? {...layout, bottom: {...layout.bottom, h: Math.max(BOTTOM.min, Math.min(BOTTOM.max, Math.round(height)))}}
    : layout;
  const setFocus = (layout, on) => {
    const want = on == null ? !layout?.focus : Boolean(on);
    if (Boolean(layout?.focus) === want) return layout;
    const next = clone(layout);
    if (want) next.focus = true; else delete next.focus;
    return next;
  };
  const setCmd = (layout, cmd) => {
    const nextCmd = validCmd(cmd);
    if (!nextCmd) {
      if (!layout?.cmd) return layout;
      const next = clone(layout);
      delete next.cmd;
      return next;
    }
    if (layout?.cmd && layout.cmd.x === nextCmd.x && layout.cmd.y === nextCmd.y) return layout;
    return {...layout, cmd: nextCmd};
  };

  window.UI = window.UI || {};
  // The Build preset is the default layout. A layout is named by where its panels sit and whether cmd moved; widths and folds do not rename it.
  // The Thread comes and goes with its session (Show the thread), so it never renames a layout.
  const slotsOf = list => (list || []).map(sl => sl.p.filter(id => id !== 'thread')).filter(p => p.length);
  const places = layout => JSON.stringify([
    ...SIDES.map(side => slotsOf(layout[side]?.st)),
    slotsOf(layout.bottom?.st),
    (layout.float || []).map(f => f.id).filter(id => id !== 'thread'),
  ]);
  const presetName = layout => {
    if (!layout?.cmd) {
      if (layout?.savedName && !layout?.savedChanged) return layout.savedName;
      for (const name of ['Build', 'Review', 'Meeting']) {
        if (places(layout) === places(PRESETS[name]())) return name;
      }
    }
    const base = layout?.savedName || layout?.preset || 'Build';
    return base.endsWith(' (changed)') ? base : base + ' (changed)';
  };

  window.UI.dockModel = {
    PANELS, PRESETS: Object.keys(PRESETS), LEFT, RIGHT, BOTTOM,
    defaultLayout, presetLayout, normalize, where, visible, place,
    floatPanel, closePanel, movePanel, show, showAll, hide,
    toggleSlot, toggleDock, resizeSlots, setLeftWidth, setBottomHeight, setFocus, setCmd, presetName,
  };
  if (typeof React === 'undefined') return;  // the layout rules above also load alone, without a page

  const api = window.ArchHubAPI, {executeAction} = api, Icon = window.AHIcon, portal = window.ReactDOM.createPortal;
  const shortName = name => { const [app, , id] = String(name || '').split(' / '); return id ? app + ' \u00b7 ' + id.replace(/^session-/, '').slice(0, 6) : String(name || ''); };
  const onResize = notify => { window.addEventListener('resize', notify); return () => window.removeEventListener('resize', notify); };
  const narrowOpen = {held: false, listeners: new Set(),
    subscribe(notify) { narrowOpen.listeners.add(notify); return () => narrowOpen.listeners.delete(notify); },
    read() { if (window.innerWidth >= NARROW) narrowOpen.held = false; return narrowOpen.held; },
    set(value) { if (value === narrowOpen.read()) return; narrowOpen.held = value; narrowOpen.listeners.forEach(notify => notify()); }};

  // Settings > This PC > Panels writes the same one layout the dock does (settings_owner.dock_layout).
  window.UI.dockModel.current = record => normalize(record, window.innerWidth);
  window.UI.dockModel.save = next => api.setDockLayout(next);

  function PeopleDockView({onShow}) {
    const {useData, useApp, Btn, Av} = window.UI, s = useData(), u = useApp();
    const tasks = (s.tasks || []).filter(t => t.status !== 'ARCHIVED');
    const activeTask = tasks.find(t => t.id === u.task) || tasks[0] || null;
    const liveSessions = s.agentGraph?.sessions || [];
    const liveAgents = s.liveAgents || [];
    const providers = (s.providers || []).filter(p => p.enabled !== false);
    const agentRows = [];
    const seenNames = new Set();
    for (const sess of liveSessions) {
      const label = shortName(sess.name || sess.id || 'Agent');
      if (seenNames.has(label)) continue;
      seenNames.add(label);
      const t = tasks.find(row => row.id === sess.task);
      agentRows.push({key: sess.id || label, name: label, rawName: sess.name || label, status: sess.status || 'idle', detail: t ? 'On ' + t.title : 'Ready on this PC', task: t});
    }
    for (const ag of liveAgents) {
      const label = shortName(ag.name || ag.agent || 'Agent');
      if (seenNames.has(label)) continue;
      seenNames.add(label);
      agentRows.push({key: ag.handle || label, name: label, rawName: ag.name || ag.agent || label, status: ag.status || 'idle', detail: ag.task || 'Available', task: null});
    }
    // Agent sessions running on this PC that have not joined: shown whatever their sign-in state (moved from the Workshop page).
    for (const p of s.agents || []) {
      const label = p.name || p.id;
      if (!label || seenNames.has(label) || liveAgents.some(a => a.app === p.runtime)) continue;
      seenNames.add(label);
      const state = p.presence === 'working' ? 'Working' : p.presence === 'unknown' ? (p.status_text || 'Status unknown') : 'Idle';
      agentRows.push({key: 'pc:' + (p.id || label), name: label, rawName: label, status: state, detail: 'Not joined' + (p.presence === 'working' && p.task ? ' · ' + p.task : ''), task: null});
    }
    for (const p of providers.slice(0, 4)) {
      const label = p.name || p.id;
      if (!label || seenNames.has(label)) continue;
      seenNames.add(label);
      agentRows.push({key: p.id || label, name: label, rawName: label, status: p.signedIn ? 'idle' : 'offline', detail: p.model || p.availability || 'Configured', task: null});
    }
    const people = s.people || [];
    const messageAgent = row => {
      if (row.task && onShow) onShow({task: row.task});
      const input = window.document.querySelector('.v22g-composer-dock textarea, .global-composer textarea');
      if (input) input.focus();
    };
    const assignAgent = row => {
      if (!activeTask) { u.setToast?.('Open or create a task first to assign ' + row.name + '.'); return; }
      const existing = Array.isArray(activeTask.agents) ? activeTask.agents : [];
      if (existing.includes(row.rawName) || existing.includes(row.name)) {
        u.setToast?.(row.name + ' already works on ' + activeTask.title + '.');
        return;
      }
      u.act?.(() => api.setTaskSession?.(activeTask.id, {agents: [...existing, row.name]}));
      u.setToast?.(row.name + ' assigned to ' + activeTask.title + '.');
    };
    return <div className="people-pnl" data-dock-people="">
      <section className="wssec" aria-label="Agents"><span className="eyebrow"><Icon name="users" size={12} />Agents · {agentRows.length}</span>
        {agentRows.length ? agentRows.map(row => <article className="pcard" key={row.key} data-people-agent={row.name}>
          <div className="pch">{Av ? <Av id={row.name} size={24} /> : null}<span className="pcn"><b>{row.name}</b><em>{row.detail}</em></span><span className="note">{row.status}</span></div>
          <div className="pca">
            <Btn sm onClick={event => executeAction('ui.select', () => messageAgent(row), event)}>Message</Btn>
            <Btn sm onClick={event => executeAction('ui.select', () => assignAgent(row), event)}>Assign to a task</Btn>
            {row.task && <Btn sm ghost onClick={event => executeAction('ui.select', () => u.openTaskFile?.(row.task.id, 'split'), event)}>Open its thread</Btn>}
          </div>
        </article>) : <p className="hint">No agents connected yet. Configure one in Settings › Agents.</p>}
      </section>
      <section className="wssec" aria-label="People"><span className="eyebrow"><Icon name="users" size={12} />People · {people.length + 1}</span>
        <article className="pcard"><div className="pch">{Av ? <Av id={s.profile?.name || 'You'} size={24} /> : null}<span className="pcn"><b>{s.profile?.name || 'You'}</b><em>Owner</em></span></div></article>
        {people.map(person => <article className="pcard" key={person.id || person.email}><div className="pch">{Av ? <Av id={person.name || person.email} size={24} /> : null}<span className="pcn"><b>{person.name || person.email}</b><em>{person.accessRole || 'Member'}</em></span></div></article>)}
      </section>
    </div>;
  }

  // onSave(layout | null, saved?) writes through the Settings owner; the screen that mounts the dock shows its saving and failed states.
  function Dock({rightWidth, onRightWidth, onSave, onLayout, panels, controls, onMapHost, children}) {
    const {useData} = window.UI, s = useData();
    const record = s.dockLayout?.layout || null;
    const ownerSaved = s.dockLayout?.saved || null;
    const [local, setLocal] = React.useState(null);
    const [localSaved, setLocalSaved] = React.useState(null);
    const [tabMenu, setTabMenu] = React.useState(null);
    const savedSet = React.useRef(new Set()), seenRecord = React.useRef(JSON.stringify(record));
    const seenSaved = React.useRef(JSON.stringify(ownerSaved));
    const recordJson = JSON.stringify(record);
    const savedJson = JSON.stringify(ownerSaved);
    if (seenRecord.current !== recordJson) {
      seenRecord.current = recordJson;
      if (savedSet.current.has(recordJson)) savedSet.current.delete(recordJson);
      else {
        savedSet.current.clear();
        if (local) setLocal(null);
      }
    }
    if (seenSaved.current !== savedJson) {
      seenSaved.current = savedJson;
      if (localSaved) setLocalSaved(null);
    }
    const narrow = React.useSyncExternalStore(onResize, () => window.innerWidth < NARROW, () => false);
    const opened = React.useSyncExternalStore(narrowOpen.subscribe, narrowOpen.read, () => false);
    // A panel this screen does not supply (Home has no Thread) is left out of its layout.
    // shortcut: a layout change made on such a screen forgets where that panel sat; it returns to its home side when shown again.
    const absent = panels?.thread ? '' : 'thread';
    const kept = React.useMemo(() => {
      const held = local ? (local.layout ? normalize(local.layout, window.innerWidth) : defaultLayout(window.innerWidth)) : normalize(record, window.innerWidth);
      const gone = absent ? absent.split(',').filter(id => where(held, id)) : [];
      if (!gone.length) return held;
      const next = clone(held);
      for (const id of gone) stripPanel(next, id);
      delete next.savedChanged;
      return next;
    }, [local, recordJson, absent]);
    const current = React.useRef(kept), pending = React.useRef(null);
    if (pending.current === kept) pending.current = null;
    current.current = pending.current || kept;
    const layout = narrow && !opened && !kept.right.c ? {...kept, right: {...kept.right, c: true}} : kept;

    const namedLayouts = () => localSaved ?? ownerSaved ?? {};
    const persistChange = (next, keep = true, nextSaved = undefined) => {
      if (next === current.current && nextSaved === undefined) return;
      current.current = pending.current = next;
      setLocal({layout: next});
      if (nextSaved !== undefined) setLocalSaved(nextSaved);
      // Before the owner's record has loaded a change shows at once and is not saved (the loaded record then replaces it).
      if (keep && s.dockLayout) {
        savedSet.current.add(JSON.stringify(next));
        onSave(next);
      }
    };
    const change = (next, keep = true) => persistChange(next, keep);
    const reset = () => {
      pending.current = null;
      narrowOpen.set(false);
      setLocal({layout: null});
      savedSet.current.add('null');
      onSave(null);
    };
    const reveal = id => {
      if (narrow && (where(current.current, id)?.side || HOME[id]) === 'right') narrowOpen.set(true);
      change(show(current.current, id));
    };
    const fold = side => {
      if (side === 'right' && narrow && !current.current.right.c) narrowOpen.set(!narrowOpen.read());
      else change(toggleDock(current.current, side));
    };

    React.useImperativeHandle(controls, () => ({
      show: reveal,
      hide: id => change(hide(current.current, id)),
      close: id => change(closePanel(current.current, id)),
      place: (id, side, index, pos) => change(place(current.current, id, side, index, pos)),
      visible: id => visible(layout, id),
      setCmd: cmd => change(setCmd(current.current, cmd)),
      reset,
      usePreset: name => {
        if (name === 'Build') { reset(); return; }
        change(presetLayout(name, window.innerWidth));
      },
      showAll: () => change(showAll(current.current)),
      toggleFocus: on => change(setFocus(current.current, on)),
      isFocus: () => Boolean(current.current?.focus),
      saveNamedLayout: name => {
        const clean = String(name || '').trim().slice(0, 80);
        if (!clean) return false;
        const snapshot = {...clone(current.current), savedName: clean};
        delete snapshot.savedChanged;
        const nextSaved = {...namedLayouts(), [clean]: snapshot};
        persistChange(snapshot, true, nextSaved);
        return true;
      },
      savedLayouts: () => Object.keys(namedLayouts()),
      useSavedLayout: name => {
        const found = namedLayouts()[name];
        if (found) change(normalize(found, window.innerWidth));
      },
      movePanel: (id, to, rect) => change(movePanel(current.current, id, to, rect)),
      layout: () => current.current,
    }));

    // Ctrl + . toggles Focus mode; Escape leaves Focus mode when no dialog or menu is open.
    React.useLayoutEffect(() => {
      const onKey = event => {
        const tag = event.target?.tagName;
        const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || event.target?.isContentEditable;
        if (event.key === 'F11' || ((event.ctrlKey || event.metaKey) && !event.altKey && event.key === '.')) {
          event.preventDefault();
          change(setFocus(current.current, undefined));
          return;
        }
        if (event.key === 'Escape' && current.current?.focus && !typing && !window.document.querySelector('.overlay, .context-menu, .dtab-menu-pop')) {
          event.preventDefault();
          change(setFocus(current.current, false));
        }
      };
      window.addEventListener('keydown', onKey);
      return () => window.removeEventListener('keydown', onKey);
    }, [s.dockLayout]);

    const hosts = React.useRef(null);
    if (!hosts.current) {
      hosts.current = {};
      for (const id of Object.keys(PANELS)) {
        const element = document.createElement('div');
        element.className = 'pnl';
        element.dataset.p = id;
        hosts.current[id] = element;
      }
    }
    const root = React.useRef(null), pool = React.useRef(null), bodies = React.useRef({}), floatBodies = React.useRef({}), preview = React.useRef(null), ghost = React.useRef(null);
    React.useLayoutEffect(() => {
      const placed = new Set();
      for (const side of ALL_SIDES) {
        const d = side === 'bottom' ? layout.bottom : layout[side];
        if (!d) continue;
        d.st.forEach((sl, index) => sl.p.forEach(id => {
          placed.add(id);
          const body = layout.focus || d.c ? pool.current : bodies.current[side + ':' + index], host = hosts.current[id];
          if (body && host.parentNode !== body) body.appendChild(host);
          host.hidden = Boolean(layout.focus) || d.c || sl.c || sl.a !== id;
        }));
      }
      for (const f of layout.float || []) {
        placed.add(f.id);
        const body = layout.focus ? pool.current : floatBodies.current[f.id], host = hosts.current[f.id];
        if (body && host.parentNode !== body) body.appendChild(host);
        host.hidden = Boolean(layout.focus);
      }
      for (const id of Object.keys(PANELS)) {
        if (!placed.has(id)) {
          const host = hosts.current[id];
          if (pool.current && host.parentNode !== pool.current) pool.current.appendChild(host);
          host.hidden = true;
        }
      }
    });
    React.useLayoutEffect(() => { onMapHost?.(hosts.current.map); return () => onMapHost?.(null); }, []);

    const drag = React.useRef(null);
    const [dragging, setDragging] = React.useState('');
    const width = side => layout.focus || !layout[side].st.length ? 0 : layout[side].c ? 36 : side === 'left' ? layout.left.w : rightWidth;
    const sash = side => layout.focus || !layout[side].st.length ? 0 : layout[side].c ? 1 : 6;
    const bottomH = !layout.focus && layout.bottom?.st?.length ? (layout.bottom.c ? 36 : layout.bottom.h || BOTTOM.base) : 0;
    React.useLayoutEffect(() => { onLayout?.(layout, {left: width('left') + sash('left'), right: width('right') + sash('right'), bottom: bottomH}); }, [layout, rightWidth]);
    const showPreview = (box, label) => {
      const element = preview.current;
      if (!element) return;
      element.hidden = !box;
      if (!box) return;
      Object.assign(element.style, {left: box[0] + 'px', top: box[1] + 'px', width: box[2] + 'px', height: box[3] + 'px'});
      element.dataset.lab = label;
    };
    const grab = (event, held) => {
      if (event.button) return;
      drag.current = held;
      if (held.kind !== 'tab') root.current.classList.add('sizing');
      if (event.isTrusted && typeof event.currentTarget.setPointerCapture === 'function') event.currentTarget.setPointerCapture(event.pointerId);
    };
    const move = event => {
      const d = drag.current, ws = root.current;
      if (!d || !ws) return;
      const bounds = ws.getBoundingClientRect();
      if (d.kind === 'stack') {
        d.upper = Math.max(34, Math.min(d.total - 34, d.from + event.clientY - d.y));
        d.a.style.flex = d.sum * d.upper / d.total + ' 1 0';
        d.b.style.flex = d.sum * (d.total - d.upper) / d.total + ' 1 0';
      } else if (d.kind === 'sash') {
        if (d.side === 'bottom') {
          const travel = d.y - event.clientY;
          d.value = Math.round(Math.max(BOTTOM.min, Math.min(BOTTOM.max, d.from + travel)));
          ws.style.setProperty('--bh', d.value + 'px');
          return;
        }
        const limits = d.side === 'left' ? LEFT : RIGHT;
        const travel = event.clientX - d.x;
        d.value = Math.round(Math.max(limits.min, Math.min(limits.max, d.side === 'left' ? d.from + travel : d.from - travel)));
        ws.style.setProperty(d.side === 'left' ? '--lw' : '--rw', d.value + 'px');
      } else if (d.kind === 'float') {
        d.nx = Math.max(8, Math.round(d.ox + event.clientX - d.x));
        d.ny = Math.max(8, Math.round(d.oy + event.clientY - d.y));
        if (d.box) { d.box.style.left = d.nx + 'px'; d.box.style.top = d.ny + 'px'; }
      } else if (d.kind === 'tab') {
        if (!d.moved && Math.hypot(event.clientX - d.x, event.clientY - d.y) < 6) return;
        if (!d.moved) { d.moved = true; d.element.dataset.dragged = '1'; setDragging(d.id); }
        if (ghost.current) ghost.current.style.transform = 'translate(' + (event.clientX + 10) + 'px,' + (event.clientY + 10) + 'px)';
        const over = document.elementsFromPoint(event.clientX, event.clientY).map(element => element.closest && element.closest('.dockws .dslot')).find(Boolean);
        if (over) {
          const r = over.getBoundingClientRect(), head = over.querySelector('.dtabs').getBoundingClientRect(), [side, index] = over.dataset.slot.split(':');
          const pos = event.clientY < head.bottom ? 'tab' : event.clientY < r.top + r.height / 2 ? 'above' : 'below';
          d.drop = {side, index: Number(index), pos};
          showPreview([r.left - bounds.left, (pos === 'below' ? r.top + r.height / 2 : r.top) - bounds.top, r.width, pos === 'tab' ? head.height : r.height / 2],
            pos === 'tab' ? 'Tab here' : pos === 'above' ? 'Stack above' : 'Stack below');
          return;
        }
        const x = event.clientX - bounds.left, y = event.clientY - bounds.top;
        const edgeX = Math.min(140, bounds.width * .16), edgeY = Math.min(110, bounds.height * .18);
        const side = x < 0 || y < 0 || x > bounds.width || y > bounds.height ? null
          : x < edgeX ? 'left' : x > bounds.width - edgeX ? 'right' : y > bounds.height - edgeY ? 'bottom' : null;
        d.drop = side ? {side, index: 0, pos: 'dock'} : null;
        if (side === 'bottom') {
          const lw = width('left'), rw = width('right');
          showPreview([lw, bounds.height - BOTTOM.base, Math.max(120, bounds.width - lw - rw), BOTTOM.base], 'Dock bottom');
        } else {
          const wide = side === 'left' ? current.current.left.w : rightWidth;
          showPreview(side ? [side === 'left' ? 0 : bounds.width - wide, 0, wide, bounds.height] : null, 'Dock here');
        }
      }
    };
    const end = event => {
      const d = drag.current;
      if (!d) return;
      drag.current = null;
      root.current.classList.remove('sizing');
      showPreview(null, '');
      if (d.kind === 'stack' && d.upper != null) change(resizeSlots(current.current, d.side, d.index, d.upper, d.total - d.upper));
      if (d.kind === 'sash' && d.value != null) {
        if (d.side === 'left') change(setLeftWidth(current.current, d.value));
        else if (d.side === 'bottom') change(setBottomHeight(current.current, d.value));
        else onRightWidth(d.value);
      }
      if (d.kind === 'float' && d.nx != null) {
        const next = clone(current.current);
        const item = (next.float || []).find(f => f.id === d.id);
        if (item) { item.x = d.nx; item.y = d.ny; change(next); }
      }
      if (d.kind === 'tab') {
        setDragging('');
        window.requestAnimationFrame(() => { delete d.element.dataset.dragged; });
        if (d.moved && d.drop && event.type === 'pointerup') change(place(current.current, d.id, d.drop.side, d.drop.index, d.drop.pos));
      }
    };
    const nudge = (event, side) => {
      if (side === 'bottom') {
        const step = (event.shiftKey ? 48 : 16) * (({ArrowUp: 1, ArrowDown: -1})[event.key] || 0);
        if (!step) return;
        event.preventDefault();
        change(setBottomHeight(current.current, (current.current.bottom?.h || BOTTOM.base) + step));
        return;
      }
      const step = (event.shiftKey ? 48 : 16) * ({ArrowLeft: -1, ArrowRight: 1})[event.key] * (side === 'left' ? 1 : -1);
      if (!step) return;
      event.preventDefault();
      if (side === 'left') change(setLeftWidth(current.current, current.current.left.w + step));
      else onRightWidth(Math.max(RIGHT.min, Math.min(RIGHT.max, rightWidth + step)));
    };
    const openTabMenu = (event, id) => {
      event.preventDefault();
      event.stopPropagation();
      const box = event.currentTarget.getBoundingClientRect();
      setTabMenu({id, x: Math.max(8, Math.min(event.clientX || box.left, window.innerWidth - 196)), y: Math.max(8, Math.min(event.clientY || box.bottom + 4, window.innerHeight - 210))});
    };
    const tab = (id, side, on, stacked) => <button key={id} type="button" className={'dtab' + (on ? ' on' : '')} role={stacked ? 'tab' : undefined} aria-selected={stacked ? on : undefined} aria-label={stacked ? undefined : 'Open ' + PANELS[id][0]} data-tab={id}
      title={PANELS[id][0] + (stacked ? ': drag onto a panel to tab with it, onto its upper or lower half to stack, or right-click for options' : '')}
      onContextMenu={event => openTabMenu(event, id)}
      onPointerDown={event => grab(event, {kind: 'tab', id, element: event.currentTarget, x: event.clientX, y: event.clientY, moved: false})}
      onClick={event => executeAction('ui.select', () => { if (!event.currentTarget.dataset.dragged) reveal(id); }, event)}>
      <Icon name={PANELS[id][1]} size={14} /><span>{PANELS[id][0]}</span></button>;

    const dock = side => {
      const d = side === 'bottom' ? layout.bottom : layout[side];
      if (!d || !d.st.length) return side === 'bottom' ? null : <div className={'dock ' + side + ' empty'} data-dock={side} />;
      const id = side === 'right' ? 'params' : undefined;
      if (d.c) return <div id={id} className={'dock ' + side + ' col'} data-dock={side}>
        <div className="dtabs" role="toolbar" aria-label={side + ' panels'}>{d.st.flatMap(sl => sl.p).map(pid => tab(pid, side, false, false))}
          <button type="button" className="icon-btn dcol" aria-label={'Open the ' + side + ' dock'} title="Open" onClick={event => executeAction('ui.select', () => fold(side), event)}><Icon name="arrow" size={14} /></button></div>
      </div>;
      return <div id={id} className={'dock ' + side + ' stacked'} data-dock={side}><div className="dstack">{d.st.map((sl, index) => <React.Fragment key={index}>
        {index > 0 && <div className="ssash" role="separator" aria-orientation="horizontal" aria-label={'Resize ' + PANELS[d.st[index - 1].a][0] + ' and ' + PANELS[sl.a][0]}
          onPointerDown={event => { event.preventDefault(); const a = event.currentTarget.previousElementSibling, b = event.currentTarget.nextElementSibling; grab(event, {kind: 'stack', side, index: index - 1, a, b, y: event.clientY, from: a.offsetHeight, total: a.offsetHeight + b.offsetHeight, sum: d.st[index - 1].h + sl.h}); }} />}
        <section className={'dslot' + (sl.c ? ' c' : '')} data-slot={side + ':' + index} aria-label={PANELS[sl.a][0]} style={{flex: sl.c ? '0 0 auto' : sl.h + ' 1 0'}}>
          <div className="dtabs st" role="tablist" aria-label={side + ' panel ' + (index + 1)}>{sl.p.map(pid => tab(pid, side, pid === sl.a, true))}<span className="fill" />
            <button type="button" className="icon-btn scol" aria-label={(sl.c ? 'Open ' : 'Fold ') + PANELS[sl.a][0]} title={sl.c ? 'Open' : 'Fold to its header'} onClick={event => executeAction('ui.select', () => change(toggleSlot(current.current, side, index)), event)}><Icon name={sl.c ? 'arrow' : 'minus'} size={13} /></button>
            {index === 0 && <button type="button" className="icon-btn dcol" aria-label={'Fold the ' + side + ' dock to icons'} title="Fold the dock to icons" onClick={event => executeAction('ui.select', () => fold(side), event)}><Icon name="arrange" size={13} /></button>}
          </div>
          <div className="dbody" ref={element => { bodies.current[side + ':' + index] = element; }} />
        </section></React.Fragment>)}</div></div>;
    };

    const edge = (side, label, limits, value) => <div className="sash v" data-sash={side} role="separator" aria-orientation="vertical" aria-label={label} tabIndex={sash(side) === 6 ? 0 : -1}
      aria-valuemin={limits.min} aria-valuemax={limits.max} aria-valuenow={value}
      onPointerDown={event => { if (sash(side) !== 6) return; event.preventDefault(); grab(event, {kind: 'sash', side, x: event.clientX, from: value}); }}
      onDoubleClick={event => executeAction('ui.select', () => side === 'left' ? change(setLeftWidth(current.current, LEFT.base)) : onRightWidth(RIGHT.base), event)}
      onKeyDown={event => nudge(event, side)} />;

    const allPanels = {...panels, people: panels?.people || <PeopleDockView onShow={panels?.onShowWork} />};
    return <div ref={root} id="home-context" className={'dockws' + (dragging ? ' dragging' : '') + (layout.focus ? ' focus-mode' : '')} data-dock-workspace="" onPointerMove={move} onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
      style={{'--lw': width('left') + 'px', '--ls': sash('left') + 'px', '--rs': sash('right') + 'px', '--rw': width('right') + 'px', '--bh': bottomH + 'px'}}>
      {dock('left')}{edge('left', 'Resize the left panel', LEFT, layout.left.w)}
      <div className="dcenter">
        <div className="dcenter-main">{children}</div>
        {!layout.focus && layout.bottom?.st?.length > 0 && <>
          {!layout.bottom.c && <div className="sash h" data-sash="bottom" role="separator" aria-orientation="horizontal" aria-label="Resize the bottom panel" tabIndex={0}
            aria-valuemin={BOTTOM.min} aria-valuemax={BOTTOM.max} aria-valuenow={layout.bottom.h || BOTTOM.base}
            onPointerDown={event => { event.preventDefault(); grab(event, {kind: 'sash', side: 'bottom', y: event.clientY, from: layout.bottom.h || BOTTOM.base}); }}
            onDoubleClick={event => executeAction('ui.select', () => change(setBottomHeight(current.current, BOTTOM.base)), event)}
            onKeyDown={event => nudge(event, 'bottom')} />}
          {dock('bottom')}
        </>}
      </div>
      {edge('right', 'Resize the Properties pane', RIGHT, rightWidth)}{dock('right')}
      {!layout.focus && (layout.float || []).map((f, idx) => <section key={f.id} className="dfloat" data-float-panel={f.id} aria-label={PANELS[f.id][0]}
        style={{left: f.x + 'px', top: f.y + 'px', width: f.w + 'px', height: f.h + 'px', zIndex: 18 + idx}}>
        <div className="dfh" onContextMenu={event => openTabMenu(event, f.id)}
          onPointerDown={event => { if (event.target.closest('button')) return; grab(event, {kind: 'float', id: f.id, ox: f.x, oy: f.y, x: event.clientX, y: event.clientY, box: event.currentTarget.parentElement}); }}>
          <Icon name={PANELS[f.id][1]} size={14} /><b>{PANELS[f.id][0]}</b><span className="fill" />
          <button type="button" className="icon-btn" aria-label={'Dock ' + PANELS[f.id][0]} title="Dock" onClick={event => executeAction('ui.select', () => change(movePanel(current.current, f.id, HOME[f.id] || 'left', undefined)), event)}><Icon name="arrange" size={13} /></button>
          <button type="button" className="icon-btn" aria-label={'Close ' + PANELS[f.id][0]} title="Close panel" onClick={event => executeAction('ui.select', () => change(closePanel(current.current, f.id)), event)}><Icon name="close" size={13} /></button>
        </div>
        <div className="dfb" ref={element => { floatBodies.current[f.id] = element; }} />
      </section>)}
      <div className="pool" ref={pool} hidden />
      <div className="dzp" ref={preview} hidden />
      {dragging && portal(<div className="dghost" ref={ghost}><Icon name={PANELS[dragging][1]} size={14} /><span>{PANELS[dragging][0]}</span></div>, document.body)}
      {layout.focus && portal(<button type="button" className="focusexit" data-focus-exit="" onClick={event => executeAction('ui.select', () => change(setFocus(current.current, false)), event)}>
        <Icon name="fit" size={14} /><span>Leave focus mode · Esc</span>
      </button>, document.body)}
      {tabMenu && portal(<>
        <div className="context-dismiss" onMouseDown={() => setTabMenu(null)} />
        <div className="dtab-menu-pop" role="menu" aria-label={PANELS[tabMenu.id][0] + ' menu'} style={{left: tabMenu.x + 'px', top: tabMenu.y + 'px'}}>
          {[
            ['Float', () => change(floatPanel(current.current, tabMenu.id, {x: tabMenu.x, y: tabMenu.y}))],
            ['Move to the left', () => change(movePanel(current.current, tabMenu.id, 'left', undefined))],
            ['Move to the right', () => change(movePanel(current.current, tabMenu.id, 'right', undefined))],
            ['Move to the bottom', () => change(movePanel(current.current, tabMenu.id, 'bottom', undefined))],
          ].map(([label, act]) => <button key={label} type="button" role="menuitem" onClick={event => executeAction('ui.select', () => { setTabMenu(null); act(); }, event)}>{label}</button>)}
          <hr />
          <button type="button" role="menuitem" onClick={event => executeAction('ui.select', () => { const id = tabMenu.id; setTabMenu(null); change(closePanel(current.current, id)); }, event)}>Close panel</button>
        </div>
      </>, document.body)}
      {Object.keys(PANELS).filter(id => allPanels[id]).map(id => portal(allPanels[id], hosts.current[id], id))}
    </div>;
  }

  // What needs the user, what failed and who is working, from the Workshop, approval and task owners already in Studio state.
  function WorkshopDockView({onShow}) {
    const {useData, useApp, Btn, Av} = window.UI, s = useData(), u = useApp();
    const [busy, setBusy] = React.useState(''), [shown, setShown] = React.useState(''), acting = React.useRef('');
    // The design's Workshop panel: what waits, what failed, who works and the threads; no project picker or search row.
    const all = (s.tasks || []).filter(task => task.status !== 'ARCHIVED'), tasks = all;
    // The room: Workshop messages bound to no task, shown while no session is open. An older page asked for under one
    // graph or account is dropped if it arrives after a switch (the scope key), so another room's messages never show.
    const roomScope = JSON.stringify([s.graph?.id, s.profile?.email, s.profile?.signedIn, s.workshopMessagesScope]);
    const currentScope = React.useRef(roomScope);
    currentScope.current = roomScope;
    const [older, setOlder] = React.useState({scope: roomScope, messages: [], before: null, more: true});
    const previous = older.scope === roomScope ? older : {messages: [], before: null, more: true};
    const bound = new Set((s.tasks || []).flatMap(task => [...(task.messages || []), ...(task.agentLog || [])].map(message => message.id)));
    const room = [...new Map([...previous.messages, ...(s.workshopMessages || [])].map(message => [message.id, message])).values()]
      .filter(message => !bound.has(message.id));
    const roomMore = previous.before ? previous.more : s.workshopMessagesMore;
    const roomShown = !(u.route === 'task-file' && u.task);
    const taskOf = card => all.find(task => [card.taskId, card.task_id, card.work, ...(card.taskIds || [])].includes(task.id));
    const waiting = (s.approvals || []).filter(card => card.status === 'pending')
      .filter((card, index, all) => all.findIndex(row => (row.input_digest || row.id) === (card.input_digest || card.id)) === index);
    const stepTitle = (task, id) => (task.workflow || []).find(node => node.id === id)?.title || (task.sessionOpen ? s.graph.nodes.find(node => node.id === id)?.title : '') || 'A step';
    const failed = tasks.flatMap(task => (task.activity || []).filter(row => row.status === 'Error').map(row => ({task, row})));
    // Only agents working now: a task whose run record says it stopped (interrupted, limit reached) has nobody on it,
    // whatever an older declaration of its last agent still says (founder 2026-11-26).
    const stopped = task => Boolean(task && window.UI.taskRowReason(task));
    const live = (s.agentGraph?.sessions || []).filter(agent => agent.status === 'working' && !stopped(tasks.find(task => task.id === agent.task)));
    const working = [...live.map(agent => ({key: 'live:' + agent.id, name: agent.name, task: tasks.find(task => task.id === agent.task)})),
      ...tasks.filter(task => task.status === 'WIP' && !stopped(task) && !live.some(agent => agent.task === task.id)).map(task => ({key: task.id, name: task.owner || (task.agents || [])[0] || 'Agent', task}))];
    const run = async (key, action) => {
      if (acting.current) return;
      acting.current = key;
      setBusy(key);
      try { await action(); } catch (error) { u.setToast(error.message || 'Could not complete that action. Retry.'); } finally { acting.current = ''; setBusy(''); }
    };
    const decide = (card, word) => run(card.id, async () => {
      if (api.getSnapshot().approvals.find(row => row.id === card.id)?.status !== 'pending') return;
      const result = await (word === 'approve' ? api.approve(card.id) : api.decline(card.id));
      if (result && result.ok !== false) await api.listTasks?.();
    });
    const retry = ({task, row}) => run(task.id + ':' + row.id, async () => {
      if (!task.sessionOpen) await u.openTaskFile(task.id);
      await u.act(() => api.runNode(row.id));
    });
    return <div className="wsb" data-dock-workshop="">
      <section className="wssec" aria-label="Waiting for you"><span className="eyebrow"><Icon name="shield" size={12} />Waiting for you · {waiting.length}</span>
        {waiting.map(card => { const task = taskOf(card), draft = card.draft || card.send;
          const whereLabel = task?.title || (card.path ? card.path.split(/[\\/]/).pop().replace(/\.archhub$/, '') : '');
          const step = card.nodeId && (task?.workflow || []).find(node => node.id === card.nodeId)?.title;
          const what = card.send ? 'Send email to ' + (card.send.to || 'no recipient') : draft ? (/reply/i.test(card.action || '') ? 'Draft a reply' : 'Draft a message') + (card.who ? ' in ' + card.who : '') : step ? 'Run ' + step : card.title;
          return <div className="wsc warn" key={card.id} data-ws-approval={card.id} data-ws-draft={draft ? '' : undefined} title="1 Approve · 2 Reject" tabIndex={0}
            onMouseEnter={event => { if (!window.document.activeElement?.closest?.('input, textarea, select, [contenteditable="true"]')) event.currentTarget.focus({preventScroll: true}); }}
            onKeyDown={event => { if (event.target === event.currentTarget && !event.ctrlKey && !event.metaKey && !event.altKey && (event.key === '1' || event.key === '2')) { event.preventDefault(); decide(card, event.key === '1' ? 'approve' : 'decline'); } }}>
          <div className="wsch"><Av id={card.who || task?.owner || 'Agent'} size={22} /><b>{whereLabel || what}</b><em>{card.who || task?.owner}</em></div>
          {draft && <dl className="ws-draft"><dt>To</dt><dd>{draft.to || 'No recipient'}{draft.cc ? ' · cc ' + draft.cc : ''}</dd>{draft.subject && <><dt>Subject</dt><dd>{draft.subject}</dd></>}</dl>}
          {draft?.body && (shown === card.id ? <pre className="ws-draft-body" data-ws-draft-body="">{draft.body}</pre> : <p className="soft ws-draft-preview">{draft.body.slice(0, 160)}{draft.body.length > 160 ? '…' : ''}</p>)}
          <p>{whereLabel && <>{what} · </>}{card.who ? card.who + ' asked' : 'Asked'}{card.summary ? <> · <span className="soft">{card.summary}</span></> : null}</p>
          <div className="wsca"><Btn p sm disabled={busy === card.id} onClick={event => executeAction('ui.select', () => decide(card, 'approve'), event)}>Approve</Btn>
            <Btn sm disabled={busy === card.id} onClick={event => executeAction('ui.select', () => decide(card, 'decline'), event)}>Reject</Btn>
            <Btn sm ghost aria-expanded={draft ? shown === card.id : undefined} onClick={event => executeAction('ui.select', () => draft ? setShown(shown === card.id ? '' : card.id) : onShow({task, path: card.path, nodeId: card.nodeId, approvalId: card.id}), event)}>{draft && shown === card.id ? 'Hide' : 'Show'}</Btn></div></div>; })}
        {!waiting.length && <p className="hint">Nothing waits for you.</p>}</section>
      {failed.length > 0 && <section className="wssec" aria-label="Failed"><span className="eyebrow"><Icon name="close" size={12} />Failed · {failed.length}</span>
        {failed.map(({task, row}) => <div className="wsc bad" key={task.id + ':' + row.id} data-ws-failed={row.id}>
          <div className="wsch"><Av id={task.owner || (task.agents || [])[0] || 'Agent'} size={22} /><b>{task.title}</b><em>{task.owner || (task.agents || [])[0]}</em></div>
          <p>{stepTitle(task, row.id)} · <span className="bad">{row.error || (typeof row.output === 'string' && row.output) || 'failed'}</span></p>
          <div className="wsca"><Btn p sm disabled={busy === task.id + ':' + row.id} onClick={event => executeAction('ui.select', () => retry({task, row}), event)}>Retry</Btn>
            <Btn sm ghost onClick={event => executeAction('ui.select', () => onShow({task, nodeId: row.id}), event)}>Show</Btn></div></div>)}
        </section>}
      <section className="wssec" aria-label="Working now"><span className="eyebrow"><Icon name="users" size={12} />Working now</span>
        {working.map(({key, name, task}) => { const step = (task?.activity || []).find(row => row.status === 'Running'); return <button type="button" className="wsl" key={key} data-ws-working={key}
          onClick={event => executeAction('ui.select', () => task ? onShow({task}) : u.go('settings/Agents'), event)} title={name}><Av id={shortName(name)} size={22} /><span><b>{shortName(name)}</b>{task ? ' · ' + task.title : ''}{step && <em>On: {stepTitle(task, step.id)}</em>}</span><i className="wsd" /></button>; })}
        </section>
      {(threads => <section className="wssec" aria-label="Threads"><span className="eyebrow"><Icon name="workshop" size={12} />Threads · {threads.length}</span>
        {threads.slice(0, 8).map(({task, messages}) => { const last = [...messages].reverse().find(row => row.who !== 'You') || messages.at(-1);
          return <div className="wst" key={task.id} data-ws-thread={task.id}><button type="button" className="wsl" onClick={event => executeAction('ui.select', () => onShow({task}), event)}>
            <span><b>{task.title}</b><em>{(last.who === 'You' ? 'You' : last.who) + ': ' + last.text}</em></span><span className="note">{messages.length}</span></button>
            <button type="button" className="dx-link wsraw" onClick={event => executeAction('ui.select', () => u.show('Raw log', {id: task.id}), event)}>Raw log</button></div>; })}
        {!threads.length && <p className="hint">No thread has messages yet.</p>}</section>)(tasks.map(task => ({task, messages: window.UI.homeTaskMessages?.(task) || []})).filter(row => row.messages.length))}
      {roomShown && (room.length > 0 || roomMore) && <section className="wssec" aria-label="Workshop room" data-ws-room=""><span className="eyebrow"><Icon name="workshop" size={12} />Workshop room · {room.length}</span>
        {roomMore && <Btn sm ghost onClick={async () => {
          const page = await executeAction('listWorkshopMessages', u, previous.before || s.workshopMessagesBefore);
          if (currentScope.current === roomScope && Array.isArray(page?.messages)) setOlder({scope: roomScope, messages: [...page.messages, ...previous.messages], before: page.next_before, more: page.more});
        }}>Older messages</Btn>}
        {window.UI.Messages && <window.UI.Messages task={{messages: room}} whoIs={window.UI.workshopPeople?.(s).whoIs} />}</section>}
      <p className="hint">Talk to an agent in the composer on its canvas. What it does shows up here and as nodes.</p>
    </div>;
  }

  function CanvasMap({nodes, sizes, area, surfaceSize, view, onView, onZoom}) {
    const W = 168, H = 104, surface = area.current;
    if (!surface || !nodes.length) return <div className="mmap"><p className="mmh">This canvas has no nodes yet.</p></div>;
    const boxes = nodes.map(node => ({node, x: node.x, y: node.y, w: sizes?.get(node.id)?.width || 240, h: sizes?.get(node.id)?.height || 120}));
    const seen = {x: -view.pan.x / view.zoom, y: -view.pan.y / view.zoom, w: (surfaceSize ? surfaceSize.w : surface.clientWidth) / view.zoom, h: (surfaceSize ? surfaceSize.h : surface.clientHeight) / view.zoom};
    const x0 = Math.min(seen.x, ...boxes.map(b => b.x)) - 40, y0 = Math.min(seen.y, ...boxes.map(b => b.y)) - 40;
    const x1 = Math.max(seen.x + seen.w, ...boxes.map(b => b.x + b.w)) + 40, y1 = Math.max(seen.y + seen.h, ...boxes.map(b => b.y + b.h)) + 40;
    const k = Math.min(W / (x1 - x0), H / (y1 - y0));
    const go = event => {
      const r = event.currentTarget.getBoundingClientRect();
      const x = x0 + (event.clientX - r.left) * (W / r.width) / k, y = y0 + (event.clientY - r.top) * (H / r.height) / k;
      onView({zoom: view.zoom, pan: {x: -(x - seen.w / 2) * view.zoom, y: -(y - seen.h / 2) * view.zoom}});
    };
    const state = node => /approval|waiting/i.test(node.status || '') ? ' s-approval' : /error|fail/i.test(node.status || '') ? ' s-failed' : '';
    return <div className="mmap"><svg className="mms" viewBox={'0 0 ' + W + ' ' + H} role="img" aria-label="Mini map of this canvas"
      onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); go(event); }} onPointerMove={event => { if (event.buttons & 1) go(event); }}
      onWheel={event => onZoom(view.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12))}>
      {boxes.map(b => <rect key={b.node.id} className={'mn' + (b.node.type === 'thing.session' ? ' k-session' : '') + state(b.node)} x={(b.x - x0) * k} y={(b.y - y0) * k} width={Math.max(2, b.w * k)} height={Math.max(2, b.h * k)} rx="1.5" />)}
      <rect className="mv" x={(seen.x - x0) * k} y={(seen.y - y0) * k} width={seen.w * k} height={seen.h * k} rx="2" /></svg>
      <p className="mmh">Click or drag to move the view. Wheel to zoom.</p></div>;
  }

  window.UI.Dock = Dock;
  window.UI.DockWorkshop = WorkshopDockView;
  window.UI.DockPeople = PeopleDockView;
  window.UI.CanvasMap = CanvasMap;
})();
