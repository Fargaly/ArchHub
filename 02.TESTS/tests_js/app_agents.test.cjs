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
test('Workshop shows native working sessions even when OAuth state is unknown',()=>{
 const c=context({agents:[{id:'codex:s',runtime:'codex',name:'Codex',signedIn:null,presence:'working',status_text:'Working',task:'Native task',sessions:[{id:'s'}]}]});
 load(c,'ds_workshop3.jsx');assert.match(text(c.UI.Workshop()),/Codex/);
});
test('A message without a model does not claim an independent check',()=>{
 const c=context();load(c,'ds_workshop3.jsx');
 assert.doesNotMatch(text(c.UI.Messages({task:{messages:[{id:'m',who:'Codex',text:'stored'}]}})),/Checks the result/);
});
test('Meetings renders missing calendar and participants without invented defaults',()=>{
 const c=context();load(c,'meetings.jsx');
 const tree=c.UI.Meetings();
 const calendar=nodes(tree).find(n=>n.props?.['aria-label']==='Meeting from calendar');
 assert.equal(calendar.props.value,'');
 assert.doesNotMatch(text(tree),/Mona|fire door|site plan/);
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
test('Team meeting task uses the reviewed meeting action owner, rather than sending an unowned duplicate',async()=>{
 const c=context({meeting:{title:'Real meeting',actions:['A real decision'],actionOwners:{0:'Owner'},actionTasks:{}}}),calls=[];
 c.UI.api.createMeetingTask=async i=>{calls.push(i);return {id:'existing-task'};};
 load(c,'ds_colleagues.jsx');const tree=c.UI.Colleagues();
 assert.doesNotMatch(text(tree),/fire door|revised site plan/);
 await nodes(tree).find(n=>text(n)==='Make task').props.onClick();assert.deepEqual(calls,[0]);
});

test('The company directory is never presented as meeting attendance',()=>{
 const c=context({people:[{id:'employee',name:'Employee not in meeting'}]});load(c,'meetings.jsx');
 assert.doesNotMatch(text(c.UI.Meetings()),/Employee not in meeting/);
});

test('Native sessions button calls only discovery, without sending into a session',async()=>{
 const c=context();let calls=0;c.UI.api.listAgentSessions=async()=>{calls++;return {sessions:[],adapters:{},truncated:false};};
 load(c,'agent-states.jsx');const tree=c.UI.AgentChannel({id:'codex'});
 await nodes(tree).find(n=>text(n)==='Read native sessions').props.onClick();assert.equal(calls,1);
});

function updateSettings(update){
 const c=context({pages:['Updates & About'],settings:[],capabilities:[],workspaces:[],update});
 c.app={act:async fn=>fn(),show:()=>{},go:()=>{}};c.UI.useApp=()=>c.app;
 load(c,'ds_settings3.jsx');return {...c,render:()=>c.UI.Settings({page:'Updates & About',full:true})};
}

test('Updates never claims up to date without a successful lifecycle read',()=>{
 for(const update of [{},{state:'failed',detail:'Feed unreachable'},{state:'checking',detail:'Checking'}]){
  const c=updateSettings(update),tree=c.render();
  assert.doesNotMatch(text(tree),/Up to date/);
  assert.ok(nodes(tree).find(n=>text(n)==='Check for updates'));
 }
 const c=updateSettings({state:'idle',detail:'Up to date',installed:'running-build'});
 assert.match(text(c.render()),/Up to date/);
});

test('Updates check invokes the owner and a ready build opens the existing update review',async()=>{
 const c=updateSettings({state:'ready',available:true,installed:'running-build',next:'new-build'});
 let checks=0;const opened=[];c.UI.api.checkForUpdates=async()=>{checks++;};
 c.app.show=kind=>opened.push(kind);
 await nodes(c.render()).find(n=>text(n)==='Check for updates').props.onClick();
 await nodes(c.render()).find(n=>text(n)==='Update').props.onClick();
 assert.equal(checks,1);assert.deepEqual(opened,['Update']);
});

test('Updates retains the installed-build confirmation until the owner acknowledges it',async()=>{
 const c=updateSettings({state:'idle',installed:'new-build',updatedFrom:'old-build',updatedTo:'new-build'});
 let acknowledgements=0;c.UI.api.acknowledgeUpdate=async()=>{acknowledgements++;};
 const tree=c.render();assert.match(text(tree),/old-build.*new-build/);
 await nodes(tree).find(n=>text(n)==='Dismiss update confirmation').props.onClick();
 assert.equal(acknowledgements,1);
});
