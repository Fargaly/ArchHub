'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {transformSync} = require('esbuild');
const {chromium} = require('playwright');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const read = name => process.env.CANVASLOOK_BASELINE === '1'
  ? require('node:child_process').execFileSync('git',['show','HEAD:01.APP/nodelang/studio/'+name],{cwd:path.resolve(studio,'../../..'),encoding:'utf8'})
  : fs.readFileSync(path.join(studio,name),'utf8');
const node = (id, i, parent = null) => ({id, title:['Level','Doors of level','Untagged only','Tag doors'][i % 4], kind:['Input','Host','Filter','Document'][i % 4],
  x:0, y:0, parent, children:[], status:i % 4 === 3 ? 'Waiting for approval' : 'Done', params:{Level:'L3'}, defaults:{},
  inputs:[{id:'in',name:'level',type:'text'}],outputs:[{id:'out',name:'doors',type:'elements',list:true}]});
const fixture = () => {
  const nodes = Array.from({length:12},(_,i)=>node('n'+i,i,'g'+Math.floor(i/4)));
  const groups = Array.from({length:3},(_,i)=>({id:'g'+i,title:['Revit','CAD Lines','Studio'][i],kind:'Group',x:0,y:0,status:'Idle',params:{},defaults:{},inputs:[],outputs:[],children:nodes.filter(n=>n.parent==='g'+i).map(n=>n.id)}));
  return {id:'fixture',name:'Canvas look fixture',nodes:[...groups,...nodes],wires:nodes.filter((_,i)=>i%4!==3).map((n,i)=>({id:'w'+i,from:n.id,to:'n'+(Number(n.id.slice(1))+1),fromPort:'out',toPort:'in',type:'elements'}))};
};
const overlaps = (a,b) => a.x < b.x+b.width && b.x < a.x+a.width && a.y < b.y+b.height && b.y < a.y+a.height;

async function mount(t, graph = fixture()) {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  t.after(()=>browser.close());
  const page = await browser.newPage({viewport:{width:1496,height:960}}), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>r.fulfill({contentType:'text/html',body:'<div id="root" style="display:grid;height:100vh"></div>'}));
  await page.goto('http://canvaslook.test/');
  await page.addStyleTag({content:read('style.css')+'html,body{margin:0;height:100%}'});
  for(const name of ['vendor/react.js','vendor/react-dom.js','tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx'])
    await page.addScriptTag({content:name.endsWith('.jsx')?transformSync(read(name),{loader:'jsx'}).code:read(name)});
  await page.evaluate(graph=>{
    const R=window.React,h=R.createElement;
    let state={revision:1,graph,settings:[],workspaces:[],catalogue:[{id:'level',name:'Level',description:'A level value',family:'Get',output:'text',descriptor:{engine:'Input'}},
      {id:'host',name:'Doors of level',description:'Read doors from Revit',family:'Host',output:'elements',descriptor:{engine:'Host'}},
      {id:'filter',name:'Untagged only',description:'Keep rows where a rule is true',family:'Change',output:'elements',descriptor:{engine:'Filter'}},
      {id:'document',name:'Tag doors',description:'Write tags to the document',family:'Send',output:'elements',descriptor:{engine:'Document'}}],templates:[],runs:[],mods:[]};
    const listeners=new Set();
    window.fixtureCalls=[];
    const publish=()=>{state={...state,revision:state.revision+1};listeners.forEach(f=>f());};
    window.fixtureState=()=>state;
    const api={refreshProjects:async()=>{},getSnapshot:()=>state,getNodeParameters:()=>[],setSetting:async()=>{},
      addNode:async(id,position)=>{window.fixtureCalls.push({action:'add',id,position});const n={...state.graph.nodes.find(n=>!n.children.length),id:'added',title:'Level',parent:null,children:[],...position};state.graph={...state.graph,nodes:[...state.graph.nodes,n]};publish();return n;},
      moveNodes:async positions=>{window.fixtureCalls.push({action:'move',positions});state.graph={...state.graph,nodes:state.graph.nodes.map(n=>({...n,...positions[n.id]}))};publish();}};
    window.UI={...window.UI,A:window.AH,D:window.AH_DS,api,Chip:({children})=>h('span',null,children),Empty:({children})=>h('p',null,children),
      useData:()=>R.useSyncExternalStore(f=>{listeners.add(f);return()=>listeners.delete(f);},()=>state),useApp:()=>window.fixtureApp,
      GraphProperties:()=>null,NodeRunPolicy:()=>null,MixedProperties:()=>null,CompositeParameters:()=>null};
    window.mountFixture=()=>{
      function App(){const [libraryOpen,setLibraryOpen]=R.useState(false),[selectedNodeId,setSelectedNodeId]=R.useState(null);
        window.fixtureApp={libraryOpen,setLibraryOpen,selectedNodeId,setSelectedNodeId,act:f=>Promise.resolve(f()),show(){},go(){}};
        return h(window.UI.Canvas);}
      window.ReactDOM.createRoot(document.getElementById('root')).render(h(App));
    };
  },graph);
  for(const name of ['ds_library.jsx','ds_screens.jsx'])await page.addScriptTag({content:transformSync(read(name),{loader:'jsx'}).code});
  await page.evaluate(()=>window.mountFixture());
  await page.locator('[data-graph-node]').first().waitFor({timeout:5000});
  await page.waitForTimeout(120);
  t.after(()=>assert.deepEqual(errors,[],'no browser errors'));
  return page;
}
async function checkCards(page,count) {
  const boxes=await page.locator('[data-graph-node]').evaluateAll(els=>els.map(el=>({id:el.dataset.graphNode,...el.getBoundingClientRect().toJSON()})));
  assert.equal(boxes.length,count);
  for(let i=0;i<boxes.length;i++)for(let j=0;j<i;j++)assert.ok(!overlaps(boxes[i],boxes[j]),boxes[i].id+' overlaps '+boxes[j].id);
  const area=await page.locator('.node-canvas').boundingBox();
  for(const b of boxes)assert.ok(b.x>=area.x && b.y>=area.y && b.x+b.width<=area.x+area.width && b.y+b.height<=area.y+area.height,b.id+' fitted on open');
}
test('12 nodes in 3 groups open without overlaps, fitted at each scope; groups show members',async t=>{
  const page=await mount(t);
  await checkCards(page,3);
  assert.equal(await page.locator('[data-stacked-edge]').count(),6);
  assert.equal(await page.locator('[data-group-member]').count(),12);
  for(const id of ['g0','g1','g2']){
    await page.locator('[data-graph-node="'+id+'"] .node-header').dblclick();
    await page.waitForTimeout(100);await checkCards(page,4);
    assert.equal(await page.getByText('Group · 0 nodes',{exact:false}).count(),0,'empty children arrays are ordinary nodes');
    await page.getByRole('button',{name:'← Parent',exact:true}).click();await page.waitForTimeout(100);
  }
  assert.deepEqual(await page.evaluate(()=>window.fixtureCalls),[],'open/layout never writes positions');
  if(process.env.CANVASLOOK_EVIDENCE)await page.screenshot({path:path.join(process.env.CANVASLOOK_EVIDENCE,'AFTER.png')});
});
test('Library is present on open and a real drag adds the selected definition at its drop point',async t=>{
  const page=await mount(t);
  assert.equal(await page.getByRole('complementary',{name:'Library shelf'}).count(),1,'library opens beside canvas');
  assert.equal(await page.getByRole('button',{name:'Add Doors of level',exact:true}).count(),1,'catalogue categories outside the five families remain available');
  const expected=await page.locator('.node-canvas').evaluate(el=>{const world=el.querySelector(':scope > div[style*="scale"]'), m=new window.DOMMatrix(window.getComputedStyle(world).transform);return {x:(550-m.e)/m.a,y:(500-m.f)/m.d};});
  await page.getByRole('button',{name:'Add Level',exact:true}).dragTo(page.locator('.node-canvas'),{targetPosition:{x:550,y:500}});
  await page.waitForTimeout(100);
  const calls=await page.evaluate(()=>window.fixtureCalls);
  assert.equal(calls.length,1);assert.equal(calls[0].action,'add');assert.equal(calls[0].id,'level');
  assert.ok(Math.abs(calls[0].position.x-expected.x)<.001 && Math.abs(calls[0].position.y-expected.y)<.001,'drop translates the actual screen point through pan and zoom');
  assert.equal(await page.locator('[data-graph-node="added"]').count(),1);
  assert.equal(await page.getByRole('complementary',{name:'Library shelf'}).count(),1,'library stays available after a drop');
});
test('flat overlapping ordinary nodes retain the approved 224px anatomy and 2px clipped wires',async t=>{
  const graph=fixture();graph.nodes=graph.nodes.filter(n=>!n.children.length).map(n=>({...n,parent:null}));
  const page=await mount(t,graph);await checkCards(page,12);
  const card=page.locator('[data-ds-node]').first();
  assert.equal(await card.evaluate(el=>el.style.width),'224px');
  assert.equal(await card.evaluate(el=>window.getComputedStyle(el).borderRadius),'6px');
  assert.equal(await page.locator('[data-stacked-edge]').count(),0);
  assert.equal(await page.locator('.node-properties').count(),0,'rejected node properties panel absent');
  assert.ok(await page.locator('svg [clip-path]').count()>0,'wires clip away from cards');
  if(process.env.CANVASLOOK_EVIDENCE)await page.screenshot({path:path.join(process.env.CANVASLOOK_EVIDENCE,'AFTER-FLAT.png')});
});
test('saving a drag keeps untouched cards at their repaired display positions',async t=>{
  const page=await mount(t), positions=()=>page.locator('[data-graph-node]').evaluateAll(els=>Object.fromEntries(els.map(el=>[el.dataset.graphNode,{x:el.style.left,y:el.style.top}])));
  const before=await positions();
  await page.locator('[data-graph-node="g0"] .node-header').evaluate(el=>{
    // Synthetic fixture pointers have no browser capture; this court checks the save/readback, not capture.
    el.setPointerCapture=()=>{};
    const r=el.getBoundingClientRect(), emit=(target,type,x,y)=>target.dispatchEvent(new window.PointerEvent(type,{bubbles:true,cancelable:true,button:0,pointerId:1,clientX:x,clientY:y}));
    emit(el,'pointerdown',r.left+25,r.top+20);
    emit(el,'pointermove',r.left+625,r.top+520);
    emit(el,'pointerup',r.left+625,r.top+520);
  });
  await page.waitForTimeout(80);const after=await positions();
  assert.notDeepEqual(after.g0,before.g0);
  assert.deepEqual(after.g1,before.g1);assert.deepEqual(after.g2,before.g2);
  assert.equal((await page.evaluate(()=>window.fixtureCalls)).filter(c=>c.action==='move').length,1);
});


test('STUDIOFIX distinct saved coordinates stay authoritative even when intentionally overlapping',async t=>{
 const graph=fixture();graph.nodes=graph.nodes.filter(n=>!n.children.length).slice(0,2).map((n,i)=>({...n,parent:null,x:20+i*80,y:40+i*10}));graph.wires=[];
 const page=await mount(t,graph);
 const positions=await page.locator('[data-graph-node]').evaluateAll(els=>els.map(el=>[el.style.left,el.style.top]));
 assert.deepEqual(positions,[['20px','40px'],['100px','50px']]);
 assert.deepEqual(await page.evaluate(()=>window.fixtureCalls),[]);
});
