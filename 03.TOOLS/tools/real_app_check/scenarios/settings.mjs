import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
export const steps=[
 'Installed Settings opens all eleven areas',
 'First available Workspace selection writes only its owner',
 'Session preferences persist and retain other scopes',
 'Shortcut capture changes the actual Search command',
 'Invalid import refuses without changing any preference owner',
 'Reset inherits and reopening retains workspace preferences',
 'Late startup preserves the newer saved workflow',
 'Installed Projects preserves workspace selection, files and registrations',
 'Installed Settings recovers a stale scope without replaying a write',
 'Installed Projects creates the selected Office folder tree through its native picker',
];
export default async function({step,js,until,clickText,cdp,out,native}){
 const runs=fs.readdirSync(out,{withFileTypes:true}).filter(entry=>entry.isDirectory()&&entry.name.startsWith('run-'));assert.equal(runs.length,1);
 const isolated=path.join(out,runs[0].name),folder=path.join(isolated,'settings-fixture');fs.mkdirSync(folder,{recursive:true});
 const file=path.join(folder,'settings.archhub'),globalFile=path.join(isolated,'state/settings/settings.json'),workspaceFile=path.join(isolated,'state/settings/workspaces.json');
 const json=p=>JSON.parse(fs.readFileSync(p,'utf8'));
 const owners=()=>[globalFile,workspaceFile,file].map(p=>fs.existsSync(p)?fs.readFileSync(p,'utf8'):null);
 const snapshot=()=>js("(()=>{const s=window.ArchHubAPI.getSnapshot();return {scope:s.settingsScope,destination:s.settingsDestination,theme:s.settings.find(r=>r.id==='Appearance.Theme')?.value,keys:s.keybindings};})()");
 const key=async(key,code,virtual,modifiers=0)=>{for(const type of ['rawKeyDown','keyUp'])await cdp('Input.dispatchKeyEvent',{type,key,code,windowsVirtualKeyCode:virtual,modifiers});};
 // A single change event exercises the installed React selector without intermediate scope writes.
 const select=async(label,value)=>{assert.equal(await until(()=>js(`(()=>{const e=[...document.querySelectorAll('select')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)});return Boolean(e&&!e.disabled&&[...e.options].some(o=>o.value===${JSON.stringify(value)}&&!o.disabled));})()`),Boolean),true);await js(`(()=>{const e=document.querySelector('select[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');if(!e||e.disabled)throw Error('Selector is unavailable');if(e.value===${JSON.stringify(value)})return;Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('change',{bubbles:true}));})()`);};
 let controlsReady;
 const scope=async value=>{controlsReady??=js('window.ArchHubAPI.getSettings()');await controlsReady;await js('window.ArchHubAPI.refreshPreferences()');await select('Settings scope',value);const got=await until(snapshot,s=>s?.scope===value&&s.destination?.scope===value);assert.equal(got.scope,value);assert.equal(got.destination.scope,value);const label={User:'Everywhere',Workspace:'Current workspace',Session:'Current session'}[value];assert.equal(await until(()=>js(`Boolean([...document.querySelectorAll('button')].find(e=>e.textContent.trim()===${JSON.stringify('Import into '+label)}))`),Boolean),true);return got;};
 const theme=async value=>{if((await snapshot()).theme===value){const other=value==='Dark'?'Light':'Dark';await select('Theme',other);assert.equal((await until(snapshot,s=>s?.theme===other)).theme,other);}await select('Theme',value);const got=await until(snapshot,s=>s?.theme===value);assert.equal(got.theme,value);return got;};
 let workspaceId;
 await step(steps[0],async()=>{
  assert.equal(await until(()=>js("Boolean(window.ArchHubAPI && document.querySelector('[data-home-page]'))"),Boolean),true);
  await js('window.ArchHubAPI.ready.then(()=>true)');
  const prepared=await js(`(async()=>{const api=window.ArchHubAPI;await api.addWorkspace({folder:${JSON.stringify(folder)}});const w=api.getSnapshot().workspaces.find(w=>(w.path||w.folder).replaceAll('\\\\','/').toLowerCase()===${JSON.stringify(folder.replaceAll('\\','/').toLowerCase())});if(!w)throw Error('Fixture workspace not registered');await api.newSession('Settings installed acceptance');await api.saveSession(${JSON.stringify(file)});await api.setSessionModel(${JSON.stringify(file)},{project:w.id});return {workspace:w.id};})()`);workspaceId=prepared.workspace;
  assert.equal(await clickText('Settings'),true);
  const ready=await until(()=>js("Boolean(document.querySelector('select[aria-label=\"Settings scope\"]')&&!document.querySelector('select[aria-label=\"Settings scope\"]').disabled)"),Boolean);assert.equal(ready,true);
  const areas=await js("[...document.querySelectorAll('nav[aria-label=\"Settings categories\"] button')].map(e=>e.getAttribute('aria-label'))");
  assert.deepEqual(areas,['Account','Look','Projects','Agents','Connections','You','Workshop','Library & Mods','Automations','System','Updates & About']);
  const opened=[];
  for(const name of areas){
   assert.equal(await js(`(()=>{const e=[...document.querySelectorAll('nav[aria-label="Settings categories"] button')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(name)});if(!e)return false;e.click();return true;})()`),true);
   const selected=await until(()=>js(`(()=>{const e=document.querySelector('nav[aria-label="Settings categories"] button[aria-current="page"]');const heading=document.querySelector('.sheet-page-heading h2');return {selected:e?.getAttribute('aria-label'),heading:heading?.textContent,screen:document.querySelector('[data-settings-full]')?.getAttribute('data-screen')};})()`),s=>s.selected===name&&s.heading===name);
   assert.equal(selected.selected,name);assert.equal(selected.heading,name);opened.push(selected);
  }
  assert.equal(await clickText('Look'),true);
  assert.equal(await until(()=>js("Boolean(document.querySelector('select[aria-label=\"Theme\"]'))"),Boolean),true);
  return {pass:true,got:{areas:opened,workspace:workspaceId}};
 });
 await step(steps[1],async()=>{
  await scope('User');await theme('Dark');await scope('Workspace');const globalBefore=fs.readFileSync(globalFile,'utf8');
  await theme('Light');
  assert.equal(fs.readFileSync(globalFile,'utf8'),globalBefore);
  const row=json(workspaceFile).roots.find(w=>w.root_id===workspaceId);assert.equal(row.settings['Appearance.Theme'],'Light');
  assert.equal(json(file).properties.settings?.['Appearance.Theme'],undefined);
  return {pass:true,got:{scope:'Workspace',theme:'Light',globalUnchanged:true,sessionUnchanged:true}};
 });
 await step(steps[2],async()=>{
  await scope('Session');await theme('System');
  assert.equal(json(file).properties.settings['Appearance.Theme'],'System');
  assert.equal(json(workspaceFile).roots.find(w=>w.root_id===workspaceId).settings['Appearance.Theme'],'Light');assert.equal(json(globalFile).appearanceTheme,'Dark');
  const binding=await js("(async()=>{const api=window.ArchHubAPI;await api.exposeSettingsPage('Appearance');const node=api.getSessionDocument().nodes.find(n=>n.params.setting==='Appearance.Theme');if(!node)throw Error('Theme binding absent');await api.setNodeParam(node.id,'value','Light');return node.id;})()");
  assert.equal((await until(snapshot,s=>s.theme==='Light')).theme,'Light');assert.equal(json(file).properties.settings['Appearance.Theme'],'Light');
  await theme('System');
  assert.equal(await js(`window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id===${JSON.stringify(binding)}).params.value`),'System');
  await js('window.ArchHubAPI.saveSession()');
  assert.deepEqual(json(file).nodes.find(n=>n.id===binding).params,{setting:'Appearance.Theme'});
  await js(`window.ArchHubAPI.openSession(${JSON.stringify(file)})`);await js('window.ArchHubAPI.refreshPreferences()');
  const got=await until(snapshot,s=>s.theme==='System');assert.equal(got.theme,'System');
  assert.equal(await js(`window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id===${JSON.stringify(binding)}).params.value`),'System');
  return {pass:true,got:{...got,binding,nodeToSettings:true,settingsToNode:true,noCopiedValue:true}};
 });
 await step(steps[3],async()=>{
  await js("document.querySelector('[aria-label=\"Change shortcut for Search and do\"]')?.scrollIntoView({block:'center'})");
  assert.equal(await clickText('Change shortcut for Search and do'),true);await key('k','KeyK',75,3);
  const got=await until(snapshot,s=>s.keys?.['keyboard.search']==='Ctrl Alt K');assert.equal(got.keys['keyboard.search'],'Ctrl Alt K');
  await js('document.activeElement?.blur()');await key('k','KeyK',75,2);
  assert.equal(await js('Boolean(document.querySelector(\'[role="dialog"][aria-label="Search"]\'))'),false);
  await key('k','KeyK',75,3);assert.equal(await until(()=>js('Boolean(document.querySelector(\'[role="dialog"][aria-label="Search"]\'))'),Boolean),true);
  await key('Escape','Escape',27);assert.equal(json(file).properties.settings['Keyboard.keyboard.search'],'Ctrl Alt K');
  return {pass:true,got:{saved:'Ctrl Alt K',oldShortcutInactive:true,newShortcutOpenedSearch:true}};
 });
 await step(steps[4],async()=>{
  const invalid=path.join(folder,'invalid-settings.json');fs.writeFileSync(invalid,JSON.stringify({format:'archhub.settings',version:1,scopes:{Session:{'Appearance.Theme':'impossible'}}}));
  const before=owners();const doc=await cdp('DOM.getDocument');const found=await cdp('DOM.querySelector',{nodeId:doc.result.root.nodeId,selector:'input[aria-label="Import settings file"]'});
  await cdp('DOM.setFileInputFiles',{nodeId:found.result.nodeId,files:[invalid]});
  assert.equal(await until(()=>js("Boolean([...document.querySelectorAll('[role=alert]')].find(e=>e.textContent.includes('Choose a valid value for this Appearance setting.')))"),Boolean),true);
  assert.deepEqual(owners(),before);return {pass:true,got:{allOwnersUnchanged:true},expected_http:['409 /api/universal/settings-action']};
 });
 await step(steps[5],async()=>{
  await js('document.querySelector(\'[aria-label="Reset Theme"]\')?.scrollIntoView({block:"center"})');
  assert.equal(await clickText('Reset Theme'),true);const inherited=await until(snapshot,s=>s.theme==='Light');assert.equal(inherited.theme,'Light');assert.equal(json(file).properties.settings?.['Appearance.Theme'],undefined);
  await js(`window.ArchHubAPI.openSession(${JSON.stringify(file)})`);await js('window.ArchHubAPI.refreshPreferences()');
  const got=await until(snapshot,s=>s.theme==='Light');assert.equal(got.theme,'Light');assert.equal(json(workspaceFile).roots.find(w=>w.root_id===workspaceId).settings['Appearance.Theme'],'Light');return {pass:true,got:{reopened:got.theme,sessionOverrideRemoved:true,workspaceRetained:true}};
 });
 await step(steps[6],async()=>{
  await js('window.ArchHubAPI.ready.then(()=>true)');
  const ordinaryPath=path.join(folder,'startup-ordinary.archhub'),chosenPath=path.join(folder,'startup-chosen.archhub');
  const current=()=>js('(()=>{const api=window.ArchHubAPI;return {id:api.getSessionDocument()?.id,title:api.getSessionDocument()?.title,path:api.getSessionPath()};})()');
  const reload=async()=>{
   const previous=await js('performance.timeOrigin');await cdp('Page.reload',{ignoreCache:true});
   const ready=await until(async()=>{try{return await js('performance.timeOrigin!=='+JSON.stringify(previous)+'&&Boolean(window.ArchHubAPI?.ready)');}catch(error){if(/context|navigat/i.test(error.message))return false;throw error;}},Boolean);
   assert.equal(ready,true,'The reloaded installed page did not expose its API');
  };
  await js('(async()=>{const api=window.ArchHubAPI;await api.addWorkspace({folder:'+JSON.stringify(folder)+'});await api.newSession("Startup ordinary open");await api.saveSession('+JSON.stringify(ordinaryPath)+');})()');
  const ordinary=await current(),ordinaryBytes=fs.readFileSync(ordinaryPath);assert.equal(json(ordinaryPath).id,ordinary.id);
  await reload();await js('window.ArchHubAPI.ready.then(()=>true)');
  assert.deepEqual(await current(),ordinary,'Ordinary startup did not reopen the saved workflow');assert.deepEqual(fs.readFileSync(ordinaryPath),ordinaryBytes);
  function delayInitialResponse(){
   const browser=globalThis,original=browser.fetch;let release,stopped=false;
   const probe=browser.__archhubStartupWitness={held:false,release(){release?.();},restore(){stopped=true;browser.fetch=original;release?.();}};
   browser.fetch=function(...args){
    const pending=Reflect.apply(original,this,args);let body;
    try{body=JSON.parse(args[1]?.body||'{}');}catch{return pending;}
    const url=new browser.URL(typeof args[0]==='string'?args[0]:args[0].url,browser.location.href);
    if(url.pathname!=='/api/session-files'||body.action!=='initial')return pending;
    return pending.then(response=>stopped?response:new Promise(resolve=>{release=()=>resolve(response);probe.held=true;browser.fetch=original;}));
   };
  }
  const script=await cdp('Page.addScriptToEvaluateOnNewDocument',{source:'('+delayInitialResponse.toString()+')()'});
  try{
   await reload();assert.equal(await until(()=>js('Boolean(globalThis.__archhubStartupWitness?.held)'),Boolean),true,'The real initial-file response was not held');
   await js('(async()=>{const api=window.ArchHubAPI;await api.newSession("Saved while startup was pending");await api.saveSession('+JSON.stringify(chosenPath)+');})()');
   const chosen=await current(),chosenBytes=fs.readFileSync(chosenPath);assert.equal(json(chosenPath).id,chosen.id);assert.equal(path.normalize(chosen.path),path.normalize(chosenPath));
   await js('globalThis.__archhubStartupWitness.release();true');await js('window.ArchHubAPI.ready.then(()=>true)');
   assert.deepEqual(await current(),chosen,'A late initial-file response replaced the newer saved workflow');assert.deepEqual(fs.readFileSync(chosenPath),chosenBytes);
   return {pass:true,got:{ordinary,chosen,ordinaryFileReread:true,newerFileReread:true,realInitialResponseDelayed:true,sourceBytesModified:false}};
  }finally{
   await js('globalThis.__archhubStartupWitness?.restore();true').catch(()=>{});
   await cdp('Page.removeScriptToEvaluateOnNewDocument',{identifier:script.result.identifier});
  }
 });
 await step(steps[7],async()=>{
  await js('window.ArchHubAPI.ready.then(()=>true)');await js('window.ArchHubAPI.listWorkspaces()');
  const before=await js('(()=>{const a=window.ArchHubAPI;return {path:a.getSessionPath(),id:a.getSessionDocument().id,workspace:a.getSnapshot().activeWorkspace};})()');
  const beforeBytes=fs.readFileSync(before.path),baseline=path.join(folder,'projects-canvas.archhub');
  const initialIds=new Set(json(workspaceFile).roots.map(row=>row.root_id));
  const rows=()=>json(workspaceFile).roots;
  const call=(method,args)=>js('(async()=>window.ArchHubAPI['+JSON.stringify(method)+'](...'+JSON.stringify(args)+'))()');
  const fill=async(label,value)=>js(`(()=>{const e=[...document.querySelectorAll('input')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)});if(!e)throw Error('Input unavailable');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  const current=()=>js('(()=>{const a=window.ArchHubAPI,d=a.getSessionDocument();return {id:d.id,title:d.title,nodes:d.nodes,project:d.properties?.project};})()');
  const dirty=()=>js('window.ArchHubAPI.getSnapshot().sessionDirty');
  try{
   await call('newSession',['Projects edited Canvas']);await call('saveSession',[baseline]);
   const baselineBytes=fs.readFileSync(baseline),note='UNSAVED Projects witness '+Date.now();
   function holdAutosave(){
    const browser=globalThis,original=browser.fetch,pending=[];
    const probe=browser.__archhubProjectsWitness={held:0,restore(){browser.fetch=original;for(const release of pending.splice(0))release();}};
    browser.fetch=function(...args){let body;try{body=JSON.parse(args[1]?.body||'{}');}catch{return Reflect.apply(original,this,args);}
     const url=new browser.URL(typeof args[0]==='string'?args[0]:args[0].url,browser.location.href);
     if(url.pathname!=='/api/session-files'||body.action!=='autosave')return Reflect.apply(original,this,args);
     probe.held++;return new Promise((resolve,reject)=>pending.push(()=>Reflect.apply(original,this,args).then(resolve,reject)));
    };
   }
   await js('('+holdAutosave.toString()+')()');await call('addNote',[note,{x:120,y:120}]);
   const edited=await current();assert(edited.nodes.some(node=>Object.values(node.params||{}).includes(note)));assert.equal(await dirty(),true);assert.deepEqual(fs.readFileSync(baseline),baselineBytes);

   assert.equal(await js("(()=>{const e=[...document.querySelectorAll('nav button')].find(e=>e.getAttribute('aria-label')==='Settings'||e.textContent.trim()==='Settings');if(!e)throw Error('Settings rail unavailable');e.click();return true;})()"),true);assert.equal(await until(()=>js("Boolean(document.querySelector('nav[aria-label=\"Settings categories\"]'))"),Boolean),true);assert.equal(await clickText('Projects'),true);
   assert.equal(await until(()=>js("Boolean(document.querySelector('[data-screen=\"settings/Projects\"]')&&[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='New project'&&e.getClientRects().length))"),Boolean),true);
   assert.equal(await clickText('New project'),true);assert.equal(await until(()=>js("Boolean(document.querySelector('input[aria-label=\"Project name\"]'))"),Boolean),true);await fill('Project name','Installed project');await select('Parent workspace',workspaceId);assert.equal(await clickText('Create project'),true);
   const created=await until(()=>js('window.ArchHubAPI.getSnapshot().workspaces.find(w=>w.name==="Installed project")'),Boolean);assert(created?.id);
   const projectPath=path.join(folder,'Installed project');assert.deepEqual(fs.readdirSync(projectPath),[],'Unrelated customer folders must not inherit the ArchHub tree');
   const retry=await call('addWorkspace',[{folder}]);assert.equal(retry.root.root_id,workspaceId,'Re-adding the parent replaced its identity');
   assert.equal(await js('(()=>{const heading=[...document.querySelectorAll("h3")].find(e=>e.textContent==='+JSON.stringify(path.basename(folder))+');const row=heading?.closest(".spread.row");const open=[...(row?.querySelectorAll("button")||[])].find(e=>e.textContent.trim()==="Open"||e.getAttribute("aria-label")==="Open");if(!open)throw Error("Workspace Open is unavailable");open.click();return true;})()'),true);
   assert.equal(await until(()=>js('Boolean(document.querySelector("[data-home-page]"))&&window.ArchHubAPI.getSnapshot().activeWorkspace==='+JSON.stringify(workspaceId)),Boolean),true);
   assert.deepEqual(await current(),edited);assert.equal(await dirty(),true);assert.deepEqual(fs.readFileSync(baseline),baselineBytes);
   assert.equal(await js("document.querySelector('button[aria-label=\"Workspace\"]')?.textContent.trim()"),path.basename(folder));
   await call('refreshPreferences',[]);assert.equal(await js('window.ArchHubAPI.getSnapshot().activeWorkspace'),workspaceId);
   await key('n','KeyN',78,2);assert.equal(await until(()=>js('Boolean(document.querySelector(\'[role="dialog"][aria-label="New task"]\'))'),Boolean),true);
   assert.equal(await js('document.querySelector(\'[role="dialog"][aria-label="New task"] select[aria-label="Workspace"]\')?.value'),workspaceId);assert.equal(await clickText('Cancel'),true);
   assert.deepEqual(await current(),edited);assert.equal(await dirty(),true);assert.deepEqual(fs.readFileSync(baseline),baselineBytes);
   const held=await js('globalThis.__archhubProjectsWitness.held');
   await js('globalThis.__archhubProjectsWitness.restore();window.ArchHubAPI.saveSession()');const savedBytes=fs.readFileSync(baseline);assert.notDeepEqual(savedBytes,baselineBytes);assert.equal(await dirty(),false);
   await call('newSession',['Different disposable Canvas']);await call('openSession',[baseline]);assert.deepEqual(await current(),edited);assert.deepEqual(fs.readFileSync(baseline),savedBytes);
   const adds=Array.from({length:10},(_,i)=>path.join(folder,'parallel-add-'+i));for(const directory of adds)fs.mkdirSync(directory);
   await js('Promise.all('+JSON.stringify(adds)+'.map(folder=>window.ArchHubAPI.addWorkspace({folder})))');
   for(const directory of adds)assert.equal(rows().filter(row=>path.normalize(row.path)===path.normalize(directory)).length,1);
   const mixed=[];
   for(let i=0;i<4;i++){
    const added=path.join(folder,'mixed-add-'+i),name='Mixed created '+i;fs.mkdirSync(added);
    await js('Promise.all([window.ArchHubAPI.addWorkspace({folder:'+JSON.stringify(added)+'}),window.ArchHubAPI.addWorkspace({create:true,parent:'+JSON.stringify(workspaceId)+',name:'+JSON.stringify(name)+'})])');
    assert(rows().some(row=>path.normalize(row.path)===path.normalize(added)));assert(rows().some(row=>path.normalize(row.path)===path.normalize(path.join(folder,name))));mixed.push(name);
   }
   const removed=[];
   for(let i=0;i<4;i++){
    const victim=rows().find(row=>path.normalize(row.path)===path.normalize(adds[i])),name='Created during removal '+i;
    await js('Promise.all([window.ArchHubAPI.removeWorkspace('+JSON.stringify(victim.root_id)+'),window.ArchHubAPI.addWorkspace({create:true,parent:'+JSON.stringify(workspaceId)+',name:'+JSON.stringify(name)+'})])');
    assert(!rows().some(row=>row.root_id===victim.root_id));assert(rows().some(row=>path.normalize(row.path)===path.normalize(path.join(folder,name))));assert(fs.existsSync(adds[i]));removed.push(name);
   }
   assert.equal(rows().find(row=>path.normalize(row.path)===path.normalize(folder)).root_id,workspaceId);
   assert.deepEqual(await current(),edited);assert.deepEqual(fs.readFileSync(baseline),savedBytes);assert.deepEqual(fs.readFileSync(before.path),beforeBytes);
   return {pass:true,got:{workspace:workspaceId,created:projectPath,layout:'Empty folder',unsavedNote:note,sessionDirtyRetained:true,baselineBytesUnchangedUntilExplicitSave:true,realAutosavesHeld:held,explicitSaveAndReopen:true,canvasEditRetained:true,savedCanvasBytesUnchanged:true,newTaskDefault:workspaceId,originalIdRetained:true,normalFileReopened:true,parallelRegisters:adds.length,mixedCreateRegister:mixed.length,mixedCreateUnregister:removed.length}};
  }finally{
   await js('globalThis.__archhubProjectsWitness?.restore();true').catch(()=>{});
   for(const row of rows().filter(row=>!initialIds.has(row.root_id)))await call('removeWorkspace',[row.root_id]);
   await call('openSession',[before.path]);if(before.workspace)await call('selectWorkspace',[before.workspace]);
   assert.deepEqual(new Set(rows().map(row=>row.root_id)),initialIds);assert.equal(await js('window.ArchHubAPI.getSessionDocument().id'),before.id);assert.deepEqual(fs.readFileSync(before.path),beforeBytes);
  }
 });
 await step(steps[8],async()=>{
  const before=await js('(()=>{const a=window.ArchHubAPI,s=a.getSnapshot();return {path:a.getSessionPath(),id:a.getSessionDocument().id,scope:s.settingsScope,workspace:s.activeWorkspace};})()');
  const beforeBytes=fs.readFileSync(before.path),scopeFile=path.join(folder,'scope-recovery.archhub');
  const buffers=()=>[globalFile,workspaceFile,scopeFile].map(file=>fs.readFileSync(file));
  const call=(method,args)=>js('(async()=>window.ArchHubAPI['+JSON.stringify(method)+'](...'+JSON.stringify(args)+'))()');
  try{
   await call('newSession',['Scope recovery acceptance']);await call('saveSession',[scopeFile]);await call('setSessionModel',[scopeFile,{project:workspaceId}]);await call('getSettings',[]);await call('refreshPreferences',[]);
   assert.equal(await js("(()=>{const e=[...document.querySelectorAll('nav button')].find(e=>e.getAttribute('aria-label')==='Settings'||e.textContent.trim()==='Settings');if(!e)throw Error('Settings rail unavailable');e.click();return true;})()"),true);
   assert.equal(await until(()=>js("Boolean(document.querySelector('nav[aria-label=\"Settings categories\"]'))"),Boolean),true);assert.equal(await clickText('Look'),true);await scope('User');
   const stale=(await snapshot()).destination;
   function holdScopeResponse(){
    const browser=globalThis,original=browser.fetch;let release;
    const probe=browser.__archhubScopeWitness={held:false,restore(){browser.fetch=original;release?.();}};
    browser.fetch=function(...args){const pending=Reflect.apply(original,this,args);let body;try{body=JSON.parse(args[1]?.body||'{}');}catch{return pending;}
     const url=new browser.URL(typeof args[0]==='string'?args[0]:args[0].url,browser.location.href);
     if(url.pathname!=='/api/universal/settings-action'||body.function!=='setSettingsScope'||body.args?.[0]!=='Workspace')return pending;
     return pending.then(response=>new Promise(resolve=>{release=()=>resolve(response);probe.held=true;}));
    };
   }
   await js('('+holdScopeResponse.toString()+')()');await select('Settings scope','Workspace');
   assert.equal(await until(()=>js('Boolean(globalThis.__archhubScopeWitness?.held)'),Boolean),true);
   const pending=await js("(()=>{const s=window.ArchHubAPI.getSnapshot();return {busy:s.settingsScopePending===true,scopeDisabled:document.querySelector('select[aria-label=\"Settings scope\"]')?.disabled,themeDisabled:document.querySelector('select[aria-label=\"Theme\"]')?.disabled,notice:[...document.querySelectorAll('[role=status]')].some(e=>e.textContent.includes('Changing settings scope'))};})()");
   assert.deepEqual(pending,{busy:true,scopeDisabled:true,themeDisabled:true,notice:true});
   await js('globalThis.__archhubScopeWitness.restore();true');assert.equal((await until(snapshot,s=>s.scope==='Workspace'&&s.destination?.scope==='Workspace')).scope,'Workspace');
   const untouched=buffers();
   const refusal=await js('(async()=>{try{await window.ArchHubAPI.setSetting("Appearance.Theme","System",'+JSON.stringify(stale)+');return {refused:false};}catch(error){return {refused:true,code:error.response?.code,message:error.message};}})()');
   assert.equal(refusal.refused,true);assert.equal(refusal.code,'settings_destination_changed');assert.deepEqual(buffers(),untouched);
   assert.equal(await until(()=>js('Boolean([...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="Refresh settings scope"))'),Boolean),true);assert.equal(await clickText('Refresh settings scope'),true);
   assert.equal((await until(snapshot,s=>s.destination?.scope==='Workspace')).destination.scope,'Workspace');assert.deepEqual(buffers(),untouched);
   await scope('Session');const otherOwners=buffers().slice(0,2);await theme('Light');
   assert.equal(json(scopeFile).properties.settings['Appearance.Theme'],'Light');assert.deepEqual(buffers().slice(0,2),otherOwners);assert.equal(await js('Boolean(window.ArchHubAPI.getSnapshot().settingsScopePending)'),false);
   return {pass:true,got:{pending,actualStaleDestinationRefused:true,refusalCode:refusal.code,refusedWriteChangedNoOwner:true,readOnlyRefreshReplayedNoWrite:true,explicitSessionLight:true,globalAndWorkspaceUnchanged:true},expected_http:['409 /api/universal/settings-action']};
  }finally{
   await js('globalThis.__archhubScopeWitness?.restore();true').catch(()=>{});await call('openSession',[before.path]);await call('refreshPreferences',[]);await call('setSettingsScope',[before.scope]);if(before.workspace)await call('selectWorkspace',[before.workspace]);assert.equal(await js('window.ArchHubAPI.getSessionDocument().id'),before.id);assert.deepEqual(fs.readFileSync(before.path),beforeBytes);
  }
 });
 await step(steps[9],async()=>{
  const fill=async(label,value)=>js(`(()=>{const e=[...document.querySelectorAll('input')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)});if(!e)throw Error('Input unavailable');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  assert.equal(typeof native,'function','The isolated native-dialog helper is required');
  const before=await js('(()=>{const a=window.ArchHubAPI,s=a.getSnapshot();return {path:a.getSessionPath(),document:a.getSessionDocument(),workspace:s.activeWorkspace};})()');
  const initialIds=new Set(json(workspaceFile).roots.map(row=>row.root_id));
  const parent=path.join(folder,'Office customer'),source=path.join(folder,'Office source'),target=path.join(parent,'Office created');
  fs.mkdirSync(parent);fs.mkdirSync(path.join(source,'Alpha','Beta'),{recursive:true});fs.mkdirSync(path.join(source,'Gamma'));fs.writeFileSync(path.join(source,'marker.txt'),'Synthetic source stays here');
  const tree=(root)=>{const rows=[];const visit=relative=>{for(const name of fs.readdirSync(path.join(root,relative)).sort()){const entry=path.join(relative,name),full=path.join(root,entry),directory=fs.statSync(full).isDirectory();rows.push({path:entry.replaceAll('\\','/'),directory,...(directory?{}:{bytes:fs.readFileSync(full).toString('base64')})});if(directory)visit(entry);}};visit('');return rows;};
  const sourceBefore=tree(source),savedFiles=[...new Set([before.path,file])].map(path=>({path,bytes:fs.readFileSync(path)}));
  const call=(method,args)=>js('(async()=>window.ArchHubAPI['+JSON.stringify(method)+'](...'+JSON.stringify(args)+'))()');
  try{
   const added=await call('addWorkspace',[{folder:parent}]);const parentId=added.root.root_id;
   assert(!json(workspaceFile).roots.some(row=>path.normalize(row.path)===path.normalize(source)),'Chooser source must remain unregistered');
   assert.equal(await js("(()=>{const e=[...document.querySelectorAll('nav button')].find(e=>e.getAttribute('aria-label')==='Settings'||e.textContent.trim()==='Settings');if(!e)throw Error('Settings rail unavailable');e.click();return true;})()"),true);
   assert.equal(await until(()=>js("Boolean(document.querySelector('nav[aria-label=\"Settings categories\"]'))"),Boolean),true);assert.equal(await clickText('Projects'),true);assert.equal(await until(()=>js("Boolean([...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='New project'&&e.getClientRects().length))"),Boolean),true);assert.equal(await clickText('New project'),true);
   await fill('Project name','Office created');await select('Parent workspace',parentId);await select('New project folders','Office project tree');
   assert.equal(await js("[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Create project')?.disabled"),true);
   assert.equal(await clickText('Choose template folder'),true);
   const dialog=await native({kind:'pick-folder',title:'Choose a project folder template',folder:source});assert.equal(dialog.closed,true,dialog.error||'The real folder chooser did not close');assert.equal(path.normalize(dialog.folder),path.normalize(source));
   assert.equal(await until(()=>js("[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Create project')?.disabled===false"),Boolean),true);
   assert.equal(await clickText('Create project'),true);
   const created=await until(()=>js('window.ArchHubAPI.getSnapshot().workspaces.find(w=>w.name==="Office created")'),Boolean);assert(created?.id);
   assert.deepEqual(tree(target),sourceBefore.filter(row=>row.directory));assert.deepEqual(tree(source),sourceBefore);
   const registered=json(workspaceFile).roots.find(row=>row.root_id===created.id);assert.equal(path.normalize(registered.path),path.normalize(target));assert.equal(registered.privacy,'private');
   assert(!json(workspaceFile).roots.some(row=>path.normalize(row.path)===path.normalize(source)));assert.deepEqual(await js('window.ArchHubAPI.getSessionDocument()'),before.document);for(const saved of savedFiles)assert.deepEqual(fs.readFileSync(saved.path),saved.bytes);
   return {pass:true,got:{template:'Office project tree',nativePicker:dialog,sourceWasUnregistered:true,folders:tree(target),noFilesCopied:true,sourceUnchanged:true,registration:created.id,canvasDocumentUnchanged:true,savedCanvasBytesUnchanged:true}};
  }finally{
   for(const row of json(workspaceFile).roots.filter(row=>!initialIds.has(row.root_id)))await call('removeWorkspace',[row.root_id]);
   if(before.workspace)await call('selectWorkspace',[before.workspace]);assert.deepEqual(new Set(json(workspaceFile).roots.map(row=>row.root_id)),initialIds);for(const saved of savedFiles)assert.deepEqual(fs.readFileSync(saved.path),saved.bytes);
  }
 });
}
