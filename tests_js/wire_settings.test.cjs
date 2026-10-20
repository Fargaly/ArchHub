const test=require('node:test'), assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..');const read=f=>fs.readFileSync(path.join(root,'nodelang/studio',f),'utf8');
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
 pages:['Account','Connections','Brain','Advanced'],settings:[],capabilities:[],providers:[],tasks:[],brain:[],receipts:[],update:{state:'idle',detail:'Up to date'}};
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
 for(const f of ['ds_settings3.jsx','account-tools.jsx','access.jsx','ds_firstrun.jsx','dependencies.jsx'])vm.runInContext(compile(f),context);
 return {state,api,app,calls,window,reset(){slots=[];cursor=0;},render(name,props={}){cursor=0;return window.UI[name](props);},setSlot(i,v){slots[i]=v;}};
}
function elements(tree){if(!tree||typeof tree!=='object')return [];if(Array.isArray(tree))return tree.flatMap(elements);return [tree,...(tree.children||[]).flatMap(elements)];}
function label(tree){if(typeof tree==='string'||typeof tree==='number')return String(tree);if(!tree)return '';if(Array.isArray(tree))return tree.map(label).join('');return (tree.children||[]).map(label).join('');}
function button(h,tree,text){const found=elements(tree).find(e=>(e.type==='button'||e.type===h.window.UI.Btn)&&(label(e)===text||e.props['aria-label']===text));assert.ok(found,'rendered control '+text);return found;}

test('registered callbacks preserve the selected row, office and package identities',async()=>{
 const h=harness();let tree=h.render('WorkspaceRows');const opens=elements(tree).filter(e=>e.type===h.window.UI.Btn&&label(e)==='Open');await opens[1].props.onClick({});assert.deepEqual(h.calls.slice(-2),[['api','selectWorkspace','two'],['go','canvas']]);
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
async function apiHarness(answer, account={signed_in:false,email:''}, extra={}){
 const calls=[],window={structuredClone:globalThis.structuredClone,ARCHHUB_BOOT:{token:'transport-only',csrf:'csrf'},crypto:require('node:crypto'),AH:{},addEventListener(){},dispatchEvent(){},open(){}};
 window.ArchHubStudioAuthority={create:({get})=>({load:()=>get('/api/universal/canvas')})};
 const context=vm.createContext({window,document:{hidden:true,addEventListener(){}},URL,URLSearchParams,AbortSignal:globalThis.AbortSignal,CustomEvent:class {},sessionStorage:{getItem:()=>null},
 fetch:async(url,options)=>{const body=options.body&&JSON.parse(options.body);calls.push([url,body]);if(url==='/api/universal/set-property'&&extra.canvas)extra.canvas.nodes[0].params[0].value=body.value;return {ok:true,status:200,json:async()=>url==='/api/universal/canvas'?(extra.canvas||{root:'graph',nodes:[],wires:[]}):url==='/api/universal/workspace-roots'&&body?.action==='browse'?{ok:true,path:extra.path||''}:url==='/api/universal/cloud-session'?account:url==='/api/universal/settings-action'?{ok:true,result:await answer(body)}:{ok:true}};}});
 vm.runInContext(read('api.js'),context);await window.ArchHubAPI.ready;return {api:window.ArchHubAPI,calls};
}

test('profile adapter posts the exact owner command and cannot overwrite account or transport identity',async()=>{
 const h=await apiHarness(()=>({profile:{name:'Saved User',firm:'Saved Firm',id:'forged-account',signedIn:true,isFounder:true}}));
 await h.api.updateProfile({name:'Saved User',firm:'Saved Firm'});
 const p=h.api.getSnapshot().profile;assert.equal(p.name,'Saved User');assert.equal(p.signedIn,false);assert.equal(p.id,'');assert.equal(p.isFounder,false);
 assert.deepEqual(JSON.parse(JSON.stringify(h.calls.find(([url])=>url==='/api/universal/settings-action'))),['/api/universal/settings-action',{function:'updateProfile',args:[{name:'Saved User',firm:'Saved Firm'}]}]);
});

test('rejected profile changes preserve the confirmed snapshot',async()=>{
 const h=await apiHarness(()=>({ok:false,error:'Sign in again and retry.'}));const before=JSON.stringify(h.api.getSnapshot().profile);
 await assert.rejects(()=>h.api.updateProfile({name:'Draft'}),/Sign in again/);assert.equal(JSON.stringify(h.api.getSnapshot().profile),before);
});

test('billing refresh only publishes a real owner response',async()=>{
 const h=await apiHarness(body=>({billing:{status:'studio',requestedPlan:'Office',cycle:'Annual',invoices:[],remainingMessages:42}}));
 await h.api.refreshBilling();assert.equal(h.api.getSnapshot().billing.status,'studio');assert.equal(h.api.getUsageSummary()['Remaining messages'],42);
 assert.deepEqual(JSON.parse(JSON.stringify(h.calls.find(([url])=>url==='/api/universal/settings-action'))),['/api/universal/settings-action',{function:'refreshBilling',args:[]}]);
});

test('account refresh preserves saved display fields and clears them on account change',async()=>{
 let saved={name:'Saved display',firm:'First firm',plan:'Personal'};
 const account={signed_in:true,email:'first@example.test',user_id:'first'};
 const h=await apiHarness(()=>({profile:{...saved},billing:{status:'solo',invoices:[]},people:[],firms:[]}),account);
 await h.api.syncAccount();await h.api.updateProfile({name:'Saved display'});await h.api.syncAccount();
 assert.equal(h.api.getSnapshot().profile.name,'Saved display');assert.equal(h.api.getSnapshot().profile.firm,'First firm');
 saved={name:'Second display',firm:'Second firm',plan:'Personal'};Object.assign(account,{email:'second@example.test',user_id:'second'});await h.api.syncAccount();
 assert.equal(h.api.getSnapshot().profile.id,'second');assert.equal(h.api.getSnapshot().profile.name,'Second display');assert.equal(h.api.getSnapshot().profile.firm,'Second firm');
 Object.assign(account,{signed_in:false,email:''});await h.api.syncAccount();assert.equal(h.api.getSnapshot().profile.firm,'');assert.equal(h.api.getSnapshot().profile.id,'');
});

test('capability folder selection uses the full native path and the real property owner',async()=>{
 const canvas={root:'graph',catalog:[{id:'cap',name:'Tool',descriptor:{engine:'library.tool'}}],nodes:[{id:'node',engine:'library.tool',params:[{label:'folder',value:'C:/OLD',editor:'path',editable:true,relation:'folder-relation'}]}],wires:[]};
 const h=await apiHarness(()=>({}),undefined,{canvas,path:'C:/FULL/NATIVE/FOLDER'});
 assert.equal(h.api.getCapabilityState('cap').params.folder,'C:/OLD');assert.equal(h.api.getCapabilityParameters('cap')[0].type,'path');
 await h.api.pickCapabilityFolder('cap','folder');assert.equal(h.api.getCapabilityState('cap').params.folder,'C:/FULL/NATIVE/FOLDER');
 assert.deepEqual(JSON.parse(JSON.stringify(h.calls.find(([url])=>url==='/api/universal/set-property'))),['/api/universal/set-property',{relation:'folder-relation',value:'C:/FULL/NATIVE/FOLDER'}]);
 canvas.nodes.push({...canvas.nodes[0],id:'other-node'});await h.api.selectGraph('graph');
 assert.throws(()=>h.api.setCapabilityParameter('cap','folder','C:/OTHER'),/exact instance/);
});
