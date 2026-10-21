import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const root = process.cwd();
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
const library = JSON.parse(execFileSync(process.env.PYTHON || 'python', [
  '-c',
  'import json; from nodelang.library_engines import library_catalogue; print(json.dumps(library_catalogue()))',
], {cwd: root, encoding: 'utf8'}));
const registryCount = library.reduce((count, group) => count + (group.items || []).length, 0);

const browser = await chromium.launch({headless:true});
const page = await browser.newPage({viewport:{width:1496, height:959}, deviceScaleFactor:1});
await page.setContent('<!doctype html><html><head><meta charset="utf-8"><style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden;background:#0f1014}</style></head><body><div id="root"></div></body></html>', {waitUntil:'domcontentloaded'});
await page.addScriptTag({path:path.join(root, '01.APP/nodelang/studio/vendor/react.js')});
await page.addScriptTag({path:path.join(root, '01.APP/nodelang/studio/vendor/react-dom.js')});
await page.evaluate(libraryData => {
  window.ARCHHUB_LIVE = {
    currentGraph:'graph-a',
    sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    hosts:[], connectors:[], memory:[], skills:[],
    graph:{nodes:[], wires:[]},
  };
  window.AH_LIBRARY = libraryData;
  window.ARCHHUB_BOOT = {open_graph:'graph-a'};
  window.matchMedia = () => ({matches:false, addEventListener(){}, removeEventListener(){}});
  window.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:async () => ({ok:true, selected_route:'qwen/qwen3.8-27b:free', groups:[]})})
    : String(url) === '/tools' ? Promise.resolve({ok:true, json:async () => ({ok:true, tools:[]})})
    : String(url) === '/waiting' ? Promise.resolve({ok:true, json:async () => ({ok:true, items:[]})})
    : new Promise(() => {});
  const topology = {
    canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:{subject:'owner-a', session:'view-a'}, revision:1},
    graph:{nodes:[], wires:[]},
    library:libraryData,
    selected:null,
  };
  const snapshot = {topology, canvas:{graph_id:'graph-a', root:'scope-a', revision:1, authorization:{subject:'owner-a', session:'view-a'}}, workshops:[], applicationUpdate:{state:'idle', current_build:'proof'}};
  window.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:() => () => {},
    watchApplicationUpdate:() => () => {},
    refreshTopologyCanvas:async () => topology.canvas,
  };
}, library);

for (const file of manifest.files) {
  if (file.source !== 'mount.jsx') await page.addScriptTag({path:path.join(root, '01.APP/nodelang/studio/compiled', file.output)});
}
await page.evaluate(() => {
  window.__studioRoot = ReactDOM.createRoot(document.getElementById('root'));
  ReactDOM.flushSync(() => window.__studioRoot.render(React.createElement(StudioLM)));
});
await page.waitForSelector('[data-library-row="Filter"]', {timeout:10000});
const renderedSearchCount = await page.locator('input[placeholder^="Search "]').first().getAttribute('placeholder');
if (renderedSearchCount !== `Search ${registryCount} nodes`) {
  throw new Error(`Library render used ${renderedSearchCount}, expected Search ${registryCount} nodes`);
}
await page.waitForTimeout(2300);
await page.screenshot({path:path.join(root, 'library64-after.png'), fullPage:false});
await browser.close();
