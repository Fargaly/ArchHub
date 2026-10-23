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
    if (outcome === 'owner') {
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
    if (body.action === 'list') data = {ok:true, built_in:{id:'archhub',path:'C:\\FIXTURE\\BUILTIN'}, roots};
    return {ok:true, status:200, json:async () => data};
  };
  win.eval(read('vendor/react.js'));
  win.eval(read('vendor/react-dom.js'));
  win.eval(read('api.js'));
  win.eval(`window.AH={};window.AH_DS={Toggle:()=>null};`);
  win.eval(transformSync(read('ds/index.jsx'), {loader:'jsx',target:'es2022'}).code);
  win.eval(transformSync(read('ui.jsx'), {loader:'jsx',target:'es2022'}).code);
  win.eval(`
    window.UI.Btn=({children,onClick,...props})=>React.createElement('button',{onClick},children);
    window.UI.Card=({children})=>React.createElement('section',null,children);
    window.UI.Chip=window.UI.Empty=()=>null;
    window.UI.BaboomSprite=()=>null;
    window.AHIcon=()=>null;
    window.ArchHubRouteNames={home:'Home'};
    window.UI.Home=()=>React.createElement(window.UI.WorkspaceRows);
    const createRoot=ReactDOM.createRoot;
    ReactDOM.createRoot=element=>(window.__root=createRoot(element));`);
  for (const name of ['app.jsx','ds_settings3.jsx']) {
    win.eval(transformSync(read(name), {loader:'jsx',target:'es2022'}).code);
  }
  const settle = () => new Promise(resolve => setTimeout(resolve, 40));
  await settle();
  const add = [...win.document.querySelectorAll('button')].find(b => b.textContent === 'Add');
  assert.ok(add, 'real Settings Add rendered');
  add.click();
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
    assert.match(page.text, /Workspace registered/);
    assert.doesNotMatch(page.text, /Action completed/);
  } finally {page.close();}
});

test('cancel says cancelled and never registers', async () => {
  const page = await mount('cancel');
  try {
    assert.deepEqual(page.requests.map(r => r.action), ['browse']);
    assert.match(page.text, /Folder selection cancelled/);
    assert.doesNotMatch(page.text, /Action completed|Workspace registered/);
  } finally {page.close();}
});

test('register refusal reaches the Settings status unchanged', async () => {
  const page = await mount('refuse');
  try {
    assert.equal(page.win.document.querySelector('[role="alert"]')?.textContent,
      'fixture folder is already governedRetry');
    assert.doesNotMatch(page.text, /Action completed|Workspace registered/);
  } finally {page.close();}
});

if (process.env.WSADD_OWNER_URL) test('desktop owner Add registers the actual catalogue and renders its refreshed list', async () => {
  const page = await mount('owner');
  try {
    assert.deepEqual(page.requests.map(r => r.action), ['browse','register','list']);
    assert.equal(page.requests[1].path, process.env.WSADD_OWNER_FOLDER);
    assert.match(page.text, /CLIENT/);
    assert.match(page.text, /Workspace registered/);
    assert.doesNotMatch(page.text, /Action completed/);
  } finally {page.close();}
});
