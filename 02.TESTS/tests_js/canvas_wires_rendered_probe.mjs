// Real-browser (headless Chrome) measurement of canvas wires: the effective colour of
// every visible wire (stroke x opacity x stroke-opacity over the canvas background)
// and the set of opacity states in use. Input on stdin: {chrome, html, cases:[{name,
// projection}]}; every request is answered by page.route, nothing else is contacted.
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
  const rgb = text => (String(text).match(/[\d.]+/g) || []).slice(0, 4).map(Number);
  const luminance = ([r, g, b]) => {
    const channel = value => { const c = value / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const ratio = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const canvas = document.querySelector('.canvas');
  const background = rgb(getComputedStyle(canvas).backgroundColor);
  const wires = [...document.querySelectorAll('.universal-wire')].filter(wire => {
    const style = getComputedStyle(wire);
    return style.display !== 'none' && style.visibility !== 'hidden';
  });
  const rows = wires.map(wire => {
    const style = getComputedStyle(wire);
    let alpha = Number(style.opacity) * Number(style.strokeOpacity || 1);
    for (let node = wire.parentElement; node && node !== canvas; node = node.parentElement) {
      alpha *= Number(getComputedStyle(node).opacity);
    }
    const stroke = rgb(style.stroke);
    const strokeAlpha = stroke.length > 3 ? stroke[3] : 1;
    const a = alpha * strokeAlpha;
    const seen = [0, 1, 2].map(i => a * stroke[i] + (1 - a) * background[i]);
    return { opacity: Number(style.opacity), alpha: a, contrast: ratio(seen, background),
      context: wire.dataset.context, focused: wire.dataset.focused || '', stroke: style.stroke };
  });
  return {
    selection: canvas.dataset.selection, background, wires: rows.length,
    opacities: [...new Set(rows.map(row => Math.round(row.opacity * 100) / 100))].sort(),
    minimumContrast: rows.length ? Math.min(...rows.map(row => row.contrast)) : null,
    worst: rows.sort((p, q) => p.contrast - q.contrast).slice(0, 3),
  };
}

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
  await page.waitForSelector('.universal-wire', { state: 'attached', timeout: 30000 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  results.push({ name: item.name, ...(await page.evaluate(measure)), errors });
  await page.close();
}
await browser.close();
process.stdout.write(JSON.stringify(results));
