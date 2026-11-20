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
  window.fixture={profile,settings:[],hosts:[],agents:[],providers:[],workspaces:[{id:'example',name:'Example workspace',folder:'C:\\Example',path:'C:\\Example',available:true}],activeWorkspace:'example',workspaceHealth:{state:'ready'},graph:{workspaceIds:[]},connections:[],capabilities:[],pages:['Account','Appearance','Workshop','Privacy'],settingsScope:'User',sessionsFolder:'Sessions',runtimeParameters:{},...extra};
  window.writes=[];const listeners=new Set();
  window.ArchHubAPI={subscribe:f=>{listeners.add(f);return()=>listeners.delete(f);},getSnapshot:()=>window.fixture,supportsAction:()=>true,
   refreshRouter:async()=>({default_model:'free',models:[],fallback_models:[],requests:[],free_first:true}),readHostAvailability:async()=>[],listAgentsWorking:async()=>[],refreshSettingsControls:async()=>({}),readSessionsFolder:async()=> 'Sessions',
   setSetting:async(id,value)=>{window.writes.push({id,value});window.fixture={...window.fixture,settings:window.fixture.settings.map(r=>r.id===id?{...r,value}:r)};listeners.forEach(f=>f());return {ok:true};},
  };
  window.ArchHubAPI.resetSetting=async id=>window.ArchHubAPI.setSetting(id,window.fixture.settings.find(row=>row.id===id).default);
  window.ArchHubAPI.setSettingsScope=async scope=>{window.writes.push({scope});return {ok:true};};
  window.ArchHubAPI.exposeSettingsPage=async page=>{window.writes.push({page});return {ok:true};};
 },{profile,extra});
 for(const name of ['tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx','ds_settings3.jsx']){
  const file=path.join(studio,name);
  await page.addScriptTag({content:transformSync(fs.readFileSync(file,'utf8'),{loader:'jsx'}).code});
 }
 await page.evaluate(()=>{
  for(const name of ['MemoryRules','Automations','HostSkills','SystemGraph','Providers'])window.UI[name]=()=>React.createElement('p',null,name+' owner');
  function Harness(){const [page,setPage]=React.useState('Account');const [advanced,setAdvanced]=React.useState(false);
   const u={go:route=>{if(route.startsWith('settings/'))setPage(route.slice(9));},act:async fn=>fn(),show:()=>{},settingsOrigin:'home',advanced,setAdvanced};
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
    {id:'Appearance.Theme',page:'Appearance',group:'Theme and colour',label:'Theme',type:'enum',options:['Dark','Light','System'],value:'Dark',default:'Dark'},
    {id:'Appearance.Text scale',page:'Appearance',group:'Size and density',label:'Text scale',type:'number',value:110,default:100},
    {id:'Workshop.Keep messages',page:'Workshop',group:'Messages',label:'Keep messages',description:'Conversation retention',type:'number',value:20,default:10},
    {id:'Privacy.Review',page:'Privacy',group:'Privacy',label:'Review before sharing',type:'boolean',value:true,default:true},
    {id:'Advanced.Limit',page:'Advanced',group:'Budgets',label:'Call limit',type:'number',value:30,default:20,advanced:true},
    {id:'Appearance.Node radius',page:'Appearance',group:'Canvas',label:'Node radius',type:'number',value:6,default:6,advanced:true},
   ]});
   await page.locator('.sheet-columns:not([hidden])').waitFor();
   const nav=page.getByRole('navigation',{name:'Settings categories'});
   const expected=['Account','Look','Projects','Agents','Connections','You','Workshop','Library & Mods','Automations','System','Updates & About'];
   for(const name of expected) assert.equal(await nav.getByRole('button',{name,exact:true}).count(),1,'missing design area '+name);
   await nav.getByRole('button',{name:'Workshop',exact:true}).click();
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
   await nav.getByRole('button',{name:'Look',exact:true}).click();
   await page.getByLabel('Theme',{exact:true}).selectOption('Light');
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{id:'Appearance.Theme',value:'Light'});
   await page.getByRole('button',{name:'Reset Theme',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{id:'Appearance.Theme',value:'Dark'});
   await page.getByRole('navigation',{name:'On this page'}).getByRole('button').first().click();
   await page.getByRole('button',{name:'Hide advanced',exact:true}).click();
   assert.equal(await page.locator('[data-setting="Appearance.Node radius"]').count(),0);
   await page.getByRole('button',{name:'Show advanced',exact:true}).click();
   await page.getByLabel('Node radius',{exact:true}).waitFor();
   await page.getByRole('button',{name:'Put on Canvas',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>window.writes.at(-1)),{page:'Appearance'});
   assert.equal(await page.getByLabel('Settings scope',{exact:true}).locator('option[value=Workspace]').isDisabled(),true);
   await nav.getByRole('button',{name:'Projects',exact:true}).click();
   await page.getByRole('heading',{name:'Project folders',exact:true}).waitFor();
   await page.getByRole('heading',{name:'Example workspace',exact:true}).waitFor();
   await page.getByRole('group',{name:'Units and precision. Coming soon: not built yet',exact:true}).waitFor();
   assert.deepEqual(errors,[]);
   console.log(JSON.stringify({width,areas:expected.length,wordSearch:true,keyboardJump:true,globalChanged:true,errors}));
   await page.close();
  }
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
 assert.ok(html.includes('Custom keyboard shortcuts'),'unimplemented keyboard settings are visible');
 data.graph={workspaceIds:[]};
 const empty=renderToStaticMarkup(React.createElement(window.UI.Settings,{page:'Appearance'}));
 assert.ok(empty.includes('Open a workflow to preview its real nodes here.'));
 assert.equal(calls.length,1,'an unloaded workflow does not mount a Canvas');
});
