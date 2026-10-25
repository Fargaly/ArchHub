const {test}=require('node:test');
const assert=require('node:assert/strict');

test('saved local revision reads the exact immutable submission and refuses a foreign decision after editor removal',async()=>{
  const {transport,plain}=require('./workshop72_regression_helpers.cjs');
  const pending={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),input_digest:'d'.repeat(64),result:'grant:project-result',resolution:'grant:project-local-resolution',
    inputs:{model:'openrouter/free',artifact_name:'pinned.patch',data_class:'public-text',files:[{path:'saved.js',content:'saved immutable text',sha256:'e'.repeat(64)}]},
    requirements:{acceptance_criteria:[{criterion:'Saved criterion',verification:'Saved verification'}]}};
  const status={ok:true,root:'room-a',scope:'scope-a',owner:'owner-a',view:'view-a',work:'work-a',artifacts_work:'work-a',artifacts:[],failures:[],
    state:'local_delivery_abandoned',mode:'project',approved:false,request_id:'attempt-a',available_work:['work-a'],worker:'worker-a',
    local_deliveries:[{work:'work-a',grant:'grant',result:pending.result,input_digest:'d'.repeat(64),worker:'worker-a',provider_outcome:'unknown',output_bytes:0,
      state:'local_delivery_abandoned',resolution:pending.resolution}],
    local_resolution:{decision:'abandon_local_delivery',provider_outcome:'unknown',grant:'grant',result:pending.result,input_digest:'d'.repeat(64),work:'work-a',worker:'worker-a',
      actor:'owner-a',view:'view-a',scope:'scope-a',claim:'claim-a',grant_revision:20,created_at:1,resolution:pending.resolution}};
  for(const foreign of [false,true]){
    const fx=transport({get:()=>status,post:(_url,body)=>({...status,request_id:body.request_id,state:'draft',draft:{title:'Keep title',description:'Keep description',
      revision:10,input_digest:pending.base_digest,inputs:pending.inputs,requirements:pending.requirements,pending_revision:{...pending,...(foreign?{resolution:'other-decision'}:{})}}})});
    await fx.api.refreshNativeWork('room-a','work-a');const operation=fx.api.nativeWorkAction('room-a','read_project','work-a');
    if(foreign)await assert.rejects(operation,/saved revision/);
    else{const draft=(await operation).draft;assert.deepEqual(plain(draft.pending_revision),pending);
      assert.equal(draft.inputs.files[0].content,'saved immutable text');assert.equal(draft.requirements.acceptance_criteria[0].criterion,'Saved criterion');assert.equal(draft.title,'Keep title');}
    assert.equal(fx.posts.length,1);assert.equal(fx.posts[0].body.action,'read_project');assert.equal(fx.posts[0].body.work,'work-a');
    assert.equal(fx.api.getSnapshot().nativeWork.draft,undefined,'source text never persists in the status projection');
  }
});
