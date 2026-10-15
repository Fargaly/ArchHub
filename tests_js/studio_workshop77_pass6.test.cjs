const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {fixture}=require('./workshop72_fixture.cjs');
const {mounted,text,read}=require('./workshop72_regression_helpers.cjs');
const {mountWorkshopNode,slice}=require('./workshop72_node_helpers.cjs');
const {plateFixture}=require('./workshop77_plate_fixture.cjs');
const {renderModels}=require('./workshop77_render_models.cjs');
function accents(doc){const probe=doc.createElement('i');probe.style.color=doc.defaultView.AH.accent;return [...doc.querySelectorAll('button:not([data-socket-port])')].filter(el=>el.style.backgroundColor===probe.style.color||(el.style.background.includes('linear-gradient')&&(el.style.background.includes(probe.style.color)||el.style.background.includes(doc.defaultView.AH.accent))));}
function labelledIcons(doc){
  const icons=[...doc.querySelectorAll('button')].filter(el=>!/[a-z0-9]/i.test(text(el)));
  for(const el of icons){assert.ok(el.getAttribute('aria-label')?.trim(),el.outerHTML);assert.ok(el.title.trim(),el.outerHTML);}
  return icons;
}
for(const pending of [false,true])test(`PASS6 window accent follows composer text and pending=${pending}`,async()=>{
  const f=fixture();if(!pending){f.state.nativeWork=null;f.state.workshop.workflows=[];}
  const ui=await mounted(f.state,f.authority);
  try{
    const send=()=>ui.button('Send'),create=()=>ui.button('New task');
    assert.equal(create().style.backgroundColor,'rgb(38, 38, 45)');
    assert.equal(send().style.backgroundColor,'rgb(38, 38, 45)');
    assert.equal(accents(ui.doc).length,pending?1:0);
    if(pending)assert.equal(text(accents(ui.doc)[0]),'Approve');
    await ui.input('Inspect these labels');
    assert.equal(accents(ui.doc).length,1);
    assert.equal(text(accents(ui.doc)[0]),pending?'Approve':'Send');
    labelledIcons(ui.doc);
    await ui.input('   ');assert.equal(accents(ui.doc).length,pending?1:0);
    await ui.click(create());assert.ok(ui.doc.querySelector('[data-workshop-empty]'));assert.ok(accents(ui.doc).length<=1);
  }finally{await ui.close();}
});
test('PASS6 tiled approvals share one accent and preserve secondary decision controls',async()=>{
  const f=plateFixture();f.state.workshopPresentation.layout=4;
  f.state.workshop.workflows.push({...f.state.workshop.workflows[0],root:'work:mail0001',title:'Second proposal',approval:{current:false}});
  const base=fixture(),ui=await mounted(f.state,base.authority);
  try{assert.ok(ui.doc.querySelectorAll('[data-workshop-approval-card]').length>=2);assert.ok(accents(ui.doc).length<=1);labelledIcons(ui.doc);}
  finally{await ui.close();}
});
test('PASS6 canvas Review owns the accent; labelled zoom and history retain their actions',async()=>{
  const f=fixture(),ui=await mountWorkshopNode({state:f.state,node:f.node});
  const React=require('react'),{createRoot}=require('react-dom/client'),{transformSync}=require('esbuild');
  const holder=ui.doc.createElement('div');ui.doc.body.append(holder);const root=createRoot(holder);
  try{
    const source=read('nodelang/studio/studio-lm.jsx');
    Object.assign(ui.context,{smallBtn:()=>({}),canvasCardSurface:()=>({}),studioCategory:()=>({col:'#fff'})});
    vm.runInContext(transformSync(slice(source,'const CanvasToolbar =','const FloatingComposer =')+slice(source,'const minimapViewBox =','const useLibraryRefreshEpoch =')+'\nglobalThis.P6Toolbar=CanvasToolbar;globalThis.P6Map=MiniMap;globalThis.P6Face=GraphWorkshopFace;', {loader:'jsx'}).code,ui.context);
    let zoom=1,fits=0,runs=0,undos=0,redos=0;
    const paint=waiting=>ui.act(()=>root.render(React.createElement(React.Fragment,null,
      React.createElement(ui.context.P6Toolbar,{zoom,setZoom:fn=>zoom=fn(zoom),waiting,onFit:()=>fits++,fitLabel:'Fit all nodes',onArrange:()=>{},setLibraryOpen:()=>{},onRun:()=>runs++,runDisabled:false,
        undo:{run:()=>undos++,disabled:false},redo:{run:()=>redos++,disabled:false}}),
      React.createElement(ui.context.P6Map,{pan:{x:0,y:0},zoom,positions:{},allNodes:[]}))));
    await paint(1);assert.equal(accents(ui.doc).length,1);assert.equal(text(accents(ui.doc)[0]),'Review');
    assert.equal(holder.querySelector('[data-canvas-run-primary]').style.backgroundColor,'rgb(38, 38, 45)');
    const buttons=[...holder.querySelectorAll('button')];
    assert.deepEqual(buttons.filter(b=>['Zoom out','Zoom in','Fit'].includes(text(b))).map(text),['Zoom out','Zoom in','Fit']);
    assert.equal(text(holder.querySelector('[data-canvas-zoom]')),'100%');assert.match(text(holder.querySelector('[data-canvas-minimap]')),/Overview/);
    const byLabel=label=>holder.querySelector(`[aria-label="${label}"]`);
    await ui.click(byLabel('Zoom out'));assert.equal(zoom,.9);await ui.click(byLabel('Zoom in'));assert.equal(zoom,1);
    await ui.click(byLabel('Fit all nodes'));assert.equal(fits,1);
    for(const label of ['Undo','Redo']){assert.equal(byLabel(label).title,label);await ui.click(byLabel(label));}
    assert.equal(undos,1);assert.equal(redos,1);assert.equal(labelledIcons(holder).length,2);assert.ok(labelledIcons(ui.doc).length>=4);
    await ui.click(holder.querySelector('[data-canvas-run-primary]'));assert.equal(runs,1);
    // A second waiting Workshop keeps its route, but only the first owns the accent.
    const second={...f.node,id:'room-b',conversation_root:f.node.id};f.state.topology.graph.nodes.push(second);f.state.workshops.push({root:'room-b',label:'Second room'});
    await ui.act(()=>root.render(React.createElement(ui.context.P6Face,{n:second})));assert.equal(accents(ui.doc).length,1);
    assert.equal(holder.querySelector('[data-workshop-node-review]').style.backgroundColor,'rgb(38, 38, 45)');
    Object.assign(ui.context,{ASK_SCALE:{node:{field:13,send:{padding:'0 8px',radius:6,size:13}}},modelRoute:()=>null,nodeModelRoute:()=>null});
    vm.runInContext(transformSync(slice(source,'const InlineAsk =','const useLastRunEpoch =')+'\nglobalThis.P6InlineAsk=InlineAsk;', {loader:'jsx'}).code,ui.context);
    await ui.act(()=>root.render(React.createElement(ui.context.P6InlineAsk,{scale:'node'})));
    assert.equal(holder.querySelector('button').style.backgroundColor,'rgb(38, 38, 45)');assert.equal(accents(ui.doc).length,1);
    assert.match(source,/title=\{expanded \? 'Collapse' : 'Expand & search'\} aria-label=\{expanded \? 'Collapse' : 'Expand & search'\}/);
    assert.match(source,/title="Clear conversation search" aria-label="Clear conversation search"/);
    f.state.nativeWork=null;f.state.workshop.workflows=[];await ui.draw({state:f.state});await paint(0);
    assert.equal(accents(ui.doc).length,1);assert.match(text(accents(ui.doc)[0]),/Run/);
  }finally{await ui.act(()=>root.unmount());holder.remove();await ui.close();}
});
test('PASS6 render fixture reads free entries through the real catalogue; synthetic court ids stay intact',()=>{
  const models=Array.from({length:3},(_,i)=>({route:`provider/model-${i}:free`,name:`Catalogue entry ${i}`,cost:'free'}));let called=false;
  const rows=renderModels((exe,args,options)=>{called=true;assert.match(args[1],/from nodelang.model_catalogue import openrouter_models/);assert.match(args[1],/opener=urllib.request.urlopen/);assert.equal(options.cwd, require('node:path').resolve(__dirname, '..'));return {status:0,stdout:JSON.stringify(models)};});
  assert.ok(called);const f=plateFixture({models:rows});
  assert.deepEqual(f.state.workshop.participants.filter(a=>a.is_agent).map(a=>a.model),models.map(a=>a.route));
  assert.deepEqual(f.state.workshopPresentation.models.groups[0].items.map(a=>a.name),models.map(a=>a.name));
  assert.equal(plateFixture().state.workshop.participants[1].model,'registry-a');
  assert.throws(()=>renderModels(()=>({status:1})),/catalogue unavailable/);
  assert.throws(()=>renderModels(()=>({status:0,stdout:'[]'})),/three free/);
});
