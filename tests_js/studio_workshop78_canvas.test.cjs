const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('./studio_ds_context.cjs');
const {mountWorkshopNode, read, slice} = require('./workshop72_node_helpers.cjs');

function fixture() {
  const node = {id:'room-authority',cat:'workshop',title:'Inspect selected elements',x:30,y:40,
    members:[{id:'agent-authority',title:'Assigned agent'}],
    ins:[{id:'items-in',label:'items',t:'object',list:true,connectable:true}],
    outs:[{id:'result-out',label:'results',t:'object',list:true,connectable:true}]};
  const authorization = {subject:'person-authority',session:'view-authority'};
  const state = {canvas:{graph_id:'graph-authority',root:'scope-authority',authorization},
    workshops:[{root:node.id,label:node.title}],models:{items:[{id:'registry-model',name:'Registry supplied model'}]},
    workshop:{root:node.id,ok:true,self:'person-authority',participants:[
      {root:'agent-authority',label:'Assigned agent',runtime:'codex',is_agent:true,model:'registry-model',state:'working'}],
      assignments:[{work:'work-authority',agent_session:'agent-authority'}],messages:[],workflows:[
        {root:'flow-authority',title:'Inspection plan',approval:{current:true},nodes:[
          {root:'step-authority',title:'Read selected objects',state:'done',result:'Read receipt'}]}]},
    topology:{graph:{nodes:[node,{id:'agent-authority',cat:'ai',title:'Agent',group:node.id,live:true,
      x:400,y:40,params:[],state:'working',ins:[{id:'task-in',label:'task',t:'object',connectable:true}],
      outs:[{id:'agent-result-out',label:'result',t:'object',connectable:true}]},
      {id:'work-authority',engine:'work',title:node.title}],wires:[]},
      canvas:{application_root:'graph-authority',scope:{current:'scope-authority'},authorization}}};
  return {node,state};
}

test('DSYS-078 mounts a surf + e2 skin and preview slot on every graph card category', async () => {
  const fx = fixture(), ui = await mountWorkshopNode(fx);
  try {
    for (const cat of ['read','logic','filter','watch','output','host','ai']) {
      const node = {id:'real-' + cat,cat,title:'Graph supplied title',x:10,y:20,params:[],ins:[],outs:[],state:'working'};
      await ui.draw({node});
      const card = ui.doc.querySelector('.lm-node');
      assert.equal(card.dataset.canvasCardSkin,'078');
      assert.match(card.style.background,/linear-gradient/);
      assert.equal(card.style.boxShadow,ui.win.AH.elev.e2);
      assert.equal(ui.doc.querySelectorAll('[data-node-preview-slot]').length,1);
      assert.equal(ui.doc.querySelector('[data-category-tile]').style.width,'30px');
      assert.equal(ui.doc.querySelector('[data-node-card-title]').style.fontSize,'14px');
      assert.equal(ui.doc.querySelector('[data-node-card-title]').style.fontWeight,'700');
      assert.equal(ui.doc.querySelector('[data-node-card-subtitle]').style.fontSize,'12px');
      assert.equal(ui.doc.querySelector('[data-node-footer-status]').textContent,'working');
    }
  } finally {await ui.close();}
});

test('DSYS-078 warning glow follows needs-user state and disappears after the real approval is resolved', async () => {
  const fx = fixture();
  fx.state.nativeWork = {root:fx.node.id,scope:'scope-authority',owner:'person-authority',view:'view-authority',
    work:'work-authority',state:'awaiting_approval',approved:false,result_count:4,output_label:'results',input_digest:'a'.repeat(64)};
  const ui = await mountWorkshopNode(fx);
  try {
    const face = () => ui.doc.querySelector('[data-workshop-node-face]');
    assert.equal(face().dataset.workshopNodeState,'needs-user');
    assert.equal(face().style.borderColor,'rgb(229, 178, 90)','plate 073 uses a warning hairline');
    assert.equal(ui.doc.querySelector('[data-workshop-node-status]').textContent,'Waits for you · 4 results');
    fx.state.nativeWork = {...fx.state.nativeWork,state:'complete',approved:true};
    await ui.draw({state:fx.state});
    assert.equal(face().style.borderColor,'rgb(38, 38, 46)','resolved face returns to the standard hairline');
    assert.equal(ui.doc.querySelector('[data-workshop-node-review]'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-node-status]').textContent,'complete');
  } finally {await ui.close();}
});

test('DSYS-073 compact Workshop keeps plan in the shared model and real ports remain 11px typed graph interfaces', async () => {
  const fx=fixture(),ui = await mountWorkshopNode(fx);
  try {
    assert.equal(ui.model().steps[0].title,'Read selected objects');
    assert.equal(ui.doc.querySelectorAll('[data-node-preview-slot]').length,0,'073 replaces the expanded preview DOM');
    const ports = [...ui.doc.querySelectorAll('[data-socket-port]')];
    assert.deepEqual(ports.map(port => [port.dataset.socketPort,port.dataset.socketShape,port.style.width]),
      [['items-in','diamond','11px'],['result-out','diamond','11px']]);
    await ui.click(ports[1]);
    assert.equal(ui.calls[0][1].id,'result-out');
  } finally {await ui.close();}
});

test('DSYS-076 agent node keeps graph identity, real task/result ports, live state and registry model label', async () => {
  const fx = fixture(), ui = await mountWorkshopNode({...fx,node:fx.state.topology.graph.nodes[1]});
  try {
    assert.equal(ui.doc.querySelector('[data-agent-node]').dataset.agentNode,'agent-authority');
    assert.equal(ui.doc.querySelector('[data-node-card-title]').textContent,'Assigned agent');
    assert.equal(ui.doc.querySelector('[data-node-card-subtitle]').textContent,'Registry supplied model');
    assert.deepEqual([...ui.doc.querySelectorAll('[data-socket-label]')].map(port => port.dataset.socketLabel),['task','result']);
    assert.equal(ui.doc.querySelector('[data-node-footer-status]').textContent,'Inspect selected elements · working');
    fx.state.models.items[0].name = 'Registry revision model';
    await ui.draw({state:fx.state});
    assert.equal(ui.doc.querySelector('[data-node-card-subtitle]').textContent,'Registry revision model');
    assert.equal(ui.calls.length,0,'mount does not fetch agents or models at startup');
  } finally {await ui.close();}
});

test('DSYS-076 free agent model label refuses a paid registry route', async () => {
  const fx = fixture(), agent = fx.state.topology.graph.nodes[1];
  fx.state.workshop.participants[0].free_only = true;
  const ui = await mountWorkshopNode({...fx,node:agent});
  try {
    assert.equal(ui.win.ARCHHUB_WORKSHOP_AGENT_MODEL(fx.state.workshop.participants[0],fx.state),null,
      'free-only model selection rejects the paid registry entry');
    assert.equal(ui.doc.querySelector('[data-node-card-subtitle]').textContent,'Unavailable');
    assert.doesNotMatch(ui.doc.querySelector('[data-node-card-subtitle]').textContent,/Not available yet/);
    fx.state.models.items[0].free = true;
    await ui.draw({state:fx.state});
    assert.equal(ui.doc.querySelector('[data-node-card-subtitle]').textContent,'Registry supplied model');
  } finally {await ui.close();}
});

test('DSYS-078 fit centres the real graph vertically and does not mutate saved positions', () => {
  const context = vm.createContext({});
  vm.runInContext(slice(read('nodelang/studio/studio-lm.jsx'),'const CANVAS_FIT_TOP =','const canvasRevealBounds =') +
    '\nglobalThis.fit=canvasFitBounds;',context);
  const positions = {one:{x:80,y:420},two:{x:800,y:90}}, sizes = {one:{w:224,h:160},two:{w:300,h:220}};
  const before = JSON.stringify(positions), fit = context.fit(Object.keys(positions),positions,sizes,{width:1200,height:800},1);
  assert.equal(JSON.stringify(positions),before);
  assert.equal(fit.pan.y + (fit.bounds.top+fit.bounds.bottom)*fit.zoom/2,400);
  const canvas = slice(read('nodelang/studio/studio-lm.jsx'),'const NodeCanvas =','const NodeRenderer =');
  assert.match(canvas,/openFitPending = React\.useRef\(workshopCanvas \|\|/);
  assert.match(canvas,/workshopCanvas && !workshopOpenFitCompleted\.current/);
});

test('DSYS-078 doubles only real list wires and keeps their endpoint interfaces', () => {
  const source = slice(read('nodelang/studio/studio-lm.jsx'),'const NodeCanvas =','const NodeRenderer =');
  assert.match(source,/list:!!fromNode\.outs\[fromIdx\]\.list \|\| !!fromNode\.outs\[fromIdx\]\.multiple/);
  assert.match(source,/w\.list && <path data-wire-list-strand/);
  assert.match(source,/const x1 = fromNode\.x \+ sourceWidth, y1 = fromNode\.y \+ portY\(portBands\[fromNode\.id\], fromIdx\)/);
  assert.match(source,/onRun=\{\(\) => menuRun\(\)\}/);
});

test('DSYS-078 scalar event ports are round and list event ports diamond without changing graph type',async()=>{
  const fx=fixture();fx.node.ins=[{id:'event-in',label:'run',t:'trigger',connectable:true}];
  fx.node.outs=[{id:'event-out',label:'events',t:'trigger',list:true,connectable:true}];
  const ui=await mountWorkshopNode(fx);
  try{
    const input=ui.doc.querySelector('[data-socket-port="event-in"]'),output=ui.doc.querySelector('[data-socket-port="event-out"]');
    assert.equal(input.dataset.socketShape,'circle');assert.equal(output.dataset.socketShape,'diamond');
    assert.equal(input.dataset.socketType,'trigger');assert.equal(output.dataset.socketType,'trigger');
    assert.equal(input.style.width,'11px');assert.equal(output.style.width,'11px');
  }finally{await ui.close();}
});

test('DSYS-076 every existing Home/status/social approval decision uses the shared approval component', () => {
  const source = read('nodelang/studio/studio-lm.jsx');
  for (const [start,end] of [['const WaitingButton =','const FRAME_TOOL_DEFAULTS ='],['const SettingsSocialApprovals =','const SettingsConnectedSocialAccounts =']]) {
    const surface = slice(source,start,end);
    assert.match(surface,/React\.createElement\(window\.ARCHHUB_APPROVAL_CARD/);
    assert.doesNotMatch(surface,/>Approve(?: this post)?<|>Deny<|>Decline<|confirmReject/);
  }
});

test('DSYS-078 Settings system canvas mounts the same skin, preview, 30px ring, parameters and live footer', async () => {
  const ui = await mountWorkshopNode(fixture()), React = require('react'), {createRoot} = require('react-dom/client');
  const container = ui.doc.createElement('div');ui.doc.body.appendChild(container);const root = createRoot(container);
  try {
    const source = read('nodelang/studio/studio-lm.jsx'), {transformSync} = require('esbuild');
    vm.runInContext(transformSync(read('nodelang/studio/param-types.jsx'),{loader:'jsx'}).code,ui.context);
    // Keep the real parameter module's local bindings isolated from the canvas source slice,
    // while retaining its actual ApplicationNodeParameters export and readonly row behavior.
    vm.runInContext(transformSync('(function(){\n'+read('nodelang/studio/studio-params.jsx')+'\n})();',{loader:'jsx'}).code,ui.context);
    const helpers = ['settings54NodeTitle','settings54ParamKey','settings54ParamLabel','settings54ParamValue']
      .map(name => source.match(new RegExp('const ' + name + ' = [^\\n]+'))[0]).join('\n');
    vm.runInContext(transformSync(helpers + '\n' + slice(source,'const Settings54Tile =','const Settings54Seg =') +
      slice(source,'const Settings54Socket =','const Settings =') + '\nglobalThis.Settings54Card=Settings54Card;', {loader:'jsx'}).code,ui.context);
    let opened = 0;
    const node = {id:'settings-real',title:'Graph-owned Settings',state:'ready',params:[{k:'density',label:'Density',v:'Compact'}],
      preview:{text:'Real preview receipt'},ins:[],outs:[{id:'settings-value',t:'text',label:'value'}]};
    await ui.act(() => root.render(React.createElement(ui.context.Settings54Card,{node,view:{x:10,y:20,glyph:'S',color:ui.win.AH.accent},
      connected:{in:false,out:true},selected:false,action:() => opened++})));
    const card = container.querySelector('[data-settings54-node-card]');
    assert.equal(card.dataset.canvasCardSkin,'065');assert.equal(card.style.background,ui.win.getComputedStyle(Object.assign(ui.doc.createElement('div'),{style:'background:'+ui.win.AH.bgPanel})).background);
    assert.equal(card.style.boxShadow,'none');
    assert.equal(card.querySelector('[data-node-preview-slot]').textContent,'Real preview receipt');
    assert.equal(card.querySelector('[aria-hidden=true]').style.width,'20px');
    assert.equal(card.querySelector('[data-settings54-footer]').textContent,'ready');
    assert.ok(card.textContent.includes('DensityCompact'));
    await ui.click(card);assert.equal(opened,1);
  } finally {await ui.act(() => root.unmount());await ui.close();}
});

test('DSYS-078 Fit measures mounted cards when the real projection omits optional width', async () => {
  const fx = fixture(), ui = await mountWorkshopNode(fx);
  try {
    const card = ui.doc.querySelector('.lm-node');
    Object.defineProperty(card,'offsetWidth',{configurable:true,value:300});
    Object.defineProperty(card,'offsetHeight',{configurable:true,value:180});
    Object.assign(ui.context,{allNodes:[fx.node],positions:{[fx.node.id]:{x:fx.node.x,y:fx.node.y}},expanded:{},
      wrapRef:{current:ui.container},MAX_LAYOUT_NODES:2048,setLayoutError:message => {throw new Error(message);}});
    vm.runInContext(slice(read('nodelang/studio/studio-lm.jsx'),'const measureCards =','const fitIds =') +
      '\nglobalThis.measure=measureCards;',ui.context);
    const size = ui.context.measure()[fx.node.id];
    assert.equal(size.w,300);assert.equal(size.h,180);assert.equal(Number.isFinite(size.w),true);
  } finally {await ui.close();}
});

test('DSYS-078 actual live parameter rows render human labels and value chips while preserving node focus/open routes', async () => {
  let focused = 0, opened = 0;
  const ui = await mountWorkshopNode({...fixture(),onFocus:() => focused++,onOpen:() => opened++});
  try {
    const source = read('nodelang/studio/studio-lm.jsx'), params = read('nodelang/studio/studio-params.jsx');
    const {transformSync} = require('esbuild');
    ui.context.PM_META = {};
    vm.runInContext(params.match(/const humanParamLabel = [^\n]+/)[0] + '\nwindow.humanParamLabel=humanParamLabel;',ui.context);
    vm.runInContext(transformSync(slice(source,'const visibleNodeParams =','const socketShapeOf =') +
      slice(source,'const LiveBody =','const HostBody =') + '\nglobalThis.NodeBody=LiveBody;', {loader:'jsx'}).code,ui.context);
    for (const editable of [false,true]) {
      const node = {id:'live-parameter-node',cat:'logic',title:'Projected node',live:true,x:10,y:20,ins:[],outs:[],
        params:[{k:'selection_scope',label:'Scope',v:'Current selection',editable},
          {k:'keep_condition',label:'Keep where',v:'Label is empty',editable}]};
      await ui.draw({node});
      const rows = [...ui.doc.querySelectorAll('[data-node-inline-param]')];
      assert.deepEqual(rows.map(row => row.querySelector('[data-node-param-label]').textContent),['Scope','Keep where']);
      assert.deepEqual(rows.map(row => row.querySelector('[data-node-param-value]').textContent),['Current selection','Label is empty']);
      for (const row of rows) {
        const chip = row.querySelector('[data-node-param-value]');
        assert.equal(chip.style.background,ui.win.getComputedStyle(chip).backgroundColor);
        assert.equal(chip.style.borderRadius,'5px');assert.equal(chip.title,chip.textContent);
        assert.equal(row.querySelectorAll('button,input,select,textarea').length,0,'no parameter edit authority is fabricated');
      }
      await ui.click(rows[0].querySelector('[data-node-param-value]'));
      await ui.mouse(rows[0].querySelector('[data-node-param-value]'),'dblclick',10,20);
    }
    assert.equal(focused,2,'parameter clicks still focus the real node');
    assert.equal(opened,2,'double-click propagation still reaches the existing node route');
    assert.equal(ui.calls.length,0,'display-only chips send no writes');
  } finally {await ui.close();}
});
