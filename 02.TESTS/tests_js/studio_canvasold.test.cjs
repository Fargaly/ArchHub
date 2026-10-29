'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {transformSync} = require('esbuild');
const {chromium} = require('playwright');
const xyflow = require('./studio_xyflow.cjs'); // CANVASXY: the canvas runs on the bundled xyflow
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const read = name => fs.readFileSync(path.join(process.env.CANVASOLD_STUDIO || studio,name),'utf8');
const prop = (label,value,type='number',unit='') => ({label,value,type,editor:type,unit,editable:true,relation:'property-'+label});
const port = (id,name,side,type,list=false,extra={}) => ({id,name,side,logical_type:type,contract_root:'contract-'+type,contract:'contract-'+type,cardinality:list?'many':'one',connectable:true,...extra});
function fixture(){return {root:'root',graph_id:'root',revision:1,scope:{current:'user',current_label:'My work'},viewport:{zoom:1},
 nodes:[{id:'level',label:'Level',kind:'Input',assembly:{definition:'number-def',name:'Number',version:'1',interfaces:[],part_count:1},category:'Input',x:80,y:80,application:false,properties:[prop('value',3,'number','m')],ports:[port('level-value','value','source','number')]},
 {id:'filter',label:'Filter',kind:'Filter',assembly:{definition:'filter-def',name:'Filter',version:'1',interfaces:[],part_count:1},category:'Shape',x:470,y:80,application:false,properties:[prop('threshold',2,'number','m')],ports:[port('filter-count','count','target','number'),port('filter-items','items','target','elements',true),port('filter-result','result','source','elements',true),port('filter-event','done','source','event')]},
 {id:'text',label:'Text',kind:'Input',assembly:{definition:'text-def',name:'Text',version:'1',interfaces:[],part_count:1},category:'Input',x:850,y:80,application:false,properties:[prop('value','hello','text')],ports:[port('text-value','value','source','text')]},
 {id:'revit',label:'Revit',kind:'Host',category:'Host',group:'Hosts',x:0,y:0,application:true,properties:[prop('enabled',true,'boolean')],ports:[port('revit-out','elements','source','elements',true,{connectable:false,read_only:true})]},
 {id:'agents',label:'Models & Agents',kind:'Agent',category:'AI',group:'Agents',x:0,y:0,application:true,properties:[],ports:[port('agent-in','elements','target','elements',true,{connectable:false,read_only:true})]},
 {id:'studio',label:'Studio',kind:'System',category:'System',group:'Studio',x:0,y:0,application:true,properties:[],ports:[]}],
 wires:[{id:'wire-value',source:'level',target:'filter',source_interface:'level-value',target_interface:'filter-count',value_type:'number'},{id:'reader-wire',source:'revit',target:'agents',source_interface:'revit-out',target_interface:'agent-in',value_type:'elements'}],
 catalog:[{id:'number-def',name:'Number',category:'Input',parameters:{value:{type:'number',unit:'m'}},interface_contract:{value:{type:'number',direction:'output'}},descriptor:{engine:'Input'}},
 {id:'text-def',name:'Text',category:'Input',parameters:{value:{type:'text'}},interface_contract:{value:{type:'text',direction:'output'}},descriptor:{engine:'Input'}},
 {id:'filter-def',name:'Filter',category:'Shape',parameters:{threshold:{type:'number',unit:'m'}},interface_contract:{count:{type:'number',direction:'input'},items:{type:'elements',multiple:true,direction:'input'},result:{type:'elements',multiple:true,direction:'output'},done:{type:'event',direction:'output'}},descriptor:{engine:'Filter'}}]};}
async function mount(t,{raw=fixture(),shell=false,system=false}={}) {
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 t.after(()=>browser.close());
 const page=await browser.newPage({viewport:{width:1496,height:960}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<div id="root" style="display:grid;height:100vh"></div>'}));
 await page.goto('http://canvasold.test/');
 await page.addStyleTag({content:xyflow.css()+read('style.css')+'html,body{margin:0;height:100%}'});
 for(const name of ['vendor/react.js','vendor/react-dom.js','xyflow','tokens.jsx','ds/index.jsx','icons.jsx'])
  await page.addScriptTag({content:name==='xyflow'?xyflow.script():name.endsWith('.jsx')?transformSync(read(name),{loader:'jsx'}).code:read(name)});
 await page.evaluate(raw=>{
  window.fixtureRaw=raw; window.fixtureCalls=[];
  window.fetch=async (url,options={})=>{
   let data={ok:true,result:[],tasks:[],providers:[],agents:[],items:[],workspaces:[]};
   if(url==='/api/universal/session')data={token:'fixture',csrf:'fixture'};
   else if(url.startsWith('/api/universal/canvas?')||url==='/api/universal/canvas')data=window.fixtureRaw;
   else if(url.startsWith('/api/universal/graphs'))data={graphs:[{id:'root',title:'System'},{id:'user',title:'User graph'}],current_graph:window.fixtureRaw.scope.current};
   else if(url==='/api/universal/gesture'){
    const body=JSON.parse(options.body);window.fixtureCalls.push({action:'move',body});
    if(window.holdMove)await new Promise(resolve=>{window.releaseMove=resolve;});
    window.fixtureRaw={...window.fixtureRaw,revision:window.fixtureRaw.revision+1,nodes:window.fixtureRaw.nodes.map(n=>({...n,...body.positions[n.id]}))};data=window.fixtureRaw;
   }
   else if(url==='/api/universal/canvas-op'&&JSON.parse(options.body).op==='library_ports')data={ok:true,result:window.fixtureRaw.fixtureLibraryPorts||[]};
   else if(url==='/api/universal/graph-open'){
    const root=JSON.parse(options.body).root;window.fixtureCalls.push({action:'open',root});
    window.fixtureRaw={...window.fixtureRaw,scope:{current:root,current_label:root==='root'?'System':'User graph'}};data=window.fixtureRaw;
   }
   return {ok:true,status:200,json:async()=>data};
  };
 },raw);
 for(const name of ['studio-authority.js','api.js'])await page.addScriptTag({content:read(name)});
 await page.evaluate(async()=>{await window.ArchHubAPI.ready;});
 await page.addScriptTag({content:transformSync(read('ui.jsx'),{loader:'jsx'}).code});
 await page.evaluate(()=>{
  const R=window.React,h=R.createElement,real=window.ArchHubAPI;
  let state={...real.getSnapshot(),connectionNotice:'● Isolated fixture'};const listeners=new Set();
  const publish=values=>{state={...state,...values,revision:state.revision+1};listeners.forEach(f=>f());};
  const api={...real,refreshProjects:async()=>{},getSnapshot:()=>state,subscribe:f=>{listeners.add(f);return()=>listeners.delete(f);},
   refreshSystemGraph:async()=>{},refreshAgentSurface:async()=>null,getNodeParameters:id=>state.graph.nodes.find(n=>n.id===id)?.parameterSchema||[],
   connectSockets:async wire=>{window.fixtureCalls.push({action:'connect',wire});return {ok:true};},setSetting:async()=>{},
   selectGraph:async id=>{window.fixtureCalls.push({action:'selectGraph',id});if(window.fixtureRaw.fixtureSystemFailures>0){window.fixtureRaw.fixtureSystemFailures--;throw Error('System graph read refused');}return {ok:true};}};
  api.moveNodes=async positions=>{const result=await real.moveNodes(positions);publish({graph:real.getSnapshot().graph});return result;};
  api.setNodeParam=async(id,key,value)=>{window.fixtureCalls.push({action:'parameter',id,key,value});publish({graph:{...state.graph,nodes:state.graph.nodes.map(n=>n.id===id?{...n,params:{...n.params,[key]:value}}:n)}});};
  window.UI={...window.UI,A:window.AH,D:window.AH_DS,api,
   useData:()=>R.useSyncExternalStore(api.subscribe,api.getSnapshot),
   Home:()=>null,AccountIdentity:()=>null,BaboomSprite:()=>null,GraphProperties:()=>null,NodeRunPolicy:()=>null,MixedProperties:()=>null,CapabilityRows:()=>null};
  window.fixtureState=()=>state;window.fixturePublish=publish;
  window.mountFixture=system=>{
   function Fixture(){const [libraryOpen,setLibraryOpen]=R.useState(true),[selectedNodeId,setSelectedNodeId]=R.useState(null);
    const app={libraryOpen,setLibraryOpen,selectedNodeId,setSelectedNodeId,act:f=>Promise.resolve(f()),show:(kind,data)=>window.fixtureCalls.push({action:'show',kind,data}),go:route=>window.fixtureCalls.push({action:'go',route})};
    return h(window.UI.Ctx.Provider,{value:app},h(system?window.UI.SystemGraph:window.UI.Canvas));}
   window.ReactDOM.createRoot(document.getElementById('root')).render(h(Fixture));
  };
 });
 for(const name of ['ds_library.jsx','ds_screens.jsx','ds_settings3.jsx'])await page.addScriptTag({content:transformSync(read(name),{loader:'jsx'}).code});
 if(shell)await page.addScriptTag({content:transformSync(read('app.jsx'),{loader:'jsx'}).code});
 else await page.evaluate(system=>window.mountFixture(system),system);
 if(shell){await page.getByRole('button',{name:'Canvas',exact:true}).click();}
 await page.locator(system?'[data-screen="system"]':'.node-canvas').waitFor();
 await page.waitForTimeout(180);
 if(shell&&process.env.CANVASOLD_EVIDENCE)await page.screenshot({path:path.join(process.env.CANVASOLD_EVIDENCE,process.env.CANVASOLD_STUDIO?'BEFORE-INSTALLED-CODE.png':'AFTER.png')});
 t.after(()=>assert.deepEqual(errors,[],'no browser errors'));
 return page;
}
test('actual adapter preserves declared types, cardinality, units and real endpoint IDs',async t=>{
 const page=await mount(t),s=await page.evaluate(()=>window.fixtureState());
 const n=s.graph.nodes.find(n=>n.id==='filter');
 assert.equal(n.inputs.find(p=>p.id==='filter-count').type,'number');
 assert.equal(n.inputs.find(p=>p.id==='filter-items').list,true);
 assert.equal(s.graph.nodes.find(n=>n.id==='level').outputs[0].unit,'m');
 // Every typed socket is an xyflow Handle carrying its real endpoint key and declared type.
 assert.equal(await page.locator('[data-port-key="filter:in:filter-items"]').evaluate(el=>el.classList.contains('react-flow__handle')&&el.dataset.portList),'true');
 assert.equal(await page.locator('[data-port-key="filter:out:filter-event"]').getAttribute('data-port-type'),'event');
 assert.equal(await page.locator('[data-port-key="level:out:level-value"]').count(),1);
});
test('every wire terminates at the real socket centers',async t=>{
 const page=await mount(t);
 const delta=await page.evaluate(()=>{
  const wire=document.querySelector('[data-graph-wire]');
  const nums=wire.getAttribute('d').match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi).map(Number);
  const world=document.querySelector('.node-canvas .react-flow__viewport'),matrix=new window.DOMMatrix(window.getComputedStyle(world).transform),wr=world.getBoundingClientRect();
  return [['level:out:level-value',nums[0],nums[1]],['filter:in:filter-count',nums.at(-2),nums.at(-1)]].map(([key,x,y])=>{
   const r=document.querySelector('[data-port-key="'+key+'"]').getBoundingClientRect();return Math.hypot(wr.left+x*matrix.a-(r.left+r.width/2),wr.top+y*matrix.d-(r.top+r.height/2));});
 });
 assert.ok(delta.every(d=>d<.5),JSON.stringify(delta));
});
test('clicking a wire inspects its type, both sockets and its value',async t=>{
 const page=await mount(t);
 await page.locator('[data-graph-wire]').first().evaluate(el=>el.parentNode.querySelector('.react-flow__edge-interaction').dispatchEvent(new window.MouseEvent('click',{bubbles:true})));
 const text=await page.locator('[data-wire-inspection]').innerText();
 for(const label of ['Type','From','To','Value'])assert.match(text,new RegExp(label));
 assert.match(text,/Number/);
});test('logical type mismatch never writes a wire; compatible socket activation writes the real IDs',async t=>{
 const page=await mount(t);
 const key=key=>page.locator('[data-port-key="'+key+'"]');
 const wire=async(a,b)=>{const p=await key(a).boundingBox(),q=await key(b).boundingBox(),release=await beginDrag(page,{x:p.x+p.width/2,y:p.y+p.height/2},{x:q.x+q.width/2,y:q.y+q.height/2});await release();await page.waitForTimeout(60);};
 await wire('text:out:text-value','filter:in:filter-count');
 assert.equal((await page.evaluate(()=>window.fixtureCalls)).filter(c=>c.action==='connect').length,0);
 assert.match(await page.locator('[data-refused-chip]').innerText(),/Needs a text → number converter/,'refusal is inline on the target socket, no modal');
 assert.equal((await page.evaluate(()=>window.fixtureCalls)).filter(c=>c.action==='show'&&c.kind==='Type mismatch').length,0);
 await page.locator('.node-canvas').press('Escape');
 await wire('level:out:level-value','filter:in:filter-count');
 const calls=(await page.evaluate(()=>window.fixtureCalls)).filter(c=>c.action==='connect');
 assert.equal(calls.length,1);assert.deepEqual(calls[0].wire,{from:'level',to:'filter',fromPort:'level-value',toPort:'filter-count'});
});
test('real shell gives canvas all height below top bar, floats composer and fills Library to bottom',async t=>{
 const page=await mount(t,{shell:true});
 if(process.env.CANVASOLD_EVIDENCE)fs.writeFileSync(path.join(process.env.CANVASOLD_EVIDENCE,'BROWSER-METRICS.json'),JSON.stringify(await page.locator('.node-canvas,[data-graph-node]').evaluateAll(els=>els.map(el=>({node:el.dataset.graphNode,rect:el.getBoundingClientRect().toJSON(),clientWidth:el.clientWidth,style:el.getAttribute('style')}))),null,2));
 const boxes=await page.evaluate(()=>{
  const rect=q=>document.querySelector(q)?.getBoundingClientRect().toJSON();return {window:window.innerHeight,top:rect('.app-window > header'),canvas:rect('.node-canvas'),library:rect('.library-shelf'),composer:rect('.global-composer'),position:window.getComputedStyle(document.querySelector('.global-composer')).position,footer:rect('.app-window > footer')};
 });
 const cards=await page.locator('[data-graph-node]').evaluateAll(els=>els.map(el=>el.getBoundingClientRect().toJSON()));
 assert.ok(cards.every(b=>b.x>=boxes.canvas.x&&b.right<=boxes.canvas.right&&b.y>=boxes.canvas.y&&b.bottom<=boxes.canvas.bottom),'all nodes fit after Library opens');
 assert.equal(boxes.canvas.y,boxes.top.bottom);assert.equal(boxes.canvas.bottom,boxes.window);
 assert.equal(boxes.library.y,boxes.top.bottom);assert.equal(boxes.library.bottom,boxes.window);
 assert.equal(boxes.position,'absolute');assert.ok(boxes.composer.y>boxes.canvas.y&&boxes.composer.bottom<boxes.canvas.bottom);
 assert.ok(!boxes.footer||boxes.footer.height===0,'no bottom footer band');
 if(process.env.CANVASOLD_EVIDENCE)await page.screenshot({path:path.join(process.env.CANVASOLD_EVIDENCE,'AFTER.png')});
});
test('system nodes are absent from Canvas; Settings System graph groups actual system nodes',async t=>{
 const page=await mount(t);
 assert.equal(await page.locator('[data-graph-node="revit"]').count(),0);
 assert.equal(await page.locator('[data-graph-node="agents"]').count(),0);
 const system=await mount(t,{system:true});
 assert.equal(await system.locator('[data-system-group]').count(),3);
 for(const id of ['revit','agents','studio'])assert.equal(await system.locator('[data-graph-node="'+id+'"]').count(),1);
 assert.equal(await system.locator('[data-graph-node="level"]').count(),0);
 assert.equal(await system.locator('[data-system-wires] [data-graph-wire="reader-wire"]').count(),1,'actual system relation retains its edge');
 if(process.env.CANVASOLD_EVIDENCE)await system.screenshot({path:path.join(process.env.CANVASOLD_EVIDENCE,'SYSTEM.png')});
});

async function navigation({delayCanvas=async()=>{}}={}) {
 const vm=require('node:vm'),calls=[],stored={},root='root';let current='user';
 const snapshot=()=>({root,revision:1,scope:{current},nodes:[],wires:[],catalog:[]});
 const window={structuredClone:globalThis.structuredClone,crypto:require('node:crypto').webcrypto,
  ARCHHUB_BOOT:{home_load_ms:60000,token:'fixture',csrf:'fixture'},document:{hidden:true,addEventListener(){}},addEventListener(){},dispatchEvent(){},
  ArchHubStudioAuthority:{create:({get})=>{let canvas;return {getSnapshot:()=>({canvas}),clear:()=>{canvas=null;},adopt:async result=>canvas=result,transact:async action=>canvas=await action(),load:async()=>canvas=await get('/api/universal/canvas')};}}};
 const fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({url,body});let data={ok:true,result:[],mods:{rows:[]}};
  if(url==='/api/universal/canvas'){data=snapshot();await delayCanvas(current);}
  if(url==='/api/universal/graphs?screen=home')data={ok:true,graphs:[{id:'root'},{id:'user'},{id:'other'}],current_graph:current};
  if(url==='/api/universal/graph-open'){current=body.root;data={ok:true};}
  return {ok:true,status:200,json:async()=>data};
 };
 vm.runInNewContext(read('api.js'),{window,document:window.document,fetch,
  sessionStorage:{getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=v;}},CustomEvent:class{},setTimeout,clearTimeout,URLSearchParams,AbortSignal,console});
 await window.ArchHubAPI.ready;await new Promise(r=>setTimeout(r,5));
 return {api:window.ArchHubAPI,calls,stored};
}
test('explicit Settings system navigation preserves and restores the last admitted user graph',async()=>{
 const s=await navigation();await s.api.selectGraph('user');await s.api.selectGraph('root');
 assert.equal(s.api.getSnapshot().graph.id,'root');assert.equal(JSON.parse(s.stored['archhub.studio.session']).lastGraphId,'user');
 await s.api.refreshProjects();assert.equal(s.api.getSnapshot().graph.id,'user');
 assert.deepEqual(s.calls.filter(c=>c.url==='/api/universal/graph-open').map(c=>c.body.root),['user','root','user']);
});
test('a slow System canvas response cannot overwrite newer explicit user navigation',async()=>{
 let release,entered;const started=new Promise(r=>{entered=r;});let hold=false;
 const s=await navigation({delayCanvas:async id=>{if(hold&&id==='root'){entered();await new Promise(r=>{release=r;});}}});
 hold=true;const system=s.api.selectGraph('root');await started;
 await s.api.selectGraph('other');release();await system;
 assert.equal(s.api.getSnapshot().graph.id,'other');
});

function desktopFixture(){
 const raw=fixture();
 raw.fixtureLibraryPorts=[{id:'number',title:'Number',engine:'data.constant',cat:'Input',ports:{source:[{id:'value',type:'number',logical_type:'number',cardinality:'one'}],target:[]}},
 {id:'text',title:'Text',engine:'data.constant',cat:'Input',ports:{source:[{id:'value',type:'text',logical_type:'text',cardinality:'one'}],target:[]}},
 {id:'filter',title:'Filter',engine:'data.filter',cat:'Shape',ports:{source:[{id:'result',type:'elements',cardinality:'many'},{id:'done',type:'event',cardinality:'one'}],target:[{id:'count',type:'number',cardinality:'one'},{id:'items',type:'elements',cardinality:'many'}]}}];
 raw.catalog=raw.catalog.map(c=>({id:c.id,name:c.name,version:'1',interfaces:Object.keys(c.interface_contract).length,parts:1,category:c.category,interface_details:Object.keys(c.interface_contract).map(name=>({name,contract:'Universal assembly',contract_root:'universal-contract'}))}));
 raw.nodes=raw.nodes.map(n=>{
  if(n.application)return n;
  const engine=n.id==='filter'?'data.filter':'data.constant';
  return {...n,label:n.assembly.name,kind:undefined,engine,category:undefined,properties:[...n.properties,{label:'engine',value:engine,editor:'text'}],
   ports:n.ports.map(({logical_type,cardinality,...p})=>({...p,contract:'Universal assembly',contract_root:'universal-contract',mode:'connection'}))};
 });
 return raw;
}
test('desktop assembly objects and library_ports metadata render real typed interfaces without a clean-only schema',async t=>{
 const page=await mount(t,{raw:desktopFixture()}),s=await page.evaluate(()=>window.fixtureState());
 assert.equal(s.graph.nodes.find(n=>n.id==='level').kind,'data.constant');
 assert.equal(s.graph.nodes.find(n=>n.id==='level').outputs[0].type,'number');
 assert.equal(s.graph.nodes.find(n=>n.id==='text').outputs[0].type,'text');
 assert.equal(s.graph.nodes.find(n=>n.id==='filter').inputs.find(p=>p.id==='filter-items').list,true);
 assert.equal(await page.locator('[data-port-key="filter:out:filter-event"] svg path').count(),1);
 assert.equal(await page.locator('[data-graph-node="level"]').count(),1);
});
test('fast Settings-to-Canvas refresh cancels the old System read and restores the admitted user graph',async()=>{
 let release,entered;const started=new Promise(r=>{entered=r;});let hold=false;
 const s=await navigation({delayCanvas:async id=>{if(hold&&id==='root'){hold=false;entered();await new Promise(r=>{release=r;});}}});
 await s.api.selectGraph('user');hold=true;
 const system=s.api.selectGraph('root');await started;
 const canvas=s.api.refreshProjects({userCanvas:true});release();await Promise.all([system,canvas]);
 assert.equal(s.api.getSnapshot().graph.id,'user');
});

const card = (page,id) => page.locator('[data-graph-node="'+id+'"]');
async function selectedIds(page){return page.locator('[data-graph-node]').evaluateAll(els=>els.filter(el=>window.getComputedStyle(el.querySelector('[data-ds-node]')).outlineStyle==='solid').map(el=>el.dataset.graphNode).sort());}
async function beginDrag(page,a,b,modifier=null){
 // CDP targets only this isolated headless page, never the desktop pointer.
 const cdp=await page.context().newCDPSession(page),modifiers=modifier==='Shift'?8:modifier==='Control'?2:0;
 await cdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:a.x,y:a.y,modifiers});
 await cdp.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x:a.x,y:a.y,modifiers});
 for(let i=1;i<=8;i++)await cdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',button:'left',buttons:1,x:a.x+(b.x-a.x)*i/8,y:a.y+(b.y-a.y)*i/8,modifiers});
 return async()=>{await cdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x:b.x,y:b.y,modifiers});await cdp.detach();};
}
async function boxSelect(page,ids,modifier=null){
 const boxes=await Promise.all(ids.map(id=>card(page,id).boundingBox()));
 const a={x:Math.min(...boxes.map(b=>b.x))-6,y:Math.min(...boxes.map(b=>b.y))-6},
  b={x:Math.max(...boxes.map(b=>b.x+b.width))+6,y:Math.max(...boxes.map(b=>b.y+b.height))+6};
 const target=await page.evaluate(a=>document.elementFromPoint(a.x,a.y)?.outerHTML.slice(0,300),a);
 const release=await beginDrag(page,a,b,modifier);
 assert.equal(await page.locator('.react-flow__selection').count(),1,'empty-canvas drag draws its rectangle '+JSON.stringify({ids,modifier,a,b,target}));
 await release();
}
test('plain box selection, Shift-click add, Escape and empty click give visible selection',async t=>{
 const page=await mount(t);
 await boxSelect(page,['level','filter']);assert.deepEqual(await selectedIds(page),['filter','level']);
 await card(page,'text').locator('.node-header').click({modifiers:['Shift']});assert.deepEqual(await selectedIds(page),['filter','level','text']);
 await page.locator('.node-canvas').press('Escape');assert.deepEqual(await selectedIds(page),[]);
 await card(page,'level').locator('.node-header').click();assert.deepEqual(await selectedIds(page),['level']);
 const r=await page.locator('.node-canvas').boundingBox();await page.locator('.node-canvas').click({position:{x:8,y:r.height-8}});
 assert.deepEqual(await selectedIds(page),[]);
});
test('node body drag and selected group drag persist through the real move adapter without snapping back',async t=>{
 const page=await mount(t),before=await card(page,'level').boundingBox();
 await page.evaluate(()=>{window.holdMove=true;});
 const drag=async(id,dx,dy)=>{const b=await card(page,id).locator('.node-header').first().boundingBox(),release=await beginDrag(page,{x:b.x+30,y:b.y+8},{x:b.x+30+dx,y:b.y+8+dy});await release();};
 await drag('level',35,90);await page.waitForFunction(()=>window.releaseMove);
 let after=await card(page,'level').boundingBox();assert.ok(Math.abs(after.x-before.x-35)<2&&Math.abs(after.y-before.y-90)<2,'local movement stays visible while its save is pending');
 await page.evaluate(()=>{window.holdMove=false;window.releaseMove();});await page.waitForTimeout(80);
 after=await card(page,'level').boundingBox();assert.ok(Math.abs(after.y-before.y-90)<2,'confirmed move stays where it was dropped');
 await card(page,'text').locator('.node-header').click({modifiers:['Shift']});
 const start=await Promise.all(['level','text'].map(id=>card(page,id).boundingBox()));await drag('level',-20,45);await page.waitForTimeout(80);
 const end=await Promise.all(['level','text'].map(id=>card(page,id).boundingBox()));
 for(let i=0;i<2;i++)assert.ok(Math.abs(end[i].x-start[i].x+20)<2&&Math.abs(end[i].y-start[i].y-45)<2,'all selected nodes move together '+JSON.stringify({start,end,ids:await selectedIds(page),calls:await page.evaluate(()=>window.fixtureCalls)}));
 const saved=await page.evaluate(()=>({raw:window.fixtureRaw,calls:window.fixtureCalls.filter(c=>c.action==='move')}));
 assert.equal(saved.calls.length,2);assert.deepEqual(Object.keys(saved.calls[1].body.positions).sort(),['level','text']);
 for(const id of ['level','text'])assert.deepEqual(saved.calls[1].body.positions[id],{x:saved.raw.nodes.find(n=>n.id===id).x,y:saved.raw.nodes.find(n=>n.id===id).y});
 await page.evaluate(()=>window.fixturePublish({graph:{...window.fixtureState().graph}}));
 assert.ok(Math.abs((await card(page,'level').boundingBox()).y-end[0].y)<2,'refresh retains saved positions');
});
test('no selected user graph leaves an empty canvas even when System contains child compositions',async t=>{
 const raw=fixture();raw.scope.current='root';const page=await mount(t,{raw});
 assert.equal(await page.locator('[data-graph-node]').count(),0);
});
test('non-interface parameters remain editable widgets without fabricated socket IDs',async t=>{
 const page=await mount(t),node=card(page,'filter');
 assert.equal(await node.locator('[data-port-key]').count(),4);
 await page.getByRole('spinbutton',{name:'Filter threshold',exact:true}).fill('7');
 assert.equal(await page.getByRole('spinbutton',{name:'Filter threshold',exact:true}).inputValue(),'7');
 assert.deepEqual((await page.evaluate(()=>window.fixtureCalls)).filter(c=>c.action==='parameter'),[{action:'parameter',id:'filter',key:'threshold',value:7}]);
 assert.equal(await node.locator('[data-port-key="filter:in:threshold"]').count(),0);
});
test('Settings hosts the grouped system graph in the actual shell',async t=>{
 const page=await mount(t,{shell:true});await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByRole('button',{name:'System graph',exact:true}).click({timeout:1500});
 assert.equal(await page.locator('[data-system-group]').count(),3);
 assert.equal(await page.locator('.node-canvas:visible').count(),0);
 assert.equal(await page.locator('.node-canvas').count(),1,'the previously opened Canvas remains mounted and hidden');
 await page.getByRole('button',{name:'Open graph',exact:true}).click();
 assert.equal(await page.locator('[data-screen="settings/System graph"]').count(),1,'legacy system door still belongs to Settings');
 if(process.env.CANVASOLD_EVIDENCE)await page.screenshot({path:path.join(process.env.CANVASOLD_EVIDENCE,'SETTINGS.png')});
});
test('System graph exposes a refused read and retries the same owner',async t=>{
 const raw=fixture();raw.fixtureSystemFailures=1;const page=await mount(t,{raw,system:true});
 assert.match(await page.getByRole('alert').textContent(),/System graph read refused/);
 await page.getByRole('button',{name:'Retry loading system graph'}).click();
 assert.equal(await page.locator('[data-system-group]').count(),3);
 assert.equal((await page.evaluate(()=>window.fixtureCalls)).filter(c=>c.action==='selectGraph'&&c.id==='root').length,2);
});


test('CARDPOLISH bounds human rows while retaining internal parameters and every socket',async t=>{
 const raw=fixture(),n=raw.nodes[0],hash='a'.repeat(64);
 n.properties=[{...prop('engine','library.think','text'),editable:false},{...prop('template_instance',hash,'text'),editable:false},
  {...prop('responsibility',JSON.stringify({owner:'assembly-instance:'+hash}),'text'),editable:false},
  {...prop('room_width',3,'number','m'),display_label:'Room width'},
  prop('description','A complete long description '.repeat(8),'text'),
  prop('enabled',true,'boolean'),prop('extra_value',4),{...prop('last_result',{raw:'private result'}),editable:false}];
 n.status='blocked by assembly-instance:'+hash;
 const page=await mount(t,{raw}),card=page.locator('[data-graph-node="level"]');
 assert.equal(await card.locator('[data-parameter="template_instance"]').count(),0,'internal instance hash must stay off the face');
 assert.equal(await card.locator('[data-parameter="engine"]').count(),0);
 assert.equal(await card.locator('[data-parameter="responsibility"]').count(),0,'serialized JSON stays in Properties');
 assert.equal(await card.locator('[data-parameter="last_result"]').count(),0);
 assert.equal(await card.locator('[data-parameter]').count(),4,'spec section 0b: the default card shows every human row');
 assert.match(await card.innerText(),/Room width/);
 assert.equal(await card.getByRole('button',{name:'Compact',exact:true}).count(),1,'compact is an opt-in toggle');
 assert.doesNotMatch(await card.innerText(),/[a-f0-9]{64}|assembly-instance:|\{"/);
 const description=card.locator('[data-parameter="description"]');
 assert.equal(await description.locator('[title]').last().getAttribute('title'),n.properties.find(p=>p.label==='description').value);
 assert.equal(await description.locator('[data-row-value]').evaluate(el=>window.getComputedStyle(el).textOverflow),'ellipsis');
 assert.equal(await card.locator('[data-port-key]').count(),1);
 const stored=await page.evaluate(()=>window.fixtureState().graph.nodes.find(n=>n.id==='level'));
 assert.equal(stored.params.template_instance,hash);
 assert.equal(stored.params.responsibility,n.properties.find(p=>p.label==='responsibility').value);
 assert.equal(await card.locator('[data-parameter="template_instance"]').count(),0);
 await card.getByRole('spinbutton',{name:'Level extra_value',exact:true}).fill('9');
 await card.getByRole('button',{name:'Compact',exact:true}).click();
 assert.equal(await card.locator('[data-parameter]').count(),3);
 assert.equal(await card.getByRole('button',{name:'+1 more',exact:true}).count(),1);
 await card.getByRole('spinbutton',{name:'Level room_width',exact:true}).fill('8');
 assert.ok((await page.evaluate(()=>window.fixtureCalls)).some(c=>c.action==='parameter'&&c.key==='room_width'&&c.value===8));
});


test('CARDPOLISH declared editable text remains reachable regardless of key or value shape',async t=>{
 const raw=fixture(),n=raw.nodes[0];
 n.properties=[prop('value',3),prop('caption','[TBD]','text'),prop('note','{draft}','text'),
  prop('root_id','workspace-root','text'),prop('level_ref','Level 3','text'),
  prop('source_hash','a'.repeat(64),'text'),prop('metadata','{"draft":true}','text')];
 const page=await mount(t,{raw}),card=page.locator('[data-graph-node="level"]');
 assert.equal(await card.getByRole('textbox',{name:'Level caption',exact:true}).inputValue(),'[TBD]');
 assert.equal(await card.getByRole('textbox',{name:'Level note',exact:true}).inputValue(),'{draft}');
 for(const key of ['caption','note','root_id','level_ref','source_hash','metadata']){
  await card.getByRole('textbox',{name:'Level '+key,exact:true}).fill('edited-'+key);
  assert.ok((await page.evaluate(()=>window.fixtureCalls)).some(c=>c.action==='parameter'&&c.key===key&&c.value==='edited-'+key));
 }
 await card.getByRole('button',{name:'Compact',exact:true}).click();
 assert.equal(await card.locator('[data-parameter]').count(),3);
 await card.getByRole('button',{name:'+4 more',exact:true}).click();
 assert.equal(await card.getByRole('textbox',{name:'Level root_id',exact:true}).inputValue(),'edited-root_id');
});
