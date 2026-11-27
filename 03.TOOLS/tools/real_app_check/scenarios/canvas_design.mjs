// Canvas and dock panels beside the binding design (archhub-directions) at 1920x1032.
// Same states as the design captures: empty, a 6-node workflow, a node selected, a group expanded
// and collapsed, and the left dock's Map tab. Each step's screenshot is the live half of a pair.
import assert from 'node:assert/strict';

export const steps = [
  'Canvas: an empty workflow at 1920x1032',
  'Canvas: a 6-node workflow',
  'Canvas: one node selected opens its Inspector',
  'Canvas: two nodes grouped, expanded',
  'Canvas: the group collapsed',
  'Dock: the Map tab beside the Library',
];

export default async function run(ctx) {
  const {js, cdp, step, until, rectOf, mouse, native} = ctx;
  const read = (fn, arg) => js('(' + fn.toString() + ')(' + JSON.stringify(arg ?? null) + ')');
  const run = fn => read(fn, null);
  const click = async (selector, count = 1) => {
    const element = 'document.querySelector(' + JSON.stringify(selector) + ')';
    const p = await until(async () => {
      const point = await rectOf(element);
      return point?.w && point.h && await js(element + '?.contains(document.elementFromPoint(' + point.x + ',' + point.y + '))') ? point : null;
    }, Boolean, 20, 150);
    assert.ok(p, 'Missing or covered control: ' + selector);
    await mouse(p, 'left', count);
  };
  const canvasShown = () => until(() => js("!!document.querySelector('[data-screen=\"canvas\"]')?.getClientRects().length"), Boolean, 30, 200);
  // The reused QA profile may hold another run's language and folded docks: English, both docks open.
  const english = () => run(async () => {
    const a = window.ArchHubAPI; await a.getSettings();
    for (const [id, value] of [['Account.App language', 'English'], ['Account.Right-to-left layout', 'Auto']]) {
      const s = a.getSnapshot(), row = s.settings.find(r => r.id === id);
      if (row && row.value !== value) await a.setSetting(row.id, value, s.settingsDestination);
    }
    const s = a.getSnapshot();
    return {dir: document.documentElement.dir, rows: s.settings.filter(r => /language|Right-to-left/i.test(r.id)).map(r => [r.id, r.value])};
  });
  const openCanvas = async () => {
    const label = await run(() => window.UI.productLabel('Canvas', window.ArchHubAPI.getSnapshot().settings));
    await click('nav button[aria-label=' + JSON.stringify(label) + ']');
    assert.ok(await canvasShown(), 'Canvas did not open');
    for (const side of ['left', 'right']) {
      if (await js('!!document.querySelector(\'[data-dock="' + side + '"]\')?.classList.contains("col")')) {
        await click('[data-dock="' + side + '"] button[aria-label="Open the ' + side + ' dock"]');
        await until(() => js('!document.querySelector(\'[data-dock="' + side + '"]\')?.classList.contains("col")'), Boolean, 20, 100);
      }
    }
  };
  // Open a new task the way the app does (its open-task request), so tabs, header and Inspector follow it.
  const openTask = async title => {
    const id = await read(async title => {
      const api = window.ArchHubAPI, t = await api.createTask(title);
      await api.listTasks();
      window.dispatchEvent(new CustomEvent('archhub:open-task', {detail: {task_id: t.taskId}}));
      return t.taskId;
    }, title);
    const shown = await until(() => read(title => window.ArchHubAPI.getSnapshot().graph?.name === title || document.querySelector('[data-design="tab.active"]')?.innerText.includes(title), title), Boolean, 30, 200);
    assert.ok(shown, 'The task did not open: ' + title);
    return {id};
  };
  let ids = [];

  await step(steps[0], async () => {
    const frame = await native({kind: 'window-frame', client: [1920, 1032]});
    assert.ok(frame.client, frame.error || 'Missing native client size');
    await cdp('Emulation.setDeviceMetricsOverride', {width: 1920, height: 1032, screenWidth: 1920, screenHeight: 1032, deviceScaleFactor: 1, mobile: false});
    const dir = await english();
    const finalDir = await until(() => js('document.documentElement.dir'), d => d === 'ltr', 20, 150);
    assert.equal(finalDir, 'ltr', 'The layout stayed right-to-left: ' + JSON.stringify(dir));
    const made = await openTask('QA empty canvas');
    await openCanvas();
    return {pass: true, got: made};
  });

  await step(steps[1], async () => {
    await openTask('Drawing set review');
    const got = await run(async () => {
      const api = window.ArchHubAPI;
      const cat = api.getSnapshot().catalogue || [];
      const want = ['Open model', 'Collect sheets', 'Check', 'Filter', 'Publish', 'Number', 'Convert', 'Count', 'Text'];
      const picks = [];
      for (const w of want) {
        const e = cat.find(c => !picks.includes(c) && (c.name || '').toLowerCase().includes(w.toLowerCase()));
        if (e) picks.push(e);
        if (picks.length === 6) break;
      }
      for (const e of cat) { if (picks.length >= 6) break; if (!picks.includes(e)) picks.push(e); }
      const made = [];
      for (const [i, e] of picks.entries()) {
        const n = await api.addNode(e.id || e.name, {x: 80 + (i % 3) * 340, y: 80 + Math.floor(i / 3) * 360});
        if (n?.id) made.push(n.id);
      }
      const nodes = api.getSnapshot().graph.nodes, refused = [];
      // A socket pair the owner refuses (types differ) is reported, never hidden; the chain keeps the wires it accepts.
      for (let i = 0; i + 1 < made.length; i++) {
        const a = nodes.find(n => n.id === made[i]), b = nodes.find(n => n.id === made[i + 1]);
        const o = a?.outputs?.[0], inp = b?.inputs?.[0];
        if (o && inp) await api.connectSockets({from: a.id, fromPort: o.id, to: b.id, toPort: inp.id}).catch(error => refused.push(a.title + ' → ' + b.title + ': ' + error.message));
      }
      await api.saveSession();
      return {made, names: picks.map(p => p.name), wires: api.getSnapshot().graph.wires.length, refused};
    });
    ids = got.made;
    if (!await js("!!document.querySelector('[data-screen=\"canvas\"]')?.getClientRects().length")) await openCanvas();
    await ctx.clickText('Fit');
    assert.equal(ids.length, 6, 'Six nodes were not placed: ' + JSON.stringify(got));
    assert.ok(await until(() => read(n => n.every(id => document.querySelector('[data-graph-node="' + id + '"]')), ids), Boolean, 30, 200), 'Nodes not rendered');
    return {pass: true, got};
  });

  await step(steps[2], async () => {
    await click('[data-graph-node="' + ids[1] + '"]');
    const sel = await until(() => js('ArchHubAPI.getSnapshot().selectedNodeId ?? document.querySelector(".react-flow__node.selected [data-graph-node]")?.dataset.graphNode'), Boolean, 20, 150);
    return {pass: !!sel, got: {selected: sel}, why: sel ? '' : 'No selection'};
  });

  let group;
  await step(steps[3], async () => {
    group = await read(async ids => {
      const api = window.ArchHubAPI, before = new Set(api.getSnapshot().graph.nodes.map(n => n.id));
      await api.groupNodes([ids[1], ids[2]]);
      const g = api.getSnapshot().graph.nodes.find(n => !before.has(n.id));
      if (g?.collapsed) await api.setGroupCollapsed(g.id, false);
      return g?.id;
    }, ids);
    return {pass: !!group, got: {group}, why: group ? '' : 'Group not made'};
  });

  await step(steps[4], async () => {
    await read(id => window.ArchHubAPI.setGroupCollapsed(id, true), group);
    const c = await until(() => read(id => window.ArchHubAPI.getSnapshot().graph.nodes.find(n => n.id === id)?.collapsed, group), Boolean, 20, 150);
    return {pass: !!c, got: {collapsed: c}};
  });

  await step(steps[5], async () => {
    const ok = await ctx.clickText('Map', 'button,[role=tab]');
    return {pass: ok, why: ok ? '' : 'No Map tab'};
  });
}
