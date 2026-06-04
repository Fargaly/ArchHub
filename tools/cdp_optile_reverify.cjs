// cdp_optile_reverify.cjs — confirm the op-tile click is VISIBLE, not just a
// state change. Brings the page to front (rAF live, not suspended), spawns a
// rhino connector, clicks an inactive op-tile, and asserts the CARD's
// active-tile DOM text actually becomes the clicked op (what the founder sees).
'use strict';
const path = require('path'), http = require('http');
const ROOT = path.resolve(__dirname, '..');
let WS; for (const b of [path.join(ROOT, '.lagfix_harness/node_modules'), path.join(ROOT, 'node_modules')]) { try { WS = require(path.join(b, 'ws')); break; } catch (e) {} }
if (!WS) { console.log('REVERIFY={"err":"ws missing"}'); process.exit(0); }
const sleep = ms => new Promise(r => setTimeout(r, ms));
function fj(u, t) { return new Promise((res, rej) => { const r = http.get(u, { timeout: t || 8000 }, x => { let s = ''; x.on('data', c => s += c); x.on('end', () => { try { res(JSON.parse(s)); } catch (e) { rej(e); } }); }); r.on('timeout', () => r.destroy(new Error('to'))); r.on('error', rej); }); }
(async () => {
  let pg; for (let i = 0; i < 12; i++) { try { const p = await fj('http://localhost:9223/json', 8000); pg = (p || []).find(z => z.type === 'page' && z.webSocketDebuggerUrl); if (pg) break; } catch (e) {} await sleep(1000); }
  if (!pg) { console.log('REVERIFY={"err":"no page"}'); process.exit(0); }
  const ws = new WS(pg.webSocketDebuggerUrl, { perMessageDeflate: false }); let id = 1; const pend = new Map();
  ws.on('message', d => { let m; try { m = JSON.parse(d.toString()); } catch (e) { return; } if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } });
  function send(method, params) { const i = id++; return new Promise(r => { pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params: params || {} })); }); }
  async function ev(e) { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }); return r && r.result ? r.result.value : undefined; }
  ws.on('open', async () => {
    await send('Runtime.enable', {}); await send('Page.enable', {});
    await send('Page.bringToFront', {});            // <-- force visible: rAF live
    await sleep(400);
    // fresh session so we get a clean connector + wire
    const seq = "new Promise(async (resolve)=>{var S=function(ms){return new Promise(function(r){setTimeout(r,ms);});};" +
      "window.dispatchEvent(new CustomEvent('lm-action-open-session',{detail:{id:'optile-rev'}}));await S(600);" +
      "window.dispatchEvent(new CustomEvent('lm-composer-action',{detail:{action:{command:'spawn_host_chat',family:'rhino'}}}));await S(1200);" +
      "var vis=document.visibilityState;" +
      "var g=window.__archhub_LM_GRAPH;var conn=(g.nodes||[]).find(function(n){return n.kind==='connector';});" +
      "if(!conn){resolve({err:'no connector'});return;}" +
      "window.dispatchEvent(new CustomEvent('lm-focus-node',{detail:{node_id:conn.id}}));await S(700);" +
      "var opBefore=conn.op_id;" +
      "var activeBefore=(document.querySelector('[data-active-tile]')||{}).textContent;" +
      "var tiles=[].slice.call(document.querySelectorAll('[data-host-op-tile]'));" +
      "var target=tiles.find(function(t){return t.getAttribute('data-host-op-tile')!==opBefore;});" +
      "if(!target){resolve({err:'no inactive tile',vis:vis});return;}" +
      "var clickedOp=target.getAttribute('data-host-op-tile');" +
      "target.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));" +
      "await S(1600);" +                            // generous settle for the re-render
      "var conn2=(g.nodes||[]).find(function(n){return n.id===conn.id;});" +
      "var opAfter=conn2.op_id;" +
      "var activeEl=document.querySelector('[data-active-tile]');" +
      "var activeAfter=activeEl?activeEl.textContent.slice(0,40):null;" +
      // does the active tile's text now START with the clicked op short-name?
      "var shortClicked=String(clickedOp).split('.').pop();" +
      "var cardShowsNewOp=!!(activeAfter&&activeAfter.indexOf(shortClicked)>=0);" +
      // also: is the clicked op NO LONGER in the inactive-tile list (it became active)?
      "var tilesAfter=[].slice.call(document.querySelectorAll('[data-host-op-tile]')).map(function(t){return t.getAttribute('data-host-op-tile');});" +
      "var clickedNowInactive=tilesAfter.indexOf(clickedOp)>=0;" +
      "var wireG=document.querySelectorAll('g[data-wire-i]').length;" +
      "resolve({vis:vis,opBefore:opBefore,clickedOp:clickedOp,shortClicked:shortClicked,opAfter:opAfter,opSwitched:(opAfter===clickedOp)," +
      "activeBefore:(activeBefore||'').slice(0,40),activeAfter:activeAfter,cardShowsNewOp:cardShowsNewOp,clickedNowInactive:clickedNowInactive,wireG:wireG,tilesAfter:tilesAfter});})";
    const r = await ev(seq);
    let verdict = 'UNKNOWN';
    if (r && !r.err) {
      verdict = (r.opSwitched && r.cardShowsNewOp && !r.clickedNowInactive && r.wireG >= 1)
        ? 'PASS — card visibly shows the new active op after click; wire intact'
        : 'PARTIAL ' + JSON.stringify({ opSwitched: r.opSwitched, cardShowsNewOp: r.cardShowsNewOp, clickedNowInactive: r.clickedNowInactive, wireG: r.wireG, vis: r.vis });
    } else verdict = 'FAIL ' + JSON.stringify(r);
    console.log('REVERIFY=' + JSON.stringify({ verdict, ...r }));
    ws.close(); process.exit(0);
  });
})();
