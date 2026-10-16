const {test} = require('node:test');
const assert = require('node:assert/strict');
const {mountWorkshopNode} = require('./workshop72_node_helpers.cjs');

test('SCREENS2 ordinary Canvas and System nodes use the ONE plate Node and Socket with changing store records', async()=>{
  const node={id:'stored-node',cat:'read',title:'Stored title',subtitle:'Host · Revit · read',x:30,y:70,live:true,
    params:[],ins:[{id:'stored-in',label:'level',t:'text',connectable:true}],
    outs:[{id:'stored-out',label:'doors',t:'elements',list:true,connected:true,connectable:true}],state:'running'};
  const ui=await mountWorkshopNode({state:{},node});
  try {
    assert.ok(ui.doc.querySelector('[data-ds-node][data-node-id="stored-node"]'));
    assert.equal(ui.doc.querySelector('[data-node-card-title]').style.fontSize,'13px');
    assert.ok(ui.doc.querySelector('[data-socket-port="stored-out"] [data-ds-socket]'));
    await ui.draw({node:{...node,title:'Changed in store',application:true,state:'needs-user'}});
    assert.equal(ui.doc.querySelector('[data-node-card-title]').textContent,'Changed in store');
    assert.match(ui.doc.querySelector('[data-node-footer-status]').textContent,/needs.user/);
    assert.equal(ui.calls.length,0,'presentation performs no eager writes');
  } finally {await ui.close();}
});

test('SCREENS2 Home uses shared shells, updates real results, and opens editing on the tile title',async()=>{
  const {mountStudio}=require('./studio_home3_helpers.cjs');
  const ui=await mountStudio({templates:[{id:'saved',title:'Stored recipe',child_count:1,run_count:0,children:[{title:'Stored step',params:{count:2}}]}],
    snapshot:{nativeWork:null,workshop:{root:'room-a',graph_id:'graph-a',scope_root:'scope-a',messages:[],participants:[],workflows:[]}}});
  try {
    await ui.settle();await ui.settle();
    const home=ui.doc.querySelector('[data-home-page]');
    assert.ok(home.matches('[data-ds-frame]'));
    assert.ok(home.querySelector('[data-ds-composer] textarea'));
    assert.ok(home.querySelector('[data-home-template][data-ds-card]'));
    assert.equal(home.querySelectorAll('[data-home-work-state]').length,1);
    assert.equal(home.querySelector('[data-home-template]').textContent.includes('Edit'),false);
    assert.equal(home.querySelector('[data-template-runs]').textContent,'');
    ui.win.ReactDOM.flushSync(()=>home.querySelector('[data-template-edit]').click());
    assert.equal(home.querySelector('[aria-label="Template name"]').value,'Stored recipe');
    ui.update(state=>{state.workshop={...state.workshop,workflows:[{root:'result',title:'Changed store result',state:'done',approval:{current:true},result_summary:'Verified by owner'}]};});
    await ui.settle();
    assert.match(home.querySelector('[data-home-result]').textContent,/Changed store result.*Verified by owner/);
    assert.equal(home.querySelectorAll('[data-home-work-state]').length,0);
  }finally{ui.close();}
});

test('SCREENS2 Home renders actionable error and reading states without manufactured rows',async()=>{
  const {mountStudio}=require('./studio_home3_helpers.cjs');
  for(const waiting of [true,false]){
    const ui=await mountStudio({snapshot:{nativeWork:null,workshops:[{root:'missing-room'}],workshop:null,workshopErrors:waiting?{}:{'missing-room':'offline'}}});
    try{await ui.settle();
      const state=ui.doc.querySelector('[data-home-work-state]');assert.ok(state);
      assert.equal(state.getAttribute('role'),waiting?'status':'alert');
      assert.match(state.textContent,waiting?/Reading/:/unavailable/);
      assert.equal(ui.doc.querySelectorAll('[data-home-result]').length,0);
      if(!waiting)assert.ok(state.querySelector('button'));
    }finally{ui.close();}
  }
});

test('SCREENS2 System params, labels and selection retain store identity through shared nodes',async()=>{
  const {mountSystem}=require('./studio_sysnodes.test.cjs');const ui=await mountSystem();
  try{
    const first=ui.projection.graph.nodes[0];await ui.select(first.id);
    assert.ok(ui.doc.querySelector('[data-node-id="'+first.id+'"][data-ds-node]'));
    assert.equal(ui.doc.querySelectorAll('[data-canvas-run-primary]').length,0);
    assert.equal(ui.doc.querySelectorAll('[data-sysnode-wire-label]').length,ui.projection.graph.wires.length);
    const param=first.params[0],input=ui.doc.querySelector('aside [data-sysnode-param="'+param.k+'"] input');
    await ui.change(input,'#3366aa');
    assert.equal(first.params[0].v,'#3366aa');
    assert.equal(ui.calls.writes.at(-1).id,first.id);
    assert.doesNotMatch(ui.doc.body.textContent,/Not available yet|members:\s*\d+.*status:|relation root is missing/);
  }finally{ui.close();}
});

test('SCREENS2 System loading, empty, error and refused states keep their existing recovery actions',async()=>{
  const {mountSystem}=require('./studio_sysnodes.test.cjs');const ui=await mountSystem();
  try{
    ui.win.__stateCalls=[];
    for(const state of ['loading','empty','error','refused']){
      ui.win.__state=state;
      ui.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(SystemGraphStates,{state:window.__state,error:"Connection unavailable",pinnedCount:2,movedCount:3,onReadAgain:()=>window.__stateCalls.push("read"),onAddNode:()=>window.__stateCalls.push("add"),onUnpinAndArrange:()=>window.__stateCalls.push("open"),onBackToSettings:()=>window.__stateCalls.push("back")})));');
      const shell=ui.doc.querySelector('[data-system-graph-states]');assert.ok(shell);
      assert.equal(shell.getAttribute('role'),state==='error'?'alert':'status');
      const button=shell.querySelector('button');
      if(state==='loading')assert.equal(button.disabled,true);
      else ui.flush(()=>button.click());
    }
    assert.deepEqual([...ui.win.__stateCalls],['add','read','open']);
  }finally{ui.close();}
});

test('SCREENS2 System search, current group and Reset use admitted store values',async()=>{
  const {mountSystem}=require('./studio_sysnodes.test.cjs');const ui=await mountSystem();
  try{
    ui.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(window.SystemSettingsNav,{selectedId:"sys_brain",onOpen:()=>{},onSelect:id=>window.__pickedSetting=id})));');
    assert.match(ui.doc.querySelector('[aria-current="page"]').textContent,/AI/);
    await ui.change(ui.doc.querySelector('input[aria-label="Find a setting"]'),'brain');
    const buttons=[...ui.doc.querySelectorAll('[data-system-settings-nav] button')];
    assert.equal(buttons.length,1);ui.flush(()=>buttons[0].click());assert.equal(ui.win.__pickedSetting,'sys_brain');
    const node=ui.projection.graph.nodes[0],row=node.params[0];row.default='#112233';row.v='#445566';
    ui.win.__resetNode=node;ui.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(window.ApplicationNodeParameters,{node:window.__resetNode})));');
    const reset=ui.doc.querySelector('button[aria-label="Reset Accent"]');assert.ok(reset);
    ui.flush(()=>reset.click());await ui.settle();assert.equal(ui.calls.writes.at(-1).value,'#112233');
    assert.equal(ui.doc.querySelectorAll('button[aria-label="Reset Density"]').length,0);
  }finally{ui.close();}
});

test('SCREENS2 selection approval uses Studio authority and refuses expired or rejected admission',async()=>{
  const {mountSystem}=require('./studio_sysnodes.test.cjs');
  for(const outcome of ['admitted','expired','refused','refresh-failed']){
    const ui=await mountSystem();
    try{
      const calls=[];
      ui.win.ARCHHUB_STUDIO_AUTHORITY.approveNativeWork=async(root,digest)=>{calls.push([root,digest]);return outcome==='refused'?{ok:false,error:'Admission refused'}:{ok:true};};
      if(outcome==='refresh-failed')ui.win.ARCHHUB_STUDIO_AUTHORITY.refreshTopologyCanvas=async()=>{throw new Error('Refresh connection lost');};
      ui.win.ARCHHUB_WORKSHOP_MODEL=()=>ui.win.__approvalModel;
      ui.win.__approvalModel={approval:{id:'review-a',kind:'native',state:'needs-user',title:'Place reviewed tags'},native:{work:'work-a',mode:'agent',input_digest:'digest-a',review_expires_at:Date.now()/1000+60}};
      ui.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(window.ARCHHUB_WORKSHOP_SELECTION_APPROVAL,{state:{canvas:{graph_id:"app",root:"scope-a"}},descriptor:{root:"room-a"}})));');
      const approve=[...ui.doc.querySelectorAll('[data-approval-surface="selection"] button')].find(b=>b.textContent==='Approve');assert.ok(approve);assert.equal(approve.disabled,false);
      if(outcome==='expired')ui.win.__approvalModel.native.review_expires_at=Date.now()/1000-1;
      ui.flush(()=>approve.click());await ui.settle();
      if(['admitted','refresh-failed'].includes(outcome)){
        assert.deepEqual(calls,[['room-a','digest-a']]);assert.equal(approve.textContent,'Approved');
        if(outcome==='refresh-failed'){
          assert.match(ui.doc.querySelector('[role="alert"]').textContent,/Decision recorded.*Refresh connection lost/);
          ui.win.ARCHHUB_STUDIO_AUTHORITY.refreshTopologyCanvas=async()=>({ok:true});
          ui.flush(()=>ui.doc.querySelector('[role="alert"] button').click());await ui.settle();
          assert.equal(ui.doc.querySelector('[role="alert"]'),null);
          ui.flush(()=>approve.click());await ui.settle();assert.equal(calls.length,1,'refresh retry never replays acceptance');
        }
      }
      else {assert.equal(approve.textContent,'Approve');assert.match(ui.doc.querySelector('[role="alert"]').textContent,outcome==='expired'?/no longer available/:/Admission refused/);assert.equal(calls.length,outcome==='expired'?0:1);}
    }finally{ui.close();}
  }
});

test('SCREENS2 scope chrome shows live counts and Collapse; System retains compact Add node',async()=>{
  const {mountSystem}=require('./studio_sysnodes.test.cjs');const ui=await mountSystem();
  try{
    ui.win.__openLibrary=[];
    ui.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(window.NodeCanvas,{system:true,setLibraryOpen:value=>window.__openLibrary.push(value),setFocusId:()=>{}})));');
    const add=ui.doc.querySelector('[data-canvas-add] input');assert.ok(add);assert.equal(add.placeholder,'Add node');
    ui.flush(()=>ui.doc.querySelector('button[aria-label="Open node library"]').click());assert.deepEqual([...ui.win.__openLibrary],[true]);
    ui.projection.graph.nodes.forEach((node,i)=>{node.application=false;node.state=i===0?'running':i===1?'needs-user':'done';});
    ui.win.__collapse=[];ui.authority.composition=async(op,roots)=>{ui.win.__collapse.push([op,[...roots]]);return{ok:true};};
    ui.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(window.NodeCanvas,{key:"session",system:false,setLibraryOpen:()=>{},setFocusId:()=>{}})));');
    const frame=ui.doc.querySelector('[data-canvas-scope-frame]');assert.ok(frame);assert.match(frame.textContent,/3 nodes.*1 wires/);
    assert.equal(frame.querySelector('[data-canvas-live-state]').textContent,'1 running');assert.equal(frame.querySelector('[data-canvas-needs-user]').textContent,'1 waits for you');
    ui.flush(()=>[...frame.querySelectorAll('button')].find(b=>b.textContent.includes('Collapse')).click());await ui.settle();
    assert.equal(ui.win.__collapse[0][0],'group');assert.deepEqual([...ui.win.__collapse[0][1]],ui.projection.graph.nodes.map(n=>n.id));
  }finally{ui.close();}
});


test('SCREENS2 shared segmented values are controlled native radios with zero mount writes',async()=>{
  const {mountSystem}=require('./studio_sysnodes.test.cjs');const ui=await mountSystem();
  try{
    ui.win.__segments=[];
    ui.win.eval('function SegmentedExample(){const[value,setValue]=React.useState("all");return React.createElement(window.AH_DS.Segmented,{label:"Parameters",options:[["all","All"],["changed","Changed"]],value,onChange:value=>{window.__segments.push(value);setValue(value);}});}ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(SegmentedExample)));');
    assert.equal(ui.win.__segments.length,0);
    assert.equal(ui.doc.querySelector('[role="radiogroup"]').getAttribute('aria-label'),'Parameters');
    const radios=ui.doc.querySelectorAll('input[type="radio"]');assert.equal(radios.length,2);assert.equal(radios[0].checked,true);
    ui.flush(()=>radios[1].click());await ui.settle();
    assert.deepEqual([...ui.win.__segments],['changed']);assert.equal(radios[1].checked,true);assert.equal(radios[0].checked,false);
  }finally{ui.close();}
});

test('SCREENS2 completed result retains the stored inactive member avatar',async()=>{
  const {mountStudio}=require('./studio_home3_helpers.cjs');const ui=await mountStudio({snapshot:{nativeWork:null}});
  try{
    ui.win.ARCHHUB_WORKSHOP_MODEL=()=>({tasks:[{work:'result-saved',owner:'agent-saved',title:'Stored result',state:'done',workflow:{root:'result-saved'}}],members:[{id:'agent-saved',name:'Saved agent',ini:'SA',state:'idle'}]});
    ui.update(state=>{state.workshop={...state.workshop,workflows:[{root:'result-saved',state:'done'}]};});await ui.settle();
    const result=ui.doc.querySelector('[data-home-result="result-saved"]');assert.ok(result);
    assert.equal(result.querySelector('[data-workshop-avatar]').getAttribute('data-workshop-avatar'),'agent-saved');
    assert.match(result.querySelector('[data-workshop-avatar]').textContent,/SA/);
    assert.equal(ui.doc.querySelectorAll('[data-home-working-agent]').length,0);
  }finally{ui.close();}
});
