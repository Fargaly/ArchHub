const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('./studio_ds_context.cjs');
const React=require('react');
const {transformSync}=require('esbuild');
const {fixture}=require('./workshop72_fixture.cjs');
const {mounted,text,plain,read}=require('./workshop72_regression_helpers.cjs');
const {mountWorkshopNode,slice}=require('./workshop72_node_helpers.cjs');
const clock=at=>{const d=new Date(at*1000);return [d.getHours(),d.getMinutes()].map(n=>String(n).padStart(2,'0')).join(':');};
const font=value=>value.replace(/['"]/g,'');

test('PASS4 DONE TODAY shows the graph result and completion clock, then updates from the same store',async()=>{
  const f=fixture(),at=Date.now()/1000;
  f.state.workshop.messages.push({root:'completed-event',sender_root:'agent-a',body:'Completed Work work:done0042.',category:'lifecycle',created_at:at});
  f.state.topology.graph.nodes.push({id:'work:done0042',title:'Inspection',status:'done',result_summary:'5 findings',completed_at:at-300});
  f.state.workshop.workflows.push({root:'flow-complete',title:'Verified plan',state:'done',approval:{current:true},result_summary:'8 checked',completed_at:at-120});
  f.state.topology.canvas.hidden_work=[{id:'work:hidden42',engine:'work',title:'Hidden result',status:'done',result_summary:'4 files',completed_at:at-60}];
  const ui=await mounted(f.state,f.authority);
  try{
    const section=()=>text(ui.doc.querySelector('[data-workshop-section="done-today"]'));
    assert.match(section(),new RegExp('5 findings · '+clock(at-300)));
    assert.match(section(),new RegExp('8 checked · '+clock(at-120)));
    assert.match(section(),new RegExp('4 files · '+clock(at-60)));
    const node=f.state.topology.graph.nodes.find(n=>n.id==='work:done0042');
    node.result_summary='6 findings';node.completed_at=at;
    await ui.render();assert.match(section(),new RegExp('6 findings · '+clock(at)));
    assert.doesNotMatch(text(ui.doc.querySelector('[data-workshop-task-row="work:done0042"]')),/5 findings|\bdone\b/i);
    node.result_summary=undefined;await ui.render();assert.match(section(),/Unavailable/);
    assert.doesNotMatch(section(),/Not available yet/);
  }finally{await ui.close();}
});

test('PASS4 avatar picker is a Send-height chip; keyboard selection routes exactly and @agent still overrides it',async()=>{
  const f=fixture(),ui=await mounted(f.state,f.authority);
  const key=async(el,k)=>{await ui.act(()=>el.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:k,bubbles:true})));await ui.render();};
  try{
    const chip=()=>ui.doc.querySelector('[data-workshop-agent-picker]');
    assert.equal(chip().tagName,'BUTTON');assert.equal(chip().style.height,ui.button('Send').style.height);
    assert.ok(chip().querySelector('[data-workshop-avatar="agent-a"]'));
    assert.equal(ui.doc.querySelector('select[aria-label="Reply agent"]'),null);
    chip().focus();await key(chip(),'ArrowDown');
    assert.equal(ui.doc.activeElement.getAttribute('role'),'option');
    await key(ui.doc.activeElement,'End');assert.equal(text(ui.doc.activeElement),'Codex');
    await key(ui.doc.activeElement,'Enter');assert.equal(ui.target(),'agent-b');assert.equal(ui.doc.activeElement,chip());
    assert.ok(chip().querySelector('[data-workshop-avatar="agent-b"]'));
    await ui.input('Check the selected labels');await ui.click(ui.button('Send'));
    assert.deepEqual(plain(f.calls.find(c=>c[0]==='workshopAction')),['workshopAction','room-a','send',null,{message:'Check the selected labels',target:'agent-b'}]);
    await ui.input('@Claude Code Check again');await ui.click(ui.button('Send'));
    assert.equal(f.calls.filter(c=>c[0]==='workshopAction').at(-1)[4].target,'agent-a');
    await key(chip(),'ArrowUp');assert.equal(text(ui.doc.activeElement),'Codex');
    await key(ui.doc.activeElement,'Home');assert.equal(text(ui.doc.activeElement),'Claude Code');
    await key(ui.doc.activeElement,'ArrowUp');assert.equal(text(ui.doc.activeElement),'Codex');
    await key(ui.doc.activeElement,'Escape');assert.equal(chip().getAttribute('aria-expanded'),'false');assert.equal(ui.doc.activeElement,chip());
    await ui.click(chip());await ui.act(()=>ui.button('New task').focus());assert.equal(ui.doc.querySelector('[role=listbox]'),null);
  }finally{await ui.close();}
});

test('PASS4 Watch hides only card sizing; Floor sizing and parameter/action authorities stay intact with Inter chrome',async()=>{
  const f=fixture(),ui=await mountWorkshopNode({state:f.state,node:f.node});
  try{
    const source=read('nodelang/studio/studio-lm.jsx');
    ui.context.useLastRunEpoch=()=>{};
    vm.runInContext(transformSync(slice(source,'const visibleNodeParams =','const socketShapeOf =')+
      slice(source,'const WATCH_TABLE_ROWS =','const isWorkshopGraphNode =')+
      slice(source,'const LiveBody =','const HostBody =')+'\nglobalThis.NodeBody=LiveBody;',{loader:'jsx'}).code,ui.context);
    let runs=0;ui.context.__runToHere=()=>runs++;
    vm.runInContext('const pass4LiveBody=NodeBody;NodeBody=props=>React.createElement(pass4LiveBody,{...props,watchActions:{runToHere:__runToHere}});',ui.context);
    const node={id:'watch-real',cat:'watch',live:true,title:'Result table',x:0,y:0,ins:[],outs:[],
      params:[{k:'watchSize',v:'226x140'},{k:'as',v:'table'}],
      preview:{kind:'table',state:'ready',value:[{Item:'A-17',Value:9}],shape:{rows:1}}};
    await ui.draw({node});
    assert.equal(ui.doc.querySelector('[data-node-inline-param="watchSize"]'),null);
    assert.ok(ui.doc.querySelector('[data-node-inline-param="as"]'));
    assert.equal(ui.doc.querySelector('[data-watch-well]').dataset.watchSize,'226x140');
    const footer=ui.doc.querySelector('[data-watch-actions]'),buttons=[...footer.querySelectorAll('button')];
    assert.deepEqual(buttons.map(text),['Run to here','Export CSV']);
    for(const el of [...buttons,footer.querySelector('[data-watch-caption]'),ui.doc.querySelector('thead')]){
      assert.equal(font(el.style.fontFamily),font(ui.win.AH.sans));assert.ok(parseFloat(el.style.fontSize)>=12&&parseFloat(el.style.fontSize)<=13);
    }
    assert.equal(font(ui.doc.querySelector('table').style.fontFamily),font(ui.win.AH.mono));assert.equal(text(ui.doc.querySelector('td')),'A-17');
    await ui.click(buttons[0]);assert.equal(runs,1);
    await ui.click(buttons[1]);
    assert.equal(ui.win.ARCHHUB_WATCH_EXPORTS.length,1);assert.equal(ui.win.ARCHHUB_WATCH_EXPORTS[0].node,'watch-real');
    assert.equal(ui.win.ARCHHUB_WATCH_EXPORTS[0].text,'"Item","Value"\n"A-17","9"');
    node.cat='logic';await ui.draw({node:{...node,preview:null}});assert.ok(ui.doc.querySelector('[data-node-inline-param="watchSize"]'),'other category params unchanged');
  }finally{await ui.close();}
});

test('PASS4 Doors marks use real locations/crop; no-location read shows a real count instead of empty rooms',async()=>{
  const f=fixture(),ui=await mountWorkshopNode({state:f.state,node:f.node});
  try{
    const crop='data:image/png;base64,aGVsbG8=';
    const node={id:'read-located',cat:'read',title:'Selected objects',x:0,y:0,params:[],ins:[],outs:[{id:'out',label:'doors',list:true}],
      preview:{kind:'image',state:'ready',value:crop,plan_crop:{url:crop,width:240,height:100},elements:[
        {id:'a',location:{x:17,y:32}},{id:'b',location:[112,45]},{id:'c',location:{point:{X:42,Y:80}}},{id:'d',location:{x:NaN,y:9}},null]}};
    await ui.draw({node});
    const marks=[...ui.doc.querySelectorAll('[data-node-plan-mark]')];
    assert.deepEqual(marks.map(el=>[el.dataset.nodePlanMark,el.getAttribute('cx'),el.getAttribute('cy')]),[['a','17','32'],['b','112','45'],['c','42','80']]);
    assert.equal(ui.doc.querySelector('[data-node-plan-preview] image').getAttribute('href'),crop);
    assert.equal(ui.doc.querySelector('[data-node-plan-preview]').getAttribute('viewBox'),'0 0 240 100');
    ui.win.ARCHHUB_LAST_RUN={previews:{[node.id]:{kind:'list',state:'ready',value:[{id:1},{id:2},{id:3},{id:4},{id:5}]}}};
    await ui.draw({node});assert.equal(text(ui.doc.querySelector('[data-node-plan-count]')),'5 doors');
    assert.equal(ui.doc.querySelector('[data-node-plan-preview],image'),null);
    assert.equal(ui.doc.querySelector('[data-node-plan-count]').style.fontSize,'22px');
    ui.win.ARCHHUB_LAST_RUN.previews[node.id]={kind:'list',state:'ready',value:[]};await ui.draw({node});
    assert.equal(text(ui.doc.querySelector('[data-node-plan-count]')),'0 doors');
    delete ui.win.ARCHHUB_LAST_RUN;await ui.draw({node:{...node,cat:'output'}});
    assert.equal(ui.doc.querySelector('[data-node-plan-preview],[data-node-plan-count]'),null,'non-read content unchanged');
  }finally{await ui.close();}
});

test('PASS4 zoom and minimap mount with Inter chrome and retain their routes',async()=>{
  const f=fixture(),ui=await mountWorkshopNode({state:f.state,node:f.node}),{createRoot}=require('react-dom/client');
  const container=ui.doc.createElement('div');ui.doc.body.append(container);const root=createRoot(container);
  try{
    const source=read('nodelang/studio/studio-lm.jsx');ui.context.smallBtn=()=>({});
    vm.runInContext(transformSync(slice(source,'const CanvasToolbar =','const FloatingComposer =')+
      slice(source,'const minimapViewBox =','const useLibraryRefreshEpoch =')+
      '\nglobalThis.Pass4Toolbar=CanvasToolbar;globalThis.Pass4Map=MiniMap;',{loader:'jsx'}).code,ui.context);
    let zoom=1,fits=0;const node={id:'actual',cat:'read',x:20,y:30,w:224,h:160};
    await ui.act(()=>root.render(React.createElement(React.Fragment,null,
      React.createElement(ui.context.Pass4Toolbar,{zoom,setZoom:fn=>zoom=fn(zoom),onFit:()=>fits++,fitLabel:'Fit',onArrange:()=>{},setLibraryOpen:()=>{}}),
      React.createElement(ui.context.Pass4Map,{pan:{x:0,y:0},zoom,positions:{},allNodes:[node]}))));
    const zoomText=container.querySelector('[data-canvas-zoom]'),mapText=[...container.querySelectorAll('[data-canvas-minimap] div')].find(el=>text(el)==='Overview');
    assert.equal(text(zoomText),'100%');assert.equal(font(zoomText.style.fontFamily),font(ui.win.AH.sans));assert.equal(zoomText.style.fontSize,'13px');
    assert.equal(font(mapText.style.fontFamily),font(ui.win.AH.sans));assert.equal(mapText.style.fontSize,'12px');
    await ui.click(container.querySelector('[aria-label="Zoom in"]'));assert.equal(zoom,1.1);
    await ui.click(container.querySelector('[aria-label="Fit"]'));assert.equal(fits,1);
  }finally{await ui.act(()=>root.unmount());await ui.close();}
});
