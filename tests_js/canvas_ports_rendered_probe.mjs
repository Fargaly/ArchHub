// Real-browser (headless Chrome) measurement of canvas cards: every port starts below
// the bottom of the card's rendered content rows, no content row overflows its line,
// at several zooms and after a viewport resize, and a resize does not thrash layout.
// Input on stdin: {chrome, html, cases:[{name, projection}]}. Every request is answered
// by page.route from the input, so no server, network or founder app is touched.
import { chromium } from 'playwright';

const input = JSON.parse(await new Promise((resolve, reject) => {
  let body = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { body += chunk; });
  process.stdin.on('end', () => resolve(body));
  process.stdin.on('error', reject);
}));

const ORIGIN = 'http://127.0.0.1:8501';
const browser = await chromium.launch({ executablePath: input.chrome, headless: true });
const results = [];

function measure() {
  const rows = ':scope > .node-head, :scope > .node-title, :scope > .node-summary, :scope > .node-params, :scope > .node-value';
  const lines = ':scope > .node-title, :scope > .node-summary, :scope > .node-params > .node-param, :scope > .node-value';
  const cards = [...document.querySelectorAll('.graph-node')];
  const failures = [];
  let ports = 0;
  for (const card of cards) {
    const box = card.getBoundingClientRect();
    if (!card.offsetHeight || !box.height) continue;
    const scale = box.height / card.offsetHeight;
    let contentBottom = 0;
    for (const row of card.querySelectorAll(rows)) {
      contentBottom = Math.max(contentBottom, (row.getBoundingClientRect().bottom - box.top) / scale);
    }
    for (const line of card.querySelectorAll(lines)) {
      if (line.scrollHeight > line.clientHeight + 1) {
        failures.push({ card: card.dataset.id || card.id, kind: 'row-overflows', row: line.className,
          scrollHeight: line.scrollHeight, clientHeight: line.clientHeight });
      }
    }
    for (const port of card.querySelectorAll('.node-port')) {
      ports += 1;
      const rect = port.getBoundingClientRect();
      const top = (rect.top - box.top) / scale;
      const bottom = (rect.bottom - box.top) / scale;
      if (top + 0.5 < contentBottom) {
        failures.push({ card: card.dataset.id || card.id, kind: 'port-over-content', portTop: top, contentBottom });
      }
      if (bottom > card.offsetHeight + 0.5) {
        failures.push({ card: card.dataset.id || card.id, kind: 'port-outside-card', portBottom: bottom, card: card.offsetHeight });
      }
      if (parseFloat(getComputedStyle(port).fontSize) > 0) {
        failures.push({ card: card.dataset.id || card.id, kind: 'label-text-in-card' });
      }
    }
  }
  // Card against card, in stage units: a taller card must never cover a neighbour.
  const boxes = cards.map(card => {
    const box = card.getBoundingClientRect();
    const scale = card.offsetHeight ? box.height / card.offsetHeight : 1;
    return { id: card.dataset.graphNode || '', left: box.left / scale, top: box.top / scale,
      right: box.right / scale, bottom: box.bottom / scale };
  });
  const overlaps = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 0.5 && h > 0.5) overlaps.push({ a: a.id, b: b.id, w, h });
    }
  }
  return { cards: cards.length, ports, failures, overlaps: overlaps.slice(0, 10), overlapCount: overlaps.length };
}

const settle = page => page.evaluate(() => new Promise(resolve =>
  requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));

for (const item of input.cases) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(String(error.message || error)));
  await page.route('**/*', route => {
    const url = route.request().url();
    if (url === ORIGIN + '/' || url === ORIGIN) {
      return route.fulfill({ status: 200, contentType: 'text/html', body: input.html });
    }
    if (url.includes('/canvas')) {
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, ...item.projection }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
  });
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('.graph-node .node-port', { timeout: 30000 });
  await settle(page);
  const before = await page.evaluate(measure);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  const layouts = async () => (await cdp.send('Performance.getMetrics')).metrics
    .find(metric => metric.name === 'LayoutCount').value;
  // Five resizes back and forth: a thrash costs a layout per wire on EVERY resize
  // (545 before the two-phase redraw); a stray background render inflates one sample.
  const resizeSamples = [];
  const sizes = [[1100, 760], [1440, 900], [1180, 800], [1440, 900], [1100, 760]];
  for (const [width, height] of sizes) {
    // Count the frames that pass while the resize settles: a layout per frame is the
    // browser's own work; more than that is a script forcing layout (thrash).
    await page.evaluate(() => { window.__frames = 0; const tick = () => { window.__frames++; if (window.__frames < 600) requestAnimationFrame(tick); }; requestAnimationFrame(tick); });
    const start = await layouts();
    await page.setViewportSize({ width, height });
    await settle(page);
    const frames = await page.evaluate(() => window.__frames);
    resizeSamples.push({ layouts: (await layouts()) - start, frames });
  }
  const sorted = resizeSamples.map(sample => sample.layouts).sort((a, b) => a - b);
  const resizeLayouts = sorted[Math.floor(sorted.length / 2)];
  const after = await page.evaluate(measure);
  results.push({ name: item.name, before, after, resizeLayouts, resizeSamples, errors });
  await page.close();
}
await browser.close();
process.stdout.write(JSON.stringify(results));
