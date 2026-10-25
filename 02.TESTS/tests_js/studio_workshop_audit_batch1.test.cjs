/* WORKSHOP-61 p3: legacy workflow/task cards were removed. These courts keep the
   behavior checks on the S1 Workshop surface: plain transcript, one approval
   card, no raw ids, no JSON dump, and live workflow run route. */
const {test} = require('node:test');
const assert = require('node:assert/strict');

const WF = 'wf-1';
const DIGEST = 'd'.repeat(64);

const {transport} = require('./workshop72_regression_helpers.cjs');

test('gap6 retained transport reports started only for the exact pending delivery projection',async()=>{
  for(const [state,word] of [['started','delivery started'],['replied','replied']]){
    const fx=transport({post:(_url,body)=>({ok:true,workshop:body.root,root:'entry-a',idempotency_key:body.idempotency_key,revision:5,
      native_delivery:[{recipient:'agent-a',state}]})});
    await fx.api.refreshWorkshop('room-a');await fx.api.sendWorkshopMessage('room-a',{target:'',message:'Review the result'});
    assert.match(fx.api.getSnapshot().workshopNotice,new RegExp(word));
    if(state==='replied')assert.doesNotMatch(fx.api.getSnapshot().workshopNotice,/delivery started/);
    assert.equal(fx.posts.length,1);
  }
});

test('projected workflow execution remains on the exact existing canvas authority route',async()=>{
  const fx=transport();await fx.api.refreshWorkshop('room-a');
  await fx.api.workshopWorkflow('room-a','workflow-execute',{workflow:WF});
  assert.equal(fx.posts.length,1);assert.equal(fx.posts[0].url,'/api/universal/workshop');
  assert.equal(fx.posts[0].body.action,'workflow-execute');assert.equal(fx.posts[0].body.workflow,WF);
  assert.equal(fx.posts[0].body.root,'room-a');assert.equal(fx.posts[0].body.scope,'scope-a');
});
test('OWNER parameter edit retains its exact governed relation and contact root after Properties removal',async()=>{
  const fx=transport();await fx.api.refreshWorkshop('room-a');await fx.api.workshopWorkflowParam('room-a','r-agent','app:wip-cell:second-agent');
  assert.deepEqual(fx.posts,[{url:'/api/universal/set-property',body:{relation:'r-agent',value:'app:wip-cell:second-agent'}}]);
});
test('changed agent parameter projection requires approval of the changed digest, never prior digest execution',async()=>{
  const changed='e'.repeat(64);let edited=false;
  const fx=transport({get:(_url,held)=>({...held,workflows:[{root:WF,digest:edited?changed:DIGEST,
    approval:{digest:DIGEST,current:!edited},nodes:[]}]}),post:(_url)=>{edited=true;return{ok:true};}});
  await fx.api.refreshWorkshop('room-a');await fx.api.workshopWorkflowParam('room-a','r-agent','app:wip-cell:second-agent');
  assert.equal(fx.api.getSnapshot().workshop.workflows[0].approval.current,false);
  await fx.api.workshopWorkflow('room-a','workflow-approve',{workflow:WF,digest:fx.api.getSnapshot().workshop.workflows[0].digest});
  assert.equal(fx.posts[1].body.digest,changed);assert.equal(fx.posts[1].body.action,'workflow-approve');
  assert.equal(fx.posts.some(post=>post.body.action==='workflow-execute'),false);
});
