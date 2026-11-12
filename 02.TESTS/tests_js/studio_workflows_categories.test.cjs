const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const {transformSync} = require('esbuild');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');

test('Home and Library show exactly three workflows apart from five agent sessions', async t => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.ARCHHUB_TEST_CHROMIUM});
  t.after(() => browser.close());
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => route.fulfill({contentType:'text/html', body:'<div id="root"></div>'}));
  await page.goto('http://workflows.test');
  for (const name of ['vendor/react.js', 'vendor/react-dom.js'])
    await page.addScriptTag({content:fs.readFileSync(path.join(studio, name), 'utf8')});
  await page.evaluate(() => {
    window.opened = []; window.routes = [];
    const graphs = Array.from({length:8}, (_, i) => ({id:String(i), path:'fixture-'+i+'.archhub',
      title:(i<3?'Workflow ':'Agent ')+i, kind:i<3?'workflow':'agent-session'}));
    const data = {graphs, catalogue:[], templates:[], runs:[], mods:[], tasks:[], settings:[], agents:[],
      graph:{nodes:[], wires:[]}, watcher:{geometry:{walls:[]}}, composerAttachments:[]};
    const app = {composerDraft:{}, act:fn=>fn(), setSelectedNodeId:()=>{}, taskFace:'canvas', go:route=>window.routes.push(route)};
    const api = {executeAction:(_id, fn)=>fn(), openSession:async p=>{window.opened.push(p);return {id:p};},
      readHomeLayout:async()=>({homeLayout:{width:300, collapsed:false, resume:'', order:[], hidden:[]}})};
    window.ArchHubAPI = api;
    window.executeAction = (id, context) => id==='ui.select' ? context() : window.handlers[id](context);
    window.handlers = {};
    window.registerActions = (mapping, handlers) => {
      for (const [id, name] of Object.entries(mapping)) window.handlers[id] = handlers[name];
    };
    const component = ({children})=>window.React.createElement('span', null, children);
    window.AHIcon = ()=>null;
    window.UI = {A:{}, D:{Toggle:component}, api, useData:()=>data, useApp:()=>app,
      Btn:component, Empty:component, Av:()=>null, AgentPicker:()=>null, TaskComposer:()=>null};
    window.mount = name => window.ReactDOM.render(window.React.createElement(window.UI[name]), document.getElementById('root'));
  });
  for (const name of ['ds_library.jsx', 'ds_home2.jsx'])
    await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio, name),'utf8'),{loader:'jsx'}).code});
  await page.evaluate(() => window.mount('LibraryShelf'));
  await page.getByRole('button', {name:'Sessions', exact:true}).click();
  assert.equal(await page.locator('.scroll button').filter({hasText:/^Workflow /}).count(), 3);
  assert.equal(await page.locator('.scroll button').filter({hasText:/^Agent /}).count(), 0);
  await page.getByLabel('Saved document kind').selectOption('agent-session');
  assert.equal(await page.locator('.scroll button').filter({hasText:/^Agent /}).count(), 5);
  await page.getByLabel('Saved document kind').selectOption('workflow');
  await page.getByRole('button', {name:'Workflow 0', exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.opened), ['fixture-0.archhub']);
  await page.evaluate(() => window.mount('Home'));
  await page.getByLabel('Session kind', {exact:true}).selectOption('workflow');
  assert.equal(await page.locator('.resume-session-scroll button').count(), 3);
  assert.equal(await page.locator('.resume-session-scroll').getByText(/^Agent /).count(), 0);
  await page.locator('.resume-session-scroll').getByRole('button', {name:'Workflow 1', exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.routes), ['canvas']);
  assert.deepEqual(errors, []);
});
