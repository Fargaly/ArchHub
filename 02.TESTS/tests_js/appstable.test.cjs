/* Execute the shipped API projection; fixtures contain no account credentials. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {structuredClone} = globalThis;
const root = path.resolve(__dirname, '../..');

async function providers(rows) {
  const window = {structuredClone, AH:{inkSoft:'#999'},
    ARCHHUB_NATIVE_APPROVAL:{binding:'review', approval:{rows:[]}},
    dispatchEvent:() => {}, addEventListener:() => {}};
  const context = vm.createContext({window, console, setTimeout, clearTimeout, CustomEvent:class {},
    document:{hidden:true,addEventListener:() => {}},
    fetch:async () => ({ok:true,status:200,json:async () => ({providers:rows})})});
  vm.runInContext(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/api.js'), 'utf8'), context);
  await window.ArchHubAPI.ready;
  return window.ArchHubAPI.listProviders();
}

test('connected provider state reaches Team without inventing agent eligibility', async () => {
  const rows = await providers([{id:'openai',name:'OpenAI',state:'keyed'},
    {id:'ollama',name:'Ollama',state:'running'}]);
  for (const row of rows) {
    assert.match(row.availability, /Credential present|Reachable/);
    assert.equal(row.enabled, undefined);
    assert.equal(row.signedIn, undefined);
  }
});

test('disconnected and uncertain providers say why and how to recover', async () => {
  const rows = await providers(['no key','key invalid','not running','checking','not installed','installed','keyed, not routed']
    .map((state,i) => ({id:String(i),name:'Provider '+i,state})));
  for (const row of rows) {
    assert.notEqual(row.presence, 'Unavailable');
    assert.notEqual(row.signedIn, true);
    assert.match(row.availability, /Not connected|Credential invalid|Not reachable|Checking|Not installed|Installed|No direct route/);
  }
});

test('explicit owner status and disabled state remain authoritative', async () => {
  const [row] = await providers([{id:'openai',name:'OpenAI',state:'keyed',
    status:'Rate limited; retry after the provider resets',enabled:false,signedIn:false}]);
  assert.equal(row.presence, 'Rate limited; retry after the provider resets');
  assert.equal(row.enabled, false);
  assert.equal(row.signedIn, false);
});

test('the existing refresh cadence updates a changed provider connection', async () => {
  let state='keyed';
  const timers=[];
  const window={structuredClone,AH:{inkSoft:'#999'},ARCHHUB_BOOT:{home_load_ms:60000,token:'fixture',csrf:'fixture'},
    addEventListener:() => {},dispatchEvent:() => {},clearInterval:() => {},
    setInterval:fn => {timers.push(fn);return timers.length;},
    ArchHubStudioAuthority:{create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}}};
  const context=vm.createContext({window,console,setTimeout,clearTimeout,CustomEvent:class {},
    document:{hidden:false,addEventListener:() => {}},
    fetch:async url => ({ok:true,status:200,json:async () =>
      url==='/api/universal/providers'?{providers:[{id:'openai',name:'OpenAI',state}]}:
      url==='/api/universal/canvas'?{ok:true,root:'graph:fixture',graph_id:'fixture',nodes:[],revision:1}: {ok:true,result:{}}})});
  vm.runInContext(fs.readFileSync(path.join(root,'01.APP/nodelang/studio/api.js'),'utf8'),context);
  const api=window.ArchHubAPI;
  await api.ready;
  const unsubscribe=api.subscribe(() => {});
  await api.listProviders();
  assert.equal(api.getSnapshot().providers[0].availability,'Credential present · Sign-in not checked');
  state='no key';
  await timers.at(-1)();
  assert.match(api.getSnapshot().providers[0].presence,/Not connected/);
  unsubscribe();
});
