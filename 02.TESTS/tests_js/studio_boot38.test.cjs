/* Exercise the shipped integrity loader and the launcher's actual readiness JS. */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright');
const repo=path.resolve(__dirname,'../..');
const studio=process.env.BOOT38_STUDIO||path.join(repo,'01.APP/nodelang/studio');
const launcher=fs.readFileSync(path.join(repo,'01.APP/nodelang/launcher.py'),'utf8');
const readiness=launcher.slice(launcher.indexOf('def _prepare_pipeline_after_home(')).match(/runJavaScript\("""([\s\S]*?)""", observed\)/)[1];
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/clean-canvas-fresh-runtime.json'),'utf8'));
for(const empty of [true,false])test('BOOT38 built loader paints '+(empty?'empty':'saved')+' Home before full graph, then admits Canvas',{timeout:40000},async()=>{
 const canvas=JSON.parse(JSON.stringify(fixture));
 if(empty){canvas.nodes=[];canvas.wires=[];}
 const home={...canvas,projection:'home',nodes:[],wires:[],catalog:[],selected:[]};
 const waiting=new Set();let release=false;const reads=[];
 const json=(res,data)=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
 const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');reads.push(url.pathname+url.search);
  if(url.pathname==='/api/universal/canvas'){
   if(url.searchParams.get('screen')==='home')return json(res,home);
   if(release)return json(res,canvas);
   waiting.add(res);res.on('close',()=>waiting.delete(res));return;
  }
  if(url.pathname.startsWith('/api/')){
   if(url.pathname.endsWith('/session'))return json(res,{token:'fixture',csrf:'fixture'});
   if(url.pathname.endsWith('/graphs'))return json(res,{graphs:[{id:'application',title:'System graph'},{id:canvas.root,title:'Fixture graph'}],current_graph:canvas.root});
   if(url.pathname.endsWith('/canvas-op')){let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{const op=JSON.parse(body).op;json(res,{result:op==='project_state'?{versions:[],dismissed:[],modelReview:{operation:'',results:[],issues:[]}}:[]});});return;}
   if(url.pathname.endsWith('/mods'))return json(res,{mods:{rows:[]}});
   return json(res,{ok:true,result:{ok:true},providers:[],roots:[],graphs:[],files:[],servers:[],groups:[]});
  }
  if(url.pathname==='/assets/fonts.css'){res.writeHead(200,{'Content-Type':'text/css'});res.end();return;}
  if(url.pathname==='/favicon.ico'){res.writeHead(204);res.end();return;}
  const relative=url.pathname==='/studio'?'studio.html':url.pathname.replace(/^\/studio\//,'');
  const file=path.resolve(studio,relative);
  if(!file.startsWith(path.resolve(studio)+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
  const raw=fs.readFileSync(file);
  res.writeHead(200,{'Content-Type':file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':'text/javascript'});
  return res.end(file.endsWith('studio.html')?raw.toString('utf8').replace('/*__ARCHHUB_BOOT__*/ null',JSON.stringify({token:'fixture',csrf:'fixture',first_run:empty})):raw);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 let browser;
 try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const start=Date.now();await page.goto('http://127.0.0.1:'+server.address().port+'/studio');
  await page.waitForFunction(readiness,null,{timeout:10000});
  assert.ok(await page.locator('[data-screen="home"]').isVisible());
  assert.ok(reads.includes('/api/universal/canvas?screen=home'));
  assert.equal(release,false,'Home paints while full graph responses remain held');
  assert.equal(await page.locator('script[src^="/studio/compiled/"]').count(),40);
  console.log(JSON.stringify({case:empty?'empty':'saved',screen:'home',ready:true,elapsed_ms:Date.now()-start,errors}));
  if(process.env.BOOT38_EVIDENCE)await page.screenshot({path:path.join(process.env.BOOT38_EVIDENCE,'BOOT38-HOME.png')});
  release=true;for(const res of waiting)json(res,canvas);
  await page.getByRole('button',{name:'Canvas',exact:true}).click();
  await page.locator('[data-screen="canvas"] .node-canvas').waitFor({state:'visible',timeout:10000});
  assert.equal(await page.evaluate(readiness),true,'a painted Canvas completes launcher startup without legacy globals');
  assert.equal(await page.locator('[data-graph-node]').count(),canvas.nodes.length);
  assert.deepEqual(errors,[]);
  if(process.env.BOOT38_EVIDENCE)await page.screenshot({path:path.join(process.env.BOOT38_EVIDENCE,'BOOT38-CANVAS.png')});
  await page.locator('[data-screen="canvas"]').evaluate(element=>element.style.display='none');
  assert.equal(await page.evaluate(readiness),false,'a hidden Canvas is not ready');
  console.log(JSON.stringify({case:empty?'empty':'saved',screen:'canvas',ready:true,nodes:canvas.nodes.length,errors}));
 }finally{
  release=true;for(const res of waiting)res.destroy();
  if(browser)await browser.close();
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
 }
});
