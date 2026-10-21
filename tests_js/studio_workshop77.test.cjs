const {test}=require('node:test');
const assert=require('node:assert/strict');
const {mounted,plain,text,read}=require('./workshop72_regression_helpers.cjs');
const {fixture}=require('./workshop72_fixture.cjs');

function presentation(f,layout=1){
  f.state.workshopPresentation={root:'room-a',graph_id:'graph-a',subject:'owner-a',layout,models:{groups:[{items:[
    {id:'live-route-a',name:'Registry model A'},{id:'live-route-b',name:'Registry model B'}]}]}};
  f.state.workshop.participants[1].model='live-route-a';
  f.state.workshop.participants[2].model='live-route-b';
  f.authority.setWorkshopLayout=async(root,value)=>{f.calls.push(['setWorkshopLayout',root,value]);f.state.workshopPresentation.layout=value;};
  f.authority.refreshWorkshopPresentation=async(root)=>{f.calls.push(['refreshWorkshopPresentation',root]);};
}

test('DSYS077 empty uses live agent/model chips and exactly one addressed composer',async()=>{
  const f=fixture();presentation(f);f.state.workshop.messages=[];f.state.workshop.workflows=[];f.state.nativeWork=null;
  const ui=await mounted(f.state,f.authority);
  try{
    assert.match(text(ui.doc.querySelector('[data-workshop72-list]')),/No tasks yet\./);
    assert.match(text(ui.doc.querySelector('[data-workshop-empty]')),/What should the agents do\?/);
    assert.equal(ui.doc.querySelectorAll('[data-workshop-empty] [role=radio][aria-checked=true]').length,1);
    assert.equal(ui.doc.querySelectorAll('textarea').length,1);
    assert.equal(ui.doc.querySelector('[data-workshop-plan],[data-workshop-approval-card]'),null);
    assert.match(text(ui.doc.querySelector('[data-workshop-empty]')),/Registry model A/);
    assert.equal(ui.doc.querySelector('[data-workshop72-thread]'),null);
    assert.equal(ui.doc.querySelectorAll('[data-workshop-section]').length,0);
    await ui.click([...ui.doc.querySelectorAll('[data-workshop-empty] [role=radio]')][1]);
    await ui.input('Ask selected agent');await ui.click(ui.button('Send'));
    assert.equal(f.calls.find(c=>c[0]==='sendWorkshopMessage')[2].target,'agent-b');
    f.state.workshop=null;await ui.render();
    assert.doesNotMatch(text(ui.doc.querySelector('[data-workshop72-list]')),/No tasks yet/);
    assert.match(text(ui.doc.querySelector('[data-workshop72-list] [role=status]')),/Unavailable/);
    assert.doesNotMatch(text(ui.doc.body),/Not available yet/,'missing authority uses product-safe copy');
  }finally{await ui.close();}
});

test('DSYS075 chooses durable 1/2/4 state and selected tile owns composer agent routing',async()=>{
  const f=fixture();presentation(f);
  f.state.workshop.workflows[0].proposed_by='agent-b';
  f.state.workshop.assignments.push({work:'flow-a',agent_session:'agent-b'});
  f.state.workshop.workflows.push({root:'work:second01',title:'Actual second task',proposed_by:'agent-b',nodes:[],digest:'b'.repeat(64),approval:{current:true}});
  f.state.workshop.assignments.push({work:'work:second01',agent_session:'agent-b'});
  const ui=await mounted(f.state,f.authority);
  try{
    assert.equal(ui.doc.querySelector('[data-workshop-tiles]'),null);
    await ui.click(ui.doc.querySelector('[aria-label="Task layout"] [role=radio]:nth-child(2)'));
    assert.deepEqual(f.calls.find(c=>c[0]==='setWorkshopLayout'),['setWorkshopLayout','room-a',2]);
    assert.equal(ui.doc.querySelector('[data-workshop-tiles]').dataset.workshopTiles,'2');
    assert.equal(ui.doc.querySelectorAll('textarea').length,1);
    await ui.click(ui.doc.querySelector('[data-workshop-tile="work:second01"]')||ui.doc.querySelectorAll('[data-workshop-tile]')[1]);
    const selected=ui.selection().task;
    const agent=f.state.workshop.assignments.find(a=>a.work===selected)?.agent_session || f.state.workshop.workflows.find(a=>a.root===selected)?.proposed_by;
    await ui.input('Read the selected tile');await ui.click(ui.button('Send'));
    assert.equal(f.calls.filter(c=>c[0]==='sendWorkshopMessage').at(-1)[2].target,agent);
    await ui.click(ui.doc.querySelector('[aria-label="Task layout"] [role=radio]:nth-child(3)'));
    assert.equal(f.state.workshopPresentation.layout,4);
    assert.equal(ui.doc.querySelector('[data-workshop-tiles]').dataset.workshopTiles,'4');
  }finally{await ui.close();}
  const reopened=await mounted(f.state,f.authority);
  try{assert.equal(reopened.doc.querySelector('[data-workshop-tiles]').dataset.workshopTiles,'4');}finally{await reopened.close();}
});

test('DSYS077 user bubble, live models, recorded elapsed/cost and task progress survive model registry updates',async()=>{
  const f=fixture();presentation(f);
  f.state.workshop.messages[0].work_root=f.work;
  f.state.workshop.messages[1].elapsed='17 s';f.state.workshop.messages[1].cost_label='recorded free';
  f.state.topology.graph.nodes.find(n=>n.id===f.work).progress=42;
  const ui=await mounted(f.state,f.authority);
  try{
    assert.equal(ui.doc.querySelector('[data-user-bubble]').dataset.workshopMessage,'ask-a');
    const msg=()=>text(ui.doc.querySelector('[data-workshop-message="reply-a"]'));
    assert.match(msg(),/Registry model A.*17 s.*recorded free/);
    const registryName=ui.doc.querySelector('[data-workshop-agents] [title="Registry model A"]');
    assert.equal(registryName.style.whiteSpace,'nowrap');
    assert.equal(registryName.style.textOverflow,'ellipsis');
    assert.equal(ui.doc.querySelector('[aria-label="Task progress"]').getAttribute('aria-valuenow'),'42');
    f.state.workshopPresentation.models.groups[0].items[0].name='Registry updated';await ui.render();
    assert.match(msg(),/Registry updated/);
    assert.doesNotMatch(msg(),/Sonnet 4\.6|GPT-5\.5/);
  }finally{await ui.close();}
});

test('DSYS077 search filters real task rows, Ctrl K focuses search, task switch opens at first message',async()=>{
  const f=fixture();presentation(f);const ui=await mounted(f.state,f.authority);
  try{
    ui.doc.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:'k',ctrlKey:true,bubbles:true}));
    const search=ui.doc.querySelector('[aria-label="Search tasks"]');assert.equal(ui.doc.activeElement,search);
    await ui.act(()=>{Object.getOwnPropertyDescriptor(ui.win.HTMLInputElement.prototype,'value').set.call(search,'not-found');search.dispatchEvent(new ui.win.Event('input',{bubbles:true}));});
    assert.equal(ui.doc.querySelectorAll('[data-workshop-task-row]').length,0);
    await ui.act(()=>{Object.getOwnPropertyDescriptor(ui.win.HTMLInputElement.prototype,'value').set.call(search,'');search.dispatchEvent(new ui.win.Event('input',{bubbles:true}));});
    const viewport=ui.doc.querySelector('[aria-label="Workshop conversation"]');
    Object.defineProperty(viewport,'scrollHeight',{configurable:true,value:1400});Object.defineProperty(viewport,'clientHeight',{configurable:true,value:200});
    viewport.scrollTop=650;
    await ui.click(ui.doc.querySelectorAll('[data-workshop-task-row]')[1]);
    assert.equal(viewport.scrollTop,0,'changed task starts at its first message');
    assert.deepEqual(plain(ui.win.ARCHHUB_WORKSHOP_MODEL({state:f.state,descriptor:f.state.workshops[0]}).sections.map(s=>s.id)),['review','wip','planned','done','archived']);
  }finally{await ui.close();}
});

test('DSYS077 default primary control ceiling lists six routes; unavailable layout fails closed',async()=>{
  const f=fixture(),ui=await mounted(f.state,f.authority);
  try{
    const controls=[...ui.doc.querySelectorAll('button[data-workshop-primary]')].map(el=>text(el));
    assert.deepEqual(controls.sort(),['New task','Open on canvas','Review','Approve','Decline','Send'].sort());
    assert.equal(ui.doc.querySelectorAll('[data-workshop-primary]').length,6);
    assert.equal([...ui.doc.querySelectorAll('button')].filter(button=>!button.closest('[data-app-rail]')).length,7,'six primary routes plus the plate picker');
    assert.equal(ui.doc.querySelector('[data-workshop-agent-picker]').getAttribute('aria-haspopup'),'listbox');
    assert.equal(ui.doc.querySelector('[aria-label="Task layout"] [role=radio]').getAttribute('aria-disabled'),'true');
    await ui.click(ui.doc.querySelector('[aria-label="Task layout"] [role=radio]:nth-child(2)'));
    assert.equal(ui.doc.querySelector('[data-workshop-tiles]'),null);
    const source=read('nodelang/studio/studio-workshop.jsx');
    assert.doesNotMatch(source,/localStorage|sessionStorage|Sonnet 4\.6|GPT-5\.5/);
  }finally{await ui.close();}
});

test('DSYS075 four tiles retain each inline approval, bounded primary controls and exact per-card decision digest',async()=>{
  const f=fixture();presentation(f,4);
  for(let i=0;i<3;i++)f.state.workshop.workflows.push({root:'flow-pending-'+i,title:'Reviewed actual task '+i,
    proposed_by:'agent-b',digest:String(i+1).repeat(64),nodes:[],approval:{current:false}});
  const ui=await mounted(f.state,f.authority);
  try{
    const cards=[...ui.doc.querySelectorAll('[data-workshop-tiles] [data-workshop-approval-card]')];
    assert.ok(cards.length>1,'several real waiting tasks remain reviewable inline');
    assert.ok(ui.doc.querySelectorAll('button[data-workshop-primary]').length<=4+2*cards.length,'only primary New/Open/Review/Send plus each card pair');
    assert.equal(ui.doc.querySelectorAll('button[data-workshop-agent-picker]').length,1,'the shared composer keeps one secondary agent chip');
    const card=cards.find(c=>c.dataset.workshopApprovalKind==='workflow');assert.ok(card);
    const id=card.dataset.workshopApprovalCard,workflow=f.state.workshop.workflows.find(w=>w.root===id);
    const approve=[...card.querySelectorAll('button')].find(b=>text(b)==='Approve');
    await ui.act(()=>{approve.click();approve.click();});
    assert.deepEqual(f.calls.filter(c=>c[0]==='workshopWorkflow'),[['workshopWorkflow','room-a','workflow-approve',{workflow:id,digest:workflow.digest}]]);
    workflow.digest='e'.repeat(64);await ui.render();
    const updated=ui.doc.querySelector(`[data-workshop-approval-card="${id}"] button`);
    assert.equal(updated.disabled,false,'a changed workflow requires its new review');
    await ui.click(updated);
    assert.equal(f.calls.filter(c=>c[0]==='workshopWorkflow').at(-1)[3].digest,'e'.repeat(64));
  }finally{await ui.close();}
});

test('DSYS077 an eventless planned task hides explicitly foreign Work while retaining real unscoped room transport',async()=>{
  const f=fixture();presentation(f);
  f.state.workshop.planned_items=[{id:'work:planned-b',title:'Planned real task',state:'PLANNED'}];
  f.state.workshop.messages.push({root:'foreign-a',sender_root:'agent-a',task_root:f.work,body:'Explicit foreign task record'},
    {root:'room-note',sender_root:'agent-b',body:'Actual room transport note'});
  const ui=await mounted(f.state,f.authority,{sel:{task:'work:planned-b'}});
  try{
    assert.equal(ui.doc.querySelector('[data-workshop-message="foreign-a"]'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-message="reply-a"]'),null);
    assert.match(text(ui.doc.querySelector('[data-workshop-message="room-note"]')),/Actual room transport note/);
    assert.equal(ui.doc.querySelector('[data-workshop-head]').textContent,'Planned real task');
  }finally{await ui.close();}
});
