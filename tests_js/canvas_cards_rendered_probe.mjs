// Real-browser (headless Chrome) card states: selected and focused cards use the one
// accent colour (focus adds a 2px ring), a hovered card never moves, and every
// category has its own colour. Input on stdin: {chrome, html, projection}; every
// request is answered by page.route, nothing else is contacted.
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
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(String(error.message || error)));
await page.route('**/*', route => {
  const url = route.request().url();
  if (url === ORIGIN + '/' || url === ORIGIN) return route.fulfill({ status: 200, contentType: 'text/html', body: input.html });
  if (url.includes('/canvas')) return route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, ...input.projection }) });
  return route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
});
await page.goto(ORIGIN + '/');
await page.waitForSelector('.graph-node', { timeout: 30000 });
await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

const states = await page.evaluate(() => {
  const probe = document.createElement('div');
  probe.style.color = 'var(--accent)';
  document.body.append(probe);
  const accent = getComputedStyle(probe).color;
  probe.remove();
  const card = node => {
    const style = getComputedStyle(node);
    return { id: node.dataset.id || node.getAttribute('data-root') || node.id, border: style.borderTopColor,
      borderRight: style.borderRightColor, shadow: style.boxShadow, category: node.dataset.nodeCategory || '',
      nodeColor: style.getPropertyValue('--node-color').trim(), resolvedColor: (() => {
        const swatch = document.createElement('div'); swatch.style.color = 'var(--node-color)'; node.append(swatch);
        const value = getComputedStyle(swatch).color; swatch.remove(); return value; })() };
  };
  return {
    accent,
    selected: [...document.querySelectorAll('.graph-node[data-selected="True"]:not([data-focused="True"])')].map(card),
    focused: [...document.querySelectorAll('.graph-node[data-focused="True"]')].map(card),
    categories: [...document.querySelectorAll('.graph-node[data-node-category]')].map(card),
  };
});
// Hover the first plain card: its box must not move.
const plain = page.locator('.graph-node:not([data-selected="True"])').first();
// Wait until the canvas has settled (the fit glide can still be scaling the stage):
// the same box twice, 250 ms apart. Hover is then the only thing that changes.
let before = await plain.boundingBox();
for (let i = 0; i < 20; i++) {
  await page.waitForTimeout(250);
  const again = await plain.boundingBox();
  if (JSON.stringify(again) === JSON.stringify(before)) break;
  before = again;
}
await plain.hover();
await page.waitForTimeout(250);
const after = await plain.boundingBox();
const hoverTransform = await plain.evaluate(node => getComputedStyle(node).transform);
await browser.close();
process.stdout.write(JSON.stringify({ ...states, hover: { before, after, transform: hoverTransform }, errors }));
