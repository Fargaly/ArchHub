const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..','..');
const babelContext={};vm.createContext(babelContext);
vm.runInContext(fs.readFileSync(path.join(root,'01.APP/nodelang/studio/vendor/babel.js'),'utf8'),babelContext);
const Babel=babelContext.Babel;
function context(data={}){
 const calls=[];
 const component=type=>props=>({type,props});
 const UI={A:{accent:'blue',ok:'green',inkSoft:'gray'},D:{dot:()=>null,Toggle:component('toggle')},
 api:{},useData:()=>({providers:[],tasks:[],people:[],profile:{},brain:[],graph:{},meeting:{actions:[],transcript:[],actionOwners:{},actionTasks:{}},meetingCalendar:[],...data}),
 useApp:()=>({act:async fn=>fn(),show:()=>{},go:()=>{},setTask:()=>{}}),
 Btn:component('button'),Card:component('section'),Chip:component('span'),Av:component('avatar'),
 Composer:component('composer'),ApprovalCard:component('approval'),Empty:component('empty'),Heading:component('heading')};
 const React={createElement:(type,props,...children)=>({type,props:{...props,children}}),
 useState:v=>[typeof v==='function'?v():v,()=>{}],useRef:v=>({current:v}),useEffect:()=>{}};
 const window={UI,AHIcon:component('icon'),ArchHubAPI:{getSnapshot:()=>UI.useData()}};
 // WIRE-agents: model the API boundary; the real command registry is exercised in wire_agents.test.cjs.
 window.ArchHubAPI.executeAction=(id,app,...args)=>id.startsWith('ui.')?app[id.slice(3)](...args):app.act(()=>UI.api[id](...args));
 UI.useWireSocial=()=>({status:'loaded',message:'',act:async fn=>fn(),call:async fn=>fn(),retry:()=>{}});
 UI.useRegisteredActions=(actions,handlers)=>({actionState:{status:'empty'},runAction:(id,...args)=>handlers[actions[id]](...args),retryAction:()=>{}});
 UI.RegisteredActionStatus=()=>null;
 UI.useAction=()=>({state:'empty',result:null,error:'',run:async fn=>fn(),retry:()=>{}});
 UI.bindActions=(actions,handlers)=>(id,...args)=>handlers[actions[id]](...args);
 UI.ActionStatus=()=>null;
 const c={window,React,setInterval,clearInterval,console};vm.createContext(c);
 // Task rows read their reason (interrupted, limit reached) from its one owner, ui.jsx. ui.jsx replaces window.UI,
 // so take its real export and put this fixture's UI back.
 Object.assign(window,{AH:{},AH_DS:{},registerActions:()=>{}});React.createContext=()=>({});
 vm.runInContext(Babel.transform(fs.readFileSync(path.join(root,'01.APP/nodelang/studio/ui.jsx'),'utf8'),{presets:['react']}).code,c);
 UI.taskRowReason=window.UI.taskRowReason;UI.productLabel=window.UI.productLabel;window.UI=UI;
 return {UI,c,calls};
}
function load(ctx,name){vm.runInContext(Babel.transform(fs.readFileSync(path.join(root,'01.APP/nodelang/studio',name),'utf8'),{presets:['react']}).code,ctx.c);}
function nodes(tree){if(!tree||typeof tree!=='object')return [];return [tree,...(tree.props?.children||[]).flat(Infinity).flatMap(nodes)];}
function text(tree){if(Array.isArray(tree))return tree.map(text).join(' ');if(tree==null||typeof tree==='boolean')return '';if(typeof tree!=='object')return String(tree);return text(tree.props?.children||[]);}

test('Workshop progress comes from completed steps, with an accessible count',()=>{
 const c=context();load(c,'ds_workshop3.jsx');
 const task={id:'t',owner:'codex',title:'Build',status:'WIP',steps:[{status:'Done'},{status:'Next'},{status:'Next'},{status:'Next'}]};
 const tree=c.UI.Task({task,on:false,select:()=>{}}),bar=nodes(tree).find(n=>n.props?.role==='progressbar');
 assert.ok(bar);assert.equal(bar.props['aria-valuenow'],1);assert.equal(bar.props['aria-valuemax'],4);
});
test('An active task without reported steps has no invented progress percentage',()=>{
 const c=context();load(c,'ds_workshop3.jsx');
 const tree=c.UI.Task({task:{id:'t',title:'Build',status:'WIP'},select:()=>{}});
 assert.equal(nodes(tree).some(n=>n.props?.role==='progressbar'),false);
 assert.equal(nodes(tree).some(n=>n.props?.style?.width==='50%'),false);
});
test('The People and agents dock panel shows native working sessions even when OAuth state is unknown',()=>{
 const c=context({agents:[{id:'codex:s',runtime:'codex',name:'Codex',signedIn:null,presence:'working',status_text:'Working',task:'Native task',sessions:[{id:'s'}]}]});
 c.c.window.ReactDOM={createPortal:()=>null};
 load(c,'ds_workshop3.jsx');load(c,'dock.jsx');assert.match(text(c.UI.DockPeople({})),/Codex/);
});
test('A message without a model does not claim an independent check',()=>{
 const c=context();load(c,'ds_workshop3.jsx');
 assert.doesNotMatch(text(c.UI.Messages({task:{messages:[{id:'m',who:'Codex',text:'stored'}]}})),/Checks the result/);
});
test('Agent channel is an exported face backed by the shared API',()=>{
 const c=context();load(c,'agent-states.jsx');assert.equal(typeof c.UI.AgentChannel,'function');
 const tree=c.UI.AgentChannel({id:'codex'});
 assert.ok(nodes(tree).find(n=>n.props?.onClick));
});


test('Connect channel calls the backend for this exact agent, without a browser environment',async()=>{
 const c=context(),calls=[];c.UI.api.installAgentChannel=async(...args)=>{calls.push(args);return {state:'registered',activationPending:true};};
 load(c,'agent-states.jsx');const tree=c.UI.AgentChannel({id:'codex'});
 await nodes(tree).find(n=>text(n)==='Connect channel').props.onClick();
 assert.deepEqual(calls,[['codex']]);
});
test('Desktop state reads the native frame owner and never starts another companion',async()=>{
 const c=context();let calls=0;c.UI.api.getDesktopCompanion=async()=>{calls++;return {status:'expired'};};
 load(c,'desktop.jsx');const tree=c.UI.DesktopScene();
 await nodes(tree).find(n=>text(n)==='Read companion state').props.onClick();assert.equal(calls,1);
});
test('Native sessions button calls only discovery, without sending into a session',async()=>{
 const c=context();let calls=0;c.UI.api.listAgentSessions=async()=>{calls++;return {sessions:[],adapters:{},truncated:false};};
 load(c,'agent-states.jsx');const tree=c.UI.AgentChannel({id:'codex'});
 await nodes(tree).find(n=>text(n)==='Read native sessions').props.onClick();assert.equal(calls,1);
});

test('Connect dialog tools render with session catalogue rows, which carry no nodes',()=>{
 // Catalogue rows are {id,title,path,kind} (session_files catalogue); the open canvas holds the nodes.
 const graphs=[{id:'a.archhub',title:'A',path:'a.archhub',kind:'agent-session'}];
 const label=nodes=>{const c=context({graphs,graph:{nodes:[...nodes,{id:'other',params:{}},{id:'bare'}]}});load(c,'agent-states.jsx');
  return text(c.UI.ConnectorTools({connection:{id:'whatsapp',name:'WhatsApp Business',connected:false}}));};
 const uses=n=>Array.from({length:n},(_,i)=>({id:'n'+i,params:i%2?{source:'WhatsApp Business'}:{host:'WhatsApp Business'}}));
 assert.match(label(uses(0)),/Not used on this canvas/);
 assert.match(label(uses(1)),/Used by 1 node on this canvas/);
 assert.match(label(uses(3)),/Used by 3 nodes on this canvas/);
});
