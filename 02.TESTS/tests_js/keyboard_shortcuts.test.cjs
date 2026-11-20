const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const React=require('react'),{transformSync}=require('esbuild');
const {setImmediate}=require('node:timers');
const {structuredClone,Uint8Array}=globalThis;
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');

test('one saved keybinding drives actual matching, aliases and menu hints',()=>{
 let keys={},pending=false;
 const window={AH:{},AH_DS:{},ArchHubAPI:{getSnapshot:()=>({keybindings:keys,keyboardPending:pending})},registerActions:()=>{},ArchHubRouteNames:{},
  ArchHubCommandRegistry:{commands:[
   {id:'menu.copy',label:'Copy',shortcut:'Ctrl C',contexts:['node'],read_only:true},
   {id:'menu.copy.57',label:'Copy',keyFrom:'menu.copy',shortcut:'Ctrl C',contexts:['selection'],read_only:true},
   {id:'keyboard.save_as',label:'Save as',shortcut:'Ctrl Shift S',contexts:['canvas'],read_only:true},
  ]}};
 const context={window,React};
 for(const name of ['ui.jsx','context-menus.jsx'])vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio,name),'utf8'),{loader:'jsx'}).code,context);
 const event=(key,ctrlKey=false,shiftKey=false,extra={})=>({key,ctrlKey,shiftKey,altKey:false,metaKey:false,repeat:false,isComposing:false,...extra});
 assert.equal(window.UI.matchesShortcut('menu.copy',event('c',true)),true);
 pending=true;
 assert.equal(window.UI.matchesShortcut('menu.copy',event('c',true)),false,'unresolved overrides must not run a possibly replaced default');
 pending=false;
 keys={'menu.copy':'Ctrl Shift C'};
 assert.equal(window.UI.matchesShortcut('menu.copy',event('c',true)),false,'old chord stops running');
 assert.equal(window.UI.matchesShortcut('menu.copy.57',event('C',true,true)),true,'selection alias reads same preference');
 assert.equal(window.UI.matchesShortcut('menu.copy',event('C',true,true,{repeat:true})),false);
 assert.equal(window.UI.matchesShortcut('menu.copy',event('C',true,true,{isComposing:true})),false);
 const hints=()=>window.UI.commandGroups('node',[[{id:'menu.copy',action:()=>{}}]])[0][0][2];
 assert.equal(hints(),'Ctrl Shift C','menu shows the executed chord');
 keys={'menu.copy':''};
 assert.equal(window.UI.matchesShortcut('menu.copy',event('c',true)),false);
 assert.equal(hints(),'','unbound action does not show its old default');
 keys={};
 assert.equal(window.UI.shortcutFor('menu.copy'),'Ctrl C');
 assert.equal(window.UI.matchesShortcut('keyboard.save_as',event('S',true,true)),true);
 assert.equal(window.UI.matchesShortcut('menu.copy',event('c',false,false,{metaKey:true})),true,'primary modifier remains platform-aware');
});

test('pending keyboard read does not delay first-file startup and resolves overrides without Settings',async()=>{
 for(const surface of ['home','canvas'])for(const newer of [false,true]){
  const requests=[],warnings=[];let releaseKeys;
  const storage=()=>{const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key),key:index=>[...values.keys()][index]??null,get length(){return values.size;}};};
  const response=data=>({ok:true,status:200,headers:{get:()=>null},json:async()=>data});
  const window={ARCHHUB_BOOT:{token:'test',csrf:'test',nograph:true},crypto:require('node:crypto').webcrypto,structuredClone,
   localStorage:storage(),sessionStorage:storage(),addEventListener(){},dispatchEvent(){},ArchHubStudioAuthority:{create:()=>({getSnapshot:()=>({canvas:null})})}};
  const context={window,document:{hidden:false,addEventListener(){}},sessionStorage:window.sessionStorage,localStorage:window.localStorage,
   setTimeout,clearTimeout,URLSearchParams,TextEncoder,AbortSignal,AbortController,Uint8Array,CustomEvent:class {},console:{...console,warn:(...args)=>warnings.push(args.join(' '))},
   fetch:async(url,options)=>{
    const body=options?.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/commands')return response({commands:[{id:'menu.copy',shortcut:'Ctrl C',action:{}}]});
    if(body?.function==='readKeybindings')return new Promise(resolve=>{releaseKeys=()=>resolve(response({ok:true,result:{keybindings:{'menu.copy':'Ctrl Shift C'},keyboardCommands:[],keyboardError:''}}));});
    if(body?.function==='setKeybinding')return response({ok:true,result:{keybindings:{'menu.copy':'Ctrl Alt C'},keyboardCommands:[],keyboardError:''}});
    if(body?.function==='readLibraryCollapsed')return response({ok:true,result:{libraryCollapsed:[]}});
    if(url==='/api/universal/studio-surface')return response({ok:true});
    return new Promise(()=>{});
   }};
  vm.runInNewContext(fs.readFileSync(path.join(studio,'api.js'),'utf8'),context);
  window.ArchHubAPI.setActiveSurface(surface);
  for(let i=0;i<50&&!releaseKeys;i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(typeof releaseKeys,'function');
  for(let i=0;i<50&&!requests.some(row=>row.url==='/api/session-files');i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.some(row=>row.url==='/api/session-files'),true,'first file starts while only keyboard read is pending');
  assert.equal(window.ArchHubAPI.getSnapshot().keyboardPending,true);
  assert.equal(typeof window.ArchHubAPI.getSnapshot,'function','Home and Canvas retain their state API');
  if(newer)await window.ArchHubAPI.setKeybinding('menu.copy','Ctrl Alt C');
  releaseKeys();
  for(let i=0;i<50&&window.ArchHubAPI.getSnapshot().keyboardPending;i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(window.ArchHubAPI.getSnapshot().keyboardPending,false);
  assert.equal(window.ArchHubAPI.getSnapshot().keybindings['menu.copy'],newer?'Ctrl Alt C':'Ctrl Shift C','older boot reads preserve newer accepted edits');
  assert.equal(requests.some(row=>row.body?.function==='readControls'),false,'Settings has not been visited');
  assert.equal(window.ArchHubCommandRegistry.commands[0].id,'menu.copy');
  assert.deepEqual(warnings,[]);
 }
});

test('remapped save preserves typing and the primary-modifier save inside text fields',()=>{
 const source=fs.readFileSync(path.join(studio,'ds_screens.jsx'),'utf8');
 const start=source.indexOf('      const listener = e => {');
 const stop=source.indexOf("      window.addEventListener('keydown', listener);",start);
 let binding='S',saved=0;
 const window={UI:{matchesShortcut:(id,event)=>id==='keyboard.save'&&(binding==='S'?event.key==='s'&&!event.ctrlKey:event.key==='s'&&event.ctrlKey)}};
 const listener=vm.runInNewContext(source.slice(start,stop)+'\nlistener;',{window,preview:false,u:{act:run=>run()},api:{saveSession:()=>saved++,saveSessionAs:()=>saved++}});
 const event=(typing,ctrlKey=false)=>({key:'s',ctrlKey,metaKey:false,isComposing:false,defaultPrevented:false,
  target:{closest:()=>typing?{}:null},preventDefault(){this.defaultPrevented=true;}});
 listener(event(true));
 assert.equal(saved,0,'typing the remapped plain key must not save');
 listener(event(false));
 assert.equal(saved,1,'the configured plain key still saves outside text fields');
 binding='Ctrl S';
 listener(event(true,true));
 assert.equal(saved,2,'primary-modifier save retains its existing text-field behavior');
});
