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
];
export default async function({step,js,until,clickText,cdp,out}){
 const runs=fs.readdirSync(out,{withFileTypes:true}).filter(entry=>entry.isDirectory()&&entry.name.startsWith('run-'));assert.equal(runs.length,1);
 const isolated=path.join(out,runs[0].name),folder=path.join(isolated,'settings-fixture');fs.mkdirSync(folder,{recursive:true});
 const file=path.join(folder,'settings.archhub'),globalFile=path.join(isolated,'state/settings/settings.json'),workspaceFile=path.join(isolated,'state/settings/workspaces.json');
 const json=p=>JSON.parse(fs.readFileSync(p,'utf8'));
 const owners=()=>[globalFile,workspaceFile,file].map(p=>fs.existsSync(p)?fs.readFileSync(p,'utf8'):null);
 const snapshot=()=>js("(()=>{const s=window.ArchHubAPI.getSnapshot();return {scope:s.settingsScope,destination:s.settingsDestination,theme:s.settings.find(r=>r.id==='Appearance.Theme')?.value,keys:s.keybindings};})()");
 const key=async(key,code,virtual,modifiers=0)=>{for(const type of ['rawKeyDown','keyUp'])await cdp('Input.dispatchKeyEvent',{type,key,code,windowsVirtualKeyCode:virtual,modifiers});};
 // A single change event exercises the installed React selector without intermediate scope writes.
 const select=async(label,value)=>{assert.equal(await until(()=>js(`(()=>{const e=[...document.querySelectorAll('select')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)});return Boolean(e&&!e.disabled&&[...e.options].some(o=>o.value===${JSON.stringify(value)}&&!o.disabled));})()`),Boolean),true);await js(`(()=>{const e=document.querySelector('select[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');if(!e||e.disabled)throw Error('Selector is unavailable');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('change',{bubbles:true}));})()`);};
 const scope=async value=>{await select('Settings scope',value);const got=await until(snapshot,s=>s?.scope===value&&s.destination?.scope===value);assert.equal(got.scope,value);assert.equal(got.destination.scope,value);const label={User:'Everywhere',Workspace:'Current workspace',Session:'Current session'}[value];assert.equal(await until(()=>js(`Boolean([...document.querySelectorAll('button')].find(e=>e.textContent.trim()===${JSON.stringify('Import into '+label)}))`),Boolean),true);return got;};
 const theme=async value=>{await select('Theme',value);const got=await until(snapshot,s=>s?.theme===value);assert.equal(got.theme,value);return got;};
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
}
