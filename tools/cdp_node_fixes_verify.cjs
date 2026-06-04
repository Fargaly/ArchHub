// cdp_node_fixes_verify.cjs — live proof on the installed app for two fixes:
//  #3 type-mismatch re-snap: a list output sitting on ai_chat.prompt(string)
//     re-routes to ai_chat.context(any) on op-switch (the founder's GRAPH HEALTH
//     err: connector.out 'list' does not match 'string' on ai_chat.prompt).
//  #1 legacy host upgrade: a Speckle node with cat:'host' + kind:'host' upgrades
//     to the connector master (cat/kind 'connector') on session load.
'use strict';
const path = require('path'), http = require('http');
const ROOT = path.resolve(__dirname, '..');
let WS; for (const b of [path.join(ROOT, '.lagfix_harness/node_modules'), path.join(ROOT, 'node_modules')]) { try { WS = require(path.join(b, 'ws')); break; } catch (e) {} }
if (!WS) { console.log('NODEFIX={"err":"ws missing"}'); process.exit(0); }
const sleep = ms => new Promise(r => setTimeout(r, ms));
function fj(u, t) { return new Promise((res, rej) => { const r = http.get(u, { timeout: t || 8000 }, x => { let s = ''; x.on('data', c => s += c); x.on('end', () => { try { res(JSON.parse(s)); } catch (e) { rej(e); } }); }); r.on('timeout', () => r.destroy(new Error('to'))); r.on('error', rej); }); }
(async () => {
  let pg; for (let i = 0; i < 12; i++) { try { const p = await fj('http://localhost:9223/json', 8000); pg = (p || []).find(z => z.type === 'page' && z.webSocketDebuggerUrl); if (pg) break; } catch (e) {} await sleep(1000); }
  if (!pg) { console.log('NODEFIX={"err":"no page"}'); process.exit(0); }
  const ws = new WS(pg.webSocketDebuggerUrl, { perMessageDeflate: false }); let id = 1; const pend = new Map();
  ws.on('message', d => { let m; try { m = JSON.parse(d.toString()); } catch (e) { return; } if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } });
  function send(method, params) { const i = id++; return new Promise(r => { pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params: params || {} })); }); }
  async function ev(e) { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }); return r && r.result ? r.result.value : undefined; }
  ws.on('open', async () => {
    await send('Runtime.enable', {}); await send('Page.enable', {});
    await send('Page.bringToFront', {});
    await send('Page.reload', { ignoreCache: true });
    for (let i = 0; i < 24; i++) { await sleep(900); const ok = await ev("document.readyState==='complete' && !!window.__archhub_LM_GRAPH && (window.__archhub_LM_CONNECTORS||[]).length>0").catch(() => false); if (ok) break; }

    // fresh session ids per run (node Date.now is available here) so a prior
    // run's persisted graph can't contaminate the spawn/op-switch.
    const ts = Date.now();
    const sid3 = 'nodefix-3-' + ts, sid1 = 'nodefix-1-' + ts;
    // ── #3: type-mismatch re-snap on op-switch ──
    const seqA = "new Promise(async (resolve)=>{var S=function(ms){return new Promise(function(r){setTimeout(r,ms);});};" +
      "window.dispatchEvent(new CustomEvent('lm-action-open-session',{detail:{id:'" + sid3 + "'}}));await S(600);" +
      "window.dispatchEvent(new CustomEvent('lm-composer-action',{detail:{action:{command:'spawn_host_chat',family:'rhino'}}}));await S(1100);" +
      "var g=window.__archhub_LM_GRAPH;var c=(g.nodes||[]).find(function(n){return n.kind==='connector';});var a=(g.nodes||[]).find(function(n){return n.kind==='ai_chat';});" +
      "if(!c||!a){resolve({err:'spawn failed',haveC:!!c,haveA:!!a});return;}" +
      // give ai_chat the grammar-shaped ports (prompt:string + context:any) and
      // repoint the spawn wire onto prompt — reproduces the founder's graph.
      "a.ins=[{id:'prompt',label:'prompt',t:'string'},{id:'context',label:'context',t:'any'}];" +
      "var w=(g.wires||[]).find(function(x){return x.to&&x.to[0]===a.id;});" +
      "if(!w){resolve({err:'no spawn wire'});return;}" +
      "w.to[1]='prompt';" +
      "var wireBefore=JSON.stringify({from:w.from,to:w.to});" +
      // switch the connector op to list_layers → out retypes to 'list'
      "window.dispatchEvent(new CustomEvent('lm-host-set-op',{detail:{node_id:c.id,op_id:'rhino.list_layers'}}));await S(1100);" +
      "var c2=(g.nodes||[]).find(function(n){return n.id===c.id;});var a2=(g.nodes||[]).find(function(n){return n.id===a.id;});" +
      "var outT=((c2.outs||[]).find(function(p){return p.id==='out';})||{}).t;" +
      "var w2=(g.wires||[]).find(function(x){return x.from&&x.from[0]===c.id&&x.to&&x.to[0]===a.id;});" +
      "var wireAfter=w2?JSON.stringify({from:w2.from,to:w2.to}):null;" +
      "var movedToContext=!!(w2&&w2.to[1]==='context');" +
      "resolve({outType:outT,wireBefore:wireBefore,wireAfter:wireAfter,movedToContext:movedToContext});})";
    const A = await ev(seqA);

    // ── #1: legacy Speckle host node upgrades to connector master on load ──
    const seqB = "new Promise(async (resolve)=>{var S=function(ms){return new Promise(function(r){setTimeout(r,ms);});};" +
      "if(!(window.archhub&&window.archhub.save_graph)){resolve({err:'no save_graph slot'});return;}" +
      // persist a session containing a legacy Speckle host node (cat:host +
      // kind:host — the stuck case) DIRECTLY via the bridge save slot, then open
      // it so openSession's _upgradeLegacyNodes runs on the loaded blob.
      "var sp1={id:'sp1',cat:'host',kind:'host',host:'speckle',title:'Speckle',sub:'Speckle'," +
      "ins:[{id:'trigger',label:'trigger',t:'any'}],outs:[{id:'opened_doc',t:'string'},{id:'selection',t:'any'},{id:'state',t:'any'},{id:'after',t:'any'}],config:{}};" +
      "try{await window.archhub.save_graph('" + sid1 + "',JSON.stringify({nodes:[sp1],wires:[],groups:[]}));}catch(e){resolve({err:'save failed '+e});return;}await S(600);" +
      "window.dispatchEvent(new CustomEvent('lm-action-open-session',{detail:{id:'" + sid1 + "'}}));await S(1200);" +
      "var g2=window.__archhub_LM_GRAPH;var sp=(g2.nodes||[]).find(function(n){return n.id==='sp1';});" +
      "if(!sp){resolve({err:'node lost on reload',nodeCount:(g2.nodes||[]).length});return;}" +
      "var tiles=[].slice.call(document.querySelectorAll('[data-host-op-tile]')).length;" +
      "resolve({cat:sp.cat,kind:sp.kind,host:sp.host,configHost:(sp.config||{}).host,outs:(sp.outs||[]).map(function(p){return p.id;}),upgraded:(sp.cat==='connector'&&sp.kind==='connector'),opTilesPresent:tiles});})";
    const B = await ev(seqB);

    const v3 = (A && !A.err && A.movedToContext && /list/i.test(String(A.outType||''))) ? 'PASS' : 'FAIL';
    const v1 = (B && !B.err && B.upgraded) ? 'PASS' : 'FAIL';
    console.log('NODEFIX=' + JSON.stringify({ fix3_resnap: v3, fix1_upgrade: v1, A: A, B: B }));
    ws.close(); process.exit(0);
  });
})();
