/* Production adapter multi-room cache and authority behavior courts. */
const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/studio-existing-workshop.js'),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
const canvas=(session='session-a')=>({graph_id:'graph-a',root:'scope-a',revision:4,
  authorization:{subject:'owner-a',session},workshops:['room-a','room-b'].map(root=>({root,label:root}))});
const page=root=>({ok:true,graph_id:'graph-a',root,scope_root:'scope-a',revision:4,
  owner:'owner-a',view:'view-a',self:'owner-a',can_send:true,can_join:false,messages:[],assignments:[],
  participants:[{root:'worker-a',label:'Worker',attached:true,connected:true,state:'working'}]});
function setup(read,write=async()=>{throw Error('No writes admitted in cache court');}){
  const context=vm.createContext({URLSearchParams,TextEncoder});vm.runInContext(source,context);
  const requests=[];
  const api=context.ArchHubExistingWorkshop.create({get:async url=>{
    requests.push(url);const parsed=new URL(url,'http://court');
    if(parsed.pathname==='/api/universal/native-agents')return {status:'ok',rows:[],contacts:[]};
    return read(parsed.searchParams.get('root'),parsed);
  },post:write,uuid:()=> 'court-operation-a'});
  api.setCanvas(canvas());return {api,requests};
}

test('HOME3 background refresh caches both roots and unchanged presence/assignments',async()=>{
  let round=0;
  const {api,requests}=setup(root=>round===0?page(root):{graph_id:'graph-a',root,scope_root:'scope-a',revision:4,
    unchanged:true,participants:page(root).participants.map(row=>({...row,state:'waiting',connected:false})),
    assignments:[{work:'work-'+root,agent_session:'worker-a'}]});
  await api.refreshHomeWorkshops();
  const original=api.getSnapshot().workshopPages;
  assert.deepEqual(plain(original.map(row=>row.root)),['room-a','room-b']);
  assert.equal(api.getSnapshot().workshop,null,'background reads never choose a foreground conversation');
  round=1;await api.refreshHomeWorkshops();
  for(const row of api.getSnapshot().workshopPages){
    assert.equal(row.revision,4);assert.equal(row.participants[0].state,'waiting');
    assert.equal(row.participants[0].connected,false);
    assert.equal(row.assignments[0].work,'work-'+row.root);
    assert.equal(row.messages,original.find(held=>held.root===row.root).messages,'unchanged keeps admitted message identity');
  }
  assert.equal(requests.filter(url=>url.includes('open=1')).length,0,'refresh is never a navigation activity');
});

test('HOME3 background pending read cannot replace a foreground conversation opened meanwhile',async()=>{
  const pending=deferred();let wait=true;
  const {api}=setup(root=>root==='room-a'&&wait?pending.promise:page(root));
  const refresh=api.refreshHomeWorkshops();
  await api.openWorkshop('room-b');
  const selected=api.getSnapshot().workshop,selection=api.getSnapshot().workshopPage;
  assert.equal(selected.root,'room-b');
  wait=false;pending.resolve(page('room-a'));await refresh;
  assert.equal(api.getSnapshot().workshop,selected,'foreground page object is not overwritten');
  assert.equal(api.getSnapshot().workshopPage,selection,'foreground page cursor is not overwritten');
  assert.equal(api.getSnapshot().workshop.root,'room-b');
  assert.deepEqual(plain(api.getSnapshot().workshopPages.map(row=>row.root).sort()),['room-a','room-b']);
});

test('HOME3 denied owner is projected and authorization changes discard cached pages and late replies',async()=>{
  let deny=true;const pending=deferred();let hold=false;
  const {api}=setup(root=>{
    if(root==='room-a'&&deny)throw Error('Court owner read denied');
    if(root==='room-a'&&hold)return pending.promise;
    return page(root);
  });
  await api.refreshHomeWorkshops();
  assert.equal(api.getSnapshot().workshopErrors['room-a'],'Court owner read denied');
  assert.deepEqual(plain(api.getSnapshot().workshopPages.map(row=>row.root)),['room-b']);
  deny=false;await api.refreshHomeWorkshops();
  assert.deepEqual(plain(api.getSnapshot().workshopErrors),{});
  assert.equal(api.getSnapshot().workshopPages.length,2);
  hold=true;const refresh=api.refreshHomeWorkshops();
  api.setCanvas(canvas('session-b'));pending.resolve(page('room-a'));await refresh;
  assert.equal(api.getSnapshot().workshopPages.length,0,'old authentication cache and late owner reads are discarded');
  assert.deepEqual(plain(api.getSnapshot().workshopErrors),{});
  hold=false;await api.refreshHomeWorkshops();
  assert.equal(api.getSnapshot().workshopPages.length,2);
  api.setCanvas({...canvas('session-b'),root:'scope-b'});
  assert.equal(api.getSnapshot().workshopPages.length,0,'same-account scope changes discard prior owner pages');
  assert.deepEqual(plain(api.getSnapshot().nativeContacts),{},'contacts are scoped to the admitted canvas');
  assert.deepEqual(plain(api.getSnapshot().workshopErrors),{});
});

test('HOME3 unchanged content at a newer graph revision rereads workflow approval without changing the active cursor',async()=>{
  let approved=false;
  const {api,requests}=setup((root,url)=>{
    const before=url.searchParams.get('before');
    const ordinary={...page(root),revision:approved?5:4,storage:'conversation-content',feed:'all',
      content_cursor:'content cursor / '+(before||'latest'),page_before:before,
      next_before:before?null:'older cursor / 1',has_older:!before,total:2,
      messages:[{root:before?'message-1':'message-2',sequence:before?1:2,body:'Stored result',sender_root:'worker-a'}],
      workflows:[{root:'workflow-a',approval:{current:approved}}]};
    if(approved&&url.searchParams.has('after'))return {graph_id:ordinary.graph_id,root,
      scope_root:ordinary.scope_root,revision:5,storage:ordinary.storage,unchanged:true,
      content_cursor:ordinary.content_cursor,page_before:before};
    return ordinary;
  });
  await api.refreshWorkshop('room-a');
  await api.loadOlderWorkshop('room-a');
  const selected=api.getSnapshot().workshopPage;
  assert.equal(selected.before,'older cursor / 1');
  assert.equal(api.getSnapshot().workshop.workflows[0].approval.current,false);
  approved=true;await api.refreshWorkshop('room-a');
  assert.equal(api.getSnapshot().workshopPage,selected,'graph-only approval update preserves the selected older page');
  assert.equal(api.getSnapshot().workshop.workflows[0].approval.current,true);
  assert.equal(api.getSnapshot().workshop.revision,5);
  assert.equal(api.getSnapshot().workshop.page_before,'older cursor / 1');
  assert.equal(requests.length,4,'one initial page, one older page, one unchanged response, one bounded full reread');
  const conditional=new URL(requests[2],'http://court'),full=new URL(requests[3],'http://court');
  assert.equal(conditional.searchParams.get('after'),'4');
  assert.equal(conditional.searchParams.get('content_after'),'content cursor / older cursor / 1');
  assert.equal(full.searchParams.has('after'),false);assert.equal(full.searchParams.has('content_after'),false);
  assert.equal(full.searchParams.get('before'),'older cursor / 1');
});

test('HOME3 a late foreground reply adopts a newer background approval instead of keeping the selected page stale',async()=>{
  const delayed=deferred();let pendingNext=false,approved=false;
  const result=root=>({...page(root),revision:approved?5:4,
    workflows:[{root:'workflow-a',approval:{current:approved}}]});
  const {api}=setup(root=>{
    if(root==='room-a'&&pendingNext){pendingNext=false;return delayed.promise;}
    return result(root);
  });
  await api.refreshWorkshop('room-a');
  pendingNext=true;const foreground=api.refreshWorkshop('room-a');
  const older=result('room-a');approved=true;
  await api.refreshHomeWorkshops();
  assert.equal(api.getSnapshot().workshopPages.find(row=>row.root==='room-a').revision,5);
  assert.equal(api.getSnapshot().workshop.revision,5,'background updates an already selected matching page immediately');
  assert.equal(api.getSnapshot().workshop.workflows[0].approval.current,true);
  delayed.resolve(older);const accepted=await foreground;
  assert.equal(accepted.revision,5,'caller receives the newer admitted cache');
  assert.equal(api.getSnapshot().workshop.revision,5,'selected page receives the same newer admitted cache');
  assert.equal(api.getSnapshot().workshop.workflows[0].approval.current,true);
});

test('HOME3 refresh coalesces and caches only current native contacts',async()=>{
  const first=deferred(), discovery=deferred(), requests=[];
  const context=vm.createContext({URLSearchParams,TextEncoder});vm.runInContext(source,context);
  const api=context.ArchHubExistingWorkshop.create({get:async url=>{
    requests.push(url);
    const parsed=new URL(url,'http://court');
    if(parsed.pathname==='/api/universal/native-agents')return discovery.promise;
    return first.promise;
  }});
  api.setCanvas({...canvas(),workshops:[canvas().workshops[0]]});
  const a=api.refreshHomeWorkshops(),b=api.refreshHomeWorkshops();
  assert.equal(requests.length,1,'one owner read while refresh is pending');
  first.resolve(page('room-a'));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.length,2,'one contacts discovery for the root');
  discovery.resolve({status:'ok',rows:[],contacts:[{root:'contact-a',label:'Codex',connected:true}]});
  await Promise.all([a,b]);
  assert.equal(api.getSnapshot().nativeContacts['room-a'][0].root,'contact-a');
  api.setCanvas({...canvas('new-session'),workshops:[]});
  assert.deepEqual(plain(api.getSnapshot().nativeContacts),{});
});

test('HOME3 a new authentication refresh is not trapped behind the previous session pending read',async()=>{
  const pending=deferred();let hold=true;
  const {api}=setup(root=>hold?pending.promise:page(root));
  const stale=api.refreshHomeWorkshops();api.setCanvas(canvas('session-b'));hold=false;
  await api.refreshHomeWorkshops();assert.equal(api.getSnapshot().workshopPages.length,2);
  const currentPages=api.getSnapshot().workshopPages;
  pending.resolve(page('room-a'));await stale;
  assert.deepEqual(plain(api.getSnapshot().workshopPages),plain(currentPages));
});

test('HOME3 a new canvas revision starts its own refresh while an older page read is pending',async()=>{
  const pending=deferred();let rev=4,hold=true;
  const {api,requests}=setup(root=>hold?pending.promise:{...page(root),revision:rev});
  const stale=api.refreshHomeWorkshops();
  rev=5;hold=false;api.setCanvas({...canvas(),revision:rev});
  await api.refreshHomeWorkshops();
  assert.equal(requests.filter(url=>url.startsWith('/api/universal/workshop?')).length,3,'new revision requests both roots independently');
  assert.deepEqual(plain(api.getSnapshot().workshopPages.map(row=>row.revision)),[5,5]);
  pending.resolve(page('room-a'));await stale;
  assert.deepEqual(plain(api.getSnapshot().workshopPages.map(row=>row.revision)),[5,5],'late old canvas reply never replaces current pages');
  assert.deepEqual(plain(api.getSnapshot().workshopErrors),{});
});

test('HOME3 topology revision also fences pending refresh without treating page acceptance as a canvas event',async()=>{
  const pending=deferred();let rev=4,hold=true;
  const {api,requests}=setup(root=>hold?pending.promise:{...page(root),revision:rev});
  api.setTopologyCanvas(topology(4));const stale=api.refreshHomeWorkshops();
  rev=5;hold=false;api.setTopologyCanvas(topology(5));
  await api.refreshHomeWorkshops();
  pending.resolve(page('room-a'));await stale;
  assert.deepEqual(plain(api.getSnapshot().workshopPages.map(row=>row.revision)),[5,5]);
  assert.equal(api.getSnapshot().canvas.revision,4,'page acceptance leaves the admitted scope revision unchanged');
  assert.equal(api.getSnapshot().topology.canvas.revision,5);
  assert.equal(requests.filter(url=>url.startsWith('/api/universal/workshop?')).length,3);
});

test('HOME3 cached multi-room package approval and execution preserve the selected conversation',async()=>{
  let rev=4;const posts=[];
  const {api}=setup(root=>({...page(root),revision:rev}),async(url,body)=>{
    if(body.action==='workflow-execute')assert.deepEqual(Object.keys(body).sort(),['action','idempotency_key','root','scope','workflow']);
    posts.push({url,body:plain(body)});return {ok:true,revision:++rev};
  });
  await api.refreshHomeWorkshops();await api.openWorkshop('room-b');
  const selected=api.getSnapshot().workshop,selection=api.getSnapshot().workshopPage;
  const details={workflow:'workflow-a',digest:'a'.repeat(64)};
  const approved=await api.workshopWorkflow('room-a','workflow-approve',details);
  assert.equal(approved.navigation_current,true);
  assert.equal(api.getSnapshot().workshopPages.find(row=>row.root==='room-a').revision,5);
  await api.workshopWorkflow('room-a','workflow-execute',{workflow:details.workflow});
  assert.deepEqual(posts.map(row=>row.body.action),['workflow-approve','workflow-execute']);
  assert.equal(posts[0].body.root,'room-a');assert.equal(posts[0].body.revision,4);
  assert.equal(posts[1].body.root,'room-a');assert.ok(posts[1].body.idempotency_key);
  assert.equal(api.getSnapshot().workshop,selected);assert.equal(api.getSnapshot().workshopPage,selection);
  assert.equal(api.getSnapshot().workshopPages.find(row=>row.root==='room-a').revision,6);
});

test('HOME3 cached workflow authority is discarded on auth change and late approval carries a stale-view receipt',async()=>{
  const pending=deferred();let writes=0;
  const {api}=setup(page,async()=>{writes++;return pending.promise;});
  await api.refreshHomeWorkshops();
  const approval=api.workshopWorkflow('room-a','workflow-approve',{workflow:'workflow-a',digest:'a'.repeat(64)});
  api.setCanvas(canvas('session-b'));pending.resolve({ok:true,revision:5});
  assert.equal((await approval).navigation_current,false);
  await assert.rejects(api.workshopWorkflow('room-a','workflow-execute',{workflow:'workflow-a'}),/Refresh this conversation/);
  assert.equal(writes,1);assert.equal(api.getSnapshot().workshopPages.length,0);
});

test('HOME3 workflow approval uses latest cache revision over selected older-history authority',async()=>{
  let rev=4;const posts=[];
  const {api}=setup((root,url)=>{
    const before=url.searchParams.get('before');
    return {...page(root),revision:rev,storage:'conversation-content',feed:'all',content_cursor:'cursor-'+(before||'latest'),
      page_before:before,next_before:before?null:'older',has_older:!before,total:1,
      messages:[{root:'message-'+(before||'latest'),sequence:before?1:2,body:'Stored message'}]};
  },async(url,body)=>{posts.push(plain(body));rev++;return {ok:true,revision:rev};});
  await api.refreshWorkshop('room-a');await api.loadOlderWorkshop('room-a');
  const cursor=api.getSnapshot().workshopPage;
  rev=5;await api.refreshHomeWorkshops();assert.equal(api.getSnapshot().workshop.revision,4);
  await api.workshopWorkflow('room-a','workflow-approve',{workflow:'workflow-a',digest:'a'.repeat(64)});
  assert.equal(posts[0].revision,5,'latest graph authority overrides the older selected page');
  assert.equal(api.getSnapshot().workshopPage,cursor,'workflow refresh preserves selected history cursor');
  assert.equal(api.getSnapshot().workshop.page_before,'older');assert.equal(api.getSnapshot().workshop.revision,6);
});

const template={id:'group-a',title:'Stored template',sub:'Saved workflow',children:[{engine:'watcher',title:'PDF sheets',params:{}}],child_count:1,run_count:7};
const topology=(rev=4,scope='scope-a')=>({ok:true,application_root:'graph-a',authorization:canvas().authorization,
  revision:rev,scope:{current:scope},nodes:[],wires:[],interaction_projection:{revision:rev,bindings:[]}});
function templateSetup(get,post){
  const context=vm.createContext({URLSearchParams,TextEncoder});vm.runInContext(source,context);
  const requests=[],posts=[];
  const api=context.ArchHubExistingWorkshop.create({get:async url=>{requests.push(url);return get(url);},
    post:async(url,body)=>{posts.push({url,body:plain(body)});return post(url,body);}});
  api.setCanvas(canvas());api.setTopologyCanvas(topology());return {api,requests,posts};
}

test('HOME3 template read uses the real catalogue and fences authorization changes',async()=>{
  const pending=deferred();let hold=false;
  const {api,requests}=templateSetup(()=>hold?pending.promise:{ok:true,templates:[template]});
  assert.deepEqual(plain(await api.readHomeTemplates()),{ok:true,templates:[template]});
  assert.equal(requests[0],'/api/universal/node-library?templates=1');
  hold=true;const read=api.readHomeTemplates();api.setCanvas(canvas('session-b'));
  pending.resolve({ok:true,templates:[template]});assert.equal(await read,null);
});

test('HOME3 template Start uses one admitted graph mutation and returns actual group children',async()=>{
  const pending=deferred();
  const {api,posts}=templateSetup(()=>topology(5),()=>pending.promise);
  const a=api.startHomeTemplate(template.id),b=api.startHomeTemplate(template.id);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(posts.length,1);
  assert.deepEqual(posts[0],{url:'/api/universal/node-create',body:{template:'group-a',expected_scope:'scope-a'}});
  pending.resolve({ok:true,root:'new-group',children:['child-a'],revision:5,title:template.title,template:template.id});
  const results=await Promise.all([a,b]);
  assert.equal(results[0].root,'new-group');assert.deepEqual(plain(results[0].children),['child-a']);
  assert.equal(results[0].accepted,true);assert.equal(results[0].navigation_current,true);
  assert.equal(api.getSnapshot().topology.canvas.revision,5);
});

test('HOME3 template acceptance survives navigation without repainting the new canvas or replaying Start',async()=>{
  const pending=deferred();
  const {api,requests,posts}=templateSetup(()=>{throw Error('Must not refresh another view');},()=>pending.promise);
  const start=api.startHomeTemplate(template.id);await new Promise(resolve=>setImmediate(resolve));
  api.setTopologyCanvas(topology(4,'scope-b'));
  pending.resolve({ok:true,root:'new-group',children:['child-a'],revision:5,title:template.title,template:template.id});
  const result=await start;assert.equal(result.accepted,true);assert.equal(result.navigation_current,false);
  assert.equal(api.getSnapshot().topology.canvas.scope.current,'scope-b');
  assert.equal(posts.length,1);assert.equal(requests.length,0);
});

test('HOME3 uncertain template response requires reconciliation and never replays the mutation',async()=>{
  const {api,posts}=templateSetup(()=>topology(4),()=>{throw Error('Court transport lost');});
  await assert.rejects(api.startHomeTemplate(template.id),/Court transport lost/);
  assert.equal(posts.length,1);assert.equal(api.getSnapshot().topology.requires_refresh,true);
});
