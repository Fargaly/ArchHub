/* WORKSHOP-72: the deleted embedded canvas migrates to the actual main-canvas NodeRenderer.
   Nine behavior courts retained; fit reads the actual main canvas geometry function. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {mountWorkshopNode, read, slice} = require('./workshop72_node_helpers.cjs');
const text = el => el ? el.textContent.replace(/\s+/g,' ').trim() : '';
const member = 'app:agent-session:runtime:codex';
function fixture(extra = {}) {
  const node = {id:'room-a', title:'Workshop', cat:'workshop', x:120, y:80, ins:[], outs:[], members:[member], ...extra};
  const state = {canvas:{root:'scope-a'}, workshops:[{root:'room-a', label:'Workshop'}],
    topology:{graph:{nodes:[node, {id:member, title:'Codex', group:'room-a'}], wires:[]}},
    workshop:{ok:true, root:'room-a', self:'owner-a', can_send:true, messages:[],
      participants:[{root:'owner-a', label:'Owner', is_agent:false},
        {root:member, label:'Codex', is_agent:true, connected:true, attached:true}]}};
  return {node,state};
}
async function drag(ui, end = 'pointerup') {
  const card = ui.doc.querySelector('[data-node-id="room-a"]');
  card.getBoundingClientRect = () => ({left:40,top:30,right:260,bottom:116,width:220,height:86});
  const chip = ui.doc.querySelector('[data-workshop-node-member]');
  assert.ok(chip, 'real agent tile is present');
  await ui.mouse(chip, 'pointerdown', 70, 70);
  await ui.mouse(ui.win, 'pointermove', 120, 120);
  await ui.mouse(ui.win, end, 320, 160);
  return chip;
}
function fitHarness() {
  const context = vm.createContext({});
  vm.runInContext(slice(read('01.APP/nodelang/studio/studio-lm.jsx'), 'const CANVAS_FIT_TOP =', 'const canvasRevealBounds =') +
    '\nglobalThis.fit = canvasFitBounds;',context);
  return context.fit;
}
function assertFit(fit, ids, positions, sizes, viewport) {
  const before = JSON.stringify(positions);
  const result = fit(ids,positions,sizes,viewport);
  assert.equal(JSON.stringify(positions),before,'Fit preserves persisted user positions');
  for (const id of ids) {
    const p=positions[id],s=sizes[id],z=result.zoom,pan=result.pan;
    assert.ok(pan.x+p.x*z >= 24-1 && pan.x+(p.x+s.w)*z <= viewport.width-24+1,id+' horizontal bounds');
    assert.ok(pan.y+p.y*z >= 80-1 && pan.y+(p.y+s.h)*z <= viewport.height-80+1,id+' vertical bounds');
  }
}

test('p5 empty workflow renders no fabricated nodes or Watch result on the main-canvas Workshop face',async()=>{
  const ui=await mountWorkshopNode(fixture());
  try {
    assert.equal(ui.doc.querySelectorAll('[data-socket-port]').length,0);
    assert.equal(ui.doc.querySelectorAll('[data-node-id]').length,1);
    assert.equal(ui.doc.querySelector('[data-workshop-watch-table]'),null);
    assert.doesNotMatch(text(ui.doc.body),/Host read|Filter|LevelDoorTag|Door tags|12 tags/);
  } finally {await ui.close();}
});

test('p5 non-door workflow renders its own typed ports and no fabricated Watch result',async()=>{
  const fx=fixture({ins:[{id:'beams',label:'beams',t:'elements',list:true,connectable:true}],
    outs:[{id:'spans',label:'spans',t:'rows',list:true,connectable:true}]});
  const ui=await mountWorkshopNode(fx);
  try {
    assert.deepEqual([...ui.doc.querySelectorAll('[data-socket-port]')].map(el=>el.dataset.socketPort),['beams','spans']);
    assert.deepEqual([...ui.doc.querySelectorAll('[data-socket-port]')].map(el=>el.dataset.socketShape),['diamond','diamond']);
    assert.doesNotMatch(text(ui.doc.body),/doors|Door tags|12 tags/);
  } finally {await ui.close();}
});

test('p5 the real Workshop face keeps socket actions live and suppresses duplicate window controls',async()=>{
  const fx=fixture({ins:[{id:'beams',label:'beams',t:'elements',connectable:true}]});
  const ui=await mountWorkshopNode(fx);
  try {
    await ui.click(ui.doc.querySelector('[data-socket-port="beams"]'));
    assert.equal(ui.calls.filter(row=>row[0]==='socket').length,1);
    assert.equal(ui.doc.querySelector('textarea'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-add-node]'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-node-member]').getAttribute('draggable'),'false');
  } finally {await ui.close();}
});

test('p6 main-canvas Workshop group uses real agent ids and ports without raw ids in its text',async()=>{
  const ui=await mountWorkshopNode(fixture());
  try {
    const face=ui.doc.querySelector('[data-workshop-node-face]');
    assert.equal(face.dataset.workshopId,'room-a');
    assert.equal(face.querySelectorAll('[data-workshop-node-member]').length,1);
    assert.equal(face.querySelector('[data-workshop-node-member]').dataset.workshopNodeMember,member);
    assert.doesNotMatch(text(face),/app:agent-session|scope-a|room-a/);
    assert.equal(face.querySelector('[data-socket-port="drives"]'),null);
    assert.equal(face.querySelector('[data-socket-port="start"]'),null);
  } finally {await ui.close();}
});

test('p8 Workshop tile drag uses membership authority with readback and undo, preserving agent identity',async()=>{
  const fx=fixture(), history=[];
  const onMemberLeave=async(id,fromGroup,position)=>{
    history.push({member:id,fromGroup,toGroup:''});
    const agent=fx.state.topology.graph.nodes.find(n=>n.id===id);
    agent.group=''; Object.assign(agent,position);
  };
  const ui=await mountWorkshopNode({...fx,onMemberLeave});
  try {
    await drag(ui);
    assert.deepEqual(history,[{member,fromGroup:'room-a',toGroup:''}]);
    const agent=fx.state.topology.graph.nodes.find(n=>n.id===member);
    assert.equal(agent.group,''); assert.equal(agent.x,320); assert.equal(agent.y,160);
    agent.group=history.pop().fromGroup;
    await ui.draw({state:fx.state});
    assert.equal(agent.group,'room-a');
    assert.equal(ui.doc.querySelector('[data-workshop-node-member]').dataset.workshopNodeMember,member);
  } finally {await ui.close();}
});

test('p8 actual main-canvas Fit measures viewport bounds and preserves stored positions at two viewports',()=>{
  const fit=fitHarness(),positions={read:{x:70,y:120},filter:{x:360,y:480},workshop:{x:920,y:30}};
  const sizes={read:{w:190,h:180},filter:{w:190,h:180},workshop:{w:320,h:170}};
  for(const viewport of [{width:1496,height:959},{width:1024,height:768}]) assertFit(fit,Object.keys(positions),positions,sizes,viewport);
});

test('p9 stored overlaps and 30 real card sizes fit two main-canvas viewports without rewriting positions',()=>{
  const fit=fitHarness(),positions={},sizes={};
  for(let i=0;i<30;i++) {positions['node-'+i]={x:i%3*80,y:Math.floor(i/3)*70}; sizes['node-'+i]={w:320,h:i===29?340:170};}
  for(const viewport of [{width:1496,height:959},{width:1024,height:768}]) assertFit(fit,Object.keys(positions),positions,sizes,viewport);
});

test('p7 pointercancel cleans up the main-canvas member drag without committing a membership action',async()=>{
  const ui=await mountWorkshopNode(fixture());
  try {
    const chip=await drag(ui,'pointercancel');
    assert.equal(ui.calls.filter(row=>row[0]==='memberLeave').length,0);
    await ui.mouse(ui.win,'pointerup',320,160);
    assert.equal(ui.calls.filter(row=>row[0]==='memberLeave').length,0);
    assert.notEqual(chip.dataset.memberDrag,'left');
  } finally {await ui.close();}
});

test('p8 pointerup outside commits exactly one same-id membership move despite duplicate mouseup',async()=>{
  const ui=await mountWorkshopNode(fixture());
  try {
    await drag(ui); await ui.mouse(ui.win,'mouseup',320,160); await ui.mouse(ui.win,'pointerup',320,160);
    assert.deepEqual(ui.calls.filter(row=>row[0]==='memberLeave'),[['memberLeave',member,'room-a',{x:320,y:160}]]);
  } finally {await ui.close();}
});
