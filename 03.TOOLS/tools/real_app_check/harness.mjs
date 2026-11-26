// Drives the REAL ArchHub window (QtWebEngine) through raw page CDP for real_app_check.py.
// A scenario module exports `default async function (ctx)` and calls ctx.step(asked, fn) per step.
// Every step writes one row (asked -> what the real window did -> screenshot) and one PNG.
// Clicks are real CDP mouse events at the element's on-screen centre.
// Native dialogs: ctx.native({kind:'pick-folder', title, folder}) asks real_app_check.py, which
// answers the dialog on the hidden desktop with pywinauto.
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { pathToFileURL } from 'node:url';
import { refuseSigning, stepVerdict } from './guards.mjs';


const lines = readline.createInterface({ input: process.stdin })[Symbol.asyncIterator]();
const setup = JSON.parse((await lines.next()).value);
const out = setup.out;
// Qt exposes page targets but does not implement browser context management.
const response = await fetch('http://127.0.0.1:' + setup.cdp + '/json');
const targets = await response.json();
const target = targets.find(p => p.type === 'page' && p.url.includes('/studio'));
if (!target?.webSocketDebuggerUrl) throw new Error('no Studio page target to drive');
const socket = new globalThis.WebSocket(target.webSocketDebuggerUrl);
const pending = new Map(), listeners = new Map();
const connectTimeout = setup.connect_timeout_ms || 10000;
const commandTimeout = setup.command_timeout_ms || 30000;
let requestId = 0;
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    clearTimeout(request.timer);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  } else for (const listener of listeners.get(message.method) || []) listener(message.params);
});
socket.addEventListener('close', () => {
  for (const request of pending.values()) {
    clearTimeout(request.timer);
    request.reject(new Error('CDP page disconnected'));
  }
  pending.clear();
});
await new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('CDP page connection timed out')), connectTimeout);
  socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, {once: true});
  socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('CDP page connection failed')); }, {once: true});
});
const session = {
  on(method, listener) {
    if (!listeners.has(method)) listeners.set(method, []);
    listeners.get(method).push(listener);
  },
  send(method, params) {
    return new Promise((resolve, reject) => {
      const id = ++requestId;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timed out: ' + method)); }, commandTimeout);
      pending.set(id, {resolve, reject, timer});
      socket.send(JSON.stringify({id, method, params}));
    });
  },
};
const failed = [], fileActions = new Map(), fileFailures = [];
const observe = m => {
  if (m.method === 'Network.requestWillBeSent' && new URL(m.params.request.url).pathname === '/api/session-files') {
    const {requestId, request} = m.params;
    const entry = {method:request.method, route:new URL(request.url).pathname, action:'unknown'};
    fileActions.set(requestId, entry);
    const actionOf = raw => {
      try {
        const {action} = JSON.parse(raw);
        if (typeof action === 'string' && /^[a-z][a-z_-]{0,31}$/.test(action)) entry.action = action;
      } catch { entry.error = 'invalid request JSON'; }
    };
    if (request.postData) actionOf(request.postData);
    else if (request.method === 'POST') session.send('Network.getRequestPostData', {requestId})
      .then(body => actionOf(body.postData), () => { entry.error = 'request body unavailable'; });
  }
  if (m.method === 'Network.responseReceived' && m.params.response.status >= 400) {
    failed.push(m.params.response.status + ' ' + m.params.response.url.replace(/^https?:\/\/[^/]+/, '').slice(0, 90));
    if (fileActions.has(m.params.requestId)) fileFailures.push({status:m.params.response.status,...fileActions.get(m.params.requestId)});
  }
  if (m.method === 'Network.loadingFinished' || m.method === 'Network.loadingFailed') fileActions.delete(m.params.requestId);
};
for (const method of ['Network.requestWillBeSent', 'Network.responseReceived', 'Network.loadingFinished', 'Network.loadingFailed']) session.on(method, params => observe({method, params}));
const cdp = async (method, params = {}) => ({result: await session.send(method, params)});
const js = async expression => {
  let r;
  try {
    r = await cdp('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  } catch (error) {
    throw new Error(error.message, {cause:error});
  }
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
  const before = failed.length, beforeFile = fileFailures.length; let returned = null, where;
  try { returned = await fn(); }
  catch (error) {
    returned = { pass: false, why: String(error.message || error).slice(0, 300) };
    where = String(error.stack || '').split('\n').map(line => line.match(/\/scenarios\/([\w.-]+\.mjs:\d+:\d+)/)?.[1]).filter(Boolean).slice(0, 3);
  }
  await sleep(700);
  const httpErrors = failed.slice(before);
  let frame = null, captureError;
  try { frame = await shot(asked); }
  catch (error) {
    captureError = String(error.message || error).slice(0, 200);
    if (stepVerdict(returned, httpErrors).result === 'PASS') returned = {...returned, not_exercised:'Native screenshot unavailable: ' + captureError};
  }
  const verdict = stepVerdict(returned, httpErrors);
  const row = { label: setup.label, asked, result: verdict.result, did: verdict.did, got: returned?.got ?? null,
    http_errors: httpErrors, session_file_errors: fileFailures.slice(beforeFile),
    expected_http: returned?.expected_http ?? [], shot: frame, ...(captureError ? {capture_error:captureError} : {}), ...(where?.length ? {where} : {}) };
  results.push(row);
  fs.writeFileSync(path.join(out, 'steps.json'), JSON.stringify(results, null, 1));
  console.log('STEP ' + JSON.stringify(row));
  return row;
};

const ctx = { on: session.on, input: setup.input, label: setup.label, out, isolatedRoot:setup.isolated_root, cdp, js, sleep, until, rectOf, mouse, clickText, native, step, shot };
try {
  if(setup.qa_email){
    const admitted=await until(async()=>{
      try{return await js('(()=>{const a=window.ArchHubAPI?.getSnapshot()?.desktopAccess;return !!a?.admitted&&[a.email,a.subject].includes('+JSON.stringify(setup.qa_email)+');})()');}
      catch(error){if(/execution context was destroyed|cannot find context/i.test(error.message))return false;throw error;}
    },Boolean,80,300);
    if(!admitted)throw Error('The app did not admit the previous synthetic QA identity');
    ctx.input={...ctx.input,qaEmail:setup.qa_email};
  }
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
socket.close();
process.exit(0);
