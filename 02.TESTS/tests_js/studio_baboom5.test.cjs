const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('./studio_ds_context.cjs');
const {mounted, read} = require('./workshop72_regression_helpers.cjs');
const {fixture} = require('./workshop72_fixture.cjs');

test('BABOOM5 one shared rail opens Chats and every destination from the mounted frame', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react'), {createRoot} = require('react-dom/client'), {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>', {pretendToBeVisual:true});
  const prior = {window:global.window, document:global.document};
  global.window=dom.window; global.document=dom.window.document;
  const calls=[];
  const context=vm.createContext({React,window:dom.window,document:dom.window.document,
    useWorkshopProjection:()=>({}),workshopWaitingItems:()=>[]});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'),context);
  context.LM=dom.window.AH;
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/shared-data.jsx'),{loader:'jsx'}).code,context);
  const source=read('01.APP/nodelang/studio/studio-lm.jsx');
  const start=source.indexOf('// DSYS-060 app frame parts.');
  vm.runInContext(transformSync(source.slice(start,source.indexOf('const CommandBar = (',start))+'\nglobalThis.Frame=Frame;',{loader:'jsx'}).code,context);
  const root=createRoot(dom.window.document.getElementById('root'));
  try {
    await React.act(async()=>root.render(React.createElement(context.Frame,{
      onHome:()=>calls.push('Home'),onChats:()=>calls.push('Chats'),onWorkshop:()=>calls.push('Workshop'),
      onDocs:()=>calls.push('Docs'),onCockpit:()=>calls.push('Cockpit'),onCanvas:()=>calls.push('Canvas'),onPanel:name=>calls.push(name),onSettings:()=>calls.push('Settings'),account:{},
    })));
    assert.equal(dom.window.document.querySelectorAll('[data-app-rail]').length,1);
    for(const name of ['Home','Chats','Workshop','Canvas','Library','Docs','Settings','Account']) {
      const button=dom.window.document.querySelector(`[aria-label="${name}"]`);
      assert.ok(button,name+' is visible');
      await React.act(async()=>button.click());
    }
    assert.deepEqual(calls,['Home','Chats','Workshop','Canvas','nodes','Docs','Settings','Settings']);
    // UIFIX p3: Cockpit had no real content in this build and was removed from the rail (RULE 2); it must stay absent.
    assert.equal(dom.window.document.querySelector('[aria-label="Cockpit"]'), null, 'Cockpit must not be in the rail');
  } finally {await React.act(async()=>root.unmount());dom.window.close();Object.assign(global,prior);}
});

test('BABOOM5 Workshop rail leaves for Chats in one click', async()=>{
  const f=fixture(); let chats=0;
  const ui=await mounted(f.state,f.authority,{onChats:()=>chats++});
  try {
    assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length,1);
    await ui.click(ui.doc.querySelector('[data-rail-panel="Chats"]'));
    assert.equal(chats,1);
  } finally {await ui.close();}
});

test('BABOOM5 native HTML mounts the actual shared Approve card and awaits its channel receipt', async()=>{
  const {execFileSync}=require('node:child_process');
  const {fileURLToPath}=require('node:url');
  const fs=require('node:fs');
  const {JSDOM}=await import('jsdom');
  const html=execFileSync('C:\\Users\\fargaly\\AppData\\Local\\ArchHub\\.venv\\Scripts\\python.exe',
    ['-c','from nodelang.baboom_native_companion import baboom_approval_html; print(baboom_approval_html({"title":"Remember","summary":"Remember blue?","state":"needs-user","id":"reviewed"}, "binding-court"))'],{encoding:'utf8'});
  const dom=new JSDOM(html,{runScripts:'outside-only',pretendToBeVisual:true});
  const win=dom.window, calls=[], listeners=new Set();
  win.qt={webChannelTransport:{}};
  const bridge={settled:{connect:fn=>listeners.add(fn),disconnect:fn=>listeners.delete(fn)},
    decide:(binding,choice)=>calls.push({binding,choice})};
  win.QWebChannel=function(_,callback){callback({objects:{baboom:bridge}});};
  try {
    for(const script of win.document.querySelectorAll('script')) {
      if(script.src.startsWith('qrc:')) continue;
      win.eval(script.src ? fs.readFileSync(fileURLToPath(script.src),'utf8') : script.textContent);
    }
    for(let i=0;i<50&&!win.document.querySelector('[data-approval-component=shared]');i++)await new Promise(resolve=>setTimeout(resolve,10));
    const approve=win.document.querySelector('[data-workshop-primary=approve]');
    assert.ok(approve,'actual shared card is mounted from production HTML');
    assert.equal(approve.textContent,'Remember');
    approve.click();approve.click();
    await new Promise(resolve=>setTimeout(resolve,20));
    assert.deepEqual(calls,[{binding:'binding-court',choice:'approve'}]);
    assert.equal(approve.disabled,true,'awaits real receipt');
    for(const listener of listeners)listener('binding-court','');
    await new Promise(resolve=>setTimeout(resolve,20));
    assert.equal(approve.disabled,true,'single use after receipt');
  } finally {dom.window.close();}
});


test('BABOOM5 Chats leaves an active graph Workshop conversation and shows conversations', async()=>{
  const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
  const filename=path.join(__dirname,'studio_workshop_open.test.cjs');
  const harness=new Module(filename,module);harness.filename=filename;harness.paths=module.paths;
  const source=fs.readFileSync(filename,'utf8');
  harness._compile(source.slice(0,source.indexOf("\ntest('"))+'\nmodule.exports={mountStudio};',filename);
  const transcript={ok:true,graph_id:'graph-a',root:'room-a',scope_root:'scope-a',revision:7,
    owner:'owner-a',view:'view-a',self:'owner-a',can_send:true,can_join:false,
    participants:[{root:'owner-a',label:'Owner',attached:true}],messages:[]};
  const ui=await harness.exports.mountStudio({workshops:[{root:'room-a',label:'Wall conversion',is_general:false}],workshop:transcript});
  try {
    ui.flush(()=>ui.segment('Workshop').click());
    assert.ok(ui.doc.querySelector('[data-workshop72][data-workshop-id="room-a"]'),'real graph conversation is active');
    assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Workshop message"]').length,1);
    assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length,1);
    ui.flush(()=>ui.doc.querySelector('[data-app-rail] [aria-label="Chats"]').click());
    for(let i=0;i<20;i++)await new Promise(resolve=>ui.win.setTimeout(resolve,0));
    const panel=ui.doc.querySelector('[data-left-panel]');
    assert.ok(panel && /Chats/.test(panel.textContent),'shared rail must reveal the real conversations panel');
    assert.equal(ui.doc.querySelector('[data-rail-panel="Chats"]').getAttribute('aria-current'),'true');
    assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length,1);
  }finally{ui.close();}
});
