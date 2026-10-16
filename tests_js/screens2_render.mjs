// Real production components, fixture stores, intercepted network. Never opens the installed app.
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {chromium} from 'playwright';
import {transformSync} from 'esbuild';
const require=createRequire(import.meta.url);
const {plateFixture}=require('./workshop77_plate_fixture.cjs');
const read=p=>fs.readFileSync(p,'utf8');
const names=[...read('nodelang/studio/studio.html').match(/const names = \[([\s\S]*?)\];/)[1].matchAll(/['"]([^'"]+\.jsx)['"]/g)].map(m=>m[1]).filter(n=>n!=='mount.jsx');
const manifest=process.argv.includes('--compiled')?JSON.parse(read('nodelang/studio/compiled/manifest.json')):null;
if(manifest)for(const name of names){const f=manifest.files.find(f=>f.source===name);if(f?.source_sha256!==createHash('sha256').update(read('nodelang/studio/'+name)).digest('hex'))throw Error('Stale compiled render input: '+name);}
const scripts=names.map(name=>({name,code:(manifest?read('nodelang/studio/compiled/'+manifest.files.find(f=>f.source===name).output):transformSync(read('nodelang/studio/'+name),{loader:'jsx'}).code).replace(/window\.StudioLM\s*=\s*StudioLM;/,'window.SCREENS2={StudioLM,Frame,Home,Workspace,ChatsPanel,SystemSettingsNav,StatusBar,WsHeader,NodeCanvas,NodeRail,loadCatalogue,LM_HOSTS};window.StudioLM=StudioLM;')}));
const themeSeed=Object.fromEntries([...read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1].matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m=>[m[1],m[2]]));
const fixture=plateFixture();
const port=(id,label,t='elements',list=false)=>({id,label,t,list,connected:true,connectable:true});
const node=(id,title,cat,x,y,w,ins=[],outs=[],extra={})=>({id,title,cat,x,y,w,ins,outs,live:true,application:false,params:[],...extra});
const canvasNodes=[
 node('level','Level','read',30,70,170,[],[port('value','value','text')],{subtitle:'Input · text',state:'idle',status:'Level 3'}),
 node('doors','Doors of level','read',230,70,200,[port('level','level','text')],[port('doors','doors','elements',true)],{subtitle:'Host · Revit · read',state:'done',result_summary:'ran · 46 doors · 0.8 s'}),
 node('filter','Untagged only','filter',460,70,190,[port('items','items','elements',true)],[port('kept','kept','elements',true)],{subtitle:'Shape · filter',state:'done',result_summary:'ran · 12 kept'}),
 {...fixture.node,id:'room-a',title:'Workshop',x:40,y:330,w:260,application:false,live:true,subtitle:'group · 3 agents · 1 task',conversation_root:'room-a',has_conversation:true,ins:[port('doors-in','doors','elements',true)],outs:[port('doors-out','doors','elements',true)]},
 node('tag','Tag doors','annotate',340,330,200,[port('doors','doors','elements',true)],[port('tags','tags','elements',true)],{subtitle:'Document · asks first',state:'needs-user',result_summary:'waits for you'}),
 node('watch','Watch','watch',580,330,250,[port('in','in','elements',true)],[],{engine:'watch.preview',subtitle:'Watch · as table',state:'done',result_summary:'12 rows · 3 columns',preview:{kind:'table',state:'ready',value:[{Mark:'D-301',Type:'Single 900',Lvl:'L3'},{Mark:'D-307',Type:'Double 1800',Lvl:'L3'},{Mark:'D-312',Type:'Single 1000',Lvl:'L3'}]}}),
];
const links=[['level','value','doors','level','text'],['doors','doors','filter','items'],['filter','kept','room-a','doors-in'],['room-a','doors-out','tag','doors'],['tag','tags','watch','in']].map((r,i)=>({id:'wire-'+i,from:r.slice(0,2),to:r.slice(2,4),t:r[4]||'elements',list:i>0,label:i?'doors':'level'}));
const param=(k,label,v,type='text')=>({k,label,v,type,editable:true,setting:{kind:'theme',key:k},value_root:'cell-'+k});
const systemNodes=[
 node('ui','UI & Design System','display',30,70,240,[],[port('theme','theme','view')],{application:true,subtitle:'Appearance · group',state:'ready',result_summary:'accent changed · live',params:[{...param('theme','Theme','dark','select'),options:[['dark','Dark'],['light','Light'],['system','System']],default:'dark'},{...param('accent','Accent','#5fb3b3','color'),default:themeSeed.accent},{...param('density','Density','comfortable','select'),options:[['comfortable','Comfortable'],['compact','Compact']],default:'comfortable'},param('font_size','Text size',14,'number'),param('reduce_motion','Reduce motion',false,'boolean')]}),
 node('engine','Canvas & Graph Engine','logic',320,70,240,[port('theme','theme','view')],[port('graphs','graphs','any')],{application:true,subtitle:'System · app part',state:'ready',params:[{k:'zoom',label:'Default zoom',v:'100 %',editable:false},{k:'fit',label:'Fit on open',v:'on',editable:false},{k:'snap',label:'Snap to grid',v:'on',editable:false}],result_summary:'live · same values as Settings'}),
 node('brain','Brain','ai',610,70,210,[port('graphs','graphs','any')],[],{application:true,subtitle:'AI · memory',state:'ready',result_summary:'1,284 facts · syncing'}),
 node('workshop','Workshop','workshop',320,270,240,[port('theme','theme','view')],[port('tasks','tasks','any')],{application:true,subtitle:'System · agents and tasks',state:'ready',result_summary:'3 agents · free models'}),
 node('connections','Connections','host',610,270,210,[port('tasks','tasks','any')],[],{application:true,subtitle:'Hosts · AI accounts · apps',state:'needs-user',result_summary:'Revit 2024 not connected',actions:[{id:'fix',label:'Fix',kind:'open-node',root:'tool_hub'}]}),
];
const systemLinks=[['ui','theme','engine','theme'],['ui','theme','workshop','theme'],['engine','graphs','brain','graphs'],['workshop','tasks','connections','tasks']].map((r,i)=>({id:'system-wire-'+i,from:r.slice(0,2),to:r.slice(2),label:r[1],t:r[1]==='theme'?'view':'any'}));
const templates=[['Submittal turnaround',33,['Markup PDF','Clouds','Titleblock','Print','Package','QC']],['Redline QC sweep',29,['Sheets','Compare','Comments','Proof table']],['Sheets production',26,['Views','Sheets','Titleblock','Print']],['CAD detail into the model',28,['CAD file','Detail','Place','Align','Fix dims']],['Email triage',23,['Inbox','Sort','Draft reply','Your OK']],['Research → Notion',30,['Links','Read','Findings','Notion page']]].map(([title,run_count,steps],i)=>({id:'template-'+i,title,run_count,child_count:steps.length,sub:'last: reviewed run · yesterday',children:steps.map((title,j)=>({id:'step-'+j,title,params:{}}))}));
const browser=await chromium.launch({headless:true});
const results=[];
try{
 for(const mode of ['home','canvas','system']){
  const page=await browser.newPage({viewport:{width:1496,height:959},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><head><meta charset="utf-8"><style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden}*{box-sizing:border-box}button,input,textarea,select{font:inherit}button{cursor:pointer}[hidden]{display:none!important}</style></head><body><div id="root"></div></body></html>'}));
  await page.goto('http://screens2.invalid/');
  await page.evaluate(({mode,fixture,canvasNodes,links,systemNodes,systemLinks,templates,themeSeed})=>{
   const graph={nodes:mode==='system'?systemNodes:canvasNodes,wires:mode==='system'?systemLinks:links};
   const authorization={subject:'owner-a',session:'view-a',system_view:true};
   const canvas={graph_id:'graph-a',application_root:'graph-a',root:'scope-a',revision:4,authorization,scope:{current:'scope-a',label:'Tag doors L3',trail:[{root:'scope-a',label:'Tag doors L3'}]},project_label:'Nile Tower'};
   let state={...fixture.state,canvas,topology:{canvas,graph,selected:null},graph};
   if(mode==='home'){state.nativeWork=null;state.workshop={...state.workshop,messages:[],assignments:[],workflows:[{root:'package',title:'Submittal 07 is ready to issue',state:'review',approval:{current:false},digest:'d'.repeat(64),package:{available:true,destination:'03.PUBLISHED / Submittal 07',sheets:Array.from({length:14},(_,i)=>({id:'sheet-'+i,name:'Sheet '+(i+1),thumbnail_url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='}))}},{root:'qc',title:'Redline QC · Tower B',state:'done',result_summary:'3 rows rejected · proof table ready',approval:{current:true}},{root:'mail',title:'Inbox · 9 project mails sorted',state:'done',result_summary:'2 replies drafted in your format',approval:{current:true}}]};}
   const listeners=new Set();
   window.__fixtureState=state;window.__fixtureMode=mode;window.__fixtureWrites=[];
   const subscribe=fn=>{listeners.add(fn);return()=>listeners.delete(fn);};
   const update=()=>{state={...state,topology:{...state.topology,canvas:{...state.topology.canvas},graph:{...state.topology.graph,nodes:[...state.topology.graph.nodes]}}};window.__fixtureState=state;listeners.forEach(fn=>fn());};
   const owner={getSnapshot:()=>state,subscribe,readHomeTemplates:async()=>({ok:true,templates}),refreshHomeWorkshops:async()=>{},refreshTopologyCanvas:async()=>state.topology,
    watchApplicationUpdate:()=>()=>{},readProviders:async()=>[],refreshWorkshop:async()=>state.workshop,loadTopologyCanvas:async()=>state.topology,
    moveTopologyNodes:async positions=>{window.__fixtureWrites.push({kind:'layout',positions});graph.nodes=graph.nodes.map(n=>positions[n.id]?{...n,...positions[n.id]}:n);state.topology.graph=graph;update();return{ok:true};}};
   window.ARCHHUB_RUN=async()=>{window.__fixtureWrites.push({kind:'run'});return{ok:true};};
   window.ARCHHUB_WORKSHOP_TRANSCRIPT=async(id,scope)=>({ok:true,node:id,conversation_root:graph.nodes.find(n=>n.id===id)?.conversation_root,rows:state.workshop.messages.filter(m=>m.work_root==='work:doors301').map(m=>({id:m.root,who:m.sender_root==='owner-a'?'You':state.workshop.participants.find(p=>p.root===m.sender_root)?.label || 'Unavailable',is_me:m.sender_root==='owner-a',text:m.body,time:new Date(m.created_at*1000).toISOString()}))});
   window.ARCHHUB_EXISTING_WORKSHOP=owner;
   window.ARCHHUB_STUDIO_AUTHORITY={getSnapshot:()=>({...state,...state.topology}),subscribe,load:async()=>canvas,moveMany:owner.moveTopologyNodes,open:async()=>({ok:true}),approveNativeWork:async(root,digest)=>{window.__fixtureWrites.push({kind:'approval',root,digest});return{ok:true,root,input_digest:digest};}};
   window.ARCHHUB_SET_NODE_PROP=async(id,key,value)=>{window.__fixtureWrites.push({kind:'property',id,key,value});const n=graph.nodes.find(n=>n.id===id);n.params=n.params.map(p=>p.k===key?{...p,v:value}:p);update();return{ok:true};};
   window.ARCHHUB_THEME={...themeSeed,...(mode==='system'?{accent:'#5fb3b3',accent_soft:'#183b3b',accent_dim:'#152c2c',accent_hi:'#7fc7c7',accent_press:'#478b8b'}:{})};window.ARCHHUB_TOOL_HUB={tools:[],waiting:[]};
   window.ARCHHUB_LOAD_HOSTS=async()=>({hosts:window.ARCHHUB_LIVE.hosts,connectors:window.ARCHHUB_LIVE.connectors});
   window.AH_LIBRARY=[];window.AH_LIBRARY_LOADED=true;window.AH_LOAD_LIBRARY=async()=>[];
   window.ARCHHUB_LIVE={sessions:[{id:'graph-a',title:'Tag doors L3',state:'idle',host:'Revit',project:'Nile Tower',when:'saved',last:'6 nodes · 5 wires'}],currentGraph:null,graph,hosts:[{id:'r25',name:'Revit 2025',state:'connected',file:'Nile_Tower.rvt'}],connectors:[],memory:[],skills:[]};
   window.fetch=async()=>({ok:true,json:async()=>({ok:true,tools:[],items:[],models:[],templates,settings:{},selected_route:'fixture/claude'})});
  },{mode,fixture,canvasNodes,links,systemNodes,systemLinks,templates,themeSeed});
  for(const file of ['react.js','react-dom.js'])await page.addScriptTag({content:read('nodelang/studio/vendor/'+file)});
  for(const s of scripts)await page.addScriptTag({content:s.code});
  await page.evaluate(()=>{
   const C=window.SCREENS2,el=React.createElement,mode=window.__fixtureMode;
   C.loadCatalogue('ARCHHUB_LOAD_HOSTS',C.LM_HOSTS);
   function Scene(){
    const [focus,setFocus]=React.useState(mode==='system'?'ui':'room-a');
    const [view,setView]=React.useState({mode:mode==='system'?'system':'canvas',conversationRoot:'',target:'',pending:false});
    const state=window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot();
    const session={id:mode==='system'?'system:graph-a':'graph-a',title:'Tag doors L3',project:'Nile Tower',state:'idle'};
    const noop=()=>{};
    const model={name:'Claude Code',vendor:'Anthropic',routed:'fixture/claude',route:'fixture/claude'};
    const left=mode==='home'?null:mode==='system'?el(C.SystemSettingsNav,{selectedId:focus,onSelect:setFocus,onOpen:noop}):el(C.ChatsPanel,{openId:'graph-a',onOpen:noop,onNew:noop,onHome:noop});
    const body=mode==='home'?el(C.Home,{workshopState:state,model,onOpen:noop,setPickerOpen:noop,setLibraryOpen:noop,setPanel:noop,onStarted:noop}):el(C.Workspace,{session,model,openTabs:[session.id],sessionRows:[session],setOpenId:noop,closeTab:noop,setPickerOpen:noop,setLibraryOpen:noop,focusId:focus,setFocusId:setFocus,userNodes:[],addNodeFromLibrary:noop,onHome:noop,onSettings:noop,view,updateView:change=>setView(v=>({...v,...change})),wsSel:{},setWsSel:noop});
    return el(C.Frame,{rail:mode==='home'?'Home':mode==='system'?'Settings':'Chats',left,account:state.account,status:el(C.StatusBar,{session:mode==='home'?null:session,model,setDocsOpen:noop}),onHome:noop,onPanel:noop,onSettings:noop},body);
   }
   window.__root=window.ReactDOM.createRoot(document.getElementById('root'));window.ReactDOM.flushSync(()=>window.__root.render(el(Scene)));
  });
  await page.waitForTimeout(600);
  if(errors.length)throw Error(mode+': '+errors.join('; '));
  const mountWrites=await page.evaluate(()=>window.__fixtureWrites);
  if(mountWrites.length)throw Error(mode+' writes on mount: '+JSON.stringify(mountWrites));
  if(mode==='canvas'){
   const visibility=await page.evaluate(()=>{
    const well=document.querySelector('[data-node-id="watch"] [data-watch-well]'),box=well.getBoundingClientRect();
    return [...well.querySelectorAll('th,[data-watch-actions] button')].map(item=>{const r=item.getBoundingClientRect();return{text:item.textContent,left:r.left,right:r.right,wellLeft:box.left,wellRight:box.right,inside:r.left>=box.left&&r.right<=box.right};});
   });
   if(visibility.some(item=>!item.inside))throw Error('Watch clips supplied data/action: '+JSON.stringify(visibility));
   fs.writeFileSync('evidence/SCREENS2-watch-visibility.json',JSON.stringify(visibility,null,2)+'\n');
  }
  await page.screenshot({path:'evidence/SCREENS2-'+mode+'.png'});
  results.push({mode,errors,mountWrites,hash:createHash('sha256').update(fs.readFileSync('evidence/SCREENS2-'+mode+'.png')).digest('hex'),compiled:!!manifest,manifest_sha256:manifest?createHash('sha256').update(read('nodelang/studio/compiled/manifest.json')).digest('hex'):null,nodes:await page.locator('[data-ds-node]').count(),composers:await page.locator('[data-ds-composer]').count()});
  if(mode==='canvas'){
   const geometry=await page.evaluate(()=>[...document.querySelectorAll('.lm-wires [data-wire-id]')].map(w=>({id:w.dataset.wireId,d:w.getAttribute('d')})));
   results.at(-1).wires=geometry;
  }
  await page.close();
 }
 fs.writeFileSync('evidence/SCREENS2-render.json',JSON.stringify(results,null,2)+'\n');
 console.log('SCREENS2 store-fixture browser renders: 3/3; page errors: 0; mount writes: 0');
}finally{await browser.close();}
