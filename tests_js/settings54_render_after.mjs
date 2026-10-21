import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve('.');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));

const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(match => [match[1], match[2]]));

const projection = {
  canvas:{graph_id:'app', application_root:'app', root:'app', revision:7, authorization:{system_view:true}},
  graph:{nodes:[
    {id:'sys_account', application:true, title:'Account', group:'Account', cat:'logic', x:20, y:44, w:240,
      params:[{k:'identity', label:'Identity', v:'local', editable:false}]},
    {id:'sys_connections', application:true, title:'Connections', group:'Connections', cat:'tools', x:320, y:44, w:240,
      outs:[{id:'relay', label:'relay', t:'event'}], params:[{k:'relay_state', label:'Relay state', v:'open', editable:false}]},
    {id:'sys_ai', application:true, title:'BABOOM', group:'AI', cat:'ai', x:620, y:44, w:240,
      ins:[{id:'relay', label:'relay', t:'event'}], outs:[{id:'speech', label:'speech', t:'number'}],
      params:[{k:'speech_budget_per_hour', label:'Speech budget', v:2, type:'number', unit:'per hour'}]},
    {id:'sys_permissions', application:true, title:'Permissions', group:'Permissions', cat:'logic', x:320, y:252, w:240,
      ins:[{id:'speech', label:'speech', t:'number'}], params:[{k:'permission_store', label:'Permission store', v:'backend', editable:false}]},
    {id:'sys_appearance', application:true, title:'UI & Design System', group:'Appearance', cat:'display', x:20, y:252, w:260,
      outs:[{id:'theme', label:'theme', t:'view'}], params:[
        {k:'theme', label:'Theme', v:'dark', options:['dark', 'light', 'system']},
        {k:'density', label:'Density', v:'comfortable', options:['comfortable', 'compact', 'spacious']},
        {k:'text_size', label:'Text size', v:14, type:'number', unit:'px'},
      ]},
    {id:'sys_storage', application:true, title:'Storage & About', group:'Storage & About', cat:'data', x:620, y:252, w:240,
      ins:[{id:'theme', label:'theme', t:'view'}], params:[{k:'release_channel', label:'Version', v:'b1', editable:false}]},
  ], wires:[
    {id:'w-theme-storage', from:['sys_appearance', 'theme'], to:['sys_storage', 'theme']},
    {id:'w-relay-ai', from:['sys_connections', 'relay'], to:['sys_ai', 'relay']},
    {id:'w-ai-perms', from:['sys_ai', 'speech'], to:['sys_permissions', 'speech']},
  ]},
};

const browser = await chromium.launch({ headless:true });
const page = await browser.newPage({ viewport:{ width:1496, height:959 }, deviceScaleFactor:1 });
await page.route('http://127.0.0.1:53954/', route => route.fulfill({
  status:200,
  contentType:'text/html',
  body:'<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>',
}));
await page.goto('http://127.0.0.1:53954/');
await page.evaluate(({ seed, projection }) => {
  window.fetch = () => new Promise(() => {});
  window.ARCHHUB_THEME = seed;
  window.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  window.localStorage.setItem('archhub.account.v1', JSON.stringify({signedIn:true, email:'af@example.com', firm:'ArchHub'}));
  const listeners = new Set();
  window.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({applicationUpdate:{state:'idle', current_build:'b1'}, theme:{configuration:{theme:seed, binding_mode:'personal-wip', state:'WIP', history:[], personal_wip_heads:['head-a']}}, pending:false, error:''}),
    subscribe:fn => { listeners.add(fn); return () => listeners.delete(fn); },
    readProviders:async () => [{id:'openrouter', name:'OpenRouter', state:'keyed'}],
    watchApplicationUpdate:() => () => {},
    readCloudPublishConsent:async () => ({allowed:true, account:'af@example.com'}),
    setCloudPublishConsent:async allowed => ({allowed, account:'af@example.com'}),
    listSocialApprovals:async () => [{delegation:'delegation-a', input_digest:'d'.repeat(64), operation:'linkedin.post', account_id:'urn:li:person:af', account_binding:'provider-verified', review_text:'Post copy'}],
    decideSocialApproval:async () => ({ok:true}),
    listLocalSocialAccounts:async () => [{provider:'linkedin', account_id:'urn:li:person:af', vault_entry:'social-linkedin-af', display_name:'AF'}],
    removeLocalSocialAccount:async () => ({ok:true}),
  };
  window.ARCHHUB_STUDIO_AUTHORITY = {
    getSnapshot:() => ({...projection, applicationUpdate:{state:'idle', current_build:'b1'}, pending:false, error:''}),
    subscribe:fn => { listeners.add(fn); return () => listeners.delete(fn); },
    moveMany:async () => ({ok:true}),
  };
  window.ARCHHUB_SET_NODE_PROP = async () => ({ok:true});
  window.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:[], connectors:[], graph:projection.graph, memory:[], skills:[]};
}, { seed, projection });

await page.addScriptTag({ path:path.join(root, 'nodelang/studio/vendor/react.js') });
await page.addScriptTag({ path:path.join(root, 'nodelang/studio/vendor/react-dom.js') });
for (const file of manifest.files) {
  if (file.source !== 'mount.jsx') await page.addScriptTag({ path:path.join(root, 'nodelang/studio/compiled/' + file.output) });
}
await page.evaluate(() => {
  window.__studioRoot = ReactDOM.createRoot(document.getElementById('root'));
  ReactDOM.flushSync(() => window.__studioRoot.render(React.createElement(StudioLM)));
});
await page.locator('[title="Settings"]').click();
await page.locator('button', { hasText:'Permissions' }).first().click();
await page.waitForTimeout(500);
await page.screenshot({ path:path.join(root, 'SETTINGS-54-after.png'), fullPage:false });
await browser.close();
