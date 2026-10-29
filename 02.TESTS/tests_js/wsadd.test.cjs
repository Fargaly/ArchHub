/* Execute the real API, App and rendered Settings Add in an isolated DOM. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const {transformSync} = require('esbuild');
const root = path.resolve(__dirname, '../..');
const read = name => fs.readFileSync(path.join(root, '01.APP/nodelang/studio', name), 'utf8');

async function mount(outcome) {
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/', runScripts:'outside-only'});
  const win = dom.window;
  win.structuredClone = globalThis.structuredClone;
  const requests = [];
  let roots = [];
  win.fetch = async (url, options = {}) => {
    if (url !== '/api/universal/workspace-roots') return new Promise(() => {});
    const body = JSON.parse(options.body);
    requests.push(body);
    if (outcome === 'owner' || outcome === 'owner-idle') {
      const target = new URL(process.env.WSADD_OWNER_URL);
      assert.equal(target.hostname, '127.0.0.1');
      return fetch(new URL(url, target), {...options, headers:{...options.headers,
        Cookie:'ArchHub-Session=' + process.env.WSADD_OWNER_SESSION,
        'X-ArchHub-CSRF':process.env.WSADD_OWNER_CSRF}});
    }
    let data;
    if (body.action === 'browse') data = {ok:true, path:outcome === 'cancel' ? '' : 'C:\\FIXTURE\\CLIENT'};
    if (body.action === 'register') {
      if (outcome === 'refuse') return {ok:false, status:400, json:async () => ({ok:false, error:'fixture folder is already governed'})};
      roots = [{root_id:'client', path:body.path}];
      data = {ok:true, roots};
    }
    if (body.action === 'list') data = {ok:true, built_in:{id:'archhub',path:'C:\\FIXTURE\\BUILTIN',removable:false}, roots:roots.map(w=>({...w,available:outcome!=='unavailable'})), projection:'match',revision:3,health:{state:'ready',message:'Workspaces are ready.',recovery:outcome==='repaired'?{message:'Workspace list restored from the graph. Previous local files were archived.',archive:'FIXTURE/ARCHIVE'}:null}};
    return {ok:true, status:200, json:async () => data};
  };
  win.eval(read('vendor/react.js'));
  win.eval(read('vendor/react-dom.js'));
  win.eval(read('api.js'));
  win.eval(`window.AH={};window.AH_DS={Toggle:()=>null};`);
  win.eval(transformSync(read('ds/index.jsx'), {loader:'jsx',target:'es2022'}).code);
  win.eval(transformSync(read('ui.jsx'), {loader:'jsx',target:'es2022'}).code);
  win.eval(`
    window.UI.Btn=({children,onClick,sm,ghost,p,variant,...props})=>React.createElement('button',{...props,onClick},children);
    window.UI.Card=({children})=>React.createElement('section',null,children);
    window.UI.Chip=()=>null;window.UI.Empty=({children})=>React.createElement('p',null,children);
    window.UI.BaboomSprite=()=>null;
    window.AHIcon=()=>null;
    window.ArchHubRouteNames={home:'Home'};
    window.UI.Home=()=>React.createElement(window.UI.WorkspaceRows);
    window.UI.Workshop=window.UI.Home;  // the app opens on the Workshop; this test hosts the workspace rows there
    const createRoot=ReactDOM.createRoot;
    ReactDOM.createRoot=element=>(window.__root=createRoot(element));`);
  for (const name of ['app.jsx','ds_settings3.jsx']) {
    win.eval(transformSync(read(name), {loader:'jsx',target:'es2022'}).code);
  }
  const settle = () => new Promise(resolve => setTimeout(resolve, 40));
  await settle();
  const add = [...win.document.querySelectorAll('button')].find(b => b.textContent === 'Add workspace');
  assert.ok(add, 'real Settings Add rendered');
  if (outcome === 'owner-idle') await win.ArchHubAPI.listWorkspaces();
  else add.click();
  for (let attempt = 0; attempt < 100; attempt++) {
    await settle();
    const status = win.document.querySelector('[role="status"]');
    if (status && status.textContent !== 'Waiting for confirmation…') break;
  }
  return {win, requests, text:win.document.body.textContent, close:() => {
    win.ReactDOM.flushSync(() => win.__root.unmount());
    win.close();
  }};
}

test('Add picks, registers and refreshes the rendered list', async () => {
  const page = await mount('add');
  try {
    assert.deepEqual(page.requests.map(r => r.action), ['browse','register','list']);
    assert.equal(page.requests[1].path, 'C:\\FIXTURE\\CLIENT');
    assert.match(page.text, /client/);
    assert.match(page.text, /Workspace added\. Your agents can work here\./);
    assert.doesNotMatch(page.text, /Action completed/);
  } finally {page.close();}
});

test('cancel says cancelled and never registers', async () => {
  const page = await mount('cancel');
  try {
    assert.deepEqual(page.requests.map(r => r.action), ['browse']);
    assert.match(page.text, /No workspace was added\./);
    assert.doesNotMatch(page.text, /Action completed|Workspace added/);
  } finally {page.close();}
});

test('register refusal reaches the Settings status unchanged', async () => {
  const page = await mount('refuse');
  try {
    assert.equal(page.win.document.querySelector('[role="alert"]')?.textContent,
      'fixture folder is already governedRetry');
    assert.doesNotMatch(page.text, /Action completed|Workspace added/);
  } finally {page.close();}
});

test('verified recovery keeps the existing workspace controls and truthful row states', async () => {
  for (const outcome of ['repaired','unavailable']) {
    const page = await mount(outcome);
    try {
      assert.match(page.text, /Workspaces are ready\./);
      assert.match(page.text, outcome === 'repaired' ? /Workspace list restored from the graph\. Previous local files were archived\./ : /Folder unavailable/);
      const buttons = [...page.win.document.querySelectorAll('button')];
      assert.equal(buttons.filter(b => b.textContent === 'Open').length, 2);
      assert.equal(buttons.filter(b => b.textContent === 'Remove').length, 1, 'built-in is not removable');
      assert.equal(buttons.filter(b => b.getAttribute('aria-label')?.startsWith('Privacy ')).length, 2);
      assert.match(page.text, /Source: Application graph/);
      assert.match(page.text, /Projection: match/);
    } finally {page.close();}
  }
});

if (process.env.WSADD_OWNER_URL) test('desktop owner Add registers the actual catalogue and renders its refreshed list', async () => {
  const page = await mount('owner');
  try {
    assert.deepEqual(page.requests.map(r => r.action), ['browse','register','list']);
    assert.equal(page.requests[1].path, process.env.WSADD_OWNER_FOLDER);
    assert.match(page.text, /CLIENT/);
    assert.match(page.text, /Workspace added\. Your agents can work here\./);
    assert.doesNotMatch(page.text, /Action completed/);
  } finally {page.close();}
});

if (process.env.WSADD_OWNER_URL) test('fresh idle owner renders built-in Ready', async () => {
  const page = await mount('owner-idle');
  try {
    assert.deepEqual(page.requests.map(r => r.action), ['list']);
    assert.match(page.text, /No other workspaces yet\./);
    assert.match(page.text, /\u00b7 Ready/);
    assert.doesNotMatch(page.text, /Reading workspaces|Checking\u2026/);
    assert.equal([...page.win.document.querySelectorAll('button')].filter(b => b.textContent === 'Remove').length, 0);
  } finally {page.close();}
});
