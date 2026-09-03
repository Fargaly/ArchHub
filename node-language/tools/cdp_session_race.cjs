// cdp_session_race.cjs — reproduce the founder's "session not saved / opens
// disconnected" via the REAL gesture (real events -> real handlers), no
// synthetic flush. Sequence: open session A -> spawn host+conv+wire (schedules
// the 250ms debounced save) -> navigate to B WITHIN the debounce window (real
// openSession resets LM_GRAPH) -> reopen A -> did A keep its nodes+wires?
// Run BEFORE the fix (expect loss) and AFTER (expect preserved).
'use strict';
const path = require('path');
const http = require('http');
const ROOT = path.resolve(__dirname, '..');
let WebSocket;
for (const base of [path.join(ROOT, '.lagfix_harness/node_modules'), path.join(ROOT, 'node_modules')]) {
  try { WebSocket = require(path.join(base, 'ws')); break; } catch (e) {}
}
if (!WebSocket) { console.error('ws missing'); process.exit(2); }
const sleep = ms => new Promise(r => setTimeout(r, ms));
function fj(u, t) { return new Promise((res, rej) => { const r = http.get(u, { timeout: t || 8000 }, x => { let b = ''; x.on('data', c => b += c); x.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }); r.on('timeout', () => r.destroy(new Error('to'))); r.on('error', rej); }); }
async function wsUrl() { for (let i = 0; i < 16; i++) { try { const p = await fj('http://127.0.0.1:9223/json', 8000); const pg = (p || []).find(z => z.type === 'page' && z.webSocketDebuggerUrl); if (pg) return pg.webSocketDebuggerUrl; } catch (e) {} await sleep(1500); } throw new Error('no ws'); }
let ws, nextId = 1; const pending = new Map();
function send(method, params, t) { const id = nextId++; return new Promise((resolve, reject) => { const to = setTimeout(() => { pending.delete(id); reject(new Error('timeout ' + method)); }, t || 40000); pending.set(id, { resolve, reject, to }); ws.send(JSON.stringify({ id, method, params: params || {} })); }); }
async function ev(e, t) { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }, t); if (r && r.exceptionDetails) throw new Error('eval exc: ' + JSON.stringify(r.exceptionDetails).slice(0, 220)); return r && r.result ? r.result.value : undefined; }

(async () => {
  const out = { reloaded: false, afterSpawn: null, afterReopen: null, wiresAfterReopen: null, verdict: 'UNKNOWN' };
  let url; try { url = await wsUrl(); } catch (e) { out.verdict = 'FAIL: no CDP'; console.log('RACE_VERIFY=' + JSON.stringify(out)); process.exit(1); }
  ws = new WebSocket(url, { perMessageDeflate: false });
  ws.on('message', d => { let m; try { m = JSON.parse(d.toString()); } catch (e) { return; } if (m.id && pending.has(m.id)) { const { resolve, reject, to } = pending.get(m.id); clearTimeout(to); pending.delete(m.id); if (m.error) reject(new Error(JSON.stringify(m.error))); else resolve(m.result); } });
  ws.on('error', e => { out.verdict = 'FAIL: ws ' + e.message; console.log('RACE_VERIFY=' + JSON.stringify(out)); process.exit(1); });
  ws.on('open', async () => {
    try { await send('Runtime.enable', {}, 30000); } catch (e) {}
    try { await send('Page.enable', {}, 20000); } catch (e) {}
    try {
      await send('Page.reload', { ignoreCache: true }, 20000);
      out.reloaded = true;
      for (let i = 0; i < 25; i++) { await sleep(900); const ok = await ev("document.readyState==='complete' && !!window.__archhub_LM_GRAPH && !!window.archhub", 12000).catch(() => false); if (ok) break; }
      const seq = "new Promise(async (resolve)=>{var S=function(ms){return new Promise(function(r){setTimeout(r,ms);});};function fire(n,det){window.dispatchEvent(new CustomEvent(n, det?{detail:det}:undefined));}" +
        "fire('lm-action-open-session',{id:'racetestA'});await S(450);" +                       // open A
        "fire('lm-composer-action',{action:{command:'spawn_host_chat',family:'rhino'}});await S(120);" + // spawn (debounce scheduled, not fired)
        "var afterSpawn=(window.__archhub_LM_GRAPH.nodes||[]).length;" +
        "fire('lm-action-open-session',{id:'racetestB'});await S(750);" +                        // NAVIGATE within debounce window (race)
        "fire('lm-action-open-session',{id:'racetestA'});await S(800);" +                        // reopen A
        "var g=window.__archhub_LM_GRAPH;resolve({afterSpawn:afterSpawn,afterReopen:(g.nodes||[]).length,wires:(g.wires||[]).length,sid:window.__archhub_session_id});})";
      const r = await ev(seq, 30000);
      out.afterSpawn = r.afterSpawn; out.afterReopen = r.afterReopen; out.wiresAfterReopen = r.wires;
      // The bug: spawn added nodes (afterSpawn>=2) but reopening A shows 0.
      if (r.afterSpawn >= 2 && r.afterReopen === 0) out.verdict = 'BUG REPRODUCED — spawned ' + r.afterSpawn + ' nodes, reopen shows 0 (data lost on navigation)';
      else if (r.afterReopen >= 2) out.verdict = 'PRESERVED — reopen shows ' + r.afterReopen + ' nodes, ' + r.wires + ' wires (fix works)';
      else out.verdict = 'INCONCLUSIVE afterSpawn=' + r.afterSpawn + ' afterReopen=' + r.afterReopen;
    } catch (e) { out.verdict = 'FAIL: ' + e.message; }
    console.log('RACE_VERIFY=' + JSON.stringify(out));
    try { ws.close(); } catch (e) {}
    process.exit(0);
  });
})();
