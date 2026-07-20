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
const DEBUG_PORT = 9900 + Math.floor(Math.random() * 80);
const PROFILE = path.join(os.tmpdir(), 'archhub-relation-payload-' + process.pid + '-' + Date.now());
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
    await sleep(250);
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
        !!window.__archhubPublishToast && !!window.__archhubInterpretRelationPayload &&
        !!window.__archhub_LM_GRAPH && window.__archhub_LM_GRAPH.nodes.length > 100`).catch(() => false);
      if (ready) break;
      await sleep(250);
    }

    const proof = await client.evaluate(`(async () => {
      window.__archhubPublishToast({msg:'PAYLOAD RUNTIME SETUP',kind:'ok'},10000);
      const graph=window.__archhub_LM_GRAPH;
      const wireId=window.__archhubToastRelationWireId('global');
      const relationNodeId='wire:relation:'+wireId.replace(/[^a-zA-Z0-9._-]+/g,'-').replace(/^-+|-+$/g,'');
      const relation=(graph.nodes||[]).find(node=>node&&node.id===relationNodeId);
      if(!relation) return {ok:false,error:'relation node missing'};
      window.ahSetUiNodeParam(relationNodeId,'codec','json');
      window.ahSetUiNodeParam(relationNodeId,'encryption','aes-gcm');
      window.ahSetUiNodeParam(relationNodeId,'encryption_key_ref','secret://relation-proof/key');
      window.ahSetUiNodeParam(relationNodeId,'logical_type','archhub.payload.universal.v1');
      window.ahSetUiNodeParam(relationNodeId,'schema_ref','https://archhub.local/schema/universal-payload/v1');
      window.ahSetUiNodeParam(relationNodeId,'media_type','application/json');
      window.ahSetUiNodeParam(relationNodeId,'payload_mode','inline');

      const key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
      const wrongKey=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
      const input={
        scalar:42,
        text:'universal payload',
        geometry:{logical_type:'org.khronos.gltf',ref:'sha256:geometry-proof',coordinate_system:'EPSG:4326'},
        image:{media_type:'image/png',ref:'sha256:image-proof',width:64,height:64},
        values:[true,3.5,{nested:'yes'}],
      };
      const send=await window.__archhubInterpretRelationPayload(graph,relationNodeId,input,{
        direction:'send',resolveSecretRef:async ref=>ref==='secret://relation-proof/key'?key:null,
      });
      if(!send.ok)return {ok:false,error:'send: '+send.error,send};
      const envelopeNodeId=relation.data&&relation.data.payload_envelope_node_id||'';
      const receive=await window.__archhubInterpretRelationPayload(graph,relationNodeId,send.value,{
        direction:'receive',resolveSecretRef:async ref=>ref==='secret://relation-proof/key'?key:null,
      });
      const tampered={...send.value,ciphertext:new Uint8Array(send.value.ciphertext)};
      tampered.ciphertext[0]^=1;
      const tamperResult=await window.__archhubInterpretRelationPayload(graph,relationNodeId,tampered,{
        direction:'receive',resolveSecretRef:async()=>key,
      });
      const wrongKeyResult=await window.__archhubInterpretRelationPayload(graph,relationNodeId,send.value,{
        direction:'receive',resolveSecretRef:async()=>wrongKey,
      });
      const graphHasCryptoKey=(graph.nodes||[]).some(node=>{
        const values=[node&&node.data,node&&node.config].filter(Boolean).flatMap(value=>Object.values(value));
        return values.some(value=>typeof CryptoKey!=='undefined'&&value instanceof CryptoKey);
      });
      const envelope=(graph.nodes||[]).find(node=>node&&node.id===envelopeNodeId);
      const envelopeValues=Object.fromEntries((envelope&&envelope.data&&envelope.data.param_nodes||[]).map(id=>{
        const node=(graph.nodes||[]).find(item=>item&&item.id===id);
        return node&&node.data?[node.data.key,node.data.value]:['',''];
      }).filter(entry=>entry[0]));
      const roundTrip=receive.ok&&JSON.stringify(receive.value)===JSON.stringify(input);
      const encrypted=send.value&&send.value.algorithm==='AES-GCM'&&send.value.ciphertext&&send.value.ciphertext.length>0;
      const secretReferenceOnly=!graphHasCryptoKey&&JSON.stringify(graph).includes('secret://relation-proof/key');
      return {
        ok:roundTrip&&encrypted&&!tamperResult.ok&&!wrongKeyResult.ok&&secretReferenceOnly,
        relationNodeId,envelopeNodeId,roundTrip,encrypted,
        sendTrace:send.trace,receiveTrace:receive.trace,
        tamperRejected:!tamperResult.ok,tamperError:tamperResult.error||'',
        wrongKeyRejected:!wrongKeyResult.ok,wrongKeyError:wrongKeyResult.error||'',
        secretReferenceOnly,
        envelope:{
          logical_type:envelopeValues.logical_type,
          schema_ref:envelopeValues.schema_ref,
          media_type:envelopeValues.media_type,
          mode:envelopeValues.mode,
        },
        inputKinds:Object.keys(input),
        cipherBytes:send.value.ciphertext.length,
      };
    })()`);
    if (!proof || !proof.ok) throw new Error('relation payload runtime proof failed: ' + JSON.stringify(proof));
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const ready = await client.evaluate(`(() => {
        const graph=window.__archhub_LM_GRAPH||{nodes:[]};
        return !!(graph.nodes||[]).find(node=>node&&node.data&&node.data.role==='wire'&&node.data.wire_family==='ui_state_write') &&
          document.querySelectorAll('[data-action="sessions.filter.set"]').length>=3;
      })()`).catch(() => false);
      if (ready) break;
      await sleep(250);
    }
    const stateProof = await client.evaluate(`(async () => {
      const graph=window.__archhub_LM_GRAPH;
      const nodes=graph.nodes||[];
      const relation=nodes.find(node=>node&&node.data&&node.data.role==='wire'&&node.data.wire_family==='ui_state_write'&&node.data.behavior==='parameter-set');
      const state=nodes.find(node=>node&&node.id==='state:ui:home-session-filter');
      const parameter=nodes.find(node=>node&&node.id==='param:state:ui:home-session-filter:filter');
      if(!relation||!state||!parameter)return {ok:false,error:'state authority or mutation relation missing'};
      const read=()=>{
        const p=(graph.nodes||[]).find(node=>node&&node.id===parameter.id);
        return p&&p.data&&p.data.value;
      };
      const click=label=>{
        const button=[...document.querySelectorAll('[data-action="sessions.filter.set"]')]
          .find(element=>(element.textContent||'').trim().toLowerCase()===label);
        if(!button)throw new Error('filter control missing: '+label);
        button.click();
      };
      const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
      click('mine'); await wait(350);
      const afterMine=read();
      window.ahSetUiNodeParam(relation.id,'gate_policy','deny');
      click('all'); await wait(350);
      const afterDenied=read();
      window.ahSetUiNodeParam(relation.id,'gate_policy','allow-if-source-and-target-exist');
      const projectionId=relation.data&&relation.data.wire_id||'';
      graph.wires=(graph.wires||[]).filter(wire=>wire&&wire.id!==projectionId);
      click('workflows'); await wait(350);
      const afterProjectionDeleted=read();
      window.ahSetUiNodeParam(state.id,'filter_shadow','shadow');
      const shadowParameterId='param:state:ui:home-session-filter:filter_shadow';
      const targetEndpoint=(relation.data.endpoint_node_ids||[]).map(id=>(graph.nodes||[]).find(node=>node&&node.id===id)).find(node=>node&&node.data&&(node.data.endpoint_role==='target'||node.data.direction==='in'));
      if(!targetEndpoint)return {ok:false,error:'ordered target endpoint parameter missing'};
      const fanoutEndpointId=window.__archhubAppendRelationEndpoint(relation.id,{
        endpoint_role:'target',direction:'in',participant_node_id:shadowParameterId,
        participant_port_id:'value',cardinality:'many',
      });
      if(!fanoutEndpointId)return {ok:false,error:'third endpoint could not be appended'};
      click('all'); await wait(350);
      const shadowParameter=(graph.nodes||[]).find(node=>node&&node.id===shadowParameterId);
      const afterFanoutOriginal=read();
      const afterFanoutShadow=shadowParameter&&shadowParameter.data&&shadowParameter.data.value;
      window.__archhubRemoveRelationEndpoint(relation.id,targetEndpoint.id);
      click('mine'); await wait(350);
      const afterEndpointRemovedOriginal=read();
      const afterEndpointRemovedShadow=shadowParameter&&shadowParameter.data&&shadowParameter.data.value;
      window.ahSetUiNodeParam(state.id,'filter_shadow_2','shadow-2');
      const shadowParameter2Id='param:state:ui:home-session-filter:filter_shadow_2';
      const fanoutEndpoint=(graph.nodes||[]).find(node=>node&&node.id===fanoutEndpointId);
      window.ahSetUiNodeParam(fanoutEndpoint.id,'participant_node_id',shadowParameter2Id);
      click('workflows'); await wait(350);
      const shadowParameter2=(graph.nodes||[]).find(node=>node&&node.id===shadowParameter2Id);
      const afterRewireOriginal=read();
      const afterRewireShadow=shadowParameter&&shadowParameter.data&&shadowParameter.data.value;
      const afterRewireShadow2=shadowParameter2&&shadowParameter2.data&&shadowParameter2.data.value;
      graph.nodes=graph.nodes.filter(node=>node&&node.id!==relation.id);
      click('all'); await wait(350);
      const afterAuthorityDeleted=read();
      const shadowAfterAuthorityDeleted=shadowParameter&&shadowParameter.data&&shadowParameter.data.value;
      const shadow2AfterAuthorityDeleted=shadowParameter2&&shadowParameter2.data&&shadowParameter2.data.value;
      const operation=(graph.nodes||[]).filter(node=>node&&node.data&&node.data.role==='graph_operation'&&node.data.operation==='parameter.set').slice(-1)[0];
      return {
        ok:afterMine==='mine'&&afterDenied==='mine'&&afterProjectionDeleted==='workflows'&&
          afterFanoutOriginal==='all'&&afterFanoutShadow==='all'&&
          afterEndpointRemovedOriginal==='all'&&afterEndpointRemovedShadow==='mine'&&
          afterRewireOriginal==='all'&&afterRewireShadow==='mine'&&afterRewireShadow2==='workflows'&&
          afterAuthorityDeleted==='all'&&shadowAfterAuthorityDeleted==='mine'&&shadow2AfterAuthorityDeleted==='workflows'&&!!operation,
        stateNodeId:state.id,parameterNodeId:parameter.id,relationNodeId:relation.id,projectionId,
        endpointNodeIds:relation.data.endpoint_node_ids||[],fanoutEndpointId,
        afterMine,afterDenied,afterProjectionDeleted,afterFanoutOriginal,afterFanoutShadow,
        afterEndpointRemovedOriginal,afterEndpointRemovedShadow,
        afterRewireOriginal,afterRewireShadow,afterRewireShadow2,
        afterAuthorityDeleted,shadowAfterAuthorityDeleted,shadow2AfterAuthorityDeleted,
        historyOperationNodeId:operation&&operation.id||'',
      };
    })()`);
    if (!stateProof || !stateProof.ok) throw new Error('live UI state relation proof failed: ' + JSON.stringify(stateProof));
    console.log('VERIFY_LIVE_RELATION_PAYLOAD_RUNTIME ' + JSON.stringify({ payload:proof, uiState:stateProof }, null, 2));
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
