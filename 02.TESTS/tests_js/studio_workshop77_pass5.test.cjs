/* Real component + real authority adapters; HTTP and host state are fakes only. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {fixture}=require('./workshop72_fixture.cjs');
const {mounted,transport,plain,text,read}=require('./workshop72_regression_helpers.cjs');

async function workshopAuthority(kind,{refuse=false}={}) {
  const f=fixture(),receipts=[];
  if(kind==='workflow') {f.state.nativeWork=null;f.state.workshop.workflows[0].approval={current:false};}
  if(kind==='proposal') {
    f.state.nativeWork=null;f.state.workshop.workflows=[];
    f.state.workshop.messages=[{root:'proposal-real',message_id:'proposal-real',sequence:1,sender_root:'agent-a',
      body:'ArchHub work proposal v1\n'+JSON.stringify({title:'Review selected labels',description:'Only update the reviewed labels.',purpose:'general',priority:0,
        container:{container_id:'wip'},write_grants:[{path:'model',scope:'selection',operations:['write']}]})}];
  }
  let native={...f.state.nativeWork,ok:true,root:'room-a',scope:'scope-a',owner:'owner-a',view:'view-a',state:kind==='native'?'awaiting_approval':'idle',
    request_id:'native-request',worker:'worker-a'};
  const t=transport({get:async(url,transcript)=>url.startsWith('/api/universal/workshop-native?')?native:transcript,
    post:async(url,body)=>{
      let result;
      if(body.action==='workflow-approve') result={ok:!refuse,workflow:body.workflow,digest:body.digest,approval:{current:true},revision:5};
      else if(body.action==='approve_native') result=refuse?{...native,input_digest:'wrong'}:{...native,approved:true};
      else {
        const common={ok:true,root:body.root,scope:body.scope,owner:'owner-a',request_id:body.request_id,revision:5};
        if(body.action==='read_work_proposals') result={...common,bound:{'proposal-real':null},declined:{'proposal-real':null}};
        else if(body.action==='bind_work_proposals') result={...common,bound:body.proposals.map(row=>({...row,proposer:'agent-a',work_root:'work:bound',
          external_key:'proposal:'+row.message_id,authorization:refuse?'':'permit-real'}))};
        else throw new Error('Unexpected approval HTTP action '+url+' '+body.action);
      }
      receipts.push({url,action:body.action,result:plain(result)});return result;
    }});
  Object.assign(t.transcript,f.state.workshop,{ok:true,graph_id:'graph-a',scope_root:'scope-a',revision:4,owner:'owner-a',view:'view-a'});
  await t.api.refreshWorkshop('room-a');await t.api.refreshNativeWork('room-a');
  // Mount the same source snapshot; decisions still use the production adapter, not a callback spy.
  f.state.nativeWork=kind==='native'?native:f.state.nativeWork;
  const ui=await mounted(f.state,t.api,{sel:{agent:null,task:kind==='workflow'?'flow-a':kind==='proposal'?'proposal:proposal-real':f.work}});
  return {ui,t,receipts};
}

for(const kind of ['workflow','proposal','native'])test('PASS5 '+kind+' label matches approval-only HTTP action and confirmed receipt',async()=>{
  const {ui,t,receipts}=await workshopAuthority(kind);
  try {
    const button=ui.doc.querySelector('[data-workshop-primary=approve]');assert.ok(button);assert.equal(text(button),'Approve');
    await ui.act(()=>{button.click();button.click();});await ui.render();
    const action={workflow:'workflow-approve',proposal:'bind_work_proposals',native:'approve_native'}[kind];
    const posts=t.posts.filter(row=>row.body.action===action);assert.equal(posts.length,1);
    assert.equal(posts[0].url,kind==='workflow'?'/api/universal/workshop':'/api/universal/workshop-native');
    const receipt=receipts.find(row=>row.action===action).result;
    if(kind==='workflow') {assert.equal(receipt.approval.current,true);assert.equal(receipt.digest,posts[0].body.digest);}
    if(kind==='proposal') {assert.equal(receipt.bound[0].authorization,'permit-real');assert.equal(receipt.bound[0].work_root,'work:bound');}
    if(kind==='native') {assert.equal(receipt.approved,true);assert.equal(receipt.input_digest,posts[0].body.input_digest);assert.equal(receipt.worker,'worker-a');}
    assert.equal(ui.doc.querySelector('[role=alert]'),null);
    assert.equal(t.posts.some(row=>/execute|workflow-run|run_native|post$/.test(row.body.action)),false,'approval does not dispatch execution');
  } finally {await ui.close();}
});

for(const kind of ['workflow','proposal','native'])test('PASS5 '+kind+' rejected HTTP receipt leaves Approve retryable',async()=>{
  const {ui,t}=await workshopAuthority(kind,{refuse:true});
  try {
    await ui.click(ui.button('Approve'));
    assert.ok(ui.doc.querySelector('[role=alert]'));assert.equal(ui.button('Approve').disabled,false);
    assert.equal(t.posts.some(row=>/execute|workflow-run/.test(row.body.action)),false);
  } finally {await ui.close();}
});

async function waitingAuthority(kind,{refuse=false}={}) {
  const {JSDOM}=await import('jsdom');
  const dom=new JSDOM('<div id="root"></div>',{url:'http://127.0.0.1/',runScripts:'outside-only',pretendToBeVisual:true}),win=dom.window;
  const posts=[],receipts=[];
  const item={id:'waiting-real',producer:kind==='social'?'social_approve':'host_write',delegation:'delegation-real',input_digest:'d'.repeat(64),summary:'Review this prepared change'};
  const t=transport({post:async(url,body)=>{
    const result={ok:true,delegation:body.delegation,input_digest:body.input_digest,decision:refuse?'denied':'approved'};
    receipts.push(result);return result;
  }});
  win.fetch=async(url,options)=>{
    posts.push({url,body:JSON.parse(options.body)});
    const result={ok:!refuse,approved:!refuse,delegation:item.delegation,work:'work:reviewed',revision:5};receipts.push(result);
    return {ok:!refuse,json:async()=>result};
  };
  win.ARCHHUB_EXISTING_WORKSHOP=t.api;
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  const manifest=JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  for(const entry of manifest.files.filter(row=>row.source!=='mount.jsx')) {
    let source=read('01.APP/nodelang/studio/compiled/'+entry.output);
    if(entry.source==='studio-lm.jsx') source=source.replace(/window\.StudioLM\s*=\s*StudioLM\s*;/,'window.StudioLM = StudioLM; window.__pass5Waiting = WaitingButton;');
    win.eval(source);
  }
  const root=win.ReactDOM.createRoot(win.document.getElementById('root'));
  win.ReactDOM.flushSync(()=>root.render(win.React.createElement(win.__pass5Waiting,{items:[item],variant:'home'})));
  const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>win.setTimeout(resolve,0));};
  const click=async el=>{win.ReactDOM.flushSync(()=>el.click());await settle();};
  await click(win.document.querySelector('[data-waiting-trigger]'));
  return {win,doc:win.document,t,posts,receipts,click,close:()=>{win.ReactDOM.flushSync(()=>root.unmount());win.close();}};
}

for(const kind of ['social','host'])test('PASS5 '+kind+' shared surface label matches real HTTP route and approval receipt',async()=>{
  const ui=await waitingAuthority(kind);
  try {
    const button=ui.doc.querySelector('[data-workshop-primary=approve]');assert.equal(text(button),'Approve');
    await ui.click(button);await ui.click(button);
    if(kind==='social') {
      assert.deepEqual(plain(ui.t.posts),[{url:'/api/universal/social-approve',body:{delegation:'delegation-real',input_digest:'d'.repeat(64),decision:'approve'}}]);
      assert.equal(ui.receipts[0].decision,'approved');assert.equal(ui.receipts[0].input_digest,'d'.repeat(64));
    } else {
      assert.deepEqual(ui.posts,[{url:'/api/universal/connector-delegation-approve',body:{delegation:'delegation-real'}}]);
      assert.equal(ui.receipts[0].approved,true);assert.equal(ui.receipts[0].work,'work:reviewed');assert.equal(ui.receipts[0].revision,5);
    }
    assert.equal(ui.receipts.length,1);assert.equal(ui.receipts[0].delegation,'delegation-real');
    assert.equal(ui.doc.querySelector('[role=alert]'),null);assert.equal(button.disabled,true);
  } finally {ui.close();}
});

for(const kind of ['social','host'])test('PASS5 '+kind+' refused HTTP approval does not claim delivery',async()=>{
  const ui=await waitingAuthority(kind,{refuse:true});
  try {
    await ui.click(ui.doc.querySelector('[data-workshop-primary=approve]'));
    assert.ok(ui.doc.querySelector('[role=alert]'));assert.equal(ui.doc.querySelector('[data-workshop-primary=approve]').disabled,false);
    assert.doesNotMatch(ui.doc.body.textContent,/approved · delivered/);
  } finally {ui.close();}
});

test('PASS5 every approval caller supplies the label for its current approval-only authority',()=>{
  for(const file of ['studio-workshop.jsx','studio-mobile.jsx','studio-lm.jsx','workshop-board.jsx']) {
    const source=read('01.APP/nodelang/studio/'+file);assert.match(source,/approveLabel[=:]\s*['"]Approve['"]/);
    assert.doesNotMatch(source,/approveLabel[=:]\s*['"]Approve and run['"]/);
  }
});
