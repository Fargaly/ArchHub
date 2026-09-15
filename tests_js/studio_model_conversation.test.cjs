/* Real browser-owner callbacks in memory; no provider, app or database. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-existing-workshop.js'),'utf8');
const jsx = fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-lm.jsx'),'utf8');
const agent = {root:'agent-a',model:'openrouter/model-a',binding_digest:'a'.repeat(64)};
const scope = root => ({graph_id:'graph-a',root,revision:4,workshops:[{root:'child-a',label:'My session'}]});
const page = () => ({ok:true,graph_id:'graph-a',root:'child-a',scope_root:'scope-a',revision:4,
  owner:'owner-a',view:'view-a',self:'owner-a',can_send:true,participants:[],messages:[],
  storage:'conversation-content',content_cursor:'cursor-a',page_before:null,next_before:null,total:0,
  has_older:false,model_agent:{...agent}});
const receipt = body => ({ok:true,graph_id:'graph-a',root:body.root,scope_root:body.scope,
  node:body.node,binding_digest:body.binding_digest,message_id:'user-message',
  idempotency_key:body.idempotency_key,revision:5,delivery:{state:'replied',reply_message_id:'reply-message'}});
function fixture(options={}) {
  const context=vm.createContext({URLSearchParams,TextEncoder});vm.runInContext(source,context);
  const saved=options.saved || new Map(),posts=[];let sequence=0;
  const api=context.ArchHubExistingWorkshop.create({
    hash:options.hash || (async value=>createHash('sha256').update(value).digest('hex')),
    uuid:()=>`turn-${++sequence}`,pendingStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)},
    get:async url=>options.get ? options.get(url) : page(),
    post:async(url,body)=>{posts.push({url,body});return options.post ? options.post(body) : receipt(body);}});
  api.setCanvas(scope('scope-a'));
  return {api,posts,saved,prepare:()=>api.refreshWorkshop('child-a'),
    send:(selected=agent)=>api.sendModelConversation('child-a',selected,'Continue this actual task'),
    pending:()=>JSON.parse(saved.get('archhub.existing-workshop.pending.v1')||'{}')};
}
test('ongoing model message uses the saved node binding and explicit owner action',async()=>{
  const f=fixture();await f.prepare();const result=await f.send();
  assert.equal(result.accepted,true);assert.equal(f.posts[0].url,'/api/universal/workshop');
  assert.deepEqual(JSON.parse(JSON.stringify(f.posts[0].body)),{action:'send-model',root:'child-a',scope:'scope-a',
    node:agent.root,binding_digest:agent.binding_digest,prompt:'Continue this actual task',idempotency_key:'turn-1'});
  assert.deepEqual(f.pending(),{});
});
test('lookalike node or changed route cannot reuse the read binding',async()=>{
  for (const changed of [{root:'agent-b'},{model:'other-model'},{binding_digest:'b'.repeat(64)}]) {
    const f=fixture();await f.prepare();await assert.rejects(f.send({...agent,...changed}),/Refresh/);
    assert.equal(f.posts.length,0);
  }
});
test('not-called failure preserves the prompt identity for a corrected retry',async()=>{
  let refused=true;const f=fixture({post:body=>refused ? {...receipt(body),delivery:{state:'not_sent',
    provider_not_called:true,message:'Add your provider key.'}} : receipt(body)});
  await f.prepare();await assert.rejects(f.send(),/Add your provider key/);
  assert.equal(Object.keys(f.pending()).length,1);refused=false;await f.send();
  assert.equal(f.posts[0].body.idempotency_key,f.posts[1].body.idempotency_key);
  assert.deepEqual(f.pending(),{});
});
test('unknown result survives reopen and never sends again automatically',async()=>{
  const post=body=>({...receipt(body),delivery:{state:'already_recorded'}});
  const f=fixture({post});await f.prepare();await assert.rejects(f.send(),/same request/);
  assert.equal(f.posts.length,1);
  const reopened=fixture({post,saved:f.saved});await reopened.prepare();
  assert.equal(reopened.posts.length,0);await assert.rejects(reopened.send(),/same request/);
  assert.equal(f.posts[0].body.idempotency_key,reopened.posts[0].body.idempotency_key);
});
test('cross-scope or malformed success remains unconfirmed and retains recovery',async()=>{
  for (const field of ['graph_id','root','scope_root','node','binding_digest','message_id','idempotency_key','revision']) {
    const f=fixture({post:body=>{const result=receipt(body);delete result[field];return result;}});
    await f.prepare();await assert.rejects(f.send(),/unconfirmed/);
    assert.equal(Object.keys(f.pending()).length,1);
  }
});
test('navigation during identity preparation prevents dispatch',async()=>{
  let resolve;const held=new Promise(r=>{resolve=r;});const f=fixture({hash:()=>held});await f.prepare();
  const sent=f.send();f.api.setCanvas(scope('scope-b'));resolve('c'.repeat(64));
  await assert.rejects(sent,/changed/);assert.equal(f.posts.length,0);
});
test('concurrent identical sends share the one request',async()=>{
  let resolve;const held=new Promise(r=>{resolve=r;});const f=fixture({post:()=>held});await f.prepare();
  const a=f.send(),b=f.send();await new Promise(setImmediate);assert.equal(f.posts.length,1);
  resolve(receipt(f.posts[0].body));await Promise.all([a,b]);
});
test('unchanged history refresh still updates or removes the graph model binding',async()=>{
  let current=page();const f=fixture({get:()=>current});await f.prepare();
  current={...page(),unchanged:true,model_agent:{...agent,model:'updated-model',binding_digest:'b'.repeat(64)}};
  await f.prepare();assert.equal(f.api.getSnapshot().workshop.model_agent.model,'updated-model');
  await assert.rejects(f.send(),/Refresh/);assert.equal(f.posts.length,0);
  current={...current,model_agent:null};await f.prepare();assert.equal(f.api.getSnapshot().workshop.model_agent,null);
});
test('malformed projected model metadata cannot be sent',async()=>{
  const f=fixture({get:()=>({...page(),model_agent:{...agent,binding_digest:'invalid'}})});
  await assert.rejects(f.prepare(),/binding is invalid/);await assert.rejects(f.send(),/Refresh/);
  assert.equal(f.posts.length,0);
});
test('visible Send dispatches to selected model and preserves draft after refusal',async()=>{
  const component=jsx.indexOf('const WorkshopConversation =');
  const start=jsx.indexOf('  const act = async (action) => {',component),end=jsx.indexOf('\n  return <>',start);
  assert.ok(start>component && end>start);
  for (const rejected of [false,true]) {
    const calls=[],clears=[],errors=[];
    const context=vm.createContext({busyRef:{current:false},editorsReady:true,setBusy:()=>{},setActionError:value=>errors.push(value),
      target:'model:'+agent.root,draft:'actual text',execution:'',contactTarget:null,modelTarget:agent,
      authority:{sendModelConversation:async(...args)=>{calls.push(args);if(rejected)throw Error('not called');}},
      descriptor:{root:'child-a'},protectedEditors:false,editors:{current:{}},mounted:{current:true},setDraft:value=>clears.push(value)});
    vm.runInContext(jsx.slice(start,end)+'\nglobalThis.send=act;',context);await context.send('send');
    assert.equal(calls.length,1);assert.equal(calls[0][0],'child-a');assert.equal(calls[0][1],agent);
    assert.deepEqual(clears,rejected?[]:['']);if(rejected)assert.equal(errors.at(-1),'not called');
  }
});
