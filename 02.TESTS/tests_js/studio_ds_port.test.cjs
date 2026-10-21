'use strict';
// Independent DS-PORT acceptance: real plate primitives and mounted Studio routes.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {transformSync} = require('esbuild');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const componentPath = '01.APP/nodelang/studio/ds/index.jsx';
const required = ['Btn','Toggle','Row','Card','Rail','Node','Socket','Composer','EmptyState'];
const transformed = new Map();
function sourceCode(name) {
  const source = read('01.APP/nodelang/studio/' + name);
  let held = transformed.get(name);
  if (!held || held.source !== source) {
    held = {source,code:transformSync(source,{loader:'jsx'}).code};
    transformed.set(name,held);
  }
  return held.code;
}

async function browser() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'https://ds-port.invalid/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  const evaluate = name => win.eval(sourceCode(name));
  evaluate('tokens.jsx');
  return {win, doc:win.document, evaluate, close:() => dom.window.close()};
}
async function primitives() {
  assert.ok(fs.existsSync(path.join(root, componentPath)), 'the ONE shared component module exists');
  const ui = await browser();
  ui.evaluate('ds/index.jsx');
  for (const name of required) {
    const component=ui.win.AH_DS?.[name];
    assert.ok(typeof component==='function' || (component?.$$typeof===ui.win.Symbol.for('react.forward_ref') &&
      typeof component.render==='function'),name+' exports a real React component');
  }
  const reactRoot = ui.win.ReactDOM.createRoot(ui.doc.getElementById('root'));
  return {...ui, render:(name, props, ...children) => {
    ui.win.ReactDOM.flushSync(() => reactRoot.render(ui.win.React.createElement(ui.win.AH_DS[name], props, ...children)));
    return ui.doc.getElementById('root').firstElementChild;
  }, flush:action => ui.win.ReactDOM.flushSync(action),
  close:() => {ui.win.ReactDOM.flushSync(() => reactRoot.unmount()); ui.close();}};
}
const style = (node, properties) => Object.fromEntries(properties.map(key => [key, node.style[key]]));

test('DS-PORT plate button snapshots and native disabled/focus behavior', async () => {
  const ui = await primitives();
  try {
    let calls = 0;
    const btn = ui.render('Btn', {kind:'primary', onClick:() => calls++}, 'Run');
    assert.equal(btn.tagName, 'BUTTON');
    assert.equal(btn.type, 'button');
    assert.deepEqual(style(btn, ['height','padding','borderRadius','fontSize','fontWeight','display']),
      {height:'32px',padding:'0px 14px',borderRadius:'5px',fontSize:'13px',fontWeight:'500',display:'inline-flex'});
    assert.equal(btn.style.background, 'rgb(217, 119, 87)');
    ui.flush(() => btn.click()); assert.equal(calls, 1);
    ui.flush(() => btn.focus());
    assert.equal(ui.doc.activeElement, btn, 'native button is keyboard focusable');
    assert.match(btn.style.boxShadow, /0 0 0 4px/, 'keyboard focus has the plate offset accent ring');
    const disabled = ui.render('Btn', {disabled:true,onClick:() => calls++,sm:true}, 'Retry');
    ui.flush(() => disabled.click());
    assert.equal(calls, 1, 'disabled native button refuses activation');
    assert.equal(disabled.disabled, true); assert.equal(disabled.style.height, '26px');
    assert.equal(disabled.style.borderStyle, 'dashed');
    const settings = ui.render('Btn', {variant:'settings'}, 'Connect');
    assert.equal(settings.style.height, '34px'); assert.equal(settings.style.borderRadius, '8px');
    const busy = ui.render('Btn', {loading:true}, 'Run');
    assert.equal(busy.getAttribute('aria-busy'), 'true');
    assert.equal(busy.querySelector('span').style.width, '12px');
  } finally {ui.close();}
});

test('DS-PORT native button refs work with the actual shipped React 18 runtime', async () => {
  const ui=await primitives();
  try {
    assert.match(ui.win.React.version,/^18\./,'court uses the shipped React 18 vendor');
    const ref=ui.win.React.createRef();
    const button=ui.render('Btn',{ref},'Restore focus');
    assert.equal(ref.current,button,'Btn forwards the caller ref to its native button');
    assert.equal(ref.current.tagName,'BUTTON');
    ui.flush(()=>ref.current.focus());
    assert.equal(ui.doc.activeElement,button,'existing dialog/menu focus restoration remains usable');
  }finally{ui.close();}
});

test('DS-PORT Toggle and changed Row match plate geometry and invoke the owner', async () => {
  const ui = await primitives();
  try {
    const changed = [];
    const toggle = ui.render('Toggle', {checked:true,label:'Enabled',onCheckedChange:value => changed.push(value)});
    assert.equal(toggle.getAttribute('role'), 'switch');
    assert.equal(toggle.getAttribute('aria-checked'), 'true');
    assert.equal(toggle.getAttribute('aria-label'), 'Enabled');
    assert.deepEqual(style(toggle,['width','height']), {width:'30px',height:'18px'});
    assert.deepEqual(style(toggle.querySelector('i'),['width','height','left','top']),
      {width:'12px',height:'12px',left:'14px',top:'2px'});
    ui.flush(() => toggle.click()); assert.deepEqual(changed,[false]);
    const off = ui.render('Toggle', {disabled:true,label:'Enabled',onCheckedChange:value => changed.push(value)});
    ui.flush(() => off.click()); assert.deepEqual(changed,[false]);
    const settings = ui.render('Toggle', {variant:'settings',checked:true,label:'Read'});
    assert.deepEqual(style(settings,['width','height']), {width:'34px',height:'20px'});
    let resets = 0;
    const row = ui.render('Row', {k:'Theme',changed:true,hint:'Personal appearance',onReset:() => resets++}, 'Dark');
    assert.deepEqual(style(row,['gridTemplateColumns','minHeight','padding']),
      {gridTemplateColumns:'96px 1fr auto',minHeight:'32px',padding:'0px 12px'});
    assert.equal(row.querySelector('i').style.width, '6px');
    assert.match(row.textContent,/ThemeDarkPersonal appearanceReset/);
    ui.flush(() => row.querySelector('button').click()); assert.equal(resets,1);
  } finally {ui.close();}
});

test('DS-PORT typed Socket and Node anatomy snapshots match ds.jsx and ds_node.jsx', async () => {
  const ui = await primitives();
  try {
    let socket = ui.render('Socket', {type:'number',list:true,filled:true,hit:true});
    assert.deepEqual(style(socket,['width','height']), {width:'20px',height:'20px'});
    assert.equal(socket.firstElementChild.style.width,'10px');
    assert.equal(socket.firstElementChild.style.transform,'rotate(45deg) scale(.86)');
    socket = ui.render('Socket',{type:'any'});
    assert.equal(socket.firstElementChild.style.borderStyle,'dashed');
    socket = ui.render('Socket',{type:'event',filled:true});
    assert.equal(socket.querySelector('svg').getAttribute('width'),'12');
    assert.equal(socket.querySelector('path').getAttribute('d'),'M1 1 L11 6 L1 11 Z');
    const node = ui.render('Node',{glyph:'⌬',gc:'#5fb3b3',title:'Doors on Level 3',sub:'Host · Revit · read',
      ins:[{l:'level',t:'text'}],outs:[{l:'doors',t:'elements',list:true,f:true}],foot:'ran · 46 doors · 0.8 s',selected:true,edge:'l'});
    assert.deepEqual(style(node,['width','borderRadius','outlineOffset']),{width:'224px',borderRadius:'6px',outlineOffset:'2px'});
    assert.equal(node.style.borderLeftWidth,'4px');
    assert.equal(node.firstElementChild.style.padding,'7px 10px');
    assert.equal(node.firstElementChild.firstElementChild.style.width,'20px');
    assert.equal(node.firstElementChild.lastElementChild.style.width,'8px');
    assert.match(node.textContent,/Doors on Level 3Host · Revit · readleveldoorsran · 46 doors · 0.8 s/);
    assert.equal(node.querySelectorAll('[role="img"]').length,2);
    assert.equal(node.lastElementChild.style.fontSize,'11px');
  } finally {ui.close();}
});

test('DS-PORT live theme mutation recolours typed sockets and shared muted text', async () => {
  const ui=await primitives();
  const A=ui.win.AH,initial={accent:A.accent,inkSoft:A.inkSoft};
  try {
    const first=ui.render('Socket',{type:'elements',filled:true});
    const original=first.firstElementChild.style.background;
    A.accent='#123456';A.inkSoft='#abcdef';
    const socket=ui.render('Socket',{type:'elements',filled:true});
    assert.equal(socket.firstElementChild.style.background,'rgb(18, 52, 86)','typed Socket reads the current live accent');
    assert.notEqual(socket.firstElementChild.style.background,original);
    const any=ui.render('Socket',{type:'any'});
    assert.equal(any.firstElementChild.style.borderColor,'rgb(171, 205, 239)','Any socket reads the current muted ink');
    assert.equal(ui.win.AH_DS.styles.muted.color,'#abcdef','shared muted style follows the live token owner');
  }finally{Object.assign(A,initial);ui.close();}
});

test('DS-PORT Card, Rail, Composer and actionable EmptyState share plate shells', async () => {
  const ui = await primitives();
  try {
    let card = ui.render('Card',{title:'Watch',glyph:'◎',gc:'#7ec18e',foot:'Nothing wired in'});
    assert.equal(card.style.width,'224px');
    card = ui.render('Card',{variant:'settings'},'Connections');
    assert.equal(card.style.borderRadius,'14px'); assert.match(card.style.background,/linear-gradient/);
    let navigated = 0;
    const rail = ui.render('Rail',{label:'Library',glyph:'▦',active:true,onClick:() => navigated++});
    assert.equal(rail.tagName,'BUTTON'); assert.equal(rail.getAttribute('aria-label'),'Library');
    assert.equal(rail.getAttribute('aria-current'),'page');
    assert.deepEqual(style(rail,['width','height']),{width:'44px',height:'52px'});
    ui.flush(() => rail.click()); assert.equal(navigated,1);
    const composer = ui.render('Composer',{'aria-label':'Ask',as:'form'},ui.win.React.createElement('textarea',{'aria-label':'Message'}));
    assert.equal(composer.tagName,'FORM'); assert.equal(composer.style.borderRadius,'10px');
    assert.equal(composer.style.display,'grid');
    composer.querySelector('textarea').focus();
    assert.equal(ui.doc.activeElement.tagName,'TEXTAREA','composer keeps native keyboard entry');
    let retries = 0;
    const empty = ui.render('EmptyState',{title:'The library could not be read',detail:'Try reading it again.',error:true,onRetry:() => retries++});
    assert.equal(empty.getAttribute('role'),'alert');
    assert.match(empty.textContent,/The library could not be readTry reading it again.Retry/);
    ui.flush(() => empty.querySelector('button').click()); assert.equal(retries,1);
  } finally {ui.close();}
});

test('DS-PORT error copy hides internal roots, paths, addresses and tokens while retaining ordinary errors', async () => {
  const ui = await primitives();
  try {
    const explain = ui.win.AH_DS.errorText;
    assert.equal(typeof explain,'function');
    for(const raw of ['relation root is missing','Failed at C:\\Users\\owner\\AppData\\Local\\Temp\\lane',
      'Request refused by http://127.0.0.1:51058','Invalid accent_dim / l_bg','Could not open %TEMP%\\fixture']) {
      const text = explain(raw);
      assert.notEqual(text,raw,'internal detail is translated: '+raw);
      assert.doesNotMatch(text,/relation root is missing|AppData|127\.0\.0\.1|%TEMP%|accent_dim|l_bg/i);
      assert.match(text,/retry|refresh|select/i,'translated error offers a fixing action');
      const empty = ui.render('EmptyState',{error:true,title:'Could not complete the action',detail:text,onRetry:()=>{}});
      assert.equal(empty.getAttribute('role'),'alert');
      assert.match(empty.textContent,/Retry/);
      const rawEmpty=ui.render('EmptyState',{error:true,title:raw,detail:raw,onRetry:()=>{}});
      assert.doesNotMatch(rawEmpty.textContent,/relation root is missing|AppData|127\.0\.0\.1|%TEMP%|accent_dim|l_bg/i,
        'the real EmptyState boundary translates raw errors without requiring every caller to format them');
      assert.match(rawEmpty.textContent,/Retry/,'raw errors keep the fixing action');
    }
    assert.equal(explain('Revit stopped responding. Try again.'),'Revit stopped responding. Try again.');
  } finally {ui.close();}
});

test('DS-PORT compact EmptyState ports the dashed empty-session plate shell', async () => {
  const ui=await primitives();
  try {
    const empty=ui.render('EmptyState',{compact:true,glyph:null,title:'Empty session',
      action:ui.win.React.createElement(ui.win.AH_DS.Btn,{kind:'primary',sm:true},'Add node')});
    assert.equal(empty.style.borderStyle,'dashed','inputs/ds.jsx empty session has a dashed border');
    assert.equal(empty.style.borderRadius,'8px');
    assert.equal(empty.style.padding,'12px');
    assert.equal(empty.style.gap,'8px');
    assert.equal(empty.firstElementChild.style.fontWeight,'400','plate empty-session title has normal weight');
    assert.equal(empty.querySelector('button').textContent,'Add node');
  }finally{ui.close();}
});

function factories(text) {
  return [...text.matchAll(/\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*(?:\([^;]*?\)|[A-Za-z_$][\w$]*)\s*=>\s*\(\s*\{/g)]
    .map(m => m[1]).filter(name => /btn|button/i.test(name));
}
test('DS-PORT no local style button factories remain in studio-lm and both mess counts drop against main', () => {
  const lm = read('01.APP/nodelang/studio/studio-lm.jsx');
  assert.doesNotMatch(lm,/<button\b/,'all Studio actions compose the ONE shared Btn');
  assert.deepEqual(factories(lm),[], 'style factories belong to ds/');
  assert.doesNotMatch(lm,/\bconst\s+HoverBtn\s*=/,'HoverBtn is replaced by shared Btn');
  const files = execFileSync('git',['ls-tree','-r','--name-only','b16bd72f','01.APP/nodelang/studio'],{cwd:root,encoding:'utf8'}).trim().split(/\r?\n/)
    .filter(file => /^01.APP\nodelang\/studio\/[^/]+\.jsx$/.test(file));
  const before = files.map(file => execFileSync('git',['show','b16bd72f:'+file],{cwd:root,encoding:'utf8',maxBuffer:2*1024*1024})).join('\n');
  const after = fs.readdirSync(path.join(root,'01.APP/nodelang/studio')).filter(file => file.endsWith('.jsx')).map(file => read('01.APP/nodelang/studio/'+file)).join('\n');
  assert.ok(factories(after).length < factories(before).length,'local button helpers strictly decrease');
  assert.ok((after.match(/style=\{\{/g)||[]).length < (before.match(/style=\{\{/g)||[]).length,'inline style objects strictly decrease');
});

async function studio({hungLibrary=false}={}) {
  const ui = await browser(), win = ui.win;
  const graph = {nodes:[],wires:[]};
  const authorization = {subject:'ds-owner',session:'ds-view',system_view:true};
  const canvas = {graph_id:'ds-graph',application_root:'ds-graph',root:'ds-scope',revision:7,authorization};
  const snapshot = {canvas,topology:{canvas:{...canvas,scope:{current:'ds-scope'}},graph,selected:null},graph,
    workshops:[],workshop:{root:'ds-room',graph_id:'ds-graph',scope_root:'ds-scope',messages:[],participants:[],workflows:[]},
    theme:{configuration:{},pending:false,error:''},applicationUpdate:{state:'idle',current_build:'20261016-dsport'}};
  const tools = ['studio','workshop','brain','baboom','connectors','cloud'].map(id => ({id,label:id==='baboom'?'BABOOM':id[0].toUpperCase()+id.slice(1),state:'running',state_word:'RUNNING',description:'Ready.',stat_line:'Ready.',wire_summary:''}));
  win.fetch = url => Promise.resolve({ok:true,json:async()=>String(url)==='/tools'?{ok:true,tools}:String(url)==='/waiting'?{ok:true,items:[]}:{ok:true,groups:[],templates:[],settings:{},selected_route:'openrouter/free'}});
  const owner = {getSnapshot:()=>snapshot,subscribe:()=>()=>{},watchApplicationUpdate:()=>()=>{},
    readHomeTemplates:async()=>({ok:true,templates:[]}),refreshHomeWorkshops:async()=>{},refreshTopologyCanvas:async()=>snapshot.topology,refreshWorkshop:async()=>snapshot.workshop};
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner,{get:(o,k)=>k in o || k==='then'?o[k]:()=>new Promise(()=>{})});
  win.ARCHHUB_THEME = {};
  win.ARCHHUB_LIVE = {sessions:[],currentGraph:null,hosts:[],connectors:[],graph,memory:[],skills:[]};
  win.ARCHHUB_TOOL_HUB = {ok:true,tools,waiting:[]};
  win.AH_LIBRARY = []; win.AH_LIBRARY_LOADED = !hungLibrary;
  win.AH_LOAD_LIBRARY = hungLibrary?()=>new Promise(()=>{}):async()=>[];
  const loader = read('01.APP/nodelang/studio/studio.html');
  const names = loader.match(/const names = \[([\s\S]*?)\];/);
  assert.ok(names,'Studio owns a real ordered loader list');
  const sources = [...names[1].matchAll(/['"]([^'"]+\.jsx)['"]/g)].map(m=>m[1]);
  assert.ok(sources.includes('ds/index.jsx'),'the real Studio loader includes ds/');
  assert.ok(sources.indexOf('ds/index.jsx')<sources.indexOf('shared-data.jsx'),'DS loads before all consumers');
  const calls = Object.fromEntries(required.map(name=>[name,0]));
  for (const file of sources) if(file!=='mount.jsx'&&file!=='tokens.jsx') {
    if(file==='studio-lm.jsx') {
      const code = sourceCode(file).replace(/window\.StudioLM\s*=\s*StudioLM\s*;/,
        'window.StudioLM = StudioLM; window.__DSConsumers = {Settings54Switch,Settings54ParamRow,FloatingComposer,useDeferredCanvas,LazyWorkshopWindow,SettingsEmpty};');
      assert.match(code,/window\.__DSConsumers/,'real consumer functions are exposed only in this test');
      win.eval(code);
    } else ui.evaluate(file);
    if(file==='ds/index.jsx') {
      const originals=win.AH_DS;
      win.AH_DS={...originals,...Object.fromEntries(required.map(name=>[name,function CountedPrimitive(props) {
        calls[name]++; return win.React.createElement(originals[name],props);
      }]))};
    }
  }
  win.eval('window.__dsRoot=ReactDOM.createRoot(document.getElementById("root"));ReactDOM.flushSync(()=>window.__dsRoot.render(React.createElement(StudioLM)));');
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = (ms=60) => new Promise(resolve=>win.setTimeout(resolve,ms));
  const click = async label => {
    const control = ui.doc.querySelector('[data-app-rail] [data-rail-panel="'+label+'"]');
    assert.ok(control,label+' rail destination exists');
    flush(()=>control.click()); await settle();
  };
  return {...ui,snapshot,calls,click,settle,flush,close:()=>{flush(()=>win.__dsRoot.unmount());ui.close();}};
}
function visibleText(doc) {
  const body = doc.getElementById('root').cloneNode(true);
  for (const item of body.querySelectorAll('[data-app-rail], script, style, [aria-hidden="true"], [role="status"]')) item.remove();
  return body.textContent.replace(/\s+/g,' ').trim();
}
const banned = /Not available yet|\bnot read\b|Unversioned build|127\.0\.0\.1|%TEMP%|AppData[\\/]|accent_dim|l_bg|members:\s*\d+\s*·\s*status:\s*available|relation root is missing|ran 0×/i;
function assertClean(doc,label) {
  const text = doc.getElementById('root').textContent+' '+[...doc.querySelectorAll('input,textarea')].map(n=>n.placeholder).join(' ');
  assert.doesNotMatch(text,banned,label+' contains no banned user-facing fallback/internal string');
}
test('DS-PORT every rail destination renders pairwise distinct real content and clean empty DOM', async () => {
  const ui = await studio();
  try {
    await ui.settle();
    const views = new Map();
    const destinations=['Home','Chats','Workshop','Canvas','Library','Settings','Docs','Account'];
    const discovered=[...ui.doc.querySelectorAll('[data-app-rail] [data-rail-panel]')].map(n=>n.dataset.railPanel).sort();
    assert.deepEqual(discovered,[...destinations].sort(),'every actual rail control is exercised');
    for (const label of destinations) {
      // Plates have different rails. Start each route from the full Home rail rather than
      // requiring Library/Workshop to repeat destinations their plates omit.
      if(!ui.doc.querySelector('[data-app-rail] [aria-label="Home"]')) await ui.click('Chats');
      await ui.click('Home');
      await ui.click(label);
      assertClean(ui.doc,label);
      const text = visibleText(ui.doc);
      assert.ok(text.length>5,label+' renders content');
      assert.ok(!views.has(text),label+' duplicates '+views.get(text));
      views.set(text,label);
      if(['Chats','Workshop','Canvas','Library'].includes(label))
        assert.equal(ui.doc.querySelector('[data-home-page]'),null,label+' does not leave Home in its main view');
    }
    assert.equal(views.size,destinations.length);
  } finally {ui.close();}
});
test('DS-PORT a hung Library read settles into an actionable EmptyState within two seconds', async () => {
  const ui = await studio({hungLibrary:true});
  try {
    await ui.click('Library'); await ui.settle(2100);
    assert.doesNotMatch(ui.doc.getElementById('root').textContent,/Loading(?: nodes)?…/i,'loading cannot remain forever');
    const retry = [...ui.doc.querySelectorAll('button')].find(b=>/^Retry$/i.test(b.textContent.trim()));
    assert.ok(retry,'hung read offers Retry');
    assert.ok(retry.closest('[role="alert"], [role="status"]'),'Retry belongs to designed EmptyState');
    assertClean(ui.doc,'Library timeout');
  } finally {ui.close();}
});

test('DS-PORT the real deferred canvas hook times out, retries its owner and fences a stale generation', async () => {
  const ui=await studio();let hookRoot;
  try {
    const resolvers=[];let reads=0;
    ui.snapshot.topology.canvas.canvas_deferred=true;
    ui.win.ARCHHUB_LOAD_CANVAS=()=>{reads++;return new Promise(resolve=>resolvers.push(resolve));};
    const e=ui.win.React.createElement;
    function CanvasReadProbe() {
      const state=ui.win.__DSConsumers.useDeferredCanvas();
      return state.pending || state.error ? e(ui.win.AH_DS.EmptyState,{title:state.pending?'Reading canvas':'Canvas unavailable',
        error:!!state.error,detail:state.error,onRetry:state.error?state.retry:undefined}) : e('div',{'data-canvas-ready':''},'Canvas ready');
    }
    const host=ui.doc.createElement('div');ui.doc.body.appendChild(host);hookRoot=ui.win.ReactDOM.createRoot(host);
    ui.flush(()=>hookRoot.render(e(CanvasReadProbe)));await ui.settle();
    assert.equal(reads,1);assert.match(host.textContent,/Reading canvas/);
    await ui.settle(2050);
    assert.ok(host.querySelector('[role="alert"]'),'a hung actual canvas hook returns an error within two seconds');
    const retry=[...host.querySelectorAll('button')].find(b=>b.textContent==='Retry');assert.ok(retry);
    ui.flush(()=>retry.click());await ui.settle();assert.equal(reads,2,'Retry reissues the real owner read');
    resolvers[0]();await ui.settle();
    assert.equal(host.querySelector('[data-canvas-ready]'),null,'late first-generation success cannot settle the retry');
    assert.match(host.textContent,/Reading canvas/);
    resolvers[1]();await ui.settle();assert.ok(host.querySelector('[data-canvas-ready]'),'current generation settles normally');
  }finally{if(hookRoot)ui.flush(()=>hookRoot.unmount());ui.close();}
});

test('DS-PORT the real lazy Workshop wrapper bounds loading and forwards props after a fenced retry', async () => {
  const ui=await studio();let viewRoot;
  try {
    const resolvers=[];let reads=0;
    ui.win.WorkshopView=null;
    ui.win.ARCHHUB_LOAD_WORKSHOP=()=>{reads++;return new Promise(resolve=>resolvers.push(resolve));};
    const e=ui.win.React.createElement,Lazy=ui.win.__DSConsumers.LazyWorkshopWindow;
    const host=ui.doc.createElement('div');ui.doc.body.appendChild(host);viewRoot=ui.win.ReactDOM.createRoot(host);
    ui.flush(()=>viewRoot.render(e(Lazy,{marker:'retained-workshop-prop'})));await ui.settle();
    assert.equal(reads,1);
    await ui.settle(2050);
    assert.ok(host.querySelector('[role="alert"]'),'hung Workshop module read becomes an error');
    const retry=[...host.querySelectorAll('button')].find(b=>b.textContent==='Retry');assert.ok(retry,'timeout uses actionable shared EmptyState');
    ui.flush(()=>retry.click());await ui.settle();assert.equal(reads,2);
    const Loaded=props=>e('div',{'data-loaded-workshop':props.marker},'Workshop ready');
    resolvers[0](Loaded);await ui.settle();assert.equal(host.querySelector('[data-loaded-workshop]'),null,'stale lazy module cannot replace the retry');
    resolvers[1](Loaded);await ui.settle();
    assert.equal(host.querySelector('[data-loaded-workshop]').dataset.loadedWorkshop,'retained-workshop-prop','the real wrapper preserves its caller props');
  }finally{if(viewRoot)ui.flush(()=>viewRoot.unmount());ui.close();}
});

test('DS-PORT actual Studio settings, rail and composer consumers invoke the ONE shared primitives', async () => {
  const ui = await studio();
  let consumerRoot;
  try {
    await ui.settle();
    assert.ok(ui.calls.Btn>0,'real Studio actions render shared Btn');
    assert.ok(ui.calls.Rail>0,'real application rail renders shared Rail');
    const el=ui.win.React.createElement,C=ui.win.__DSConsumers;
    const host=ui.doc.createElement('div'); ui.doc.body.appendChild(host);
    consumerRoot=ui.win.ReactDOM.createRoot(host);
    const before={...ui.calls}; let toggles=0,resets=0,library=0;
    ui.flush(()=>consumerRoot.render(el(ui.win.React.Fragment,null,
      el(C.Settings54ParamRow,{label:'Enabled',changed:true,onReset:()=>resets++},
        el(C.Settings54Switch,{on:true,label:'Enabled',onClick:()=>toggles++})),
      el(C.FloatingComposer,{model:{name:'Selected model',route:'openrouter/free'},setLibraryOpen:()=>library++}))));
    assert.ok(ui.calls.Row>before.Row,'actual Settings54ParamRow renders shared Row');
    assert.ok(ui.calls.Toggle>before.Toggle,'actual Settings54Switch renders shared Toggle');
    assert.ok(ui.calls.Composer>before.Composer,'actual FloatingComposer renders shared Composer');
    const toggle=host.querySelector('[role="switch"]'); assert.ok(toggle);
    ui.flush(()=>toggle.click()); assert.equal(toggles,1,'shared toggle retains real owner callback');
    const action=text=>[...host.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
    ui.flush(()=>action('Reset').click()); assert.equal(resets,1);
    ui.flush(()=>action('library').click()); assert.equal(library,1);
  } finally {if(consumerRoot)ui.flush(()=>consumerRoot.unmount());ui.close();}
});

test('DS-PORT mixed SettingsEmpty children sanitize diagnostics and preserve the real action', async () => {
  const ui=await studio();let consumerRoot;
  try {
    const e=ui.win.React.createElement,host=ui.doc.createElement('div');ui.doc.body.appendChild(host);
    consumerRoot=ui.win.ReactDOM.createRoot(host);let retries=0;
    ui.flush(()=>consumerRoot.render(e(ui.win.__DSConsumers.SettingsEmpty,{role:'alert'},[
      'The workspace registry could not be read: ',
      'relation root is missing at C:\\Users\\owner\\AppData\\Local\\Temp\\lane',
      e(ui.win.AH_DS.Btn,{key:'retry',onClick:()=>retries++},'Retry'),
    ])));
    assert.doesNotMatch(host.textContent,/relation root is missing|AppData|C:\\Users/i,
      'the actual mixed-children boundary translates each raw diagnostic string');
    assert.match(host.textContent,/workspace registry could not be read/,'ordinary prefix is retained');
    const action=host.querySelector('button');assert.ok(action,'mixed children retain their real action element');
    ui.flush(()=>action.click());assert.equal(retries,1,'diagnostic translation preserves action callback');
  }finally{if(consumerRoot)ui.flush(()=>consumerRoot.unmount());ui.close();}
});

test('DS-PORT the retired cockpit navigates to the ONE Studio with query and fragment intact', () => {
  const vm=require('node:vm');
  const html=read('01.APP/nodelang/studio/cockpit.html');
  const script=html.match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(script,'retired route contains explicit redirect');
  const navigations=[];
  vm.runInNewContext(script[1],{location:{search:'?project=demo',hash:'#graph',replace:url=>navigations.push(url)}});
  assert.deepEqual(navigations,['/studio/studio.html?project=demo#graph']);
  assert.doesNotMatch(html,/src=["'][^"']*atlas-/,'retired route loads no old atlas module');
});
