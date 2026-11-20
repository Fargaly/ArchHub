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
    if(body?.function==='exportPreferences')return response({ok:true,result:{settingsExport:{format:'archhub.settings',version:1,scopes:{Workspace:{'Appearance.Theme':'Light'}}}}});
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
  const exported=await window.ArchHubAPI.exportData('Settings','Workspace');
  assert.equal(exported.name,'ArchHub settings.json');
  assert.equal(JSON.parse(exported.content).scopes.Workspace['Appearance.Theme'],'Light');
  assert.equal(requests.find(row=>row.body?.function==='exportPreferences').body.args[0],'Workspace','final export owner dispatches the selected scope');
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

test('session switching rejects stale preference reads and flushes edits before a session setting write',async()=>{
 const requests=[],pending=new Map(),warnings=[];
 const storage=()=>{const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key),key:index=>[...values.keys()][index]??null,get length(){return values.size;}};};
 const doc=id=>({format:'archhub',version:1,id,title:id,nodes:[],wires:[],groups:[],notes:[],viewport:{x:0,y:0,zoom:1},properties:{revision:0,project:'tower'}});
 let held=doc('first');
 const response=data=>({ok:true,status:200,headers:{get:()=>null},json:async()=>data});
 const preferences=(id,scope='User')=>({appearanceSettings:[{id:'Appearance.Theme',page:'Appearance',label:'Theme',value:id==='first'?'Light':'Dark',default:'Dark'},{id:'Projects.Working subfolder',page:'Projects',label:'Working subfolder (relative)',value:'',default:''}],keybindings:{'menu.copy':id==='first'?'Ctrl Shift C':'Ctrl Alt C'},keyboardCommands:[],keyboardError:'',settingsScope:scope,settingsScopes:{Workspace:true,Session:true},settingsDestination:{scope,workspace:'tower',session:id,workspaceIdentity:'fixture-root'}});
 const window={ARCHHUB_BOOT:{token:'test',csrf:'test',nograph:true},crypto:require('node:crypto').webcrypto,structuredClone,
  localStorage:storage(),sessionStorage:storage(),addEventListener(){},dispatchEvent(){},ArchHubStudioAuthority:{create:()=>({getSnapshot:()=>({canvas:null})})}};
 const context={window,document:{hidden:false,addEventListener(){}},localStorage:window.localStorage,sessionStorage:window.sessionStorage,setTimeout,clearTimeout,URLSearchParams,TextEncoder,AbortSignal,AbortController,Uint8Array,CustomEvent:class {},console:{...console,warn:(...args)=>warnings.push(args.join(' '))},
  fetch:async(url,options)=>{
   const body=options?.body?JSON.parse(options.body):null;requests.push({url,body});
   if(url==='/api/commands')return response({commands:[]});
   if(url==='/api/universal/workspace-roots')return response({roots:[{root_id:'tower2',label:'Example',path:'C:/probe',privacy:'private'}]});
   if(body?.function==='readKeybindings')return response({ok:true,result:{keybindings:{},keyboardCommands:[],keyboardError:''}});
   if(body?.function==='readLibraryCollapsed')return response({ok:true,result:{libraryCollapsed:[]}});
   if(body?.function==='readPreferences')return new Promise(resolve=>{window.releasePreferenceRead=()=>resolve(response({ok:true,result:preferences('second','User')}));});
   if(body?.function==='readEffectivePreferences')return new Promise(resolve=>pending.set(body.context.session,()=>resolve(response({ok:true,result:preferences(body.context.session)}))));
   if(body?.function==='resetAppearance')return response({ok:true,result:preferences('second',body.context.settingsDestination.scope)});
   if(body?.function==='readOperations')return new Promise(resolve=>{window.releaseOperationsRead=()=>resolve(response({ok:true,result:{settingsScope:'User',activeWorkspace:'old-workspace',workspacePolicies:{tower2:{rules:'Retain the actual policy'}},devices:[{id:'read-device'}],backups:[{id:'read-backup'}]}}));});
   if(body?.function==='readControls')return new Promise(resolve=>{window.releaseControlRead=()=>resolve(response({ok:true,result:{...preferences('second','User'),companion:{readDuringScopeWrite:true}}}));});
   if(body?.function==='setSettingsScope'){if(window.deferScope)return new Promise(resolve=>{window.releaseScopeWrite=()=>resolve(response({ok:true,result:preferences('second',body.args[0])}));});return response({ok:true,result:preferences('second',body.args[0])});}
   if(body?.function==='setAppearance'){
    held={...held,properties:{...held.properties,revision:held.properties.revision+1,settings:{[body.args[0]]:body.args[1]}}};
    const result=preferences('second',body.context.settingsDestination?.scope||'Session');
    result.appearanceSettings=result.appearanceSettings.map(row=>row.id===body.args[0]?{...row,value:body.args[1]}:row);
    if(window.deferAppearance)return new Promise(resolve=>{window.releaseAppearance=()=>resolve(response({ok:true,result:{appearanceSettings:result.appearanceSettings}}));});
    return response({ok:true,result});
   }
   if(url==='/api/session-model'&&body.action==='set'){
    if(body.path!=='C:/probe/second.archhub')return response({ok:true,session:{id:'separate'}});
    held={...held,properties:{...held.properties,...body.values,revision:held.properties.revision+1}};
    return response({ok:true,session:{id:held.id,project:{id:held.properties.project}}});
   }
   if(url==='/api/session-files'){
    if(body.action==='initial')return response({ok:true,document:held,path:'C:/probe/first.archhub'});
    if(body.action==='open'){held=doc('second');return response({ok:true,document:held,path:'C:/probe/second.archhub'});}
    if(body.action==='validate')return response({ok:true,document:body.document});
    if(body.action==='autosave'){held={...body.document,properties:{...body.document.properties,revision:body.base_revision+1}};return response({ok:true,document:held,path:body.path,revision:held.properties.revision});}
    if(body.action==='head')return response({ok:true,revision:held.properties.revision});
    if(body.action==='read')return response({ok:true,document:held,revision:held.properties.revision});
   }
   if(url==='/api/universal/studio-surface')return response({ok:true});
   return new Promise(()=>{});
  }};
 vm.runInNewContext(fs.readFileSync(path.join(studio,'api.js'),'utf8'),context);
 window.ArchHubAPI.setActiveSurface('home');
 const turn=()=>new Promise(resolve=>setImmediate(resolve));
 for(let i=0;i<50&&!pending.has('first');i++)await turn();
 assert.equal(pending.has('first'),true);
 await window.ArchHubAPI.ready;
 for(let i=0;i<50&&!window.ArchHubAPI.getSnapshot().workspaces.some(row=>row.id==='tower2');i++)await turn();
 assert.equal(window.ArchHubAPI.getSnapshot().workspaces.some(row=>row.id==='tower2'),true,'Home discovers local workspaces while controls and network discovery are held');
 await window.ArchHubAPI.openSession('C:/probe/second.archhub');
 for(let i=0;i<50&&!pending.has('second');i++)await turn();
 pending.get('first')();await turn();
 assert.equal(window.ArchHubAPI.getSnapshot().graph.id,'second');
 assert.equal(window.ArchHubAPI.getSnapshot().keyboardPending,true,'old completion cannot release the new session shortcut guard');
 assert.notEqual(window.ArchHubAPI.getSnapshot().keybindings['menu.copy'],'Ctrl Shift C');
 pending.get('second')();await turn();
 assert.equal(window.ArchHubAPI.getSnapshot().keybindings['menu.copy'],'Ctrl Alt C');
 assert.equal(window.ArchHubAPI.getSnapshot().keyboardPending,false);
 window.ArchHubAPI.setActiveSurface('settings/Appearance');
 const olderRead=window.ArchHubAPI.refreshPreferences();
 await window.ArchHubAPI.setSettingsScope('Session');
 window.releasePreferenceRead();await olderRead;
 assert.equal(window.ArchHubAPI.getSnapshot().settingsScope,'Session','an older read cannot undo an accepted scope selection');
 assert.equal(window.ArchHubAPI.getSnapshot().settingsDestination.scope,'Session');
 window.ArchHubAPI.setSessionViewport({x:10,y:20,zoom:1});
 const begin=requests.length;
 await window.ArchHubAPI.setSetting('Appearance.Theme','Light');
 const saved=requests.slice(begin),write=saved.findIndex(row=>row.body?.function==='setAppearance');
 assert.equal(write>=0,true);
 assert.equal(saved.slice(0,write).some(row=>row.body?.action==='autosave'),true,'pending viewport edit reaches its file owner first');
 assert.equal(saved[write].body.context.session,'second');
 assert.equal(window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Appearance.Theme').value,'Light');
 window.ArchHubAPI.setSessionViewport({x:33,y:44,zoom:1});
 const modelBegin=requests.length;
 await window.ArchHubAPI.setSessionModel('C:/probe/second.archhub',{project:'tower2'});
 const modelRequests=requests.slice(modelBegin),modelWrite=modelRequests.findIndex(row=>row.url==='/api/session-model');
 assert.equal(modelRequests.slice(0,modelWrite).some(row=>row.body?.action==='autosave'),true);
 assert.equal(held.viewport.x,33,'unsaved viewport survives the session model write');
 assert.equal(window.ArchHubAPI.getSnapshot().graph.project,'tower2','Canvas adopts the owner model change');
 const revision=held.properties.revision;
 window.ArchHubAPI.setSessionViewport({x:55,y:66,zoom:1});
 const nextBegin=requests.length;
 await window.ArchHubAPI.setSetting('Appearance.Theme','Dark');
 assert.equal(requests.slice(nextBegin).find(row=>row.body?.action==='autosave').body.base_revision,revision,'next write uses the current owner revision');
 const separateBegin=requests.length;
 await window.ArchHubAPI.setSessionModel('C:/probe/separate.archhub',{project:'tower'});
 assert.equal(requests.slice(separateBegin).some(row=>row.body?.action==='autosave'),false,'separate-file edit does not save the current Canvas');
 assert.equal(window.ArchHubAPI.getSnapshot().graph.project,'tower2');
 await window.ArchHubAPI.setSettingsScope('Session');
 window.deferAppearance=true;
 const queueBegin=requests.length;
 const firstWrite=window.ArchHubAPI.setSetting('Appearance.Theme','Light');
 for(let i=0;i<50&&!window.releaseAppearance;i++)await turn();
 assert.equal(typeof window.releaseAppearance,'function');
 const queuedWrite=window.ArchHubAPI.setSetting('Appearance.Theme','Dark');
 await window.ArchHubAPI.setSettingsScope('User');
 window.deferAppearance=false;window.releaseAppearance();
 await firstWrite;await queuedWrite;
 const destinations=requests.slice(queueBegin).filter(row=>row.body?.function==='setAppearance').map(row=>row.body.context.settingsDestination.scope);
 assert.deepEqual(destinations,['Session','Session'],'queued edits keep the scope shown when each edit began');
 await window.ArchHubAPI.listWorkspaces();
 const operations=window.ArchHubAPI.refreshSettingsOperations();await turn();
 await window.ArchHubAPI.setSettingsScope('Workspace');
 window.releaseOperationsRead();await operations;
 assert.equal(window.ArchHubAPI.getSnapshot().settingsScope,'Workspace','late readOperations cannot undo the selected scope');
 assert.equal(window.ArchHubAPI.getSnapshot().settingsDestination.scope,'Workspace');
 assert.equal(window.ArchHubAPI.getSnapshot().devices[0].id,'read-device');
 assert.equal(window.ArchHubAPI.getSnapshot().backups[0].id,'read-backup');
 assert.equal(window.ArchHubAPI.getSnapshot().workspaces.find(row=>row.id==='tower2').rules,'Retain the actual policy');
 await window.ArchHubAPI.setSettingsScope('User');window.deferScope=true;
 const writing=window.ArchHubAPI.setSettingsScope('Workspace');await turn();
 const reading=window.ArchHubAPI.refreshSettingsControls();await turn();
 window.releaseScopeWrite();await writing;
 window.releaseControlRead();await reading;
 assert.equal(window.ArchHubAPI.getSnapshot().settingsScope,'Workspace','readControls begun during a scope write cannot undo its accepted destination');
 assert.equal(window.ArchHubAPI.getSnapshot().settingsDestination.scope,'Workspace');
 assert.equal(window.ArchHubAPI.getSnapshot().companion.readDuringScopeWrite,true,'the unrelated owner still loads');
 window.deferScope=false;
 const projectBegin=requests.length;
 await window.ArchHubAPI.setSetting('Projects.Working subfolder','Models');
 assert.equal(window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Projects.Working subfolder').value,'Models');
 assert.equal(requests.slice(projectBegin).find(row=>row.body?.function==='setAppearance').body.context.settingsDestination.scope,'Workspace');
 await window.ArchHubAPI.resetSetting('Projects.Working subfolder');
 assert.equal(window.ArchHubAPI.getSnapshot().settings.find(row=>row.id==='Projects.Working subfolder').value,'');
 assert.deepEqual(warnings,[]);
});
