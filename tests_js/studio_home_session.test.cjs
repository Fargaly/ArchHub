/* Production callbacks in isolation; no DOM rendering, network, app or graph writes. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const adapter = fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-existing-workshop.js'),'utf8');
const jsx = fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-lm.jsx'),'utf8');
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const details = {prompt:'Build my actual task',model:'openrouter/model-a'};
function fixture(post) {
  const ctx=vm.createContext({URLSearchParams,TextEncoder});vm.runInContext(adapter,ctx);
  const posts=[],saved=new Map();let sequence=0;
  const api=ctx.ArchHubExistingWorkshop.create({
    hash:async value=>createHash('sha256').update(value).digest('hex'),uuid:()=>`start-${++sequence}`,
    pendingStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)},
    get:async()=>{throw Error('Unexpected read');},
    post:async(url,body)=>{posts.push({url,body});return post ? post(body) : receipt(body);}});
  const identity = session => api.setTopologyCanvas({application_root:'application-a',revision:1,
    authorization:{subject:'owner-a',session},scope:{current:'scope-a'},nodes:[],wires:[],
    interaction_projection:{revision:1,bindings:[]},
    workshop_scope:{graph_id:'graph-a',root:'scope-a',revision:1,workshops:[]}});
  identity('session-a');return {api,posts,saved,identity};
}
const receipt=body=>({ok:true,graph_id:'graph-a',root:'conversation-new',title:'My task',
  message_id:'message-new',idempotency_key:body.idempotency_key,revision:2,scope_path:['scope-a'],
  delivery:{state:'replied',node:'agent-a',reply_message_id:'reply-a'}});

test('saved Home session exposes provider refusal and retains its request identity',async()=>{
  const f=fixture(body=>({...receipt(body),delivery:{state:'not_sent',provider_not_called:true,message:'Add your provider key.'}}));
  const result=await f.api.startSession(details);
  assert.equal(result.accepted,true);assert.match(result.warning,/Add your provider key/);
  assert.equal(Object.keys(JSON.parse(f.saved.get('archhub.existing-workshop.pending.v1'))).length,1);
  await f.api.startSession(details);
  assert.equal(f.posts[0].body.idempotency_key,f.posts[1].body.idempotency_key);
});

test('Home never settles an incomplete model reply or unbound native delivery',async()=>{
  for (const fields of [{state:'replied'},{state:'replied',node:'agent-a'},
      {state:'replied',reply_message_id:'reply-a'},{state:'started',node:'agent-a'}]) {
    const f=fixture(body=>({...receipt(body),delivery:fields}));
    const result=await f.api.startSession(details);
    assert.equal(result.accepted,true);assert.match(result.warning,/not confirmed/);
    assert.equal(Object.keys(JSON.parse(f.saved.get('archhub.existing-workshop.pending.v1'))).length,1);
  }
  const f=fixture(body=>({...receipt(body),delivery:{state:'started'}}));
  const result=await f.api.startSession({prompt:'Review this',native:{app:'claude',session_id:'existing-session'}});
  assert.match(result.warning,/not confirmed/);
  assert.equal(Object.keys(JSON.parse(f.saved.get('archhub.existing-workshop.pending.v1'))).length,1);
});
test('Home model submission makes one existing Workshop request with real text',async()=>{
  const f=fixture();const result=await f.api.startSession(details);
  assert.equal(f.posts.length,1);assert.equal(f.posts[0].url,'/api/universal/workshop');
  assert.deepEqual(JSON.parse(JSON.stringify(f.posts[0].body)),{action:'start-session',...details,idempotency_key:'start-1'});
  assert.equal(result.accepted,true);assert.equal(result.navigation_current,true);
});
test('native selection sends exact environment and existing session without a model',async()=>{
  const f=fixture();await f.api.startSession({prompt:'Review this',native:{app:'claude',session_id:'existing-session',title:'Display only'}});
  assert.deepEqual(JSON.parse(JSON.stringify(f.posts[0].body.native)),{app:'claude',session_id:'existing-session'});
  assert.equal('model' in f.posts[0].body,false);
});
test('concurrent submissions share one admitted request',async()=>{
  const held=deferred(),f=fixture(()=>held.promise);
  const a=f.api.startSession(details),b=f.api.startSession(details);await new Promise(setImmediate);
  assert.equal(f.posts.length,1);held.resolve(receipt(f.posts[0].body));await Promise.all([a,b]);
});
test('lost receipt retains identity until explicit retry; no automatic second request',async()=>{
  let fail=true;const f=fixture(body=>{if(fail)throw Error('connection lost');return receipt(body);});
  await assert.rejects(f.api.startSession(details),/connection lost/);await new Promise(setImmediate);
  assert.equal(f.posts.length,1);fail=false;await f.api.startSession(details);
  assert.equal(f.posts[0].body.idempotency_key,f.posts[1].body.idempotency_key);
});
test('mismatched receipt stays unconfirmed and retains retry identity',async()=>{
  let wrong=true;const f=fixture(body=>({...receipt(body),graph_id:wrong?'other-graph':'graph-a'}));
  await assert.rejects(f.api.startSession(details),/unconfirmed/);wrong=false;await f.api.startSession(details);
  assert.equal(f.posts[0].body.idempotency_key,f.posts[1].body.idempotency_key);
});
test('truthy ok and nonstring title receipts are refused',async()=>{
  for(const changed of [{ok:'true'},{title:42}]) {
    const f=fixture(body=>({...receipt(body),...changed}));
    await assert.rejects(f.api.startSession(details),/unconfirmed/);
  }
});
test('authorization changes during request prohibit opening its saved result',async()=>{
  const held=deferred(),f=fixture(()=>held.promise);const pending=f.api.startSession(details);
  await new Promise(setImmediate);f.identity('session-b');held.resolve(receipt(f.posts[0].body));
  assert.equal((await pending).navigation_current,false);
});
function homeFixture() {
  const start=jsx.indexOf('  const startSession = async event =>',jsx.indexOf('const Home ='));
  const end=jsx.indexOf('\n\n  const [title',start);assert.ok(start>0&&end>start);
  const held=deferred(),opened=[],refs={startBusy:{current:false},acceptedSession:{current:null},homeMounted:{current:true}};
  let session='session-a',calls=0;
  const ctx=vm.createContext({...refs,draft:'Real prompt',native:null,model:{},modelRoute:()=>details.model,
    setPickerOpen:()=>{},setStarting:()=>{},setStartError:()=>{},setDraft:()=>{},
    onStarted:async result=>opened.push(result),window:{ARCHHUB_EXISTING_WORKSHOP:{
      getSnapshot:()=>({canvas:{graph_id:'graph-a'},topology:{canvas:{authorization:{subject:'owner-a',session}}}}),
      startSession:()=>{calls++;return held.promise;}}}});
  vm.runInContext(jsx.slice(start,end)+'\nglobalThis.submit=startSession;',ctx);
  return {held,opened,refs,submit:()=>ctx.submit({preventDefault(){}}),calls:()=>calls,changeAuth:()=>{session='session-b';}};
}
test('Home busy guard prevents double submit and unmounted Home never opens result',async()=>{
  const f=homeFixture();const pending=f.submit();await f.submit();assert.equal(f.calls(),1);
  f.refs.homeMounted.current=false;f.held.resolve({accepted:true});await pending;assert.equal(f.opened.length,0);
});
test('Home refuses a saved result after its authentication changed',async()=>{
  const f=homeFixture();const pending=f.submit();f.changeAuth();f.held.resolve({accepted:true});await pending;
  assert.equal(f.opened.length,0);
});
test('Home form and Enter invoke the same submission handler',()=>{
  const home=jsx.slice(jsx.indexOf('const Home ='));
  assert.match(home,/<form onSubmit=\{startSession\}/);
  assert.match(home,/<textarea[\s\S]*?onChange=\{event => setDraft\(event.target.value\)\}/);
  assert.match(home,/onKeyDown=\{event => \{if \(event.key === 'Enter'[\s\S]*?startSession\(event\)/);
  assert.match(home,/<button type="submit" disabled=\{starting \|\| !draft.trim\(\)\}/);
});
function studioFixture() {
  const start=jsx.indexOf('onStarted={async (result,');const end=jsx.indexOf('\n            }}/>}',start);
  assert.ok(start>0&&end>start);const callback=jsx.slice(start+'onStarted={'.length,end)+'\n}';
  const held=deferred(),refresh=deferred(),opened=[];let session='session-a',mounted=true;
  const ctx=vm.createContext({setOpenTabs:()=>opened.push('tabs'),setWorkspaceSelection:()=>opened.push('selection'),setOpenId:value=>opened.push(value),
    window:{ARCHHUB_SCOPE_OPEN:()=>held.promise,ARCHHUB_EXISTING_WORKSHOP:{refreshTopologyCanvas:()=>refresh.promise,
      getSnapshot:()=>({canvas:{graph_id:'graph-a',root:'scope-a'},workshops:[{root:'conversation-new'}],
        topology:{canvas:{authorization:{subject:'owner-a',session}}}})}}});
  vm.runInContext('globalThis.open='+callback,ctx);
  return {held,refresh,opened,changeAuth:()=>{session='session-b';},unmount:()=>{mounted=false;},
    open:()=>ctx.open(receipt({idempotency_key:'start-1'}),()=>mounted)};
}
test('Studio does not open a stale Home result if authentication changes during scope navigation',async()=>{
  const f=studioFixture();const pending=f.open();f.changeAuth();f.held.resolve();f.refresh.resolve();
  await assert.rejects(pending,/current view was kept/);assert.equal(f.opened.length,0);
});
test('Studio refuses unmounted Home continuation during topology refresh',async()=>{
  const f=studioFixture();const pending=f.open();f.held.resolve();await new Promise(setImmediate);
  f.unmount();f.refresh.resolve();await assert.rejects(pending,/current view was kept/);
  assert.equal(f.opened.length,0);
});
test('Studio current continuation opens the existing Workspace after both reads',async()=>{
  const f=studioFixture();const pending=f.open();f.held.resolve();f.refresh.resolve();await pending;
  assert.deepEqual(f.opened,['tabs','selection','graph-a']);
});
