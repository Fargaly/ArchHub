// Exercises the real Settings component, shared controls and action registry in a disposable browser.
const {test}=require('node:test');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),{transformSync}=require('esbuild');
const root=path.resolve(__dirname,'../..');
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
  window.fixture={profile,settings:[],hosts:[],agents:[],providers:[],workspaces:[{id:'example',name:'Example workspace',folder:'C:\\Example',path:'C:\\Example',available:true}],activeWorkspace:'example',workspaceHealth:{state:'ready'},graph:{workspaceIds:[]},connections:[],capabilities:[],pages:['Account','Appearance','Workshop','Privacy'],settingsScope:'User',settingsDestination:{scope:'User',workspace:'example',session:'fixture'},keyboardCommands:[{id:'keyboard.save',label:'Save workflow',contexts:['canvas'],value:'Ctrl S'}],sessionsFolder:'Sessions',runtimeParameters:{},update:{state:'idle',installed:'fixture-build',available:null},router:{default_model:'free',models:['free','other'],fallback_models:[],requests:[],free_first:true,live_agents:{complete:true,processes:[]}},...extra};
  window.writes=[];const listeners=new Set();
  window.ArchHubAPI={subscribe:f=>{listeners.add(f);return()=>listeners.delete(f);},getSnapshot:()=>window.fixture,supportsAction:()=>true,
   refreshRouter:async()=>({default_model:'free',models:['free','other'],fallback_models:[],requests:[],free_first:true}),readHostAvailability:async()=>[],listAgentsWorking:async()=>[],refreshSettingsControls:async()=>({}),readSessionsFolder:async()=> 'Sessions',
   setSetting:async(id,value)=>{window.writes.push({id,value});window.fixture={...window.fixture,settings:window.fixture.settings.map(r=>r.id===id?{...r,value}:r)};listeners.forEach(f=>f());return {ok:true};},
  };
  window.ArchHubAPI.setKeybinding=async(id,value,destination)=>{
   const keyboardCommands=window.fixture.keyboardCommands.map(row=>row.id===id?{...row,value,changed:true}:row);
   window.writes.push({id,value,destination});window.fixture={...window.fixture,keyboardCommands};listeners.forEach(f=>f());
   return {keyboardCommands};
  };
  window.ArchHubAPI.resetSetting=async id=>window.ArchHubAPI.setSetting(id,window.fixture.settings.find(row=>row.id===id).default);
  window.ArchHubAPI.setSettingsScope=async scope=>{window.writes.push({scope});return {ok:true};};
  window.ArchHubAPI.exposeSettingsPage=async page=>{window.writes.push({page});return {ok:true};};
  window.ArchHubAPI.setRouterSettings=async router=>{window.writes.push({router});return {default_model:router.default_model||'free',models:['free','other'],fallback_models:[],requests:[],free_first:true};};
  let permissions={runMode:'Ask first',runModes:['Ask first','Accept edits','Plan only'],tools:{},toolModes:['Ask','Allow','Deny']};
  window.ArchHubAPI.readPermissions=async()=>permissions;
  window.ArchHubAPI.setPermissions=async values=>{window.writes.push({permissions:values});permissions={...permissions,...values};return permissions;};
  // Owner reads on pages this test only opens (Updates, Library, ...) resolve empty; writes stay recorded above.
  window.ArchHubAPI=new Proxy(window.ArchHubAPI,{get:(target,key)=>key in target||typeof key!=='string'?target[key]:async()=>({})});
 },{profile,extra});
 for(const name of ['tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx','ds_settings3.jsx']){
  const file=path.join(studio,name);
  // Settings reads the provider owner at load; its own file is not part of this fixture.
  if(name==='ds_settings3.jsx')await page.evaluate(()=>{window.UI.Providers=()=>React.createElement('p',null,'Providers owner');});
  await page.addScriptTag({content:transformSync(fs.readFileSync(file,'utf8'),{loader:'jsx'}).code});
 }
 await page.evaluate(()=>{
  for(const name of ['MemoryRules','Automations','HostSkills','SystemGraph','Providers'])window.UI[name]=()=>React.createElement('p',null,name+' owner');
  function Harness(){const [page,setPage]=React.useState('Account');const [advanced,setAdvanced]=React.useState(false);
   const u={go:route=>{window.lastRoute=route;if(route.startsWith('settings/'))setPage(route.slice(9));},act:async fn=>fn(),show:()=>{},settingsOrigin:'home',advanced,setAdvanced};window.goSettings=u.go;
   return React.createElement(window.UI.Ctx.Provider,{value:u},React.createElement(window.UI.Settings,{page}));}
  window.ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Harness));
 });
}
test('Settings design areas, exact owner navigation, edits, reset and global Changed',async()=>{
 const browser=await chromium.launch({headless:true,executablePath:executable()});
 try{
  for(const width of [1440,900]){
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[];
   page.setDefaultTimeout(6000);
   page.on('pageerror',e=>{errors.push(e.message);console.error('PAGEERROR',e.message);});
   await mount(page,{name:'Design reviewer',email:'review@example.test',signedIn:false,checking:false},{settings:[
    {id:'Projects.Angle precision',page:'Projects',group:'Units and precision',label:'Angle precision',type:'number',control:'range',min:0,max:3,default:1,value:1},
    {id:'Projects.Dates',page:'Projects',group:'Units and precision',label:'Dates',type:'choice',options:['DD/MM/YYYY','YYYY-MM-DD','MM/DD/YYYY'],default:'DD/MM/YYYY',value:'DD/MM/YYYY'},
    {id:'Projects.Area',page:'Projects',group:'Units and precision',label:'Area',type:'choice',options:['m²','ft²'],default:'m²',value:'m²'},
    {id:'Projects.Area precision',page:'Projects',group:'Units and precision',label:'Area precision',type:'number',control:'range',min:0,max:3,default:2,value:2},
    {id:'Projects.Length',page:'Projects',group:'Units and precision',label:'Length',type:'choice',options:['Millimetres','Centimetres','Metres','Feet and inches'],default:'Millimetres',value:'Millimetres'},
    {id:'Projects.Length precision',page:'Projects',group:'Units and precision',label:'Length precision',type:'number',control:'range',min:0,max:3,default:0,value:0},
    {id:'Appearance.Theme',page:'Appearance',group:'Theme and colour',label:'Theme',type:'enum',options:['Dark','Light','System'],value:'Dark',default:'Dark'},
    {id:'Appearance.Text scale',page:'Appearance',group:'Size and density',label:'Text scale',type:'number',value:110,default:100},
    {id:'Workshop.Keep messages',page:'Workshop',group:'Messages',label:'Keep messages',description:'Conversation retention',type:'number',value:20,default:10},
    {id:'Privacy.Review',page:'Privacy',group:'Privacy',label:'Review before sharing',type:'boolean',value:true,default:true},
    {id:'Advanced.Limit',page:'Advanced',group:'Budgets',label:'Call limit',type:'number',value:30,default:20,advanced:true},
    {id:'Appearance.Node radius',page:'Appearance',group:'Canvas',label:'Node radius',type:'number',value:6,default:6,advanced:true},
   ]});
   await page.locator('.sheet-columns:not([hidden])').waitFor();
   const nav=page.getByRole('navigation',{name:'Settings categories'});
   const expected=['Account','Projects','Agents','Connections','This PC'];
   assert.deepEqual(await nav.getByRole('button').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-label'))),expected,'at most five Settings pages');
   // Every former area still opens its own page inside one of the five.
   for(const [former,area,screen] of [['Look','This PC','Appearance'],['You','This PC','Privacy'],['System','This PC','System graph'],['Updates & About','This PC','Updates & About'],['Dependencies','This PC','Dependencies'],['Advanced','This PC','Advanced'],['Workshop','Agents','Workshop'],['Automations','Agents','Automations'],['Library & Mods','Agents','Library & Mods'],['Brain','Account','Brain']]){
    await page.evaluate(route=>window.goSettings(route),'settings/'+former);
    await page.locator(`[data-screen="settings/${screen}"]`).waitFor();
    assert.equal(await nav.locator('button[aria-current="page"]').getAttribute('aria-label'),area,former+' opens inside '+area);
   }
   // Models and Permissions open Agents' real owners, not Account; an edit reaches that owner.
   await page.evaluate(()=>window.goSettings('settings/Models'));
   await page.locator('[data-screen="settings/BABOOM"]').waitFor();
   assert.equal(await nav.locator('button[aria-current="page"]').getAttribute('aria-label'),'Agents');
   assert.equal(await page.getByRole('heading',{name:'Your identity',exact:true}).count(),0,'Models is not Account');
   await page.getByLabel('Default model',{exact:true}).selectOption('other');
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{router:{default_model:'other'}});
   await page.evaluate(()=>window.goSettings('settings/Permissions'));
   await page.locator('[data-screen="settings/Hooks"]').waitFor();
   assert.equal(await nav.locator('button[aria-current="page"]').getAttribute('aria-label'),'Agents');
   assert.equal(await page.getByRole('heading',{name:'Your identity',exact:true}).count(),0,'Permissions is not Account');
   await page.getByLabel('Run mode',{exact:true}).selectOption('Plan only');
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{permissions:{runMode:'Plan only'}});
   await page.evaluate(()=>window.goSettings('settings/Social'));
   await page.locator('[data-screen="settings/Account"]').waitFor();
   const social=page.getByRole('heading',{name:'Social media',exact:true});
   assert.equal(await social.evaluate(node=>{const r=node.getBoundingClientRect();return r.top>=0&&r.top<window.innerHeight;}),true,'Social lands on Account › Social media');
   await page.getByRole('button',{name:'Open Social media',exact:true}).waitFor();
   // Each page shows only its own rows.
   for(const [route,shown,hidden] of [['settings/Privacy','Privacy.Review','Appearance.Theme'],['settings/Look','Appearance.Theme','Privacy.Review'],['settings/Updates & About',null,'Privacy.Review'],['settings/Workshop','Workshop.Keep messages','Privacy.Review'],['settings/Automations',null,'Workshop.Keep messages'],['settings/Hooks',null,'Workshop.Keep messages']]){
    await page.evaluate(r=>window.goSettings(r),route);
    await page.locator(`[data-screen="settings/${route==='settings/Look'?'Appearance':route.slice(9)}"]`).waitFor();
    if(shown)assert.equal(await page.locator(`[data-setting="${shown}"]`).count(),1,shown+' on '+route);
    assert.equal(await page.locator(`[data-setting="${hidden}"]`).count(),0,hidden+' not on '+route);
   }
   await page.evaluate(()=>window.goSettings('settings/Account'));
   await nav.getByRole('button',{name:'Agents',exact:true}).click();
   await page.getByRole('navigation',{name:'Agents pages'}).getByRole('button',{name:'Workshop',exact:true}).click();
   await page.locator('[data-screen="settings/Workshop"]').waitFor();
   await page.getByLabel('Keep messages',{exact:true}).waitFor();
   await page.getByLabel('Search settings',{exact:true}).fill('where do I change message retention');
   await page.getByRole('listbox',{name:'Settings results'}).getByRole('option').first().waitFor();
   assert.match(await page.getByRole('listbox',{name:'Settings results'}).getByRole('option').first().innerText(),/Keep messages/);
   await page.getByLabel('Search settings',{exact:true}).press('Enter');
   await page.locator('[data-screen="settings/Workshop"]').waitFor();
   assert.equal(await page.getByLabel('Search settings',{exact:true}).inputValue(),'');
   await page.getByLabel('Keep messages',{exact:true}).fill('25');
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{id:'Workshop.Keep messages',value:25});
   await page.getByRole('button',{name:/^Changed(?: only)?(?: \d+)?$/}).first().click();
   assert.equal(await page.locator('[data-setting="Appearance.Text scale"]').count(),1,'changed results cross areas');
   assert.equal(await page.locator('[data-setting="Workshop.Keep messages"]').count(),1);
   assert.equal(await page.locator('[data-setting="Privacy.Review"]').count(),0);
   assert.equal(await page.getByRole('button',{name:'Open Workshop',exact:true}).isVisible(),false,'Changed hides non-setting panels');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'page overflow '+JSON.stringify(await page.locator('*').evaluateAll(nodes=>nodes.filter(n=>n.getBoundingClientRect().right>window.innerWidth+1&&n.getBoundingClientRect().width).slice(0,8).map(n=>({tag:n.tagName,cls:n.className,width:n.getBoundingClientRect().width,right:n.getBoundingClientRect().right})))));
   assert.deepEqual(errors,[]);
   await page.getByRole('button',{name:'All',exact:true}).click();
   await nav.getByRole('button',{name:'This PC',exact:true}).click();
   await page.locator('[data-screen="settings/Appearance"]').waitFor();
   assert.equal(await page.locator('.sheet-page-heading h2').innerText(),'This PC');
   await page.getByLabel('Theme',{exact:true}).selectOption('Light');
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{id:'Appearance.Theme',value:'Light'});
   await page.getByRole('button',{name:'Reset Theme',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{id:'Appearance.Theme',value:'Dark'});
   const shortcut=page.getByRole('button',{name:'Change shortcut for Save workflow'});
   await shortcut.click();
   await shortcut.press('Control+Shift+K');
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{id:'keyboard.save',value:'Ctrl Shift K',destination:{scope:'User',workspace:'example',session:'fixture'}});
   await page.getByRole('navigation',{name:'On this page'}).getByRole('button').first().click();
   await page.getByRole('button',{name:'Hide advanced',exact:true}).click();
   assert.equal(await page.locator('[data-setting="Appearance.Node radius"]').count(),0);
   await page.getByRole('button',{name:'Show advanced',exact:true}).click();
   await page.getByLabel('Node radius',{exact:true}).waitFor();
   await page.getByRole('button',{name:'Put on Canvas',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{page:'Appearance'});
   const scope=page.getByLabel('Settings scope',{exact:true});
   const workspace=scope.locator('option[value=Workspace]');
   assert.equal(await workspace.evaluate(option=>option.matches(':disabled')),true,await workspace.evaluate(option=>option.outerHTML));
   await scope.focus();
   await scope.press('End');
   assert.equal(await scope.inputValue(),'User','keyboard selection must skip the unavailable workspace scope');
   assert.equal(await page.evaluate(()=>window.writes.some(row=>'scope' in row)),false);
   await nav.getByRole('button',{name:'Projects',exact:true}).click();
   await page.getByRole('heading',{name:'Project folders',exact:true}).waitFor();
   await page.getByRole('heading',{name:'Example workspace',exact:true}).waitFor();
   await page.getByLabel('Length',{exact:true}).selectOption('Metres');
   const precision=page.getByRole('slider',{name:'Length precision'});
   await precision.focus();
   await precision.press('ArrowRight');
   assert.deepEqual(await page.evaluate(()=>window.writes.slice(-2)),[{id:'Projects.Length',value:'Metres'},{id:'Projects.Length precision',value:1}]);
   await page.getByLabel('Area',{exact:true}).selectOption('ft²');
   await page.getByRole('slider',{name:'Area precision',exact:true}).press('ArrowRight');
   assert.deepEqual(await page.evaluate(()=>window.writes.slice(-2)),[{id:'Projects.Area',value:'ft²'},{id:'Projects.Area precision',value:3}]);
   await page.getByRole('slider',{name:'Angle precision',exact:true}).press('ArrowRight');
   await page.getByLabel('Dates',{exact:true}).selectOption('YYYY-MM-DD');
   assert.deepEqual(await page.evaluate(()=>window.writes.slice(-2)),[{id:'Projects.Angle precision',value:2},{id:'Projects.Dates',value:'YYYY-MM-DD'}]);
   assert.deepEqual(errors,[]);
   console.log(JSON.stringify({width,areas:expected.length,wordSearch:true,keyboardJump:true,globalChanged:true,errors}));
   await page.close();
  }
 }finally{await browser.close();}
});


// The 43 approved design sections (archhub-directions app.js CARDS) and where each lives in the product sheet.
// [design section, rail area, route, heading shown | null, door button | null, coming-soon label | null]
const DESIGN_SECTIONS=[
 ['Account','Account','Account','Your identity'],['Plan & access','Account','Account','Plan & access','Open Plan & access'],['Community','Account','Account','Community','Open Community'],['Social media','Account','Account','Social media','Open Social media'],['Brain and cloud sync','Account','Brain','Brain and cloud sync'],
 ...['Project register','Units and precision','Office standard','Templates','Location','Revit worksharing','IFC and BCF','Print and PDF','CAD','File naming','CDE folders'].map(t=>[t,'Projects','Projects',null,null,'project']),
 ['Your agents','Agents','Agents','Agents'],['Models','Agents','Models','Models'],['What agents may do','Agents','Permissions','Permissions'],['Workshop','Agents','Workshop','Workshop','Open Workshop'],['Automations','Agents','Automations','Automations'],['Meetings','Agents','Agents','Meetings','Open Meetings'],['BABOOM','Agents','BABOOM','Models'],['Tools in the Library','Agents','Library & Mods','Library & Mods','Open Library'],
 ['Programs','Connections','Connections','Programs'],['Accounts','Connections','Connections','Accounts','Connect'],['Subscriptions','Connections','Connections','Subscriptions'],['Tool servers (MCP)','Connections','Connections','Tool servers (MCP)'],['Program options','Connections','Connections','Program options',null,'Program options'],['AI providers','Connections','Connections','AI providers','Open model providers'],['Phone and cloud','Connections','Connections','Phone and cloud','Open connected devices'],['Network','Connections','Connections','Network',null,'Network'],['Notifications','Connections','Connections','Notifications','Open notification setting','Desktop notifications, sound and quiet hours'],
 ...['Theme and colour','Size and density','Panels','Canvas','Keyboard'].map(t=>[t,'This PC','Look',t]),['Agents on this PC','This PC','Dependencies','Managed tools','Open dependencies'],['Workspaces and files','This PC','Privacy','Workspaces and files'],['Privacy and keys','This PC','Privacy','Privacy'],['The app','This PC','Updates & About',null,'Check for updates'],['System graph','This PC','System','Live wiring']
];
test('all 43 design sections are reachable under their design parent, working and unavailable actions told apart',async()=>{
 assert.equal(DESIGN_SECTIONS.length,43);
 const browser=await chromium.launch({headless:true,executablePath:executable()});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:950}}),errors=[];
  page.setDefaultTimeout(6000);page.on('pageerror',e=>errors.push(e.message));
  await mount(page,{name:'Design reviewer',email:'review@example.test',signedIn:false,checking:false},{settings:[{id:'Privacy.Review',page:'Privacy',group:'Privacy',label:'Review before sharing',type:'boolean',value:true,default:true}]});
  await page.locator('.sheet-columns:not([hidden])').waitFor();
  const nav=page.getByRole('navigation',{name:'Settings categories'}),report=[];
  for(const [section,area,route,heading,door,soon] of DESIGN_SECTIONS){
   await page.evaluate(r=>window.goSettings(r),'settings/'+route);
   await page.locator(`[data-screen="settings/${({Look:'Appearance',System:'System graph',Models:'BABOOM',Permissions:'Hooks'})[route]||route}"]`).waitFor();
   if(heading)await page.locator('.sheet-content').getByRole('heading',{name:heading,exact:true}).first().waitFor();
   assert.equal(await nav.locator('button[aria-current="page"]').getAttribute('aria-label'),area,section+' sits under '+area);
   const content=page.locator('.sheet-content');
   if(heading)assert.ok(await content.getByRole('heading',{name:heading,exact:true}).count()>=1,section+': heading '+heading);
   if(door)assert.equal(await content.getByRole('button',{name:door,exact:true}).count()>=1,true,section+': working action '+door);
   let state=door?'working':'shown';
   if(soon==='project'){const items={'Project register':['Client','Stage','Confidentiality'],'Units and precision':['Length','Length precision','Area','Area precision','Angle precision','Dates'],'Templates':['Revit template','AutoCAD template','Title block','Sheet size','New project folders'],'IFC and BCF':['IFC version','IFC export setup','BCF version'],'Print and PDF':['Pen table','Sheet set','Default scale'],'CAD':['Layer standard','Colour to lineweight','DWG export setup','DWG version']}[section]||[section];
    const shown=await content.getByRole('heading',{name:section,exact:true}).count();let pending=0;for(const item of items)pending+=await content.getByRole('group',{name:item+'. Coming soon: not built yet',exact:true}).count();assert.equal(shown+pending>=1,true,section+' shown or marked coming soon');state=shown?'shown':'coming soon';}
   else if(soon){assert.equal(await content.getByRole('group',{name:soon+'. Coming soon: not built yet',exact:true}).count(),1,section+': unavailable action marked');state=door?'working + coming soon':'coming soon';}
   report.push([section,area,route,state]);
  }
  // The new doors open the existing owner screens.
  for(const [route,door,target] of [['Account','Open Plan & access','access'],['Account','Open Community','community'],['Account','Open Social media','social'],['Agents','Open Meetings','meetings'],['Connections','Open model providers','settings/Providers'],['Connections','Open connected devices','access'],['Connections','Open notification setting','settings/BABOOM']]){
   await page.evaluate(r=>window.goSettings(r),'settings/'+route);
   await page.locator(`[data-screen="settings/${route}"]`).waitFor();
   await page.locator('.sheet-content').getByRole('button',{name:door,exact:true}).click();
   assert.equal(await page.evaluate(()=>window.lastRoute),target,door);
  }
  // AI providers opens the real provider controls, which normally sit behind Show advanced.
  await page.evaluate(()=>window.goSettings('settings/Account'));
  await page.evaluate(()=>window.goSettings('settings/Providers'));
  await page.locator('[data-screen="settings/BABOOM"]').waitFor();
  await page.getByRole('heading',{name:'Providers and request profiling',exact:true}).waitFor();
  assert.equal(await page.getByText('Providers owner',{exact:true}).count(),1,'provider owner mounted');
  assert.equal(await page.getByRole('button',{name:'Hide advanced',exact:true}).count(),1);
  // New project folders is a working workflow, not a whole-feature placeholder.
  await page.evaluate(()=>window.goSettings('settings/Projects'));
  await page.locator('[data-screen="settings/Projects"]').waitFor();
  assert.equal(await page.getByRole('group',{name:'New project folders. Coming soon: not built yet',exact:true}).count(),0,'no false placeholder');
  await page.getByRole('button',{name:'Open New project',exact:true}).click();
  const folders=page.getByLabel('New project folders',{exact:true});
  await folders.waitFor();
  assert.equal(await folders.locator('option[value="ISO 19650 CDE tree"]').evaluate(o=>o.disabled),true,'ISO tree limitation stays visible');
  await folders.selectOption('Office project tree');
  await page.getByRole('button',{name:'Choose template folder',exact:true}).waitFor();
  assert.equal(await page.getByLabel('Project name',{exact:true}).count(),1,'registration fields stay separate in the New project form');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({sections:report.length,coming_soon:report.filter(r=>/coming soon/.test(r[3])).map(r=>r[0]),report}));
  await page.close();
 }finally{await browser.close();}
});

test('Look uses the five design families and passes the actual workflow to the existing read-only Canvas',()=>{
 const React=require('react'),{renderToStaticMarkup}=require('react-dom/server'),vm=require('node:vm');
 const graph={id:'actual-workflow',scopeKey:'actual-workflow',name:'Opened workflow',nodes:[{id:'real-node',title:'Actual node'}],wires:[]};
 const settings=[['Theme','Theme and colour'],['Text scale','Size and density'],['Inspector width','Panels'],['Canvas grid','Canvas']].map(([label,group],i)=>({id:'Appearance.'+label,page:'Appearance',label,group,type:'text',value:String(i),default:String(i)}));
 const data={settings,graph,pages:['Appearance'],profile:{checking:false},runtimeParameters:{},hosts:[],agents:[],workspaces:[],connections:[],settingsScope:'User'};
 const calls=[];
 const plain=({children})=>React.createElement('div',null,children);
 const window={UI:{A:{},D:{},api:{supportsAction:()=>false},useData:()=>data,useApp:()=>({}),useRegisteredActions:()=>({}),RegisteredActionStatus:()=>null,
  Btn:plain,Card:plain,Empty:plain,Heading:plain,Chip:plain,Providers:plain,Soon:plain,Ctx:React.createContext(null),
  SettingControl:({row})=>React.createElement('div',{'data-setting':row.id},row.label),
  Canvas:props=>{calls.push(props);return React.createElement('div',{'data-preview':props.preview.id});}},AHIcon:()=>null};
 vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio,'ds_settings3.jsx'),'utf8'),{loader:'jsx'}).code,{window,React});
 const html=renderToStaticMarkup(React.createElement(window.UI.Settings,{page:'Appearance'}));
 for(const name of ['Theme and colour','Size and density','Panels','Canvas','Keyboard'])assert.ok(html.includes('<h3>'+name+'</h3>'),name);
 for(const row of settings)assert.equal(html.split('data-setting="'+row.id+'"').length-1,1,row.id+' has one editor');
 assert.equal(calls.length,1);assert.equal(calls[0].preview,graph);assert.equal(calls[0].embedded,true);assert.equal(calls[0].externalInspector,true);
 assert.ok(html.includes('inert=""'),'the live preview cannot edit or run the workflow');
 assert.ok(html.includes('sheet-keybindings'),'the keyboard editor is mounted in Look');
 data.graph={workspaceIds:[]};
 const empty=renderToStaticMarkup(React.createElement(window.UI.Settings,{page:'Appearance'}));
 assert.ok(empty.includes('Open a workflow to preview its real nodes here.'));
 assert.equal(calls.length,1,'an unloaded workflow does not mount a Canvas');
});

test('dimensioned schedule keeps its warning, quantity and source measurement', async()=>{
 const browser=await chromium.launch({headless:true,executablePath:executable()});
 try{
  const page=await browser.newPage();
  await mount(page,{name:'Reviewer'}, {settings:[{id:'Projects.Length',value:'Metres'},{id:'Projects.Length precision',value:2}]});
  await page.evaluate(()=>{window.ReactResizablePanels={};});
  await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,'ds_screens.jsx'),'utf8'),{loader:'jsx'}).code});
  await page.evaluate(()=>{
   const result={columns:['length_mm','qty'],rows:[[1250,2]],warnings:['Two source rows were excluded']};
   window.rawSchedule=result;
   window.ReactDOM.createRoot(document.body.appendChild(document.createElement('section'))).render(window.React.createElement(window.UI.ResultPreview,{value:result}));
  });
  const preview=page.locator('section').filter({has:page.getByRole('columnheader',{name:'Length',exact:true})}).last();
  await preview.getByText('1.25 m',{exact:true}).waitFor();
  assert.deepEqual(await preview.locator('td').allTextContents(),['1.25 m','2']);
  assert.equal(await preview.locator('dd').innerText(),'Two source rows were excluded');
  assert.equal(await page.evaluate(()=>window.rawSchedule.rows[0][0]),1250);
 }finally{await browser.close();}
});

test('square-metre Revit fields display in project area units and preserve warnings and untyped values',async()=>{
 const browser=await chromium.launch({headless:true,executablePath:executable()});
 try{
  const page=await browser.newPage();
  await mount(page,{name:'Reviewer'},{settings:[{id:'Projects.Area',value:'ft²'},{id:'Projects.Area precision',value:3}]});
  await page.evaluate(()=>{window.ReactResizablePanels={};});
  await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,'ds_screens.jsx'),'utf8'),{loader:'jsx'}).code});
  await page.evaluate(()=>{
   const result={columns:['area_m2','area'],rows:[[1,2.75],[0,0],[null,'']],total_area_m2:1,warnings:['Some elements were missing']};
   window.rawArea=result;
   window.ReactDOM.createRoot(document.body.appendChild(document.createElement('article'))).render(window.React.createElement(window.UI.ResultPreview,{value:result}));
  });
  const preview=page.locator('article').filter({has:page.getByRole('columnheader',{name:'Area',exact:true})}).last();
  await preview.locator('td').first().waitFor();
  assert.deepEqual(await preview.locator('td').allTextContents(),['10.764 ft²','2.75','0.000 ft²','0','','']);
  assert.deepEqual(await preview.locator('dd').allTextContents(),['10.764 ft²','Some elements were missing']);
  assert.deepEqual(await page.evaluate(()=>window.rawArea.rows),[[1,2.75],[0,0],[null,'']]);
  await page.evaluate(()=>window.ArchHubAPI.setSetting('Projects.Area','m²'));
  await preview.getByRole('cell',{name:'1.000 m²',exact:true}).waitFor();
 }finally{await browser.close();}
});

test('register field previews apply project formats only to declared angles and civil dates',async()=>{
 const browser=await chromium.launch({headless:true,executablePath:executable()});
 try{
  const page=await browser.newPage({timezoneId:'America/Los_Angeles'});
  await mount(page,{name:'Reviewer'},{settings:[{id:'Projects.Angle precision',value:2},{id:'Projects.Dates',value:'MM/DD/YYYY'}]});
  const xy=require('./studio_xyflow.cjs');
  await page.addScriptTag({content:xy.script()});
  await page.addStyleTag({content:xy.css()});
  await page.addScriptTag({path:path.join(studio,'compiled/react-resizable-panels.js')});
  await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,'ds_screens.jsx'),'utf8'),{loader:'jsx'}).code});
  await page.evaluate(()=>{
   const defs=[{id:'turn',name:'Turn',type:'number',unit:'rad'},{id:'issued',name:'Issued',type:'date'},{id:'key',name:'Key',type:'text'}];
   const cells={turn:Math.PI/2,issued:'2024-02-29',key:'2024-02-29'};
   const base={kind:'Node',params:{},inputs:[],outputs:[],x:0,y:0};
   const graph={id:'register',name:'Register',wires:[],nodes:[
    {...base,id:'table',title:'Register',type:'data.dataset',dataset:{fields:defs,records:[{cells}]}},
    ...defs.map((f,i)=>({...base,id:f.id,title:f.name,x:380,y:120*i,type:'data.field',column:{dataset:'Register',field:f.id,label:f.type}}))]};
   window.fixture={...window.fixture,graph,catalogue:[],approvals:[],messages:[],workspacePolicies:{}};
   const stage=document.body.appendChild(document.createElement('div'));
   stage.style.cssText='width:1000px;height:700px';
   window.ReactDOM.createRoot(stage).render(window.React.createElement(window.UI.Ctx.Provider,{value:{act:f=>f(),show(){},go(){}}},window.React.createElement(window.UI.Canvas,{embedded:true,preview:graph})));
  });
  for(const [key,expected] of [['turn','1.57'],['issued','02/29/2024'],['key','2024-02-29']]){
   const out=page.locator('[data-column-of="Register.'+key+'"]');
   await out.waitFor({timeout:4000});
   assert.equal((await out.textContent()).trim(),expected+'  ›');
  }
 }finally{await browser.close();}
});
