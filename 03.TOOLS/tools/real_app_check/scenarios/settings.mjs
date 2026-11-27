import { execFileSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { setTimeout as sleep } from 'node:timers/promises';

async function waitForOutageView(inspect, matches) {
 const deadline = performance.now() + 150_000;
 let view = await inspect();
 let remaining = deadline - performance.now();
 while (!matches(view) && remaining > 0) {
  await sleep(Math.min(1000, remaining));
  view = await inspect();
  remaining = deadline - performance.now();
 }
 return view;
}

function compareOutageObservation(probe, view, transition) {
 const online = probe.status === 200 && probe.listed;
 const offline = probe.status === 503 && probe.refused;
 assert(online || offline, 'Unexpected protected workspace response.');
 if (online) assert(view.restored, 'The service admitted the original account but Studio did not restore its private view.');
 if (offline) assert(view.locked, 'The service refused work but Studio did not lock its private view.');
 return transition === 'disconnect' ? offline : online;
}

export const steps=[
 'Installed desktop starts locked with usable sign-in and no private work',
 'Installed Settings opens all five pages and every former area link',
 'First available Workspace selection writes only its owner',
 'Session preferences persist and retain other scopes',
 'Shortcut capture changes the actual Search command',
 'Invalid import refuses without changing any preference owner',
 'Reset inherits and reopening retains workspace preferences',
 'Late startup preserves the newer saved workflow',
 'Installed Projects preserves workspace selection, files and registrations',
 'Installed Settings recovers a stale scope without replaying a write',
 'Installed Projects creates the selected Office folder tree through its native picker',
 'Installed Canvas saves the selected Session Project folder from its native picker',
 'Installed Projects restores revision and naming controls, protects both files on refused Save As, and resumes autosave after native Cancel',
 'Installed named Settings pickers open their project and Canvas and refuse stale destinations',
];
const declaredSteps=steps;
export default async function({input,label,shot,step:recordStep,js,until,clickText,rectOf,mouse,cdp,out,isolatedRoot,native}){
 const outageRequested = input?.verifyAccountOutage === true;
 let stopProtected = false;
 const observation = {statuses:[], lockedScreenshot:null, sameAccount:false, savedFilePreserved:false, draftPreserved:false};
 function outageEvidence(result, instruction) {
  fs.writeFileSync(path.join(out, 'account-outage.json'), JSON.stringify({result, instruction, observation}, null, 2));
 }
 if (outageRequested) outageEvidence('NOT EXERCISED', 'Waiting for the signed-in Projects fixture. No authenticated outage has been observed.');
 const isolated=isolatedRoot;
 assert.ok(isolated&&path.basename(isolated).startsWith('run-'),'An isolated application profile is required');
 const entry=await recordStep(declaredSteps[0],async()=>{
  const access=await until(()=>js("window.ArchHubAPI?.getSnapshot()?.desktopAccess"),value=>value&&value.state!=='pending');
  assert(access&&typeof access.admitted==='boolean','The installed admission decision was not shown');
  if(access.admitted)return {not_exercised:'This profile already has a legitimate admitted account. Signed-out startup was not exercised; no signout was performed.',got:{authenticated:true}};
  assert(['signed_out','session_invalid','unavailable'].includes(access.state));
  await until(() => js("Boolean(document.querySelector('[data-desktop-admission]'))"), Boolean);
  const privateView=()=>js("(()=>{const a=window.ArchHubAPI,s=a.getSnapshot();return {entry:!!document.querySelector('[data-desktop-admission]'),home:!!document.querySelector('[data-home-page]'),nodes:(s.graph?.nodes||[]).length,workspaces:(s.workspaces||[]).length,tasks:(s.tasks||[]).length,messages:(s.workshopMessages||[]).length,hasEmail:Boolean(s.profile.email),hasDocument:a.getSessionDocument()!==null,hasFile:Boolean(a.getSessionPath())};})()");
  const hidden={entry:true,home:false,nodes:0,workspaces:0,tasks:0,messages:0,hasEmail:false,hasDocument:false,hasFile:false};
  assert.deepEqual(await privateView(),hidden);
  const refusal=await js("(async()=>{const held=window.__archhubSession;const response=await fetch('/api/universal/workspace-roots',{method:'POST',headers:{'Content-Type':'application/json','X-ArchHub-Session':held?.token||'','X-ArchHub-CSRF':held?.csrf||''},body:JSON.stringify({action:'list'})});const value=await response.json();return {status:response.status,code:value.code,state:value.state,hasRoots:Array.isArray(value.roots)&&value.roots.length>0};})()");
  assert([401,503].includes(refusal.status));assert.equal(refusal.code,'desktop_access_required');assert.equal(refusal.hasRoots,false);
  assert.equal(await js("(async()=>{try{await window.ArchHubAPI.newSession('Refused anonymous document');return false;}catch{return window.ArchHubAPI.getSessionDocument()===null;}})()"),true);
  const state=path.join(isolated,'state');
  const cut=path.join(state,'account-outage.active'),observed=path.join(state,'account-outage.observed');
  const launchSwitch=path.join(state,'account-browser-launch.observe'),launches=path.join(state,'account-browser-launch.count');
  assert(!fs.existsSync(cut)&&!fs.existsSync(observed)&&!fs.existsSync(launchSwitch)&&!fs.existsSync(launches),
   'The signed-out outage check requires fresh isolated observation markers.');
  const launchCount=()=>fs.existsSync(launches)?fs.statSync(launches).size:0;
  const originalPage=await js('performance.timeOrigin');
  function observeSignIn(){
   const browser=globalThis,original=browser.fetch;
   const witness=browser.__archhubAdmissionWitness={signIns:0,postStatus:null,phase:null,failure:null,restore(){browser.fetch=original;}};
   browser.fetch=function(...args){
    const pending=Reflect.apply(original,this,args);
    const endpoint=new browser.URL(typeof args[0]==='string'?args[0]:args[0].url,browser.location.href).pathname;
    if(endpoint!=='/api/universal/cloud-signin')return pending;
    const post=args[1]?.method==='POST';
    if(post)witness.signIns++;
    if(!witness.signIns)return pending;
    pending.then(async response=>{
     if(post)witness.postStatus=response.status;
     const {phase,error_code}=await response.clone().json();
     if(phase==='failed'&&!witness.failure){
      // Keep the first terminal result even if a later status response arrives out of order.
      const code=typeof error_code==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(error_code)?error_code:null;
      witness.failure={code};
     }
     if(['idle','starting','waiting','exchanging','done','failed'].includes(phase))witness.phase=phase;
    }).catch(()=>{});
    return pending;
   };
  }
  const attempt=()=>js('(()=>{const w=globalThis.__archhubAdmissionWitness;return {calls:w.signIns,status:w.postStatus,phase:w.phase,failure:w.failure};})()');
  const signInFailed=failure=>({pass:false,
   why:failure.code?('Sign-in failed ('+failure.code+').'):'Sign-in failed without a reported error code.',
   got:{authenticated:false,signInFailure:failure}});
  const retryPoint=()=>rectOf(`[...document.querySelectorAll('[data-desktop-admission] button[aria-label="Retry"]:enabled')].find(e=>e.getClientRects().length)`);
  const hasFailureNotice=()=>js("Boolean([...document.querySelectorAll('[data-desktop-admission] [role=status], [data-desktop-admission] [role=alert]')].find(e=>e.getClientRects().length&&/(sign.in failed|could not start sign.in|connection lost|check your connection)/i.test(e.textContent)))");
  await js('('+observeSignIn.toString()+')()');
  try{
   fs.closeSync(fs.openSync(launchSwitch,'wx'));
   fs.closeSync(fs.openSync(cut,'wx'));
   assert.equal(await clickText('Sign in with your browser'),true);
   const offline=await until(attempt,a=>a.calls===1&&((a.status===200&&a.phase==='failed')||a.status===503),80,500);
   assert.equal(offline.calls,1);
   assert(offline.status===503||(offline.status===200&&offline.phase==='failed'),'The offline sign-in did not report failure.');
   assert.equal(await until(hasFailureNotice,Boolean,40,500),true,'The offline failure was not explained in the entry UI.');
   assert.equal(Boolean(await until(retryPoint,Boolean)),true,'Retry was unavailable after the offline failure.');
   assert(fs.existsSync(observed),'The isolated account transport did not observe the cut.');
   assert.equal(launchCount(),0,'Offline sign-in tried to launch a browser.');
   assert.deepEqual(await privateView(),hidden);
   fs.unlinkSync(cut);

   await js('globalThis.__archhubAdmissionWitness.restore();true');
   await js('('+observeSignIn.toString()+')()');
   const retry=await retryPoint();
   assert(retry,'Retry was unavailable after restoring the connection.');
   await mouse(retry);
   await mouse(retry);
   const signin=await until(attempt,a=>a.failure||(a.status===200&&['waiting','exchanging','done'].includes(a.phase)),80,500);
   if(signin.failure)return signInFailed(signin.failure);
   assert(signin.calls>=1&&signin.calls<=2&&signin.status===200&&['waiting','exchanging','done'].includes(signin.phase),
    'Retry did not start a real sign-in attempt after restoring the connection.');
   const launch=await until(async()=>({count:launchCount(),failure:(await attempt()).failure}),v=>v.failure||v.count>0);
   if(launch.failure)return signInFailed(launch.failure);
   assert.equal(launch.count,1,'Overlapping Retry presses must produce one browser-open event.');
   // Dedicated QA operators can use the full browser sign-in window.
   const waitMs = input?.waitForSignIn === true ? 300_000 : 10_000;
   const deadline = performance.now() + waitMs;
   const current = await until(
    () => js('({admitted:window.ArchHubAPI.getSnapshot().desktopAccess.admitted,failure:globalThis.__archhubAdmissionWitness.failure})'),
    value => value.failure || value.admitted === true || performance.now() >= deadline,
    waitMs / 500 + 1, 500
   );
   if(current.failure)return signInFailed(current.failure);
   if(!current.admitted)assert.deepEqual(await privateView(),hidden);
   assert.equal(await js('performance.timeOrigin'),originalPage,'Retry replaced the installed Studio page.');
   assert.equal(launchCount(),1,'The two Retry presses produced more than one browser-open event.');
   return {pass:true,got:{authenticated:current.admitted===true,initialState:access.state,privateContentAbsent:true,
    protectedRouteRefused:refusal,newDocumentRefused:true,retryUsable:true,
    offlineSignIn:offline,offlineTransportCutObserved:true,offlineBrowserOpenEvents:0,
    realSignInRequest:signin,retryPresses:2,onlineBrowserOpenEvents:1,samePage:true},
    expected_http:['401 /api/universal/workspace-roots','503 /api/universal/workspace-roots','503 /api/universal/cloud-signin']};
  }finally{
   fs.rmSync(cut,{force:true});
   fs.rmSync(observed,{force:true});
   fs.rmSync(launchSwitch,{force:true});
   await js('globalThis.__archhubAdmissionWitness?.restore();true').catch(()=>{});
  }
 });
 const steps=declaredSteps.slice(1),authenticated=entry?.got?.authenticated===true;
 const missingAdmission=entry?.got?.signInFailure?entry.did:'No legitimate QA account admitted this isolated installed window. Authenticated assertions remain unverified; no bypass or founder credentials were used.';
 let folder,file,workspaceId;
 const globalFile=path.join(isolated,'state/settings/settings.json'),workspaceFile=path.join(isolated,'state/settings/workspaces.json');
 const json=p=>JSON.parse(fs.readFileSync(p,'utf8'));
 const owners=()=>[globalFile,workspaceFile,file].map(p=>fs.existsSync(p)?fs.readFileSync(p,'utf8'):null);
 const snapshot=()=>js("(()=>{const s=window.ArchHubAPI.getSnapshot();return {scope:s.settingsScope,destination:s.settingsDestination,theme:s.settings.find(r=>r.id==='Appearance.Theme')?.value,keys:s.keybindings,writing:s.settingsWritesPending>0};})()");
 const key=async(key,code,virtual,modifiers=0)=>{for(const type of ['rawKeyDown','keyUp'])await cdp('Input.dispatchKeyEvent',{type,key,code,windowsVirtualKeyCode:virtual,modifiers});};
 // A single change event exercises the installed React selector without intermediate scope writes.
 const select=async(label,value)=>{assert.equal(await until(()=>js(`(()=>{const e=[...document.querySelectorAll('select')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(label)});return Boolean(e&&!e.disabled&&[...e.options].some(o=>o.value===${JSON.stringify(value)}&&!o.disabled));})()`),Boolean),true);await js(`(()=>{const e=document.querySelector('select[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');if(!e||e.disabled)throw Error('Selector is unavailable');if(e.value===${JSON.stringify(value)})return;Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('change',{bubbles:true}));})()`);};
 const scope=async value=>{
  await js('window.ArchHubAPI.refreshPreferences()');
  const tools='details:has(select[aria-label="Settings scope"])';
  const closed=await js('document.querySelector('+JSON.stringify(tools)+')?.open===false');
  if(closed)await press(tools+' > summary');
  await select('Settings scope',value);
  const got=await until(snapshot,s=>s?.scope===value&&s.destination?.scope===value);
  assert.equal(got.scope,value);assert.equal(got.destination.scope,value);
  const label={User:'Everywhere',Workspace:'Current workspace',Session:'Current session'}[value];
  assert.ok(await until(()=>readPage(label=>[...document.querySelectorAll('button')].some(e=>e.textContent.trim()==='Import into '+label),label),Boolean));
  if(closed)await press(tools+' > summary');
  return got;
 };
 const readPage=(fn,...args)=>js('('+fn.toString()+')(...'+JSON.stringify(args)+')');
 async function press(selector,text=null) {
  const source='('+function(sel,text){
   const el=[...document.querySelectorAll(sel)].find(e=>(text===null||e.textContent.trim()===text)&&e.getClientRects().length&&!e.disabled);
   el?.scrollIntoView({block:'center',inline:'nearest'});
   return el;
  }.toString()+')('+JSON.stringify(selector)+','+JSON.stringify(text)+')';
  const point=await until(async()=>{
   const p=await rectOf(source);
   return p?.w&&p.h&&await js('('+source+')?.contains(document.elementFromPoint('+p.x+','+p.y+'))')?p:null;
  },Boolean,16,150);
  assert.ok(point,'No clickable control for '+selector+(text?' ('+text+')':''));
  await mouse(point);
 }
 async function theme(value){
  const choose=async choice=>{
   await press('[data-setting="Appearance.Theme"] [role="group"] button',choice);
   // A row shows the value asked for at once; its owner file holds it once the write answered.
   const got=await until(snapshot,s=>s?.theme===choice&&!s.writing);assert.equal(got.theme,choice);assert.equal(got.writing,false);return got;
  };
  if((await snapshot()).theme===value)await choose(value==='Dark'?'Light':'Dark');
  return choose(value);
 }
 async function restoreView(before) {
  await readPage(async ({path,workspace,scope})=>{
   const a=window.ArchHubAPI;
   if(workspace && a.getSnapshot().activeWorkspace!==workspace)await a.selectWorkspace(workspace);
   await a.openSession(path);await a.refreshPreferences();
   const current=a.getSnapshot();
   if(scope && current.settingsScope!==scope)await a.setSettingsScope(scope,current.settingsDestination,workspace||current.settingsDestination?.workspace);
  },before);
 }
 async function openProjectForm(){
  const folders='[data-design-section="CDE folders"] details';
  if(!await js('document.querySelector('+JSON.stringify(folders)+')?.open'))await press(folders+' > summary','Project folders');
  await press(folders+' button','New project');
  assert.ok(await until(()=>js('Boolean(document.querySelector(\'form[aria-label="New project"]\'))'),Boolean));
 }
 async function restoreAfter(failure,restore){
  try{await restore();}catch(error){
   if(!failure)throw error;
   failure.message+=' (cleanup: '+error.message.split('\n')[0].slice(0,100)+')';
  }
 }
 async function freshCase(index) {
  folder=path.join(isolated,'settings-fixture',path.basename(out),String(index+1));file=path.join(folder,'settings.archhub');
  fs.mkdirSync(folder,{recursive:true});
  const previousPage=await js('performance.timeOrigin');
  await cdp('Page.reload',{ignoreCache:false});
  const ready=await until(async()=>{
   try{return await js('performance.timeOrigin!=='+JSON.stringify(previousPage)+'&&Boolean(window.ArchHubAPI?.getSnapshot()?.desktopAccess?.admitted)');}
   catch(error){if(/execution context was destroyed|cannot find context/i.test(error.message))return false;throw error;}
  },Boolean,90,250);
  assert.ok(ready,'Isolated Settings fixture did not reach a fresh signed-in Studio page');
  workspaceId=await readPage(async (folder,file)=>{
   const a=window.ArchHubAPI;await a.ready;
   await a.addWorkspace({folder});const roots=await a.listWorkspaces();
   const w=roots.find(w=>a.sessionPathKey(w.path||w.folder)===a.sessionPathKey(folder));
   if(!w)throw Error('QA workspace missing from the registration owner');
   await a.selectWorkspace(w.id);await a.newSession('Settings installed acceptance');await a.saveSession(file);
   await a.setSessionModel(file,{project:w.id});await a.getSettings();await a.refreshPreferences();
   const s=a.getSnapshot();if(s.settingsScope!=='User')await a.setSettingsScope('User',s.settingsDestination,w.id);
   return w.id;
  },folder,file);
  assert.equal(json(file).properties.project,workspaceId);
  await press('nav button[aria-label="Home"]');
  if(index>=1&&index<=5){
   await press('nav button[aria-label="Settings"]');await press('nav[aria-label="Settings categories"] button[aria-label="This PC"]');
   if(index===2||index===5){
    await scope('User');await theme('Dark');await scope('Workspace');await theme('Light');
   }
   if(index>=2)await scope('Session');
   if(index===5)await theme('Dark');
  }
 }
 const step=(asked,run)=>recordStep(asked,async()=>{
  if(!authenticated||stopProtected)return {not_exercised:stopProtected?'Outage exercise stopped before safe continuation.':missingAdmission};
  try{await freshCase(steps.indexOf(asked));}
  catch(error){return {not_exercised:'QA fixture setup: '+error.message};}
  return run();
 });
 await step(steps[0],async()=>{
  assert.equal(await clickText('Settings'),true);
  const ready=await until(()=>js("Boolean(document.querySelector('select[aria-label=\"Settings scope\"]')&&!document.querySelector('select[aria-label=\"Settings scope\"]').disabled)"),Boolean);assert.equal(ready,true);
  const areas=await js("[...document.querySelectorAll('nav[aria-label=\"Settings categories\"] button')].map(e=>e.getAttribute('aria-label'))");
  assert.deepEqual(areas,['Account','Projects','Agents','Connections','This PC']);
  const opened=[];
  for(const name of areas){
   assert.equal(await js(`(()=>{const e=[...document.querySelectorAll('nav[aria-label="Settings categories"] button')].find(e=>e.getAttribute('aria-label')===${JSON.stringify(name)});if(!e)return false;e.click();return true;})()`),true);
   const selected=await until(()=>js(`(()=>{const e=document.querySelector('nav[aria-label="Settings categories"] button[aria-current="page"]');const heading=document.querySelector('.sheet-page-heading h2');return {selected:e?.getAttribute('aria-label'),heading:heading?.textContent,screen:document.querySelector('[data-settings-full]')?.getAttribute('data-screen')};})()`),s=>s.selected===name&&s.heading===name);
   assert.equal(selected.selected,name);assert.equal(selected.heading,name);
   const screenshot = path.basename(await shot('Settings - ' + name));
   opened.push({...selected, screenshot});
  }
  const former=[['Agents','Models & BABOOM','Agents','BABOOM'],['Agents','Hooks','Agents','What agents may do'],['Agents','Workshop','Agents','Workshop'],['Agents','Automations','Agents','Automations'],['Agents','Library & Mods','Agents','Tools in the Library'],['This PC','System','System graph','Agents on this PC'],['This PC','Updates & About','Updates & About','The app'],['This PC','Workspaces & privacy','Privacy','Workspaces and files'],['This PC','Look','Appearance','Theme and colour']];
  for(const [area,label,screen,section] of former){
   assert.equal(await js(`(()=>{const e=document.querySelector('nav[aria-label="Settings categories"] button[aria-label=${JSON.stringify(area)}]');if(!e)return false;e.click();return true;})()`),true,area);
   assert.equal(await until(()=>js(`(()=>{const e=[...document.querySelectorAll('nav.sheet-subpages button')].find(e=>e.textContent.trim()===${JSON.stringify(label)});if(!e)return false;e.click();return true;})()`),Boolean),true,label);
   const at=await until(()=>js("document.querySelector('[data-settings-full]')?.getAttribute('data-screen')"),s=>s==='settings/'+screen);
   assert.equal(at,'settings/'+screen);
   const visible=await until(()=>readPage(name=>{
    const el=document.querySelector('[data-design-section="'+name+'"]');const r=el?.getBoundingClientRect();
    return !!(r?.width&&r.height&&r.top<window.innerHeight&&r.bottom>0);
   },section),Boolean,24,150);
   assert.ok(visible,'Link did not reveal '+section);opened.push({area,page:label,screen:at,section});
  }
  assert.ok(await js("Boolean(document.querySelector('[data-setting=\"Appearance.Theme\"] [role=\"group\"] button[aria-pressed=\"true\"]'))"));
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
  const binding=await readPage(async()=>{
   const api=window.ArchHubAPI;await api.exposeSettingsPage('Appearance');
   const node=api.getSessionDocument().nodes.find(n=>n.params.setting==='Appearance.Theme');
   if(!node)throw Error('Theme binding absent');return node.id;
  });
  await readPage(async id=>{await window.ArchHubAPI.setNodeParam(id,'value','Light');return true;},binding);
  assert.equal((await until(snapshot,s=>s.theme==='Light')).theme,'Light');assert.equal(json(file).properties.settings['Appearance.Theme'],'Light');
  await theme('System');
  // The bound node re-solves after its owner answered.
  assert.equal(await until(()=>js(`window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id===${JSON.stringify(binding)}).params.value`),v=>v==='System'),'System');
  await js('window.ArchHubAPI.saveSession()');
  assert.deepEqual(json(file).nodes.find(n=>n.id===binding).params,{setting:'Appearance.Theme'});
  await js(`window.ArchHubAPI.openSession(${JSON.stringify(file)})`);await js('window.ArchHubAPI.refreshPreferences()');
  const got=await until(snapshot,s=>s.theme==='System');assert.equal(got.theme,'System');
  assert.equal(await js(`window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id===${JSON.stringify(binding)}).params.value`),'System');
  return {pass:true,got:{...got,binding,nodeToSettings:true,settingsToNode:true,noCopiedValue:true}};
 });
 await step(steps[3],async()=>{
  const searchOpen=()=>js('Boolean(document.querySelector(\'[role="dialog"] [data-design="palette.input"]\')?.getClientRects().length)');
  // Keys go to the focused element: wait on the real focus state before each key, never a fixed delay.
  const searchFocused=()=>js('document.activeElement?.matches?.(\'[role="dialog"] [data-design="palette.input"]\')===true');
  const capturing=()=>js('document.querySelector(\'button[aria-label="Change shortcut for Search and do"]\')?.textContent.trim()===\'Press keys...\'');
  const pageFocused=()=>js('document.activeElement===document.body||document.activeElement===null');
  // The header opens Search only when no dialog holds the app and nothing else holds focus.
  await js('document.activeElement?.blur()');
  assert.ok(await until(()=>js('!document.querySelector(\'[role="dialog"]\')'),Boolean),'A dialog was still open before Search');
  assert.ok(await until(pageFocused,Boolean),'Focus stayed on a control before Search');
  await press('button[data-design="header.search"]');
  assert.ok(await until(searchOpen,Boolean),'The header did not open the Search input');
  assert.ok(await until(searchFocused,Boolean),'The Search input never took focus');
  await key('Escape','Escape',27);
  assert.equal(await until(searchOpen,open=>!open),false,'Search remained open after Escape');
  const keys='details.sheet-keybindings';
  if(await js('document.querySelector('+JSON.stringify(keys)+')?.open===false'))await press(keys+' > summary');
  await press('button[aria-label="Change shortcut for Search and do"]');
  assert.ok(await until(capturing,Boolean),'Shortcut capture did not start');await key('k','KeyK',75,3);
  const got=await until(snapshot,s=>s.keys?.['keyboard.search']==='Ctrl Alt K');assert.equal(got.keys['keyboard.search'],'Ctrl Alt K');
  await js('document.activeElement?.blur()');assert.ok(await until(pageFocused,Boolean),'The page did not hold focus after blur');await key('k','KeyK',75,2);
  assert.equal(await searchOpen(),false);
  await key('k','KeyK',75,3);assert.ok(await until(searchOpen,Boolean),'The saved Ctrl Alt K shortcut did not open Search');
  assert.ok(await until(searchFocused,Boolean),'The Search input never took focus');await key('Escape','Escape',27);assert.equal(json(file).properties.settings['Keyboard.keyboard.search'],'Ctrl Alt K');
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
  const sessionTheme=json(file).properties.settings?.['Appearance.Theme'];
  const workspaceTheme=json(workspaceFile).roots.find(w=>w.root_id===workspaceId).settings['Appearance.Theme'];
  assert.equal(sessionTheme,'Dark');assert.equal(workspaceTheme,'Light');
  const reset='[data-setting="Appearance.Theme"] button[aria-label="Reset Theme"]';
  if(!await js('Boolean(document.querySelector('+JSON.stringify(reset)+')?.getClientRects().length)'))
   return {pass:false,why:'Session has a saved Dark override and inherits Light from its workspace, but the Theme row offers no Reset',got:{sessionTheme,workspaceTheme,selectedScope:(await snapshot()).scope}};
  await press(reset);const inherited=await until(snapshot,s=>s.theme==='Light');assert.equal(inherited.theme,'Light');assert.equal(json(file).properties.settings?.['Appearance.Theme'],undefined);
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
   await openProjectForm();
   await fill('Project name','Installed project');await select('Parent workspace',workspaceId);await press('form[aria-label="New project"] button','Create project');
   // Found by its folder: a reused QA profile can hold other projects with the same name.
   const projectPath=path.join(folder,'Installed project');
   const created=await until(()=>js('window.ArchHubAPI.getSnapshot().workspaces.find(w=>window.ArchHubAPI.sessionPathKey(w.folder)===window.ArchHubAPI.sessionPathKey('+JSON.stringify(projectPath)+'))'),Boolean);assert(created?.id);assert.deepEqual(fs.readdirSync(projectPath),[],'Unrelated customer folders must not inherit the ArchHub tree');
   const retry=await call('addWorkspace',[{folder}]);assert.equal(retry.root.root_id,workspaceId,'Re-adding the parent replaced its identity');
   assert.equal(await js('(()=>{const row=[...document.querySelectorAll(".spread.row")].find(e=>e.querySelector("h3")?.textContent==='+JSON.stringify(path.basename(folder))+'&&e.querySelector("span.muted")?.textContent.startsWith('+JSON.stringify(folder+' ·')+'));const open=[...(row?.querySelectorAll("button")||[])].find(e=>e.textContent.trim()==="Open"||e.getAttribute("aria-label")==="Open");if(!open)throw Error("Workspace Open is unavailable");open.click();return true;})()'),true);
   assert.equal(await until(()=>js('Boolean(document.querySelector("[data-home-page]"))&&window.ArchHubAPI.getSnapshot().activeWorkspace==='+JSON.stringify(workspaceId)),Boolean),true);
   assert.deepEqual(await current(),edited);assert.equal(await dirty(),true);assert.deepEqual(fs.readFileSync(baseline),baselineBytes);
   assert.equal(await js("document.querySelector('button[aria-label=\"Workspace\"]')?.textContent.trim()"),path.basename(folder));
   await call('refreshPreferences',[]);assert.equal(await js('window.ArchHubAPI.getSnapshot().activeWorkspace'),workspaceId);
   await key('n','KeyN',78,2);assert.equal(await until(()=>js('Boolean(document.querySelector(\'[role="dialog"][aria-label="New task"]\'))'),Boolean),true);
   assert.equal(await js('document.querySelector(\'[role="dialog"][aria-label="New task"] select[aria-label="Workspace"]\')?.value'),workspaceId);assert.equal(await clickText('Cancel'),true);
   assert.deepEqual(await current(),edited);assert.equal(await dirty(),true);assert.deepEqual(fs.readFileSync(baseline),baselineBytes);
   const held=await js('globalThis.__archhubProjectsWitness.held');
   if (outageRequested) {
    const cut=path.join(isolated,'state','account-outage.active'), observed=path.join(isolated,'state','account-outage.observed');
    stopProtected = true;
    try {
     const account = await js("(async()=>{const a=await window.ArchHubAPI.refreshDesktopAccess(true);return a.admitted && a.subject;})()");
     assert(typeof account === 'string' && account.length > 0);
     const savedPath = await js('window.ArchHubAPI.getSessionPath()');
     assert.equal(path.normalize(savedPath), path.normalize(baseline));
     const draft = await js('window.ArchHubAPI.getSessionDocument()');
     assert(held > 0 && await dirty());
     // Use the same loopback transport as the admission check; keep the cloud credential in its owner.
     async function probe(subject) {
      const lease = window.__archhubSession;
      const response = await fetch('/api/universal/workspace-roots', {
       method:'POST', cache:'no-store',
       headers:{'Content-Type':'application/json','X-ArchHub-Session':lease.token,'X-ArchHub-CSRF':lease.csrf,'X-ArchHub-Desktop-Subject':subject},
       body:JSON.stringify({action:'list'})
      });
      const data = await response.json();
      return {status:response.status, listed:data.ok !== false && Array.isArray(data.roots),
       refused:data.ok === false && data.code === 'desktop_access_required' && data.state === 'unavailable'
        && Object.keys(data).every(key => ['ok','code','state','error'].includes(key))};
     }
     const read = () => js('('+probe.toString()+')('+JSON.stringify(account)+')');
     const online = await read();
     observation.statuses.push(online.status);
     assert(online.status === 200 && online.listed);
     fs.closeSync(fs.openSync(cut,'wx'));
     function inspectView(subject) {
      const api = window.ArchHubAPI, snapshot = api.getSnapshot(), access = snapshot.desktopAccess;
      const entry = document.querySelector('[data-desktop-admission]');
      const home = document.querySelector('[data-home-page]');
      return {
       locked:!access.admitted && access.state === 'unavailable' && !!entry?.getClientRects().length
        && !home && api.getSessionDocument() === null && !api.getSessionPath() && !snapshot.graph?.nodes?.length,
       restored:access.admitted && access.ready && access.subject === subject && !entry && !!home?.getClientRects().length
      };
     }
     const inspect = () => js('('+inspectView.toString()+')('+JSON.stringify(account)+')');
     await waitForOutageView(inspect, view => view.locked);
     const denial = await read();
     observation.statuses.push(denial.status);
     if (!compareOutageObservation(denial, await inspect(), 'disconnect')) {
      throw Error('The isolated connection cut did not lock Studio.');
     }
     assert.deepEqual(fs.readFileSync(baseline),baselineBytes);
     assert.equal(label,'INSTALLED BUILD','Installed Windows evidence is required for the outage verdict.');
     assert(fs.existsSync(observed),'The isolated transport did not observe the cut');
     observation.lockedScreenshot = path.basename(await shot('Account service outage - locked Studio'));
     fs.unlinkSync(cut);
     await waitForOutageView(inspect, view => view.restored);
     const reopened = await read();
     observation.statuses.push(reopened.status);
     if (!compareOutageObservation(reopened, await inspect(), 'reconnect')) {
      throw Error('The account did not recover after restoring its transport.');
     }
     observation.sameAccount = true;
     assert.equal(await js('window.ArchHubAPI.getSessionPath()'),savedPath);
     assert.deepEqual(await js('window.ArchHubAPI.getSessionDocument()'),draft);
     assert.equal(await dirty(),true);
     assert.deepEqual(fs.readFileSync(baseline),baselineBytes);
     observation.savedFilePreserved = true;
     observation.draftPreserved = true;
     stopProtected = false;
     outageEvidence('NOT EXERCISED','Same account and dirty edit restored. Explicit save and reopen pending.');
    } catch (error) {
     outageEvidence('FAIL', 'The outage assertions failed. Inspect the Projects step.');
     return {pass:false,why:'The account outage evidence did not satisfy the installed assertions.',got:{accountOutage:observation}};
    } finally { fs.rmSync(cut,{force:true}); }
   }
   await js('globalThis.__archhubProjectsWitness.restore();window.ArchHubAPI.saveSession()');const savedBytes=fs.readFileSync(baseline);assert.notDeepEqual(savedBytes,baselineBytes);assert.equal(await dirty(),false);
   await call('newSession',['Different disposable Canvas']);await call('openSession',[baseline]);assert.deepEqual(await current(),edited);assert.deepEqual(fs.readFileSync(baseline),savedBytes);
   if(outageRequested){
    observation.explicitSaveAndReopen=true;
    outageEvidence('PASS','The isolated account connection was cut and restored. The same account recovered its draft, saved it and reopened the verified file.');
   }
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
   return {pass:true,...(outageRequested?{expected_http:['503 /api/universal/workspace-roots']}:{}),got:outageRequested?{accountOutage:observation}:{workspace:workspaceId,created:projectPath,layout:'Empty folder',unsavedNote:note,sessionDirtyRetained:true,baselineBytesUnchangedUntilExplicitSave:true,realAutosavesHeld:held,explicitSaveAndReopen:true,canvasEditRetained:true,savedCanvasBytesUnchanged:true,newTaskDefault:workspaceId,originalIdRetained:true,normalFileReopened:true,parallelRegisters:adds.length,mixedCreateRegister:mixed.length,mixedCreateUnregister:removed.length}};
  }finally{
   if (!stopProtected) {
   await js('globalThis.__archhubProjectsWitness?.restore();true').catch(()=>{});
   for(const row of rows().filter(row=>!initialIds.has(row.root_id)))await call('removeWorkspace',[row.root_id]);
   await call('openSession',[before.path]);if(before.workspace)await call('selectWorkspace',[before.workspace]);
   assert.deepEqual(new Set(rows().map(row=>row.root_id)),initialIds);assert.equal(await js('window.ArchHubAPI.getSessionDocument().id'),before.id);assert.deepEqual(fs.readFileSync(before.path),beforeBytes);
   }
  }
 });
 await step(steps[8],async()=>{
  const before=await js('(()=>{const a=window.ArchHubAPI,s=a.getSnapshot();return {path:a.getSessionPath(),id:a.getSessionDocument().id,scope:s.settingsScope,workspace:s.activeWorkspace};})()');
  const beforeBytes=fs.readFileSync(before.path),scopeFile=path.join(folder,'scope-recovery.archhub');
  const buffers=()=>[globalFile,workspaceFile,scopeFile].map(file=>fs.readFileSync(file));
  const call=(method,args)=>js('(async()=>window.ArchHubAPI['+JSON.stringify(method)+'](...'+JSON.stringify(args)+'))()');
  let failure;
  try{
   await call('newSession',['Scope recovery acceptance']);await call('saveSession',[scopeFile]);await call('setSessionModel',[scopeFile,{project:workspaceId}]);await call('getSettings',[]);await call('refreshPreferences',[]);
   assert.equal(await js("(()=>{const e=[...document.querySelectorAll('nav button')].find(e=>e.getAttribute('aria-label')==='Settings'||e.textContent.trim()==='Settings');if(!e)throw Error('Settings rail unavailable');e.click();return true;})()"),true);
   assert.equal(await until(()=>js("Boolean(document.querySelector('nav[aria-label=\"Settings categories\"]'))"),Boolean),true);assert.equal(await clickText('This PC'),true);await scope('User');
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
   const pending=await js("(()=>{const s=window.ArchHubAPI.getSnapshot(),themes=[...document.querySelectorAll('[data-setting=\"Appearance.Theme\"] [role=\"group\"] button')];return {busy:s.settingsScopePending===true,scopeDisabled:document.querySelector('select[aria-label=\"Settings scope\"]')?.disabled,themeDisabled:themes.length>0&&themes.every(b=>b.disabled),notice:[...document.querySelectorAll('[role=status]')].some(e=>e.textContent.includes('Changing settings scope'))};})()");
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
  }catch(error){failure=error;throw error;}finally{
   await restoreAfter(failure,async()=>{
    await js('globalThis.__archhubScopeWitness?.restore();true');
    await restoreView(before);assert.equal(await js('window.ArchHubAPI.getSessionDocument().id'),before.id);assert.deepEqual(fs.readFileSync(before.path),beforeBytes);
   });
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
   await press('nav[aria-label="Settings categories"] button[aria-label="Projects"]');await openProjectForm();
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
 await step(steps[10],async()=>{
  const call=(name,...args)=>js('window.ArchHubAPI['+JSON.stringify(name)+'](...'+JSON.stringify(args)+')');
  const previous=await call('getSessionPath'),previousBytes=fs.readFileSync(previous);
  const destination=path.join(folder,'Session documents','Picker.archhub'),chosen=path.join(folder,'Session project (QA)');
  fs.mkdirSync(path.dirname(destination),{recursive:true});fs.mkdirSync(chosen,{recursive:true});
  try{
   await call('newSession','Session folder acceptance');await call('refreshLibraryPorts');
   const target=await call('addNode','thing:session',{x:80,y:80});
   const other=await call('addNode','thing:session',{x:580,y:80});
   await call('saveSession',destination);await call('newSession','Prepare Session card fixture');
   const fixture=json(destination);
   fixture.nodes.find(n=>n.id===target.id).fixed=true;
   fs.writeFileSync(destination,JSON.stringify(fixture));
   await call('openSession',destination);await call('getSettings');
   const preference=()=>js("window.ArchHubAPI.getSnapshot().settings.find(r=>r.id==='Projects.Working subfolder')?.value");
   const relative=await preference(),registration=json(workspaceFile).roots;
   assert.equal(typeof relative,'string');
   assert.equal(await js("(()=>{const button=[...document.querySelectorAll('nav button')].find(e=>e.getAttribute('aria-label')==='Canvas'||e.textContent.trim()==='Canvas');if(!button)return false;button.click();return true;})()"),true);
   const card='[data-graph-node="'+target.id+'"] [data-design="session.node"]';
   const context=card+' [data-design="session.panel.context"]';
   assert.equal(await until(()=>js('Boolean(document.querySelector('+JSON.stringify(context)+')?.getClientRects().length)'),Boolean),true);
   await js('(()=>{const b=document.querySelector('+JSON.stringify(context)+');if(b.getAttribute("aria-expanded")!=="true")b.click();})()');
   const widget='[...document.querySelectorAll('+JSON.stringify(card+' label')+')].find(e=>e.querySelector("span")?.textContent==="Project folder")';
   assert.equal(await js('(()=>{const b='+widget+'?.querySelector("button");if(b?.textContent.trim()!=="Browse"||!b.getClientRects().length)return false;b.click();return true;})()'),true);
   const dialog=await native({kind:'pick-folder',title:'Choose a workspace folder',folder:chosen});
   assert.equal(dialog.closed,true,dialog.error);assert.equal(path.normalize(dialog.folder),path.normalize(chosen));
   assert.equal(await until(()=>js('('+widget+')?.querySelector("input")?.title'),v=>v===chosen),chosen);
   assert.equal(path.normalize(await call('getSessionPath')),path.normalize(destination));
   await call('saveSession');await call('newSession','Reopen Session folder');await call('openSession',destination);
   for(const doc of [json(destination),await call('getSessionDocument')]){
    assert.equal(doc.id,fixture.id);assert.equal(path.normalize(doc.nodes.find(n=>n.id===target.id).params.project_folder),path.normalize(chosen));
    assert.deepEqual(doc.nodes.find(n=>n.id===other.id).params,fixture.nodes.find(n=>n.id===other.id).params);
   }
   assert.equal(await preference(),relative);assert.deepEqual(json(workspaceFile).roots,registration);
   return {pass:true,got:{node:target.id,file:destination,projectFolder:chosen,nativePicker:dialog,savedAndReopened:true}};
  }finally{await call('openSession',previous);assert.deepEqual(fs.readFileSync(previous),previousBytes);}
 });
 await step(steps[11],async()=>{
  const call=(name,...args)=>js('window.ArchHubAPI['+JSON.stringify(name)+'](...'+JSON.stringify(args)+')');
  const previous=await call('getSessionPath'),previousScope=(await snapshot()).scope;
  const previousProject=await js('window.ArchHubAPI.getSnapshot().activeWorkspace');
  const source=path.join(folder,'Naming check.archhub'),issued=path.join(folder,'Issued naming check');
  const target=path.join(issued,'Unassigned.archhub');
  fs.mkdirSync(issued,{recursive:true});
  const register=(number,values)=>readPage(async(id,number,values)=>{
   const a=window.ArchHubAPI,w=(await a.listWorkspaces()).find(w=>w.id===id);
   if(!w?.register)throw Error('QA workspace registration unavailable for the naming check');
   return a.updateProjectRegister(w,number,w.register.override,values);
  },workspaceId,number,values);
  // A row shows the value asked for at once; read it once its owner answered every write.
  const readControl=label=>until(()=>js('(()=>{const s=window.ArchHubAPI.getSnapshot();return {writing:s.settingsWritesPending>0,value:s.settings.find(row=>row.label==='+JSON.stringify(label)+')?.value};})()'),v=>!v.writing).then(v=>v.value);
  const toggle='Check names before saving';
  const switchValue=async value=>{
   if(await readControl(toggle)!==value){
    const clicked=await js("(()=>{const e=document.querySelector('[role=switch][aria-label=\"Check names before saving\"]');if(!e||e.disabled||!e.getClientRects().length)return false;e.click();return true;})()");
    assert.equal(clicked,true);
   }
   assert.equal(await until(()=>readControl(toggle),v=>v===value),value);
  };
  let originalRegister,failure;
  try{
   await call('newSession','Naming check');await call('saveSession',source);
   await call('setSessionModel',source,{project:workspaceId});await call('selectWorkspace',workspaceId);
   await js("document.querySelector('nav button[aria-label=\"Settings\"]').click()");
   assert.equal(await until(()=>js("Boolean(document.querySelector('nav[aria-label=\"Settings categories\"]'))"),Boolean),true);
   assert.equal(await clickText('Projects'),true);await scope('Session');
   const revision=await readControl('Revisions'),initialCheck=await readControl(toggle);
   assert.equal(typeof initialCheck,'boolean');
   for(const value of ['P01, C01 (ISO 19650)','A, B, C','Rev 0, 1, 2',revision]){
    await select('Revisions',value);
    assert.equal(await until(()=>readControl('Revisions'),v=>v===value),value);
   }
   await switchValue(!initialCheck);await switchValue(initialCheck);await switchValue(true);
   await call('saveSession');
   originalRegister=await js('window.ArchHubAPI.listWorkspaces().then(rows=>rows.find(w=>w.id==='+JSON.stringify(workspaceId)+')?.register)');
   assert.ok(originalRegister,'The QA workspace register is unavailable');
   const naming='Naming QA.xlsx',containers='Issued QA.xlsx',assigned=path.join(issued,'A01.archhub');
   execFileSync(input.installedPython,['-I','-B','-c',[
    'from pathlib import Path','import sys','from openpyxl import Workbook',
    'folder = Path(sys.argv[1])','rules = Workbook()', "sheet = rules.active; sheet.title = 'Adoptions'",
    "sheet.append(['StandardID','Edition','Incorporation decision','Token order'])",
    "sheet.append(['QA',1,'Adopted','SERIAL'])","codes = rules.create_sheet('Codes')",
    "codes.append(['Token','Code','ProjectID','Authority','State'])","codes.append(['SERIAL','A01','QA','QA','Approved'])",
    'rules.save(folder/sys.argv[2]); rules.close()','issued = Workbook()', "sheet = issued.active; sheet.title = 'Container template'",
    "sheet.append(['ContainerID','Revision','Permitted use'])","sheet.append(['A01',0,'ARCHHUB'])",
    'issued.save(folder/sys.argv[3]); issued.close()'
   ].join('\n'),folder,naming,containers],{windowsHide:true});
   await register('QA',{issuedDestination:issued,namingRegister:naming,issuedRegister:containers});
   await select('Revisions','Rev 0, 1, 2');assert.equal(await until(()=>readControl('Revisions'),v=>v==='Rev 0, 1, 2'),'Rev 0, 1, 2');
   await call('saveSession');
   fs.copyFileSync(source,target,fs.constants.COPYFILE_EXCL);
   const sourceBytes=fs.readFileSync(source),targetBytes=fs.readFileSync(target);
   const refusal=await js('(async()=>{try{await window.ArchHubAPI.saveSession('+JSON.stringify(target)+',true);return "";}catch(error){return error.message;}})()');
   assert.match(refusal,/assigned ContainerID.*ARCHHUB permitted use.*exact name/i);
   assert.deepEqual(fs.readFileSync(source),sourceBytes);assert.deepEqual(fs.readFileSync(target),targetBytes);
   assert.equal(path.normalize(await call('getSessionPath')),path.normalize(source));
   const saved=await call('saveSession',assigned,true);
   assert.equal(saved.issueRevision,'Rev 0');assert.equal(path.normalize(saved.path),path.normalize(assigned));
   assert.equal(json(assigned).id,saved.document.id);
   await call('openSession',assigned);assert.equal((await call('getSessionDocument')).id,saved.document.id);
   await call('openSession',source);await call('refreshPreferences');
   // Opening a file shows its Canvas: come back to Settings › Projects for its controls.
   await js("document.querySelector('nav button[aria-label=\"Settings\"]').click()");
   assert.equal(await until(()=>js("Boolean(document.querySelector('nav[aria-label=\"Settings categories\"]'))"),Boolean),true);
   assert.equal(await clickText('Projects'),true);
   await select('Revisions',revision);assert.equal(await until(()=>readControl('Revisions'),v=>v===revision),revision);
   await switchValue(initialCheck);
   const x=(await call('getSessionDocument')).viewport.x+53;
   await js('(()=>{const a=window.ArchHubAPI;a.setSessionViewport({...a.getSessionDocument().viewport,x:'+JSON.stringify(x)+'});window.__archhubNamingCancel=a.saveSessionAs();return true;})()');
   const cancel=await native({kind:'cancel-save',title:'Save session'});
   assert.equal(cancel.closed,true,cancel.error);
   assert.equal(await js('window.__archhubNamingCancel.then(r=>r.cancelled)'),true);
   assert.equal(await until(async()=>json(source).viewport.x,v=>v===x),x);
   assert.equal(path.normalize(await call('getSessionPath')),path.normalize(source));
   assert.deepEqual(fs.readFileSync(target),targetBytes);
   return {pass:true,expected_http:['400 /api/session-files'],got:{revisionRestored:revision,nameCheckRestored:initialCheck,refusal,assignedRevision:saved.issueRevision,bothFilesPreserved:true,nativeCancel:cancel,autosaveReadBack:true}};
  }catch(error){failure=error;throw error;}finally{
   await restoreAfter(failure,async()=>{
    if(originalRegister)await register(originalRegister.number,{issuedDestination:originalRegister.issuedDestination||'',namingRegister:originalRegister.namingRegister||'',issuedRegister:originalRegister.issuedRegister||''});
    await restoreView({path:previous,workspace:previousProject,scope:previousScope});
   });
  }
 });
 await step(steps[12],async()=>{
  const call=(method,...args)=>js('window.ArchHubAPI['+JSON.stringify(method)+'](...'+JSON.stringify(args)+')');
  const previous=await js('(()=>{const a=window.ArchHubAPI,s=a.getSnapshot();return {path:a.getSessionPath(),scope:s.settingsScope,workspace:s.activeWorkspace};})()');
  assert.ok(previous.path && workspaceId,'The saved Settings fixture and its project must exist.');
  const projectName='Zinc project', sessionTitle='Zinc coordination';
  const root=path.join(folder,projectName), {sessionsFolder:docs}=await call('readSessionsFolder');
  const relative=path.relative(isolated,docs);
  assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative),'Use the isolated QA sessions folder.');
  let source=path.join(docs,'picker-source.archhub'), target=path.join(docs,'picker-target.archhub');
  assert.ok(!fs.existsSync(source) && !fs.existsSync(target) && !fs.existsSync(root),'Named-picker fixture already exists.');
  fs.mkdirSync(root);fs.mkdirSync(docs,{recursive:true});
  const ownerBytes=()=>[globalFile,workspaceFile,source,target].map(p=>fs.existsSync(p)?fs.readFileSync(p):null);
  async function saveCanvas(name,where,project){
   // Sessions names its files after their title (APPTIDY): follow the file to where it now is.
   await call('newSession',name);await call('saveSession',where);await call('setSessionModel',await call('getSessionPath'),{project});
   const at=await call('getSessionPath');const saved=json(at);assert.equal(saved.properties.project,project);return {id:saved.id,at};
  }
  // Both synthetic targets start with Z. A real select type-ahead commits once, without selecting intermediate owners.
  async function pick(label,name){
   const selector=JSON.stringify('select[aria-label="'+label+'"]');
   const options=await until(()=>js('(()=>{const s=document.querySelector('+selector+');return s&&!s.disabled?[...s.options].filter(o=>!o.disabled&&o.text.trim().toLowerCase().startsWith("z")).map(o=>({name:o.text.trim(),value:o.value})):[];})()'),rows=>rows.length>0);
   assert.deepEqual(options.map(o=>o.name),[name]);
   assert.equal(await clickText(label,'select'),true);
   await key('Escape','Escape',27);
   assert.equal(await js('document.activeElement===document.querySelector('+selector+')'),true);
   await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'z',code:'KeyZ',windowsVirtualKeyCode:90,text:'z'});
   await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'z',code:'KeyZ',windowsVirtualKeyCode:90});
   return options[0].value;
  }
  async function postSettings(operation,args,destination){
   const lease=window.__archhubSession,subject=window.ArchHubAPI.getSnapshot().desktopAccess.subject;
   const response=await fetch('/api/universal/settings-action',{method:'POST',cache:'no-store',
    headers:{'Content-Type':'application/json','X-ArchHub-Session':lease.token,'X-ArchHub-CSRF':lease.csrf,'X-ArchHub-Desktop-Subject':subject},
    body:JSON.stringify({function:operation,args,context:{surface:'settings',session:destination.session,settingsDestination:destination}})});
   const body=await response.json();
   return response.ok ? {status:response.status,destination:body.result?.settingsDestination} : {status:response.status,code:body.code};
  }
  const request=(operation,args,destination)=>js('('+postSettings.toString()+')(...'+JSON.stringify([operation,args,destination])+')');
  async function conflict(operation,args,destination){
   const before=ownerBytes();
   const result=await request(operation,args,destination);
   assert.deepEqual(result,{status:409,code:'settings_destination_changed'});
   assert.deepEqual(ownerBytes(),before,'A refused '+operation+' changed a Settings or Canvas file.');
   return result;
  }
  function projectView(){
   const api=window.ArchHubAPI;
   const heading=document.querySelector('[data-screen="settings/Projects"] .sheet-page-heading h2');
   return {heading:heading?.getClientRects().length?heading.textContent.trim():null,
    destination:api.getSnapshot().settingsDestination,path:api.getSessionPath()};
  }
  function canvasView(){
   const api=window.ArchHubAPI,canvas=document.querySelector('[data-screen="canvas"]');
   const control=document.querySelector('aside[aria-label="Session settings"] [aria-label="Done when"]');
   return {canvas:!!canvas?.getClientRects().length,inspector:!!control?.getClientRects().length,
    id:api.getSessionDocument()?.id,path:api.getSessionPath()};
  }
  let registered,failure;
  try{
   await call('addWorkspace',{folder:root});
   registered=await js('window.ArchHubAPI.getSnapshot().workspaces.find(w=>window.ArchHubAPI.sessionPathKey(w.path||w.folder)===window.ArchHubAPI.sessionPathKey('+JSON.stringify(root)+'))');
   assert.equal(registered?.name,projectName);assert.notEqual(registered.id,workspaceId);
   const savedTarget=await saveCanvas(sessionTitle,target,workspaceId),targetId=savedTarget.id;target=savedTarget.at;
   const savedSource=await saveCanvas('Source drawing',source,registered.id),sourceId=savedSource.id;source=savedSource.at;
   assert.notEqual(sourceId,targetId);
   await call('openSession',source);
   assert.equal(await clickText('Home'),true);
   assert.equal(await until(()=>js('Boolean(document.querySelector("[data-home-page]"))'),Boolean),true);
   assert.equal(await clickText('Settings'),true);
   assert.equal(await until(()=>js('Boolean(document.querySelector("nav[aria-label=\\"Settings categories\\"]"))'),Boolean),true);
   await call('refreshPreferences');await call('setSettingsScope','User');
   assert.equal(await pick('Which project',projectName),registered.id);
   const heading='Projects \u00b7 '+projectName;
   const project=await until(()=>js('('+projectView.toString()+')()'),v=>v.heading===heading&&v.destination?.workspace===registered.id);
   assert.equal(project.heading,heading);assert.equal(project.destination.scope,'Workspace');assert.equal(project.destination.session,sourceId);
   assert.equal(path.normalize(project.path),path.normalize(source));
   assert.deepEqual(await request('readPreferences',[],project.destination),{status:200,destination:project.destination});
   const wrongProject=await conflict('setSettingsScope',['Workspace',workspaceId,sourceId],project.destination);
   const wrongSession=await conflict('setSettingsScope',['Session',registered.id,targetId],project.destination);
   assert.equal(path.normalize(await pick('Which session',sessionTitle)),path.normalize(target));
   const opened=await until(()=>js('('+canvasView.toString()+')()'),v=>v.canvas&&v.inspector&&v.id===targetId);
   assert.equal(opened.canvas,true);assert.equal(opened.inspector,true);assert.equal(opened.id,targetId);
   assert.equal(path.normalize(opened.path),path.normalize(target));
   const current=await request('readPreferences',[],project.destination);
   assert.equal(current.status,200);assert.equal(current.destination.session,targetId);assert.equal(current.destination.workspace,workspaceId);
   const staleEdit=await conflict('setAppearance',['Appearance.Theme','Dark'],project.destination);
   return {pass:true,got:{projectHeading:project.heading,selectedProject:registered.id,canvas:opened,refusals:{wrongProject,wrongSession,staleEdit},unchangedFilesPerRefusal:4},expected_http:['409 /api/universal/settings-action']};
  }catch(error){failure=error;throw error;}finally{
   await restoreAfter(failure,async()=>{
   await restoreView(previous);
   if(registered)await call('removeWorkspace',registered.id);
   assert.equal(path.normalize(await call('getSessionPath')),path.normalize(previous.path));
   for(const created of [source,target])fs.rmSync(created,{force:true});
   });
  }
 });
}
