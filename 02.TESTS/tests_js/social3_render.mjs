import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {chromium} from 'playwright';
const root = path.resolve('.');
const read = file => fs.readFileSync(path.join(root,file),'utf8');
const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
for(const source of ['studio-lm.jsx','studio-params.jsx']) {
  assert.equal(manifest.files.find(f=>f.source===source)?.source_sha256,createHash('sha256').update(read('01.APP/nodelang/studio/'+source)).digest('hex'),'Build must match '+source);
}
const seedText=read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed=Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m=>[m[1],m[2]]));
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:1496,height:959},deviceScaleFactor:1});
  await page.route('**/*',route=>route.request().url()==='http://127.0.0.1:53954/'?route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><head><meta charset="utf-8"><style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden}body{background:#15151b}</style></head><body><div id="root"></div></body></html>'}):route.abort());
  await page.goto('http://127.0.0.1:53954/');
  await page.evaluate(seed=>{
    window.fetch=()=>new Promise(()=>{});
    window.ARCHHUB_THEME=seed;
    window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
    window.ARCHHUB_CLOUD_SESSION=async()=>({state:'signed_in',signed_in:true,email:'founder@example.com'});
    const providers=['instagram','facebook','linkedin','whatsapp','x','tiktok'];
    const names=['Instagram','Facebook','LinkedIn','WhatsApp Business','X','TikTok'];
    window.ARCHHUB_EXISTING_WORKSHOP={
      getSnapshot:()=>({applicationUpdate:{state:'idle',current_build:'SOCIAL3 fake transport'},theme:{configuration:{theme:seed,binding_mode:'personal-wip',state:'WIP',history:[],personal_wip_heads:[]}},pending:false,error:''}),
      subscribe:()=>()=>{},readProviders:async()=>[],watchApplicationUpdate:()=>()=>{},
      listSocialConnections:async()=>providers.map((provider,i)=>({provider,name:names[i],state:'blocked',can_connect:false,
        blocker:({instagram:'Meta publisher app not configured',facebook:'Meta publisher app not configured',linkedin:'LinkedIn publisher app not configured',whatsapp:'WhatsApp Business Embedded Signup not configured',x:'X developer app not created',tiktok:'TikTok developer app not created'})[provider]})),
      listSocialApprovals:async()=>[],installMcpClient:async()=>({ok:true}),
    };
    window.ARCHHUB_LIVE={sessions:[],hosts:[],connectors:[],graph:{nodes:[{id:'connections',application:true,title:'Connections',group:'Connections',params:[]}],wires:[]},memory:[],skills:[]};
  },seed);
  for(const vendor of ['react.js','react-dom.js']) await page.addScriptTag({path:path.join(root,'01.APP/nodelang/studio/vendor',vendor)});
  for(const file of manifest.files) if(file.source!=='mount.jsx') await page.addScriptTag({path:path.join(root,'01.APP/nodelang/studio/compiled',file.output)});
  await page.evaluate(()=>{window.__studioRoot=ReactDOM.createRoot(document.getElementById('root'));ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));});
  await page.locator('[title="Settings"]').click();
  await page.locator('[data-settings54-group-title]').filter({hasText:/^Connections$/}).click();
  await page.locator('[data-settings54-capability-nav="connections"] button').filter({hasText:/^Connections$/}).click();
  await page.locator('[data-social-provider="tiktok"]').waitFor();
  assert.equal(await page.locator('[data-social-provider]').count(),6);
  for (const provider of ['instagram','facebook','linkedin','whatsapp','x','tiktok']) {
    const box = await page.locator('[data-social-provider="'+provider+'"]').boundingBox();
    assert.ok(box && box.y >= 0 && box.y + box.height < 935, provider+' row fits the screenshot viewport');
  }
  fs.mkdirSync(path.join(root,'05.EVIDENCE'),{recursive:true});
  await page.screenshot({path:path.join(root,'05.EVIDENCE/social3-connections.png'),fullPage:false});
  console.log('SOCIAL3 render: six provider rows; 05.EVIDENCE/social3-connections.png; fake transport only');
} finally {await browser.close();}
