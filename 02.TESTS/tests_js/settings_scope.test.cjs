const {test}=require('node:test');
const {Buffer}=require('node:buffer');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const os=require('node:os');
const original=path.join(root,'02.TESTS/tests_js/settingsmatch.test.cjs');
const req=require('node:module').createRequire(original);
const {chromium}=req('playwright'),{transformSync}=req('esbuild');
const studio=path.join(root,'01.APP/nodelang/studio');
function executable(){
 const cache=process.env.PLAYWRIGHT_BROWSERS_PATH||path.join(os.homedir(),'AppData/Local/ms-playwright');
 const full=fs.existsSync(cache)&&fs.readdirSync(cache).filter(name=>/^chromium-\d+$/.test(name)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
 return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||(process.platform==='win32'&&full?path.join(cache,full,'chrome-win64/chrome.exe'):undefined);
}
async function mount(page,profile,extra){
 await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<meta charset="utf-8"><div id="root"></div>'}));
 await page.goto('http://settings-review.test');
 await page.addStyleTag({path:path.join(studio,'style.css')});
 await page.addStyleTag({content:'html,body,#root{height:100%;margin:0}'});
 for(const name of ['react.js','react-dom.js'])await page.addScriptTag({path:path.join(studio,'vendor',name)});
 await page.evaluate(({profile,extra})=>{
  window.fixture={profile,settings:[],hosts:[],agents:[],providers:[],workspaces:[{id:'example',name:'Example workspace',folder:'C:\\Example',path:'C:\\Example',available:true}],activeWorkspace:'example',workspaceHealth:{state:'ready'},graph:{workspaceIds:[]},connections:[],capabilities:[],pages:['Account','Appearance','Workshop','Privacy'],settingsScope:'User',sessionsFolder:'Sessions',runtimeParameters:{},...extra};
  window.writes=[];const listeners=new Set();window.update=values=>{window.fixture={...window.fixture,...values};listeners.forEach(fn=>fn());};
  window.ArchHubAPI={subscribe:f=>{listeners.add(f);return()=>listeners.delete(f);},getSnapshot:()=>window.fixture,supportsAction:()=>true,
   refreshRouter:async()=>({default_model:'free',models:[],fallback_models:[],requests:[],free_first:true}),readHostAvailability:async()=>[],listAgentsWorking:async()=>[],refreshSettingsControls:()=>new Promise(resolve=>{window.finishInitialSettingsRead=()=>{window.update({settingsDestination:{scope:'User',workspace:'example',session:'fixture'}});resolve({});};}),readSessionsFolder:async()=> 'Sessions',
   setSetting:async(id,value,destination)=>{window.settingCalls=(window.settingCalls||[]).concat([{id,value,destination}]);if(destination&&destination.scope!==window.fixture.settingsScope)throw Error('Settings destination changed');window.writes.push({id,value});window.fixture={...window.fixture,settings:window.fixture.settings.map(r=>r.id===id?{...r,value}:r)};listeners.forEach(f=>f());return {ok:true};},
  };
  window.ArchHubAPI.resetSetting=async id=>window.ArchHubAPI.setSetting(id,window.fixture.settings.find(row=>row.id===id).default);
  window.ArchHubAPI.setSettingsScope=async(scope,destination=window.fixture.settingsDestination)=>{window.scopeCalls=(window.scopeCalls||[]).concat([{scope,destination}]);if(destination&&destination.scope!==window.fixture.settingsScope)throw Error('Settings destination changed');if(!window.fixture.settingsDestination)throw Error('Settings destination not ready');window.writes.push({scope,destination:window.fixture.settingsDestination});window.update({settingsScope:scope,settingsDestination:{...window.fixture.settingsDestination,scope}});return {ok:true};};
window.imports=[];window.ArchHubAPI.importPreferences=async value=>{window.imports.push(value);if(window.imports.length===1)throw Error('Import refused for this test');return {ok:true};};
window.ArchHubAPI.resetPreferences=async()=>{window.writes.push({reset:window.fixture.settingsScope});return {ok:true};};
  window.ArchHubAPI.exposeSettingsPage=async page=>{window.writes.push({page});return {ok:true};};
 },{profile,extra});
 for(const name of ['tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx','ds_settings3.jsx']){
  const file=path.join(studio,name);
  await page.addScriptTag({content:transformSync(fs.readFileSync(file,'utf8'),{loader:'jsx'}).code});
 }
 await page.evaluate(()=>{
  for(const name of ['MemoryRules','Automations','HostSkills','SystemGraph','Providers'])window.UI[name]=()=>React.createElement('p',null,name+' owner');
  function Harness(){const [page,setPage]=React.useState('Account');const [advanced,setAdvanced]=React.useState(false);
   const u={go:route=>{if(route.startsWith('settings/'))setPage(route.slice(9));},act:async fn=>{if(window.queueSettingAct){window.pendingSettingAct=fn;return null;}try{return await fn();}catch(error){window.lastError=error.message;return null;}},show:()=>{},confirm:(_message,fn)=>fn(),download:(name,scope)=>window.writes.push({export:name,scope}),settingsOrigin:'home',advanced,setAdvanced};
   return React.createElement(window.UI.Ctx.Provider,{value:u},React.createElement(window.UI.Settings,{page}));}
  window.ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Harness));
 });
}
test('Settings scopes and transfers use checkout sources and preserve the destination',async()=>{
 const browser=await chromium.launch({headless:true,executablePath:executable()});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:950}}),errors=[];page.setDefaultTimeout(3000);page.on('pageerror',error=>errors.push(error.message));
  await mount(page,{name:'Scope reviewer',email:'scope@example.test',signedIn:false,checking:false},{settingsScopes:{Workspace:true,Session:true},keyboardCommands:[],settings:[]});
  const selector=page.getByLabel('Settings scope',{exact:true});
  await selector.waitFor();
  assert.equal(await selector.isDisabled(),true);
  assert.equal(await page.getByRole('button',{name:'Import into Everywhere',exact:true}).isDisabled(),true);
  assert.equal(await page.getByRole('button',{name:'Reset Everywhere',exact:true}).isDisabled(),true);
  await page.evaluate(()=>window.finishInitialSettingsRead());
  await selector.selectOption('Workspace');
  assert.deepEqual(await page.evaluate(()=>window.writes[0]),{scope:'Workspace',destination:{scope:'User',workspace:'example',session:'fixture'}});
  await page.getByRole('button',{name:'Import into Current workspace',exact:true}).waitFor();
  await page.getByRole('button',{name:'Export Current workspace',exact:true}).click();await page.getByRole('button',{name:'Export all scopes',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.writes.slice(-2)),[{export:'Settings',scope:'Workspace'},{export:'Settings',scope:'All'}]);
  const payload={format:'archhub.settings',version:1,scopes:{Workspace:{'Appearance.Theme':'Light'}}};
  await page.getByLabel('Import settings file',{exact:true}).setInputFiles({name:'settings.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(payload))});
  await page.getByRole('alert').filter({hasText:'Import refused for this test'}).waitFor();
  await page.getByRole('button',{name:'Retry settings transfer',exact:true}).click();await page.getByText('Settings applied to Current workspace.',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.imports.length),2);
  await page.getByRole('button',{name:'Reset Current workspace',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{reset:'Workspace'});
  await page.getByLabel('Settings scope',{exact:true}).selectOption('Session');await page.getByRole('button',{name:'Import into Current session',exact:true}).waitFor();
  await page.evaluate(()=>window.update({settingsDestination:{scope:'Session',workspace:'example',session:'fixture'},settings:[{id:'Appearance.Theme',label:'Theme',page:'Appearance',type:'enum',options:['Dark','Light','System'],default:'Dark',value:'Dark'}]}));
  await page.getByRole('navigation',{name:'Settings categories'}).getByRole('button',{name:'Look',exact:true}).click();
  await page.evaluate(()=>{window.queueSettingAct=true;});
  await page.getByLabel('Theme',{exact:true}).selectOption('Light');
  await page.evaluate(()=>window.update({settingsScope:'User',settingsDestination:{scope:'User',workspace:'example',session:'fixture'},settings:[{id:'Appearance.Theme',label:'Theme',page:'Appearance',type:'enum',options:['Dark','Light','System'],default:'Dark',value:'Dark'}]}));
  const refusal=await page.evaluate(async()=>{try{await window.pendingSettingAct();return null;}catch(error){return error.message;}});
  assert.equal(refusal,'Settings destination changed');
  assert.deepEqual(await page.evaluate(()=>window.settingCalls.at(-1)),{id:'Appearance.Theme',value:'Light',destination:{scope:'Session',workspace:'example',session:'fixture'}});
  assert.equal(await page.evaluate(()=>window.fixture.settings[0].value),'Dark','queued event did not change the newly selected global value');
  await page.evaluate(()=>{window.queueSettingAct=true;});
  await selector.selectOption('Workspace');
  await page.evaluate(()=>window.update({settingsScope:'Session',settingsDestination:{scope:'Session',workspace:'example',session:'other-file'}}));
  const staleScope=await page.evaluate(async()=>{try{await window.pendingSettingAct();return null;}catch(error){return error.message;}});
  assert.equal(staleScope,'Settings destination changed');
  assert.deepEqual(await page.evaluate(()=>window.scopeCalls.at(-1)),{scope:'Workspace',destination:{scope:'User',workspace:'example',session:'fixture'}});
  assert.equal(await page.evaluate(()=>window.fixture.settingsScope),'Session');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({result:'PASS',actual:'Settings sheet, controls and action registry',workspaceSelector:true,sessionSelector:true,exportSelectedAndAll:true,upload:'fixture JSON bytes',refusalAndRetry:true,resetDestination:'Workspace',pageErrors:errors,boundary:'fixture owner; real owner tested separately; not installed'}));
 }finally{await browser.close();}
});
