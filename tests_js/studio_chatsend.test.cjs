// CHATSEND: production components, shipped React and real membership adapter;
// only the application transport is fake. No app, provider, or visible window.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const names = ['tokens.jsx','ds/index.jsx','design-canvas.jsx','shared-data.jsx','studio-suite.jsx',
  'param-types.jsx','studio-params.jsx','studio-mobile.jsx','studio-account.jsx','node-registry.jsx',
  'brain-model.jsx','workshop-board.jsx','studio-workshop.jsx','studio-lm.jsx'];
const model = {name:'Configured model',routed:'openrouter/vendor/configured',vendor:'vendor',col:'#aa8844'};
async function browser() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'https://chatsend.invalid/',runScripts:'outside-only',pretendToBeVisual:true});
  const win = dom.window;
  win.matchMedia = () => ({matches:false,addEventListener(){},removeEventListener(){}});
  win.fetch = () => new Promise(() => {});
  win.ARCHHUB_LIVE = {graph:{nodes:[],wires:[]},hosts:[],sessions:[],skills:[]};
  win.ARCHHUB_TOOL_HUB = {ok:true,tools:[],waiting:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  const manifest = process.env.CHATSEND_SOURCE === '1' ? null : JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of names) {
    let code;
    if (!manifest) code = require('esbuild').transformSync(read('nodelang/studio/'+source),{loader:'jsx'}).code;
    else {
      const row = manifest.files.find(row => row.source === source);
      assert.equal(row.source_sha256, createHash('sha256').update(read('nodelang/studio/'+source)).digest('hex'), 'built source: '+source);
      code = read('nodelang/studio/compiled/'+row.output);
    }
    if (source === 'studio-lm.jsx') code = code.replace(/window\.StudioLM\s*=\s*StudioLM\s*;/,
      'window.StudioLM=StudioLM;window.__CHATSEND={Home,NodeRail,NodeRenderer};');
    win.eval(code);
  }
  win.eval(read('nodelang/studio/studio-authority.js'));
  const reactRoot = win.ReactDOM.createRoot(win.document.getElementById('root'));
  const flush = fn => win.ReactDOM.flushSync(fn);
  return {win,doc:win.document,flush,
    render:(name,props) => flush(() => reactRoot.render(win.React.createElement(win.__CHATSEND[name],props))),
    type:(input,value) => flush(() => {
      const proto = input.tagName === 'TEXTAREA' ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto,'value').set.call(input,value);
      input.dispatchEvent(new win.Event('input',{bubbles:true}));
    }),
    settle:() => new Promise(resolve => win.setTimeout(resolve,25)),
    close:() => {flush(() => reactRoot.unmount());win.close();}};
}
const button = (ui,label) => [...ui.doc.querySelectorAll('button')].find(row => row.textContent.trim() === label);

for (const action of ['button','Enter']) test('main graph chat '+action+' sends once, draws reply and leaves picker closed',async()=>{
  const ui=await browser(),calls=[],picks=[];
  ui.win.ARCHHUB_AGENT=async(...args)=>{calls.push(args);return {answer:'Reply received from configured model.'};};
  try {
    ui.render('NodeRail',{node:null,session:{id:'graph-a',title:'My graph'},graph:{nodes:[],wires:[]},
      canvas:{application_root:'graph-a',root:'scope-a',scope:{current:'scope-a'}},scope:'scope-a',model,
      setPickerOpen:value=>picks.push(value)});
    const input=ui.doc.querySelector('[aria-label="Ask selection"]');
    assert.ok(input,'main graph composer exists');ui.type(input,'hello from main chat');
    ui.flush(()=>action==='button' ? button(ui,'Send').click() : input.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    await ui.settle();
    assert.equal(calls.length,1);assert.equal(calls[0][0],'hello from main chat');
    assert.equal(calls[0][1],model.routed);assert.equal(calls[0][2].graph,true);
    assert.match(ui.doc.body.textContent,/Reply received from configured model\./);assert.deepEqual(picks,[]);
    ui.flush(()=>ui.doc.querySelector('[data-model-indicator]').click());assert.deepEqual(picks,[true]);
  } finally {ui.close();}
});

test('Send without a route retains the draft and only the model control opens the picker',async()=>{
  const ui=await browser(),picks=[],calls=[];
  ui.win.ARCHHUB_AGENT=(...args)=>calls.push(args);
  try {
    ui.render('NodeRail',{node:null,session:{id:'graph-a',title:'My graph'},graph:{nodes:[],wires:[]},
      canvas:{application_root:'graph-a',root:'scope-a'},scope:'scope-a',model:{name:'Choose a model'},setPickerOpen:v=>picks.push(v)});
    const input=ui.doc.querySelector('[aria-label="Ask selection"]');ui.type(input,'keep this draft');
    ui.flush(()=>button(ui,'Send').click());await ui.settle();
    assert.deepEqual(picks,[],'Send must never activate model picker');assert.deepEqual(calls,[]);
    assert.equal(input.value,'keep this draft');assert.match(ui.doc.body.textContent,/Choose a model/);
    ui.flush(()=>ui.doc.querySelector('[data-model-indicator]').click());assert.deepEqual(picks,[true]);
  } finally {ui.close();}
});

for (const homeAction of ['button','Enter']) test('Home '+homeAction+' submits through existing session owner, never picker',async()=>{
  const ui=await browser(),calls=[],picks=[],replies=[];
  const state={canvas:{graph_id:'graph-a'},topology:{canvas:{authorization:{subject:'owner',session:'view'}}},workshops:[]};
  ui.win.ARCHHUB_EXISTING_WORKSHOP={getSnapshot:()=>state,subscribe:()=>()=>{},readHomeTemplates:async()=>({templates:[]}),
    startSession:async details=>{calls.push(details);return {ok:true,root:'new-room',delivery:{state:'replied',reply_message_id:'reply-1'}};}};
  try {
    ui.render('Home',{model,workshopState:state,account:{name:'Owner'},setPickerOpen:v=>picks.push(v),
      onStarted:async result=>replies.push(result.delivery)});
    const input=ui.doc.querySelector('[aria-label="Start a new session"]');ui.type(input,'start a real session');
    ui.flush(()=>homeAction==='button' ? button(ui,'Send').click() : input.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    await ui.settle();assert.equal(calls.length,1);assert.equal(calls[0].model,model.routed);
    assert.equal(replies[0].state,'replied');assert.deepEqual(picks,[]);assert.equal(input.value,'');
  } finally {ui.close();}
});

for(const stream of ['pointer','mouse']) test('group drag-out '+stream+' commits final release position with coalesced movement',async()=>{
  const ui=await browser(),posts=[];
  let canvas={ok:true,application_root:'graph-a',graph_id:'graph-a',root:'scope-a',scope:{current:'scope-a'},revision:1,
    authorization:{subject:'owner',session:'view'},nodes:[{id:'G',label:'My group',composition:true,member_count:2,
      members:[{id:'a',title:'Member A'},{id:'b',title:'Member B'}],ports:[]}],wires:[],
    interaction_projection:{bindings:[{control:'app:control:canvas:remove-member',interaction:'remove',event:'activate'}]}};
  const owner=ui.win.ArchHubStudioAuthority.create({get:async()=>canvas,post:async(url,body)=>{
    posts.push({url,body});canvas={...canvas,revision:2,nodes:[{...canvas.nodes[0],member_count:1,members:[{id:'b',title:'Member B'}]},
      {id:'a',label:'Member A',x:body.membership.position.x,y:body.membership.position.y,group:'',ports:[]}]};return {ok:true,...canvas};}});
  await owner.load();
  const draw=()=>ui.render('NodeRenderer',{n:owner.getSnapshot().graph.nodes.find(n=>n.id==='G'),
    onMemberLeave:(member,group,position)=>owner.moveMember(member,group,'',position).then(draw),
    screenToCanvasPoint:(x,y)=>({x:(x-100)/2,y:(y-50)/2})});
  try {
    draw();const card=ui.doc.querySelector('[data-node-id="G"]');
    card.getBoundingClientRect=()=>({left:100,top:50,right:324,bottom:250,width:224,height:200});
    const chip=card.querySelector('[data-member-chip="a"]');assert.ok(chip);
    const fire=(target,type,x,y)=>ui.flush(()=>target.dispatchEvent(new ui.win.MouseEvent(type,{bubbles:true,cancelable:true,button:0,clientX:x,clientY:y})));
    fire(chip,stream==='pointer'?'pointerdown':'mousedown',150,100);
    // Native shells may coalesce moves; the release still carries the final point.
    fire(ui.win,stream==='pointer'?'pointerup':'mouseup',500,350);await ui.settle();
    assert.equal(posts.length,1,'drag outside must commit exactly once');
    assert.equal(posts[0].body.membership.member,'a');assert.equal(posts[0].body.membership.to_group,'');
    assert.deepEqual(JSON.parse(JSON.stringify(posts[0].body.membership.position)),{x:200,y:150});
    assert.equal(ui.doc.querySelector('[data-member-chip="a"]'),null);
    assert.equal(owner.getSnapshot().graph.nodes.find(n=>n.id==='a').group,'');
  } finally {ui.close();}
});

// Independent supplementary courts; the original RED assertions above stay intact.
for (const noRouteAction of ['button','Enter']) test('Home without route '+noRouteAction+' keeps draft and picker closed',async()=>{
  const ui=await browser(),calls=[],picks=[];
  const state={canvas:{graph_id:'graph-a'},topology:{canvas:{authorization:{subject:'owner',session:'view'}}},workshops:[]};
  ui.win.ARCHHUB_EXISTING_WORKSHOP={getSnapshot:()=>state,subscribe:()=>()=>{},readHomeTemplates:async()=>({templates:[]}),
    startSession:async details=>{calls.push(details);return {ok:true,root:'unexpected'};}};
  try {
    ui.render('Home',{model:{name:'Choose a model'},workshopState:state,account:{name:'Owner'},setPickerOpen:v=>picks.push(v)});
    const input=ui.doc.querySelector('[aria-label="Start a new session"]');ui.type(input,'retain home request');
    ui.flush(()=>noRouteAction==='button' ? button(ui,'Send').click() : input.dispatchEvent(new ui.win.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})));
    await ui.settle();assert.deepEqual(calls,[]);assert.deepEqual(picks,[]);
    assert.equal(input.value,'retain home request');assert.match(ui.doc.body.textContent,/Choose a model before sending/);
    const picker=[...ui.doc.querySelectorAll('[data-home-composer] button')].find(row=>row.textContent.includes('Choose a model')&&row.textContent.includes('▾'));
    assert.ok(picker,'Home model strip remains its own picker control');
    ui.flush(()=>picker.click());assert.deepEqual(picks,[true]);
  } finally {ui.close();}
});

for (const gesture of ['cancel','inside','small','stationary']) test('group '+gesture+' gesture never removes member',async()=>{
  const ui=await browser(),calls=[];
  try {
    ui.render('NodeRenderer',{n:{id:'G',title:'Group',cat:'data',composition:true,x:100,y:50,members:[{id:'a',title:'Member A'}],ins:[],outs:[]},
      onMemberLeave:(...args)=>{calls.push(args);return {ok:true};}});
    const card=ui.doc.querySelector('[data-node-id="G"]');
    card.getBoundingClientRect=()=>({left:100,top:50,right:324,bottom:250,width:224,height:200});
    const chip=card.querySelector('[data-member-chip="a"]');assert.ok(chip);
    const fire=(target,type,x,y)=>ui.flush(()=>target.dispatchEvent(new ui.win.MouseEvent(type,{bubbles:true,cancelable:true,button:0,clientX:x,clientY:y})));
    const start=gesture==='small'?{x:320,y:100}:{x:150,y:100};
    const end=gesture==='cancel'?{x:500,y:350}:gesture==='inside'?{x:200,y:150}:gesture==='small'?{x:325,y:100}:start;
    fire(chip,'pointerdown',start.x,start.y);
    if (gesture==='cancel'||gesture==='inside') fire(ui.win,'pointermove',end.x,end.y);
    fire(ui.win,gesture==='cancel'?'pointercancel':'pointerup',end.x,end.y);await ui.settle();
    assert.deepEqual(calls,[]);assert.ok(ui.doc.querySelector('[data-member-chip="a"]'));
  } finally {ui.close();}
});
