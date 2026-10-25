'use strict';
// Independent DS-PORT acceptance: real plate primitives and mounted Studio routes.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

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
