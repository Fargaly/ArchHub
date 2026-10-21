const {test} = require('node:test');
const assert = require('node:assert/strict');
const {mounted, read, plain, text} = require('./workshop72_regression_helpers.cjs');
const {mountWorkshopNode} = require('./workshop72_node_helpers.cjs');

const {fixture} = require('./workshop72_fixture.cjs');

test('WORKSHOP-72 real mount computes v3 rail 64, list 340, thread 780 and status 28', async () => {
  const f=fixture(), ui=await mounted(f.state,f.authority);
  try {
    const appStyle=ui.doc.createElement('style');appStyle.textContent=read('nodelang/studio/studio.html').match(/<style>([\s\S]*?)<\/style>/)[1];ui.doc.head.append(appStyle);
    const size=(selector,property)=>ui.win.getComputedStyle(ui.doc.querySelector(selector))[property];
    assert.equal(size('[data-workshop72-rail]','width'),'64px');
    assert.equal(size('[data-workshop72-list]','width'),'340px');
    assert.equal(size('[data-workshop72-thread]','width'),'780px');
    assert.equal(size('[data-workshop72-composer]','width'),'780px');
    assert.equal(size('[data-workshop72-composer]','boxSizing'),'content-box');
    assert.equal(size('[data-workshop-plan-step] > span:first-child','boxSizing'),'content-box');
    assert.equal(size('[data-workshop72] button','boxSizing'),'border-box');
    assert.equal(size('[data-workshop72-status]','height'),'28px');
    assert.equal(ui.doc.querySelector('main').dataset.screenLabel,'5.1v3_workshop');
  } finally {await ui.close();}
});

test('WORKSHOP-72 no tabs, inspector, board or second composer; visible button ceiling holds with many pending tasks', async () => {
  const f=fixture();
  for(let i=0;i<12;i++) f.state.workshop.workflows.push({root:'flow-'+i,title:'Pending '+i,digest:'f'.repeat(64),nodes:[],approval:{current:false}});
  const ui=await mounted(f.state,f.authority);
  try {
    assert.equal(ui.doc.querySelectorAll('[role=tab],[role=tablist],[data-workshop-s1-inspector],[data-workshop-board-card]').length,0);
    assert.equal(ui.doc.querySelectorAll('textarea').length,1);
    const buttons=[...ui.doc.querySelectorAll('button[data-workshop-primary]')].filter(el=>ui.win.getComputedStyle(el).display!=='none');
    assert.ok(buttons.length<=6,buttons.map(el=>text(el)).join(', '));
    assert.deepEqual(buttons.map(el=>text(el)).sort(),['Approve','Decline','New task','Open on canvas','Review','Send'].sort());
    assert.equal(ui.doc.querySelectorAll('button[data-workshop-agent-picker]').length,1,'the plate agent chip is a secondary keyboard control');
    assert.equal([...ui.doc.querySelectorAll('button')].filter(el=>!el.closest('[data-app-rail]')).length,7,'six primary routes plus the agent chip outside navigation');
  } finally {await ui.close();}
});

test('WORKSHOP-72 v3 sections read the canonical five-column board classification', async () => {
  const f=fixture(); f.state.workshop.planned_items=[{id:'planned-real',title:'Future task',state:'PLANNED'}];
  f.state.workshop.messages.push({root:'done-msg',sender_root:'agent-a',body:'Completed Work work:done0001: verified.'},
    {root:'review-msg',sender_root:'agent-b',body:'Submitted Work work:review01 for review.'});
  const ui=await mounted(f.state,f.authority);
  try {
    const model=ui.win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]});
    assert.deepEqual([...ui.doc.querySelectorAll('[data-workshop-section]')].map(el=>el.dataset.workshopSection),['needs-user','working','done-today']);
    for(const section of model.viewSections) assert.equal(ui.doc.querySelectorAll(`[data-workshop-section="${section.id}"] [data-workshop-task-row]`).length,section.rows.length);
    assert.deepEqual(plain(model.sections.map(s=>s.id)),['review','wip','planned','done','archived']);
    assert.equal(ui.win.getComputedStyle(ui.doc.querySelector('[data-workshop72-sections]')).overflowY,'auto');
  } finally {await ui.close();}
});

test('WORKSHOP-72 message avatars, real sender/time and plain body; one bordered plan carries graph states', async () => {
  const f=fixture(),ui=await mounted(f.state,f.authority);
  try {
    const message=ui.doc.querySelector('[data-workshop-message="reply-a"]');
    assert.match(text(message),/Claude Code.*Read the selection/);
    assert.equal(message.querySelector('pre,code,button,details'),null);
    const steps=[...ui.doc.querySelectorAll('[data-workshop-plan-step]')];
    assert.equal(steps.length,3); assert.match(text(steps[0]),/✓.*Read selection.*done/);
    assert.match(text(steps[1]),/Apply labels.*waits for you/); assert.match(text(steps[2]),/Verify labels.*next/);
    const surface=ui.doc.createElement('div');surface.style.background=ui.win.AH.surf;
    assert.equal(ui.doc.querySelector('[data-workshop-plan]').style.background,surface.style.background);
    assert.equal(ui.doc.querySelectorAll('[aria-label="Run progress"]').length,1);
    assert.equal(ui.win.getComputedStyle(steps[1].lastElementChild).textAlign,'right');
  } finally {await ui.close();}
});

test('WORKSHOP-72 inline approval shows its plain summary when no diff exists and approves exact retained digest once', async () => {
  const f=fixture(); f.authority.refreshTopologyCanvas=async()=>{throw new Error('refresh unavailable');};
  const ui=await mounted(f.state,f.authority);
  try {
    const card=ui.doc.querySelector('[data-workshop-approval-card]');
    assert.equal(card.dataset.workshopApprovalCard,f.work);
    assert.equal(card.querySelector('[data-approval-diff]'),null);
    assert.equal(text(card.querySelector('[data-approval-summary]')),'Label selected elements');
    await ui.act(()=>{ui.button('Approve').click();ui.button('Approve').click();}); await ui.render();
    await ui.click(ui.button('Approve'));
    assert.deepEqual(f.calls.filter(row=>row[0]==='approveNativeWork'),[['approveNativeWork','room-a','a'.repeat(64)]]);
  } finally {await ui.close();}
});

test('WORKSHOP-72 Decline invokes the existing retained native stop path once and Review focuses its card', async () => {
  const f=fixture(),ui=await mounted(f.state,f.authority);
  try {
    await ui.click(ui.button('Review')); await new Promise(resolve=>setTimeout(resolve,10));
    assert.equal(ui.doc.activeElement.dataset.workshopApprovalCard,f.work);
    await ui.act(()=>{ui.button('Decline').click();ui.button('Decline').click();});
    assert.deepEqual(f.calls.filter(row=>row[0]==='nativeWorkAction'),[['nativeWorkAction','room-a','stop_native',f.work]]);
  } finally {await ui.close();}
});

test('WORKSHOP-72 composer routes @agent and default assigned reply through exact live identities; unknown addresses fail closed', async () => {
  const f=fixture(),ui=await mounted(f.state,f.authority);
  try {
    assert.equal(ui.doc.querySelector('textarea').placeholder,'Reply to Claude Code, or @ another agent…');
    await ui.input('@Codex Check labels'); await ui.click(ui.button('Send'));
    assert.deepEqual(f.calls.filter(row=>row[0]==='sendWorkshopMessage').at(-1),['sendWorkshopMessage','room-a',{target:'agent-b',message:'Check labels'}]);
    await ui.input('@unknown Check labels'); await ui.click(ui.button('Send'));
    assert.equal(f.calls.filter(row=>row[0]==='sendWorkshopMessage').length,1); assert.match(text(ui.doc.querySelector('[role=alert]')),/Choose an agent/);
    await ui.input('@all Read results'); await ui.click(ui.button('Send'));
    assert.equal(f.calls.filter(row=>row[0]==='sendWorkshopMessage').at(-1)[2].target,'');
  } finally {await ui.close();}
});

test('WORKSHOP-72 real navigation is one click; New task uses its authority draft route', async () => {
  const f=fixture(),routes=[];
  const ui=await mounted(f.state,f.authority,{onHome:()=>routes.push('home'),onDocs:()=>routes.push('docs'),onSettings:()=>routes.push('settings'),onLibrary:()=>routes.push('library')});
  try {
    for(const name of ['Home','Library','Settings']) await ui.click(ui.doc.querySelector(`[role=link][aria-label="${name}"]`));
    assert.deepEqual(routes,['home','library','settings']);assert.equal(ui.button('New task').disabled,false);
  } finally {await ui.close();}
});

test('WORKSHOP-72 same-source court mounts node and window from one changing authority snapshot', async () => {
  const f=fixture();
  const ui=await mounted(f.state,f.authority);
  const windowModel=plain(ui.win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]}));
  const windowId=ui.doc.querySelector('[data-workshop72]').dataset.workshopId;
  await ui.close();
  const node=await mountWorkshopNode({state:f.state,node:f.node});
  let nodeClosed=false;
  try {
    assert.equal(node.doc.querySelector('[data-workshop-node-face]').dataset.workshopId,windowId);
    assert.deepEqual(plain(node.model()),windowModel);
    f.state.nativeWork.result_count=19; f.state.workshop.participants[1].label='Renamed agent';
    await node.draw({state:f.state}); assert.match(text(node.doc.querySelector('[data-workshop-node-status')),/19 labels/);
    const after=plain(node.model()); await node.close(); nodeClosed=true;
    const reopened=await mounted(f.state,f.authority);
    try {assert.deepEqual(plain(reopened.win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]})),after);}
    finally {await reopened.close();}
  } finally {if(!nodeClosed) await node.close();}
});

test('WORKSHOP-72 changed faces ship no plate samples, rich stream, split-layout or decorative authority', () => {
  const view=read('nodelang/studio/studio-workshop.jsx');
  const model=read('nodelang/studio/shared-data.jsx').split('const HOSTS =')[0];
  for(const sample of ['Nile_Tower','Omar','sara@firm.com','Clinic','46 doors','L3-D001','09:14','run #48']) assert.equal((view+model).includes(sample),false,sample);
  for(const removed of ['data-workshop-s1-inspector','data-workshop-s1-canvas','data-workshop-step-pills','Open as graph','After it runs','to: Workshop','agents listening','wsWindowLayout']) assert.equal(view.includes(removed),false,removed);
  assert.doesNotMatch(view,/localStorage|sessionStorage|role="tab/);
  assert.match(view,/window\.ARCHHUB_WORKSHOP_MODEL\(/);
  assert.match(read('nodelang/studio/studio-lm.jsx'),/window\.ARCHHUB_WORKSHOP_MODEL\?\.\(/);
});

test('WORKSHOP-72 identical snapshot keeps board lanes before and after lazy face loading; stale scope is refused', async () => {
  const f=fixture(),node=await mountWorkshopNode({state:f.state,node:f.node});
  const before=plain(node.model().sections); await node.close();
  const window=await mounted(f.state,f.authority);
  try {
    const after=plain(window.win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]}).sections);
    assert.deepEqual(after,before);
    f.state.workshop.graph_id='other-graph'; f.state.workshop.scope_root='other-scope'; f.state.nativeWork=null;
    await window.render(); const model=window.win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]});
    assert.equal(model.members.length,0);assert.equal(model.tasks.length,0);assert.equal(model.messages.length,0);assert.equal(model.approval,null);
  } finally {await window.close();}
});

test('WORKSHOP-72 hidden Work stays same-source; pending project decline has no unsupported stop action', async () => {
  const f=fixture();
  const work=f.state.topology.graph.nodes.find(row=>row.id===f.work);
  f.state.topology.graph.nodes=f.state.topology.graph.nodes.filter(row=>row.id!==f.work);
  f.state.topology.canvas={...f.state.topology.canvas,hidden_work:[work]}; f.state.nativeWork.mode='project';
  const ui=await mounted(f.state,f.authority);
  try {
    assert.match(text(ui.doc.querySelector('[data-workshop-head]')),/Label selected elements/);
    assert.equal(ui.button('Decline').disabled,true);await ui.click(ui.button('Decline'));
    assert.equal(f.calls.filter(row=>row[0]==='nativeWorkAction').length,0);
  } finally {await ui.close();}
});

module.exports = {fixture};

test('WORKSHOP-72 admitted comparison renders three real rows plus the remaining count and follows snapshot updates', async () => {
  const f=fixture();
  f.state.nativeWork.changes=Array.from({length:5},(_,index)=>({id:'change-'+index,label:'Field '+index,now:'Before '+index,after:'After '+index}));
  const ui=await mounted(f.state,f.authority);
  try {
    const rows=()=>[...ui.doc.querySelectorAll('[data-workshop-change-row]')];
    assert.equal(rows().length,3);
    assert.deepEqual(rows().map(row=>[...row.children].map(cell=>cell.textContent)),[
      ['Field 0','Before 0','After 0'],['Field 1','Before 1','After 1'],['Field 2','Before 2','After 2']]);
    assert.match(text(ui.doc.querySelector('[data-workshop-approval-card]')),/\+ 2 more labels/);
    assert.equal(ui.doc.querySelector('[data-approval-missing]').textContent,'2 changes not supplied by the host');
    await ui.click(ui.doc.querySelector('[data-approval-more]'));
    assert.equal(rows().length,5);
    f.state.nativeWork.result_count=1;f.state.nativeWork.changes=[{id:'updated',label:'Actual field',now:'Current',after:'Revised'}];
    await ui.render();assert.equal(rows().length,1);assert.match(text(rows()[0]),/Actual fieldCurrentRevised/);
    assert.doesNotMatch(text(ui.doc.querySelector('[data-workshop-approval-card]')),/\+ \d+ more/);
  } finally {await ui.close();}
});
