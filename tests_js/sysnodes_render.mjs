import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {chromium} from 'playwright';
const require=createRequire(import.meta.url);
const {applicationScripts,normalProjectionMapperSource,seed,root,read}=require('./studio_sysnodes.test.cjs');
const fixture=path.join(root,'evidence/sysnodes-projection.json');
if(!fs.existsSync(fixture))throw Error('Render requires actual backend-generated projection: '+fixture);
const raw=JSON.parse(fs.readFileSync(fixture));
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1496,height:959},deviceScaleFactor:1});
 await page.route('http://127.0.0.1:53983/',r=>r.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><head><meta charset="utf-8"><style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden}*{box-sizing:border-box}</style></head><body><div id="root"></div></body></html>'}));
 await page.goto('http://127.0.0.1:53983/');
 await page.evaluate(({seed})=>{
   window.fetch=async()=>({ok:true,json:async()=>({ok:true,models:[]})});
   window.ARCHHUB_THEME=seed;
   window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
 },{seed});
 await page.addScriptTag({content:read('nodelang/studio/studio-authority.js')});
 await page.addScriptTag({content:normalProjectionMapperSource()});
 await page.evaluate(async({raw,seed})=>{
   let projection=raw;
   if(Array.isArray(raw.nodes)){
     if(raw.graph_id){const mapper=window.ArchHubStudioAuthority.create({get:async()=>raw,post:async()=>raw,uuid:()=> 'render-fake-command'});
       await mapper.load();projection=mapper.getSnapshot();}
     else projection={canvas:raw,graph:projectStudioCanvas(raw)};
   }
   window.__projection=projection;
   const listeners=new Set();
   window.ARCHHUB_STUDIO_AUTHORITY={getSnapshot:()=>projection,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},open:async()=>({ok:true}),moveMany:async positions=>{
     projection.graph={...projection.graph,nodes:projection.graph.nodes.map(n=>positions[n.id]?{...n,...positions[n.id]}:n)};
     projection.canvas.revision++;listeners.forEach(fn=>fn());return{ok:true};
   }};
   window.ARCHHUB_SET_NODE_PROP=async(id,key,value)=>{
     const row=projection.graph.nodes.find(n=>n.id===id)?.params.find(p=>p.k===key);if(!row)throw Error('missing owner setting');row.v=value;listeners.forEach(f=>f());return{ok:true};
   };
   window.ARCHHUB_EXISTING_WORKSHOP={getSnapshot:()=>({canvas:projection.canvas,theme:{configuration:{theme:seed,binding_mode:'personal-wip',state:'WIP',history:[],personal_wip_heads:['fake-head']}}}),subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},watchApplicationUpdate:()=>()=>{},readProviders:async()=>[]};
   window.ARCHHUB_LIVE={graph:projection.graph,hosts:[],connectors:[],sessions:[],memory:[],skills:[]};
 },{raw,seed});
 await page.addScriptTag({content:read('nodelang/studio/vendor/react.js')});
 await page.addScriptTag({content:read('nodelang/studio/vendor/react-dom.js')});
 for(const script of applicationScripts())await page.addScriptTag({content:script});
 await page.evaluate(()=>{
   const focus=window.__projection.graph.nodes.find(n=>n.application&&(n.params||[]).some(p=>p.k==='accent'))?.id;
   function SystemRender(){
     const [selected,setSelected]=React.useState(focus);
     return React.createElement('div',{style:{display:'grid',gridTemplateColumns:'minmax(0,1fr) 320px',gridTemplateRows:'36px minmax(0,1fr)',height:'100vh',background:window.AH.bg,color:window.AH.ink,fontFamily:window.AH.sans}},
       React.createElement('div',{style:{gridColumn:'1 / -1',padding:'9px 16px',borderBottom:'1px solid '+window.AH.line,fontSize:12}},'System graph · real application settings · fake transport'),
       React.createElement(NodeCanvas,{focusId:selected,setFocusId:setSelected,setLibraryOpen:()=>{},system:true,fitOnOpen:true}),
       React.createElement(NodeRail,{node:window.__projection.graph.nodes.find(n=>n.id===selected),graph:window.__projection.graph,canvas:window.__projection.canvas,scope:window.__projection.canvas.root,setPickerOpen:()=>{}}));
   }
   window.__studioRoot=ReactDOM.createRoot(document.getElementById('root'));
   ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(SystemRender)));
 });
 await page.waitForTimeout(1000);
 const arrange=page.getByRole('button',{name:/^Arrange$/});if(await arrange.count())await arrange.first().click();
 await page.waitForTimeout(300);
 const fit=page.getByRole('button',{name:/^Fit$/});if(await fit.count())await fit.first().click();
 await page.waitForTimeout(300);
 await page.screenshot({path:path.join(root,'evidence/sysnodes-after.png')});
 const metrics=await page.evaluate(()=>{
   const region=document.querySelector('[aria-label="Workflow canvas"]').getBoundingClientRect();
   const cards=[...document.querySelectorAll('[data-node-id]')];
   const clippedCards=cards.filter(card=>{const box=card.getBoundingClientRect();return box.left<region.left||box.right>region.right||box.top<region.top||box.bottom>region.bottom-60;}).map(card=>card.getAttribute('data-node-id'));
   const clippedControls=[],clippedSockets=[];let socketControls=0;
   for(const card of cards){const outer=card.getBoundingClientRect();for(const control of card.querySelectorAll('input,select,button')){
     const box=control.getBoundingClientRect();if(!box.width||!box.height)continue;
     if(control.closest('[data-port-band]')){
       socketControls++;
       if(box.left<region.left||box.right>region.right||box.top<region.top||box.bottom>region.bottom-60)clippedSockets.push({node:card.getAttribute('data-node-id'),control:control.getAttribute('aria-label')});
       continue;
     }
     if(box.left<outer.left-1||box.right>outer.right+1||box.top<outer.top-1||box.bottom>outer.bottom+1)clippedControls.push({node:card.getAttribute('data-node-id'),control:control.getAttribute('aria-label')||control.textContent});
   }}
   return{nodes:cards.length,cells:document.querySelectorAll('[data-sysnode-cell]').length,wires:document.querySelectorAll('[data-wire-id]').length,labels:document.querySelectorAll('[data-sysnode-wire-label]').length,clippedCards,clippedControls,socketControls,clippedSockets};
 });
 console.log(JSON.stringify({artifact:'mounted-source',transport:'fake',...metrics}));
 if(metrics.clippedCards.length||metrics.clippedControls.length||metrics.clippedSockets.length)throw Error('System graph render clips real cards or controls; see measured metrics');
 const before=fs.readFileSync(path.join(root,'design/system-graph-today.png')).toString('base64');
 const after=fs.readFileSync(path.join(root,'evidence/sysnodes-after.png')).toString('base64');
 const compare=await browser.newPage({viewport:{width:2992,height:1010},deviceScaleFactor:1});
 await compare.setContent('<html><body style="margin:0;background:#111;color:#fff;font:18px Arial"><div style="display:flex"><section><p style="margin:12px 20px">Before · supplied installed screenshot</p><img width="1496" src="data:image/png;base64,'+before+'"></section><section><p style="margin:12px 20px">After · actual source components / backend projection / fake transport</p><img width="1496" src="data:image/png;base64,'+after+'"></section></div></body></html>');
 await compare.screenshot({path:path.join(root,'evidence/sysnodes-before-after.png'),fullPage:true});
}finally{await browser.close();}
