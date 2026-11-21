const test=require('node:test'), assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..','..');const read=f=>fs.readFileSync(path.join(root,'01.APP/nodelang/studio',f),'utf8');
const babelContext={};vm.runInNewContext(read('vendor/babel.js'),babelContext);const Babel=babelContext.Babel;
const compiled=new Map();const compile=f=>{if(!compiled.has(f))compiled.set(f,Babel.transform(read(f),{presets:['react'],sourceType:'script'}).code);return compiled.get(f);};
function harness(){
 let slots=[],cursor=0;const calls=[];
 const state={profile:{name:'Test User',email:'test@example.test',signedIn:false,firm:'Test Office',plan:'Personal'},sync:'Signed out',
 firms:[{id:'office-1',name:'First office'},{id:'office-2',name:'Second office'}],activeFirm:'office-1',officeInvitations:[{id:'invitation',office:'Office',email:'test@example.test',status:'Pending',role:'Member'}],
 billing:{status:'solo',requestedPlan:'Personal',cycle:'Monthly',checkout:{plan:'Personal',cycle:'Monthly',status:'Awaiting provider'},invoices:[{id:'invoice',number:'1',plan:'Personal',amount:5,status:'Paid'}],limitReached:true},
 dependencies:[{id:'codex',name:'Codex',group:'Agents',version:'1',availableVersion:'2',state:'Update ready',diskMb:2,ramMb:3,description:'Managed CLI',usedBy:['BABOOM'],logs:['Inventory read'],integrity:'npm inventory'},{id:'opencode',name:'OpenCode',group:'Agents',version:'',state:'Not installed',diskMb:0,ramMb:0,usedBy:[],logs:[]}],
 workspaces:[{id:'one',name:'First root',folder:'C:/FIRST'},{id:'two',name:'Second root',folder:'C:/SECOND'}],graph:{workspaceIds:[]},files:[],backups:[{id:'copy',name:'Cloud copy'}],
 people:[{id:'person',name:'Person',accessRole:'Member'}],devices:[{id:'device',name:'Office device',status:'Online'}],activeDevice:'device',connections:[{id:'revit',name:'Revit',connected:false},{id:'notion',name:'Notion',connected:true}],
 secrets:[],pages:['Account','Connections','Brain','Advanced'],settings:[],capabilities:[],providers:[],templates:[],tasks:[],brain:[],receipts:[],update:{state:'idle',detail:'Up to date'}};
 const api=new Proxy({subscribe(){},getSnapshot:()=>state,getUsageSummary:()=>({'Remaining messages':7}),getCapabilityParameters:()=>[],getCapabilityState:()=>null},{get:(target,key)=>target[key]||((...args)=>{calls.push(['api',key,...args]);return Promise.resolve({ok:true,message:'Owner confirmed'});})});
 const app={advanced:false,setAdvanced(){},act:fn=>fn(),go:r=>calls.push(['go',r]),show:(...args)=>calls.push(['show',...args]),pickWorkspace:()=>calls.push(['pickWorkspace']),confirm:(...args)=>calls.push(['confirm',...args]),download:(...args)=>calls.push(['download',...args]),schedule:id=>calls.push(['schedule',id]),setTask:id=>calls.push(['setTask',id])};
 const React={Fragment:'fragment',createContext:()=>({}),useContext:()=>app,useSyncExternalStore:()=>state,
 useState(initial){const i=cursor++;if(!(i in slots))slots[i]=initial;return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},
 useRef(initial){const i=cursor++;if(!(i in slots))slots[i]={current:initial};return slots[i];},useEffect(){},createElement:(type,props,...children)=>({type,props:props||{},children})};
 const window={ArchHubAPI:api,AH:{},AH_DS:{Toggle:'Toggle'},AHIcon:'Icon'};
 const context=vm.createContext({window,React,document:{querySelector:()=>({scrollIntoView(){}})},requestAnimationFrame:fn=>fn(),setTimeout,clearTimeout,console});
 React.forwardRef=render=>render;
 const components=window.AH_DS;vm.runInContext(compile('ds/index.jsx'),context);window.AH_DS=components;
 vm.runInContext(compile('ui.jsx'),context);
 for(const f of ['answer-widgets.jsx','ds_settings3.jsx','account-tools.jsx','access.jsx','ds_firstrun.jsx','dependencies.jsx'])vm.runInContext(compile(f),context);
 return {state,api,app,calls,window,reset(){slots=[];cursor=0;},render(name,props={}){cursor=0;return window.UI[name](props);},setSlot(i,v){slots[i]=v;}};
}
function elements(tree){if(!tree||typeof tree!=='object')return [];if(Array.isArray(tree))return tree.flatMap(elements);return [tree,...(tree.children||[]).flatMap(elements)];}
function label(tree){if(typeof tree==='string'||typeof tree==='number')return String(tree);if(!tree)return '';if(Array.isArray(tree))return tree.map(label).join('');return (tree.children||[]).map(label).join('');}
function button(h,tree,text){const found=elements(tree).find(e=>(e.type==='button'||e.type===h.window.UI.Btn)&&(label(e)===text||e.props['aria-label']===text));assert.ok(found,'rendered control '+text);return found;}

test('registered callbacks preserve the selected row, office and package identities',async()=>{
 const h=harness();let tree=h.render('WorkspaceRows');const opens=elements(tree).filter(e=>e.type===h.window.UI.Btn&&label(e)==='Open');await opens[1].props.onClick({});assert.deepEqual(h.calls.slice(-2),[['api','selectWorkspace','two'],['go','home']]);
 h.reset();tree=h.render('AccountIdentity');await button(h,tree,'Accept invitation').props.onClick({});assert.deepEqual(h.calls.at(-1),['api','acceptOfficeInvitation','invitation']);
 h.reset();tree=h.render('Dependencies');await button(h,tree,'Install').props.onClick({});assert.deepEqual(h.calls.at(-1),['api','manageDependency','opencode','Install']);
});

test('connection groups filter rendered rows and a connection action uses its actual ID',async()=>{
 const h=harness();let tree=h.render('Connections');await button(h,tree,'Programs').props.onClick({});tree=h.render('Connections');assert.ok(label(tree).includes('Revit'));assert.ok(!label(tree).includes('Notion'));
 await button(h,tree,'Connect').props.onClick({});assert.deepEqual(JSON.parse(JSON.stringify(h.calls.at(-1))),['show','Connect',{id:'revit'}]);
});

test('a rejected button shows a retry and never changes authoritative dependency state',async()=>{
 const h=harness();h.api.manageDependency=()=>Promise.reject(Error('Package signature refused. Check publisher and retry.'));
 const before=JSON.stringify(h.state.dependencies);let tree=h.render('Dependencies');await button(h,tree,'Install').props.onClick({});tree=h.render('Dependencies');
 const status=elements(tree).find(e=>e.type===h.window.UI.RegisteredActionStatus);assert.equal(status.props.state.status,'error');assert.match(status.props.state.message,/signature refused/);assert.equal(JSON.stringify(h.state.dependencies),before);
 h.api.manageDependency=()=>Promise.resolve({ok:true,message:'OpenCode: Ready'});await status.props.retry();tree=h.render('Dependencies');assert.equal(elements(tree).find(e=>e.type===h.window.UI.RegisteredActionStatus).props.state.status,'loaded');
});

test('first run retains all six steps and refuses a finished-result claim before DONE',async()=>{
 const h=harness();h.setSlot(0,4);h.setSlot(1,'task-real');h.state.tasks=[{id:'task-real',status:'WIP'}];let tree=h.render('FirstRun');await button(h,tree,'Next').props.onClick({});tree=h.render('FirstRun');const status=elements(tree).find(e=>e.type===h.window.UI.RegisteredActionStatus);assert.equal(status.props.state.status,'error');assert.match(status.props.state.message,/checked result/);
 h.state.tasks[0].status='DONE';await status.props.retry();tree=h.render('FirstRun');assert.ok(label(tree).includes('Your change is checked'));await button(h,tree,'Run it every morning').props.onClick({});assert.deepEqual(h.calls.at(-1),['schedule','task-real']);
});

test('approved account, storage, plan and billing controls remain present',()=>{
 const h=harness();for(const [component,controls]of [['Account',['Sync','Sign in with your browser','My profile','My secrets','My files']],['Storage',['Archive old activity','Back up now','Roll back']],['Access',['Settings']],['BillingAccount',['Review plan','Refresh payment confirmation','Cancel checkout','Download invoice','Refresh billing','Plan & access']]]){
 h.reset();const tree=h.render(component);for(const control of controls)button(h,tree,control);
 }
});
async function apiHarness(answer, account={signed_in:true,user_id:'fixture-account',email:'fixture@example.test'}, extra={}){
 const calls=[],window={structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{home_load_ms:60000,token:'transport-only',csrf:'csrf'},crypto:require('node:crypto'),AH:{},addEventListener(){},dispatchEvent(){},open(){},requestAnimationFrame:fn=>setTimeout(fn,0),cancelAnimationFrame:clearTimeout};
 const file=extra.file||{format:'archhub',version:1,id:'fixture-session',title:'Fixture',properties:{},nodes:[],wires:[],groups:[],notes:[]};
 const filePath='C:/fixture/workflow.archhub';
 const context=vm.createContext({window,setTimeout,clearTimeout,document:{hidden:true,addEventListener(){}},URL,URLSearchParams,AbortSignal:globalThis.AbortSignal,CustomEvent:class {},sessionStorage:{getItem:()=>null},
 fetch:async(url,options)=>{
  const body=options.body&&JSON.parse(options.body);calls.push([url,body]);
  let data={ok:true};
  if(url==='/api/universal/desktop-access')data=account.signed_in
   ?{ok:true,admitted:true,state:'admitted',subject:account.user_id,email:account.email}
   :{ok:true,admitted:false,state:'signed_out'};
  if(url==='/api/commands')data={commands:[]};
  if(url==='/api/session-files'){
   if(body.action==='param-op'&&body.op==='set'){
    const [id,key,value]=body.args;
    const document=globalThis.structuredClone(body.document);
    document.nodes.find(node=>node.id===id).params[key]=value;
    await extra.paramResponse?.();
    data={document,changed:[id]};
   }else data=body.action==='catalogue'?{items:[],sessions:[]}:{document:file,path:filePath};
  }
  if(url==='/api/universal/workspace-roots')data=body?.action==='browse'?{ok:true,path:(await extra.path)||''}:{ok:true,roots:[]};
  if(url==='/api/universal/cloud-session')data=account;
  if(url==='/api/universal/settings-action')data={ok:true,result:await answer(body)};
  return {ok:true,status:200,json:async()=>data};
 }});
 vm.runInContext(read('studio-authority.js'),context);
 vm.runInContext(read('api.js'),context);
 let timer;
 try{await Promise.race([window.ArchHubAPI.ready,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Desktop fixture did not become ready')),3000);})]);}
 finally{clearTimeout(timer);}
 return {api:window.ArchHubAPI,calls};
}

test('profile adapter posts the exact owner command and cannot overwrite account or transport identity',async()=>{
 const h=await apiHarness(()=>({profile:{name:'Saved User',firm:'Saved Firm',id:'forged-account',signedIn:true,isFounder:true}}));
 await h.api.syncAccount();
 await h.api.updateProfile({name:'Saved User',firm:'Saved Firm'});
 const p=h.api.getSnapshot().profile;assert.equal(p.name,'Saved User');assert.equal(p.signedIn,true);assert.equal(p.id,'fixture-account');assert.equal(p.isFounder,false);
 assert.deepEqual(JSON.parse(JSON.stringify(h.calls.find(([url,body])=>url==='/api/universal/settings-action'&&body.function==='updateProfile'))),['/api/universal/settings-action',{function:'updateProfile',args:[{name:'Saved User',firm:'Saved Firm'}],context:{session:'fixture-session',surface:'home'}}]);
});

test('rejected profile changes preserve the confirmed snapshot',async()=>{
 const h=await apiHarness(()=>({ok:false,error:'Sign in again and retry.'}));const before=JSON.stringify(h.api.getSnapshot().profile);
 await assert.rejects(()=>h.api.updateProfile({name:'Draft'}),/Sign in again/);assert.equal(JSON.stringify(h.api.getSnapshot().profile),before);
});

test('billing refresh only publishes a real owner response',async()=>{
 const h=await apiHarness(body=>({billing:{status:'studio',requestedPlan:'Office',cycle:'Annual',invoices:[],remainingMessages:42}}));
 await h.api.refreshBilling();assert.equal(h.api.getSnapshot().billing.status,'studio');assert.equal(h.api.getUsageSummary()['Remaining messages'],42);
 assert.deepEqual(JSON.parse(JSON.stringify(h.calls.find(([url,body])=>url==='/api/universal/settings-action'&&body.function==='refreshBilling'))),['/api/universal/settings-action',{function:'refreshBilling',args:[],context:{session:'fixture-session',surface:'home'}}]);
});

test('account refresh preserves saved display fields and clears them on account change',async()=>{
 let saved={name:'Saved display',firm:'First firm',plan:'Personal'};
 const account={signed_in:true,email:'first@example.test',user_id:'first'};
 const h=await apiHarness(()=>({profile:{...saved},billing:{status:'solo',invoices:[]},people:[],firms:[]}),account);
 await h.api.syncAccount();await h.api.updateProfile({name:'Saved display'});await h.api.syncAccount();
 assert.equal(h.api.getSnapshot().profile.name,'Saved display');assert.equal(h.api.getSnapshot().profile.firm,'First firm');
 saved={name:'Second display',firm:'Second firm',plan:'Personal'};Object.assign(account,{email:'second@example.test',user_id:'second'});await h.api.refreshDesktopAccess(true);await h.api.syncAccount();
 assert.equal(h.api.getSnapshot().profile.id,'second');assert.equal(h.api.getSnapshot().profile.name,'Second display');assert.equal(h.api.getSnapshot().profile.firm,'Second firm');
 Object.assign(account,{signed_in:false,email:''});await h.api.refreshDesktopAccess(true);assert.equal(h.api.getSnapshot().desktopAccess.admitted,false);assert.equal(h.api.getSnapshot().profile.firm,'');assert.equal(h.api.getSnapshot().profile.id,'');
});

test('Canvas discards a native folder choice when another document opens with the same node ID',async()=>{
 const file={format:'archhub',version:1,id:'first',title:'First',properties:{},nodes:[{id:'session',type:'thing.session',position:{x:0,y:0},params:{project_folder:''}}],wires:[],groups:[],notes:[]};
 let choose;
 const path=new Promise(resolve=>{choose=resolve;});
 const h=await apiHarness(()=>({}),undefined,{file,path});
 const pending=h.api.pickNodeParameter('session','project_folder','folder');
 await h.api.openSession('C:/fixture/other.archhub');
 choose('C:/Chosen');
 await assert.rejects(pending,/selected node changed/);
 assert.equal(file.nodes[0].params.project_folder,'');
 assert.equal(h.calls.some(([,body])=>body?.action==='param-op'),false);
});

for(const change of ['open','rename'])test('Canvas protects newer work after Browse returns: '+change,async()=>{
 const node={id:'shared',type:'thing.session',position:{x:0,y:0},params:{project_folder:'original'},paramDefs:[{id:'project_folder',name:'Project folder',type:'folder'}]};
 const file={format:'archhub',version:1,id:'first',title:'First',properties:{},nodes:[node],wires:[],groups:[],notes:[]};
 let release,started;
 const received=new Promise(resolve=>{started=resolve;});
 const paramResponse=()=>new Promise(resolve=>{release=resolve;started();});
 const h=await apiHarness(()=>({}),undefined,{file,path:'C:/Chosen',paramResponse});
 const pending=h.api.pickNodeParameter('shared','project_folder','folder');
 await received;
 if(change==='open'){file.id='second';await h.api.openSession('C:/fixture/second.archhub');}
 else await h.api.renameNode('shared','Newer name');
 release();
 await assert.rejects(pending,/document changed|canvas changed/);
 if(change==='open')assert.equal(h.api.getSessionDocument().id,'second');
 else assert.equal(h.api.getSessionDocument().nodes[0].title,'Newer name');
 assert.equal(h.api.getSessionDocument().nodes[0].params.project_folder,'original');
});

test('capability folder selection uses the full native path and the real property owner',async()=>{
 const node={id:'fixture-node',type:'thing.session',position:{x:0,y:0},params:{project_folder:'C:/OLD'},paramDefs:[{id:'project_folder',name:'Project folder',type:'folder',group:'Context',value:''}]};
 const file={format:'archhub',version:1,id:'fixture-session',title:'Fixture',properties:{},nodes:[node],wires:[],groups:[],notes:[]};
 const h=await apiHarness(()=>({}),undefined,{file,path:'C:/FULL/NATIVE/FOLDER'});
 const id=node.type;
 assert.equal(h.api.getCapabilityState(id).params.project_folder,'C:/OLD');
 assert.equal(h.api.getCapabilityParameters(id)[0].type,'path');
 await h.api.pickCapabilityFolder(id,'project_folder');
 const edit=h.calls.find(([url,body])=>url==='/api/session-files'&&body?.action==='param-op');
 assert.ok(edit,'the session file owner received the folder edit');
 assert.deepEqual(JSON.parse(JSON.stringify(edit[1].args)),[node.id,'project_folder','C:/FULL/NATIVE/FOLDER']);
 assert.equal(h.api.getCapabilityState(id).params.project_folder,'C:/FULL/NATIVE/FOLDER');
 file.nodes.push({...node,id:'second-node'});await h.api.openSession('C:/fixture/second.archhub');
 assert.throws(()=>h.api.setCapabilityParameter(id,'project_folder','C:/OTHER'),/exact instance/);
});
