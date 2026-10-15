/* Render the production Home with an explicitly isolated store fixture. No installed app or host. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process'),{createHash}=require('node:crypto');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8');
const sourceMode=process.env.HOME3_SOURCE==='1';
(async()=>{
 // Valid PDF fixture -> actual rasterized sheet. The product never fabricates a thumbnail.
 execFileSync('python',['-c',`from pathlib import Path
import fitz
for i in range(1,7):
 p=Path(f'evidence/HOME3-sheet-fixture-{i}.pdf')
 doc=fitz.open();page=doc.new_page(width=420,height=297)
 page.insert_text((28,38),f'HOME3 isolated package court - sheet {i}',fontsize=18)
 page.insert_text((28,70),'Reviewed file fixture - no client data',fontsize=12)
 page.insert_text((28,255),f'A10{i} | 2026-10-15 | TEST STORE',fontsize=10)
 page.draw_rect(fitz.Rect(20,20,400,277),color=(.5,.5,.5))
 doc.save(p);doc.close()
 doc=fitz.open(p);doc[0].get_pixmap().save(f'evidence/HOME3-sheet-thumbnail-{i}.png');doc.close()
`],{cwd:root});
 const sheets=Array.from({length:6},(_,i)=>{const file=path.join(root,'evidence/HOME3-sheet-fixture-'+(i+1)+'.pdf');return {
 id:'fixture-'+i,name:path.basename(file),path:file,digest:createHash('sha256').update(fs.readFileSync(file)).digest('hex'),
 thumbnail_url:'data:image/png;base64,'+fs.readFileSync(path.join(root,'evidence/HOME3-sheet-thumbnail-'+(i+1)+'.png')).toString('base64')};});
 const flow=(id,state,title,extra={})=>({root:id,title,state,proposed_by:'fixture-agent',approval:{current:true},...extra});
 const workflows=[flow('fixture-package','review','Reviewed drawing package is ready',{digest:'a'.repeat(64),approval:{current:false},package:{available:true,destination:'03.PUBLISHED/Reviewed drawing package',sheets}}),
 flow('fixture-running','running','Drawing coordination · checking references'),
 flow('fixture-complete','done','Coordination check complete',{result_summary:'Proof table is ready for review',completed_at:'2026-10-15T10:00:00Z'}),
 flow('fixture-mail','done','Project correspondence sorted',{result_summary:'Draft responses are ready',completed_at:'2026-10-15T09:00:00Z'})];
 const titles=['Drawing issue flow','Reference comparison','Drawing production','Detail coordination','Correspondence review','Source research'];
 const templates=titles.map((title,i)=>({id:'stored-'+i,title,run_count:[17,12,9,7,4,1][i],sub:(i+2)+' saved steps',child_count:i+2,
 children:Array.from({length:i+2},(_,j)=>({id:'step-'+j,title:['Read','Compare','Prepare','Check','Package','Review','Record'][j]}))}));
 const authorization={subject:'fixture-owner',session:'fixture-session'};
 const snapshot={canvas:{graph_id:'fixture-graph',root:'fixture-scope',revision:7,authorization},workshops:[{root:'fixture-room',label:'Court Workshop'}],
 workshop:{root:'fixture-room',graph_id:'fixture-graph',scope_root:'fixture-scope',can_send:true,messages:[],participants:[{root:'fixture-agent',runtime:'codex',label:'Court agent',connected:true,state:'working',attached:true}],assignments:[{work:'fixture-running',agent_session:'fixture-agent'},{work:'fixture-package',agent_session:'fixture-agent'}],workflows},
 topology:{canvas:{application_root:'fixture-graph',scope:{current:'fixture-scope'},authorization,revision:7},graph:{nodes:[],wires:[]},selected:null},nativeWork:{state:'idle'},theme:{configuration:{}},applicationUpdate:{state:'idle'}};
 const record={notice:'Isolated store fixture; real PDF rendered for preview. Not installed/live work.',snapshot,templates};
 fs.writeFileSync(path.join(root,'evidence/HOME3-render-fixture.json'),JSON.stringify(record,null,2));
 const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage({viewport:{width:1496,height:959},deviceScaleFactor:1});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const fontCss=JSON.parse(read('public_site/site-export.json')).assets['assets/fonts.css'];
 await page.route('http://127.0.0.1:53992/assets/fonts.css',route=>route.fulfill({contentType:'text/css',body:fontCss}));
 await page.route('http://127.0.0.1:53992/assets/fonts/*',route=>route.fulfill({contentType:'font/woff2',body:fs.readFileSync(path.join(root,'nodelang/data/website/fonts',path.basename(new URL(route.request().url()).pathname)))}));
 await page.route('http://127.0.0.1:53992/',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><head><link rel="stylesheet" href="/assets/fonts.css"><style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden}*{box-sizing:border-box}button,input,textarea{font:inherit}</style></head><body><div id="root"></div></body></html>'}));
 await page.goto('http://127.0.0.1:53992/');
 await page.evaluate(({snapshot,templates})=>{
 window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
 window.fetch=async url=>({ok:true,json:async()=>String(url).includes('/models')?{ok:true,groups:[],selected_route:'openrouter/court'}:{ok:true,items:[],tools:[]}});
 window.ARCHHUB_LIVE={sessions:[{id:'fixture-graph',title:'Isolated court graph',state:'idle'}],currentGraph:'fixture-graph',hosts:[],connectors:[],graph:{nodes:[],wires:[]},memory:[],skills:[]};
 window.ARCHHUB_TOOL_HUB={tools:[],waiting:[]};
 const owner={getSnapshot:()=>snapshot,subscribe:()=>()=>{},watchApplicationUpdate:()=>()=>{},readHomeTemplates:async()=>({ok:true,templates}),refreshHomeWorkshops:async()=>{},workshopWorkflow:async()=>{throw Error('Render fixture cannot publish');}};
 window.ARCHHUB_EXISTING_WORKSHOP=new Proxy(owner,{get:(target,key)=>key in target||typeof key!=='string'||key==='then'?target[key]:()=>new Promise(()=>{})});
 },record);
 for(const file of ['react.js','react-dom.js'])await page.addScriptTag({content:read('nodelang/studio/vendor/'+file)});
 const sources=['tokens.jsx','design-canvas.jsx','shared-data.jsx','studio-suite.jsx','param-types.jsx','studio-params.jsx','studio-mobile.jsx','studio-account.jsx','node-registry.jsx','brain-model.jsx','workshop-board.jsx','studio-workshop.jsx','studio-lm.jsx'];
 const manifest=sourceMode?null:JSON.parse(read('nodelang/studio/compiled/manifest.json'));
 for(const source of sources){let code;if(sourceMode)code=require('esbuild').transformSync(read('nodelang/studio/'+source),{loader:'jsx'}).code;
 else{const row=manifest.files.find(row=>row.source===source);assert.equal(row.source_sha256,createHash('sha256').update(read('nodelang/studio/'+source)).digest('hex'));code=read('nodelang/studio/compiled/'+row.output);}await page.addScriptTag({content:code});}
 await page.evaluate(()=>{window.__renderRoot=ReactDOM.createRoot(document.getElementById('root'));ReactDOM.flushSync(()=>window.__renderRoot.render(React.createElement(StudioLM)));});
 await page.waitForTimeout(2150);await page.locator('[data-rail-panel="Home"]').click();await page.locator('[data-home-template]').first().waitFor();
 await page.evaluate(async()=>{await document.fonts.load('13px Inter');await document.fonts.ready;});
 await page.screenshot({path:path.join(root,'evidence/HOME3-1496x959.png')});
 const geometry=await page.locator('[data-home-page]').evaluate(el=>({rect:el.getBoundingClientRect().toJSON(),overflowX:el.scrollWidth>el.clientWidth,overflowY:el.scrollHeight>el.clientHeight,
 heading:el.querySelector('[data-home-heading]').getBoundingClientRect().toJSON(),results:el.querySelector('[data-home-results]').getBoundingClientRect().toJSON(),templates:el.querySelector('[data-home-templates]').getBoundingClientRect().toJSON(),composer:el.querySelector('[data-home-composer]').getBoundingClientRect().toJSON(),railCount:document.querySelectorAll('[data-app-rail]').length}));
 assert.deepEqual(errors,[]);assert.equal(geometry.overflowX,false);assert.equal(geometry.overflowY,false);assert.equal(geometry.railCount,1);
 fs.writeFileSync(path.join(root,'evidence/HOME3-geometry.json'),JSON.stringify({sourceMode,errors,...geometry},null,2));
 const plate=fs.readFileSync(path.join(root,'design/ARCHHUB-CLD-DES-DSYS-082-2026-10-13_5.6b_home2.png')).toString('base64'),actual=fs.readFileSync(path.join(root,'evidence/HOME3-1496x959.png')).toString('base64');
 const comparison=await browser.newPage({viewport:{width:3024,height:1015},deviceScaleFactor:1});
 await comparison.setContent(`<html><body style="margin:0;padding:12px;display:flex;gap:8px;background:#0a0a0d;color:#eee;font:13px sans-serif"><div><p style="margin:0 0 10px">DSYS-082 plate</p><img width="1496" height="959" src="data:image/png;base64,${plate}"></div><div><p style="margin:0 0 10px">HOME3 production renderer · isolated store fixture · shared eight-item rail</p><img width="1496" height="959" src="data:image/png;base64,${actual}"></div></body></html>`);
 await comparison.screenshot({path:path.join(root,'evidence/HOME3-side-by-side.png'),fullPage:true});
 console.log('HOME3 render: 1496x959; browser exceptions=0; horizontal overflow=false; vertical overflow=false; rail=1; evidence/HOME3-side-by-side.png');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
