// cdp_optile_verify.cjs — LIVE proof the on-card op-tile is no longer a dead
// click. Reload → open session → spawn rhino connector (master + ai_chat +
// value→ctx wire) → record op_id + wire count → CLICK an INACTIVE op-tile with
// a REAL DOM MouseEvent (drives the onClick I added, not a synthetic event
// dispatch) → assert: node.op_id switched to the clicked op, the active-tile
// moved, and the wire SURVIVED (g[data-wire-i] + LM_GRAPH.wires preserved).
'use strict';
const path = require('path'), http = require('http');
const ROOT = path.resolve(__dirname, '..');
let WS; for (const b of [path.join(ROOT, '.lagfix_harness/node_modules'), path.join(ROOT, 'node_modules')]) { try { WS = require(path.join(b, 'ws')); break; } catch (e) {} }
if (!WS) { console.log('OPTILE={"err":"ws missing"}'); process.exit(0); }
const sleep = ms => new Promise(r => setTimeout(r, ms));
function fj(u, t) { return new Promise((res, rej) => { const r = http.get(u, { timeout: t || 8000 }, x => { let s = ''; x.on('data', c => s += c); x.on('end', () => { try { res(JSON.parse(s)); } catch (e) { rej(e); } }); }); r.on('timeout', () => r.destroy(new Error('to'))); r.on('error', rej); }); }
(async () => {
  let pg; for (let i = 0; i < 12; i++) { try { const p = await fj('http://127.0.0.1:9223/json', 8000); pg = (p || []).find(z => z.type === 'page' && z.webSocketDebuggerUrl); if (pg) break; } catch (e) {} await sleep(1200); }
  if (!pg) { console.log('OPTILE={"err":"no page"}'); process.exit(0); }
  const ws = new WS(pg.webSocketDebuggerUrl, { perMessageDeflate: false }); let id = 1; const pend = new Map();
  ws.on('message', d => { let m; try { m = JSON.parse(d.toString()); } catch (e) { return; } if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } });
  function send(method, params) { const i = id++; return new Promise(r => { pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params: params || {} })); }); }
  async function ev(e) { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }); return r && r.result ? r.result.value : undefined; }
  ws.on('open', async () => {
    await send('Runtime.enable', {}); await send('Page.enable', {});
    await send('Page.reload', { ignoreCache: true });
    // wait for bundle ready
    for (let i = 0; i < 24; i++) { await sleep(900); const ok = await ev("document.readyState==='complete' && !!window.__archhub_LM_GRAPH && (window.__archhub_LM_CONNECTORS||[]).length>0").catch(() => false); if (ok) break; }
    const seq = "new Promise(async (resolve)=>{var S=function(ms){return new Promise(function(r){setTimeout(r,ms);});};" +
      "window.dispatchEvent(new CustomEvent('lm-action-open-session',{detail:{id:'optile-test'}}));await S(600);" +
      "window.dispatchEvent(new CustomEvent('lm-composer-action',{detail:{action:{command:'spawn_host_chat',family:'rhino'}}}));await S(1100);" +
      "var g=window.__archhub_LM_GRAPH;var conn=(g.nodes||[]).find(function(n){return n.kind==='connector';});" +
      "if(!conn){resolve({err:'no connector spawned'});return;}" +
      "var opBefore=conn.op_id;var wiresBefore=(g.wires||[]).length;var wireGBefore=document.querySelectorAll('g[data-wire-i]').length;" +
      // focus the connector node so its card body (op-tiles) is mounted/visible
      "window.dispatchEvent(new CustomEvent('lm-focus-node',{detail:{node_id:conn.id}}));await S(700);" +
      // find an INACTIVE op-tile whose op != current op
      "var tiles=[].slice.call(document.querySelectorAll('[data-host-op-tile]'));" +
      "var tileOps=tiles.map(function(t){return t.getAttribute('data-host-op-tile');});" +
      "var target=tiles.find(function(t){return t.getAttribute('data-host-op-tile')!==opBefore;});" +
      "if(!target){resolve({err:'no inactive op-tile found',tileCount:tiles.length,tileOps:tileOps,opBefore:opBefore});return;}" +
      "var clickedOp=target.getAttribute('data-host-op-tile');" +
      // REAL dom click (bubbles → React delegated onClick fires)
      "target.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));await S(900);" +
      "var conn2=(g.nodes||[]).find(function(n){return n.id===conn.id;});" +
      "var opAfter=conn2.op_id;var wiresAfter=(g.wires||[]).length;var wireGAfter=document.querySelectorAll('g[data-wire-i]').length;" +
      "var activeTile=document.querySelector('[data-active-tile]');var activeText=activeTile?activeTile.textContent.slice(0,60):null;" +
      "var connOuts=(conn2.outs||[]).map(function(p){return p.id;});var connIns=(conn2.ins||[]).map(function(p){return p.id;});" +
      "var wires=(g.wires||[]).map(function(w){return {from:w.from,to:w.to};});" +
      "resolve({opBefore:opBefore,clickedOp:clickedOp,opAfter:opAfter,opSwitched:(opAfter===clickedOp&&opAfter!==opBefore),tileCount:tiles.length," +
      "wiresBefore:wiresBefore,wiresAfter:wiresAfter,wireGBefore:wireGBefore,wireGAfter:wireGAfter,wireSurvived:(wiresAfter>=wiresBefore&&wiresBefore>0)," +
      "connIns:connIns,connOuts:connOuts,activeText:activeText,wires:wires});})";
    const r = await ev(seq);
    let verdict = 'UNKNOWN';
    if (r && !r.err) {
      const okOp = r.opSwitched;
      const okWire = r.wireSurvived;
      verdict = (okOp && okWire) ? 'PASS — op-tile click switched op AND wire survived'
              : 'FAIL ' + (okOp ? '' : '[op did not switch] ') + (okWire ? '' : '[wire lost]');
    } else { verdict = 'FAIL ' + JSON.stringify(r); }
    console.log('OPTILE=' + JSON.stringify({ verdict, ...r }));
    ws.close(); process.exit(0);
  });
})();
