/* Execute the compiled approved design in a DOM over the real API adapter.
   The lifecycle responses are isolated: no installed app, feed or user data is touched. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const UPDATE = '/api/universal/application-update';
const INSTALLED = 'installed-build', NEXT = 'next-build';
const status = (state, extra = {}) => ({ok:true, current_build:INSTALLED, state,
  available_build:['ready','restarting'].includes(state) ? NEXT : null,
  detail:state === 'idle' ? 'Up to date' : state === 'ready' ? 'Verified download' : state,
  restart_supported:true, updated_from:null, updated_to:null, ...extra});
const pause = () => new Promise(resolve => setTimeout(resolve, 5));
const plain = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve}; };

test('boot timeout is neutral and the next successful automatic read clears the rendered footer',async()=>{
  let current=new Promise(()=>{});const v=await mount({get:()=>current});
  try{
    v.deadlines.at(-1).abort(new Error('signal timed out'));
    await v.settle(()=>v.api.getSnapshot().update.state==='failed','read failed');
    await v.settle(()=>!!v.doc.querySelector('footer'),'footer rendered');
    assert.equal(v.api.getSnapshot().connectionNotice,'Checking for updates…');
    assert.doesNotMatch(v.doc.querySelector('footer').textContent,/signal timed out/);
    current=status('ready');await v.advance(5000);
    await v.settle(()=>v.api.getSnapshot().update.available,'retry succeeded');
    assert.equal(v.api.getSnapshot().connectionNotice,'');
    await v.settle(()=>/Local session/.test(v.doc.querySelector('footer').textContent),'footer recovered');
    assert.equal(v.gets.length,2);
  }finally{v.close();}
});

test('failed reads back off at 5s, 15s, 60s, then 5min; hidden pauses reads',async()=>{
  const v=await mount({get:()=>{throw Error('status endpoint unavailable');}});
  try{
    await v.settle(()=>v.api.getSnapshot().update.state==='failed','boot failed');
    let count=v.gets.length;
    for(const delay of [5000,15000,60000,300000,300000]){
      await v.advance(delay-1);assert.equal(v.gets.length,count,'not before deadline');
      await v.advance(1);assert.equal(v.gets.length,++count,'one bounded retry');
    }
    await v.setHidden(true);await v.advance(600000);
    assert.equal(v.gets.length,count,'no hidden retries');
    await v.setHidden(false);assert.equal(v.gets.length,++count,'visible resumes overdue read');
  }finally{v.close();}
});

test('ready pushes bypass backoff without update actions',async()=>{
  let current=status('idle');const v=await mount({get:()=>current});
  try{
    current=Promise.reject(Error('status endpoint unavailable'));current.catch(()=>{});
    v.push();await v.settle(()=>v.api.getSnapshot().update.state==='failed','push read failed');
    current=status('ready');v.push();
    await v.settle(()=>v.api.getSnapshot().update.available,'push bypasses deadline');
    assert.equal(v.api.getSnapshot().connectionNotice,'');
    assert.equal(v.posts.length,0,'background reads never invoke an action');
  }finally{v.close();}
});

test('successful status reads preserve another owners connection failure',async()=>{
  const v=await mount({get:()=>status('idle'),settingsFailure:'Settings service unavailable'});
  try{
    await v.settle(()=>v.api.getSnapshot().connectionNotice==='Settings service unavailable','settings error visible');
    await v.api.refreshApplicationUpdate();
    assert.equal(v.api.getSnapshot().connectionNotice,'Settings service unavailable');
  }finally{v.close();}
});

test('a good status after a boot timeout removes the stale rendered error',async()=>{
  let current=new Promise(()=>{});const v=await mount({get:()=>current});
  try{
    v.deadlines.at(-1).abort(new Error('signal timed out'));
    await v.settle(()=>v.api.getSnapshot().update.state==='failed','read failed');
    current=status('idle');await v.api.refreshApplicationUpdate();
    assert.equal(v.api.getSnapshot().update.state,'idle');
    await v.settle(()=>!!v.doc.querySelector('footer'),'footer exists');
    await pause();
    assert.doesNotMatch(v.doc.querySelector('footer').textContent,/signal timed out/);
    assert.equal(v.api.getSnapshot().connectionNotice,'');
  }finally{v.close();}
});

test('hiding during an owner refresh prevents a new background status read',async()=>{
  const v=await mount({get:()=>status('idle')});
  try{
    const count=v.gets.length;
    const advancing=v.advance(5000);await v.setHidden(true);await advancing;
    assert.equal(v.gets.length,count,'visibility is checked after awaited owners');
    await v.setHidden(false);
    assert.equal(v.gets.length,count+1);
  }finally{v.close();}
});

test('background reads share pending work and a success resets failure backoff',async()=>{
  let current=status('idle');const v=await mount({get:()=>current});
  try{
    const held=deferred();current=held.promise;
    await v.advance(5000);const count=v.gets.length;
    await v.advance(5000);assert.equal(v.gets.length,count,'pending read is not duplicated');
    held.resolve(status('idle'));await v.advance(0);
    current=Promise.reject(Error('offline'));current.catch(()=>{});
    await v.advance(5000);const failed=v.gets.length;
    await v.advance(4999);assert.equal(v.gets.length,failed);
    current=status('idle');await v.advance(1);
    assert.equal(v.gets.length,failed+1,'first retry remains five seconds after success');
  }finally{v.close();}
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
  let hidden=false; Object.defineProperty(win.document,'hidden',{get:()=>hidden});
  let now=0; win.Date.now=()=>now;
  const intervals=new Map(); let timerId=0;
  win.setInterval=(fn,ms)=>{const id=++timerId;intervals.set(id,fn);return id;};
  win.clearInterval=id=>intervals.delete(id);
  const drain=async()=>{for(let i=0;i<100;i++)await Promise.resolve();await pause();await pause();};
  const advance=async ms=>{now+=ms;for(const fn of [...intervals.values()])fn();await drain();};
  const setHidden=async value=>{hidden=value;win.document.dispatchEvent(new win.Event('visibilitychange'));await drain();};
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
    if(url==='/api/universal/cloud-session')data=server.cloud?await server.cloud():{ok:true,signed_in:false};
    if(url==='/api/universal/settings-action')data=server.settingsFailure?{ok:false,error:server.settingsFailure}:{ok:true,result:{}};
    if(url==='/api/universal/workshop'){
      const body=JSON.parse(options.body);
      data=server.workshop?await server.workshop(body):{ok:true,result:[]};
    }
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
  win.ArchHubStudioAuthority={create:({get})=>({load:()=>get('/api/universal/canvas')})};
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
  await pause(); // Let React subscribe before advancing the owner's virtual clock.
  return {win,doc,button,click,settle,settings,gets,posts,deadlines,advance,setHidden,api:win.ArchHubAPI,
    push:()=>win.dispatchEvent(new win.Event('archhub:update-ready')),
    close:()=>{dom.window.close();}};
}
