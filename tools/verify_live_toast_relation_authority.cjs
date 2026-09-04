'use strict';

const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const REPO = path.resolve(__dirname, '..');
let WebSocket;
for (const base of [
  process.env.ARCHHUB_NODE_MODULES,
  path.join(REPO, '.lagfix_harness', 'node_modules'),
  path.join(REPO, 'node_modules'),
].filter(Boolean)) {
  try { WebSocket = require(path.join(base, 'ws')); break; } catch (_error) {}
}
if (!WebSocket && typeof globalThis.WebSocket === 'function') {
  WebSocket = globalThis.WebSocket;
}
if (!WebSocket) throw new Error('WebSocket dependency not found');

const URL = process.env.ARCHHUB_URL || 'http://127.0.0.1:8480/?prod=1';
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const DEBUG_PORT = 9800 + Math.floor(Math.random() * 100);
const PROFILE = path.join(os.tmpdir(), 'archhub-toast-authority-' + process.pid + '-' + Date.now());
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function fetchJson(url, timeout = 5000) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout }, response => {
      let body = '';
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    });
    request.on('timeout', () => request.destroy(new Error('timeout')));
    request.on('error', reject);
  });
}

async function waitForTarget() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const targets = await fetchJson(`http://127.0.0.1:${DEBUG_PORT}/json`);
      const page = (targets || []).find(target => target.type === 'page' && target.webSocketDebuggerUrl);
      if (page) return page;
    } catch (_error) {}
    await sleep(2000);
  }
  throw new Error('Chrome DevTools target did not start');
}

class CdpClient {
  constructor(url) {
    this.ws = new WebSocket(url, { perMessageDeflate:false });
    this.nextId = 1;
    this.pending = new Map();
    const onMessage = raw => {
      let message;
      const body = raw && raw.data !== undefined ? raw.data : raw;
      try { message = JSON.parse(body.toString()); } catch (_error) { return; }
      if (!message.id || !this.pending.has(message.id)) return;
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
      else pending.resolve(message.result || {});
    };
    if (typeof this.ws.on === 'function') this.ws.on('message', onMessage);
    else this.ws.addEventListener('message', onMessage);
  }
  open() {
    return new Promise((resolve, reject) => {
      if (this.ws.readyState === 1) {
        resolve();
        return;
      }
      if (typeof this.ws.once === 'function') {
        this.ws.once('open', resolve);
        this.ws.once('error', reject);
        return;
      }
      this.ws.addEventListener('open', resolve, { once:true });
      this.ws.addEventListener('error', reject, { once:true });
    });
  }
  send(method, params = {}, timeout = 30000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('timeout ' + method));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const response = await this.send('Runtime.evaluate', {
      expression, awaitPromise:true, returnByValue:true,
    });
    if (response.exceptionDetails) throw new Error('evaluation failed: ' + JSON.stringify(response.exceptionDetails));
    return response.result && response.result.value;
  }
  close() { try { this.ws.close(); } catch (_error) {} }
}

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${PROFILE}`, 'about:blank',
], { stdio:'ignore', windowsHide:true });

(async () => {
  let client;
  try {
    const target = await waitForTarget();
    client = new CdpClient(target.webSocketDebuggerUrl);
    await client.open();
    await client.send('Runtime.enable');
    await client.send('Page.enable');
    await client.send('Page.navigate', { url:URL });
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const ready = await client.evaluate(`document.readyState === 'complete' &&
        !!window.__archhubPublishToast && !!window.__archhub_LM_GRAPH &&
        window.__archhub_LM_GRAPH.nodes.length > 100` ).catch(() => false);
      if (ready) break;
      await sleep(250);
    }
    await sleep(1500);

    const setup = await client.evaluate(`(() => {
      window.__archhubPublishToast({msg:'GRAPH TOAST PROOF',kind:'ok'},10000);
      const graph=window.__archhub_LM_GRAPH,wireId=window.__archhubToastRelationWireId('global');
      const wire=(graph.wires||[]).find(item=>item&&item.id===wireId);
      const relationNodeId=wire&&wire.data&&wire.data.relation_node||'';
      const relationNode=(graph.nodes||[]).find(item=>item&&item.id===relationNodeId);
      const gateLayerNodeId=relationNode&&relationNode.data&&relationNode.data.layer_nodes&&relationNode.data.layer_nodes.gate||'';
      const gateValueNodeId=gateLayerNodeId?('param:'+gateLayerNodeId+':value'):'';
      return {wireId,relationNodeId,gateLayerNodeId,gateValueNodeId};
    })()`);
    let shownState = null;
    for (let attempt = 0; attempt < 60; attempt += 1) {
      shownState = await client.evaluate(`(() => {
        const el=document.querySelector('[data-uisurface="global-toast"]');
        const graph=window.__archhub_LM_GRAPH||{nodes:[]};
        return {
          visible:!!el && (el.innerText||'').includes('GRAPH TOAST PROOF') && getComputedStyle(el).display!=='none',
          channel:window.__archhubReadToastChannel('global'),
          rootNode:!!(graph.nodes||[]).find(node=>node&&node.id==='ui:grandmap:global-toast'),
          surfaces:[...document.querySelectorAll('[data-uisurface]')].map(node=>node.getAttribute('data-uisurface')).filter(Boolean).slice(-30),
          body:(document.body.innerText||'').slice(-500),
        };
      })()`);
      if (shownState && shownState.visible) break;
      await sleep(250);
    }

    const denied = await client.evaluate(`(() => {
      const graph=window.__archhub_LM_GRAPH,node=(graph.nodes||[]).find(item=>item&&item.id===${JSON.stringify(setup.gateValueNodeId)});
      if(!node)return {ok:false,reason:'gate value parameter node missing before deny'};
      window.ahSetUiNodeParam(${JSON.stringify(setup.gateValueNodeId)},'value','deny');
      window.__archhubPublishToast({msg:'DENIED TOAST',kind:'err'},10000);
      return {ok:window.__archhubReadToastChannel('global')===null};
    })()`);
    await sleep(500);
    const deniedVisible = await client.evaluate(`(document.body.innerText||'').includes('DENIED TOAST')`);

    const restored = await client.evaluate(`(() => {
      const graph=window.__archhub_LM_GRAPH,node=(graph.nodes||[]).find(item=>item&&item.id===${JSON.stringify(setup.gateValueNodeId)});
      if(!node)return null;
      window.ahSetUiNodeParam(${JSON.stringify(setup.gateValueNodeId)},'value','allow-if-target-exists');
      window.__archhubPublishToast({msg:'RESTORED TOAST',kind:'ok'},10000);
      return window.__archhubReadToastChannel('global');
    })()`);
    await sleep(800);
    const restoredDom = await client.evaluate(`({
      visible:(document.body.innerText||'').includes('RESTORED TOAST'),
      toastHtml:(document.querySelector('[data-uisurface="global-toast"]')||{}).outerHTML||'',
      rootExists:(window.__archhub_LM_GRAPH.nodes||[]).some(node=>node&&node.id==='ui:grandmap:global-toast'),
      messageValue:((window.__archhub_LM_GRAPH.nodes||[]).find(node=>node&&node.id==='slot:global-toast-message')||{data:{}}).data.value||'',
      messageParamValue:((window.__archhub_LM_GRAPH.nodes||[]).find(node=>node&&node.id==='param:slot:global-toast-message:value')||{data:{}}).data.value||'',
      kindValue:((window.__archhub_LM_GRAPH.nodes||[]).find(node=>node&&node.id==='slot:global-toast-kind')||{data:{}}).data.value||'',
      kindParamValue:((window.__archhub_LM_GRAPH.nodes||[]).find(node=>node&&node.id==='param:slot:global-toast-kind:value')||{data:{}}).data.value||'',
      bindings:(window.__archhub_LM_GRAPH.wires||[]).filter(wire=>wire&&wire.data&&wire.data.target_node==='ui:grandmap:global-toast').map(wire=>({id:wire.id,role:wire.data.role,binding:wire.data.binding_key,source:wire.data.source_node,relationNode:wire.data.relation_node})).slice(0,10),
      surfaces:[...document.querySelectorAll('[data-uisurface]')].map(node=>node.getAttribute('data-uisurface')).filter(Boolean).slice(-20),
      body:(document.body.innerText||'').slice(-300),
    })`);
    const restoredVisible = restoredDom.visible;

    const projectionOnly = await client.evaluate(`(() => {
      const graph=window.__archhub_LM_GRAPH,id=${JSON.stringify(setup.wireId)};
      graph.wires=(graph.wires||[]).filter(item=>!item||item.id!==id);
      window.__archhubPublishToast({msg:'PROJECTIONLESS TOAST',kind:'ok'},10000);
      return {
        read:window.__archhubReadToastChannel('global'),
        projectionAbsent:!(graph.wires||[]).some(item=>item&&item.id===id),
        relationPresent:(graph.nodes||[]).some(item=>item&&item.id===${JSON.stringify(setup.relationNodeId)}),
      };
    })()`);
    await sleep(250);
    const projectionlessVisible = await client.evaluate(`(document.body.innerText||'').includes('PROJECTIONLESS TOAST')`);

    const deleted = await client.evaluate(`(() => {
      const graph=window.__archhub_LM_GRAPH,id=${JSON.stringify(setup.relationNodeId)};
      graph.nodes=(graph.nodes||[]).filter(item=>!item||item.id!==id);
      window.__archhubPublishToast({msg:'DELETED TOAST',kind:'err'},10000);
      return {
        read:window.__archhubReadToastChannel('global'),
        relationRecreated:(graph.nodes||[]).some(item=>item&&item.id===id),
      };
    })()`);
    await sleep(150);
    const deletedVisible = await client.evaluate(`(document.body.innerText||'').includes('DELETED TOAST')`);

    const proof = {
      shown:shownState.visible,
      shownState,
      relationWireId:setup.wireId,
      relationNodeId:setup.relationNodeId,
      gateLayerNodeId:setup.gateLayerNodeId,
      gateValueNodeId:setup.gateValueNodeId,
      gateDenied:!!denied.ok && !deniedVisible,
      restored:!!restored && restored.msg === 'RESTORED TOAST' && restoredVisible,
      restoredRead:restored,
      restoredVisible,
      restoredDom,
      projectionIsDisposable:projectionOnly.projectionAbsent && projectionOnly.relationPresent &&
        projectionOnly.read && projectionOnly.read.msg === 'PROJECTIONLESS TOAST' && projectionlessVisible,
      deletionDidNotFallback:deleted.read === null && !deleted.relationRecreated && !deletedVisible,
    };
    proof.ok = proof.shown && proof.gateDenied && proof.restored && proof.projectionIsDisposable && proof.deletionDidNotFallback;
    if (!proof.ok) throw new Error('toast relation authority failed: ' + JSON.stringify(proof));
    console.log('VERIFY_LIVE_TOAST_RELATION_AUTHORITY ' + JSON.stringify(proof, null, 2));
  } finally {
    if (client) client.close();
    try { chrome.kill(); } catch (_error) {}
    await sleep(250);
    try { require('fs').rmSync(PROFILE, { recursive:true, force:true }); } catch (_error) {}
  }
})().catch(error => {
  console.error('VERIFY_FAIL: ' + (error && error.stack || error));
  process.exitCode = 1;
});
