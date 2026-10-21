const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('./studio_ds_context.cjs');
const {read,transport,plain} = require('./workshop72_regression_helpers.cjs');

async function mount(approval,callbacks={}) {
  const {JSDOM} = await import('jsdom');
  const React = require('react'), {createRoot} = require('react-dom/client'), {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>',{url:'http://127.0.0.1/'});
  const prior = {window:global.window,document:global.document};
  global.window=dom.window;global.document=dom.window.document;global.IS_REACT_ACT_ENVIRONMENT=true;
  const win=dom.window, context=vm.createContext({React,window:win,console});
  vm.runInContext(read('nodelang/studio/tokens.jsx'),context);
  vm.runInContext(transformSync(read('nodelang/studio/shared-data.jsx'),{loader:'jsx'}).code,context);
  const root=createRoot(win.document.getElementById('root'));
  const render=async next=>React.act(async()=>root.render(React.createElement(win.ARCHHUB_APPROVAL_CARD,{approval:next,...callbacks})));
  await render(approval);
  return {win,doc:win.document,render,act:React.act,close:async()=>{await React.act(async()=>root.unmount());dom.window.close();Object.assign(global,prior);delete global.IS_REACT_ACT_ENVIRONMENT;}};
}

test('one mounted approval card renders real diff/crop and affected markers, gates glow and truthful undo',async()=>{
  const rows=Array.from({length:7},(_,i)=>({id:'real-'+i,label:'Element '+i,now:'old '+i,after:'new '+i}));
  const approval={id:'approval-a',state:'needs-user',title:'Reviewed change',agent_label:'Assigned agent',host:'Host',document:'Current document',scope:'Selection',rows,count:7,
    plan_crop:{url:'data:image/png;base64,AA==',width:400,height:200},affected_items:[{id:'real-0',x:20,y:30}],undo_available:true,unchanged_scope:true,writes_to_model:true};
  const ui=await mount(approval,{onApprove:async()=>{},onDecline:async()=>{}});
  try {
    assert.equal(ui.doc.querySelectorAll('[data-workshop-change-row]').length,3);
    assert.equal(ui.doc.querySelector('[data-approval-more]').textContent,'+ 4 more');
    assert.equal(ui.doc.querySelector('[data-approval-more]').getAttribute('aria-expanded'),'false');
    await ui.act(async()=>ui.doc.querySelector('[data-approval-more]').click());
    assert.deepEqual([...ui.doc.querySelectorAll('[data-workshop-change-row]')].map(row=>row.textContent),rows.map(row=>row.label+row.now+row.after));
    assert.equal(ui.doc.querySelector('[data-approval-more]').getAttribute('aria-expanded'),'true');
    assert.equal(ui.doc.querySelector('[data-approval-plan]').dataset.approvalPlan,'host-crop');
    assert.equal(ui.doc.querySelector('image').getAttribute('href'),approval.plan_crop.url);
    assert.equal(ui.doc.querySelector('[data-approval-affected]').getAttribute('cx'),'20');
    assert.equal(ui.doc.querySelector('[data-approval-component]').style.boxShadow,ui.win.AH.glow.warn);
    assert.equal(ui.doc.querySelector('[data-approval-meta]').textContent,'Host · Current document · Selection · nothing else changes');
    const writes=ui.doc.querySelector('[data-approval-writes-model]');
    assert.equal(writes.style.height,'24px');assert.equal(writes.style.padding,'0px 9px');
    assert.equal(writes.style.borderRadius,'999px');assert.equal(writes.style.fontSize,'12px');assert.equal(writes.style.fontWeight,'600');
    const expectedChip=ui.doc.createElement('span');expectedChip.style.background=ui.win.AH.warn+'1f';
    assert.equal(writes.style.background,expectedChip.style.background);
    const primary=ui.doc.querySelector('[data-workshop-primary=approve]');
    assert.equal(primary.style.height,'36px');assert.equal(primary.style.padding,'0px 16px');
    assert.match(primary.style.background,/linear-gradient\(180deg/);assert.match(primary.style.boxShadow,/0 4px 14px/);
    assert.ok(ui.doc.querySelector('[data-approval-undo]'));
    await ui.render({...approval,state:'done',undo_available:false});
    assert.notEqual(ui.doc.querySelector('[data-approval-component]').style.boxShadow,ui.win.AH.glow.warn);
    assert.equal(ui.doc.querySelector('[data-approval-undo]'),null);
  } finally {await ui.close();}
});

test('compact approval surfaces stack the real crop and diff within a narrow tile',async()=>{
  const ui=await mount({id:'tile',state:'needs-user',rows:[{id:'affected',now:'Before',after:'After'}]},
    {surface:'workshop-tile'});
  try {
    assert.equal(ui.doc.querySelector('[data-approval-preview]').style.gridTemplateColumns,'1fr');
    assert.equal(ui.doc.querySelector('svg'),null);
    assert.equal(ui.doc.querySelector('[data-approval-plan]').dataset.approvalPlan,'unavailable');
    assert.match(ui.doc.querySelector('[data-approval-plan]').textContent,/1 changesSpatial preview unavailable/);
    assert.equal(ui.doc.querySelectorAll('[data-workshop-change-row]').length,1);
  } finally {await ui.close();}
});

test('no host crop means a visible non-spatial count, never invented geometry or locations',async()=>{
  const ui=await mount({id:'no-crop',state:'needs-user',count:12,unit:'doors',affected_items:[{id:'unplaced',x:10,y:20}]});
  try {
    assert.equal(ui.doc.querySelector('[data-approval-plan]').textContent,'12 doorsSpatial preview unavailable');
    assert.equal(ui.doc.querySelector('svg,image,rect,circle,[data-approval-affected]'),null);
    assert.equal(ui.doc.querySelector('[data-approval-missing]').textContent,'12 changes not supplied by the host','zero supplied rows still disclose missing detail');
    assert.equal(ui.doc.querySelector('[data-workshop-change-row]'),null,'no invented rows');
    await ui.render({id:'unsafe-crop',count:12,unit:'doors',plan_crop:{url:'https://untrusted.invalid/crop.png'},rows:[{id:'a',after:'Actual change'}]});
    assert.match(ui.doc.querySelector('[data-approval-plan]').textContent,/Spatial preview unavailable/);
    assert.equal(ui.doc.querySelector('[data-approval-more]'),null,'no expandable invented changes');
    assert.equal(ui.doc.querySelector('[data-approval-missing]').textContent,'11 changes not supplied by the host');
  } finally {await ui.close();}
});

test('workflow review expands every source Brain operation with complete fragment values before approval',async()=>{
  const ops=Array.from({length:8},(_,i)=>({op:'add',fragment:{id:'fact-'+i,kind:'decision',text:'Full reviewed text '+i+'\n'+'.'.repeat(160)}}));
  const approval={id:'brain',kind:'workflow',state:'needs-user',workflow:{nodes:[{root:'brain-node',engine:'brain.write',params:{arguments:{value:JSON.stringify({ops})}}}]}};
  const ui=await mount(approval);
  try {
    assert.equal(ui.doc.querySelectorAll('[data-workshop-change-row]').length,3);
    assert.equal(ui.doc.querySelector('[data-approval-more]').textContent,'+ 5 more');
    await ui.act(async()=>ui.doc.querySelector('[data-approval-more]').click());
    const actual=[...ui.doc.querySelectorAll('[data-workshop-change-row]')].map(row=>JSON.parse(row.lastElementChild.textContent));
    assert.deepEqual(actual,ops);
    await ui.render({...approval,id:'brain-ops',workflow:{nodes:[{root:'brain-node',engine:'brain.write',params:{ops:{value:JSON.stringify(ops)}}}]}});
    assert.equal(ui.doc.querySelectorAll('[data-workshop-change-row]').length,3,'new reviewed identity collapses');
    await ui.act(async()=>ui.doc.querySelector('[data-approval-more]').click());
    assert.deepEqual([...ui.doc.querySelectorAll('[data-workshop-change-row]')].map(row=>JSON.parse(row.lastElementChild.textContent)),ops);
  } finally {await ui.close();}
});

test('approval callbacks fire once for rapid gestures and retained settled identity',async()=>{
  let approve=0,decline=0,finish;const pending=new Promise(resolve=>finish=resolve);
  const ui=await mount({id:'one',state:'needs-user',title:'One'},{onApprove:()=>{approve++;return pending;},onDecline:async()=>{decline++;}});
  try {
    await ui.act(async()=>{ui.doc.querySelector('[data-workshop-primary=approve]').click();ui.doc.querySelector('[data-workshop-primary=approve]').click();});
    assert.equal(approve,1);await ui.act(async()=>finish());
    await ui.act(async()=>ui.doc.querySelector('[data-workshop-primary=decline]').click());assert.equal(decline,0);
    await ui.render({id:'two',state:'needs-user',title:'Two'});
    await ui.act(async()=>ui.doc.querySelector('[data-workshop-primary=decline]').click());assert.equal(decline,1);
  } finally {await ui.close();}
});

test('shared approval supports post/email attachment/sign-in variants without synthetic rows',async()=>{
  const ui=await mount({id:'post',state:'needs-user',agent_label:'Assigned agent',target:'Confirmed account',preview:{kind:'post',text:'Actual approved draft'}},{surface:'home'});
  try {
    assert.equal(ui.doc.querySelector('[data-approval-post]').textContent,'Actual approved draft');
    assert.equal(ui.doc.querySelector('[data-approval-meta]').textContent,'Assigned agent · Confirmed account');
    assert.equal(ui.doc.querySelectorAll('[data-workshop-change-row]').length,0);
    await ui.render({id:'mail',preview_kind:'email',email:{to:'Recipient',subject:'Actual subject',body:'Actual body',attachments:[{name:'Actual.pdf'}]}});
    assert.equal(ui.doc.querySelector('[data-approval-attachment]').textContent,'Actual.pdf');
    await ui.render({id:'signin',preview:{kind:'sign-in',line:'Authenticate the connected account'}});
    assert.equal(ui.doc.querySelector('[data-approval-sign-in]').textContent,'Authenticate the connected account');
    assert.equal(ui.doc.querySelectorAll('button:disabled').length,2);
  } finally {await ui.close();}
});

test('a refused approval keeps the same reviewed card retryable and reports its producer error',async()=>{
  let attempts=0;
  const ui=await mount({id:'retry',input_digest:'reviewed',state:'needs-user',title:'Reviewed request'},
    {onApprove:async()=>{if(++attempts===1)throw new Error('Producer refused');}});
  try {
    await ui.act(async()=>ui.doc.querySelector('[data-workshop-primary=approve]').click());
    assert.equal(ui.doc.querySelector('[role=alert]').textContent,'Producer refused');
    assert.equal(ui.doc.querySelector('[data-workshop-primary=approve]').disabled,false);
    await ui.act(async()=>ui.doc.querySelector('[data-workshop-primary=approve]').click());
    assert.equal(attempts,2);assert.equal(ui.doc.querySelector('[role=alert]'),null);
  } finally {await ui.close();}
});

test('layout and model catalogue first-open read is lazy and account-bound, no localStorage preference',async()=>{
  let layout=1;
  const t=transport({get:async url=>url==='/api/universal/models'?{ok:true,groups:[{items:[{id:'registered',name:'Registered model'}]}]}:{},post:async(url,body)=>{
    if(body.action==='presentation-layout')layout=body.layout;
    return {ok:true,graph_id:'graph-a',subject:'owner-a',root:body.root,scope_root:body.scope,revision:5,layout};
  }});
  assert.equal(t.posts.length,0);assert.equal(t.gets.length,0);
  t.api.setCanvas({graph_id:'graph-a',root:'scope-a',revision:4,authorization:{subject:'owner-a',session:'view-a'},workshops:[{root:'room-a',label:'Workshop'}]});
  const first=await t.api.refreshWorkshopPresentation('room-a');assert.equal(first.layout,1);
  await t.api.refreshWorkshopPresentation('room-a');assert.equal(t.gets.filter(url=>url==='/api/universal/models').length,1);
  await t.api.setWorkshopLayout('room-a',4);assert.equal(t.api.getSnapshot().workshopPresentation.layout,4);
  assert.equal(plain(t.posts.at(-1).body).action,'presentation-layout');
  assert.doesNotMatch(read('nodelang/studio/studio-existing-workshop.js'),/localStorage.*(?:layout|tile)|(?:layout|tile).*localStorage/);
});

test('agent model labels resolve only live registry entries and free-only agents reject paid models',()=>{
  const source=read('nodelang/studio/shared-data.jsx');const win={};
  vm.runInNewContext(source.slice(0,source.indexOf('const HOSTS =')),{window:win});
  const state={canvas:{graph_id:'graph-a',authorization:{subject:'owner-a'}},workshopPresentation:{graph_id:'graph-a',subject:'owner-a',models:{groups:[{items:[{id:'free-id:free',name:'Live free name'},{id:'paid-id',name:'Live paid name'}]}]}}};
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'free-id:free',runtime:'opencode'},state),'Live free name');
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'paid-id',runtime:'opencode'},state),null);
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'paid-id',runtime:'claude'},state),'Live paid name');
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'invented'},state),null);
  state.workshopPresentation.subject='another-account';
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'paid-id',runtime:'claude'},state),null);
  state.workshopPresentation.subject='owner-a';state.workshopPresentation.graph_id='another-graph';
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'paid-id',runtime:'claude'},state),null);
  state.models={items:[{id:'paid-id',name:'Current account registry'}]};
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'paid-id',runtime:'claude'},state),'Current account registry');
  state.workshopPresentation.graph_id='graph-a';state.workshopPresentation.layout=4;
  state.topology={canvas:{application_root:'graph-a',authorization:{subject:'another-account'}}};
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'paid-id',runtime:'claude'},state),null);
  state.topology.canvas.authorization.subject='owner-a';state.topology.canvas.application_root='another-graph';
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL({model:'paid-id',runtime:'claude'},state),null);
  assert.equal(win.ARCHHUB_WORKSHOP_MODEL({state}).layout,1);
});

test('missing account presentation is null-safe and confirmed native approval clears the needs-user row',()=>{
  const source=read('nodelang/studio/shared-data.jsx'), win={};
  const context=vm.createContext({window:win});
  vm.runInContext(read('nodelang/studio/tokens.jsx'),context);
  vm.runInContext(source.slice(0,source.indexOf('const HOSTS =')),context);
  assert.equal(win.ARCHHUB_WORKSHOP_MODEL().layout,1);
  assert.equal(win.ARCHHUB_WORKSHOP_MODEL({state:{workshopPresentation:{layout:4}}}).layout,1);
  assert.equal(win.ARCHHUB_WORKSHOP_AGENT_MODEL(), null);
  const f=require('./workshop72_fixture.cjs').fixture();
  const before=win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]});
  assert.equal(before.tasks.find(row=>row.work===f.work).approving,true);
  assert.ok(before.viewSections[0].rows.some(row=>row.work===f.work));
  f.state.nativeWork.approved=true;
  const after=win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]});
  assert.equal(after.tasks.find(row=>row.work===f.work).approving,false);
  assert.equal(after.viewSections[0].rows.some(row=>row.work===f.work),false);
  assert.equal(after.needs_user,false);assert.equal(after.status.text,'Approved');
});

test('all app approval surfaces route through one shared component, without duplicated action markup',()=>{
  for(const file of ['studio-workshop.jsx','studio-mobile.jsx','studio-lm.jsx','workshop-board.jsx'])assert.match(read('nodelang/studio/'+file),/ARCHHUB_APPROVAL_CARD/);
  const all=['shared-data.jsx','studio-workshop.jsx','studio-mobile.jsx','studio-lm.jsx'].map(file=>read('nodelang/studio/'+file)).join('\n');
  assert.equal((all.match(/function ApprovalCard\(/g)||[]).length,1);
  assert.equal((all.match(/>\{approveLabel\}<\/button>/g)||[]).length,1);
  assert.doesNotMatch(read('nodelang/studio/studio-mobile.jsx'),/MB_GATES_SEED|Simulate new requests/);
});

test('missing change detail is disclosed with a crop and zero rows, and on post/email/sign-in previews',async()=>{
  const ui=await mount({id:'crop-zero',count:5,plan_crop:{url:'data:image/png;base64,AA==',width:400,height:200},affected_items:[{id:'p',x:20,y:30}]});
  try {
    assert.equal(ui.doc.querySelector('[data-approval-plan]').getAttribute('data-approval-plan'),'host-crop');
    assert.equal(ui.doc.querySelector('[data-approval-missing]').textContent,'5 changes not supplied by the host');
    assert.equal(ui.doc.querySelector('[data-workshop-change-row]'),null);
    for (const [kind,extra] of [['post',{post:{text:'Real post'}}],['email',{email:{to:'a@example.invalid',subject:'S',body:'B'}}],['sign-in',{sign_in:{line:'Sign in to X'}}]]) {
      await ui.render({id:'k-'+kind,preview_kind:kind,count:3,rows:[{id:'r',after:'one'}],...extra});
      assert.equal(ui.doc.querySelector('[data-approval-missing]').textContent,'2 changes not supplied by the host',kind);
    }
    await ui.render({id:'one',count:2,rows:[{id:'r',after:'one'}]});
    assert.equal(ui.doc.querySelector('[data-approval-missing]').textContent,'1 change not supplied by the host');
    await ui.render({id:'complete',count:1,rows:[{id:'r',after:'one'}]});
    assert.equal(ui.doc.querySelector('[data-approval-missing]'),null,'nothing missing, nothing disclosed');
  } finally {await ui.close();}
});
