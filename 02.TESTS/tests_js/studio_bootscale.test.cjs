/* Real integrity loader: slow Home data must not hide the usable shell. */
'use strict';
const test=require('node:test'), assert=require('node:assert/strict');
const fs=require('node:fs'), path=require('node:path'), http=require('node:http');
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const repo=path.resolve(__dirname,'../..'), studio=path.join(repo,'01.APP/nodelang/studio');
const launcher=fs.readFileSync(path.join(repo,'01.APP/nodelang/launcher.py'),'utf8');
const readiness=launcher.slice(launcher.indexOf('def _prepare_pipeline_after_home(')).match(/runJavaScript\("""([\s\S]*?)""", observed\)/)[1];
const canvas=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/clean-canvas-fresh-runtime.json'),'utf8'));
for(const entry of ['launcher','clean','legacy'])test(`${entry}: Home shell paints while data is pending; hydration preserves input`,{timeout:25000},async()=>{
 const cleanPage=entry==='clean'?execFileSync((process.env.PYTHON || 'python'),['-c',
  'from types import SimpleNamespace; from nodelang.application_server import _CleanAuthorityHttpServer as S; print(S._clean_studio_page(SimpleNamespace(clean_canvas_key="fixture",_clean_studio_asset=lambda name:open("01.APP/nodelang/studio/"+name,"rb").read())))'],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'01.APP')},encoding:'utf8'}):null;
 const home={...canvas,projection:'home',nodes:[],wires:[],catalog:[],selected:[]};
 let release=false;const waiting=new Set(),errors=[];
 const json=(res,data)=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
 const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/api/universal/canvas'){
   if(url.searchParams.get('screen')==='home'&&!release){waiting.add(res);res.on('close',()=>waiting.delete(res));return;}
   return json(res,url.searchParams.get('screen')==='home'?home:canvas);
  }
  if(url.pathname.startsWith('/api/')){
   if(url.pathname.endsWith('/session'))return json(res,{token:'fixture',csrf:'fixture'});
   if(url.pathname.endsWith('/graphs'))return json(res,{graphs:[{id:'application',title:'System graph'},{id:canvas.root,title:'Saved graph'}],current_graph:canvas.root});
   if(url.pathname.endsWith('/canvas-op')){let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{const op=JSON.parse(body).op;json(res,{result:op==='project_state'?{versions:[],dismissed:[],modelReview:{operation:'',results:[],issues:[]}}:[]});});return;}
   if(url.pathname.endsWith('/mods'))return json(res,{mods:{rows:[]}});
   return json(res,{ok:true,result:{ok:true},providers:[],roots:[],graphs:[],files:[],servers:[],groups:[]});
  }
  const file=path.resolve(studio,url.pathname==='/studio'?'studio.html':url.pathname.replace(/^\/studio\//,''));
  if(!file.startsWith(studio+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
  let raw=fs.readFileSync(file);
  if(file.endsWith('studio.html'))raw=cleanPage||raw.toString().replace('/*__ARCHHUB_BOOT__*/ null',entry==='legacy'?'null':JSON.stringify({token:'fixture',csrf:'fixture',first_run:false,home_load_ms:290000}));
  res.writeHead(200,{'Content-Type':file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':'text/javascript'});return res.end(raw);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
 try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1280,height:800}});page.setDefaultTimeout(5000);page.on('pageerror',e=>{errors.push(e.message);console.log('pageerror',e.message);});
  await page.addInitScript(()=>{window.bootTimeouts=[];const original=window.setTimeout;window.setTimeout=(callback,delay,...args)=>{window.bootTimeouts.push(delay);return original(callback,delay,...args);};});
  const start=Date.now();await page.goto('http://127.0.0.1:'+server.address().port+'/studio');
  await page.waitForFunction(readiness,null,{timeout:8000});
  if(entry==='clean')assert.equal(await page.evaluate(()=>window.ARCHHUB_BOOT?.home_load_ms),290000);
  await page.waitForTimeout(150);
  assert.ok(await page.evaluate(()=>window.bootTimeouts.includes(290000)),'Home uses a numeric 290 s deadline');
  assert.equal(await page.getByRole('button',{name:'Retry opening ArchHub'}).count(),0);
  assert.equal(release,false);assert.ok(await page.locator('[data-screen="home"]').isVisible());
  await page.getByRole('button',{name:'Canvas',exact:true}).click();
  if(process.env.BOOTSCALE_EVIDENCE)await page.screenshot({path:path.join(process.env.BOOTSCALE_EVIDENCE,'EARLY-CANVAS.png')});
  await page.getByRole('status').filter({hasText:/Loading your graph/}).waitFor({state:'visible'});
  await page.getByRole('button',{name:'Home',exact:true}).click();
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await page.locator('[data-screen="settings/Account"]').waitFor({state:'visible'});
  await page.getByRole('button',{name:'Home',exact:true}).click();
  assert.equal(release,false);
  const composer=page.locator('textarea').first();await composer.fill('Keep this request while opening my saved graph');
  await composer.press('Enter');
  await page.waitForFunction(()=>!document.querySelector('.composer-tools button[type="submit"]').disabled);
  assert.equal(await composer.inputValue(),'Keep this request while opening my saved graph');
  if(process.env.BOOTSCALE_EVIDENCE)await page.screenshot({path:path.join(process.env.BOOTSCALE_EVIDENCE,'SLOW-HOME.png')});
  console.log(JSON.stringify({pending_home_paint_ms:Date.now()-start}));
  release=true;for(const res of waiting)json(res,home);
  await page.evaluate(()=>window.ArchHubAPI.ready);
  assert.equal(await composer.inputValue(),'Keep this request while opening my saved graph');
  await page.getByRole('button',{name:'Canvas',exact:true}).click();
  await page.locator('[data-screen="canvas"] .node-canvas').waitFor({state:'visible'});
  await page.waitForFunction(n=>document.querySelectorAll('[data-graph-node]').length===n,canvas.nodes.length);
  assert.equal(await page.evaluate(readiness),true);
  await page.locator('[data-screen="canvas"]').evaluate(e=>e.style.display='none');
  assert.equal(await page.evaluate(readiness),false);
  assert.deepEqual(errors,[]);
 }finally{
  for(const res of waiting)res.destroy();if(browser)await browser.close();
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
 }
});

for(const hung of [false,true])test(hung?'never-returning Home read shows retry within 60 seconds':'failed Home read keeps the existing visible retry and no unhandled rejection',{timeout:hung?75000:15000},async()=>{
 let browser;
 try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage(), errors=[],logs=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error'&&message.text().includes('Home load timed out'))logs.push(message.text());});
  await page.route('https://bootscale.test/**',async route=>{
   const url=new URL(route.request().url());
   if(hung&&url.pathname==='/api/universal/canvas'&&url.searchParams.get('screen')==='home')return;
   if(url.pathname.startsWith('/api/'))return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Saved graph temporarily unavailable'})});
   const file=path.join(studio,url.pathname==='/studio'?'studio.html':url.pathname.replace(/^\/studio\//,''));
   if(!fs.existsSync(file)||!fs.statSync(file).isFile())return route.fulfill({status:404,body:''});
   let body=fs.readFileSync(file);
   if(file.endsWith('studio.html'))body=body.toString().replace('/*__ARCHHUB_BOOT__*/ null',JSON.stringify({token:'fixture',csrf:'fixture',first_run:false,home_load_ms:60000}));
   return route.fulfill({contentType:file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':'text/javascript',body});
  });
  const start=Date.now();await page.goto('https://bootscale.test/studio');
  await page.getByRole('button',{name:'Retry opening ArchHub'}).waitFor({state:'visible',timeout:hung?65000:10000});
  const elapsed=Date.now()-start;
  if(hung){assert.ok(elapsed>=59000&&elapsed<65000);assert.equal(logs.length,1);console.log(JSON.stringify({hung_home_retry_ms:elapsed,timeout_log_lines:logs.length}));}
  if(process.env.BOOTSCALE_EVIDENCE)await page.screenshot({path:path.join(process.env.BOOTSCALE_EVIDENCE,hung?'HUNG-HOME.png':'FAILED-HOME.png')});
  assert.ok(await page.getByRole('button',{name:'Retry opening ArchHub'}).evaluate(element=>{
   const box=element.getBoundingClientRect();return box.top>=0&&box.bottom<=window.innerHeight;
  }),'retry stays within the visible viewport after the shell mounts');
  assert.match(await page.locator('#studio-boot').innerText(),hung?/Home load timed out/:/Saved graph temporarily unavailable/);
  assert.deepEqual(errors,[]);
 }finally{if(browser)await browser.close();}
});
