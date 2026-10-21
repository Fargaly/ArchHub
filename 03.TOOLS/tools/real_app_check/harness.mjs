// Drives the REAL ArchHub window (QtWebEngine) over raw CDP for real_app_check.py.
// A scenario module exports `default async function (ctx)` and calls ctx.step(asked, fn) per step.
// Every step writes one row (asked -> what the real window did -> screenshot) and one PNG.
// Clicks are real CDP mouse events at the element's on-screen centre.
// Native dialogs: ctx.native({kind:'pick-folder', title, folder}) asks real_app_check.py, which
// answers the dialog on the hidden desktop with winapp.
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { pathToFileURL } from 'node:url';
import { refuseSigning, stepVerdict } from './guards.mjs';


const lines = readline.createInterface({ input: process.stdin })[Symbol.asyncIterator]();
const setup = JSON.parse((await lines.next()).value);
const out = setup.out;
const targets = await (await fetch('http://127.0.0.1:' + setup.cdp + '/json')).json();
const target = targets.find(t => t.type === 'page' && t.url.includes('/studio')) || targets.find(t => t.type === 'page');
if (!target) { console.log('DONE ' + JSON.stringify(['no page to drive'])); process.exit(2); }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener('open', resolve, { once: true }));
let id = 0; const waiting = new Map(); const failed = [];
ws.addEventListener('message', event => {
  const m = JSON.parse(event.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  if (m.method === 'Network.responseReceived' && m.params.response.status >= 400)
    failed.push(m.params.response.status + ' ' + m.params.response.url.replace(/^https?:\/\/[^/]+/, '').slice(0, 90));
});
const cdp = (method, params = {}) => new Promise(resolve => { const i = ++id; waiting.set(i, resolve); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async expression => {
  const r = await cdp('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error((r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text || 'page error').slice(0, 300));
  return r.result?.result?.value;
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
await cdp('Network.enable'); await cdp('Page.enable');
await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

let n = 0; const results = [];
const shot = async name => {
  const r = await cdp('Page.captureScreenshot', { format: 'png' });
  const file = path.join(out, String(++n).padStart(2, '0') + '_' + name.replace(/\W+/g, '_').slice(0, 60) + '.png');
  fs.writeFileSync(file, Buffer.from(r.result.data, 'base64'));
  return file;
};
const until = async (read, ok, tries = 40, ms = 500) => { let value; for (let i = 0; i < tries; i++) { value = await read(); if (ok(value)) return value; await sleep(ms); } return value; };
const rectOf = expression => js(`(() => { const e = ${expression}; if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + Math.min(r.height / 2, 14), w: r.width, h: r.height, text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 80) }; })()`);
const mouse = async (point, button = 'left', clickCount = 1) => {
  if (point) refuseSigning(point.text);
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: point.x, y: point.y });
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: point.x, y: point.y, button, clickCount });
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: point.x, y: point.y, button, clickCount });
};
// Click the visible element whose own text, aria-label or title is exactly `text`, with the real mouse.
const clickText = async (text, selector = 'button,[role=button],[role=tab],a') => {
  refuseSigning(text);
  const point = await rectOf(`[...document.querySelectorAll(${JSON.stringify(selector)})].find(e => e.getClientRects().length && [(e.innerText||'').trim(), (e.getAttribute('aria-label')||'').trim(), (e.title||'').trim()].includes(${JSON.stringify(text)}))`);
  if (!point) return false;
  await mouse(point);
  return true;
};
const native = async request => { console.log('NATIVE ' + JSON.stringify(request)); return JSON.parse((await lines.next()).value); };
const step = async (asked, fn) => {
  const before = failed.length; let returned = null;
  try { returned = await fn(); }
  catch (error) { returned = { pass: false, why: String(error.message || error).slice(0, 300) }; }
  await sleep(700);
  const httpErrors = failed.slice(before);
  const verdict = stepVerdict(returned, httpErrors);
  const row = { label: setup.label, asked, result: verdict.result, did: verdict.did, got: returned?.got ?? null,
    http_errors: httpErrors, expected_http: returned?.expected_http ?? [], shot: await shot(asked) };
  results.push(row);
  console.log('STEP ' + JSON.stringify(row));
  return row;
};

const ctx = { input: setup.input, label: setup.label, out, cdp, js, sleep, until, rectOf, mouse, clickText, native, step, shot };
try {
  const scenario = await import(pathToFileURL(process.argv[2]).href);
  // Every scenario declares the steps it will run; real_app_check.py fails the run unless exactly
  // these ran, in this order, and the probe reached DONE and exited 0.
  if (!Array.isArray(scenario.steps) || !scenario.steps.length || scenario.steps.some(name => typeof name !== 'string' || !name)) {
    throw new Error('the scenario must export its step names as `steps`');
  }
  console.log('DECLARED ' + JSON.stringify(scenario.steps));
  await scenario.default(ctx);
} catch (error) {
  await step('scenario ran to its end', async () => ({ pass: false, why: String(error.message || error).slice(0, 300) }));
}
fs.writeFileSync(path.join(out, 'steps.json'), JSON.stringify(results, null, 1));
console.log('DONE ' + JSON.stringify(results.map(row => row.asked + ': ' + row.result)));
ws.close();
process.exit(0);
