const {test} = require('node:test');
const assert = require('node:assert/strict');

const {read,transport,plain} = require('./workshop72_regression_helpers.cjs');

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
  assert.doesNotMatch(read('01.APP/nodelang/studio/studio-existing-workshop.js'),/localStorage.*(?:layout|tile)|(?:layout|tile).*localStorage/);
});
