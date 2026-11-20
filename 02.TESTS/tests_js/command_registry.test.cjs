const {test,after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const profileRoot = path.join(root,'.cache/testiso-commandregistry');
fs.mkdirSync(profileRoot,{recursive:true});
const testProfile = fs.mkdtempSync(path.join(profileRoot,'js-profile-'));
for(const name of ['USERPROFILE','LOCALAPPDATA','APPDATA','HOME'])process.env[name]=testProfile;
process.env.ARCHHUB_TEST_STATE_DIR=path.join(testProfile,'state');
after(()=>{
  assert.ok(path.resolve(testProfile).startsWith(path.resolve(profileRoot)+path.sep));
  fs.rmSync(testProfile,{recursive:true,force:true});
});
const {execFileSync} = require('node:child_process');
const studio = path.join(root,'01.APP/nodelang/studio');
const registryPath = path.join(root,'.cache/testiso-commandregistry/commands.json');

function runtime(source, state, {more=false}={}) {
  const calls=[];
  const record=(owner,name)=>(...args)=>{calls.push([owner+'.'+String(name),...args.filter(x=>typeof x!=='function')]);return {ok:true};};
  const api=new Proxy({hasCopiedNodes:()=>state.copied!==false},{get:(target,key)=>target[key]||record('api',key)});
  const u=new Proxy({canvasTabs:{tabs:[{id:'task',kept:false},{id:'other'}]},task:'other',
    act:fn=>fn(),confirm:(title,fn)=>{calls.push(['u.confirm',title]);return fn();}},
    {get:(target,key)=>target[key]||record('u',key)});
  const actionState={run:fn=>fn()};
  const sandbox={window:{innerWidth:1400,innerHeight:900,UI:{api,useData:()=>state,useApp:()=>u,
    useAction:()=>actionState,bindActions:()=> (_id,fn,event)=>fn(event)},AHIcon:()=>null,
    ArchHubCommandRegistry:JSON.parse(fs.readFileSync(registryPath,'utf8'))},
    navigator:{clipboard:{writeText:record('clipboard','writeText')}},
    React:{useRef:()=>({current:null}),useState:()=>[more,record('state','setMore')],useLayoutEffect:()=>{},
      createElement:(type,props,...children)=>({type,props:props||{},children})}};
  sandbox.window.ArchHubRouteNames=Object.fromEntries(sandbox.window.ArchHubCommandRegistry.commands.filter(x=>x.action.route).map(x=>[x.action.route,x.label]));
  vm.createContext(sandbox);
  vm.runInContext(source,sandbox);
  return {sandbox,calls,api,u,actionState};
}
function buttons(tree,result=[]) {
  if(Array.isArray(tree))tree.forEach(child=>buttons(child,result));
  else if(tree&&typeof tree==='object'){
    if(tree.type==='button')result.push(tree);
    else buttons(tree.children,result);
  }
  return result;
}
const plain=value=>JSON.parse(JSON.stringify(value));

test('one reader supplies identical ordered menu and palette commands', () => {
  const sandbox = {window: {UI: {}}, React: {}};
  vm.createContext(sandbox);
  // The same compiled classic script the Studio loads; no source assertions.
  vm.runInContext(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/compiled/context-menus.js'), 'utf8'), sandbox);
  assert.equal(typeof sandbox.window.UI.commandsForContext, 'function');
  const registry = [{id:'copy',label:'Copy',group:'input',contexts:['node'],read_only:true,order:1},
    {id:'delete',label:'Delete',group:'input',contexts:['node'],read_only:false,order:2}];
  const bindings = {copy: {action:()=>1}, delete: {action:()=>2}};
  const read = sandbox.window.UI.commandsForContext;
  const menu = read(registry, 'node', {}, bindings);
  const palette = read(registry, 'node', {}, bindings);
  assert.deepEqual(menu.map(x=>x.id), palette.map(x=>x.id));
  assert.deepEqual(Array.from(read(registry, 'node', {readOnly:true}, bindings), x=>x.id), ['copy']);
});

test('a newly declared context reuses an existing command without another handler', async()=>{
  const state={graph:{nodes:[{id:'node',title:'Node',inputs:[],outputs:[],parameterSchema:[]}],wires:[]},tasks:[]};
  const rig=runtime(fs.readFileSync(path.join(studio,'compiled/context-menus.js'),'utf8'),state);
  const registry=rig.sandbox.window.ArchHubCommandRegistry;
  registry.commands.find(row=>row.id==='menu.properties').contexts.push('run');
  const rows=rig.sandbox.window.UI.contextCommandGroups({kind:'run',nodeId:'node',selected:['node'],close:()=>{}},state,rig.u,rig.actionState).flat();
  assert.deepEqual(plain(rows.map(row=>row.command.id)),['menu.properties']);
  await rows[0][3]();
  assert.deepEqual(plain(rig.calls),[['u.setSelectedNodeId','node']]);
});

test('node and group registrations contain exactly their reachable menu actions',()=>{
  const contexts={};
  for(const [context,kind,extra] of [['node','Node menu',{}],['group','Group menu',{children:['child']}],['group','Group menu',{frameMembers:['child']}]]){
    const state={graph:{nodes:[{id:'node',title:'Node',type:'script.python',inputs:[],outputs:[],parameterSchema:[],...extra}],wires:[]},tasks:[]};
    const rig=runtime(fs.readFileSync(path.join(studio,'compiled/context-menus.js'),'utf8'),state);
    const ids=new Set();
    for(const more of [false,true])for(const row of rig.sandbox.window.UI.contextCommandGroups({kind,nodeId:'node',selected:['node','child'],close:()=>{}},state,rig.u,rig.actionState,more).flat())ids.add(row.command.id);
    contexts[context]=[...new Set([...(contexts[context]||[]),...ids])].sort();
  }
  fs.writeFileSync(path.join(profileRoot,'menu-contexts.json'),JSON.stringify(contexts,null,2));
  const registry=JSON.parse(fs.readFileSync(registryPath,'utf8'));
  for(const [context,ids] of Object.entries(contexts)){
    assert.deepEqual(registry.commands.filter(row=>row.action.binding&&row.contexts.includes(context)).map(row=>row.id).sort(),ids,context);
  }
});

test('every existing menu item preserves label, order, state and action calls', async () => {
  const compiler={};vm.createContext(compiler);
  vm.runInContext(fs.readFileSync(path.join(studio,'vendor/babel.js'),'utf8'),compiler);
  const before=execFileSync('git',['show','60dc0f8e:01.APP/nodelang/studio/context-menus.jsx'],{cwd:root,encoding:'utf8'});
  const baseline=compiler.Babel.transform(before,{presets:['react','env']}).code;
  const current=fs.readFileSync(path.join(studio,'compiled/context-menus.js'),'utf8');
  const node={id:'node',title:'Node',type:'script.python',inputs:[],outputs:[{id:'out'}],parameterSchema:[{key:'value',editable:true}],
    frameMembers:null,children:null,frozen:false,bypassed:false,pinned:false};
  const fixtures=[...['Open tasks','Canvas attachments','Task message menu','Task tab menu','Wire menu','Port menu','Node menu',
    'Selection menu','Canvas menu','Tray','App menu'].map(kind=>({kind})),
    {kind:'Group menu',node:{children:['child']}},{kind:'Frame menu',node:{frameMembers:['child']}},
    {kind:'Node menu',more:true},{kind:'Node menu',node:{fixed:true}},{kind:'Node menu',node:{agentWork:{role:'session'}}},
    {kind:'Node menu',node:{frozen:true,bypassed:true,pinned:true}},
    {kind:'Port menu',node:{parameterSchema:[{key:'value',editable:true,promoted:true}]}},
    {kind:'Task message menu',pinned:true},{kind:'Canvas menu',copied:false},
    {kind:'Wire menu',wire:{enabled:false}},{kind:'Group menu',node:{children:['child'],collapsed:true}}];
  let mapped=0;
  for(const fixture of fixtures){
    const state={copied:fixture.copied,graph:{nodes:[{...node,...fixture.node}],wires:[{id:'wire',from:'node',fromPort:'param:value',to:'node',toPort:'in',...fixture.wire}]},
      tasks:[{id:'task',title:'Task',pinnedMessages:fixture.pinned?['message']:[]},{id:'third',title:'Third'},{id:'fourth',title:'Fourth'}]};
    const old=runtime(baseline,state,fixture),now=runtime(current,state,fixture);
    const props=rig=>({kind:rig===now&&fixture.kind==='Frame menu'?'Group menu':fixture.kind,nodeId:fixture.kind==='Task tab menu'?'task':'node',wireId:'wire',taskId:'task',
      message:{id:'message',text:'Node message'},port:'param:value',paramKey:'value',selected:['node','child'],
      close:()=>rig.calls.push(['close']),open:()=>rig.calls.push(['open']),
      canvas:new Proxy({point:{x:10,y:20}},{get:(target,key)=>target[key]||((...args)=>{rig.calls.push(['canvas.'+String(key),...args]);return {ok:true};})})});
    const labelOf=row=>row.children[1].children[0];
    const oldButtons=buttons(old.sandbox.window.UI.ContextMenu(props(old))).filter(row=>labelOf(row)!=='Frame');
    const newButtons=buttons(now.sandbox.window.UI.ContextMenu(props(now)));
    const shape=rows=>plain(rows.map(row=>({label:labelOf(row)==='Remove frame, keep nodes'?'Remove group, keep nodes':labelOf(row),key:row.children[2].children[0],
      disabled:!!row.props.disabled,danger:row.props.className==='danger'})));
    assert.deepEqual(shape(newButtons),shape(oldButtons),fixture.kind+JSON.stringify(fixture));
    for(let index=0;index<oldButtons.length;index++){
      if(oldButtons[index].props.disabled)continue;
      old.calls.length=now.calls.length=0;
      await oldButtons[index].props.onClick({});await newButtons[index].props.onClick({});
      // #372: Rerun runs the node again (runNode(id, true)); every other control keeps the old calls exactly.
      const label=shape(oldButtons)[index].label;
      const expected=plain(old.calls).map(call=>label==='Rerun'&&call[0]==='api.runNode'?[...call,true]:call);
      assert.deepEqual(plain(now.calls),expected,fixture.kind+' '+label);
      mapped++;
    }
    const contextProps=props(now);
    const menu=now.sandbox.window.UI.contextCommandGroups(contextProps,state,now.u,now.actionState);
    const palette=now.sandbox.window.UI.paletteCommands(state,now.u,now.api,{context:{...contextProps,id:contextProps.nodeId},actionState:now.actionState});
    assert.deepEqual(plain(palette.map(x=>x.id)),plain(menu.flat().map(x=>x.command.id)),fixture.kind+' palette parity');
    if(palette.length){
      const mode=palette[0].group;
      const filtered=now.sandbox.window.UI.paletteCommands(state,now.u,now.api,{context:{...contextProps,id:contextProps.nodeId},mode,actionState:now.actionState});
      assert.deepEqual(plain(filtered.map(x=>x.id)),plain(palette.filter(x=>x.group===mode).map(x=>x.id)),fixture.kind+' palette filter');
    }
  }
  console.log('MAPPED existing menu action cases: '+mapped+'; unmapped: 0');
});

// The doors that left the Library shelf: command id, label, command-list group, and the call the registered action makes.
const LIBRARY_DOORS=[['palette.mcp_tools','MCP tools','Hosts',['u.show','MCP tools']],['palette.share_session','Share session','Workflows',['u.download','Recipe']]];

test('all old palette sources and every navigation page preserve their actions', async()=>{
  const source=execFileSync('git',['show','60dc0f8e:01.APP/nodelang/studio/app.jsx'],{cwd:root,encoding:'utf8'});
  const start=source.indexOf('      const searchOrder = '),end=source.indexOf('      body = <><input',start);
  const expression='(function(s,u,api,routeNames,query,mode){'+source.slice(start,end)+'return items;})';
  const state={graph:{nodes:[]},catalogue:[{name:'Text'},{name:'Number'}],templates:[{id:'template',title:'Template'}],tasks:[{id:'task',title:'Task'}],
    liveAgents:[{name:'Codex',app:'codex',task:'Review'}],agents:[{name:'Codex',runtime:'codex'},{name:'Claude',runtime:'claude'}],
    graphs:[{id:'graph',name:'Workflow'}],hosts:[{name:'Revit',state:'connected'}],pages:['Account','Appearance']};
  const old=runtime('',state),now=runtime(fs.readFileSync(path.join(studio,'compiled/context-menus.js'),'utf8'),state);
  const prior=vm.runInContext(expression,old.sandbox)(state,old.u,old.api,old.sandbox.window.ArchHubRouteNames,'','All');
  // The two doors that left the Library shelf are new rows; the next test proves them. Every old entry stays as it was.
  const items=now.sandbox.window.UI.paletteCommands(state,now.u,now.api).filter(x=>!LIBRARY_DOORS.some(([id])=>id===x.id));
  assert.deepEqual(plain(items.map(x=>[x.label,x.group])),plain(prior.map(x=>[x.label,x.group])));
  for(let index=0;index<items.length;index++){
    old.calls.length=now.calls.length=0;
    await prior[index].action();await items[index].action();
    // a55d4923: a starter or saved-workflow result opens it in Canvas (openTemplateGraph, then Canvas), not the Skill card.
    const template=state.templates.find(t=>t.title===items[index].label);
    const expected=template?[['api.openTemplateGraph',template.id],['u.go','canvas']]:plain(old.calls);
    assert.deepEqual(plain(now.calls),expected,items[index].label);
  }
  console.log('MAPPED existing palette entries: '+items.length+'; unmapped: 0');
});

test('MCP tools and Share session are command-list doors that run their registered Library actions', async()=>{
  const state={graph:{nodes:[]},catalogue:[],templates:[],tasks:[],graphs:[],hosts:[],pages:[]};
  const rig=runtime('',state),handlers={};
  // The Studio's own action table (ds/index.jsx): ids registered by a screen, run by id.
  rig.sandbox.window.registerActions=(mapping,held)=>{for(const [id,name] of Object.entries(mapping))handlers[id]=held[name];};
  rig.sandbox.window.executeAction=(id,context,event)=>handlers[id](context,event);
  for(const name of ['ds_library.js','context-menus.js'])vm.runInContext(fs.readFileSync(path.join(studio,'compiled',name),'utf8'),rig.sandbox);
  const registry=rig.sandbox.window.ArchHubCommandRegistry,read=options=>rig.sandbox.window.UI.paletteCommands(state,rig.u,rig.api,options);
  for(const [id,label,group,call] of LIBRARY_DOORS){
    const row=registry.commands.find(command=>command.id===id);
    assert.ok(row&&row.contexts.includes('palette'),id+' is a row of the one registry');
    assert.equal(typeof handlers[row.action.client],'function',id+' names a registered action: '+row.action.client);
    const found=read({}).filter(item=>item.id===id);
    assert.deepEqual(plain(found.map(item=>[item.label,item.group])),[[label,group]]);
    rig.calls.length=0;
    await found[0].action();
    assert.deepEqual(plain(rig.calls),[call],label+' runs its action');
    assert.deepEqual(plain(read({query:label.toLowerCase()}).map(item=>item.id)),[id],'typing "'+label+'" finds it');
  }
  // The flow-file picker that the shelf's "Open session" used is gone; no action is left pointing at it.
  assert.equal(Object.keys(handlers).some(id=>id.includes('ImportFlow')),false);
  // A card the catalogue marks not available (coming soon) is not offered as an "Add node" row.
  // Nor is an agent session: it is a conversation record, not a skill.
  const offered=rig.sandbox.window.UI.paletteCommands({...state,templates:[{id:'skill:talk',title:'Talk',kind:'agent-session'},{id:'skill:flow',title:'Flow',kind:'workflow'}],
    catalogue:[{name:'Number'},{name:'Remote tunnel',unavailable:true,soon:true},{id:'skill:talk',name:'Talk'},{id:'skill:flow',name:'Flow'}]},rig.u,rig.api);
  assert.deepEqual(plain(offered.filter(item=>item.id==='palette.add_node').map(item=>item.label)),['Number','Flow']);
});

test('compiled Canvas supplies the real selection and callbacks to both readers', async()=>{
  const {chromium}=require('playwright'),os=require('node:os');
  const cache=process.env.PLAYWRIGHT_BROWSERS_PATH||path.join(os.userInfo().homedir,'AppData/Local/ms-playwright');
  const shell=fs.readdirSync(cache).filter(name=>/^chromium_headless_shell-\d+$/.test(name)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
  const full=fs.readdirSync(cache).filter(name=>/^chromium-\d+$/.test(name)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
  const browser=await chromium.launch({headless:true,executablePath:path.join(cache,shell||full,shell?'chrome-headless-shell-win64/chrome-headless-shell.exe':'chrome-win64/chrome.exe')});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<div id="root"></div>'}));
    await page.goto('http://commandregistry.test');
    await page.addStyleTag({path:path.join(studio,'style.css')});
    await page.addStyleTag({content:'html,body,#root{height:100%;margin:0}'});
    for(const name of ['react.js','react-dom.js'])await page.addScriptTag({path:path.join(studio,'vendor',name)});
    await page.addScriptTag({content:require('./studio_xyflow.cjs').script()});
    await page.addScriptTag({path:path.join(studio,'compiled/react-resizable-panels.js')});
    await page.evaluate(()=>{window.fetch=()=>new Promise(()=>{});});
    for(const name of ['tokens.js','ds-index.js','api.js','icons.js'])await page.addScriptTag({path:path.join(studio,'compiled',name)});
    await page.evaluate(registry=>{
      window.ArchHubCommandRegistry=registry;
      window.ArchHubRouteNames=Object.fromEntries(registry.commands.filter(x=>x.action.route).map(x=>[x.action.route,x.label]));
      const s=window.structuredClone(window.ArchHubAPI.getSnapshot());
      s.graph={...s.graph,id:'fixture',scopeKey:'fixture',canvasLayout:'v48',name:'Registry fixture',nodes:[1,2].map(id=>({id:String(id),title:'Text '+id,type:'data.text',kind:'Text',
        x:id*260,y:100,width:220,height:160,params:{value:'hello'},inputs:[],outputs:[],parameterSchema:[],status:'Idle'}))};
      s.libraryPorts=[];
      window.commandFixture=s;window.commandCalls=[];
      window.ArchHubAPI={...window.ArchHubAPI,getSnapshot:()=>s,subscribe:()=>()=>{},refreshProjects:async()=>s.graph,
        supportsAction:()=>true,setSessionViewport:()=>{},getSessionDocument:()=>null,
        groupNodes:async(ids,frame)=>{window.commandCalls.push(['groupNodes',ids,!!frame]);return {id:'made'};}};
      window.commandApp={selectedNodeId:'1',setSelectedNodeId:()=>{},act:fn=>fn(),libraryOpen:false,route:'canvas',task:'',
        setLibraryOpen:()=>{},setToast:()=>{},show:(kind,data)=>{window.commandMenu={kind,...data};},close:()=>{},
        setTaskFace:()=>{},confirm:(_title,fn)=>fn()};
    },JSON.parse(fs.readFileSync(registryPath,'utf8')));
    for(const name of ['ui.js','answer-widgets.js','ds_library.js','context-menus.js'])await page.addScriptTag({path:path.join(studio,'compiled',name)});
    await page.evaluate(()=>{window.UI.useApp=()=>window.commandApp;});
    await page.addScriptTag({path:path.join(studio,'compiled/ds_screens.js')});
    await page.evaluate(()=>{window.commandRoot=window.ReactDOM.createRoot(document.getElementById('root'));window.commandRoot.render(window.React.createElement(window.UI.Canvas));});
    await page.locator('[data-graph-node="1"]').waitFor();
    assert.equal(await page.evaluate(()=>typeof window.UI.canvasCommandContext),'function');
    const comparison=await page.evaluate(()=>{
      const context=window.UI.canvasCommandContext({clientX:400,clientY:300}),s=window.commandFixture,u=window.commandApp;
      const action={run:fn=>fn()},props={...context,nodeId:context.id,close:u.close};
      const menu=window.UI.contextCommandGroups(props,s,u,action).flat().map(row=>row.command);
      const palette=window.UI.paletteCommands(s,u,window.ArchHubAPI,{context,actionState:action});
      return {kind:context.kind,selection:context.selected,menu:menu.map(x=>x.id),palette:palette.map(x=>x.id)};
    });
    assert.equal(comparison.kind,'Node menu');assert.deepEqual(comparison.selection,['1']);
    assert.deepEqual(comparison.menu,comparison.palette);
    await page.evaluate(async()=>{
      const context=window.UI.canvasCommandContext({clientX:400,clientY:300});
      const items=window.UI.paletteCommands(window.commandFixture,window.commandApp,window.ArchHubAPI,{context,actionState:{run:fn=>fn()}});
      await items.find(x=>x.label==='Group').action();
    });
    assert.deepEqual(await page.evaluate(()=>window.commandCalls),[['groupNodes',['1'],false]]);
    assert.deepEqual(errors,[]);
    await page.evaluate(()=>window.commandRoot.unmount());
    assert.equal(await page.evaluate(()=>typeof window.UI.canvasCommandContext),'undefined');
  }finally{await browser.close();}
});
