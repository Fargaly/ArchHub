// Canvas dock: panels tab together, stack with a splitter and fold to their header. Behaviour and look are ported from the
// approved prototype (archhub-directions app.js, "the layout is the user's"); settings_owner.dock_layout owns the record.
(() => {
  const PANELS = {workshop: ['Workshop', 'workshop'], library: ['Library', 'library'], map: ['Map', 'canvas'], insp: ['Inspector', 'settings']};
  const HOME = {workshop: 'left', library: 'left', map: 'left', insp: 'right'};
  const SIDES = ['left', 'right'];
  const LEFT = {min: 200, max: 520, base: 268}, RIGHT = {min: 280, max: 480, base: 320};
  const clone = layout => JSON.parse(JSON.stringify(layout));
  const slot = id => ({p: [id], a: id, h: 1, c: false});
  const NARROW = 1280;  // below this window width the right dock starts folded to icons, so the canvas keeps its room
  // Workshop over Library|Map on the left; the Inspector on the right, open as before the dock.
  const defaultLayout = width => ({
    left: {w: LEFT.base, c: false, st: [{p: ['workshop'], a: 'workshop', h: 1.15, c: false}, {p: ['library', 'map'], a: 'library', h: 1, c: false}]},
    right: {c: false, st: [slot('insp')]}});
  // A held record becomes a layout where every known panel sits in exactly one place.
  const normalize = (held, width) => {
    if (!held || !held.left || !held.right) return defaultLayout(width);
    const seen = new Set();
    const dock = side => ({
      ...(side === 'left' ? {w: Math.max(LEFT.min, Math.min(LEFT.max, Math.round(held.left.w) || LEFT.base))} : {}),
      c: held[side].c === true,
      st: (Array.isArray(held[side].st) ? held[side].st : []).map(sl => {
        const p = (Array.isArray(sl.p) ? sl.p : []).filter(id => PANELS[id] && !seen.has(id) && seen.add(id));
        return {p, a: p.includes(sl.a) ? sl.a : p[0], h: sl.h > 0 ? Math.max(.05, Math.min(20, sl.h)) : 1, c: sl.c === true};
      }).filter(sl => sl.p.length)});
    const next = {left: dock('left'), right: dock('right')};
    for (const id of Object.keys(PANELS)) if (!seen.has(id)) {
      const st = next[HOME[id]].st;
      if (st.length) st[st.length - 1].p.push(id); else st.push(slot(id));
    }
    return next;
  };
  const where = (layout, id) => {
    for (const side of SIDES) {
      const index = layout[side].st.findIndex(sl => sl.p.includes(id));
      if (index >= 0) return {side, index};
    }
    return null;
  };
  const visible = (layout, id) => {
    const at = where(layout, id);
    return !!at && !layout[at.side].c && !layout[at.side].st[at.index].c && layout[at.side].st[at.index].a === id;
  };
  // pos: 'tab' joins the slot at index; 'above' / 'below' stack a new slot beside it; 'dock' joins the dock's last slot.
  const place = (layout, id, side, index, pos) => {
    const next = clone(layout), st = next[side].st, target = pos === 'dock' ? st[st.length - 1] : st[index];
    if (target && target.p.length === 1 && target.p[0] === id) return layout;
    for (const s of SIDES) for (const sl of next[s].st) {
      sl.p = sl.p.filter(panel => panel !== id);
      if (sl.a === id) sl.a = sl.p[0];
    }
    if (target && (pos === 'tab' || pos === 'dock')) { target.p.push(id); target.a = id; target.c = false; }
    else st.splice(target ? st.indexOf(target) + (pos === 'below' ? 1 : 0) : st.length, 0, slot(id));
    for (const s of SIDES) next[s].st = next[s].st.filter(sl => sl.p.length);
    next[side].c = false;
    return next;
  };
  const show = (layout, id) => {
    const at = where(layout, id);
    if (!at || visible(layout, id)) return layout;
    const next = clone(layout), sl = next[at.side].st[at.index];
    sl.a = id; sl.c = false; next[at.side].c = false;
    return next;
  };
  const hide = (layout, id) => {
    if (!visible(layout, id)) return layout;
    const at = where(layout, id), next = clone(layout);
    next[at.side].st[at.index].c = true;
    return next;
  };
  const toggleSlot = (layout, side, index) => {
    const next = clone(layout);
    next[side].st[index].c = !next[side].st[index].c;
    return next;
  };
  const toggleDock = (layout, side) => {
    const next = clone(layout);
    next[side].c = !next[side].c;
    return next;
  };
  // Two stacked neighbours share their height by the dragged pixel sizes; each keeps at least its 34 px header.
  const resizeSlots = (layout, side, index, upper, lower) => {
    const next = clone(layout), a = next[side].st[index], b = next[side].st[index + 1];
    const total = upper + lower, kept = Math.max(34, Math.min(total - 34, upper)), sum = a.h + b.h;  // other slots keep their share
    a.h = Math.max(.05, Math.round(sum * kept / total * 1000) / 1000);
    b.h = Math.max(.05, Math.round((sum - a.h) * 1000) / 1000);
    return next;
  };
  const setLeftWidth = (layout, width) => ({...layout, left: {...layout.left, w: Math.max(LEFT.min, Math.min(LEFT.max, Math.round(width)))}});
  window.UI = window.UI || {};
  // The Build preset is the default layout. A layout is named by where its panels sit; widths and folds do not rename it.
  const places = layout => JSON.stringify(SIDES.map(side => layout[side].st.map(sl => sl.p)));
  const presetName = layout => places(layout) === places(defaultLayout(NARROW)) ? 'Build' : 'Build (changed)';
  window.UI.dockModel = {PANELS, LEFT, RIGHT, defaultLayout, normalize, where, visible, place, show, hide, toggleSlot, toggleDock, resizeSlots, setLeftWidth, presetName};
  if (typeof React === 'undefined') return;  // the layout rules above also load alone, without a page

  const api = window.ArchHubAPI, {executeAction} = api, Icon = window.AHIcon, portal = window.ReactDOM.createPortal;
  // "Claude Code / 00.ARCHUB / session-62fdf0706b09" reads "Claude Code · 62fdf0": two sessions of one app are told apart, no raw id.
  const shortName = name => { const [app, , id] = String(name || '').split(' / '); return id ? app + ' \u00b7 ' + id.replace(/^session-/, '').slice(0, 6) : String(name || ''); };
  const onResize = notify => { window.addEventListener('resize', notify); return () => window.removeEventListener('resize', notify); };  // the window width as a React store
  // Below 1280 px he may open the folded right dock. That choice lives outside any one Dock, so going Home and back (two Dock
  // mounts) keeps it; it ends when the window is wide again (read as closed from then on) or on Reset.
  const narrowOpen = {held: false, listeners: new Set(),
    subscribe(notify) { narrowOpen.listeners.add(notify); return () => narrowOpen.listeners.delete(notify); },
    read() { if (window.innerWidth >= NARROW) narrowOpen.held = false; return narrowOpen.held; },
    set(value) { if (value === narrowOpen.read()) return; narrowOpen.held = value; narrowOpen.listeners.forEach(notify => notify()); }};

  // onSave(layout | null) writes through the Settings owner; the screen that mounts the dock shows its saving and failed states.
  function Dock({face, rightWidth, onRightWidth, onSave, onLayout, panels, controls, onMapHost, children}) {
    const {useData} = window.UI, s = useData();
    // The layout is one user setting (founder 2026-11-18): Home and every session show the same docks, widths and folds.
    // The owner holds that one record (and reads an older per-session record as the layout he arranged last).
    const record = s.dockLayout?.layout || null;
    // The user's edits show at once and stay while he moves between Home and sessions; the owner holds the same record.
    const [local, setLocal] = React.useState(null);
    // Below 1280 px the right dock is SHOWN folded so the canvas keeps its room. That is display only: it is never saved folded,
    // and it is back as he set it when the window is wide again. He can still open it while the window is narrow.
    const narrow = React.useSyncExternalStore(onResize, () => window.innerWidth < NARROW, () => false);
    const opened = React.useSyncExternalStore(narrowOpen.subscribe, narrowOpen.read, () => false);
    const kept = React.useMemo(() => local ? local.layout || defaultLayout(window.innerWidth) : normalize(record, window.innerWidth), [local, JSON.stringify(record)]);
    // pending: the layout a change asked for, until it renders. A change during a pending fold transition builds on it.
    const current = React.useRef(kept), pending = React.useRef(null);
    if (pending.current === kept) pending.current = null;
    current.current = pending.current || kept;
    const layout = narrow && !opened && !kept.right.c ? {...kept, right: {...kept.right, c: true}} : kept;
    const change = (next, keep = true) => {
      // Until the owner's record has arrived a change would replace his saved layout with the default: it waits for the record.
      if (next === current.current || !s.dockLayout) return;
      current.current = pending.current = next;
      setLocal({layout: next});
      if (keep) onSave(next);
    };
    const reset = () => { pending.current = null; narrowOpen.set(false); setLocal({layout: null}); onSave(null); };  // no layout of his own: the default
    const reveal = id => {
      if (narrow && where(current.current, id)?.side === 'right') narrowOpen.set(true);
      const held = folded.current || [];
      if (!held.length) { change(show(current.current, id)); return; }
      // While the thread shows, its fold is display only: what is saved is built from his own layout (those sides as he had them);
      // the screen keeps the thread's fold on every side but the one now opened.
      const saved = show({...current.current, ...Object.fromEntries(held.map(side => [side, {...current.current[side], c: false}]))}, id);
      folded.current = held.filter(side => side !== where(saved, id)?.side);
      change({...saved, ...Object.fromEntries(folded.current.map(side => [side, {...saved[side], c: true}]))}, false);
      if (s.dockLayout) onSave(saved);
    };
    const fold = side => { if (side === 'right' && narrow && !current.current.right.c) narrowOpen.set(!narrowOpen.read()); else change(toggleDock(current.current, side)); };
    React.useImperativeHandle(controls, () => ({
      show: reveal,
      hide: id => change(hide(current.current, id)),
      visible: id => visible(layout, id),
      reset,
    }));
    // The thread beside the canvas needs the room: open docks fold while it shows and come back after (not saved).
    // As a transition, after the thread's own frame: folding synchronously inside the click doubled its commit.
    const folded = React.useRef(null);
    React.useLayoutEffect(() => {
      const held = current.current;
      const set = (sides, c) => React.startTransition(() => change({...held, ...Object.fromEntries(sides.map(side => [side, {...held[side], c}]))}, false));
      if (face === 'split' && !folded.current) {
        folded.current = SIDES.filter(side => !held[side].c && held[side].st.length);
        if (folded.current.length) set(folded.current, true);
      } else if (face !== 'split' && folded.current) {
        const sides = folded.current;
        folded.current = null;
        if (sides.length) set(sides, false);
      }
    }, [face]);

    // One lasting element per panel: moving a panel between slots moves its element, so its content keeps its state.
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
    const root = React.useRef(null), pool = React.useRef(null), bodies = React.useRef({}), preview = React.useRef(null), ghost = React.useRef(null);
    React.useLayoutEffect(() => {
      for (const side of SIDES) layout[side].st.forEach((sl, index) => sl.p.forEach(id => {
        const body = layout[side].c ? pool.current : bodies.current[side + ':' + index], host = hosts.current[id];
        if (body && host.parentNode !== body) body.appendChild(host);
        host.hidden = layout[side].c || sl.c || sl.a !== id;
      }));
    });
    React.useLayoutEffect(() => { onMapHost?.(hosts.current.map); return () => onMapHost?.(null); }, []);

    const drag = React.useRef(null);
    const [dragging, setDragging] = React.useState('');
    const width = side => !layout[side].st.length ? 0 : layout[side].c ? 36 : side === 'left' ? layout.left.w : rightWidth;
    const sash = side => !layout[side].st.length ? 0 : layout[side].c ? 1 : 6;
    // The screen learns the layout and the room each dock takes, so what floats over the canvas stays over the canvas.
    React.useLayoutEffect(() => { onLayout?.(layout, {left: width('left') + sash('left'), right: width('right') + sash('right')}); }, [layout, rightWidth]);
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
      if (held.kind !== 'tab') root.current.classList.add('sizing');  // no easing while a splitter follows the pointer
      event.currentTarget.setPointerCapture(event.pointerId);
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
        const limits = d.side === 'left' ? LEFT : RIGHT;
        // Relative to where the press landed: the pane follows the pointer's travel, not the pointer's position, so
        // grabbing the 6 px sash anywhere never jumps the width by the grab offset (it was 3 px: 378 for 375).
        const travel = event.clientX - d.x;
        d.value = Math.round(Math.max(limits.min, Math.min(limits.max, d.side === 'left' ? d.from + travel : d.from - travel)));
        ws.style.setProperty(d.side === 'left' ? '--lw' : '--rw', d.value + 'px');
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
        // Outside every panel: the left and right edges take the panel into that dock.
        const x = event.clientX - bounds.left, y = event.clientY - bounds.top, edge = Math.min(140, bounds.width * .16);
        const side = x < 0 || y < 0 || x > bounds.width || y > bounds.height ? null : x < edge ? 'left' : x > bounds.width - edge ? 'right' : null;
        d.drop = side ? {side, index: 0, pos: 'dock'} : null;
        const wide = side === 'left' ? current.current.left.w : rightWidth;
        showPreview(side ? [side === 'left' ? 0 : bounds.width - wide, 0, wide, bounds.height] : null, 'Dock here');
      }
    };
    const end = event => {
      const d = drag.current;
      if (!d) return;
      drag.current = null;
      root.current.classList.remove('sizing');
      showPreview(null, '');
      if (d.kind === 'stack' && d.upper != null) change(resizeSlots(current.current, d.side, d.index, d.upper, d.total - d.upper));
      if (d.kind === 'sash' && d.value != null) { if (d.side === 'left') change(setLeftWidth(current.current, d.value)); else onRightWidth(d.value); }
      if (d.kind === 'tab') {
        setDragging('');
        window.requestAnimationFrame(() => { delete d.element.dataset.dragged; });  // after the click that ends the drag
        if (d.moved && d.drop && event.type !== 'pointercancel') change(place(current.current, d.id, d.drop.side, d.drop.index, d.drop.pos));
      }
    };
    const nudge = (event, side) => {
      const step = (event.shiftKey ? 48 : 16) * ({ArrowLeft: -1, ArrowRight: 1})[event.key] * (side === 'left' ? 1 : -1);
      if (!step) return;
      event.preventDefault();
      if (side === 'left') change(setLeftWidth(current.current, current.current.left.w + step));
      else onRightWidth(Math.max(RIGHT.min, Math.min(RIGHT.max, rightWidth + step)));
    };
    const tab = (id, side, on, stacked) => <button key={id} type="button" className={'dtab' + (on ? ' on' : '')} role={stacked ? 'tab' : undefined} aria-selected={stacked ? on : undefined} aria-label={stacked ? undefined : 'Open ' + PANELS[id][0]} data-tab={id}
      title={PANELS[id][0] + (stacked ? ': drag onto a panel to tab with it, or onto its upper or lower half to stack' : '')}
      onPointerDown={event => grab(event, {kind: 'tab', id, element: event.currentTarget, x: event.clientX, y: event.clientY, moved: false})}
      onClick={event => executeAction('ui.select', () => { if (!event.currentTarget.dataset.dragged) reveal(id); }, event)}>
      <Icon name={PANELS[id][1]} size={14} /><span>{PANELS[id][0]}</span></button>;
    const dock = side => {
      const d = layout[side];
      if (!d.st.length) return <div className={'dock ' + side + ' empty'} data-dock={side} />;
      const id = side === 'right' ? 'params' : undefined;  // the Properties column keeps its id
      if (d.c) return <div id={id} className={'dock ' + side + ' col'} data-dock={side}>
        <div className="dtabs" role="toolbar" aria-label={side + ' panels'}>{d.st.flatMap(sl => sl.p).map(id => tab(id, side, false, false))}
          <button type="button" className="icon-btn dcol" aria-label={'Open the ' + side + ' dock'} title="Open" onClick={event => executeAction('ui.select', () => fold(side), event)}><Icon name="arrow" size={14} /></button></div>
      </div>;
      return <div id={id} className={'dock ' + side + ' stacked'} data-dock={side}><div className="dstack">{d.st.map((sl, index) => <React.Fragment key={index}>
        {index > 0 && <div className="ssash" role="separator" aria-orientation="horizontal" aria-label={'Resize ' + PANELS[d.st[index - 1].a][0] + ' and ' + PANELS[sl.a][0]}
          onPointerDown={event => { event.preventDefault(); const a = event.currentTarget.previousElementSibling, b = event.currentTarget.nextElementSibling; grab(event, {kind: 'stack', side, index: index - 1, a, b, y: event.clientY, from: a.offsetHeight, total: a.offsetHeight + b.offsetHeight, sum: d.st[index - 1].h + sl.h}); }} />}
        <section className={'dslot' + (sl.c ? ' c' : '')} data-slot={side + ':' + index} aria-label={PANELS[sl.a][0]} style={{flex: sl.c ? '0 0 auto' : sl.h + ' 1 0'}}>
          <div className="dtabs st" role="tablist" aria-label={side + ' panel ' + (index + 1)}>{sl.p.map(id => tab(id, side, id === sl.a, true))}<span className="fill" />
            <button type="button" className="icon-btn scol" aria-label={(sl.c ? 'Open ' : 'Fold ') + PANELS[sl.a][0]} title={sl.c ? 'Open' : 'Fold to its header'} onClick={event => executeAction('ui.select', () => change(toggleSlot(current.current, side, index)), event)}><Icon name={sl.c ? 'arrow' : 'minus'} size={13} /></button>
            {index === 0 && <button type="button" className="icon-btn dcol" aria-label={'Fold the ' + side + ' dock to icons'} title="Fold the dock to icons" onClick={event => executeAction('ui.select', () => fold(side), event)}><Icon name="arrange" size={13} /></button>}
          </div>
          <div className="dbody" ref={element => { bodies.current[side + ':' + index] = element; }} />
        </section></React.Fragment>)}</div></div>;
    };
    const edge = (side, label, limits, value) => <div className="sash v" data-sash={side} role="separator" aria-orientation="vertical" aria-label={label} tabIndex={sash(side) === 6 ? 0 : -1}
      aria-valuemin={limits.min} aria-valuemax={limits.max} aria-valuenow={value}
      onPointerDown={event => { if (sash(side) !== 6) return; event.preventDefault(); grab(event, {kind: 'sash', side, x: event.clientX, from: value}); }}
      onDoubleClick={() => executeAction('ui.select', () => side === 'left' ? change(setLeftWidth(current.current, LEFT.base)) : onRightWidth(RIGHT.base))}
      onKeyDown={event => nudge(event, side)} />;
    return <div ref={root} id="home-context" className={'dockws' + (dragging ? ' dragging' : '')} data-dock-workspace="" onPointerMove={move} onPointerUp={end} onPointerCancel={end}
      style={{'--lw': width('left') + 'px', '--ls': sash('left') + 'px', '--rs': sash('right') + 'px', '--rw': width('right') + 'px'}}>
      {dock('left')}{edge('left', 'Resize the left panel', LEFT, layout.left.w)}
      <div className="dcenter">{children}</div>
      {edge('right', 'Resize the Properties pane', RIGHT, rightWidth)}{dock('right')}
      <div className="pool" ref={pool} hidden />
      <div className="dzp" ref={preview} hidden />
      {dragging && portal(<div className="dghost" ref={ghost}><Icon name={PANELS[dragging][1]} size={14} /><span>{PANELS[dragging][0]}</span></div>, document.body)}
      {Object.keys(PANELS).filter(id => panels[id]).map(id => portal(panels[id], hosts.current[id], id))}
    </div>;
  }

  // What needs the user, what failed and who is working, from the Workshop, approval and task owners already in Studio state.
  function WorkshopPanel({onShow}) {
    const {useData, useApp, Btn, Av} = window.UI, s = useData(), u = useApp();
    const [busy, setBusy] = React.useState(''), [shown, setShown] = React.useState(''), acting = React.useRef('');  // the ref holds a second click in the same frame
    const tasks = (s.tasks || []).filter(task => task.status !== 'ARCHIVED');
    const taskOf = card => tasks.find(task => [card.taskId, card.task_id, card.work, ...(card.taskIds || [])].includes(task.id));
    const waiting = (s.approvals || []).filter(card => card.status === 'pending')
      .filter((card, index, all) => all.findIndex(row => (row.input_digest || row.id) === (card.input_digest || card.id)) === index);
    const stepTitle = (task, id) => (task.workflow || []).find(node => node.id === id)?.title || (task.sessionOpen ? s.graph.nodes.find(node => node.id === id)?.title : '') || 'A step';
    const failed = tasks.flatMap(task => (task.activity || []).filter(row => row.status === 'Error').map(row => ({task, row})));
    const live = (s.agentGraph?.sessions || []).filter(agent => agent.status === 'working');
    const working = [...live.map(agent => ({key: 'live:' + agent.id, name: agent.name, task: tasks.find(task => task.id === agent.task)})),
      ...tasks.filter(task => task.status === 'WIP' && !live.some(agent => agent.task === task.id)).map(task => ({key: task.id, name: task.owner || (task.agents || [])[0] || 'Agent', task}))];
    const run = async (key, action) => {
      if (acting.current) return;
      acting.current = key;
      setBusy(key);
      try { await action(); } catch (error) { u.setToast(error.message || 'Could not complete that action. Retry.'); } finally { acting.current = ''; setBusy(''); }
    };
    // The one approval path: api.approve / api.decline answer through hook_decision.decide.
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
        {waiting.map(card => { const task = taskOf(card), draft = card.draft || card.send;  // the held mail: a draft, or a real send
          // In plain words: what will change and where (the session or file, the step), who asked and why; a draft shows its own text.
          const where = task?.title || (card.path ? card.path.split(/[\\/]/).pop().replace(/\.archhub$/, '') : '');
          const step = card.nodeId && (task?.workflow || []).find(node => node.id === card.nodeId)?.title;
          const what = card.send ? 'Send email to ' + (card.send.to || 'no recipient') : draft ? (/reply/i.test(card.action || '') ? 'Draft a reply' : 'Draft a message') + (card.who ? ' in ' + card.who : '') : step ? 'Run ' + step : card.title;
          return <div className="wsc warn" key={card.id} data-ws-approval={card.id} data-ws-draft={draft ? '' : undefined} title="1 Approve · 2 Reject" tabIndex={0}
            // Keys 1 and 2 answer the card under the pointer (design): the card takes the focus on hover, never away from typing.
            onMouseEnter={event => { if (!window.document.activeElement?.closest?.('input, textarea, select, [contenteditable="true"]')) event.currentTarget.focus({preventScroll: true}); }}
            onKeyDown={event => { if (event.target === event.currentTarget && !event.ctrlKey && !event.metaKey && !event.altKey && (event.key === '1' || event.key === '2')) { event.preventDefault(); decide(card, event.key === '1' ? 'approve' : 'decline'); } }}>
          <div className="wsch"><Av id={card.who || task?.owner || 'Agent'} size={22} /><b>{where || what}</b><em>{card.who || task?.owner}</em></div>
          {draft && <dl className="ws-draft"><dt>To</dt><dd>{draft.to || 'No recipient'}{draft.cc ? ' · cc ' + draft.cc : ''}</dd>{draft.subject && <><dt>Subject</dt><dd>{draft.subject}</dd></>}</dl>}
          {draft?.body && (shown === card.id ? <pre className="ws-draft-body" data-ws-draft-body="">{draft.body}</pre> : <p className="soft ws-draft-preview">{draft.body.slice(0, 160)}{draft.body.length > 160 ? '…' : ''}</p>)}
          <p>{where && <>{what} · </>}{card.who ? card.who + ' asked' : 'Asked'}{card.summary ? <> · <span className="soft">{card.summary}</span></> : null}</p>
          <div className="wsca"><Btn p sm disabled={busy === card.id} onClick={event => executeAction('ui.select', () => decide(card, 'approve'), event)}>Approve</Btn>
            <Btn sm disabled={busy === card.id} onClick={event => executeAction('ui.select', () => decide(card, 'decline'), event)}>Reject</Btn>
            <Btn sm ghost aria-expanded={draft ? shown === card.id : undefined} onClick={event => executeAction('ui.select', () => draft ? setShown(shown === card.id ? '' : card.id) : onShow({task, path: card.path, nodeId: card.nodeId, approvalId: card.id}), event)}>{draft && shown === card.id ? 'Hide' : 'Show'}</Btn></div></div>; })}
        {!waiting.length && <p className="hint">Nothing waits for you.</p>}</section>
      {failed.length > 0 && <section className="wssec" aria-label="Failed"><span className="eyebrow"><Icon name="close" size={12} />Failed · {failed.length}</span>
        {failed.map(({task, row}) => <div className="wsc bad" key={task.id + ':' + row.id} data-ws-failed={row.id}>
          <div className="wsch"><Av id={task.owner || (task.agents || [])[0] || 'Agent'} size={22} /><b>{task.title}</b><em>{task.owner || (task.agents || [])[0]}</em></div>
          <p>{stepTitle(task, row.id)} · <span className="bad">{row.error || (typeof row.output === "string" && row.output) || "failed"}</span></p>
          <div className="wsca"><Btn p sm disabled={busy === task.id + ':' + row.id} onClick={event => executeAction('ui.select', () => retry({task, row}), event)}>Retry</Btn>
            <Btn sm ghost onClick={event => executeAction('ui.select', () => onShow({task, nodeId: row.id}), event)}>Show</Btn></div></div>)}
        </section>}
      <section className="wssec" aria-label="Working now"><span className="eyebrow"><Icon name="users" size={12} />Working now</span>
        {working.map(({key, name, task}) => { const step = (task?.activity || []).find(row => row.status === 'Running'); return <button type="button" className="wsl" key={key} data-ws-working={key}
          onClick={event => executeAction('ui.select', () => task ? onShow({task}) : u.go('settings/Agents'), event)} title={name}><Av id={shortName(name)} size={22} /><span><b>{shortName(name)}</b>{task ? ' · ' + task.title : ''}{step && <em>On: {stepTitle(task, step.id)}</em>}</span><i className="wsd" /></button>; })}
        </section>
      {/* Threads (design): every task with messages, the other side's last line and the count; a row opens its thread, Raw log its full record. */}
      {(threads => <section className="wssec" aria-label="Threads"><span className="eyebrow"><Icon name="workshop" size={12} />Threads · {threads.length}</span>
        {threads.slice(0, 8).map(({task, messages}) => { const last = [...messages].reverse().find(row => row.who !== 'You') || messages.at(-1);
          return <div className="wst" key={task.id} data-ws-thread={task.id}><button type="button" className="wsl" onClick={event => executeAction('ui.select', () => onShow({task}), event)}>
            <span><b>{task.title}</b><em>{(last.who === 'You' ? 'You' : last.who) + ': ' + last.text}</em></span><span className="note">{messages.length}</span></button>
            <button type="button" className="dx-link wsraw" onClick={event => executeAction('ui.select', () => u.show('Raw log', {id: task.id}), event)}>Raw log</button></div>; })}
        {!threads.length && <p className="hint">No thread has messages yet.</p>}</section>)(tasks.map(task => ({task, messages: window.UI.homeTaskMessages?.(task) || []})).filter(row => row.messages.length))}
      <p className="hint">Talk to an agent in the composer on its canvas. What it does shows up here and as nodes.</p>
    </div>;
  }

  // Mini map of the open canvas: real node boxes and the real view; click or drag moves the view, the wheel zooms.
  // sizes: the canvas engine's measured card sizes by id, so a pan or zoom frame reads no layout.
  // surfaceSize: the canvas size the Canvas observes ({w, h}), so drawing the map reads no layout; without it (Home's
  // map, or the frame before the first observation) the surface is measured once.
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
  window.UI.DockWorkshop = WorkshopPanel;
  window.UI.CanvasMap = CanvasMap;
})();
