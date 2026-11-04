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
    assert.equal(retry.textContent,'Retry');
    assert.equal(failure.querySelector('.boot-receipts').textContent,'See receipts');
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
    if(url==='/api/universal/canvas')data={root:'graph',nodes:server.nodes||[],wires:[],catalog:[],...(server.workshop?{scope:{current:'graph'},workshops:[{root:'workshop'}]}:{})};
    if(url==='/api/router/chat'){
      const body=JSON.parse(options.body||'{}');
      const answer=server.chat?await server.chat(body):{ok:true,result:{answer:'ok'}};
      const encoded=new TextEncoder().encode('data: '+JSON.stringify({result:answer.result||{answer:'ok'}})+'\n\n');
      let sent=false;
      return {ok:answer.ok!==false,status:answer.ok===false?409:200,json:async()=>plain(answer),body:{getReader(){return {async read(){if(sent)return {done:true,value:undefined};sent=true;return {done:false,value:encoded};},releaseLock(){}}}}};
    }
    if(url==='/api/universal/cloud-session')data={ok:true,signed_in:false};
    if(url==='/api/universal/settings-action' && server.settings) data=await server.settings(JSON.parse(options.body||'{}'));
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
  win.ArchHubStudioAuthority={create:({get,post:send})=>{let held;const post=async(...args)=>{const result=await send(...args);held=Array.isArray(result.nodes)?result:await get('/api/universal/canvas');return result;};return ({getSnapshot:()=>({canvas:held}),clear:()=>{held=null;},adopt:async result=>held=result,transact:async action=>held=await action(),load:async()=>held=await get('/api/universal/canvas'),undo:()=>post('/api/universal/gesture',{undo:true}),redo:()=>post('/api/universal/gesture',{redo:true})})}};
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

test('Home composer admits one chat request and restores a refused draft only when nothing newer is typed',async()=>{
  let gate=deferred();const chats=[];
  const v=await mount({get:()=>status('idle'),chat:async body=>{chats.push(body);return gate.promise;},workshop:body=>{
    if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
    if(body.function==='getGraphMetadata')return {ok:true,result:{}};
    return {ok:true,result:[]};
  }});
  const message=()=>v.doc.querySelector('.dx-composer textarea[aria-label="Message"]');
  const type=text=>{const field=message();Object.getOwnPropertyDescriptor(v.win.HTMLTextAreaElement.prototype,'value').set.call(field,text);field.dispatchEvent(new v.win.Event('input',{bubbles:true}));field.dispatchEvent(new v.win.Event('change',{bubbles:true}));};
  const submit=()=>{const form=message().closest('form');form.dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));};
  try{
    type('Review this graph');
    await v.settle(()=>message().closest('form').querySelector('button[type="submit"]').disabled===false,'Home draft is ready');
    submit();submit();
    await v.settle(()=>chats.length===1,'a same-tick duplicate sends one /api/router/chat request');
    gate.resolve({ok:false,error:'The model request was refused.'});
    await v.settle(()=>message().value==='Review this graph','a refusal restores the draft when nothing newer is typed');
    assert.equal(chats.length,1);
    gate=deferred();
    submit();
    await v.settle(()=>chats.length===2,'retry sends the restored draft');
    type('A newer request');
    gate.resolve({ok:false,error:'The model request was refused.'});
    await v.settle(()=>message().value==='A newer request','a refusal keeps newer text');
    gate=deferred();
    submit();
    await v.settle(()=>chats.length===3,'a later send uses the newer draft');
    gate.resolve({ok:true,result:{answer:'done'}});
    await v.settle(()=>message().value==='','a completed send clears only its own draft');
  }finally{gate.resolve({ok:false,error:'closed'});v.close();}
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
  const primary=v.doc.querySelector('textarea[aria-label="Message"]');
  const type=(field,text)=>{const proto=field.tagName==='TEXTAREA'?v.win.HTMLTextAreaElement.prototype:v.win.HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(field,text);field.dispatchEvent(new v.win.Event('input',{bubbles:true}));field.dispatchEvent(new v.win.Event('change',{bubbles:true}));};
  type(primary,'Primary unsent draft');await pause();
  await v.click([...v.doc.querySelectorAll('button')].find(b=>b.textContent.trim()==='+ New task'));
  await v.settle(()=>!!v.doc.querySelector('[role="dialog"] [aria-label="Task name"]'),'New task opens on Home');
  const auxiliary=v.doc.querySelector('[role="dialog"] [aria-label="Task name"]');
  assert.equal(auxiliary.value,'','a new task opens with an empty name');
  type(auxiliary,'Auxiliary request');await pause();
  assert.equal(primary.value,'Primary unsent draft');
  assert.equal(sends.length,0,'naming a task does not send the primary draft');
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
  assert.equal(v.doc.querySelector('nav [aria-label="Workshop"]'),null);
  assert.equal(v.doc.querySelector('nav [aria-label="Canvas"]'),null);
  const view=name=>[...v.doc.querySelectorAll('[data-dx="views"] button')].find(b=>b.textContent.trim()===name);
  assert.equal(view('Workshop').getAttribute('aria-pressed'),'true');
  assert.ok(view('Canvas'));
  await v.click(view('Workshop'));
  assert.equal(v.doc.title.includes('Home'),true);
  assert.equal(message().value,'Home draft');
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
  const select=async title=>{await v.click([...v.doc.querySelectorAll('button.dx-task')].find(b=>b.textContent.includes(title)));};
 try{
  await v.settle(()=>!!message(),'Home task composer opens');
  await type('A reply');
  message().closest('form').dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true}));
  await pause();await type('A newer reply');
  await select('Task B');assert.equal(message().value,'','task B owns a separate draft');
  await type('B reply');
  pending.resolve({ok:true,result:tasks[0]});
  await v.settle(()=>message().closest('form').querySelector('button[type="submit"]').getAttribute('aria-busy')!=='true','late task send completed');
  await select('Task A');assert.equal(message().value,'A newer reply','late task receipt must preserve newer text');
  await select('Task B');assert.equal(message().value,'B reply');
 }finally{pending.resolve({ok:true,result:tasks[0]});v.close();}
});

test('the File menu is file-only and Workshop leads with the thread',async()=>{
 const v=await mount({get:()=>status('idle'),settings:body=>body.function==='readPermissions'?{ok:true,result:{runMode:''}}:{ok:true,result:{}},workshop:body=>{
  if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body.function==='getGraphMetadata')return {ok:true,result:{}};
  return {ok:true,result:[]};
 }});
 try{
  await v.settle(()=>v.doc.querySelector('[data-run-mode]')?.textContent.includes('Mode unavailable'),'an unreported run mode stays Mode unavailable');
  assert.equal(v.doc.querySelector('[data-run-mode]').textContent.includes('Accept edits'),false,'the header has no Accept edits pill');
  assert.equal(v.doc.querySelector('[data-dx="canvas-commands"]'),null,'canvas commands stay off the Workshop face');
  assert.ok(v.doc.querySelector('[data-dx="conversation"]'),'Workshop leads with the conversation');
  assert.equal(v.doc.querySelector('[data-dx="workflow"]'),null,'Workshop hides workflow cards until a plan is recorded');
  assert.equal(v.doc.querySelector('.dx-new-task').textContent,'+ New task');
  assert.equal(v.doc.querySelector('.dx-model select').getAttribute('aria-label'),'Model');
  assert.match(v.doc.querySelector('.dx-model').textContent,/Free models first/);
  const menu=v.doc.querySelector('[data-dx="file-menu"]');
  assert.equal(menu.getAttribute('aria-label'),'File');
  const labels=[...menu.querySelectorAll('[role="menuitem"]')].map(node=>node.textContent.trim());
  assert.deepEqual(labels,['New file','Open file…','Import…','Library']);
  assert.doesNotMatch(menu.textContent,/Search|Activity|Add node|Overview|Save as/);
  assert.match(read('01.APP/nodelang/studio/ds_home2.jsx'),/data-dx="canvas-commands"[\s\S]*\+ Add node[\s\S]*Library[\s\S]*Program view[\s\S]*Present[\s\S]*Model review[\s\S]*Overview/);
  const library=[...menu.querySelectorAll('[role="menuitem"]')].find(node=>node.textContent.trim()==='Library');
  await v.click(library);
  await v.settle(()=>!!v.doc.querySelector('[aria-label="Library shelf"]'),'Library from Workshop opens the shelf');
 }finally{v.close();}
});

test('Workshop plan steps are cards beside the conversation and review rows keep Evidence',async()=>{
 const tasks=[{id:'review',title:'Header and buttons',status:'IN REVIEW',owner:'717',summary:'Needs a visual check',reviews:[{summary:'Needs a visual check'}],plan:['Study the task'],progress:{'Study the task':'Saved'}},{id:'work',title:'Unify task workspace',status:'WIP',owner:'designer',summary:'Layout and interactions',plan:['Unify Home','Verify installed app'],progress:{'Unify Home':'Working','Verify installed app':'Awaiting verification'}}];
 const v=await mount({get:()=>status('idle'),workshop:body=>{
  if(body.function==='listTasks')return {ok:true,result:tasks};
  if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body.function==='getGraphMetadata')return {ok:true,result:{}};
  if(body.function==='openTaskGraph')return {ok:true,result:{}};
  return {ok:true,result:[]};
 }});
 try{
  await v.settle(()=>v.doc.querySelector('[data-dx="workflow"]'),'a recorded plan draws workflow cards');
  const cards=[...v.doc.querySelectorAll('.dx-flow-card')];
  assert.equal(cards.length,1,'the selected task shows only its own steps');
  assert.match(cards[0].textContent,/Study the task/);
  assert.match(cards[0].textContent,/Saved/);
  assert.ok(v.doc.querySelector('[data-dx="conversation"]'),'the conversation stays beside the cards');
  const review=v.doc.querySelector('.dx-task-row[data-status="review"]');
  assert.ok(review,'a review row carries its status line');
  assert.equal(review.querySelector('.dx-evidence').textContent,'Evidence');
  assert.match(review.textContent,/Needs a visual check/);
  await v.click([...v.doc.querySelectorAll('button.dx-task')].find(node=>node.textContent.includes('Unify task workspace')));
  await v.settle(()=>v.doc.querySelectorAll('.dx-flow-card').length===2,'the working task shows its own cards');
  const words=[...v.doc.querySelectorAll('.dx-flow-status')].map(node=>node.textContent);
  assert.deepEqual(words,['Working','Awaiting verification']);
 }finally{v.close();}
});

test('Settings search shows values and Advanced rows, then reveals the control in place',async()=>{
 const nodes=[{id:'n1',label:'Appearance',properties:[{label:'Text scale',value:100,editor:'number',setting:{kind:'theme'},relation:'n1',editable:true}]}];
 const v=await mount({get:()=>status('idle'),nodes,workshop:body=>{
  if(body.function==='getAgentSurface')return {ok:true,result:{agentProfiles:{},learning:{layers:{}}}};
  if(body.function==='getGraphMetadata')return {ok:true,result:{}};
  return {ok:true,result:[]};
 }});
 try{
  await v.click(v.doc.querySelector('[aria-label="Settings"]'));
  await v.settle(()=>!!v.doc.querySelector('[aria-label="Search settings"]'),'Settings search is on the sheet');
  const field=v.doc.querySelector('[aria-label="Search settings"]');
  Object.getOwnPropertyDescriptor(v.win.HTMLInputElement.prototype,'value').set.call(field,'100');
  field.dispatchEvent(new v.win.Event('input',{bubbles:true}));
  field.dispatchEvent(new v.win.Event('change',{bubbles:true}));
  await v.settle(()=>!![...v.doc.querySelectorAll('.sheet-result')].find(node=>node.textContent.includes('Text scale')&&node.textContent.includes('100')&&node.textContent.includes('Advanced')),'the value and Advanced row are in the results');
  await v.click([...v.doc.querySelectorAll('.sheet-result')].find(node=>node.textContent.includes('Text scale')));
  await v.settle(()=>!!v.doc.querySelector('[data-setting="n1:Text scale"]')&&!v.doc.querySelector('[aria-label="Search settings"]').value,'selecting the result reveals that control and keeps Settings open');
  assert.equal(v.doc.querySelector('[data-screen]').getAttribute('data-screen').startsWith('settings/'),true);
  assert.equal(v.doc.querySelector('[aria-expanded="true"]').textContent,'Advanced');
 }finally{v.close();}
});
