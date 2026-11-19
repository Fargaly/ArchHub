// Court 11 (performance) on the compiled Studio over a seeded isolated server: real CDP input, real owners.
// Prints one JSON line of metrics: frame p95 (pan/zoom/drag), selection feedback, Workshop fold, open canvas,
// long tasks and requests in an idle window. The Python court asserts the budgets.
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const p95 = list => { const s = [...list].sort((a, b) => a - b); return s.length ? +s[Math.min(s.length - 1, Math.ceil(s.length * .95) - 1)].toFixed(1) : null; };

async function court() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const idleMs = input.idleMs || 20000;
  const newest = pattern => fs.readdirSync(input.browserCache).filter(name => pattern.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = newest(/^chromium-\d+$/), shell = newest(/^chromium_headless_shell-\d+$/);
  const executablePath = full ? path.join(input.browserCache, full, 'chrome-win64/chrome.exe') : path.join(input.browserCache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe');
  const browser = await chromium.launch({headless: true, executablePath});
  const out = {errors: []};
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 900}});
    await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
    await context.addInitScript(() => {
      window.__perf = {long: [], loaf: [], frames: null};
      // Long animation frames name the scripts (and rendering) behind a slow frame that no single long task shows.
      try { new window.PerformanceObserver(list => { for (const e of list.getEntries()) if (e.duration > 50) window.__perf.loaf.push({ms: Math.round(e.duration), render: Math.round(e.renderStart ? e.startTime + e.duration - e.renderStart : 0),
        scripts: (e.scripts || []).filter(x => x.duration > 5).map(x => (x.invoker || '') + ' ' + (x.sourceFunctionName || '') + ' ' + String(x.sourceURL || '').split('/').pop() + ' ' + Math.round(x.duration))}); }).observe({type: 'long-animation-frame', buffered: true}); } catch {}
      new window.PerformanceObserver(list => { for (const e of list.getEntries()) window.__perf.long.push(Math.round(e.duration)); }).observe({type: 'longtask', buffered: true});
      window.__perfFrames = () => { const f = []; let last = window.performance.now(), on = true; const tick = t => { f.push(t - last); last = t; if (on) requestAnimationFrame(tick); }; requestAnimationFrame(tick); return () => { on = false; return f.slice(1); }; };
    });
    const page = await context.newPage();
    page.on('pageerror', error => out.errors.push(error.message));
    const requests = [];
    page.on('request', request => {
      const url = new URL(request.url()); let key = url.pathname;
      try { const body = JSON.parse(request.postData() || '{}'); if (body.function) key += '#' + body.function; else if (body.action) key += '#' + body.action; } catch {}
      requests.push({at: Date.now(), key});
    });
    const responses = [];
    page.on('response', response => responses.push({at: Date.now(), status: response.status()}));
    const cdp = await context.newCDPSession(page);
    const mouse = (type, x, y, extra = {}) => cdp.send('Input.dispatchMouseEvent', {type, x, y, ...extra});
    await cdp.send('Performance.enable');
    const metric = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m => [m.name, m.value * 1000]));
        out.splitPerFrameMs = {};
    // Frame p95 (rAF deltas, vsync-bound) and main-thread work per frame (CDP TaskDuration), which shows cost below one vsync.
    out.workPerFrameMs = {};
    // Self time by function over one step (input.profile names it): where the work goes.
    const profiled = async (name, step) => {
      if (input.profile !== name) return step();
      await cdp.send('Profiler.enable'); await cdp.send('Profiler.setSamplingInterval', {interval: 200}); await cdp.send('Profiler.start');
      const result = await step();
      const {profile} = await cdp.send('Profiler.stop'), self = {}, gap = profile.timeDeltas;
      const byId = new Map(profile.nodes.map(n => [n.id, n]));
      profile.samples.forEach((id, i) => { const f = byId.get(id).callFrame; const key = f.functionName + ' ' + f.url.split('/').pop() + ':' + (f.lineNumber + 1); self[key] = (self[key] || 0) + (gap[i] || 0) / 1000; });
      out.profile = Object.entries(self).sort((a, b) => b[1] - a[1]).slice(0, 30).map(([k, v]) => k + ' ' + v.toFixed(1));
      // Inclusive time of Studio functions (not the libraries): which of our calls the self time sits under.
      const parent = new Map(), total = {};
      for (const n of profile.nodes) for (const c of n.children || []) parent.set(c, n.id);
      profile.samples.forEach((id, i) => { const seen = new Set();
        for (let at = id; at; at = parent.get(at)) { const f = byId.get(at).callFrame, file = f.url.split('/').pop();
          if (!/^(react|react-dom|xyflow)\.js$/.test(file) && file) { const key = f.functionName + ' ' + file + ':' + (f.lineNumber + 1); if (!seen.has(key)) { seen.add(key); total[key] = (total[key] || 0) + (gap[i] || 0) / 1000; } } } });
      out.profileTotal = Object.entries(total).sort((a, b) => b[1] - a[1]).slice(0, 25).map(([k, v]) => k + ' ' + v.toFixed(1));
      return result;
    };
    const longTasks = () => page.evaluate(() => { const list = window.__perf.long; window.__perf.long = []; return list.filter(d => d > 50); });
    const longFrames = () => page.evaluate(() => { const list = window.__perf.loaf; window.__perf.loaf = []; return list; });
    const frames = async (gesture, name) => {
      await page.evaluate(() => { window.__stop = window.__perfFrames(); }); const start = await metric();
      await longTasks(); await longFrames();
      await profiled(name, gesture);
      await page.waitForTimeout(300);  // the gesture's end (drop, save) belongs to it
      const list = await page.evaluate(() => window.__stop());
      out.longTasks = {...out.longTasks, [name]: await longTasks()};
      out.longFrames = {...out.longFrames, [name]: await longFrames()};
      out.maxFrameMs = {...out.maxFrameMs, [name]: Math.round(Math.max(...list))};
      const end = await metric(), per = key => +((end[key] - start[key]) / Math.max(1, list.length)).toFixed(2);
      out.workPerFrameMs[name] = per('TaskDuration');
      out.splitPerFrameMs[name] = {script: per('ScriptDuration'), style: per('RecalcStyleDuration'), layout: per('LayoutDuration')};
      return p95(list);
    };
    // Double-click on empty canvas (fit), sent as CDP input to this headless page only.
    const fitView = async () => { const x = pane.x + pane.width / 2, y = pane.y + pane.height - 20;
      for (const clickCount of [1, 2]) { await mouse('mousePressed', x, y, {button: 'left', buttons: 1, clickCount}); await mouse('mouseReleased', x, y, {button: 'left', buttons: 0, clickCount}); } };
    const nextPaint = () => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r()))));

    await page.goto(input.url);
    const open = page.getByRole('button', {name: 'Open its Canvas', exact: true});
    await open.waitFor({timeout: 60000});
    await page.waitForTimeout(3000);  // Home's first reads settle before the click is timed
    out.homeMapBoxes = await page.evaluate(() => document.querySelectorAll('.mmap .mn').length);  // Home's map draws its cards
    const flow = page.getByLabel('Workflow canvas', {exact: true});
    await longTasks();
    const t0 = Date.now();
    await profiled('open', async () => {
      await open.click();
      await flow.locator('.react-flow__node[data-id="n28"]').waitFor({timeout: 30000});
      await nextPaint();
    });
    out.openCanvasMs = Date.now() - t0;
    out.longTasks = {open: await longTasks()};
    out.arrangedOnOpen = await page.evaluate(() => window.ArchHubAPI.getSnapshot().graph.canvasLayout === 'v48');
    await page.waitForTimeout(2500);

    // Idle: nobody touches the canvas. Long tasks and requests are counted in the same window.
    await page.evaluate(() => { window.__perf.long = []; });
    const idleFrom = Date.now(), revision0 = await page.evaluate(() => {
      // Which state keys each idle publish changed: evidence for what still re-renders.
      let last = window.ArchHubAPI.getSnapshot(); window.__changed = {};
      window.ArchHubAPI.subscribe(() => { const next = window.ArchHubAPI.getSnapshot();
        for (const key of Object.keys(next)) if (key !== 'revision' && next[key] !== last[key]) window.__changed[key] = (window.__changed[key] || 0) + 1;
        last = next; });
      return last.revision;
    });
    await page.waitForTimeout(idleMs);
    // Store publishes in the idle window: each one re-renders every subscriber.
    out.idlePublishesPerMinute = Math.round((await page.evaluate(() => window.ArchHubAPI.getSnapshot().revision) - revision0) * 60000 / idleMs);
    out.idlePublishedKeys = await page.evaluate(() => window.__changed);
    const idleResponses = responses.filter(r => r.at >= idleFrom);
    out.idleResponsesPerMinute = {changed200: Math.round(idleResponses.filter(r => r.status === 200).length * 60000 / idleMs), unchanged304: Math.round(idleResponses.filter(r => r.status === 304).length * 60000 / idleMs)};
    out.idleLongTasks = await page.evaluate(() => window.__perf.long.filter(d => d > 50));
    const idle = requests.filter(r => r.at >= idleFrom);
    const perMinute = {};
    for (const r of idle) perMinute[r.key] = (perMinute[r.key] || 0) + 1;
    for (const key of Object.keys(perMinute)) perMinute[key] = Math.round(perMinute[key] * 60000 / idleMs);
    out.idleRequestsPerMinute = perMinute;
    out.idleRequestsTotalPerMinute = Math.round(idle.length * 60000 / idleMs);

    const pane = await flow.boundingBox();
    // Pan: the canvas pans with the middle button (left-drag on the pane is box selection).
    out.panP95 = await frames(async () => {
      const x0 = pane.x + pane.width * .5, y0 = pane.y + pane.height - 40;
      await mouse('mouseMoved', x0, y0); await mouse('mousePressed', x0, y0, {button: 'middle', buttons: 4, clickCount: 1});
      for (let i = 1; i <= 40; i++) await mouse('mouseMoved', x0 - i * 6, y0 - i * 2, {button: 'middle', buttons: 4});
      await mouse('mouseReleased', x0 - 240, y0 - 80, {button: 'middle', buttons: 0, clickCount: 1});
    }, 'pan');
    out.zoomP95 = await frames(async () => {
      const x = pane.x + pane.width / 2, y = pane.y + pane.height / 2;
      for (let i = 0; i < 40; i++) { await mouse('mouseWheel', x, y, {deltaX: 0, deltaY: i < 20 ? -60 : 60}); await page.evaluate(() => new Promise(r => requestAnimationFrame(r))); }
    }, 'zoom');
    await fitView();
    await page.waitForTimeout(800);
    const box = async id => flow.locator('.react-flow__node[data-id="' + id + '"]').boundingBox();
    out.dragP95 = await frames(async () => {
      const b = await box('n10'), x0 = b.x + b.width / 2, y0 = b.y + 14;
      await mouse('mouseMoved', x0, y0); await mouse('mousePressed', x0, y0, {button: 'left', buttons: 1, clickCount: 1});
      for (let i = 1; i <= 40; i++) await mouse('mouseMoved', x0 + i * 4, y0 + i * 2, {button: 'left', buttons: 1});
      // The drop alone can be profiled (profile 'dragEnd'): the save and redraw it starts.
      await profiled('dragEnd', async () => { await mouse('mouseReleased', x0 + 160, y0 + 80, {button: 'left', buttons: 0, clickCount: 1}); await nextPaint(); });
    }, 'drag');
    await page.waitForTimeout(800);

    // Selection: fit the view (double-click the empty canvas), then press time to the node's selected class and to the frame painted after it.
    await fitView();
    await page.waitForTimeout(800);
    out.select = [];
    for (const id of ['n3', 'n7', 'n12', 'n16']) {
      // The header point of the card that is on top at that point (not under a dock panel).
      const [x, y] = await page.evaluate(nodeId => {
        const el = document.querySelector('[aria-label="Workflow canvas"] .react-flow__node[data-id="' + nodeId + '"]'), r = (el.querySelector('.node-header') || el).getBoundingClientRect();
        for (const fx of [.5, .3, .7, .15, .85]) { const px = r.left + r.width * fx, py = r.top + Math.min(10, r.height / 2); if (document.elementFromPoint(px, py)?.closest('.react-flow__node') === el) return [px, py]; }
        return [r.left + r.width / 2, r.top + Math.min(10, r.height / 2)];
      }, id);
      await page.evaluate(nodeId => {
        const el = document.querySelector('[aria-label="Workflow canvas"] .react-flow__node[data-id="' + nodeId + '"]');
        window.__sel = {pressed: 0, selected: 0, painted: 0, frame: 0};
        window.addEventListener('pointerdown', () => { window.__sel.pressed = window.performance.now(); requestAnimationFrame(() => { window.__sel.frame = window.performance.now(); }); }, {capture: true, once: true});
        const seen = () => { if (!window.__sel.selected && el.classList.contains('selected')) { window.__sel.selected = window.performance.now(); requestAnimationFrame(() => requestAnimationFrame(() => { window.__sel.painted = window.performance.now(); })); } };
        new window.MutationObserver(seen).observe(el, {attributes: true, attributeFilter: ['class']});
      }, id);
      await mouse('mouseMoved', x, y);
      await profiled(id === 'n3' ? 'select' : '', async () => {
        await mouse('mousePressed', x, y, {button: 'left', buttons: 1, clickCount: 1});
        await mouse('mouseReleased', x, y, {button: 'left', buttons: 0, clickCount: 1});
        await page.waitForTimeout(700);
      });
      const sel = await page.evaluate(([px, py]) => ({...window.__sel, hit: document.elementFromPoint(px, py)?.closest('.react-flow__node')?.dataset.id || document.elementFromPoint(px, py)?.className,
        now: [...document.querySelectorAll('[aria-label="Workflow canvas"] .react-flow__node.selected')].map(el => el.dataset.id)}), [x, y]);
      out.select.push({id, selectedMs: sel.selected ? Math.round(sel.selected - sel.pressed) : null, paintedMs: sel.painted ? Math.round(sel.painted - sel.pressed) : null,
        sameFrame: !!sel.selected && !!sel.frame && sel.selected <= sel.frame, hit: sel.hit, selectedNow: sel.now});
    }

    // Two quick clicks: the second card stays selected (no deferred echo of the first may revert it).
    {
      const point = id => page.evaluate(nodeId => { const r = document.querySelector('[aria-label="Workflow canvas"] .react-flow__node[data-id="' + nodeId + '"] .node-header').getBoundingClientRect(); return [r.left + r.width / 2, r.top + Math.min(10, r.height / 2)]; }, id);
      for (const id of ['n12', 'n3']) { const [x, y] = await point(id); await mouse('mousePressed', x, y, {button: 'left', buttons: 1, clickCount: 1}); await mouse('mouseReleased', x, y, {button: 'left', buttons: 0, clickCount: 1}); }
      await page.waitForTimeout(900);
      out.rapidSelect = await page.evaluate(() => [...document.querySelectorAll('[aria-label="Workflow canvas"] .react-flow__node.selected')].map(el => el.dataset.id));
    }

    // Click a card, then empty canvas, on a 4x slower CPU: the Inspector must end with nothing selected, every time.
    {
      const point = id => page.evaluate(nodeId => { const r = document.querySelector('[aria-label="Workflow canvas"] .react-flow__node[data-id="' + nodeId + '"] .node-header').getBoundingClientRect(); return [r.left + r.width / 2, r.top + Math.min(10, r.height / 2)]; }, id);
      const click = async (x, y) => { await mouse('mousePressed', x, y, {button: 'left', buttons: 1, clickCount: 1}); await mouse('mouseReleased', x, y, {button: 'left', buttons: 0, clickCount: 1}); };
      await cdp.send('Emulation.setCPUThrottlingRate', {rate: 4});
      out.inspectorClears = [];
      for (const id of ['n3', 'n7', 'n12', 'n16', 'n3', 'n7']) {
        const [x, y] = await point(id);
        await click(x, y);
        await click(pane.x + pane.width / 2, pane.y + pane.height - 20);
        await page.waitForTimeout(1200);
        out.inspectorClears.push(await page.evaluate(() => document.querySelector('.shared-properties-selection')?.hidden !== false
          && !document.querySelector('[aria-label="Workflow canvas"] .react-flow__node.selected')));
      }
      await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
    }

    // Workshop fold and open: click to the control's new state, painted.
    out.workshopToggleMs = [];
    await longTasks();
    for (const [from, to] of [['Fold Workshop', 'Open Workshop'], ['Open Workshop', 'Fold Workshop']]) {
      const button = page.getByRole('button', {name: from, exact: true}).first();
      await button.waitFor();
      const b = await button.boundingBox();
      await page.evaluate(() => { window.addEventListener('pointerdown', () => { window.__press = window.performance.now(); }, {capture: true, once: true}); });
      await mouse('mouseMoved', b.x + b.width / 2, b.y + b.height / 2);
      const ms = await profiled(from === 'Fold Workshop' ? 'fold' : '', async () => {
        await mouse('mousePressed', b.x + b.width / 2, b.y + b.height / 2, {button: 'left', buttons: 1, clickCount: 1});
        await mouse('mouseReleased', b.x + b.width / 2, b.y + b.height / 2, {button: 'left', buttons: 0, clickCount: 1});
        return page.evaluate(label => new Promise(resolve => {
          const check = () => document.querySelector('[aria-label="' + label + '"]') ? requestAnimationFrame(() => requestAnimationFrame(() => resolve(Math.round(window.performance.now() - window.__press)))) : requestAnimationFrame(check);
          check();
        }), to);
      });
      out.workshopToggleMs.push(ms);
      await page.waitForTimeout(600);
    }
    out.longTasks.fold = await longTasks();

    // The canvas toolbar's Thread button (the Workshop thread beside the canvas), open then close: press to painted,
    // and the long animation frames it causes.
    out.threadToggleMs = [];
    await longTasks(); await longFrames();
    for (const round of ['open', 'close']) {
      const button = page.locator('[data-design="toolbar.thread"]').first();
      await button.waitFor();
      const b = await button.boundingBox(), pressed = await button.getAttribute('aria-pressed');
      await page.evaluate(() => { window.addEventListener('pointerdown', () => { window.__press = window.performance.now(); }, {capture: true, once: true}); });
      await mouse('mouseMoved', b.x + b.width / 2, b.y + b.height / 2);
      const ms = await profiled(round === 'open' ? 'thread' : '', async () => {
        await mouse('mousePressed', b.x + b.width / 2, b.y + b.height / 2, {button: 'left', buttons: 1, clickCount: 1});
        await mouse('mouseReleased', b.x + b.width / 2, b.y + b.height / 2, {button: 'left', buttons: 0, clickCount: 1});
        return page.evaluate(was => new Promise(resolve => {
          const check = () => document.querySelector('[data-design="toolbar.thread"]')?.getAttribute('aria-pressed') !== was
            ? requestAnimationFrame(() => requestAnimationFrame(() => resolve(Math.round(window.performance.now() - window.__press)))) : requestAnimationFrame(check);
          check();
        }), pressed);
      });
      out.threadToggleMs.push(ms);
      await page.waitForTimeout(900);
    }
    out.longTasks.thread = await longTasks();
    out.longFrames = {...out.longFrames, thread: await longFrames()};

    // A drop is in the file at once: reloading right after it, or a window whose frames stop (minimized) and then
    // closes, keeps the dropped place. The Python court reads the saved file against these engine positions.
    const placed = id => page.evaluate(nodeId => { const m = /translate\(([-\d.]+)px, ?([-\d.]+)px\)/.exec(document.querySelector('.react-flow__node[data-id="' + nodeId + '"]').style.transform); return {x: +m[1], y: +m[2]}; }, id);
    // The first of these cards whose header is on top at its point (a dock panel can cover some after a reload).
    // fit: double-click the empty canvas first (after a reload the restored view can put a card there instead).
    const drop = async (ids, framesStop, fit) => { if (fit) { await fitView(); await page.waitForTimeout(600); }
      let id, x0, y0;
      for (const candidate of ids) {
        const b = await box(candidate); if (!b) continue;
        const x = b.x + b.width / 2, y = b.y + 14;
        if (await page.evaluate(([nodeId, px, py]) => document.elementFromPoint(px, py)?.closest('.react-flow__node')?.dataset.id === nodeId, [candidate, x, y])) { id = candidate; x0 = x; y0 = y; break; }
      }
      if (!id) throw Error('no uncovered card to drop among ' + ids.join(','));
      const before = await placed(id);
      await mouse('mouseMoved', x0, y0); await mouse('mousePressed', x0, y0, {button: 'left', buttons: 1, clickCount: 1});
      for (let i = 1; i <= 10; i++) await mouse('mouseMoved', x0 + i * 9, y0 + i * 5, {button: 'left', buttons: 1});
      const kept = {id, ...(await placed(id)), from: before};
      if (framesStop) await page.evaluate(() => { window.requestAnimationFrame = () => 0; });  // as a minimized window
      await mouse('mouseReleased', x0 + 90, y0 + 50, {button: 'left', buttons: 0, clickCount: 1});
      return kept; };
    const cards = ['n20', 'n23', 'n17', 'n14', 'n11', 'n8', 'n5', 'n2'];
    out.dropKept = [await drop(cards, false, true)];
    await page.reload();
    // A reload lands on Home again, as the first visit did: open the canvas the same way.
    await open.waitFor({timeout: 60000});
    await page.waitForTimeout(3000);
    await open.click();
    await flow.locator('.react-flow__node[data-id="n0"]').waitFor({timeout: 30000});
    await page.waitForTimeout(1500);
    // What the file holds after the reload (read from the file, not the view: a reopened file can be shown arranged,
    // and the next edit then keeps that arrangement, as an open-then-edit does).
    out.dropKept[0].saved = await page.evaluate(async nodeId => { const g = window.ArchHubAPI.getSnapshot();
      const task = g.tasks.find(t => t.sessionPath === g.sessionFile); const file = await window.ArchHubAPI.readTaskPreview(task.id);
      const n = file.nodes.find(r => r.id === nodeId); return {x: n.x, y: n.y}; }, out.dropKept[0].id);
    out.dropKept.push(await drop(cards.filter(id => id !== out.dropKept[0].id), true, false));
    await page.waitForTimeout(1000);
    await page.close({runBeforeUnload: true});
  } catch (error) {
    out.errors.push(error.stack || String(error));
  } finally {
    await browser.close();
  }
  console.log('PERF ' + JSON.stringify(out));
  process.exit(out.errors.length ? 1 : 0);
}
court();
