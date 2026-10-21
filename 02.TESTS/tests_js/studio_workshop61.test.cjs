/* Four WORKSHOP-61 behavior contracts migrated to superseding DSYS-072/073. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..', '..');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
const workshop=read('01.APP/nodelang/studio/studio-workshop.jsx');
const studio=read('01.APP/nodelang/studio/studio-lm.jsx');
const surface=()=>workshop.slice(workshop.indexOf('const WorkshopView ='),workshop.indexOf('const createWorkshopMessageScroll ='));

test('WORKSHOP-61 frame contract migrates to DSYS-077 rail64 list340 thread780 with live selectors',async()=>{
  const view=surface(),{fixture}=require('./workshop72_fixture.cjs'),{mounted}=require('./workshop72_regression_helpers.cjs');
  const fx=fixture(),ui=await mounted(fx.state,fx.authority);
  try{
    const main=ui.doc.querySelector('[data-workshop72]');
    assert.equal(main.dataset.screenLabel,'5.1v3_workshop');
    assert.equal(main.firstElementChild.style.gridTemplateColumns,'64px 340px minmax(0,1fr)');
    assert.equal(main.style.gridTemplateRows,'1fr 28px');
    assert.equal(ui.doc.querySelector('[data-workshop72-thread]').style.width,'780px');
    assert.match(view,/window\.ARCHHUB_WORKSHOP_MODEL(?:\?\.)?\(\{state, descriptor/);
    assert.doesNotMatch(view,/data-workshop-s1-inspector|role="tab"|WorkshopBoardView|data-workshop-s1-canvas/);
    assert.ok(ui.doc.querySelector('textarea[aria-label="Workshop message"]'));
  }finally{await ui.close();}
});

test('WORKSHOP-61 sample-data and single-source invariant survives DSYS-077',()=>{
  for(const seeded of ['Nile_Tower','Omar','sara@firm.com','Clinic','46 doors','L3-D001','09:14','run #48']) {
    assert.equal(workshop.includes(seeded),false,'plate sample leaked: '+seeded);
  }
  assert.equal((workshop.match(/data-workshop-s1=""/g)||[]).length,1);
  assert.match(read('01.APP/nodelang/studio/shared-data.jsx'),/window\.ARCHHUB_WORKSHOP_MODEL =/);
});

test('WORKSHOP-61 action wiring migrates to the DSYS-077 controls and unavailable fallback',()=>{
  const buttons=surface().match(/<button\b[^>]*>/g)||[];
  assert.ok(buttons.length>0);
  for(const button of buttons) {
    if (/\bdisabled(?=\s|>)/.test(button)) assert.match(button,/onClick=\{/);
    else assert.match(button,/onClick=\{/);
  }
  assert.match(surface(),/onClick=\{beginTask\}/);
  assert.doesNotMatch(surface(),/createConversation|refreshConversationCatalog/);
  assert.doesNotMatch(surface(),/Ask why|Save as skill|Open as graph|to: Workshop \(everyone\)/);
});

test('WORKSHOP-61 second-face contract migrates to DSYS-073 same source and exact approval Review',()=>{
  const start=studio.indexOf('const GraphWorkshopFace =');
  const end=studio.indexOf('const NodeBody =',start);
  const face=studio.slice(start,end);
  assert.match(face,/window\.ARCHHUB_WORKSHOP_MODEL(?:\?\.)?\(/);
  assert.match(face,/data-workshop-id=\{descriptor\?\.root \|\| ''\}/);
  assert.match(face,/data-workshop-node-review/);
  assert.match(face,/archhub:reach-conversation/);
  assert.doesNotMatch(face,/sendModelConversation|<textarea|<input/);
});
