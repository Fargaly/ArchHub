/* Isolated production-adapter callbacks; no browser, network or graph. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-existing-workshop.js'), 'utf8');
const context = vm.createContext({URLSearchParams,TextEncoder});
vm.runInContext(source, context);
const create = context.ArchHubExistingWorkshop.create;
const plain = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; };
const storage = () => {
  const data = new Map();
  return {getItem:key => data.get(key) || null, setItem:(key,value) => data.set(key,value), data};
};
const scope = (root='scope-a', rev=4) => ({graph_id:'graph-a', root, revision:rev,
  workshops:[{root:'workshop-a', label:'Workshop', send_category:'declared-message'}]});
const transcript = (root='scope-a', rev=4) => ({graph_id:'graph-a',root:'workshop-a',scope_root:root,revision:rev,
  owner:'owner-a',view:'view-a',self:'owner-a',can_send:true,can_join:false,messages:[],
  participants:[{root:'owner-a',label:'Owner',attached:true},{root:'worker-a',label:'Worker',attached:true}]});
const accepted = body => ({ok:true,workshop:body.root,root:'entry-a',idempotency_key:body.idempotency_key,revision:5});
function setup(options={}) {
  const posts=[], gets=[], pendingStorage=options.pendingStorage || storage();
  let next=0;
  const api=create({pendingStorage,uuid:options.uuid || (()=>`message-${++next}`),
    hash:async value => createHash('sha256').update(value).digest('hex'),
    get:async url => {gets.push(url);return options.get ? options.get(url) : transcript();},
    post:async (url,body) => {posts.push({url,body});return options.post ? options.post(url,body) : accepted(body);}});
  api.setCanvas(scope());
  return {api,posts,gets,pendingStorage};
}
const send = api => api.workshopAction('workshop-a','send',null,{target:'worker-a',message:'Actual task text'});

test('Everyone sends its broadcast marker and surfaces actual mixed delivery outcomes',async()=>{
  const fixture=setup({post:(_url,body)=>({...accepted(body),native_delivery:[
    {recipient:'one',state:'started'}, {recipient:'two',state:'not_sent'},
    {recipient:'three',state:'uncertain'}, {recipient:'four',state:'replied'}]})});
  await fixture.api.refreshWorkshop('workshop-a');
  await fixture.api.workshopAction('workshop-a','send',null,{target:'',message:'Work together'});
  assert.deepEqual(plain(fixture.posts[0].body.recipients),[]);
  const notice=fixture.api.getSnapshot().workshopNotice;
  for(const expected of ['1 delivery started','1 not sent','1 delivery uncertain','1 replied'])
    assert.ok(notice.includes(expected),notice);
  assert.equal(fixture.posts.length,1);
});

test('social enrollment confirms exact account without publishing credentials',async()=>{
  const input={provider:'meta',account_id:'123',vault_entry:'social-studio',token:'fake-tok-1'};
  const fixture=setup({post:()=>({...input,ok:true,state:'enrolled',account_binding:'operator-declared',
    vault_reference:'dpapi://ArchHub/social-studio',revision:5})});
  const result=await fixture.api.enrollSocialAccount(input);
  assert.equal(fixture.posts[0].url,'/api/universal/social-credential');
  assert.equal(result.vault_entry,input.vault_entry);
  assert.equal('token' in result,false);
  assert.equal(JSON.stringify(fixture.api.getSnapshot()).includes(input.token),false);
  assert.equal([...fixture.pendingStorage.data.values()].some(value=>value.includes(input.token)),false);
});

test('social credential save serializes writes and never echoes provider errors',async()=>{
  const held=deferred(), secret='fake-private-1';
  const fixture=setup({post:()=>held.promise});
  const saving=fixture.api.enrollSocialAccount({provider:'meta',account_id:'123',vault_entry:'social-studio',token:secret});
  await assert.rejects(fixture.api.saveProviderKey('openrouter','another-synthetic'),/current key save/);
  held.reject(new Error('server echoed '+secret));
  await assert.rejects(saving,error=>!error.message.includes(secret) && /could not be confirmed/.test(error.message));
});

test('social enrollment rejects a response for a different account',async()=>{
  const fixture=setup({post:()=>({ok:true,state:'enrolled',provider:'meta',account_id:'456',
    vault_entry:'social-studio',account_binding:'operator-declared',vault_reference:'dpapi://ArchHub/social-studio',revision:5})});
  await assert.rejects(fixture.api.enrollSocialAccount({provider:'meta',account_id:'123',
    vault_entry:'social-studio',token:'synthetic'}),/could not be confirmed/);
});

const repairDetails = {title:'Repair',description:'Keep the public export',criterion:'Export remains available',
  verification:'Read the patch',path:'src/example.js',content:'export const value=1;',x:100,y:200};
const repairUUID = () => 'a0000000-0000-4000-8000-000000000001';

test('native repair creation stores exact graph material and bounded runtime parameters',async()=>{
  const fixture=setup({uuid:repairUUID,post:(_url,body)=>({ok:true,created_root:'work-a',membership_wire:'wire-a',
    revision:5,workshop_root:body.workshop_root,workshop_scope:body.workshop_scope})});
  await fixture.api.createProjectWork('workshop-a',{...repairDetails,runtime:'claude',model:'sonnet'});
  const request=fixture.posts[0];
  assert.equal(request.url,'/api/universal/work');
  const input=plain(request.body.structured_references.inputs);
  assert.deepEqual(Object.keys(input).sort(),['artifact_name','data_class','files','limits','model','runtime']);
  assert.equal(input.runtime,'claude');assert.equal(input.model,'sonnet');
  assert.equal(input.files[0].content,repairDetails.content);
  assert.equal(input.files[0].sha256,createHash('sha256').update(repairDetails.content).digest('hex'));
  assert.deepEqual(input.limits,{max_turns:12,max_processes:8,max_input_bytes:262144,
    max_output_bytes:4194304,max_event_bytes:1048576,max_events:512,max_process_bytes:805306368,
    startup_timeout_seconds:60,turn_timeout_seconds:180,lifetime_seconds:600,stop_timeout_seconds:30});
  assert.deepEqual(plain(request.body.structured_references.requirements),{acceptance_criteria:[{
    criterion:repairDetails.criterion,verification:repairDetails.verification}]});
  await assert.rejects(fixture.api.createProjectWork('workshop-a',{...repairDetails,runtime:'claude',model:'--unsafe'}),/identifier/);
  assert.equal(fixture.posts.length,1);
});

test('native approval binds exact worker and digest; expiry and missing approval refuse before dispatch',async()=>{
  let status={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',mode:'agent',
    work:'work-a',artifacts_work:'work-a',state:'awaiting_approval',approved:false,request_id:'native-a',
    worker:'worker-a',input_digest:'a'.repeat(64),review_expires_at:Date.now()/1000+300};
  const fixture=setup({get:()=>status,post:(_url,body)=>{status={...status,approved:true};return status;}});
  await fixture.api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(fixture.api.nativeWorkAction('workshop-a','execute','work-a'),/Approve/);
  await assert.rejects(fixture.api.approveNativeWork('workshop-a','b'.repeat(64)),/exact current/);
  assert.equal(fixture.posts.length,0);
  await fixture.api.approveNativeWork('workshop-a',status.input_digest);
  assert.deepEqual(plain(fixture.posts[0].body),{action:'approve_native',root:'workshop-a',scope:'scope-a',
    work:'work-a',request_id:'native-a',data_class:'public-text',input_digest:'a'.repeat(64)});
  status={...status,review_expired:true};await fixture.api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(fixture.api.nativeWorkAction('workshop-a','execute','work-a'),/Approve/);
  assert.equal(fixture.posts.length,1);
});

test('native response loss reads status once without replay and stop keeps exact operation identity',async()=>{
  let status={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',state:'idle',
    artifacts_work:'work-a',selected_work_mode:'agent'};
  const fixture=setup({get:()=>status,post:(_url,body)=>{
    status={...status,mode:'agent',work:body.work,request_id:body.request_id,state:'uncertain'};
    if(body.action==='prepare_native') throw new Error('reply lost');
    return {...status,state:'native_stopped'};
  }});
  await fixture.api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(fixture.api.nativeWorkAction('workshop-a','prepare_native','work-a'),/reply lost/);
  assert.equal(fixture.posts.length,1);assert.equal(fixture.gets.length,2);
  await fixture.api.nativeWorkAction('workshop-a','stop_native','work-a');
  assert.equal(fixture.posts[1].body.request_id,fixture.posts[0].body.request_id);
  assert.equal(fixture.posts[1].body.action,'stop_native');
});

test('saved native artifact download verifies mode, bytes and digest without execution',async()=>{
  const content='--- a/x\n+++ b/x\n';
  const artifact={mode:'agent',work:'work-a',outcome:'succeeded',name:'native.patch',bytes:Buffer.byteLength(content),
    digest:createHash('sha256').update(content).digest('hex'),result:'native-result',receipt:'native-receipt'};
  const status={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',state:'idle',
    artifacts_work:'work-a',artifacts:[artifact]};
  let responseMode='agent';
  const fixture=setup({get:()=>status,post:(_url,body)=>({...status,work:body.work,request_id:body.request_id,
    mode:responseMode,artifact,artifact_text:content})});
  await fixture.api.refreshNativeWork('workshop-a','work-a');
  const selectors={result:artifact.result,receipt:artifact.receipt};
  assert.equal((await fixture.api.nativeWorkAction('workshop-a','read_artifact','work-a',selectors)).artifact_text,content);
  responseMode='project';
  await assert.rejects(fixture.api.nativeWorkAction('workshop-a','read_artifact','work-a',selectors),/verified/);
  assert.deepEqual(fixture.posts.map(row=>row.body.action),['read_artifact','read_artifact']);
});

test('concurrent native stop reaches transport and a delayed stop reply cannot replace settled status',async()=>{
  const execute=deferred(),stop=deferred();
  let status={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',mode:'agent',
    work:'work-a',artifacts_work:'work-a',request_id:'native-a',state:'awaiting_approval',approved:true,
    worker:'worker-a',input_digest:'a'.repeat(64)};
  const fixture=setup({get:()=>status,post:(_url,body)=>body.action==='execute'?execute.promise:stop.promise});
  await fixture.api.refreshNativeWork('workshop-a','work-a');
  const observed=[];fixture.api.subscribe(()=>observed.push(fixture.api.getSnapshot().nativeWork?.state));
  const running=fixture.api.nativeWorkAction('workshop-a','execute','work-a');
  const stopping=fixture.api.nativeWorkAction('workshop-a','stop_native','work-a');
  assert.deepEqual(fixture.posts.map(row=>row.body.action),['execute','stop_native']);
  const oldStop={...status,state:'executing',stop_requested:true};
  status={...status,state:'settled',receipt:'real-receipt'};execute.resolve(status);await running;
  stop.resolve(oldStop);await stopping;
  assert.equal(fixture.api.getSnapshot().nativeWork.state,'settled');
  const settled=observed.indexOf('settled');assert.ok(settled>=0);
  assert.equal(observed.slice(settled).includes('executing'),false);
  assert.equal(fixture.posts.length,2);
});

test('native release requires exact confirmed cancellation, never stopped or uncertain state',async()=>{
  const cancellation={state:'cancelled',releasable:true,work:'work-a',worker:'worker-a',
    assignment:'assignment-a',cancellation:'assignment-a:native-cancellation',
    session_close_receipt:'close-receipt-a',revision:42};
  const base={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',mode:'agent',
    state:'native_cancelled',work:'work-a',worker:'worker-a',request_id:'native-a',artifacts_work:'work-a',
    native_cancellation:cancellation};
  for(const change of [{state:'native_stopped'},{state:'uncertain'},
    ...[{work:'other-work'},{worker:'other-worker'},{releasable:false},{assignment:''},
      {cancellation:'foreign-cancellation'},{session_close_receipt:''},{revision:-1}]
      .map(value=>({native_cancellation:{...cancellation,...value}}))]) {
    const fixture=setup({get:()=>({...base,...change})});
    await fixture.api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(fixture.api.nativeWorkAction('workshop-a','release','work-a'),/Confirm this native failure or cancellation/);
    assert.equal(fixture.posts.length,0);
  }
  const fixture=setup({get:()=>base,post:(_url,body)=>({ok:true,state:'released',released:true,
    root:body.root,scope:body.scope,work:body.work,request_id:body.request_id,owner:'owner-a',view:'view-a'})});
  await fixture.api.refreshNativeWork('workshop-a','work-a');
  await fixture.api.nativeWorkAction('workshop-a','release','work-a');
  assert.deepEqual(plain(fixture.posts[0].body),{action:'release',root:'workshop-a',scope:'scope-a',
    work:'work-a',request_id:'native-a',data_class:'public-text'});
  assert.equal(fixture.posts.length,1); // No delegation, digest, renewal or prepare operation.
});

const failedNative = () => ({ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',mode:'agent',
  state:'settled',work:'work-a',worker:'worker-a',request_id:'native-failed-a',artifacts_work:'work-a',artifact:null,
  native_result:{state:'settled',outcome:'failed',work:'work-a',grant:'grant-a',
    result:'grant-a:native-result',receipt:'grant-a:native-receipt',revision:42,
    error_code:'native_output_invalid',output_bytes:0}});
const releasedNative = body => ({ok:true,state:'released',released:true,root:body.root,scope:body.scope,
  work:body.work,request_id:body.request_id,owner:'owner-a',view:'view-a'});

test('native failed result closes only its exact settled operation',async()=>{
  for(const change of [{state:'uncertain'},{state:'native_stopped'},
    ...[{state:'pending'},{outcome:'uncertain'},{work:'other-work'},{grant:''},
      {receipt:'foreign-receipt'},{result:'foreign-result'},{revision:-1}]
      .map(value=>({native_result:{...failedNative().native_result,...value}}))]) {
    const fixture=setup({get:()=>({...failedNative(),...change})});
    await fixture.api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(fixture.api.nativeWorkAction('workshop-a','release','work-a'),
      /Confirm this native failure or cancellation/);
    assert.equal(fixture.posts.length,0);
    assert.equal(fixture.pendingStorage.getItem('archhub.existing-workshop.releases.v1'),null);
  }
  const fixture=setup({get:failedNative,post:(_url,body)=>releasedNative(body)});
  await fixture.api.refreshNativeWork('workshop-a','work-a');
  const result=await fixture.api.nativeWorkAction('workshop-a','release','work-a');
  assert.equal(result.released,true);
  assert.deepEqual(plain(fixture.posts),[{url:'/api/universal/workshop-native',body:{action:'release',
    root:'workshop-a',scope:'scope-a',work:'work-a',request_id:'native-failed-a',data_class:'public-text'}}]);
  assert.equal(fixture.pendingStorage.getItem('archhub.existing-workshop.releases.v1'),'{}');
  // No publication, artifact writer, prepare, approval or model execution request.
});

test('native failed close preserves exact request across lost response and explicit reconciliation',async()=>{
  const pendingStorage=storage();let status=failedNative();
  const idle={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',state:'idle',artifacts_work:'work-a'};
  const first=setup({pendingStorage,get:()=>status,post:()=>{
    status=idle;throw new Error('native close response lost');
  }});
  await first.api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(first.api.nativeWorkAction('workshop-a','release','work-a'),/response lost/);
  assert.equal(first.posts.length,1);assert.equal(first.gets.length,2);
  assert.equal(first.api.getSnapshot().nativeWork.state,'release_pending');
  const originalBody=plain(first.posts[0].body);
  const saved=JSON.parse(pendingStorage.getItem('archhub.existing-workshop.releases.v1'));
  assert.equal(Object.values(saved).length,1);
  assert.equal(Object.values(saved)[0].request_id,'native-failed-a');
  assert.equal(Object.values(saved)[0].work,'work-a');
  const successor=setup({pendingStorage,get:()=>idle,post:(_url,body)=>releasedNative(body)});
  await successor.api.refreshNativeWork('workshop-a','work-a');
  assert.equal(successor.api.getSnapshot().nativeWork.state,'release_pending');
  assert.equal(successor.posts.length,0); // Reading/reloading never repeats the close.
  const released=await successor.api.nativeWorkAction('workshop-a','release');
  assert.equal(released.released,true);
  assert.deepEqual(plain(successor.posts[0].body),originalBody);
  assert.equal(successor.posts.length,1);
  assert.equal(pendingStorage.getItem('archhub.existing-workshop.releases.v1'),'{}');
});

test('native pending close rejects foreign reply owner after idle status loses mode',async()=>{
  for(const foreign of [{owner:'foreign-owner'},{view:'foreign-view'}]) {
    const pendingStorage=storage();let status=failedNative();
    const idle={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',state:'idle',artifacts_work:'work-a'};
    const first=setup({pendingStorage,get:()=>status,post:()=>{
      status=idle;throw new Error('native close response lost');
    }});
    await first.api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(first.api.nativeWorkAction('workshop-a','release'),/response lost/);
    const saved=pendingStorage.getItem('archhub.existing-workshop.releases.v1');
    const successor=setup({pendingStorage,get:()=>idle,
      post:(_url,body)=>({...releasedNative(body),...foreign})});
    await successor.api.refreshNativeWork('workshop-a','work-a');
    assert.equal(successor.api.getSnapshot().nativeWork.mode,undefined);
    await assert.rejects(successor.api.nativeWorkAction('workshop-a','release'),/needs reconciliation/);
    assert.equal(successor.posts.length,1);
    assert.deepEqual(plain(successor.posts[0].body),plain(first.posts[0].body));
    assert.equal(pendingStorage.getItem('archhub.existing-workshop.releases.v1'),saved);
    assert.equal(successor.api.getSnapshot().nativeWork.state,'release_pending');
  }
});

const publishedProject = () => ({ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',
  work:'work-a',artifacts_work:'work-a',artifacts:[],failures:[],state:'published',mode:'project',request_id:'attempt-a'});
const projectDraft = () => ({title:'Repair',description:'Keep the public export',revision:10,input_digest:'a'.repeat(64),
  inputs:{data_class:'public-text',model:'openrouter/free',artifact_name:'old.patch',
    files:[{path:'example.js',content:'export const value=1;',sha256:'b'.repeat(64)}]},
  requirements:{acceptance_criteria:[{criterion:'Keep export',verification:'Read patch'}]}});

const unreceivedDelivery = () => ({work:'work-a',grant:'grant-a',result:'grant-a:project-result',
  input_digest:'d'.repeat(64),worker:'worker-a',provider_outcome:'unknown',output_bytes:0,
  state:'unreceived',resolution:null});
const unresolvedProject = () => ({...publishedProject(),state:'uncertain',worker:'worker-a',approved:false,
  local_deliveries:[unreceivedDelivery()],artifact:null});
const abandonmentDetails = () => ({grant:'grant-a',result:'grant-a:project-result',input_digest:'d'.repeat(64)});
const abandonedProject = requestId => ({...unresolvedProject(),state:'local_delivery_abandoned',
  request_id:requestId,local_deliveries:[{...unreceivedDelivery(),state:'local_delivery_abandoned',
    resolution:'grant-a:project-local-resolution'}],local_resolution:{
    decision:'abandon_local_delivery',provider_outcome:'unknown',...abandonmentDetails(),
    work:'work-a',worker:'worker-a',actor:'owner-a',view:'view-a',scope:'scope-a',
    claim:'claim-a',grant_revision:20,created_at:1,resolution:'grant-a:project-local-resolution'}});

const expiredProjectReview = () => ({...publishedProject(),state:'awaiting_approval',approved:false,
  worker:'worker-a',delegation:'delegation-old',input_digest:'a'.repeat(64),model:'openrouter/free',
  review_text:'Exact public input',artifact_name:'review.patch',review_expires_at:1,review_expired:true});
const refreshedProjectReview = () => ({...expiredProjectReview(),delegation:'delegation-new',
  review_expires_at:Date.now()/1000+300,review_expired:false,
  review_refresh:{delegation:'delegation-old',input_digest:'a'.repeat(64),request_id:'attempt-a'}});
const refreshReviewDetails = () => ({delegation:'delegation-old',input_digest:'a'.repeat(64)});

test('expired project review refresh retains operation and worker, requires fresh approval and never executes',async()=>{
  let status=expiredProjectReview();
  const {api,posts}=setup({get:()=>status,post:()=>{status=refreshedProjectReview();return status;}});
  await api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(api.approveNativeWork('workshop-a',status.input_digest),/before approving/);
  assert.equal(posts.length,0);
  const result=await api.nativeWorkAction('workshop-a','refresh_project_review','work-a',refreshReviewDetails());
  assert.deepEqual(plain(posts[0].body),{action:'refresh_project_review',root:'workshop-a',scope:'scope-a',
    work:'work-a',request_id:'attempt-a',data_class:'public-text',...refreshReviewDetails()});
  assert.equal(posts.length,1);assert.equal(result.worker,'worker-a');assert.equal(result.approved,false);
  assert.equal(result.delegation,'delegation-new');assert.equal(result.input_digest,'a'.repeat(64));
  await assert.rejects(api.nativeWorkAction('workshop-a','execute','work-a'),/Approve/);
  await assert.rejects(api.nativeWorkAction('workshop-a','refresh_project_review','work-a',refreshReviewDetails()),/expired/);
  assert.equal(posts.length,1);
});

test('refresh refuses unexpired, approved or changed selectors before dispatch',async()=>{
  for(const change of [{review_expired:false,review_expires_at:Date.now()/1000+300},{approved:true},{worker:''},
      {state:'uncertain'},{revision_pending:'saved-draft'}]) {
    const {api,posts}=setup({get:()=>({...expiredProjectReview(),...change})});
    await api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(api.nativeWorkAction('workshop-a','refresh_project_review','work-a',refreshReviewDetails()),/expired/);
    assert.equal(posts.length,0);
  }
  const {api,posts}=setup({get:expiredProjectReview});
  await api.refreshNativeWork('workshop-a','work-a');
  for(const details of [{delegation:'foreign'},{input_digest:'b'.repeat(64)}]) {
    await assert.rejects(api.nativeWorkAction('workshop-a','refresh_project_review','work-a',
      {...refreshReviewDetails(),...details}),/expired/);
  }
  assert.equal(posts.length,0);
});

test('lost refresh response performs only a status read and cannot replay from uncertainty',async()=>{
  let status=expiredProjectReview();
  const {api,posts,gets}=setup({get:()=>status,post:()=>{
    status={...status,state:'uncertain',review_refresh:refreshedProjectReview().review_refresh};
    throw new Error('refresh reply lost');
  }});
  await api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(api.nativeWorkAction('workshop-a','refresh_project_review','work-a',refreshReviewDetails()),/reply lost/);
  assert.equal(gets.length,2);assert.equal(posts.length,1);
  assert.equal(api.getSnapshot().nativeWork.state,'uncertain');
  await assert.rejects(api.nativeWorkAction('workshop-a','refresh_project_review','work-a',refreshReviewDetails()),/expired/);
  assert.equal(posts.length,1);
});

test('refresh rejects foreign worker, material or refresh provenance in a successful reply',async()=>{
  for(const change of [{owner:'foreign'},{view:'foreign'},{worker:'foreign'},{delegation:'delegation-old'},
      {input_digest:'b'.repeat(64)},{review_text:'changed'},{artifact_name:'changed.patch'},
      {approved:true},{review_refresh:null},{review_expires_at:1}]) {
    const {api,posts}=setup({get:expiredProjectReview,post:()=>({...refreshedProjectReview(),...change})});
    await api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(api.nativeWorkAction('workshop-a','refresh_project_review','work-a',refreshReviewDetails()));
    assert.equal(posts.length,1);
  }
});

test('local delivery abandonment submits only the exact selected attempt and creates no execution receipt or artifact',async()=>{
  for(const state of ['uncertain','idle']) {
    let status={...unresolvedProject(),state,...(state==='idle'?{request_id:undefined}: {})};
    const {api,posts,gets}=setup({get:()=>status,post:(url,body)=>{
      assert.equal(url,'/api/universal/workshop-native');
      status=abandonedProject(body.request_id);return status;
    }});
    await api.refreshNativeWork('workshop-a','work-a');
    const result=await api.nativeWorkAction('workshop-a','abandon_project','work-a',abandonmentDetails());
    assert.equal(posts.length,1);
    assert.deepEqual(plain(posts[0].body),{action:'abandon_project',root:'workshop-a',scope:'scope-a',
      work:'work-a',request_id:state==='idle'?'message-1':'attempt-a',data_class:'public-text',...abandonmentDetails()});
    assert.equal(result.state,'local_delivery_abandoned');
    assert.equal(result.local_resolution.provider_outcome,'unknown');
    assert.equal(result.artifact,null);assert.equal(result.receipt,undefined);
    assert.deepEqual(plain(result.artifacts),[]);assert.deepEqual(plain(result.failures),[]);
    assert.equal(result.approved,false);assert.equal(gets.length,2);
    assert.equal(api.getSnapshot().nativeWork.state,'local_delivery_abandoned');
    assert.deepEqual(posts.map(row=>row.body.action),['abandon_project']);
  }
});

test('abandonment refuses a changed or ambiguous unreceived selection before any POST',async()=>{
  const cases=[
    {details:{grant:'another-grant'}},{details:{result:'another-result'}},
    {details:{input_digest:'e'.repeat(64)}},{work:'another-work'},
    {delivery:{provider_outcome:'failed'}},{delivery:{output_bytes:1}},
    {delivery:{work:'another-work'}},{duplicate:true},
  ];
  for(const item of cases) {
    const delivery={...unreceivedDelivery(),...item.delivery};
    const {api,posts}=setup({get:()=>({...unresolvedProject(),local_deliveries:item.duplicate?
      [delivery,delivery]:[delivery]})});
    if(item.delivery || item.duplicate) {
      await assert.rejects(api.refreshNativeWork('workshop-a','work-a'),/metadata/);
    } else {
      await api.refreshNativeWork('workshop-a','work-a');
      await assert.rejects(api.nativeWorkAction('workshop-a','abandon_project',item.work||'work-a',
        {...abandonmentDetails(),...item.details}),/exact unreceived/);
    }
    assert.equal(posts.length,0);
  }
});

test('lost abandonment response triggers one GET and never replays the action or runs a provider',async()=>{
  let status=unresolvedProject();
  const {api,posts,gets}=setup({get:()=>status,post:(_url,body)=>{
    status=abandonedProject(body.request_id);throw new Error('abandonment response lost');
  }});
  await api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(api.nativeWorkAction('workshop-a','abandon_project','work-a',abandonmentDetails()),/response lost/);
  assert.equal(posts.length,1);assert.equal(gets.length,2);
  assert.deepEqual(posts.map(row=>row.body.action),['abandon_project']);
  assert.match(gets[1],/^\/api\/universal\/workshop-native\?/);
  const observed=api.getSnapshot().nativeWork;
  assert.equal(observed.state,'local_delivery_abandoned');
  assert.equal(observed.local_resolution.provider_outcome,'unknown');
  assert.equal(observed.artifact,null);assert.equal(observed.receipt,undefined);
});

test('foreign or mismatched abandonment resolution replies cannot be accepted as closure',async()=>{
  const cases=[
    {resolution:{grant:'another-grant'}},{resolution:{result:'another-result'}},
    {resolution:{input_digest:'e'.repeat(64)}},{resolution:{work:'another-work'}},
    {resolution:{actor:'foreign-owner'}},{resolution:{view:'foreign-view'}},
    {resolution:{scope:'foreign-scope'}},{resolution:{provider_outcome:'failed'}},
    {resolution:{decision:'retry_provider'}},{resolution:{resolution:null}},
    {resolution:{resolution:'another-resolution'}},
    {outer:{owner:'foreign-owner'}},{outer:{view:'foreign-view'}},
    {outer:{scope:'foreign-scope'}},{outer:{request_id:'other-attempt'}},
    {outer:{state:'settled'}},
  ];
  for(const item of cases) {
    const {api,posts}=setup({get:unresolvedProject,post:(_url,body)=>{
      const reply=abandonedProject(body.request_id);
      return {...reply,...item.outer,local_resolution:{...reply.local_resolution,...item.resolution}};
    }});
    await api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(api.nativeWorkAction('workshop-a','abandon_project','work-a',abandonmentDetails()),/reconciliation/);
    assert.deepEqual(posts.map(row=>row.body.action),['abandon_project']);
    assert.equal(api.getSnapshot().nativeWork.state,'uncertain');
  }
});

test('an abandonment reply from the previous canvas scope is rejected without replay',async()=>{
  const reply=deferred();
  const {api,posts,gets}=setup({get:unresolvedProject,post:()=>reply.promise});
  await api.refreshNativeWork('workshop-a','work-a');
  const pending=api.nativeWorkAction('workshop-a','abandon_project','work-a',abandonmentDetails());
  assert.equal(posts.length,1);
  api.setCanvas(scope('scope-b',5));
  reply.resolve(abandonedProject('attempt-a'));
  await assert.rejects(pending,/changed|reconciliation/);
  assert.equal(posts.length,1);assert.equal(gets.length,1);
});

test('local recovery selects its saved decision and prepares fresh approval without execution',async()=>{
  let status=abandonedProject('attempt-a');
  const {api,posts}=setup({get:()=>status,post:(_url,body)=>{
    status={...status,state:'awaiting_approval',request_id:body.request_id,approved:false,
      worker:'fresh-worker',delegation:'fresh-delegation',input_digest:'c'.repeat(64),
      recovery_kind:'local_delivery',recovery:{provider_outcome:'unknown'},
      recovery_request:{result:body.result,resolution:body.resolution,work:body.work,request_id:body.request_id}};
    return status;
  }});
  await api.refreshNativeWork('workshop-a','work-a');
  const details={result:unreceivedDelivery().result,resolution:'grant-a:project-local-resolution'};
  const prepared=await api.nativeWorkAction('workshop-a','recover_local_project','work-a',details);
  assert.equal(prepared.state,'awaiting_approval');assert.equal(prepared.approved,false);
  assert.equal(posts.length,1);assert.equal(posts[0].body.action,'recover_local_project');
  assert.equal(posts[0].body.result,details.result);assert.equal(posts[0].body.resolution,details.resolution);
  assert.equal(posts[0].body.receipt,undefined);assert.equal(posts[0].body.input_digest,undefined);
  const missing=setup({get:unresolvedProject});
  await missing.api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(missing.api.nativeWorkAction('workshop-a','recover_local_project','work-a',details),/saved local-delivery/);
  assert.equal(missing.posts.length,0);
});

test('local recovery rejects another owner or decision and never treats preparation as approval',async()=>{
  for(const change of [
    {owner:'another-owner'}, {view:'another-view'}, {recovery_kind:'failed_project'},
    {recovery:{provider_outcome:'failed'}}, {recovery_request:{result:'other-result'}}, {approved:true},
  ]) {
    const {api,posts}=setup({get:()=>abandonedProject('attempt-a'),post:(_url,body)=>({
      ...abandonedProject(body.request_id),state:'awaiting_approval',approved:false,
      recovery_kind:'local_delivery',recovery:{provider_outcome:'unknown'},
      recovery_request:{result:body.result,resolution:body.resolution,work:body.work,request_id:body.request_id},...change})});
    await api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(api.nativeWorkAction('workshop-a','recover_local_project','work-a',{
      result:'grant-a:project-result',resolution:'grant-a:project-local-resolution'}),/reconciliation/);
    assert.equal(posts.length,1);assert.equal(posts[0].body.action,'recover_local_project');
  }
});

test('lost local release reply survives owner and adapter restart through exact durable selectors',async()=>{
  const pendingStorage=storage();let status=abandonedProject('attempt-a');
  const first=setup({pendingStorage,get:()=>status,post:()=>{
    status={...abandonedProject('attempt-a'),state:'idle',request_id:undefined};
    throw new Error('release reply lost');
  }});
  await first.api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(first.api.nativeWorkAction('workshop-a','release'),/reply lost/);
  assert.equal(first.api.getSnapshot().nativeWork.state,'release_pending');
  const pending=JSON.parse(pendingStorage.getItem('archhub.existing-workshop.releases.v1'));
  assert.equal(Object.values(pending)[0].resolution,'grant-a:project-local-resolution');
  const successor=setup({pendingStorage,get:()=>status,post:(_url,body)=>({
    ok:true,root:body.root,scope:body.scope,work:body.work,request_id:body.request_id,
    owner:'owner-a',view:'view-a',state:'released',released:true,result:body.result,resolution:body.resolution})});
  await successor.api.refreshNativeWork('workshop-a','work-a');
  assert.equal(successor.api.getSnapshot().nativeWork.state,'release_pending');
  const released=await successor.api.nativeWorkAction('workshop-a','release');
  assert.equal(released.resolution,'grant-a:project-local-resolution');
  assert.equal(successor.posts.length,1);assert.equal(successor.posts[0].body.action,'release');
  assert.equal(successor.posts[0].body.result,'grant-a:project-result');
  assert.equal(pendingStorage.getItem('archhub.existing-workshop.releases.v1'),'{}');
});

test('a status read started before an action cannot replace that action input',async()=>{
  const older=deferred(), response=deferred(); let reads=0;
  const {api,posts}=setup({get:()=>++reads===2?older.promise:publishedProject(),
    post:()=>response.promise});
  await api.refreshNativeWork('workshop-a','work-a');
  const pending=api.refreshNativeWork('workshop-a','work-a');
  const action=api.nativeWorkAction('workshop-a','read_project','work-a');
  older.resolve({...publishedProject(),request_id:'obsolete-attempt'});
  assert.equal(await pending,null);
  assert.equal(api.getSnapshot().nativeWork.request_id,'attempt-a');
  response.resolve({...publishedProject(),request_id:posts[0].body.request_id,state:'draft',draft:projectDraft()});
  assert.equal((await action).draft.input_digest,'a'.repeat(64));
  assert.equal(posts.length,1);
});

test('saved review recovery binds the exact artifact and retains one request across response loss',async()=>{
  const artifact={work:'work-a',result:'result-a',receipt:'receipt-a',name:'old.patch',digest:'a'.repeat(64),
    bytes:10,outcome:'succeeded'};
  let failed=true;
  const {api,posts}=setup({get:()=>({...publishedProject(),state:'idle',request_id:undefined,artifacts:[artifact]}),
    post:(_url,body)=>{if(failed) throw new Error('reply lost');return {...publishedProject(),request_id:body.request_id};}});
  await api.refreshNativeWork('workshop-a','work-a');
  const resume=()=>api.nativeWorkAction('workshop-a','recover_review','work-a',{result:'result-a',receipt:'receipt-a'});
  await assert.rejects(resume(),/reply lost/);
  assert.equal(posts.length,1);failed=false;
  await resume();
  assert.equal(posts.length,2);
  assert.equal(posts[0].body.request_id,posts[1].body.request_id);
  assert.deepEqual(posts.map(row=>row.body.action),['recover_review','recover_review']);
  await assert.rejects(api.nativeWorkAction('workshop-a','recover_review','work-a',{
    result:'different-result',receipt:'receipt-a'}),/exact|saved patch/);
  assert.equal(posts.length,2);
});

test('revision editor reads selected graph inputs without replacing operation metadata or persisting source',async()=>{
  const {api,posts,pendingStorage}=setup({get:publishedProject,post:(_url,body)=>({
    ...publishedProject(),request_id:body.request_id,state:'draft',draft:projectDraft()})});
  await api.refreshNativeWork('workshop-a','work-a');
  const read=await api.nativeWorkAction('workshop-a','read_project','work-a');
  assert.equal(read.draft.inputs.files[0].content,'export const value=1;');
  assert.equal(posts.length,1);assert.equal(posts[0].body.action,'read_project');
  assert.equal(api.getSnapshot().nativeWork.state,'published');
  assert.equal(api.getSnapshot().nativeWork.draft,undefined);
  assert.equal(pendingStorage.data.size,0);
});

test('same-Work revision submits structured values once and checks the exact revision receipt',async()=>{
  const draft={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),
    inputs:projectDraft().inputs,requirements:projectDraft().requirements};
  const {api,posts}=setup({get:publishedProject,post:(_url,body)=>({...publishedProject(),
    work_revision:{revision_id:body.draft.revision_id,applied:true,input_digest:'d'.repeat(64),current_input_digest:'d'.repeat(64)}})});
  await api.refreshNativeWork('workshop-a','work-a');
  const result=await api.nativeWorkAction('workshop-a','revise_project','work-a',{draft});
  assert.equal(result.work_revision.applied,true);
  assert.equal(posts.length,1);assert.deepEqual(plain(posts[0].body.draft),draft);
  assert.equal(posts[0].body.work,'work-a');assert.equal(posts[0].body.request_id,'attempt-a');
});
test('historical revision receipt retains the current digest and malformed current identity refuses',async()=>{
  const draft={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),
    inputs:projectDraft().inputs,requirements:projectDraft().requirements};
  for(const digest of ['e'.repeat(64),undefined]) {
    const {api}=setup({get:publishedProject,post:()=>({...publishedProject(),
      work_revision:{revision_id:draft.revision_id,applied:true,input_digest:'d'.repeat(64),
        current_input_digest:digest}})});
    await api.refreshNativeWork('workshop-a','work-a');
    const result=api.nativeWorkAction('workshop-a','revise_project','work-a',{draft});
    if(digest) assert.equal((await result).work_revision.current_input_digest,digest);
    else await assert.rejects(result,error=>/reconciliation/.test(error.message) && error.revisionRejectedNoWrite!==true);
  }
});

test('revision response loss reads status without replaying the mutation or executing a model',async()=>{
  const {api,posts}=setup({get:publishedProject,post:()=>{throw new Error('response lost');}});
  await api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(api.nativeWorkAction('workshop-a','revise_project','work-a',{
    draft:{revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),
      inputs:projectDraft().inputs,requirements:projectDraft().requirements}}),error=>
        /response lost/.test(error.message) && error.revisionRejectedNoWrite !== true);
  assert.equal(posts.length,1);assert.equal(posts[0].body.action,'revise_project');
});
test('revision unlock requires exact completed no-write refusal, never a staged or mismatched response',async()=>{
  const draft={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),
    inputs:projectDraft().inputs,requirements:projectDraft().requirements};
  for(const change of [{},{staged:true},{confirmed:false},{revision_id:'e'.repeat(32)},
      {owner:'another-owner'}]) {
    const {owner,...rejection}=change;
    const {api,posts}=setup({get:publishedProject,post:()=>({...publishedProject(),
      ...(owner?{owner}:{}),revision_rejection:{revision_id:draft.revision_id,
        staged:false,confirmed:true,...rejection}})});
    await api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(api.nativeWorkAction('workshop-a','revise_project','work-a',{draft}),error=>
      (error.revisionRejectedNoWrite===true) === (Object.keys(change).length===0));
    assert.equal(posts.length,1);
  }
});
test('revision local preflight refusal permits correcting fields without issuing a request',async()=>{
  const {api,posts}=setup({get:publishedProject});
  await api.refreshNativeWork('workshop-a','work-a');
  await assert.rejects(api.nativeWorkAction('workshop-a','revise_project','different-work',{
    draft:{revision_id:'c'.repeat(32),base_digest:'a'.repeat(64)}}),error=>error.revisionRejectedNoWrite===true);
  assert.equal(posts.length,0);
});

test('local closed-result revision preserves exact decision and uses fresh approval semantics from active or idle',async()=>{
  for(const idle of [false,true]) {
    let status=abandonedProject('attempt-a');
    if(idle) status={...status,state:'idle',request_id:undefined,local_resolution:undefined};
    const draft={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),
      inputs:projectDraft().inputs,requirements:projectDraft().requirements};
    const details={draft,result:'grant-a:project-result',resolution:'grant-a:project-local-resolution'};
    const {api,posts}=setup({get:()=>status,post:(_url,body)=>{
      status={...abandonedProject(body.request_id),work_revision:{applied:true,
        revision_id:draft.revision_id,input_digest:'e'.repeat(64),current_input_digest:'e'.repeat(64)}};
      return status;
    }});
    await api.refreshNativeWork('workshop-a','work-a');
    const result=await api.nativeWorkAction('workshop-a','revise_project','work-a',details);
    assert.equal(result.state,'local_delivery_abandoned');assert.equal(result.approved,false);
    assert.equal(result.local_resolution.provider_outcome,'unknown');
    assert.equal(result.local_resolution.input_digest,'d'.repeat(64));
    assert.equal(result.receipt,undefined);assert.equal(result.artifact,null);
    assert.equal(posts.length,1);
    assert.equal(posts[0].body.result,details.result);assert.equal(posts[0].body.resolution,details.resolution);
    assert.deepEqual(plain(posts[0].body.draft),draft);
    assert.equal(posts[0].body.request_id,idle?'local-revision-'+draft.revision_id:'attempt-a');
  }
});

test('local revision rejects foreign decisions and response loss reads once without replay',async()=>{
  const draft={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),
    inputs:projectDraft().inputs,requirements:projectDraft().requirements};
  const details={draft,result:'grant-a:project-result',resolution:'grant-a:project-local-resolution'};
  for(const corrupt of ['owner','claim','resolution','state','approved','loss']) {
    const {api,posts,gets}=setup({get:()=>abandonedProject('attempt-a'),post:()=>{
      if(corrupt==='loss') throw Error('response lost');
      const result={...abandonedProject('attempt-a'),work_revision:{applied:true,
        revision_id:draft.revision_id,input_digest:'e'.repeat(64),current_input_digest:'e'.repeat(64)}};
      if(corrupt==='owner') result.owner='foreign';
      else if(corrupt==='claim') result.local_resolution.claim='foreign';
      else if(corrupt==='resolution') result.local_resolution.resolution='foreign';
      else if(corrupt==='state') result.state='published';
      else result.approved=true;
      return result;
    }});
    await api.refreshNativeWork('workshop-a','work-a');
    await assert.rejects(api.nativeWorkAction('workshop-a','revise_project','work-a',details),
      error=>error.revisionRejectedNoWrite!==true);
    assert.equal(posts.length,1);assert.equal(gets.length,2);
  }
});

test('read draft returns exact saved local revision and refuses another decision',async()=>{
  const pending={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),input_digest:'e'.repeat(64),
    inputs:{...projectDraft().inputs,artifact_name:'immutable.patch'},requirements:projectDraft().requirements,
    result:'grant-a:project-result',resolution:'grant-a:project-local-resolution'};
  for(const foreign of [false,true]) {
    const {api,posts,pendingStorage}=setup({get:()=>abandonedProject('attempt-a'),post:(_url,body)=>({
      ...publishedProject(),request_id:body.request_id,state:'draft',
      draft:{...projectDraft(),pending_revision:{...pending,...(foreign?{resolution:'other'}:{})}}})});
    await api.refreshNativeWork('workshop-a','work-a');
    const operation=api.nativeWorkAction('workshop-a','read_project','work-a');
    if(foreign) await assert.rejects(operation,/saved revision/);
    else assert.deepEqual(plain((await operation).draft.pending_revision),pending);
    assert.equal(posts.length,1);assert.equal(pendingStorage.data.size,0);
  }
});

test('pending revision blocks preparation and release before writes',async()=>{
  const {api,posts}=setup({get:()=>({...abandonedProject('attempt-a'),revision_pending:'c'.repeat(32)})});
  await api.refreshNativeWork('workshop-a','work-a');
  for(const action of ['prepare','prepare_project','recover_local_project','release']) {
    await assert.rejects(api.nativeWorkAction('workshop-a',action,'work-a'),/saved Work revision/);
  }
  assert.equal(posts.length,0);
});
test('Work creation uses refreshed conversation scope and checks its returned link',async()=>{
  const fixture=setup({uuid:repairUUID,get:()=>transcript('scope-a',12),post:(url,body)=>{
    assert.equal(url,'/api/universal/work');
    assert.equal(body.workshop_root,'workshop-a');assert.equal(body.workshop_scope,'scope-a');
    assert.equal(body.revision,12);assert.equal(body.projection,false);
    return {ok:true,created_root:'work-a',membership_wire:'wire-a',revision:13,
      workshop_root:body.workshop_root,workshop_scope:body.workshop_scope};
  }});
  const result=await fixture.api.createProjectWork('workshop-a',repairDetails);
  assert.equal(result.accepted,true);assert.equal(result.original_workshop,'workshop-a');
  assert.equal(fixture.posts.length,1);
});
test('Work creation never posts after failed refresh and does not imply partial creation',async()=>{
  const fixture=setup({uuid:repairUUID,get:()=>{throw Error('offline');}});
  await assert.rejects(fixture.api.createProjectWork('workshop-a',repairDetails),error=>!error.creationUncertain);
  assert.equal(fixture.posts.length,0);
});
test('Work creation with wrong returned conversation remains uncertain without retry',async()=>{
  const fixture=setup({uuid:repairUUID,post:()=>({ok:true,created_root:'work-a',membership_wire:'wire-a',
    revision:5,workshop_root:'different-room',workshop_scope:'scope-a'})});
  await assert.rejects(fixture.api.createProjectWork('workshop-a',repairDetails),error=>error.creationUncertain===true);
  assert.equal(fixture.posts.length,1);
});

function editorSetup(intercept) {
  const pages=new Map(), opens=new Map();
  const fixture=setup({post:async(url,body)=>{
    if(intercept) await intercept(body);
    if(!body.action) return accepted(body);
    let row;
    if(body.action==='page-open') {
      if(!opens.has(body.request_key)) {
        const id='page-'+(pages.size+1); opens.set(body.request_key,id);
        pages.set(id,{page_id:id,page_revision:1,state:'open',draft_state:'unknown',resolution_kind:'none'});
      }
      row=pages.get(opens.get(body.request_key));
    } else if(body.action==='page-status') {
      row=pages.get(body.page_id);
    } else {
      row=pages.get(body.page_id);
      assert.equal(body.page_revision,row.page_revision);
      if(body.change==='close') row.state='closed';
      else {row.draft_state=body.change==='dirty'?'dirty':'clear';row.resolution_kind=body.change==='dirty'?'none':body.change;}
      row.page_revision++;
    }
    return {ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,revision:body.revision,
      request_revision:body.revision,owner:'owner-a',view:'view-a',page:{...row}};
  }});
  return {...fixture,pages};
}

test('editor: message receipt cannot clear a separate repair draft; close preserves it',async()=>{
  const {api,pages,posts}=editorSetup();
  const message=await api.openConversationEditor('workshop-a','document-message');
  const work=await api.openConversationEditor('workshop-a','document-work');
  await message.dirty();await work.dirty();
  const result=await api.workshopAction('workshop-a','send',null,{target:'worker-a',message:'Task'},message);
  assert.equal(result.accepted,true);assert.equal(result.warning,'');
  assert.equal(pages.get('page-1').draft_state,'clear');
  await work.close();
  assert.equal(pages.get('page-2').state,'closed');assert.equal(pages.get('page-2').draft_state,'dirty');
  const staged=posts.find(row=>row.body.change==='dirty'&&row.body.resolution_reference);
  const sent=posts.find(row=>row.body.idempotency_key);
  assert.equal(staged.body.resolution_reference,sent.body.idempotency_key);
  assert.equal(posts.find(row=>row.body.change==='saved').body.resolution_reference,result.root);
});

test('editor: editing does not post a protection write for every keystroke',async()=>{
  const {api,posts}=editorSetup(); const editor=await api.openConversationEditor('workshop-a','document');
  await Promise.all(Array.from({length:20},()=>editor.dirty()));
  assert.equal(posts.filter(row=>row.body.change==='dirty').length,1);
});

const pageProjectionConflict = body => {
  const {root,scope,revision,...request}=plain(body);
  return {ok:true,refused:true,error_code:'page_projection_conflict',operation_started:false,
    graph_id:'graph-a',root,scope_root:scope,owner:'owner-a',view:'view-a',revision,request};
};

test('actual Studio POST transports only the explicit completed page refusal for adapter reconciliation',async()=>{
  const html=fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio.html'),'utf8');
  const begin=html.indexOf('    const jpost = async');
  const end=html.indexOf('    window.ARCHHUB_AGENT =',begin);
  assert.ok(begin>=0 && end>begin);
  const request={root:'workshop-a',scope:'scope-a',revision:4,action:'page-open',request_key:'fixed-key'};
  let reply=pageProjectionConflict(request);
  const context=vm.createContext({H:()=>({}),window:{},fetch:async()=>({ok:true,json:async()=>reply})});
  vm.runInContext(html.slice(begin,end)+'\nglobalThis.post=jpost;',context);
  assert.deepEqual(plain(await context.post('/api/universal/workshop',request)),reply);
  reply={ok:false,error:'ordinary refusal'};
  await assert.rejects(context.post('/api/universal/workshop',request),/ordinary refusal/);
});

test('editor: unrelated graph advance before every page request preserves exact page transitions without retries',async()=>{
    let graphRevision=4,page=null;
    const {api,posts}=setup({get:()=>transcript('scope-a',graphRevision),post:(_url,body)=>{
      assert.equal(body.revision,graphRevision);graphRevision++;
      if(body.action==='page-open') {
        assert.equal(page,null);
        page={page_id:'same-page',page_revision:1,state:'open',draft_state:'unknown',resolution_kind:'none'};
      } else if(body.action!=='page-status') {
        assert.equal(body.page_id,page.page_id);assert.equal(body.page_revision,page.page_revision);
        page={...page,page_revision:page.page_revision+1,
          draft_state:body.change==='dirty'?'dirty':'clear',resolution_kind:body.change==='dirty'?'none':body.change};
      }
      return {ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,revision:graphRevision,
        request_revision:body.revision,owner:'owner-a',view:'view-a',page};
    }});
    const editor=await api.openConversationEditor('workshop-a','fixed-editor-key');
    assert.ok(editor);assert.equal(page.page_id,'same-page');assert.equal(page.page_revision,2);
    await editor.dirty();assert.equal(page.page_revision,3);assert.equal(page.draft_state,'dirty');
    assert.equal(posts.length,3);assert.equal(posts[0].body.request_key,'fixed-editor-key');
    assert.deepEqual(posts.map(row=>row.body.revision),[4,5,6]);
});

test('editor: old confirmed conflicts and generic or foreign failures never retry',async()=>{
  for(const kind of ['repeat','loss','generic','started','owner','view','scope','request']) {
    const {api,posts}=setup({get:()=>transcript(),post:(_url,body)=>{
      if(kind==='loss') throw Error('response lost');
      const result=pageProjectionConflict(body);
      if(kind==='generic') result.error_code='another_failure';
      if(kind==='started') result.operation_started=true;
      if(kind==='owner') result.owner='another-owner';
      if(kind==='view') result.view='another-view';
      if(kind==='scope') result.scope_root='another-scope';
      if(kind==='request') result.request.request_key='another-key';
      return result;
    }});
    await assert.rejects(api.openConversationEditor('workshop-a','fixed-key'),/Retry|retry|response lost/);
    assert.equal(posts.length,1);
    for(const row of posts) assert.equal(row.body.action,'page-open');
  }
});

test('editor: missing correlation, stale actual revision and foreign owner or view refuse without replay',async()=>{
  for(const invalid of [{request_revision:3},{request_revision:undefined},{revision:3},{revision:true},
    {owner:'other-owner'},{view:'other-view'},{scope_root:'other-scope'}]) {
    const {api,posts}=setup({post:(_url,body)=>({ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,
      revision:body.revision+1,request_revision:body.revision,owner:'owner-a',view:'view-a',
      page:{page_id:'page-one',page_revision:1,state:'open',draft_state:'unknown',resolution_kind:'none'},...invalid})});
    await assert.rejects(api.openConversationEditor('workshop-a','fixed-key'),/Retry|retry/);
    assert.equal(posts.length,1);
  }
});

test('editor: late message receipt refuses to clear a newer draft',async()=>{
  const {api,pages}=editorSetup();const editor=await api.openConversationEditor('workshop-a','document');
  const staged=await editor.stageMessage('intended-message');
  await editor.dirty();
  await assert.rejects(editor.savedMessage('accepted-message',staged),/newer or unresolved/);
  assert.equal(pages.get('page-1').draft_state,'dirty');
});

test('editor: protection failure prevents physical message sending and preserves pending identity',async()=>{
  let refuse=true;
  const {api,posts,pendingStorage}=editorSetup(body=>{
    if(body.change==='dirty'&&body.resolution_reference&&refuse) throw Error('offline');
  });
  const editor=await api.openConversationEditor('workshop-a','document');
  await assert.rejects(api.workshopAction('workshop-a','send',null,{target:'worker-a',message:'Task'},editor),/offline/);
  assert.equal(posts.filter(row=>row.body.idempotency_key).length,0);
  const pending=[...pendingStorage.data.values()].join(''); assert.match(pending,/message-/);
  refuse=false;await editor.retry();
  const result=await api.workshopAction('workshop-a','send',null,{target:'worker-a',message:'Task'},editor);
  assert.equal(result.accepted,true);
  const staged=posts.filter(row=>row.body.change==='dirty'&&row.body.resolution_reference);
  assert.equal(staged[0].body.resolution_reference,result.idempotency_key);
  assert.equal(staged[0].body.page_revision,staged[1].body.page_revision);
});

test('editor: navigation does not close a page through a different scope',async()=>{
  const {api,posts,pages}=editorSetup();const editor=await api.openConversationEditor('workshop-a','document');
  const count=posts.length;api.setCanvas(scope('other-scope'));
  await assert.rejects(editor.close(),/Return to this conversation/);
  assert.equal(posts.length,count);assert.equal(pages.get('page-1').state,'open');
});

test('editor: retry re-admits the same page after sibling removal without losing its draft',async()=>{
  const {api,pages,posts}=editorSetup();
  api.setCanvas({...scope(),workshops:[...scope().workshops,{root:'sibling',label:'Sibling',send_category:'declared-message'}]});
  const editor=await api.openConversationEditor('workshop-a','document');await editor.dirty();
  api.setCanvas(scope());
  await assert.rejects(editor.stageMessage('next-message'),/Return to this conversation/);
  await editor.retry();await editor.dirty();
  const status=posts.find(row=>row.body.action==='page-status');
  assert.equal(status.body.page_id,'page-1');assert.equal(pages.size,1);
  assert.equal(pages.get('page-1').draft_state,'dirty');
  const staged=await editor.stageMessage('final-message');
  assert.equal(staged.page_id,'page-1');
});

test('editor: retried staging is invalidated by newer local text',async()=>{
  let offline=true;
  const {api}=editorSetup(body=>{if(body.resolution_reference==='pending'&&offline)throw Error('offline');});
  const editor=await api.openConversationEditor('workshop-a','document');
  await assert.rejects(editor.stageMessage('pending'),/offline/);
  offline=false;const staged=await editor.retry();await editor.dirty();
  await assert.rejects(editor.savedMessage('old-accepted',staged),/newer or unresolved/);
});

function storageReviewSetup(options={}) {
  const metadata={page_id:'old-editor',page_revision:8,state:'closed',draft_state:'dirty',resolution_kind:'none',
    opened_at:1700000000.125,changed_at:1700001000.375,session_root:'old-session',subject_root:'owner-a',
    view_root:'old-view',tenant_root:'tenant',assurance_root:'assurance'};
  const fixture=setup({get:()=>({...transcript(),can_manage_history:options.allowed!==false}),
    post:async(url,body)=>{
      if(options.post) return options.post(body,metadata);
      const result={ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,revision:body.revision,
        protection:{tracking_state:'unknown',protected:true},activity_revision:7,page:null,
        retention:{last_activity_at:1700001000.375,archived_at:null,activity_revision:7,archive_revision:0,last_sequence:3,content_generation:0}};
      if(body.action==='page-owner-review') return {...result,pages:[{...metadata}],next_page_id:null};
      assert.equal(body.action,'page-owner-discard');assert.equal(body.page_revision,8);
      return {...result,page:{page_id:metadata.page_id,page_revision:9,state:'closed',draft_state:'clear',resolution_kind:'owner-discard'}};
    }});
  return {...fixture,metadata};
}

test('storage review: actual owner flag and reviewed metadata gate release',async()=>{
  const denied=storageReviewSetup({allowed:false});
  await assert.rejects(denied.api.reviewConversationPages('workshop-a'),/admitted application owner/);
  assert.equal(denied.posts.length,0);
  const {api,posts,metadata}=storageReviewSetup();
  await assert.rejects(api.discardConversationPage('workshop-a',metadata),/Review this protected editor/);
  const review=await api.reviewConversationPages('workshop-a');
  assert.equal(review.pages[0].changed_at,1700001000.375);
  assert.equal(posts[0].body.limit,50);
  assert.equal(Object.isFrozen(review.pages[0]),true);
  const released=await api.discardConversationPage('workshop-a',review.pages[0]);
  assert.equal(released.page.resolution_kind,'owner-discard');
  await assert.rejects(api.discardConversationPage('workshop-a',review.pages[0]),/Review this protected editor/);
  assert.equal(posts.length,2);
});

test('storage review: navigation invalidates prior release metadata',async()=>{
  const {api,posts}=storageReviewSetup();const review=await api.reviewConversationPages('workshop-a');
  api.setCanvas(scope('other-scope'));
  await assert.rejects(api.discardConversationPage('workshop-a',review.pages[0]),/Conversation changed/);
  assert.equal(posts.length,1);
});

test('storage review: rejects private pending references and invalid pagination',async()=>{
  for(const invalid of ['private','cursor','oversized']) {
    const {api}=storageReviewSetup({post:(body,row)=>({ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,
      revision:body.revision,activity_revision:7,protection:{tracking_state:'unknown',protected:true},page:null,
      retention:{last_activity_at:1700001000.375,archived_at:null,activity_revision:7,archive_revision:0,last_sequence:3,content_generation:0},
      pages:invalid==='private'?[{...row,resolution_reference:'private-pending-key'}]:invalid==='oversized'?Array(51).fill(row):[row],
      next_page_id:invalid==='cursor'?'unrelated-cursor':null})});
    await assert.rejects(api.reviewConversationPages('workshop-a'),/metadata is invalid/);
  }
});

test('storage archive: requires the exact clear review and retains graph/content positions',async()=>{
  let archived=false;
  const {api,posts}=storageReviewSetup({post:body=>{
    const retention={last_activity_at:1700001000.375,archived_at:archived?1700002000:null,
      activity_revision:7,archive_revision:archived?1:0,last_sequence:3,content_generation:2};
    if(body.action==='conversation-archive') {
      assert.deepEqual(plain(body),{root:'workshop-a',scope:'scope-a',revision:4,action:'conversation-archive',
        activity_revision:7,archive_revision:0,head:3,content_generation:2});
      archived=true;retention.archived_at=1700002000;retention.archive_revision=1;
    } else assert.equal(body.action,'page-owner-review');
    return {ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,revision:4,
      activity_revision:7,protection:{tracking_state:'ready',protected:false},retention,pages:[],next_page_id:null,page:null};
  }});
  const review=await api.reviewConversationPages('workshop-a');
  await assert.rejects(api.archiveConversation('workshop-a',{...review}),/Review and resolve/);
  const result=await api.archiveConversation('workshop-a',review);
  assert.equal(result.retention.last_sequence,3);assert.equal(result.retention.content_generation,2);
  await assert.rejects(api.archiveConversation('workshop-a',review),/Review and resolve/);
  assert.equal(posts.length,2);
});

test('storage tracking: explicit resolution uses reviewed activity and preserves protected editors',async()=>{
  const {api}=storageReviewSetup({post:body=>{
    const resolving=body.action==='page-tracking-resolve';
    if(resolving) {assert.equal(body.activity_revision,7);assert.equal(body.disposition,'discard-untracked-drafts');}
    return {ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,revision:4,activity_revision:7,
      protection:{tracking_state:resolving?'ready':'unknown',protected:true},
      retention:{last_activity_at:1700001000.375,archived_at:null,activity_revision:7,archive_revision:0,last_sequence:3,content_generation:0},
      pages:[],next_page_id:null,page:null};
  }});
  const review=await api.reviewConversationPages('workshop-a');
  await assert.rejects(api.archiveConversation('workshop-a',review),/Review and resolve/);
  const result=await api.resolveConversationTracking('workshop-a',review);
  assert.equal(result.protection.protected,true);
  await assert.rejects(api.resolveConversationTracking('workshop-a',review),/Review the earlier/);
});

// Exercise the two production transports used by the same conversation panel.
const authoritySource = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-authority.js'), 'utf8');
const authorityContext = vm.createContext({URLSearchParams});
vm.runInContext(authoritySource, authorityContext);
const ordinary = (change={}) => ({...transcript(), storage:'conversation-content',
  content_cursor:'opaque visible cursor / first', page_before:null,
  next_before:'opaque older position / first', has_older:true, total:102,
  messages:[{root:'message-102',sequence:102,body:'Latest task result',sender_root:'worker-a',
    recipient_root:'owner-a',state:'sent',category:'declared-message'}], ...change});
const unchanged = page => ({graph_id:page.graph_id,root:page.root,scope_root:page.scope_root,
  revision:page.revision,storage:page.storage,content_cursor:page.content_cursor,
  page_before:page.page_before,unchanged:true});
for(const kind of ['existing','authority']) test(`${kind}: an unchanged page at a newer graph revision keeps its messages and carries the graph's assignments`, async()=>{
  // A graph write that adds no message (an assignment, 3a6bf6ba) moves the graph
  // revision while the content cursor holds: the page stays, takes the revision
  // and the assignments and participants it carries, and is not refused. Both
  // transports: the hosted Workshop (studio-authority.js) as well as the desktop.
  let calls=0; const latest=ordinary();
  const assignments=[{work:'work-a',agent:'worker-a'}];
  const participants=latest.participants.map(row=>({...row,connection_status:'stale'}));
  const {api}=await readers(kind,()=>++calls===1?latest:{...unchanged(latest),revision:5,assignments,participants});
  await api.refreshWorkshop('workshop-a');
  const messages=api.getSnapshot().workshop.messages;
  const next=await api.refreshWorkshop('workshop-a');
  assert.equal(next.revision,5); assert.equal(api.getSnapshot().workshop.messages,messages);
  assert.deepEqual(api.getSnapshot().workshop.assignments,assignments);
  assert.deepEqual(api.getSnapshot().workshop.participants,participants);
  assert.equal(api.getSnapshot().workshop.error,'');
});
test('existing: participant activity changes refresh without replacing message history',async()=>{
  const page=ordinary(); let response=page;
  const {api}=setup({get:()=>response});
  await api.refreshWorkshop('workshop-a');
  const messages=api.getSnapshot().workshop.messages;
  response={...unchanged(page),participants:page.participants.map(row=>({...row,connection_status:'stale'}))};
  await api.refreshWorkshop('workshop-a');
  assert.equal(api.getSnapshot().workshop.messages,messages);
  assert.equal(api.getSnapshot().workshop.participants[1].connection_status,'stale');
  const held=api.getSnapshot();
  await api.refreshWorkshop('workshop-a');
  assert.equal(api.getSnapshot(),held);
});
async function readerSetup(kind, get) {
  if (kind === 'existing') {
    const value=setup({get});
    return {...value, setCanvas:async canvas=>value.api.setCanvas(canvas)};
  }
  let canvas=scope(); const gets=[];
  const api=authorityContext.ArchHubStudioAuthority.create({
    get:async url=>{
      if(url==='/api/universal/canvas') return {...canvas,nodes:[{id:'workshop-a',label:'Workshop'}],wires:[],catalog:[]};
      gets.push(url); return get(url);
    }, post:async()=>{throw new Error('No write belongs to a conversation read.');}});
  await api.load();
  return {api,gets,setCanvas:async value=>{canvas=value;return api.load();}};
}
async function readers(kind, get) {
  return readerSetup(kind,get);
}

for(const kind of ['existing','authority']) {
  test(`${kind}: ordinary refresh uses visible cursor at the same graph revision without republishing unchanged`, async()=>{
    let page=ordinary(), calls=0;
    const {api,gets}=await readers(kind,()=>++calls===2?unchanged(page):page);
    await api.refreshWorkshop('workshop-a');
    const held=api.getSnapshot(); let notified=0; api.subscribe(()=>notified++);
    await api.refreshWorkshop('workshop-a');
    const url=new URL(gets[1],'http://test');
    assert.equal(url.searchParams.get('content_after'),page.content_cursor);
    assert.equal(url.searchParams.has('before'),false);
    assert.equal(api.getSnapshot(),held); assert.equal(notified,0);
    page=ordinary({content_cursor:'opaque visible cursor / next',messages:[{...page.messages[0],root:'message-103',sequence:103,body:'New real result'}]});
    // A new visible arrival changes only ordinary content, not the graph revision.
    await api.refreshWorkshop('workshop-a');
    assert.equal(api.getSnapshot().workshop.messages[0].body,'New real result');
  });

  test(`${kind}: older navigation replaces one bounded page and polls that opaque position`, async()=>{
    const latest=ordinary(), older=ordinary({page_before:latest.next_before,content_cursor:'older visible cursor',
      next_before:'next opaque older / position',messages:[{...latest.messages[0],root:'message-2',sequence:2,body:'Earlier result'}]});
    const {api,gets}=await readers(kind,url=>{
      const query=new URL(url,'http://test').searchParams;
      if(!query.has('before')) return latest;
      assert.equal(query.get('before'),latest.next_before);
      return query.has('content_after')?unchanged(older):older;
    });
    await api.refreshWorkshop('workshop-a'); await api.loadOlderWorkshop('workshop-a');
    assert.deepEqual(plain(api.getSnapshot().workshop.messages.map(row=>row.root)),['message-2']);
    assert.equal(api.getSnapshot().workshop.page_before,latest.next_before);
    await api.refreshWorkshop('workshop-a');
    assert.equal(new URL(gets[2],'http://test').searchParams.get('content_after'),older.content_cursor);
    await api.showLatestWorkshop('workshop-a');
    assert.equal(api.getSnapshot().workshop.page_before,null);
    assert.equal(api.getSnapshot().workshop.messages[0].root,'message-102');
    assert.equal(new URL(gets[3],'http://test').searchParams.has('before'),false);
  });

  test(`${kind}: explicit navigation wins over pending latest polls and coalesces only its own page`, async()=>{
    const poll=deferred(), olderRead=deferred(), latest=ordinary(); let calls=0;
    const {api,gets}=await readers(kind,url=>{
      calls++;
      if(calls===1) return latest;
      if(new URL(url,'http://test').searchParams.has('before')) return olderRead.promise;
      return poll.promise;
    });
    await api.refreshWorkshop('workshop-a');
    const pending=api.refreshWorkshop('workshop-a');
    const navigation=api.loadOlderWorkshop('workshop-a');
    const duplicate=api.refreshWorkshop('workshop-a');
    assert.equal(gets.length,3);
    olderRead.resolve(ordinary({page_before:latest.next_before,content_cursor:'older cursor',next_before:null,
      has_older:false,messages:[{...latest.messages[0],root:'message-1',sequence:1}]}));
    await navigation; await duplicate;
    poll.resolve(ordinary({content_cursor:'new latest cursor'}));
    assert.equal(await pending,null);
    assert.equal(api.getSnapshot().workshop.messages[0].root,'message-1');
  });

  test(`${kind}: Latest supersedes a pending older read without retaining conversation content in storage`, async()=>{
    const older=deferred(), latest=ordinary();
    const {api,gets,pendingStorage}=await readers(kind,url=>new URL(url,'http://test').searchParams.has('before')?
      older.promise:latest);
    await api.refreshWorkshop('workshop-a');
    const navigation=api.loadOlderWorkshop('workshop-a');
    assert.equal(api.getSnapshot().workshop,null);
    assert.equal(api.getSnapshot().workshopPage.before,latest.next_before);
    await api.showLatestWorkshop('workshop-a');
    assert.equal(gets.length,3);
    assert.equal(api.getSnapshot().workshop.messages[0].root,'message-102');
    older.reject(new Error('The obsolete page was refused.'));
    assert.equal(await navigation,null);
    assert.equal(api.getSnapshot().workshop.error,'');
    if(pendingStorage) assert.equal(pendingStorage.data.size,0);
  });

  test(`${kind}: Latest recovers refused older tokens and rejects wrong-page or oversized data`, async()=>{
    const latest=ordinary(); let refusal=true;
    const {api}=await readers(kind,url=>new URL(url,'http://test').searchParams.has('before')?
      (refusal?{ok:false,error:'Workshop page was refused.'}:ordinary({page_before:'different page'})):latest);
    await api.refreshWorkshop('workshop-a');
    await assert.rejects(api.loadOlderWorkshop('workshop-a'),/refused/);
    assert.equal(api.getSnapshot().workshop.messages.length,0);
    await api.showLatestWorkshop('workshop-a');
    assert.equal(api.getSnapshot().workshop.error,'');
    refusal=false;
    await assert.rejects(api.loadOlderWorkshop('workshop-a'),/page|invalid/);
    assert.equal(api.getSnapshot().workshop.messages.length,0);
    const oversized=await readers(kind,()=>ordinary({messages:Array.from({length:101},(_,i)=>({
      ...latest.messages[0],root:'message-'+(i+1),sequence:i+1}))}));
    await assert.rejects(oversized.api.refreshWorkshop('workshop-a'),/invalid|limit|bounded/);
  });

  test(`${kind}: ordinary unchanged requires exact cursor and page and clears refused content`, async()=>{
    // The content cursor and page are the page's identity. A newer graph
    // revision alone is not a refusal (see the next court).
    for(const change of [{content_cursor:'wrong cursor'},{page_before:'wrong page'},{storage:undefined}]) {
      let calls=0; const latest=ordinary();
      const {api}=await readers(kind,()=>++calls===1?latest:{...unchanged(latest),...change});
      await api.refreshWorkshop('workshop-a');
      await assert.rejects(api.refreshWorkshop('workshop-a'),/refresh|page|invalid|stale/);
      assert.equal(api.getSnapshot().workshop.messages.length,0);
    }
  });

  test(`${kind}: canvas invalidates older authority but keeps a projection while catching up`, async()=>{
    const latest=ordinary({revision:6});
    const {api,setCanvas}=await readers(kind,()=>latest);
    await api.refreshWorkshop('workshop-a');
    const held=api.getSnapshot().workshop;
    await setCanvas(scope('scope-a',5)); assert.equal(api.getSnapshot().workshop,held);
    await setCanvas(scope('scope-a',6)); assert.equal(api.getSnapshot().workshop,held);
    await setCanvas(scope('scope-a',7)); assert.equal(api.getSnapshot().workshop,null);
  });

  test(`${kind}: removing and restoring a Workshop ignores a previously pending page`, async()=>{
    const pending=deferred(); const {api,setCanvas}=await readers(kind,()=>pending.promise);
    const read=api.refreshWorkshop('workshop-a');
    await setCanvas({...scope(),workshops:[]}); await setCanvas(scope());
    pending.resolve(ordinary()); assert.equal(await read,null);
    assert.equal(api.getSnapshot().workshop,null);
  });

  test(`${kind}: legacy transcripts keep graph polling without offering opaque paging`, async()=>{
    let calls=0;
    const {api,gets}=await readers(kind,()=>++calls===1?transcript():{...transcript(),unchanged:true});
    await api.refreshWorkshop('workshop-a'); await api.refreshWorkshop('workshop-a');
    assert.equal(new URL(gets[1],'http://test').searchParams.get('after'),'4');
    assert.equal(new URL(gets[1],'http://test').searchParams.has('content_after'),false);
    await assert.rejects(api.loadOlderWorkshop('workshop-a'),/older|page|paging|available/i);
    assert.equal(gets.length,2);
  });
}

// The Workshop conversation lives in WorkshopView (studio-workshop.jsx) since
// db74408d; these courts read its own page navigation and its one poll effect.
const workshopView = () => {
  const jsx=fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-workshop.jsx'),'utf8');
  const view=jsx.indexOf('const WorkshopView =');
  const pollEnd=jsx.indexOf('  const participants = transcript?.participants',view);
  const pollBegin=jsx.lastIndexOf('  React.useEffect(() => {',pollEnd);
  const navigateBegin=jsx.indexOf('  const navigatePage = async latest => {',view);
  const navigateEnd=jsx.indexOf('  React.useEffect(() => { setPublicReview(false); }',navigateBegin);
  assert.ok(view>=0 && pollBegin>view && pollEnd>pollBegin);
  assert.ok(navigateBegin>view && navigateEnd>navigateBegin && navigateEnd<pollBegin);
  return {jsx, poll:jsx.slice(pollBegin,pollEnd), navigate:jsx.slice(navigateBegin,navigateEnd)};
};

test('WorkshopConversation visibility and 2.5 second poll keep the selected page live and dispose cleanly', async()=>{
  const latest=ordinary(), older=ordinary({page_before:latest.next_before,content_cursor:'visible older page',
    next_before:null,has_older:false,messages:[{...latest.messages[0],root:'message-1',sequence:1}]});
  const {api,gets}=setup({get:url=>{
    const query=new URL(url,'http://test').searchParams;
    if(query.has('before')) return query.has('content_after')?unchanged(older):older;
    return query.has('content_after')?unchanged(latest):latest;
  }});
  const {jsx,poll,navigate}=workshopView();
  const effects=[],timers=new Map(),listeners=new Map(); let timerId=0;
  const document={hidden:true,addEventListener:(name,fn)=>listeners.set(name,fn),
    removeEventListener:(name,fn)=>{assert.equal(listeners.get(name),fn);listeners.delete(name);}};
  const panelContext=vm.createContext({document,Date,authority:api,descriptor:{root:'workshop-a'},
    openedRoot:{current:'workshop-a'},nativeAvailable:false,nativeTarget:null,busyRef:{current:false},
    revisionSubmission:{current:null},setRefreshing:()=>{},setNativeSyncError:()=>{},
    olderPage:true,transcript:null,pageIntent:{current:0},latestJump:{current:false},
    setPaging:()=>{},setActionError:()=>{},
    React:{useEffect:fn=>effects.push(fn)},
    setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},
    clearTimeout:id=>timers.delete(id)});
  vm.runInContext(navigate+poll+'\nglobalThis.panel={navigatePage};',panelContext);
  const panel=panelContext.panel;
  const dispose=effects.find(fn=>fn.toString().includes("document.addEventListener('visibilitychange'"))();
  assert.equal(gets.length,0); assert.equal(timers.size,0);
  document.hidden=false; listeners.get('visibilitychange')();
  await new Promise(setImmediate);
  assert.equal(gets.length,1); assert.equal(timers.size,1);
  await panel.navigatePage(false);
  assert.equal(api.getSnapshot().workshop.messages[0].root,'message-1');
  const [id,timer]=[...timers.entries()][0];
  assert.equal(timer.ms,2500); timers.delete(id); timer.fn();
  await new Promise(setImmediate);
  assert.equal(gets.length,3); assert.equal(timers.size,1);
  const read=new URL(gets[2],'http://test').searchParams;
  assert.equal(read.get('before'),latest.next_before);
  assert.equal(read.get('content_after'),older.content_cursor);
  document.hidden=true; listeners.get('visibilitychange')();
  assert.equal(timers.size,0); assert.equal(gets.length,3);
  await panel.navigatePage(true);
  assert.equal(api.getSnapshot().workshop.messages[0].root,'message-102');
  dispose(); assert.equal(timers.size,0); assert.equal(listeners.size,0);
  assert.ok(jsx.includes('onClick={() => navigatePage(false)}>Older messages</Mini>'));
  assert.ok(jsx.includes('title="Jump to latest messages" onClick={() => navigatePage(true)}'));
});

test('WorkshopConversation opens a newly shown Workshop once, then polls with refresh', async()=>{
  const {poll}=workshopView();
  const calls=[], timers=new Map(), listeners=new Map(); let timerId=0, dispose;
  const openedRoot={current:''};
  const context=vm.createContext({document:{hidden:false,addEventListener:(name,fn)=>listeners.set(name,fn),
      removeEventListener:(name,fn)=>listeners.delete(name)},
    Date,descriptor:{root:'workshop-a'},openedRoot,nativeAvailable:false,nativeTarget:null,
    busyRef:{current:false},revisionSubmission:{current:null},setRefreshing:()=>{},setNativeSyncError:()=>{},
    authority:{getSnapshot:()=>null,openWorkshop:root=>{calls.push(['open',root]);return Promise.resolve(null);},
      refreshWorkshop:root=>{calls.push(['refresh',root]);return Promise.resolve(null);}},
    React:{useEffect:fn=>{dispose=fn();}},
    setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
  vm.runInContext(poll,context);
  await new Promise(setImmediate);
  assert.deepEqual(calls,[['open','workshop-a']]); assert.equal(openedRoot.current,'workshop-a');
  const [id,timer]=[...timers.entries()][0]; assert.equal(timer.ms,2500); timers.delete(id); timer.fn();
  await new Promise(setImmediate);
  assert.deepEqual(calls,[['open','workshop-a'],['refresh','workshop-a']]);
  dispose(); assert.equal(timers.size,0); assert.equal(listeners.size,0);
});

test('WorkshopConversation message refresh settles before pending native status without overlapping polls', async()=>{
  const {poll}=workshopView();
  for(const outcome of ['native-pending-unmount','message-failure','message-pending-unmount']) {
    const message=deferred(), native=deferred(), changes=[], errors=[], timers=new Map(), listeners=new Map();
    let now=0, reads=0, nativeReads=0, dispose, timerId=0;
    const document={hidden:false,addEventListener:(name,fn)=>listeners.set(name,fn),
      removeEventListener:(name,fn)=>{assert.equal(listeners.get(name),fn);listeners.delete(name);}};
    const context=vm.createContext({document,Date:{now:()=>now},descriptor:{root:'workshop-a'},
      openedRoot:{current:'workshop-a'},
      nativeAvailable:true,nativeTarget:'work-a',busyRef:{current:false},revisionSubmission:{current:null},
      authority:{getSnapshot:()=>({workshop:{content_cursor:'old'}}),
        refreshWorkshop:()=>{reads++;return message.promise;},
        refreshNativeWork:()=>{nativeReads++;return native.promise;}},
      setRefreshing:value=>changes.push(value),setNativeSyncError:value=>errors.push(value),
      React:{useEffect:fn=>{dispose=fn();}},
      setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},
      clearTimeout:id=>timers.delete(id)});
    vm.runInContext(poll,context);
    assert.deepEqual(changes,[true]); assert.equal(reads,1);
    now=10001;
    if(outcome==='message-pending-unmount') dispose();
    if(outcome==='message-failure') message.reject(new Error('message read refused'));
    else message.resolve({content_cursor:'new'});
    await new Promise(setImmediate);
    if(outcome==='message-pending-unmount') {
      assert.deepEqual(changes,[true]); assert.equal(nativeReads,0); assert.equal(timers.size,0);
    } else {
      assert.deepEqual(changes,[true,false]);
      if(outcome==='message-failure') {
        assert.equal(nativeReads,0); assert.equal(timers.size,1);
        assert.equal([...timers.values()][0].ms,2500); dispose();
      } else {
        assert.equal(nativeReads,1); assert.equal(timers.size,0);
        listeners.get('visibilitychange')();
        assert.equal(reads,1); assert.equal(nativeReads,1);
        dispose(); native.reject(new Error('late native failure'));
        await new Promise(setImmediate);
        assert.deepEqual(changes,[true,false]); assert.deepEqual(errors,[]);
      }
    }
    assert.equal(timers.size,0); assert.equal(listeners.size,0);
  }
});

test('authorized descriptors and exact guarded legacy message body',async () => {
  const {api,posts}=setup();
  await api.refreshWorkshop('workshop-a');
  const result=await send(api);
  assert.equal(result.accepted,true);
  assert.deepEqual(plain(posts[0].body), {root:'workshop-a',scope:'scope-a',category:'declared-message',
    text:'Actual task text',refs:[],evidence:[],recipients:['worker-a'],reply_to:null,created_at:null,idempotency_key:'message-1'});
  assert.equal(api.getSnapshot().workshops[0].root,'workshop-a');
});

test('no fake join, execution or sender override',async () => {
  const {api,posts}=setup(); await api.refreshWorkshop('workshop-a');
  await assert.rejects(api.workshopAction('workshop-a','attach',null,{}),/messaging only/);
  for(const extra of [{execution_root:'node-a'},{actor:'worker-a'}]) {
    await assert.rejects(api.workshopAction('workshop-a','send',null,{target:'worker-a',message:'text',...extra}),/messaging only/);
  }
  assert.equal(posts.length,0);
});

test('server refusal of send capability and detached recipient are respected',async () => {
  const response=transcript(); response.can_send=false;
  const {api,posts}=setup({get:()=>response}); await api.refreshWorkshop('workshop-a');
  await assert.rejects(send(api),/Refresh/);
  response.can_send=true; response.participants[1].attached=false;
  await api.refreshWorkshop('workshop-a');
  await assert.rejects(send(api),/current participant/);
  assert.equal(posts.length,0);
});

test('stale and foreign transcript responses are refused',async () => {
  for(const change of [{revision:3},{graph_id:'other'},{scope_root:'other'},{root:'other'}]) {
    const {api}=setup({get:()=>({...transcript(),...change})});
    await assert.rejects(api.refreshWorkshop('workshop-a'),/stale or belongs/);
    assert.ok(api.getSnapshot().workshop.error);
  }
});

test('navigation ignores the old outstanding read',async () => {
  const gate=deferred(); const {api}=setup({get:()=>gate.promise});
  const read=api.refreshWorkshop('workshop-a'); api.setCanvas(scope('scope-b'));
  gate.resolve(transcript()); assert.equal(await read,null);
  assert.equal(api.getSnapshot().workshop,null);
});

test('same-scope reads coalesce and unchanged requires an exact prior stamp',async () => {
  let call=0;
  const {api,gets}=setup({get:()=>++call===1?transcript():{...transcript(),unchanged:true}});
  await Promise.all([api.refreshWorkshop('workshop-a'),api.refreshWorkshop('workshop-a')]);
  assert.equal(gets.length,1);
  let notifications=0; const snapshot=api.getSnapshot();
  api.subscribe(()=>notifications++);
  await api.refreshWorkshop('workshop-a'); assert.match(gets[1],/after=4/);
  assert.equal(notifications,0); assert.equal(api.getSnapshot(),snapshot);
  const cold=setup({get:()=>({...transcript(),unchanged:true})});
  await assert.rejects(cold.api.refreshWorkshop('workshop-a'),/full refresh/);
});

test('lost reply keeps digest-only pending identity across adapter reload',async () => {
  const saved=storage();
  const first=setup({pendingStorage:saved,post:()=>{throw new Error('lost response');}});
  await first.api.refreshWorkshop('workshop-a'); await assert.rejects(send(first.api),/lost response/);
  assert.ok(!JSON.stringify([...saved.data]).includes('Actual task text'));
  assert.ok(!JSON.stringify([...saved.data]).includes('owner-a'));
  const second=setup({pendingStorage:saved}); await second.api.refreshWorkshop('workshop-a');
  await send(second.api);
  assert.equal(second.posts[0].body.idempotency_key,first.posts[0].body.idempotency_key);
  assert.equal(Object.keys(JSON.parse([...saved.data.values()][0])).length,0);
});

test('simultaneous same message invokes one POST',async () => {
  const gate=deferred(), started=deferred();
  const {api,posts}=setup({post:()=>{started.resolve();return gate.promise;}});
  await api.refreshWorkshop('workshop-a');
  const a=send(api), b=send(api);
  await started.promise;
  assert.equal(posts.length,1); gate.resolve(accepted(posts[0].body));
  assert.equal((await a).accepted,true); assert.equal((await b).accepted,true);
});

test('accepted response survives navigation and storage cleanup errors',async () => {
  const gate=deferred(), started=deferred(); const saved=storage();
  const {api,posts}=setup({pendingStorage:saved,post:()=>{started.resolve();return gate.promise;}});
  await api.refreshWorkshop('workshop-a'); const sending=send(api);
  await started.promise;
  api.setCanvas(scope('scope-b')); saved.setItem=()=>{throw new Error('storage blocked');};
  gate.resolve(accepted(posts[0].body)); const result=await sending;
  assert.equal(result.accepted,true); assert.equal(result.navigated,true); assert.ok(result.warning);
  assert.equal(api.getSnapshot().canvas.root,'scope-b');
});

test('unrecognized success does not clear pending identity',async () => {
  const {api,pendingStorage}=setup({post:()=>({ok:true})}); await api.refreshWorkshop('workshop-a');
  await assert.rejects(send(api),/could not be reconciled/);
  assert.equal(Object.keys(JSON.parse([...pendingStorage.data.values()][0])).length,1);
});

test('post acceptance projection callback or refresh failure cannot request resend',async () => {
  let reads=0;
  const {api}=setup({get:()=>{if(++reads>1)throw new Error('offline');return transcript();}});
  await api.refreshWorkshop('workshop-a'); api.subscribe(()=>{throw new Error('render failure');});
  assert.equal((await send(api)).accepted,true);
});

test('lost execution response is read back without a second execution request', async () => {
  let state = {ok:true,root:'workshop-a',scope:'scope-a',state:'awaiting_approval',request_id:'operation-a',work:'work-a'};
  const {api,posts} = setup({get:()=>state,post:()=>{
    state={...state,state:'settled',receipt:'receipt-a'};throw new Error('response lost');
  }});
  await api.refreshNativeWork('workshop-a');
  await assert.rejects(api.nativeWorkAction('workshop-a','execute'),/response lost/);
  assert.equal(posts.length,1);
  assert.equal(api.getSnapshot().nativeWork.receipt,'receipt-a');
});

test('lost reconciliation response reads the recovered receipt without executing again', async () => {
  let state = {ok:true,root:'workshop-a',scope:'scope-a',state:'uncertain',request_id:'operation-a',work:'work-a'};
  const {api,posts} = setup({get:()=>state,post:(_url,body)=>{
    assert.equal(body.action,'reconcile');
    assert.equal(body.request_id,'operation-a');
    state={...state,state:'settled',receipt:'receipt-a'}; throw new Error('recovery response lost');
  }});
  await api.refreshNativeWork('workshop-a');
  await assert.rejects(api.nativeWorkAction('workshop-a','reconcile'),/recovery response lost/);
  assert.equal(posts.length,1);
  assert.equal(api.getSnapshot().nativeWork.receipt,'receipt-a');
});

test('older native status read cannot replace a newer result', async () => {
  const first=deferred(); let reads=0;
  const result={ok:true,root:'workshop-a',scope:'scope-a',state:'published'};
  const {api}=setup({get:()=>++reads===1 ? first.promise : result});
  const older=api.refreshNativeWork('workshop-a');
  await api.refreshNativeWork('workshop-a');
  first.resolve({...result,state:'executing'}); await older;
  assert.equal(api.getSnapshot().nativeWork.state,'published');
});

test('lost release survives adapter reload and replays the same identity', async () => {
  const pendingStorage=storage();
  let state={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',
    state:'published',request_id:'operation-a',work:'work-a'};
  const first=setup({pendingStorage,get:()=>state,post:()=>{
    state={...state,state:'idle'};delete state.request_id;delete state.work;
    throw new Error('release response lost');
  }});
  await first.api.refreshNativeWork('workshop-a');
  await assert.rejects(first.api.nativeWorkAction('workshop-a','release'),/response lost/);
  assert.equal(first.api.getSnapshot().nativeWork.state,'release_pending');
  const second=setup({pendingStorage,get:()=>state,post:(_url,body)=>releasedNative(body)});
  await second.api.refreshNativeWork('workshop-a');
  assert.equal(second.api.getSnapshot().nativeWork.state,'release_pending');
  await second.api.nativeWorkAction('workshop-a','release');
  assert.equal(second.posts.length,1);
  assert.equal(second.posts[0].body.request_id,'operation-a');
  assert.equal(second.api.getSnapshot().nativeWork.state,'idle');
});

test('accepted release remains recoverable if storage cleanup fails', async () => {
  const pendingStorage=storage(), write=pendingStorage.setItem;
  const state={ok:true,root:'workshop-a',scope:'scope-a',owner:'owner-a',view:'view-a',
    state:'published',request_id:'operation-a',work:'work-a'};
  const {api}=setup({pendingStorage,get:()=>state,post:(_url,body)=>{
    pendingStorage.setItem=()=>{throw new Error('storage blocked');};
    return releasedNative(body);
  }});
  await api.refreshNativeWork('workshop-a');
  const result=await api.nativeWorkAction('workshop-a','release');
  assert.equal(result.released,true);
  assert.match(api.getSnapshot().workshopNotice,/storage needs recovery/);
  assert.equal(api.getSnapshot().nativeWork.state,'release_pending');
  pendingStorage.setItem=write;
});

test('slow panel catalogue reads coalesce and publish related rows together', async () => {
  const jsx=fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-lm.jsx'),'utf8');
  const section=jsx.slice(jsx.indexOf('const catalogueStates ='),jsx.indexOf('const withLiveCatalogue ='));
  const pending=deferred(); let calls=0;
  const window={ARCHHUB_LIVE:{connectors:[]},ARCHHUB_LOAD_HOSTS:()=>{calls++;return pending.promise;}};
  const context=vm.createContext({window});
  vm.runInContext(section+';globalThis.load=loadCatalogue;globalThis.states=catalogueStates;',context);
  const rows=[], first=context.load('ARCHHUB_LOAD_HOSTS',rows), second=context.load('ARCHHUB_LOAD_HOSTS',rows);
  assert.equal(first,second); await Promise.resolve(); assert.equal(calls,1);
  pending.resolve({hosts:[{name:'host-a'}],connectors:[{name:'connector-a'}]}); await first;
  assert.deepEqual(plain(rows),[{name:'host-a'}]);
  assert.deepEqual(plain(window.ARCHHUB_LIVE.connectors),[{name:'connector-a'}]);
  assert.equal(context.states.get('ARCHHUB_LOAD_HOSTS').loading,false);
});

test('invalid host rows preserve prior data and a failed subscriber cannot reject completion', async () => {
  const jsx=fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-lm.jsx'),'utf8');
  const section=jsx.slice(jsx.indexOf('const catalogueStates ='),jsx.indexOf('const withLiveCatalogue ='));
  let result={hosts:[{name:'new'}]};
  const window={ARCHHUB_LIVE:{connectors:[{name:'old'}]},ARCHHUB_LOAD_HOSTS:async()=>result};
  const context=vm.createContext({window});
  vm.runInContext(section+';globalThis.load=loadCatalogue;globalThis.states=catalogueStates;'+
    'catalogueListeners.add(()=>{throw new Error("subscriber failed")});',context);
  const rows=[{name:'old'}];
  await context.load('ARCHHUB_LOAD_HOSTS',rows);
  assert.deepEqual(plain(rows),[{name:'old'}]);
  assert.match(context.states.get('ARCHHUB_LOAD_HOSTS').error,/invalid/);
  result={hosts:[{name:'new'}],connectors:[{name:'new'}]};
  await context.load('ARCHHUB_LOAD_HOSTS',rows);
  assert.deepEqual(plain(rows),[{name:'new'}]);
  assert.equal(context.states.get('ARCHHUB_LOAD_HOSTS').error,'');
});

const catalogReply = (change={}) => ({ok:true,graph_id:'graph-a',root:'workshop-a',scope_root:'scope-a',
  workbench_root:'workbench-a',revision:4,owner:'owner-a',view:'view-a',self:'owner-a',can_create:true,
  participants:transcript().participants,
  conversations:[{root:'workshop-a',title:'General Workshop',participant_roots:['owner-a','worker-a'],is_general:true}],
  has_more:false,next_after:null,...change});
const newConversation = body => ({ok:true,graph_id:'graph-a',scope_root:body.scope,root:'created-chat',
  title:body.title,participant_roots:body.participant_roots,is_general:false,created:true,
  revision:body.revision+1,idempotency_key:body.idempotency_key});
const createdCanvas = (rev=5) => ({ok:true,application_root:'graph-a',revision:rev,
  authorization:{subject:'owner-a',session:'view-a'},scope:{current:'scope-a'},
  nodes:[{id:'workshop-a',label:'Workshop'},{id:'created-chat',label:'Walls'}],wires:[],
  interaction_projection:{revision:rev,bindings:[]},workshop_scope:{...scope('scope-a',rev),workshops:[
    {...scope().workshops[0],is_general:true,native_work_available:true},
    {root:'created-chat',label:'Walls',is_general:false,native_work_available:false}]}});
const createConversation = api => api.createConversation('workshop-a',{
  title:'Walls',participant_roots:['owner-a','worker-a']});

test('catalog pages coalesce separately and never replace the selected child transcript',async()=>{
  const pending=deferred();
  const child={root:'child-chat',label:'Child'};
  const next={root:child.root,title:child.label,participant_roots:['owner-a'],is_general:false};
  const {api,gets}=setup({get:url=>{
    const query=new URL(url,'http://test').searchParams;
    if(!query.has('catalog')) return {...transcript(),root:child.root};
    if(query.has('after')) {
      assert.equal(query.get('after'),'opaque / next page');
      return catalogReply({conversations:[next]});
    }
    return pending.promise;
  }});
  api.setCanvas({...scope(),workshops:[...scope().workshops,child]});
  await api.refreshWorkshop(child.root);
  const held=api.getSnapshot().workshop,page=api.getSnapshot().workshopPage;
  const one=api.refreshConversationCatalog('workshop-a');
  const two=api.refreshConversationCatalog('workshop-a');
  assert.equal(gets.length,2);
  pending.resolve(catalogReply({has_more:true,next_after:'opaque / next page'}));
  await one; await two;
  assert.equal(api.getSnapshot().workshop,held);
  assert.equal(api.getSnapshot().workshopPage,page);
  await api.loadNextConversationPage('workshop-a');
  assert.deepEqual(plain(api.getSnapshot().conversationCatalog.conversations),[next]);
  assert.equal(api.getSnapshot().workshop,held);
  await assert.rejects(api.loadNextConversationPage('workshop-a'),/No next/);
});

test('catalog navigation and scope removal invalidate pending pages',async()=>{
  const older=deferred(); let calls=0;
  const {api}=setup({get:url=>{
    const query=new URL(url,'http://test').searchParams;
    if(query.has('after')) return catalogReply({conversations:[{
      root:'other-chat',title:'Other',participant_roots:['owner-a'],is_general:false}]});
    return ++calls===1?catalogReply({has_more:true,next_after:'next'}):older.promise;
  }});
  await api.refreshConversationCatalog('workshop-a');
  const poll=api.refreshConversationCatalog('workshop-a');
  await api.loadNextConversationPage('workshop-a');
  older.resolve(catalogReply());
  assert.equal(await poll,null);
  assert.equal(api.getSnapshot().conversationCatalog.conversations[0].root,'other-chat');
  const pending=deferred(), second=setup({get:()=>pending.promise});
  const read=second.api.refreshConversationCatalog('workshop-a');
  second.api.setCanvas({...scope(),workshops:[]});second.api.setCanvas(scope());
  pending.resolve(catalogReply());
  assert.equal(await read,null);
  assert.equal(second.api.getSnapshot().conversationCatalog,null);
});

test('catalog rejects foreign scopes, oversized pages and incomplete participant authority',async()=>{
  for(const change of [{graph_id:'another-graph'},
      {conversations:Array.from({length:51},(_,i)=>({root:'chat-'+i,title:'Chat',participant_roots:['owner-a'],is_general:false}))},
      {has_more:true,next_after:null},{participants:undefined}]) {
    const {api}=setup({get:()=>catalogReply(change)});
    await assert.rejects(api.refreshConversationCatalog('workshop-a'),/invalid|stale|scope|authority/);
    assert.equal(api.getSnapshot().conversationCatalog.conversations.length,0);
  }
});

test('lost conversation creation survives reload and reuses identity before refreshing the real canvas',async()=>{
  const pendingStorage=storage();
  const first=setup({pendingStorage,get:()=>catalogReply(),post:()=>{throw new Error('response lost');}});
  await first.api.refreshConversationCatalog('workshop-a');
  await assert.rejects(createConversation(first.api),error=>error.creationUncertain===true);
  assert.equal(first.posts.length,1);
  const saved=[...pendingStorage.data.values()][0];
  assert.equal(saved.includes('Walls'),false);assert.equal(saved.includes('worker-a'),false);
  const original=first.posts[0].body.idempotency_key;
  const second=setup({pendingStorage,
    get:url=>url==='/api/universal/canvas'?createdCanvas():catalogReply({revision:5,conversations:[
      ...catalogReply().conversations,{root:'created-chat',title:'Walls',participant_roots:['owner-a','worker-a'],is_general:false}]}),
    post:(_url,body)=>({...newConversation(body),created:false,revision:5})});
  await second.api.refreshConversationCatalog('workshop-a');
  const result=await createConversation(second.api);
  assert.equal(second.posts[0].body.idempotency_key,original);
  assert.equal(second.posts[0].body.revision,5);
  assert.equal(result.accepted,true);assert.equal(result.canvas_refreshed,true);assert.equal(result.node_visible,true);
  assert.equal(second.gets.filter(url=>url==='/api/universal/canvas').length,1);
  assert.equal(second.api.getSnapshot().topology.canvas.nodes[1].id,'created-chat');
  assert.equal(second.api.getSnapshot().workshops[1].is_general,false);
  assert.equal(second.api.getSnapshot().workshops[1].native_work_available,false);
  assert.equal(Object.keys(JSON.parse([...pendingStorage.data.values()][0])).length,0);
});

test('creation uses the catalog while a child remains selected and coalesces the same request',async()=>{
  const pending=deferred(); const child={root:'child-chat',label:'Child'};
  const {api,posts}=setup({get:url=>{
    if(url==='/api/universal/canvas') return createdCanvas();
    if(new URL(url,'http://test').searchParams.has('catalog')) return catalogReply({revision:posts.length?5:4});
    return {...transcript(),root:child.root};
  },post:()=>pending.promise});
  api.setCanvas({...scope(),workshops:[...scope().workshops,child]});
  await api.refreshWorkshop(child.root); const held=api.getSnapshot().workshop;
  await api.refreshConversationCatalog('workshop-a');
  const first=createConversation(api),duplicate=createConversation(api);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(posts.length,1);assert.equal(api.getSnapshot().workshop,held);
  await assert.rejects(api.createConversation('workshop-a',{title:'Different',participant_roots:['owner-a']}),/Wait/);
  pending.resolve(newConversation(posts[0].body));
  assert.equal((await first).accepted,true);assert.equal((await duplicate).accepted,true);
  assert.equal(posts.length,1);
});

test('accepted creation keeps success when projection fails and an unverified receipt retains retry identity',async()=>{
  const good=setup({get:url=>{
    if(url==='/api/universal/canvas') throw new Error('canvas unavailable');
    return catalogReply();
  },post:(_url,body)=>newConversation(body)});
  await good.api.refreshConversationCatalog('workshop-a');
  good.api.subscribe(()=>{throw new Error('presentation failed');});
  const result=await createConversation(good.api);
  assert.equal(result.accepted,true);assert.equal(result.canvas_refreshed,false);
  assert.equal(good.posts.length,1);assert.equal(good.api.getSnapshot().conversationCreation.requires_refresh,true);
  assert.equal(Object.keys(JSON.parse([...good.pendingStorage.data.values()][0])).length,0);
  const bad=setup({get:()=>catalogReply(),post:(_url,body)=>({...newConversation(body),idempotency_key:'different'})});
  await bad.api.refreshConversationCatalog('workshop-a');
  await assert.rejects(createConversation(bad.api),error=>error.creationUncertain===true);
  assert.equal(Object.keys(JSON.parse([...bad.pendingStorage.data.values()][0])).length,1);
  assert.equal(bad.gets.some(url=>url==='/api/universal/canvas'),false);
});

test('navigation during creation canvas refresh cannot overwrite the new workspace',async()=>{
  const pending=deferred();
  const {api,gets}=setup({get:url=>url==='/api/universal/canvas'?pending.promise:catalogReply(),
    post:(_url,body)=>newConversation(body)});
  await api.refreshConversationCatalog('workshop-a');
  const request=createConversation(api);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(gets.includes('/api/universal/canvas'),true);
  api.setCanvas(scope('scope-b',6));
  pending.resolve(createdCanvas());
  const result=await request;
  assert.equal(result.accepted,true);assert.equal(result.navigated,true);
  assert.equal(api.getSnapshot().canvas.root,'scope-b');assert.equal(api.getSnapshot().topology,null);
});

test('catalog creation permission and UTF-8 title budget reject before submission',async()=>{
  const denied=setup({get:()=>catalogReply({can_create:false})});
  await denied.api.refreshConversationCatalog('workshop-a');
  await assert.rejects(createConversation(denied.api),/does not admit/);assert.equal(denied.posts.length,0);
  const bounded=setup({get:()=>catalogReply()});
  await bounded.api.refreshConversationCatalog('workshop-a');
  await assert.rejects(bounded.api.createConversation('workshop-a',{
    title:'\ud83d\udfe5'.repeat(129),participant_roots:['owner-a']}),/512 UTF-8/);
  await assert.rejects(bounded.api.createConversation('workshop-a',{
    title:'Walls',participant_roots:['worker-a']}),/including the owner/);
  assert.equal(bounded.posts.length,0);
});

test('removing and restoring an anchor or changing authenticated view cannot revive pending catalog authority',async()=>{
  const pending=deferred();
  const {api,posts,gets}=setup({get:()=>catalogReply(),post:()=>pending.promise});
  await api.refreshConversationCatalog('workshop-a');
  const writing=createConversation(api);
  await new Promise(resolve=>setImmediate(resolve));
  api.setCanvas({...scope(),workshops:[]});api.setCanvas(scope());
  pending.resolve(newConversation(posts[0].body));
  assert.equal((await writing).navigated,true);
  assert.equal(gets.includes('/api/universal/canvas'),false);
  const slow=deferred();
  const other=setup({get:()=>slow.promise});
  other.api.setTopologyCanvas(createdCanvas(4));
  const reading=other.api.refreshConversationCatalog('workshop-a');
  other.api.setTopologyCanvas({...createdCanvas(4),authorization:{subject:'another-owner',session:'another-view'}});
  slow.resolve(catalogReply());
  assert.equal(await reading,null);assert.equal(other.api.getSnapshot().conversationCatalog,null);
});

const agentRow = {root:'app:agent-session:runtime:' + 'c'.repeat(32), label:'Codex', attached:true, is_agent:true, session_link:'attached'};
const withAgent = () => ({...transcript(), participants:[...transcript().participants, agentRow]});
const disconnected = body => ({ok:true, graph_id:'graph-a', root:body.root, scope_root:body.scope, agent:body.agent,
  revision:body.revision, outcome:'revoked', session_link:'none',
  disconnect:{status:'ok', detached:true, revoked:true, local_call_joined:true, worker_stopped:true}});
test('agent disconnect posts the exact browser body and returns the reconciled outcome',async()=>{
  const {api,posts}=setup({get:withAgent, post:(url,body)=>disconnected(body)});
  await api.refreshWorkshop('workshop-a');
  const result=await api.disconnectAgent('workshop-a',agentRow.root);
  assert.deepEqual(plain(posts.map(row=>[row.url,row.body])),[['/api/universal/workshop',
    {action:'agent-disconnect',root:'workshop-a',scope:'scope-a',revision:4,agent:agentRow.root}]]);
  assert.deepEqual(plain(result),{outcome:'revoked',session_link:'none',
    disconnect:{status:'ok',detached:true,revoked:true,local_call_joined:true,worker_stopped:true}});
});
test('agent disconnect never reports a revocation the grant did not confirm',async()=>{
  const changes=[
    {disconnect:{status:'ok',detached:true,revoked:false,local_call_joined:true,worker_stopped:true}},
    {disconnect:{status:'uncertain',detached:false,revoked:false,local_call_joined:false,worker_stopped:false}},
    {outcome:'gone'}, {session_link:'maybe'}, {agent:'app:agent-session:runtime:' + 'd'.repeat(32)},
    {disconnect:{status:'ok',detached:'yes',revoked:true,local_call_joined:true,worker_stopped:true}}];
  for (const change of changes) {
    const {api}=setup({get:withAgent, post:(url,body)=>({...disconnected(body),...change})});
    await api.refreshWorkshop('workshop-a');
    await assert.rejects(api.disconnectAgent('workshop-a',agentRow.root),/could not be reconciled/);
  }
  const {api}=setup({get:withAgent, post:(url,body)=>({...disconnected(body),outcome:'uncertain',session_link:'retiring',
    disconnect:{status:'uncertain',detached:false,revoked:false,local_call_joined:false,worker_stopped:false}})});
  await api.refreshWorkshop('workshop-a');
  assert.deepEqual(plain(await api.disconnectAgent('workshop-a',agentRow.root)),{outcome:'uncertain',session_link:'retiring',
    disconnect:{status:'uncertain',detached:false,revoked:false,local_call_joined:false,worker_stopped:false}});
});
test('agent disconnect needs a current participant and surfaces a refused request',async()=>{
  const {api,posts}=setup({get:withAgent, post:()=>({ok:false,error:'Agent is not a participant of this Workshop'})});
  await api.refreshWorkshop('workshop-a');
  await assert.rejects(api.disconnectAgent('workshop-a','app:agent-session:runtime:' + 'e'.repeat(32)),/Refresh the Workshop/);
  await assert.rejects(api.disconnectAgent('workshop-a','owner-a'),/Choose an agent/);
  assert.equal(posts.length,0);
  await assert.rejects(api.disconnectAgent('workshop-a',agentRow.root),/not a participant/);
});

test('local social removal checks exact identity and never claims provider revocation',async()=>{
  const body={provider:'linkedin',account_id:'urn:li:person:synthetic',vault_entry:'social-studio'};
  const {api,posts}=setup({post:()=>({...body,ok:true,state:'removed',provider_token_revoked:false,
    graph_reference_retained:true,revision:4})});
  const result=await api.removeLocalSocialAccount(body);
  assert.deepEqual(plain(posts.map(row=>[row.url,row.body])),[['/api/universal/social-credential-remove',body]]);
  assert.equal(result.provider_token_revoked,false);
  for(const changed of [{account_id:'another'},{provider_token_revoked:true},{state:'uncertain'},{graph_reference_retained:'yes'}]){
    const {api:bad}=setup({post:()=>({...body,ok:true,state:'removed',provider_token_revoked:false,
      graph_reference_retained:true,revision:4,...changed})});
    await assert.rejects(bad.removeLocalSocialAccount(body),/could not be confirmed/);
  }
});
