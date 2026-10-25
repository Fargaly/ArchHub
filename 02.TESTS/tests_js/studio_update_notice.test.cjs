/* Execute the compiled approved design in a DOM over the real API adapter.
   The lifecycle responses are isolated: no installed app, feed or user data is touched. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const UPDATE = '/api/universal/application-update';
const INSTALLED = 'installed-build', NEXT = 'next-build', PREVIOUS = 'previous-build';
const status = (state, extra = {}) => ({ok:true, current_build:INSTALLED, state,
  available_build:['ready','restarting'].includes(state) ? NEXT : null,
  detail:state === 'idle' ? 'Up to date' : state === 'ready' ? 'Verified download' : state,
  restart_supported:true, updated_from:null, updated_to:null, ...extra});
const pause = () => new Promise(resolve => setTimeout(resolve, 5));
const plain = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve}; };

test('failed Studio startup keeps its error visible and offers one explicit reload',async()=>{
  const dom=new JSDOM(read('01.APP/nodelang/studio/studio.html'));
  const doc=dom.window.document;
  const loader=[...doc.querySelectorAll('script:not([src])')].at(-1).textContent;
  let reloads=0,reads=0;
  try{
    await vm.runInNewContext(loader,{document:doc,window:{location:{reload(){reloads++;}}},
      fetch:async()=>{reads++;throw Error('Owner is unavailable');},
      location:{reload(){reloads++;}},TextDecoder});
    const failure=doc.querySelector('#studio-boot');
    assert.equal(failure.getAttribute('role'),'alert');
    assert.match(failure.textContent,/Owner is unavailable/);
    const retry=failure.querySelector('button');
    assert.ok(retry,'startup offers recovery');
    assert.equal(retry.textContent,'Retry opening ArchHub');
    assert.equal(reloads,0,'no automatic retry');
    retry.click();retry.click();
    assert.equal(reloads,1,'one explicit reload; double-click cannot replay');
    assert.equal(reads,1,'failed loader is not started again in the same document');
  }finally{dom.window.close();}
});

async function mount(server,{holdBootDelay=false}={}) {
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/',
    runScripts:'outside-only', pretendToBeVisual:true});
  const win=dom.window, posts=[],gets=[],deadlines=[];
  if(holdBootDelay){
    const schedule=win.setTimeout.bind(win);
    win.setTimeout=(callback,delay,...args)=>delay===500?0:schedule(callback,delay,...args);
  }
  // The application's existing owner-refresh timer is paused while hidden.
  Object.defineProperty(win.document,'hidden',{value:true});
  win.structuredClone=globalThis.structuredClone;
  win.crypto.randomUUID=require('node:crypto').randomUUID;
  win.ARCHHUB_BOOT={home_load_ms:60000,token:'isolated-session',csrf:'isolated-csrf'};
  win.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
  win.AbortSignal.timeout=ms=>{
    assert.equal(ms,15000);
    const controller=new win.AbortController();deadlines.push(controller);return controller.signal;
  };
  win.fetch=async(url,options={})=>{
    let data={ok:true};
    if(url==='/api/universal/canvas')data={root:'graph',nodes:[],wires:[],catalog:[],...(server.workshop?{scope:{current:'graph'},workshops:[{root:'workshop'}]}:{})};
    if(url==='/api/universal/cloud-session')data={ok:true,signed_in:false};
    if(url==='/api/universal/workshop'){
      const body=JSON.parse(options.body);
      data=server.workshop?await server.workshop(body):{ok:true,result:[]};
    }
    if(url==='/api/universal/gesture'&&server.gesture)data=await server.gesture(JSON.parse(options.body));
    if(url===UPDATE){
      const body=options.body&&JSON.parse(options.body);
      if(body)posts.push(body);else gets.push(url);
      const answer=Promise.resolve().then(()=>body?server.post(body):server.get());
      data=await new Promise((resolve,reject)=>{
        const aborted=()=>reject(options.signal.reason);
        if(options.signal?.aborted){aborted();return;}
        options.signal?.addEventListener('abort',aborted,{once:true});
        answer.then(resolve,reject).finally(()=>options.signal?.removeEventListener('abort',aborted));
      });
    }
    return {ok:data.ok!==false,status:data.ok===false?409:200,json:async()=>plain(data)};
  };
  win.ArchHubStudioAuthority={create:({get,post})=>({load:()=>get('/api/universal/canvas'),undo:()=>post('/api/universal/gesture',{undo:true}),redo:()=>post('/api/universal/gesture',{redo:true})})};
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  const manifest=JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  for(const file of manifest.files){
    win.eval(read('01.APP/nodelang/studio/compiled/'+file.output));
    if(file.source==='api.js')await win.ArchHubAPI.ready;
  }
  const settle=async(predicate,description)=>{
    for(let i=0;i<300&&!predicate();i++)await pause();
    assert.ok(predicate(),description);
  };
  const doc=win.document;
  const button=label=>[...doc.querySelectorAll('button')].find(b=>b.textContent.trim()===label)||null;
  const click=async node=>{assert.ok(node,'button exists');assert.equal(node.disabled,false);node.click();await pause();};
  try{
    await settle(()=>!!doc.querySelector('[aria-label="Main navigation"]'),'the compiled Home opens');
  }catch(error){dom.window.close();throw error;}
  const settings=async()=>{
    await click(doc.querySelector('[aria-label="Settings"]'));
    await settle(()=>!!doc.querySelector('[data-screen="settings/Account"]'),'Account opens');
    const updates=[...doc.getElementsByTagName('button')].find(b=>b.getAttribute('aria-label')==='Updates & About');
    await click(updates);
    await settle(()=>[...doc.querySelectorAll('[data-screen]')].some(el=>el.getAttribute('data-screen')==='settings/Updates & About'),'Updates opens');
  };
  return {win,doc,button,click,settle,settings,gets,posts,deadlines,api:win.ArchHubAPI,
    push:()=>win.dispatchEvent(new win.Event('archhub:update-ready')),
    close:()=>{dom.window.close();}};
}

test('Workshop settings failure stays visible and retries the actual owner',async()=>{
  let attempts=0;
  const v=await mount({get:()=>status('idle'),workshop:body=>{
    if(body.function==='getAgentSurface'){
      attempts++;
      return attempts===1 ? {ok:false,error:'Workshop settings read refused'} :
        {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
    }
    if(body.function==='getGraphMetadata')return {ok:true,result:{}};
    return {ok:true,result:[]};
  }});
  try{
    await v.settle(()=>!!v.doc.querySelector('[aria-label="Retry Workshop connection"]'),'Workshop failure offers a persistent retry');
    assert.match(v.doc.body.textContent,/Workshop settings read refused/);
    await v.click(v.doc.querySelector('[aria-label="Retry Workshop connection"]'));
    await v.settle(()=>!!v.doc.querySelector('[aria-label="Workshop settings ready"]'),'retry re-reads the owner');
    assert.equal(attempts,2);
    assert.equal(v.doc.querySelector('[aria-label="Retry Workshop connection"]'),null);
  }finally{v.close();}
});

test('a loaded graph opens without waiting for an artificial splash timer',async()=>{
  const v=await mount({get:()=>status('idle')},{holdBootDelay:true});
  try{assert.ok(v.doc.querySelector('[aria-label="Main navigation"]'));}finally{v.close();}
});

test('repeated composer submission sends one request and retains refused text',async()=>{
  const pending=deferred(),sends=[];
  const v=await mount({get:()=>status('idle'),workshop:body=>{
    if(body.function==='sendToBaboom'){sends.push(body);return pending.promise;}
    if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
    if(body.function==='getGraphMetadata')return {ok:true,result:{}};
    return {ok:true,result:[]};
  }});
  try{
    const message=v.doc.querySelector('textarea[aria-label="Message"]');
    Object.getOwnPropertyDescriptor(v.win.HTMLTextAreaElement.prototype,'value').set.call(message,'Review this graph');
    message.dispatchEvent(new v.win.Event('input',{bubbles:true}));
    message.dispatchEvent(new v.win.Event('change',{bubbles:true}));
    await v.settle(()=>!v.doc.querySelector('[aria-label="Send ↵"]').disabled,'message reaches the controlled composer');
    const form=message.closest('form');
    form.dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));
    form.dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));
    await pause();
    assert.equal(sends.length,1,v.doc.body.textContent);
    pending.resolve({ok:false,error:'Workshop refused this request. Review its connection.'});
    await v.settle(()=>!v.doc.querySelector('[aria-label="Send ↵"]').disabled,'composer becomes usable after refusal');
    assert.equal(message.value,'Review this graph');
    assert.match(v.doc.body.textContent,/Workshop refused this request/);
    assert.equal(sends.length,1);
  }finally{pending.resolve({ok:false,error:'Test closed'});v.close();}
});

test('idle Studio needs no update timer and a native ready push reads once',async()=>{
  let current=status('idle');const v=await mount({get:()=>current});
  try{
    const before=v.gets.length;current=status('ready');v.push();
    await v.settle(()=>v.api.getSnapshot().update.available,'native notification refreshes status');
    assert.equal(v.gets.length,before+1);
    assert.ok(v.doc.querySelector('[aria-label="Update available"]'));
  }finally{v.close();}
});

test('a read that never answers times out and Read status can recover',async()=>{
  let current=new Promise(()=>{});const v=await mount({get:()=>current});
  try{
    v.deadlines.at(-1).abort(new Error('Update status did not answer within 15 seconds'));
    await v.settle(()=>v.api.getSnapshot().update.state==='failed','timeout reported');
    await v.settings();assert.match(v.doc.body.textContent,/did not answer within 15 seconds/);
    assert.equal(v.button('Up to date'),null);
    current=status('ready');await v.api.refreshApplicationUpdate();
    await v.settle(()=>!!v.button('Update'),'a subsequent status read recovers');
  }finally{v.close();}
});

test('up to date draws no notice; a ready build shows one relaunch notification',async()=>{
  let current=status('idle');const v=await mount({get:()=>current});
  try{
    assert.equal(v.doc.querySelector('[aria-label="Update available"]'),null);
    current=status('ready');v.push();
    await v.settle(()=>!!v.doc.querySelector('[aria-label="Update available"]'),'ready badge appears');
    assert.equal(!!v.doc.querySelector('[role="dialog"]'),false);
    const notice=v.doc.querySelector('[aria-label="Update available"]');
    assert.equal(notice.textContent,'Relaunch to update');
    assert.match(notice.title,/installed-build.*next-build/);
    assert.match(notice.title,/Unsent text is lost/);
  }finally{v.close();}
});

test('one review action restarts once, with no second confirmation',async()=>{
  const v=await mount({get:()=>status('ready'),post:()=>status('restarting')});
  try{
    await v.settings();await v.click(v.button('Update'));
    await v.settle(()=>!!v.button('Restart and update'),'review opens');
    await v.click(v.button('Restart and update'));
    await v.settle(()=>v.api.getSnapshot().update.state==='restarting','restart requested');
    assert.deepEqual(v.posts,[{action:'reload'}]);
    assert.equal(v.doc.querySelector('[aria-label="Update available"]'),null);
  }finally{v.close();}
});

test('R11 ready notification applies with ONE button and no review dialog',async()=>{
  const pending=deferred(),v=await mount({get:()=>status('ready'),post:()=>pending.promise});
  try{
    const update=v.doc.querySelector('[aria-label="Update available"]');
    assert.equal(update.textContent.trim(),'Relaunch to update');
    update.click();update.click();
    await v.settle(()=>v.posts.length===1,'one click requests the update');
    assert.equal(!!v.doc.querySelector('[role="dialog"]'),false,
      v.doc.querySelector('[role="dialog"]')?.textContent.slice(0,300));
    assert.deepEqual(v.posts,[{action:'reload'}]);
    pending.resolve(status('restarting'));
    await v.settle(()=>v.api.getSnapshot().update.state==='restarting','owner accepted restart');
    await v.settle(()=>!v.doc.querySelector('[aria-label="Update available"]'),'ready notification disappears during restart');
    assert.equal(!!v.doc.querySelector('[aria-label="Update available"]'),false);
  }finally{pending.resolve(status('restarting'));v.close();}
});

test('a refused restart reports its reason and recovers only after Read status',async()=>{
  const v=await mount({get:()=>status('ready'),post:()=>({ok:false,error:'A Workshop job is running'})});
  try{
    await v.settings();await v.click(v.button('Update'));
    await v.settle(()=>!!v.button('Restart and update'),'review opens');
    await v.click(v.button('Restart and update'));
    await v.settle(()=>/Workshop job is running/.test(v.doc.body.textContent),'refusal visible');
    assert.equal(v.button('Restart and update').disabled,true);
    assert.deepEqual(v.posts,[{action:'reload'}]);
    await v.click(v.button('Read status'));
    await v.settle(()=>!v.button('Restart and update').disabled,'read reoffers verified ready build');
    assert.equal(v.posts.length,1);
  }finally{v.close();}
});

for(const from of [null,PREVIOUS])test('installed build confirmation persists until acknowledged: '+(from||'local install'),async()=>{
  let current=status('idle',{updated_from:from,updated_to:INSTALLED});
  const v=await mount({get:()=>current,post:body=>{assert.equal(body.action,'acknowledge');return current=status('idle');}});
  try{
    const badge=v.doc.querySelector('[aria-label="Update installed"]');assert.ok(badge);
    await v.click(badge);
    await v.settle(()=>!!v.button('Dismiss update confirmation'),'confirmation opens');
    assert.match(v.doc.body.textContent,new RegExp((from||'ArchHub')+' → '+INSTALLED));
    assert.equal(v.posts.length,0);
    await v.click(v.button('Dismiss update confirmation'));
    await v.settle(()=>!v.button('Dismiss update confirmation'),'confirmation acknowledged');
    assert.deepEqual(v.posts,[{action:'acknowledge'}]);
  }finally{v.close();}
});

test('a delayed successful status confirms the running build',async()=>{
  const late=deferred(),v=await mount({get:()=>late.promise});
  try{
    late.resolve(status('idle',{updated_from:PREVIOUS,updated_to:INSTALLED}));
    await v.settle(()=>!!v.doc.querySelector('[aria-label="Update installed"]'),'delayed confirmation visible');
    assert.equal(v.posts.length,0);
  }finally{v.close();}
});

test('late reads cannot override newer reads and failed first reads are visible',async()=>{
  let current=()=>{throw Error('Update status could not be read');};const v=await mount({get:()=>current()});
  try{
    await v.settle(()=>v.api.getSnapshot().update.state==='failed','read failure visible');
    await v.settings();assert.match(v.doc.body.textContent,/could not be read/);
    const late=deferred();current=()=>late.promise;
    const first=v.api.refreshApplicationUpdate();
    current=()=>status('idle');await v.api.refreshApplicationUpdate();
    late.resolve(status('ready'));await first;
    assert.equal(v.api.getSnapshot().update.state,'idle');
    assert.equal(v.api.getSnapshot().update.available,false);
  }finally{v.close();}
});

test('all update entry points lead to the same review with one restart control',async()=>{
  const v=await mount({get:()=>status('ready'),post:()=>status('restarting')});
  try{
    await v.settings();await v.click(v.button('Update'));
    await v.settle(()=>!!v.button('Restart and update'),'Settings uses the same review');
    assert.equal([...v.doc.querySelectorAll('button')].filter(b=>b.textContent==='Restart and update').length,1);
    await v.click(v.button('Restart and update'));
    await v.settle(()=>v.posts.length===1,'one lifecycle mutation');
    assert.deepEqual(v.posts,[{action:'reload'}]);
  }finally{v.close();}
});

for(const draft of ['New unsent draft','First request',null])test(draft === 'New unsent draft' ? 'STUDIOTESTS a late successful send preserves a newer unsent Composer draft' : draft === null ? 'STUDIOFIX a successful send clears only its unchanged draft' : 'STUDIOFIX a retyped identical draft survives a late send and navigation',async()=>{
 const pending=deferred(),sends=[];
 const v=await mount({get:()=>status('idle'),workshop:body=>{
  if(body.function==='sendToBaboom'){sends.push(body);return pending.promise;}
  if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body.function==='getGraphMetadata')return {ok:true,result:{}};
  return {ok:true,result:[]};
 }});
 try{
  const message=v.doc.querySelector('textarea[aria-label="Message"]');
  const type=text=>{Object.getOwnPropertyDescriptor(v.win.HTMLTextAreaElement.prototype,'value').set.call(message,text);message.dispatchEvent(new v.win.Event('input',{bubbles:true}));message.dispatchEvent(new v.win.Event('change',{bubbles:true}));};
  type('First request');await v.settle(()=>!v.doc.querySelector('[aria-label="Send ↵"]').disabled,'first draft is ready');
  const form=message.closest('form');form.dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));form.dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));
  await v.settle(()=>sends.length===1,'one admitted send');
  if(draft!==null){type('Intervening edit');await pause();type(draft);await pause();}
  pending.resolve({ok:true,result:{id:'task-a',title:'First request'}});
  await v.settle(()=>v.doc.title.includes('Workshop'),'successful send opened its confirmed task');
  assert.equal(sends.length,1);
  assert.equal(v.doc.querySelector('textarea[aria-label="Message"]').value,'','Home text must not leak into a task reply');
  await v.click(v.doc.querySelector('[aria-label="Home"]'));
  await v.settle(()=>v.doc.title.includes('Home'),'return to the sending surface');
  assert.equal(v.doc.querySelector('textarea[aria-label="Message"]').value,draft??'','late receipt clears only its submitted draft; newer Home edits survive navigation');
 }finally{pending.resolve({ok:true,result:{id:'task-a'}});v.close();}
});

test('STUDIOTESTS Undo and Redo ignore editable targets and use the current graph owner',async()=>{
 let undo=0,redo=0;const v=await mount({get:()=>status('idle'),gesture:body=>{if(body.undo)undo++;if(body.redo)redo++;return {ok:true};}});
 try{
  await pause();
  const key=(target,shiftKey=false)=>target.dispatchEvent(new v.win.KeyboardEvent('keydown',{key:'z',ctrlKey:true,shiftKey,bubbles:true,cancelable:true}));
  for(const tag of ['input','textarea','select']){const field=v.doc.createElement(tag);v.doc.body.append(field);key(field);key(field,true);field.remove();}
  const editable=v.doc.createElement('div');editable.contentEditable='true';v.doc.body.append(editable);key(editable);key(editable,true);editable.remove();
  for(const value of ['true','','plaintext-only']){const editable=v.doc.createElement('div'),child=v.doc.createElement('span');editable.setAttribute('contenteditable',value);editable.append(child);v.doc.body.append(editable);key(child);key(child,true);editable.remove();}
  await pause();assert.equal(undo,0,'editing must not undo the graph');assert.equal(redo,0,'editing must not redo the graph');
  key(v.doc.body);key(v.doc.body,true);await pause();assert.equal(undo,1);assert.equal(redo,1);
 }finally{v.close();}
});

test('STUDIOFIX an auxiliary Composer edits and sends without replacing the primary draft',async()=>{
 const sends=[],v=await mount({get:()=>status('idle'),workshop:body=>{
  if(body.function==='sendToBaboom'){sends.push(body);return {ok:true,result:{id:'task-aux',title:'Auxiliary request'}};}
  if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body.function==='getGraphMetadata')return {ok:true,result:{}};
  return {ok:true,result:[]};
 }});
 try{
  await v.click(v.doc.querySelector('[aria-label="Workshop"]'));await v.settle(()=>!!v.button('New task'),'Workshop opens');
  const primary=v.doc.querySelector('textarea[aria-label="Message"]');
  const type=(field,text)=>{Object.getOwnPropertyDescriptor(v.win.HTMLTextAreaElement.prototype,'value').set.call(field,text);field.dispatchEvent(new v.win.Event('input',{bubbles:true}));field.dispatchEvent(new v.win.Event('change',{bubbles:true}));};
  type(primary,'Primary unsent draft');await pause();await v.click(v.button('New task'));
  const auxiliary=v.doc.querySelector('[role="dialog"] textarea[aria-label="Message"]');assert.ok(auxiliary);
  assert.equal(auxiliary.value,'','a new task owns its own empty draft');
  type(auxiliary,'Auxiliary request');await pause();assert.equal(primary.value,'Primary unsent draft');
  auxiliary.closest('form').dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));
  await v.settle(()=>sends.length===1&&!v.doc.querySelector('[role="dialog"]'),'auxiliary send confirmed');
  assert.equal(v.doc.querySelector('textarea[aria-label="Message"]').value,'Primary unsent draft');
 }finally{v.close();}
});

test('STUDIOFIX Home and Workshop reply drafts are separate across navigation',async()=>{
 const v=await mount({get:()=>status('idle'),workshop:body=>{
  if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body.function==='getGraphMetadata')return {ok:true,result:{}};
  return {ok:true,result:[]};
 }});
 const message=()=>v.doc.querySelector('textarea[aria-label="Message"]');
 const type=async text=>{const field=message();Object.getOwnPropertyDescriptor(v.win.HTMLTextAreaElement.prototype,'value').set.call(field,text);field.dispatchEvent(new v.win.Event('input',{bubbles:true}));field.dispatchEvent(new v.win.Event('change',{bubbles:true}));await pause();};
 try{
  await type('Home draft');
  await v.click(v.doc.querySelector('[aria-label="Workshop"]'));
  await v.settle(()=>v.doc.title.includes('Workshop'),'Workshop opens');
  assert.equal(message().value,'','Workshop has its own draft');
  await type('Reply draft');
  await v.click(v.doc.querySelector('[aria-label="Home"]'));
  await v.settle(()=>v.doc.title.includes('Home'),'Home opens');
  assert.equal(message().value,'Home draft');
  await v.click(v.doc.querySelector('[aria-label="Workshop"]'));
  await v.settle(()=>v.doc.title.includes('Workshop'),'Workshop reopens');
  assert.equal(message().value,'Reply draft');
 }finally{v.close();}
});

test('STUDIOFIX task replies own separate drafts and late replies preserve newer text',async()=>{
 const pending=deferred(),tasks=[{id:'task-a',title:'Task A',status:'WIP'},{id:'task-b',title:'Task B',status:'WIP'}];
 const v=await mount({get:()=>status('idle'),workshop:body=>{
  if(body.function==='listTasks')return {ok:true,result:tasks};
  if(body.function==='sendToBaboom')return pending.promise;
  if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body.function==='getGraphMetadata')return {ok:true,result:{}};
  return {ok:true,result:[]};
 }});
 const message=()=>v.doc.querySelector('textarea[aria-label="Message"]');
 const type=async text=>{const field=message();Object.getOwnPropertyDescriptor(v.win.HTMLTextAreaElement.prototype,'value').set.call(field,text);field.dispatchEvent(new v.win.Event('input',{bubbles:true}));field.dispatchEvent(new v.win.Event('change',{bubbles:true}));await pause();};
 const select=async title=>{await v.click([...v.doc.querySelectorAll('button.listbutton')].find(b=>b.textContent.includes(title)));};
 try{
  await v.click(v.doc.querySelector('[aria-label="Workshop"]'));
  await v.settle(()=>!!message(),'Workshop opens');
  await type('A reply');
  message().closest('form').dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));
  await pause();await type('A newer reply');
  await select('Task B');assert.equal(message().value,'','task B owns a separate draft');
  await type('B reply');
  pending.resolve({ok:true,result:tasks[0]});
  await v.settle(()=>!v.doc.querySelector('[aria-label="Send ↵"]').disabled,'late task send completed');
  await select('Task A');assert.equal(message().value,'A newer reply','late task receipt must preserve newer text');
  await select('Task B');assert.equal(message().value,'B reply');
 }finally{pending.resolve({ok:true,result:tasks[0]});v.close();}
});
